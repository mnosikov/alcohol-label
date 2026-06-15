from hashlib import sha256
from io import BytesIO
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent, LabelCase, VerificationJob
from backend.app.pipeline.types import CANONICAL_GOVERNMENT_WARNING
from backend.app.storage import save_image_bytes

DEFAULT_APPLICATION = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
}


def _label_font() -> ImageFont.ImageFont:
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(font_path, 38)
        except OSError:
            continue
    return ImageFont.load_default()


def create_label_bytes(lines: list[str], *, poor_quality: bool = False) -> bytes:
    image = Image.new("RGB", (1200, 800), color="#f7f2e8")
    draw = ImageDraw.Draw(image)
    font = _label_font()
    y = 80
    for line in lines:
        for wrapped in wrap(line, width=48):
            draw.text((80, y), wrapped, fill="#1f2933", font=font)
            y += 52
        y += 10
    if poor_quality:
        image = image.rotate(4, expand=True, fillcolor="#f7f2e8").filter(
            ImageFilter.GaussianBlur(1.2)
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def fixture_definitions() -> dict[str, tuple[list[str], bool]]:
    return {
        "happy-bourbon.png": (
            [
                "OLD TOM DISTILLERY",
                "Kentucky Straight Bourbon Whiskey",
                "45% Alc./Vol. (90 Proof)",
                "750 mL",
                CANONICAL_GOVERNMENT_WARNING,
            ],
            False,
        ),
        "abv-mismatch.png": (
            [
                "OLD TOM DISTILLERY",
                "Kentucky Straight Bourbon Whiskey",
                "40% Alc./Vol. (80 Proof)",
                "750 mL",
                CANONICAL_GOVERNMENT_WARNING,
            ],
            False,
        ),
        "warning-title-case.png": (
            [
                "OLD TOM DISTILLERY",
                "Kentucky Straight Bourbon Whiskey",
                "45% Alc./Vol. (90 Proof)",
                "750 mL",
                CANONICAL_GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"),
            ],
            False,
        ),
        "missing-warning.png": (
            [
                "OLD TOM DISTILLERY",
                "Kentucky Straight Bourbon Whiskey",
                "45% Alc./Vol. (90 Proof)",
                "750 mL",
            ],
            False,
        ),
        "poor-image.png": (
            [
                "OLD TOM DISTILLERY",
                "Kentucky Straight Bourbon Whiskey",
                "45% Alc./Vol. (90 Proof)",
                "750 mL",
                CANONICAL_GOVERNMENT_WARNING,
            ],
            True,
        ),
    }


def generate_fixtures(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, (lines, poor_quality) in fixture_definitions().items():
        (directory / filename).write_bytes(create_label_bytes(lines, poor_quality=poor_quality))


def seed_demo_cases(session: Session, upload_dir: Path) -> None:
    for filename, (lines, poor_quality) in fixture_definitions().items():
        content = create_label_bytes(lines, poor_quality=poor_quality)
        digest = sha256(content).hexdigest()
        existing = session.scalar(select(LabelCase).where(LabelCase.image_sha256 == digest))
        if existing is not None:
            continue
        _, image_path = save_image_bytes(upload_dir, filename, content, "image/png")
        case = LabelCase(
            source="seed_demo",
            status="queued",
            application_fields=dict(DEFAULT_APPLICATION),
            image_sha256=digest,
            image_path=image_path,
        )
        session.add(case)
        session.flush()
        session.add(VerificationJob(case_id=case.id, status="queued"))
        session.add(
            AuditEvent(
                case_id=case.id,
                event_type="case_created",
                payload={"source": "seed_demo", "fixture": filename},
            )
        )
    session.commit()


if __name__ == "__main__":
    generate_fixtures(Path("backend/tests/fixtures"))
