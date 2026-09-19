"""Decision Outcome Backfiller — 让软件开始"学习"。

决策结果回填闭环:
  查到期未验证决策 → 对比决策后 5 个交易日真实收益(个股 vs 等权基准)
  → 回填 was_correct / actual_return → 喂 Calibration(_case_history)

这是系统从"规则引擎"变成"会进化系统"的开关:有了 verified case,
Confidence Calibration 才有数据校准、案例库才开始积累。

was_correct 标准 = 基准超额:excess = 个股收益 - 全市场等权同期收益
  BUY       : excess > 0          为对
  SELL      : excess < 0          为对
  HOLD/其它 : |excess| < 0.5%     为对(相对基准横盘)

基准从沪深300 换成等权:扫描器在全市场(20 亿市值下限)排序,候选里 82.7%
低于 200 亿、只有 3.1% 高于 1000 亿,拿大盘指数做基准会把规模因子记成选股
能力。等权基准的定义与 point-in-time 可投资域见 src/explain/benchmark.py。

触发:POST /decision/backfill(手动)或 APScheduler 每日 16:05(定时)。
幂等:只处理 outcome_known=0,UPDATE 带 outcome_known=0 守卫。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as dt_date
from datetime import datetime, timedelta
from typing import Any

from src.explain.evidence_quality import EvidenceGrade, ResearchCase, archive_case
from src.infrastructure.storage.market_database import market_db

logger = logging.getLogger("uvicorn.error")

N_TRADING_DAYS = 5           # 回填窗口:决策后 5 个交易日
HOLD_EXCESS_BAND = 0.005     # HOLD 方向正确阈值:|excess| < 0.5%


# 当次回填运行状态(单 worker,模块级即可)
_backfill_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
}


def _compute_was_correct(direction: str, excess: float) -> bool:
    """按方向 + 超额收益判定决策是否正确。"""
    d = (direction or "").lower()
    if d == "sell":
        return excess < 0
    if d in ("hold", "neutral", ""):
        return abs(excess) < HOLD_EXCESS_BAND
    # buy 及其它默认按多头判定
    return excess > 0


def _return_between(bars_by_date: dict[str, float], start_date: str, n: int) -> float | None:
    """从 {date: close} 算 start_date 到其后第 n 个交易日的涨幅。

    若 start_date 当日无数据(非交易日/缺失),用其后首个交易日作基准近似。
    数据不足(还没到 n 个交易日后的行情)返回 None。
    """
    value, _ = _return_between_with_date(bars_by_date, start_date, n)
    return value


def _return_between_with_date(
    bars_by_date: dict[str, float],
    start_date: str,
    n: int,
    as_of_date: str | None = None,
) -> tuple[float | None, str | None]:
    """Return N-session return plus the real observation date."""
    cutoff = as_of_date or dt_date.today().isoformat()
    ordered = sorted(d for d in bars_by_date if start_date <= d <= cutoff)
    if not ordered:
        return None, None
    if start_date in bars_by_date:
        base_idx = ordered.index(start_date)
    else:
        base_idx = 0  # start_date 缺失,用之后的第一个交易日作基准
    if base_idx + n >= len(ordered):
        return None, None
    base_close = bars_by_date[ordered[base_idx]]
    observation_date = ordered[base_idx + n]
    end_close = bars_by_date[observation_date]
    if base_close <= 0:
        return None, None
    return (end_close - base_close) / base_close, observation_date


def _window_end(
    calendar: list[str], decision_date: str, horizon_days: int
) -> str | None:
    """The horizon_days-th session after decision_date on the market calendar."""
    days = [d for d in calendar if decision_date <= d <= dt_date.today().isoformat()]
    if not days:
        return None
    base = days.index(decision_date) if decision_date in days else 0
    if base + horizon_days >= len(days):
        return None
    return days[base + horizon_days]


def _build_market_observation(
    stock_by_date: dict[str, float],
    calendar: list[str],
    decision_date: str,
    horizon_days: int,
) -> dict[str, Any] | None:
    """Build one comparable stock-vs-benchmark sample or reject it.

    The window end is fixed by the market calendar rather than by whichever
    series supplies the benchmark.  A stock suspended across the horizon then
    lands on a different date and is rejected, instead of being scored against
    a benchmark that covered a different window.
    """
    observation_date = _window_end(calendar, decision_date, horizon_days)
    if observation_date is None:
        return None
    stock_return, stock_observation_date = _return_between_with_date(
        stock_by_date, decision_date, horizon_days
    )
    if stock_return is None or stock_observation_date != observation_date:
        return None
    benchmark_return, basis = market_db.equal_weight_benchmark(
        decision_date, observation_date
    )
    if benchmark_return is None:
        return None
    return {
        "stock_return": stock_return,
        "benchmark_return": benchmark_return,
        "excess_return": stock_return - benchmark_return,
        "observation_date": observation_date,
        "benchmark_basis": basis.status,
    }


def _observation_skip_reason(
    stock_by_date: dict[str, float], calendar: list[str],
    decision_date: str, horizon_days: int, expected_absences: dict[str, str],
) -> str:
    """Explain deferred labels without equating missing bars with failure."""
    if not calendar:
        return "market_calendar_unavailable"
    dates = sorted(day for day in calendar
                   if decision_date <= day <= dt_date.today().isoformat())
    if len(dates) <= horizon_days:
        return "horizon_not_ready_or_benchmark_pending"
    required_dates = dates[:horizon_days + 1]
    for day in required_dates:
        if day not in stock_by_date and day in expected_absences:
            return expected_absences[day]
    if any(day not in stock_by_date for day in required_dates):
        return "stock_data_missing_unclassified"
    return "invalid_price_or_observation_date_mismatch"


def _record_observation_skip(
    stats: dict, decision: dict, stock_by_date: dict[str, float],
    calendar: list[str], horizon_days: int,
) -> None:
    dates = [day for day in calendar
             if decision["decision_date"] <= day <= dt_date.today().isoformat()]
    code = decision["stock_code"]
    expected = market_db.get_expected_market_absences([code], dates).get(code, {})
    reason = _observation_skip_reason(
        stock_by_date, calendar, decision["decision_date"], horizon_days, expected
    )
    reasons = stats.setdefault("skip_reasons", {})
    reasons[reason] = reasons.get(reason, 0) + 1
    stats["skipped"] += 1


def _backfill_market_observations(
    horizon_days: int,
    calendar: list[str],
    limit: int = 1000,
) -> dict:
    """Persist comparable directional samples for one learning horizon."""
    stats = {"pending": 0, "verified": 0, "skipped": 0, "failed": 0}
    pending = market_db.get_pending_market_learning_decisions(
        horizon_days=horizon_days, limit=limit
    )
    stats["pending"] = len(pending)
    for decision in pending:
        try:
            stock_bars = market_db.get_daily_bars(decision["stock_code"], limit=250)
            stock_by_date = {bar["date"]: bar["close"] for bar in stock_bars}
            sample = _build_market_observation(
                stock_by_date,
                calendar,
                decision["decision_date"],
                horizon_days,
            )
            if sample is None:
                _record_observation_skip(
                    stats, decision, stock_by_date, calendar, horizon_days
                )
                continue
            saved = market_db.save_market_learning_observation(
                decision=decision,
                observation_date=str(sample["observation_date"]),
                horizon_days=horizon_days,
                stock_return=float(sample["stock_return"]),
                benchmark_return=float(sample["benchmark_return"]),
                excess_return=float(sample["excess_return"]),
                was_correct=_compute_was_correct(
                    decision.get("direction", "neutral"),
                    float(sample["excess_return"]),
                ),
                benchmark_basis=str(sample.get("benchmark_basis") or ""),
            )
            stats["verified" if saved else "skipped"] += 1
        except Exception as exc:
            logger.warning(
                "[backfill] horizon=%s decision id=%s 失败: %s",
                horizon_days,
                decision.get("id"),
                exc,
            )
            stats["failed"] += 1
    return stats


def backfill_once(min_calendar_days: int = 9) -> dict:
    """跑一次回填,返回统计 {pending, verified, skipped, failed, benchmark_ok}。"""
    if _backfill_state["running"]:
        return {"status": "already_running"}
    _backfill_state.update(
        running=True, started_at=datetime.now().isoformat(),
        finished_at=None, last_result=None,
    )
    stats = {
        "pending": 0, "verified": 0, "skipped": 0, "failed": 0,
        "daily_pending": 0, "daily_verified": 0, "daily_skipped": 0,
        "benchmark_ok": False,
        "benchmark_source": "equal_weight",
        "learning_horizons": {},
    }
    try:
        # 1. 取市场交易日历(本地,无网络)。等权基准逐窗计算,不再需要预取序列。
        calendar = market_db.get_market_calendar()
        stats["benchmark_ok"] = len(calendar) > N_TRADING_DAYS
        if not stats["benchmark_ok"]:
            logger.warning("[backfill] 本地交易日历不足(%d 日),跳过超额收益样本", len(calendar))

        # 2. 保存1日快速样本和20日长期样本。所有样本必须有可比的
        # 等权基准结果；基准缺失时安全跳过，不能退化为绝对收益。
        if stats["benchmark_ok"]:
            daily_learning = _backfill_market_observations(1, calendar)
            long_learning = _backfill_market_observations(20, calendar)
        else:
            daily_learning = {"pending": 0, "verified": 0, "skipped": 0, "failed": 0}
            long_learning = {"pending": 0, "verified": 0, "skipped": 0, "failed": 0}
        stats["daily_pending"] = daily_learning["pending"]
        stats["daily_verified"] = daily_learning["verified"]
        stats["daily_skipped"] = daily_learning["skipped"]
        stats["learning_horizons"]["1"] = daily_learning
        stats["learning_horizons"]["20"] = long_learning

        profile = market_db.get_market_learning_profile(horizon_days=1)
        market_db.upsert_daily_learning(
            dt_date.today().isoformat(),
            "market_feedback",
            (
                f"已积累下一交易日真实观察 {profile['total_observations']} 条，"
                f"其中明确 BUY/SELL 样本 {profile['decisive_observations']} 条；"
                "达到股票2次/来源3次阈值后才调整后续评分。"
            ),
            {"backfill": stats, "profile": profile},
        )

        # 3. 查 5 日正式 pending 决策
        pending = market_db.get_pending_outcome_decisions(min_calendar_days)
        stats["pending"] = len(pending)
        logger.info("[backfill] 待回填 %d 条 (交易日历 %d 日)", len(pending), len(calendar))

        for d in pending:
            try:
                code = d["stock_code"]
                decision_date = d["decision_date"]
                direction = d.get("direction", "neutral")

                # 4-5. 个股与等权基准必须在同一观测日都有5日收益。
                stock_bars = market_db.get_daily_bars(code, limit=250)
                stock_by_date = {b["date"]: b["close"] for b in stock_bars}
                sample = _build_market_observation(
                    stock_by_date, calendar, decision_date, N_TRADING_DAYS
                )
                if sample is None:
                    _record_observation_skip(
                        stats, d, stock_by_date, calendar, N_TRADING_DAYS
                    )
                    continue
                stock_ret = float(sample["stock_return"])
                bench_ret = float(sample["benchmark_return"])
                excess = float(sample["excess_return"])

                market_db.save_market_learning_observation(
                    decision=d,
                    observation_date=str(sample["observation_date"]),
                    horizon_days=N_TRADING_DAYS,
                    stock_return=stock_ret,
                    benchmark_return=bench_ret,
                    excess_return=excess,
                    was_correct=_compute_was_correct(direction, excess),
                    benchmark_basis=str(sample.get("benchmark_basis") or ""),
                )

                # 6. 判定 + 回填
                was_correct = _compute_was_correct(direction, excess)
                ok = market_db.update_decision_outcome(d["id"], was_correct, stock_ret)
                if not ok:
                    stats["failed"] += 1
                    continue
                stats["verified"] += 1

                # 7. 喂 Calibration(构造 ResearchCase 并 archive_case)
                case = ResearchCase(
                    case_id=f"RC-BACKFILL-{d['id']}",
                    stock_code=code,
                    stock_name=d.get("stock_name", code),
                    created_at=d.get("created_at", datetime.now().isoformat()),
                    ai_score=d.get("ai_score", 50),
                    direction=direction,
                    confidence=d.get("confidence", 0),
                    recommendation_text=d.get("recommendation", ""),
                    evidence_grade=EvidenceGrade.C,
                    outcome_known=True,
                    actual_30d_return=stock_ret,
                    was_correct=was_correct,
                    outcome_analyzed_at=datetime.now().isoformat(),
                )
                archive_case(case)
            except Exception as e:
                logger.warning("[backfill] 决策 id=%s 失败: %s", d.get("id"), e)
                stats["failed"] += 1

        stats["learning_horizons"]["5"] = {
            "pending": stats["pending"],
            "verified": stats["verified"],
            "skipped": stats["skipped"],
            "failed": stats["failed"],
            "skip_reasons": stats.get("skip_reasons", {}),
        }

        _backfill_state["last_result"] = stats
        logger.info("[backfill] 完成: %s", stats)
        return stats
    except Exception as e:
        logger.exception("[backfill] 异常: %s", e)
        _backfill_state["last_result"] = {**stats, "error": str(e)[:200]}
        return {**stats, "error": str(e)[:200]}
    finally:
        _backfill_state["running"] = False
        _backfill_state["finished_at"] = datetime.now().isoformat()


async def backfill_async(min_calendar_days: int = 9) -> dict:
    """异步入口:把同步回填写进线程池(含 baostock 阻塞 IO)。"""
    return await asyncio.to_thread(backfill_once, min_calendar_days)


def get_backfill_status() -> dict:
    return dict(_backfill_state)
