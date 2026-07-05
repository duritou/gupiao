"use strict";
/** Dashboard v4.2 — Mission Control with Alert Intelligence.
 *
 * Layout:
 *   1. Portfolio Summary Cards (from Morning Brief)
 *   2. 🔥 Today Focus — AI-prioritized urgent alerts (P0/P1)
 *   3. Market Overview — breadth, volume, northbound
 *   4. Hot Sectors + Risk Warnings
 *   5. Top Opportunities (from Scanner)
 *   6. My Watchlist Snapshot
 */
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
    const alertFeed = data.alerts || {};
    const todayFocus = alertFeed.today_focus || {};
    const urgentAlerts = todayFocus.urgent || [];
    const importantAlerts = todayFocus.important || [];
    const trackRecord = data.trackRecord || {};
    const aiAlpha = data.aiAlpha || {};
    const userProfile = data.userProfile || {};
    const greeting = userProfile.greeting || '';
    const dataHealth = data.dataQuality || {};
    const healthStatus = dataHealth.status || 'unknown';
    const healthIcon = healthStatus === 'healthy' ? '🟢' : healthStatus === 'degraded' ? '🟡' : '🔴';
    const pfPlColor = (pf.total_pl || 0) >= 0 ? 'up' : 'down';
    const qualityPct = dataHealth.overall_quality ? (dataHealth.overall_quality * 100).toFixed(0) + '%' : '--';
    const qualityColor = healthStatus === 'healthy' ? '#22C55E' : healthStatus === 'degraded' ? '#F59E0B' : '#EF4444';
    const content = `
<!-- Data Quality + Greeting Bar -->
<div style="padding:8px 24px;display:flex;justify-content:space-between;align-items:center">
${greeting ? '<div style="font-size:12px;color:#A78BFA;line-height:1.5">🤖 ' + greeting + '</div>' : '<div></div>'}
<div style="font-size:11px;display:flex;align-items:center;gap:6px">
<span>${healthIcon}</span>
<span style="color:#8b949e">${dataHealth.provider || 'mock'}</span>
<span style="color:${qualityColor}">${qualityPct}</span>
</div>
</div>

<!-- ═══════════ Portfolio Summary Cards ═══════════ -->
${pf.position_count > 0 ? `
<div class="grid4">
<div class="card" style="border-left:3px solid #7C3AED"><h3>总资产</h3><div class="metric-value" style="font-size:24px">¥${((pf.total_value || 0) / 10000).toFixed(1)}万</div><span class="text-sm text-muted">${pf.position_count || 0}只持仓</span></div>
<div class="card"><h3>总盈亏</h3><div class="metric-value ${pfPlColor}">${(pf.total_pl || 0) >= 0 ? '+' : ''}${(pf.total_pl_pct || 0).toFixed(1)}%</div><span class="text-sm ${(pf.daily_pl_pct || 0) >= 0 ? 'up' : 'down'}">今日 ${(pf.daily_pl_pct || 0) >= 0 ? '+' : ''}${(pf.daily_pl_pct || 0).toFixed(1)}%</span></div>
<div class="card" style="border-left:3px solid ${(pf.avg_score || 50) >= 70 ? '#22C55E' : '#F59E0B'}"><h3>AI评分</h3><div class="metric-value ${(pf.avg_score || 50) >= 70 ? 'up' : 'warn'}">${(pf.avg_score || 50).toFixed(0)}</div><span class="text-sm ${(pf.score_trend || 0) >= 0 ? 'up' : 'down'}">${(pf.score_trend || 0) >= 0 ? '↑' : '↓'}${Math.abs(pf.score_trend || 0).toFixed(0)} vs 昨日</span></div>
<div class="card"><h3>情绪</h3><div class="metric-value" style="color:#F59E0B;font-size:36px">${'★'.repeat(brief.market?.sentiment_stars || 4)}${'☆'.repeat(5 - (brief.market?.sentiment_stars || 4))}</div><span class="text-sm text-muted">${brief.market?.sentiment_label || '积极'} ${brief.market?.sentiment_score || 72}分</span></div>
</div>
` : ''}

<!-- ═══════════ 🔥 Today Focus (Alert Intelligence) ═══════════ -->
<div style="padding:0 24px;margin-bottom:8px">
<div class="card" style="border:1px solid ${urgentAlerts.length > 0 ? '#F59E0B' : '#30363d'};${urgentAlerts.length > 0 ? 'background:linear-gradient(135deg,#1a1800 0%,#161b22 100%);' : ''}">
<div class="card-header">
<h3 style="font-size:15px;color:#F59E0B">🔥 Today Focus · 今日最重要</h3>
<span class="text-sm text-muted">AI 已为你排好优先级</span>
</div>
${urgentAlerts.length > 0 || importantAlerts.length > 0 ? `
<div style="display:flex;flex-direction:column;gap:8px">
${urgentAlerts.map((a) => _renderFocusAlert(a, true)).join('')}
${importantAlerts.map((a) => _renderFocusAlert(a, false)).join('')}
</div>` : `
<div class="empty-state" style="padding:24px"><p>今日暂无紧急预警 · AI持续监控中</p></div>`}
${alertFeed.one_liner ? `
<div style="margin-top:12px;padding-top:12px;border-top:1px solid #21262d;font-size:13px;color:#A78BFA;line-height:1.5">💬 ${alertFeed.one_liner}</div>` : ''}
${brief.one_liner ? `
<div style="margin-top:8px;font-size:13px;color:#8B5CF6;line-height:1.5">💬 ${brief.one_liner}</div>` : ''}
</div></div>

<!-- ═══════════ Market Overview ═══════════ -->
<div class="grid4">
<div class="card"><h3>上涨</h3><div class="metric-value up">${m.up?.toLocaleString() || '3,865'}</div><span class="text-sm text-muted">涨停 ${m.limit_up || 68}</span></div>
<div class="card"><h3>下跌</h3><div class="metric-value down">${m.down?.toLocaleString() || '1,023'}</div><span class="text-sm text-muted">跌停 ${m.limit_down || 12}</span></div>
<div class="card"><h3>成交额</h3><div class="metric-value" style="font-size:24px">${market.total_volume || '1.43'}万亿</div></div>
<div class="card"><h3>北向资金</h3><div class="metric-value ${nb.direction === 'inflow' ? 'up' : 'down'}">${nb.net_flow != null ? (nb.net_flow > 0 ? '+' : '') + nb.net_flow + '亿' : '+58亿'}</div></div>
</div>

<!-- ═══════════ Hot Sectors + Risk ═══════════ -->
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

<!-- ═══════════ Top Opportunities ═══════════ -->
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

<!-- ═══════════ My Watchlist Snapshot ═══════════ -->
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

<!-- ═══════════ AI Alpha — Value Attribution (v5.0 final) ═══════════ -->
${aiAlpha.total_suggestions > 0 ? `
<div style="padding:0 24px;margin-top:8px;margin-bottom:8px"><div class="card" style="border:1px solid #7C3AED;background:linear-gradient(135deg,#0f0a1a 0%,#161b22 100%)">
<div class="card-header">
<h3 style="color:#A78BFA">🤖 AI 价值验证 · ${aiAlpha.period_label || '最近90天'}</h3>
<span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('resume')">完整档案 →</span>
</div>

