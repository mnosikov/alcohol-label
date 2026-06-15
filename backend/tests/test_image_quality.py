from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from backend.app.pipeline.image_quality import assess_local_image_quality


def _clear_label(path: Path) -> None:
    image = Image.new("RGB", (640, 360), "#f6f1dc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((46, 42, 594, 318), outline="#353535", width=4)
    draw.rectangle((80, 78, 560, 142), fill="#2b2b2b", outline="#8a1f1f", width=3)
    draw.rectangle((80, 270, 560, 310), fill="#7d1f1f")
    draw.text((110, 98), "OLD TOM DISTILLERY", fill="#f6f1dc")
    draw.text((110, 162), "Bourbon", fill="#151515")
    draw.text((110, 210), "45% Alc./Vol.", fill="#151515")
    draw.text((110, 282), "750 mL", fill="#f6f1dc")
    for y in range(188, 252, 16):
        draw.line((110, y, 530, y), fill="#5f5138", width=2)
    for x in range(120, 540, 42):
        draw.line((x, 84, x, 136), fill="#f6f1dc", width=1)
    image.save(path)


def test_clear_label_does_not_require_review(tmp_path: Path) -> None:
    image_path = tmp_path / "clear.png"
    _clear_label(image_path)

    assessment = assess_local_image_quality(image_path)

    assert assessment.requires_review is False
    assert assessment.flags == []


def test_low_contrast_label_requires_review(tmp_path: Path) -> None:
    image_path = tmp_path / "low-contrast.png"
    image = Image.new("RGB", (640, 360), "#777777")
    draw = ImageDraw.Draw(image)
    draw.rectangle((46, 42, 594, 318), outline="#858585", width=4)
    draw.text((110, 94), "OLD TOM DISTILLERY", fill="#8a8a8a")
    draw.text((110, 162), "Bourbon", fill="#8a8a8a")
    draw.text((110, 210), "45% Alc./Vol.", fill="#8a8a8a")
    image.save(image_path)

    assessment = assess_local_image_quality(image_path)

    assert assessment.requires_review is True
    assert "local_low_contrast" in assessment.flags
    assert "low contrast" in assessment.rationale


def test_blurry_label_requires_review(tmp_path: Path) -> None:
    image_path = tmp_path / "blurry.png"
    _clear_label(image_path)
    Image.open(image_path).filter(ImageFilter.GaussianBlur(radius=3)).save(image_path)

    assessment = assess_local_image_quality(image_path)

    assert assessment.requires_review is True
    assert "local_blur" in assessment.flags
    assert "blur or weak edge detail" in assessment.rationale


def test_glare_obscured_label_requires_review(tmp_path: Path) -> None:
    image_path = tmp_path / "glare.png"
    _clear_label(image_path)
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((440, 0, 639, 359), fill="#ffffff")
    image.save(image_path)

    assessment = assess_local_image_quality(image_path)

    assert assessment.requires_review is True
    assert "local_glare" in assessment.flags
    assert "glare or washed-out bright areas" in assessment.rationale


def test_skewed_label_requires_review(tmp_path: Path) -> None:
    image_path = tmp_path / "skewed.png"
    _clear_label(image_path)
    image = Image.open(image_path).convert("RGB")
    skewed = image.rotate(
        7,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor="#f6f1dc",
    )
    skewed.save(image_path)

    assessment = assess_local_image_quality(image_path)

    assert assessment.requires_review is True
    assert "local_skew" in assessment.flags
    assert "skew or rotation" in assessment.rationale
