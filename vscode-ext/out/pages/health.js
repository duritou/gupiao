"use strict";
/** System Health v7.3 — Data Trust + all subsystems at a glance. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildHealthPage = buildHealthPage;
const layout_1 = require("../webview/layout");
function buildHealthPage(data) {
    const health = data.health || {};
    const subsystems = health.subsystems || [];
    const liveData = health.live_data || {};
    const hithink = data.hithink || null;
    const hithinkHealth = hithink?.health || {};
    const hithinkStatus = hithink?.status || 'unknown';
    const hithinkStatusColor = {
        healthy: '#22C55E', degraded: '#F59E0B',
        not_configured: '#8b949e', unknown: '#8b949e', down: '#EF4444',
    };
    const hithinkColor = hithinkStatusColor[hithinkStatus] || '#8b949e';
    const escapeHtml = (value) => String(value ?? '--')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const formatRate = (value) => {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : '--';
    };
    const hithinkCapabilities = Object.entries(hithink?.by_capability || {})
        .slice(0, 8);
    const hithinkRollout = Object.entries(hithink?.rollout || {})
        .slice(0, 8);
    const overallColor = {
        healthy: '#22C55E', degraded: '#F59E0B', down: '#EF4444',
    };
    const content = `
<!-- Overall Status -->
<div style="text-align:center;padding:24px 24px 0">
<div style="display:inline-block;width:16px;height:16px;border-radius:50%;background:${overallColor[health.overall_status] || '#8b949e'};margin-bottom:8px"></div>
<h1 style="font-size:20px;color:${overallColor[health.overall_status] || '#8b949e'}">System ${health.overall_status === 'healthy' ? 'Healthy' : health.overall_status === 'degraded' ? 'Degraded' : 'Down'}</h1>
<div style="font-size:12px;color:#8b949e">最后检查: ${health.checked_at || '--'}</div>
</div>

<!-- Live Data Status -->
<div style="padding:16px 24px 0"><div class="card" style="border-left:3px solid ${liveData.available ? '#22C55E' : '#EF4444'}">
<div class="flex-between">
<div><h3>Live Market Data</h3></div>
<div><span style="color:${liveData.available ? '#22C55E' : '#EF4444'};font-weight:600">● ${liveData.available ? 'Connected' : 'Unavailable'}</span></div>
</div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">Provider</span><span>akshare</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">Indices</span><span>${liveData.indices_count || 0} loaded</span></div>
</div></div>

<!-- HiThink Provider Status -->
<div style="padding:16px 24px 0"><div class="card" style="border-left:3px solid ${hithinkColor}">
<div class="flex-between" style="margin-bottom:8px">
<div><h3>HiThink · 同花顺金融数据服务</h3></div>
<span style="color:${hithinkColor};font-weight:600">● ${escapeHtml(hithinkStatus.toUpperCase())}</span>
</div>
${hithink ? `
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">Configured</span><span>${hithink.configured ? 'Yes' : 'No'}</span></div>
<div class="grid2" style="margin-top:8px">
<div><div class="text-sm text-muted">Calls</div><div style="font-size:18px;font-weight:600">${Number(hithinkHealth.calls || 0).toLocaleString()}</div></div>
<div><div class="text-sm text-muted">Success rate</div><div style="font-size:18px;font-weight:600">${formatRate(hithinkHealth.success_rate)}</div></div>
<div><div class="text-sm text-muted">P95 latency</div><div style="font-size:18px;font-weight:600">${escapeHtml(hithinkHealth.p95_latency_ms)} ms</div></div>
<div><div class="text-sm text-muted">Circuit</div><div style="font-size:18px;font-weight:600">${escapeHtml(hithink.circuit?.state || '--')}</div></div>
</div>
${hithinkCapabilities.length ? `<div style="margin-top:12px;font-size:11px;color:#8b949e">按能力统计</div>${hithinkCapabilities.map(([name, stats]) => `
<div class="flex-between" style="padding:4px 0;border-bottom:1px solid #21262d">
<span>${escapeHtml(name)}</span><span>${Number(stats.calls || 0)} calls · ${Number(stats.successes || 0)} ok · P95 ${escapeHtml(stats.p95_latency_ms)} ms</span>
</div>`).join('')}` : '<div class="text-sm text-muted" style="margin-top:10px">暂无 canary 样本</div>'}
${hithinkRollout.length ? `<div style="margin-top:12px;font-size:11px;color:#8b949e">Rollout</div>${hithinkRollout.map(([name, mode]) => `
<div class="flex-between" style="padding:3px 0"><span>${escapeHtml(name)}</span><span style="color:#c9d1d9">${escapeHtml(mode)}</span></div>`).join('')}` : ''}
` : '<div class="text-sm text-muted">后端未返回 HiThink 健康接口；请确认前后端版本一致。</div>'}
</div></div>

<!-- Subsystem Grid -->
<div class="grid2" style="padding:16px 24px">
${subsystems.map((s) => {
        const statusColor = {
            healthy: '#22C55E', degraded: '#F59E0B', down: '#EF4444', unknown: '#8b949e',
        };
        const details = s.details || {};
        const detailLines = Object.entries(details).filter(([k]) => !String(k).startsWith('_')).slice(0, 4);
        return `
<div class="card" style="border-left:3px solid ${statusColor[s.status] || '#8b949e'}">
<div class="flex-between" style="margin-bottom:8px">
<h3>${s.name}</h3>
<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${statusColor[s.status] || '#8b949e'}"></span>
</div>
<div style="font-size:12px;font-weight:600;color:${statusColor[s.status] || '#8b949e'}">● ${s.status.toUpperCase()}</div>
<div style="font-size:11px;color:#6B7280;margin-top:4px">Uptime ${s.uptime_pct || 100}%</div>
${detailLines.map(([k, v]) => `
<div style="font-size:11px;color:#8b949e;margin-top:3px;display:flex;justify-content:space-between">
<span>${String(k)}</span>
<span style="color:#c9d1d9">${typeof v === 'object' ? JSON.stringify(v).slice(0, 40) : String(v)}</span>
</div>`).join('')}
</div>`;
    }).join('')}
</div>

<!-- Refresh -->
<div style="text-align:center;padding:16px" class="text-muted text-sm">
🔄 每30秒自动刷新 · <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
<button class="btn btn-sm" style="margin-left:8px" onclick="refreshHealth()">立即检查</button>
</div>`;
    const extraScript = `
async function refreshHealth() {
    vscode.postMessage({command:'refreshPage'});
}
let healthInterval;
function startAutoRefresh() { healthInterval = setInterval(refreshHealth, 30000); }
function stopAutoRefresh() { clearInterval(healthInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();`;
    return (0, layout_1.pageShell)('health', 'System Health · 系统健康', content, extraScript);
}
//# sourceMappingURL=health.js.map