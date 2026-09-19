"""Numeric guards for values that arrive from models and providers.

Two Python behaviours make an unguarded clamp fail *open*:

* ``json.loads`` accepts the bare literals ``NaN``, ``Infinity`` and
  ``-Infinity`` unless ``parse_constant`` rejects them.
* ``min``/``max`` do not order NaN -- every comparison against it is false --
  so ``min(10.0, nan)`` returns ``10.0``.  A clamp written to bound a value
  instead promotes a non-finite one to the top of its range, which is the
  opposite of the intent.

Score entry points therefore need to check finiteness *before* clamping, and
model output needs to be parsed strictly.  Use these helpers rather than
re-deriving the check at each call site.
"""

from __future__ import annotations

import json
import math
from typing import Any


class NonFiniteNumberError(ValueError):
    """A JSON document contained ``NaN`` or an ``Infinity`` literal."""


def _reject_constant(name: str) -> Any:
    raise NonFiniteNumberError(f"non-finite JSON constant: {name}")


def finite_or(value: Any, default: float) -> float:
    """Return ``value`` as a finite float, or ``default``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp_finite(value: Any, low: float, high: float, default: float) -> float:
    """Clamp a value into ``[low, high]``, mapping non-finite input to default.

    The finiteness check must come first: ``min``/``max`` cannot bound NaN.
    """
    number = finite_or(value, default)
    return max(low, min(high, number))


def round_finite(value: Any, ndigits: int, default: float = 0.0) -> float:
    """Round for serialization without ever emitting NaN or Infinity."""
    return round(finite_or(value, default), ndigits)


def strict_json_loads(text: str) -> Any:
    """``json.loads`` that rejects NaN and Infinity instead of accepting them."""
    return json.loads(text, parse_constant=_reject_constant)
