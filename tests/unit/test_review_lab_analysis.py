from src.review_lab.analysis import PROJECTS, build_learning_summary, build_project_reviews
from src.review_lab.replay import replay


def _snapshot():
    rows = []
    values = {
        "2026-09-09": (10, 11, 4.0),
        "2026-09-10": (11, 11.5, 5.0),
        "2026-09-11": (11.4, 12, 6.0),
    }
    for date, (opening, closing, change) in values.items():
        rows.append(
            {
                "ts_code": "000001.SZ",
                "trade_date": date,
                "open": opening,
                "high": closing,
                "low": opening,
                "close": closing,
                "change_pct": change,
                "volume": 1000,
                "amount": 10000,
                "turnover": 1.2,
                "name": "fixture",
            }
        )
    return rows


def test_build_project_reviews_keeps_seven_methods_and_causal_replay():
    rows = _snapshot()
    dates = ["2026-09-09", "2026-09-10", "2026-09-11"]
    result = replay([{key: value for key, value in row.items() if key != "name"} for row in rows])
    reviews = build_project_reviews(rows, dates, "2026-09-11", result)
    assert [item["project"] for item in reviews] == list(PROJECTS)
    assert all(item["method"] == "local_observation" for item in reviews)
    assert reviews[1]["metrics"]["signal_date"] == "2026-09-10"
    assert reviews[4]["metrics"]["net_pnl"] == result["net_pnl"]
    assert reviews[6]["status"] == "partial"


def test_learning_summary_is_reference_only_and_counts_complete_reviews():
    rows = _snapshot()
    dates = ["2026-09-09", "2026-09-10", "2026-09-11"]
    result = replay([{key: value for key, value in row.items() if key != "name"} for row in rows])
    reviews = build_project_reviews(rows, dates, "2026-09-11", result)
    summary = build_learning_summary(reviews, "2026-09-11")
    assert len(summary) == 4
    assert "七个项目" in summary[0]
    assert "未调用 AI" in summary[-1]
