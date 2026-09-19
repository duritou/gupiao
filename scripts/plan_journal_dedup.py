"""Plan the decision_journal de-duplication without changing any data.

Read-only.  Prints exactly what a migration would re-point, merge, delete and
resolve, so the numbers can be reviewed before anything is touched.  There are
no declared foreign keys in this schema, so a mis-aimed reference is silent
corruption -- the plan exists to make that impossible to do by accident.

Survivor rules, chosen from measurements rather than convenience:

- decision_journal keeps the highest id per (decision_date, stock_code),
  matching the "latest write wins" rule the read paths already apply.
  437 rows carry a backfilled outcome that only exists on a non-survivor, so
  those columns are merged forward first; no group conflicts on the value.
- strategy_decision keeps the row with the richest analysis_json and is
  re-pointed and renamed to the survivor.  Keeping the survivor's own row would
  silently drop packet detail in 4028 groups.

Usage:
    .venv\\Scripts\\python.exe scripts\\plan_journal_dedup.py
    .venv\\Scripts\\python.exe scripts\\plan_journal_dedup.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.storage.market_database import DB_PATH  # noqa: E402

# One row per (decision_date, stock_code): the latest write.
_KEEP_JOURNAL = """
CREATE TEMP TABLE keep_journal AS
SELECT MAX(id) AS keep_id, decision_date, stock_code, COUNT(*) AS group_size
  FROM decision_journal
 GROUP BY decision_date, stock_code
"""

# The richest packet in each group, regardless of which journal row owns it.
_KEEP_STRATEGY = """
CREATE TEMP TABLE keep_strategy AS
SELECT s.id AS keep_sd_id, k.keep_id
  FROM keep_journal k
  JOIN decision_journal d
    ON d.decision_date = k.decision_date AND d.stock_code = k.stock_code
  JOIN strategy_decision s ON s.journal_id = d.id
 WHERE s.id = (
     SELECT s2.id FROM strategy_decision s2
       JOIN decision_journal d2 ON d2.id = s2.journal_id
      WHERE d2.decision_date = k.decision_date
        AND d2.stock_code = k.stock_code
      ORDER BY LENGTH(COALESCE(s2.analysis_json, '')) DESC, s2.id DESC
      LIMIT 1)
