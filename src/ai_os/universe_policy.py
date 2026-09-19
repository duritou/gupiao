"""Deterministic eligibility checks for the stock research universe.

The policy separates explicit risk exclusions from missing metadata.  An
unknown listing date or industry must be visible to callers, but it must not
be silently treated as proof that a stock is eligible.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_A_SHARE_CODE = re.compile(
    r"^(?:000|001|002|003|300|301|600|601|603|605|688|689)\d{3}\.(?:SH|SZ)$"
)
_ACTIVE_STATUSES = {"", "1", "active", "normal", "正常", "上市"}
_SUSPENDED_STATUSES = {
    "0", "suspended", "suspend", "停牌", "暂停上市", "halted"
}
_DELISTED_STATUSES = {"delisted", "退市", "terminated", "终止上市"}


@dataclass(frozen=True)
class UniversePolicyConfig:
    """Thresholds used by the live and scanner universe policy."""

    min_market_cap: float = 20.0
    min_avg_daily_amount_million: float = 50.0
    exclude_st: bool = True
    min_listing_days: int = 60
    max_industry_pct: float = 0.40


@dataclass(frozen=True)
class UniverseAssessment:
    """Point-in-time eligibility assessment for one stock."""

    stock_code: str
    status: str = "eligible"  # eligible / review_only / excluded
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    metadata_complete: bool = True
    industry: str = ""
    avg_daily_amount_million: float | None = None

    @property
    def excluded(self) -> bool:
        return self.status == "excluded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "metadata_complete": self.metadata_complete,
            "industry": self.industry,
            "avg_daily_amount_million": self.avg_daily_amount_million,
        }


@dataclass(frozen=True)
class IndustryConcentrationResult:
    """Result of applying a deterministic industry cap to a candidate set."""

    retained_codes: tuple[str, ...] = field(default_factory=tuple)
    excluded_codes: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    capped_industries: dict[str, int] = field(default_factory=dict)
    applied: bool = False


def config_from_settings(settings: Any) -> UniversePolicyConfig:
    """Build the policy from typed settings while tolerating old processes."""
    return UniversePolicyConfig(
        min_market_cap=max(
            0.0, float(getattr(settings, "SCANNER_MIN_MARKET_CAP", 20.0))
        ),
        min_avg_daily_amount_million=max(
            0.0, float(getattr(settings, "SCANNER_MIN_DAILY_VOLUME", 50.0))
        ),
        exclude_st=bool(getattr(settings, "SCANNER_EXCLUDE_ST", True)),
        min_listing_days=max(
            0, int(getattr(settings, "SCANNER_EXCLUDE_NEW_IPO_DAYS", 60))
        ),
        max_industry_pct=min(
            1.0, max(0.0, float(getattr(settings, "MAX_INDUSTRY_PCT", 0.40)))
        ),
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "st", "suspended", "停牌", "是"
    }


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _is_st(stock: dict[str, Any]) -> bool:
    if _as_bool(stock.get("is_st") or stock.get("isST")):
        return True
    name = str(stock.get("name") or stock.get("stock_name") or "").strip().upper()
    return bool(re.match(r"^\*?ST(?:$|[^A-Z])", name))


def _average_amount_million(stock: dict[str, Any]) -> float | None:
    for key in ("avg_daily_amount_million", "avg_amount_million"):
        value = _as_float(stock.get(key))
        if value is not None:
            return value
    # ScannerEngine's public contract uses million yuan for avg_amount.
    value = _as_float(stock.get("avg_amount"))
    if value is not None:
        return value
    # K-line providers disagree on whether ``amount`` is yuan, thousand yuan
    # or another unit.  Do not infer a liquidity threshold from an undeclared
    # unit; the live local-universe query supplies the explicit field above.
    return None


def assess_stock(
    stock: dict[str, Any],
    bars: Iterable[dict[str, Any]] | None = None,
    *,
    as_of_date: str = "",
    config: UniversePolicyConfig | None = None,
) -> UniverseAssessment:
    """Assess one stock without using future data or external state."""
    policy = config or UniversePolicyConfig()
    code = str(stock.get("code") or stock.get("stock_code") or "").strip().upper()
    reasons: list[str] = []
    metadata_complete = True
    reference_date = _parse_date(as_of_date) or date.today()
    industry = str(stock.get("industry") or "").strip()

    if not _A_SHARE_CODE.fullmatch(code):
        reasons.append("invalid_a_share_code")

    if policy.exclude_st and _is_st(stock):
        reasons.append("st_stock")

    status = str(stock.get("status") or "").strip().lower()
    if (
        _as_bool(stock.get("is_suspended") or stock.get("suspended"))
        or status in _SUSPENDED_STATUSES
    ):
        reasons.append("suspended")
    elif status in _DELISTED_STATUSES:
        reasons.append("delisted")

    list_date_text = str(stock.get("list_date") or stock.get("ipoDate") or "").strip()
    list_date = _parse_date(list_date_text)
    if list_date_text and list_date is None:
        metadata_complete = False
        reasons.append("listing_date_invalid")
    elif list_date is None:
        metadata_complete = False
        reasons.append("listing_date_missing")
    else:
        if list_date > reference_date:
            reasons.append("not_listed_on_date")
        elif (reference_date - list_date).days < policy.min_listing_days:
            reasons.append("new_ipo")

    delist_date = _parse_date(stock.get("delist_date") or stock.get("outDate"))
    if delist_date and delist_date <= reference_date:
        reasons.append("delisted")

    market_cap = _as_float(stock.get("market_cap"))
    if market_cap is not None and market_cap < policy.min_market_cap:
        reasons.append("market_cap_below_minimum")
    elif market_cap is None:
        metadata_complete = False
        reasons.append("market_cap_missing")

    avg_amount = _average_amount_million(stock)
    if avg_amount is None:
        metadata_complete = False
        reasons.append("liquidity_data_missing")
    elif avg_amount < policy.min_avg_daily_amount_million:
        reasons.append("insufficient_liquidity")

    latest_close = None
    for bar in list(bars or [])[-1:]:
        latest_close = _as_float(bar.get("close"))
    if latest_close is not None and latest_close <= 0:
        reasons.append("suspended")

    unique_reasons = tuple(dict.fromkeys(reasons))
    hard_reasons = {
        "invalid_a_share_code", "st_stock", "suspended", "delisted",
        "not_listed_on_date", "new_ipo", "market_cap_below_minimum",
        "insufficient_liquidity",
    }
    status_value = "excluded" if any(r in hard_reasons for r in unique_reasons) else (
        "review_only" if unique_reasons else "eligible"
    )
    return UniverseAssessment(
        stock_code=code,
        status=status_value,
        reason_codes=unique_reasons,
        metadata_complete=metadata_complete,
        industry=industry,
        avg_daily_amount_million=avg_amount,
    )


def apply_industry_concentration(
    assessments: Iterable[UniverseAssessment],
    scores: dict[str, float],
    *,
    max_industry_pct: float = 0.40,
) -> IndustryConcentrationResult:
    """Keep the strongest names while capping industry concentration.

    A candidate whose industry metadata is missing is bucketed as unknown and
    capped like any other group.  It used to be retained unconditionally, which
    meant a day with poor metadata had *fewer* names under the cap -- the risk
    control loosened exactly when the data was worst, and did so silently,
    since `applied` was still reported as true.
    """
    unknown_industry = "__unknown__"
    items = [item for item in assessments if not item.excluded]
    if not items or max_industry_pct <= 0:
        return IndustryConcentrationResult(
            retained_codes=tuple(item.stock_code for item in items),
        )

    limit = max(1, math.ceil(len(items) * min(1.0, max_industry_pct)))
    by_industry: dict[str, list[UniverseAssessment]] = {}
    for item in items:
        group = str(item.industry or "").strip() or unknown_industry
        by_industry.setdefault(group, []).append(item)

    retained: list[str] = []
    excluded: list[str] = []
    reasons: dict[str, tuple[str, ...]] = {}
    capped: dict[str, int] = {}
    for industry, group in by_industry.items():
        ordered = sorted(
            group,
            key=lambda item: (
                -float(scores.get(item.stock_code, 0.0)), item.stock_code
            ),
        )
        retained.extend(item.stock_code for item in ordered[:limit])
        if len(ordered) > limit:
            capped[industry] = len(ordered) - limit
            for item in ordered[limit:]:
                excluded.append(item.stock_code)
                reasons[item.stock_code] = ("industry_concentration_limit",)

    return IndustryConcentrationResult(
        retained_codes=tuple(retained),
        excluded_codes=tuple(excluded),
        reason_codes=reasons,
        capped_industries=capped,
        applied=True,
    )


def projected_industry_exposure(
    positions: Iterable[dict],
    candidate_industry: str,
    candidate_value: float,
    marked_value: float,
    *,
    max_industry_pct: float = 0.40,
) -> dict[str, object]:
    """Check a proposed position against actual portfolio industry weight."""
    industry = str(candidate_industry or "").strip()
    total = float(marked_value or 0)
    proposed = max(0.0, float(candidate_value or 0))
    if not industry:
        return {
            "allowed": False,
            "reason": "industry_metadata_missing",
            "industry": "",
            "projected_pct": None,
        }
    if total <= 0 or max_industry_pct <= 0:
        return {
            "allowed": True,
            "reason": "industry_exposure_not_applicable",
            "industry": industry,
            "projected_pct": 0.0,
        }
    current = 0.0
    for position in positions:
        if str(position.get("industry") or "").strip() == industry:
            current += max(0.0, float(position.get("market_value") or 0))
    projected_pct = (current + proposed) / total
    allowed = projected_pct <= min(1.0, float(max_industry_pct)) + 1e-9
    return {
        "allowed": allowed,
        "reason": "" if allowed else "industry_exposure_limit",
        "industry": industry,
        "current_value": round(current, 2),
        "proposed_value": round(proposed, 2),
        "projected_pct": round(projected_pct, 6),
        "max_pct": round(min(1.0, float(max_industry_pct)), 6),
    }
