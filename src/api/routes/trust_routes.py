"""Trust routes computed from persisted, directionally valid journal outcomes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from fastapi import APIRouter, Query

from src.infrastructure.storage.market_database import market_db

router = APIRouter(tags=["trust"], prefix="/trust")


def _decisions(limit: int = 5000) -> list[dict]:
    return market_db.get_recent_decisions(limit=limit)


def _verified(decisions: list[dict]) -> list[dict]:
    return [
        item for item in decisions
        if bool(item.get("outcome_known"))
        and str(item.get("direction") or "").strip().lower() in {"buy", "sell"}
    ]


def _streaks(decisions: list[dict]) -> tuple[int, int]:
    ordered = sorted(
        _verified(decisions),
        key=lambda item: (str(item.get("decision_date") or ""), int(item.get("id") or 0)),
    )
    longest = 0
    current = 0
    for item in ordered:
        if bool(item.get("was_correct")):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest, current


def _strategy_breakdown(decisions: list[dict]) -> list[dict]:
    performance = market_db.get_strategy_performance().get("buckets", [])
    if performance:
        return sorted([
            {
                "strategy": item.get("strategy", "technical_only"),
                "total": int(item.get("total") or 0),
                "correct": int(item.get("correct") or 0),
                "accuracy": float(item.get("accuracy") or 0),
                "avg_return": float(item.get("avg_return") or 0) * 100,
            }
            for item in performance
        ], key=lambda item: (-item["accuracy"], -item["total"]))

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in _verified(decisions):
        scores = {
            "MACD": float(item.get("macd_score") or 50),
            "RSI": float(item.get("rsi_score") or 50),
            "KDJ": float(item.get("kdj_score") or 50),
            "MA": float(item.get("ma_score") or 50),
            "Volume": float(item.get("volume_score") or 50),
        }
        strategy = max(scores, key=lambda name: abs(scores[name] - 50))
        groups[strategy].append(item)
    result = []
    for strategy, rows in groups.items():
        returns = [float(row.get("actual_return") or 0) * 100 for row in rows]
        correct = sum(bool(row.get("was_correct")) for row in rows)
        result.append({
            "strategy": strategy,
            "total": len(rows),
            "correct": correct,
            "accuracy": round(correct / len(rows), 3) if rows else 0,
            "avg_return": round(mean(returns), 2) if returns else 0,
        })
    return sorted(result, key=lambda item: (-item["accuracy"], -item["total"]))


@router.get("/track-record")
async def track_record(days: int = Query(30, ge=7, le=365)):
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    decisions = [
        item for item in _decisions()
        if str(item.get("decision_date") or "") >= cutoff
    ]
    studies = len(decisions)
    directional = [
        item for item in decisions
        if str(item.get("direction") or "").strip().lower() in {"buy", "sell"}
    ]
    observed = [item for item in decisions if bool(item.get("outcome_known"))]
    verified_rows = _verified(decisions)
    verified = len(verified_rows)
    correct = sum(bool(item.get("was_correct")) for item in verified_rows)
    returns = [float(item.get("actual_return") or 0) * 100 for item in verified_rows]
    longest, current = _streaks(decisions)
    by_direction = []
    for direction in ("buy", "sell"):
        rows = [
            item for item in verified_rows
            if str(item.get("direction") or "").strip().lower() == direction
        ]
        if rows:
            direction_correct = sum(bool(item.get("was_correct")) for item in rows)
            by_direction.append({
                "direction": direction,
                "count": len(rows),
                "correct": direction_correct,
                "accuracy": round(direction_correct / len(rows), 3),
            })
    if studies == 0:
        return _insufficient("track-record", days)
    return {
        "status": "live" if verified else "collecting_samples",
        "period_days": days,
        "total_studies": studies,
        "total_decisions": len(directional),
        "total_recommendations": len(directional),
        "observed_decisions": len(observed),
        "verified_decisions": verified,
        "neutral_observations": len(observed) - verified,
        "correct_decisions": correct,
        "correct_count": correct,
        "decisive_verified_decisions": verified,
        "accuracy_available": verified > 0,
        "accuracy": round(correct / verified, 3) if verified else 0,
        "by_direction": by_direction,
        "current_streak": current,
        "longest_streak": longest,
        "avg_return_pct": round(mean(returns), 2) if returns else 0,
        "total_return_pct": round(sum(returns), 2) if returns else 0,
        "beat_index_pct": 0,
        "message": (
            f"AI 共产生 {len(directional)} 条 BUY/SELL 建议，已验证 {verified} 条"
            if verified else
            f"AI 共产生 {len(directional)} 条 BUY/SELL 建议，尚无到期样本；准确率暂不可用"
        ),
    }


@router.get("/ai-alpha")
async def ai_alpha(days: int = Query(90, ge=30, le=365)):
    stats = market_db.get_decision_stats()
    if stats["total_decisions"] == 0:
        return _insufficient("ai-alpha", days)
    learning_profiles = {
        horizon: market_db.get_market_learning_profile(horizon_days=horizon)
        for horizon in (1, 5, 20)
    }
    learning = learning_profiles[1]
    return {
        "status": "live" if learning.get("decisive_observations") else "collecting_samples",
        "period_days": days,
        "total_decisions": stats["total_decisions"],
        "observed_decisions": stats["verified_decisions"],
        "verified_decisions": stats["decisive_verified_decisions"],
        "accuracy_available": stats["accuracy_available"],
        "accuracy": stats["accuracy"],
        "market_observations": learning.get("total_observations", 0),
        "decisive_observations": learning.get("decisive_observations", 0),
        "learning_horizons": {
            str(horizon): {
                "total_observations": profile.get("total_observations", 0),
                "decisive_observations": profile.get("decisive_observations", 0),
                "accuracy_available": profile.get("accuracy_available", False),
                "mature_for_scoring": profile.get("decisive_observations", 0)
                >= {1: 2, 5: 20, 20: 40}[horizon],
            }
            for horizon, profile in learning_profiles.items()
        },
        "message": "AI Alpha only uses decisive buy/sell observations against the benchmark.",
    }


@router.get("/execution")
async def execution_stats(days: int = Query(30, ge=1, le=365)):
    """Expose execution tiers separately from stock-selection quality."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    trades = market_db.get_paper_trades(
        limit=500,
        date_from=cutoff,
        date_to=date.today().isoformat(),
    )
    rejections = [
        item for item in market_db.get_paper_order_rejections(limit=500)
        if str(item.get("signal_date") or item.get("execution_at") or "") >= cutoff
    ]
    by_day: dict[str, dict[str, int]] = {}

    def day_bucket(day: str) -> dict[str, int]:
        return by_day.setdefault(day, {
            "normal": 0,
            "probe": 0,
            "blocked": 0,
            "probe_opened": 0,
            "probe_promoted": 0,
            "probe_expired": 0,
        })

    for trade in trades:
        day = str(trade.get("trade_date") or "")
        bucket = day_bucket(day)
        tier = str(trade.get("execution_tier") or "normal").lower()
        if tier in {"normal", "probe"}:
            bucket[tier] += 1
        if tier == "probe" and str(trade.get("action") or "").upper() == "BUY":
            bucket["probe_opened"] += 1
        if str(trade.get("promotion_status") or "") == "promoted":
            bucket["probe_promoted"] += 1
        if (
            tier == "probe"
            and str(trade.get("action") or "").upper() == "SELL"
            and str(trade.get("reason") or "").startswith("probe_")
        ):
            bucket["probe_expired"] += 1
    for rejection in rejections:
        day = str(rejection.get("signal_date") or "")[:10]
        day_bucket(day)["blocked"] += 1

    probe_closes = [
        trade for trade in trades
        if str(trade.get("execution_tier") or "").lower() == "probe"
        and str(trade.get("action") or "").upper() == "SELL"
    ]
    wins = sum(float(trade.get("realized_pnl") or 0) > 0 for trade in probe_closes)
    losses = sum(float(trade.get("realized_pnl") or 0) <= 0 for trade in probe_closes)
    portfolio = market_db.get_paper_portfolio()
    open_probes = sum(
        str(position.get("execution_tier") or "").lower() == "probe"
        for position in portfolio.get("positions", [])
    )
    promoted_open = sum(
        str(position.get("promotion_status") or "") == "promoted"
        for position in portfolio.get("positions", [])
    )
    sample_count = len(probe_closes)
    return {
        "status": "live" if sample_count else "collecting_samples",
        "period_days": days,
        "daily": [by_day[key] | {"date": key} for key in sorted(by_day)],
        "normal_count": sum(item["normal"] for item in by_day.values()),
        "probe_count": sum(item["probe"] for item in by_day.values()),
        "blocked_count": sum(item["blocked"] for item in by_day.values()),
        "probe_open": open_probes,
        "probe_promoted_open": promoted_open,
        "probe_closed": sample_count,
        "probe_wins": wins,
        "probe_losses": losses,
        "probe_win_rate": round(wins / sample_count, 3) if sample_count else None,
        "probe_accuracy_available": sample_count > 0,
        "message": (
            "probe 胜率基于已完成的 probe 卖出成交"
            if sample_count else
            "probe 胜率暂不可用，等待完成的 probe 卖出样本"
        ),
    }


