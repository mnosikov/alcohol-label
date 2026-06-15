from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import worker
from backend.app.config import Settings
from backend.app.db.base import Base
from backend.app.db.models import Batch, LabelCase, VerificationJob
from backend.app.pipeline.runner import PipelineResult
from backend.app.pipeline.types import ApplicationFields, CaseStatus, MachineDecision


class PassingPipeline:
    def verify(self, image_path: Path, application: ApplicationFields) -> PipelineResult:
        return PipelineResult(MachineDecision.PASS, [])


class RecordingPipeline:
    def __init__(self) -> None:
        self.seen_image_path: Path | None = None

    def verify(self, image_path: Path, application: ApplicationFields) -> PipelineResult:
        self.seen_image_path = image_path
        return PipelineResult(MachineDecision.PASS, [])


def test_process_one_job_updates_batch_progress(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'worker.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    image_path = tmp_path / "label.png"
    image_path.write_bytes(b"not-an-image-needed-by-fake-pipeline")

    with session_factory() as session:
        batch = Batch(id="batch-1", filename="labels.zip", status="queued", total_count=2)
        first_case = LabelCase(
            id="case-1",
            batch_id=batch.id,
            source="batch_upload",
            status="queued",
            application_fields={
                "brand_name": "Ironwood Brewing Co.",
                "class_type": "India Pale Ale",
                "alcohol_content": "6.8% Alc./Vol.",
                "net_contents": "12 FL OZ (355 mL)",
            },
            image_sha256="sha-1",
            image_path=str(image_path),
        )
        second_case = LabelCase(
            id="case-2",
            batch_id=batch.id,
            source="batch_upload",
            status="queued",
            application_fields=first_case.application_fields,
            image_sha256="sha-2",
            image_path=str(image_path),
        )
        session.add_all(
            [
                batch,
                first_case,
                second_case,
                VerificationJob(case_id=first_case.id, batch_id=batch.id, status="queued"),
                VerificationJob(case_id=second_case.id, batch_id=batch.id, status="queued"),
            ]
        )
        session.commit()

    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "build_pipeline", lambda: PassingPipeline())
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: Settings(database_url="sqlite+pysqlite://", sampled_review_rate=0.0),
    )

    assert worker.process_one_job() is True
    with session_factory() as session:
        batch = session.get(Batch, "batch-1")
        first_case = session.get(LabelCase, "case-1")
        assert batch is not None
        assert first_case is not None
        assert batch.processed_count == 1
        assert batch.status == "processing"
        assert first_case.status == CaseStatus.MACHINE_PASSED.value
        assert all(event.event_type != "verification_started" for event in first_case.audit_events)

    assert worker.process_one_job() is True
    with session_factory() as session:
        batch = session.get(Batch, "batch-1")
        assert batch is not None
        assert batch.processed_count == 2
        assert batch.status == "completed"


def test_process_one_job_uses_verification_image_asset(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'worker.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    front_path = tmp_path / "front.png"
    verification_path = tmp_path / "front-back-verification.png"
    front_path.write_bytes(b"front")
    verification_path.write_bytes(b"combined")

    with session_factory() as session:
        case = LabelCase(
            id="case-1",
            source="single_upload",
            status="queued",
            application_fields={
                "brand_name": "Ironwood Brewing Co.",
                "class_type": "India Pale Ale",
                "alcohol_content": "6.8% Alc./Vol.",
                "net_contents": "12 FL OZ (355 mL)",
                "fanciful_name": "Trailhead IPA",
            },
            image_sha256="sha-front",
            image_path=str(front_path),
            label_images=[
                {"key": "front", "label": "Front", "path": str(front_path), "sha256": "sha-front"},
                {
                    "key": "verification",
                    "label": "Verification",
                    "path": str(verification_path),
                    "sha256": "sha-combined",
                    "role": "verification",
                },
            ],
        )
        session.add(case)
        session.add(VerificationJob(case_id=case.id, status="queued"))
        session.commit()

    pipeline = RecordingPipeline()
    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "build_pipeline", lambda: pipeline)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: Settings(database_url="sqlite+pysqlite://", sampled_review_rate=0.0),
    )

    assert worker.process_one_job() is True

    assert pipeline.seen_image_path == verification_path
