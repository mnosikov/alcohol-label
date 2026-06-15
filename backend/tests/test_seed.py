from pathlib import Path

from backend.app.seed import generate_fixtures


def test_generate_fixtures_creates_expected_images(tmp_path: Path) -> None:
    generate_fixtures(tmp_path)

    assert (tmp_path / "happy-bourbon.png").exists()
    assert (tmp_path / "abv-mismatch.png").exists()
    assert (tmp_path / "warning-title-case.png").exists()
