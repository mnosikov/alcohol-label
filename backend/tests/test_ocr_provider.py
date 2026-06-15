from pathlib import Path

from PIL import Image

from backend.app.pipeline.ocr import OcrProvider, TesseractOcrProvider, parse_ocr_text
from backend.app.pipeline.types import ApplicationFields


class FakeOcrProvider(OcrProvider):
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return (
            "OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n45% Alc./Vol.\n750 mL\n"
            "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
            "alcoholic beverages during pregnancy because of the risk of birth defects. "
            "(2) Consumption of alcoholic beverages impairs your ability to drive a car or operate "
            "machinery, and may cause health problems.",
            0.91,
        )


def test_parse_ocr_text_extracts_obvious_fields() -> None:
    text, confidence = FakeOcrProvider().extract_text(Path("label.png"))

    extracted = parse_ocr_text(text, confidence)

    assert extracted.brand_name == "OLD TOM DISTILLERY"
    assert extracted.alcohol_content == "45% Alc./Vol."
    assert extracted.net_contents == "750 mL"
    assert extracted.government_warning is not None
    assert extracted.field_confidence["ocr_text"] == 0.91


def test_parse_ocr_text_uses_application_context_for_nonlinear_labels() -> None:
    text = (
        "ORIGINAL RECIPE FROM 18th CENTURY GERMANY\n"
        "Bärenjäger\n"
        "HONEY LIQUEUR\n"
        "ALL NATURAL HONEY\n"
        "50ML\n"
        "35% ALC. BY VOL.\n"
        "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT "
        "DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH "
        "DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO "
        "DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
    )

    extracted = parse_ocr_text(
        text,
        0.93,
        application=ApplicationFields(
            brand_name="Barenjager",
            class_type="Honey Liqueur",
            alcohol_content="35%",
            net_contents="750 mL",
        ),
    )

    assert extracted.brand_name == "Bärenjäger"
    assert extracted.class_type == "HONEY LIQUEUR"
    assert extracted.alcohol_content == "35% ALC. BY VOL."
    assert extracted.net_contents == "50ML"
    assert extracted.government_warning is not None
    assert extracted.government_warning.startswith("GOVERNMENT WARNING:")
    assert extracted.warning_prefix_bold is None


def test_parse_ocr_text_extracts_title_case_warning_for_casing_verdict() -> None:
    text = (
        "OLD TOM DISTILLERY\n"
        "Kentucky Straight Bourbon Whiskey\n"
        "45% Alc./Vol. (90 Proof)\n"
        "750 mL\n"
        "Government Warning: (1) According to the Surgeon General, women should not drink "
        "alcoholic beverages during pregnancy because of the risk of birth defects. "
        "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
        "operate machinery, and may cause health problems."
    )

    extracted = parse_ocr_text(text, 0.92)

    assert extracted.government_warning is not None
    assert extracted.government_warning.startswith("Government Warning:")


def test_tesseract_provider_uses_token_confidence(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "label.png"
    Image.new("RGB", (200, 100), "#ffffff").save(image_path)

    def fake_image_to_data(*args, **kwargs) -> dict:
        return {
            "block_num": [1, 1, 1],
            "par_num": [1, 1, 1],
            "line_num": [1, 1, 2],
            "text": ["OLD", "TOM", ""],
            "conf": ["96", "88", "-1"],
        }

    monkeypatch.setattr("backend.app.pipeline.ocr.pytesseract.image_to_data", fake_image_to_data)

    text, confidence = TesseractOcrProvider().extract_text(image_path)

    assert text == "OLD TOM"
    assert confidence == 0.92
