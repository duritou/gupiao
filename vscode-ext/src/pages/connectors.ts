/** Data Connectors v7.4 — manage all data sources at a glance. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildConnectorsPage(data: any): string {
    const status = data.dataStatus || {};
    const registry = data.registry || {};
    const layers = registry.layers || {};
    const ranking = status.provider_ranking || [];

    const layerNames: Record<string, string> = {
        exchange: '交易所数据', disclosure: '公司公告',
        market: '行情数据', macro: '宏观经济',
        industry: '行业政策', news: '新闻资讯',
        company: '上市公司',
    };

    const tierBadges: Record<string, string> = {
        official: '官方', disclosure: '披露', commercial: '商业',
        community: '社区', news: '媒体', company: '公司',
    };
    const tierColors: Record<string, string> = {
        official: '#22C55E', disclosure: '#22C55E', commercial: '#58a6ff',
        community: '#F59E0B', news: '#8B5CF6', company: '#8b949e',
    };

    const content = `
<!-- Header -->
<div style="text-align:center;padding:24px 24px 0">
<div style="font-size:36px;margin-bottom:8px">🔌</div>
<h1 style="font-size:20px;color:#58a6ff">Data Connectors</h1>
<div style="font-size:12px;color:#8b949e">${registry.total_sources || 0} sources · 7 layers · ${registry.active_sources || 0} active</div>
</div>

<!-- Global Status -->
<div style="padding:16px 24px 0">
<div class="card" style="border-left:3px solid ${status.status === 'live' ? '#22C55E' : '#F59E0B'}">
<div class="flex-between">
<div>
<div style="font-weight:600;font-size:15px">${status.status_icon || '🟢'} Pipeline: ${status.status || 'unknown'}</div>
<div style="font-size:11px;color:#8b949e;margin-top:2px">Primary: ${status.primary_display || status.primary_provider || '--'} · ${status.cache_entries || 0} cached entries</div>
</div>
<div style="text-align:right">
<div style="font-size:11px;color:#8b949e">${status.recommendation || ''}</div>
</div>
</div>
</div></div>

<!-- Provider Ranking -->
<div style="padding:0 24px"><div class="card">
<div class="card-header"><h3>Provider Ranking (Auto-sorted)</h3></div>
${ranking.length > 0 ? ranking.map((p: any) => `
<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #21262d">
<span style="font-size:11px;color:#6B7280;width:24px">#${p.rank}</span>
<div style="flex:1">
<div style="font-weight:600;font-size:13px">${p.name}</div>
<div style="font-size:11px;color:#8b949e">${p.total_calls} calls · ${p.avg_latency_ms.toFixed(0)}ms avg</div>
</div>
<div style="width:80px">
<div style="height:6px;background:#21262d;border-radius:3px">
<div style="height:6px;width:${(p.reliability * 100).toFixed(0)}%;background:${p.reliability >= 0.95 ? '#22C55E' : '#F59E0B'};border-radius:3px"></div>
</div>
<div style="font-size:10px;color:#8b949e;text-align:center">${(p.reliability * 100).toFixed(1)}%</div>
</div>
<div style="width:60px;text-align:right">
<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.status ? '#22C55E' : '#EF4444'}"></span>
<span style="font-size:11px;color:${p.status ? '#22C55E' : '#EF4444'};margin-left:4px">${p.status ? 'UP' : 'DOWN'}</span>
</div>
</div>`).join('') : '<div class="empty-state"><p>No provider data yet</p></div>'}
</div></div>

<!-- Layer-by-layer sources -->
${Object.entries(layers).map(([layerKey, layer]: [string, any]) => `
<div style="padding:0 24px;margin-top:8px"><div class="card">
<div class="card-header">
<h3>${layerNames[layerKey] || layerKey}</h3>
<span class="text-sm text-muted">${layer.count} sources · ${layer.active_count} active</span>
</div>
${(layer.sources || []).map((s: any) => {
    const icon = s.status === 'active' ? '🟢' : '○';
    const statusText = s.status === 'active' ? 'Active' : 'Planned';
    return `
<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #21262d">
<span style="font-size:14px">${icon}</span>
<div style="flex:1">
<div style="font-weight:600;font-size:13px">${s.name}</div>
<div style="font-size:11px;color:#8b949e">${(s.provides || []).slice(0, 4).join(' · ')}</div>
</div>
<div style="text-align:right">
<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;color:${tierColors[s.tier] || '#8b949e'};background:#21262d">${tierBadges[s.tier] || s.tier}</span>
<div style="font-size:10px;color:#8b949e;margin-top:2px">${statusText} · trust ${(s.base_trust * 100).toFixed(0)}%</div>
</div>
</div>`;
}).join('') || '<div class="empty-state"><p>No sources in this layer</p></div>'}
</div></div>
`).join('')}

<div style="text-align:center;padding:16px" class="text-muted text-sm">
🔄 Auto-refresh: 60s · <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>`;

    const extraScript = `
let connInterval;
async function refreshConnectors() {
    try {
        await fetch('${BASE_URL}/market/data-status');
        await fetch('${BASE_URL}/market/registry');
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) {}
}
function startAutoRefresh() { refreshConnectors(); connInterval = setInterval(refreshConnectors, 60000); }
function stopAutoRefresh() { clearInterval(connInterval); }
document.addEventListener('visibilitychange', () => { document.hidden ? stopAutoRefresh() : startAutoRefresh(); });
startAutoRefresh();`;

    return pageShell('connectors', 'Data Connectors · 数据连接器', content, extraScript);
}
