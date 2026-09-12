"""每日增量数据同步脚本 — baostock 拉最近 N 日日线入库。

供 Windows 任务计划每日 16:00 调用(独立进程,不依赖 uvicorn 服务)。
与 app.py lifespan 的启动同步互补:那个只在服务启动时跑一次,
本脚本保证每个交易日收盘后都把最新日线入库,供 backfill 回填用。

用法(手动测试):
    <venv_python> scripts/daily_sync.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

# 确保能 import src.*(任务计划/命令行运行时 cwd 可能不在项目根)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_os.trading_calendar import get_trading_day_status
from src.infrastructure.market_data.current_metadata_sync import (
    sync_current_stock_metadata,
)
from src.infrastructure.market_data.tushare_provider import tushare_provider
from src.infrastructure.storage.market_database import SyncResult, market_db

DAYS_BACK = 3  # 每日增量:最近 3 个交易日(覆盖周末/节假日缺口)


def sync_latest_metadata_snapshot() -> dict:
    """Persist the latest local market date's point-in-time stock metadata."""
    market_date = market_db.get_latest_market_date_on_or_before(
        date.today().isoformat()
    )
    if not market_date:
        return {
            "status": "no_market_date",
            "as_of_date": "",
            "stock_count": 0,
            "stored_count": 0,
        }
    return market_db.sync_stock_metadata_snapshot(market_date)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync recent A-share daily bars into the local warehouse."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the trading calendar and show the planned sync without changing local data.",
    )
    return parser.parse_args()


async def sync_tushare_recent() -> dict:
    """Fetch recent complete snapshots through the configured Tushare tier."""
    dates = await tushare_provider.recent_trade_dates(DAYS_BACK)
    if len(dates) < DAYS_BACK:
        return {"status": "failed", "errors": ["tushare_trade_calendar_incomplete"]}
    results = []
    errors = []
    for target_date in dates:
        payload = await tushare_provider.fetch_daily_snapshot(target_date)
        complete = payload.coverage_ratio is not None and payload.coverage_ratio >= 0.80
        stored = market_db.upsert_tushare_daily_rows(
            payload.data,
            target_date,
            expected_count=(
                int(round(payload.row_count / payload.coverage_ratio))
                if payload.coverage_ratio else 0
            ),
            complete=complete,
        )
        results.append(stored)
        if stored.get("status") != "completed":
            errors.append(
                f"{target_date}: coverage={payload.coverage_ratio}"
            )
    return {
        "status": "completed" if not errors else "partial",
        "dates": dates,
        "stored_count": sum(int(item.get("stored_count", 0)) for item in results),
        "coverage": {
            date: item.get("coverage_ratio")
            for date, item in zip(dates, results, strict=False)
        },
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    calendar = asyncio.run(get_trading_day_status())
    if not calendar.is_trading_day:
        print(
            f"=== Daily sync skipped: non-trading day (calendar={calendar.source}) ===",
            flush=True,
        )
        return 0
    if args.dry_run:
        print(
            f"=== Daily sync ready: days_back={DAYS_BACK}, calendar={calendar.source} ===",
            flush=True,
        )
        return 0

    def progress(idx: int, total: int, code: str, status: str) -> None:
        if total and (idx % 500 == 0 or idx == total):
            print(f"  [{idx}/{total}] {code} {status}", flush=True)

    print(f"=== 每日增量同步 (days_back={DAYS_BACK}) 开始 ===", flush=True)
    try:
        tushare_result = asyncio.run(sync_tushare_recent())
    except Exception as exc:
        tushare_result = {
            "status": "failed",
            "stored_count": 0,
            "errors": [f"tushare:{type(exc).__name__}:{str(exc)[:160]}"],
        }
    print(
        f"=== Tushare 同步: {tushare_result.get('status')} | 新增/更新 "
        f"{tushare_result.get('stored_count', 0)} 条 | 错误 "
        f"{len(tushare_result.get('errors') or [])} ===",
        flush=True,
    )
    if tushare_result.get("status") == "completed":
        result = SyncResult(
            new_daily=int(tushare_result.get("stored_count", 0)),
            errors=tushare_result.get("errors") or [],
        )
    else:
        print("=== Tushare 快照不完整，切换 BaoStock 兜底 ===", flush=True)
        result = market_db.sync_daily_bars(
            codes=None, days_back=DAYS_BACK, progress_callback=progress
        )
    metadata = sync_latest_metadata_snapshot()
    print(
        f"=== 元数据快照: {metadata.get('status')} | 日期 {metadata.get('as_of_date', '')} | "
        f"读取 {metadata.get('stock_count', 0)} 只 | 保存 {metadata.get('stored_count', 0)} 条 ===",
        flush=True,
    )
    if metadata.get("errors"):
        print("元数据错误(最多3条):", metadata["errors"][-3:])
    quote_metadata = asyncio.run(
        sync_current_stock_metadata(as_of_date=str(metadata.get("as_of_date") or ""))
    )
    print(
        f"=== 实时元数据: {quote_metadata.get('status')} | 请求 "
        f"{quote_metadata.get('requested_count', 0)} 只 | 报价 "
        f"{quote_metadata.get('quote_count', 0)} 只 | 市值 "
        f"{quote_metadata.get('market_cap_count', 0)} 只 | "
        f"回放快照更新 {quote_metadata.get('history_count', 0)} 条 ===",
        flush=True,
    )
    if quote_metadata.get("errors"):
        print("实时元数据错误(最多3条):", quote_metadata["errors"][-3:])
    if result.errors:
        print("近期错误(最多3条):", result.errors[-3:])
    return 0 if quote_metadata.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
