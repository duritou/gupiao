from __future__ import annotations

from src.agents.codex_stock_analyzer import _compact, _evidence_consumption_summary


def test_ai_consumption_summary_keeps_period_and_flow_windows_visible():
    financial_rows = []
    for index in range(8):
        quarter = ("03", "06", "09", "12")[index % 4]
        financial_rows.append({
            "end_date": f"202{6 - index // 4}-{quarter}-31",
            "n_income": index,
        })
    flow_rows = []
    for index in range(20):
        flow_rows.append({
            "trade_date": f"2026-08-{22 - index:02d}",
            "main_net": 0.0 if index == 0 else -index,
            "status": "neutral" if index == 0 else "negative",
        })
    evidence = {
        "fact_dossier": {
            "items": {
                "financials": {
                    "status": "available",
                    "payload": {
                        "data": {
                            "requested_periods": 8,
                            "period_counts": {"income": 8, "cashflow": 8},
                            "history_complete": True,
                            "statements": {"income": financial_rows},
                        },
                        "_meta": {"source_layer": "adaptive_tushare_history"},
                    },
                },
                "fundflow": {
                    "status": "available",
                    "payload": {
                        "data": {"requested_days": 20, "rows": flow_rows},
                        "_meta": {"source_layer": "adaptive_tushare_flow_history"},
                    },
                },
            }
        }
    }

    summary = _evidence_consumption_summary(evidence)
    compacted = _compact({"ai_consumption_summary": summary})
    financial = compacted["ai_consumption_summary"]["financials"]
    income = financial["statements"]["income"]
    fund_flow = compacted["ai_consumption_summary"]["fund_flow"]
    assert len(summary["input_sha256"]) == 64
    assert financial["requested_periods"] == 8
    assert income["actual_period_count"] == 8
    assert isinstance(income["period_samples"], list)
    assert [row["n_income"] for row in income["period_samples"]] == list(range(8))
    assert isinstance(income["report_dates"], list)
    assert fund_flow["row_count"] == 20
    assert fund_flow["rows"][0]["main_net"] == 0.0
