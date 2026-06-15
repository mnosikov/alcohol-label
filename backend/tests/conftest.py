import os
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

os.environ.setdefault("RUN_DB_STARTUP", "false")

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.db.session import get_session
from backend.app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_png_bytes(width: int = 320, height: int = 180, color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    test_settings = Settings(
        database_url="sqlite+pysqlite://",
        upload_dir=tmp_path / "uploads",
        static_dir=tmp_path / "static",
        max_upload_mb=15,
        seed_demo_data=False,
    )

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client_with_case(client: TestClient) -> tuple[TestClient, str]:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "OLD TOM DISTILLERY",
            "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_content": "45% Alc./Vol. (90 Proof)",
            "net_contents": "750 mL",
            "applicant_name_address": "Old Tom Distillery, Louisville, KY",
            "source_of_product": "Domestic",
        },
        files={"image": ("label.png", make_png_bytes(), "image/png")},
    )
    assert response.status_code == 201
    return client, response.json()["id"]
