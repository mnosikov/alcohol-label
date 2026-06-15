from pathlib import Path

from backend.app.evals.golden import load_eval_suite, run_eval_suite
from backend.app.pipeline.types import CaseStatus, MachineDecision

REAL_LABEL_EVAL_MANIFEST = (
    Path(__file__).parent / "fixtures" / "evals" / "real-label-evals.json"
)


def test_real_label_eval_suite_captures_observed_edge_cases() -> None:
    suite = load_eval_suite(REAL_LABEL_EVAL_MANIFEST)
    report = run_eval_suite(suite, image_path=Path("eval-label.png"))

    assert report.passed is True, report.to_text()
    assert len(suite.cases) >= 10
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
        "accent_tolerant",
        "beer_word_present",
        "beer_style_without_beer_word",
        "canonical_warning_uppercase",
        "missing_rear_label_evidence",
        "soft_quality_pass",
        "warning_punctuation",
    }.issubset({tag for case in suite.cases for tag in case.tags})
