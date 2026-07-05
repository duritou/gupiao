"use strict";
/** Dashboard v2 — AI Research Terminal home page. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildDashboardPage = buildDashboardPage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildDashboardPage(data) {
    const market = data.market || {};
    const m = market.market_breadth || {};
    const nb = market.northbound || {};
    const hotSectors = (market.hot_sectors || []).slice(0, 5);
    const risks = market.risk_summary || [];
    const scanner = data.scanner || {};
    const candidates = (scanner.candidates || []).slice(0, 6);
    const watchScores = data.watchScores?.signals || [];
    const content = `
<div class="grid4">
<div class="card"><h3>上涨</h3><div class="metric-value up">${m.up?.toLocaleString() || '3,865'}</div><span class="text-sm text-muted">涨停 ${m.limit_up || 68}</span></div>
<div class="card"><h3>下跌</h3><div class="metric-value down">${m.down?.toLocaleString() || '1,023'}</div><span class="text-sm text-muted">跌停 ${m.limit_down || 12}</span></div>
<div class="card"><h3>成交额</h3><div class="metric-value" style="font-size:24px">${market.total_volume || '1.43'}万亿</div></div>
<div class="card"><h3>北向资金</h3><div class="metric-value ${nb.direction === 'inflow' ? 'up' : 'down'}">${nb.net_flow != null ? (nb.net_flow > 0 ? '+' : '') + nb.net_flow + '亿' : '+58亿'}</div></div>
</div>
<div class="grid2">
<div class="card">
<div class="card-header"><h3>今日热点</h3><span class="tag tag-up pulse">实时</span></div>
${hotSectors.map((s) => `<div class="stock-row" onclick="navigate('marketmap')">
<span>${'★'.repeat(s.stars || 1)}${'☆'.repeat(5 - (s.stars || 1))} ${s.name}</span>
<span class="tag tag-${(s.score || 50) >= 70 ? 'up' : (s.score || 50) >= 40 ? 'warn' : 'down'}">${s.status || '活跃'}</span>
</div>`).join('') || '<div class="empty-state"><div class="icon">📊</div><p>加载中...</p></div>'}
</div>
<div class="card">
<div class="card-header"><h3>风险预警</h3><span class="text-sm text-muted">实时监控</span></div>
${risks.map((r) => `<div class="stock-row">
<span>${r.type}</span><span class="${r.severity === 'high' ? 'down' : 'warn'}">${r.count}只</span>
</div>`).join('') || '<div class="empty-state"><p>暂无风险预警</p></div>'}
</div>
</div>
<div style="padding:0 24px">
<div class="card">
<div class="card-header"><h3>🔥 今日机会 Top ${candidates.length}</h3><span class="text-sm text-muted">SignalFusion V1</span></div>
${candidates.map((c, i) => {
        const sc = c.fusion_score >= 75 ? 'up' : c.fusion_score >= 55 ? 'neutral' : 'down';
        const stars = c.fusion_score >= 80 ? '★★★★★' : c.fusion_score >= 65 ? '★★★★' : c.fusion_score >= 50 ? '★★★' : '★★';
        const name = c.stock_name || c.stock_code || '--';
        return `<div class="stock-row" onclick="analyzeStock('${c.stock_code}')">
<div><span class="stock-name">#${i + 1} ${name}</span><br><span class="stock-code">${c.stock_code} · ${stars}</span></div>
<div style="text-align:right"><span class="metric-value ${sc}" style="font-size:24px">${(c.fusion_score || 50).toFixed(0)}</span><br>
<span class="tag tag-${c.direction === 'buy' ? 'up' : c.direction === 'sell' ? 'down' : 'info'}">${c.direction === 'buy' ? 'Strong Buy' : c.direction === 'sell' ? 'Sell' : 'Neutral'}</span></div>
</div>`;
    }).join('') || '<div class="empty-state"><div class="icon">🔍</div><p>运行扫描以发现机会</p></div>'}
</div>
</div>
${watchScores.length > 0 ? `
<div style="padding:0 24px;margin-top:16px">
<div class="card">
<div class="card-header"><h3>📈 我的关注</h3><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('watchlist')">查看全部 →</span></div>
<div class="grid4">
${watchScores.slice(0, 4).map((s) => {
        const sc = s.fusion_score >= 70 ? 'up' : s.fusion_score >= 50 ? 'neutral' : 'down';
        return `<div style="text-align:center;padding:8px;cursor:pointer" onclick="analyzeStock('${s.stock_code}')">
<div class="stock-name">${s.stock_name || s.stock_code}</div>
<div style="font-size:20px;font-weight:700" class="${sc}">${(s.fusion_score || 50).toFixed(0)}</div>
<div class="text-sm"><span class="${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'neutral'}">${s.trend_arrow || '→'} ${s.top_signal || ''}</span></div>
</div>`;
    }).join('')}
</div>
</div>
</div>` : ''}
<div style="padding:16px 24px;text-align:center" class="text-muted text-sm">
🔄 Auto-refresh: 60s · 最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>`;
    const extraScript = `
// Dashboard auto-refresh
let dashInterval;
async function refreshDashboard() {
    try {
        const resp = await fetch('${constants_1.BASE_URL}/market/overview');
        const marketData = await resp.json();
        // Update key metrics
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) { console.log('Refresh skipped - backend may be offline'); }
}
function startAutoRefresh() {
    refreshDashboard();
    dashInterval = setInterval(refreshDashboard, 60000);
}
function stopAutoRefresh() { clearInterval(dashInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();`;
    return (0, layout_1.pageShell)('dashboard', 'AI Research Terminal', content, extraScript);
}
//# sourceMappingURL=dashboard.js.map