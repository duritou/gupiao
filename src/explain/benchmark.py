"""Equal-weight market benchmark with a point-in-time universe.

The live scanner ranks the whole market from a 20亿 market-cap floor, so its
candidates are small and mid caps -- measured over the decisions on record,
82.7% sit below 200亿 and only 3.1% above 1000亿.  Comparing that book against
沪深300 attributes the size factor to stock selection.  An equal-weight average
of the same investable universe isolates selection instead.

The universe is resolved from ``stock_metadata_history`` as of the decision
date, never from ``stock_basic``, which holds essentially one current snapshot
and would leak later information into a historical filter.  Requiring a bar at
both window endpoints is itself point-in-time and drops suspensions and
delistings.

Every result carries a :class:`BenchmarkBasis`.  Coverage is uneven -- the
metadata table spans only 2026-08-31 onward while ``market_daily`` has 309
trading days -- so a day that could not be filtered is reported as such rather
than silently averaged in with the ones that could.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

MIN_MARKET_CAP_YI = 20.0

# A day whose metadata capture is complete enough to filter on.
_MIN_METADATA_ROWS = 1000

BASIS_FILTERED = "filtered"
BASIS_UNFILTERED = "unfiltered"
BASIS_UNRELIABLE_ST = "unreliable_st"


@dataclass(frozen=True, slots=True)
class BenchmarkBasis:
    """How the universe behind one benchmark number was resolved."""

    status: str
    metadata_date: str | None
    constituent_count: int
    reasons: tuple[str, ...] = ()

    @property
    def is_filtered(self) -> bool:
        return self.status == BASIS_FILTERED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metadata_date": self.metadata_date,
            "constituent_count": self.constituent_count,
            "reasons": list(self.reasons),
        }


def _metadata_date(conn: sqlite3.Connection, start_date: str) -> str | None:
    row = conn.execute(
        """SELECT MAX(as_of_date) FROM stock_metadata_history
            WHERE as_of_date <= ?""",
        (start_date,),
    ).fetchone()
    value = row[0] if row else None
    return str(value) if value else None


def _basis_for(conn: sqlite3.Connection, metadata_date: str | None) -> tuple[str, tuple[str, ...]]:
    """Classify how much filtering the metadata on this day can support."""
    if not metadata_date:
        return BASIS_UNFILTERED, ("no_point_in_time_metadata",)

    rows, capped, st_count = conn.execute(
        """SELECT COUNT(*),
                  SUM(CASE WHEN market_cap_yi IS NOT NULL THEN 1 ELSE 0 END),
                  SUM(CASE WHEN is_st = 1 THEN 1 ELSE 0 END)
             FROM stock_metadata_history WHERE as_of_date = ?""",
        (metadata_date,),
    ).fetchone()
    rows = int(rows or 0)
    if rows < _MIN_METADATA_ROWS:
        return BASIS_UNFILTERED, ("metadata_capture_incomplete",)
    if int(capped or 0) < rows // 2:
        return BASIS_UNFILTERED, ("market_cap_missing",)

    # Every real A-share session in this dataset carries ~200 ST names, so an
    # all-zero flag means it was written without being fetched -- 2026-09-07 to
    # 09-09 are exactly that.  Trusting it would quietly admit every ST stock.
    if int(st_count or 0) == 0:
        return BASIS_UNRELIABLE_ST, ("st_flag_unpopulated",)
    return BASIS_FILTERED, ()


def equal_weight_return(
    conn: sqlite3.Connection, start_date: str, end_date: str
) -> tuple[float | None, BenchmarkBasis]:
    """Equal-weight return of the investable universe from start to end.

    Returns ``(None, basis)`` when no constituent has bars at both endpoints.
    The mean of constituent returns is the equal-weight buy-and-hold return
    over a single window, so no rebalancing assumption is smuggled in.
    """
    metadata_date = _metadata_date(conn, start_date)
    status, reasons = _basis_for(conn, metadata_date)

    # Apply each filter only when its input is trustworthy.  A day with a
    # broken ST flag still has complete market caps, so it keeps the cap filter
    # and loses only the ST one -- dropping both would widen the universe past
    # even the unfiltered case.
    use_cap = status in (BASIS_FILTERED, BASIS_UNRELIABLE_ST) and metadata_date
    use_st = status == BASIS_FILTERED

    # Parameters are listed in the order they appear in the SQL below.
    params: list[Any] = [start_date, end_date]
    metadata_join = ""
    if use_cap:
        metadata_join = (
            "JOIN stock_metadata_history m "
            "ON m.ts_code = f.ts_code AND m.as_of_date = ?"
        )
        params.append(metadata_date)

    clauses = []
    if use_cap:
        clauses.append("m.market_cap_yi IS NOT NULL AND m.market_cap_yi >= ?")
        params.append(MIN_MARKET_CAP_YI)
    if use_st:
        clauses.append("COALESCE(m.is_st, 0) = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = conn.execute(
        f"""WITH first_bar AS (
                SELECT ts_code, close FROM market_daily
                 WHERE trade_date = ? AND close > 0
            ), last_bar AS (
                SELECT ts_code, close FROM market_daily
                 WHERE trade_date = ? AND close > 0
            )
            SELECT f.close, l.close
              FROM first_bar f
              JOIN last_bar l ON l.ts_code = f.ts_code
              {metadata_join}
              {where}""",
        tuple(params),
    ).fetchall()
    constituents = len(rows)
    returns = [(float(last) / float(first)) - 1.0 for first, last in rows if first]

    basis = BenchmarkBasis(
        status=status,
        metadata_date=metadata_date,
        constituent_count=constituents,
        reasons=reasons,
    )
    if not returns:
        return None, basis
    return sum(returns) / len(returns), basis
