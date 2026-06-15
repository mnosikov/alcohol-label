from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import get_settings
from backend.app.db.models import Batch, LabelCase, VerificationJob
from backend.app.db.session import get_session
from backend.app.main import app


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (300, 180), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def batch_zip_bytes() -> bytes:
    buffer = BytesIO()
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "label1.png,OLD TOM DISTILLERY,Bourbon,45% Alc./Vol.,750 mL,"
        "Old Tom Distillery Louisville KY,Domestic\n"
    )
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest.getvalue())
        archive.writestr("label1.png", png_bytes())
    return buffer.getvalue()


def batch_zip_with_optional_fields_and_back_image() -> bytes:
    buffer = BytesIO()
    manifest = StringIO()
    manifest.write(
        "filename,back_filename,brand_name,fanciful_name,class_type,"
        "alcohol_content,net_contents,applicant_name_address,source_of_product,"
        "formula,grape_varietals,wine_appellation\n"
    )
    manifest.write(
        "front.png,back.png,Hollow Creek Vineyards,Reserve Label,"
        "Cabernet Sauvignon,13.5% Alc./Vol.,750 mL,Hollow Creek Vineyards Napa CA,"
        "Domestic,F-999,Cabernet Sauvignon,Napa Valley\n"
    )
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest.getvalue())
        archive.writestr("front.png", png_bytes())
        archive.writestr("back.png", png_bytes())
    return buffer.getvalue()


def manifest_csv_bytes(*, include_back: bool = False) -> bytes:
    manifest = StringIO()
    if include_back:
        manifest.write(
            "filename,back_filename,brand_name,fanciful_name,class_type,"
            "alcohol_content,net_contents,applicant_name_address,source_of_product,"
            "formula,grape_varietals,wine_appellation\n"
        )
        manifest.write(
            "front.png,back.png,Hollow Creek Vineyards,Reserve Label,"
            "Cabernet Sauvignon,13.5% Alc./Vol.,750 mL,Hollow Creek Vineyards Napa CA,"
            "Domestic,F-999,Cabernet Sauvignon,Napa Valley\n"
        )
    else:
        manifest.write(
            "filename,brand_name,class_type,alcohol_content,net_contents,"
            "applicant_name_address,source_of_product\n"
        )
        manifest.write(
            "label1.png,OLD TOM DISTILLERY,Bourbon,45% Alc./Vol.,750 mL,"
            "Old Tom Distillery Louisville KY,Domestic\n"
        )
    return manifest.getvalue().encode("utf-8")


def application_fields() -> dict[str, str]:
    return {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Bourbon",
        "alcohol_content": "45% Alc./Vol.",
        "net_contents": "750 mL",
        "applicant_name_address": "Old Tom Distillery Louisville KY",
        "source_of_product": "Domestic",
    }


def add_directly_to_test_database(*rows: object) -> None:
    override_session = app.dependency_overrides[get_session]
    session_iterator = override_session()
    session = next(session_iterator)
    try:
        session.add_all(rows)
        session.commit()
    finally:
        try:
            next(session_iterator)
        except StopIteration:
            pass


