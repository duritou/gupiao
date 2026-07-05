/** Alert Intelligence Center v4.2 — P0-P4 levels, evidence, lifecycle management. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildAlertsPage(data: any): string {
    const alertsData = data.alerts || {};
    const alerts = alertsData.alerts || [];
    const unread = alertsData.unread || 0;
    const urgentCount = alertsData.urgent_summary?.urgent_count || 0;

    const levelFilters = [
        { label: '全部', level: '' },
        { label: `🔴 P0 紧急`, level: 'P0' },
        { label: `🟢 P1 重要`, level: 'P1' },
        { label: 'P2 持仓', level: 'P2' },
        { label: 'P3 市场', level: 'P3' },
        { label: 'P4 信息', level: 'P4' },
    ];

    const statusFilters = [
        { label: '全部', status: '' },
        { label: '未读', status: 'new' },
        { label: '已读', status: 'read' },
        { label: '已操作', status: 'acted' },
    ];

    const content = `
<div class="flex-between p-24" style="padding-bottom:0">
<div class="flex-row gap-8">
    <span class="pulse" style="color:#3fb950;font-size:14px">● AI 实时监控中</span>
    ${unread > 0
        ? `<span style="background:#3a1b1b;color:#f85149;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600">${unread}条未读</span>`
        : '<span class="text-sm text-muted">全部已读</span>'}
    ${urgentCount > 0
        ? `<span style="background:#3a351b;color:#F59E0B;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600">${urgentCount}条紧急</span>`
        : ''}
</div>
</div>

<!-- Level Filter Bar -->
<div style="padding:8px 24px;display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #21262d">
${levelFilters.map(f => `<button class="btn btn-sm level-filter-btn" data-level="${f.level}" onclick="filterByLevel('${f.level}')">${f.label}</button>`).join('')}
</div>

<!-- Status Filter Bar -->
<div style="padding:4px 24px;display:flex;gap:4px;flex-wrap:wrap">
${statusFilters.map(f => `<button class="btn btn-sm status-filter-btn" data-status="${f.status}" onclick="filterByStatus('${f.status}')">${f.label}</button>`).join('')}
</div>

<!-- Alert Feed -->
<div style="padding:16px 24px">
<div id="alertsFeed">
${alerts.map((a: any) => _renderAlertCard(a)).join('') || '<div class="empty-state"><div class="icon">🔔</div><p>暂无预警 · AI持续监控中</p></div>'}
</div>
<div style="text-align:center;padding:16px" class="text-muted text-sm">
🔄 每30秒自动刷新 · 最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>
</div>`;

    const extraScript = `
let alertInterval;
let currentLevel = '';
let currentStatus = '';

async function refreshAlerts() {
    try {
        let url = '${BASE_URL}/alerts?limit=50';
        if (currentLevel) url += '&level=' + currentLevel;
        if (currentStatus) url += '&status=' + currentStatus;
        const resp = await fetch(url);
        const data = await resp.json();
        const feedEl = document.getElementById('alertsFeed');
        if (feedEl && data.alerts) {
            feedEl.innerHTML = data.alerts.map(a => renderAlertCard(a)).join('') || '<div class="empty-state"><div class="icon">🔔</div><p>暂无匹配预警</p></div>';
        }
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) {}
}

function filterByLevel(level) {
    currentLevel = level;
    document.querySelectorAll('.level-filter-btn').forEach(b => {
        b.style.background = b.dataset.level === level ? '#30363d' : '#21262d';
        b.style.borderColor = b.dataset.level === level ? '#58a6ff' : '#30363d';
    });
    refreshAlerts();
}

function filterByStatus(status) {
    currentStatus = status;
    document.querySelectorAll('.status-filter-btn').forEach(b => {
        b.style.background = b.dataset.status === status ? '#30363d' : '#21262d';
        b.style.borderColor = b.dataset.status === status ? '#58a6ff' : '#30363d';
    });
    refreshAlerts();
}

async function markRead(alertId) {
    try {
        await fetch('${BASE_URL}/alerts/' + alertId + '/read', { method: 'POST' });
        refreshAlerts();
    } catch(e) {}
}

async function dismissAlert(alertId) {
    try {
        await fetch('${BASE_URL}/alerts/' + alertId + '/dismiss', { method: 'POST' });
        refreshAlerts();
    } catch(e) {}
}

async function recordAction(alertId, actionType, stockCode) {
    try {
        await fetch('${BASE_URL}/alerts/' + alertId + '/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action_type: actionType, stock_code: stockCode, notes: '' })
        });
        refreshAlerts();
    } catch(e) {}
}

function startAutoRefresh() {
    refreshAlerts();
    alertInterval = setInterval(refreshAlerts, 30000);
}
function stopAutoRefresh() { clearInterval(alertInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();

// Embed render function for dynamic refresh
function renderAlertCard(a) {
    return ${'_renderAlertCardJS'}(a);
}`;

    return pageShell('alerts', 'Alert Intelligence · 智能预警中心', content, extraScript);
}

/** Render a single alert card with level, evidence, lifecycle actions. */
function _renderAlertCard(a: any): string {
    const levelColorMap: Record<string, string> = {
        P0: '#EF4444', P1: '#F59E0B', P2: '#8B5CF6', P3: '#58a6ff', P4: '#6B7280',
    };
    const levelBgMap: Record<string, string> = {
        P0: '#3a1b1b', P1: '#3a351b', P2: '#1b1d3a', P3: '#1b2d3a', P4: '#21262d',
    };
    const levelColor = levelColorMap[a.level] || '#6B7280';
    const levelBg = levelBgMap[a.level] || '#21262d';
    const categoryIcon: Record<string, string> = {
        signal: '📊', portfolio: '📦', market: '📈', knowledge: '📚', risk: '⚠', opportunity: '🔥',
    };
    const icon = categoryIcon[a.category] || '🔔';

    const clickAction = a.stock_code ? `onclick="analyzeStock('${a.stock_code}')"` : '';
    const isNew = a.status === 'new';

    return `
<div class="evidence-card" style="cursor:${a.stock_code ? 'pointer' : 'default'};border-left:3px solid ${levelColor};${isNew ? 'background:#1a1c20;' : ''}" ${clickAction}>
<div class="flex-between" style="margin-bottom:4px">
<div class="flex-row gap-8">
    <span style="display:inline-block;padding:2px 8px;border-radius:3px;background:${levelBg};color:${levelColor};font-size:11px;font-weight:700;font-family:monospace">${a.level}</span>
    <span style="font-size:11px;color:#8b949e">${icon} ${_levelCategoryLabel(a)}</span>
    ${a.stock_code ? `<span class="stock-code">${a.stock_code}</span>` : ''}
    ${a.stock_name ? `<span style="font-weight:600;font-size:13px">${a.stock_name}</span>` : ''}
</div>
<div class="flex-row gap-8">
    <span style="font-size:11px;color:#6B7280">${_formatTime(a.created_at)}</span>
    ${isNew ? '<span style="color:#58a6ff;font-size:11px;animation:pulse 2s infinite">● NEW</span>' : ''}
    ${a.status === 'read' ? '<span style="color:#6B7280;font-size:11px">✓ 已读</span>' : ''}
    ${a.status === 'acted' ? '<span style="color:#22C55E;font-size:11px">✓ 已操作</span>' : ''}
</div>
</div>

<div style="font-size:14px;font-weight:600;margin-bottom:4px;color:#E5E7EB">${a.title}</div>
${a.body ? `<div style="font-size:12px;color:#9CA3AF;margin-bottom:6px;line-height:1.5">${a.body}</div>` : ''}

<!-- Evidence Chain -->
${a.evidence && a.evidence.length > 0 ? `
<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px">
${a.evidence.slice(0, 4).map((e: any) => `
<div style="flex:1;min-width:120px;background:#0B1220;border:1px solid #1F2937;border-radius:6px;padding:6px 8px">
<div style="font-size:11px;font-weight:600;color:#E5E7EB">✓ ${e.title}</div>
<div style="font-size:10px;color:#9CA3AF;margin-top:2px">${e.description}</div>
<div style="display:flex;justify-content:space-between;margin-top:4px">
<span style="font-size:9px;color:#6B7280">${e.source || ''}</span>
<span style="font-size:10px;font-family:monospace;color:${e.confidence >= 0.8 ? '#22C55E' : e.confidence >= 0.6 ? '#F59E0B' : '#6B7280'}">${(e.confidence * 100).toFixed(0)}%</span>
</div>
</div>`).join('')}
</div>` : ''}

<!-- Stats & Actions Row -->
<div class="flex-between" style="margin-top:4px">
<div class="flex-row gap-12">
${a.ai_confidence ? `<span style="font-size:11px;color:#8b949e">AI置信度 <b style="color:${a.ai_confidence >= 0.8 ? '#22C55E' : '#8b949e'}">${(a.ai_confidence * 100).toFixed(0)}%</b></span>` : ''}
${a.historical_accuracy ? `<span style="font-size:11px;color:#8b949e">历史准确 <b>${(a.historical_accuracy * 100).toFixed(0)}%</b></span>` : ''}
${a.score_change ? `<span style="font-size:11px;color:${a.score_change >= 0 ? '#22C55E' : '#EF4444'}">${a.score_change >= 0 ? '▲' : '▼'}${Math.abs(a.score_change).toFixed(0)}</span>` : ''}
${a.tags ? a.tags.slice(0, 3).map((t: string) => `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:#21262d;color:#8b949e">${t}</span>`).join('') : ''}
</div>
<div class="flex-row gap-4">
${a.stock_code ? `<button class="btn btn-sm" onclick="event.stopPropagation();analyzeStock('${a.stock_code}')">研究</button>` : ''}
${a.status === 'new' ? `<button class="btn btn-sm" onclick="event.stopPropagation();markRead('${a.id}')">已读</button>` : ''}
${a.status !== 'acted' && a.status !== 'dismissed' ? `<button class="btn btn-sm" onclick="event.stopPropagation();dismissAlert('${a.id}')">忽略</button>` : ''}
</div>
</div>
</div>`;
}

/** Render function embedded in webview JS for dynamic refresh. */
const _renderAlertCardJS = _renderAlertCard.toString();

function _levelCategoryLabel(a: any): string {
    const labels: Record<string, Record<string, string>> = {
        P0: { risk: '紧急风险', signal: '紧急信号', portfolio: '紧急持仓' },
        P1: { opportunity: '强烈机会', risk: '重要风险', signal: '重要信号' },
        P2: { portfolio: '持仓变化', signal: '技术信号', risk: '组合风险' },
        P3: { market: '市场事件', knowledge: '行业情报' },
        P4: { knowledge: '信息提示', signal: '信号提示' },
    };
    return (labels[a.level] || {})[a.category] || a.category || '';
}

function _formatTime(iso: string): string {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } catch { return iso.slice(11, 16) || iso; }
}
