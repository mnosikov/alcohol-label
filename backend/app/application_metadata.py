import re
from collections.abc import Mapping

RESPONSIBLE_PARTY_FIELD = "applicant_name_address"
PRODUCT_ORIGIN_FIELD = "source_of_product"
COUNTRY_OF_ORIGIN_FIELD = "country_of_origin"

DOMESTIC_PRODUCT_ORIGIN = "Domestic"
IMPORTED_PRODUCT_ORIGIN = "Imported"

_DOMESTIC_ALIASES = {
    "domestic",
    "us",
    "u s",
    "u.s.",
    "u.s",
    "usa",
    "u.s.a.",
    "united states",
    "united states of america",
}
_IMPORTED_ALIASES = {"import", "imported", "foreign"}

_US_STATE_ABBREVIATIONS = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "PR",
    "VI",
    "GU",
}
_US_STATE_NAMES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "district of columbia",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
    "puerto rico",
    "virgin islands",
    "guam",
}


class ApplicationMetadataError(ValueError):
    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.message = message


def normalize_and_validate_responsible_party_metadata(
    fields: Mapping[str, str | None],
) -> dict[str, str]:
    responsible_party = (fields.get(RESPONSIBLE_PARTY_FIELD) or "").strip()
    if not responsible_party:
        raise ApplicationMetadataError(RESPONSIBLE_PARTY_FIELD, "is required")
    if not contains_us_state(responsible_party):
        raise ApplicationMetadataError(
            RESPONSIBLE_PARTY_FIELD,
            "must include at least a U.S. state",
        )

    product_origin = normalize_product_origin(fields.get(PRODUCT_ORIGIN_FIELD))
    normalized = {
        RESPONSIBLE_PARTY_FIELD: responsible_party,
        PRODUCT_ORIGIN_FIELD: product_origin,
    }

    country_of_origin = (fields.get(COUNTRY_OF_ORIGIN_FIELD) or "").strip()
    if product_origin == IMPORTED_PRODUCT_ORIGIN and not country_of_origin:
        raise ApplicationMetadataError(
            COUNTRY_OF_ORIGIN_FIELD,
            "is required for imported products",
        )
    if country_of_origin:
        normalized[COUNTRY_OF_ORIGIN_FIELD] = country_of_origin

    return normalized


def normalize_product_origin(value: str | None) -> str:
    origin = (value or "").strip()
    if not origin:
        raise ApplicationMetadataError(PRODUCT_ORIGIN_FIELD, "is required")

    normalized = re.sub(r"[\s_-]+", " ", origin.lower()).strip()
    if normalized in _DOMESTIC_ALIASES:
        return DOMESTIC_PRODUCT_ORIGIN
    if normalized in _IMPORTED_ALIASES:
        return IMPORTED_PRODUCT_ORIGIN
    raise ApplicationMetadataError(
        PRODUCT_ORIGIN_FIELD,
        "must be Domestic or Imported",
    )


def contains_us_state(value: str) -> bool:
    upper_value = re.sub(
        r"(?<![A-Z])([A-Z])\.\s*([A-Z])\.(?![A-Z])",
        r"\1\2",
        value.upper(),
    )
    if any(
        match.group(0) in _US_STATE_ABBREVIATIONS
        for match in re.finditer(r"\b[A-Z]{2}\b", upper_value)
    ):
        return True

    lower_value = value.lower()
    return any(
        re.search(rf"\b{re.escape(state_name)}\b", lower_value)
        for state_name in _US_STATE_NAMES
    )
