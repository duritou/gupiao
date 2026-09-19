"""AI Pipeline Runner — the daily decision loop.

Closes the loop that makes every Dashboard/Portfolio/Journal/Resume work:

  Market Data → Scanner → Signals → Decisions → Journal → Stats

Previously: each step existed but nothing connected them.
Now: run_pipeline() orchestrates the full daily flow.

Usage:
  runner = AIPipelineRunner()
  await runner.run_daily_pipeline()  # → produces today's decisions

Output:
  - Decisions saved to SQLite (decision_journal table)
  - Trust/Resume/Journal pages read from real data
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from src.ai_os.candidate_allocator import (
    allocate_deep_candidates,
    has_market_evidence,
)
from src.ai_os.causal_execution import CHINA_TZ
from src.ai_os.deep_research_identity import deep_input_fingerprint
from src.ai_os.numeric_policy import (
    clamp_finite,
    finite_or,
    round_finite,
    strict_json_loads,
)
from src.ai_os.cross_sectional_scoring import flow_positive, flow_status
from src.ai_os.execution_policy import (
    evaluate_entry_execution,
    is_flow_probe_candidate,
)
from src.ai_os.market_learning import multi_horizon_learning_adjustment
from src.ai_os.pipeline_observability import (
    classify_run_outcome,
    summarize_execution_dispositions,
)
from src.ai_os.recommendation_quality import (
    apply_decision_display_fields,
    apply_publication_quality,
    is_actionable_recommendation,
    is_publishable_recommendation,
    sort_decisions,
)
from src.ai_os.strategy_version import create_strategy_run_metadata
from src.ai_os.trading_policy import (
    PAPER_CONDITIONAL_BUY_MAX_CANDIDATES,
    PAPER_LIVENESS_LOG_LIMIT,
    PAPER_MOMENTUM_PROBE_MAX_CANDIDATES,
    conditional_probe_rank,
    is_deep_buy_approved,
    is_conditional_probe_candidate,
    is_momentum_probe_candidate,
    momentum_probe_rank,
    paper_liveness_status,
)
from src.ai_os.universe_policy import (
    apply_industry_concentration,
    assess_stock,
    config_from_settings,
)


def _model_code_key(value: Any) -> str:
    """Return a stable six-digit key for model output matching."""
    text = str(value or "").strip().upper()
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:] if len(digits) >= 6 else text


def _selection_weights(settings: Any) -> dict[str, float]:
    """Read scoring weights across mixed-version Settings instances."""
    return {
        "technical": float(getattr(settings, "SELECTION_TECHNICAL_WEIGHT", 0.70)),
        "discovery": float(getattr(settings, "SELECTION_DISCOVERY_WEIGHT", 0.20)),
        "learning": float(getattr(settings, "SELECTION_LEARNING_WEIGHT", 0.10)),
        "rank": float(getattr(settings, "CROSS_SECTIONAL_RANK_WEIGHT", 0.70)),
    }


def _deep_candidate_rank(decision: dict) -> tuple[float, float, float, float]:
    """Rank deep-analysis candidates without losing raw signal strength."""
    return (
        float(decision.get("raw_ai_score") or decision.get("ai_score") or 0),
        float(decision.get("ai_score") or 0),
        float(decision.get("technical_score") or 0),
        float(decision.get("discovery_score") or 0),
    )


def _apply_deep_score(decision: dict[str, Any], deep: dict[str, Any]) -> None:
    """Store the deep score separately while retaining ranking audit fields."""
    if not deep.get("available"):
        return
    score = round_finite(deep.get("score"), 1, 0.0)
    decision["deep_base_score"] = round(
        float(decision.get("ai_score") or decision.get("ranking_score") or 0), 1
    )
    decision["deep_score"] = score
    decision["ai_score"] = score


def _deep_analysis_plan(
    deep_candidates: list[dict],
    cached_deep: dict[str, dict[str, Any]],
    deep_target: int,
    daily_deep_successes: int,
    daily_deep_attempts: int,
    force_reanalysis: bool,
    max_new_candidates: int | None = None,
    daily_call_limit: int | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict], int]:
    """Choose cache reuse and a bounded fresh-analysis batch.

    The optional limits support the morning/afternoon continuation budget while
    preserving the original helper contract for callers and replay tests.
    """
    reusable_cache = {} if force_reanalysis else cached_deep
    uncached_candidates = [
        item for item in deep_candidates
        if str(item.get("stock_code") or "").upper() not in reusable_cache
    ]
    if force_reanalysis:
        # A manual, auditable refresh may bypass the normal same-day budget,
        # but it still cannot exceed the configured deep-analysis target.
        daily_call_budget = min(max(0, int(deep_target)), len(uncached_candidates))
    elif max_new_candidates is not None:
        available = max(0, int(max_new_candidates))
        if daily_call_limit is not None:
            available = min(
                available,
                max(0, int(daily_call_limit) - max(0, int(daily_deep_attempts))),
            )
        daily_call_budget = min(available, len(uncached_candidates))
    else:
        daily_successes_needed = max(0, deep_target - daily_deep_successes)
        daily_attempts_remaining = max(0, deep_target * 2 - daily_deep_attempts)
        daily_call_budget = min(daily_successes_needed, daily_attempts_remaining)
    missing_candidates = uncached_candidates[:daily_call_budget]
    skipped_count = max(0, len(uncached_candidates) - len(missing_candidates))
    return reusable_cache, missing_candidates, skipped_count


def _json_array_spans(text: str) -> list[str]:
    """Return top-level ``[...]`` substrings, respecting string literals.

    The previous implementation used a greedy ``\\[[\\s\\S]*\\]`` search, which
    spans from the first ``[`` to the last ``]`` in the whole reply.  A model
    that wrote "结果如下：[{...}] 以上。" produced a candidate that included the
    trailing prose and failed to parse, and any stray bracket in the preamble
    broke it the same way.
    """
    spans: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            if depth == 0:
                start = index
            depth += 1
        elif char == "]" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(text[start:index + 1])
                start = None
    return spans


def _extract_json_items(text: str) -> list[dict]:
    """Extract a JSON list from a concise model response.

    Parsing is strict: the bare ``NaN``/``Infinity`` literals that
    ``json.loads`` accepts by default are rejected here, because a non-finite
    score would otherwise reach the arithmetic in the callers.
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    candidates = [raw, *_json_array_spans(raw)]
    for candidate in candidates:
        try:
            payload = strict_json_loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("results") or []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def _select_candidate_records(
    records: list[dict],
    discovery_by_code: dict[str, dict],
    shortlist_count: int,
    held_codes: set[str] | None = None,
) -> list[dict]:
    """Select a bounded shortlist after the deterministic full-market pass.

    Technical leaders form the base shortlist. Remote discovery candidates
    that were also successfully scored are overlaid before the final cap, so
    a strong news/flow signal can enter without bypassing the technical pass.
    Held positions are always retained for risk review.
    """
    if not records:
        return []
    by_code = {str(item.get("code")): item for item in records}
    ordered = sorted(
        records,
        key=lambda item: (
            float(item.get("adaptive_score", 50.0)),
            float(item.get("technical_score", 50.0)),
        ),
        reverse=True,
    )
    cap = max(1, int(shortlist_count))
    selected = {str(item["code"]): item for item in ordered[:cap]}
    remote_order = sorted(
        discovery_by_code.values(),
        key=lambda item: float(item.get("discovery_score", 0.0)),
        reverse=True,
    )
    for item in remote_order:
        code = str(item.get("stock_code") or "")
        if code in by_code:
            selected.setdefault(code, by_code[code])
    ranked = sorted(
        selected.values(),
        key=lambda item: (
            float(item.get("adaptive_score", 50.0)),
            float(item.get("technical_score", 50.0)),
        ),
        reverse=True,
    )
    ranked = ranked[:cap]
    for code in held_codes or set():
        item = by_code.get(code)
        if item and all(str(existing.get("code")) != code for existing in ranked):
            ranked.append(item)
    return ranked


def _build_decision_from_record(
    record: dict, selection_mode: str, discovery_snapshot: Any
) -> dict:
    """Convert a scored technical record into the persisted decision shape."""
    code = str(record["code"])
    name = str(record["name"])
    sig = record["sig"]
    discovery_item = record.get("discovery_item") or {}
    sources = list(record.get("sources") or [])
    learned = record.get("learned") or {}
    flow = record.get("flow") or {}
    technical_score = float(record.get("technical_score", 50.0))
    discovery_score = float(record.get("discovery_score", 50.0))
    adaptive_score = float(record.get("adaptive_score", 50.0))
    direction = str(record.get("direction") or "neutral")
    rec = (
        "强烈买入" if direction == "buy" and adaptive_score >= 80 else
        "买入" if direction == "buy" else
        "卖出" if direction == "sell" else
        "热点观察" if discovery_score >= 65 else
        "观望"
    )
    evidence_payload = {
        "schema_version": 3,
        "selection_mode": selection_mode,
        "stock_skill": {
            "hot_reason": discovery_item.get("stock_skill") or {},
            "quote": discovery_item.get("quote") or {},
        },
        "market_discovery": {
            "version": (
                discovery_snapshot.version if discovery_snapshot
                else "explicit-or-local"
            ),
            "fetched_at": (
                discovery_snapshot.fetched_at if discovery_snapshot else None
            ),
            "sources": sources,
            "source_ranks": discovery_item.get("source_ranks") or {},
            "reasons": (discovery_item.get("reasons") or [])[:5],
            "concepts": (discovery_item.get("concepts") or [])[:10],
            "discovery_score": round(discovery_score, 2),
            "score_breakdown": discovery_item.get("score_breakdown") or {},
            "quote": discovery_item.get("quote") or {},
            "fund_flow": flow,
        },
        "technical": {
            "score": technical_score,
            "data_days": sig.data_days,
            "data_source": sig.data_source,
        },
        "learning": learned,
    }
    quote = discovery_item.get("quote") or {}
    return {
        "date": date.today().isoformat(),
        "signal_at": "",
        "stock_code": code,
        "stock_name": name,
        "ai_score": round(adaptive_score, 1),
        "scanner_score": round(adaptive_score, 1),
        "technical_score": round(technical_score, 1),
        "discovery_score": round(discovery_score, 1),
        "learning_adjustment": learned.get("score_adjustment", 0),
        "direction": direction,
        "confidence": round(
            min(0.95, abs(adaptive_score - 50) / 50 * 0.8 + 0.3), 3
        ),
        "recommendation": rec,
        "fusion_score": round(adaptive_score, 1),
        "macd_score": sig.macd_score,
        "rsi_score": sig.rsi_score,
        "kdj_score": sig.kdj_score,
        "ma_score": sig.ma_score,
        "volume_score": sig.volume_score,
        "buy_signals": sum(
            1 for value in [
                sig.macd_score, sig.rsi_score, sig.kdj_score,
                sig.ma_score, sig.volume_score,
            ] if value >= 65
        ),
        "sell_signals": sum(
            1 for value in [
                sig.macd_score, sig.rsi_score, sig.kdj_score,
                sig.ma_score, sig.volume_score,
            ] if value <= 35
        ),
        "evidence": json.dumps(evidence_payload, ensure_ascii=False),
        "market_sources": sources,
        "market_reasons": (discovery_item.get("reasons") or [])[:5],
        "market_flow": flow,
        "market_price": float(quote.get("price") or 0),
        "market_pre_close": float(
            quote.get("prev_close") or quote.get("pre_close") or 0
        ),
        "market_change_pct": float(quote.get("change_pct") or 0),
        "market_price_source": str(quote.get("source") or ""),
        "market_price_date": str(quote.get("data_date") or ""),
        "market_price_fetched_at": str(quote.get("fetched_at") or ""),
        "stock_skill_evidence": {
            "hot_reason": discovery_item.get("stock_skill") or {},
            "quote": quote,
        },
    }


