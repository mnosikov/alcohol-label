import re
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

import pytesseract
from PIL import Image
from rapidfuzz import fuzz

from backend.app.pipeline.rules import normalize_text
from backend.app.pipeline.types import (
    CANONICAL_GOVERNMENT_WARNING,
    ApplicationFields,
    ExtractedFields,
)


class OcrProvider(Protocol):
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        pass


class TesseractOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        data = pytesseract.image_to_data(
            Image.open(image_path),
            output_type=pytesseract.Output.DICT,
        )
        return _text_and_confidence_from_tesseract_data(data)


class NoopOcrProvider:
    def extract_text(self, image_path: Path) -> tuple[str, float]:
        return "", 0.0


def parse_ocr_text(
    text: str,
    confidence: float,
    *,
    application: ApplicationFields | None = None,
) -> ExtractedFields:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    alcohol = _first_alcohol_content(text)
    net = _first_net_contents(text)
    warning = _extract_warning(text)
    brand_name = lines[0] if lines else None
    class_type = lines[1] if len(lines) > 1 else None

    if application is not None:
        brand_name = _best_matching_line(lines, application.brand_name) or brand_name
        class_type = _best_matching_line(lines, application.class_type) or class_type
        alcohol = _best_alcohol_content(text, application.alcohol_content) or alcohol
        net = _best_net_contents(text, application.net_contents) or net

    return ExtractedFields(
        brand_name=brand_name,
        class_type=class_type,
        alcohol_content=alcohol,
        net_contents=net,
        government_warning=warning,
        warning_prefix_bold=None,
        raw_text=text,
        field_confidence={"ocr_text": confidence},
    )


def _extract_warning(text: str) -> str | None:
    warning_match = re.search(r"government\s+warning\s*:", text, flags=re.I)
    if warning_match is None:
        return None
    warning_candidate = " ".join(text[warning_match.start() :].split())
    if warning_candidate.startswith(CANONICAL_GOVERNMENT_WARNING):
        return CANONICAL_GOVERNMENT_WARNING
    return warning_candidate


def _text_and_confidence_from_tesseract_data(data: dict) -> tuple[str, float]:
    line_words: OrderedDict[tuple[int, int, int], list[str]] = OrderedDict()
    confidences: list[float] = []
    count = len(data.get("text", []))
    for index in range(count):
        token = str(data["text"][index]).strip()
        if not token:
            continue

        key = (
            int(data.get("block_num", [0] * count)[index]),
            int(data.get("par_num", [0] * count)[index]),
            int(data.get("line_num", [index] * count)[index]),
        )
        line_words.setdefault(key, []).append(token)

        try:
            confidence = float(data.get("conf", ["-1"] * count)[index])
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            confidences.append(confidence)

    text = "\n".join(" ".join(words) for words in line_words.values()).strip()
    if not text:
        return "", 0.0
    if not confidences:
        return text, 0.5
    return text, round(sum(confidences) / len(confidences) / 100, 2)


def _best_matching_line(lines: list[str], expected: str) -> str | None:
    expected_normalized = normalize_text(expected)
    if not expected_normalized:
        return None
    best_line = None
    best_score = 0
    for line in lines:
        normalized_line = normalize_text(line)
        score = int(fuzz.token_set_ratio(expected_normalized, normalized_line))
        if score > best_score:
            best_line = line
            best_score = score
    return best_line if best_score >= 88 else None


def _first_alcohol_content(text: str) -> str | None:
    match = _ALCOHOL_PATTERN.search(text)
    return match.group(0).strip() if match else None


def _best_alcohol_content(text: str, expected: str) -> str | None:
    expected_percent = _first_percent(expected)
    matches = list(_ALCOHOL_PATTERN.finditer(text))
    if not matches:
        return None
    if expected_percent is not None:
        for match in matches:
            if _first_percent(match.group(0)) == expected_percent:
                return match.group(0).strip()
    return matches[0].group(0).strip()


def _first_percent(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\b(\d{1,2}(?:\.\d+)?)\s*%", value)
    return round(float(match.group(1)), 2) if match else None


def _first_net_contents(text: str) -> str | None:
    match = _NET_CONTENTS_PATTERN.search(text)
    return match.group(0).strip() if match else None


def _best_net_contents(text: str, expected: str) -> str | None:
    expected_quantities = {_quantity(match) for match in _NET_CONTENTS_PATTERN.finditer(expected)}
    matches = list(_NET_CONTENTS_PATTERN.finditer(text))
    if not matches:
        return None
    if expected_quantities:
        for match in matches:
            if _quantity(match) in expected_quantities:
                return match.group(0).strip()
    return matches[0].group(0).strip()


_NET_CONTENTS_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|ml|mL|l|L)\b", re.I)
_ALCOHOL_PATTERN = re.compile(
    r"\b\d{1,2}(?:\.\d+)?\s*%\s*(?:Alc\.?\s*(?:/|by)?\s*Vol\.?|ABV)?",
    re.I,
)


def _quantity(match: re.Match[str]) -> tuple[str, float]:
    value = match.group(0)
    quantity = re.match(r"\b(\d+(?:\.\d+)?)\s*(fl\s*oz|oz|ml|mL|l|L)\b", value, re.I)
    if quantity is None:
        return ("", 0.0)
    amount = float(quantity.group(1))
    unit = normalize_text(quantity.group(2))
    if unit == "l":
        amount *= 1000
        unit = "ml"
    if unit == "oz":
        unit = "fl oz"
    return (unit, round(amount, 2))
