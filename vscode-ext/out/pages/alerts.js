"use strict";
/** Alert Center v2 — real-time signal alerts. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildAlertsPage = buildAlertsPage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildAlertsPage(data) {
    const alertsData = data.alerts || {};
    const alerts = alertsData.alerts || [];
    const unread = alertsData.unread || 0;
    const filterButtons = [
        { label: '全部', type: 'all' },
        { label: '金叉/买入', type: 'signal' },
        { label: '死叉/卖出', type: 'risk' },
    ];
    const content = `
<div class="flex-between p-24" style="padding-bottom:0">
<div class="flex-row gap-8">
    <span class="pulse" style="color:#3fb950;font-size:14px">● 实时监控中</span>
    <span class="text-sm text-muted">${unread > 0 ? unread + '条未读' : '全部已读'}</span>
</div>
<div class="flex-row gap-4">
    ${filterButtons.map(f => `<button class="btn btn-sm" onclick="filterAlerts('${f.type}')">${f.label}</button>`).join('')}
</div>
</div>
<div style="padding:16px 24px">
<div id="alertsFeed">
${alerts.map((a) => `
<div class="evidence-card" style="cursor:pointer;border-left:3px solid ${a.direction === 'up' ? '#3fb950' : '#f85149'}" onclick="analyzeStock('${a.stock_code}')">
<div class="flex-between">
<div class="flex-row gap-8">
<span style="color:#8b949e;font-family:monospace">${a.time}</span>
<b>${a.stock_name || a.stock_code}</b>
<span class="stock-code">${a.stock_code}</span>
</div>
<div class="flex-row gap-8">
<span class="tag tag-${a.direction}">${a.signal_type || a.alert_type}</span>
<span style="font-size:18px;font-weight:700" class="${a.direction === 'up' ? 'up' : 'down'}">${a.score}</span>
<span style="font-size:18px">${a.direction === 'up' ? '▲' : '▼'}</span>
</div>
</div>
${a.read ? '' : '<div class="text-sm" style="color:#58a6ff;margin-top:4px">● 新</div>'}
</div>`).join('') || '<div class="empty-state"><div class="icon">🔔</div><p>暂无预警</p></div>'}
</div>
<div style="text-align:center;padding:16px" class="text-muted text-sm">
🔄 每30秒自动刷新 · 最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>
</div>`;
    const extraScript = `
let alertInterval;
let currentFilter = 'all';
async function refreshAlerts() {
    try {
        const resp = await fetch('${constants_1.BASE_URL}/alerts/recent?limit=50' + (currentFilter !== 'all' ? '&type=' + currentFilter : ''));
        const data = await resp.json();
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) {}
}
function filterAlerts(type) {
    currentFilter = type;
    refreshAlerts();
    vscode.postMessage({command:'navigate',page:'alerts',filter:type});
}
function startAutoRefresh() {
    refreshAlerts();
    alertInterval = setInterval(refreshAlerts, 30000);
}
function stopAutoRefresh() { clearInterval(alertInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();`;
    return (0, layout_1.pageShell)('alerts', 'Alert Center · 预警中心', content, extraScript);
}
//# sourceMappingURL=alerts.js.map