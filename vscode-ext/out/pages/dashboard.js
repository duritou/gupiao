"use strict";
/** Dashboard v3 — AI Research Terminal home page with Portfolio + Morning Brief. */
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
    const brief = data.brief || {};
    const pf = brief.portfolio || {};
    const items = pf.items || [];
    const changes = brief.score_changes || {};
    // Portfolio summary cards
    const pfPlColor = (pf.total_pl || 0) >= 0 ? 'up' : 'down';
    const content = `
<!-- Portfolio Summary (from Morning Brief) -->
${pf.position_count > 0 ? `
<div class="grid4">
<div class="card" style="border-left:3px solid #7C3AED"><h3>总资产</h3><div class="metric-value" style="font-size:24px">¥${((pf.total_value || 0) / 10000).toFixed(1)}万</div><span class="text-sm text-muted">${pf.position_count || 0}只持仓</span></div>
<div class="card"><h3>总盈亏</h3><div class="metric-value ${pfPlColor}">${(pf.total_pl || 0) >= 0 ? '+' : ''}${(pf.total_pl_pct || 0).toFixed(1)}%</div><span class="text-sm ${(pf.daily_pl_pct || 0) >= 0 ? 'up' : 'down'}">今日 ${(pf.daily_pl_pct || 0) >= 0 ? '+' : ''}${(pf.daily_pl_pct || 0).toFixed(1)}%</span></div>
<div class="card" style="border-left:3px solid ${(pf.avg_score || 50) >= 70 ? '#22C55E' : '#F59E0B'}"><h3>AI评分</h3><div class="metric-value ${(pf.avg_score || 50) >= 70 ? 'up' : 'warn'}">${(pf.avg_score || 50).toFixed(0)}</div><span class="text-sm ${(pf.score_trend || 0) >= 0 ? 'up' : 'down'}">${(pf.score_trend || 0) >= 0 ? '↑' : '↓'}${Math.abs(pf.score_trend || 0).toFixed(0)} vs 昨日</span></div>
<div class="card"><h3>情绪</h3><div class="metric-value" style="color:#F59E0B;font-size:36px">${'★'.repeat(brief.market?.sentiment_stars || 4)}${'☆'.repeat(5 - (brief.market?.sentiment_stars || 4))}</div><span class="text-sm text-muted">${brief.market?.sentiment_label || '积极'} ${brief.market?.sentiment_score || 72}分</span></div>
</div>

<!-- Score Changes -->
${(changes.upgraded || []).length > 0 || (changes.downgraded || []).length > 0 ? `
<div class="grid2">
${(changes.upgraded || []).length > 0 ? `
<div class="card" style="border-left:3px solid #22C55E">
<h3>▲ 评分提升</h3>
${changes.upgraded.map((p) => `
<div class="stock-row" onclick="analyzeStock('${p.stock_code}')">
<span><span class="stock-name">${p.stock_name}</span> <span class="stock-code">${p.stock_code}</span></span>
<span><span style="color:#22C55E;font-weight:700">${p.ai_score.toFixed(0)}</span> <span style="color:#22C55E;font-size:11px">↑${p.score_change.toFixed(0)}</span> <span class="tag tag-up" style="font-size:10px">${p.top_signal || ''}</span></span>
</div>`).join('')}
</div>` : ''}
${(changes.downgraded || []).length > 0 ? `
<div class="card" style="border-left:3px solid #EF4444">
<h3>▼ 评分下降</h3>
${changes.downgraded.map((p) => `
<div class="stock-row" onclick="analyzeStock('${p.stock_code}')">
<span><span class="stock-name">${p.stock_name}</span> <span class="stock-code">${p.stock_code}</span></span>
<span><span style="color:#EF4444;font-weight:700">${p.ai_score.toFixed(0)}</span> <span style="color:#EF4444;font-size:11px">↓${Math.abs(p.score_change).toFixed(0)}</span> <span class="tag tag-down" style="font-size:10px">${p.risk_level || ''}风险</span></span>
</div>`).join('')}
</div>` : ''}
</div>` : ''}

