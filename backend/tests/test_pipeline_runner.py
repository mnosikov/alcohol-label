from pathlib import Path

from PIL import Image, ImageDraw

from backend.app.pipeline.runner import VerificationPipeline
from backend.app.pipeline.types import (
    CANONICAL_GOVERNMENT_WARNING,
    ApplicationFields,
    MachineDecision,
)
from backend.app.pipeline.vision import NoopVisionProvider, VisionExtraction


class EmptyOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return "", 0.0


class MatchingOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "OLD TOM DISTILLERY\n"
            "Bourbon\n"
            "45% Alc./Vol.\n"
            "750 mL\n"
            f"{CANONICAL_GOVERNMENT_WARNING}",
            0.94,
        )


class NetContentsMismatchOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "Bärenjäger\n"
            "Honey Liqueur\n"
            "50ML\n"
            "35% ALC. BY VOL.\n"
            f"{CANONICAL_GOVERNMENT_WARNING.upper()}",
            0.93,
        )


class LowConfidenceMatchingOcrProvider(MatchingOcrProvider):
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        text, _confidence = super().extract_text(image_path)
        return text, 0.62


class LowConfidenceBeerTextOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "IRONWOOD BREWING CO.\n"
            "India Pale Ale\n"
            "Beer\n"
            "6.8% Alc./Vol.\n"
            "12 FL OZ\n",
            0.68,
        )


class TextualMismatchOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "SMALL BATCH\n"
            "Bourbon\n"
            "45% Alc./Vol.\n"
            "750 mL\n"
            f"{CANONICAL_GOVERNMENT_WARNING}",
            0.96,
        )


class UnexpectedVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        raise AssertionError("Vision provider should not be called")


class PassingVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=10,
            extracted={
                "brand_name": "OLD TOM DISTILLERY",
                "class_type": "Bourbon",
                "alcohol_content": "45% Alc./Vol.",
                "net_contents": "750 mL",
                "government_warning": CANONICAL_GOVERNMENT_WARNING,
                "warning_prefix_bold": True,
                "image_quality": "clear",
                "field_confidence": {},
            },
        )


class FailingVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=10,
            extracted={
                "brand_name": "MB Liquors",
                "class_type": "Vodka",
                "alcohol_content": "40% Alc./Vol.",
                "net_contents": "750 mL",
                "government_warning": CANONICAL_GOVERNMENT_WARNING,
                "warning_prefix_bold": True,
                "image_quality": "skewed",
                "field_confidence": {},
            },
        )


class BeerStyleVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=10,
            extracted={
                "brand_name": "IRONWOOD BREWING CO.",
                "class_type": "India Pale Ale",
                "alcohol_content": "6.8% Alc./Vol.",
                "net_contents": "12 FL OZ",
                "government_warning": CANONICAL_GOVERNMENT_WARNING,
                "warning_prefix_bold": True,
                "image_quality": "clear",
                "field_confidence": {},
            },
        )


class ExactWarningPrefixOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "GOVERNMENT WARNING: noisy OCR body with enough evidence that the statutory "
            "prefix is printed in uppercase",
            0.75,
        )


class TitleCaseWarningVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=10,
            extracted={
                "brand_name": "OLD TOM DISTILLERY",
                "class_type": "Bourbon",
                "alcohol_content": "45% Alc./Vol.",
                "net_contents": "750 mL",
                "government_warning": CANONICAL_GOVERNMENT_WARNING.replace(
                    "GOVERNMENT WARNING:", "Government Warning:"
                ),
                "warning_prefix_bold": True,
                "image_quality": "clear",
                "field_confidence": {},
            },
        )


class JaldaWarningOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "GOVERNMENT WARNING:\n"
            "(1) According to the Surgeon General,\n"
            "women should not drink alcoholic beverages during pregnancy because\n"
            "of the risk of birth defects.\n"
            "(2) Consumption of alcoholic beverages impairs your ability to drive a car or\n"
            "\u2018operate machinery, and may cause health problems.\n"
            "RUM\n"
            "80 PROOF\n"
            "750 mL",
            0.82,
        )


class JaldaVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=10,
            extracted={
                "brand_name": "JAIDA",
                "class_type": "RUM",
                "alcohol_content": "80 PROOF",
                "net_contents": "750 mL",
                "government_warning": (
                    "(1) According to the Surgeon General, women should not drink alcoholic "
                    "beverages during pregnancy because of the risk of birth defects. "
                    "(2) Consumption of alcohol beverages impairs your ability to drive a car "
                    "or operate machinery, and may cause health problems."
                ),
                "warning_prefix_bold": True,
                "image_quality": "clear",
                "raw_text": (
                    "JAIDA RUM 80 PROOF 750 mL "
                    "(1) According to the Surgeon General, women should not drink alcoholic "
                    "beverages during pregnancy because of the risk of birth defects. "
                    "(2) Consumption of alcohol beverages impairs your ability to drive a car "
                    "or operate machinery, and may cause health problems."
                ),
                "field_confidence": {},
            },
        )


