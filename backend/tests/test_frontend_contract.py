import re
from pathlib import Path


def test_review_status_strip_exposes_final_human_decision_statuses() -> None:
    app_source = Path("frontend/src/App.tsx").read_text()
    match = re.search(r"const queueStatusFilters = \[(?P<body>.*?)\];", app_source, re.S)

    assert match is not None
    status_filter_source = match.group("body")
    assert '"approved"' in status_filter_source
    assert '"rejected"' in status_filter_source
