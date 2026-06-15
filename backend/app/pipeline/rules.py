import re
import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz

from backend.app.application_metadata import (
    COUNTRY_OF_ORIGIN_FIELD,
    DOMESTIC_PRODUCT_ORIGIN,
    IMPORTED_PRODUCT_ORIGIN,
    PRODUCT_ORIGIN_FIELD,
    RESPONSIBLE_PARTY_FIELD,
)
from backend.app.pipeline.evidence import LABEL_APPLICATION_SOURCES, confidence_evidence
from backend.app.pipeline.types import (
    CANONICAL_GOVERNMENT_WARNING,
    ApplicationFields,
    ExtractedFields,
    FieldResult,
    FieldVerdict,
    LayerName,
    LayerOutcome,
    MachineDecision,
)


def _comparison_evidence(
    *,
    raw_score: float | None,
    calibration_context: str,
    out_of_distribution_flags: list[str] | None = None,
) -> dict:
    return {
        **confidence_evidence(
            raw_score=raw_score,
            calibrated_confidence=None,
            calibration_context=calibration_context,
            out_of_distribution_flags=out_of_distribution_flags,
        ),
        "claim_type": "field_comparison",
        "source_references": LABEL_APPLICATION_SOURCES,
    }


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    normalized = re.sub(r"[^a-z0-9.%/]+", " ", folded)
    return re.sub(r"\s+", " ", normalized).strip()


def _compact_normalized_text(value: str | None) -> str:
    return normalize_text(value).replace(" ", "")


def _normalized_contains(haystack: str | None, needle: str | None) -> bool:
    normalized_needle = normalize_text(needle)
    if not normalized_needle:
        return False
    normalized_haystack = normalize_text(haystack)
    return f" {normalized_needle} " in f" {normalized_haystack} "


def _has_normalized_token(value: str | None, token: str) -> bool:
    return token in set(normalize_text(value).split())


def _ratio(expected: str, extracted: str) -> int:
    return int(fuzz.token_set_ratio(normalize_text(expected), normalize_text(extracted)))


_QUALITY_REVIEW_TERMS = {
    "poor",
    "low",
    "low quality",
    "blurry",
    "blurred",
    "unreadable",
    "glare",
    "shadow",
    "skew",
    "skewed",
    "crop",
    "cropped",
    "partial crop",
    "damaged",
    "damage",
    "worn",
    "faded",
    "low contrast",
    "washed out",
    "distorted",
    "obscured",
}


def _quality_requires_review(image_quality: str | None) -> bool:
    if not image_quality:
        return False
    normalized = normalize_text(image_quality)
    tokens = set(normalized.split())
    return any(
        term in normalized if " " in term else term in tokens for term in _QUALITY_REVIEW_TERMS
    )


