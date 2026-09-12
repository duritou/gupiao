"use strict";
/** Timeline Page — score evolution over time with explanations. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildTimelinePage = buildTimelinePage;
const layout_1 = require("../webview/layout");
function finiteNumber(value, fallback = 0) {
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
function buildTimelinePage(data) {
    const result = data?.timeline || {};
    const entries = (Array.isArray(result.entries) ? result.entries : []).map((entry) => ({
        ...entry,
        date: String(entry?.date || ''),
        score: finiteNumber(entry?.score, 50),
        change: finiteNumber(entry?.change, 0),
        direction: entry?.direction === 'up' ? 'up' : entry?.direction === 'down' ? 'down' : 'flat',
        events: Array.isArray(entry?.events) ? entry.events : [],
    }));
    const stockCode = String(result.stock_code || '');
    const stockName = String(result.stock_name || '');
    const currentScore = result.current_score == null ? null : finiteNumber(result.current_score, 50);
    const totalChange = finiteNumber(result.total_change, 0);
    const errorHtml = data?.timelineError
        ? `<div class="card" style="border-left:3px solid #f85149">
<div class="flex-between"><span>Timeline 加载失败：${escapeHtml(data.timelineError)}</span>
<button class="btn" onclick="retryTimeline()">重试</button></div>
</div>`
        : '';
    // Build a mini ASCII-style chart using divs
    const scores = entries.map((e) => e.score);
    const maxScore = Math.max(...scores, 50);
    const minScore = Math.min(...scores, 50);
    const range = maxScore - minScore || 1;
    const chartHeight = 8; // rows
    let chartHtml = '<pre style="margin:0;font-family:monospace;font-size:11px;line-height:1.8;color:#8b949e;white-space:pre;overflow-x:auto">';
    for (let row = chartHeight - 1; row >= 0; row--) {
        const level = minScore + (range * row) / (chartHeight - 1 || 1);
        chartHtml += `<span style="color:#8b949e">${level.toFixed(0).padStart(3)}</span> `;
        for (let col = 0; col < entries.length; col++) {
            const normY = (entries[col].score - minScore) / range;
            const expectedRow = Math.round(normY * (chartHeight - 1));
            if (expectedRow === row) {
                const color = entries[col].direction === 'up' ? '#3fb950' : entries[col].direction === 'down' ? '#f85149' : '#8b949e';
                chartHtml += `<span style="color:${color}">●</span>`;
            }
            else if (col > 0) {
                const prevNormY = (entries[col - 1].score - minScore) / range;
                const prevRow = Math.round(prevNormY * (chartHeight - 1));
                if ((row > Math.min(prevRow, expectedRow)) && (row < Math.max(prevRow, expectedRow))) {
                    chartHtml += '<span style="color:#30363d">│</span>';
                }
                else {
                    chartHtml += ' ';
                }
            }
            else {
                chartHtml += ' ';
            }
        }
        chartHtml += '\n';
    }
    // X axis
    chartHtml += '<span style="color:#30363d">    ├</span>' + '─'.repeat(entries.length) + '\n';
    chartHtml += '     ';
    const step = Math.max(1, Math.floor(entries.length / 6));
    for (let i = 0; i < entries.length; i += step) {
        const d = entries[i].date || '';
        chartHtml += d.slice(5); // MM-DD
        chartHtml += ' '.repeat(Math.max(1, step * 1 - (d.length - 5)));
    }
    chartHtml += '</pre>';
    const content = `
<div style="padding:16px 24px">
${errorHtml}
<div class="card">
<div class="flex-row gap-8" style="margin-bottom:16px">
    <input type="text" id="timelineCode" placeholder="股票代码，如 600613" value="${escapeHtml(stockCode)}" style="width:200px">
    <button class="btn btn-primary" onclick="loadTimeline()">查看</button>
</div>
<div id="timelineInputError" class="text-sm" style="display:none;color:#f85149;margin-top:-8px;margin-bottom:12px"></div>
${currentScore != null ? `
<div class="flex-between mb-16">
    <div><span class="stock-name">${escapeHtml(stockName || stockCode)}</span> <span class="stock-code">${escapeHtml(stockCode)}</span></div>
    <div><span class="metric-value ${totalChange >= 0 ? 'up' : 'down'}" style="font-size:28px">${currentScore.toFixed(0)}</span>
    <span class="text-sm ${totalChange >= 0 ? 'up' : 'down'}">${totalChange >= 0 ? '+' : ''}${totalChange.toFixed(1)}（${entries.length}个交易日）</span></div>
</div>` : ''}
</div>

<div class="card">
<h3>Score Timeline (${entries.length}天)</h3>
<div class="timeline-chart">${entries.length ? chartHtml : '<p class="text-muted">暂无该股票的历史评分。完成一次 AI 分析后会在这里形成时间线。</p>'}</div>
</div>

<div class="card">
<h3>最近变化</h3>
<div id="timelineEvents">
${entries.slice(-6).reverse().map((e) => {
        const changeStr = e.change >= 0 ? `+${e.change.toFixed(1)}` : e.change.toFixed(1);
        const dirColor = e.direction === 'up' ? '#3fb950' : e.direction === 'down' ? '#f85149' : '#8b949e';
        return `<div class="evidence-card" style="border-left:3px solid ${dirColor}">
<div class="flex-between">
<span style="font-weight:600">${escapeHtml(e.date)} · Score ${e.score.toFixed(0)}</span>
<span style="color:${dirColor};font-weight:700">${changeStr}</span>
</div>
${(e.events || []).map((ev) => `
<div class="ev-desc" style="margin-top:4px">
<span style="color:${finiteNumber(ev?.impact) >= 0 ? '#3fb950' : '#f85149'}">${escapeHtml(ev?.impact)}</span>
· ${escapeHtml(ev?.event)} <span class="tag tag-info">${escapeHtml(ev?.source)}</span>
</div>`).join('')}
</div>`;
    }).join('') || '<p class="text-muted">点击"查看"加载评分演变</p>'}
</div>
</div>
</div>`;
    const extraScript = `
function loadTimeline() {
    const input = document.getElementById('timelineCode');
    const error = document.getElementById('timelineInputError');
    const code = input.value.trim().toUpperCase();
    if (!code) return;
    if (!/^\\d{6}(\\.(SH|SZ|BJ))?$/.test(code)) {
        error.textContent = '请输入6位股票代码，可选 .SH、.SZ 或 .BJ 后缀';
        error.style.display = 'block';
        input.focus();
        return;
    }
    error.style.display = 'none';
    vscode.postMessage({command:'timeline',code:code});
}
document.getElementById('timelineCode').addEventListener('keydown', function(event) {
    if (event.key === 'Enter') loadTimeline();
});
function retryTimeline() {
    vscode.postMessage({command:'refreshPage'});
}
`;
    return (0, layout_1.pageShell)('timeline', 'Timeline · 评分演变', content, extraScript);
}
//# sourceMappingURL=timeline.js.map