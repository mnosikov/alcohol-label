from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.models import LabelCase
from backend.app.pipeline.types import CaseStatus


def test_label_case_round_trips_application_fields() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        case = LabelCase(
            source="single_upload",
            status=CaseStatus.QUEUED.value,
            application_fields={
                "brand_name": "OLD TOM DISTILLERY",
                "class_type": "Kentucky Straight Bourbon Whiskey",
                "alcohol_content": "45% Alc./Vol. (90 Proof)",
                "net_contents": "750 mL",
            },
            image_sha256="abc123",
            image_path="/data/uploads/ab/abc123.png",
        )
        session.add(case)
        session.commit()

        saved = session.get(LabelCase, case.id)

    assert saved is not None
    assert saved.application_fields["brand_name"] == "OLD TOM DISTILLERY"
    assert saved.status == "queued"