@router.get("/journal")
async def journal(limit: int = Query(30, ge=1, le=100)):
    decisions = market_db.get_recent_decisions(limit)
    return {
        "status": "live" if decisions else "accumulating",
        "total_entries": len(decisions),
        "entries": [
            {
                "id": item["id"],
                "date": item["decision_date"],
                "stock_code": item["stock_code"],
                "stock_name": item["stock_name"],
                "ai_score": item["ai_score"],
                "direction": item["direction"],
                "recommendation": item["recommendation"],
                "outcome_known": bool(item["outcome_known"]),
                "was_correct": item["was_correct"],
            }
            for item in decisions
        ],
    }


@router.get("/journal/summary")
async def journal_summary():
    stats = market_db.get_decision_stats()
    return {"status": "live" if stats["total_decisions"] else "accumulating", **stats}


@router.get("/resume")
async def resume():
    decisions = _decisions()
    stats = market_db.get_decision_stats()
    strategies = _strategy_breakdown(decisions)
    portfolio = market_db.get_paper_portfolio()
    longest, current = _streaks(decisions)
    verified = _verified(decisions)
    returns = [float(item.get("actual_return") or 0) * 100 for item in verified]
    established = min((str(item.get("decision_date") or "") for item in decisions), default="")[:7]
    best = strategies[0] if strategies else {}
    return {
        "status": "live" if decisions else "accumulating",
        "established": established,
        "total_studies": stats["total_decisions"],
        "total_recommendations": stats.get("decisive_decisions", stats["total_decisions"]),
        "total_decisions": stats.get("decisive_decisions", stats["total_decisions"]),
        "observed_decisions": stats["verified_decisions"],
        "verified_decisions": stats["decisive_verified_decisions"],
        "neutral_observations": stats["neutral_verified_decisions"],
        "correct_count": stats["decisive_correct_decisions"],
        "accuracy_available": stats["accuracy_available"],
        "overall_accuracy": stats["accuracy"],
        "accuracy": stats["accuracy"],
        "longest_streak": longest,
        "current_streak": current,
        "avg_return_per_rec": round(mean(returns), 2) if returns else 0,
        "cumulative_user_return": round(float(portfolio.get("total_pl_pct") or 0), 2),
        "best_strategy": best.get("strategy", ""),
        "best_strategy_accuracy": best.get("accuracy", 0),
        "data_source": "decision_journal + strategy_decision + paper_portfolio",
    }


