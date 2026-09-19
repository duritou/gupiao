"""The score guard runs several times per pipeline; it must be idempotent.

``apply_score_guard`` is invoked once before deep analysis, once per deep
batch, and once more before persistence.  It previously reduced the score when
evidence was missing, and because it also wrote the reduced value back to
``ai_score``/``action_score`` -- which ``decision_research_score`` then read as
its own input -- the value could only ever go down.  A candidate that recovered
its evidence kept the reduced score, which is what these tests pin down.
"""

from src.ai_os.score_guard import apply_score_guard

_CLEAN_DISCOVERY = {"sources": ["cninfo"], "quote": {"price": 10.0}}
_CLEAN_DEEP = {"available": True, "evidence_gaps": [], "decision": "持有", "thesis": ""}


def _decision(score: float = 82.0) -> dict:
    return {"ai_score": score, "fusion_score": score, "direction": "buy"}


def test_guard_is_idempotent_when_evidence_is_missing():
    decision = _decision()

    snapshots = []
    for _ in range(4):
        apply_score_guard(decision, {})
        snapshots.append(
            (
                decision["ai_score"],
                decision["action_score"],
                decision["research_score"],
                decision["decision_status"],
                tuple(decision["score_guard_reasons"]),
            )
        )

    assert len(set(snapshots)) == 1, f"guard is not idempotent: {snapshots}"
    assert decision["ai_score"] == 82.0


def test_recovered_evidence_restores_the_original_score():
    """The regression: a capped value must not survive reasons clearing."""
    decision = _decision()

    apply_score_guard(decision, {})
    assert decision["score_guard_reasons"], "expected the first pass to find gaps"

    apply_score_guard(decision, _CLEAN_DISCOVERY, _CLEAN_DEEP)

    assert decision["score_guard_reasons"] == []
    assert decision["ai_score"] == 82.0
    assert decision["action_score"] == 82.0
    assert decision["score_guarded"] is False


def test_guard_preserves_the_evaluated_score_across_every_application():
    decision = _decision(91.5)

    for _ in range(4):
        apply_score_guard(decision, {})
        assert decision["action_score"] == 91.5
        assert decision["research_score"] == 91.5


def test_guard_keeps_ranking_score_and_raw_ai_score_equal_to_the_input():
    decision = _decision(77.0)

    apply_score_guard(decision, {})

    assert decision["ranking_score"] == 77.0
    assert decision["raw_ai_score"] == 77.0
    assert decision["score_lineage"]["guarded_action_score"] == 77.0