def _first_percent(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace(",", ".")
    match = re.search(r"\b(\d{1,2}(?:\.\d+)?)\s*%", normalized)
    return float(match.group(1)) if match else None


def _proof_value(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\b(\d{1,3}(?:[.,]\d+)?)\s*proof\b", value, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _alcohol_percent_values(value: str | None) -> set[float]:
    values: set[float] = set()
    percent = _first_percent(value)
    if percent is not None:
        values.add(round(percent, 2))
    proof = _proof_value(value)
    if proof is not None:
        values.add(round(proof / 2, 2))
    return values


def _quantities(value: str | None) -> set[tuple[str, float]]:
    if not value:
        return set()
    normalized = value.replace(",", ".")
    matches = re.finditer(
        r"\b(\d+(?:\.\d+)?)\s*(fl\.?\s*oz\.?|oz\.?|ml|mL|cl|cL|l|L|liter|litre|gal\.?|gallon|pint)\b",
        normalized,
        re.I,
    )
    quantities: set[tuple[str, float]] = set()
    for match in matches:
        amount = float(match.group(1))
        unit = normalize_text(match.group(2))
        unit = unit.replace(".", "")
        if unit in {"liter", "litre"}:
            unit = "l"
        if unit == "l":
            amount *= 1000
            unit = "ml"
        if unit == "cl":
            amount *= 10
            unit = "ml"
        if unit in {"oz", "floz"}:
            unit = "fl oz"
        if unit == "pint":
            amount *= 16
            unit = "fl oz"
        if unit in {"gal", "gallon"}:
            amount *= 128
            unit = "fl oz"
        quantities.add((unit, round(amount, 2)))
    return quantities


def _strict_numeric_result(
    field_name: str,
    expected: str,
    extracted: str | None,
    source_layer: LayerName,
    *,
    expected_values: Iterable[float] | set[tuple[str, float]],
    extracted_values: Iterable[float] | set[tuple[str, float]],
    rationale_label: str,
    fuzzy_threshold: int,
) -> FieldResult:
    if not extracted:
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=None,
            verdict=FieldVerdict.MISSING,
            confidence=0.0,
            rationale="No extracted value",
            source_layer=source_layer,
        )

    expected_set = set(expected_values)
    extracted_set = set(extracted_values)
    if expected_set or extracted_set:
        verdict = (
            FieldVerdict.MATCH
            if expected_set and extracted_set and bool(expected_set & extracted_set)
            else FieldVerdict.MISMATCH
        )
        confidence = 1.0 if verdict == FieldVerdict.MATCH else 0.0
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=extracted,
            verdict=verdict,
            confidence=confidence,
            rationale=(
                f"{rationale_label} match"
                if verdict == FieldVerdict.MATCH
                else f"{rationale_label} mismatch"
            ),
            source_layer=source_layer,
        )

    return _field_result(field_name, expected, extracted, source_layer, fuzzy_threshold)


def _alcohol_content_result(
    expected: str, extracted: str | None, source_layer: LayerName
) -> FieldResult:
    return _strict_numeric_result(
        "alcohol_content",
        expected,
        extracted,
        source_layer,
        expected_values=_alcohol_percent_values(expected),
        extracted_values=_alcohol_percent_values(extracted),
        rationale_label="Alcohol percentage",
        fuzzy_threshold=88,
    )


def _net_contents_result(
    expected: str, extracted: str | None, source_layer: LayerName
) -> FieldResult:
    return _strict_numeric_result(
        "net_contents",
        expected,
        extracted,
        source_layer,
        expected_values=_quantities(expected),
        extracted_values=_quantities(extracted),
        rationale_label="Net contents quantity",
        fuzzy_threshold=88,
    )


_WARNING_STATUTORY_SPAN_RE = re.compile(
    r"government\s+warning\s*:\s*"
    r"\(\s*1\s*\)\s*according\s+to\s+the\s+surgeon\s+general,\s*"
    r"women\s+should\s+not\s+drink\s+alcoholic\s+beverages\s+during\s+pregnancy\s+"
    r"because\s+of\s+the\s+risk\s+of\s+birth\s+defects\.\s*"
    r"\(\s*2\s*\)\s*consumption\s+of\s+alcoholic\s+beverages\s+impairs\s+"
    r"your\s+ability\s+to\s+drive\s+a\s+car\s+or\s+"
    r"[\u2018\u2019\u201c\u201d`´\"']*\s*operate\s+machinery,\s*"
    r"and\s+may\s+cause\s+health\s+problems[\.,]",
    re.I,
)


def _normalize_warning_clause_markers(value: str) -> str:
    return re.sub(r"\(\s*([12])\s*\)", r"(\1)", value)


def _normalize_warning_clause_markers_permissive(value: str) -> str:
    return re.sub(r"(?<!\d)\(?\s*([12])\s*\)", r"(\1)", value)


def _canonical_warning_body(value: str) -> str:
    body = re.sub(r"^government warning:\s*", "", value, count=1, flags=re.I).strip()
    body = _normalize_warning_clause_markers(body)
    body = body.removeprefix("(1)").strip()
    return re.sub(r"\s+", " ", body)


def _compact_warning_text(value: str) -> str:
    without_ocr_quote_noise = re.sub(r"[\u2018\u2019\u201c\u201d`´]", "", value)
    normalized_clause_markers = _normalize_warning_clause_markers(without_ocr_quote_noise)
    return re.sub(r"\s+", "", normalized_clause_markers).casefold()


