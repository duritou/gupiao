from src.review_lab.analysis import build_project_reviews
from src.review_lab.narrative import build_narrative, enrich_project_reviews
from src.review_lab.replay import replay


def _rows():
    values = {
        "2026-09-09": (10, 11, 4.0),
        "2026-09-10": (11, 11.5, 5.0),
        "2026-09-11": (11.4, 12, 6.0),
    }
    rows = []
    for index in range(10):
        for date, (opening, closing, change) in values.items():
            rows.append(
                {
                    "ts_code": f"00000{index}.SZ",
                    "trade_date": date,
                    "open": opening,
                    "high": closing,
                    "low": opening,
                    "close": closing,
                    "change_pct": change,
                    "volume": 1000,
                    "amount": 10000,
                    "turnover": 1.2,
                    "name": "平安银行",
                    "industry": "银行",
                }
            )
    return rows


def test_narrative_contains_facts_evidence_and_next_checks():
    rows = _rows()
    dates = ["2026-09-09", "2026-09-10", "2026-09-11"]
    replay_result = replay(rows)
    reviews = build_project_reviews(rows, dates, "2026-09-11", replay_result)
    narrative = build_narrative(rows, dates, "2026-09-11", reviews, replay_result)
    assert "headline" in narrative
    assert narrative["quality"]["target_rows"] == 10
    assert narrative["evidence"][0]["symbol"].endswith(".SZ")
    assert narrative["next_checks"]
    assert narrative["industry_views"][0]["items"][0]["industry"] == "银行"


def test_enrichment_labels_interpretation_and_keeps_project_identity():
    rows = _rows()
    dates = ["2026-09-09", "2026-09-10", "2026-09-11"]
    replay_result = replay(rows)
    reviews = build_project_reviews(rows, dates, "2026-09-11", replay_result)
    narrative = build_narrative(rows, dates, "2026-09-11", reviews, replay_result)
    enriched = enrich_project_reviews(reviews, narrative)
    assert len(enriched) == 7
    assert all(item["facts"] and item["watch_next"] for item in enriched)
    assert all("推断" in item["interpretation"] for item in enriched)
