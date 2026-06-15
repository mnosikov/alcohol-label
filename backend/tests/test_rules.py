from backend.app.pipeline.rules import compare_application_to_extraction, normalize_text
from backend.app.pipeline.types import (
    CANONICAL_GOVERNMENT_WARNING,
    ApplicationFields,
    ExtractedFields,
    FieldVerdict,
    LayerName,
    MachineDecision,
)


def test_canonical_government_warning_has_exact_required_prefix() -> None:
    assert CANONICAL_GOVERNMENT_WARNING.startswith("GOVERNMENT WARNING:")
    assert "Government Warning:" not in CANONICAL_GOVERNMENT_WARNING


def test_machine_decision_values_are_submission_facing() -> None:
    assert MachineDecision.PASS.value == "PASS"
    assert MachineDecision.FAIL.value == "FAIL"
    assert MachineDecision.NEEDS_REVIEW.value == "NEEDS_REVIEW"


def test_normalize_text_removes_case_punctuation_noise() -> None:
    assert normalize_text("STONE'S   THROW!") == "stone s throw"


def test_normalize_text_folds_diacritics_for_transcription_variants() -> None:
    assert normalize_text("Bärenjäger") == "barenjager"


def test_brand_punctuation_and_case_variants_match() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Stone's Throw",
            class_type="IPA",
            alcohol_content="6.5% Alc./Vol.",
            net_contents="12 fl oz",
        ),
        ExtractedFields(
            brand_name="STONE'S THROW",
            class_type="India Pale Ale",
            alcohol_content="6.5% ALC./VOL.",
            net_contents="12 FL OZ",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.OCR,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MATCH
    assert outcome.evidence["confidence_assessment"]["calibrated_confidence"] is None
    assert outcome.evidence["source_references"][0]["kind"] == "label_artifact"


def test_brand_diacritic_variant_matches_plain_application_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Barenjager",
            class_type="Honey Liqueur",
            alcohol_content="35%",
            net_contents="50 mL",
        ),
        ExtractedFields(
            brand_name="Bärenjäger",
            class_type="Honey Liqueur",
            alcohol_content="35% Alc. by Vol.",
            net_contents="50ML",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MATCH


def test_warning_title_case_without_verified_prefix_routes_to_fail() -> None:
    warning = CANONICAL_GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.OCR,
    )

    assert outcome.decision == MachineDecision.FAIL


