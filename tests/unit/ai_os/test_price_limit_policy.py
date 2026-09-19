"""Price-limit bands and the flat-session regression.

Two failures are pinned here: a hardcoded 10%/20% band that ignores ST and
北交所, and a `float(a or b or 0)` chain that read a genuine 0.0% session as
missing and substituted a stored bar of unknown date.
"""

import pytest

from src.ai_os.price_limit_policy import (
    at_limit_down,
    at_limit_up,
    price_limit_pct,
    resolve_change_pct,
)

TRADE_DATE = "2026-09-18"


@pytest.mark.parametrize(
    ("code", "is_st", "expected"),
    [
        ("600519.SH", False, 10.0),
        ("000001.SZ", False, 10.0),
        ("002594.SZ", False, 10.0),
        ("300750.SZ", False, 20.0),
        ("301058.SZ", False, 20.0),
        ("688981.SH", False, 20.0),
        ("689009.SH", False, 20.0),
        ("830799.BJ", False, 30.0),
        ("920001.BJ", False, 30.0),
        # ST halves the main board band but not the growth boards'.
        ("600519.SH", True, 5.0),
        ("000001.SZ", True, 5.0),
        ("300750.SZ", True, 20.0),
        ("688981.SH", True, 20.0),
    ],
)
def test_price_limit_band_by_board_and_st(code, is_st, expected):
    assert price_limit_pct(code, is_st=is_st) == expected


def test_band_is_computed_from_the_code_body_not_the_suffix():
    assert price_limit_pct("300750.SZ") == price_limit_pct("300750.SH")


def test_a_flat_session_is_not_treated_as_a_missing_value():
    """0.0 is a real observation; `or` chaining dropped it."""
    decision = {"market_change_pct": 0.0}
    stored = {"trade_date": TRADE_DATE, "change_pct": -10.0}

    # The old chain returned -10.0 here and could skip a stop-loss.
    assert resolve_change_pct(decision, stored, TRADE_DATE) == 0.0


def test_a_stale_stored_bar_is_not_used():
    stale = {"trade_date": "2026-08-01", "change_pct": -10.0}

    assert resolve_change_pct({}, stale, TRADE_DATE) == 0.0


def test_a_same_day_stored_bar_is_used():
    stored = {"trade_date": TRADE_DATE, "change_pct": -8.5}

    assert resolve_change_pct({}, stored, TRADE_DATE) == -8.5


def test_non_finite_change_is_not_propagated():
    assert resolve_change_pct({"market_change_pct": float("nan")}, {}, TRADE_DATE) == 0.0


def test_limit_helpers_match_the_previous_inline_comparisons():
    # These are the exact comparisons the call sites used before.
    assert at_limit_up(9.9, 10.0) is True
    assert at_limit_up(9.7, 10.0) is False
    assert at_limit_down(-9.9, 10.0) is True
    assert at_limit_down(-9.7, 10.0) is False
    assert at_limit_up(19.9, 20.0) is True
    assert at_limit_down(-4.9, 5.0) is True


def test_an_st_limit_down_now_blocks_a_sell_that_used_to_pass():
    """The regression the hardcoded 10% band caused for ST names."""
    at_st_limit_down = -5.0
    assert at_limit_down(at_st_limit_down, price_limit_pct("600519.SH", is_st=True))
    # With the old hardcoded 10% band this was False, so the fill went through
    # at a price below the limit-down -- unattainable in the real market.
    assert not at_limit_down(at_st_limit_down, 10.0)
