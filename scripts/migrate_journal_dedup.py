"""De-duplicate decision_journal and put the constraint into the schema.

Runs one transaction.  Nothing is committed unless every check passes, and the
final step -- creating UNIQUE(decision_date, stock_code) -- is itself the
acceptance test: if the de-duplication missed anything, the index cannot be
built and the whole migration rolls back with the data untouched.

Order matters and is deliberate.  References are re-pointed before anything is
deleted, so a failure leaves a consistent database rather than one with rows
pointing at ids that no longer exist.  This schema declares no foreign keys, so
nothing else would catch that.

The plan is recomputed inside the transaction rather than taken from
scripts/plan_journal_dedup.py's output: the service writes to this table, and a
frozen plan would be stale by the time it ran.  Run that script first to review
the expected numbers, then run this one during a maintenance window with the
service stopped.

Usage:
    .venv\\Scripts\\python.exe scripts\\migrate_journal_dedup.py
    .venv\\Scripts\\python.exe scripts\\migrate_journal_dedup.py --confirm --backup
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.plan_journal_dedup import build_plan  # noqa: E402
from src.infrastructure.storage.market_database import DB_PATH  # noqa: E402

UNIQUE_INDEX = "idx_decision_journal_unique"

# old journal id -> surviving id, for every row.  Re-pointing joins against this
# instead of repeating the group-by in each statement.
_ID_MAP = """
CREATE TEMP TABLE id_map AS
SELECT d.id AS old_id, k.keep_id
  FROM decision_journal d
  JOIN keep_journal k
    ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
"""

# Outcomes are backfilled onto whichever row a read path handed over, which is
# not always the survivor.  437 rows carry a result that exists nowhere else.
_MERGE_OUTCOMES = """
UPDATE decision_journal AS t
   SET (outcome_known, was_correct, actual_return, outcome_checked_at) = (
        SELECT d.outcome_known, d.was_correct, d.actual_return, d.outcome_checked_at
          FROM decision_journal d
         WHERE d.decision_date = t.decision_date
           AND d.stock_code = t.stock_code
           AND d.outcome_known = 1
         ORDER BY d.id DESC LIMIT 1)
 WHERE t.id IN (SELECT keep_id FROM keep_journal)
   AND t.outcome_known = 0
   AND EXISTS (SELECT 1 FROM decision_journal d2
                WHERE d2.decision_date = t.decision_date
                  AND d2.stock_code = t.stock_code
                  AND d2.outcome_known = 1)
"""

_REPOINT = {
    "paper_trade": """
        UPDATE paper_trade
           SET decision_id = (SELECT m.keep_id FROM id_map m
                               WHERE m.old_id = paper_trade.decision_id)
         WHERE decision_id IN (SELECT old_id FROM id_map WHERE old_id <> keep_id)
    """,
    "market_learning_observation": """
        UPDATE market_learning_observation
           SET decision_id = (SELECT m.keep_id FROM id_map m
                               WHERE m.old_id = market_learning_observation.decision_id)
         WHERE decision_id IN (SELECT old_id FROM id_map WHERE old_id <> keep_id)
    """,
}

# Must run BEFORE re-pointing.  Re-pointing two rows onto one survivor key
# violates UNIQUE(decision_id, horizon_days) mid-UPDATE, so the losers have to
# go first -- grouped by the id they will end up on, not the one they hold now.
_DEDUPE_OBSERVATIONS = """
DELETE FROM market_learning_observation WHERE id IN (
    SELECT id FROM (
        SELECT o.id, ROW_NUMBER() OVER (
                   PARTITION BY m.keep_id, o.horizon_days ORDER BY o.id DESC) AS rn
          FROM market_learning_observation o
          JOIN id_map m ON m.old_id = o.decision_id)
     WHERE rn > 1)
"""

_DELETE_REDUNDANT_STRATEGY = """
DELETE FROM strategy_decision
 WHERE id NOT IN (SELECT keep_sd_id FROM keep_strategy)
"""

_REPOINT_STRATEGY = """
UPDATE strategy_decision
   SET journal_id = (SELECT k.keep_id FROM keep_strategy k
                      WHERE k.keep_sd_id = strategy_decision.id),
       strategy_name = 'adaptive-paper:journal:' || (
           SELECT k.keep_id FROM keep_strategy k
            WHERE k.keep_sd_id = strategy_decision.id)
 WHERE id IN (SELECT keep_sd_id FROM keep_strategy)
