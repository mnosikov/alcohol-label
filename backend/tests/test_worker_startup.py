from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.startup import create_schema


def test_create_schema_creates_verification_jobs_table() -> None:
    test_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    create_schema(test_engine)

    assert "verification_jobs" in inspect(test_engine).get_table_names()
    Base.metadata.drop_all(test_engine)
