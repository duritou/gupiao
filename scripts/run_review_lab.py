"""One-shot bounded offline review, deliberately not attached to production scheduler."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.review_lab.replay import replay
from src.review_lab.store import lab_root


def main() -> None:
    source = ROOT / 'src/infrastructure/storage/market_data.db'
    started = time.monotonic()
    # No MarketDatabase singleton import: it would initialize/migrate production storage.
    connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=0.1)
    connection.execute('PRAGMA query_only=ON')
    connection.set_progress_handler(lambda: int(time.monotonic() - started > 2), 1000)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(
            'SELECT ts_code,trade_date,open,high,low,close,volume FROM market_daily '
            'WHERE ts_code IN (?,?,?) AND trade_date BETWEEN ? AND ? '
            'ORDER BY ts_code,trade_date LIMIT 9',
            ('600519.SH', '000001.SZ', '600036.SH', '2026-09-09', '2026-09-11'))]
    finally:
        connection.close()
    if len(rows) != 9:
        raise ValueError('Required Friday replay inputs are incomplete; no provider fallback')
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    result = replay(rows)
    result.update({'reference_only': True, 'schema_version': 1, 'date': '2026-09-11',
                   'input_sha256': hashlib.sha256(encoded).hexdigest(),
                   'source': 'local market_daily read-only extract; upstream provenance unverified',
                   'universe': '3 preselected demonstration stocks; not a market-wide selection',
                   'method': 'local illustrative rule, not upstream project execution',
                   'rows': rows})
    run_id = 'friday-' + uuid.uuid4().hex
    folder = lab_root() / run_id
    folder.mkdir(parents=True, exist_ok=False)
    output = folder / 'result.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'run_id': run_id, 'output': str(output), 'result': result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
