from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CANONICAL_GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or operate "
    "machinery, and may cause health problems."
)


class MachineDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class HumanDecisionValue(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    BETTER_IMAGE_REQUESTED = "better_image_requested"
    OVERRIDE_APPROVED = "override_approved"
    OVERRIDE_REJECTED = "override_rejected"


class CaseStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    MACHINE_PASSED = "machine_passed"
    MACHINE_FAILED = "machine_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    BETTER_IMAGE_REQUESTED = "better_image_requested"
    ERROR = "error"


class BatchStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class LayerName(StrEnum):
    RULES = "rules"
    OCR = "ocr"
    IMAGE_QUALITY = "image_quality"
    VISION = "vision"
    HUMAN_REVIEW = "human_review"


class FieldVerdict(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class ApplicationFields:
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    cola_id: str | None = None
    fanciful_name: str | None = None
    formula: str | None = None
    grape_varietals: str | None = None
    wine_appellation: str | None = None
    serial_number: str | None = None
    source_of_product: str | None = None
    applicant_name_address: str | None = None
    producer: str | None = None
    country_of_origin: str | None = None


@dataclass(frozen=True)
class ExtractedFields:
    brand_name: str | None = None
    class_type: str | None = None
    alcohol_content: str | None = None
    net_contents: str | None = None
    government_warning: str | None = None
    warning_prefix_bold: bool | None = None
    raw_text: str | None = None
    field_confidence: dict[str, float] = field(default_factory=dict)
    image_quality: str | None = None


@dataclass(frozen=True)
class FieldResult:
    field_name: str
    expected_value: str
    extracted_value: str | None
    verdict: FieldVerdict
    confidence: float
    rationale: str
    source_layer: LayerName


@dataclass(frozen=True)
class LayerOutcome:
    layer: LayerName
    decision: MachineDecision
    confidence: float | None
    rationale: str
    extracted: ExtractedFields | None = None
    field_results: list[FieldResult] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0
