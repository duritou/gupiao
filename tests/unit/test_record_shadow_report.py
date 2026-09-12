import json

import pytest

from scripts.record_shadow_report import _load_decisions


def test_load_decisions_accepts_enveloped_same_day_payload(tmp_path):
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps({
        "trade_date": "2026-09-01",
        "decisions": [{"stock_code": "000001.SZ", "direction": "buy"}],
    }), encoding="utf-8")

    rows = _load_decisions(path, "2026-09-01")

    assert rows == [{"stock_code": "000001.SZ", "direction": "buy"}]


def test_load_decisions_rejects_cross_day_payload(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({
        "trade_date": "2026-08-31",
        "decisions": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="expected 2026-09-01"):
        _load_decisions(path, "2026-09-01")