def _statutory_warning_span(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value).strip()
    match = _WARNING_STATUTORY_SPAN_RE.search(normalized)
    if match is None:
        return None

    span = normalized[match.start() : match.end()]
    span = re.sub(r"[\u2018\u2019\u201c\u201d`´\"']", "", span)
    return f"{span[:-1]}." if span.endswith(",") else span


def _warning_display_value(value: str, *, warning_prefix_bold: bool | None = None) -> str:
    statutory_span = _statutory_warning_span(value)
    if statutory_span:
        return statutory_span
    if warning_prefix_bold is True and _warning_body_matches(value):
        return CANONICAL_GOVERNMENT_WARNING
    return value


def _warning_body_matches(extracted_warning: str) -> bool:
    comparison_warning = _statutory_warning_span(extracted_warning) or extracted_warning
    extracted_body = _compact_warning_text(_canonical_warning_body(comparison_warning))
    canonical_body = _compact_warning_text(_canonical_warning_body(CANONICAL_GOVERNMENT_WARNING))
    return extracted_body.startswith(canonical_body)


def _warning_body_has_incomplete_clause_marker_evidence(extracted_warning: str) -> bool:
    permissive_warning = _normalize_warning_clause_markers_permissive(extracted_warning)
    if permissive_warning == extracted_warning:
        return False

    extracted_body = _compact_warning_text(_canonical_warning_body(permissive_warning))
    canonical_body = _compact_warning_text(_canonical_warning_body(CANONICAL_GOVERNMENT_WARNING))
    return extracted_body.startswith(canonical_body)


