from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Batch, LabelCase, VerificationJob
from backend.app.pipeline.types import BatchStatus, CaseStatus, JobStatus

TERMINAL_CASE_STATUSES = {
    CaseStatus.NEEDS_REVIEW.value,
    CaseStatus.MACHINE_PASSED.value,
    CaseStatus.MACHINE_FAILED.value,
    CaseStatus.APPROVED.value,
    CaseStatus.REJECTED.value,
    CaseStatus.BETTER_IMAGE_REQUESTED.value,
    CaseStatus.ERROR.value,
}


def sync_batch_progress(session: Session, batch_id: str | None) -> None:
    if batch_id is None:
        return
    batch = session.get(Batch, batch_id)
    if batch is None:
        return
    reconcile_batch_progress(session, batch)


def reconcile_batch_progress(session: Session, batch: Batch) -> None:
    session.flush()
    job_counts = _status_counts(session, VerificationJob.status, VerificationJob.batch_id, batch.id)
    case_counts = _status_counts(session, LabelCase.status, LabelCase.batch_id, batch.id)

    if job_counts:
        completed_count = int(job_counts.get(JobStatus.COMPLETED.value, 0))
        failed_count = int(job_counts.get(JobStatus.FAILED.value, 0))
        processing_count = int(job_counts.get(JobStatus.PROCESSING.value, 0))
        queued_count = int(job_counts.get(JobStatus.QUEUED.value, 0))
        terminal_count = completed_count + failed_count
        record_count = sum(job_counts.values())
        error = f"{failed_count} verification job(s) failed" if failed_count else None
    else:
        failed_count = int(case_counts.get(CaseStatus.ERROR.value, 0))
        processing_count = int(case_counts.get(CaseStatus.PROCESSING.value, 0))
        queued_count = int(case_counts.get(CaseStatus.QUEUED.value, 0))
        terminal_count = sum(
            int(count)
            for status, count in case_counts.items()
            if status in TERMINAL_CASE_STATUSES
        )
        record_count = sum(case_counts.values())
        error = f"{failed_count} verification case(s) errored" if failed_count else None

    batch.processed_count = min(batch.total_count, terminal_count)
    batch.error = error
    if batch.total_count == 0:
        batch.status = BatchStatus.COMPLETED.value
    elif record_count == 0:
        batch.status = BatchStatus.FAILED.value
        batch.error = "Batch has no verification jobs or cases"
    elif terminal_count >= batch.total_count:
        batch.status = (
            BatchStatus.FAILED.value if failed_count else BatchStatus.COMPLETED.value
        )
    elif processing_count > 0 or terminal_count > 0:
        batch.status = BatchStatus.PROCESSING.value
    elif queued_count > 0:
        batch.status = BatchStatus.QUEUED.value
    else:
        batch.status = BatchStatus.FAILED.value
        batch.error = (
            f"Only {record_count} verification record(s) found for "
            f"{batch.total_count} expected item(s)"
        )


def _status_counts(session: Session, status_column, batch_column, batch_id: str) -> dict[str, int]:
    return dict(
        session.execute(
            select(status_column, func.count())
            .where(batch_column == batch_id)
            .group_by(status_column)
        ).all()
    )
