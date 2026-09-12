"use strict";
/** AI Operating System — real system heartbeat, learning state and events. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildAIOSPage = buildAIOSPage;
const layout_1 = require("../webview/layout");
function finiteNumber(value, fallback = 0) {
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}
function displayNumber(value, available) {
    if (!available || value === null || value === undefined || value === '')
        return '—';
    const parsed = Number(value);
    return Number.isFinite(parsed) ? String(parsed) : '—';
}
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function latestLearningProfile(entries) {
    for (const entry of entries) {
        const evidence = entry?.evidence || {};
        const profile = evidence.learning_profile || evidence.profile;
        if (profile && (profile.total_observations != null || profile.decisive_observations != null))
            return profile;
    }
    return {};
}
function buildAIOSPage(data) {
    const statusAvailable = data?.status != null;
    const todayAvailable = data?.todayMemory != null;
    const weekAvailable = data?.weeklyMemory != null;
    const learningAvailable = data?.learningLog != null;
    const eventsAvailable = data?.events != null;
    const status = data?.status || {};
    const today = data?.todayMemory || {};
    const week = data?.weeklyMemory || {};
    const learningEntries = Array.isArray(data?.learningLog?.learning_log) ? data.learningLog.learning_log : [];
    const events = Array.isArray(data?.events?.events) ? data.events.events : [];
    const progress = status.today_progress || {};
    const taskStats = Array.isArray(status?.executor?.task_stats) ? status.executor.task_stats : [];
    const failedTasks = statusAvailable ? taskStats.filter((task) => task.last_status === 'failed') : [];
    const learning = latestLearningProfile(learningEntries);
    const tradesToday = todayAvailable
        ? (today?.paper_portfolio?.trades || []).filter((trade) => trade.trade_date === today.date).length
        : null;
    const hasFailures = statusAvailable && finiteNumber(progress.failed) > 0;
    const heartbeatColor = !statusAvailable ? '#D2991D' : hasFailures ? '#F59E0B' : '#22C55E';
    const strategyVersion = statusAvailable
        ? String(status?.executor?.strategy_version || 'unknown')
        : '暂不可用';
    const statusTitle = !statusAvailable
        ? 'AI OS 状态暂不可用'
        : hasFailures ? 'AI OS 运行中 · 有任务待处理' : 'AI OS 运行正常';
    const errorMessage = data?.aiosError || data?.pageError;
    const errorHtml = errorMessage
        ? `<div class="card" style="border-left:3px solid #f85149">AI OS 接口异常：${escapeHtml(errorMessage)}</div>` : '';
    const learningMetric = (value) => {
        if (!learningAvailable)
            return '—';
        return value === null || value === undefined ? '样本积累中' : displayNumber(value, true);
    };
    const todayDecisionCount = todayAvailable
        ? displayNumber(progress.journal_decisions_today ?? today.recommendations_made, true)
        : '—';
    const todayAlerts = todayAvailable ? displayNumber(today.alerts_fired, true) : '—';
    const todayTrades = tradesToday === null ? '—' : String(tradesToday);
    const todayOutcomes = !todayAvailable
        ? '—'
        : today.outcomes_recorded === null || today.outcomes_recorded === undefined
            ? '待次日'
            : displayNumber(today.outcomes_recorded, true);
    const completion = statusAvailable
        ? displayNumber(progress.completion_pct, true) + '%'
        : '—';
    const content = `
<style>
.aios-page{padding:16px 24px}.aios-page .metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px}
.aios-page .two-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:16px}
.aios-page .metric{text-align:center;padding:10px;min-width:0}.aios-page .metric-value-sm{font-size:22px;font-weight:700;line-height:1.2;overflow-wrap:anywhere}
.aios-page .learning-row{padding:8px 0;border-bottom:1px solid #21262d}.aios-page .learning-meta{font-size:10px;color:#6B7280;margin-bottom:3px}
@media(max-width:520px){.aios-page{padding:12px}.aios-page .two-columns{grid-template-columns:1fr}}
</style>
<div class="aios-page">
${errorHtml}
<div class="card" style="border-left:3px solid ${heartbeatColor};background:linear-gradient(135deg,#0a1a0a 0%,#161b22 100%)">
<div class="flex-between" style="gap:16px;flex-wrap:wrap"><div class="flex-row gap-8"><span class="pulse" style="color:${heartbeatColor};font-size:16px">●</span><div><div style="font-size:16px;font-weight:700;color:${heartbeatColor}">${statusTitle}</div><div style="font-size:12px;color:#8b949e">当前阶段: ${escapeHtml(statusAvailable ? (status.phase_label || '未知') : '暂不可用')} · 已完成 ${statusAvailable ? displayNumber(progress.completed, true) : '—'}/${statusAvailable ? displayNumber(progress.total_tasks, true) : '—'} 项任务</div><div style="font-size:10px;color:#6B7280;margin-top:3px">策略版本: ${escapeHtml(strategyVersion)}</div></div></div><div style="text-align:right"><div style="font-size:24px;font-weight:700;color:#58a6ff">${completion}</div><div style="font-size:11px;color:#8b949e">今日完成度</div></div></div>
${failedTasks.length ? `<div style="margin-top:10px;padding:8px;background:#3a351b;border-radius:6px;font-size:12px;color:#F59E0B">待处理任务：${failedTasks.map((task) => `${escapeHtml(task.task_name)}（最近状态失败）`).join('、')}</div>` : ''}
</div>

<div class="card"><div class="card-header"><h3>📅 今日运行 · ${escapeHtml(todayAvailable ? (today.date || '日期未知') : '接口暂不可用')}</h3><button class="btn btn-sm" onclick="refreshAIOS()">刷新</button></div>
<div class="metric-grid">
<div class="metric"><div class="metric-value-sm" style="color:#58a6ff">${todayDecisionCount}</div><div class="text-sm text-muted">今日决策</div></div>
<div class="metric"><div class="metric-value-sm" style="color:#F59E0B">${todayAlerts}</div><div class="text-sm text-muted">关注信号</div></div>
<div class="metric"><div class="metric-value-sm" style="color:#A78BFA">${todayTrades}</div><div class="text-sm text-muted">自动模拟成交</div></div>
<div class="metric"><div class="metric-value-sm" style="color:#22C55E">${todayOutcomes}</div><div class="text-sm text-muted">结果回写</div></div>
</div>
${todayAvailable && today.daily_summary ? `<div style="margin-top:10px;padding:10px;background:#0B1220;border-radius:6px;font-size:12px;line-height:1.5">📝 ${escapeHtml(today.daily_summary)}</div>` : ''}
${todayAvailable && today.tomorrow_preview ? `<div style="margin-top:6px;font-size:12px;color:#8b949e">🔮 ${escapeHtml(today.tomorrow_preview)}</div>` : ''}
</div>

<div class="two-columns">
<div class="card"><div class="card-header"><h3>📊 市场学习样本</h3><span class="text-sm text-muted">不是用户画像样本</span></div>
<div class="flex-between" style="padding:5px 0"><span class="text-sm text-muted">市场观察</span><span style="font-weight:600">${learningMetric(learning.total_observations)}</span></div>
<div class="flex-between" style="padding:5px 0"><span class="text-sm text-muted">明确 BUY/SELL</span><span style="font-weight:600">${learningMetric(learning.decisive_observations)}</span></div>
<div class="flex-between" style="padding:5px 0"><span class="text-sm text-muted">已学习股票</span><span style="font-weight:600">${learningAvailable ? (learning.learned_symbols != null ? displayNumber(learning.learned_symbols, true) : Object.keys(learning.by_symbol || {}).length) : '—'}</span></div>
<div class="flex-between" style="padding:5px 0"><span class="text-sm text-muted">已学习来源</span><span style="font-weight:600">${learningAvailable ? (learning.learned_sources != null ? displayNumber(learning.learned_sources, true) : Object.keys(learning.by_source || {}).length) : '—'}</span></div>
<div style="margin-top:8px;padding:8px;background:#0B1220;border-radius:6px;font-size:12px;color:#8b949e">${escapeHtml(weekAvailable ? (week.summary || '周度汇总尚未生成') : '周度记忆接口暂不可用；历史数据未删除。')}</div></div>

<div class="card"><div class="card-header"><h3>🧠 AI 学习日志</h3><span class="text-sm text-muted">最近 ${learningAvailable ? Math.min(8, learningEntries.length) : '—'} 条</span></div>
${learningAvailable ? (learningEntries.slice(0, 8).map((entry) => `<div class="learning-row"><div class="learning-meta">${escapeHtml(entry.learning_date || '')} · ${escapeHtml(entry.category || 'learning')}</div><div style="font-size:12px;color:#c9d1d9;line-height:1.5">${escapeHtml(entry.lesson || entry)}</div></div>`).join('') || '<div class="empty-state"><p>学习日志尚未生成</p></div>') : '<div class="empty-state"><p>学习日志接口暂不可用，历史记录未删除</p></div>'}
</div></div>

<div class="card" style="margin-top:16px"><div class="card-header"><h3>📡 决策时间线</h3><span class="text-sm text-muted">最近 ${eventsAvailable ? events.length : '—'} 条</span></div><div style="max-height:400px;overflow-y:auto">${eventsAvailable ? (events.map(renderEventRow).join('') || '<div class="empty-state"><p>暂无事件</p></div>') : '<div class="empty-state"><p>决策事件接口暂不可用，历史记录未删除</p></div>'}</div></div>
</div>`;
    return (0, layout_1.pageShell)('aios', 'AI OS · 系统运行', content, `function refreshAIOS(){vscode.postMessage({command:'refreshPage'});}`);
}
function renderEventRow(event) {
    const sourceIcons = { decision_journal: '📈', market: '📈', scanner: '🔍', alert: '🔔', portfolio: '📦', research: '🔬', user: '👤', trust: '🤖', ai_os: '⚙', system: '🖥' };
    const icon = sourceIcons[event?.source] || '•';
    const timestamp = String(event?.timestamp || event?.ts || '');
    return `<div style="display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:1px solid #21262d;font-size:12px"><span style="color:#6B7280;font-family:monospace;white-space:nowrap;min-width:48px">${escapeHtml(timestamp.slice(11, 19))}</span><span style="min-width:20px;text-align:center">${icon}</span><span style="flex:1;color:#c9d1d9">${escapeHtml(event?.summary)}</span>${event?.related_stock ? `<span class="stock-code">${escapeHtml(event.related_stock)}</span>` : ''}</div>`;
}
//# sourceMappingURL=aios.js.map