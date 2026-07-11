/** Watchlist v2 — Auto-refreshing stock watchlist. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildWatchlistPage(data: any): string {
    const stocks = data.stocks || [];
    const initialScores = data.watchScores?.signals || [];
    const scoreMap: Record<string, any> = {};
    initialScores.forEach((s: any) => { scoreMap[s.stock_code] = s; });

    // Build initial rows with scores if available
    const rows = stocks.map((code: string, i: number) => {
        const s = scoreMap[code] || {};
        const sc = (s.fusion_score || 0) >= 70 ? 'up' : (s.fusion_score || 0) >= 50 ? 'neutral' : 'down';
        const riskColor = s.risk_level === '极低' ? 'up' : s.risk_level === '低' ? 'up' :
                         s.risk_level === '中' ? 'warn' : s.risk_level === '高' ? 'down' : 'down';
        return `<tr onclick="analyzeStock('${code}')" style="cursor:pointer">
<td>${i + 1}</td>
<td class="stock-code">${code}</td>
<td class="stock-name">${s.stock_name || '加载中...'}</td>
<td>${s.price ? '¥' + s.price.toFixed(2) : '-'}</td>
<td id="score_${i}"><span class="${sc}" style="font-weight:700;font-size:16px">${s.fusion_score != null ? s.fusion_score.toFixed(0) : '-'}</span></td>
<td id="trend_${i}"><span class="${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'neutral'}">${s.trend_arrow || '-'}</span></td>
<td id="signal_${i}"><span class="tag tag-${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'info'}">${s.top_signal || '-'}</span></td>
<td id="risk_${i}"><span style="color:var(--${riskColor})">${s.risk_level || '-'}</span></td>
</tr>`;
    }).join('');

    const content = `
<div class="flex-between p-24" style="padding-bottom:0">
<div class="flex-row gap-12">
    <button class="btn btn-primary" onclick="addToWatchlist()">+ 添加自选</button>
    <span class="text-sm text-muted">🔄 Auto-refresh: 30s</span>
</div>
<span class="text-sm text-muted">最后更新: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span></span>
</div>
<div style="padding:16px 24px">
<div class="card">
<table>
<thead><tr>
<th>#</th><th>代码</th><th>名称</th><th>最新</th><th>AI评分</th><th>趋势</th><th>信号</th><th>风险</th>
</tr></thead>
<tbody id="watchlistBody">
${rows || '<tr><td colspan="8" class="empty-state">暂无自选股，点击"+ 添加自选"开始</td></tr>'}
</tbody>
</table>
</div>
</div>`;

    const stockCodesJson = JSON.stringify(stocks);

    const extraScript = `
// Watchlist stocks
const WATCH_CODES = ${stockCodesJson};

// Auto-refresh scores
let watchInterval;
async function refreshWatchlist() {
    if (!WATCH_CODES.length) return;
    try {
        const resp = await fetch('${BASE_URL}/signals/batch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({codes: WATCH_CODES, trend: 'up'})
        });
        const data = await resp.json();
        const signals = data.signals || [];
        signals.forEach((s, i) => {
            const idx = WATCH_CODES.indexOf(s.stock_code);
            if (idx < 0) return;
            const sc = s.fusion_score >= 70 ? 'up' : s.fusion_score >= 50 ? 'neutral' : 'down';
            const scoreEl = document.getElementById('score_' + idx);
            const trendEl = document.getElementById('trend_' + idx);
            const signalEl = document.getElementById('signal_' + idx);
            const riskEl = document.getElementById('risk_' + idx);
            if (scoreEl) scoreEl.innerHTML = '<span class="' + sc + '" style="font-weight:700;font-size:16px">' + (s.fusion_score || 50).toFixed(0) + '</span>';
            if (trendEl) trendEl.innerHTML = '<span class="' + (s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'neutral') + '">' + (s.trend_arrow || '→') + '</span>';
            if (signalEl) signalEl.innerHTML = '<span class="tag tag-' + (s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'info') + '">' + (s.top_signal || '-') + '</span>';
            if (riskEl) riskEl.textContent = s.risk_level || '-';
        });
        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
    } catch(e) { console.log('Watchlist refresh skipped'); }
}
function startAutoRefresh() {
    refreshWatchlist();
    watchInterval = setInterval(refreshWatchlist, 30000);
}
function stopAutoRefresh() { clearInterval(watchInterval); }
document.addEventListener('visibilitychange', () => {
    document.hidden ? stopAutoRefresh() : startAutoRefresh();
});
startAutoRefresh();`;

    return pageShell('watchlist', 'Watchlist · 自选股', content, extraScript);
}
