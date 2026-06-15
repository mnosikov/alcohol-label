import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.api.deps import require_review_token
from backend.app.application_metadata import (
    COUNTRY_OF_ORIGIN_FIELD,
    PRODUCT_ORIGIN_FIELD,
    RESPONSIBLE_PARTY_FIELD,
    ApplicationMetadataError,
    normalize_and_validate_responsible_party_metadata,
)
from backend.app.batch_progress import reconcile_batch_progress
from backend.app.config import Settings, get_settings
from backend.app.db.models import (
    AuditEvent,
    Batch,
    FieldResultRow,
    HumanDecision,
    LabelCase,
    ProviderUsage,
    TierEvent,
    VerificationJob,
)
from backend.app.db.session import get_session
from backend.app.storage import (
    BatchManifestParseResult,
    parse_manifest_files,
    parse_manifest_zip,
    save_batch_image,
    save_combined_label_image,
    save_upload,
)

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ReviewTokenDep = Annotated[None, Depends(require_review_token)]
FormText = Annotated[str, Form()]
UploadFilePart = Annotated[UploadFile, File()]
OptionalFormText = Annotated[str | None, Form()]
OptionalUploadFilePart = Annotated[UploadFile | None, File()]
OptionalUploadFileList = Annotated[list[UploadFile] | None, File()]

REQUIRED_APPLICATION_FIELD_LABELS = {
    "brand_name": "Brand",
    "class_type": "Class/type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
    RESPONSIBLE_PARTY_FIELD: "Responsible party name/address",
    PRODUCT_ORIGIN_FIELD: "Product origin",
}
OPTIONAL_APPLICATION_FIELD_LABELS = {
    "cola_id": "COLA ID",
    "fanciful_name": "Fanciful name",
    "formula": "Formula",
    "grape_varietals": "Grape varietals",
    "wine_appellation": "Wine appellation",
    "serial_number": "Serial number",
    "producer": "Producer",
    COUNTRY_OF_ORIGIN_FIELD: "Country of origin",
}
FIELD_RESULT_DISPLAY_ORDER = {
    "brand_name": 0,
    "class_type": 1,
    "alcohol_content": 2,
    "net_contents": 3,
    "government_warning": 4,
    RESPONSIBLE_PARTY_FIELD: 5,
    PRODUCT_ORIGIN_FIELD: 6,
    COUNTRY_OF_ORIGIN_FIELD: 7,
}


class HumanDecisionRequest(BaseModel):
    decision: str
    note: str = Field(default="", max_length=2000)
    reviewer_label: str = Field(default="demo-agent", max_length=120)


@router.get("/config")
def app_config(settings: SettingsDep) -> dict[str, bool]:
    return {"review_token_required": settings.review_token_required}


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    brand_name: FormText,
    class_type: FormText,
    alcohol_content: FormText,
    net_contents: FormText,
    session: SessionDep,
    settings: SettingsDep,
    image: OptionalUploadFilePart = None,
    front_image: OptionalUploadFilePart = None,
    back_image: OptionalUploadFilePart = None,
    cola_id: OptionalFormText = None,
    fanciful_name: OptionalFormText = None,
    formula: OptionalFormText = None,
    grape_varietals: OptionalFormText = None,
    wine_appellation: OptionalFormText = None,
    serial_number: OptionalFormText = None,
    source_of_product: OptionalFormText = None,
    applicant_name_address: OptionalFormText = None,
    producer: OptionalFormText = None,
    country_of_origin: OptionalFormText = None,
) -> dict:
    application_fields = _normalize_application_fields(
        {
            "brand_name": brand_name,
            "class_type": class_type,
            "alcohol_content": alcohol_content,
            "net_contents": net_contents,
            "cola_id": cola_id,
            "fanciful_name": fanciful_name,
            "formula": formula,
            "grape_varietals": grape_varietals,
            "wine_appellation": wine_appellation,
            "serial_number": serial_number,
            "source_of_product": source_of_product,
            "applicant_name_address": applicant_name_address,
            "producer": producer,
            "country_of_origin": country_of_origin,
        }
    )
    uses_modern_assets = front_image is not None or back_image is not None
    upload_result = await _save_uploaded_label_images(
        settings,
        front_upload=front_image or image,
        back_upload=back_image,
        include_label_images=uses_modern_assets,
    )
    case = LabelCase(
        source="single_upload",
        status="queued",
        application_fields=application_fields,
        image_sha256=upload_result["verification_sha256"],
        image_path=upload_result["front_path"],
        label_images=upload_result["label_images"],
    )
    session.add(case)
    session.flush()
    session.add(VerificationJob(case_id=case.id, status="queued"))
    session.add(
        AuditEvent(case_id=case.id, event_type="case_created", payload={"source": "single_upload"})
    )
    session.commit()
    return {
        "id": case.id,
        "status": case.status,
        "application_fields": case.application_fields,
        "image_sha256": case.image_sha256,
        "image_assets": _public_image_assets(case),
    }


