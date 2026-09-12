"""Legacy compatibility bridge for the retired TradingAgents-Astock graph.

The scheduled stock loop uses ``codex_stock_analyzer``. The old graph code is
kept below only for backwards compatibility with saved integrations and is no
longer an active analysis entry point.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

_SHARED_PYTHON = Path(__file__).resolve().parents[3] / "shared" / "python"
if str(_SHARED_PYTHON) not in sys.path:
    sys.path.insert(0, str(_SHARED_PYTHON))
from investment_common import plain_code  # noqa: E402


DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "tradingagents" / "astock"
WORKER_PATH = Path(__file__).with_name("tradingagents_worker.py")
DEFAULT_ANALYSTS = ("market", "news", "fundamentals")
ALLOWED_ANALYSTS = {
    "market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"
}
EXECUTION_GUARDRAIL_MARKER = "[Adaptive execution hard limit]"
EXECUTION_GUARDRAIL = (
    f"{EXECUTION_GUARDRAIL_MARKER}\n"
    "硬性执行约束（优先级最高）：模拟账户初始资金10万元；单只股票的实际持仓和"
    "建议初始仓位均不得超过账户总资产20%；禁止建议五成、50%或任何超过20%的单票"
    "仓位；只有最终Rating为Buy或Overweight时才允许新开仓。最终交易计划必须明确"
    "写出‘单票正常仓位上限20%’，其他研究中的仓位建议一律由此规则覆盖。"
)


def _with_execution_guardrail(past_context: str = "") -> str:
    """Inject the hard paper-trading policy into the portfolio-manager prompt."""
    context = str(past_context or "").strip()
    if EXECUTION_GUARDRAIL_MARKER in context:
        return context
    return f"{EXECUTION_GUARDRAIL}\n\n{context}".strip()


def _guarded_plan(text: str) -> str:
    """Make the effective execution cap explicit in every displayed plan."""
    return (
        "**Execution Guardrail**: 单只股票正常仓位硬上限为账户总资产20%；"
        "下文如出现更高仓位建议，均不执行。\n\n"
        f"{str(text or '').strip()}"
    ).strip()


def _source() -> Path:
    return Path(os.environ.get("TRADINGAGENTS_SOURCE", str(DEFAULT_SOURCE))).resolve()


def _worker_python() -> Path | None:
    override = os.environ.get("TRADINGAGENTS_PYTHON")
    candidates = [Path(override)] if override else []
    source = _source()
    if os.name == "nt":
        candidates.append(source / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(source / ".venv" / "bin" / "python")
    return next((path for path in candidates if path.is_file()), None)


def _in_process_available() -> bool:
    return importlib.util.find_spec("langgraph") is not None


def _use_in_process() -> bool:
    """Prefer the isolated TradingAgents environment when it is available."""
    requested = os.environ.get("TRADINGAGENTS_EXECUTION_MODE", "").strip().lower()
    if requested == "in_process":
        return _in_process_available()
    if requested == "isolated":
        return False
    return _in_process_available() and _worker_python() is None


def _selected_analysts() -> list[str]:
    raw = os.environ.get("TRADINGAGENTS_ANALYSTS", "").strip()
    values = [item.strip().lower() for item in raw.split(",")] if raw else []
    selected = [item for item in values if item in ALLOWED_ANALYSTS]
    return selected or list(DEFAULT_ANALYSTS)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


def availability_status() -> dict[str, Any]:
    from src.agents.codex_stock_analyzer import availability_status as codex_status

    status = codex_status()
    return {
        **status,
        "source": "Codex-Terra Multi-Agent",
        "analysts": _selected_analysts(),
    }


def is_available() -> bool:
    return bool(availability_status()["available"])


def _ticker(code: str) -> str:
    return plain_code(code)


def _rating_to_signal(rating: str) -> tuple[str, float]:
    value = rating.lower()
    if value == "buy":
        return "buy", 85.0
    if value == "overweight":
        return "buy", 72.0
    if value == "underweight":
        return "sell", 35.0
    if value == "sell":
        return "sell", 20.0
    return "neutral", 50.0


def _run_one(
    code: str,
    trade_date: str,
    past_context: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    # Keep the private compatibility symbol on the Codex-native path too.
    # The former graph implementation below is intentionally unreachable.
    from src.agents.codex_stock_analyzer import _analyze_one as codex_analyze_one

    result = asyncio.run(
        codex_analyze_one(
            {"stock_code": code},
            trade_date,
            _with_execution_guardrail(past_context),
        )
    )
    if progress_callback:
        progress_callback({
            "provider": "codex_cli",
            "runtime": "codex_cli",
            "has_final_decision": bool(result),
        })
    return result

    from config.settings import settings

    source = _source()
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

    # TradingAgents reads provider credentials from the process environment,
    # while the application reads them from pydantic-settings/.env. Bridge
    # the two at runtime without writing or printing the credential.
    api_key = os.environ.get("DEEPSEEK_API_KEY") or settings.DEEPSEEK_API_KEY
    if api_key:
        os.environ.setdefault("DEEPSEEK_API_KEY", api_key)

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = (
        os.environ.get("AI_PRIMARY_PROVIDER")
        or os.environ.get("TRADINGAGENTS_LLM_PROVIDER")
        or "codex_cli"
    )
    model = (
        os.environ.get("AI_FAST_MODEL")
        or os.environ.get("CODEX_MODEL")
        or settings.CODEX_MODEL
    )
    config["deep_think_llm"] = (
        os.environ.get("AI_DEEP_MODEL")
        or os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM")
        or os.environ.get("TRADINGAGENTS_DEEP_MODEL")
        or model
    )
    config["quick_think_llm"] = (
        os.environ.get("AI_FAST_MODEL")
        or os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM")
        or os.environ.get("TRADINGAGENTS_QUICK_MODEL")
        or model
    )
    config["output_language"] = "Chinese"
    config["checkpoint_enabled"] = False
    # The upstream default graph uses seven analysts plus two full debate
    # circuits.  That is useful interactively, but too slow for a scheduled
    # top-5 pipeline.  The daily profile keeps three complementary analysts
    # and one synthesis/risk pass; environment variables can opt back into a
    # heavier run.
    config["max_debate_rounds"] = _bounded_env_int(
        "TRADINGAGENTS_DEBATE_ROUNDS", 0, 0, 3
    )
    config["max_risk_discuss_rounds"] = _bounded_env_int(
        "TRADINGAGENTS_RISK_ROUNDS", 0, 0, 3
    )
    config["llm_timeout_seconds"] = _bounded_env_int(
        "TRADINGAGENTS_LLM_TIMEOUT_SECONDS", 60, 10, 120
    )
    config["llm_max_retries"] = _bounded_env_int(
        "TRADINGAGENTS_LLM_MAX_RETRIES", 2, 0, 4
    )
    config["llm_max_tokens"] = _bounded_env_int(
        "TRADINGAGENTS_LLM_MAX_TOKENS", 1000, 256, 4096
    )
    config["llm_streaming"] = True
    # DeepSeek V4 defaults to thinking mode. Its thinking mode rejects the
    # forced tool_choice used by LangChain structured output, so the scheduled
    # graph explicitly uses V4 Flash in non-thinking mode.
    config["deepseek_thinking_type"] = "disabled"
    if config["llm_provider"] == "deepseek":
        # Keep the isolated TradingAgents worker on the same explicit endpoint
        # as the Adaptive router.  This avoids one process using /v1 while the
        # other silently falls back to a different default.
        config["backend_url"] = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or settings.DEEPSEEK_BASE_URL
        )
    config["memory_log_path"] = str(DEFAULT_CONFIG["memory_log_path"])

    graph = TradingAgentsGraph(
        selected_analysts=_selected_analysts(), debug=False, config=config
    )
    initial_state, args, _ = graph.prepare_graph_run(_ticker(code), trade_date)
    if initial_state is not None:
        initial_state["past_context"] = _with_execution_guardrail(past_context)
    try:
        final_state = None
        for step, state in enumerate(graph.graph.stream(initial_state, **args), start=1):
            final_state = state
            if progress_callback:
                messages = state.get("messages") or []
                last_message = messages[-1] if messages else None
                progress_callback({
                    "step": step,
                    "last_message": (
                        getattr(last_message, "name", None)
                        or type(last_message).__name__ if last_message else ""
                    ),
                    "reports": [
                        name for name in (
                            "market_report", "news_report", "fundamentals_report",
                            "sentiment_report", "policy_report", "hot_money_report",
                            "lockup_report",
                        ) if state.get(name)
                    ],
                    "debate_count": (state.get("investment_debate_state") or {}).get(
                        "count", 0
                    ),
                    "risk_count": (state.get("risk_debate_state") or {}).get(
                        "count", 0
                    ),
                    "has_final_decision": bool(state.get("final_trade_decision")),
                })
        if not isinstance(final_state, dict):
            raise RuntimeError("TradingAgents graph returned no final state")
        graph.finalize_graph_run(_ticker(code), trade_date, final_state)
        raw_decision = str(final_state.get("final_trade_decision", ""))
        rating = "Hold"
        for candidate in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            if f"**Rating**: {candidate}" in raw_decision:
                rating = candidate
                break
        direction, score = _rating_to_signal(rating)
        return {
            "available": True,
            "rating": rating,
            "direction": direction,
            "score": score,
            "decision": _guarded_plan(raw_decision),
            "thesis": str(final_state.get("investment_plan", "")),
            "trader_plan": _guarded_plan(
                str(final_state.get("trader_investment_plan", ""))
            ),
            "source": "TradingAgents-Astock",
            "provider": config["llm_provider"],
            "model": config["quick_think_llm"],
        }
    finally:
        graph.close_graph_run()


async def _run_one_subprocess(
    code: str, trade_date: str, past_context: str = ""
) -> dict[str, Any]:
    """Run TradingAgents in its own venv to avoid dependency collisions."""
    from config.settings import settings

    python = _worker_python()
    if not python:
        raise RuntimeError("TradingAgents worker Python is unavailable")
    env = os.environ.copy()
    env.setdefault("TRADINGAGENTS_SOURCE", str(_source()))
    env.setdefault("AI_PRIMARY_PROVIDER", "codex_cli")
    env.setdefault("AI_FAST_MODEL", settings.CODEX_MODEL)
    env.setdefault("AI_DEEP_MODEL", settings.CODEX_MODEL)
    env.setdefault("TRADINGAGENTS_LLM_MAX_RETRIES", "2")
    env.setdefault("PYTHONUTF8", "1")
    try:
        timeout_seconds = max(
            10.0, float(env.get("TRADINGAGENTS_ANALYSIS_TIMEOUT_SECONDS", "240"))
        )
    except ValueError:
        timeout_seconds = 240.0
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = await asyncio.create_subprocess_exec(
        str(python),
        str(WORKER_PATH),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        creationflags=creationflags,
    )
    payload = json.dumps(
        {
            "code": code,
            "trade_date": trade_date,
            "past_context": _with_execution_guardrail(past_context),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    communicate_task = asyncio.create_task(process.communicate(payload))
    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(communicate_task), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        stdout, stderr = await communicate_task
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"TradingAgents timed out after {timeout_seconds:.0f}s; "
            f"last progress: {stderr_text[-800:]}"
        ) from exc
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    try:
        envelope = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        if process.returncode:
            raise RuntimeError(
                f"TradingAgents worker exited {process.returncode}: "
                f"{stderr_text[-300:]}"
            ) from exc
        raise RuntimeError(
            f"TradingAgents worker returned invalid JSON: {stderr_text[-300:]}"
        ) from exc
    if not envelope.get("ok"):
        raise RuntimeError(str(envelope.get("error") or "TradingAgents worker failed"))
    if process.returncode:
        raise RuntimeError(
            f"TradingAgents worker exited {process.returncode}: {stderr_text[-300:]}"
        )
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("TradingAgents worker returned no result")
    return result


async def analyze_candidates(
    candidates: list[dict], trade_date: str, past_context: str = "", limit: int = 3
) -> list[dict]:
    """Analyze only the top candidates through the Codex-native path."""
    runtime_status = availability_status()
    selected = candidates[: max(0, int(limit))]
    if not runtime_status.get("available"):
        reasons = ", ".join(runtime_status.get("reasons") or []) or "unknown"
        return [
            {
                "available": False,
                "stock_code": str(item.get("stock_code") or item.get("code") or ""),
                "error": f"TradingAgents unavailable: {reasons}",
                "error_type": "RuntimeUnavailable",
                "runtime": runtime_status.get("runtime", "unavailable"),
                "source": "TradingAgents-Astock",
            }
            for item in selected
        ]

    from src.agents.codex_stock_analyzer import analyze_candidates as codex_analyze

    return await codex_analyze(
        selected,
        trade_date,
        past_context,
        limit=len(selected),
    )

    # The code below is retained for old callers that copied the former
    # implementation, but the public entry point above is the only scheduled
    # path.
    if not candidates:
        return []
    selected = candidates[: max(0, limit)]
    runtime_status = availability_status()
    if not runtime_status["available"]:
        reasons = ", ".join(runtime_status.get("reasons") or []) or "unknown"
        return [
            {
                "available": False,
                "stock_code": str(item.get("stock_code") or item.get("code") or ""),
                "error": f"TradingAgents unavailable: {reasons}",
                "error_type": "RuntimeUnavailable",
                "runtime": runtime_status.get("runtime", "unavailable"),
                "source": "TradingAgents-Astock",
            }
            for item in selected
        ]
    run_in_process = runtime_status["runtime"] == "adaptive_process"
    concurrency = _bounded_env_int("TRADINGAGENTS_MAX_CONCURRENCY", 2, 1, 3)
    semaphore = asyncio.Semaphore(concurrency)
    governed_context = _with_execution_guardrail(past_context)

    async def analyze_one(candidate: dict) -> dict:
        code = str(candidate.get("stock_code") or candidate.get("code") or "")
        started = time.perf_counter()
        async with semaphore:
            try:
                if run_in_process:
                    result = await asyncio.to_thread(
                        _run_one, code, trade_date, governed_context
                    )
                else:
                    result = await _run_one_subprocess(
                        code, trade_date, governed_context
                    )
                result["stock_code"] = code
                result["runtime"] = runtime_status["runtime"]
                result["duration_seconds"] = round(time.perf_counter() - started, 2)
                return result
            except Exception as exc:  # Deep research is optional by design.
                return {
                    "available": False,
                    "stock_code": code,
                    "error": str(exc)[:240],
                    "error_type": type(exc).__name__,
                    "runtime": runtime_status["runtime"],
                    "duration_seconds": round(time.perf_counter() - started, 2),
                    "source": "TradingAgents-Astock",
                }

    return list(await asyncio.gather(*(analyze_one(item) for item in selected)))
