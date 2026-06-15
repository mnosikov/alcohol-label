from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import get_settings
from backend.app.db.models import FieldResultRow, LabelCase, ProviderUsage, TierEvent
from backend.app.db.session import get_session
from backend.app.main import app


def png_bytes(color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (320, 180), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def assert_versioned_image_url(url: str, case_id: str, image_key: str | None = None) -> None:
    parsed = urlparse(url)
    assert parsed.path == f"/api/cases/{case_id}/image"
    query = parse_qs(parsed.query)
    if image_key:
        assert query["image_key"] == [image_key]
    else:
        assert "image_key" not in query
    assert len(query["v"][0]) == 64


def test_create_case_accepts_image_and_application_fields(client: TestClient) -> None:
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
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["application_fields"]["brand_name"] == "OLD TOM DISTILLERY"
    assert payload["image_sha256"]


def test_create_case_normalizes_numeric_alcohol_content(client: TestClient) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "LOWLAND CIDER",
            "class_type": "Hard Cider",
            "alcohol_content": "10",
            "net_contents": "750 mL",
            "applicant_name_address": "Lowland Cider, Burlington, VT",
            "source_of_product": "Domestic",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["application_fields"]["alcohol_content"] == "10%"


def test_create_case_accepts_optional_fields_and_front_back_images(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "OLD TOM DISTILLERY",
            "fanciful_name": "Founder Reserve",
            "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_content": "45% Alc./Vol. (90 Proof)",
            "net_contents": "750 mL",
            "cola_id": "25101001000001",
            "serial_number": "26-104",
            "source_of_product": "Domestic",
            "formula": "TTB Formula ID F-12345",
            "applicant_name_address": "Old Tom Distillery, Louisville, KY",
        },
        files={
            "front_image": ("front.png", png_bytes("white"), "image/png"),
            "back_image": ("back.png", png_bytes("gray"), "image/png"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["application_fields"]["cola_id"] == "25101001000001"
    assert payload["application_fields"]["fanciful_name"] == "Founder Reserve"
    assert payload["application_fields"]["serial_number"] == "26-104"
    assert [image["key"] for image in payload["image_assets"]] == ["front", "back"]

    detail = client.get(f"/api/cases/{payload['id']}").json()
    assert_versioned_image_url(detail["image_url"], payload["id"], image_key="front")
    assert [image["label"] for image in detail["image_assets"]] == ["Front", "Back"]

    back_response = client.get(f"/api/cases/{payload['id']}/image?image_key=back")
    assert back_response.status_code == 200
    assert back_response.content.startswith(b"\x89PNG")


def test_create_case_accepts_dotted_state_abbreviation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "Barenjager",
            "class_type": "Honey Liqueur",
            "alcohol_content": "35%",
            "net_contents": "50 mL",
            "applicant_name_address": "New Rochelle, N.Y.",
            "source_of_product": "Imported",
            "country_of_origin": "Germany",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["application_fields"]["applicant_name_address"] == "New Rochelle, N.Y."


def test_create_case_rejects_imported_product_without_country_of_origin(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "PORTO DA LUA",
            "class_type": "Port",
            "alcohol_content": "19.5% Alc./Vol.",
            "net_contents": "750 mL",
            "applicant_name_address": "Atlas Imports, Providence, RI",
            "source_of_product": "Imported",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Country of origin is required for imported products"


def test_create_case_rejects_responsible_party_without_state(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "LOWLAND CIDER",
            "class_type": "Hard Cider",
            "alcohol_content": "6% Alc./Vol.",
            "net_contents": "750 mL",
            "applicant_name_address": "Lowland Cider",
            "source_of_product": "Domestic",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Responsible party name/address must include at least a U.S. state"
    )


def test_create_case_rejects_non_image_upload(client: TestClient) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "OLD TOM DISTILLERY",
            "class_type": "Bourbon",
            "alcohol_content": "45% Alc./Vol.",
            "net_contents": "750 mL",
            "applicant_name_address": "Old Tom Distillery, Louisville, KY",
            "source_of_product": "Domestic",
        },
        files={"image": ("label.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload must be PNG, JPEG, or WebP"


def test_create_case_rejects_blank_application_fields_before_storing_image(
    client: TestClient,
) -> None:
    settings = app.dependency_overrides[get_settings]()
    upload_dir = Path(settings.upload_dir)

    response = client.post(
        "/api/cases",
        data={
            "brand_name": "   ",
            "class_type": "Vodka",
            "alcohol_content": "40% Alc./Vol.",
            "net_contents": "750 mL",
            "applicant_name_address": "Neutral Spirits, Austin, TX",
            "source_of_product": "Domestic",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Brand is required"
    assert not upload_dir.exists()
    assert client.get("/api/cases").json()["items"] == []


def test_reprocess_endpoint_requires_existing_case(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case

    response = client.post(f"/api/cases/{case_id}/verify")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_reprocess_endpoint_normalizes_stored_numeric_alcohol_content(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.application_fields = {
            **case.application_fields,
            "alcohol_content": "10",
        }
        session.add(case)
        session.commit()
    finally:
        try:
            next(session_iterator)
        except StopIteration:
            pass

    response = client.post(f"/api/cases/{case_id}/verify")

    assert response.status_code == 202
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["application_fields"]["alcohol_content"] == "10%"


def test_reprocess_endpoint_clears_stale_machine_evidence(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "machine_failed"
        case.current_recommendation = "FAIL"
        session.add(
            TierEvent(
                case_id=case_id,
                layer="vision",
                decision="FAIL",
                rationale="Old result",
            )
        )
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="brand_name",
                expected_value="OLD TOM DISTILLERY",
                extracted_value="OTHER",
                verdict="mismatch",
                confidence=0.1,
                rationale="Old mismatch",
                source_layer="vision",
            )
        )
        session.add(
            ProviderUsage(
                case_id=case_id,
                provider="openai",
                model="gpt-5.4-mini",
                latency_ms=100,
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    response = client.post(f"/api/cases/{case_id}/verify")

    assert response.status_code == 202

    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["status"] == "queued"
    assert detail["current_recommendation"] is None
    assert detail["tier_events"] == []
    assert detail["field_results"] == []
    assert detail["provider_usage"] == []


def test_case_list_includes_status_counts(client_with_case: tuple[TestClient, str]) -> None:
    client, case_id = client_with_case

    response = client.get("/api/cases")

    assert response.status_code == 200
    assert response.json()["counts"]["queued"] >= 1
    assert any(item["id"] == case_id for item in response.json()["items"])


def test_case_detail_includes_tier_and_field_arrays(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case

    response = client.get(f"/api/cases/{case_id}")

    assert response.status_code == 200
    payload = response.json()
    assert_versioned_image_url(payload["image_url"], case_id)
    assert payload["image_assets"][0]["key"] == "front"
    assert payload["tier_events"] == []
    assert payload["field_results"] == []


def test_case_detail_returns_verifier_responsible_party_field_evidence(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/cases",
        data={
            "brand_name": "PORTO DA LUA",
            "class_type": "Port",
            "alcohol_content": "19.5% Alc./Vol.",
            "net_contents": "750 mL",
            "applicant_name_address": "Atlas Imports, Providence, RI",
            "source_of_product": "Imported",
            "country_of_origin": "Portugal",
        },
        files={"image": ("label.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 201

    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case_id = response.json()["id"]
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="applicant_name_address",
                expected_value="Atlas Imports, Providence, RI",
                extracted_value="Atlas Imports, Providence, RI",
                verdict="match",
                confidence=0.9,
                rationale="Responsible party components found in whole-label text",
                source_layer="vision",
            )
        )
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="source_of_product",
                expected_value="Imported",
                extracted_value="Imported",
                verdict="match",
                confidence=0.9,
                rationale="Imported origin supported by country-of-origin label text",
                source_layer="vision",
            )
        )
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="country_of_origin",
                expected_value="Portugal",
                extracted_value="Portugal",
                verdict="match",
                confidence=0.95,
                rationale="Country of origin present in whole-label text",
                source_layer="vision",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{response.json()['id']}").json()
    metadata_rows = {
        row["field_name"]: row
        for row in detail["field_results"]
        if row["field_name"] in {"applicant_name_address", "source_of_product", "country_of_origin"}
    }

    assert metadata_rows["applicant_name_address"] == {
        "id": metadata_rows["applicant_name_address"]["id"],
        "field_name": "applicant_name_address",
        "expected_value": "Atlas Imports, Providence, RI",
        "extracted_value": "Atlas Imports, Providence, RI",
        "verdict": "match",
        "confidence": 0.9,
        "rationale": "Responsible party components found in whole-label text",
        "source_layer": "vision",
        "created_at": metadata_rows["applicant_name_address"]["created_at"],
    }
    assert metadata_rows["source_of_product"]["expected_value"] == "Imported"
    assert metadata_rows["country_of_origin"]["expected_value"] == "Portugal"


def test_machine_pass_summary_ignores_non_terminal_ocr_mismatch(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "machine_passed"
        case.current_recommendation = "PASS"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="brand_name",
                expected_value="OLD TOM DISTILLERY",
                extracted_value="SMALL BATCH",
                verdict="mismatch",
                confidence=0.0,
                rationale="OCR textual mismatch",
                source_layer="ocr",
            )
        )
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="brand_name",
                expected_value="OLD TOM DISTILLERY",
                extracted_value="OLD TOM DISTILLERY",
                verdict="match",
                confidence=1.0,
                rationale="Vision match",
                source_layer="vision",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["issue_summary"] == "All checked fields matched the application"


def test_case_issue_summary_prefers_later_vision_evidence_over_ocr_miss(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "machine_failed"
        case.current_recommendation = "FAIL"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value=None,
                verdict="missing",
                confidence=0.0,
                rationale="No extracted government warning",
                source_layer="ocr",
            )
        )
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value="Government Warning: required warning",
                verdict="mismatch",
                confidence=0.0,
                rationale="Warning prefix casing does not match statutory text",
                source_layer="vision",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["issue_summary"] == (
        "Government Warning mismatch: expected GOVERNMENT WARNING: required warning; "
        "found Government Warning: required warning"
    )


def test_needs_review_summary_prefers_human_review_reason_over_intermediate_ocr_mismatch(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "needs_review"
        case.current_recommendation = "NEEDS_REVIEW"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="class_type",
                expected_value="Bourbon",
                extracted_value="cold",
                verdict="mismatch",
                confidence=0.18,
                rationale="OCR textual mismatch",
                source_layer="ocr",
            )
        )
        session.add(
            TierEvent(
                case_id=case_id,
                layer="human_review",
                decision="NEEDS_REVIEW",
                confidence=None,
                rationale="Human review required after provider failure",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["issue_summary"] == "Human review required after provider failure"


def test_needs_review_summary_uses_event_id_to_break_provider_failure_ties(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    same_timestamp = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "needs_review"
        case.current_recommendation = "NEEDS_REVIEW"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value="full noisy OCR transcript",
                verdict="mismatch",
                confidence=0.0,
                rationale="OCR textual mismatch",
                source_layer="ocr",
            )
        )
        session.add_all(
            [
                TierEvent(
                    case_id=case_id,
                    layer="vision",
                    decision="NEEDS_REVIEW",
                    confidence=0.0,
                    rationale="Vision provider unavailable",
                    evidence={"reason": "provider_unavailable"},
                    error="APITimeoutError: Request timed out.",
                    created_at=same_timestamp,
                ),
                TierEvent(
                    case_id=case_id,
                    layer="human_review",
                    decision="NEEDS_REVIEW",
                    confidence=None,
                    rationale="Human review required after provider failure",
                    evidence={"reason": "provider_failure"},
                    created_at=same_timestamp,
                ),
            ]
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["issue_summary"] == "Human review required after provider failure"


def test_needs_review_summary_names_uncertain_field_before_generic_review_reason(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "needs_review"
        case.current_recommendation = "NEEDS_REVIEW"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value="GOVERNMENT WARNING: uncertain warning",
                verdict="uncertain",
                confidence=0.55,
                rationale=(
                    "Warning text is canonical except required clause-marker "
                    "punctuation is uncertain"
                ),
                source_layer="vision",
            )
        )
        session.add(
            TierEvent(
                case_id=case_id,
                layer="human_review",
                decision="NEEDS_REVIEW",
                confidence=None,
                rationale="Human review required after uncertainty",
                evidence={"reason": "uncertain_or_incomplete_evidence"},
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["issue_summary"] == "Government Warning needs review"


def test_case_detail_returns_latest_field_evidence_per_field(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value=None,
                verdict="missing",
                confidence=0.0,
                rationale="OCR missed the warning",
                source_layer="ocr",
            )
        )
        session.flush()
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="government_warning",
                expected_value="GOVERNMENT WARNING: required warning",
                extracted_value="GOVERNMENT WARNING: required warning",
                verdict="match",
                confidence=1.0,
                rationale="Vision found the warning",
                source_layer="vision",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    detail = client.get(f"/api/cases/{case_id}").json()

    assert detail["field_results"][0] == {
        "id": detail["field_results"][0]["id"],
        "field_name": "government_warning",
        "expected_value": "GOVERNMENT WARNING: required warning",
        "extracted_value": "GOVERNMENT WARNING: required warning",
        "verdict": "match",
        "confidence": 1.0,
        "rationale": "Vision found the warning",
        "source_layer": "vision",
        "created_at": detail["field_results"][0]["created_at"],
    }
    assert detail["field_results"][1:] == []


def test_replace_case_image_queues_verification_and_records_activity(
    client_with_case: tuple[TestClient, str],
) -> None:
    client, case_id = client_with_case
    original_detail = client.get(f"/api/cases/{case_id}").json()
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        case = session.get(LabelCase, case_id)
        assert case is not None
        case.status = "machine_failed"
        case.current_recommendation = "FAIL"
        session.add(
            FieldResultRow(
                case_id=case_id,
                field_name="brand_name",
                expected_value="OLD TOM DISTILLERY",
                extracted_value="OTHER BRAND",
                verdict="mismatch",
                confidence=0.0,
                rationale="Brand mismatch",
                source_layer="vision",
            )
        )
        session.commit()
    finally:
        session_iterator.close()

    response = client.post(
        f"/api/cases/{case_id}/image",
        data={"image_key": "front"},
        files={"image": ("replacement.png", png_bytes("gray"), "image/png")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["image_sha256"] != original_detail["image_sha256"]
    assert payload["current_recommendation"] is None
    assert payload["field_results"] == []
    assert any(event["event_type"] == "label_image_replaced" for event in payload["audit_events"])


def test_replace_back_image_preserves_front_back_assets(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/cases",
        data={
            "brand_name": "OLD TOM DISTILLERY",
            "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_content": "45% Alc./Vol. (90 Proof)",
            "net_contents": "750 mL",
            "applicant_name_address": "Old Tom Distillery, Louisville, KY",
            "source_of_product": "Domestic",
        },
        files={
            "front_image": ("front.png", png_bytes("white"), "image/png"),
            "back_image": ("back.png", png_bytes("gray"), "image/png"),
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    response = client.post(
        f"/api/cases/{case_id}/image",
        data={"image_key": "back"},
        files={"image": ("new-back.png", png_bytes("blue"), "image/png")},
    )

    assert response.status_code == 202
    detail = response.json()
    assert [image["key"] for image in detail["image_assets"]] == ["front", "back"]
    back_response = client.get(f"/api/cases/{case_id}/image?image_key=back")
    assert back_response.status_code == 200
    assert back_response.content.startswith(b"\x89PNG")