@router.post("/cases/{case_id}/verify", status_code=status.HTTP_202_ACCEPTED)
def queue_verification(case_id: str, session: SessionDep) -> dict[str, str]:
    case = session.get(LabelCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    case.application_fields = _normalize_stored_application_fields(case.application_fields)
    _clear_machine_evidence(session, case.id)
    case.status = "queued"
    case.current_recommendation = None
    session.add(VerificationJob(case_id=case.id, batch_id=case.batch_id, status="queued"))
    session.add(AuditEvent(case_id=case.id, event_type="verification_queued", payload={}))
    session.commit()
    return {"id": case.id, "status": "queued"}


@router.post("/batches", status_code=status.HTTP_201_CREATED)
async def create_batch(
    session: SessionDep,
    settings: SettingsDep,
    archive: OptionalUploadFilePart = None,
    manifest: OptionalUploadFilePart = None,
    images: OptionalUploadFileList = None,
) -> dict:
    parse_result, batch_filename = await _parse_batch_upload(archive, manifest, images, settings)
    rows = parse_result.rows
    import_summary = _batch_import_summary(parse_result)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No valid manifest rows were accepted",
                "rejected_rows": import_summary["rejected_rows"],
            },
        )
    batch = Batch(filename=batch_filename, status="queued", total_count=len(rows))
    session.add(batch)
    session.flush()
    for row in rows:
        image_bytes = row["image_bytes"]
        if not isinstance(image_bytes, bytes):
            raise HTTPException(status_code=400, detail="Batch parser returned invalid image bytes")
        digest, image_path = save_batch_image(
            settings.upload_dir,
            str(row["filename"]),
            image_bytes,
        )
        label_images = None
        verification_digest = digest
        if isinstance(row.get("back_image_bytes"), bytes):
            back_digest, back_path = save_batch_image(
                settings.upload_dir,
                str(row["back_filename"]),
                row["back_image_bytes"],
            )
            verification_digest, verification_path = save_combined_label_image(
                settings.upload_dir,
                [image_path, back_path],
            )
            label_images = [
                _stored_image_asset(
                    "front",
                    "Front",
                    image_path,
                    digest,
                    filename=str(row["filename"]),
                ),
                _stored_image_asset(
                    "back",
                    "Back",
                    back_path,
                    back_digest,
                    filename=str(row["back_filename"]),
                ),
                _stored_image_asset(
                    "verification",
                    "Verification",
                    verification_path,
                    verification_digest,
                    role="verification",
                ),
            ]
        case = LabelCase(
            batch_id=batch.id,
            source="batch_upload",
            status="queued",
            application_fields=_normalize_application_fields(
                {
                    field_name: _field_value(row, field_name)
                    for field_name in _all_application_fields()
                }
            ),
            image_sha256=verification_digest,
            image_path=image_path,
            label_images=label_images,
        )
        session.add(case)
        session.flush()
        session.add(VerificationJob(case_id=case.id, batch_id=batch.id, status="queued"))
    session.add(
        AuditEvent(
            batch_id=batch.id,
            event_type="batch_created",
            payload={"total_count": len(rows), "import_summary": import_summary},
        )
    )
    session.commit()
    return {
        "id": batch.id,
        "status": batch.status,
        "total_count": batch.total_count,
        "import_summary": import_summary,
    }


@router.get("/cases")
def list_cases(session: SessionDep, status_filter: str | None = None) -> dict:
    statement = select(LabelCase).order_by(LabelCase.created_at.desc()).limit(100)
    if status_filter:
        statement = (
            select(LabelCase)
            .where(LabelCase.status == status_filter)
            .order_by(LabelCase.created_at.desc())
            .limit(100)
        )
    cases = session.scalars(statement).all()
    counts = dict(
        session.execute(select(LabelCase.status, func.count()).group_by(LabelCase.status)).all()
    )
    return {
        "counts": counts,
        "items": [_serialize_case_summary(case) for case in cases],
    }