<!-- Hero Metric: AI Alpha -->
<div style="text-align:center;padding:16px 0">
<div style="font-size:12px;color:#8b949e;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">AI Alpha · 超额收益</div>
<div style="font-size:48px;font-weight:800;color:${aiAlpha.ai_alpha_pct >= 0 ? '#22C55E' : '#EF4444'};line-height:1">
${aiAlpha.ai_alpha_pct >= 0 ? '+' : ''}${aiAlpha.ai_alpha_pct.toFixed(1)}%
</div>
<div style="font-size:12px;color:#8b949e;margin-top:4px">跟随AI vs 自主决策的收益差</div>
</div>

<!-- 3-column breakdown -->
<div class="grid3" style="padding:0">
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #1F2937">
<div style="font-size:11px;color:#8b949e;margin-bottom:4px">跟随 AI</div>
<div style="font-size:24px;font-weight:700;color:#22C55E">${aiAlpha.follow_ai_return_pct >= 0 ? '+' : ''}${aiAlpha.follow_ai_return_pct.toFixed(1)}%</div>
<div style="font-size:10px;color:#6B7280">${aiAlpha.followed_correct_count}胜/${aiAlpha.followed_wrong_count}负</div>
</div>
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #1F2937">
<div style="font-size:11px;color:#8b949e;margin-bottom:4px">自主决策</div>
<div style="font-size:24px;font-weight:700;color:${aiAlpha.self_decision_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${aiAlpha.self_decision_return_pct >= 0 ? '+' : ''}${aiAlpha.self_decision_return_pct.toFixed(1)}%</div>
<div style="font-size:10px;color:#6B7280">未跟随AI的收益</div>
</div>
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #7C3AED">
<div style="font-size:11px;color:#A78BFA;margin-bottom:4px">执行率</div>
<div style="font-size:24px;font-weight:700;color:#A78BFA">${(aiAlpha.execution_rate * 100).toFixed(0)}%</div>
<div style="font-size:10px;color:#6B7280">${aiAlpha.executed_count}/${aiAlpha.total_suggestions}条建议被执行</div>
</div>
</div>

