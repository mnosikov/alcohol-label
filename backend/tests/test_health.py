from fastapi.testclient import TestClient

from backend.app.config import Settings, get_settings
from backend.app.main import app


def test_health_returns_service_status() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "alcohol-label-verifier",
        "status": "ok",
    }


def test_demo_seed_data_is_disabled_by_default() -> None:
    assert Settings().seed_demo_data is False


def test_config_reports_public_review_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        run_db_startup=False,
        seed_demo_data=False,
        review_token="",
    )
    try:
        client = TestClient(app)

        response = client.get("/api/config")

        assert response.status_code == 200
        assert response.json() == {"review_token_required": False}
    finally:
        app.dependency_overrides.clear()


def test_config_reports_protected_review_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        run_db_startup=False,
        seed_demo_data=False,
        review_token="secret",
        public_review_enabled=False,
    )
    try:
        client = TestClient(app)

        response = client.get("/api/config")

        assert response.status_code == 200
        assert response.json() == {"review_token_required": True}
    finally:
        app.dependency_overrides.clear()


def test_config_reports_public_review_mode_when_demo_flag_is_enabled() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        run_db_startup=False,
        seed_demo_data=False,
        review_token="secret",
        public_review_enabled=True,
    )
    try:
        client = TestClient(app)

        response = client.get("/api/config")

        assert response.status_code == 200
        assert response.json() == {"review_token_required": False}
    finally:
        app.dependency_overrides.clear()