@router.get("/cases/{case_id}")
def get_case(case_id: str, session: SessionDep) -> dict:
    case = session.get(LabelCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return serialize_case_detail(case)


@router.get("/cases/{case_id}/image")
def get_case_image(
    case_id: str,
    session: SessionDep,
    image_key: str | None = None,
) -> FileResponse:
    case = session.get(LabelCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return FileResponse(_image_path_for_key(case, image_key))


@router.post("/cases/{case_id}/image", status_code=status.HTTP_202_ACCEPTED)
async def replace_case_image(
    case_id: str,
    image: UploadFilePart,
    session: SessionDep,
    settings: SettingsDep,
    _: ReviewTokenDep,
    image_key: Annotated[str, Form()] = "front",
) -> dict:
    case = session.get(LabelCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if image_key not in {"front", "back"}:
        raise HTTPException(status_code=400, detail="Image key must be front or back")

    previous_sha256 = case.image_sha256
    digest, path = await save_upload(settings.upload_dir, image, settings.max_upload_mb)
    _replace_case_image_asset(
        settings,
        case,
        image_key=image_key,
        path=path,
        sha256=digest,
        filename=image.filename or f"{image_key}-label",
    )
    _clear_machine_evidence(session, case.id)
    case.application_fields = _normalize_stored_application_fields(case.application_fields)
    case.status = "queued"
    case.current_recommendation = None
    case.final_decision = None
    case.final_note = None
    session.add(VerificationJob(case_id=case.id, batch_id=case.batch_id, status="queued"))
    session.add(
        AuditEvent(
            case_id=case.id,
            event_type="label_image_replaced",
            payload={
                "image_key": image_key,
                "filename": image.filename,
                "previous_sha256": previous_sha256,
                "new_sha256": case.image_sha256,
            },
        )
    )
    session.add(
        AuditEvent(
            case_id=case.id,
            event_type="verification_queued",
            payload={"source": "label_image_replaced"},
        )
    )
    session.commit()
    return serialize_case_detail(case)


@router.get("/batches")
def list_batches(session: SessionDep) -> dict:
    batches = session.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(100)).all()
    for batch in batches:
        reconcile_batch_progress(session, batch)
    session.commit()
    return {
        "items": [
            {
                "id": batch.id,
                "filename": batch.filename,
                "status": batch.status,
                "total_count": batch.total_count,
                "processed_count": batch.processed_count,
                "error": batch.error,
                "created_at": batch.created_at.isoformat(),
                "import_summary": _batch_import_summary_for_batch(session, batch.id),
            }
            for batch in batches
        ]
    }


@router.post("/cases/{case_id}/human-decision")
def record_human_decision(
    case_id: str,
    payload: HumanDecisionRequest,
    session: SessionDep,
    _: ReviewTokenDep,
) -> dict[str, str | None]:
    case = session.get(LabelCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    allowed = {
        "approved",
        "rejected",
        "better_image_requested",
        "override_approved",
        "override_rejected",
    }
    if payload.decision not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported human decision")

    case.final_decision = payload.decision
    case.final_note = payload.note
    case.status = _status_for_human_decision(payload.decision)
    session.add(
        HumanDecision(
            case_id=case.id,
            decision=payload.decision,
            note=payload.note,
            reviewer_label=payload.reviewer_label,
        )
    )
    session.add(
        AuditEvent(
            case_id=case.id,
            event_type="human_decision_recorded",
            payload=payload.model_dump(),
        )
    )
    session.commit()
    return {"id": case.id, "final_decision": case.final_decision, "status": case.status}


@router.get("/audit-events")
def list_audit_events(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    total_count = session.scalar(select(func.count()).select_from(AuditEvent)) or 0
    rows = session.scalars(
        select(AuditEvent)
        .options(
            selectinload(AuditEvent.case).selectinload(LabelCase.audit_events),
            selectinload(AuditEvent.case).selectinload(LabelCase.provider_usage),
        )
        .order_by(AuditEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [_serialize_audit_event(row, include_case_target=True) for row in rows],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
    }


def _status_for_human_decision(decision: str) -> str:
    if decision in {"approved", "override_approved"}:
        return "approved"
    if decision == "better_image_requested":
        return "better_image_requested"
    return "rejected"


def _normalize_application_fields(fields: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    try:
        metadata = normalize_and_validate_responsible_party_metadata(fields)
    except ApplicationMetadataError as exc:
        raise HTTPException(
            status_code=400,
            detail=_application_metadata_error_detail(exc),
        ) from exc
    for field_name, label in REQUIRED_APPLICATION_FIELD_LABELS.items():
        value = (fields.get(field_name) or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail=f"{label} is required")
        normalized[field_name] = metadata.get(
            field_name,
            _normalize_application_value(field_name, value),
        )
    for field_name in OPTIONAL_APPLICATION_FIELD_LABELS:
        value = (fields.get(field_name) or "").strip()
        if value:
            normalized[field_name] = metadata.get(
                field_name,
                _normalize_application_value(field_name, value),
            )
    normalized.update(metadata)
    return normalized


def _application_metadata_error_detail(exc: ApplicationMetadataError) -> str:
    label = REQUIRED_APPLICATION_FIELD_LABELS.get(
        exc.field_name,
        OPTIONAL_APPLICATION_FIELD_LABELS.get(exc.field_name, exc.field_name),
    )
    return f"{label} {exc.message}"


def _normalize_application_value(field_name: str, value: str) -> str:
    if field_name == "alcohol_content" and re.fullmatch(r"\d+(?:\.\d+)?", value):
        return f"{value}%"
    return value


def _normalize_stored_application_fields(fields: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for field_name, raw_value in fields.items():
        value = str(raw_value).strip() if raw_value is not None else ""
        if value:
            normalized[field_name] = _normalize_application_value(field_name, value)
    return normalized


def _clear_machine_evidence(session: Session, case_id: str) -> None:
    session.execute(delete(FieldResultRow).where(FieldResultRow.case_id == case_id))
    session.execute(delete(ProviderUsage).where(ProviderUsage.case_id == case_id))
    session.execute(delete(TierEvent).where(TierEvent.case_id == case_id))


def _serialize_case_summary(case: LabelCase) -> dict:
    return {
        "id": case.id,
        "batch_id": case.batch_id,
        "source": case.source,
        "status": case.status,
        "current_recommendation": case.current_recommendation,
        "final_decision": case.final_decision,
        "issue_summary": _case_issue_summary(case),
        "application_fields": case.application_fields,
        "created_at": case.created_at.isoformat(),
    }


def serialize_case_detail(case: LabelCase) -> dict:
    detail = _serialize_case_summary(case)
    detail.update(
        {
            "image_sha256": case.image_sha256,
            "image_url": _default_image_url(case),
            "image_assets": _public_image_assets(case),
            "final_note": case.final_note,
            "tier_events": [
                {
                    "id": event.id,
                    "layer": event.layer,
                    "decision": event.decision,
                    "confidence": event.confidence,
                    "rationale": event.rationale,
                    "evidence": event.evidence,
                    "latency_ms": event.latency_ms,
                    "error": event.error,
                    "created_at": event.created_at.isoformat(),
                }
                for event in case.tier_events
            ],
            "field_results": _serialize_field_results(case),
            "provider_usage": [
                {
                    "id": usage.id,
                    "provider": usage.provider,
                    "model": usage.model,
                    "base_url_label": usage.base_url_label,
                    "latency_ms": usage.latency_ms,
                    "tokens_input": usage.tokens_input,
                    "tokens_output": usage.tokens_output,
                    "estimated_cost_usd": usage.estimated_cost_usd,
                    "error": usage.error,
                    "created_at": usage.created_at.isoformat(),
                }
                for usage in case.provider_usage
            ],
            "human_decisions": [
                {
                    "id": decision.id,
                    "decision": decision.decision,
                    "note": decision.note,
                    "reviewer_label": decision.reviewer_label,
                    "created_at": decision.created_at.isoformat(),
                }
                for decision in case.human_decisions
            ],
            "audit_events": [
                _serialize_audit_event(event, include_case_target=False)
                for event in case.audit_events
            ],
        }
    )
    return detail


def _serialize_audit_event(row: AuditEvent, *, include_case_target: bool) -> dict:
    payload = {
        "id": row.id,
        "case_id": row.case_id,
        "batch_id": row.batch_id,
        "event_type": row.event_type,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }
    if include_case_target and row.case is not None:
        payload["case"] = {
            "id": row.case.id,
            "display_id": _case_display_id(row.case),
            "display_label": _case_display_label(row.case),
            "brand_name": row.case.application_fields.get("brand_name", "Untitled case"),
            "status": row.case.status,
            "issue_summary": _case_issue_summary(row.case),
            "provider_latency_ms": _provider_latency_ms(row.case) or None,
        }
    return payload


def _batch_import_summary_for_batch(session: Session, batch_id: str) -> dict | None:
    event = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.batch_id == batch_id,
            AuditEvent.event_type == "batch_created",
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    if event is None:
        return None
    import_summary = event.payload.get("import_summary")
    return import_summary if isinstance(import_summary, dict) else None


def _provider_latency_ms(case: LabelCase) -> int:
    return sum(max(0, usage.latency_ms) for usage in case.provider_usage)


def _case_display_id(case: LabelCase) -> str:
    fields = case.application_fields
    return (
        fields.get("cola_id")
        or fields.get("ttb_id")
        or fields.get("serial_number")
        or case.id[:8]
    )


def _case_display_label(case: LabelCase) -> str:
    fields = case.application_fields
    identifier = fields.get("cola_id") or fields.get("ttb_id") or fields.get("serial_number")
    return f"COLA {identifier}" if identifier else f"Case {case.id[:8]}"


def _case_issue_summary(case: LabelCase) -> str:
    if case.final_note:
        return case.final_note

    if case.field_results and case.current_recommendation == "PASS":
        return "All checked fields matched the application"

    latest_event = max(
        case.tier_events,
        key=lambda event: (event.created_at, event.id or 0),
        default=None,
    )
    if (
        case.status == "needs_review"
        and latest_event
        and latest_event.layer == "human_review"
        and latest_event.rationale
        and _human_review_reason(latest_event) != "uncertain_or_incomplete_evidence"
    ):
        return latest_event.rationale

    problem_rows = [
        row
        for row in _latest_field_results(case.field_results)
        if row.verdict in {"mismatch", "missing", "uncertain"}
    ]
    if problem_rows:
        return "; ".join(_field_issue_summary(row) for row in problem_rows[:2])

    if latest_event and latest_event.rationale:
        return latest_event.rationale

    if case.status == "queued":
        return "Waiting for verification"
    if case.status == "processing":
        return "Verification in progress"
    if case.status == "needs_review":
        return "Needs human review"
    if case.status == "machine_passed":
        return "Machine verification passed"
    if case.status == "machine_failed":
        return "Machine verification failed"
    if case.status == "approved":
        return "Approved by reviewer"
    if case.status == "rejected":
        return "Rejected by reviewer"
    if case.status == "better_image_requested":
        return "Replacement image requested"
    return case.status.replace("_", " ")


def _human_review_reason(event: TierEvent) -> str | None:
    evidence = event.evidence if isinstance(event.evidence, dict) else {}
    reason = evidence.get("reason")
    return reason if isinstance(reason, str) else None


def _latest_field_results(rows: list[FieldResultRow]) -> list[FieldResultRow]:
    latest_by_field: dict[str, FieldResultRow] = {}
    for row in rows:
        current = latest_by_field.get(row.field_name)
        if current is None or (row.created_at, row.id) > (current.created_at, current.id):
            latest_by_field[row.field_name] = row
    return sorted(
        latest_by_field.values(),
        key=lambda row: (
            FIELD_RESULT_DISPLAY_ORDER.get(row.field_name, len(FIELD_RESULT_DISPLAY_ORDER)),
            row.field_name,
        ),
    )


def _serialize_field_results(case: LabelCase) -> list[dict]:
    latest_rows = _latest_field_results(case.field_results)
    return sorted(
        [_serialize_field_result_row(row) for row in latest_rows],
        key=lambda row: (
            FIELD_RESULT_DISPLAY_ORDER.get(row["field_name"], len(FIELD_RESULT_DISPLAY_ORDER)),
            row["field_name"],
        ),
    )


def _serialize_field_result_row(row: FieldResultRow) -> dict:
    return {
        "id": row.id,
        "field_name": row.field_name,
        "expected_value": row.expected_value,
        "extracted_value": row.extracted_value,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "source_layer": row.source_layer,
        "created_at": row.created_at.isoformat(),
    }


def _field_issue_summary(row: FieldResultRow) -> str:
    label = REQUIRED_APPLICATION_FIELD_LABELS.get(
        row.field_name,
        OPTIONAL_APPLICATION_FIELD_LABELS.get(
            row.field_name,
            row.field_name.replace("_", " ").title(),
        ),
    )
    if row.verdict == "missing":
        return f"{label} not found"
    if row.verdict == "uncertain":
        return f"{label} needs review"
    extracted = row.extracted_value or "not found"
    return f"{label} mismatch: expected {row.expected_value}; found {extracted}"


async def _save_uploaded_label_images(
    settings: Settings,
    front_upload: UploadFile | None,
    back_upload: UploadFile | None,
    include_label_images: bool,
) -> dict[str, object]:
    if not _has_file(front_upload):
        raise HTTPException(status_code=400, detail="Front label image is required")

    assert front_upload is not None
    front_digest, front_path = await save_upload(
        settings.upload_dir,
        front_upload,
        settings.max_upload_mb,
    )
    verification_digest = front_digest
    label_images = (
        [
            _stored_image_asset(
                "front",
                "Front",
                front_path,
                front_digest,
                filename=front_upload.filename or "front-label",
            )
        ]
        if include_label_images
        else None
    )

    if _has_file(back_upload):
        assert back_upload is not None
        back_digest, back_path = await save_upload(
            settings.upload_dir,
            back_upload,
            settings.max_upload_mb,
        )
        verification_digest, verification_path = save_combined_label_image(
            settings.upload_dir,
            [front_path, back_path],
        )
        label_images = label_images or [
            _stored_image_asset(
                "front",
                "Front",
                front_path,
                front_digest,
                filename=front_upload.filename or "front-label",
            )
        ]
        label_images.append(
            _stored_image_asset(
                "back",
                "Back",
                back_path,
                back_digest,
                filename=back_upload.filename or "back-label",
            )
        )
        label_images.append(
            _stored_image_asset(
                "verification",
                "Verification",
                verification_path,
                verification_digest,
                role="verification",
            )
        )

    return {
        "front_path": front_path,
        "verification_sha256": verification_digest,
        "label_images": label_images,
    }


def _replace_case_image_asset(
    settings: Settings,
    case: LabelCase,
    *,
    image_key: str,
    path: str,
    sha256: str,
    filename: str,
) -> None:
    if not case.label_images and image_key == "front":
        case.image_path = path
        case.image_sha256 = sha256
        return

    assets = [
        dict(asset)
        for asset in (case.label_images or [])
        if asset.get("role") != "verification"
    ]
    if not assets:
        assets.append(
            _stored_image_asset("front", "Front", case.image_path, case.image_sha256)
        )

    replacement = _stored_image_asset(
        image_key,
        image_key.title(),
        path,
        sha256,
        filename=filename,
    )
    for index, asset in enumerate(assets):
        if asset.get("key") == image_key:
            assets[index] = replacement
            break
    else:
        assets.append(replacement)

    front_asset = _asset_for_key(assets, "front")
    back_asset = _asset_for_key(assets, "back")
    if front_asset is None:
        raise HTTPException(status_code=400, detail="Front label image is required")

    case.image_path = str(front_asset["path"])
    if back_asset is not None:
        verification_digest, verification_path = save_combined_label_image(
            settings.upload_dir,
            [str(front_asset["path"]), str(back_asset["path"])],
        )
        assets.append(
            _stored_image_asset(
                "verification",
                "Verification",
                verification_path,
                verification_digest,
                role="verification",
            )
        )
        case.image_sha256 = verification_digest
    else:
        case.image_sha256 = str(front_asset["sha256"])
    case.label_images = assets


def _asset_for_key(assets: list[dict[str, object]], key: str) -> dict[str, object] | None:
    return next((asset for asset in assets if asset.get("key") == key), None)


async def _parse_batch_upload(
    archive: UploadFile | None,
    manifest: UploadFile | None,
    images: list[UploadFile] | None,
    settings: Settings,
) -> tuple[BatchManifestParseResult, str]:
    image_uploads = [upload for upload in images or [] if _has_file(upload)]
    if _has_file(archive):
        if _has_file(manifest) or image_uploads:
            raise HTTPException(
                status_code=400,
                detail="Use either a ZIP archive or a CSV manifest with image files",
            )
        assert archive is not None
        if archive.content_type not in {"application/zip", "application/x-zip-compressed"}:
            raise HTTPException(status_code=400, detail="Batch upload must be a ZIP file")
        try:
            parse_result = parse_manifest_zip(await archive.read())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return parse_result, archive.filename or "labels.zip"

    if not _has_file(manifest):
        raise HTTPException(status_code=400, detail="Batch upload requires a manifest CSV")
    if not image_uploads:
        raise HTTPException(status_code=400, detail="Batch upload requires image files")

    assert manifest is not None
    image_lookup = await _read_batch_image_uploads(image_uploads, settings)
    try:
        parse_result = parse_manifest_files(await manifest.read(), image_lookup)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parse_result, manifest.filename or "manifest.csv"


def _batch_import_summary(parse_result: BatchManifestParseResult) -> dict:
    return {
        "selected_image_count": parse_result.selected_image_count,
        "accepted_image_count": parse_result.accepted_image_count,
        "ignored_images": parse_result.ignored_images,
        "inferred_back_images": [
            {"filename": item.filename, "back_filename": item.back_filename}
            for item in parse_result.inferred_back_images
        ],
        "rejected_rows": [
            {
                "row_number": item.row_number,
                "filename": item.filename,
                "reason": item.reason,
            }
            for item in parse_result.rejected_rows
        ],
    }


async def _read_batch_image_uploads(
    uploads: list[UploadFile],
    settings: Settings,
) -> dict[str, bytes]:
    image_lookup: dict[str, bytes] = {}
    max_bytes = settings.max_upload_mb * 1024 * 1024
    for upload in uploads:
        filename = upload.filename or ""
        if not filename:
            continue
        if filename in image_lookup:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate selected image filename: {filename}",
            )
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"Selected image is empty: {filename}")
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Selected image exceeds {settings.max_upload_mb} MB: {filename}",
            )
        image_lookup[filename] = content
    return image_lookup


def _has_file(upload: UploadFile | None) -> bool:
    return bool(upload and upload.filename)


def _stored_image_asset(
    key: str,
    label: str,
    path: str,
    sha256: str,
    *,
    filename: str | None = None,
    role: str | None = None,
) -> dict[str, str]:
    asset = {"key": key, "label": label, "path": path, "sha256": sha256}
    if filename:
        asset["filename"] = filename
    if role:
        asset["role"] = role
    return asset


def _public_image_assets(case: LabelCase) -> list[dict[str, str]]:
    if not case.label_images:
        return [
            {
                "key": "front",
                "label": "Front",
                "image_url": _public_image_url(case, sha256=case.image_sha256),
                "sha256": case.image_sha256,
            }
        ]

    assets: list[dict[str, str]] = []
    for asset in case.label_images:
        if asset.get("role") == "verification":
            continue
        key = str(asset.get("key") or "")
        if not key:
            continue
        public_asset = {
            "key": key,
            "label": str(asset.get("label") or key.title()),
            "image_url": _public_image_url(
                case,
                image_key=key,
                sha256=str(asset.get("sha256") or ""),
            ),
        }
        if asset.get("sha256"):
            public_asset["sha256"] = str(asset["sha256"])
        assets.append(public_asset)
    return assets or [
        {
            "key": "front",
            "label": "Front",
            "image_url": _public_image_url(case, sha256=case.image_sha256),
            "sha256": case.image_sha256,
        }
    ]


def _default_image_url(case: LabelCase) -> str:
    assets = _public_image_assets(case)
    return assets[0]["image_url"] if assets else _public_image_url(case, sha256=case.image_sha256)


def _public_image_url(
    case: LabelCase,
    *,
    image_key: str | None = None,
    sha256: str | None = None,
) -> str:
    params = []
    if image_key:
        params.append(f"image_key={image_key}")
    if sha256:
        params.append(f"v={sha256}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return f"/api/cases/{case.id}/image{suffix}"


def _image_path_for_key(case: LabelCase, image_key: str | None) -> str:
    if not case.label_images:
        if image_key and image_key != "front":
            raise HTTPException(status_code=404, detail="Image asset not found")
        return case.image_path

    selected_key = image_key or "front"
    for asset in case.label_images:
        if asset.get("key") == selected_key and asset.get("path"):
            return str(asset["path"])
    raise HTTPException(status_code=404, detail="Image asset not found")


def _all_application_fields() -> tuple[str, ...]:
    return tuple(REQUIRED_APPLICATION_FIELD_LABELS) + tuple(OPTIONAL_APPLICATION_FIELD_LABELS)


def _field_value(row: dict[str, str | bytes], field_name: str) -> str | None:
    value = row.get(field_name)
    return value if isinstance(value, str) else None
