from typing import Any


def confidence_evidence(
    *,
    raw_score: float | None = None,
    calibrated_confidence: float | None = None,
    calibration_context: str | None = None,
    out_of_distribution_flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "confidence_assessment": {
            "raw_score": raw_score,
            "calibrated_confidence": calibrated_confidence,
            "calibration_context": calibration_context,
            "is_calibrated": calibrated_confidence is not None,
            "out_of_distribution_flags": out_of_distribution_flags or [],
            "note": (
                "Raw scores guide escalation, but only calibrated confidence should be used "
                "for release gates or automation-rate claims."
            ),
        }
    }


def source_reference(
    kind: str,
    key: str,
    value: str,
    *,
    source_id: str | None = None,
) -> dict[str, str]:
    reference = {"kind": kind, "key": key, "value": value}
    if source_id is not None:
        reference["source_id"] = source_id
    return reference


LABEL_APPLICATION_SOURCES = [
    source_reference("label_artifact", "uploaded_image", "preserved case image"),
    source_reference("application_fields", "expected_values", "submitted COLA-style fields"),
]
