"""Point-in-time Replay engine backed by the local decision journal and bars.

Replay never downloads current quotes and never falls back to another date.
Every technical signal is computed from bars at or before the selected market
date. Forward bars are used only in the labelled evaluation and what-if layers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

MODEL_POLICIES: dict[str, dict[str, Any]] = {
    "technical-v1": {
        "label": "经典五因子",
        "weights": {
            "macd": 0.30, "rsi": 0.20, "kdj": 0.15,
            "ma": 0.20, "volume": 0.15, "boll": 0.0,
        },
        "buy_threshold": 65.0,
        "sell_threshold": 35.0,
    },
    "balanced-v2": {
        "label": "均衡六因子",
        "weights": {
            "macd": 0.22, "rsi": 0.18, "kdj": 0.15,
            "ma": 0.20, "volume": 0.15, "boll": 0.10,
        },
        "buy_threshold": 63.0,
        "sell_threshold": 37.0,
    },
    "defensive-v2": {
        "label": "防守趋势过滤",
        "weights": {
            "macd": 0.20, "rsi": 0.15, "kdj": 0.10,
            "ma": 0.25, "volume": 0.15, "boll": 0.15,
        },
        "buy_threshold": 70.0,
        "sell_threshold": 32.0,
    },
}

MODEL_ALIASES = {
    "v4.0": "technical-v1",
    "v4.2": "balanced-v2",
    "v5.0": "defensive-v2",
    "v6.0": "balanced-v2",
    "current": "balanced-v2",
}

DEFAULT_SCENARIOS = [
    {
        "name": "baseline", "description": "评分≥63，前10只，持有5个交易日",
        "buy_threshold": 63.0, "top_n": 10, "holding_days": 5,
        "stop_loss_pct": 0.0,
    },
    {
        "name": "high_confidence", "description": "评分≥68，前5只，持有5个交易日",
        "buy_threshold": 68.0, "top_n": 5, "holding_days": 5,
        "stop_loss_pct": 0.0,
    },
    {
        "name": "broad_selection", "description": "评分≥58，前20只，持有5个交易日",
        "buy_threshold": 58.0, "top_n": 20, "holding_days": 5,
        "stop_loss_pct": 0.0,
    },
    {
        "name": "risk_controlled", "description": "评分≥63，前10只，持有5日，跌5%止损",
        "buy_threshold": 63.0, "top_n": 10, "holding_days": 5,
        "stop_loss_pct": 5.0,
    },
    {
        "name": "next_session", "description": "评分≥63，前10只，持有1个交易日",
        "buy_threshold": 63.0, "top_n": 10, "holding_days": 1,
        "stop_loss_pct": 0.0,
    },
]


def _canonical_model(version: str) -> str:
    normalized = str(version or "").strip().lower()
    canonical = MODEL_ALIASES.get(normalized, normalized)
    return canonical if canonical in MODEL_POLICIES else "balanced-v2"


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ReplayContext:
    timestamp: str = ""
    replay_date: str = ""
    market_data_date: str = ""
    status: str = "ok"
    message: str = ""
    index_level: float | None = None
    index_change_pct: float | None = None
    market_breadth_up: int = 0
    market_breadth_down: int = 0
    market_breadth_flat: int = 0
    market_coverage: int = 0
    market_sentiment: float = 0.0
    market_regime: dict[str, Any] = field(default_factory=dict)
    northbound_flow: float | None = None
    stock_pool: list[dict] = field(default_factory=list)
    decision_count: int = 0
    watchlist: list[str] = field(default_factory=list)
    portfolio_positions: list[dict] = field(default_factory=list)
    knowledge_version: str = "journal"
    prompt_version: str = "journal"
    model_version: str = "balanced-v2"
    signal_weights: dict[str, float] = field(default_factory=dict)
    scanner_config: dict = field(default_factory=dict)
    context_hash: str = ""
    data_source: str = "decision_journal + local_market_daily"
    exact_date_match: bool = True
    lookahead_safe: bool = True

    def compute_hash(self) -> str:
        return _stable_hash({
            "replay_date": self.replay_date,
            "market_data_date": self.market_data_date,
            "metadata_policy": self.scanner_config.get("metadata_policy", "auto"),
            "metadata_snapshot_count": self.scanner_config.get(
                "metadata_snapshot_count", 0
            ),
            "market_regime": {
                "state": self.market_regime.get("state", "unknown"),
                "score": self.market_regime.get("score", 50),
                "as_of_date": self.market_regime.get("as_of_date", ""),
            },
            "pool": [
                (
                    stock.get("code", ""), stock.get("decision_id", 0),
                    round(float(stock.get("original_score") or 0), 3),
                )
                for stock in self.stock_pool
            ],
        })

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp,
            "replay_date": self.replay_date,
            "market_data_date": self.market_data_date,
            "index_level": self.index_level,
            "index_change_pct": self.index_change_pct,
            "market_breadth_up": self.market_breadth_up,
            "market_breadth_down": self.market_breadth_down,
            "market_breadth_flat": self.market_breadth_flat,
            "market_coverage": self.market_coverage,
            "market_sentiment": round(self.market_sentiment, 1),
            "market_regime": self.market_regime,
            "northbound_flow": self.northbound_flow,
            "stock_pool_count": len(self.stock_pool),
            "decision_count": self.decision_count,
            "watchlist": self.watchlist,
            "portfolio_positions_count": len(self.portfolio_positions),
            "knowledge_version": self.knowledge_version,
            "prompt_version": self.prompt_version,
            "model_version": self.model_version,
            "model_label": MODEL_POLICIES.get(self.model_version, {}).get("label", ""),
            "signal_weights": self.signal_weights,
            "scanner_config": self.scanner_config,
            "context_hash": self.context_hash,
            "data_source": self.data_source,
            "exact_date_match": self.exact_date_match,
            "lookahead_safe": self.lookahead_safe,
        }


@dataclass
class ReplayResult:
    context: ReplayContext | None = None
    context_hash: str = ""
    model_version: str = ""
    model_label: str = ""
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
    evaluated_count: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    avg_forward_return_pct: float | None = None
    horizon_days: int = 5
    status: str = "ok"
    message: str = ""

    def compute_result_hash(self) -> str:
        return _stable_hash({
            "model": self.model_version,
            "candidates": [
                (
                    candidate.get("stock_code", ""),
                    round(float(candidate.get("fusion_score") or 0), 2),
                    candidate.get("direction", ""),
                )
                for candidate in sorted(
                    self.candidates, key=lambda item: item.get("stock_code", "")
                )
            ],
            "total": self.total_scanned,
        })

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "context": self.context.to_dict() if self.context else None,
            "context_hash": self.context_hash,
            "model_version": self.model_version,
            "model_label": self.model_label,
            "total_scanned": self.total_scanned,
            "candidates_found": self.candidates_found,
            "candidates": self.candidates[:20],
            "is_deterministic": self.is_deterministic,
            "hash_matched": self.hash_matched,
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "top_score": round(self.top_score, 1),
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "avg_confidence": round(self.avg_confidence, 3),
            "evaluated_count": self.evaluated_count,
            "correct_count": self.correct_count,
            "accuracy": round(self.accuracy, 4) if self.accuracy is not None else None,
            "avg_forward_return_pct": (
                round(self.avg_forward_return_pct, 3)
                if self.avg_forward_return_pct is not None else None
            ),
            "horizon_days": self.horizon_days,
            "lookahead_safe": self.context.lookahead_safe if self.context else True,
            "data_source": "decision_journal + point_in_time_local_bars",
        }


@dataclass
class ModelCompareResult:
    replay_date: str = ""
    context_hash: str = ""
    versions_compared: list[str] = field(default_factory=list)
    results: dict[str, ReplayResult] = field(default_factory=dict)
    metrics: dict[str, dict] = field(default_factory=dict)
    accuracy_by_version: dict[str, float | None] = field(default_factory=dict)
    accuracy_change: dict[str, float | None] = field(default_factory=dict)
    best_version: str = ""
    best_accuracy: float | None = None
    improvement_summary: str = ""
    status: str = "ok"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "replay_date": self.replay_date,
            "context_hash": self.context_hash,
            "versions_compared": self.versions_compared,
            "results": {version: result.to_dict() for version, result in self.results.items()},
            "metrics": self.metrics,
            "accuracy_by_version": self.accuracy_by_version,
            "accuracy_change": self.accuracy_change,
            "best_version": self.best_version,
            "best_accuracy": self.best_accuracy,
            "improvement_summary": self.improvement_summary,
            "lookahead_safe": (
                all(
                    result.context is not None and result.context.lookahead_safe
                    for result in self.results.values()
                )
                if self.results else False
            ),
            "data_source": "same frozen universe + point-in-time local bars",
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
    market_data_date: str = ""
    base_scenario: str = "baseline"
    scenarios: list[SimulationScenario] = field(default_factory=list)
    results: dict[str, dict] = field(default_factory=dict)
    best_scenario: str = ""
    best_alpha_pct: float = 0.0
    worst_scenario: str = ""
    worst_alpha_pct: float = 0.0
    insights: list[str] = field(default_factory=list)
    status: str = "insufficient_data"
    lookahead_safe: bool = True

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "replay_date": self.replay_date,
            "market_data_date": self.market_data_date,
            "base_scenario": self.base_scenario,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "results": self.results,
            "best_scenario": self.best_scenario,
            "best_alpha_pct": round(self.best_alpha_pct, 3),
            "worst_scenario": self.worst_scenario,
            "worst_alpha_pct": round(self.worst_alpha_pct, 3),
            "insights": self.insights,
            "lookahead_safe": self.lookahead_safe,
            "data_source": "point-in-time signals + observed forward local bars",
        }


class ReplayEngine:
    """Run deterministic point-in-time analysis and observed-path experiments."""

    def __init__(self):
        self._replay_runs: dict[str, list[ReplayResult]] = {}

    @staticmethod
    def available_models() -> list[dict]:
        return [
            {
                "id": model_id,
                "label": policy["label"],
                "weights": policy["weights"],
                "buy_threshold": policy["buy_threshold"],
                "sell_threshold": policy["sell_threshold"],
            }
            for model_id, policy in MODEL_POLICIES.items()
        ]

    def freeze_world(
        self,
        target_date: str,
        stock_pool: list[dict] | None = None,
        watchlist: list[str] | None = None,
        portfolio: list[dict] | None = None,
        knowledge_version: str = "journal",
        prompt_version: str = "journal",
        model_version: str = "balanced-v2",
        pool_size: int = 200,
        metadata_policy: str = "auto",
    ) -> ReplayContext:
        from src.api.routes.journal_utils import latest_per_stock
        from src.infrastructure.storage.market_database import market_db

        date.fromisoformat(target_date)
        metadata_policy = str(metadata_policy or "auto").strip().lower()
        if metadata_policy not in {"auto", "ignore", "strict"}:
            raise ValueError("metadata_policy must be auto, ignore or strict")
        canonical_model = _canonical_model(model_version)
        policy = MODEL_POLICIES[canonical_model]
        decisions = latest_per_stock(
            market_db.get_decisions_for_date(target_date, limit=5000)
        )
        decisions.sort(
            key=lambda item: float(item.get("ai_score") or item.get("fusion_score") or 0),
            reverse=True,
        )
        decisions = decisions[:max(1, min(int(pool_size), 500))]
        market_data_date = market_db.get_latest_market_date_on_or_before(target_date)
        market = market_db.get_market_snapshot_for_date(market_data_date)
        from src.ai_os.market_regime import classify_market_regime

        market_regime = classify_market_regime(
            market,
            as_of_date=market_data_date,
            signal_date=target_date,
        ).to_dict()

        if stock_pool is None:
            stock_pool = [
                {
                    "code": decision.get("stock_code", ""),
                    "name": decision.get("stock_name", decision.get("stock_code", "")),
                    "decision_id": int(decision.get("id") or 0),
                    "decision_date": decision.get("decision_date", ""),
                    "created_at": decision.get("created_at", ""),
                    "original_score": float(
                        decision.get("ai_score") or decision.get("fusion_score") or 50
                    ),
                    "original_direction": str(decision.get("direction") or "neutral"),
                    "original_confidence": float(decision.get("confidence") or 0),
                    "original_scores": {
                        "macd": float(decision.get("macd_score") or 50),
                        "rsi": float(decision.get("rsi_score") or 50),
                        "kdj": float(decision.get("kdj_score") or 50),
                        "ma": float(decision.get("ma_score") or 50),
                        "volume": float(decision.get("volume_score") or 50),
                    },
                }
                for decision in decisions
                if decision.get("stock_code")
            ]

        watchlist_was_default = watchlist is None
        if watchlist is None:
            watchlist = [stock["code"] for stock in stock_pool[:30] if stock.get("code")]
        if portfolio is None:
            portfolio = []

        metadata_coverage = market_db.get_stock_metadata_coverage(target_date)
        metadata_filtered = 0
        metadata_missing = 0
        metadata_applied = False
        if metadata_policy != "ignore" and metadata_coverage["stock_count"] > 0:
            metadata_applied = True
            filtered_pool: list[dict] = []
            for stock in stock_pool:
                code = str(stock.get("code") or "")
                if not code or market_db.get_stock_metadata(code, target_date) is None:
                    metadata_missing += 1
                    if metadata_policy == "strict":
                        continue
                    filtered_pool.append(stock)
                    continue
                if market_db.is_stock_eligible(code, target_date):
                    filtered_pool.append(stock)
                else:
                    metadata_filtered += 1
            stock_pool = filtered_pool
            if watchlist_was_default:
                watchlist = [stock["code"] for stock in stock_pool[:30] if stock.get("code")]

        status = "ok"
        message = ""
        if metadata_policy == "strict" and metadata_coverage["stock_count"] == 0:
            status = "metadata_unavailable"
            message = f"{target_date} 缺少历史股票元数据快照，严格回放已停止"
        elif metadata_policy == "strict" and metadata_missing > 0:
            status = "metadata_incomplete"
            message = f"{target_date} 股票元数据快照有 {metadata_missing} 只未覆盖"
        elif not decisions:
            status = "no_journal_data"
            message = f"{target_date} 没有决策快照；Replay 不会回退到其他日期。"
        elif not market_data_date:
            status = "no_market_data"
            message = f"{target_date} 之前没有本地市场日线。"

        ctx = ReplayContext(
            timestamp=f"{target_date}T23:59:59",
            replay_date=target_date,
            market_data_date=market_data_date,
            status=status,
            message=message,
            index_change_pct=(float(market.get("average_change_pct")) if market else None),
            market_breadth_up=int(market.get("advancing") or 0),
            market_breadth_down=int(market.get("declining") or 0),
            market_breadth_flat=int(market.get("unchanged") or 0),
            market_coverage=int(market.get("total") or 0),
            market_sentiment=float(market.get("sentiment") or 0),
            market_regime=market_regime,
            stock_pool=stock_pool,
            decision_count=len(decisions),
            watchlist=watchlist,
            portfolio_positions=portfolio,
            knowledge_version=knowledge_version,
            prompt_version=prompt_version,
            model_version=canonical_model,
            signal_weights=dict(policy["weights"]),
            scanner_config={
                "source": "exact_date_decision_journal",
                "pool_limit": max(1, min(int(pool_size), 500)),
                "future_data_excluded": True,
                "metadata_policy": metadata_policy,
                "metadata_snapshot_count": metadata_coverage["stock_count"],
                "metadata_snapshot_first": metadata_coverage["first_snapshot"],
                "metadata_snapshot_last": metadata_coverage["last_snapshot"],
                "metadata_applied": metadata_applied,
                "metadata_filtered_count": metadata_filtered,
                "metadata_missing_count": metadata_missing,
                "market_regime_state": market_regime.get("state", "unknown"),
                "market_regime_score": market_regime.get("score", 50),
            },
            lookahead_safe=(
                metadata_policy == "ignore"
                or (
                    metadata_coverage["stock_count"] > 0
                    and metadata_missing == 0
                )
            ),
        )
        ctx.context_hash = ctx.compute_hash()
        return ctx

    @staticmethod
    def _weighted_signal(
        scores: dict[str, float], model_version: str
    ) -> tuple[float, str, float]:
        policy = MODEL_POLICIES[_canonical_model(model_version)]
        weights = policy["weights"]
        fusion = sum(float(scores.get(name, 50)) * weight for name, weight in weights.items())
        fusion /= sum(weights.values()) or 1.0
        direction = (
            "buy" if fusion >= policy["buy_threshold"]
            else "sell" if fusion <= policy["sell_threshold"]
            else "neutral"
        )
        confidence = min(0.95, 0.30 + abs(fusion - 50) / 50 * 0.65)
        return round(fusion, 2), direction, round(confidence, 3)

    @staticmethod
    def _forward_outcome(
        code: str,
        market_date: str,
        entry_price: float,
        direction: str,
        horizon_days: int,
    ) -> dict:
        from src.infrastructure.storage.market_database import market_db

        future = market_db.get_daily_bars_after(code, market_date, limit=horizon_days)
        if entry_price <= 0 or len(future) < horizon_days:
            return {
                "outcome_available": False,
                "forward_return_pct": None,
                "was_correct": None,
                "exit_date": "",
            }
        exit_bar = future[horizon_days - 1]
        forward_return = (float(exit_bar["close"]) / entry_price - 1) * 100
        was_correct = None
        if direction == "buy":
            was_correct = forward_return > 0
        elif direction == "sell":
            was_correct = forward_return < 0
        return {
            "outcome_available": True,
            "forward_return_pct": round(forward_return, 3),
            "was_correct": was_correct,
            "exit_date": exit_bar["date"],
        }

    def _previous_result_hash(self, ctx: ReplayContext, model_version: str) -> str:
        from src.infrastructure.storage.market_database import market_db

        for run in market_db.get_replay_runs(limit=100):
            if (
                run.get("mode") == "replay"
                and run.get("replay_date") == ctx.replay_date
                and run.get("model_version") == model_version
                and run.get("context_hash") == ctx.context_hash
            ):
                return str(run.get("result_hash") or "")
        return ""

    @staticmethod
    def _record_payload(
        replay_date: str,
        mode: str,
        model_version: str,
        context_hash: str,
        result_hash: str,
        status: str,
        payload: dict,
    ) -> None:
        from src.infrastructure.storage.market_database import market_db

        market_db.save_replay_run(
            replay_date=replay_date,
            mode=mode,
            model_version=model_version,
            context_hash=context_hash,
            result_hash=result_hash,
            status=status,
            result=payload,
        )

    async def rerun(
        self,
        ctx: ReplayContext,
        previous_hash: str = "",
        horizon_days: int = 5,
        record_run: bool = True,
    ) -> ReplayResult:
        from src.infrastructure.market_data.real_data_provider import real_data
        from src.infrastructure.storage.market_database import market_db

        horizon_days = max(1, min(int(horizon_days), 20))
        model_version = _canonical_model(ctx.model_version)
        run_context = replace(
            ctx,
            model_version=model_version,
            signal_weights=dict(MODEL_POLICIES[model_version]["weights"]),
        )
        if ctx.status != "ok":
            result = ReplayResult(
                context=run_context,
                context_hash=ctx.context_hash,
                model_version=model_version,
                model_label=MODEL_POLICIES[model_version]["label"],
                horizon_days=horizon_days,
                status=ctx.status,
                message=ctx.message,
            )
            result.current_hash = result.compute_result_hash()
            if record_run:
                payload = result.to_dict()
                self._record_payload(
                    ctx.replay_date, "replay", model_version, ctx.context_hash,
                    result.current_hash, result.status, payload,
                )
            return result

        candidates: list[dict] = []
        for stock in ctx.stock_pool:
            code = str(stock.get("code") or "")
            if not code:
                continue
            bars = market_db.get_daily_bars_until(code, ctx.market_data_date, limit=250)
            if len(bars) < 20:
                continue
            signal = real_data.compute_signals(code, stock.get("name", code), bars)
            scores = {
                "macd": signal.macd_score,
                "rsi": signal.rsi_score,
                "kdj": signal.kdj_score,
                "ma": signal.ma_score,
                "volume": signal.volume_score,
                "boll": signal.boll_score,
            }
            fusion, direction, confidence = self._weighted_signal(scores, model_version)
            entry_price = float(bars[-1].get("close") or 0)
            outcome = self._forward_outcome(
                code, ctx.market_data_date, entry_price, direction, horizon_days
            )
            candidates.append({
                "stock_code": code,
                "stock_name": stock.get("name", code),
                "decision_id": stock.get("decision_id", 0),
                "fusion_score": fusion,
                "original_score": round(float(stock.get("original_score") or 0), 2),
                "score_delta": round(fusion - float(stock.get("original_score") or 0), 2),
                "direction": direction,
                "original_direction": stock.get("original_direction", "neutral"),
                "confidence": confidence,
                "scores": scores,
                "entry_price": entry_price,
                "entry_date": bars[-1].get("date", ""),
                "data_source": "local_market_daily_point_in_time",
                "data_days": len(bars),
                **outcome,
            })

        candidates.sort(key=lambda candidate: candidate["fusion_score"], reverse=True)
        for index, candidate in enumerate(candidates):
            candidate["rank"] = index + 1

        actionable = [
            candidate for candidate in candidates
            if candidate["direction"] in ("buy", "sell")
        ]
        evaluated = [
            candidate for candidate in actionable if candidate["was_correct"] is not None
        ]
        correct = sum(candidate["was_correct"] is True for candidate in evaluated)
        returns = [
            float(candidate["forward_return_pct"])
            for candidate in actionable
            if candidate["forward_return_pct"] is not None
        ]
        result = ReplayResult(
            context=run_context,
            context_hash=ctx.context_hash,
            model_version=model_version,
            model_label=MODEL_POLICIES[model_version]["label"],
            total_scanned=len(candidates),
            candidates_found=len(actionable),
            candidates=candidates,
            top_score=candidates[0]["fusion_score"] if candidates else 0,
            buy_signals=sum(candidate["direction"] == "buy" for candidate in candidates),
            sell_signals=sum(candidate["direction"] == "sell" for candidate in candidates),
            avg_confidence=(
                sum(candidate["confidence"] for candidate in candidates) / len(candidates)
                if candidates else 0
            ),
            evaluated_count=len(evaluated),
            correct_count=correct,
            accuracy=correct / len(evaluated) if evaluated else None,
            avg_forward_return_pct=sum(returns) / len(returns) if returns else None,
            horizon_days=horizon_days,
            status="ok" if candidates else "insufficient_history",
            message=(
                "" if candidates
                else f"{ctx.market_data_date} 前可用日线不足20根，无法重算技术信号。"
            ),
        )
        result.current_hash = result.compute_result_hash()
        prior_hash = previous_hash or self._previous_result_hash(ctx, model_version)
        if prior_hash:
            result.previous_hash = prior_hash
            result.hash_matched = result.current_hash == prior_hash
            result.is_deterministic = result.hash_matched

        self._replay_runs.setdefault(ctx.replay_date, []).append(result)
        if record_run:
            payload = result.to_dict()
            self._record_payload(
                ctx.replay_date, "replay", model_version, ctx.context_hash,
                result.current_hash, result.status, payload,
            )
        return result

    async def compare_models(
        self,
        target_date: str,
        versions: list[str] | None = None,
        pool_size: int = 200,
        horizon_days: int = 5,
        metadata_policy: str = "auto",
    ) -> ModelCompareResult:
        requested = versions or list(MODEL_POLICIES)
        canonical_versions = list(dict.fromkeys(_canonical_model(version) for version in requested))
        ctx = self.freeze_world(
            target_date, pool_size=pool_size, metadata_policy=metadata_policy
        )
        comparison = ModelCompareResult(
            replay_date=target_date,
            context_hash=ctx.context_hash,
            versions_compared=canonical_versions,
            status=ctx.status if ctx.status != "ok" else "ok",
        )

        for version in canonical_versions:
            version_context = replace(ctx, model_version=version)
            replay = await self.rerun(
                version_context, horizon_days=horizon_days, record_run=False
            )
            comparison.results[version] = replay
            comparison.accuracy_by_version[version] = replay.accuracy
            comparison.metrics[version] = {
                "label": replay.model_label,
                "accuracy": replay.accuracy,
                "evaluated_count": replay.evaluated_count,
                "actionable_count": replay.candidates_found,
                "avg_forward_return_pct": replay.avg_forward_return_pct,
                "top_score": replay.top_score,
            }

        baseline_accuracy = (
            comparison.results[canonical_versions[0]].accuracy if canonical_versions else None
        )
        for version in canonical_versions:
            accuracy = comparison.results[version].accuracy
            comparison.accuracy_change[version] = (
                accuracy - baseline_accuracy
                if accuracy is not None and baseline_accuracy is not None else None
            )

        evaluated_versions = [
            version for version in canonical_versions
            if comparison.results[version].accuracy is not None
        ]
        if evaluated_versions:
            best = max(
                evaluated_versions,
                key=lambda version: (
                    comparison.results[version].accuracy or 0,
                    comparison.results[version].avg_forward_return_pct or -999,
                ),
            )
            comparison.best_version = best
            comparison.best_accuracy = comparison.results[best].accuracy
            comparison.improvement_summary = (
                f"{MODEL_POLICIES[best]['label']} 在 {comparison.results[best].evaluated_count} 个"
                f"可验证方向信号中准确率最高：{(comparison.best_accuracy or 0):.1%}。"
            )
        elif ctx.status != "ok":
            comparison.improvement_summary = ctx.message
        else:
            comparison.status = "outcomes_pending"
            comparison.improvement_summary = (
                f"{ctx.market_data_date} 之后不足 {horizon_days} 个交易日，暂不能比较准确率。"
            )

        payload = comparison.to_dict()
        self._record_payload(
            target_date, "compare", ",".join(canonical_versions), ctx.context_hash,
            _stable_hash(payload), comparison.status, payload,
        )
        return comparison

    @staticmethod
    def _normalize_scenarios(scenarios: list[dict] | None) -> list[dict]:
        source = scenarios or DEFAULT_SCENARIOS
        normalized = []
        for index, raw in enumerate(source[:10]):
            params = raw.get("override", raw.get("params_overrides", raw))
            normalized.append({
                "name": str(raw.get("name") or f"scenario_{index + 1}")[:40],
                "description": str(raw.get("description") or "")[:200],
                "buy_threshold": max(
                    50.0, min(float(params.get("buy_threshold", 65)), 90.0)
                ),
                "top_n": max(1, min(int(params.get("top_n", 10)), 50)),
                "holding_days": max(1, min(int(params.get("holding_days", 5)), 20)),
                "stop_loss_pct": max(
                    0.0, min(float(params.get("stop_loss_pct", 0)), 20.0)
                ),
                "cost_pct": max(0.0, min(float(params.get("cost_pct", 0.2)), 2.0)),
            })
        return normalized

    @staticmethod
    def _simulate_path(
        candidates: list[dict], market_date: str, scenario: dict
    ) -> dict:
        from src.infrastructure.storage.market_database import market_db

        selected = [
            candidate for candidate in candidates
            if candidate["fusion_score"] >= scenario["buy_threshold"]
        ][:scenario["top_n"]]
        position_paths: list[list[float]] = []
        final_returns: list[float] = []
        details = []
        for candidate in selected:
            entry = float(candidate.get("entry_price") or 0)
            future = market_db.get_daily_bars_after(
                candidate["stock_code"], market_date, scenario["holding_days"]
            )
            if entry <= 0 or len(future) < scenario["holding_days"]:
                continue
            path = []
            exit_date = future[-1]["date"]
            stopped = False
            for bar in future:
                raw_return = (float(bar["close"]) / entry - 1) * 100
                path.append(raw_return)
                if scenario["stop_loss_pct"] and raw_return <= -scenario["stop_loss_pct"]:
                    stopped = True
                    exit_date = bar["date"]
                    break
            final_return = path[-1] - scenario["cost_pct"]
            if stopped and len(path) < scenario["holding_days"]:
                path.extend([path[-1]] * (scenario["holding_days"] - len(path)))
            position_paths.append(path)
            final_returns.append(final_return)
            details.append({
                "stock_code": candidate["stock_code"],
                "stock_name": candidate["stock_name"],
                "score": candidate["fusion_score"],
                "return_pct": round(final_return, 3),
                "exit_date": exit_date,
                "stopped": stopped,
            })

        portfolio_curve = [1.0]
        if position_paths:
            for day_index in range(scenario["holding_days"]):
                daily_value = sum(
                    1 + path[min(day_index, len(path) - 1)] / 100
                    for path in position_paths
                ) / len(position_paths)
                portfolio_curve.append(daily_value)
        peak = portfolio_curve[0]
        max_drawdown = 0.0
        for value in portfolio_curve:
            peak = max(peak, value)
            drawdown = (value / peak - 1) * 100 if peak else 0.0
            max_drawdown = min(max_drawdown, drawdown)

        total_return = sum(final_returns) / len(final_returns) if final_returns else 0.0
        return {
            "description": scenario["description"],
            "parameters": {
                key: scenario[key]
                for key in (
                    "buy_threshold", "top_n", "holding_days", "stop_loss_pct", "cost_pct"
                )
            },
            "selected_count": len(selected),
            "total_trades": len(final_returns),
            "evaluation_coverage": (
                round(len(final_returns) / len(selected), 3) if selected else 0.0
            ),
            "total_return_pct": round(total_return, 3),
            "max_drawdown_pct": round(abs(max_drawdown), 3),
            "win_rate": (
                round(sum(value > 0 for value in final_returns) / len(final_returns), 4)
                if final_returns else 0.0
            ),
            "alpha_vs_baseline_pct": 0.0,
            "trades": details[:20],
        }

    async def simulate(
        self,
        target_date: str,
        scenarios: list[dict] | None = None,
        pool_size: int = 200,
        metadata_policy: str = "auto",
    ) -> SimulationResult:
        ctx = self.freeze_world(
            target_date,
            pool_size=pool_size,
            model_version="balanced-v2",
            metadata_policy=metadata_policy,
        )
        simulation = SimulationResult(
            replay_date=target_date,
            market_data_date=ctx.market_data_date,
            lookahead_safe=ctx.lookahead_safe,
        )
        if ctx.status != "ok":
            simulation.insights = [ctx.message]
            return simulation

        replay = await self.rerun(ctx, horizon_days=1, record_run=False)
        normalized = self._normalize_scenarios(scenarios)
        simulation.base_scenario = normalized[0]["name"] if normalized else "baseline"
        for scenario in normalized:
            simulation.scenarios.append(SimulationScenario(
                name=scenario["name"],
                description=scenario["description"],
                params_overrides={
                    key: scenario[key]
                    for key in (
                        "buy_threshold", "top_n", "holding_days", "stop_loss_pct", "cost_pct"
                    )
                },
            ))
            simulation.results[scenario["name"]] = self._simulate_path(
                replay.candidates, ctx.market_data_date, scenario
            )

        baseline = simulation.results.get(simulation.base_scenario, {})
        baseline_return = float(baseline.get("total_return_pct") or 0)
        baseline_available = bool(baseline.get("total_trades"))
        available = []
        for name, result in simulation.results.items():
            if result.get("total_trades"):
                available.append(name)
                result["alpha_vs_baseline_pct"] = (
                    round(float(result.get("total_return_pct") or 0) - baseline_return, 3)
                    if baseline_available else None
                )
            else:
                result["alpha_vs_baseline_pct"] = None

        if available:
            simulation.status = "ok"
            simulation.best_scenario = max(
                available, key=lambda name: simulation.results[name]["total_return_pct"]
            )
            simulation.worst_scenario = min(
                available, key=lambda name: simulation.results[name]["total_return_pct"]
            )
            simulation.best_alpha_pct = simulation.results[
                simulation.best_scenario
            ]["alpha_vs_baseline_pct"] or 0.0
            simulation.worst_alpha_pct = simulation.results[
                simulation.worst_scenario
            ]["alpha_vs_baseline_pct"] or 0.0
            best_result = simulation.results[simulation.best_scenario]
            simulation.insights = [
                f"{simulation.best_scenario} 在真实后续K线上收益最高："
                f"{best_result['total_return_pct']:+.2f}%（{best_result['total_trades']}笔）。",
                "所有场景使用同一冻结股票池；未来K线只用于结果评估，不参与信号计算。",
            ]
        else:
            simulation.insights = [
                "所选日期之后的交易日不足，或没有股票达到场景阈值，暂不能评估。"
            ]

        payload = simulation.to_dict()
        self._record_payload(
            target_date, "simulate", "balanced-v2", ctx.context_hash,
            _stable_hash(payload), simulation.status, payload,
        )
        return simulation


_engine: ReplayEngine | None = None


def get_replay_engine() -> ReplayEngine:
    global _engine
    if _engine is None:
        _engine = ReplayEngine()
    return _engine
