"""Small SQLite backed request budget shared by Tushare processes.

The budget is deliberately conservative for a 2000-point account.  A
reservation is made before every SDK call, including retries, so the API,
daily sync and historical backfill cannot each assume an independent quota.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


class BudgetExhaustedError(RuntimeError):
    """The account's daily request budget is exhausted."""


_ACCOUNT_TIMEZONE = timezone(timedelta(hours=8))


class TushareRequestBudget:
    """Cross-process minute and daily request reservations."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        max_per_minute: int = 190,
        max_per_day: int = 95_000,
    ) -> None:
        default_path = Path(__file__).resolve().parents[3] / "data" / "tushare_request_budget.db"
        self.db_path = Path(db_path or os.getenv("TUSHARE_BUDGET_DB_PATH", default_path))
        self.max_per_minute = max(1, int(max_per_minute))
        self.max_per_day = max(1, int(max_per_day))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS request_usage (
                       bucket_minute INTEGER NOT NULL,
                       usage_date TEXT NOT NULL,
                       endpoint TEXT NOT NULL,
                       request_count INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY(bucket_minute, endpoint)
                   )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_usage_date ON request_usage(usage_date)"
            )

    def _try_reserve(self, endpoint: str) -> tuple[bool, bool]:
        now = time.time()
        bucket = int(now // 60)
        today = datetime.now(_ACCOUNT_TIMEZONE).date().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            minute_count = int(
                conn.execute(
                    "SELECT COALESCE(SUM(request_count), 0) FROM request_usage WHERE bucket_minute=?",
                    (bucket,),
                ).fetchone()[0]
                or 0
            )
            day_count = int(
                conn.execute(
                    "SELECT COALESCE(SUM(request_count), 0) FROM request_usage WHERE usage_date=?",
                    (today,),
                ).fetchone()[0]
                or 0
            )
            if day_count >= self.max_per_day:
                conn.rollback()
                return False, True
            if minute_count >= self.max_per_minute:
                conn.rollback()
                return False, False
            conn.execute(
                """INSERT INTO request_usage(bucket_minute, usage_date, endpoint, request_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(bucket_minute, endpoint) DO UPDATE SET
                     request_count=request_usage.request_count + 1""",
                (bucket, today, str(endpoint or "unknown")),
            )
            conn.commit()
        return True, False

    async def reserve(self, endpoint: str, *, max_wait_seconds: float = 65.0) -> float:
        """Reserve one request and return seconds spent waiting.

        Waiting is bounded so callers can record a rate-limit outcome instead
        of hanging an API request forever.
        """
        started = time.monotonic()
        deadline = started + max(0.1, float(max_wait_seconds))
        while True:
            reserved, daily_exhausted = await asyncio.to_thread(self._try_reserve, endpoint)
            if reserved:
                return round(time.monotonic() - started, 4)
            if daily_exhausted:
                raise BudgetExhaustedError("tushare_daily_request_budget_exhausted")
            if time.monotonic() >= deadline:
                raise BudgetExhaustedError("tushare_minute_request_budget_wait_timeout")
            now = time.time()
            delay = min(max(0.1, 60.0 - (now % 60.0) + 0.05), deadline - time.monotonic())
            await asyncio.sleep(max(0.1, delay))

    def usage(self) -> dict[str, int]:
        """Return redacted current usage for diagnostics."""
        today = datetime.now(_ACCOUNT_TIMEZONE).date().isoformat()
        bucket = int(time.time() // 60)
        with self._connect() as conn:
            minute = int(
                conn.execute(
                    "SELECT COALESCE(SUM(request_count), 0) FROM request_usage WHERE bucket_minute=?",
                    (bucket,),
                ).fetchone()[0]
                or 0
            )
            day = int(
                conn.execute(
                    "SELECT COALESCE(SUM(request_count), 0) FROM request_usage WHERE usage_date=?",
                    (today,),
                ).fetchone()[0]
                or 0
            )
        return {
            "current_minute": minute,
            "current_day": day,
            "max_per_minute": self.max_per_minute,
            "max_per_day": self.max_per_day,
        }
