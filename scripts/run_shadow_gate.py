"""Evaluate the independent five-day shadow gate from local reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai_os.shadow_runner import load_persisted_shadow_reports  # noqa: E402
from src.replay.shadow_gate import evaluate_shadow_gate  # noqa: E402


def _load_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("reports") or []
    if not isinstance(payload, list):
        raise ValueError("shadow report file must contain a JSON list or reports field")
    return [item for item in payload if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require five distinct, non-executable shadow trading days."
    )
    parser.add_argument("report_file", type=Path, nargs="?")
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--required-days", type=int, default=5)
    args = parser.parse_args()
    if args.from_db and args.report_file:
        parser.error("use report_file or --from-db, not both")
    if args.from_db:
        reports = load_persisted_shadow_reports()
    elif args.report_file:
        reports = _load_file(args.report_file)
    else:
        parser.error("report_file or --from-db is required")
    result = evaluate_shadow_gate(reports, required_days=args.required_days)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.shadow_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