def test_all_caps_warning_body_matches_when_prefix_is_verified() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING.upper(),
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    warning = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_all_caps_warning_body_with_missing_required_comma_fails() -> None:
    warning = CANONICAL_GOVERNMENT_WARNING.upper().replace("MACHINERY, AND", "MACHINERY AND")

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Brouwerij 'Tij",
            class_type="Beer",
            alcohol_content="6.5%",
            net_contents="20 Liter",
            fanciful_name="India Pale Ale",
        ),
        ExtractedFields(
            brand_name="BROUWERIJ 'T IJ",
            class_type="India Pale Ale",
            alcohol_content="6.5% ALC/VOL.",
            net_contents="20 LITER",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MISMATCH
    assert outcome.decision == MachineDecision.FAIL


def test_warning_clause_markers_without_opening_parentheses_require_review() -> None:
    warning = CANONICAL_GOVERNMENT_WARNING.upper().replace("(1)", "1)").replace("(2)", "2)")

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Liba Spirits",
            class_type="Gin",
            alcohol_content="45%",
            net_contents="1 liter",
            fanciful_name="Departure Gin",
        ),
        ExtractedFields(
            brand_name="LIBA SPIRITS",
            class_type="Departure GIN",
            alcohol_content="90 PROOF 45% ALC./VOL.",
            net_contents="1 LITER",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.UNCERTAIN
    assert outcome.decision == MachineDecision.NEEDS_REVIEW


def test_warning_matches_when_full_warning_is_present_in_raw_label_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Paradox Brewery",
            class_type="Ale",
            alcohol_content="5.5%",
            net_contents="16 fl oz",
        ),
        ExtractedFields(
            brand_name="Paradox Brewery",
            class_type="Ale",
            alcohol_content="5.5%",
            net_contents="16 fl oz",
            government_warning=None,
            raw_text=f"PARADOX BREWERY 5.5% ALC/VOL ALE 16 FL OZ {CANONICAL_GOVERNMENT_WARNING}",
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_warning_match_extracted_value_stops_at_statutory_warning() -> None:
    warning = (
        f"{CANONICAL_GOVERNMENT_WARNING} Distilled by LIST DISTILLERY LLC. "
        "VODKA ALC. 40% BY VOL. 80 PROOF 750 mL."
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Vodka",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="VODKA",
            alcohol_content="40%",
            net_contents="750 mL",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.OCR,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert warning_result.extracted_value == CANONICAL_GOVERNMENT_WARNING


def test_warning_match_trims_trailing_text_when_ocr_terminal_period_is_comma() -> None:
    warning = (
        f"{CANONICAL_GOVERNMENT_WARNING.replace('health problems.', 'health problems,')} "
        "Distilled by LIST DISTILLERY LLC. FOR SALE ONLY IN PUERTO RICO."
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Vodka",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="VODKA",
            alcohol_content="40%",
            net_contents="750 mL",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.OCR,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert warning_result.extracted_value == CANONICAL_GOVERNMENT_WARNING


def test_warning_match_removes_ocr_quote_noise_inside_statutory_span() -> None:
    warning = (
        CANONICAL_GOVERNMENT_WARNING.replace("operate machinery", "\u2018operate machinery")
        + " Bottled by LATIN SHOTS, Inc."
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Rum",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="RUM",
            alcohol_content="80 PROOF",
            net_contents="750 mL",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert warning_result.extracted_value == CANONICAL_GOVERNMENT_WARNING


def test_warning_match_restores_verified_prefix_for_body_only_extraction() -> None:
    warning = CANONICAL_GOVERNMENT_WARNING.removeprefix("GOVERNMENT WARNING: ")

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Vodka",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="VODKA",
            alcohol_content="40%",
            net_contents="750 mL",
            government_warning=warning,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert warning_result.extracted_value == CANONICAL_GOVERNMENT_WARNING


def test_warning_matches_when_full_warning_appears_after_other_extracted_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Stillwater Artisanal",
            class_type="Ale",
            alcohol_content="6.8%",
            net_contents="5.17 gal",
        ),
        ExtractedFields(
            brand_name="Stillwater Artisanal",
            class_type="Ale",
            alcohol_content="6.8%",
            net_contents="5.17 gal. 5.4 gal. 10.8 gal. 15.5 gal.",
            government_warning=(
                "CAUTION: use a tapping system with pressure regulator. "
                f"{CANONICAL_GOVERNMENT_WARNING.upper()}"
            ),
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_warning_matches_when_dedicated_warning_field_misses_raw_text_warning() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Chateau Grand Traverse",
            class_type="Riesling",
            alcohol_content="12%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="Chateau Grand Traverse",
            class_type="Riesling",
            alcohol_content="12%",
            net_contents="750 mL",
            government_warning="Do not drink unless you are over the legal drinking age.",
            raw_text=f"CHATEAU GRAND TRAVERSE RIESLING 12% 750 ML {CANONICAL_GOVERNMENT_WARNING}",
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_warning_raw_text_candidate_does_not_display_whole_label_transcript() -> None:
    raw_text = (
        "ROM 184, Cey a & # ALL NATURAL HONEY Pochsoad aie bottled by TEUCKE & KONIG "
        "BARENFANGFABRIK 50ML IN RINTEEN RALCHTWL Barenjager HONEY LiQueUr "
        "MENT oneae 4) ACCORDING TO THE NOT DRINK ALCOHOLIC GOVERN SURGEON GENERAL, "
        "WOWE! BEVERAGES DURNG PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. "
        "i CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR "
        "OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS. IMPORTED BY SIDNEY FRANK"
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Barenjager",
            class_type="Honey Liqueur",
            alcohol_content="35%",
            net_contents="50mL",
        ),
        ExtractedFields(
            brand_name="Barenjager",
            class_type="HONEY LiQueUr",
            alcohol_content=None,
            net_contents="50ML",
            government_warning=None,
            raw_text=raw_text,
        ),
        source_layer=LayerName.OCR,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MISSING
    assert warning_result.extracted_value is None


def test_warning_spacing_artifacts_do_not_create_punctuation_failure() -> None:
    warning = (
        CANONICAL_GOVERNMENT_WARNING.upper()
        .replace(": (1)", ":(1)")
        .replace(
            ", WOMEN",
            ",WOMEN",
        )
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="RED DOG",
            class_type="Beer",
            alcohol_content="5.5%",
            net_contents="16 oz",
        ),
        ExtractedFields(
            brand_name="RED DOG",
            class_type="Beer",
            alcohol_content="5.5%",
            net_contents="16oz",
            government_warning=warning,
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_all_caps_warning_with_matching_body_passes_without_bold_evidence() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Fathers & Sons",
            class_type="RUM",
            alcohol_content="40%",
            net_contents="750 ML",
        ),
        ExtractedFields(
            brand_name="FATHERS",
            class_type="WHITE RUM",
            alcohol_content="40% ALC/VOL",
            net_contents="750 ML",
            government_warning=CANONICAL_GOVERNMENT_WARNING.upper(),
            warning_prefix_bold=None,
            image_quality="clear",
        ),
        source_layer=LayerName.VISION,
    )

    warning_result = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning_result.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_warning_body_matches_when_prefix_is_verified_separately() -> None:
    warning_body = CANONICAL_GOVERNMENT_WARNING.removeprefix("GOVERNMENT WARNING: ").strip()

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=warning_body,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    assert outcome.decision == MachineDecision.PASS


def test_beer_class_matches_when_exact_beer_word_appears_in_raw_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ironwood Brewing Co.",
            class_type="Beer",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 fl oz",
            fanciful_name="India Pale Ale",
        ),
        ExtractedFields(
            brand_name="Ironwood Brewing Co.",
            class_type="India Pale Ale",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 FL OZ",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text="IRONWOOD BREWING CO.\nINDIA PALE ALE\nBEER\n6.8% Alc./Vol.",
        ),
        source_layer=LayerName.VISION,
    )

    class_type = next(
        result for result in outcome.field_results if result.field_name == "class_type"
    )
    assert class_type.verdict == FieldVerdict.MATCH
    assert class_type.extracted_value == "Beer"
    assert outcome.decision == MachineDecision.PASS


def test_beer_class_with_style_only_routes_to_review() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ironwood Brewing Co.",
            class_type="Beer",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 fl oz",
            fanciful_name="India Pale Ale",
        ),
        ExtractedFields(
            brand_name="Ironwood Brewing Co.",
            class_type="India Pale Ale",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 FL OZ",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    class_type = next(
        result for result in outcome.field_results if result.field_name == "class_type"
    )
    assert class_type.verdict == FieldVerdict.UNCERTAIN
    assert outcome.decision == MachineDecision.NEEDS_REVIEW


