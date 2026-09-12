"""Tests for shared evidence semantics and last-good recovery."""

import json

import pytest

from src.agents.evidence_dossier import (
    EvidenceDossierCache,
    collect_evidence_dossier,
    normalize_evidence,
)


def test_normalizer_distinguishes_empty_from_unavailable():
    empty = normalize_evidence(
        "announcements",
        {"announcements": [], "count": 0, "_meta": {"available": True}},
    )
    failed = normalize_evidence(
        "announcements",
        {"announcements": [], "_meta": {"available": False, "error": "timeout"}},
    )

    assert empty["status"] == "empty"
    assert empty["error"] == ""
    assert failed["status"] == "unavailable"
    assert failed["error"] == "timeout"


def test_failed_fetch_returns_stale_last_good_without_overwriting(tmp_path):
    cache = EvidenceDossierCache(tmp_path / "evidence.json")
    good = normalize_evidence(
        "valuation", {"data": {"pe": 12}, "_meta": {"available": True}}
    )
    failed = normalize_evidence(
        "valuation", {"_meta": {"available": False, "error": "rate limited"}}
    )

    assert cache.remember_or_stale("000001:valuation", good)["status"] == "available"
    stale = cache.remember_or_stale("000001:valuation", failed)

    assert stale["status"] == "stale"
    assert stale["stale"] is True
    assert stale["payload"]["data"]["pe"] == 12
    assert stale["current_error"] == "rate limited"
    stored = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert stored["items"]["000001:valuation"]["status"] == "available"


@pytest.mark.asyncio
async def test_dossier_freezes_all_source_states_in_one_snapshot(tmp_path):
    async def available():
        return {"data": {"roe": 12}, "_meta": {"available": True}}

    async def empty():
        return {"reports": [], "count": 0, "_meta": {"available": True}}

    async def failed():
        raise TimeoutError("provider timeout")

    dossier = await collect_evidence_dossier(
        "000001.SZ",
        [("financials", available), ("reports", empty), ("fundflow", failed)],
        EvidenceDossierCache(tmp_path / "dossier.json"),
    )

    assert dossier["stock_code"] == "000001.SZ"
    assert dossier["summary"] == {
        "available": 1, "empty": 1, "unavailable": 1, "stale": 0,
    }
    assert dossier["items"]["fundflow"]["error"].startswith("TimeoutError")
