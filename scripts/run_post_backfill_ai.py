"""Run one post-backfill AI research pass without paper execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def _run() -> dict:
    from src.ai_os.pipeline_runner import pipeline_runner

    result = await pipeline_runner.run_daily_pipeline(
        save_to_journal=True,
        execute_paper_trades=False,
        force_reanalysis=True,
        research_window="post_backfill",
    )
    return {
        "status": "success",
        "execute_paper_trades": False,
        "result": result.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persist one AI research pass after research-data backfill"
    )
    parser.add_argument("--execution-key", default="")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    try:
        payload = asyncio.run(_run())
    except Exception as exc:
        payload = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "execute_paper_trades": False,
        }
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 1
    payload.update({
        "execution_key": args.execution_key,
        "source_run_id": args.source_run_id,
        "data_revision": args.data_revision,
    })
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
