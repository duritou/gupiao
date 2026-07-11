"""Baostock session coordination.

baostock 的 login/logout 是进程级全局单例状态,被三处共享:
  - ``market_database.sync_daily_bars``(后台全量同步,长 session)
  - ``source_manager._try_baostock_quote`` / ``_try_baostock_kline``(API fallback)
  - ``real_data_provider._get_universe_from_api``(股票池拉取)

并发调用会互相 logout 导致 session 失效。由于后台全量同步(全 A 股)会长时间
占用 baostock,本模块用一个"同步进行中"标志:同步期间,API 侧的 baostock
fallback 主动跳过(改走 mootdx/akshare 等其他源),避免与同步长 session 互踢;
同步结束后 API 恢复 baostock 访问。

相比"全局锁序列化每处 login",标志位不会让 API 在同步期间长时间阻塞等锁。
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_sync_in_progress = False


def mark_sync_start() -> None:
    """标记一次全量同步开始 —— API 侧 baostock 访问将跳过。"""
    global _sync_in_progress
    with _lock:
        _sync_in_progress = True


def mark_sync_end() -> None:
    """标记同步结束,恢复 API 侧 baostock 访问。"""
    global _sync_in_progress
    with _lock:
        _sync_in_progress = False


def is_sync_in_progress() -> bool:
    """API 侧 baostock 访问前调用:True 表示应跳过 baostock,走其他数据源。"""
    with _lock:
        return _sync_in_progress
