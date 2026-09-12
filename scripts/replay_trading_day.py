"""Run a frozen, read-only end-to-end trading-cycle contract replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.replay.trading_cycle_replay import replay_trading_cycle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one frozen Adaptive Investment day without network or ledger writes."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = replay_trading_cycle(payload)
    rendered = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
