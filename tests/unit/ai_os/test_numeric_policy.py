"""A non-finite number must not be able to reach a score or a response.

The failure these guard against is specifically fail-open: CPython's min/max
cannot order NaN, so `min(10.0, nan)` returns 10.0 and a clamp written to bound
a value instead awards it the maximum.  Each test below is the regression for
that direction of failure, not merely for "no exception".
"""

import json
import math

import pytest

from src.ai_os.numeric_policy import (
    NonFiniteNumberError,
    clamp_finite,
    finite_or,
    round_finite,
    strict_json_loads,
)

NAN = float("nan")
INF = float("inf")


def test_clamp_maps_nan_to_the_default_not_the_upper_bound():
    # The bug: min(10.0, nan) is 10.0, so a "bound" would award the maximum.
    assert clamp_finite(NAN, -10.0, 10.0, 0.0) == 0.0
    assert clamp_finite(NAN, 0.0, 100.0, 50.0) == 50.0


def test_clamp_still_bounds_ordinary_values():
    assert clamp_finite(250, 0.0, 100.0, 50.0) == 100.0
    assert clamp_finite(-5, 0.0, 100.0, 50.0) == 0.0
    assert clamp_finite(42, 0.0, 100.0, 50.0) == 42.0


def test_clamp_handles_infinities_and_junk():
    assert clamp_finite(INF, 0.0, 100.0, 50.0) == 50.0
    assert clamp_finite(-INF, 0.0, 100.0, 50.0) == 50.0
    assert clamp_finite(None, 0.0, 100.0, 50.0) == 50.0
    assert clamp_finite("not a number", 0.0, 100.0, 50.0) == 50.0


def test_finite_or_falls_back_for_non_finite():
    assert finite_or(NAN, 7.0) == 7.0
    assert finite_or(INF, 7.0) == 7.0
    assert finite_or(3.5, 7.0) == 3.5


def test_round_finite_never_emits_a_non_finite_number():
    assert round_finite(NAN, 1, 0.0) == 0.0
    assert round_finite(1.234, 1) == 1.2
    # This is the property the API depends on.
    json.dumps({"score": round_finite(NAN, 1, 0.0)}, allow_nan=False)


def test_strict_json_loads_rejects_the_bare_nan_literal():
    # Plain json.loads accepts this; the strict loader must not.
    assert math.isnan(json.loads('[{"score": NaN}]')[0]["score"])
    with pytest.raises((NonFiniteNumberError, ValueError)):
        strict_json_loads('[{"score": NaN}]')


def test_strict_json_loads_rejects_infinity():
    for literal in ("Infinity", "-Infinity"):
        with pytest.raises((NonFiniteNumberError, ValueError)):
            strict_json_loads(f'[{{"score": {literal}}}]')


def test_strict_json_loads_accepts_ordinary_documents():
    assert strict_json_loads('[{"score": 1.5}]') == [{"score": 1.5}]