<!-- AI One-Liner -->
${brief.one_liner ? `
<div class="card" style="border-left:3px solid #7C3AED;margin:0 24px 12px">
<div style="font-size:14px;color:#A78BFA;line-height:1.6">💬 ${brief.one_liner}</div>
</div>` : ''}

<!-- AI Recommendations -->
${(brief.recommendations || []).length > 0 ? `
<div style="padding:0 24px;margin-bottom:12px">
<div class="card">
<h3>AI 建议</h3>
${brief.recommendations.map((r) => `
<div class="stock-row" onclick="analyzeStock('${r.stock_code}')">
<span><span class="stock-name">${r.stock_name}</span> <span class="stock-code">${r.stock_code}</span></span>
<span><span class="tag tag-${r.type === 'hold_or_add' ? 'up' : 'down'}">${r.type === 'hold_or_add' ? '继续持有' : '建议减仓'}</span> <span class="text-sm text-muted">${r.reason}</span></span>
</div>`).join('')}
</div></div>` : ''}
` : ''}

<!-- Market Overview -->
<div class="grid4">
<div class="card"><h3>上涨</h3><div class="metric-value up">${m.up?.toLocaleString() || '3,865'}</div><span class="text-sm text-muted">涨停 ${m.limit_up || 68}</span></div>
<div class="card"><h3>下跌</h3><div class="metric-value down">${m.down?.toLocaleString() || '1,023'}</div><span class="text-sm text-muted">跌停 ${m.limit_down || 12}</span></div>
<div class="card"><h3>成交额</h3><div class="metric-value" style="font-size:24px">${market.total_volume || '1.43'}万亿</div></div>
<div class="card"><h3>北向资金</h3><div class="metric-value ${nb.direction === 'inflow' ? 'up' : 'down'}">${nb.net_flow != null ? (nb.net_flow > 0 ? '+' : '') + nb.net_flow + '亿' : '+58亿'}</div></div>
</div>

<div class="grid2">
<div class="card"><div class="card-header"><h3>今日热点</h3></div>
${hotSectors.map((s) => `<div class="stock-row" onclick="navigate('marketmap')">
<span>${'★'.repeat(s.stars || 1)}${'☆'.repeat(5 - (s.stars || 1))} ${s.name}</span>
<span class="tag tag-${(s.score || 50) >= 70 ? 'up' : (s.score || 50) >= 40 ? 'warn' : 'down'}">${s.status || '活跃'}</span>
</div>`).join('') || '<div class="empty-state"><p>加载中...</p></div>'}
</div>
<div class="card"><div class="card-header"><h3>风险预警</h3></div>
${risks.map((r) => `<div class="stock-row">
<span>${r.type}</span><span class="${r.severity === 'high' ? 'down' : 'warn'}">${r.count}只</span>
</div>`).join('') || '<div class="empty-state"><p>暂无风险预警</p></div>'}
</div>
</div>

<div style="padding:0 24px"><div class="card"><div class="card-header"><h3>🔥 今日机会 Top ${candidates.length}</h3></div>
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
</div></div>

${watchScores.length > 0 ? `
<div style="padding:0 24px;margin-top:16px"><div class="card">
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
</div></div></div>` : ''}

<div style="padding:16px 24px;text-align:center" class="text-muted text-sm">
🔄 Auto-refresh: 60s · 最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>`;
    const extraScript = `
let dashInterval;
async function refreshDashboard() {
    try {
        await fetch('${constants_1.BASE_URL}/market/overview');
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) {}
}
function startAutoRefresh() { refreshDashboard(); dashInterval = setInterval(refreshDashboard, 60000); }
function stopAutoRefresh() { clearInterval(dashInterval); }
document.addEventListener('visibilitychange', () => { document.hidden ? stopAutoRefresh() : startAutoRefresh(); });
startAutoRefresh();`;
    return (0, layout_1.pageShell)('dashboard', 'Dashboard · 晨报', content, extraScript);
}
//# sourceMappingURL=dashboard.js.map