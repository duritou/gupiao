"""Local Market Database — v7.5 Data Foundation.

SQLite-based local data warehouse. Sync once daily from baostock.
AI queries local DB — no network, no API rate limits, no anti-scraping.

Tables:
  stock_basic      — stock code, name, industry
  market_daily     — OHLCV per stock per day
  indicator_daily  — pre-computed MACD/RSI/KDJ/MA/Volume signals
  sync_log         — sync history for incremental updates

After initial sync: Scanner 5000 stocks in <2s (SQL vs 30s API).
Replay: SELECT date range instead of re-fetching from API.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, date as dt_date, timedelta
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).parent / "market_data.db"


@dataclass
class SyncResult:
    """Result of a data sync operation."""
    new_daily: int = 0
    new_indicators: int = 0
    stocks_updated: int = 0
    errors: list[str] = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class MarketDatabase:
    """Local SQLite market data warehouse."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stock_basic (
                    ts_code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    industry TEXT DEFAULT '',
                    list_date TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS market_daily (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL DEFAULT 0,
                    high REAL DEFAULT 0,
                    low REAL DEFAULT 0,
                    close REAL DEFAULT 0,
                    pre_close REAL DEFAULT 0,
                    change_pct REAL DEFAULT 0,
                    volume REAL DEFAULT 0,
                    amount REAL DEFAULT 0,
                    turnover REAL DEFAULT 0,
                    PRIMARY KEY (ts_code, trade_date)
                );

                CREATE INDEX IF NOT EXISTS idx_market_daily_date
                    ON market_daily(trade_date);
                CREATE INDEX IF NOT EXISTS idx_market_daily_code
                    ON market_daily(ts_code);

                CREATE TABLE IF NOT EXISTS indicator_daily (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    macd_score REAL DEFAULT 50,
                    rsi_score REAL DEFAULT 50,
                    kdj_score REAL DEFAULT 50,
                    ma_score REAL DEFAULT 50,
                    volume_score REAL DEFAULT 50,
                    fusion_score REAL DEFAULT 50,
                    direction TEXT DEFAULT 'neutral',
                    confidence REAL DEFAULT 0,
                    PRIMARY KEY (ts_code, trade_date)
                );

                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    new_rows INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                );

                CREATE TABLE IF NOT EXISTS decision_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    ai_score REAL DEFAULT 50,
                    direction TEXT DEFAULT 'neutral',
                    confidence REAL DEFAULT 0,
                    recommendation TEXT DEFAULT '',
                    fusion_score REAL DEFAULT 50,
                    macd_score REAL DEFAULT 50,
                    rsi_score REAL DEFAULT 50,
                    kdj_score REAL DEFAULT 50,
                    ma_score REAL DEFAULT 50,
                    volume_score REAL DEFAULT 50,
                    buy_signals INTEGER DEFAULT 0,
                    sell_signals INTEGER DEFAULT 0,
                    evidence TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    outcome_known INTEGER DEFAULT 0,
                    was_correct INTEGER DEFAULT NULL,
                    actual_return REAL DEFAULT NULL,
                    outcome_checked_at TEXT DEFAULT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decision_date
                    ON decision_journal(decision_date);
                CREATE INDEX IF NOT EXISTS idx_decision_code
                    ON decision_journal(stock_code);
            """)

    # ================================================================
    # Sync — pull from baostock into local DB
    # ================================================================

    def sync_daily_bars(
        self, codes: list[str] | None = None,
        days_back: int = 30,
        progress_callback=None,
    ) -> SyncResult:
        """Sync daily OHLCV data from baostock to local DB.

        Args:
            codes: Stock codes to sync. None = use default universe.
            days_back: How many days back to sync.
            progress_callback: Optional callback(stock_idx, total, code, status)

        Returns:
            SyncResult with counts and errors.
        """
        import baostock as bs
        from src.infrastructure.market_data.baostock_lock import mark_sync_start, mark_sync_end

        result = SyncResult()
        t0 = time.time()
        started_iso = datetime.now().isoformat()
        today = dt_date.today()

        # 标记同步进行中:API 侧 baostock fallback 将跳过,避免与长 session 互踢
        mark_sync_start()
        try:
            lg = bs.login()
            if lg.error_code != '0':
                result.errors.append(f"baostock login failed: {lg.error_msg}")
                self._record_sync_log("daily_bars", started_iso,
                                      datetime.now().isoformat(), 0, "failed")
                return result

            # codes=None:在已 login 会话内拉真实全 A 股(替代返回空的 _get_default_universe)
            if codes is None:
                universe = self._fetch_baostock_universe(bs)
                codes = [u["code"] for u in universe]
                # 批量初始化 stock_basic(名称来自 baostock code_name)
                if universe:
                    today_iso = today.isoformat()
                    with self._get_conn() as conn:
                        for u in universe:
                            conn.execute(
                                """INSERT OR REPLACE INTO stock_basic(ts_code, name, updated_at)
                                   VALUES (?, ?, ?)""",
                                (u["code"], u["name"], today_iso),
                            )
                if not codes:
                    result.errors.append("baostock universe fetch returned empty")

            for idx, code in enumerate(codes):
                try:
                    # Convert code format
                    if ".SH" in code:
                        bs_code = f"sh.{code.replace('.SH', '')}"
                    elif ".SZ" in code:
                        bs_code = f"sz.{code.replace('.SZ', '')}"
                    elif ".BJ" in code:
                        bs_code = f"bj.{code.replace('.BJ', '')}"
                    else:
                        continue

                    start = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
                    end = today.strftime('%Y-%m-%d')

                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        'date,open,high,low,close,preclose,volume,amount,turn',
                        start_date=start, end_date=end,
                        frequency='d', adjustflag='3',
                    )

                    if rs.error_code != '0':
                        continue

                    rows = []
                    while (rs.error_code == '0') & rs.next():
                        rows.append(rs.get_row_data())

                    if not rows:
                        continue

                    # Also get stock name if not in DB
                    stock_name = code
                    try:
                        rs_name = bs.query_stock_basic(code=bs_code)
                        if rs_name.error_code == '0':
                            name_rows = []
                            while rs_name.next():
                                name_rows.append(rs_name.get_row_data())
                            if name_rows and len(name_rows[0]) > 1:
                                stock_name = name_rows[0][1]
                    except Exception:
                        pass

                    # Upsert into local DB
                    with self._get_conn() as conn:
                        conn.execute(
                            """INSERT OR REPLACE INTO stock_basic(ts_code, name, updated_at)
                               VALUES (?, ?, ?)""",
                            (code, stock_name, today.isoformat()),
                        )

                        for r in rows:
                            if not r[0] or not r[4]:
                                continue
                            close = float(r[4]) if r[4] else 0
                            pre_close = float(r[5]) if r[5] else float(r[1]) if r[1] else close
                            change_pct = ((close - pre_close) / pre_close * 100) if pre_close > 0 else 0

                            conn.execute(
                                """INSERT OR REPLACE INTO market_daily
                                   (ts_code, trade_date, open, high, low, close,
                                    pre_close, change_pct, volume, amount, turnover)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    code, r[0],
                                    float(r[1]) if r[1] else 0,
                                    float(r[2]) if r[2] else 0,
                                    float(r[3]) if r[3] else 0,
                                    close, pre_close, round(change_pct, 2),
                                    float(r[6]) if r[6] else 0,
                                    float(r[7]) if r[7] else 0,
                                    float(r[8]) if len(r) > 8 and r[8] else 0,
                                ),
                            )
                            result.new_daily += 1

                    result.stocks_updated += 1

                    if progress_callback:
                        progress_callback(idx + 1, len(codes), code, "ok")

                except Exception as e:
                    result.errors.append(f"{code}: {str(e)[:80]}")
                    if progress_callback:
                        progress_callback(idx + 1, len(codes), code, f"err: {str(e)[:40]}")

            # Record sync log(用真实起始时间 started_iso,而非循环结束时刻)
            self._record_sync_log(
                "daily_bars", started_iso,
                datetime.now().isoformat(), result.new_daily, "completed",
            )

        finally:
            try:
                bs.logout()
            except Exception:
                pass
            mark_sync_end()

        result.duration_seconds = time.time() - t0
        return result

    def _record_sync_log(self, sync_type, started_at, completed_at, new_rows, status):
        """写一条 sync_log 记录(容错,不抛错)。"""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO sync_log (sync_type, started_at, completed_at, new_rows, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sync_type, started_at, completed_at, new_rows, status),
                )
        except Exception:
            pass

    def _fetch_baostock_universe(self, bs) -> list[dict]:
        """在已 login 的 baostock 会话上拉取全 A 股股票池。

        复用 get_stock_universe 的过滤逻辑(仅 sh./sz.、tradeStatus 正常)。
        非交易日 query_all_stock 可能返回空,因此向前回溯最多 5 天。
        返回 [{"code": "600000.SH", "name": "浦发银行"}, ...]。
        """
        universe: list[dict] = []
        try:
            today = dt_date.today()
            for offset in range(5):
                query_date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
                rs = bs.query_all_stock(day=query_date)
                if rs.error_code != '0':
                    continue
                while rs.next():
                    item = dict(zip(rs.fields, rs.get_row_data()))
                    raw_code = item.get("code", "")
                    if not raw_code.startswith(("sh.", "sz.")):
                        continue
                    # 排除指数:上证 000xxx 系列(上证综指等)、深证 399xxx 系列(深证成指等)
                    if raw_code.startswith("sh.000") or raw_code.startswith("sz.399"):
                        continue
                    if item.get("tradeStatus") not in ("", "1"):
                        continue
                    suffix = "SH" if raw_code.startswith("sh.") else "SZ"
                    normalized = f"{raw_code[3:]}.{suffix}"
                    universe.append({"code": normalized, "name": item.get("code_name", normalized)})
                if universe:
                    break
        except Exception:
            pass
        return universe

    def compute_and_store_indicators(self, codes: list[str] | None = None) -> int:
        """Pre-compute MACD/RSI/KDJ/MA/Volume for all stocks in local DB.

        Reads OHLCV from market_daily, computes indicators, stores in indicator_daily.
        This is the key performance optimization — signals are pre-computed,
        not calculated on every request.
        """
        from src.infrastructure.market_data.real_data_provider import real_data

        if codes is None:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT ts_code FROM market_daily"
                ).fetchall()
                codes = [r["ts_code"] for r in rows]

        total_computed = 0

        for code in codes:
            try:
                # Get all daily bars for this stock from local DB
                daily = self.get_daily_bars(code, limit=300)
                if len(daily) < 20:
                    continue

                # Get stock name
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT name FROM stock_basic WHERE ts_code=?",
                        (code,),
                    ).fetchone()
                    name = row["name"] if row else code

                # Compute signals
                sig = real_data.compute_signals(code, name, daily)

                # Store latest indicator
                latest_date = daily[-1]["date"]
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO indicator_daily
                           (ts_code, trade_date, macd_score, rsi_score,
                            kdj_score, ma_score, volume_score,
                            fusion_score, direction, confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            code, latest_date,
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score,
                            sig.volume_score, sig.fusion_score,
                            sig.direction, sig.confidence,
                        ),
                    )
                    total_computed += 1

            except Exception:
                continue

        return total_computed

    # ================================================================
    # Query — local, fast, no network
    # ================================================================

    def get_daily_bars(
        self, code: str, limit: int = 250
    ) -> list[dict]:
        """Get daily OHLCV bars from local DB. No network, <2ms."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close,
                          volume, amount, change_pct
                   FROM market_daily
                   WHERE ts_code=?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (code, limit),
            ).fetchall()

        # Return chronological order (oldest first)
        rows = list(reversed(rows))
        return [
            {
                "date": r["trade_date"],
                "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"],
                "volume": r["volume"], "amount": r["amount"],
            }
            for r in rows
        ]

    def get_latest_quote(self, code: str) -> dict | None:
        """Get latest quote from local DB."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT m.*, s.name, i.fusion_score, i.direction, i.confidence
                   FROM market_daily m
                   LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                   LEFT JOIN indicator_daily i
                     ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date
                   WHERE m.ts_code=?
                   ORDER BY m.trade_date DESC
                   LIMIT 1""",
                (code,),
            ).fetchone()

            if row is None:
                return None

            return {
                "code": row["ts_code"],
                "name": row["name"] or code,
                "price": row["close"],
                "open": row["open"], "high": row["high"], "low": row["low"],
                "pre_close": row["pre_close"],
                "change_pct": row["change_pct"],
                "volume": row["volume"], "amount": row["amount"],
                "turnover": row["turnover"] or 0,
                "pe": 0, "pb": 0, "total_market_cap": 0,
                "data_date": row["trade_date"],
                "fusion_score": row["fusion_score"] or 50,
                "direction": row["direction"] or "neutral",
                "confidence": row["confidence"] or 0,
                "source": "local_db",
                "source_name": "本地数据库 (SQLite)",
            }

    def get_all_latest_quotes(
        self, codes: list[str] | None = None,
    ) -> list[dict]:
        """Get latest quotes for multiple stocks. Bulk query, very fast."""
        with self._get_conn() as conn:
            if codes:
                placeholders = ",".join("?" * len(codes))
                rows = conn.execute(
                    f"""SELECT m.ts_code, m.trade_date, m.close, m.change_pct,
                               m.volume, m.amount, s.name,
                               i.fusion_score, i.direction, i.confidence
                        FROM market_daily m
                        JOIN (
                            SELECT ts_code, MAX(trade_date) as max_date
                            FROM market_daily
                            WHERE ts_code IN ({placeholders})
                            GROUP BY ts_code
                        ) latest ON m.ts_code = latest.ts_code
                            AND m.trade_date = latest.max_date
                        LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                        LEFT JOIN indicator_daily i
                            ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date""",
                    codes,
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT m.ts_code, m.trade_date, m.close, m.change_pct,
                              m.volume, m.amount, s.name,
                              i.fusion_score, i.direction, i.confidence
                       FROM market_daily m
                       JOIN (
                           SELECT ts_code, MAX(trade_date) as max_date
                           FROM market_daily GROUP BY ts_code
                       ) latest ON m.ts_code = latest.ts_code
                           AND m.trade_date = latest.max_date
                       LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                       LEFT JOIN indicator_daily i
                           ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date""",
                ).fetchall()

        return [
            {
                "code": r["ts_code"],
                "name": r["name"] or r["ts_code"],
                "price": r["close"],
                "change_pct": r["change_pct"] or 0,
                "volume": r["volume"] or 0,
                "amount": r["amount"] or 0,
                "fusion_score": r["fusion_score"] or 50,
                "direction": r["direction"] or "neutral",
                "confidence": r["confidence"] or 0,
                "data_date": r["trade_date"],
            }
            for r in rows
        ]

    def get_indicator(
        self, code: str, days: int = 30
    ) -> list[dict]:
        """Get pre-computed indicator history."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, macd_score, rsi_score, kdj_score,
                          ma_score, volume_score, fusion_score, direction
                   FROM indicator_daily
                   WHERE ts_code=?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (code, days),
            ).fetchall()

        return [dict(r) for r in reversed(rows)]

    # ================================================================
    # Decision Journal — AI decision persistence
    # ================================================================

    def save_decision(self, decision: dict) -> int:
        """Save an AI decision to the journal. Returns row id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO decision_journal
                   (decision_date, stock_code, stock_name, ai_score,
                    direction, confidence, recommendation,
                    fusion_score, macd_score, rsi_score, kdj_score,
                    ma_score, volume_score, buy_signals, sell_signals,
                    evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.get("date", ""),
                    decision.get("stock_code", ""),
                    decision.get("stock_name", ""),
                    decision.get("ai_score", 50),
                    decision.get("direction", "neutral"),
                    decision.get("confidence", 0),
                    decision.get("recommendation", ""),
                    decision.get("fusion_score", 50),
                    decision.get("macd_score", 50),
                    decision.get("rsi_score", 50),
                    decision.get("kdj_score", 50),
                    decision.get("ma_score", 50),
                    decision.get("volume_score", 50),
                    decision.get("buy_signals", 0),
                    decision.get("sell_signals", 0),
                    decision.get("evidence", ""),
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """Get recent AI decisions from the journal."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM decision_journal
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_decision_stats(self) -> dict:
        """Get journal statistics for Trust/Resume display."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal"
            ).fetchone()["n"]
            verified = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal WHERE outcome_known=1"
            ).fetchone()["n"]
            correct = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal WHERE outcome_known=1 AND was_correct=1"
            ).fetchone()["n"]
            by_direction = conn.execute(
                """SELECT direction, COUNT(*) as n,
                          SUM(CASE WHEN was_correct=1 THEN 1 ELSE 0 END) as correct
                   FROM decision_journal WHERE outcome_known=1
                   GROUP BY direction"""
            ).fetchall()

        return {
            "total_decisions": total,
            "verified_decisions": verified,
            "correct_decisions": correct,
            "accuracy": round(correct / verified, 3) if verified > 0 else 0,
            "by_direction": [
                {
                    "direction": r["direction"],
                    "count": r["n"],
                    "correct": r["correct"] or 0,
                }
                for r in by_direction
            ],
        }

    def get_stats(self) -> dict:
        """Database statistics for monitoring."""
        with self._get_conn() as conn:
            stocks = conn.execute(
                "SELECT COUNT(*) as n FROM stock_basic"
            ).fetchone()["n"]
            daily = conn.execute(
                "SELECT COUNT(*) as n FROM market_daily"
            ).fetchone()["n"]
            indicators = conn.execute(
                "SELECT COUNT(*) as n FROM indicator_daily"
            ).fetchone()["n"]
            latest_date = conn.execute(
                "SELECT MAX(trade_date) as d FROM market_daily"
            ).fetchone()["d"]
            last_sync = conn.execute(
                "SELECT completed_at FROM sync_log WHERE status='completed' ORDER BY id DESC LIMIT 1"
            ).fetchone()

        return {
            "stocks": stocks,
            "daily_bars": daily,
            "indicators": indicators,
            "latest_data_date": latest_date,
            "last_sync": last_sync["completed_at"] if last_sync else None,
            "db_path": str(self.db_path),
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1)
                if self.db_path.exists() else 0,
        }


# Singleton
market_db = MarketDatabase()