def test_beer_class_with_known_style_only_routes_to_review() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ironwood Brewing Co.",
            class_type="Beer",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 fl oz",
        ),
        ExtractedFields(
            brand_name="Ironwood Brewing Co.",
            class_type="Pilsner",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 FL OZ",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    class_type = next(
        result for result in outcome.field_results if result.field_name == "class_type"
    )
    assert class_type.verdict == FieldVerdict.UNCERTAIN
    assert outcome.decision == MachineDecision.NEEDS_REVIEW


def test_brand_spacing_variant_matches_compact_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Brouwerij 'Tij",
            class_type="Beer",
            alcohol_content="6.5%",
            net_contents="20 Liter",
            fanciful_name="India Pale Ale",
        ),
        ExtractedFields(
            brand_name="BROUWERIJ 'T IJ",
            class_type="Beer",
            alcohol_content="6.5% ALC/VOL.",
            net_contents="20 LITER",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_brand_matches_when_claimed_text_is_present_in_raw_label_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Fat Bottom Brewing",
            class_type="IPA",
            alcohol_content="7%",
            net_contents="12 FL. OZ.",
            fanciful_name="Robot Lover",
        ),
        ExtractedFields(
            brand_name="TEDDY LOVES IPA",
            class_type="IPA",
            alcohol_content="7% ALC/VOL",
            net_contents="12 FL. OZ.",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text="TEDDY LOVES IPA FAT BOTTOM BREWING ROBOT LOVER IPA 7% ALC/VOL 12 FL. OZ.",
        ),
        source_layer=LayerName.VISION,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MATCH
    assert brand.extracted_value == "Fat Bottom Brewing"
    assert outcome.decision == MachineDecision.PASS


