"""Compare baseline and candidate algorithms from local frozen snapshots only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.replay.algorithm_comparator import compare_algorithms  # noqa: E402


def _load_snapshots(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(payload, dict):
        payload = payload.get("snapshots") or []
    if not isinstance(payload, list):
        raise ValueError("snapshot file must contain a JSON list or JSONL records")
    return [item for item in payload if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two algorithms on frozen local snapshots; no network access."
    )
    parser.add_argument("snapshot_file", type=Path)
    args = parser.parse_args()
    result = compare_algorithms(_load_snapshots(args.snapshot_file))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
