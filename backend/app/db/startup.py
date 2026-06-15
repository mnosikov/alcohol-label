from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.app.db.base import Base
from backend.app.db.session import engine

SCHEMA_LOCK_ID = 740_516_221


def create_schema(schema_engine: Engine = engine) -> None:
    if schema_engine.dialect.name != "postgresql":
        Base.metadata.create_all(schema_engine)
        with schema_engine.begin() as connection:
            _ensure_case_label_images_column(connection)
        return

    with schema_engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": SCHEMA_LOCK_ID})
        try:
            Base.metadata.create_all(connection)
            _ensure_case_label_images_column(connection)
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": SCHEMA_LOCK_ID},
            )


def _ensure_case_label_images_column(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("cases")}
    if "label_images" in columns:
        return
    if connection.dialect.name == "postgresql":
        connection.execute(text("ALTER TABLE cases ADD COLUMN label_images JSON"))
    else:
        connection.execute(text("ALTER TABLE cases ADD COLUMN label_images JSON"))
