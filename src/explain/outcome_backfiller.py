"""Decision Outcome Backfiller — 让软件开始"学习"。

决策结果回填闭环:
  查到期未验证决策 → 对比决策后 5 个交易日真实收益(个股 vs 沪深300 基准)
  → 回填 was_correct / actual_return → 喂 Calibration(_case_history)

这是系统从"规则引擎"变成"会进化系统"的开关:有了 verified case,
Confidence Calibration 才有数据校准、案例库才开始积累。

was_correct 标准 = 基准超额:excess = 个股收益 - 沪深300 同期收益
  BUY       : excess > 0          为对
  SELL      : excess < 0          为对
  HOLD/其它 : |excess| < 0.5%     为对(相对基准横盘)

触发:POST /decision/backfill(手动)或 APScheduler 每日 16:05(定时)。
幂等:只处理 outcome_known=0,UPDATE 带 outcome_known=0 守卫。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as dt_date
from datetime import datetime, timedelta

from src.explain.evidence_quality import EvidenceGrade, ResearchCase, archive_case
from src.infrastructure.market_data.baostock_lock import mark_sync_end, mark_sync_start
from src.infrastructure.storage.market_database import market_db

logger = logging.getLogger("uvicorn.error")

N_TRADING_DAYS = 5           # 回填窗口:决策后 5 个交易日
HOLD_EXCESS_BAND = 0.005     # HOLD 方向正确阈值:|excess| < 0.5%
HS300_CODE = "sh.000300"     # 沪深300(baostock 格式,指数,不在 market_daily)
HS300_TUSHARE_CODE = "000300.SH"

_benchmark_source = ""

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


def _fetch_hs300_bars(days: int = 60) -> dict[str, float]:
    """Fetch沪深300 closes from Tushare first, then BaoStock."""
    global _benchmark_source
    _benchmark_source = ""
    try:
        from src.infrastructure.market_data.tushare_provider import tushare_provider

        payload = asyncio.run(
            tushare_provider.fetch_index_closes(HS300_TUSHARE_CODE, days)
        )
        if len(payload.data) > N_TRADING_DAYS:
            _benchmark_source = "tushare"
            return dict(payload.data)
        logger.warning("[backfill] Tushare 沪深300 数据不足(%d 日)", len(payload.data))
    except Exception as exc:
        logger.warning("[backfill] Tushare 沪深300 获取失败: %s", exc)

    # BaoStock 兜底直连拉沪深300；指数不在本地 market_daily。
    import baostock as bs
    mapping: dict[str, float] = {}
    mark_sync_start()
    try:
        lg = bs.login()
        if lg.error_code != '0':
            logger.warning("[backfill] 沪深300 login 失败: %s", lg.error_msg)
            return mapping
        try:
            end = dt_date.today().strftime('%Y-%m-%d')
            start = (dt_date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
            rs = bs.query_history_k_data_plus(
                HS300_CODE, 'date,close',
                start_date=start, end_date=end,
                frequency='d', adjustflag='3',
            )
            if rs.error_code != '0':
                logger.warning("[backfill] 沪深300 query 失败: %s", rs.error_msg)
                return mapping
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                if row[0] and row[1]:
                    mapping[row[0]] = float(row[1])
            if mapping:
                _benchmark_source = "baostock"
        finally:
            try:
                bs.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning("[backfill] 拉沪深300 异常: %s", e)
    finally:
        mark_sync_end()
    return mapping


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


def _build_market_observation(
    stock_by_date: dict[str, float],
    benchmark_by_date: dict[str, float],
    decision_date: str,
    horizon_days: int,
) -> dict[str, float | str] | None:
    """Build one comparable stock-vs-benchmark sample or reject it."""
    stock_return, observation_date = _return_between_with_date(
        stock_by_date, decision_date, horizon_days
    )
    benchmark_return, benchmark_observation_date = _return_between_with_date(
        benchmark_by_date, decision_date, horizon_days
    )
    if (
        stock_return is None
        or benchmark_return is None
        or observation_date is None
        or observation_date != benchmark_observation_date
    ):
        return None
    return {
        "stock_return": stock_return,
        "benchmark_return": benchmark_return,
        "excess_return": stock_return - benchmark_return,
        "observation_date": observation_date,
    }


def _observation_skip_reason(
    stock_by_date: dict[str, float], benchmark_by_date: dict[str, float],
    decision_date: str, horizon_days: int, expected_absences: dict[str, str],
) -> str:
    """Explain deferred labels without equating missing bars with failure."""
    if not benchmark_by_date:
        return "benchmark_unavailable"
    dates = sorted(day for day in benchmark_by_date
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
    benchmark_by_date: dict[str, float], horizon_days: int,
) -> None:
    dates = [day for day in benchmark_by_date
             if decision["decision_date"] <= day <= dt_date.today().isoformat()]
    code = decision["stock_code"]
    expected = market_db.get_expected_market_absences([code], dates).get(code, {})
    reason = _observation_skip_reason(
        stock_by_date, benchmark_by_date, decision["decision_date"], horizon_days, expected
    )
    reasons = stats.setdefault("skip_reasons", {})
    reasons[reason] = reasons.get(reason, 0) + 1
    stats["skipped"] += 1


def _backfill_market_observations(
    horizon_days: int,
    benchmark_by_date: dict[str, float],
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
                benchmark_by_date,
                decision["decision_date"],
                horizon_days,
            )
            if sample is None:
                _record_observation_skip(
                    stats, decision, stock_by_date, benchmark_by_date, horizon_days
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
    """跑一次回填,返回统计 {pending, verified, skipped, failed, hs300_ok}。"""
    if _backfill_state["running"]:
        return {"status": "already_running"}
    _backfill_state.update(
        running=True, started_at=datetime.now().isoformat(),
        finished_at=None, last_result=None,
    )
    stats = {
        "pending": 0, "verified": 0, "skipped": 0, "failed": 0,
        "daily_pending": 0, "daily_verified": 0, "daily_skipped": 0,
        "hs300_ok": False,
        "benchmark_source": "",
        "learning_horizons": {},
    }
    try:
        # 1. 拉沪深300 基准(当次缓存,所有决策共用)
        hs300 = _fetch_hs300_bars(days=60)
        stats["hs300_ok"] = len(hs300) > N_TRADING_DAYS
        stats["benchmark_source"] = _benchmark_source
        if not stats["hs300_ok"]:
            logger.warning("[backfill] 沪深300 基准数据不足(%d 日),跳过超额收益样本", len(hs300))

        # 2. 保存1日快速样本和20日长期样本。所有样本必须有可比的
        # 沪深300结果；基准缺失时安全跳过，不能退化为绝对收益。
        if stats["hs300_ok"]:
            daily_learning = _backfill_market_observations(1, hs300)
            long_learning = _backfill_market_observations(20, hs300)
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
        logger.info("[backfill] 待回填 %d 条 (沪深300 %d 日)", len(pending), len(hs300))

        for d in pending:
            try:
                code = d["stock_code"]
                decision_date = d["decision_date"]
                direction = d.get("direction", "neutral")

                # 4-5. 个股与沪深300必须在同一观测日都有5日收益。
                stock_bars = market_db.get_daily_bars(code, limit=250)
                stock_by_date = {b["date"]: b["close"] for b in stock_bars}
                sample = _build_market_observation(
                    stock_by_date, hs300, decision_date, N_TRADING_DAYS
                )
                if sample is None:
                    _record_observation_skip(stats, d, stock_by_date, hs300, N_TRADING_DAYS)
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