async def _apply_ai_preselection(
    decisions: list[dict], limit: int, ai_router: Any, provider_ready: bool
) -> tuple[int, bool, str]:
    """Apply one batched Codex pre-ranking call to the shortlist."""
    selected = decisions[: max(0, int(limit))]
    if not selected or not provider_ready:
        return 0, False, ""
    rows = []
    for item in selected:
        rows.append({
            "code": item.get("stock_code"),
            "name": item.get("stock_name"),
            "technical_score": item.get("technical_score"),
            "discovery_score": item.get("discovery_score"),
            "fusion_score": item.get("fusion_score"),
            "change_pct": item.get("market_change_pct"),
            "sources": item.get("market_sources") or [],
            "reasons": (item.get("market_reasons") or [])[:3],
            "flow": item.get("market_flow") or {},
            "stock_skill": item.get("stock_skill_evidence") or {},
        })
    prompt = (
        "你是量化策略的轻量预筛选器。以下股票已经通过全市场技术指标筛选。"
        "请结合技术分、热点来源、资金流和风险证据，对每只股票给出 -10 到 +10 的"
        "score_adjustment。不要编造资讯或行情。只返回 JSON 数组，不要 Markdown："
        '[{"code":"000001.SZ","score_adjustment":2,"direction":"buy|sell|neutral",'
        '"reason":"不超过30字"}]\n\n候选数据：'
        + json.dumps(rows, ensure_ascii=False)
    )
    system_prompt = (
        "你是严格的股票研究预筛选器，只能使用输入数据。"
        "输出必须是可解析的 JSON 数组。"
    )
    request_payload = json.dumps(
        {"system_prompt": system_prompt, "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_sha256 = hashlib.sha256(request_payload.encode("utf-8")).hexdigest()
    input_fields = [
        "code", "name", "technical_score", "discovery_score", "fusion_score",
        "change_pct", "sources", "reasons", "flow", "stock_skill",
    ]
    for decision in selected:
        decision["preselection_input_sha256"] = input_sha256
        decision["preselection_input_chars"] = len(request_payload)
        decision["preselection_input_count"] = len(rows)
        decision["preselection_input_fields"] = input_fields
    try:
        response = await ai_router.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            primary_provider="codex_cli",
            allow_fallback=False,
        )
    except Exception as exc:
        return 0, False, str(exc)[:160]

    for decision in selected:
        decision["preselection_provider"] = response.provider
        decision["preselection_model"] = response.model
        decision["preselection_called"] = True
    matched = 0
    by_code = {_model_code_key(item.get("stock_code")): item for item in selected}
    for item in _extract_json_items(response.text):
        decision = by_code.get(_model_code_key(item.get("code")))
        if not decision:
            continue
        try:
            # min/max cannot bound NaN, and `min(10.0, nan)` is 10.0 -- i.e. a
            # non-finite adjustment would take the maximum bonus, not zero.
            adjustment = clamp_finite(
                item.get("score_adjustment", 0), -10.0, 10.0, 0.0
            )
        except (TypeError, ValueError):
            adjustment = 0.0
        direction = str(item.get("direction") or "neutral").lower()
        if direction not in {"buy", "sell", "neutral"}:
            direction = "neutral"
        decision["ai_preselection_available"] = True
        decision["preselection_base_score"] = round(
            float(decision.get("ai_score") or decision.get("ranking_score") or 0), 1
        )
        decision["ai_preselection_score"] = round(adjustment, 1)
        decision["ai_preselection_direction"] = direction
        decision["ai_preselection_reason"] = str(item.get("reason") or "")[:240]
        decision["ai_score"] = round(
            clamp_finite(
                finite_or(decision.get("ai_score"), 50.0) + adjustment,
                0.0, 100.0, 50.0,
            ),
            1,
        )
        decision["preselection_adjusted_score"] = decision["ai_score"]
        decision["ranking_score"] = decision["ai_score"]
        decision["fusion_score"] = decision["ai_score"]
        decision["ai_analysis"] = decision["ai_preselection_reason"]
        decision["ai_provider"] = response.provider
        decision["ai_model"] = response.model
        decision["ai_fallback_used"] = response.fallback_used
        matched += 1
    return matched, True, ""


def _preauthorize_final_review(
    decisions: list[dict], stock_codes: set[str] | None = None
) -> None:
    """Record a fail-closed review state before the review is attempted.

    `_apply_final_ai_review` is what writes `final_review_required` and
    `final_buy_approved`, but the caller skips it entirely once the research
    deadline is spent.  `deep_buy_rejection_reason` treats "neither key is
    present" as approval, so a skipped stage used to open the buy gate without
    any final review -- exactly when the analysis budget, and therefore the
    analysis quality, was worst.

    Values are only filled in when absent.  The review is attempted twice (the
    first batch, then the full set), and a later skip must not discard a
    verdict the earlier attempt already reached.
    """
    review_code_keys = (
        {_model_code_key(code) for code in stock_codes}
        if stock_codes is not None
        else None
    )
    for item in decisions:
        if not item.get("deep_analysis_available"):
            continue
        if review_code_keys is not None and _model_code_key(
            item.get("stock_code")
        ) not in review_code_keys:
            continue
        item.setdefault(
            "final_review_required",
            str(item.get("deep_rating") or "").lower() in {"buy", "overweight"},
        )
        item.setdefault("final_review_available", False)
        item.setdefault("final_review_verdict", "unavailable")
        item.setdefault("final_buy_approved", False)
        item.setdefault("final_review_error", "final_review_not_invoked")


async def _apply_final_ai_review(
    decisions: list[dict],
    ai_router: Any,
    recent_learning: list[dict],
    primary_provider: str,
    stock_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Let a separate Codex turn confirm or veto Codex-Terra deep decisions."""
    review_code_keys = {
        _model_code_key(code) for code in stock_codes
    } if stock_codes is not None else None
    selected = [
        item for item in decisions
        if item.get("deep_analysis_available")
        and (
            stock_codes is None
            or _model_code_key(item.get("stock_code")) in review_code_keys
        )
    ]
    if not selected:
        return {
            "called": False,
            "matched": 0,
            "provider": "",
            "model": "",
            "fallback_used": False,
            "error": "",
            "input_sha256": "",
            "input_chars": 0,
            "input_count": 0,
            "input_fields": [],
        }

    rows = []
    for item in selected:
        item["tradingagents_rating"] = item.get("deep_rating", "")
        item["tradingagents_direction"] = item.get("direction", "neutral")
        item["tradingagents_score"] = item.get("ai_score", 50)
        item["final_review_required"] = str(item.get("deep_rating") or "").lower() in {
            "buy",
            "overweight",
        }
        rows.append({
            "code": item.get("stock_code"),
            "name": item.get("stock_name"),
            "technical_score": item.get("technical_score"),
            "tradingagents_rating": item.get("deep_rating"),
            "tradingagents_direction": item.get("direction"),
            "tradingagents_score": item.get("ai_score"),
            "tradingagents_analysis": str(item.get("deep_analysis") or "")[:1800],
            "market_sources": item.get("market_sources") or [],
            "market_reasons": (item.get("market_reasons") or [])[:4],
            "market_flow": item.get("market_flow") or {},
            "stock_skill_evidence": item.get("stock_skill_evidence") or {},
        })
    lessons = [
        str(item.get("lesson") or "")[:500]
        for item in recent_learning[:8]
        if item.get("lesson")
    ]
    prompt = (
        "请对上一轮Codex-Terra多角色深度分析做独立终审。你只能确认或否决现有买入，"
        "绝不能把 Hold/Sell/Underweight 升级为买入。存在数据矛盾、追高、流动性、"
        "估值或证据不足时应 veto。只返回 JSON 数组，不要 Markdown："
        '[{"code":"000001.SZ","verdict":"approve|veto",'
        '"reason":"不超过50字","risk":"不超过30字"}]\n\n'
        "历史学习："
        + json.dumps(lessons, ensure_ascii=False)
        + "\n候选数据："
        + json.dumps(rows, ensure_ascii=False)
    )
    system_prompt = (
        "你是模拟交易的最终风险审查员。只能使用输入事实，不得联网或编造；"
        "单票正常仓位上限20%，终审结论必须逐只覆盖输入股票。"
    )
    request_payload = json.dumps(
        {"system_prompt": system_prompt, "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_sha256 = hashlib.sha256(request_payload.encode("utf-8")).hexdigest()
    input_fields = [
        "code", "name", "technical_score", "tradingagents_rating",
        "tradingagents_direction", "tradingagents_score",
        "tradingagents_analysis", "market_sources", "market_reasons",
        "market_flow", "stock_skill_evidence", "recent_learning",
    ]
    for decision in selected:
        decision["final_review_input_sha256"] = input_sha256
        decision["final_review_input_chars"] = len(request_payload)
        decision["final_review_input_count"] = len(rows)
        decision["final_review_input_fields"] = input_fields
    response = None
    error = ""
    try:
        response = await ai_router.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            primary_provider=primary_provider,
            allow_fallback=False,
        )
    except Exception as exc:
        error = str(exc)[:240]

    parsed = _extract_json_items(response.text) if response else []
    by_code = {_model_code_key(item.get("code")): item for item in parsed}
    matched = 0
    for decision in selected:
        review = by_code.get(_model_code_key(decision.get("stock_code")))
        verdict = str((review or {}).get("verdict") or "unavailable").strip().lower()
        if verdict not in {"approve", "veto"}:
            verdict = "unavailable"
        available = review is not None and verdict in {"approve", "veto"}
        if available:
            matched += 1
        decision["final_review_available"] = available
        decision["final_review_verdict"] = verdict
        decision["final_review_reason"] = str((review or {}).get("reason") or "")[:240]
        decision["final_review_risk"] = str((review or {}).get("risk") or "")[:160]
        decision["final_review_provider"] = getattr(response, "provider", "")
        decision["final_review_model"] = getattr(response, "model", "")
        decision["final_review_fallback_used"] = bool(
            getattr(response, "fallback_used", False)
        )
        decision["final_review_error"] = error

        requires_approval = bool(decision.get("final_review_required"))
        from src.ai_os.final_review import final_buy_approval

        # Approval is a strict truth table: only a Buy/Overweight deep rating
        # with an available, explicit approve verdict may enter the buy gate.
        # Hold/Sell/Underweight can never become approved by an unavailable or
        # malformed review response.
        decision["final_buy_approved"] = final_buy_approval(
            decision.get("deep_rating"),
            verdict,
            review_available=available,
        )
        if requires_approval and not decision["final_buy_approved"]:
            decision["direction"] = "neutral"
            decision["recommendation"] = "Hold"
            decision["ai_score"] = min(50.0, float(decision.get("ai_score") or 50))
            decision["decision_status"] = "review_blocked"

    return {
        "called": response is not None,
        "matched": matched,
        "provider": getattr(response, "provider", ""),
        "model": getattr(response, "model", ""),
        "fallback_used": bool(getattr(response, "fallback_used", False)),
        "error": error,
        "input_sha256": input_sha256,
        "input_chars": len(request_payload),
        "input_count": len(rows),
        "input_fields": input_fields,
    }


def _serialize_recommendation(decision: dict) -> dict:
    """Expose one auditable recommendation without leaking guarded ties."""
    return {
        "stock_code": decision["stock_code"],
        "stock_name": decision["stock_name"],
        "ai_score": round_finite(decision.get("ai_score"), 1, 0.0),
        "action_score": round(
            float(decision.get("action_score") or decision.get("ai_score") or 0),
            1,
        ),
        "ranking_score": round(
            float(decision.get("ranking_score") or decision.get("raw_ai_score") or 0),
            1,
        ),
        "raw_ai_score": decision.get("raw_ai_score", decision.get("ai_score")),
        "scanner_score": decision.get("scanner_score"),
        "preselection_base_score": decision.get("preselection_base_score"),
        "preselection_adjusted_score": decision.get("preselection_adjusted_score"),
        "preselection_input_sha256": decision.get("preselection_input_sha256", ""),
        "preselection_input_chars": decision.get("preselection_input_chars", 0),
        "preselection_input_count": decision.get("preselection_input_count", 0),
        "deep_base_score": decision.get("deep_base_score"),
        "deep_score": decision.get("deep_score"),
        "research_score": decision.get("research_score"),
        "primary_score": decision.get("primary_score"),
        "primary_score_label": decision.get("primary_score_label", "研究评分"),
        "ranking_score_label": decision.get("ranking_score_label", "机会排名分"),
        "display_state": decision.get("display_state", "research_pending"),
        "display_state_label": decision.get("display_state_label", "分析待完成"),
        "score_lineage": decision.get("score_lineage") or {},
        "score_guarded": decision.get("score_guarded", False),
        "score_guard_reasons": decision.get("score_guard_reasons", []),
        "publication_blocked": decision.get("publication_blocked", False),
        "publication_block_reasons": decision.get("publication_block_reasons", []),
        "recommendation_tier": decision.get("recommendation_tier", "unknown"),
        "actionable": decision.get("actionable", False),
        "deep_candidate_eligible": decision.get("deep_candidate_eligible", False),
        "deep_candidate_exclusion_reason": decision.get(
            "deep_candidate_exclusion_reason", ""
        ),
        "fundamental_evidence_available": decision.get(
            "fundamental_evidence_available", False
        ),
        "execution_evidence_complete": decision.get(
            "execution_evidence_complete", False
        ),
        "pre_gate_direction": decision.get("pre_gate_direction", ""),
        "flow_state": decision.get("flow_state", decision.get("flow_status", "")),
        "flow_sources": decision.get("flow_sources", []),
        "fallback_attempted": decision.get("fallback_attempted", False),
        "fallback_status": decision.get("fallback_status", ""),
        "gate_reasons": decision.get("gate_reasons", []),
        "non_flow_gates_passed": decision.get("non_flow_gates_passed", False),
        "execution_disposition": decision.get("execution_disposition", "blocked"),
        "execution_block_reason": decision.get("execution_block_reason", ""),
        "execution_status_label": decision.get(
            "execution_status_label", "等待执行确认"
        ),
        "execution_quote_verified": decision.get("execution_quote_verified", False),
        "market_evidence_complete": decision.get(
            "market_evidence_complete", False
        ),
        "market_evidence_sources": decision.get("market_evidence_sources", []),
        "market_evidence_reasons": decision.get("market_evidence_reasons", []),
        "evidence_enrichment": decision.get("evidence_enrichment", {}),
        "component_evidence_cache": decision.get("component_evidence_cache", {}),
        "universe_status": decision.get("universe_status", ""),
        "universe_reason_codes": decision.get("universe_reason_codes", []),
        "universe_industry": decision.get("universe_industry", ""),
        "evidence_status": decision.get("evidence_status", ""),
        "actionability_status": decision.get("actionability_status", ""),
        "decision_status": decision.get("decision_status", "unknown"),
        "predicted_direction": decision.get("predicted_direction", ""),
        "executable_direction": decision.get("executable_direction", ""),
        "direction": decision["direction"],
        "recommendation": decision["recommendation"],
        "analysis": decision.get("ai_analysis"),
        "deep_rating": decision.get("deep_rating"),
        "deep_analysis": decision.get("deep_analysis"),
        "deep_kline_evidence": decision.get("deep_kline_evidence", {}),
        "deep_evidence_consumption": decision.get(
            "deep_evidence_consumption", {}
        ),
        "deep_analysis_available": decision.get("deep_analysis_available", False),
        "deep_analysis_error": decision.get("deep_analysis_error", ""),
        "deep_evidence_gaps": decision.get("deep_evidence_gaps", []),
        "deep_provider": decision.get("deep_provider", ""),
        "deep_model": decision.get("deep_model", ""),
        "deep_source": decision.get("deep_source", ""),
        "deep_runtime": decision.get("deep_runtime", ""),
        "deep_cached": decision.get("deep_cached", False),
        "deep_duration_seconds": decision.get("deep_duration_seconds", 0),
        "deep_input_fingerprint": decision.get("deep_input_fingerprint", ""),
        "tradingagents_rating": decision.get("tradingagents_rating"),
        "final_review_available": decision.get("final_review_available", False),
        "final_review_verdict": decision.get("final_review_verdict", ""),
        "final_review_reason": decision.get("final_review_reason", ""),
        "final_review_risk": decision.get("final_review_risk", ""),
        "final_review_provider": decision.get("final_review_provider", ""),
        "final_review_model": decision.get("final_review_model", ""),
        "final_review_input_sha256": decision.get("final_review_input_sha256", ""),
        "final_review_input_chars": decision.get("final_review_input_chars", 0),
        "final_review_input_count": decision.get("final_review_input_count", 0),
        "final_buy_approved": decision.get("final_buy_approved", False),
        "ai_provider": decision.get("ai_provider"),
        "ai_model": decision.get("ai_model"),
        "ai_fallback_used": decision.get("ai_fallback_used", False),
        "technical_score": decision.get("technical_score"),
        "discovery_score": decision.get("discovery_score"),
        "learning_adjustment": decision.get("learning_adjustment", 0),
        "market_sources": decision.get("market_sources", []),
        "market_reasons": decision.get("market_reasons", []),
        "stock_skill_evidence": decision.get("stock_skill_evidence") or {},
        "technical_data_through": decision.get("technical_data_through", ""),
        "run_id": decision.get("run_id", ""),
        "strategy_version": decision.get("strategy_version", ""),
        "config_hash": decision.get("config_hash", ""),
        "code_hash": decision.get("code_hash", ""),
    }


def _market_data_block_reasons(
    selection_mode: str,
    discovery_snapshot: Any,
    stocks_scanned: int,
    signals_computed: int,
    latest_local_data_date: str,
    technical_data_dates: set[str],
    policy_excluded_count: int = 0,
) -> list[str]:
    """Return fail-closed reasons for publishing a normal recommendation list."""
    if not selection_mode.startswith("full_market"):
        return []

    reasons: list[str] = []
    if discovery_snapshot is None or not discovery_snapshot.remote_available:
        reasons.append("market_data_unavailable")
    elif discovery_snapshot.degraded:
        reasons.append("market_data_degraded")

    eligible_scanned = max(0, stocks_scanned - max(0, policy_excluded_count))
    if eligible_scanned <= 0 or signals_computed / max(eligible_scanned, 1) < 0.95:
        reasons.append("technical_scan_incomplete")
    if (
        not technical_data_dates
        or latest_local_data_date and max(technical_data_dates) < latest_local_data_date
    ):
        reasons.append("technical_data_stale")
    return list(dict.fromkeys(reasons))


def _causal_daily_bars(
    bars: list[dict], observed_at: datetime | None = None
) -> list[dict]:
    """Exclude incomplete or future daily candles from a live decision."""
    observed = observed_at or datetime.now().astimezone()
    local = observed.astimezone(CHINA_TZ)
    today = local.date().isoformat()
    include_today = local.time().replace(tzinfo=None) >= dt_time(15, 5)
    causal: list[dict] = []
    for bar in bars or []:
        bar_date = str(bar.get("date") or bar.get("trade_date") or "")[:10]
        if not bar_date:
            continue
        if bar_date < today or (include_today and bar_date == today):
            causal.append(bar)
    return causal


def _execution_candidates(
    decisions: list[dict],
    held_codes: set[str] | list[str] | tuple[str, ...],
    observation_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    """Select only decisions that can change the paper portfolio.

    A scan can persist hundreds of ranked decisions, but execution only needs
    a fresh quote for actionable buys and current holdings. Fetching all 300
    quotes creates unnecessary batches and lets the first batch age before
    the final batch is validated.
    """
    held = {str(code or "").strip().upper() for code in held_codes}
    observation_scope = (
        {str(code or "").strip().upper() for code in observation_codes}
        if observation_codes is not None else None
    )
    selected: list[dict] = []
    seen: set[str] = set()
    for decision in decisions:
        code = str(decision.get("stock_code") or "").strip().upper()
        actionable = code in held or (
            decision.get("actionable")
            if "actionable" in decision
            else is_deep_buy_approved(decision)
        ) or is_deep_buy_approved(decision)
        if actionable and code and code not in seen:
            selected.append(decision)
            seen.add(code)
    probe_candidates = sorted(
        (
            decision
            for decision in decisions
            if (
                observation_scope is None
                or str(decision.get("stock_code") or "").strip().upper()
                in observation_scope
            )
            and is_flow_probe_candidate(decision)
        ),
        key=lambda item: float(
            item.get("action_score")
            or item.get("ranking_score")
            or item.get("ai_score")
            or 0
        ),
        reverse=True,
    )[:PAPER_MOMENTUM_PROBE_MAX_CANDIDATES]
    for decision in probe_candidates:
        code = str(decision.get("stock_code") or "").strip().upper()
        if code and code not in seen:
            selected.append(decision)
            seen.add(code)
    # Keep the historical momentum lane available only for non-strict replay
    # callers.  Strict production execution uses the flow-specific lane above.
    legacy_probe_candidates = sorted(
        (
            decision
            for decision in decisions
            if (
                observation_scope is None
                or str(decision.get("stock_code") or "").strip().upper()
                in observation_scope
            )
            and is_momentum_probe_candidate(decision)
            and not is_flow_probe_candidate(decision)
        ),
        key=momentum_probe_rank,
        reverse=True,
    )[:PAPER_MOMENTUM_PROBE_MAX_CANDIDATES]
    for decision in legacy_probe_candidates:
        code = str(decision.get("stock_code") or "").strip().upper()
        if code and code not in seen:
            selected.append(decision)
            seen.add(code)
    conditional_candidates = sorted(
        (
            decision
            for decision in decisions
            if (
                observation_scope is None
                or str(decision.get("stock_code") or "").strip().upper()
                in observation_scope
            )
            and is_conditional_probe_candidate(decision)
            and not is_flow_probe_candidate(decision)
            and not is_momentum_probe_candidate(decision)
        ),
        key=conditional_probe_rank,
        reverse=True,
    )[:PAPER_CONDITIONAL_BUY_MAX_CANDIDATES]
    for decision in conditional_candidates:
        code = str(decision.get("stock_code") or "").strip().upper()
        if code and code not in seen:
            selected.append(decision)
            seen.add(code)
    return selected


def _apply_current_execution_metadata(
    decisions: list[dict], metadata_by_code: dict[str, dict]
) -> None:
    """Overlay only current tradability fields before opening execution."""
    for decision in decisions:
        code = str(decision.get("stock_code") or "").strip().upper()
        metadata = metadata_by_code.get(code) or {}
        for field in ("status", "is_st", "is_suspended", "delist_date"):
            if field in metadata:
                decision[field] = metadata[field]


def _include_held_decisions(
    shortlist: list[dict],
    all_scored: list[dict],
    held_codes: set[str] | list[str] | tuple[str, ...],
) -> list[dict]:
    """Append every scored holding even when it ranks below the shortlist."""
    selected = list(shortlist)
    seen = {
        str(item.get("stock_code") or "").strip().upper()
        for item in selected
    }
    by_code = {
        str(item.get("stock_code") or "").strip().upper(): item
        for item in all_scored
        if item.get("stock_code")
    }
    for code in held_codes:
        normalized = str(code or "").strip().upper()
        if normalized and normalized not in seen and normalized in by_code:
            selected.append(by_code[normalized])
            seen.add(normalized)
    return selected


def _add_held_risk_decisions(
    decisions: list[dict],
    held_positions: list[dict],
    *,
    trade_date: str,
    signal_at: str,
    data_cutoff_at: str,
) -> list[dict]:
    """Ensure every holding reaches the independent exit-risk evaluator."""
    selected = list(decisions)
    seen = {
        str(item.get("stock_code") or "").strip().upper()
        for item in selected
    }
    for position in held_positions:
        code = str(position.get("stock_code") or "").strip().upper()
        if not code:
            continue
        entry_identity = {
            "entry_decision_id": position.get("entry_decision_id"),
            "entry_strategy_version": position.get("entry_strategy_version") or "",
            "entry_deep_rating": position.get("entry_deep_rating") or "",
            "entry_identity_status": position.get(
                "entry_identity_status", "legacy_unverified"
            ),
            "execution_tier": position.get("execution_tier") or "normal",
            "entry_flow_state": position.get("entry_flow_state") or "",
            "entry_fallback_status": position.get("entry_fallback_status") or "",
            "entry_gate_reasons": position.get("entry_gate_reasons") or [],
            "probe_expiry_date": position.get("probe_expiry_date") or "",
            "promotion_status": position.get("promotion_status") or "none",
        }
        if code in seen:
            for decision in selected:
                if str(decision.get("stock_code") or "").strip().upper() == code:
                    decision.update(entry_identity)
                    decision["position_risk_review"] = True
                    break
            continue
        selected.append({
            "stock_code": code,
            "stock_name": position.get("stock_name") or code,
            "date": trade_date,
            "decision_date": trade_date,
            "signal_at": signal_at,
            "data_cutoff_at": data_cutoff_at,
            "ai_score": 50.0,
            "action_score": 0.0,
            "direction": "neutral",
            "recommendation": "Hold",
            "decision_status": "held_risk_review_fallback",
            "position_risk_review": True,
            **entry_identity,
            "actionable": False,
            "evidence": "{}",
        })
        seen.add(code)
    return selected


async def _execute_paper_cycle(
    decisions: list[dict],
    *,
    execute_paper_trades: bool,
    intraday_monitor: bool = False,
) -> dict:
    """Mark the portfolio and execute only already-produced decisions.

    Discovery and execution intentionally have different latency budgets. A
    full-market scan may take minutes, while the market-open task must consume
    the persisted plan and obtain a post-signal quote quickly. Keeping the
    causal execution block in one helper lets both paths use identical quote
    and ledger checks without rerunning the 5,200-stock scan.
    """
    from config.settings import settings
    from src.ai_os.causal_execution import (
        fetch_post_signal_quotes,
        in_a_share_session,
    )
    from src.ai_os.portfolio_marking import refresh_paper_portfolio_quotes
    from src.ai_os.trading_calendar import (
        get_trading_day_status,
        paper_execution_calendar_verified,
    )
    from src.infrastructure.storage.market_database import market_db

    now_iso = datetime.now().astimezone().isoformat()
    paper_positions = market_db.get_paper_portfolio().get("positions") or []
    decisions = _add_held_risk_decisions(
        decisions,
        paper_positions,
        trade_date=date.today().isoformat(),
        signal_at=now_iso,
        data_cutoff_at=now_iso,
    )
    # The minute monitor only executes a bounded candidate set.  Refreshing
    # metadata for every persisted scan row here made one cycle longer than a
    # minute, so APScheduler skipped the next run (max_instances=1).  Keep the
    # same metadata gate, but scope the refresh to the exact execution lane.
    if execute_paper_trades and intraday_monitor:
        held_codes = {
            str(position.get("stock_code") or "").strip().upper()
            for position in paper_positions
            if position.get("stock_code")
        }
        monitor_metadata_decisions = _execution_candidates(
            decisions,
            held_codes,
            observation_codes=None,
        )
        metadata_codes = sorted({
            str(decision.get("stock_code") or "").strip().upper()
            for decision in monitor_metadata_decisions
            if decision.get("stock_code")
        })
    else:
        metadata_codes = sorted({
            str(decision.get("stock_code") or "").strip().upper()
            for decision in decisions
            if decision.get("stock_code")
        })
    metadata_date = date.today().isoformat()
    # The minute monitor must not call BaoStock for the same metadata on every
    # tick.  The opening/scan paths keep the authoritative refresh, while the
    # monitor reuses the point-in-time snapshot and only fills genuinely
    # missing codes.  An empty candidate set must also avoid the database
    # method's "codes=None means full universe" behavior.
    current_metadata = await asyncio.to_thread(
        market_db.get_stock_metadata_snapshot,
        metadata_date,
    )
    missing_metadata_codes = [
        code for code in metadata_codes if code not in current_metadata
    ]
    if not metadata_codes:
        status_snapshot = {
            "status": "no_execution_candidates",
            "as_of_date": metadata_date,
            "stock_count": 0,
            "stored_count": 0,
            "errors": [],
        }
    elif not intraday_monitor or missing_metadata_codes:
        status_snapshot = await asyncio.to_thread(
            market_db.sync_stock_metadata_snapshot,
            metadata_date,
            codes=metadata_codes if not intraday_monitor else missing_metadata_codes,
        )
        current_metadata = await asyncio.to_thread(
            market_db.get_stock_metadata_snapshot,
            metadata_date,
        )
    else:
        status_snapshot = {
            "status": "cached",
            "as_of_date": metadata_date,
            "stock_count": len(metadata_codes),
            "stored_count": len(metadata_codes),
            "errors": [],
        }
    _apply_current_execution_metadata(decisions, current_metadata)
    pre_trade_mark = await refresh_paper_portfolio_quotes()
    for decision in decisions:
        decision["market_price"] = 0.0
        decision["market_price_date"] = ""
        decision["market_price_source"] = ""
        decision["market_price_fetched_at"] = ""
        decision["market_price_exchange_at"] = ""
        decision["market_price_source_lag_seconds"] = None
        decision["market_price_causality_status"] = "unverified"
        decision["execution_quote_verified"] = False
        decision["market_change_pct"] = 0.0
        decision["market_volume_ratio"] = 0.0
        decision["market_active_volume_ratio"] = None

    execution_quotes: dict[str, dict] = {}
    causal_rejections: list[dict] = []
    execution_decisions: list[dict] = []
    execution_requested_at = datetime.now().astimezone()
    trading_day_status = await get_trading_day_status(date.today())
    trading_day_verified = False
    if execute_paper_trades:
        # A weekday fallback may attempt execution, but a fill still requires
        # a current exchange timestamp strictly after the frozen signal.
        trading_day_verified = paper_execution_calendar_verified(trading_day_status)
        if not trading_day_verified:
            causal_reason = "trading_calendar_unverified"
        elif not trading_day_status.is_trading_day:
            causal_reason = "market_holiday"
        elif not in_a_share_session(execution_requested_at):
            causal_reason = "execution_requested_outside_market_session"
        else:
            causal_reason = ""

        held_codes = {
            str(position.get("stock_code") or "").strip().upper()
            for position in market_db.get_paper_portfolio().get("positions", [])
        }
        if intraday_monitor:
            # Recheck every persisted probe candidate during the minute loop.
            # The helper still applies per-lane caps, so this broadens quote
            # coverage without rescanning the universe or changing sizing.
            observation_codes = None
        else:
            observation_limit = max(
                1, int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_COUNT", 5))
            )
            observation_codes = {
                str(item.get("stock_code") or "").strip().upper()
                for item in decisions[:observation_limit]
                if item.get("stock_code")
            }
        execution_decisions = _execution_candidates(
            decisions, held_codes, observation_codes=observation_codes
        )
        if not causal_reason and execution_decisions:
            from src.infrastructure.market_data.remote_market_discovery import (
                RemoteMarketDiscovery,
            )

            execution_source = RemoteMarketDiscovery(
                timeout_seconds=settings.REMOTE_MARKET_TIMEOUT_SECONDS,
                stock_skill_enabled=getattr(
                    settings, "STOCK_SKILL_BRIDGE_ENABLED", True
                ),
            )
            quote_attempts = getattr(settings, "PAPER_EXECUTION_QUOTE_ATTEMPTS", 8)
            quote_retry_delay = getattr(
                settings, "PAPER_EXECUTION_QUOTE_RETRY_DELAY_SECONDS", 1.25
            )
            if intraday_monitor:
                # A minute loop needs a bounded retry budget.  The provider
                # fallback above handles source diversity; repeated long
                # batches only cause the next scheduled minute to be skipped.
                quote_attempts = min(3, max(1, int(quote_attempts)))
                quote_retry_delay = min(0.5, max(0.0, float(quote_retry_delay)))
            execution_quotes, causal_rejections = await fetch_post_signal_quotes(
                execution_decisions,
                execution_source.fetch_live_quotes,
                attempts=quote_attempts,
                retry_delay_seconds=quote_retry_delay,
            )
        elif causal_reason:
            causal_rejections = [
                {
                    "stock_code": decision.get("stock_code", ""),
                    "signal_at": decision.get("signal_at", ""),
                    "data_cutoff_at": decision.get("data_cutoff_at", ""),
                    "reason": causal_reason,
                }
                for decision in execution_decisions
            ]

    # Preserve the causal fetch result on the decision passed to the ledger.
    # Previously a missing quote was flattened to blank fields, so the ledger
    # could only report generic stale/future-date failures and hid whether the
    # provider was absent, late, or rejected by the timestamp gate.
    causal_reason_by_code = {
        str(item.get("stock_code") or "").strip().upper(): str(
            item.get("reason") or "missing_execution_quote"
        )
        for item in causal_rejections
    }
    for decision in execution_decisions:
        code = str(decision.get("stock_code") or "").strip().upper()
        if code in causal_reason_by_code and code not in execution_quotes:
            decision["execution_quote_rejection_reason"] = causal_reason_by_code[code]

    for decision in decisions:
        quote = execution_quotes.get(decision["stock_code"])
        if not quote:
            continue
        decision["market_price"] = float(quote.get("price") or 0)
        decision["market_price_date"] = str(quote.get("data_date") or "")
        decision["market_price_source"] = str(quote.get("source") or "")
        decision["market_price_fetched_at"] = str(quote.get("fetched_at") or "")
        decision["market_price_exchange_at"] = str(quote.get("exchange_at") or "")
        decision["market_price_source_lag_seconds"] = quote.get(
            "source_lag_seconds"
        )
        decision["market_price_causality_status"] = str(
            quote.get("causality_status") or ""
        )
        decision["execution_quote_verified"] = (
            decision["market_price_causality_status"] == "verified_post_signal_quote"
        )
        decision["market_change_pct"] = float(quote.get("change_pct") or 0)
        decision["market_volume_ratio"] = float(
            quote.get("volume_ratio") or quote.get("vol_ratio") or 0
        )
        active_ratio = quote.get("active_volume_ratio")
        decision["market_active_volume_ratio"] = (
            float(active_ratio) if active_ratio is not None else None
        )

    if execute_paper_trades:
        simulated_fill_requested_at = datetime.now().astimezone()
        from src.ai_os.paper_execution_service import paper_execution_service

        # The opening path retains its historical full-decision audit.  The
        # minute path must pass only the bounded execution candidates; sending
        # all 300 persisted decisions to the ledger created hundreds of
        # rejection rows per tick and made the next minute miss its deadline.
        paper_decisions = execution_decisions if intraday_monitor else decisions
        paper_result = await asyncio.to_thread(
            paper_execution_service.execute,
            paper_decisions,
            date.today().isoformat(),
            initial_capital=100000.0,
            max_position_pct=settings.MAX_POSITION_PCT,
            execution_timestamp=simulated_fill_requested_at.isoformat(),
            trading_day_verified=trading_day_verified,
            is_trading_day=trading_day_status.is_trading_day,
            trading_calendar_source=trading_day_status.source,
        )
        portfolio_mark = await refresh_paper_portfolio_quotes()
    else:
        portfolio_mark = pre_trade_mark
        paper = market_db.get_paper_portfolio()
        paper_result = {
            "actions": [],
            "cash": paper.get("cash", 100000.0),
            "position_count": len(paper.get("positions") or []),
            "execution_status": "deferred_until_market_session",
            "execution_at": execution_requested_at.isoformat(),
            "rejections": [],
        }

    return {
        "paper_result": paper_result,
        "pre_trade_portfolio_mark": pre_trade_mark,
        "portfolio_mark": portfolio_mark,
        "execution_quotes": execution_quotes,
        "execution_decisions": execution_decisions,
        "causal_rejections": causal_rejections,
        "trading_calendar_source": trading_day_status.source,
        "trading_calendar_verified": trading_day_verified,
        "trading_status_snapshot": status_snapshot,
        "intraday_monitor": intraday_monitor,
    }


@dataclass
class PipelineResult:
    """Result of one pipeline run."""
    run_date: str = ""
    run_id: str = ""
    strategy_version: str = ""
    stocks_scanned: int = 0
    signals_computed: int = 0
    decisions_generated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    top_picks: list[dict] = field(default_factory=list)
    actionable_picks: list[dict] = field(default_factory=list)
    paper_trades: list[dict] = field(default_factory=list)
    paper_cash: float = 100000.0
    paper_position_count: int = 0
    candidate_source: str = ""
    remote_data_used: bool = False
    technical_universe_size: int = 0
    technical_shortlist_size: int = 0
    ai_preselection_count: int = 0
    deep_analysis_count: int = 0
    final_review_count: int = 0
    market_data_quality: dict = field(default_factory=dict)
    learning_profile: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_date": self.run_date,
            "run_id": self.run_id,
            "strategy_version": self.strategy_version,
            "stocks_scanned": self.stocks_scanned,
            "signals_computed": self.signals_computed,
            "decisions_generated": self.decisions_generated,
            "errors": self.errors[:5],
            "duration_seconds": round(self.duration_seconds, 1),
            "top_picks": self.top_picks[:10],
            "actionable_picks": self.actionable_picks[:10],
            "paper_trades": self.paper_trades,
            "paper_cash": round(self.paper_cash, 2),
            "paper_position_count": self.paper_position_count,
            "candidate_source": self.candidate_source,
            "remote_data_used": self.remote_data_used,
            "technical_universe_size": self.technical_universe_size,
            "technical_shortlist_size": self.technical_shortlist_size,
            "ai_preselection_count": self.ai_preselection_count,
            "deep_analysis_count": self.deep_analysis_count,
            "final_review_count": self.final_review_count,
            "market_data_quality": self.market_data_quality,
            "learning_profile": self.learning_profile,
        }


class AIPipelineRunner:
    """Orchestrates the daily AI decision pipeline.

    Single entry point. Call run_daily_pipeline() once per day.
    Results are persisted: Dashboard/Decision/Journal read from DB.
    """

    # Default stock universe — scanned every day
    def __init__(self) -> None:
        self._run_lock = asyncio.Lock()

    async def run_daily_pipeline(
        self,
        codes: list[str] = None,
        save_to_journal: bool = True,
        execute_paper_trades: bool | None = None,
        force_reanalysis: bool = False,
        research_window: str = "manual",
    ) -> PipelineResult:
        """Serialize runs and only execute fills during a live session.

        Manual/API calls are time-aware when the flag is omitted: a pre-market
        scan persists decisions and defers fills until a market-session task.
        Scheduled market-open and afternoon tasks pass ``True`` explicitly.
        ``force_reanalysis`` bypasses same-day deep-analysis cache and budget
        only when explicitly requested; it never enables paper execution.
        """
        if execute_paper_trades is None:
            from src.ai_os.causal_execution import in_a_share_session

            execute_paper_trades = in_a_share_session(datetime.now().astimezone())
        async with self._run_lock:
            kwargs = {
                "execute_paper_trades": execute_paper_trades,
                "force_reanalysis": force_reanalysis,
            }
            if str(research_window or "manual").strip().lower() != "manual":
                kwargs["research_window"] = research_window
            return await self._run_daily_pipeline_once(
                codes, save_to_journal, **kwargs
            )

    async def execute_persisted_strategy(
        self, *, intraday_monitor: bool = False,
    ) -> dict:
        """Execute today's persisted plan without rescanning the market.

        The continuous intraday task uses the same frozen decisions and paper
        safeguards, but broadens live-quote coverage to all persisted probe
        candidates so a watchlist signal can trigger later in the session.
        """
        from src.api.routes.journal_utils import latest_per_stock
        from src.infrastructure.storage.market_database import market_db

        async def execute_locked(*, intraday_monitor: bool) -> dict:
            """Execute a frozen plan after the caller has acquired ``_run_lock``."""
            trade_date = date.today().isoformat()
            decisions = latest_per_stock(
                market_db.get_decisions_for_date(trade_date, limit=5000)
            )
            source_decision_count = len(decisions)
            if not decisions:
                paper = market_db.get_paper_portfolio()
                held_positions = paper.get("positions") or []
                if not held_positions:
                    return {
                        "status": "no_persisted_decisions",
                        "run_date": trade_date,
                        "source_decision_count": 0,
                        "paper_trades": [],
                        "paper_cash": paper.get("cash", 100000.0),
                        "paper_position_count": 0,
                        "paper_execution": {
                            "status": "not_executed",
                            "reason": "overnight_scan_missing",
                        },
                    }

                # A missing overnight plan must not disable risk management
                # for already-held positions. This fallback contains no buy
                # candidates; it only lets the normal exit rules inspect each
                # holding with a fresh post-signal quote.
                fallback_at = datetime.now().astimezone().isoformat()
                decisions = _add_held_risk_decisions(
                    [],
                    held_positions,
                    trade_date=trade_date,
                    signal_at=fallback_at,
                    data_cutoff_at=fallback_at,
                )
                fallback_mode = True
            else:
                fallback_mode = False

            # Journal rows store the immutable signal timestamp as created_at.
            # Restore the aliases expected by the causality guard.
            if not fallback_mode:
                for decision in decisions:
                    frozen_at = str(decision.get("created_at") or "")
                    decision["date"] = str(
                        decision.get("decision_date") or trade_date
                    )
                    decision["data_cutoff_at"] = frozen_at
                    decision["signal_at"] = frozen_at

            cycle = await _execute_paper_cycle(
                decisions,
                execute_paper_trades=True,
                intraday_monitor=intraday_monitor,
            )
            paper_result = cycle["paper_result"]
            if paper_result["actions"]:
                market_db.save_learning(
                    trade_date,
                    "execution",
                    "今日根据凌晨策略执行纸面交易：" + ", ".join(
                        f"{action['action']} {action['stock_code']} "
                        f"{action['shares']}股"
                        for action in paper_result["actions"]
                    ),
                    {
                        "actions": paper_result["actions"],
                        "cash": paper_result["cash"],
                        "execution_mode": "persisted_overnight_plan",
                    },
                )
            return {
                "status": (
                    "executed_held_risk_fallback"
                    if fallback_mode
                    else "executed_persisted_plan"
                ),
                "run_date": trade_date,
                "source_decision_count": source_decision_count,
                "paper_trades": paper_result["actions"],
                "paper_cash": paper_result["cash"],
                "paper_position_count": paper_result["position_count"],
                "paper_execution": {
                    "status": paper_result.get("execution_status"),
                    "execution_at": paper_result.get("execution_at"),
                    "causal_quote_count": len(cycle["execution_quotes"]),
                    "execution_candidate_count": len(
                        cycle["execution_decisions"]
                    ),
                    "trading_calendar_source": cycle[
                        "trading_calendar_source"
                    ],
                    "trading_calendar_verified": cycle[
                        "trading_calendar_verified"
                    ],
                    "trading_status_snapshot": cycle.get(
                        "trading_status_snapshot", {}
                    ),
                    "intraday_monitor": intraday_monitor,
                    "observation_scope": (
                        "all_persisted_probe_candidates"
                        if intraday_monitor else "configured_probe_scope"
                    ),
                    "causal_quote_rejections": cycle["causal_rejections"],
                    "rejections": paper_result.get("rejections", []),
                },
                "pre_trade_portfolio_mark": cycle[
                    "pre_trade_portfolio_mark"
                ],
                "portfolio_mark": cycle["portfolio_mark"],
            }

        # The minute monitor shares the pipeline lock with the scheduled
        # opening/afternoon runs. It must never wait for or hold that lock:
        # waiting would make APScheduler skip the next minute, while holding it
        # during a slow provider call could delay the next full phase. A busy
        # full run is a normal, safe outcome; the next tick retries the same
        # frozen plan.
        if intraday_monitor:
            if self._run_lock.locked():
                return {
                    "status": "intraday_monitor_deferred_pipeline_busy",
                    "paper_trades": [],
                    "paper_execution": {
                        "execution_status": "deferred_pipeline_busy",
                    },
                }
            return await execute_locked(intraday_monitor=True)

        async with self._run_lock:
            return await execute_locked(intraday_monitor=False)

    async def _run_daily_pipeline_once(
        self,
        codes: list[str] = None,
        save_to_journal: bool = True,
        execute_paper_trades: bool = True,
        force_reanalysis: bool = False,
        research_window: str = "manual",
    ) -> PipelineResult:
        """Run the full daily AI decision pipeline.

        1. Scan the full local A-share universe with real daily bars
        2. Compute deterministic signals (MACD/RSI/KDJ/MA/Volume)
        3. Keep a bounded technical shortlist and enrich it with remote data
        4. Run one batched Codex preselection, then Codex-Terra on Top N
        5. Save decisions and paper-trading outcomes to the journal

        Args:
            codes: Stock codes to scan. None = default universe.
            save_to_journal: Whether to persist decisions to DB.

        Returns:
            PipelineResult with summary stats and top picks.
        """
        from config.settings import settings
        from src.infrastructure.market_data.real_data_provider import real_data
        from src.infrastructure.storage.market_database import market_db

        run_metadata = create_strategy_run_metadata(settings)
        normalized_window = str(research_window or "manual").strip().lower()
        if normalized_window not in {"morning", "midday", "manual"}:
            normalized_window = "manual"
        universe_policy = config_from_settings(settings)
        held_codes = {
            str(position.get("stock_code") or "").strip().upper()
            for position in market_db.get_paper_portfolio().get("positions", [])
            if position.get("stock_code")
        }
        universe_assessments = {}
        universe_reason_counts: dict[str, int] = {}
        universe_excluded_count = 0
        universe_review_only_count = 0

        universe_by_code = {}
        discovery_by_code: dict[str, dict] = {}
        discovery_snapshot = None
        selection_mode = "explicit_codes"
        if codes is None:
            # The daily pipeline starts from the broad local, auditable
            # universe. The scheduled sync task populates this cache from
            # BaoStock; the provider can still fetch the symbol list remotely
            # when the cache is empty. Remote discovery enriches the shortlist
            # but no longer replaces the full-market technical pass.
            selection_mode = "full_market_technical"
            universe = await real_data.get_stock_universe(
                min_count=settings.SCANNER_FULL_UNIVERSE_COUNT
            )
            universe_by_code = {s["code"]: s for s in universe if s.get("code")}
            codes = list(universe_by_code)

            if settings.REMOTE_MARKET_DISCOVERY_ENABLED:
                from src.infrastructure.market_data.remote_market_discovery import (
                    RemoteMarketDiscovery,
                )

                discovery = RemoteMarketDiscovery(
                    timeout_seconds=settings.REMOTE_MARKET_TIMEOUT_SECONDS,
                    stock_skill_enabled=getattr(
                        settings, "STOCK_SKILL_BRIDGE_ENABLED", True
                    ),
                    max_quote_count=getattr(
                        settings, "STOCK_SKILL_MAX_QUOTE_COUNT", 300
                    ),
                )
                discovery_snapshot = await discovery.discover(
                    date.today().isoformat(),
                    limit=settings.REMOTE_MARKET_CANDIDATE_LIMIT,
                )
                discovery_by_code = {
                    item["stock_code"]: item for item in discovery_snapshot.candidates
                }
                if discovery_snapshot.remote_available:
                    selection_mode = "full_market_technical_plus_remote"

            if not codes:
                selection_mode = "full_market_unavailable"

            # Always label held stocks for daily risk review. This label must
            # also be added when the symbol already exists in the 6k universe;
            # otherwise a neutral holding can be filtered out before the sell
            # gate ever sees it.
            paper = market_db.get_paper_portfolio()
            for position in paper.get("positions", []):
                code = position.get("stock_code")
                if code and code not in codes:
                    codes.append(code)
                    universe_by_code[code] = {
                        "code": code,
                        "name": position.get("stock_name") or code,
                    }
                if code:
                    review = dict(discovery_by_code.get(code) or {
                        "stock_code": code,
                        "stock_name": position.get("stock_name") or code,
                        "source_ranks": {},
                        "concepts": [],
                        "discovery_score": 50.0,
                        "score_breakdown": {},
                        "quote": {"price": position.get("current_price")},
                        "fund_flow": {},
                    })
                    sources = list(review.get("sources") or [])
                    if "portfolio_review" not in sources:
                        sources.append("portfolio_review")
                    reasons = list(review.get("reasons") or [])
                    review_reason = "当前纸面持仓，强制进入每日风险复核"
                    if review_reason not in reasons:
                        reasons.append(review_reason)
                    review["sources"] = sources
                    review["reasons"] = reasons
                    discovery_by_code[code] = review

        result = PipelineResult(
            run_date=date.today().isoformat(),
            run_id=run_metadata["run_id"],
            strategy_version=run_metadata["strategy_version"],
        )
        result.candidate_source = selection_mode
        result.remote_data_used = bool(discovery_snapshot and discovery_snapshot.remote_available)
        latest_local_data_date = ""
        current_metadata_by_code: dict[str, dict] = {}
        if selection_mode.startswith("full_market"):
            stats = await asyncio.to_thread(market_db.get_stats)
            latest_local_data_date = str(stats.get("latest_data_date") or "")
            current_metadata_by_code = await asyncio.to_thread(
                market_db.get_stock_metadata_snapshot,
                latest_local_data_date,
            )
        if discovery_snapshot:
            result.market_data_quality = {
                "version": discovery_snapshot.version,
                "fetched_at": discovery_snapshot.fetched_at,
                "source_counts": discovery_snapshot.source_counts,
                "candidate_count": len(discovery_snapshot.candidates),
                "degraded": discovery_snapshot.degraded,
                "errors": discovery_snapshot.errors[:10],
                "stock_skill_fallback": discovery_snapshot.stock_skill_fallback,
                "bars_scan_mode": "local_first_cache",
                "latest_local_data_date": latest_local_data_date,
            }
        else:
            result.market_data_quality = {
                "candidate_count": len(codes or []),
                "degraded": selection_mode != "explicit_codes",
                "bars_scan_mode": "local_first_cache",
                "latest_local_data_date": latest_local_data_date,
            }
        result.market_data_quality.update({
            "run_id": run_metadata["run_id"],
            "strategy_name": run_metadata["strategy_name"],
            "strategy_version": run_metadata["strategy_version"],
            "config_snapshot": run_metadata["config_snapshot"],
            "config_hash": run_metadata["config_hash"],
            "code_hash": run_metadata["code_hash"],
            "run_created_at": run_metadata["run_created_at"],
        })
        result.technical_universe_size = len(codes or [])
        learning_profiles = {
            horizon: await asyncio.to_thread(
                market_db.get_market_learning_profile,
                horizon_days=horizon,
                decay_half_life_days=getattr(
                    settings, "RESEARCH_MEMORY_DECAY_DAYS", 90
                ),
            )
            for horizon in (1, 5, 20)
        }
        learning_profile = learning_profiles[1]
        result.learning_profile = {
            "horizon_days": 1,
            "total_observations": learning_profile.get("total_observations", 0),
            "decisive_observations": learning_profile.get("decisive_observations", 0),
            "learned_symbols": len(learning_profile.get("by_symbol") or {}),
            "learned_sources": len(learning_profile.get("by_source") or {}),
            "horizons": {
                str(horizon): {
                    "total_observations": profile.get("total_observations", 0),
                    "decisive_observations": profile.get("decisive_observations", 0),
                    "accuracy_available": profile.get("accuracy_available", False),
                }
                for horizon, profile in learning_profiles.items()
            },
        }
        t0 = time.time()
        decisions = []
        technical_data_dates: set[str] = set()

        for index, code in enumerate(codes):
            try:
                name = universe_by_code.get(code, {}).get("name", code)
                discovery_item = discovery_by_code.get(code) or {}
                name = discovery_item.get("stock_name") or name
                if selection_mode.startswith("full_market"):
                    # Keep synchronous SQLite reads off FastAPI's event loop.
                    # Otherwise a slow 5k-stock pass also prevents the outer
                    # asyncio timeout and health endpoints from being scheduled.
                    bars = await asyncio.to_thread(
                        market_db.get_daily_bars, code, 250
                    )
                else:
                    bars = await real_data.get_daily_bars(
                        code, days=250, prefer_remote=False
                    )
                result.stocks_scanned += 1

                bars = _causal_daily_bars(bars or [])
                if len(bars) < 20:
                    continue
                technical_data_date = str(
                    bars[-1].get("date") or bars[-1].get("trade_date") or ""
                )
                if technical_data_date:
                    technical_data_dates.add(technical_data_date)

                stock_context = dict(universe_by_code.get(code) or {})
                current_metadata = current_metadata_by_code.get(code) or {}
                stock_context.update({
                    key: current_metadata[key]
                    for key in (
                        "status", "is_st", "is_suspended", "list_date",
                        "delist_date", "industry", "market_cap_yi",
                    )
                    if current_metadata.get(key) not in (None, "")
                })
                stock_context.update({"code": code, "name": name})
                assessment = assess_stock(
                    stock_context,
                    bars,
                    as_of_date=(
                        latest_local_data_date
                        or technical_data_date
                        or date.today().isoformat()
                    ),
                    config=universe_policy,
                )
                normalized_code = str(code or "").strip().upper()
                universe_assessments[normalized_code] = assessment
                for reason in assessment.reason_codes:
                    universe_reason_counts[reason] = (
                        universe_reason_counts.get(reason, 0) + 1
                    )
                if assessment.status == "excluded" and normalized_code not in held_codes:
                    universe_excluded_count += 1
                    continue
                if assessment.status == "review_only":
                    universe_review_only_count += 1

                sig = await asyncio.to_thread(
                    real_data.compute_signals, code, name, bars
                )
                result.signals_computed += 1

                sources = list(discovery_item.get("sources") or [])
                learned = multi_horizon_learning_adjustment(
                    learning_profiles, code, sources
                )
                technical_score = float(sig.fusion_score)
                discovery_score = float(discovery_item.get("discovery_score", 50.0))
                if discovery_item:
                    base_score = 0.55 * technical_score + 0.45 * discovery_score
                else:
                    base_score = technical_score
                adaptive_score = max(
                    0.0,
                    min(100.0, base_score + float(learned["score_adjustment"])),
                )

                flow = discovery_item.get("fund_flow") or {}
                decision_flow_status = flow_status({"market_flow": flow})
                decision_flow_positive = flow_positive({"market_flow": flow})
                buy_gate = (
                    adaptive_score >= 65
                    and technical_score >= 50
                    and decision_flow_positive
                )
                direction = (
                    "buy" if buy_gate else
                    "sell" if adaptive_score < 35 else
                    "neutral"
                )

                # Weak non-position observations add noise without helping
                # either the user or the learning policy.
                # Keep the full deterministic cohort until cross-sectional
                # ranks are available; filtering here would bias percentiles.

                rec = (
                    "强烈买入" if direction == "buy" and adaptive_score >= 80 else
                    "买入" if direction == "buy" else
                    "卖出" if direction == "sell" else
                    "热门观察" if result.remote_data_used and discovery_score >= 65 else
                    "观望"
                )

                evidence_payload = {
                    "schema_version": 2,
                    "selection_mode": selection_mode,
                    "stock_skill": {
                        "hot_reason": discovery_item.get("stock_skill") or {},
                        "quote": discovery_item.get("quote") or {},
                    },
                    "market_discovery": {
                        "version": (
                            discovery_snapshot.version if discovery_snapshot
                            else "explicit-or-local"
                        ),
                        "fetched_at": (
                            discovery_snapshot.fetched_at if discovery_snapshot else None
                        ),
                        "sources": sources,
                        "source_ranks": discovery_item.get("source_ranks") or {},
                        "reasons": (discovery_item.get("reasons") or [])[:5],
                        "concepts": (discovery_item.get("concepts") or [])[:10],
                        "discovery_score": round(discovery_score, 2),
                        "score_breakdown": discovery_item.get("score_breakdown") or {},
                        "quote": discovery_item.get("quote") or {},
                        "stock_skill": discovery_item.get("stock_skill") or {},
                        "fund_flow": flow,
                    },
                    "technical": {
                        "score": technical_score,
                        "data_days": sig.data_days,
                        "data_source": sig.data_source,
                    },
                    "universe_policy": assessment.to_dict(),
                    "learning": learned,
                }

                decision = {
                    "date": date.today().isoformat(),
                    "signal_at": "",
                    "stock_code": code,
                    "stock_name": name,
                    "ai_score": round(adaptive_score, 1),
                    "technical_score": round(technical_score, 1),
                    "discovery_score": round(discovery_score, 1),
                    "learning_adjustment": learned["score_adjustment"],
                    "direction": direction,
                    "confidence": round(
                        min(0.95, abs(adaptive_score - 50) / 50 * 0.8 + 0.3), 3
                    ),
                    "recommendation": rec,
                    "fusion_score": round(adaptive_score, 1),
                    "macd_score": sig.macd_score,
                    "rsi_score": sig.rsi_score,
                    "kdj_score": sig.kdj_score,
                    "ma_score": sig.ma_score,
                    "volume_score": sig.volume_score,
                    "buy_signals": sum(
                        1 for s in [
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score, sig.volume_score,
                        ] if s >= 65
                    ),
                    "sell_signals": sum(
                        1 for s in [
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score, sig.volume_score,
                        ] if s <= 35
                    ),
                    "evidence": json.dumps(evidence_payload, ensure_ascii=False),
                    "market_sources": sources,
                    "market_reasons": (discovery_item.get("reasons") or [])[:5],
                    "market_flow": flow,
                    "flow_status": decision_flow_status,
                    "stock_skill_evidence": {
                        "hot_reason": discovery_item.get("stock_skill") or {},
                        "quote": discovery_item.get("quote") or {},
                    },
                    "market_price": float(
                        (discovery_item.get("quote") or {}).get("price") or 0
                    ),
                    "market_pre_close": float(
                        (discovery_item.get("quote") or {}).get("prev_close")
                        or (discovery_item.get("quote") or {}).get("pre_close")
                        or 0
                    ),
                    "market_change_pct": float(
                        (discovery_item.get("quote") or {}).get("change_pct") or 0
                    ),
                    "market_price_source": str(
                        (discovery_item.get("quote") or {}).get("source") or ""
                    ),
                    "market_price_date": str(
                        (discovery_item.get("quote") or {}).get("data_date") or ""
                    ),
                    "market_price_fetched_at": str(
                        (discovery_item.get("quote") or {}).get("fetched_at") or ""
                    ),
                    "signal_input_price": float(
                        (discovery_item.get("quote") or {}).get("price") or 0
                    ),
                    "signal_input_quote_at": str(
                        (discovery_item.get("quote") or {}).get(
                            "exchange_timestamp"
                        ) or ""
                    ),
                    "signal_input_fetched_at": str(
                        (discovery_item.get("quote") or {}).get("fetched_at") or ""
                    ),
                    "technical_data_through": str(
                        bars[-1].get("date") or bars[-1].get("trade_date") or ""
                    ),
                    "universe_status": (
                        "held_risk_review"
                        if assessment.excluded and normalized_code in held_codes
                        else assessment.status
                    ),
                    "universe_reason_codes": list(assessment.reason_codes),
                    "universe_metadata_complete": assessment.metadata_complete,
                    "universe_industry": assessment.industry,
                    "universe_avg_daily_amount_million": (
                        assessment.avg_daily_amount_million
                    ),
                    "universe_exclusion_bypassed": bool(
                        assessment.excluded and normalized_code in held_codes
                    ),
                }

                decisions.append(decision)
                result.decisions_generated += 1

            except Exception as e:
                result.errors.append(f"{code}: {str(e)[:80]}")

            # Guarantee cancellation and API responsiveness between batches,
            # even if an async provider returns without actually yielding.
            if index and index % 50 == 0:
                await asyncio.sleep(0)

        publication_block_reasons = _market_data_block_reasons(
            selection_mode,
            discovery_snapshot,
            result.stocks_scanned,
            result.signals_computed,
            latest_local_data_date,
            technical_data_dates,
            policy_excluded_count=universe_excluded_count,
        )
        result.market_data_quality.update({
            "technical_data_dates": sorted(technical_data_dates),
            "publication_blocked": bool(publication_block_reasons),
            "publication_block_reasons": publication_block_reasons,
            "universe_policy": {
                "config": {
                    "min_market_cap": universe_policy.min_market_cap,
                    "min_avg_daily_amount_million": (
                        universe_policy.min_avg_daily_amount_million
                    ),
                    "exclude_st": universe_policy.exclude_st,
                    "min_listing_days": universe_policy.min_listing_days,
                    "max_industry_pct": universe_policy.max_industry_pct,
                },
                "excluded_count": universe_excluded_count,
                "review_only_count": universe_review_only_count,
                "reason_counts": universe_reason_counts,
            },
        })

        from src.ai_os.cross_sectional_scoring import apply_cross_sectional_scores

        selection_weights = _selection_weights(settings)
        apply_cross_sectional_scores(
            decisions,
            # Keep a safe default for a server process that was started from
            # an older Settings class.  The next restart picks up the typed
            # fields, while a mixed-version process can still finish a scan.
            technical_weight=selection_weights["technical"],
            discovery_weight=selection_weights["discovery"],
            learning_weight=selection_weights["learning"],
            rank_weight=selection_weights["rank"],
        )

        # Keep the broad technical scan deterministic, but pass only a bounded
        # shortlist to market-context/AI stages. Remote discovery candidates
        # that were also technically scored are overlaid before the final cap.
        decisions = sort_decisions(decisions)
        shortlist_cap = max(
            1, int(getattr(settings, "SCANNER_TECHNICAL_SHORTLIST_COUNT", 300))
        )
        all_scored_decisions = decisions
        technical_shortlist = all_scored_decisions[:shortlist_cap]
        remote_codes = {
            str(item.get("stock_code"))
            for item in sorted(
                discovery_by_code.values(),
                key=lambda item: float(item.get("discovery_score", 0.0)),
                reverse=True,
            )
        }
        shortlist_by_code = {
            str(item.get("stock_code")): item for item in technical_shortlist
        }
        for decision in all_scored_decisions:
            code = str(decision.get("stock_code"))
            if code in remote_codes:
                shortlist_by_code.setdefault(code, decision)
        decisions = sort_decisions(list(shortlist_by_code.values()))[:shortlist_cap]
        decisions = _include_held_decisions(
            decisions,
            all_scored_decisions,
            held_codes,
        )

        # Concentration is a candidate/portfolio constraint, not a full-universe
        # eligibility rule. Applying it after the shortlist makes a 40% cap
        # meaningful while keeping held positions available for risk exits.
        shortlist_codes = {
            str(item.get("stock_code") or "").strip().upper()
            for item in decisions
        }
        shortlist_assessments = [
            assessment
            for code, assessment in universe_assessments.items()
            if code in shortlist_codes
        ]
        concentration = apply_industry_concentration(
            shortlist_assessments,
            {
                str(item.get("stock_code") or "").strip().upper(): float(
                    item.get("ranking_score") or item.get("ai_score") or 0
                )
                for item in decisions
            },
            max_industry_pct=universe_policy.max_industry_pct,
        )
        concentration_excluded = set(concentration.excluded_codes)
        if concentration_excluded:
            decisions = [
                item
                for item in decisions
                if str(item.get("stock_code") or "").strip().upper()
                not in concentration_excluded
                or str(item.get("stock_code") or "").strip().upper() in held_codes
            ]
            for item in decisions:
                code = str(item.get("stock_code") or "").strip().upper()
                if code in concentration_excluded and code in held_codes:
                    item["universe_status"] = "held_risk_review"
                    item["universe_reason_codes"] = list(dict.fromkeys(
                        [
                            *(item.get("universe_reason_codes") or []),
                            "industry_concentration_limit",
                        ]
                    ))
                    item["universe_exclusion_bypassed"] = True
        candidate_excluded = concentration_excluded - held_codes
        result.market_data_quality["universe_policy"].update({
            "industry_cap_applied": concentration.applied,
            "industry_cap_scope": "technical_shortlist",
            "industry_cap_excluded_count": len(candidate_excluded),
            "industry_cap_excluded_codes": sorted(candidate_excluded)[:50],
            "industry_cap_capped": concentration.capped_industries,
        })
        result.technical_shortlist_size = len(decisions)
        result.decisions_generated = len(decisions)
        result.market_data_quality.update({
            "technical_universe_size": result.technical_universe_size,
            "signals_computed": result.signals_computed,
            "technical_shortlist_size": result.technical_shortlist_size,
            "technical_shortlist_target": shortlist_cap,
            "remote_candidate_count": len(discovery_by_code),
        })
        # The technical shortlist is local and cheap, while deep analysis
        # requires a current quote and source provenance. Fill only a bounded
        # high-score queue before preselection and score guarding so both
        # downstream stages consume the same evidence packet.
        from src.ai_os.candidate_evidence_enricher import (
            enrich_candidate_evidence,
        )
        from src.ai_os.cross_sectional_scoring import refresh_execution_gate

        stage_started = time.perf_counter()
        evidence_enrichment = await enrich_candidate_evidence(
            decisions,
            discovery_by_code,
            max_candidates=getattr(
                settings, "SCANNER_EVIDENCE_ENRICHMENT_COUNT", 80
            ),
            # No ranking floor: this runs before apply_score_guard, so the only
            # readable score is the technical/discovery composite, which does
            # not reach the BUY gate.  The bounded queue below is what limits
            # the work; see enrich_candidate_evidence's docstring.
            concurrency=getattr(
                settings, "SCANNER_EVIDENCE_ENRICHMENT_CONCURRENCY", 4
            ),
            timeout_seconds=getattr(
                settings, "SCANNER_EVIDENCE_ENRICHMENT_TIMEOUT_SECONDS", 30.0
            ),
            target_trade_date=market_db.get_latest_market_date_on_or_before(
                date.today().isoformat()
            ),
        )
        result.market_data_quality["candidate_evidence_enrichment"] = (
            evidence_enrichment
        )
        stage_seconds = result.market_data_quality.setdefault("stage_seconds", {})
        stage_seconds["candidate_enrichment"] = round(time.perf_counter() - stage_started, 3)
        # The enrichment bridge can attach newer flow evidence than the broad
        # selector had at its first pass. Refresh only the original gate
        # decision; never recompute scores/ranks or bypass later research and
        # execution guards.
        for decision in decisions:
            refresh_execution_gate(decision)
        # Sort by score before the single batched Codex preselection call.
        decisions = sort_decisions(decisions)
        from src.infrastructure.ai import ai_router

        ai_status = ai_router.status()
        stage_started = time.perf_counter()
        preselection_count, preselection_called, preselection_error = (
            await _apply_ai_preselection(
                decisions,
                getattr(settings, "SCANNER_AI_PRESELECT_COUNT", 20),
                ai_router,
                bool(ai_status.get("primary_configured")),
            )
        )
        result.ai_preselection_count = preselection_count
        stage_seconds["ai_preselection"] = round(time.perf_counter() - stage_started, 3)
        result.market_data_quality.update({
            "ai_preselection_target": getattr(settings, "SCANNER_AI_PRESELECT_COUNT", 20),
            "ai_preselection_count": preselection_count,
            "ai_preselection_called": preselection_called,
            "ai_preselection_input": {
                "sha256": next(
                    (
                        str(item.get("preselection_input_sha256") or "")
                        for item in decisions
                        if item.get("preselection_input_sha256")
                    ),
                    "",
                ),
                "chars": next(
                    (
                        int(item.get("preselection_input_chars") or 0)
                        for item in decisions
                        if item.get("preselection_input_chars")
                    ),
                    0,
                ),
                "count": next(
                    (
                        int(item.get("preselection_input_count") or 0)
                        for item in decisions
                        if item.get("preselection_input_count")
                    ),
                    0,
                ),
                "fields": next(
                    (
                        item.get("preselection_input_fields") or []
                        for item in decisions
                        if item.get("preselection_input_fields")
                    ),
                    [],
                ),
            },
        })
        if preselection_error:
            result.market_data_quality["ai_preselection_error"] = preselection_error
        from src.ai_os.score_guard import apply_score_guard
        for decision in decisions:
            apply_score_guard(
                decision,
                discovery_by_code.get(str(decision.get("stock_code"))) or {},
            )
        decisions = sort_decisions(decisions)

        await asyncio.to_thread(
            market_db.upsert_daily_learning,
            date.today().isoformat(),
            "remote_market_snapshot",
            (
                f"每日候选来源={selection_mode}，远程候选={len(discovery_by_code)}，"
                f"生成决策={len(decisions)}，下一交易日结果将回写来源与股票学习权重。"
            ),
            {
                "selection_mode": selection_mode,
                "remote_data_used": result.remote_data_used,
                "data_quality": result.market_data_quality,
                "top_candidates": [
                    {
                        "stock_code": item.get("stock_code"),
                        "stock_name": item.get("stock_name"),
                        "ai_score": item.get("ai_score"),
                        "technical_score": item.get("technical_score"),
                        "discovery_score": item.get("discovery_score"),
                        "sources": item.get("market_sources"),
                        "reasons": (item.get("market_reasons") or [])[:2],
                    }
                    for item in decisions[:10]
                ],
                "learning_profile": result.learning_profile,
            },
        )

        # Collect local evidence, then let one Codex-Terra multi-role turn
        # analyze each top candidate. No DeepSeek call is permitted here.
        from src.agents.codex_stock_analyzer import analyze_candidates, availability_status
        recent_learning = market_db.get_learning_log(12)
        learning_context = "\n".join(
            f"- {item.get('learning_date')}: {item.get('lesson')}"
            for item in recent_learning
        )
        deep_initial_target = max(
            0, int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_N", 5))
        )
        if normalized_window == "morning":
            deep_session_limit = max(
                deep_initial_target,
                int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_MORNING_MAX", 10)),
            )
            deep_daily_limit = max(
                deep_session_limit,
                int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_DAILY_MAX", 15)),
            )
        elif normalized_window == "midday":
            deep_session_limit = max(
                deep_initial_target,
                int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_MIDDAY_MAX", 5)),
            )
            deep_daily_limit = max(
                deep_session_limit,
                int(getattr(settings, "SCANNER_AI_DEEP_ANALYSIS_DAILY_MAX", 15)),
            )
        else:
            deep_session_limit = deep_initial_target
            deep_daily_limit = deep_initial_target
        research_started = time.monotonic()
        research_deadline_seconds = max(
            1.0,
            float(
                getattr(
                    settings,
                    "SCANNER_AI_DEEP_ANALYSIS_DEADLINE_SECONDS",
                    480.0,
                )
            ),
        )
        # Deep analysis is expensive and must only consume candidates with a
        # sourced quote/context. The queue is expanded only within the same
        # preselection/shortlist, never by changing the selector itself.
        for decision in decisions:
            decision.setdefault(
                "strategy_version", str(run_metadata.get("strategy_version") or "")
            )
        deep_candidates, deep_allocation = allocate_deep_candidates(
            decisions, deep_session_limit
        )
        result.market_data_quality["deep_candidate_eligibility"] = deep_allocation
        deep_codes = [str(item.get("stock_code") or "") for item in deep_candidates]
        input_fingerprints = {
            str(item.get("stock_code") or "").strip().upper(): deep_input_fingerprint(
                item,
                date.today().isoformat(),
                strategy_version=str(run_metadata.get("strategy_version") or ""),
                model=settings.CODEX_MODEL,
            )
            for item in deep_candidates
            if item.get("stock_code")
        }
        for item in deep_candidates:
            code = str(item.get("stock_code") or "").strip().upper()
            if code:
                item["deep_input_fingerprint"] = input_fingerprints.get(code, "")
        cached_deep = market_db.get_cached_deep_analyses(
            date.today().isoformat(), deep_codes,
            provider="codex_cli", model=settings.CODEX_MODEL,
            input_fingerprints=input_fingerprints,
        )
        daily_deep_successes = market_db.count_cached_deep_analyses(
            date.today().isoformat(), provider="codex_cli", model=settings.CODEX_MODEL
        )
        daily_deep_attempts = market_db.count_daily_deep_attempts(
            date.today().isoformat(), provider="codex_cli", model=settings.CODEX_MODEL
        )
        cached_deep, missing_candidates, budget_skipped_count = _deep_analysis_plan(
            deep_candidates,
            cached_deep,
            deep_session_limit,
            daily_deep_successes,
            daily_deep_attempts,
            force_reanalysis,
            max_new_candidates=deep_session_limit,
            daily_call_limit=deep_daily_limit,
        )
        planned_missing_candidates = list(missing_candidates)
        initial_missing_candidates = planned_missing_candidates[:deep_initial_target]
        continuation_candidates = planned_missing_candidates[deep_initial_target:]
        reservation = market_db.reserve_deep_analysis_slots(
            date.today().isoformat(),
            normalized_window,
            initial_missing_candidates,
            input_fingerprints,
            window_limit=deep_session_limit,
            daily_limit=deep_daily_limit,
            override_daily_limit=force_reanalysis,
            override_window_usage=force_reanalysis,
        )
        missing_candidates = list(reservation.get("selected") or [])
        budget_skipped_count += int(reservation.get("skipped") or 0)
        stage_started = time.perf_counter()
        fresh_deep_results: list[dict[str, Any]] = []
        remaining_seconds = max(
            0.1,
            research_deadline_seconds - (time.monotonic() - research_started),
        )
        if missing_candidates:
            try:
                fresh_deep_results = await asyncio.wait_for(
                    analyze_candidates(
                        missing_candidates,
                        date.today().isoformat(),
                        learning_context,
                        limit=len(missing_candidates),
                    ),
                    timeout=remaining_seconds,
                )
            except asyncio.TimeoutError:
                fresh_deep_results = [
                    {
                        "available": False,
                        "stock_code": str(item.get("stock_code") or ""),
                        "error": "deep research deadline exceeded",
                        "error_type": "ResearchDeadlineExceeded",
                        "duration_seconds": round(
                            time.perf_counter() - stage_started, 2
                        ),
                        "provider": "codex_cli",
                        "model": settings.CODEX_MODEL,
                    }
                    for item in missing_candidates
                ]
        market_db.finalize_deep_analysis_slots(
            date.today().isoformat(),
            normalized_window,
            fresh_deep_results,
            input_fingerprints,
        )
        stage_seconds["deep_analysis"] = round(time.perf_counter() - stage_started, 3)
        fresh_by_code = {
            str(item.get("stock_code") or "").upper(): item
            for item in fresh_deep_results
        }
        deep_results = [
            cached_deep.get(code.upper()) or fresh_by_code.get(code.upper())
            for code in deep_codes
        ]
        deep_results = [item for item in deep_results if item]
        result.deep_analysis_count = sum(
            bool(item.get("available")) for item in deep_results
        )
        runtime_status = availability_status()
        result.market_data_quality["deep_analysis_initial_target"] = deep_initial_target
        result.market_data_quality["deep_analysis_session_limit"] = deep_session_limit
        result.market_data_quality["deep_analysis_daily_limit"] = deep_daily_limit
        result.market_data_quality["deep_analysis_research_window"] = normalized_window
        result.market_data_quality["deep_analysis_target"] = len(deep_candidates)
        result.market_data_quality["deep_analysis_cached_count"] = len(cached_deep)
        result.market_data_quality["deep_analysis_daily_successes_before"] = (
            daily_deep_successes
        )
        result.market_data_quality["deep_analysis_daily_attempts_before"] = (
            daily_deep_attempts
        )
        result.market_data_quality["deep_analysis_daily_call_budget"] = (
            len(missing_candidates)
        )
        result.market_data_quality["deep_analysis_daily_budget_skipped_count"] = max(
            0, budget_skipped_count
        )
        result.market_data_quality["deep_analysis_force_reanalysis"] = force_reanalysis
        result.market_data_quality["deep_analysis_cache_mode"] = (
            "bypassed" if force_reanalysis else "same_day"
        )
        result.market_data_quality["deep_analysis_daily_budget_overridden"] = bool(
            force_reanalysis and missing_candidates
        )
        result.market_data_quality["deep_analysis_budget_reservation"] = {
            "used_before": reservation.get("used_before", 0),
            "used_after": reservation.get("used_after", 0),
            "window_used_after": reservation.get("window_used_after", 0),
            "selected_count": len(missing_candidates),
            "skipped_count": int(reservation.get("skipped") or 0),
        }
        result.market_data_quality["deep_analysis_deadline_seconds"] = (
            research_deadline_seconds
        )
        result.market_data_quality["deep_analysis_elapsed_seconds"] = round(
            time.monotonic() - research_started, 3
        )
        result.market_data_quality["deep_analysis_attempted_count"] = len(
            fresh_deep_results
        )
        result.market_data_quality["deep_analysis_evaluated_count"] = len(deep_results)
        result.market_data_quality["deep_analysis_count"] = result.deep_analysis_count
        result.market_data_quality["deep_analysis_runtime"] = runtime_status
        # Compatibility key for existing Dashboard clients.
        result.market_data_quality["tradingagents_runtime"] = runtime_status
        deep_errors = [
            {
                "stock_code": item.get("stock_code", ""),
                "error": str(item.get("error") or "")[:240],
            }
            for item in deep_results
            if not item.get("available")
        ]
        if deep_errors:
            result.market_data_quality["deep_analysis_errors"] = deep_errors
        deep_by_code = {
            str(item.get("stock_code") or "").strip().upper(): item
            for item in deep_results
        }

        def apply_deep_results(result_items: list[dict[str, Any]]) -> None:
            """Attach one bounded deep batch without changing selector scores."""
            from src.ai_os.score_guard import apply_score_guard

            for item in result_items:
                code = str(item.get("stock_code") or "").strip().upper()
                if code:
                    deep_by_code[code] = item
            for decision in decisions:
                deep = deep_by_code.get(
                    str(decision.get("stock_code") or "").strip().upper()
                )
                if not deep:
                    continue
                decision["deep_analysis_available"] = bool(deep.get("available"))
                decision["deep_rating"] = deep.get("rating", "")
                decision["deep_analysis"] = deep.get("decision", "")
                decision["deep_thesis"] = deep.get("thesis", "")
                decision["deep_trader_plan"] = deep.get("trader_plan", "")
                decision["deep_kline_evidence"] = deep.get("kline_evidence", {})
                decision["deep_evidence_consumption"] = deep.get(
                    "deep_evidence_consumption", {}
                )
                decision["deep_analysis_error"] = deep.get("error", "")
                decision["deep_evidence_gaps"] = deep.get("evidence_gaps") or []
                decision["deep_provider"] = deep.get("provider", "")
                decision["deep_model"] = deep.get("model", "")
                decision["deep_source"] = deep.get("source", "")
                decision["deep_runtime"] = deep.get("runtime", "")
                decision["deep_cached"] = bool(deep.get("cached"))
                decision["deep_duration_seconds"] = deep.get("duration_seconds", 0)
                decision["deep_input_fingerprint"] = str(
                    deep.get("deep_input_fingerprint")
                    or input_fingerprints.get(
                        str(decision.get("stock_code") or "").strip().upper(), ""
                    )
                )
                if deep.get("available"):
                    # The PM rating is the execution gate. Keep the technical
                    # score for auditability, but expose the effective decision.
                    _apply_deep_score(decision, deep)
                    decision["direction"] = deep["direction"]
                    decision["recommendation"] = deep["rating"]

                apply_score_guard(
                    decision,
                    discovery_by_code.get(str(decision.get("stock_code"))) or {},
                    deep,
                )

        apply_deep_results(deep_results)

        await asyncio.to_thread(
            market_db.upsert_daily_learning,
            date.today().isoformat(),
            "tradingagents_status",
            (
                f"Codex-Terra深度分析目标 {len(deep_candidates)} 只，成功 {result.deep_analysis_count} 只，"
                f"同日缓存 {len(cached_deep)} 只，新调用 {len(fresh_deep_results)} 只。"
            ),
            {
                "target": len(deep_candidates),
                "successful": result.deep_analysis_count,
                "cached": len(cached_deep),
                "attempted": len(fresh_deep_results),
                "daily_successes_before": daily_deep_successes,
                "daily_attempts_before": daily_deep_attempts,
                "daily_call_budget": len(missing_candidates),
                "force_reanalysis": force_reanalysis,
                "runtime": runtime_status,
                "errors": deep_errors,
            },
        )

        _preauthorize_final_review(decisions)
        stage_started = time.perf_counter()
        remaining_seconds = max(
            0.1,
            research_deadline_seconds - (time.monotonic() - research_started),
        )
        if result.deep_analysis_count and remaining_seconds > 0.1:
            try:
                final_review = await asyncio.wait_for(
                    _apply_final_ai_review(
                        decisions,
                        ai_router,
                        recent_learning,
                        settings.AI_REVIEW_PROVIDER,
                    ),
                    timeout=remaining_seconds,
                )
            except asyncio.TimeoutError:
                final_review = {
                    "called": False,
                    "matched": 0,
                    "provider": "",
                    "model": "",
                    "fallback_used": False,
                    "error": "research deadline exceeded before final review",
                }
        else:
            final_review = {
                "called": False,
                "matched": 0,
                "provider": "",
                "model": "",
                "fallback_used": False,
                "error": (
                    "research deadline exceeded before final review"
                    if result.deep_analysis_count else ""
                ),
            }
        result.final_review_count = int(final_review["matched"])
        stage_seconds["final_review"] = round(time.perf_counter() - stage_started, 3)
        result.market_data_quality.update({
            "final_review_target": result.deep_analysis_count,
            "final_review_count": result.final_review_count,
            "final_review_called": final_review["called"],
            "final_review_provider": final_review["provider"],
            "final_review_model": final_review["model"],
            "final_review_fallback_used": final_review["fallback_used"],
            "final_review_input": {
                "sha256": final_review.get("input_sha256", ""),
                "chars": int(final_review.get("input_chars") or 0),
                "count": int(final_review.get("input_count") or 0),
                "fields": final_review.get("input_fields") or [],
            },
        })
        if final_review["error"]:
            result.market_data_quality["final_review_error"] = final_review["error"]
        result.market_data_quality["deep_analysis_elapsed_seconds"] = round(
            time.monotonic() - research_started, 3
        )
        result.market_data_quality["deep_analysis_deadline_status"] = (
            "within_budget"
            if time.monotonic() - research_started <= research_deadline_seconds
            else "deadline_exceeded"
        )
        await asyncio.to_thread(
            market_db.upsert_daily_learning,
            date.today().isoformat(),
            "codex_final_review",
            (
                f"最终AI复核目标 {result.deep_analysis_count} 只，"
                f"有效结论 {result.final_review_count} 只，"
                f"提供方 {final_review['provider'] or 'unavailable'}。"
            ),
            {
                "target": result.deep_analysis_count,
                "matched": result.final_review_count,
                "provider": final_review["provider"],
                "model": final_review["model"],
                "fallback_used": final_review["fallback_used"],
                "error": final_review["error"],
                "reviews": [
                    {
                        "stock_code": item.get("stock_code"),
                        "tradingagents_rating": item.get("tradingagents_rating"),
                        "verdict": item.get("final_review_verdict"),
                        "reason": item.get("final_review_reason"),
                        "approved": item.get("final_buy_approved"),
                    }
                    for item in decisions
                    if item.get("deep_analysis_available")
                ],
            },
        )
        final_review_calls = int(bool(final_review.get("called")))

        # If the first five deep results yield no executable approval, use the
        # remaining candidates from the same preselection queue. This is a
        # bounded continuation: it never expands the selector or bypasses the
        # shared daily/window reservation.
        first_review_codes = {
            str(item.get("stock_code") or "").strip().upper()
            for item in deep_candidates[:deep_initial_target]
            if item.get("stock_code")
        }
        first_review_approved = any(
            bool(decision.get("final_buy_approved"))
            for decision in decisions
            if str(decision.get("stock_code") or "").strip().upper()
            in first_review_codes
        )
        continuation_triggered = False
        continuation_results: list[dict[str, Any]] = []
        continuation_reservation: dict[str, Any] = {}
        continuation_stop_reason = "no_remaining_candidates"
        if continuation_candidates and first_review_approved:
            continuation_stop_reason = "first_batch_approved"
        elif continuation_candidates:
            remaining_seconds = max(
                0.1,
                research_deadline_seconds - (time.monotonic() - research_started),
            )
            if remaining_seconds <= 0.1:
                continuation_stop_reason = "research_deadline_exceeded"
            else:
                continuation_reservation = market_db.reserve_deep_analysis_slots(
                    date.today().isoformat(),
                    normalized_window,
                    continuation_candidates,
                    input_fingerprints,
                    window_limit=deep_session_limit,
                    daily_limit=deep_daily_limit,
                )
                continuation_batch = list(
                    continuation_reservation.get("selected") or []
                )
                budget_skipped_count += int(
                    continuation_reservation.get("skipped") or 0
                )
                if not continuation_batch:
                    continuation_stop_reason = "deep_budget_exhausted"
                else:
                    continuation_triggered = True
                    continuation_started = time.perf_counter()
                    remaining_seconds = max(
                        0.1,
                        research_deadline_seconds
                        - (time.monotonic() - research_started),
                    )
                    try:
                        continuation_results = await asyncio.wait_for(
                            analyze_candidates(
                                continuation_batch,
                                date.today().isoformat(),
                                learning_context,
                                limit=len(continuation_batch),
                            ),
                            timeout=remaining_seconds,
                        )
                    except asyncio.TimeoutError:
                        continuation_results = [
                            {
                                "available": False,
                                "stock_code": str(item.get("stock_code") or ""),
                                "error": "deep research deadline exceeded",
                                "error_type": "ResearchDeadlineExceeded",
                                "duration_seconds": round(
                                    time.perf_counter() - continuation_started, 2
                                ),
                                "provider": "codex_cli",
                                "model": settings.CODEX_MODEL,
                            }
                            for item in continuation_batch
                        ]
                    market_db.finalize_deep_analysis_slots(
                        date.today().isoformat(),
                        normalized_window,
                        continuation_results,
                        input_fingerprints,
                    )
                    fresh_deep_results.extend(continuation_results)
                    deep_results.extend(continuation_results)
                    apply_deep_results(continuation_results)
                    result.deep_analysis_count = sum(
                        bool(item.get("available"))
                        for item in deep_by_code.values()
                    )
                    continuation_stop_reason = "continuation_completed"
                    # Re-run the final review over the complete researched set
                    # so the final gate sees one coherent batch.
                    _preauthorize_final_review(decisions, set(deep_by_code))
                    remaining_seconds = max(
                        0.1,
                        research_deadline_seconds
                        - (time.monotonic() - research_started),
                    )
                    if result.deep_analysis_count and remaining_seconds > 0.1:
                        try:
                            final_review = await asyncio.wait_for(
                                _apply_final_ai_review(
                                    decisions,
                                    ai_router,
                                    recent_learning,
                                    settings.AI_REVIEW_PROVIDER,
                                    stock_codes=set(deep_by_code),
                                ),
                                timeout=remaining_seconds,
                            )
                        except asyncio.TimeoutError:
                            final_review = {
                                "called": False,
                                "matched": 0,
                                "provider": "",
                                "model": "",
                                "fallback_used": False,
                                "error": "research deadline exceeded before final review",
                            }
                    else:
                        final_review = {
                            "called": False,
                            "matched": 0,
                            "provider": "",
                            "model": "",
                            "fallback_used": False,
                            "error": "research deadline exceeded before final review",
                        }
                    result.final_review_count = int(final_review["matched"])
                    result.market_data_quality.update({
                        "final_review_target": result.deep_analysis_count,
                        "final_review_count": result.final_review_count,
                        "final_review_called": final_review["called"],
                        "final_review_provider": final_review["provider"],
                        "final_review_model": final_review["model"],
                        "final_review_fallback_used": final_review["fallback_used"],
                        "final_review_input": {
                            "sha256": final_review.get("input_sha256", ""),
                            "chars": int(final_review.get("input_chars") or 0),
                            "count": int(final_review.get("input_count") or 0),
                            "fields": final_review.get("input_fields") or [],
                        },
                    })
                    if final_review["error"]:
                        result.market_data_quality["final_review_error"] = (
                            final_review["error"]
                        )
                    final_review_calls += int(bool(final_review.get("called")))

        if continuation_reservation:
            result.market_data_quality["deep_analysis_budget_reservation"] = {
                "used_before": reservation.get("used_before", 0),
                "used_after": continuation_reservation.get(
                    "used_after", reservation.get("used_after", 0)
                ),
                "window_used_after": continuation_reservation.get(
                    "window_used_after", reservation.get("window_used_after", 0)
                ),
                "selected_count": len(missing_candidates)
                + len(continuation_results),
                "skipped_count": int(reservation.get("skipped") or 0)
                + int(continuation_reservation.get("skipped") or 0),
            }
        result.market_data_quality.update({
            "deep_analysis_continuation_triggered": continuation_triggered,
            "deep_analysis_continuation_count": len(continuation_results),
            "deep_analysis_continuation_stop_reason": continuation_stop_reason,
            "deep_analysis_deferred_count": max(
                0,
                len(continuation_candidates)
                - len(continuation_results),
            ),
            "deep_analysis_attempted_count": len(fresh_deep_results),
            "deep_analysis_evaluated_count": len(deep_by_code),
            "deep_analysis_count": result.deep_analysis_count,
            "deep_analysis_daily_call_budget": len(fresh_deep_results),
            "deep_analysis_daily_budget_skipped_count": max(
                0, budget_skipped_count
            ),
            "deep_analysis_elapsed_seconds": round(
                time.monotonic() - research_started, 3
            ),
            "deep_analysis_deadline_status": (
                "within_budget"
                if time.monotonic() - research_started <= research_deadline_seconds
                else "deadline_exceeded"
            ),
            "final_review_calls": final_review_calls,
        })
        deep_errors = [
            {
                "stock_code": item.get("stock_code", ""),
                "error": str(item.get("error") or "")[:240],
            }
            for item in deep_by_code.values()
            if not item.get("available")
        ]
        if deep_errors:
            result.market_data_quality["deep_analysis_errors"] = deep_errors
        if continuation_triggered:
            await asyncio.to_thread(
                market_db.upsert_daily_learning,
                date.today().isoformat(),
                "codex_continuation",
                (
                    f"深度分析递补 {len(continuation_results)} 只，"
                    f"总成功 {result.deep_analysis_count} 只，"
                    f"停止原因={continuation_stop_reason}。"
                ),
                {
                    "continuation_count": len(continuation_results),
                    "total_successful": result.deep_analysis_count,
                    "stop_reason": continuation_stop_reason,
                    "budget_reservation": result.market_data_quality.get(
                        "deep_analysis_budget_reservation", {}
                    ),
                },
            )

        # Apply global market-quality gates only after all research stages have
        # had a chance to annotate their evidence. A degraded run may still
        # be persisted for audit, but it cannot become a normal recommendation.
        for decision in decisions:
            decision.update(run_metadata)
            local_block_reasons = publication_block_reasons
            # A degraded optional provider should not erase a complete
            # per-stock quote/source packet. Mandatory run failures remain
            # fail-closed.
            if (
                publication_block_reasons == ["market_data_degraded"]
                and has_market_evidence(decision)
            ):
                local_block_reasons = []
            apply_score_guard(
                decision,
                discovery_by_code.get(str(decision.get("stock_code"))) or {},
                deep_by_code.get(str(decision.get("stock_code"))),
                additional_reasons=local_block_reasons,
            )
            apply_publication_quality(decision, local_block_reasons)

        decisions = sort_decisions(decisions)

        # Freeze the final model output before requesting any execution price.
        # Everything used by the strategy exists no later than data_cutoff_at;
        # signal_at is the immutable point after which a fill quote may occur.
        data_cutoff_at = datetime.now().astimezone().isoformat()
        signal_at = datetime.now().astimezone().isoformat()
        for decision in decisions:
            decision["data_cutoff_at"] = data_cutoff_at
            decision["signal_at"] = signal_at

        if save_to_journal:
            journal_ids = await asyncio.to_thread(
                market_db.save_decisions_batch, decisions
            )
            for decision, journal_id in zip(decisions, journal_ids, strict=True):
                decision["journal_id"] = journal_id
            # Register the complete final candidate batch for the shared
            # background completion worker.  This is a pending checkpoint,
            # not a claim that any component has already been fetched.
            backfill_codes = [
                str(item.get("stock_code") or "").strip().upper()
                for item in decisions
                if item.get("stock_code")
            ]
            backfill_target = await asyncio.to_thread(
                market_db.get_latest_market_date_on_or_before,
                date.today().isoformat(),
            )
            backfill_partition = ":".join((
                "20260906-v3", "candidate", str(run_metadata["run_id"]),
                str(len(backfill_codes)), backfill_target, "250", "8", "20",
            ))
            await asyncio.to_thread(
                market_db.save_completion_checkpoint,
                "research_data_backfill", "candidate", backfill_partition,
                {
                    "codes": backfill_codes,
                    "completed": [],
                    "target_date": backfill_target,
                    "results": {},
                    "run_id": str(run_metadata["run_id"]),
                },
                "pending",
            )
            result.market_data_quality["research_backfill_task"] = {
                "status": "pending",
                "run_id": str(run_metadata["run_id"]),
                "code_count": len(backfill_codes),
                "target_date": backfill_target,
                "partition_key": backfill_partition,
            }
            result.market_data_quality["target_trade_date"] = backfill_target

        # The same causal execution helper is used by the lightweight 09:35
        # task, which reads this persisted plan instead of rescanning 5,200
        # symbols and rerunning Codex-Terra at the market open.
        cycle = await _execute_paper_cycle(
            decisions,
            execute_paper_trades=execute_paper_trades,
        )
        paper_result = cycle["paper_result"]
        execution_quotes = cycle["execution_quotes"]
        execution_decisions = cycle["execution_decisions"]
        causal_rejections = cycle["causal_rejections"]
        trading_day_verified = cycle["trading_calendar_verified"]
        pre_trade_mark = cycle["pre_trade_portfolio_mark"]
        portfolio_mark = cycle["portfolio_mark"]
        result.paper_trades = paper_result["actions"]
        result.paper_cash = paper_result["cash"]
        result.paper_position_count = paper_result["position_count"]
        result.market_data_quality["pre_trade_portfolio_mark"] = pre_trade_mark
        result.market_data_quality["portfolio_mark"] = portfolio_mark
        result.market_data_quality["paper_execution"] = {
            "status": paper_result.get("execution_status"),
            "execution_at": paper_result.get("execution_at"),
            "causal_quote_count": len(execution_quotes),
            "execution_candidate_count": len(execution_decisions),
            "execution_deferred": not execute_paper_trades,
            "trading_calendar_source": cycle["trading_calendar_source"],
            "trading_calendar_verified": trading_day_verified,
            "causal_quote_rejections": causal_rejections,
            "rejections": paper_result.get("rejections", []),
        }
        if paper_result["actions"]:
            await asyncio.to_thread(
                market_db.save_learning,
                date.today().isoformat(), "execution",
                "今日根据评分执行纸面交易：" + ", ".join(
                    f"{a['action']} {a['stock_code']} {a['shares']}股"
                    for a in paper_result["actions"]
                ),
                {"actions": paper_result["actions"], "cash": paper_result["cash"]},
            )

        status_counts: dict[str, int] = {}
        for decision in decisions:
            status = str(decision.get("decision_status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        rejection_counts: dict[str, int] = {}
        for rejection in [
            *(causal_rejections or []),
            *(paper_result.get("rejections") or []),
        ]:
            reason = str(rejection.get("reason") or "unknown")
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        execution_observability = {
            "decision_status_counts": status_counts,
            "deep_buy_approved_count": sum(
                is_deep_buy_approved(decision) for decision in decisions
            ),
            "exploration_candidate_count": sum(
                is_momentum_probe_candidate(decision) for decision in decisions
            ),
            "conditional_candidate_count": sum(
                is_conditional_probe_candidate(decision) for decision in decisions
            ),
            "new_buy_count": sum(
                str(action.get("action") or "").upper() == "BUY"
                for action in paper_result.get("actions") or []
            ),
            "new_sell_count": sum(
                str(action.get("action") or "").upper() == "SELL"
                for action in paper_result.get("actions") or []
            ),
            "probe_opened": int(paper_result.get("probe_opened") or 0),
            "probe_promoted": int(paper_result.get("probe_promoted") or 0),
            "probe_expired": int(paper_result.get("probe_expired") or 0),
            "rejection_counts": rejection_counts,
            "execution_deferred": not execute_paper_trades,
        }
        execution_observability.update(
            summarize_execution_dispositions(
                decisions,
                allow_probe=bool(
                    getattr(settings, "PAPER_EXPLORATION_ENABLED", True)
                ),
            )
        )
        for decision in decisions:
            disposition = evaluate_entry_execution(
                decision,
                allow_probe=bool(
                    getattr(settings, "PAPER_EXPLORATION_ENABLED", True)
                ),
            )
            decision["execution_disposition"] = disposition.get("tier", "blocked")
            decision["execution_block_reason"] = disposition.get("reason", "")
            apply_decision_display_fields(decision)
        persistence = None
        if save_to_journal:
            saved_count = await asyncio.to_thread(
                market_db.save_strategy_decisions_batch, decisions
            )
            readback = await asyncio.to_thread(
                market_db.get_strategy_run_evidence_summary,
                str(run_metadata.get("run_id") or ""),
            )
            persistence = {
                "expected_count": len(decisions),
                "saved_count": int(saved_count),
                "readback_count": int(readback.get("decision_count") or 0),
                "readback_verified": int(saved_count) == len(decisions)
                and int(readback.get("decision_count") or 0) == len(decisions),
            }
        result.market_data_quality["pipeline_errors"] = result.errors[:10]
        result.market_data_quality.setdefault(
            "target_trade_date",
            str(result.market_data_quality.get("latest_local_data_date") or ""),
        )
        result.market_data_quality["execution_observability"] = execution_observability
        run_classification = classify_run_outcome(
            decisions,
            result.market_data_quality,
            actionable_count=sum(
                is_actionable_recommendation(decision) for decision in decisions
            ),
            execution_deferred=not execute_paper_trades,
            persistence=persistence,
            learning={
                "status": "not_due",
                "reason_codes": [
                    "scanner_does_not_backfill_mature_learning_outcomes"
                ],
                "source": "scheduled_learning_tasks",
            },
        )
        execution_observability["run_outcome"] = run_classification
        result.market_data_quality["run_outcome"] = run_classification
        stage_acceptance = run_classification.get("stage_acceptance") or {}
        result.market_data_quality["stage_acceptance"] = stage_acceptance
        if save_to_journal:
            audit_payload = {
                **stage_acceptance,
                "run_id": str(run_metadata.get("run_id") or ""),
                "decision_date": result.run_date,
                "target_trade_date": str(
                    result.market_data_quality.get("target_trade_date") or ""
                ),
                "requirement_version": stage_acceptance.get("schema_version", ""),
                "strategy_version": result.strategy_version,
                "code_hash": str(run_metadata.get("code_hash") or ""),
                "config_hash": str(run_metadata.get("config_hash") or ""),
            }
            audit_persistence = {"status": "unverified", "readback_verified": False}
            try:
                await asyncio.to_thread(
                    market_db.save_pipeline_run_audit, audit_payload
                )
                saved_audit = await asyncio.to_thread(
                    market_db.get_pipeline_run_audit,
                    str(run_metadata.get("run_id") or ""),
                )
                audit_persistence = {
                    "status": "verified"
                    if isinstance(saved_audit, dict)
                    and saved_audit.get("run_id") == str(run_metadata.get("run_id") or "")
                    and saved_audit.get("schema_version")
                    else "partial",
                    "readback_verified": bool(
                        isinstance(saved_audit, dict)
                        and saved_audit.get("run_id") == str(run_metadata.get("run_id") or "")
                    ),
                }
            except Exception as exc:
                audit_persistence = {
                    "status": "failed",
                    "readback_verified": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
            stage_acceptance["audit_persistence"] = audit_persistence
            result.market_data_quality["stage_acceptance"] = stage_acceptance
            audit_payload["audit_persistence"] = audit_persistence
            await asyncio.to_thread(
                market_db.save_pipeline_run_audit, audit_payload
            )
        await asyncio.to_thread(
            market_db.upsert_daily_learning,
            date.today().isoformat(),
            "execution_observability",
            (
                f"execution candidates={len(execution_decisions)}; "
                f"new BUY={execution_observability['new_buy_count']}; "
                f"new SELL={execution_observability['new_sell_count']}"
            ),
            execution_observability,
        )
        paper_snapshot = market_db.get_paper_portfolio()
        liveness = paper_liveness_status(
            market_db.get_learning_log(PAPER_LIVENESS_LOG_LIMIT),
            paper_snapshot.get("cash", 0.0),
            paper_snapshot.get("total_value", 0.0),
            alert_after_days=getattr(settings, "PAPER_LIVENESS_ALERT_DAYS", 5),
            minimum_cash_pct=getattr(settings, "PAPER_LIVENESS_MIN_CASH_PCT", 0.70),
            as_of_date=date.today().isoformat(),
        )
        result.market_data_quality["paper_liveness"] = liveness
        if liveness["alert"]:
            result.market_data_quality.setdefault("alerts", []).append(
                "paper_liveness_no_actionable_buy"
            )

        published = [
            decision for decision in decisions
            if is_publishable_recommendation(decision)
        ]
        result.top_picks = [_serialize_recommendation(d) for d in published[:10]]
        result.actionable_picks = [
            _serialize_recommendation(decision)
            for decision in published
            if is_actionable_recommendation(decision)
        ][:10]
        result.market_data_quality.update({
            "publication_status": (
                "published" if published else "no_valid_recommendation"
            ),
            "published_recommendation_count": len(published),
            "actionable_recommendation_count": len(result.actionable_picks),
            "publication_block_scope": (
                "global_run_quality; complete per-stock evidence may still publish"
            ),
            "publication_status_note": (
                "全局数据质量存在降级，但逐股票证据完整的候选仍可发布；"
                "published 不代表本轮全部候选可交易。"
                if publication_block_reasons and published else
                "published recommendations satisfy per-stock evidence and publication gates."
            ),
            "technical_watchlist_count": sum(
                decision.get("recommendation_tier") == "technical_watchlist"
                for decision in decisions
            ),
        })

        result.duration_seconds = time.time() - t0
        return result


# Singleton
pipeline_runner = AIPipelineRunner()