def _warning_from_raw_text(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    warning_match = re.search(r"government\s+warning\s*:", raw_text, flags=re.I)
    if warning_match is None:
        return None
    warning_fragment = " ".join(raw_text[warning_match.start() :].split())
    return _statutory_warning_span(warning_fragment) or warning_fragment


def _warning_candidates(extracted: ExtractedFields) -> list[str]:
    candidates: list[str] = []
    if extracted.government_warning:
        normalized_warning = " ".join(extracted.government_warning.split())
        candidates.append(normalized_warning)
        warning_fragment = _warning_from_raw_text(extracted.government_warning)
        if warning_fragment and warning_fragment not in candidates:
            candidates.append(warning_fragment)
    if extracted.raw_text:
        warning_fragment = _warning_from_raw_text(extracted.raw_text)
        if warning_fragment and warning_fragment not in candidates:
            candidates.append(warning_fragment)
    return candidates


def _evaluate_warning_candidate(
    warning: str, *, warning_prefix_bold: bool | None
) -> tuple[FieldVerdict, float, str]:
    normalized_warning = re.sub(r"\s+", " ", warning).strip()
    has_warning_prefix = re.match(r"^government warning:", normalized_warning, re.I) is not None
    has_exact_prefix = normalized_warning.startswith("GOVERNMENT WARNING:")
    body_matches = _warning_body_matches(normalized_warning)
    if normalized_warning == CANONICAL_GOVERNMENT_WARNING:
        verdict = FieldVerdict.MATCH
        confidence = 1.0
        rationale = "Exact statutory warning text comparison"
    elif has_warning_prefix and not has_exact_prefix:
        verdict = FieldVerdict.MISMATCH
        confidence = 0.0
        rationale = "Warning prefix casing does not match statutory text"
    elif has_exact_prefix and body_matches:
        verdict = FieldVerdict.MATCH
        confidence = 0.98
        rationale = "Warning prefix matches and body text matches ignoring capitalization"
    elif warning_prefix_bold is True and body_matches:
        verdict = FieldVerdict.MATCH
        confidence = 0.95
        rationale = "Warning body matches and uppercase prefix was verified separately"
    elif body_matches:
        verdict = FieldVerdict.UNCERTAIN
        confidence = 0.5
        rationale = "Warning body matches but prefix evidence is incomplete"
    elif has_exact_prefix and _warning_body_has_incomplete_clause_marker_evidence(
        normalized_warning
    ):
        verdict = FieldVerdict.UNCERTAIN
        confidence = 0.55
        rationale = (
            "Warning text is canonical except required clause-marker punctuation is uncertain"
        )
    else:
        verdict = FieldVerdict.MISMATCH
        confidence = 0.0
        rationale = "Exact statutory warning text comparison"

    return verdict, confidence, rationale


def _warning_result(extracted: ExtractedFields, source_layer: LayerName) -> FieldResult:
    candidates = _warning_candidates(extracted)
    if not candidates:
        return FieldResult(
            field_name="government_warning",
            expected_value=CANONICAL_GOVERNMENT_WARNING,
            extracted_value=None,
            verdict=FieldVerdict.MISSING,
            confidence=0.0,
            rationale="No extracted government warning",
            source_layer=source_layer,
        )

    fallback: tuple[str, FieldVerdict, float, str] | None = None
    fallback_priority = -1
    for warning in candidates:
        verdict, confidence, rationale = _evaluate_warning_candidate(
            warning, warning_prefix_bold=extracted.warning_prefix_bold
        )
        if verdict == FieldVerdict.MATCH:
            return FieldResult(
                field_name="government_warning",
                expected_value=CANONICAL_GOVERNMENT_WARNING,
                extracted_value=_warning_display_value(
                    warning, warning_prefix_bold=extracted.warning_prefix_bold
                ),
                verdict=verdict,
                confidence=confidence,
                rationale=rationale,
                source_layer=source_layer,
            )
        priority = 2 if verdict == FieldVerdict.MISMATCH else 1
        if priority > fallback_priority:
            fallback = (warning, verdict, confidence, rationale)
            fallback_priority = priority

    warning, verdict, confidence, rationale = fallback or (
        candidates[0],
        FieldVerdict.MISMATCH,
        0.0,
        "Exact statutory warning text comparison",
    )
    return FieldResult(
        field_name="government_warning",
        expected_value=CANONICAL_GOVERNMENT_WARNING,
        extracted_value=_warning_display_value(
            warning, warning_prefix_bold=extracted.warning_prefix_bold
        ),
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        source_layer=source_layer,
    )


def _warning_prefix_requirement_satisfied(extracted: ExtractedFields) -> bool:
    if extracted.warning_prefix_bold is True:
        return True
    return any(
        candidate.startswith("GOVERNMENT WARNING:") and _warning_body_matches(candidate)
        for candidate in _warning_candidates(extracted)
    )


def _field_result(
    field_name: str,
    expected: str,
    extracted: str | None,
    source_layer: LayerName,
    fuzzy_threshold: int = 90,
    near_review_threshold: int | None = None,
) -> FieldResult:
    if not extracted:
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=None,
            verdict=FieldVerdict.MISSING,
            confidence=0.0,
            rationale="No extracted value",
            source_layer=source_layer,
        )
    if _compact_normalized_text(expected) == _compact_normalized_text(extracted):
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=extracted,
            verdict=FieldVerdict.MATCH,
            confidence=0.98,
            rationale="Compact text match",
            source_layer=source_layer,
        )
    score = _ratio(expected, extracted)
    if score >= fuzzy_threshold:
        verdict = FieldVerdict.MATCH
        rationale = f"Fuzzy score {score}"
    elif near_review_threshold is not None and score >= near_review_threshold:
        verdict = FieldVerdict.UNCERTAIN
        rationale = f"Near text match requires review (fuzzy score {score})"
    else:
        verdict = FieldVerdict.MISMATCH
        rationale = f"Fuzzy score {score}"
    return FieldResult(
        field_name=field_name,
        expected_value=expected,
        extracted_value=extracted,
        verdict=verdict,
        confidence=score / 100,
        rationale=rationale,
        source_layer=source_layer,
    )


def _raw_text_field_result(
    field_name: str,
    expected: str,
    extracted: str | None,
    raw_text: str | None,
    source_layer: LayerName,
    *,
    fuzzy_threshold: int = 90,
    near_review_threshold: int | None = None,
) -> FieldResult:
    result = _field_result(
        field_name,
        expected,
        extracted,
        source_layer,
        fuzzy_threshold=fuzzy_threshold,
        near_review_threshold=near_review_threshold,
    )
    if result.verdict != FieldVerdict.MATCH and _normalized_contains(raw_text, expected):
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=expected,
            verdict=FieldVerdict.MATCH,
            confidence=0.95,
            rationale="Claimed text present in whole-label text",
            source_layer=source_layer,
        )
    return result


