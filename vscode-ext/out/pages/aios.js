"use strict";
/** AI Operating System v7.0 — system heartbeat, event timeline, AI memory. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildAIOSPage = buildAIOSPage;
const layout_1 = require("../webview/layout");
function buildAIOSPage(data) {
    const status = data.status || {};
    const todayMemory = data.todayMemory || {};
    const weeklyMemory = data.weeklyMemory || {};
    const learningLog = data.learningLog?.learning_log || [];
    const events = data.events?.events || [];
    const phaseLabel = status.phase_label || '运行中';
    const progress = status.today_progress || {};
    const content = `
<!-- System Heartbeat -->
<div style="padding:16px 24px 0">
<div class="card" style="border-left:3px solid #22C55E;background:linear-gradient(135deg,#0a1a0a 0%,#161b22 100%)">
<div class="flex-between">
<div class="flex-row gap-8">
<span class="pulse" style="color:#22C55E;font-size:16px">●</span>
<div>
<div style="font-size:16px;font-weight:700;color:#22C55E">AI OS 运行中</div>
<div style="font-size:12px;color:#8b949e">当前阶段: ${phaseLabel} · 已完成 ${progress.completed || 0}/${progress.total_tasks || 0} 项任务</div>
</div>
</div>
<div style="text-align:right">
<div style="font-size:24px;font-weight:700;color:#58a6ff">${progress.completion_pct || 0}%</div>
<div style="font-size:11px;color:#8b949e">今日完成度</div>
</div>
</div>
</div></div>

<!-- Today's AI Memory -->
<div style="padding:16px 24px 0">
<div class="card">
<div class="card-header"><h3>📅 今日记忆 · ${todayMemory.date || ''}</h3><span class="text-sm text-muted">${todayMemory.day_of_week || ''}</span></div>
<div class="grid4" style="padding:0">
<div style="text-align:center;padding:8px">
<div style="font-size:20px;font-weight:700;color:#58a6ff">${todayMemory.total_events || 0}</div>
<div class="text-sm text-muted">事件</div>
</div>
<div style="text-align:center;padding:8px">
<div style="font-size:20px;font-weight:700;color:#22C55E">${todayMemory.recommendations_made || 0}</div>
<div class="text-sm text-muted">推荐</div>
</div>
<div style="text-align:center;padding:8px">
<div style="font-size:20px;font-weight:700;color:#F59E0B">${todayMemory.alerts_fired || 0}</div>
<div class="text-sm text-muted">预警</div>
</div>
<div style="text-align:center;padding:8px">
<div style="font-size:20px;font-weight:700;color:#A78BFA">${todayMemory.user_actions || 0}</div>
<div class="text-sm text-muted">用户操作</div>
</div>
</div>
${todayMemory.daily_summary ? `
<div style="margin-top:8px;padding:10px;background:#0B1220;border-radius:6px;font-size:12px;color:#c9d1d9;line-height:1.5">📝 ${todayMemory.daily_summary}</div>` : ''}
${todayMemory.lessons_learned ? `
<div style="margin-top:4px;padding:10px;background:#0B1220;border-radius:6px;font-size:12px;color:#F59E0B;line-height:1.5">💡 ${todayMemory.lessons_learned}</div>` : ''}
${todayMemory.tomorrow_preview ? `
<div style="margin-top:4px;font-size:12px;color:#8b949e">🔮 ${todayMemory.tomorrow_preview}</div>` : ''}
</div></div>

<!-- Weekly Review -->
<div class="grid2" style="padding:0 24px">
<div class="card">
<div class="card-header"><h3>📊 本周回顾</h3><span class="text-sm text-muted">${weeklyMemory.week_start || ''} → ${weeklyMemory.week_end || ''}</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">推荐数</span><span style="font-weight:600">${weeklyMemory.total_recommendations || 0}</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">正确率</span><span style="font-weight:600;color:#22C55E">${((weeklyMemory.accuracy || 0) * 100).toFixed(0)}%</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">AI Alpha</span><span style="font-weight:600;color:#22C55E">${(weeklyMemory.ai_alpha_pct || 0) >= 0 ? '+' : ''}${(weeklyMemory.ai_alpha_pct || 0).toFixed(1)}%</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">最佳策略</span><span style="font-weight:600">${weeklyMemory.top_performing_strategy || '--'}</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">最佳行业</span><span style="font-weight:600;color:#22C55E">${weeklyMemory.best_sector || '--'}</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">最差策略</span><span style="font-weight:600;color:#EF4444">${weeklyMemory.worst_performing_strategy || '--'}</span></div>
${weeklyMemory.weekly_summary ? `
<div style="margin-top:8px;padding:8px;background:#0B1220;border-radius:6px;font-size:12px;color:#c9d1d9;line-height:1.5">${weeklyMemory.weekly_summary}</div>` : ''}
</div>
<div class="card">
<div class="card-header"><h3>🧠 AI 学习日志</h3></div>
${learningLog.length > 0 ? learningLog.slice(0, 8).map((l) => `
<div style="padding:6px 0;border-bottom:1px solid #21262d;font-size:12px;color:#c9d1d9;line-height:1.5">${l}</div>`).join('') : '<div class="empty-state"><p>数据积累中</p></div>'}
${weeklyMemory.user_behavior_change ? `
<div style="margin-top:8px;padding:8px;background:#1b1d3a;border-radius:6px;font-size:12px;color:#A78BFA">👤 ${weeklyMemory.user_behavior_change}</div>` : ''}
${weeklyMemory.ai_improvement ? `
<div style="margin-top:4px;padding:8px;background:#1b1d3a;border-radius:6px;font-size:12px;color:#A78BFA">🤖 ${weeklyMemory.ai_improvement}</div>` : ''}
</div>
</div>

<!-- Event Timeline -->
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>📡 事件时间线</h3><span class="text-sm text-muted">最近事件</span></div>
<div style="max-height:400px;overflow-y:auto">
${events.map((e) => _renderEventRow(e)).join('') || '<div class="empty-state"><p>暂无事件</p></div>'}
</div>
</div></div>
`;
    return (0, layout_1.pageShell)('aios', 'AI OS · 系统运行', content, '');
}
function _renderEventRow(e) {
    const sourceIcons = {
        market: '📈', scanner: '🔍', alert: '🔔', portfolio: '📦',
        research: '🔬', user: '👤', trust: '🤖', ai_os: '⚙', system: '🖥',
    };
    const icon = sourceIcons[e.source] || '•';
    const time = (e.timestamp || '').slice(11, 19) || '';
    return `
<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;border-bottom:1px solid #21262d;font-size:12px">
<span style="color:#6B7280;font-family:monospace;white-space:nowrap;min-width:48px">${time}</span>
<span style="min-width:20px;text-align:center">${icon}</span>
<span style="flex:1;color:#c9d1d9">${e.summary || ''}</span>
${e.related_stock ? `<span class="stock-code">${e.related_stock}</span>` : ''}
</div>`;
}
//# sourceMappingURL=aios.js.map