@router.get("/strategies")
async def strategies():
    result = _strategy_breakdown(_decisions())
    return {
        "status": "live" if result else "insufficient_data",
        "strategies": result,
        "data_source": "verified strategy_decision or dominant verified signal",
    }


@router.get("/score-ranges")
async def score_ranges():
    buckets = [
        ("0-39", 0, 40),
        ("40-49", 40, 50),
        ("50-64", 50, 65),
        ("65-79", 65, 80),
        ("80-100", 80, 101),
    ]
    verified = _verified(_decisions())
    ranges = []
    for label, lower, upper in buckets:
        rows = [item for item in verified if lower <= float(item.get("ai_score") or 0) < upper]
        correct = sum(bool(item.get("was_correct")) for item in rows)
        ranges.append({
            "range_label": label,
            "min_score": lower,
            "max_score": upper - 1,
            "total": len(rows),
            "correct": correct,
            "accuracy": round(correct / len(rows), 3) if rows else 0,
        })
    populated = [item for item in ranges if item["total"] > 0]
    return {
        "status": "live" if populated else "insufficient_data",
        "verified_decisions": len(verified),
        "ranges": populated,
    }


@router.get("/model-evolution")
async def model_evolution():
    rows = market_db.get_strategy_context(limit=5000)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in rows:
        if str(item.get("effective_direction") or "").strip().lower() not in {"buy", "sell"}:
            continue
        grouped[str(item.get("strategy_version") or "unknown")].append(item)
    versions = []
    previous_accuracy = 0.0
    for version in sorted(grouped):
        items = grouped[version]
        verified = [
            item for item in items
            if item.get("outcome_status") in {"correct", "wrong"}
            and str(item.get("effective_direction") or "").strip().lower() in {"buy", "sell"}
        ]
        correct = sum(item.get("outcome_status") == "correct" for item in verified)
        accuracy = round(correct / len(verified), 3) if verified else 0
        versions.append({
            "version": version,
            "total_recs": len(items),
            "verified_recs": len(verified),
            "accuracy_available": bool(verified),
            "accuracy": accuracy,
            "change_vs_prev": round(accuracy - previous_accuracy, 3) if versions else 0,
        })
        previous_accuracy = accuracy
    return {
        "status": (
            "live" if any(item["accuracy_available"] for item in versions)
            else "collecting_samples" if versions
            else "insufficient_data"
        ),
        "versions": versions,
        "message": "Version comparison uses persisted strategy_version values.",
    }


