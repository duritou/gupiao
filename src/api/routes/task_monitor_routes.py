"""AI OS 任务监控 API 路由。

提供任务执行状态、历史记录、统计信息的查询接口。
供 VSCode 插件展示任务监控面板。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.ai_os.scheduler import ALL_TASKS, SchedulePhase, get_current_phase
from src.ai_os.task_executor import task_executor

router = APIRouter(prefix="/tasks", tags=["Task Monitor"])
_scheduler_runtime = {
    "running": False,
    "timezone": "Asia/Shanghai",
    "jobs": [],
    "error": "调度器尚未启动",
}
_scheduler_instance = None


def update_scheduler_runtime(scheduler=None, error: str = "") -> None:
    """Publish APScheduler state to the monitoring API."""
    global _scheduler_instance
    if scheduler is None:
        _scheduler_instance = None
        _scheduler_runtime.update({"running": False, "jobs": [], "error": error})
        return
    _scheduler_instance = scheduler
    jobs = [
        {
            "id": job.id,
            "next_run_at": job.next_run_time.isoformat() if job.next_run_time else "",
        }
        for job in scheduler.get_jobs()
    ]
    _scheduler_runtime.update({"running": scheduler.running, "jobs": jobs, "error": error})


@router.get("/status")
async def get_executor_status():
    """获取任务执行器总体状态。

    Returns:
        - is_running: 执行器是否运行中
        - total_executions: 总执行次数
        - running_tasks: 当前正在运行的任务列表
        - task_stats: 各任务的统计信息
        - current_phase: 当前时段
    """
    if _scheduler_instance is not None:
        update_scheduler_runtime(_scheduler_instance)
    status = task_executor.get_status()
    status["current_phase"] = get_current_phase()
    status["scheduler"] = dict(_scheduler_runtime)
    return status


@router.get("/executions/recent")
async def get_recent_executions(limit: int = 20):
    """获取最近的任务执行记录。

    Args:
        limit: 返回记录数量（默认20条）

    Returns:
        执行记录列表，按时间倒序
    """
    return task_executor.get_recent_executions(limit=limit)


@router.get("/failures")
async def get_actionable_failures(hours: int = 24):
    """Return recent critical failures suitable for proactive notification."""
    safe_hours = max(1, min(hours, 168))
    # Execution history contains both legacy naive timestamps and newer
    # timezone-aware timestamps.  Normalize both forms before comparing;
    # otherwise Python raises ``TypeError`` and the monitoring endpoint returns
    # HTTP 500 as soon as an aware execution is within the lookback window.
    local_now = datetime.now().astimezone()
    cutoff = local_now - timedelta(hours=safe_hours)
    # Scanner failures block the decision chain even though the schedule
    # marks only the downstream brief as critical.  Surface the root cause,
    # not every dependent task that was consequently skipped.
    critical_tasks = {task.name for task in ALL_TASKS if task.is_critical}
    critical_tasks.update({"run_scanner", "afternoon_scan"})
    benign_skip_prefixes = (
        "非交易日",
        "同名任务正在执行",
        "依赖未完成",
    )
    incidents = []
    seen_incidents: set[tuple[str, str]] = set()
    for execution in task_executor.get_recent_executions(limit=100):
        completed_at = str(execution.get("completed_at", ""))
        try:
            completed = datetime.fromisoformat(completed_at)
        except ValueError:
            continue
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=local_now.tzinfo)
        else:
            completed = completed.astimezone(local_now.tzinfo)
        error = str(execution.get("error", ""))
        if completed < cutoff or execution.get("task_name") not in critical_tasks:
            continue
        if execution.get("status") not in {"failed", "skipped"}:
            continue
        if error.startswith(benign_skip_prefixes):
            continue
        incident_key = (str(execution.get("task_name", "")), error)
        if incident_key in seen_incidents:
            continue
        seen_incidents.add(incident_key)
        incidents.append({
            "id": f"task:{execution['task_name']}:{completed_at}",
            "task_name": execution["task_name"],
            "status": execution["status"],
            "error": error,
            "completed_at": completed_at,
            "severity": "P0",
        })

    if task_executor.get_status()["is_running"] and not _scheduler_runtime["running"]:
        incidents.append({
            "id": (
                f"scheduler:{datetime.now().date().isoformat()}:"
                f"{_scheduler_runtime.get('error', 'not-running')}"
            ),
            "task_name": "scheduler",
            "status": "failed",
            "error": _scheduler_runtime.get("error") or "APScheduler 未运行",
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "severity": "P0",
        })
    return {"failures": incidents, "count": len(incidents), "window_hours": safe_hours}


@router.get("/executions/{task_name}")
async def get_task_history(task_name: str, limit: int = 10):
    """获取指定任务的执行历史。

    Args:
        task_name: 任务名称
        limit: 返回记录数量（默认10条）

    Returns:
        该任务的执行记录列表
    """
    return task_executor.get_task_history(task_name, limit=limit)


@router.get("/schedule")
async def get_schedule_info():
    """获取完整的任务调度信息。

    Returns:
        - phases: 各时段及其任务定义
        - current_phase: 当前时段
        - all_tasks: 所有任务列表
    """
    phases_info = {}
    for phase in SchedulePhase:
        phase_tasks = [
            {
                "name": t.name,
                "description": t.description,
                "phase": t.phase,
                "is_critical": t.is_critical,
                "depends_on": t.depends_on,
            }
            for t in ALL_TASKS if t.phase == phase
        ]
        if phase_tasks:
            phases_info[phase] = phase_tasks

    return {
        "phases": phases_info,
        "current_phase": get_current_phase(),
        "all_tasks": [
            {
                "name": t.name,
                "description": t.description,
                "phase": t.phase,
                "is_critical": t.is_critical,
            }
            for t in ALL_TASKS
        ],
    }


@router.post("/execute/{task_name}")
async def execute_task_manually(
    task_name: str, rerun_id: str = Query(default="", pattern=r"^[a-zA-Z0-9_-]{0,64}$")
):
    """手动触发执行指定任务。

    Args:
        task_name: 任务名称

    Returns:
        执行结果
    """
    # 找到任务定义
    task = next((t for t in ALL_TASKS if t.name == task_name), None)
    if not task:
        return {"error": f"任务 {task_name} 不存在"}

    # 执行任务
    if rerun_id:
        if task_name != "execute_open_strategy":
            raise HTTPException(status_code=400, detail="only open strategy supports explicit rerun")
        execution = await task_executor.rerun_open_strategy(task, rerun_id)
    else:
        execution = await task_executor.execute_task(task, trigger_source="manual_api")
    return execution.to_dict()
