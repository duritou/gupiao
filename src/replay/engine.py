"""Replay engine backed by real journal decisions and real market data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ReplayContext:
    timestamp: str = ""
    replay_date: str = ""
    index_level: float = 0.0
    index_change_pct: float = 0.0
    market_breadth_up: int = 0
    market_breadth_down: int = 0
    northbound_flow: float = 0.0
    market_sentiment: float = 0.0
    stock_pool: list[dict] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    portfolio_positions: list[dict] = field(default_factory=list)
    knowledge_version: str = "v12"
    prompt_version: str = "v5.1"
    model_version: str = "v6.0"
    signal_weights: dict[str, float] = field(default_factory=dict)
    scanner_config: dict = field(default_factory=dict)
    user_profile_version: str = "v6.0"
    context_hash: str = ""
    data_source: str = "decision_journal"

    def compute_hash(self) -> str:
        raw = json.dumps(
            {
                "ts": self.timestamp,
                "date": self.replay_date,
                "pool": [(s.get("code", ""), s.get("score", 0)) for s in self.stock_pool],
                "model_ver": self.model_version,
            },
            sort_keys=True,
        )
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "replay_date": self.replay_date,
            "index_level": round(self.index_level, 2),
            "index_change_pct": round(self.index_change_pct, 2),
            "market_breadth_up": self.market_breadth_up,
            "market_breadth_down": self.market_breadth_down,
            "northbound_flow": round(self.northbound_flow, 2),
            "market_sentiment": round(self.market_sentiment, 1),
            "stock_pool_count": len(self.stock_pool),
            "watchlist": self.watchlist,
            "portfolio_positions_count": len(self.portfolio_positions),
            "knowledge_version": self.knowledge_version,
            "prompt_version": self.prompt_version,
            "model_version": self.model_version,
            "signal_weights": self.signal_weights,
            "scanner_config": self.scanner_config,
            "context_hash": self.context_hash,
            "data_source": self.data_source,
        }


@dataclass
class ReplayResult:
    context: ReplayContext | None = None
    context_hash: str = ""
    total_scanned: int = 0
    candidates_found: int = 0
    candidates: list[dict] = field(default_factory=list)
    is_deterministic: bool | None = None
    hash_matched: bool | None = None
    previous_hash: str = ""
    current_hash: str = ""
    top_score: float = 0.0
    buy_signals: int = 0
    sell_signals: int = 0
    avg_confidence: float = 0.0
    status: str = "ok"
    message: str = ""

    def compute_result_hash(self) -> str:
        raw = json.dumps(
            {
                "candidates": [
                    (c.get("stock_code", ""), round(c.get("fusion_score", 0), 1))
                    for c in sorted(self.candidates, key=lambda x: x.get("stock_code", ""))
                ],
                "total": self.total_scanned,
            },
            sort_keys=True,
        )
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "context": self.context.to_dict() if self.context else None,
            "context_hash": self.context_hash,
            "total_scanned": self.total_scanned,
            "candidates_found": self.candidates_found,
            "candidates": self.candidates[:10],
            "is_deterministic": self.is_deterministic,
            "hash_matched": self.hash_matched,
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "top_score": round(self.top_score, 1),
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "avg_confidence": round(self.avg_confidence, 2),
            "data_source": "decision_journal + real_data_provider",
        }


@dataclass
class ModelCompareResult:
    replay_date: str = ""
    context_hash: str = ""
    versions_compared: list[str] = field(default_factory=list)
    results: dict[str, ReplayResult] = field(default_factory=dict)
    accuracy_change: dict[str, float] = field(default_factory=dict)
    best_version: str = ""
    best_accuracy: float = 0.0
    improvement_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "replay_date": self.replay_date,
            "context_hash": self.context_hash,
            "versions_compared": self.versions_compared,
            "results": {v: r.to_dict() for v, r in self.results.items()},
            "accuracy_change": self.accuracy_change,
            "best_version": self.best_version,
            "best_accuracy": self.best_accuracy,
            "improvement_summary": self.improvement_summary,
            "data_source": "decision_journal + real_data_provider",
        }


@dataclass
class SimulationScenario:
    name: str = ""
    description: str = ""
    params_overrides: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "params_overrides": self.params_overrides,
        }


@dataclass
class SimulationResult:
    replay_date: str = ""
    base_scenario: str = "baseline"
    scenarios: list[SimulationScenario] = field(default_factory=list)
    results: dict[str, dict] = field(default_factory=dict)
    best_scenario: str = ""
    best_alpha_pct: float = 0.0
    worst_scenario: str = ""
    worst_alpha_pct: float = 0.0
    insights: list[str] = field(default_factory=list)
    status: str = "insufficient_data"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "replay_date": self.replay_date,
            "base_scenario": self.base_scenario,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "results": self.results,
            "best_scenario": self.best_scenario,
            "best_alpha_pct": round(self.best_alpha_pct, 2),
            "worst_scenario": self.worst_scenario,
            "worst_alpha_pct": round(self.worst_alpha_pct, 2),
            "insights": self.insights,
            "data_source": "real replay only; no synthetic what-if simulation",
        }


class ReplayEngine:
    """Replay uses only persisted decisions and real bars. No synthetic market state."""

    def __init__(self):
        self._replay_runs: dict[str, list[ReplayResult]] = {}

    def freeze_world(
        self,
        target_date: str,
        stock_pool: list[dict] | None = None,
        watchlist: list[str] | None = None,
        portfolio: list[dict] | None = None,
        knowledge_version: str = "v12",
        prompt_version: str = "v5.1",
        model_version: str = "v6.0",
    ) -> ReplayContext:
        from src.api.routes.journal_utils import get_journal_decisions

        decisions = get_journal_decisions(limit=100)
        dated = [d for d in decisions if str(d.get("decision_date", "")).startswith(target_date)]
        if not dated:
            dated = decisions

        if stock_pool is None:
            stock_pool = [
                {
                    "code": d.get("stock_code", ""),
                    "name": d.get("stock_name", d.get("stock_code", "")),
                    "score": float(d.get("ai_score") or 0),
                    "decision_date": d.get("decision_date", ""),
                }
                for d in dated
                if d.get("stock_code")
            ]

        if watchlist is None:
            watchlist = [s["code"] for s in stock_pool if s.get("code")]

        if portfolio is None:
            portfolio = [
                {
                    "stock_code": s.get("code", ""),
                    "stock_name": s.get("name", s.get("code", "")),
                    "ai_score": s.get("score", 0),
                    "ai_direction": "journal",
                }
                for s in stock_pool
            ]

        ctx = ReplayContext(
            timestamp=f"{target_date}T00:00:00",
            replay_date=target_date,
            stock_pool=stock_pool,
            watchlist=watchlist,
            portfolio_positions=portfolio,
            knowledge_version=knowledge_version,
            prompt_version=prompt_version,
            model_version=model_version,
            signal_weights={"MACD": 1.0, "RSI": 0.8, "MA": 0.7, "Volume": 0.8},
            scanner_config={"source": "decision_journal"},
        )
        ctx.context_hash = ctx.compute_hash()
        return ctx

    async def rerun(self, ctx: ReplayContext, previous_hash: str = "") -> ReplayResult:
        from src.infrastructure.market_data.real_data_provider import real_data

        candidates = []
        for stock in ctx.stock_pool:
            code = stock.get("code", "")
            if not code:
                continue
            bars = await real_data.get_daily_bars(code, days=250)
            if not bars or len(bars) < 20:
                continue
            sig = real_data.compute_signals(code, stock.get("name", code), bars)
            candidates.append(
                {
                    "stock_code": code,
                    "stock_name": stock.get("name", code),
                    "fusion_score": sig.fusion_score,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "scores": {
                        "macd": sig.macd_score,
                        "rsi": sig.rsi_score,
                        "kdj": sig.kdj_score,
                        "ma": sig.ma_score,
                        "volume": sig.volume_score,
                    },
                    "data_source": sig.data_source,
                    "data_days": sig.data_days,
                }
            )

        candidates.sort(key=lambda c: c["fusion_score"], reverse=True)
        for i, c in enumerate(candidates):
            c["rank"] = i + 1

        result = ReplayResult(
            context=ctx,
            context_hash=ctx.context_hash,
            total_scanned=len(ctx.stock_pool),
            candidates_found=len(candidates),
            candidates=candidates[:10],
            top_score=candidates[0]["fusion_score"] if candidates else 0,
            buy_signals=sum(1 for c in candidates if c["direction"] == "buy"),
            sell_signals=sum(1 for c in candidates if c["direction"] == "sell"),
            avg_confidence=(sum(c["confidence"] for c in candidates) / len(candidates)) if candidates else 0,
            status="ok" if candidates else "insufficient_data",
            message="" if candidates else "No real bars are available for journal decisions.",
        )
        result.current_hash = result.compute_result_hash()
        if previous_hash:
            result.hash_matched = result.current_hash == previous_hash
            result.previous_hash = previous_hash
            result.is_deterministic = result.hash_matched
        else:
            result.is_deterministic = None

        self._replay_runs.setdefault(ctx.replay_date, []).append(result)
        return result

    async def compare_models(self, target_date: str, versions: list[str] | None = None) -> ModelCompareResult:
        if versions is None:
            versions = ["current"]
        ctx = self.freeze_world(target_date)
        cmp = ModelCompareResult(
            replay_date=target_date,
            context_hash=ctx.context_hash,
            versions_compared=versions,
            improvement_summary="Model comparison uses the same real replay data; no synthetic accuracy is generated.",
        )
        for version in versions:
            ctx.model_version = version
            ctx.context_hash = ctx.compute_hash()
            cmp.results[version] = await self.rerun(ctx)
            cmp.accuracy_change[version] = 0.0
        cmp.best_version = versions[0] if versions else ""
        cmp.best_accuracy = 0.0
        return cmp

    async def simulate(self, target_date: str, scenarios: list[dict] | None = None) -> SimulationResult:
        sim = SimulationResult(replay_date=target_date)
        for sc in scenarios or []:
            sim.scenarios.append(
                SimulationScenario(
                    name=sc.get("name", "scenario"),
                    description=sc.get("description", ""),
                    params_overrides=sc.get("override", sc),
                )
            )
        sim.insights = ["What-if simulation is disabled until real execution/outcome data is available."]
        return sim


_engine: ReplayEngine | None = None


def get_replay_engine() -> ReplayEngine:
    global _engine
    if _engine is None:
        _engine = ReplayEngine()
    return _engine
