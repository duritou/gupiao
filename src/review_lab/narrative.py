"""Human-readable, evidence-linked summaries for an isolated review snapshot."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any


def _number(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _evidence(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    clean = [row for row in rows if abs(_number(row, "change_pct")) <= 30]
    ordered = sorted(clean, key=lambda row: _number(row, "change_pct"), reverse=True)
    selected = ordered if len(ordered) <= limit else ordered[: limit // 2] + ordered[-limit // 2 :]
    return [
        {
            "symbol": str(row.get("ts_code") or "--"),
            "name": str(row.get("name") or row.get("ts_code") or "--"),
            "industry": str(row.get("industry") or "未匹配行业"),
            "change_pct": round(_number(row, "change_pct"), 4),
            "amount": round(_number(row, "amount"), 2),
            "turnover": round(_number(row, "turnover"), 4),
            "side": "强势样本" if _number(row, "change_pct") > 0 else "弱势样本",
        }
        for row in selected
    ]


def _industry_summary(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        industry = str(row.get("industry") or "").strip()
        if industry:
            groups[industry].append(row)
    summaries: list[dict[str, Any]] = []
    for industry, members in groups.items():
        if len(members) < 10:
            continue
        changes = [_number(row, "change_pct") for row in members]
        positive = sum(1 for value in changes if value > 0)
        summaries.append(
            {
                "industry": industry,
                "universe": len(members),
                "positive": positive,
                "negative": sum(1 for value in changes if value < 0),
                "breadth_pct": round(positive / len(members) * 100, 2),
                "mean_change_pct": round(sum(changes) / len(changes), 4),
                "median_change_pct": round(float(median(changes)), 4),
                "amount": round(sum(_number(row, "amount") for row in members), 2),
            }
        )
    active = sorted(summaries, key=lambda item: item["amount"], reverse=True)[:limit]
    strongest = sorted(
        summaries, key=lambda item: (item["mean_change_pct"], item["breadth_pct"]), reverse=True
    )[:limit]
    weakest = sorted(summaries, key=lambda item: (item["mean_change_pct"], item["breadth_pct"]))[
        :limit
    ]
    return [
        {"view": "成交额靠前", "items": active},
        {"view": "平均涨跌靠前", "items": strongest},
        {"view": "平均涨跌靠后", "items": weakest},
    ]


def build_narrative(
    rows: list[dict[str, Any]],
    dates: list[str],
    target_date: str,
    project_reviews: list[dict[str, Any]],
    replay_result: dict[str, Any],
) -> dict[str, Any]:
    """Build facts, labelled interpretations and falsifiable next checks."""
    target = [row for row in rows if row.get("trade_date") == target_date]
    changes = [_number(row, "change_pct") for row in target]
    positive = sum(1 for value in changes if value > 0)
    negative = sum(1 for value in changes if value < 0)
    extreme = [row for row in target if abs(_number(row, "change_pct")) > 30]
    names = sum(1 for row in target if str(row.get("name") or "").strip())
    industries = sum(1 for row in target if str(row.get("industry") or "").strip())
    amount = sum(_number(row, "amount") for row in target)
    breadth = positive / len(target) * 100 if target else 0
    industry_views = _industry_summary(target)
    evidence = _evidence(target)
    top_industry = industry_views[1]["items"][0] if industry_views[1]["items"] else None
    weakest_industry = industry_views[2]["items"][0] if industry_views[2]["items"] else None
    facts = [
        f"周五共有 {len(target)} 只个股，{positive} 只上涨、{negative} 只下跌，"
        f"市场宽度为 {breadth:.1f}%（事实）。",
        f"成交额合计约 {amount / 1e12:.2f} 万亿元；行业可匹配 {industries}/{len(target)}，"
        f"名称可匹配 {names}/{len(target)}（事实）。",
    ]
    if top_industry:
        facts.append(
            f"行业横截面中，{top_industry['industry']} 平均涨跌 "
            f"{top_industry['mean_change_pct']:+.2f}%，"
            f"上涨占比 {top_industry['breadth_pct']:.1f}%（事实）。"
        )
    if weakest_industry:
        facts.append(
            f"平均表现最弱的可匹配行业为 {weakest_industry['industry']}，"
            f"平均涨跌 {weakest_industry['mean_change_pct']:+.2f}%（事实）。"
        )
    interpretations = [
        f"推断：上涨占比仅 {breadth:.1f}%，当天更接近普跌/防守环境；这不是趋势预测。",
        "推断：成交额只能说明交易活跃度，不能单独证明主力净流入或上涨原因。",
    ]
    if extreme:
        interpretations.append(
            f"风险：发现 {len(extreme)} 个绝对涨跌幅超过 30% 的异常样本，已从证据榜单排除，"
            "需核对新股、复权和公司行动后才能解释。"
        )
    next_checks = [
        "下一交易日待验证：市场上涨家数是否回升，强势行业是否仍保持正的行业宽度。",
        "下一交易日待验证：证据榜单中的强势样本是否延续，弱势样本是否出现反包；当前没有未来数据，不能预先下结论。",
        "若要解释涨跌原因，需要接入新闻、公告、板块资金流和分钟数据；当前结果对此保持未知。",
    ]
    quality = {
        "target_rows": len(target),
        "null_core_rows": sum(
            1
            for row in target
            if any(row.get(key) is None for key in ("open", "close", "volume", "change_pct"))
        ),
        "non_positive_core_rows": sum(
            1
            for row in target
            if any(_number(row, key) <= 0 for key in ("open", "close", "volume"))
        ),
        "extreme_change_rows": len(extreme),
        "name_coverage_pct": round(names / len(target) * 100, 2) if target else 0,
        "industry_coverage_pct": round(industries / len(target) * 100, 2) if target else 0,
        "dates": dates,
        "indicator_daily_used": False,
    }
    return {
        "headline": "；".join(facts[:2]),
        "facts": facts,
        "interpretations": interpretations,
        "next_checks": next_checks,
        "evidence": evidence,
        "industry_views": industry_views,
        "quality": quality,
        "paper_replay": {
            "trades": len(replay_result.get("trades", [])),
            "net_pnl": replay_result.get("net_pnl"),
            "causal_window": dates,
        },
    }


def enrich_project_reviews(
    project_reviews: list[dict[str, Any]], narrative: dict[str, Any]
) -> list[dict[str, Any]]:
    """Attach facts and falsifiable checks to each project card."""
    facts = narrative["facts"]
    next_checks = narrative["next_checks"]
    interpretations = narrative["interpretations"]
    enriched: list[dict[str, Any]] = []
    for item in project_reviews:
        project = str(item.get("project", ""))
        copy = dict(item)
        copy["facts"] = facts[:2]
        copy["interpretation"] = interpretations[0]
        copy["watch_next"] = next_checks[:2]
        if project.endswith("limit-up-sniper"):
            copy["facts"] = [
                facts[0],
                f"证据榜单已排除 {narrative['quality']['extreme_change_rows']} 个极端涨跌样本。",
            ]
            copy["interpretation"] = "推断：收盘涨幅只能作为候选筛选，不能替代首板封单和盘中确认。"
        elif project.endswith("MingCang"):
            copy["watch_next"] = [
                "验证影子持仓次日是否延续，并记录失败原因；不写入生产记忆。"
            ] + next_checks[:1]
        elif project.endswith("replay"):
            copy["facts"] = [
                facts[0],
                f"历史窗口为 {', '.join(narrative['quality']['dates'])}，仅有日线数据。",
            ]
        elif project.endswith("china-astock-quant"):
            copy["watch_next"] = ["下一交易日只做结果验证，不把周五收盘倒推成买点。"] + next_checks[
                :1
            ]
        enriched.append(copy)
    return enriched