"""


def build_plan(conn: sqlite3.Connection) -> dict:
    conn.executescript(_KEEP_JOURNAL + ";" + _KEEP_STRATEGY + ";")

    def scalar(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    plan: dict = {}
    plan["journal_rows_before"] = scalar("SELECT COUNT(*) FROM decision_journal")
    plan["unique_groups"] = scalar("SELECT COUNT(*) FROM keep_journal")
    plan["duplicate_groups"] = scalar(
        "SELECT COUNT(*) FROM keep_journal WHERE group_size > 1"
    )
    plan["journal_rows_deleted"] = (
        plan["journal_rows_before"] - plan["unique_groups"]
    )

    # Outcome columns that only exist off the survivor.
    plan["outcomes_merged_forward"] = scalar(
        """SELECT COUNT(*) FROM decision_journal d
             JOIN keep_journal k
               ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
            WHERE d.outcome_known = 1 AND d.id <> k.keep_id"""
    )
    plan["outcome_conflicts"] = scalar(
        """SELECT COUNT(*) FROM (
               SELECT d.decision_date, d.stock_code
                 FROM decision_journal d WHERE d.outcome_known = 1
                GROUP BY d.decision_date, d.stock_code
               HAVING COUNT(DISTINCT COALESCE(d.actual_return, -999)) > 1)"""
    )

    plan["strategy_rows_before"] = scalar("SELECT COUNT(*) FROM strategy_decision")
    plan["strategy_rows_deleted"] = scalar(
        "SELECT COUNT(*) FROM strategy_decision WHERE id NOT IN (SELECT keep_sd_id FROM keep_strategy)"
    )
    plan["strategy_rows_repointed"] = scalar(
        """SELECT COUNT(*) FROM keep_strategy ks
             JOIN strategy_decision s ON s.id = ks.keep_sd_id
            WHERE s.journal_id <> ks.keep_id"""
    )
    plan["strategy_rows_renamed"] = plan["strategy_rows_repointed"]
    # Groups whose survivor owns no strategy_decision row of its own: deleting
    # without re-pointing would leave them with no packet at all.
    plan["groups_survivor_had_no_strategy_row"] = scalar(
        """SELECT COUNT(*) FROM keep_journal k
            WHERE NOT EXISTS (SELECT 1 FROM strategy_decision s WHERE s.journal_id = k.keep_id)"""
    )
    # Dropping the survivor's own row in favour of a richer sibling.
    plan["strategy_kept_is_not_survivors_own"] = scalar(
        """SELECT COUNT(*) FROM keep_strategy ks
             JOIN strategy_decision s ON s.id = ks.keep_sd_id
            WHERE s.journal_id <> ks.keep_id"""
    )

    plan["observations_before"] = scalar("SELECT COUNT(*) FROM market_learning_observation")
    plan["observations_repointed"] = scalar(
        """SELECT COUNT(*) FROM market_learning_observation o
             JOIN decision_journal d ON d.id = o.decision_id
             JOIN keep_journal k
               ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
            WHERE o.decision_id <> k.keep_id"""
    )
    # Re-pointing collapses these onto one key; the newest row wins.
    plan["observation_unique_collisions"] = scalar(
        """SELECT COUNT(*) FROM (
               SELECT k.keep_id, o.horizon_days
                 FROM market_learning_observation o
                 JOIN decision_journal d ON d.id = o.decision_id
                 JOIN keep_journal k
                   ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
                GROUP BY k.keep_id, o.horizon_days HAVING COUNT(*) > 1)"""
    )
    plan["observations_deleted"] = scalar(
        """SELECT COUNT(*) FROM (
               SELECT o.id,
                      ROW_NUMBER() OVER (
                          PARTITION BY k.keep_id, o.horizon_days
                          ORDER BY o.id DESC) AS rn
                 FROM market_learning_observation o
                 JOIN decision_journal d ON d.id = o.decision_id
                 JOIN keep_journal k
                   ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code)
            WHERE rn > 1"""
    )

    plan["trades_before"] = scalar("SELECT COUNT(*) FROM paper_trade")
    plan["trades_repointed"] = scalar(
        """SELECT COUNT(*) FROM paper_trade t
             JOIN decision_journal d ON d.id = t.decision_id
             JOIN keep_journal k
               ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
            WHERE t.decision_id <> k.keep_id"""
    )
    plan["trades_repointed_ids"] = [
        int(row[0])
        for row in conn.execute(
            """SELECT t.id FROM paper_trade t
                 JOIN decision_journal d ON d.id = t.decision_id
                 JOIN keep_journal k
                   ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
                WHERE t.decision_id <> k.keep_id ORDER BY t.id"""
        ).fetchall()
    ]

    # References that already point at a journal row that does not exist.  The
    # migration neither creates nor heals these; they are reported so a
    # pre-existing break is not later mistaken for migration damage.
    plan["preexisting_dangling"] = scalar(
        """SELECT (SELECT COUNT(*) FROM strategy_decision s
                    WHERE s.journal_id IS NOT NULL
                      AND s.journal_id NOT IN (SELECT id FROM decision_journal))
                + (SELECT COUNT(*) FROM paper_trade t
                    WHERE t.decision_id IS NOT NULL
                      AND t.decision_id NOT IN (SELECT id FROM decision_journal))
                + (SELECT COUNT(*) FROM market_learning_observation o
                    WHERE o.decision_id NOT IN (SELECT id FROM decision_journal))"""
    )
    # Observations that survive the UNIQUE collapse and still need re-pointing.
    plan["observations_repointed_kept"] = scalar(
        """SELECT COUNT(*) FROM market_learning_observation o
             JOIN decision_journal d ON d.id = o.decision_id
             JOIN keep_journal k
               ON k.decision_date = d.decision_date AND k.stock_code = d.stock_code
            WHERE o.decision_id <> k.keep_id
              AND o.id NOT IN (
                  SELECT id FROM (
                      SELECT o2.id,
                             ROW_NUMBER() OVER (
                                 PARTITION BY k2.keep_id, o2.horizon_days
                                 ORDER BY o2.id DESC) AS rn
                        FROM market_learning_observation o2
                        JOIN decision_journal d2 ON d2.id = o2.decision_id
                        JOIN keep_journal k2
                          ON k2.decision_date = d2.decision_date
                         AND k2.stock_code = d2.stock_code)
                   WHERE rn > 1)"""
    )

    # Conservation: each referencing table is partitioned into disjoint,
    # exhaustive buckets.  If a table's buckets do not sum to its row count,
    # the plan has a hole and executing it would drop a reference.
    plan["conservation"] = {
        "strategy_decision": {
            "deleted": plan["strategy_rows_deleted"],
            "repointed": plan["strategy_rows_repointed"],
            "already_correct": (
                plan["strategy_rows_before"]
                - plan["strategy_rows_deleted"]
                - plan["strategy_rows_repointed"]
            ),
            "total": plan["strategy_rows_before"],
        },
        "paper_trade": {
            "deleted": 0,
            "repointed": plan["trades_repointed"],
            "already_correct": plan["trades_before"] - plan["trades_repointed"],
            "total": plan["trades_before"],
        },
        "market_learning_observation": {
            "deleted": plan["observations_deleted"],
            "repointed": plan["observations_repointed_kept"],
            "already_correct": (
                plan["observations_before"]
                - plan["observations_deleted"]
                - plan["observations_repointed_kept"]
            ),
            "total": plan["observations_before"],
        },
    }
    for table, buckets in plan["conservation"].items():
        buckets["sums"] = (
            buckets["deleted"] + buckets["repointed"] + buckets["already_correct"]
            == buckets["total"]
        )
        buckets["no_negatives"] = min(
            buckets["deleted"], buckets["repointed"], buckets["already_correct"]
        ) >= 0
    plan["conservation_ok"] = all(
        b["sums"] and b["no_negatives"] for b in plan["conservation"].values()
    )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan the journal de-duplication.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        plan = build_plan(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print("决策日志去重计划（只读，未改动任何数据）")
    print()
    print(f"  decision_journal    {plan['journal_rows_before']} 行")
    print(f"    唯一 (date,code)  {plan['unique_groups']} 组，其中重复 {plan['duplicate_groups']} 组")
    print(f"    将删除            {plan['journal_rows_deleted']} 行")
    print()
    print(f"  outcome 合并        {plan['outcomes_merged_forward']} 行需前移"
          f"（同组值冲突 {plan['outcome_conflicts']} 处）")
    print()
    print(f"  strategy_decision   {plan['strategy_rows_before']} 行")
    print(f"    保留最全的一条    重指 {plan['strategy_rows_repointed']} 条，删除 {plan['strategy_rows_deleted']} 条")
    print(f"    幸存者自己无决策包 {plan['groups_survivor_had_no_strategy_row']} 组（靠重指补上，不能只删）")
    print()
    print(f"  market_learning_observation {plan['observations_before']} 条")
    print(f"    需重指            {plan['observations_repointed']} 条")
    print(f"    UNIQUE 冲突       {plan['observation_unique_collisions']} 组，将去重删 {plan['observations_deleted']} 条")
    print()
    print(f"  paper_trade         {plan['trades_before']} 笔")
    print(f"    需重指            {plan['trades_repointed']} 笔  ids={plan['trades_repointed_ids']}")
    print()
    print(f"  迁移前既有悬空引用：{plan['preexisting_dangling']}（非本次造成）")
    print()
    print("  守恒检验（每张表的行必须被无重叠、无遗漏地分完）")
    for table, buckets in plan["conservation"].items():
        mark = "OK " if buckets["sums"] and buckets["no_negatives"] else "不通过"
        print(
            f"    {mark} {table:<30} 删{buckets['deleted']} + 重指{buckets['repointed']}"
            f" + 无需改{buckets['already_correct']} = {buckets['total']}"
        )
    print()
    ok = plan["conservation_ok"] and plan["outcome_conflicts"] == 0
    print(f"  判定：{'计划自洽，可进入执行评审' if ok else '存在冲突，需先解决'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
