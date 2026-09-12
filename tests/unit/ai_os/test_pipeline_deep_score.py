from src.ai_os.pipeline_runner import _apply_deep_score


def test_deep_score_does_not_overwrite_technical_or_ranking_scores():
    decision = {
        "technical_score": 71.5,
        "ranking_score": 78.2,
        "ai_score": 78.2,
    }

    _apply_deep_score(decision, {"available": True, "score": 84.0})

    assert decision["technical_score"] == 71.5
    assert decision["ranking_score"] == 78.2
    assert decision["deep_score"] == 84.0
    assert decision["ai_score"] == 84.0


def test_unavailable_deep_score_does_not_change_scores():
    decision = {"technical_score": 71.5, "ranking_score": 78.2, "ai_score": 78.2}

    _apply_deep_score(decision, {"available": False, "score": 84.0})

    assert decision == {
        "technical_score": 71.5,
        "ranking_score": 78.2,
        "ai_score": 78.2,
    }
