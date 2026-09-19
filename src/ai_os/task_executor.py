"""AI OS Task Executor — 自动化任务执行引擎。

负责：
1. 按调度器定义的时间自动执行任务
2. 追踪任务执行历史（状态、运行时间、次数）
3. 提供任务监控 API 供插件展示

使用：
    executor = TaskExecutor()
    await executor.start()  # 启动后台任务执行器
    status = executor.get_status()  # 获取任务状态
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from .scheduler import ScheduledTask
from .trading_calendar import (
    CompletedTradingDayStatus,
    get_latest_completed_trading_day,
    get_trading_day_status,
)
from src.ai_os.strategy_version import ALGORITHM_VERSION

_TRADING_PHASES = {
    "pre_market",
    "market_open",
    "midday",
    "afternoon",
    "late_afternoon",
    "market_close",
    "evening",
}
_TASK_TIMEOUT_SECONDS = {
    "refresh_market_news": 180,
    "sync_market_data": 1800,
    "run_scanner": 900,
    # This task consumes the overnight plan and only requests fresh quotes;
    # it must never rerun the full-market scanner at the open.
    "execute_open_strategy": 180,
    "afternoon_scan": 900,
    "update_outcomes": 600,
}
_RETRYABLE_TASKS = {
    "check_alerts",
    "market_open_check",
    "midday_review",
    "generate_morning_brief",
    "update_trust_metrics",
}
_RECOVERY_FAILURE_COOLDOWN_SECONDS = {
    # Full-market scans are expensive. A deterministic code/configuration
    # failure must not trigger another 5k-stock scan every watchdog tick.
    "run_scanner": 900,
    "afternoon_scan": 900,
    "execute_open_strategy": 300,
}
_FAILURE_CIRCUIT_THRESHOLD = 3
_CIRCUIT_PROBE_COOLDOWN_SECONDS = 900
_CIRCUIT_PROBE_MAX_COOLDOWN_SECONDS = 3600


def _failure_fingerprint(task_name: str, error: BaseException) -> str:
    """Create a stable fingerprint without timestamps, paths, or UUIDs."""
    message = re.sub(r"[0-9a-f]{8,}", "<id>", str(error).lower())
    message = re.sub(r"[A-Za-z]:\\[^ ]+|/[^ ]+", "<path>", message)
    payload = f"{task_name}|{type(error).__module__}.{type(error).__name__}|{message[:240]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _is_import_error(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ImportError):
            return True
        current = current.__cause__ or current.__context__
    return False


def market_data_covers_latest_completed_day(
    latest_data_date: str,
    completed_day: CompletedTradingDayStatus,
) -> bool:
    """Judge freshness by trading sessions, not raw calendar-day distance."""
    if not latest_data_date or completed_day.day is None:
        return False
    try:
        latest = date.fromisoformat(latest_data_date)
    except ValueError:
        return False
    return latest >= completed_day.day


def market_checkpoint_freshness(
    data_date: str,
    is_live: bool,
    *,
    today: date | None = None,
) -> str:
    """Classify whether a checkpoint can represent the current session."""
    normalized = str(data_date or "").strip()[:10]
    if not normalized:
        return "unavailable"
    try:
        snapshot_day = date.fromisoformat(normalized)
    except ValueError:
        return "invalid"
    current_day = today or datetime.now().date()
    if snapshot_day > current_day:
        return "invalid"
    if snapshot_day == current_day:
        return "today_live" if is_live else "dated_snapshot_only"
    return "previous_close_only"


def local_market_cache_can_run_scanner(stats: dict, latest_data_date: str) -> bool:
    """Return whether an existing warehouse is usable when sync is blocked.

    A failed BaoStock login should not deadlock the entire daily workflow when
    the local warehouse already contains a broad, analyzable history.  The
    scanner still records the older ``technical_data_through`` date, while
    paper fills independently require a fresh post-signal quote.
    """
    if not latest_data_date:
        return False
    try:
        stocks = int(stats.get("stocks") or 0)
        daily_bars = int(stats.get("daily_bars") or 0)
    except (TypeError, ValueError):
        return False
    return stocks >= 1000 and daily_bars >= stocks * 20


class TaskStatus(str, Enum):
    """任务执行状态。"""
    PENDING = "pending"      # 待执行
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功
    FAILED = "failed"        # 失败
    SKIPPED = "skipped"      # 跳过（依赖未满足）


@dataclass
class TaskExecution:
    """单次任务执行记录。"""
    task_name: str
    phase: str
    status: TaskStatus
    trigger_source: str = "internal"
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    error: str = ""
    output: dict = field(default_factory=dict)
    is_critical: bool = False
    failure_fingerprint: str = ""
    consecutive_failures: int = 0
    circuit_state: str = "healthy"
    incident_key: str = ""

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "phase": self.phase,
            "status": self.status,
            "trigger_source": self.trigger_source,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
            "output": self.output,
            "is_critical": self.is_critical,
            "failure_fingerprint": self.failure_fingerprint,
            "consecutive_failures": self.consecutive_failures,
            "circuit_state": self.circuit_state,
            "incident_key": self.incident_key,
        }


@dataclass
class TaskStats:
    """任务统计信息。"""
    task_name: str
    total_runs: int = 0
    success_count: int = 0
    failed_count: int = 0
    last_run_at: str = ""
    last_status: TaskStatus = TaskStatus.PENDING
    avg_duration_seconds: float = 0.0
    next_scheduled_at: str = ""  # 下次预定执行时间

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "success_rate": (
                round(self.success_count / self.total_runs * 100, 1)
                if self.total_runs > 0 else 0
            ),
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "avg_duration_seconds": round(self.avg_duration_seconds, 2),
            "next_scheduled_at": self.next_scheduled_at,
        }


class TaskExecutor:
    """自动化任务执行引擎。

    启动后在后台按调度器定义的时间自动执行任务。
    """

    def __init__(self, persist: bool = False):
        self._execution_history: list[TaskExecution] = []  # 执行历史（最多保留100条）
        self._task_stats: dict[str, TaskStats] = {}  # 任务统计
        self._running_tasks: dict[str, asyncio.Task] = {}  # 正在运行的任务
        self._is_running = False
        self._executor_task: asyncio.Task | None = None
        self._persist = persist
        self._manual_rerun_lock = asyncio.Lock()
        self._failure_incidents: dict[str, dict] = {}
        if self._persist:
            self._restore_history()
            self._restore_failure_incidents()

    def start(self) -> None:
        """启动任务执行器（非阻塞）。"""
        if self._is_running:
            return
        self._is_running = True
        # 注意：这里只是设置标志，实际的后台循环需要在 app lifespan 中启动
        print("[TaskExecutor] 任务执行器已启动")

    def stop(self) -> None:
        """停止任务执行器。"""
        self._is_running = False
        for task in self._running_tasks.values():
            task.cancel()
        self._running_tasks.clear()
        print("[TaskExecutor] 任务执行器已停止")

    async def rerun_open_strategy(self, task: ScheduledTask, request_id: str) -> TaskExecution:
        """Explicit operator rerun; preserve original history and all execution gates."""
        if task.name != "execute_open_strategy" or not request_id:
            raise ValueError("only an identified open-strategy rerun is supported")
        async with self._manual_rerun_lock:
            key = f"{datetime.now().date().isoformat()}:{task.name}:{ALGORITHM_VERSION}:rerun:{request_id}"
            if self._persist:
                from src.infrastructure.storage.market_database import market_db

                history = await asyncio.to_thread(market_db.get_task_executions, 500)
            else:
                history = [item.to_dict() for item in self._execution_history]
            for item in history:
                if item.get("output", {}).get("execution_key") == key:
                    execution = self._skipped_execution(task, "重跑请求已记录", "manual_rerun")
                    execution.output = {"execution_key": key, "skip_reason": "rerun_already_recorded"}
                    return execution
            return await self.execute_task(task, trigger_source="manual_rerun", rerun_id=request_id)

    async def execute_task(
        self, task: ScheduledTask, trigger_source: str = "internal", *, rerun_id: str = ""
    ) -> TaskExecution:
        """执行单个任务。

        Args:
            task: 要执行的任务定义

        Returns:
            TaskExecution: 执行记录
        """
        execution_key = (
            f"{datetime.now().date().isoformat()}:{task.name}:{ALGORITHM_VERSION}"
        )
        if rerun_id:
            if task.name != "execute_open_strategy" or trigger_source != "manual_rerun":
                raise ValueError("rerun is restricted to explicit open-strategy requests")
            execution_key += f":rerun:{rerun_id}"
        incident = self._failure_incidents.get(task.name)
        if incident and incident.get("state") == "circuit_open" \
                and not self._circuit_probe_due(incident):
            execution = self._skipped_execution(
                task, "任务熔断中，等待恢复探针", trigger_source
            )
            execution.output = {
                "execution_key": execution_key,
                "strategy_version": ALGORITHM_VERSION,
                "stage_status": TaskStatus.SKIPPED.value,
                "skip_reason": "circuit_open",
                "failure_fingerprint": incident.get("fingerprint", ""),
                "circuit_state": "circuit_open",
            }
            await self._add_execution_async(execution)
            return execution
        if task.name in self._running_tasks:
            execution = self._skipped_execution(
                task, "同名任务正在执行，已阻止重复运行", trigger_source
            )
            execution.output = {
                "execution_key": execution_key,
                "strategy_version": ALGORITHM_VERSION,
                "stage_status": TaskStatus.SKIPPED.value,
                "skip_reason": "already_running",
            }
            await self._add_execution_async(execution)
            return execution

        if not rerun_id and self._succeeded_today(task.name):
            execution = self._skipped_execution(
                task, "今日同一策略版本已成功，已阻止重复执行", trigger_source
            )
            execution.output = {
                "execution_key": execution_key,
                "strategy_version": ALGORITHM_VERSION,
                "stage_status": TaskStatus.SKIPPED.value,
                "skip_reason": "idempotent_success",
            }
            await self._add_execution_async(execution)
            return execution

        phase_value = task.phase.value if hasattr(task.phase, "value") else str(task.phase)
        calendar_status = None
        if phase_value in _TRADING_PHASES:
            calendar_status = await get_trading_day_status()
            if not calendar_status.is_trading_day:
                execution = self._skipped_execution(
                    task,
                    f"非交易日（判断来源: {calendar_status.source}）",
                    trigger_source,
                )
                execution.output = {
                    "calendar_source": calendar_status.source,
                    "calendar_degraded": calendar_status.degraded,
                    "execution_key": execution_key,
                    "strategy_version": ALGORITHM_VERSION,
                    "stage_status": TaskStatus.SKIPPED.value,
                    "skip_reason": "non_trading_day",
                }
                await self._add_execution_async(execution)
                return execution

        missing_dependencies = [
            dependency
            for dependency in task.depends_on
            if not self._succeeded_today(dependency)
        ]
        if missing_dependencies:
            execution = self._skipped_execution(
                task,
                f"依赖未完成: {', '.join(missing_dependencies)}",
                trigger_source,
            )
            execution.output = {
                "execution_key": execution_key,
                "strategy_version": ALGORITHM_VERSION,
                "stage_status": TaskStatus.SKIPPED.value,
                "skip_reason": "missing_dependencies",
                "missing_dependencies": missing_dependencies,
            }
            await self._add_execution_async(execution)
            return execution

        execution = TaskExecution(
            task_name=task.name,
            phase=task.phase,
            status=TaskStatus.RUNNING,
            trigger_source=trigger_source,
            started_at=datetime.now().isoformat(),
            is_critical=task.is_critical,
        )
        current_task = asyncio.current_task()
        if current_task is not None:
            self._running_tasks[task.name] = current_task

        attempts = 2 if task.name in _RETRYABLE_TASKS else 1
        timeout = _TASK_TIMEOUT_SECONDS.get(task.name, 120)
        attempts_used = 0
        failure_error: BaseException | None = None
        failure_incident: dict | None = None
        alert_state = ""
        try:
            last_error: Exception | None = None
            result = None
            succeeded = False
            for attempt in range(1, attempts + 1):
                attempts_used = attempt
                try:
                    result = await asyncio.wait_for(self._route_task(task), timeout=timeout)
                    succeeded = True
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts:
                        await asyncio.sleep(1)
            if not succeeded:
                raise last_error or RuntimeError("任务执行失败")
            execution.status = TaskStatus.SUCCESS
            execution.output = dict(result or {})
            execution.output["attempts"] = attempts_used
            execution.output["timeout_seconds"] = timeout
            execution.output["execution_key"] = execution_key
            execution.output["strategy_version"] = ALGORITHM_VERSION
            execution.output["stage_status"] = TaskStatus.SUCCESS.value
            execution.output["is_critical"] = task.is_critical
            if calendar_status is not None:
                execution.output["calendar_source"] = calendar_status.source
                execution.output["calendar_degraded"] = calendar_status.degraded
        except Exception as e:
            failure_error = e
            execution.status = TaskStatus.FAILED
            execution.error = f"{type(e).__name__}: {str(e)}"[:200]
            failure_incident, alert_state = self._record_failure(task, e)
            execution.failure_fingerprint = failure_incident["fingerprint"]
            execution.consecutive_failures = failure_incident["consecutive_failures"]
            execution.circuit_state = failure_incident["state"]
            execution.incident_key = failure_incident["incident_key"]
            execution.output = {
                "attempts": attempts_used,
                "timeout_seconds": timeout,
                "execution_key": execution_key,
                "strategy_version": ALGORITHM_VERSION,
                "stage_status": TaskStatus.FAILED.value,
                "is_critical": task.is_critical,
                "failure_fingerprint": execution.failure_fingerprint,
                "consecutive_failures": execution.consecutive_failures,
                "circuit_state": execution.circuit_state,
                "incident_key": execution.incident_key,
            }
        finally:
            execution.completed_at = datetime.now().isoformat()
            execution.duration_seconds = (
                datetime.fromisoformat(execution.completed_at) -
                datetime.fromisoformat(execution.started_at)
            ).total_seconds()
            self._running_tasks.pop(task.name, None)

        # 更新历史和统计
        await self._add_execution_async(execution)
        if failure_incident is not None:
            await self._persist_failure_incident(failure_incident)
        if execution.status == TaskStatus.SUCCESS:
            recovered = self._record_success(task)
            if recovered is not None:
                await self._persist_failure_incident(recovered)
                await self._notify_recovery_once(task, recovered)
        elif execution.is_critical or (
            failure_error is not None and _is_import_error(failure_error)
        ):
            await self._notify_failure_once(task, execution, alert_state)
        return execution

    @staticmethod
    def _skipped_execution(
        task: ScheduledTask, reason: str, trigger_source: str = "internal"
    ) -> TaskExecution:
        now = datetime.now().isoformat()
        return TaskExecution(
            task_name=task.name,
            phase=task.phase,
            status=TaskStatus.SKIPPED,
            trigger_source=trigger_source,
            started_at=now,
            completed_at=now,
            error=reason,
            is_critical=task.is_critical,
        )

    def _succeeded_today(self, task_name: str) -> bool:
        today = datetime.now().date()
        return any(
            execution.task_name == task_name
            and execution.status == TaskStatus.SUCCESS
            and bool(execution.completed_at)
            and datetime.fromisoformat(execution.completed_at).date() == today
            for execution in self._execution_history
        )

    def has_succeeded_today(self, task_name: str) -> bool:
        """Return whether a task already completed successfully today.

        Scheduler recovery uses this public read-only check to make retries
        idempotent across a normal cron run, a process restart, and the
        periodic missed-phase watchdog.
        """
        return self._succeeded_today(task_name)

    def is_in_failure_cooldown(self, task_name: str) -> bool:
        """Prevent the recovery watchdog from retrying a recent failure storm."""
        cooldown = _RECOVERY_FAILURE_COOLDOWN_SECONDS.get(task_name, 300)
        now = datetime.now()
        for execution in reversed(self._execution_history):
            if execution.task_name != task_name or not execution.completed_at:
                continue
            try:
                completed = datetime.fromisoformat(execution.completed_at)
            except ValueError:
                return False
            if completed.date() != now.date() or execution.status != TaskStatus.FAILED:
                return False
            return (now - completed).total_seconds() < cooldown
        return False

    def is_circuit_open(self, task_name: str) -> bool:
        """Return whether a task is currently blocked by its failure circuit."""
        incident = self._failure_incidents.get(task_name)
        return bool(incident and incident.get("state") == "circuit_open")

    def is_recovery_blocked(self, task_name: str) -> bool:
        """Return whether recovery should wait instead of recording another skip."""
        incident = self._failure_incidents.get(task_name)
        return bool(
            incident
            and incident.get("state") == "circuit_open"
            and not self._circuit_probe_due(incident)
        )

    @staticmethod
    def _circuit_probe_due(incident: dict) -> bool:
        raw = str(incident.get("next_probe_at") or "")
        if not raw:
            return True
        try:
            return datetime.now() >= datetime.fromisoformat(raw)
        except ValueError:
            return True

    def _record_failure(
        self, task: ScheduledTask, error: BaseException
    ) -> tuple[dict, str]:
        now = datetime.now()
        now_iso = now.isoformat()
        fingerprint = _failure_fingerprint(task.name, error)
        previous = self._failure_incidents.get(task.name)
        same_incident = previous and previous.get("fingerprint") == fingerprint
        count = int(previous.get("consecutive_failures", 0) or 0) + 1 if same_incident else 1
        previous_state = str(previous.get("state") or "healthy") if previous else "healthy"
        state = (
            "circuit_open"
            if previous_state == "circuit_open" or count >= _FAILURE_CIRCUIT_THRESHOLD
            else "failed"
        )
        probe_seconds = min(
            _CIRCUIT_PROBE_MAX_COOLDOWN_SECONDS,
            _CIRCUIT_PROBE_COOLDOWN_SECONDS * max(1, count - _FAILURE_CIRCUIT_THRESHOLD + 1),
        )
        incident_key = (
            str(previous.get("incident_key"))
            if same_incident and previous else
            f"{now.date().isoformat()}:{task.name}:{fingerprint}"
        )
        incident = {
            "incident_key": incident_key,
            "task_name": task.name,
            "phase": str(task.phase.value if hasattr(task.phase, "value") else task.phase),
            "fingerprint": fingerprint,
            "severity": "P0" if task.is_critical or _is_import_error(error) else "P1",
            "state": state,
            "consecutive_failures": count,
            "first_failed_at": (
                str(previous.get("first_failed_at"))
                if same_incident and previous else now_iso
            ),
            "last_failed_at": now_iso,
            "last_alert_state": str(previous.get("last_alert_state") or "")
            if same_incident and previous else "",
            "next_probe_at": (
                (now + timedelta(seconds=probe_seconds)).isoformat()
                if state == "circuit_open" else ""
            ),
            "recovered_at": "",
            "updated_at": now_iso,
        }
        self._failure_incidents[task.name] = incident
        alert_state = ""
        if incident["last_alert_state"] != "failed" and count == 1:
            alert_state = "failed"
        elif state == "circuit_open" and incident["last_alert_state"] != "circuit_open":
            alert_state = "circuit_open"
        return incident, alert_state

    def _record_success(self, task: ScheduledTask) -> dict | None:
        incident = self._failure_incidents.get(task.name)
        if not incident or incident.get("state") == "healthy":
            return None
        recovered = dict(incident)
        recovered.update({
            "state": "healthy",
            "consecutive_failures": 0,
            "last_alert_state": "recovered",
            "recovered_at": datetime.now().isoformat(),
            "next_probe_at": "",
            "updated_at": datetime.now().isoformat(),
        })
        self._failure_incidents[task.name] = recovered
        return recovered

    async def _persist_failure_incident(self, incident: dict) -> None:
        if not self._persist:
            return
        try:
            from src.infrastructure.storage.market_database import market_db

            await asyncio.to_thread(market_db.save_task_failure_incident, incident)
        except Exception:
            # Monitoring persistence must never change the task result.
            pass

    async def _notify_failure_once(
        self, task: ScheduledTask, execution: TaskExecution, alert_state: str
    ) -> None:
        if not alert_state:
            return
        content = (
            f"任务: {task.name}\n阶段: {execution.phase}\n状态: {alert_state}\n"
            f"连续失败: {execution.consecutive_failures}\n"
            f"错误指纹: {execution.failure_fingerprint}\n错误: {execution.error}\n"
            f"熔断状态: {execution.circuit_state}"
        )
        try:
            await self._notify_wechat(
                f"[{('P0' if task.is_critical else 'P1')}] AI任务失败",
                content,
            )
        except Exception:
            # Notification failure must not turn an auditable task failure
            # into an unhandled executor error.
            return
        incident = self._failure_incidents.get(task.name)
        if incident:
            incident["last_alert_state"] = alert_state
            incident["updated_at"] = datetime.now().isoformat()
            await self._persist_failure_incident(incident)

    async def _notify_recovery_once(self, task: ScheduledTask, incident: dict) -> None:
        if not incident.get("last_alert_state"):
            return
        try:
            await self._notify_wechat(
                f"[{incident.get('severity', 'P1')}] AI任务恢复: {task.name}",
                f"任务已通过恢复探针。错误指纹: {incident.get('fingerprint', '')}",
            )
        except Exception:
            pass

    def _restore_failure_incidents(self) -> None:
        try:
            from src.infrastructure.storage.market_database import market_db

            rows = market_db.get_task_failure_incidents()
        except Exception:
            return
        for row in rows:
            task_name = str(row.get("task_name") or "")
            if task_name:
                self._failure_incidents[task_name] = row

    async def _route_task(self, task: ScheduledTask) -> dict:
        """路由任务到具体的执行函数。"""
        # 这里根据任务名称调用相应的实现
        # 先返回模拟结果，后续补充实际实现
        task_handlers = {
            "refresh_market_news": self._refresh_market_news,
            "sync_market_data": self._sync_market_data,
            "update_portfolio": self._update_portfolio,
            "run_scanner": self._run_scanner,
            "generate_morning_brief": self._generate_morning_brief,
            "check_alerts": self._check_alerts,
            "market_open_check": self._market_checkpoint,
            "execute_open_strategy": self._execute_open_strategy,
            "midday_review": self._market_checkpoint,
            "afternoon_scan": self._run_scanner,
            "late_afternoon_review": self._market_checkpoint,
            "close_positions_check": self._update_portfolio,
            "update_outcomes": self._update_outcomes,
            "update_trust_metrics": self._update_trust_metrics,
            "generate_daily_journal": self._generate_daily_journal,
            "ai_reflection": self._ai_reflection,
            "weekly_review": self._periodic_review,
            "weekly_user_insights": self._weekly_user_insights,
            "weekly_learning_log": self._weekly_learning_log,
            "monthly_review": self._periodic_review,
            "model_evolution_check": self._model_evolution_check,
            "update_user_model": self._update_user_model,
        }

        handler = task_handlers.get(task.name, self._default_handler)
        return await handler(task)

    async def _refresh_market_news(self, task: ScheduledTask) -> dict:
        """Refresh internal market-news evidence and persist its availability."""
        from src.infrastructure.market_data.news_freshness import apply_news_freshness
        from src.infrastructure.market_data.eastmoney_news import fetch_eastmoney_global_news
        from src.infrastructure.market_data.vibe_provider import get_vibe_provider
        from src.infrastructure.storage.market_database import market_db

        data = apply_news_freshness(await fetch_eastmoney_global_news())
        if not (data.get("_meta") or {}).get("available"):
            data = apply_news_freshness(await get_vibe_provider().refresh_news_radar())
        metadata = dict(data.get("_meta") or {})
        count = len(data.get("news") or [])
        available = bool(metadata.get("available")) and count > 0
        lesson = (
            f"资讯雷达刷新成功，共 {count} 条，更新时间 {data.get('updated_at', '')}。"
            if available else
            f"资讯雷达刷新后仍不可用：{metadata.get('error') or '没有有效资讯'}。"
        )
        await asyncio.to_thread(
            market_db.upsert_daily_learning,
            datetime.now().date().isoformat(),
            "market_news_status",
            lesson,
            {
                "available": available,
                "count": count,
                "updated_at": data.get("updated_at", ""),
                "metadata": metadata,
            },
        )
        return {
            "status": "refreshed" if available else "refreshed_degraded",
            "available": available,
            "news_count": count,
            "updated_at": data.get("updated_at", ""),
            "metadata": metadata,
        }

    async def _sync_market_data(self, task: ScheduledTask) -> dict:
        """同步市场数据。"""
        from src.infrastructure.storage.market_database import market_db

        # Reference indices are independent of the stock-bar freshness check
        # below, which returns early on an already-fresh day.  A failure here
        # must not fail the market sync -- the learning label reads none of it.
        index_sync: dict = {}
        try:
            from src.infrastructure.market_data.index_sync import sync_reference_indices

            index_sync = await sync_reference_indices()
        except Exception as exc:
            index_sync = {"errors": [f"{type(exc).__name__}: {exc}"]}

        stats = await asyncio.to_thread(market_db.get_stats)
        latest = str(stats.get("latest_data_date") or "")
        completed_day = await get_latest_completed_trading_day(date.today())
        expected = completed_day.day.isoformat() if completed_day.day else ""
        if market_data_covers_latest_completed_day(latest, completed_day):
            metadata_sync = await self._sync_current_metadata(expected or latest)
            return {
                "status": "already_fresh",
                "latest_data_date": latest,
                "expected_completed_trading_day": expected,
                "stocks": stats.get("stocks", 0),
                "daily_bars": stats.get("daily_bars", 0),
                "calendar_source": completed_day.source,
                "metadata_sync": metadata_sync,
                "index_sync": index_sync,
            }

        missing_days = (
            (date.today() - date.fromisoformat(latest)).days
            if latest else 3
        )
        try:
            result = await asyncio.to_thread(
                market_db.sync_daily_bars,
                codes=None,
                days_back=max(3, min(missing_days + 2, 14)),
                target_date=expected,
            )
        except Exception as exc:
            result = None
            sync_errors = [f"sync exception: {type(exc).__name__}: {exc}"]
        else:
            sync_errors = list(result.errors or [])
        if result is None or (sync_errors and result.stocks_updated == 0):
            if local_market_cache_can_run_scanner(stats, latest):
                metadata_sync = await self._sync_current_metadata(expected or latest)
                return {
                    "status": "cache_fallback",
                    "degraded": True,
                    "usable_for_scanner": True,
                    "latest_data_date": latest,
                    "expected_completed_trading_day": expected,
                    "stocks": stats.get("stocks", 0),
                    "daily_bars": stats.get("daily_bars", 0),
                    "calendar_source": completed_day.source,
                    "sync_errors": sync_errors[:3],
                    "metadata_sync": metadata_sync,
                    "index_sync": index_sync,
                    "note": (
                        "BaoStock 同步不可用，继续使用本地历史行情扫描；"
                        "模拟成交仍必须通过信号后的新鲜行情校验。"
                    ),
                }
            raise RuntimeError(sync_errors[0] if sync_errors else "市场数据同步失败")
        metadata_sync = await self._sync_current_metadata(expected or latest)
        return {
            "status": "synced",
            "new_daily": result.new_daily,
            "stocks_updated": result.stocks_updated,
            "errors": len(sync_errors),
            "previous_latest_data_date": latest,
            "expected_completed_trading_day": expected,
            "calendar_source": completed_day.source,
            "calendar_degraded": completed_day.degraded,
            "metadata_sync": metadata_sync,
            "index_sync": index_sync,
        }

    async def _sync_current_metadata(self, as_of_date: str) -> dict:
        """Refresh quote-derived metadata without weakening scanner gates."""
        from src.infrastructure.market_data.current_metadata_sync import (
            sync_current_stock_metadata,
        )

        try:
            return await sync_current_stock_metadata(as_of_date=as_of_date)
        except Exception as exc:
            return {
                "status": "failed",
                "as_of_date": as_of_date,
                "requested_count": 0,
                "quote_count": 0,
                "market_cap_count": 0,
                "current_count": 0,
                "history_count": 0,
                "missing_count": 0,
                "errors": [
                    f"metadata_sync_failed:{type(exc).__name__}:{str(exc)[:160]}"
                ],
            }

    async def _update_portfolio(self, task: ScheduledTask) -> dict:
        """更新持仓数据。"""
        from src.ai_os.portfolio_marking import refresh_paper_portfolio_quotes

        result = await refresh_paper_portfolio_quotes()
        return {
            "status": "marked",
            "position_count": result["position_count"],
            "fresh_position_count": result["fresh_position_count"],
            "price_coverage": result["price_coverage"],
            "stale_positions": result["stale_positions"],
            "price_sources": result["price_sources"],
            "total_value": round(result["total_value"], 2),
            "daily_pl": round(result["daily_pl"], 2),
            "daily_pl_pct": round(result["daily_pl_pct"], 4),
        }

    async def _run_scanner(self, task: ScheduledTask) -> dict:
        """运行市场扫描。"""
        from .pipeline_runner import pipeline_runner
        # Pre-market is discovery only. Market-open and afternoon tasks rerun
        # with a fresh post-signal quote, so a long 6k-stock scan cannot create
        # a misleading pre-open fill or a batch of market_closed rejections.
        result = await pipeline_runner.run_daily_pipeline(
            execute_paper_trades=task.name != "run_scanner",
            research_window=(
                "morning" if task.name == "run_scanner" else "midday"
            ),
        )
        return result.to_dict()

    async def _execute_open_strategy(self, task: ScheduledTask) -> dict:
        """Execute a persisted plan with post-signal live quotes.

        The continuous monitor passes its explicit intraday scope so eligible
        persisted watchlist probes can be filled when live conditions arrive.
        """
        from .pipeline_runner import pipeline_runner

        if getattr(task, "name", "") == "intraday_paper_monitor":
            result = await pipeline_runner.execute_persisted_strategy(
                intraday_monitor=True,
            )
        else:
            result = await pipeline_runner.execute_persisted_strategy()
        trades = list(result.get("paper_trades") or [])
        if trades:
            lines = [
                f"- {trade.get('action')} {trade.get('stock_name') or trade.get('stock_code')} "
                f"{trade.get('shares')}股 @ {float(trade.get('price') or 0):.2f} "
                f"({trade.get('execution_tier') or 'normal'})"
                for trade in trades
            ]
            notified = await self._notify_wechat(
                "Adaptive 模拟交易成交提醒",
                "\n".join([
                    f"执行时间：{result.get('paper_execution', {}).get('execution_at', '')}",
                    *lines,
                    f"模拟现金：{float(result.get('paper_cash') or 0):.2f}",
                    "仅为模拟交易，不是实盘委托。",
                ]),
            )
            result["trade_notification_sent"] = notified
        else:
            result["trade_notification_sent"] = False
        return result

    async def monitor_intraday_paper_opportunities(
        self, now: datetime | None = None,
    ) -> dict:
        """Recheck the frozen plan locally during continuous trading.

        This path does not rescan the universe or call an LLM. The underlying
        paper executor remains responsible for calendar, quote, position, and
        duplicate-order guards; notifications are emitted only for fills.
        """
        from src.ai_os.causal_execution import in_a_share_session

        observed_at = now or datetime.now().astimezone()
        if not in_a_share_session(observed_at):
            return {"status": "outside_continuous_session", "paper_trades": []}
        task = ScheduledTask(
            phase=self._intraday_phase(observed_at),
            name="intraday_paper_monitor",
            description="每分钟复核冻结策略，仅在模拟成交时通知",
        )
        return await self._execute_open_strategy(task)

    @staticmethod
    def _intraday_phase(observed_at: datetime):
        from src.ai_os.causal_execution import CHINA_TZ
        from .scheduler import SchedulePhase

        return (
            SchedulePhase.MARKET_OPEN
            if observed_at.astimezone(CHINA_TZ).hour < 12
            else SchedulePhase.AFTERNOON
        )

    async def _generate_morning_brief(self, task: ScheduledTask) -> dict:
        """生成晨报。"""
        from src.api.routes.brief_utils import build_real_brief
        from src.infrastructure.storage.market_database import market_db

        brief = await build_real_brief(force_refresh=True)
        paper = await asyncio.to_thread(market_db.get_paper_portfolio)
        regime = brief.get("market_regime") or {}
        regime_state = str(regime.get("state") or "unknown")
        regime_score = regime.get("score", 50)
        regime_date = str(regime.get("as_of_date") or "")
        regime_line = f"{regime_state} ({regime_score}/100)"
        if regime_date:
            regime_line += f" @ {regime_date}"
        picks = brief.get("considered_stocks", [])[:5]
        pattern_picks = brief.get("pattern_watchlist", [])[:5]
        pick_parts = []
        for p in picks:
            name = p.get("stock_name") or p.get("stock_code") or "未知标的"
            code = p.get("stock_code") or ""
            conclusion = p.get("deep_rating") or p.get("recommendation") or "NO_TRADE"
            price = p.get("reference_price")
            price_text = f"{float(price):.2f}元" if price else "暂无可靠报价"
            price_date = str(p.get("reference_price_date") or "")
            if price_date:
                price_text += f"（{price_date}）"
            analysis = " ".join(str(p.get("analysis") or "暂无可用分析").split())
            # Keep the decision rationale visible in PushPlus.  The channel
            # applies a 3800-character message cap, so keep each stock's
            # explanation substantial without allowing one item to consume
            # the whole brief.
            if len(analysis) > 360:
                analysis = analysis[:357] + "..."
            pick_parts.append(
                f"- {name}（{code}）｜{conclusion}｜排名分 {p.get('ranking_score', p.get('score'))}\n"
                f"  参考价：{price_text}\n"
                f"  分析：{analysis}"
            )
        pick_lines = "\n".join(pick_parts) or "- 今日无可发布的盘前关注标的（NO_TRADE）"
        pattern_parts = []
        for p in pattern_picks:
            name = p.get("stock_name") or p.get("stock_code") or "未知标的"
            code = p.get("stock_code") or ""
            dates = " → ".join(str(item) for item in (p.get("pattern_dates") or []))
            latest_flow = float(p.get("latest_main_net") or 0) / 10000
            five_flow = float(p.get("five_day_main_net") or 0) / 10000
            volume_ratio = p.get("volume_ratio_latest_vs_middle") or 0
            pattern_parts.append(
                f"- {name}（{code}）｜{p.get('pattern_label', '两阳夹一阴')}｜观察\n"
                f"  数据日：{p.get('data_date') or ''}｜形态：{dates}\n"
                f"  第三日放量/阴线日：{volume_ratio:.2f}倍｜"
                f"主力净流入：{latest_flow:.0f}万元｜近5日：{five_flow:.0f}万元\n"
                f"  说明：{p.get('recommendation') or '观察，不改变原有规则'}"
            )
        pattern_lines = "\n".join(pattern_parts) or "- 今日没有通过数据完整性核验的两阳夹一阴候选"
        trade_lines = "\n".join(
            f"- {t.get('action')} {t.get('stock_name') or t.get('stock_code')} "
            f"{t.get('shares')}股 @ {float(t.get('price') or 0):.2f}"
            for t in paper.get("trades", [])[:8]
            if str(t.get("trade_date", "")).startswith(str(brief.get("date", "")))
        ) or "- 今日暂无纸面成交"
        await self._notify_wechat(
            "AI盘前关注与纸面交易简报",
            "\n".join([
                f"market_regime: {regime_line}",
                f"日期：{brief.get('date', '')}",
                f"市场：{brief.get('market_summary', '')}",
                "盘前关注清单（最多5只）：", pick_lines,
                "两阳夹一阴额外观察（不替换原5只）：", pattern_lines,
                "今日纸面成交：", trade_lines,
                f"纸面账户：总值 {paper['total_value']:.2f}，现金 {paper['cash']:.2f}，"
                f"累计盈亏 {paper['total_pl']:.2f}",
                "\n参考价为最近可用行情，不是限价委托或买入指令。",
                "仅供研究与纸面模拟，不下真实订单，非投资建议。",
            ]),
        )
        return {
            "status": "generated",
            "generated_at": brief.get("generated_at", ""),
            "degraded": (brief.get("data_status") or {}).get("degraded", True),
            "considered_count": len(picks),
            "pattern_watch_count": len(pattern_picks),
        }

    async def _notify_wechat(self, title: str, content: str) -> bool:
        """Send a best-effort notification to the configured WeChat destination."""
        from src.notification.engine import get_notifier

        notifier = get_notifier()
        channel = "pushplus" if "pushplus" in notifier.channel_names else "wechat_work"
        if channel not in notifier.channel_names:
            return False
        results = await notifier.send(title, content, channel=channel)
        return any(item.success for item in results)

    async def _update_outcomes(self, task: ScheduledTask) -> dict:
        """Backfill decision outcomes using the implemented outcome engine."""
        from src.explain.outcome_backfiller import backfill_async

        result = await backfill_async()
        return result if isinstance(result, dict) else {"status": "completed"}

    async def _check_alerts(self, task: ScheduledTask) -> dict:
        """Evaluate alert rules against persisted pipeline decisions."""
        from src.api.routes.alerts_routes import get_today_alerts
        from src.ai_os.trading_policy import (
            PAPER_LIVENESS_LOG_LIMIT,
            paper_liveness_status,
        )
        from src.infrastructure.storage.market_database import market_db

        alerts = await get_today_alerts()
        paper = await asyncio.to_thread(market_db.get_paper_portfolio)
        today = datetime.now().date().isoformat()
        learning_log = await asyncio.to_thread(
            market_db.get_learning_log, PAPER_LIVENESS_LOG_LIMIT
        )
        liveness = paper_liveness_status(
            learning_log,
            paper.get("cash", 0.0),
            paper.get("total_value", 0.0),
            as_of_date=today,
        )
        liveness_alert_sent = False
        already_notified = any(
            str(item.get("learning_date") or "") == today
            and item.get("category") == "paper_liveness_alert"
            for item in learning_log
        )
        recent_execution = next(
            (
                item
                for item in learning_log
                if item.get("category") == "execution_observability"
            ),
            {},
        )
        execution_evidence = recent_execution.get("evidence") or {}
        if isinstance(execution_evidence, str):
            try:
                execution_evidence = json.loads(execution_evidence)
            except (TypeError, ValueError, json.JSONDecodeError):
                execution_evidence = {}
        flow_probe_alert = bool(
            int(execution_evidence.get("probe_eligible") or 0) > 0
            and int(execution_evidence.get("new_buy_count") or 0) == 0
        )
        flow_alert_already_sent = any(
            str(item.get("learning_date") or "") == today
            and item.get("category") == "flow_probe_data_alert"
            for item in learning_log
        )
        flow_execution_alert_sent = False
        if flow_probe_alert and not flow_alert_already_sent:
            flow_execution_alert_sent = await self._notify_wechat(
                "[P1] Adaptive资金流证据不足",
                (
                    f"本轮有 {execution_evidence.get('probe_eligible', 0)} 只满足非资金流条件，"
                    "但未产生正常买入。系统保持资金流缺失不放行；请检查主源和备用源。"
                ),
            )
            if flow_execution_alert_sent:
                await asyncio.to_thread(
                    market_db.save_learning,
                    today,
                    "flow_probe_data_alert",
                    "资金流证据不足导致候选无法正常执行，未自动放宽买入门槛。",
                    execution_evidence,
                )
        if liveness["alert"] and not already_notified:
            liveness_alert_sent = await self._notify_wechat(
                "[P1] Adaptive长期无可执行买入",
                (
                    f"连续无买入交易日：{liveness['consecutive_no_buy_sessions']}；"
                    f"现金比例：{liveness['cash_pct']:.1%}。"
                    "请区分市场无机会与数据不足弃权，不自动放宽买入门槛。"
                ),
            )
            if liveness_alert_sent:
                await asyncio.to_thread(
                    market_db.save_learning,
                    today,
                    "paper_liveness_alert",
                    "已发送长期无可执行买入告警，保持买入门槛不变。",
                    liveness,
                )
        return {
            "status": "evaluated",
            "total": alerts.get("total_today", 0),
            "urgent": alerts.get("urgent_count", 0),
            "data_source": "decision_journal",
            "paper_liveness": liveness,
            "liveness_alert_sent": liveness_alert_sent,
            "flow_execution_alert_sent": flow_execution_alert_sent,
        }

    async def _market_checkpoint(self, task: ScheduledTask) -> dict:
        """Capture a real market and alert checkpoint for intraday tasks."""
        from src.api.routes.alerts_routes import get_today_alerts
        from src.api.routes.market_routes import market_overview

        market, alerts = await asyncio.gather(
            market_overview(require_intraday=True), get_today_alerts()
        )
        breadth = market.get("market_breadth") or {}
        regime = market.get("market_regime") or {}
        data = market.get("_data") or {}
        breadth_provenance = data.get("breadth") or {}
        market_data_date = str(
            breadth.get("data_date")
            or breadth_provenance.get("data_date")
            or regime.get("as_of_date")
            or ""
        )[:10]
        market_data_is_live = bool(breadth_provenance.get("is_live"))
        freshness = market_checkpoint_freshness(
            market_data_date,
            market_data_is_live,
        )
        intraday_available = freshness == "today_live" and bool(
            data.get("intraday_available")
        )
        return {
            "status": "evaluated",
            "up": breadth.get("up"),
            "down": breadth.get("down"),
            "urgent_alerts": alerts.get("urgent_count", 0),
            "data_available": bool(data.get("available")),
            "intraday_data_available": intraday_available,
            "market_data_date": market_data_date,
            "market_data_source": breadth_provenance.get("source_name")
            or breadth_provenance.get("provider", ""),
            "market_data_is_live": market_data_is_live,
            "market_data_freshness": freshness,
            "market_regime_usable_for_intraday": intraday_available,
            "market_regime": regime,
            "market_regime_state": (
                regime.get("state", "unknown") if intraday_available else "unknown"
            ),
            "market_regime_score": (
                regime.get("score", 50) if intraday_available else None
            ),
        }

    async def _update_trust_metrics(self, task: ScheduledTask) -> dict:
        """Recompute trust metrics from persisted, verified decisions."""
        from src.infrastructure.storage.market_database import market_db

        stats = await asyncio.to_thread(market_db.get_decision_stats)
        return {"status": "computed", **stats}

    async def _generate_daily_journal(self, task: ScheduledTask) -> dict:
        """Summarize the real decision journal without fabricating narrative."""
        from src.api.routes.journal_utils import latest_per_stock
        from src.infrastructure.storage.market_database import market_db

        today = datetime.now().date().isoformat()
        decisions = await asyncio.to_thread(
            market_db.get_decisions_for_date, today, 5000
        )
        today_decisions = latest_per_stock(decisions)
        paper = await asyncio.to_thread(market_db.get_paper_portfolio)
        lesson = (
            f"收盘复盘：账户总值 {paper['total_value']:.2f}，"
            f"累计盈亏 {paper['total_pl']:.2f} ({paper['total_pl_pct']:.2f}%)，"
            f"现金 {paper['cash']:.2f}，持仓 {len(paper['positions'])} 只。"
        )
        await asyncio.to_thread(
            market_db.save_learning, today, "daily_review", lesson,
            {"total_value": paper["total_value"], "total_pl": paper["total_pl"],
             "trade_count": len(paper["trades"]), "decision_count": len(today_decisions)},
        )
        return {
            "status": "summarized",
            "date": today,
            "decision_count": len(today_decisions),
            "verified_count": sum(bool(item.get("outcome_known")) for item in today_decisions),
            "paper_portfolio": paper,
            "lesson": lesson,
            "data_source": "decision_journal",
        }

    async def _ai_reflection(self, task: ScheduledTask) -> dict:
        """Generate a durable, evidence-backed reflection for tomorrow's run."""
        from config.settings import settings
        from src.api.routes.journal_utils import latest_per_stock
        from src.infrastructure.ai import ai_router
        from src.infrastructure.storage.market_database import market_db

        today = datetime.now().date().isoformat()
        paper = await asyncio.to_thread(market_db.get_paper_portfolio)
        decisions = await asyncio.to_thread(
            market_db.get_decisions_for_date, today, 5000
        )
        today_decisions = latest_per_stock(decisions)
        context_decisions = sorted(
            today_decisions,
            key=lambda item: (
                bool(item.get("deep_analysis_available")),
                float(item.get("ai_score") or 0),
            ),
            reverse=True,
        )[:20]
        reflection_fields = (
            "stock_code", "stock_name", "decision_status", "direction",
            "deep_rating", "ai_score", "ranking_score", "action_score",
            "execution_disposition", "execution_block_reason",
            "outcome_known", "actual_return", "recommendation_tier",
        )
        context_decisions = [
            {
                field: item.get(field)
                for field in reflection_fields
                if item.get(field) not in (None, "", [], {})
            }
            for item in context_decisions
        ]
        recent_learning = await asyncio.to_thread(
            market_db.get_learning_log, 8
        )
        context_portfolio = {
            key: paper.get(key)
            for key in ("total_value", "total_pl", "cash", "positions", "trades")
            if key in paper
        }
        context = (
            f"date={today}\nportfolio={context_portfolio}\n"
            f"decisions={context_decisions}\n"
            f"recent_learning={recent_learning}"
        )
        reflection = (
            f"事实复盘：今日决策 {len(today_decisions)} 条，账户总值 {paper['total_value']:.2f}，"
            f"累计盈亏 {paper['total_pl']:.2f}，持仓 {len(paper['positions'])} 只。"
        )
        ai_status = "fact_only"
        ai_provider = settings.AI_REVIEW_PROVIDER
        ai_model = (
            settings.CODEX_MODEL
            if settings.AI_REVIEW_PROVIDER == "codex_cli"
            else settings.DEEPSEEK_MODEL
        )
        ai_fallback_used = False
        ai_fallback_reason = ""
        ai_error = ""
        try:
            result = await ai_router.generate(
                prompt=(
                    "请根据以下真实数据生成简洁的股票策略复盘。必须分成：做对的事、做错的事、"
                    "证据、明日一条可执行调整。不能编造行情或收益。硬性执行规则：单只股票"
                    "正常持仓上限为账户总资产20%；Codex-Terra深度评级为Buy或Overweight可正常开仓；"
                    "无深度结果时仅允许通过双数据源与实时量价确认的2%观察仓；已有超限持仓在满足T+1且非跌停时"
                    "直接降至不超过20%，不得建议继续超限。\n" + context
                ),
                system_prompt="你是量化策略复盘员，只能基于输入事实，不提供保证收益的承诺。",
                primary_provider=settings.AI_REVIEW_PROVIDER,
                allow_fallback=False,
                model=settings.AI_FAST_MODEL,
            )
            reflection = result.text
            ai_status = "ok"
            ai_provider = result.provider
            ai_model = result.model
            ai_fallback_used = bool(result.fallback_used)
            ai_fallback_reason = str(result.fallback_reason or "")[:240]
        except Exception as exc:
            ai_status = "degraded"
            ai_error = str(exc)[:240]
            reflection += f" AI复盘暂不可用：{ai_error}"
        await asyncio.to_thread(
            market_db.save_learning, today, "ai_reflection", reflection,
            {
                "decision_count": len(today_decisions),
                "portfolio_value": paper["total_value"],
                "ai_status": ai_status,
                "ai_provider": ai_provider,
                "ai_model": ai_model,
                "ai_fallback_used": ai_fallback_used,
                "ai_fallback_reason": ai_fallback_reason,
                "ai_error": ai_error,
            },
        )
        await self._notify_wechat("AI每日复盘", reflection)
        return {
            "status": "reflected" if ai_status == "ok" else "reflected_degraded",
            "date": today,
            "reflection": reflection,
            "ai_status": ai_status,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "ai_fallback_used": ai_fallback_used,
            "ai_fallback_reason": ai_fallback_reason,
            "ai_error": ai_error,
        }

    async def _periodic_review(self, task: ScheduledTask) -> dict:
        """Produce factual weekly/monthly metrics from the decision journal."""
        from src.infrastructure.storage.market_database import market_db

        stats = await asyncio.to_thread(market_db.get_decision_stats)
        return {
            "status": "computed",
            "review": task.name,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            **stats,
        }

    async def _update_user_model(self, task: ScheduledTask) -> dict:
        """Refresh the learned user profile and persist an audit entry."""
        from src.infrastructure.storage.market_database import market_db
        from src.user_model.journal_loader import load_user_model_from_journal

        engine, model_metadata = await asyncio.to_thread(load_user_model_from_journal)
        profile = await asyncio.to_thread(engine.generate_profile)
        profile_data = profile.to_dict() if hasattr(profile, "to_dict") else {}
        decisions = await asyncio.to_thread(market_db.get_decision_stats)
        await asyncio.to_thread(
            market_db.save_learning,
            datetime.now().date().isoformat(),
            "user_model",
            profile_data.get("user_summary") or "用户行为画像已更新，当前数据仍在积累。",
            {
                "profile": profile_data,
                "decision_stats": decisions,
                "model_metadata": model_metadata,
            },
        )
        return {
            "status": "updated",
            "profile_version": profile_data.get("profile_version", ""),
            "total_decisions_analyzed": profile_data.get("total_decisions_analyzed", 0),
            "paper_action_count": model_metadata.get("paper_action_count", 0),
        }

    async def _weekly_user_insights(self, task: ScheduledTask) -> dict:
        """Persist a weekly user/portfolio insight from local evidence."""
        from src.infrastructure.storage.market_database import market_db

        stats = await asyncio.to_thread(market_db.get_decision_stats)
        paper = await asyncio.to_thread(market_db.get_paper_portfolio)
        decisive = int(stats.get("decisive_verified_decisions") or 0)
        neutral = int(stats.get("neutral_verified_decisions") or 0)
        accuracy_text = (
            f"BUY/SELL 已验证 {decisive} 条，方向准确率 {stats['accuracy']:.1%}"
            if decisive else
            f"BUY/SELL 尚无到期样本，暂不计算准确率；中性观察 {neutral} 条"
        )
        lesson = (
            f"周度用户与账户洞察：{accuracy_text}；"
            f"纸面账户总值 {paper['total_value']:.2f}，持仓 {len(paper['positions'])} 只。"
        )
        await asyncio.to_thread(
            market_db.save_learning,
            datetime.now().date().isoformat(), "weekly_user_insights", lesson,
            {"decision_stats": stats, "paper_portfolio": paper},
        )
        return {"status": "insights_saved", "decision_stats": stats}

    async def _weekly_learning_log(self, task: ScheduledTask) -> dict:
        """Persist a weekly strategy lesson for the next scan to consume."""
        from src.infrastructure.storage.market_database import market_db

        stats = await asyncio.to_thread(market_db.get_decision_stats)
        performance = await asyncio.to_thread(market_db.get_strategy_performance)
        buckets = performance.get("buckets", [])
        best = max(buckets, key=lambda item: item.get("accuracy", 0), default=None)
        decisive = int(stats.get("decisive_verified_decisions") or 0)
        neutral = int(stats.get("neutral_verified_decisions") or 0)
        lesson = (
            f"周度策略学习：验证 {decisive} 条 BUY/SELL 决策，"
            f"方向准确率 {stats['accuracy']:.1%}；"
            f"当前最佳策略层 {best.get('strategy')}。"
            if best and decisive else
            f"周度策略学习：BUY/SELL 尚无到期样本，中性观察 {neutral} 条不计入准确率；"
            "继续积累真实方向结果。"
        )
        await asyncio.to_thread(
            market_db.save_learning,
            datetime.now().date().isoformat(), "weekly_learning", lesson,
            {"decision_stats": stats, "strategy_performance": performance},
        )
        return {"status": "learning_saved", "strategy_performance": performance}

    async def _model_evolution_check(self, task: ScheduledTask) -> dict:
        """Record monthly model/strategy evolution metrics without inventing a version change."""
        from src.infrastructure.storage.market_database import market_db

        stats = await asyncio.to_thread(market_db.get_decision_stats)
        performance = await asyncio.to_thread(market_db.get_strategy_performance)
        decisive = int(stats.get("decisive_verified_decisions") or 0)
        lesson = (
            f"月度模型演进检查：已验证 {decisive} 条 BUY/SELL，"
            f"方向准确率 {stats['accuracy']:.1%}；仅在样本达到统计要求后调整策略参数。"
            if decisive else
            "月度模型演进检查：BUY/SELL 尚无到期样本，准确率暂不可用；"
            "等待真实方向结果后再调整策略参数。"
        )
        await asyncio.to_thread(
            market_db.save_learning,
            datetime.now().date().isoformat(), "model_evolution", lesson,
            {"decision_stats": stats, "strategy_performance": performance},
        )
        return {
            "status": "checked",
            "verified_decisions": decisive,
            "observed_decisions": stats["verified_decisions"],
            "strategy_buckets": len(performance.get("buckets", [])),
        }

    async def _default_handler(self, task: ScheduledTask) -> dict:
        """Reject unimplemented tasks instead of recording a false success."""
        raise NotImplementedError(f"任务 {task.name} 尚未接入真实执行逻辑")

    def _add_execution(self, execution: TaskExecution) -> None:
        """添加执行记录并更新统计 for synchronous callers."""
        self._record_execution_in_memory(execution)
        self._persist_execution(execution)

    async def _add_execution_async(self, execution: TaskExecution) -> None:
        """Record execution without blocking the event loop on SQLite."""
        self._record_execution_in_memory(execution)
        if self._persist:
            await asyncio.to_thread(self._persist_execution, execution)

    def _record_execution_in_memory(self, execution: TaskExecution) -> None:
        """Add an execution to the in-memory history and statistics."""
        # 添加到历史（保留最近100条）
        self._execution_history.append(execution)
        if len(self._execution_history) > 100:
            self._execution_history.pop(0)

        self._update_stats(execution)

    def _persist_execution(self, execution: TaskExecution) -> None:
        """Persist one execution; persistence failures never change task state."""
        if self._persist:
            try:
                from src.infrastructure.storage.market_database import market_db

                market_db.save_task_execution(execution.to_dict())
            except Exception:
                # Monitoring persistence must never make the actual task fail.
                pass

    def _restore_history(self) -> None:
        """Restore recent executions after a backend restart."""
        try:
            from src.infrastructure.storage.market_database import market_db

            rows = market_db.get_task_executions(limit=100)
        except Exception:
            return
        for row in rows:
            try:
                execution = TaskExecution(
                    task_name=str(row.get("task_name", "")),
                    phase=str(row.get("phase", "")),
                    status=TaskStatus(str(row.get("status", TaskStatus.FAILED.value))),
                    trigger_source=str(row.get("trigger_source") or "legacy"),
                    started_at=str(row.get("started_at", "")),
                    completed_at=str(row.get("completed_at", "")),
                    duration_seconds=float(row.get("duration_seconds", 0) or 0),
                    error=str(row.get("error", "")),
                    output=row.get("output") if isinstance(row.get("output"), dict) else {},
                    is_critical=bool(
                        row.get("is_critical", False)
                        or (row.get("output") or {}).get("is_critical", False)
                    ),
                    failure_fingerprint=str(
                        row.get("failure_fingerprint")
                        or (row.get("output") or {}).get("failure_fingerprint")
                        or ""
                    ),
                    consecutive_failures=int(
                        row.get("consecutive_failures", 0)
                        or (row.get("output") or {}).get("consecutive_failures", 0)
                        or 0
                    ),
                    circuit_state=str(
                        row.get("circuit_state")
                        or (row.get("output") or {}).get("circuit_state")
                        or "healthy"
                    ),
                    incident_key=str(
                        row.get("incident_key")
                        or (row.get("output") or {}).get("incident_key")
                        or ""
                    ),
                )
            except (TypeError, ValueError):
                continue
            self._execution_history.append(execution)
            self._update_stats(execution)

    def _update_stats(self, execution: TaskExecution) -> None:
        """Update aggregate counters for one execution."""
        stats = self._task_stats.get(execution.task_name)
        if not stats:
            stats = TaskStats(task_name=execution.task_name)
            self._task_stats[execution.task_name] = stats

        stats.total_runs += 1
        stats.last_run_at = execution.completed_at
        stats.last_status = execution.status
        if execution.status == TaskStatus.SUCCESS:
            stats.success_count += 1
        elif execution.status == TaskStatus.FAILED:
            stats.failed_count += 1
        old_avg = stats.avg_duration_seconds
        stats.avg_duration_seconds = (
            old_avg * (stats.total_runs - 1) + execution.duration_seconds
        ) / stats.total_runs

    def get_status(self) -> dict:
        """获取任务执行器状态。"""
        return {
            "is_running": self._is_running,
            "persistence_enabled": self._persist,
            "strategy_version": ALGORITHM_VERSION,
            "history_retention": 500 if self._persist else 100,
            "total_executions": len(self._execution_history),
            "running_tasks": list(self._running_tasks.keys()),
            "open_circuits": [
                task_name for task_name, incident in self._failure_incidents.items()
                if incident.get("state") == "circuit_open"
            ],
            "failure_incidents": list(self._failure_incidents.values()),
            "task_stats": [stats.to_dict() for stats in self._task_stats.values()],
        }

    def get_recent_executions(self, limit: int = 20) -> list[dict]:
        """获取最近的执行记录。"""
        recent = self._execution_history[-limit:] if self._execution_history else []
        return [exec.to_dict() for exec in reversed(recent)]

    def get_task_history(self, task_name: str, limit: int = 10) -> list[dict]:
        """获取指定任务的执行历史。"""
        history = [
            exec for exec in self._execution_history
            if exec.task_name == task_name
        ]
        recent = history[-limit:] if history else []
        return [exec.to_dict() for exec in reversed(recent)]


# 全局单例
task_executor = TaskExecutor(persist=True)