<!-- Detail row: missed + avoided -->
<div class="grid2" style="padding:0;margin-top:8px">
<div style="padding:8px 12px;font-size:11px;text-align:center">
<span style="color:#F59E0B">💔 错过机会 </span>
<span style="color:#F59E0B;font-weight:600">${aiAlpha.missed_opportunity_count}次</span>
<span style="color:#8b949e"> · 损失 </span>
<span style="color:#F59E0B;font-weight:600">+${aiAlpha.missed_profit_total_pct.toFixed(1)}%</span>
</div>
<div style="padding:8px 12px;font-size:11px;text-align:center">
<span style="color:#22C55E">🛡 避免亏损 </span>
<span style="color:#22C55E;font-weight:600">${aiAlpha.avoided_loss_count}次</span>
<span style="color:#8b949e"> · 保住 </span>
<span style="color:#22C55E;font-weight:600">${aiAlpha.avoided_loss_total_pct.toFixed(1)}%</span>
</div>
</div>
</div></div>` : (trackRecord.total_recommendations > 0 ? `
<div style="padding:0 24px;margin-top:8px;margin-bottom:8px"><div class="card" style="border-left:3px solid #7C3AED">
<div class="card-header"><h3>🤖 AI Track Record</h3><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('resume')">AI完整档案 →</span></div>
<div class="grid4">
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22C55E">${(trackRecord.accuracy * 100).toFixed(0)}%</div><div class="text-sm text-muted">准确率</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22C55E">${trackRecord.correct_count}/${trackRecord.total_recommendations}</div><div class="text-sm text-muted">正确/总数</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22C55E">${trackRecord.current_streak}次</div><div class="text-sm text-muted">连续命中</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:${trackRecord.avg_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${trackRecord.avg_return_pct >= 0 ? '+' : ''}${trackRecord.avg_return_pct.toFixed(1)}%</div><div class="text-sm text-muted">平均收益</div></div>
</div>
</div></div>` : '')}

<div style="padding:16px 24px;text-align:center" class="text-muted text-sm">
🔄 Auto-refresh: 60s · 最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>`;
    const extraScript = `
let dashInterval;
let alertUnread = ${alertFeed.unread_count || 0};
async function refreshDashboard() {
    try {
        await fetch('${constants_1.BASE_URL}/market/overview');
        // Refresh alerts for Today Focus
        const alertsResp = await fetch('${constants_1.BASE_URL}/alerts/today').catch(() => null);
        if (alertsResp) {
            const alertData = await alertsResp.json();
            const newUnread = alertData.unread_count || 0;
            if (newUnread > alertUnread) {
                vscode.postMessage({command:'alertUpdate',unread:newUnread,urgent:alertData.urgent_count||0});
            }
            alertUnread = newUnread;
        }
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) {}
}
function startAutoRefresh() { refreshDashboard(); dashInterval = setInterval(refreshDashboard, 60000); }
function stopAutoRefresh() { clearInterval(dashInterval); }
document.addEventListener('visibilitychange', () => { document.hidden ? stopAutoRefresh() : startAutoRefresh(); });
startAutoRefresh();`;
    return (0, layout_1.pageShell)('dashboard', 'Dashboard · Mission Control', content, extraScript);
}
/** Render a single Today Focus alert card. */
function _renderFocusAlert(a, isUrgent) {
    const levelColor = a.level === 'P0' ? '#EF4444' : a.level === 'P1' ? '#F59E0B' : '#8b949e';
    const levelBg = a.level === 'P0' ? '#3a1b1b' : a.level === 'P1' ? '#3a351b' : '#21262d';
    const levelBadge = `<span style="display:inline-block;padding:1px 6px;border-radius:3px;background:${levelBg};color:${levelColor};font-size:10px;font-weight:700;font-family:monospace">${a.level}</span>`;
    const directionIcon = a.direction === 'buy' ? '🟢' : a.direction === 'sell' ? '🔴' : '⚪';
    const clickAction = a.stock_code
        ? `onclick="analyzeStock('${a.stock_code}')"`
        : '';
    return `
<div class="evidence-card" style="cursor:${a.stock_code ? 'pointer' : 'default'};border-left:3px solid ${levelColor};${isUrgent ? 'background:#1a1a10;' : ''}" ${clickAction}>
<div class="flex-between">
<div class="flex-row gap-8">
${levelBadge}
<span style="font-size:14px;font-weight:600">${a.title}</span>
</div>
<div class="flex-row gap-8">
<span style="color:#8b949e;font-size:11px">${_timeAgo(a.created_at)}</span>
${a.status === 'new' ? '<span style="color:#58a6ff;font-size:10px">● NEW</span>' : ''}
</div>
</div>
${a.evidence && a.evidence.length > 0 ? `
<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px">
${a.evidence.slice(0, 3).map((e) => `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:#21262d;color:#8b949e">✓ ${e.title}</span>`).join('')}
</div>` : ''}
${a.ai_confidence ? `
<div style="margin-top:6px;display:flex;gap:16px;font-size:11px;color:#8b949e">
<span>置信度 ${(a.ai_confidence * 100).toFixed(0)}%</span>
${a.historical_accuracy ? `<span>历史准确率 ${(a.historical_accuracy * 100).toFixed(0)}%</span>` : ''}
</div>` : ''}
</div>`;
}
function _timeAgo(iso) {
    if (!iso)
        return '';
    const now = new Date();
    const then = new Date(iso);
    const mins = Math.floor((now.getTime() - then.getTime()) / 60000);
    if (mins < 1)
        return '刚刚';
    if (mins < 60)
        return `${mins}分钟前`;
    const hours = Math.floor(mins / 60);
    if (hours < 24)
        return `${hours}小时前`;
    return `${Math.floor(hours / 24)}天前`;
}
//# sourceMappingURL=dashboard.js.map