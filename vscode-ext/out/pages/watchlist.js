"use strict";
/** Watchlist v2 — Auto-refreshing stock watchlist. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildWatchlistPage = buildWatchlistPage;
const layout_1 = require("../webview/layout");
const score_display_1 = require("../webview/score-display");
function buildWatchlistPage(data) {
    const stocks = data.stocks || [];
    const initialScores = data.watchScores?.signals || [];
    const liveQuotes = data.liveQuotes?.quotes || [];
    const dataNote = data.watchScores?.data_note || '尚未取得信号数据';
    const newest = initialScores.find((s) => s.data_date || s.computed_at) || {};
    const sourceLabel = newest.data_source || '不可用';
    const freshnessLabel = newest.data_date
        ? `行情日期 ${newest.data_date}`
        : '行情日期未知';
    const scoreMap = {};
    initialScores.forEach((s) => { scoreMap[s.stock_code] = s; });
    const quoteMap = {};
    liveQuotes.forEach((q) => { quoteMap[q.stock_code] = q; });
    // Build initial rows with scores if available
    const rows = stocks.map((code, i) => {
        const s = scoreMap[code] || {};
        const q = quoteMap[code] || {};
        const signalName = String(s.stock_name || '').trim();
        const quoteName = String(q.stock_name || q.name || '').trim();
        const displayName = signalName && signalName !== code
            ? signalName
            : quoteName || signalName || '加载中...';
        const score = (0, score_display_1.finiteScore)(s.fusion_score);
        const provenance = q.provenance || {};
        const quoteStatus = !q.available
            ? '<span class="down" title="' + (provenance.error_message || '实时行情不可用') + '">不可用</span>'
            : provenance.is_cached
                ? '<span class="warn" title="缓存 ' + Math.round(provenance.cache_age_seconds || 0) + ' 秒">缓存</span>'
                : provenance.is_live
                    ? '<span class="up">实时</span>'
                    : '<span class="warn">延迟</span>';
        const change = q.change_pct;
        const changeClass = change > 0 ? 'up' : change < 0 ? 'down' : 'neutral';
        const sc = (0, score_display_1.scoreTone)(score);
        const riskColor = s.risk_level === '极低' ? 'up' : s.risk_level === '低' ? 'up' :
            s.risk_level === '中' ? 'warn' : s.risk_level === '高' ? 'down' : 'down';
        return `<tr onclick="analyzeStock('${code}')" style="cursor:pointer">
<td>${i + 1}</td>
<td class="stock-code">${code}</td>
<td class="stock-name">${displayName}</td>
<td>${q.available && q.price != null ? '¥' + Number(q.price).toFixed(2) : '-'}</td>
<td><span class="${changeClass}">${change != null ? (change > 0 ? '+' : '') + Number(change).toFixed(2) + '%' : '-'}</span></td>
<td>${quoteStatus}<div class="text-sm text-muted">${provenance.source_name || provenance.provider || ''}</div></td>
<td id="score_${i}"><span class="${sc}" style="font-weight:700;font-size:16px" title="自选股技术信号评分">${(0, score_display_1.scoreText)(score)}</span><div class="text-sm text-muted">技术分</div></td>
<td id="trend_${i}"><span class="${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'neutral'}">${s.trend_arrow || '-'}</span></td>
<td id="signal_${i}"><span class="tag tag-${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'info'}">${s.top_signal || '-'}</span></td>
<td id="risk_${i}"><span style="color:var(--${riskColor})">${s.risk_level || '-'}</span></td>
<td><button onclick="event.stopPropagation(); removeFromWatchlist('${code}')" title="移除" style="background:transparent;border:1px solid var(--border);border-radius:4px;padding:2px 8px;cursor:pointer;color:var(--text-muted)">✕</button></td>
</tr>`;
    }).join('');
    const content = `
<div class="flex-between p-24" style="padding-bottom:0">
<div class="flex-row gap-12">
    <button class="btn btn-primary" onclick="addToWatchlist()">+ 添加自选</button>
    <button class="btn" onclick="refreshWatchlist()">立即刷新</button>
    <span class="text-sm text-muted">🔄 自动刷新: 30秒</span>
</div>
<span class="text-sm text-muted">最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span></span>
</div>
<div style="padding:8px 24px 0;color:#8b949e;font-size:12px">
技术信号: ${sourceLabel} · ${freshnessLabel} · ${dataNote}
</div>
<div style="padding:16px 24px">
<div class="card">
<table>
<thead><tr>
<th>#</th><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>行情状态</th><th>技术评分</th><th>趋势</th><th>信号</th><th>风险</th><th>操作</th>
</tr></thead>
<tbody id="watchlistBody">
${rows || '<tr><td colspan="11" class="empty-state">暂无自选股，点击"+ 添加自选"开始</td></tr>'}
</tbody>
</table>
</div>
</div>`;
    const stockCodesJson = JSON.stringify(stocks);
    const extraScript = `
// Watchlist stocks
const WATCH_CODES = ${stockCodesJson};

// Ask the extension host to bypass its page cache and render a fresh snapshot.
let watchInterval;
async function refreshWatchlist() {
    if (!WATCH_CODES.length) return;
    vscode.postMessage({command:'refreshPage'});
}
function startAutoRefresh() {
    clearInterval(watchInterval);
    watchInterval = setInterval(refreshWatchlist, 30000);
}
function stopAutoRefresh() { clearInterval(watchInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();`;
    return (0, layout_1.pageShell)('watchlist', 'Watchlist · 自选股', content, extraScript);
}
//# sourceMappingURL=watchlist.js.map