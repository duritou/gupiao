"""FastAPI Application — Adaptive Investment Intelligence Platform API"""

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, date as dt_date
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("uvicorn.error")  # 复用 uvicorn 日志 handler,确保启动同步日志可见


def _deployment_validation_active() -> bool:
    """Keep startup work out of the deployment validation window."""
    candidates: list[Path] = []
    manifest_path = str(os.getenv("ADAPTIVE_RELEASE_MANIFEST") or "").strip()
    if manifest_path:
        candidates.append(Path(manifest_path).with_name("maintenance.json"))
    candidates.append(Path(__file__).resolve().parents[2] / "runtime" / "maintenance.json")
    for path in candidates:
        try:
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            return str(payload.get("status") or "").lower() == "deploying"
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return False


from src.api.routes import (
    system_routes,
    knowledge_routes,
    wechat_routes,
    signals_routes,
    scanner_routes,
    research_routes,
    backtest_routes,
    market_routes,
    timeline_routes,
    alerts_routes,
    dailybrief_routes,
    detail_routes,
    explain_routes,
    trust_routes,
    user_routes,
    ai_os_routes,
    replay_routes,
    knowledge_graph_routes,
    decision_routes,
    vibe_compat_routes,
    unified_research_routes,
    task_monitor_routes,
)

# Portfolio routes — direct import
from src.api.routes import portfolio_routes as portfolio_mod
from src.api.routes import morning_brief_routes as morning_mod

