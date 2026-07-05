"use strict";
/** Decision Center v8.0 — "What should I do today?" */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildDecisionsPage = buildDecisionsPage;
const layout_1 = require("../webview/layout");
function buildDecisionsPage(data) {
    const decisionsData = data.decisions || {};
    const decisions = decisionsData.decisions || [];
    const urgentCount = decisionsData.urgent_count || 0;
    const recLabels = {
        buy: '买入', add: '加仓', hold: '继续持有', watch: '观察',
        reduce: '减仓', sell: '卖出', monitor: '关注',
    };
    const recColors = {
        buy: '#22C55E', add: '#22C55E', hold: '#58a6ff', watch: '#F59E0B',
        reduce: '#EF4444', sell: '#EF4444', monitor: '#8b949e',
    };
    const content = `
<!-- Header -->
<div style="text-align:center;padding:24px 24px 0">
<div style="font-size:36px;margin-bottom:8px">🎯</div>
<h1 style="font-size:20px;color:#58a6ff">Decision Center</h1>
<div style="font-size:12px;color:#8b949e;margin-top:4px">${decisionsData.summary || ''}</div>
<div style="font-size:12px;margin-top:4px">
${urgentCount > 0
        ? `<span style="color:#EF4444;font-weight:600">🔴 ${urgentCount}条紧急</span>`
        : '<span style="color:#22C55E">🟢 暂无紧急操作</span>'}
</div>
</div>

<!-- Decision List -->
<div style="padding:16px 24px">
${decisions.map((d) => _renderDecisionCard(d, recLabels, recColors)).join('')}
</div>`;
    return (0, layout_1.pageShell)('decisions', 'Decision Center · 决策中心', content, '');
}
function _renderDecisionCard(d, labels, colors) {
    const color = colors[d.recommendation] || '#8b949e';
    const urgencyColors = { today: '#EF4444', this_week: '#F59E0B', monitor: '#8b949e' };
    return `
<div class="card" style="border-left:3px solid ${color};margin-bottom:12px" onclick="${d.stock_code ? `analyzeStock('${d.stock_code}')` : ''}">
<!-- Header: Rank + Name + Score + Action -->
<div class="flex-between" style="margin-bottom:10px">
<div class="flex-row gap-12">
<span style="font-size:11px;color:#6B7280;font-family:monospace">#${d.rank}</span>
<span style="font-weight:600;font-size:15px">${d.stock_name}</span>
<span class="stock-code">${d.stock_code}</span>
${d.user_has_position ? '<span style="font-size:10px;background:#1b2d3a;color:#58a6ff;padding:1px 6px;border-radius:8px">已持仓</span>' : ''}
${d.user_past_trades > 0 ? `<span style="font-size:10px;color:#8b949e">${d.user_past_trades}次交易</span>` : ''}
</div>
<div class="flex-row gap-8">
<span style="font-size:10px;color:${urgencyColors[d.urgency]};border:1px solid ${urgencyColors[d.urgency]};padding:1px 6px;border-radius:8px">${d.urgency === 'today' ? '今日' : d.urgency === 'this_week' ? '本周' : '关注'}</span>
<div style="text-align:right">
<div style="font-size:22px;font-weight:700;color:${color}">${(d.ai_score || 50).toFixed(0)}</div>
<div style="font-size:10px;color:${color}">${labels[d.recommendation] || d.recommendation}</div>
</div>
</div>
</div>

<!-- Bull vs Bear -->
<div class="grid2" style="margin-bottom:8px">
<!-- Bull -->
<div style="background:#0B1220;border:1px solid #1F2937;border-radius:6px;padding:8px 10px">
<div style="font-size:10px;color:#22C55E;text-transform:uppercase;margin-bottom:4px">✅ Bull Case (${(d.bull_score || 0).toFixed(0)})</div>
${(d.bull_points || []).slice(0, 3).map((b) => `
<div style="font-size:11px;color:#c9d1d9;margin-bottom:3px;line-height:1.4">
<span style="color:#22C55E">✓</span> ${b.point}
<span style="font-size:9px;color:#6B7280;display:block">来源: ${b.source}</span>
</div>`).join('') || '<div class="text-sm text-muted">—</div>'}
</div>
<!-- Bear -->
<div style="background:#0B1220;border:1px solid #1F2937;border-radius:6px;padding:8px 10px">
<div style="font-size:10px;color:#EF4444;text-transform:uppercase;margin-bottom:4px">⚠ Bear Case (${(d.bear_score || 0).toFixed(0)})</div>
${(d.bear_points || []).slice(0, 3).map((b) => `
<div style="font-size:11px;color:#c9d1d9;margin-bottom:3px;line-height:1.4">
<span style="color:#EF4444">✗</span> ${b.point}
<span style="font-size:9px;color:#6B7280;display:block">来源: ${b.source}</span>
</div>`).join('') || '<div class="text-sm text-muted">—</div>'}
</div>
</div>

<!-- Net Score Bar -->
<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
<div style="flex:1;height:4px;background:#21262d;border-radius:2px;overflow:hidden;display:flex">
<div style="height:4px;width:${Math.max(5, (d.bull_score || 0) / Math.max(d.bull_score + d.bear_score, 1) * 100)}%;background:#22C55E"></div>
<div style="height:4px;width:${Math.max(5, (d.bear_score || 0) / Math.max(d.bull_score + d.bear_score, 1) * 100)}%;background:#EF4444"></div>
</div>
<span style="font-size:10px;color:#8b949e">Bull ${(d.bull_score || 0).toFixed(0)} / Bear ${(d.bear_score || 0).toFixed(0)}</span>
</div>

<!-- Personal Note -->
${d.personal_note ? `
<div style="font-size:11px;color:#A78BFA;background:#1A1030;padding:8px;border-radius:6px;margin-bottom:4px">
🧠 ${d.personal_note}
${d.user_win_rate > 0 ? ` <span style="color:#8B5CF6">胜率 ${(d.user_win_rate * 100).toFixed(0)}%</span>` : ''}
</div>` : ''}

<!-- Primary Reason -->
<div style="font-size:11px;color:#8b949e;display:flex;justify-content:space-between">
<span>${d.primary_reason || ''}</span>
<span>${d.evidence_count}条证据</span>
</div>
</div>`;
}
//# sourceMappingURL=decisions.js.map