_BRAND_RESPONSIBLE_CONTEXT_PHRASES = {
    "bottled by",
    "brewed by",
    "brewed and canned by",
    "brewed canned by",
    "canned by",
    "cellared by",
    "distilled by",
    "distributed by",
    "imported by",
    "manufactured by",
    "packed by",
    "prepared by",
    "produced by",
    "vinted by",
}


def _has_responsible_party_context(value: str | None) -> bool:
    normalized = normalize_text(value)
    return any(phrase in normalized for phrase in _BRAND_RESPONSIBLE_CONTEXT_PHRASES)


def _brand_occurrence_has_responsible_context(preceding_text: str) -> bool:
    preceding_tokens = preceding_text.split()[-6:]
    preceding_window = " ".join(preceding_tokens)
    return any(phrase in preceding_window for phrase in _BRAND_RESPONSIBLE_CONTEXT_PHRASES)


def _raw_text_has_brand_outside_responsible_context(
    raw_text: str | None, expected: str | None
) -> bool:
    normalized_expected = normalize_text(expected)
    if not normalized_expected:
        return False
    normalized_raw_text = normalize_text(raw_text)
    pattern = re.compile(rf"(?<!\S){re.escape(normalized_expected)}(?!\S)")
    for match in pattern.finditer(normalized_raw_text):
        if not _brand_occurrence_has_responsible_context(normalized_raw_text[: match.start()]):
            return True
    return False


def _brand_result(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
) -> FieldResult:
    direct_result = _field_result(
        "brand_name",
        application.brand_name,
        extracted.brand_name,
        source_layer,
        near_review_threshold=80,
    )
    if (
        direct_result.verdict == FieldVerdict.MATCH
        and extracted.brand_name
        and _has_responsible_party_context(extracted.brand_name)
    ):
        direct_result = FieldResult(
            field_name="brand_name",
            expected_value=application.brand_name,
            extracted_value=extracted.brand_name,
            verdict=FieldVerdict.MISMATCH,
            confidence=0.0,
            rationale="Brand appears only in responsible-party context",
            source_layer=source_layer,
        )

    brand_visible_outside_responsible_context = _raw_text_has_brand_outside_responsible_context(
        extracted.raw_text, application.brand_name
    )
    if direct_result.verdict != FieldVerdict.MATCH and brand_visible_outside_responsible_context:
        return FieldResult(
            field_name="brand_name",
            expected_value=application.brand_name,
            extracted_value=application.brand_name,
            verdict=FieldVerdict.MATCH,
            confidence=0.95,
            rationale="Brand text present outside responsible-party context",
            source_layer=source_layer,
        )
    return direct_result


_STATE_NAME_BY_ABBREVIATION = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "dc": "district of columbia",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "pr": "puerto rico",
    "vi": "virgin islands",
    "gu": "guam",
}
_STATE_ABBREVIATION_BY_NAME = {
    state_name: abbreviation for abbreviation, state_name in _STATE_NAME_BY_ABBREVIATION.items()
}
_IMPORT_ORIGIN_TERMS = {
    "imported",
    "importer",
    "imports",
    "product of",
    "produced in",
}


def _component_is_visible(raw_text: str | None, component: str) -> bool:
    normalized_component = normalize_text(component)
    if not normalized_component:
        return False
    if _normalized_contains(raw_text, normalized_component):
        return True

    state_name = _STATE_NAME_BY_ABBREVIATION.get(normalized_component)
    if state_name:
        return _normalized_contains(raw_text, state_name) or _state_abbreviation_is_visible(
            raw_text, normalized_component
        )

    state_abbreviation = _STATE_ABBREVIATION_BY_NAME.get(normalized_component)
    if state_abbreviation:
        return _state_abbreviation_is_visible(raw_text, state_abbreviation)
    return False


def _state_abbreviation_is_visible(raw_text: str | None, state_abbreviation: str) -> bool:
    normalized_state = normalize_text(state_abbreviation).replace(".", "")
    if not normalized_state:
        return False
    tokens = {token.replace(".", "") for token in normalize_text(raw_text).split()}
    return normalized_state in tokens


