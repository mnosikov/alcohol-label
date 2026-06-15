from pathlib import Path

from backend.app.evals.golden import DEFAULT_EVAL_MANIFEST, load_eval_suite, run_eval_suite
from backend.app.pipeline.types import CaseStatus, MachineDecision


def test_golden_eval_suite_covers_core_routing_outcomes() -> None:
    suite = load_eval_suite(DEFAULT_EVAL_MANIFEST)
    report = run_eval_suite(suite, image_path=Path("eval-label.png"))

    assert report.passed is True, report.to_text()
    assert {case.expected_recommendation for case in suite.cases} == {
        MachineDecision.PASS,
        MachineDecision.FAIL,
        MachineDecision.NEEDS_REVIEW,
    }
    assert {case.expected_status for case in suite.cases} >= {
        CaseStatus.MACHINE_PASSED,
        CaseStatus.MACHINE_FAILED,
        CaseStatus.NEEDS_REVIEW,
    }
    assert {
        "ocr_escalation",
        "provider_failure",
        "poor_image",
        "sampled_review",
        "warning_format",
    }.issubset({tag for case in suite.cases for tag in case.tags})