@router.get("/monthly")
async def monthly():
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _decisions():
        if str(item.get("direction") or "").strip().lower() not in {"buy", "sell"}:
            continue
        month = str(item.get("decision_date") or "")[:7]
        if month:
            grouped[month].append(item)
    result = []
    for month in sorted(grouped):
        rows = grouped[month]
        verified = _verified(rows)
        correct = sum(bool(item.get("was_correct")) for item in verified)
        result.append({
            "month": month,
            "total": len(rows),
            "verified": len(verified),
            "accuracy_available": bool(verified),
            "accuracy": round(correct / len(verified), 3) if verified else 0,
        })
    return {
        "status": (
            "live" if any(item["accuracy_available"] for item in result)
            else "collecting_samples" if result
            else "insufficient_data"
        ),
        "monthly": result,
    }


@router.get("/snapshot/{snapshot_id}")
async def snapshot(snapshot_id: str):
    decision = next(
        (item for item in _decisions() if str(item.get("id")) == snapshot_id),
        None,
    )
    return (
        {"status": "live", "snapshot": decision, "snapshot_id": snapshot_id}
        if decision else {"status": "not_found", "snapshot_id": snapshot_id}
    )


def _insufficient(endpoint: str, days: int) -> dict:
    return {
        "status": "insufficient_data",
        "endpoint": endpoint,
        "requested_days": days,
        "message": "尚无 AI 决策记录。运行 AI Pipeline Runner 后自动生成。",
        "next_step": "调用 /api/v1/ai-os/run-pipeline 启动 AI 决策流水线",
    }
