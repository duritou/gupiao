"""A final review that never runs must not read as approval.

`_apply_final_ai_review` is skipped outright once the research deadline is
spent, and `deep_buy_rejection_reason` treats "no final-review key recorded" as
approval.  `_preauthorize_final_review` records the fail-closed state up front
so the buy gate stays shut when the stage is skipped.
"""

from config.settings import settings
from src.ai_os.final_review import final_buy_approval
from src.ai_os.pipeline_runner import _preauthorize_final_review
from src.ai_os.trading_policy import (
    deep_buy_rejection_reason,
    is_deep_buy_approved,
)


def _deep_buy(**overrides) -> dict:
    decision = {
        "stock_code": "000001.SZ",
        "action_score": 80.0,
        "direction": "buy",
        "deep_analysis_available": True,
        "deep_rating": "buy",
        "deep_provider": "codex_cli",
        "deep_model": settings.CODEX_MODEL,
    }
    decision.update(overrides)
    return decision


def test_a_review_that_never_ran_does_not_approve_the_buy():
    decision = _deep_buy()

    _preauthorize_final_review([decision])

    assert decision["final_buy_approved"] is False
    assert is_deep_buy_approved(decision) is False
    assert deep_buy_rejection_reason(decision) == "codex_final_review_required"


def test_preauthorization_leaves_a_non_buy_rating_unapproved():
    decision = _deep_buy(deep_rating="underweight")

    _preauthorize_final_review([decision])

    assert decision["final_review_required"] is False
    assert decision["final_buy_approved"] is False


def test_an_earlier_approval_survives_a_later_skipped_attempt():
    """The review runs twice; the second skip must not discard the first verdict."""
    decision = _deep_buy()
    _preauthorize_final_review([decision])
    decision.update({
        "final_review_available": True,
        "final_review_verdict": "approve",
        "final_buy_approved": True,
    })

    _preauthorize_final_review([decision])

    assert decision["final_buy_approved"] is True
    assert is_deep_buy_approved(decision) is True


def test_preauthorization_ignores_candidates_without_deep_analysis():
    decision = _deep_buy(deep_analysis_available=False)

    _preauthorize_final_review([decision])

    assert "final_buy_approved" not in decision


def test_final_buy_approval_requires_an_explicit_approve():
    assert final_buy_approval("buy", "approve", review_available=True) is True
    assert final_buy_approval("buy", "veto", review_available=True) is False
    assert final_buy_approval("buy", "approve", review_available=False) is False
    assert final_buy_approval("hold", "approve", review_available=True) is False
