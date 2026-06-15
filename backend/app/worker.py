from pathlib import Path
from time import sleep

from sqlalchemy import select

from backend.app.batch_progress import sync_batch_progress
from backend.app.config import get_settings
from backend.app.db.models import AuditEvent, LabelCase, VerificationJob
from backend.app.db.session import SessionLocal
from backend.app.db.startup import create_schema
from backend.app.pipeline.decision import status_for_machine_decision
from backend.app.pipeline.ocr import NoopOcrProvider, TesseractOcrProvider
from backend.app.pipeline.openai_vision import OpenAIVisionProvider
from backend.app.pipeline.review_sampling import should_sample_auto_pass
from backend.app.pipeline.runner import VerificationPipeline, persist_pipeline_result
from backend.app.pipeline.types import (
    ApplicationFields,
    CaseStatus,
    JobStatus,
    MachineDecision,
)
from backend.app.pipeline.vision import NoopVisionProvider


def build_pipeline() -> VerificationPipeline:
    settings = get_settings()
    ocr = TesseractOcrProvider() if settings.ocr_enabled else NoopOcrProvider()
    vision = (
        OpenAIVisionProvider(settings)
        if settings.vision_provider == "openai" and settings.openai_api_key
        else NoopVisionProvider()
    )
    return VerificationPipeline(ocr=ocr, vision=vision)


def prepare_worker_database() -> None:
    settings = get_settings()
    if settings.run_db_startup:
        create_schema()


def process_one_job() -> bool:
    pipeline = build_pipeline()
    with SessionLocal() as session:
        job = session.scalar(
            select(VerificationJob)
            .where(VerificationJob.status == JobStatus.QUEUED.value)
            .order_by(VerificationJob.created_at)
            .limit(1)
        )
        if job is None:
            return False

        job.status = JobStatus.PROCESSING.value
        job.attempts += 1
        case = session.get(LabelCase, job.case_id)
        if case is None:
            job.status = JobStatus.FAILED.value
            job.error = "Case not found"
            sync_batch_progress(session, job.batch_id)
            session.commit()
            return True

        case.status = CaseStatus.PROCESSING.value
        sync_batch_progress(session, job.batch_id)
        session.commit()

        try:
            application = ApplicationFields(**case.application_fields)
            result = pipeline.verify(Path(_verification_image_path(case)), application)
            persist_pipeline_result(session, case, result)
            case.current_recommendation = result.recommendation.value
            sampled_for_review = (
                result.recommendation == MachineDecision.PASS
                and should_sample_auto_pass(
                    case.id,
                    case.image_sha256,
                    get_settings().sampled_review_rate,
                )
            )
            case.status = (
                CaseStatus.NEEDS_REVIEW.value
                if sampled_for_review
                else status_for_machine_decision(result.recommendation).value
            )
            job.status = JobStatus.COMPLETED.value
            session.add(
                AuditEvent(
                    case_id=case.id,
                    event_type="verification_completed",
                    payload={
                        "recommendation": result.recommendation.value,
                        "sampled_review": {
                            "selected": sampled_for_review,
                            "sample_rate": get_settings().sampled_review_rate,
                        },
                    },
                )
            )
            if sampled_for_review:
                session.add(
                    AuditEvent(
                        case_id=case.id,
                        event_type="sampled_review_selected",
                        payload={
                            "reason": "random_sample_of_auto_passed_case",
                            "sample_rate": get_settings().sampled_review_rate,
                        },
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            case.status = CaseStatus.ERROR.value
            job.status = JobStatus.FAILED.value
            job.error = str(exc)
            session.add(
                AuditEvent(
                    case_id=case.id,
                    event_type="verification_failed",
                    payload={"error": str(exc)},
                )
            )
        sync_batch_progress(session, job.batch_id)
        session.commit()
        return True


def _verification_image_path(case: LabelCase) -> str:
    for asset in case.label_images or []:
        if asset.get("role") == "verification" and asset.get("path"):
            return str(asset["path"])
        if asset.get("key") == "verification" and asset.get("path"):
            return str(asset["path"])
    return case.image_path


def main() -> None:
    prepare_worker_database()
    settings = get_settings()
    while True:
        processed = process_one_job()
        if not processed:
            sleep(settings.worker_idle_sleep_seconds)


if __name__ == "__main__":
    main()
