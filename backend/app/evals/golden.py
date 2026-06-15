import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.observability.langsmith import traceable
from backend.app.pipeline.decision import status_for_machine_decision
from backend.app.pipeline.review_sampling import should_sample_auto_pass
from backend.app.pipeline.runner import VerificationPipeline
from backend.app.pipeline.types import (
    CANONICAL_GOVERNMENT_WARNING,
    ApplicationFields,
    CaseStatus,
    MachineDecision,
)
from backend.app.pipeline.vision import VisionExtraction

DEFAULT_EVAL_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "tests"
    / "fixtures"
    / "evals"
    / "golden-label-evals.json"
)

CANONICAL_WARNING_TOKEN = "__CANONICAL_GOVERNMENT_WARNING__"
CANONICAL_WARNING_UPPER_TOKEN = "__CANONICAL_GOVERNMENT_WARNING_UPPER__"


@dataclass(frozen=True)
class GoldenEvalCase:
    id: str
    description: str
    application: ApplicationFields
    ocr_text: str
    ocr_confidence: float
    vision_payload: dict[str, Any]
    expected_recommendation: MachineDecision
    expected_status: CaseStatus
    sampled_review_rate: float
    image_sha256: str
    tags: list[str]


@dataclass(frozen=True)
class GoldenEvalSuite:
    name: str
    version: int
    cases: list[GoldenEvalCase]


@dataclass(frozen=True)
class GoldenEvalResult:
    case_id: str
    expected_recommendation: MachineDecision
    actual_recommendation: MachineDecision
    expected_status: CaseStatus
    actual_status: CaseStatus
    passed: bool
    tags: list[str]


@dataclass(frozen=True)
class GoldenEvalReport:
    suite_name: str
    results: list[GoldenEvalResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def counts_by_status(self) -> dict[str, int]:
        return dict(Counter(result.actual_status.value for result in self.results))

    def to_text(self) -> str:
        passed_count = sum(result.passed for result in self.results)
        lines = [f"{self.suite_name}: {passed_count}/{len(self.results)} passed"]
        for result in self.results:
            marker = "PASS" if result.passed else "FAIL"
            lines.append(
                f"{marker} {result.case_id}: expected "
                f"{result.expected_recommendation.value}/{result.expected_status.value}, got "
                f"{result.actual_recommendation.value}/{result.actual_status.value}"
            )
        return "\n".join(lines)


class EvalOcrProvider:
    def __init__(self, text: str, confidence: float) -> None:
        self.text = text
        self.confidence = confidence

    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return self.text, self.confidence


class EvalVisionProvider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def extract(self, image_path: Path) -> VisionExtraction:
        if self.payload.get("error"):
            return VisionExtraction(
                provider="eval",
                model="fixture",
                latency_ms=0,
                error=str(self.payload["error"]),
            )
        return VisionExtraction(
            provider="eval",
            model="fixture",
            latency_ms=0,
            extracted=_resolve_placeholders(self.payload.get("extracted", {})),
        )


def load_eval_suite(path: Path = DEFAULT_EVAL_MANIFEST) -> GoldenEvalSuite:
    payload = json.loads(path.read_text())
    return GoldenEvalSuite(
        name=payload["name"],
        version=int(payload["version"]),
        cases=[_load_case(case) for case in payload["cases"]],
    )


@traceable(
    name="golden_eval_suite",
    run_type="chain",
    process_inputs=lambda inputs: {
        "suite_name": inputs["suite"].name,
        "version": inputs["suite"].version,
        "case_count": len(inputs["suite"].cases),
    },
    process_outputs=lambda output: {
        "passed": output.passed,
        "counts_by_status": output.counts_by_status,
        "case_count": len(output.results),
    },
)
def run_eval_suite(suite: GoldenEvalSuite, image_path: Path) -> GoldenEvalReport:
    return GoldenEvalReport(
        suite_name=suite.name,
        results=[run_eval_case(case, image_path) for case in suite.cases],
    )


@traceable(
    name="golden_eval_case",
    run_type="tool",
    process_inputs=lambda inputs: {
        "case_id": inputs["case"].id,
        "tags": inputs["case"].tags,
        "expected_recommendation": inputs["case"].expected_recommendation.value,
        "expected_status": inputs["case"].expected_status.value,
        "sampled_review_rate": inputs["case"].sampled_review_rate,
    },
    process_outputs=lambda output: {
        "case_id": output.case_id,
        "passed": output.passed,
        "actual_recommendation": output.actual_recommendation.value,
        "actual_status": output.actual_status.value,
    },
)
def run_eval_case(case: GoldenEvalCase, image_path: Path) -> GoldenEvalResult:
    pipeline = VerificationPipeline(
        ocr=EvalOcrProvider(case.ocr_text, case.ocr_confidence),
        vision=EvalVisionProvider(case.vision_payload),
    )
    pipeline_result = pipeline.verify(image_path, case.application)
    actual_status = status_for_machine_decision(pipeline_result.recommendation)
    if (
        pipeline_result.recommendation == MachineDecision.PASS
        and should_sample_auto_pass(case.id, case.image_sha256, case.sampled_review_rate)
    ):
        actual_status = CaseStatus.NEEDS_REVIEW

    passed = (
        pipeline_result.recommendation == case.expected_recommendation
        and actual_status == case.expected_status
    )
    return GoldenEvalResult(
        case_id=case.id,
        expected_recommendation=case.expected_recommendation,
        actual_recommendation=pipeline_result.recommendation,
        expected_status=case.expected_status,
        actual_status=actual_status,
        passed=passed,
        tags=case.tags,
    )


def _load_case(payload: dict[str, Any]) -> GoldenEvalCase:
    return GoldenEvalCase(
        id=payload["id"],
        description=payload["description"],
        application=ApplicationFields(**payload["application"]),
        ocr_text=_resolve_text(payload.get("ocr", {}).get("text", "")),
        ocr_confidence=float(payload.get("ocr", {}).get("confidence", 0.0)),
        vision_payload=payload.get("vision", {}),
        expected_recommendation=MachineDecision(payload["expected_recommendation"]),
        expected_status=CaseStatus(payload["expected_status"]),
        sampled_review_rate=float(payload.get("sampled_review_rate", 0.0)),
        image_sha256=payload.get("image_sha256", payload["id"]),
        tags=list(payload.get("tags", [])),
    )


def _resolve_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(item) for item in value]
    if value == CANONICAL_WARNING_TOKEN:
        return CANONICAL_GOVERNMENT_WARNING
    if value == CANONICAL_WARNING_UPPER_TOKEN:
        return CANONICAL_GOVERNMENT_WARNING.upper()
    return value


def _resolve_text(text: str) -> str:
    return text.replace(CANONICAL_WARNING_TOKEN, CANONICAL_GOVERNMENT_WARNING).replace(
        CANONICAL_WARNING_UPPER_TOKEN,
        CANONICAL_GOVERNMENT_WARNING.upper(),
    )


if __name__ == "__main__":
    report = run_eval_suite(load_eval_suite(), Path("eval-label.png"))
    print(report.to_text())
    raise SystemExit(0 if report.passed else 1)
