from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api.deps import require_review_token
from backend.app.config import Settings
from backend.app.db.models import AuditEvent, ProviderUsage
from backend.app.db.session import get_session
from backend.app.main import app


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (320, 180), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_review_token_dependency_requires_matching_token() -> None:
    with pytest.raises(HTTPException):
        require_review_token(
            Settings(review_token="secret", public_review_enabled=False),
            x_review_token=None,
        )


def test_review_token_dependency_allows_public_review_flag() -> None:
    require_review_token(
        Settings(review_token="secret", public_review_enabled=True),
        x_review_token=None,
    )


def test_human_decision_records_final_decision(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case

    response = client.post(
        f"/api/cases/{case_id}/human-decision",
        json={
            "decision": "approved",
            "note": "Reviewed label and evidence",
            "reviewer_label": "demo-agent",
        },
    )

    assert response.status_code == 200
    assert response.json()["final_decision"] == "approved"


def test_human_decision_rejects_unknown_value(client_with_case: tuple[TestClient, str]) -> None:
    client, case_id = client_with_case

    response = client.post(
        f"/api/cases/{case_id}/human-decision",
        json={
            "decision": "maybe",
            "note": "Not a supported action",
            "reviewer_label": "demo-agent",
        },
    )

    assert response.status_code == 400


def test_audit_history_lists_case_creation(client_with_case: tuple[TestClient, str]) -> None:
    client, case_id = client_with_case

    response = client.get("/api/audit-events")

    assert response.status_code == 200
    assert any(event["case_id"] == case_id for event in response.json()["items"])


def test_audit_history_supports_limit_offset_and_total(client: TestClient) -> None:
    for index in range(3):
        response = client.post(
            "/api/cases",
            data={
                "brand_name": f"TEST BRAND {index}",
                "class_type": "Wine",
                "alcohol_content": "12%",
                "net_contents": "750 mL",
                "applicant_name_address": f"Test Winery {index}, Salem, OR",
                "source_of_product": "Domestic",
            },
            files={"image": ("label.png", png_bytes(), "image/png")},
        )
        assert response.status_code == 201

    response = client.get("/api/audit-events?limit=2&offset=1")

    payload = response.json()
    assert response.status_code == 200
    assert payload["total_count"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert len(payload["items"]) == 2


def test_audit_history_includes_model_processing_time_only(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    session_iterator = app.dependency_overrides[get_session]()
    session = next(session_iterator)
    try:
        session.add(
            ProviderUsage(
                case_id=case_id,
                provider="openai",
                model="gpt-test",
                latency_ms=2400,
            )
        )
        session.add(
            AuditEvent(
                case_id=case_id,
                event_type="verification_completed",
                payload={"recommendation": "pass"},
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    response = client.get("/api/audit-events?limit=10")

    assert response.status_code == 200
    completed_event = next(
        event
        for event in response.json()["items"]
        if event["event_type"] == "verification_completed"
    )
    assert completed_event["case"]["provider_latency_ms"] == 2400
    assert "processing_time_ms" not in completed_event["case"]
    assert "queue_time_ms" not in completed_event["case"]
    assert "case_processing_time_ms" not in completed_event["case"]
