"""Run the minimum offline replay gate on a local snapshot file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.compare_algorithm_versions import _load_snapshots  # noqa: E402
from src.replay.historical_gate import evaluate_historical_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require complete frozen replay history before promotion."
    )
    parser.add_argument("snapshot_file", type=Path)
    parser.add_argument("--required-days", type=int, default=20)
    args = parser.parse_args()
    result = evaluate_historical_gate(
        _load_snapshots(args.snapshot_file), required_days=args.required_days
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.historical_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
