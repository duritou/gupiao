"""Isolated TradingAgents worker used by the Adaptive pipeline.

The Adaptive API and TradingAgents intentionally keep separate virtual
environments.  This worker accepts one JSON request on stdin and emits one JSON
response on stdout so dependency versions cannot contaminate the API process.
"""

from __future__ import annotations

import contextlib
import asyncio
import io
import json
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        from src.agents.codex_stock_analyzer import _analyze_one

        def report_progress(progress: dict) -> None:
            sys.stderr.write(
                "PROGRESS " + json.dumps(progress, ensure_ascii=False) + "\n"
            )
            sys.stderr.flush()

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = asyncio.run(_analyze_one(
                {"stock_code": str(payload.get("code") or "")},
                str(payload.get("trade_date") or ""),
                str(payload.get("past_context") or ""),
            ))
            report_progress({
                "provider": "codex_cli",
                "runtime": "codex_cli",
                "has_final_decision": bool(result),
            })
        sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