def test_high_confidence_ocr_match_with_exact_warning_can_pass_without_vision() -> None:
    pipeline = VerificationPipeline(ocr=MatchingOcrProvider(), vision=PassingVisionProvider())

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    assert [event.layer.value for event in result.events] == ["rules", "ocr"]
    assert result.events[1].rationale == "All required fields match"
    assert result.provider_usage == []


def test_high_confidence_ocr_numeric_mismatch_skips_vision_provider() -> None:
    pipeline = VerificationPipeline(
        ocr=NetContentsMismatchOcrProvider(),
        vision=UnexpectedVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="Barenjager",
            class_type="Honey Liqueur",
            alcohol_content="35%",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.FAIL
    assert [event.layer.value for event in result.events] == ["rules", "ocr"]
    assert result.provider_usage == []
    net_contents = next(
        field for field in result.events[-1].field_results if field.field_name == "net_contents"
    )
    assert net_contents.extracted_value == "50ML"


def test_high_confidence_ocr_textual_mismatch_escalates_to_vision_provider() -> None:
    pipeline = VerificationPipeline(
        ocr=TextualMismatchOcrProvider(),
        vision=PassingVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    assert [event.layer.value for event in result.events] == ["rules", "ocr", "vision"]
    assert result.provider_usage[0].provider == "fake"


def test_low_confidence_ocr_still_escalates_to_vision_provider() -> None:
    pipeline = VerificationPipeline(
        ocr=LowConfidenceMatchingOcrProvider(),
        vision=PassingVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    assert [event.layer.value for event in result.events] == ["rules", "ocr", "vision"]
    assert result.provider_usage[0].provider == "fake"


def test_low_confidence_ocr_beer_text_supports_vision_style_match() -> None:
    pipeline = VerificationPipeline(
        ocr=LowConfidenceBeerTextOcrProvider(),
        vision=BeerStyleVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="Ironwood Brewing Co.",
            class_type="Beer",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 fl oz",
            fanciful_name="India Pale Ale",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    vision_event = result.events[-1]
    class_type = next(
        field for field in vision_event.field_results if field.field_name == "class_type"
    )
    assert class_type.rationale == "Beer class matched by exact Beer text"


def test_provider_failure_routes_to_human_review() -> None:
    pipeline = VerificationPipeline(ocr=EmptyOcrProvider(), vision=NoopVisionProvider())

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.NEEDS_REVIEW
    assert [event.layer.value for event in result.events] == [
        "rules",
        "ocr",
        "vision",
        "human_review",
    ]
    assert result.events[0].evidence["confidence_assessment"]["is_calibrated"] is False
    assert result.events[1].evidence["confidence_assessment"]["out_of_distribution_flags"] == [
        "low_ocr_confidence"
    ]
    assert {field.field_name for field in result.events[1].field_results} == {
        "brand_name",
        "class_type",
        "alcohol_content",
        "net_contents",
        "government_warning",
    }
    assert all(field.verdict.value == "missing" for field in result.events[1].field_results)
    assert result.provider_usage[0].provider == "noop"


def test_provider_failure_keeps_low_confidence_ocr_field_evidence() -> None:
    pipeline = VerificationPipeline(
        ocr=LowConfidenceMatchingOcrProvider(),
        vision=NoopVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.NEEDS_REVIEW
    assert [event.layer.value for event in result.events] == [
        "rules",
        "ocr",
        "vision",
        "human_review",
    ]
    ocr_event = result.events[1]
    assert ocr_event.rationale == "OCR confidence below threshold"
    brand = next(field for field in ocr_event.field_results if field.field_name == "brand_name")
    assert brand.verdict.value == "match"
    assert brand.extracted_value == "OLD TOM DISTILLERY"


def test_ocr_uppercase_prefix_evidence_corrects_vision_warning_case_artifact() -> None:
    pipeline = VerificationPipeline(
        ocr=ExactWarningPrefixOcrProvider(),
        vision=TitleCaseWarningVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    vision_event = next(event for event in result.events if event.layer.value == "vision")
    warning = next(
        field for field in vision_event.field_results if field.field_name == "government_warning"
    )
    assert warning.extracted_value is not None
    assert warning.extracted_value.startswith("GOVERNMENT WARNING:")


def test_ocr_raw_warning_evidence_and_near_brand_read_route_to_review() -> None:
    pipeline = VerificationPipeline(
        ocr=JaldaWarningOcrProvider(),
        vision=JaldaVisionProvider(),
    )

    result = pipeline.verify(
        Path("missing.png"),
        ApplicationFields(
            brand_name="JALDA",
            class_type="Rum",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.NEEDS_REVIEW
    assert [event.layer.value for event in result.events] == [
        "rules",
        "ocr",
        "vision",
        "human_review",
    ]
    vision_event = next(event for event in result.events if event.layer.value == "vision")
    brand = next(field for field in vision_event.field_results if field.field_name == "brand_name")
    warning = next(
        field for field in vision_event.field_results if field.field_name == "government_warning"
    )
    assert brand.verdict.value == "uncertain"
    assert warning.verdict.value == "match"
    assert warning.extracted_value is not None
    assert warning.extracted_value.startswith("GOVERNMENT WARNING:")


def test_degraded_local_image_quality_overrides_vision_pass(tmp_path: Path) -> None:
    image_path = tmp_path / "low-contrast-label.png"
    image = Image.new("RGB", (640, 360), "#777777")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 320), outline="#858585", width=4)
    draw.text((80, 80), "OLD TOM DISTILLERY", fill="#8a8a8a")
    draw.text((80, 130), "Bourbon", fill="#8a8a8a")
    draw.text((80, 180), "45% Alc./Vol.", fill="#8a8a8a")
    draw.text((80, 230), "750 mL", fill="#8a8a8a")
    image.save(image_path)

    pipeline = VerificationPipeline(ocr=EmptyOcrProvider(), vision=PassingVisionProvider())

    result = pipeline.verify(
        image_path,
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.NEEDS_REVIEW
    image_quality_event = next(
        event for event in result.events if event.layer.value == "image_quality"
    )
    assert image_quality_event.decision == MachineDecision.NEEDS_REVIEW
    assert "low contrast" in image_quality_event.rationale
    assert result.events[-1].layer.value == "human_review"
    assert "low contrast" in result.events[-1].rationale
    assert "Verify label legibility before approval" in result.events[-1].rationale
    assert "low contrast" in result.events[-1].evidence["quality_findings"]


def test_bright_decorative_local_quality_flags_do_not_override_vision_pass(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "bright-decorative-label.png"
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 610, 330), outline="#111111", width=4)
    draw.rectangle((80, 50, 560, 130), fill="#008c92")
    draw.rectangle((80, 220, 560, 305), fill="#d62d6c")
    draw.text((120, 80), "FATHERS & SONS", fill="white")
    draw.text((120, 160), "WHITE RUM", fill="#008c92")
    draw.text((120, 245), "750 ML 40% ALC/VOL", fill="white")
    draw.text((500, 40), "GOVERNMENT WARNING:", fill="#111111")
    image = image.rotate(
        7,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor="white",
    )
    image.save(image_path)

    pipeline = VerificationPipeline(ocr=EmptyOcrProvider(), vision=PassingVisionProvider())

    result = pipeline.verify(
        image_path,
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.PASS
    assert [event.layer.value for event in result.events] == [
        "rules",
        "ocr",
        "image_quality",
        "vision",
    ]
    image_quality_event = next(
        event for event in result.events if event.layer.value == "image_quality"
    )
    assert image_quality_event.decision == MachineDecision.NEEDS_REVIEW
    flags = image_quality_event.evidence["confidence_assessment"]["out_of_distribution_flags"]
    assert "local_glare" in flags
    assert "local_border_crop_or_damage" in flags
    assert "local_skew" in flags
    assert "local_low_contrast" not in flags
    assert "local_blur" not in flags


def test_degraded_local_image_quality_allows_clear_vision_mismatch_to_fail(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "skewed-label.png"
    image = Image.new("RGB", (640, 360), "#777777")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 320), outline="#858585", width=4)
    draw.text((80, 80), "MB Liquors", fill="#8a8a8a")
    draw.text((80, 130), "Vodka", fill="#8a8a8a")
    draw.text((80, 180), "40% Alc./Vol.", fill="#8a8a8a")
    draw.text((80, 230), "750 mL", fill="#8a8a8a")
    image.save(image_path)
    pipeline = VerificationPipeline(ocr=EmptyOcrProvider(), vision=FailingVisionProvider())

    result = pipeline.verify(
        image_path,
        ApplicationFields(
            brand_name="MB Liquors",
            class_type="Kentucky Straight Bourbon Whiskey",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
    )

    assert result.recommendation == MachineDecision.FAIL
    assert [event.layer.value for event in result.events] == [
        "rules",
        "ocr",
        "image_quality",
        "vision",
    ]
    vision_event = result.events[-1]
    assert vision_event.decision == MachineDecision.FAIL
    class_type_result = next(
        field for field in vision_event.field_results if field.field_name == "class_type"
    )
    assert class_type_result.verdict.value == "mismatch"
