import pytest

from src.ai_os.final_review import final_buy_approval


@pytest.mark.parametrize(
    ("rating", "verdict", "available", "expected"),
    [
        ("Buy", "approve", True, True),
        ("Overweight", "approve", True, True),
        ("Buy", "veto", True, False),
        ("Buy", "", False, False),
        ("Hold", "approve", True, False),
        ("Underweight", "approve", True, False),
        ("Sell", "approve", True, False),
        ("", "approve", True, False),
    ],
)
def test_final_buy_approval_truth_table(rating, verdict, available, expected):
    assert final_buy_approval(
        rating,
        verdict,
        review_available=available,
    ) is expected

