"""One-shot bounded offline review, deliberately not attached to production scheduler."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.review_lab.analysis import build_learning_summary, build_project_reviews  # noqa: E402
from src.review_lab.narrative import build_narrative, enrich_project_reviews  # noqa: E402
from src.review_lab.replay import replay  # noqa: E402
from src.review_lab.store import lab_root  # noqa: E402


def _load_snapshot(
    connection: sqlite3.Connection, requested_date: str | None
) -> tuple[list[dict[str, Any]], list[str], str, str | None]:
    """Read three sessions with one read-only query and return rows, dates and target."""
    target_date = requested_date or str(
        connection.execute("SELECT max(trade_date) FROM market_daily").fetchone()[0]
    )
    dates = sorted(
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT trade_date FROM market_daily WHERE trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT 3",
            (target_date,),
        )
    )
    if len(dates) != 3 or target_date not in dates:
        raise ValueError(f"Required three sessions ending at {target_date} are incomplete")
    placeholders = ",".join("?" for _ in dates)
    rows = [
        dict(row)
        for row in connection.execute(
            f"SELECT md.ts_code,md.trade_date,md.open,md.high,md.low,md.close,md.pre_close,"
            f"md.change_pct,md.volume,md.amount,md.turnover,sb.name,sb.industry "
            f"FROM market_daily md LEFT JOIN stock_basic sb ON sb.ts_code = md.ts_code "
            f"WHERE md.trade_date IN ({placeholders}) ORDER BY md.trade_date,md.ts_code",
            dates,
        )
    ]
    if not rows:
        raise ValueError("Required historical review inputs are empty; no provider fallback")
    indicator_latest = connection.execute("SELECT max(trade_date) FROM indicator_daily").fetchone()[
        0
    ]
    return rows, dates, target_date, str(indicator_latest) if indicator_latest else None


def _replay_inputs(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    """Use a small, deterministic top-signal set for the causal paper replay."""
    signal_date = dates[-3]
    candidates = [
        row
        for row in rows
        if row["trade_date"] == signal_date and float(row.get("change_pct") or 0) > 0
    ]
    candidates.sort(key=lambda row: float(row.get("change_pct") or 0), reverse=True)
    symbols = {str(row["ts_code"]) for row in candidates[:20]}
    return [row for row in rows if str(row["ts_code"]) in symbols]


def main() -> None:
    source = ROOT / "src/infrastructure/storage/market_data.db"
    requested_date = sys.argv[1] if len(sys.argv) > 1 else None
    started = time.monotonic()
    # No MarketDatabase singleton import: it would initialize/migrate production storage.
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
    connection.execute("PRAGMA query_only=ON")
    connection.set_progress_handler(lambda: int(time.monotonic() - started > 5), 1000)
    connection.row_factory = sqlite3.Row
    try:
        rows, dates, target_date, indicator_latest = _load_snapshot(connection, requested_date)
    finally:
        connection.close()
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    replay_result = replay(_replay_inputs(rows, dates))
    project_reviews = build_project_reviews(rows, dates, target_date, replay_result)
    narrative = build_narrative(rows, dates, target_date, project_reviews, replay_result)
    narrative["quality"]["indicator_daily_latest"] = indicator_latest
    if indicator_latest and indicator_latest != target_date:
        narrative["interpretations"].append(
            f"风险：指标表最新日期为 {indicator_latest}，未把它冒充成周五指标，也未用于本次结论。"
        )
    project_reviews = enrich_project_reviews(project_reviews, narrative)
    target_rows = [row for row in rows if row["trade_date"] == target_date]
    counts = {date: sum(1 for row in rows if row["trade_date"] == date) for date in dates}
    result: dict[str, Any] = {
        **replay_result,
        "reference_only": True,
        "schema_version": 1,
        "date": target_date,
        "input_as_of": target_date,
        "input_sha256": hashlib.sha256(encoded).hexdigest(),
        "source": "local market_daily + stock_basic read-only extract; "
        "upstream provenance unverified",
        "universe": "market-wide rows available in the local database for three sessions",
        "method": "seven local observation perspectives; not upstream project execution",
        "source_data": {
            "table": "market_daily",
            "dates": dates,
            "rows_by_date": counts,
            "target_rows": len(target_rows),
            "selected_replay_rows": len(_replay_inputs(rows, dates)),
            "indicator_daily_latest": indicator_latest,
        },
        "project_reviews": project_reviews,
        "narrative": narrative,
        "learning": build_learning_summary(project_reviews, target_date),
    }
    run_id = "friday-" + uuid.uuid4().hex
    folder = lab_root() / run_id
    folder.mkdir(parents=True, exist_ok=False)
    output = folder / "result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({"run_id": run_id, "output": str(output), "result": result}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