def _responsible_party_components(expected: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[,;\n]+", expected) if part.strip()]
    if len(parts) > 1:
        return parts
    return [expected.strip()] if expected.strip() else []


def _visible_label_text_result(
    *,
    field_name: str,
    expected: str,
    raw_text: str | None,
    source_layer: LayerName,
    label: str,
    component_match: bool = False,
) -> FieldResult:
    if _normalized_contains(raw_text, expected):
        return FieldResult(
            field_name=field_name,
            expected_value=expected,
            extracted_value=expected,
            verdict=FieldVerdict.MATCH,
            confidence=0.95,
            rationale=f"{label} present in whole-label text",
            source_layer=source_layer,
        )

    components = _responsible_party_components(expected) if component_match else []
    if components:
        visible_components = [
            component for component in components if _component_is_visible(raw_text, component)
        ]
        if len(visible_components) == len(components):
            return FieldResult(
                field_name=field_name,
                expected_value=expected,
                extracted_value=expected,
                verdict=FieldVerdict.MATCH,
                confidence=0.9,
                rationale=f"{label} components found in whole-label text",
                source_layer=source_layer,
            )
        if visible_components:
            return FieldResult(
                field_name=field_name,
                expected_value=expected,
                extracted_value=", ".join(visible_components),
                verdict=FieldVerdict.MISSING,
                confidence=0.0,
                rationale=f"Only part of {label.lower()} was found in label text",
                source_layer=source_layer,
            )

    return FieldResult(
        field_name=field_name,
        expected_value=expected,
        extracted_value=None,
        verdict=FieldVerdict.MISSING,
        confidence=0.0,
        rationale=f"{label} not found in label text",
        source_layer=source_layer,
    )


def _responsible_party_result(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
) -> FieldResult | None:
    if not application.applicant_name_address:
        return None
    direct_result = _raw_text_field_result(
        RESPONSIBLE_PARTY_FIELD,
        application.applicant_name_address,
        None,
        extracted.raw_text,
        source_layer,
        near_review_threshold=80,
    )
    if direct_result.verdict == FieldVerdict.MATCH:
        return direct_result
    return _visible_label_text_result(
        field_name=RESPONSIBLE_PARTY_FIELD,
        expected=application.applicant_name_address,
        raw_text=extracted.raw_text,
        source_layer=source_layer,
        label="Responsible party",
        component_match=True,
    )


def _country_of_origin_result(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
) -> FieldResult | None:
    if not application.country_of_origin:
        return None
    return _visible_label_text_result(
        field_name=COUNTRY_OF_ORIGIN_FIELD,
        expected=application.country_of_origin,
        raw_text=extracted.raw_text,
        source_layer=source_layer,
        label="Country of origin",
    )


def _has_import_origin_evidence(raw_text: str | None) -> bool:
    normalized = normalize_text(raw_text)
    tokens = set(normalized.split())
    return any(
        term in normalized if " " in term else term in tokens for term in _IMPORT_ORIGIN_TERMS
    )


def _source_of_product_result(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
    *,
    responsible_party: FieldResult | None,
    country_of_origin: FieldResult | None,
) -> FieldResult | None:
    if not application.source_of_product:
        return None

    expected = application.source_of_product
    normalized_expected = normalize_text(expected)
    has_import_evidence = _has_import_origin_evidence(extracted.raw_text)
    country_matches = (
        country_of_origin is not None and country_of_origin.verdict == FieldVerdict.MATCH
    )
    responsible_party_matches = (
        responsible_party is not None and responsible_party.verdict == FieldVerdict.MATCH
    )

    if normalized_expected == normalize_text(IMPORTED_PRODUCT_ORIGIN):
        if country_matches:
            rationale = "Imported origin supported by country-of-origin label text"
        elif has_import_evidence:
            rationale = "Imported origin supported by import language on the label"
        else:
            return FieldResult(
                field_name=PRODUCT_ORIGIN_FIELD,
                expected_value=expected,
                extracted_value=None,
                verdict=FieldVerdict.MISSING,
                confidence=0.0,
                rationale="Imported origin not found in label text",
                source_layer=source_layer,
            )
        return FieldResult(
            field_name=PRODUCT_ORIGIN_FIELD,
            expected_value=expected,
            extracted_value=expected,
            verdict=FieldVerdict.MATCH,
            confidence=0.9,
            rationale=rationale,
            source_layer=source_layer,
        )

    if normalized_expected == normalize_text(DOMESTIC_PRODUCT_ORIGIN):
        if has_import_evidence:
            return FieldResult(
                field_name=PRODUCT_ORIGIN_FIELD,
                expected_value=expected,
                extracted_value=IMPORTED_PRODUCT_ORIGIN,
                verdict=FieldVerdict.MISMATCH,
                confidence=0.0,
                rationale="Import language conflicts with domestic product origin",
                source_layer=source_layer,
            )
        if responsible_party_matches:
            return FieldResult(
                field_name=PRODUCT_ORIGIN_FIELD,
                expected_value=expected,
                extracted_value=expected,
                verdict=FieldVerdict.MATCH,
                confidence=0.8,
                rationale=(
                    "Domestic origin supported by visible U.S. responsible party "
                    "and no import-origin evidence"
                ),
                source_layer=source_layer,
            )
        return FieldResult(
            field_name=PRODUCT_ORIGIN_FIELD,
            expected_value=expected,
            extracted_value=None,
            verdict=FieldVerdict.UNCERTAIN,
            confidence=0.4,
            rationale="Domestic origin requires visible responsible party evidence",
            source_layer=source_layer,
        )

    return FieldResult(
        field_name=PRODUCT_ORIGIN_FIELD,
        expected_value=expected,
        extracted_value=None,
        verdict=FieldVerdict.UNCERTAIN,
        confidence=0.0,
        rationale="Product origin is not Domestic or Imported",
        source_layer=source_layer,
    )


_BEER_STYLE_TERMS = {
    "ale",
    "beer",
    "bock",
    "brown ale",
    "dunkel",
    "gose",
    "india pale ale",
    "ipa",
    "kolsch",
    "lager",
    "malt beverage",
    "pale ale",
    "pilsner",
    "porter",
    "saison",
    "stout",
    "wheat beer",
    "witbier",
}

_CLASS_TYPE_ALIASES = {
    "ipa": {"india pale ale"},
    "india pale ale": {"ipa"},
}


def _class_type_alias_matches(expected: str, extracted: str | None) -> bool:
    normalized_expected = normalize_text(expected)
    normalized_extracted = normalize_text(extracted)
    return normalized_extracted in _CLASS_TYPE_ALIASES.get(normalized_expected, set())


def _class_type_result(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
) -> FieldResult:
    result = _field_result(
        "class_type",
        application.class_type,
        extracted.class_type,
        source_layer,
        fuzzy_threshold=75,
    )
    if result.verdict != FieldVerdict.MISMATCH:
        return result

    if _class_type_alias_matches(application.class_type, extracted.class_type):
        return FieldResult(
            field_name="class_type",
            expected_value=application.class_type,
            extracted_value=extracted.class_type,
            verdict=FieldVerdict.MATCH,
            confidence=0.95,
            rationale="Class/type abbreviation alias match",
            source_layer=source_layer,
        )

    expected = normalize_text(application.class_type)
    extracted_value = normalize_text(extracted.class_type)
    fanciful_name = normalize_text(application.fanciful_name)
    if expected == "beer" and extracted_value:
        if _has_normalized_token(extracted.class_type, "beer") or _has_normalized_token(
            extracted.raw_text, "beer"
        ):
            matched_value = (
                extracted.class_type
                if _has_normalized_token(extracted.class_type, "beer")
                else application.class_type
            )
            return FieldResult(
                field_name="class_type",
                expected_value=application.class_type,
                extracted_value=matched_value,
                verdict=FieldVerdict.MATCH,
                confidence=0.95,
                rationale="Beer class matched by exact Beer text",
                source_layer=source_layer,
            )
        if extracted_value in _BEER_STYLE_TERMS or (
            fanciful_name and extracted_value == fanciful_name
        ):
            return FieldResult(
                field_name="class_type",
                expected_value=application.class_type,
                extracted_value=extracted.class_type,
                verdict=FieldVerdict.UNCERTAIN,
                confidence=0.5,
                rationale=(
                    "Beer style evidence requires review because exact Beer text was not extracted"
                ),
                source_layer=source_layer,
            )

    if _normalized_contains(extracted.raw_text, application.class_type):
        return FieldResult(
            field_name="class_type",
            expected_value=application.class_type,
            extracted_value=application.class_type,
            verdict=FieldVerdict.MATCH,
            confidence=0.95,
            rationale="Claimed text present in whole-label text",
            source_layer=source_layer,
        )

    return result


def compare_application_to_extraction(
    application: ApplicationFields,
    extracted: ExtractedFields,
    source_layer: LayerName,
) -> LayerOutcome:
    results = [
        _brand_result(application, extracted, source_layer),
        _class_type_result(application, extracted, source_layer),
        _alcohol_content_result(
            application.alcohol_content,
            extracted.alcohol_content,
            source_layer,
        ),
        _net_contents_result(application.net_contents, extracted.net_contents, source_layer),
    ]

    results.append(_warning_result(extracted, source_layer))
    responsible_party = _responsible_party_result(application, extracted, source_layer)
    country_of_origin = _country_of_origin_result(application, extracted, source_layer)
    source_of_product = _source_of_product_result(
        application,
        extracted,
        source_layer,
        responsible_party=responsible_party,
        country_of_origin=country_of_origin,
    )
    for result in (responsible_party, source_of_product, country_of_origin):
        if result is not None:
            results.append(result)

    if any(result.verdict == FieldVerdict.MISMATCH for result in results):
        return LayerOutcome(
            layer=source_layer,
            decision=MachineDecision.FAIL,
            confidence=0.95,
            rationale="Required field mismatch",
            extracted=extracted,
            field_results=results,
            evidence=_comparison_evidence(
                raw_score=0.95,
                calibration_context=f"{source_layer.value}_required_field_rule_v1",
            ),
        )

    if _quality_requires_review(extracted.image_quality):
        return LayerOutcome(
            layer=source_layer,
            decision=MachineDecision.NEEDS_REVIEW,
            confidence=0.5,
            rationale="Image quality requires human review",
            extracted=extracted,
            field_results=results,
            evidence=_comparison_evidence(
                raw_score=0.5,
                calibration_context=f"{source_layer.value}_image_quality_rule_v1",
                out_of_distribution_flags=["poor_image_quality"],
            ),
        )

    if any(result.verdict == FieldVerdict.MISSING for result in results):
        return LayerOutcome(
            layer=source_layer,
            decision=MachineDecision.FAIL,
            confidence=0.95,
            rationale="Required field mismatch or missing",
            extracted=extracted,
            field_results=results,
            evidence=_comparison_evidence(
                raw_score=0.95,
                calibration_context=f"{source_layer.value}_required_field_rule_v1",
            ),
        )

    if any(result.verdict == FieldVerdict.UNCERTAIN for result in results):
        confidence = min(
            result.confidence for result in results if result.verdict == FieldVerdict.UNCERTAIN
        )
        return LayerOutcome(
            layer=source_layer,
            decision=MachineDecision.NEEDS_REVIEW,
            confidence=confidence,
            rationale="Field evidence requires human review",
            extracted=extracted,
            field_results=results,
            evidence=_comparison_evidence(
                raw_score=confidence,
                calibration_context=f"{source_layer.value}_uncertain_field_rule_v1",
                out_of_distribution_flags=["uncertain_field_evidence"],
            ),
        )

    if not _warning_prefix_requirement_satisfied(extracted):
        return LayerOutcome(
            layer=source_layer,
            decision=MachineDecision.NEEDS_REVIEW,
            confidence=0.55,
            rationale="Warning bold evidence is uncertain",
            extracted=extracted,
            field_results=results,
            evidence=_comparison_evidence(
                raw_score=0.55,
                calibration_context=f"{source_layer.value}_warning_bold_rule_v1",
                out_of_distribution_flags=["unverified_warning_boldness"],
            ),
        )

    confidence = min(result.confidence for result in results)
    return LayerOutcome(
        layer=source_layer,
        decision=MachineDecision.PASS,
        confidence=confidence,
        rationale="All required fields match",
        extracted=extracted,
        field_results=results,
        evidence=_comparison_evidence(
            raw_score=confidence,
            calibration_context=f"{source_layer.value}_field_match_rule_v1",
        ),
    )
