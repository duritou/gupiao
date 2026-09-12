import json

import pytest
from fastapi import HTTPException

from src.api.routes import review_lab_routes as routes
from src.review_lab import store
from src.review_lab.replay import replay


def bars():
    return [
        {
            "ts_code": "600036.SH",
            "trade_date": f"2026-09-{day}",
            "open": price,
            "close": price + 0.5,
            "volume": 1000,
        }
        for day, price in [("09", 40), ("10", 41), ("11", 42)]
    ]


def test_causal_dates_cash_and_learning():
    result = replay(bars())
    trade = result["trades"][0]
    assert trade["name"] == "600036.SH"
    assert trade["signal_date"] < trade["buy_date"] < trade["sell_date"]
    assert result["cash"] == round(100000 - trade["cost"] + trade["proceeds"], 2)
    assert not result["positions"]
    assert len(result["learning"]) == 4


def test_friday_close_does_not_change_prior_signal_or_execution():
    data = bars()
    before = replay(data)
    data[-1]["close"] *= 2
    assert replay(data)["trades"] == before["trades"]


def test_no_signal_and_missing_session():
    data = bars()
    data[0]["close"] = 39
    assert not replay(data)["trades"]
    with pytest.raises(ValueError):
        replay(data[:2])


def test_replay_keeps_market_name_for_display():
    data = bars()
    data[0]["name"] = "招商银行"
    assert replay(data)["trades"][0]["name"] == "招商银行"


def test_route_isolated_read(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "lab_root", lambda: tmp_path)
    run = "friday-" + "a" * 32
    folder = tmp_path / run
    folder.mkdir()
    file = folder / "result.json"
    raw = json.dumps({"reference_only": True, "schema_version": 1})
    file.write_text(raw)
    assert routes.get_review_run(run)["reference_only"]
    assert file.read_text() == raw
    with pytest.raises(HTTPException):
        routes.get_review_run("../production")
    file.write_text("invalid")
    with pytest.raises(HTTPException):
        routes.get_review_run(run)


def test_store_is_same_for_source_and_release_despite_localappdata(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/runtime.env").write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "different-user"))
    for location in (
        "app/src/review_lab/store.py",
        "app/runtime/releases/release/app/src/review_lab/store.py",
    ):
        monkeypatch.setattr(store, "__file__", str(tmp_path / location))
        assert store.lab_root() == tmp_path / "runtime/adaptive-review-lab"
