/** Timeline Page — score evolution over time with explanations. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildTimelinePage(data: any): string {
    const result = data.timeline || {};
    const entries = result.entries || [];
    const stockCode = result.stock_code || '600519.SH';
    const stockName = result.stock_name || '';

    // Build a mini ASCII-style chart using divs
    const scores = entries.map((e: any) => e.score);
    const maxScore = Math.max(...scores, 50);
    const minScore = Math.min(...scores, 50);
    const range = maxScore - minScore || 1;
    const chartHeight = 8; // rows

    let chartHtml = '<div style="font-family:monospace;font-size:11px;line-height:1.8;color:#8b949e">';
    for (let row = chartHeight - 1; row >= 0; row--) {
        const level = minScore + (range * row) / (chartHeight - 1 || 1);
        chartHtml += `<span style="color:#8b949e">${level.toFixed(0).padStart(3)}</span> `;
        for (let col = 0; col < entries.length; col++) {
            const normY = (entries[col].score - minScore) / range;
            const expectedRow = Math.round(normY * (chartHeight - 1));
            if (expectedRow === row) {
                const color = entries[col].direction === 'up' ? '#3fb950' : entries[col].direction === 'down' ? '#f85149' : '#8b949e';
                chartHtml += `<span style="color:${color}">●</span>`;
            } else if (col > 0) {
                const prevNormY = (entries[col - 1].score - minScore) / range;
                const prevRow = Math.round(prevNormY * (chartHeight - 1));
                if ((row > Math.min(prevRow, expectedRow)) && (row < Math.max(prevRow, expectedRow))) {
                    chartHtml += '<span style="color:#30363d">│</span>';
                } else {
                    chartHtml += ' ';
                }
            } else {
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
    chartHtml += '</div>';

    const content = `
<div style="padding:16px 24px">
<div class="card">
<div class="flex-row gap-8" style="margin-bottom:16px">
    <input type="text" id="timelineCode" placeholder="股票代码" value="${stockCode}" style="width:160px">
    <button class="btn btn-primary" onclick="loadTimeline()">查看</button>
</div>
${result.current_score != null ? `
<div class="flex-between mb-16">
    <div><span class="stock-name">${stockName || stockCode}</span> <span class="stock-code">${stockCode}</span></div>
    <div><span class="metric-value ${result.total_change >= 0 ? 'up' : 'down'}" style="font-size:28px">${result.current_score.toFixed(0)}</span>
    <span class="text-sm ${result.total_change >= 0 ? 'up' : 'down'}">${result.total_change >= 0 ? '+' : ''}${result.total_change.toFixed(1)} (30天)</span></div>
</div>` : ''}
</div>

<div class="card">
<h3>Score Timeline (${entries.length}天)</h3>
<div class="timeline-chart">${chartHtml}</div>
</div>

<div class="card">
<h3>最近变化</h3>
<div id="timelineEvents">
${entries.slice(-6).reverse().map((e: any) => {
    const changeStr = e.change >= 0 ? `+${e.change.toFixed(1)}` : e.change.toFixed(1);
    const dirColor = e.direction === 'up' ? '#3fb950' : e.direction === 'down' ? '#f85149' : '#8b949e';
    return `<div class="evidence-card" style="border-left:3px solid ${dirColor}">
<div class="flex-between">
<span style="font-weight:600">${e.date} · Score ${e.score.toFixed(0)}</span>
<span style="color:${dirColor};font-weight:700">${changeStr}</span>
</div>
${(e.events || []).map((ev: any) => `
<div class="ev-desc" style="margin-top:4px">
<span style="color:${parseFloat(ev.impact) >= 0 ? '#3fb950' : '#f85149'}">${ev.impact}</span>
· ${ev.event} <span class="tag tag-info">${ev.source}</span>
</div>`).join('')}
</div>`;
}).join('') || '<p class="text-muted">点击"查看"加载评分演变</p>'}
</div>
</div>
</div>`;

    const extraScript = `
async function loadTimeline() {
    const code = document.getElementById('timelineCode').value.trim();
    if (!code) return;
    vscode.postMessage({command:'navigate',page:'timeline',code:code});
}
`;

    return pageShell('timeline', 'Timeline · 评分演变', content, extraScript);
}