def test_batch_upload_creates_batch_and_case(client: TestClient) -> None:
    response = client.post(
        "/api/batches",
        files={"archive": ("labels.zip", batch_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["total_count"] == 1


def test_batch_upload_accepts_manifest_csv_and_multiple_image_files(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest_csv_bytes(include_back=True), "text/csv")),
            ("images", ("front.png", png_bytes(), "image/png")),
            ("images", ("back.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["status"] == "queued"
    assert payload["total_count"] == 1
    batch_id = payload["id"]

    list_response = client.get("/api/cases")
    case = next(item for item in list_response.json()["items"] if item["batch_id"] == batch_id)
    detail = client.get(f"/api/cases/{case['id']}").json()

    assert detail["application_fields"]["fanciful_name"] == "Reserve Label"
    assert [image["key"] for image in detail["image_assets"]] == ["front", "back"]


def test_batch_upload_ignores_unreferenced_extra_images_and_reports_them(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest_csv_bytes(), "text/csv")),
            ("images", ("label1.png", png_bytes(), "image/png")),
            ("images", ("accidental-extra.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["selected_image_count"] == 2
    assert payload["import_summary"]["accepted_image_count"] == 1
    assert payload["import_summary"]["ignored_images"] == ["accidental-extra.png"]

    list_response = client.get("/api/cases")
    cases = [item for item in list_response.json()["items"] if item["batch_id"] == payload["id"]]
    assert len(cases) == 1


def test_batch_upload_accepts_valid_rows_and_reports_rejected_sample_row(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,back_filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "front-label.jpg,back-label.jpg,Example Brand,Beer,5% Alc./Vol.,12 fl oz,"
        "Example Brewing Denver CO,Domestic\n"
    )
    manifest.write(
        "label1.png,,OLD TOM DISTILLERY,Bourbon,45% Alc./Vol.,750 mL,"
        "Old Tom Distillery Louisville KY,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("label1.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["rejected_rows"] == [
        {
            "row_number": 1,
            "filename": "front-label.jpg",
            "reason": "Manifest image not found in selected files: front-label.jpg",
        }
    ]

    list_response = client.get("/api/cases")
    cases = [item for item in list_response.json()["items"] if item["batch_id"] == payload["id"]]
    assert len(cases) == 1
    assert cases[0]["application_fields"]["brand_name"] == "OLD TOM DISTILLERY"


def test_batch_upload_rejects_sample_row_and_accepts_complete_extended_row(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,back_filename,brand_name,fanciful_name,class_type,"
        "alcohol_content,net_contents,applicant_name_address,source_of_product,"
        "cola_id,producer,country_of_origin\n"
    )
    manifest.write(
        "front-label.jpg,back-label.jpg,Example Brand,Optional name,"
        "Beer,5% Alc./Vol.,12 fl oz,,,\n"
    )
    manifest.write(
        "brandy_blurry_incorrect_warning_incomplete.jpg,,Beauclair,,VSOP Brandy,"
        "40% Alc./Vol. (80 Proof),700 mL,Beauclair Imports Boston MA,Domestic,,,\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            (
                "images",
                (
                    "brandy_blurry_incorrect_warning_incomplete.jpg",
                    png_bytes(),
                    "image/jpeg",
                ),
            ),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["rejected_rows"] == [
        {
            "row_number": 1,
            "filename": "front-label.jpg",
            "reason": "Manifest image not found in selected files: front-label.jpg",
        }
    ]

    list_response = client.get("/api/cases")
    case = next(item for item in list_response.json()["items"] if item["batch_id"] == payload["id"])
    assert case["application_fields"]["brand_name"] == "Beauclair"
    assert case["application_fields"]["class_type"] == "VSOP Brandy"
    assert case["application_fields"]["alcohol_content"] == "40% Alc./Vol. (80 Proof)"
    assert case["application_fields"]["net_contents"] == "700 mL"


def test_batch_upload_skips_row_with_blank_required_field_and_accepts_valid_rows(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "blank.png,   ,Bourbon,45% Alc./Vol.,750 mL,"
        "Blank Distillery Lexington KY,Domestic\n"
    )
    manifest.write(
        "label1.png,OLD TOM DISTILLERY,Bourbon,45% Alc./Vol.,750 mL,"
        "Old Tom Distillery Louisville KY,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("blank.png", png_bytes(), "image/png")),
            ("images", ("label1.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["rejected_rows"] == [
        {
            "row_number": 1,
            "filename": "blank.png",
            "reason": "Manifest row 1 brand_name is required",
        }
    ]


def test_batch_upload_skips_imported_row_without_country_and_accepts_domestic_row(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product,country_of_origin\n"
    )
    manifest.write(
        "imported.png,PORTO DA LUA,Port,19.5% Alc./Vol.,750 mL,"
        "Atlas Imports Providence RI,Imported,\n"
    )
    manifest.write(
        "domestic.png,OLD TOM DISTILLERY,Bourbon,45% Alc./Vol.,750 mL,"
        "Old Tom Distillery Louisville KY,Domestic,\n"
    )

    response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("imported.png", png_bytes(), "image/png")),
            ("images", ("domestic.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["rejected_rows"] == [
        {
            "row_number": 1,
            "filename": "imported.png",
            "reason": "Manifest row 1 country_of_origin is required for imported products",
        }
    ]

    list_response = client.get("/api/cases")
    cases = [item for item in list_response.json()["items"] if item["batch_id"] == payload["id"]]
    assert len(cases) == 1
    assert cases[0]["application_fields"]["brand_name"] == "OLD TOM DISTILLERY"


def test_batch_upload_rejects_responsible_party_without_state(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "label1.png,LOWLAND CIDER,Hard Cider,6% Alc./Vol.,750 mL,"
        "Lowland Cider,Domestic\n"
    )

    response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("label1.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "No valid manifest rows were accepted",
        "rejected_rows": [
            {
                "row_number": 1,
                "filename": "label1.png",
                "reason": (
                    "Manifest row 1 applicant_name_address must include at least a U.S. state"
                ),
            }
        ],
    }


def test_batch_upload_infers_unreferenced_back_image_by_filename(client: TestClient) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "sample-front.png,Hollow Creek Vineyards,Wine,13.5% Alc./Vol.,750 mL,"
        "Hollow Creek Vineyards Napa CA,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("sample-front.png", png_bytes(), "image/png")),
            ("images", ("sample-rear.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["total_count"] == 1
    assert payload["import_summary"]["inferred_back_images"] == [
        {"filename": "sample-front.png", "back_filename": "sample-rear.png"}
    ]
    assert payload["import_summary"]["ignored_images"] == []

    list_response = client.get("/api/cases")
    case = next(item for item in list_response.json()["items"] if item["batch_id"] == payload["id"])
    detail = client.get(f"/api/cases/{case['id']}").json()
    assert [image["key"] for image in detail["image_assets"]] == ["front", "back"]


def test_batch_upload_infers_numbered_rear_image_pair_by_filename(client: TestClient) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "pinnacle-ridge-01.png,Pinnacle Ridge,Wine,13% Alc./Vol.,700 mL,"
        "Pinnacle Ridge Winery Salem OR,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("pinnacle-ridge-01.png", png_bytes(), "image/png")),
            ("images", ("pinnacle-ridge-02.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["import_summary"]["inferred_back_images"] == [
        {"filename": "pinnacle-ridge-01.png", "back_filename": "pinnacle-ridge-02.png"}
    ]
    assert payload["import_summary"]["ignored_images"] == []

    list_response = client.get("/api/cases")
    case = next(item for item in list_response.json()["items"] if item["batch_id"] == payload["id"])
    detail = client.get(f"/api/cases/{case['id']}").json()
    assert [image["key"] for image in detail["image_assets"]] == ["front", "back"]


def test_batch_upload_does_not_infer_ambiguous_numbered_rear_image_pair(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "pinnacle-ridge-01.png,Pinnacle Ridge,Wine,13% Alc./Vol.,700 mL,"
        "Pinnacle Ridge Winery Salem OR,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("pinnacle-ridge-01.png", png_bytes(), "image/png")),
            ("images", ("pinnacle-ridge-02.png", png_bytes(), "image/png")),
            ("images", ("pinnacle-ridge-002.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["import_summary"]["inferred_back_images"] == []
    assert payload["import_summary"]["ignored_images"] == [
        "pinnacle-ridge-02.png",
        "pinnacle-ridge-002.png",
    ]


def test_batch_upload_accepts_quoted_front_back_in_filename_cell(client: TestClient) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        '"front.png, back.png",Hollow Creek Vineyards,Wine,13.5% Alc./Vol.,750 mL,'
        "Hollow Creek Vineyards Napa CA,Domestic\n"
    )

    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("front.png", png_bytes(), "image/png")),
            ("images", ("back.png", png_bytes(), "image/png")),
        ],
    )

    assert create_response.status_code == 201
    assert create_response.json()["import_summary"]["inferred_back_images"] == [
        {"filename": "front.png", "back_filename": "back.png"}
    ]


def test_batch_upload_rejects_comma_shifted_front_back_rows(client: TestClient) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "front.png,back.png,Hollow Creek Vineyards,Wine,13.5% Alc./Vol.,750 mL,"
        "Hollow Creek Vineyards Napa CA,Domestic\n"
    )

    response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("front.png", png_bytes(), "image/png")),
            ("images", ("back.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "No valid manifest rows were accepted",
        "rejected_rows": [
            {
                "row_number": 1,
                "filename": "front.png",
                "reason": (
                    "Manifest row 1 has extra comma-separated values. Use a back_filename "
                    "column for back labels instead of adding another filename to the row."
                ),
            }
        ],
    }


def test_batch_upload_rejects_comma_shifted_back_filename_absorbed_by_optional_columns(
    client: TestClient,
) -> None:
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product,fanciful_name\n"
    )
    manifest.write(
        "front.png,back.png,Hollow Creek Vineyards,Wine,13.5% Alc./Vol.,750 mL,"
        "Hollow Creek Vineyards Napa CA,Domestic\n"
    )

    response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest.getvalue().encode("utf-8"), "text/csv")),
            ("images", ("front.png", png_bytes(), "image/png")),
            ("images", ("back.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "No valid manifest rows were accepted",
        "rejected_rows": [
            {
                "row_number": 1,
                "filename": "front.png",
                "reason": (
                    "Manifest row 1 appears to put a back label filename in the brand_name "
                    "column. Use a back_filename column for back labels."
                ),
            }
        ],
    }


def test_batch_upload_manifest_csv_requires_referenced_image_file(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest_csv_bytes(), "text/csv")),
            ("images", ("other.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "No valid manifest rows were accepted",
        "rejected_rows": [
            {
                "row_number": 1,
                "filename": "label1.png",
                "reason": "Manifest image not found in selected files: label1.png",
            }
        ],
    }


def test_batch_upload_accepts_optional_fields_and_back_image(client: TestClient) -> None:
    create_response = client.post(
        "/api/batches",
        files={
            "archive": (
                "labels.zip",
                batch_zip_with_optional_fields_and_back_image(),
                "application/zip",
            )
        },
    )

    assert create_response.status_code == 201
    batch_id = create_response.json()["id"]

    list_response = client.get("/api/cases")
    case = next(item for item in list_response.json()["items"] if item["batch_id"] == batch_id)
    detail = client.get(f"/api/cases/{case['id']}").json()

    assert detail["application_fields"]["fanciful_name"] == "Reserve Label"
    assert detail["application_fields"]["formula"] == "F-999"
    assert detail["application_fields"]["wine_appellation"] == "Napa Valley"
    assert [image["key"] for image in detail["image_assets"]] == ["front", "back"]


def test_batch_upload_requires_manifest(client: TestClient) -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("label1.png", png_bytes())

    response = client.post(
        "/api/batches",
        files={"archive": ("labels.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Batch ZIP must include manifest.csv"


def test_batch_upload_rejects_blank_required_manifest_field_before_storing_image(
    client: TestClient,
) -> None:
    settings = app.dependency_overrides[get_settings]()
    upload_dir = Path(settings.upload_dir)
    buffer = BytesIO()
    manifest = StringIO()
    manifest.write(
        "filename,brand_name,class_type,alcohol_content,net_contents,"
        "applicant_name_address,source_of_product\n"
    )
    manifest.write(
        "label1.png,   ,Bourbon,45% Alc./Vol.,750 mL,"
        "Old Tom Distillery Louisville KY,Domestic\n"
    )
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest.getvalue())
        archive.writestr("label1.png", png_bytes())

    response = client.post(
        "/api/batches",
        files={"archive": ("labels.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "No valid manifest rows were accepted",
        "rejected_rows": [
            {
                "row_number": 1,
                "filename": "label1.png",
                "reason": "Manifest row 1 brand_name is required",
            }
        ],
    }
    assert not upload_dir.exists()
    assert client.get("/api/cases").json()["items"] == []


def test_batch_list_includes_uploaded_batch(client: TestClient) -> None:
    create_response = client.post(
        "/api/batches",
        files=[
            ("manifest", ("manifest.csv", manifest_csv_bytes(), "text/csv")),
            ("images", ("label1.png", png_bytes(), "image/png")),
            ("images", ("accidental-extra.png", png_bytes(), "image/png")),
        ],
    )
    assert create_response.status_code == 201
    batch_id = create_response.json()["id"]

    response = client.get("/api/batches")

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == batch_id)
    assert item["import_summary"] == {
        "selected_image_count": 2,
        "accepted_image_count": 1,
        "ignored_images": ["accidental-extra.png"],
        "inferred_back_images": [],
        "rejected_rows": [],
    }


def test_batch_list_reconciles_stale_completed_batch(client: TestClient) -> None:
    batch_id = "stale-batch"
    batch = Batch(
        id=batch_id,
        filename="labels.zip",
        status="queued",
        total_count=2,
        processed_count=0,
    )
    add_directly_to_test_database(
        batch,
        LabelCase(
            id="case-pass",
            batch_id=batch.id,
            source="batch_upload",
            status="machine_passed",
            application_fields=application_fields(),
            image_sha256="sha-pass",
            image_path="/tmp/pass.png",
        ),
        LabelCase(
            id="case-fail",
            batch_id=batch.id,
            source="batch_upload",
            status="machine_failed",
            application_fields=application_fields(),
            image_sha256="sha-fail",
            image_path="/tmp/fail.png",
        ),
        VerificationJob(case_id="case-pass", batch_id=batch.id, status="completed"),
        VerificationJob(case_id="case-fail", batch_id=batch.id, status="completed"),
    )

    response = client.get("/api/batches")

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == batch_id)
    assert item["status"] == "completed"
    assert item["processed_count"] == 2
    assert item["error"] is None


def test_batch_list_marks_orphaned_batch_failed(client: TestClient) -> None:
    batch_id = "orphaned-batch"
    batch = Batch(
        id=batch_id,
        filename="labels.zip",
        status="queued",
        total_count=50,
        processed_count=0,
    )
    add_directly_to_test_database(batch)

    response = client.get("/api/batches")

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == batch_id)
    assert item["status"] == "failed"
    assert item["processed_count"] == 0
    assert item["error"] == "Batch has no verification jobs or cases"
