import pytest

from backend.app.application_metadata import contains_us_state

STATE_NAMES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]


@pytest.mark.parametrize(("abbreviation", "state_name"), STATE_NAMES)
def test_contains_us_state_accepts_all_state_abbreviations_and_full_names(
    abbreviation: str,
    state_name: str,
) -> None:
    dotted = ".".join(abbreviation) + "."

    assert contains_us_state(f"Responsible Party, Example City, {abbreviation}")
    assert contains_us_state(f"Responsible Party, Example City, {abbreviation}.")
    assert contains_us_state(f"Responsible Party, Example City, {dotted}")
    assert contains_us_state(f"Responsible Party, Example City, {dotted}, USA")
    assert contains_us_state(f"Responsible Party, Example City, {state_name}")


@pytest.mark.parametrize(
    "value",
    [
        "Responsible Party, San Juan, PR",
        "Responsible Party, San Juan, P.R.",
        "Responsible Party, St. Thomas, VI",
        "Responsible Party, St. Thomas, V.I.",
        "Responsible Party, Hagatna, GU",
        "Responsible Party, Hagatna, G.U.",
        "Responsible Party, San Juan, Puerto Rico",
        "Responsible Party, St. Thomas, Virgin Islands",
        "Responsible Party, Hagatna, Guam",
    ],
)
def test_contains_us_state_accepts_supported_territories(value: str) -> None:
    assert contains_us_state(value)