@asynccontextmanager
async def lifespan(app):
    """启动时:数据落后则后台增量同步 + 注册每日决策回填定时任务(16:05)。"""
    from src.ai_os.strategy_version import create_runtime_identity
    from src.infrastructure.runtime_identity import validate_startup_if_managed
    from src.infrastructure.storage.market_database import market_db

    validate_startup_if_managed()
    # Validate the process identity before starting any task that can write
    # market, decision, learning, or paper-trading state.
    try:
        await asyncio.to_thread(
            market_db.validate_runtime_contract, create_runtime_identity()
        )
    except Exception as exc:
        logger.critical("[startup] runtime compatibility validation failed: %s", exc)
        try:
            from src.notification.engine import get_notifier

            notifier = get_notifier()
            channel = "pushplus" if "pushplus" in notifier.channel_names else "wechat_work"
            if channel in notifier.channel_names:
                await notifier.send(
                    "[P0] Adaptive启动被阻断",
                    f"运行时契约校验失败，交易任务未启动：{type(exc).__name__}: {exc}",
                    channel=channel,
                )
        except Exception:
            logger.exception("[startup] failed to send compatibility alert")
        raise
    try:
        from src.explain.evidence_quality import restore_cases

        restored_cases = restore_cases(
            await asyncio.to_thread(market_db.get_research_case_rows, 5000)
        )
        logger.info("[startup] restored %d persisted research cases", restored_cases)
    except Exception:
        logger.exception("[startup] failed to restore persisted research cases")

    scheduler = None
    try:
        deployment_validation = _deployment_validation_active()
        startup_recovery_grace_until = (
            time.monotonic() + 60.0 if deployment_validation else 0.0
        )
        stats = await asyncio.to_thread(market_db.get_stats)
        latest = str(stats.get("latest_data_date") or "")
        from src.ai_os.task_executor import market_data_covers_latest_completed_day
        from src.ai_os.trading_calendar import get_latest_completed_trading_day

        completed_day = await get_latest_completed_trading_day(dt_date.today())
        expected = completed_day.day.isoformat() if completed_day.day else ""
        stale = not market_data_covers_latest_completed_day(latest, completed_day)

        if stale and not deployment_validation:
            logger.info(
                "[sync] 本地数据落后(latest=%s, expected=%s, calendar=%s),"
                "启动后台增量同步(全 A 股,约 30-60 分钟)...",
                latest, expected, completed_day.source,
            )
            from src.api.routes.market_routes import _run_sync, _sync_state
            _sync_state["running"] = True
            _sync_state["started_at"] = datetime.now().isoformat()
            _sync_state["progress"] = {"done": 0, "total": 0, "current": "startup"}
            _sync_state["result"] = None
            _sync_state["error"] = None
            asyncio.create_task(_run_sync(None, 30, True, target_date=expected))
        elif stale:
            logger.info("[sync] 部署验收期间跳过启动同步，避免阻塞新版本就绪检查。")
        else:
            logger.info(
                "[sync] 本地数据覆盖最近已完成交易日(latest=%s, expected=%s),跳过启动同步。",
                latest, expected,
            )

        # 启动任务执行器
        from src.ai_os.task_executor import task_executor
        task_executor.start()
        logger.info("[TaskExecutor] 任务执行器已启动")

        # Probe a stable real-time provider once after every restart.  Health
        # pages then show measured state instead of treating "untested" as down.
        from src.infrastructure.market_data.source_manager import source_manager
        if not deployment_validation:
            asyncio.create_task(source_manager.probe_live_sources())
        else:
            logger.info("[startup] 部署验收期间跳过实时源探测。")

        # 决策结果回填定时任务(每日 16:05 收盘后,让系统持续"学习")
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from src.explain.outcome_backfiller import backfill_async

            async def _daily_backfill():
                logger.info("[backfill] 定时触发每日决策回填 (16:05)")
                await backfill_async()

            research_backfill_lock = asyncio.Lock()

            async def _run_research_backfill_worker(
                arguments: list[str],
                working_directory: str,
            ) -> int:
                """Run bounded research backfill outside the API event loop."""
                script = Path(__file__).resolve().parents[2] / "scripts" / "backfill_research_data.py"
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(script),
                    *arguments,
                    cwd=working_directory,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    detail = (stderr or stdout or b"").decode(
                        "utf-8", errors="replace"
                    )[-500:]
                    logger.warning(
                        "[research-backfill] worker exit=%s detail=%s",
                        process.returncode,
                        detail,
                    )
                return int(process.returncode or 0)

            async def _run_post_backfill_ai_worker(
                source_db: str,
                working_directory: str,
                execution_key: str,
                source_run_id: str,
                data_revision: str,
            ) -> dict:
                """Run one research-only AI pass in a bounded child process."""
                script = Path(__file__).resolve().parents[2] / "scripts" / "run_post_backfill_ai.py"
                environment = os.environ.copy()
                environment["ADAPTIVE_MARKET_DB_PATH"] = str(source_db)
                started = time.monotonic()
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(script),
                    "--execution-key", execution_key,
                    "--source-run-id", source_run_id,
                    "--data-revision", data_revision,
                    cwd=working_directory,
                    env=environment,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=1800
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    stdout, stderr = await process.communicate()
                    return {
                        "status": "timeout",
                        "returncode": process.returncode,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "error": "post_backfill_ai_worker_timeout",
                    }
                output_text = (stdout or b"").decode("utf-8", errors="replace")
                payload = {}
                for line in reversed(output_text.splitlines()):
                    try:
                        candidate = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(candidate, dict):
                        payload = candidate
                        break
                if process.returncode != 0:
                    detail = (stderr or stdout or b"").decode(
                        "utf-8", errors="replace"
                    )[-500:]
                    payload.setdefault("status", "failed")
                    payload.setdefault("error", detail)
                return {
                    **payload,
                    "returncode": int(process.returncode or 0),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }

            async def _record_post_backfill_execution(
                database: object,
                execution_key: str,
                status: str,
                started_at: str,
                output: dict,
                error: str = "",
            ) -> None:
                completed_at = datetime.now().astimezone().isoformat()
                started = started_at or completed_at
                try:
                    duration = (
                        datetime.fromisoformat(completed_at)
                        - datetime.fromisoformat(started)
                    ).total_seconds()
                except ValueError:
                    duration = 0.0
                await asyncio.to_thread(
                    database.save_task_execution,
                    {
                        "task_name": "post_backfill_ai_rerun",
                        "phase": "evening",
                        "status": status,
                        "trigger_source": "post_backfill_coverage_gate",
                        "started_at": started,
                        "completed_at": completed_at,
                        "duration_seconds": duration,
                        "error": error,
                        "execution_key": execution_key,
                        "output": output,
                    },
                )

            async def _maybe_post_backfill_ai_rerun(
                source_db: str, output_dir: str, working_directory: str,
                worker_codes: list[int],
            ) -> None:
                """Gate and dispatch one durable, research-only rerun."""
                if worker_codes and any(code not in {0, 2} for code in worker_codes):
                    logger.warning(
                        "[research-backfill] worker failed; AI rerun not triggered: %s",
                        worker_codes,
                    )
                    return
                from src.ai_os.post_backfill_rerun import (
                    evaluate_post_backfill_gate,
                    make_rerun_execution_key,
                    summarize_latest_backfill,
                    verify_rerun_result,
                )
                from src.infrastructure.storage.market_database import MarketDatabase

                database = await asyncio.to_thread(MarketDatabase, source_db)
                summary = await asyncio.to_thread(summarize_latest_backfill, database)
                if summary.get("status") == "not_ready":
                    logger.warning(
                        "[research-backfill] no matching checkpoint for AI rerun: %s",
                        summary.get("reason_codes"),
                    )
                    return
                latest_run = await asyncio.to_thread(database.get_latest_strategy_run)
                gate = evaluate_post_backfill_gate(
                    summary,
                    previous_ai_run_created_at=str(
                        latest_run.get("run_created_at") or ""
                    ),
                )
                execution_key = make_rerun_execution_key(summary)
                claim = await asyncio.to_thread(
                    database.claim_research_rerun,
                    execution_key,
                    summary.get("target_date", ""),
                    summary.get("source_run_id", ""),
                    summary.get("data_revision", ""),
                )
                if not claim.get("claimed"):
                    logger.info(
                        "[research-backfill] AI rerun already dispatched: %s",
                        execution_key,
                    )
                    return
                started_at = datetime.now().astimezone().isoformat()
                if not gate.get("eligible"):
                    result = {
                        "stage_status": "backfill_below_threshold_ai_not_triggered",
                        "summary": summary,
                        "gate": gate,
                    }
                    await asyncio.to_thread(
                        database.finish_research_rerun,
                        execution_key, "not_eligible", result,
                    )
                    await _record_post_backfill_execution(
                        database, execution_key, "skipped", started_at, result,
                        ";".join(gate.get("reason_codes") or []),
                    )
                    logger.info(
                        "[research-backfill] AI rerun not eligible: %s",
                        gate.get("reason_codes"),
                    )
                    return
                worker_result = await _run_post_backfill_ai_worker(
                    source_db, working_directory, execution_key,
                    str(summary.get("source_run_id") or ""),
                    str(summary.get("data_revision") or ""),
                )
                new_result = worker_result.get("result") or {}
                new_run_id = str(new_result.get("run_id") or "")
                persisted = await asyncio.to_thread(
                    database.get_strategy_run_evidence_summary, new_run_id
                )
                verification = verify_rerun_result(
                    worker_result, persisted,
                    source_run_id=str(summary.get("source_run_id") or ""),
                    checkpoint_updated_at=str(summary.get("checkpoint_updated_at") or ""),
                    expected_decision_count=int(summary.get("candidate_count") or 1),
                )
                terminal_status = (
                    "succeeded" if verification.get("verified") else "failed"
                )
                stage_status = (
                    "backfill_partial_threshold_met_ai_rerun_succeeded"
                    if summary.get("worker_status") == "partial"
                    and verification.get("verified")
                    else "backfill_completed_ai_rerun_succeeded"
                    if verification.get("verified")
                    else "ai_consumption_verification_failed"
                )
                result = {
                    "stage_status": stage_status,
                    "summary": summary,
                    "gate": gate,
                    "worker": worker_result,
                    "verification": verification,
                }
                await asyncio.to_thread(
                    database.finish_research_rerun,
                    execution_key, terminal_status, result,
                )
                await _record_post_backfill_execution(
                    database, execution_key,
                    "success" if verification.get("verified") else "failed",
                    started_at, result,
                    ";".join(verification.get("reason_codes") or []),
                )
                logger.info(
                    "[research-backfill] post-backfill AI rerun %s: run_id=%s",
                    stage_status, verification.get("new_run_id"),
                )

            async def _daily_research_data_backfill(include_current: bool = True):
                """Resume candidate component backfill outside trading hours."""
                if research_backfill_lock.locked():
                    logger.warning("[research-backfill] 已有补采任务运行，跳过本次触发")
                    return
                async with research_backfill_lock:
                    try:
                        from src.infrastructure.storage.market_database import DB_PATH

                        output_dir = str(
                            Path(DB_PATH).resolve().parents[3]
                            / "test-reports"
                            / "production-research-backfill"
                        )
                        working_directory = str(Path(DB_PATH).resolve().parents[3])
                        common_args = [
                            "--source-db", str(DB_PATH),
                            "--output-dir", output_dir,
                            "--scope", "candidate", "--limit", "300",
                            "--required-bars", "250", "--periods", "8",
                            "--flow-days", "20",
                            "--write-production", "--confirm-production",
                            # 300 codes take roughly 150s (measured).  The old
                            # 60s deadline stopped every run about 40% of the
                            # way through, and because the checkpoint partition
                            # embeds the pipeline run id -- which changes on
                            # every scan -- the next run started over instead of
                            # resuming.  Coverage therefore never converged, the
                            # 95% gate in post_backfill_rerun kept blocking the
                            # research rerun, and the missing financial evidence
                            # kept the deep model on Hold.
                            "--batch-deadline-seconds", "600",
                            # The lease has to outlive the batch deadline or it
                            # expires mid-run and a second worker can claim it.
                            "--lease-seconds", "900",
                        ]
                        worker_codes = [await _run_research_backfill_worker(
                            [*common_args, "--recover-pending"],
                            working_directory,
                        )]
                        if include_current:
                            worker_codes.append(await _run_research_backfill_worker(
                                common_args,
                                working_directory,
                            ))
                        await _maybe_post_backfill_ai_rerun(
                            str(DB_PATH), output_dir, working_directory, worker_codes
                        )
                    except Exception as exc:
                        logger.exception(
                            "[research-backfill] 生产补采失败: %s: %s",
                            type(exc).__name__,
                            str(exc) or repr(exc),
                        )

            wechat_sync_lock = asyncio.Lock()

            async def _daily_wechat_sync():
                """Refresh optional public-account knowledge once per day."""
                from config.settings import settings

                if deployment_validation or not settings.WECHAT_RSS_ENABLED:
                    return
                if wechat_sync_lock.locked():
                    logger.warning("[wechat-rss] 已有同步任务运行，跳过本次触发")
                    return
                async with wechat_sync_lock:
                    try:
                        from src.knowledge.wechat_rss import (
                            learn_wechat_methodology,
                            sync_wechat_articles,
                        )

                        result = await asyncio.to_thread(sync_wechat_articles)
                        learning = await learn_wechat_methodology()
                        logger.info(
                            "[wechat-rss] daily sync status=%s fetched=%s new=%s updated=%s learning=%s",
                            result.get("status"),
                            result.get("fetched_count", 0),
                            result.get("new", 0),
                            result.get("updated", 0),
                            learning.get("status", "unknown"),
                        )
                    except Exception as exc:
                        logger.warning(
                            "[wechat-rss] daily sync failed: %s: %s",
                            type(exc).__name__, str(exc)[:200],
                        )

            # Pin the business schedule to China Standard Time instead of
            # inheriting a machine timezone that may change after reboot.
            scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
            scheduler.add_job(
                _daily_backfill,
                "cron",
                hour=16,
                minute=5,
                id="decision_backfill",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=30,
            )
            scheduler.add_job(
                _daily_research_data_backfill,
                "cron",
                day_of_week="mon-fri",
                hour=20,
                minute=30,
                id="research_data_backfill",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            from config.settings import settings as app_settings

            scheduler.add_job(
                _daily_wechat_sync,
                "cron",
                hour=max(0, min(int(app_settings.WECHAT_RSS_SYNC_HOUR), 23)),
                minute=max(0, min(int(app_settings.WECHAT_RSS_SYNC_MINUTE), 59)),
                id="wechat_rss_sync",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=900,
            )

            # 注册AI OS调度器定时任务
            from src.ai_os.scheduler import (
                HITHINK_CANARY_CHECKPOINTS,
                PHASE_SCHEDULE_TIMES,
                SchedulePhase,
                get_recoverable_phases,
                get_schedule_for_phase,
            )
            from src.ai_os.trading_calendar import get_trading_day_status

            # A phase can be triggered by its cron job and by recovery at the
            # same time. Serialize the whole phase so a slow scan cannot race
            # with a restart watchdog or produce duplicate paper orders.
            phase_lock = asyncio.Lock()
            intraday_monitor_lock = asyncio.Lock()

            async def _run_hithink_canary_checkpoint(checkpoint: str):
                """Run an aggregate HiThink probe without entering strategy flow."""
                if _deployment_validation_active():
                    return
                try:
                    from src.ai_os.hithink_canary import run_hithink_canary

                    result = await run_hithink_canary(checkpoint)
                    if result["status"] == "failed":
                        logger.warning(
                            "[hithink-canary] checkpoint=%s failed: %s",
                            checkpoint,
                            result.get("error_type", "unknown"),
                        )
                    else:
                        logger.info(
                            "[hithink-canary] checkpoint=%s status=%s supported=%s/%s",
                            checkpoint,
                            result["status"],
                            result.get("supported_count", 0),
                            result.get("capability_count", 0),
                        )
                except Exception as exc:
                    logger.warning(
                        "[hithink-canary] checkpoint=%s isolated failure: %s: %s",
                        checkpoint,
                        type(exc).__name__,
                        str(exc)[:160],
                    )

            async def _monitor_intraday_paper_opportunities():
                """Use local rules each minute; fills alone trigger notifications."""
                if _deployment_validation_active() or intraday_monitor_lock.locked():
                    return
                async with intraday_monitor_lock:
                    try:
                        await task_executor.monitor_intraday_paper_opportunities()
                    except Exception as exc:
                        logger.warning(
                            "[TaskExecutor] 盘中本地监控失败: %s: %s",
                            type(exc).__name__,
                            str(exc)[:200],
                        )

            async def _execute_phase_tasks(
                phase: SchedulePhase,
                trigger_source: str = "scheduler",
            ):
                """Execute a phase once, skipping tasks already successful today."""
                async with phase_lock:
                    tasks = get_schedule_for_phase(phase)
                    for task in tasks:
                        if task_executor.has_succeeded_today(task.name):
                            logger.info(
                                "[TaskExecutor] 跳过今日已成功任务: %s (phase=%s)",
                                task.name,
                                phase.value,
                            )
                            continue
                        if (
                            "recovery" in trigger_source
                            and task_executor.is_in_failure_cooldown(task.name)
                        ):
                            logger.warning(
                                "[TaskExecutor] 任务失败冷却中，跳过恢复重试: %s",
                                task.name,
                            )
                            continue
                        try:
                            execution = await task_executor.execute_task(
                                task,
                                trigger_source=trigger_source,
                            )
                            if execution.status.value == "failed" and task.is_critical:
                                logger.error(
                                    "[TaskExecutor] 关键任务失败，停止阶段后续任务: %s",
                                    task.name,
                                )
                                break
                        except Exception as e:
                            logger.error("[TaskExecutor] 任务 %s 执行失败: %s", task.name, e)

            async def _recover_missed_phases(trigger_source: str = "startup_recovery"):
                """Catch up safe missed phases after a late start or restart.

                The recovery windows are intentionally bounded. A late
                pre-market restart can still complete the morning workflow;
                an afternoon restart will not retroactively create a new
                opening trade. Close reconciliation remains recoverable into
                the evening because it only marks the paper portfolio and
                unlocks the daily learning loop.
                """
                if (
                    _deployment_validation_active()
                    or time.monotonic() < startup_recovery_grace_until
                ):
                    return
                phases = get_recoverable_phases()
                if not phases:
                    return
                try:
                    calendar_status = await get_trading_day_status()
                    if not calendar_status.is_trading_day:
                        return
                    for phase in phases:
                        tasks = get_schedule_for_phase(phase)
                        pending = [
                            task for task in tasks
                            if not task_executor.has_succeeded_today(task.name)
                            and not task_executor.is_in_failure_cooldown(task.name)
                            and not task_executor.is_recovery_blocked(task.name)
                        ]
                        if not pending:
                            continue
                        # Do not execute dependent tasks while an expensive
                        # prerequisite is in its recovery cooldown.  Without
                        # this guard, every 30-second watchdog tick records
                        # another skipped P0 morning brief/check-alerts entry
                        # and can contend with the scheduled pre-market phase.
                        pending_names = {task.name for task in pending}
                        blocked_by_cooldown = {
                            dependency
                            for task in pending
                            for dependency in task.depends_on
                            if dependency not in pending_names
                            and task_executor.is_in_failure_cooldown(dependency)
                        }
                        if blocked_by_cooldown:
                            logger.warning(
                                "[TaskExecutor] 恢复阶段等待失败冷却结束: phase=%s, blocked=%s",
                                phase.value,
                                sorted(blocked_by_cooldown),
                            )
                            continue
                        logger.warning(
                            "[TaskExecutor] 检测到漏跑阶段，开始补执行: phase=%s, pending=%s, trigger=%s",
                            phase.value,
                            [task.name for task in pending],
                            trigger_source,
                        )
                        await _execute_phase_tasks(phase, trigger_source=trigger_source)
                except Exception as exc:
                    logger.exception("[TaskExecutor] 漏跑阶段补偿失败: %s", exc)

            # 每日定时任务 - 直接传递async函数
            pre_market_time = PHASE_SCHEDULE_TIMES[SchedulePhase.PRE_MARKET]
            scheduler.add_job(
                _execute_phase_tasks,
                "cron",
                day_of_week="mon-fri",
                hour=pre_market_time.hour,
                minute=pre_market_time.minute,
                args=[SchedulePhase.PRE_MARKET],
                id="pre_market",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=30,
            )
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=9, minute=35,
                            args=[SchedulePhase.MARKET_OPEN], id="market_open", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=11, minute=30,
                            args=[SchedulePhase.MIDDAY], id="midday", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=13, minute=30,
                            args=[SchedulePhase.AFTERNOON], id="afternoon", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=14, minute=30,
                            args=[SchedulePhase.LATE_AFTERNOON], id="late_afternoon", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=15, minute=0,
                            args=[SchedulePhase.MARKET_CLOSE], id="market_close", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="mon-fri", hour=20, minute=0,
                            args=[SchedulePhase.EVENING], id="evening", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(
                _monitor_intraday_paper_opportunities,
                "interval",
                minutes=5,
                id="intraday_paper_monitor",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=30,
            )
            for hour, minute, checkpoint in HITHINK_CANARY_CHECKPOINTS:
                scheduler.add_job(
                    _run_hithink_canary_checkpoint,
                    "cron",
                    day_of_week="mon-fri",
                    hour=hour,
                    minute=minute,
                    args=[checkpoint],
                    id=f"hithink_canary_{hour:02d}{minute:02d}",
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=30,
                )
            scheduler.add_job(_execute_phase_tasks, "cron", day_of_week="sat", hour=10,
                            args=[SchedulePhase.WEEKLY], id="weekly", coalesce=True,
                            max_instances=1, misfire_grace_time=30)
            scheduler.add_job(_execute_phase_tasks, "cron", day=1, hour=9,
                            args=[SchedulePhase.MONTHLY], id="monthly", coalesce=True,
                            max_instances=1, misfire_grace_time=30)

            # Cron handles the normal path; this short watchdog handles a
            # process that starts after a checkpoint or is briefly restarted.
            scheduler.add_job(
                _recover_missed_phases,
                "interval",
                seconds=30,
                id="missed_phase_recovery",
                kwargs={"trigger_source": "scheduler_recovery"},
                coalesce=True,
                max_instances=1,
                # The recovery check is idempotent and re-evaluates the safe
                # window at execution time.  Match the 30-second cadence so a
                # short I/O pause does not create a misleading missed-tick
                # warning or suppress the next recovery check.
                misfire_grace_time=30,
            )

            scheduler.start()
            from src.api.routes.task_monitor_routes import update_scheduler_runtime
            update_scheduler_runtime(scheduler)
            logger.info(
                "[TaskExecutor] AI OS定时任务已注册(每日%s策略计划/开盘/午间/午盘/收盘/晚间)",
                pre_market_time.strftime("%H:%M"),
            )
            async def _delayed_startup_phase_recovery():
                # Let the API finish binding and answer health checks before
                # any potentially expensive recovery phase can start.
                await asyncio.sleep(10)
                await _recover_missed_phases()

            if not deployment_validation:
                asyncio.create_task(
                    _delayed_startup_phase_recovery(),
                    name="startup-phase-recovery",
                )
            else:
                logger.info("[startup] 部署验收期间跳过启动阶段恢复。")
            logger.info("[TaskExecutor] 已启用启动补偿与漏跑阶段监控(每30秒检查)")
            logger.info("[backfill] 决策回填定时任务已注册(每日 16:05)")
            logger.info("[research-backfill] 候选组件补采已注册(每日 20:30，断点恢复)")
            async def _delayed_research_data_recovery():
                # Avoid competing with initial API probes and route startup.
                # The backfill itself remains resumable and bounded.
                await asyncio.sleep(15)
                await _daily_research_data_backfill(include_current=False)

            if not deployment_validation:
                asyncio.create_task(
                    _delayed_research_data_recovery(),
                    name="research-data-backfill-startup-recovery",
                )
            else:
                logger.info("[startup] 部署验收期间跳过研究补采恢复。")
        except Exception as e:
            logger.warning("[backfill] 决策回填定时任务启动失败: %s", e)
            from src.api.routes.task_monitor_routes import update_scheduler_runtime
            update_scheduler_runtime(error=str(e)[:200])
    except Exception as e:
        logger.warning("[sync] 启动同步检查失败: %s", e)
    yield
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    try:
        from src.ai_os.task_executor import task_executor
        from src.api.routes.task_monitor_routes import update_scheduler_runtime
        task_executor.stop()
        update_scheduler_runtime(error="应用已停止")
    except Exception:
        pass


app = FastAPI(
    title="Adaptive Investment Intelligence Platform",
    version=system_routes.PRODUCT_VERSION,
    description="Adaptive Investment Intelligence Platform — REST API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(system_routes.router, prefix="/api/v1")
app.include_router(knowledge_routes.router, prefix="/api/v1")
app.include_router(wechat_routes.router, prefix="/api/v1")
app.include_router(signals_routes.router, prefix="/api/v1")
app.include_router(scanner_routes.router, prefix="/api/v1")
app.include_router(research_routes.router, prefix="/api/v1")
app.include_router(backtest_routes.router, prefix="/api/v1")
app.include_router(market_routes.router, prefix="/api/v1")
app.include_router(timeline_routes.router, prefix="/api/v1")
app.include_router(alerts_routes.router, prefix="/api/v1")
app.include_router(dailybrief_routes.router, prefix="/api/v1")
app.include_router(detail_routes.router, prefix="/api/v1")
app.include_router(explain_routes.router, prefix="/api/v1")
app.include_router(trust_routes.router, prefix="/api/v1")
app.include_router(user_routes.router, prefix="/api/v1")
app.include_router(ai_os_routes.router, prefix="/api/v1")
app.include_router(replay_routes.router, prefix="/api/v1")
app.include_router(knowledge_graph_routes.router, prefix="/api/v1")
app.include_router(decision_routes.router, prefix="/api/v1")
app.include_router(portfolio_mod.router, prefix="/api/v1")
app.include_router(morning_mod.router, prefix="/api/v1")
app.include_router(vibe_compat_routes.router, prefix="/api/v1")
app.include_router(unified_research_routes.router, prefix="/api/v1")
app.include_router(unified_research_routes.router, prefix="/api/v1/vibe")
app.include_router(task_monitor_routes.router, prefix="/api/v1")
