"""Tests for deterministic stock-universe eligibility and concentration rules."""

from src.ai_os.universe_policy import (
    UniversePolicyConfig,
    apply_industry_concentration,
    assess_stock,
    projected_industry_exposure,
)


def _stock(code="000001.SZ", **overrides):
    stock = {
        "code": code,
        "name": "测试公司",
        "list_date": "2010-01-01",
        "market_cap": 100.0,
        "avg_daily_amount_million": 100.0,
        "industry": "银行",
    }
    stock.update(overrides)
    return stock


def test_explicit_st_is_excluded_with_reason_code():
    result = assess_stock(_stock(name="*ST测试"), as_of_date="2026-08-31")

    assert result.status == "excluded"
    assert result.reason_codes == ("st_stock",)


def test_new_ipo_is_excluded_only_when_listing_date_is_known():
    result = assess_stock(
        _stock(list_date="2026-08-01"), as_of_date="2026-08-31",
        config=UniversePolicyConfig(min_listing_days=60),
    )

    assert result.status == "excluded"
    assert "new_ipo" in result.reason_codes


def test_missing_metadata_is_review_only_not_implicitly_eligible():
    result = assess_stock(
        _stock(list_date="", market_cap=None, avg_daily_amount_million=None),
        as_of_date="2026-08-31",
    )

    assert result.status == "review_only"
    assert result.metadata_complete is False
    assert "listing_date_missing" in result.reason_codes
    assert "market_cap_missing" in result.reason_codes
    assert "liquidity_data_missing" in result.reason_codes


def test_zero_close_is_treated_as_suspended():
    result = assess_stock(
        _stock(),
        bars=[{"close": 0.0}],
        as_of_date="2026-08-31",
    )

    assert result.status == "excluded"
    assert "suspended" in result.reason_codes


def test_industry_cap_keeps_highest_scores_and_unknown_industry():
    assessments = [
        assess_stock(_stock("000001.SZ", industry="银行")),
        assess_stock(_stock("000002.SZ", industry="银行")),
        assess_stock(_stock("000003.SZ", industry="银行")),
        assess_stock(_stock("000004.SZ", industry="软件")),
        assess_stock(_stock("000005.SZ", industry="")),
    ]

    result = apply_industry_concentration(
        assessments,
        {
            "000001.SZ": 80,
            "000002.SZ": 70,
            "000003.SZ": 60,
            "000004.SZ": 50,
            "000005.SZ": 40,
        },
        max_industry_pct=0.40,
    )

    assert result.applied is True
    assert "000001.SZ" in result.retained_codes
    assert "000002.SZ" in result.retained_codes
    assert "000003.SZ" in result.excluded_codes
    assert "000005.SZ" in result.retained_codes
    assert result.reason_codes["000003.SZ"] == (
        "industry_concentration_limit",
    )


def test_invalid_code_is_never_eligible():
    result = assess_stock(_stock("IDX0001.SH"))

    assert result.status == "excluded"
    assert "invalid_a_share_code" in result.reason_codes


def test_projected_industry_exposure_caps_market_value_not_candidate_count():
    result = projected_industry_exposure(
        [
            {"industry": "银行", "market_value": 30_000},
            {"industry": "软件", "market_value": 20_000},
        ],
        "银行",
        12_000,
        100_000,
        max_industry_pct=0.40,
    )

    assert result["allowed"] is False
    assert result["reason"] == "industry_exposure_limit"
    assert result["projected_pct"] == 0.42


def test_projected_industry_exposure_fails_closed_without_candidate_industry():
    result = projected_industry_exposure([], "", 1_000, 100_000)

    assert result["allowed"] is False
    assert result["reason"] == "industry_metadata_missing"
