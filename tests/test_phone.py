"""
Phone normalisation.

Farmers write their own number several ways. Every one of these must reach the
same account, or a farmer who typed it differently on a new device is locked
out of their own records.
"""

import pytest

from apps.accounts.phone import InvalidPhoneNumber, mask, normalise, to_e164


@pytest.mark.parametrize(
    "written",
    [
        "08034129087",
        "8034129087",
        "+2348034129087",
        "2348034129087",
        "0803 412 9087",
        "0803-412-9087",
        " 0803 412 9087 ",
    ],
)
def test_every_way_a_farmer_writes_it_reaches_one_number(written):
    assert to_e164(written) == "+2348034129087"


@pytest.mark.parametrize("prefix", ["70", "80", "81", "90", "91"])
def test_accepts_the_nigerian_mobile_prefixes(prefix):
    assert normalise(f"0{prefix}12345678") == f"{prefix}12345678"


@pytest.mark.parametrize(
    "bad",
    [
        "0123456789012",  # too long
        "080341290",  # too short
        "01234567890",  # landline prefix
        "",
        "not a number",
    ],
)
def test_rejects_what_cannot_be_a_mobile_number(bad):
    with pytest.raises(InvalidPhoneNumber):
        normalise(bad)


def test_mask_shows_only_the_last_four():
    assert mask("+2348034129087") == "+234 ••• ••• 9087"