"""

_DELETE_REDUNDANT_JOURNAL = """
DELETE FROM decision_journal WHERE id NOT IN (SELECT keep_id FROM keep_journal)
"""

_DANGLING = """
SELECT (SELECT COUNT(*) FROM strategy_decision s
         WHERE s.journal_id IS NOT NULL
           AND s.journal_id NOT IN (SELECT id FROM decision_journal))
     + (SELECT COUNT(*) FROM paper_trade t
         WHERE t.decision_id IS NOT NULL
           AND t.decision_id NOT IN (SELECT id FROM decision_journal))
     + (SELECT COUNT(*) FROM market_learning_observation o
         WHERE o.decision_id NOT IN (SELECT id FROM decision_journal))
"""


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def migrate(conn: sqlite3.Connection, *, confirm: bool, backup: bool) -> dict:
    """Apply the de-duplication. Commits only when every check passes."""
    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = DB_PATH.parent / f"market_data.db.pre-dedup-{stamp}"
        print(f"备份到 {target} ...")
        shutil.copy2(DB_PATH, target)
        print(f"  完成 ({target.stat().st_size / 1e9:.2f} GB)")

    conn.isolation_level = None
    conn.execute("PRAGMA busy_timeout=30000")
    # IMMEDIATE takes the write lock up front, so a running service cannot slip
    # a write in between the plan and the delete.
    conn.execute("BEGIN IMMEDIATE")
    try:
        plan = build_plan(conn)
        if not plan["conservation_ok"]:
            raise RuntimeError("conservation check failed on the current data")
        if plan["outcome_conflicts"]:
            raise RuntimeError(
                f"{plan['outcome_conflicts']} groups disagree on actual_return"
            )

        conn.execute(_ID_MAP)

        conn.execute(_MERGE_OUTCOMES)
        # Dedupe observations before re-pointing them: the collapse onto one
        # survivor key has to happen while the losers are still identifiable.
        conn.execute(_DEDUPE_OBSERVATIONS)
        for statement in _REPOINT.values():
            conn.execute(statement)
        conn.execute(_DELETE_REDUNDANT_STRATEGY)
        conn.execute(_REPOINT_STRATEGY)
        conn.execute(_DELETE_REDUNDANT_JOURNAL)

        dangling = _scalar(conn, _DANGLING)
        if dangling:
            raise RuntimeError(f"{dangling} references left dangling; rolling back")

        kept = _scalar(conn, "SELECT COUNT(*) FROM decision_journal")
        if kept != plan["unique_groups"]:
            raise RuntimeError(
                f"expected {plan['unique_groups']} rows, found {kept}; rolling back"
            )

        # The de-duplication is proven complete by this succeeding.  If a
        # (decision_date, stock_code) pair survived twice, it fails here and
        # everything rolls back with no data lost.
        conn.execute(
            f"CREATE UNIQUE INDEX {UNIQUE_INDEX} "
            "ON decision_journal(decision_date, stock_code)"
        )
        indexed = int(
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
                (UNIQUE_INDEX,),
            ).fetchone()[0]
        )
        if not indexed:
            raise RuntimeError("unique index was not created; rolling back")

        result = {
            **plan,
            "journal_rows_after": kept,
            "dangling_after": dangling,
        }
        if confirm:
            conn.execute("COMMIT")
            result["committed"] = True
        else:
            conn.execute("ROLLBACK")
            result["committed"] = False
        return result
    except Exception:
        # Only roll back what is actually open; an error before BEGIN would
        # otherwise mask the original failure with "no transaction is active".
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="De-duplicate decision_journal.")
    parser.add_argument("--confirm", action="store_true", help="Actually commit.")
    parser.add_argument("--backup", action="store_true", help="Copy the DB first.")
    args = parser.parse_args()

    if not args.confirm:
        print("未加 --confirm：本次只做演练，结束时会回滚，不写入任何数据。")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        result = migrate(conn, confirm=args.confirm, backup=args.backup)
    except Exception as exc:
        print(f"迁移中止并已回滚: {type(exc).__name__}: {exc}")
        return 1
    finally:
        conn.close()

    print()
    print(f"  decision_journal  {result['journal_rows_before']} -> {result['journal_rows_after']}")
    print(f"  删除              {result['journal_rows_deleted']} 行")
    print(f"  outcome 前移      {result['outcomes_merged_forward']} 行")
    print(f"  strategy_decision 删 {result['strategy_rows_deleted']}, 重指 {result['strategy_rows_repointed']}")
    print(f"  观察重指          {result['observations_repointed_kept']}, 去重删 {result['observations_deleted']}")
    print(f"  成交重指          {result['trades_repointed']} 笔 {result['trades_repointed_ids']}")
    print(f"  残留悬空引用      {result['dangling_after']}")
    print()
    print(f"  UNIQUE 索引已建立，去重完备（这是验收证明）")
    print(f"  结果：{'已提交' if result['committed'] else '已回滚（演练）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