def test_brand_raw_text_match_ignores_responsible_party_only_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Crooked Orchard",
            class_type="Hard Apple Cider",
            alcohol_content="6.9% Alc./Vol.",
            net_contents="16 FL OZ (473 mL)",
            applicant_name_address="Crooked Orchard Cider Co., Burlington, VT",
            source_of_product="Domestic",
        ),
        ExtractedFields(
            brand_name="Bent Branch Cidery",
            class_type="Hard Apple Cider",
            alcohol_content="6.9% Alc./Vol.",
            net_contents="16 FL OZ (473 mL)",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text=(
                "BENT BRANCH CIDERY WINDFALL HARD APPLE CIDER 6.9% Alc./Vol. "
                "16 FL OZ (473 mL) BREWED & CANNED BY Crooked Orchard Cider Co., "
                "Burlington, VT"
            ),
        ),
        source_layer=LayerName.VISION,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MISMATCH
    assert outcome.decision == MachineDecision.FAIL


def test_brand_extracted_responsible_party_context_does_not_match() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Beauclair",
            class_type="VSOP Brandy",
            alcohol_content="40% Alc./Vol. (80 Proof)",
            net_contents="700 mL",
            applicant_name_address="Beauclair Distillers, New York, NY",
            source_of_product="Imported",
            country_of_origin="France",
        ),
        ExtractedFields(
            brand_name="Imported by Beauclair Distillers, New York, NY",
            class_type="VSOP Brandy",
            alcohol_content="40% Alc./Vol. (80 Proof)",
            net_contents="700 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text=(
                "BEAUCHAMP CELLAR VSOP Brandy 40% Alc./Vol. 700 mL "
                "Product of France Imported by Beauclair Distillers, New York, NY"
            ),
        ),
        source_layer=LayerName.OCR,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.MISMATCH
    assert outcome.decision == MachineDecision.FAIL


def test_class_type_matches_when_claimed_text_is_present_in_raw_label_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Paradox Brewery",
            class_type="Ale",
            alcohol_content="5.5%",
            net_contents="16 fl oz",
            fanciful_name="One Handed Applause",
        ),
        ExtractedFields(
            brand_name="Paradox Brewery",
            class_type="New England Style IPA",
            alcohol_content="5.5%",
            net_contents="16 fl oz",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text="ONE HANDED APPLAUSE NEW ENGLAND STYLE IPA 5.5% ALC/VOL ALE 16 FL OZ",
        ),
        source_layer=LayerName.VISION,
    )

    class_type = next(
        result for result in outcome.field_results if result.field_name == "class_type"
    )
    assert class_type.verdict == FieldVerdict.MATCH
    assert class_type.extracted_value == "Ale"
    assert outcome.decision == MachineDecision.PASS


def test_responsible_party_and_import_origin_match_visible_label_text() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Porto da Lua",
            class_type="Port",
            alcohol_content="19.5%",
            net_contents="750 mL",
            applicant_name_address="Atlas Imports, Providence, RI",
            source_of_product="Imported",
            country_of_origin="Portugal",
        ),
        ExtractedFields(
            brand_name="Porto da Lua",
            class_type="Port",
            alcohol_content="19.5% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text=(
                "PORTO DA LUA PORT PRODUCT OF PORTUGAL 19.5% ALC./VOL. "
                "750 ML IMPORTED BY ATLAS IMPORTS PROVIDENCE RI"
            ),
        ),
        source_layer=LayerName.VISION,
    )

    rows = {result.field_name: result for result in outcome.field_results}
    assert rows["applicant_name_address"].verdict == FieldVerdict.MATCH
    assert rows["applicant_name_address"].confidence > 0
    assert rows["source_of_product"].verdict == FieldVerdict.MATCH
    assert rows["country_of_origin"].verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_responsible_party_state_matches_dotted_state_abbreviation() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Barenjager",
            class_type="Honey Liqueur",
            alcohol_content="35%",
            net_contents="50mL",
            applicant_name_address="Sidney Frank Importing CO., Inc. New Rochelle, NY",
            source_of_product="Imported",
            country_of_origin="Germany",
        ),
        ExtractedFields(
            brand_name="Bärenjäger",
            class_type="HONEY LIQUEUR",
            alcohol_content="35% ALC. BY VOL.",
            net_contents="50ML",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text=(
                "IMPORTED BY SIDNEY FRANK IMPORTING CO., INC. "
                "NEW ROCHELLE, N.Y. PRODUCED AND BOTTLED IN GERMANY"
            ),
        ),
        source_layer=LayerName.VISION,
    )

    responsible_party = next(
        result for result in outcome.field_results if result.field_name == "applicant_name_address"
    )
    assert responsible_party.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_missing_responsible_party_label_text_routes_to_fail() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Old Tom Distillery",
            class_type="Bourbon",
            alcohol_content="45%",
            net_contents="750 mL",
            applicant_name_address="Old Tom Distillery, Louisville, KY",
            source_of_product="Domestic",
        ),
        ExtractedFields(
            brand_name="Old Tom Distillery",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            raw_text=("OLD TOM DISTILLERY BOURBON 45% ALC./VOL. 750 ML BATCH NO. 14"),
        ),
        source_layer=LayerName.VISION,
    )

    responsible_party = next(
        result for result in outcome.field_results if result.field_name == "applicant_name_address"
    )
    assert responsible_party.verdict == FieldVerdict.MISSING
    assert responsible_party.confidence == 0.0
    assert outcome.decision == MachineDecision.FAIL


