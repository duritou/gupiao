/** Task Monitor — 任务执行监控面板 */

import { pageShell } from '../webview/layout';

export function buildTaskMonitorPage(data: any): string {
    const status = data.status || {};
    const executions = data.executions || [];
    const schedule = data.schedule || {};

    const isRunning = status.is_running || false;
    const taskStats = status.task_stats || [];
    const currentPhase = schedule.current_phase || 'unknown';
    const scheduler = status.scheduler || {};
    const schedulerJobs = scheduler.jobs || [];
    const allTasks = schedule.all_tasks || [];

    const phaseLabels: Record<string, string> = {
        'pre_market': '每日策略计划 (01:00)',
        'market_open': '开盘监控 (09:35)',
        'midday': '午间检查 (11:30)',
        'afternoon': '午盘扫描 (14:30)',
        'market_close': '收盘处理 (15:00)',
        'evening': '晚间复盘 (20:00)',
        'weekly': '周度复盘',
        'monthly': '月度复盘',
    };

    const content = `
<!-- 执行器状态 -->
<div style="padding:16px 24px 0">
<div class="card" style="border-left:3px solid ${isRunning ? '#22C55E' : '#8b949e'}">
<div class="flex-between">
<div class="flex-row gap-8">
<span class="pulse" style="color:${isRunning ? '#22C55E' : '#8b949e'};font-size:16px">●</span>
<div>
<div style="font-size:16px;font-weight:700;color:${isRunning ? '#22C55E' : '#8b949e'}">
任务执行器${isRunning ? '运行中' : '已停止'}
</div>
<div style="font-size:12px;color:#8b949e">
当前时段: ${phaseLabels[currentPhase] || currentPhase} · 已执行 ${status.total_executions || 0} 次 · 策略 ${status.strategy_version || 'unknown'}
· 历史记录${status.persistence_enabled ? '已持久化' : '仅内存'}
</div>
</div>
</div>
</div>
</div></div>

<!-- APScheduler真实状态 -->
<div style="padding:16px 24px 0">
<div class="card" style="border-left:3px solid ${scheduler.running ? '#22C55E' : '#EF4444'}">
<div class="card-header"><h3>⏱ 调度器${scheduler.running ? '运行中' : '未运行'}</h3><button class="btn" onclick="refreshTasks()">刷新</button></div>
${scheduler.error ? `<div style="font-size:12px;color:#EF4444;margin-bottom:8px">${scheduler.error}</div>` : ''}
${schedulerJobs.length ? schedulerJobs.map((job: any) => `
<div class="flex-between" style="padding:6px 0;border-bottom:1px solid #21262d;font-size:12px">
<span>${job.id}</span><span class="text-muted">${job.next_run_at ? new Date(job.next_run_at).toLocaleString('zh-CN') : '无下次运行时间'}</span>
</div>`).join('') : '<div class="text-muted">没有已注册的调度任务</div>'}
</div></div>

<!-- 手动验证 -->
<div style="padding:16px 24px 0">
<div class="card"><div class="card-header"><h3>🧪 手动验证任务</h3></div>
<div class="flex-row gap-8" style="flex-wrap:wrap">
${allTasks.map((task: any) => `<button class="btn" onclick="executeTask('${task.name}')" title="${task.description || ''}">${task.name}</button>`).join('')}
</div></div></div>

<!-- 任务统计 -->
<div style="padding:16px 24px 0">
<div class="card">
<div class="card-header"><h3>📊 任务统计</h3></div>
<div style="max-height:400px;overflow-y:auto">
${taskStats.length > 0 ? taskStats.map((t: any) => `
<div style="padding:12px;margin:8px 0;background:#0B1220;border-radius:6px;border-left:3px solid ${t.last_status === 'success' ? '#22C55E' : t.last_status === 'failed' ? '#EF4444' : '#8b949e'}">
<div class="flex-between">
<div style="flex:1">
<div style="font-weight:600;color:#c9d1d9">${t.task_name}</div>
<div style="font-size:11px;color:#8b949e;margin-top:4px">
最后运行: ${t.last_run_at ? new Date(t.last_run_at).toLocaleString('zh-CN') : '未运行'}
</div>
</div>
<div style="text-align:right">
<div style="font-size:20px;font-weight:700;color:#58a6ff">${t.total_runs || 0}</div>
<div style="font-size:11px;color:#8b949e">总次数</div>
</div>
</div>
<div class="flex-row gap-16" style="margin-top:8px;font-size:12px">
<span style="color:#22C55E">✓ ${t.success_count || 0}</span>
<span style="color:#EF4444">✗ ${t.failed_count || 0}</span>
<span style="color:#8b949e">成功率 ${t.success_rate || 0}%</span>
<span style="color:#8b949e">平均 ${t.avg_duration_seconds || 0}s</span>
${t.next_scheduled_at ? `<span style="color:#F59E0B">下次: ${new Date(t.next_scheduled_at).toLocaleString('zh-CN')}</span>` : ''}
</div>
</div>
`).join('') : '<div class="empty-state"><p>暂无任务统计</p></div>'}
</div>
</div></div>

<!-- 最近执行记录 -->
<div style="padding:16px 24px 24px">
<div class="card">
<div class="card-header"><h3>📝 最近执行记录</h3></div>
<div style="max-height:400px;overflow-y:auto">
${executions.length > 0 ? executions.map((e: any) => `
<div style="padding:10px;margin:6px 0;background:#0B1220;border-radius:4px;font-size:12px">
<div class="flex-between">
<span style="font-weight:600;color:#c9d1d9">${e.task_name}</span>
<span class="badge badge-${e.status === 'success' ? 'success' : e.status === 'failed' ? 'danger' : 'default'}">${e.status}</span>
</div>
<div style="color:#8b949e;margin-top:4px">
${new Date(e.started_at).toLocaleString('zh-CN')} · 耗时 ${e.duration_seconds}s
</div>
<div style="color:#6B7280;margin-top:3px;font-size:10px">阶段: ${e.output?.stage_status || e.status} · 幂等键: ${e.output?.execution_key || '历史记录无'}</div>
${e.error ? `<div style="color:#EF4444;margin-top:4px;font-size:11px">${e.error}</div>` : ''}
</div>
`).join('') : '<div class="empty-state"><p>暂无执行记录</p></div>'}
</div>
</div></div>
`;

    const extraScript = `
function refreshTasks() { vscode.postMessage({command:'refreshPage'}); }
function executeTask(name) { vscode.postMessage({command:'executeTask',taskName:name}); }
let taskMonitorInterval = setInterval(refreshTasks, 30000);
document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearInterval(taskMonitorInterval);
    else { clearInterval(taskMonitorInterval); taskMonitorInterval = setInterval(refreshTasks, 30000); }
});`;

    return pageShell('taskmonitor', 'Task Monitor · 任务监控', content, extraScript);
}
