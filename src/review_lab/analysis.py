"""Bounded, read-only review perspectives for the isolated review lab.

The functions in this module intentionally implement *local observations* inspired by
the supplied repositories.  They do not import or execute those repositories and do
not write to any production store.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import median
from typing import Any

PROJECTS = (
    "guoyaohua/limit-up-sniper",
    "Zeeechenn/MingCang",
    "NNNightglow/replay",
    "dfqddd/A-Stock-Analysis",
    "MisakaMikoto128/china-astock-quant",
    "fkchaos/a-share-quant-sim",
    "yangchas/AShare-Runtime-Engine",
)


def _number(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("ts_code") or "--")


def _top(
    rows: Iterable[dict[str, Any]], key: str, reverse: bool = True, limit: int = 5
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: _number(row, key), reverse=reverse)
    return [
        {
            "symbol": str(row.get("ts_code", "--")),
            "name": _name(row),
            "change_pct": round(_number(row, "change_pct"), 4),
            "close": round(_number(row, "close"), 4),
        }
        for row in ordered[:limit]
    ]


def _finding_list(top: list[dict[str, Any]], label: str) -> str:
    if not top:
        return f"{label}暂无可用标的。"
    return f"{label}：" + "、".join(f"{item['symbol']} {item['change_pct']:+.2f}%" for item in top)


def _shadow_positions(
    signal_rows: list[dict[str, Any]], target_rows: dict[str, dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    candidates = [row for row in signal_rows if _number(row, "change_pct") > 0]
    positions: list[dict[str, Any]] = []
    for row in sorted(candidates, key=lambda item: _number(item, "change_pct"), reverse=True)[
        :limit
    ]:
        target = target_rows.get(str(row.get("ts_code")))
        if target is None:
            continue
        positions.append(
            {
                "symbol": str(row.get("ts_code", "--")),
                "signal_change_pct": round(_number(row, "change_pct"), 4),
                "review_change_pct": round(_number(target, "change_pct"), 4),
                "outcome": "positive" if _number(target, "change_pct") > 0 else "negative_or_flat",
            }
        )
    return positions


def build_project_reviews(
    rows: list[dict[str, Any]],
    dates: list[str],
    target_date: str,
    replay_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return seven compact project-specific observations over one data snapshot."""
    by_date: dict[str, list[dict[str, Any]]] = {date: [] for date in dates}
    for row in rows:
        date = str(row.get("trade_date", ""))
        if date in by_date:
            by_date[date].append(row)
    target_rows = by_date.get(target_date, [])
    previous_date = dates[-2] if len(dates) >= 2 else None
    signal_rows = by_date.get(previous_date, []) if previous_date else []
    target_map = {str(row.get("ts_code")): row for row in target_rows}
    positive = sum(1 for row in target_rows if _number(row, "change_pct") > 0)
    negative = sum(1 for row in target_rows if _number(row, "change_pct") < 0)
    limit_up = [row for row in target_rows if _number(row, "change_pct") >= 9.5]
    limit_down = [row for row in target_rows if _number(row, "change_pct") <= -9.5]
    top_gainers = _top(target_rows, "change_pct", True)
    top_losers = _top(target_rows, "change_pct", False)
    amount = sum(_number(row, "amount") for row in target_rows)
    turnovers = [_number(row, "turnover") for row in target_rows if _number(row, "turnover") > 0]
    shadow = _shadow_positions(signal_rows, target_map)
    shadow_positive = sum(1 for item in shadow if item["outcome"] == "positive")
    mean_change = (
        sum(_number(row, "change_pct") for row in target_rows) / len(target_rows)
        if target_rows
        else 0
    )
    median_change = (
        float(median([_number(row, "change_pct") for row in target_rows])) if target_rows else 0
    )
    phase_fields = {
        "premarket": False,
        "auction": False,
        "open": False,
        "intraday": False,
        "post_close": bool(target_rows),
        "night_review": False,
    }

    return [
        {
            "project": PROJECTS[0],
            "method": "local_observation",
            "status": "completed",
            "title": "涨停与首板观察",
            "findings": [
                _finding_list(top_gainers, "周五涨幅靠前"),
                f"涨停近似（涨幅≥9.5%）{len(limit_up)} 只；涨停基因和盘中确认需要逐笔/分钟数据，"
                "本快照无法验证。",
            ],
            "metrics": {
                "universe": len(target_rows),
                "limit_up_like": len(limit_up),
                "limit_down_like": len(limit_down),
                "top_gainers": top_gainers,
            },
            "limitations": [
                "仅使用日线收盘快照，不等同于仓库原策略执行。",
                "没有盘中封单、开板和错失机会标签；不输出真实买点。",
            ],
        },
        {
            "project": PROJECTS[1],
            "method": "local_observation",
            "status": "completed" if shadow else "partial",
            "title": "研究→信号→影子持仓→复盘",
            "findings": [
                f'以前一交易日（{previous_date or "--"}）正收益标的形成影子信号，'
                f'周五验证 {len(shadow)} 个；其中 {shadow_positive} 个周五仍为正。',
                "结果只记录验证与记忆候选，不写入主系统学习记忆。",
            ],
            "metrics": {
                "signal_date": previous_date,
                "shadow_positions": shadow,
                "validated_positive": shadow_positive,
            },
            "limitations": ["没有人工确认、新闻研究和多日记忆库，属于本地闭环草稿。"],
        },
        {
            "project": PROJECTS[2],
            "method": "local_observation",
            "status": "completed",
            "title": "指数/板块/个股/情绪历史回放",
            "findings": [
                f"周五样本覆盖 {len(target_rows)} 只个股，涨跌家数 {positive}/{negative}；"
                "这是个股宽度代理，不是指数或板块行情。",
                _finding_list(top_losers, "跌幅靠前"),
            ],
            "metrics": {
                "sessions": dates,
                "universe": len(target_rows),
                "positive": positive,
                "negative": negative,
                "flat": len(target_rows) - positive - negative,
            },
            "limitations": ["数据库没有分钟级历史回放和完整指数/板块快照，本结果只重建日线场景。"],
        },
        {
            "project": PROJECTS[3],
            "method": "local_observation",
            "status": "completed",
            "title": "大盘宽度、资金与情绪日报",
            "findings": [
                f"周五平均涨跌幅 {mean_change:+.2f}%，中位数 {median_change:+.2f}%。"
                if target_rows
                else "周五没有有效行情行。",
                f"成交额合计约 {amount / 1e12:.2f} 万亿元；换手率有效样本 {len(turnovers)} 个。",
            ],
            "metrics": {
                "mean_change_pct": round(mean_change, 4) if target_rows else None,
                "median_change_pct": round(median_change, 4) if target_rows else None,
                "amount": round(amount, 2),
                "median_turnover": round(float(median(turnovers)), 4) if turnovers else None,
            },
            "limitations": [
                "资金流为成交额代理，不是主力净流入；行业字段可能滞后，未据此生成交易信号。"
            ],
        },
        {
            "project": PROJECTS[4],
            "method": "local_observation",
            "status": "completed" if replay_result.get("trades") else "partial",
            "title": "T+1、100股、费用与滑点纸面模拟",
            "findings": [
                f"按周三信号→周四买入→周五卖出的因果窗口，"
                f"模拟成交 {len(replay_result.get('trades', []))} 笔，"
                f"净结果 {float(replay_result.get('net_pnl', 0)):+.2f} 元。",
                "周五收盘仅用于卖出/验证，未倒推周五买点。",
            ],
            "metrics": {
                "trades": len(replay_result.get("trades", [])),
                "net_pnl": replay_result.get("net_pnl"),
                "rejected": len(replay_result.get("rejected", [])),
                "cash": replay_result.get("cash"),
            },
            "limitations": [
                "开盘成交、滑点、佣金和印花税均为假设；没有验证真实成交。",
                "三日窗口不能证明收益能力，仍需 walk-forward 和防未来函数审计。",
            ],
        },
        {
            "project": PROJECTS[5],
            "method": "local_observation",
            "status": "completed",
            "title": "研究与纸面交易共用一套策略输入",
            "findings": [
                "候选、拒绝和执行均复用同一个因果 replay 输入；"
                f'候选样本 {len(signal_rows)}，成交 {len(replay_result.get("trades", []))}，'
                f'拒绝 {len(replay_result.get("rejected", []))}。',
                "该结果用于发现研究/模拟逻辑分叉，不代表策略已经盈利。",
            ],
            "metrics": {
                "signal_rows": len(signal_rows),
                "executed": len(replay_result.get("trades", [])),
                "rejected": len(replay_result.get("rejected", [])),
            },
            "limitations": ["当前是一个受限示例窗口，不是完整回测或 walk-forward 评估。"],
        },
        {
            "project": PROJECTS[6],
            "method": "local_observation",
            "status": "partial",
            "title": "阶段化运行时覆盖检查",
            "findings": [
                "日线库可支持盘后复盘；未发现竞价、开盘、盘中逐阶段数据，因此这些阶段标记为不可用。",
                "本模块不启动定时任务，也不与 Adaptive Investment 的运行时抢占资源。",
            ],
            "metrics": {"phase_available": phase_fields, "observed_date": target_date},
            "limitations": ["缺少分钟/事件流和阶段时间戳，不能重建盘前到盘中的完整生命周期。"],
        },
    ]


def build_learning_summary(project_reviews: list[dict[str, Any]], target_date: str) -> list[str]:
    completed = sum(1 for item in project_reviews if item["status"] == "completed")
    return [
        f"周五 {target_date} 已按七个项目方向生成 {len(project_reviews)} 份本地观察，"
        f"其中 {completed} 份数据条件完整。",
        "所有观察共享同一只读日线快照；项目名用于方法映射，不表示执行了上游仓库代码。",
        "纸面成交严格遵循先决策、下一交易日买入、再下一交易日卖出；没有把周五收盘倒灌成买点。",
        "结果仅供参考，未调用 AI、未更新生产记忆、未写入 Adaptive Investment 任何表。",
    ]