def test_alcohol_content_numeric_mismatch_routes_to_fail() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Hollow Creek Vineyards",
            class_type="Cabernet Sauvignon",
            alcohol_content="13.5% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="Hollow Creek Vineyards",
            class_type="Cabernet Sauvignon",
            alcohol_content="12.5% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    alcohol = next(
        result for result in outcome.field_results if result.field_name == "alcohol_content"
    )
    assert alcohol.verdict == FieldVerdict.MISMATCH
    assert outcome.decision == MachineDecision.FAIL


def test_alcohol_content_matches_decimal_comma_and_proof_equivalent() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Vodka",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="Vodka",
            alcohol_content="80 PROOF",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    alcohol = next(
        result for result in outcome.field_results if result.field_name == "alcohol_content"
    )
    assert alcohol.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS

    comma_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ortigao",
            class_type="Sparkling wine",
            alcohol_content="12.5%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="Ortigao",
            class_type="Sparkling wine",
            alcohol_content="12,5% vol",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    comma_alcohol = next(
        result for result in comma_outcome.field_results if result.field_name == "alcohol_content"
    )
    assert comma_alcohol.verdict == FieldVerdict.MATCH
    assert comma_outcome.decision == MachineDecision.PASS


def test_net_contents_matches_common_us_and_metric_equivalents() -> None:
    pint_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Paradox Brewery",
            class_type="IPA",
            alcohol_content="5.5%",
            net_contents="1 Pint (16 fl. oz.)",
        ),
        ExtractedFields(
            brand_name="Paradox Brewery",
            class_type="IPA",
            alcohol_content="5.5%",
            net_contents="16 Fl oz",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    pint_net = next(
        result for result in pint_outcome.field_results if result.field_name == "net_contents"
    )
    assert pint_net.verdict == FieldVerdict.MATCH
    assert pint_outcome.decision == MachineDecision.PASS

    centiliter_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ortigao",
            class_type="Sparkling wine",
            alcohol_content="12.5%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="Ortigao",
            class_type="Sparkling wine",
            alcohol_content="12.5%",
            net_contents="75cl",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    centiliter_net = next(
        result for result in centiliter_outcome.field_results if result.field_name == "net_contents"
    )
    assert centiliter_net.verdict == FieldVerdict.MATCH
    assert centiliter_outcome.decision == MachineDecision.PASS

    fluid_ounce_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Villainess",
            class_type="Imperial Stout",
            alcohol_content="9%",
            net_contents="12 fl oz",
        ),
        ExtractedFields(
            brand_name="Villainess",
            class_type="Imperial Stout",
            alcohol_content="9%",
            net_contents="12 FL. OZ.",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    fluid_ounce_net = next(
        result
        for result in fluid_ounce_outcome.field_results
        if result.field_name == "net_contents"
    )
    assert fluid_ounce_net.verdict == FieldVerdict.MATCH
    assert fluid_ounce_outcome.decision == MachineDecision.PASS

    compact_fl_oz_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Paradox Brewery",
            class_type="IPA",
            alcohol_content="5.5%",
            net_contents="1 Pint (16 fl. oz.)",
        ),
        ExtractedFields(
            brand_name="Paradox Brewery",
            class_type="IPA",
            alcohol_content="5.5%",
            net_contents="1 Pint (16 Fl.oz)",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    compact_fl_oz_net = next(
        result
        for result in compact_fl_oz_outcome.field_results
        if result.field_name == "net_contents"
    )
    assert compact_fl_oz_net.verdict == FieldVerdict.MATCH
    assert compact_fl_oz_outcome.decision == MachineDecision.PASS

    multiple_options_outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Stillwater Artisanal",
            class_type="Ale",
            alcohol_content="6.8%",
            net_contents="5.17 gal",
        ),
        ExtractedFields(
            brand_name="Stillwater Artisanal",
            class_type="Ale",
            alcohol_content="6.8%",
            net_contents="5.17 gal. 5.4 gal. 10.8 gal. 15.5 gal.",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    multiple_options_net = next(
        result
        for result in multiple_options_outcome.field_results
        if result.field_name == "net_contents"
    )
    assert multiple_options_net.verdict == FieldVerdict.MATCH
    assert multiple_options_outcome.decision == MachineDecision.PASS


def test_ipa_abbreviation_matches_india_pale_ale_class_type() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Brouwerij 't IJ",
            class_type="IPA",
            alcohol_content="6.5%",
            net_contents="20 LITER",
        ),
        ExtractedFields(
            brand_name="Brouwerij 't IJ",
            class_type="India Pale Ale",
            alcohol_content="6.5%",
            net_contents="20 LITER",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
        ),
        source_layer=LayerName.VISION,
    )

    class_type = next(
        result for result in outcome.field_results if result.field_name == "class_type"
    )
    assert class_type.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_exact_warning_prefix_and_body_pass_without_bold_evidence() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=None,
        ),
        source_layer=LayerName.VISION,
    )

    assert outcome.decision == MachineDecision.PASS


def test_near_brand_read_routes_to_review_instead_of_hard_fail() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Rum",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JAIDA",
            class_type="RUM",
            alcohol_content="80 PROOF",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            image_quality="clear",
        ),
        source_layer=LayerName.VISION,
    )

    brand = next(result for result in outcome.field_results if result.field_name == "brand_name")
    assert brand.verdict == FieldVerdict.UNCERTAIN
    assert outcome.decision == MachineDecision.NEEDS_REVIEW


def test_warning_body_ignores_stray_ocr_quote_noise_without_ignoring_commas() -> None:
    warning_with_ocr_quote = CANONICAL_GOVERNMENT_WARNING.replace(
        "operate machinery",
        "\u2018operate machinery",
    )

    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="JALDA",
            class_type="Rum",
            alcohol_content="40%",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="JALDA",
            class_type="RUM",
            alcohol_content="80 PROOF",
            net_contents="750 mL",
            government_warning=warning_with_ocr_quote,
            warning_prefix_bold=True,
            image_quality="clear",
        ),
        source_layer=LayerName.VISION,
    )

    warning = next(
        result for result in outcome.field_results if result.field_name == "government_warning"
    )
    assert warning.verdict == FieldVerdict.MATCH
    assert outcome.decision == MachineDecision.PASS


def test_poor_image_quality_routes_to_review_even_when_fields_match() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        ),
        ExtractedFields(
            brand_name="OLD TOM DISTILLERY",
            class_type="Bourbon",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            image_quality="poor",
        ),
        source_layer=LayerName.VISION,
    )

    assert outcome.decision == MachineDecision.NEEDS_REVIEW
    confidence = outcome.evidence["confidence_assessment"]
    assert "poor_image_quality" in confidence["out_of_distribution_flags"]


def test_degraded_image_quality_allows_explicit_field_mismatch_to_fail() -> None:
    outcome = compare_application_to_extraction(
        ApplicationFields(
            brand_name="Ironwood Brewing Co.",
            class_type="India Pale Ale",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="12 FL OZ (355 mL)",
        ),
        ExtractedFields(
            brand_name="Ironwood Brewing Co.",
            class_type="India Pale Ale",
            alcohol_content="6.8% Alc./Vol.",
            net_contents="11 FL OZ (325 mL)",
            government_warning=CANONICAL_GOVERNMENT_WARNING,
            warning_prefix_bold=True,
            image_quality="blurry scan with glare",
        ),
        source_layer=LayerName.VISION,
    )

    assert outcome.decision == MachineDecision.FAIL
    net_contents = next(
        result for result in outcome.field_results if result.field_name == "net_contents"
    )
    assert net_contents.verdict.value == "mismatch"
    confidence = outcome.evidence["confidence_assessment"]
    assert confidence["raw_score"] == 0.95
