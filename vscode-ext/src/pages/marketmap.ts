/** Market Map v2 — sector heatmap with live data. */

import { pageShell } from '../webview/layout';
import { finiteScore, scoreText } from '../webview/score-display';

export function buildMarketMapPage(data: any): string {
    const sectors = data.sectors || [];
    const isLive = data.is_live !== false;
    const isProxy = data.is_proxy === true;
    const dataSource = data.data_source || 'unknown';
    const message = data.message || '';
    const refreshing = data.refreshing === true;
    const fetchedAt = data.fetched_at || '';

    // 数据源状态提示
    const statusBanner = (refreshing || isProxy || (!isLive && sectors.length > 0))
        ? `<div class="alert alert-warn" style="margin-bottom:16px">
            <span style="font-size:14px">${refreshing ? '⏳' : isProxy ? 'ℹ️' : '⚠️'} ${message || '实时数据源暂时不可用，显示参考板块列表'}</span>
           </div>`
        : '';

    const sourceLabel = isProxy ? ' · 行业ETF代理' : isLive ? ' · 实时快照' : '';

    const content = `
<div style="padding:24px">
${statusBanner}
<div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:12px;color:#8b949e;font-size:12px">
<span>数据源：${dataSource}${sourceLabel}</span>
<span>${fetchedAt ? `更新时间：${fetchedAt.replace('T', ' ')}` : ''}</span>
</div>
<div class="grid3">
${sectors.map((s: any) => {
    const score = finiteScore(s.score);
    const color = score === null ? '#6B7280' : score >= 70 ? '#3fb950' : score >= 40 ? '#d2991d' : '#f85149';
    const statusClass = s.status === '强势' ? 'up' : s.status === '震荡' ? 'warn' : s.status === '暂无数据' ? 'muted' : 'down';
    return `<div class="card" style="cursor:pointer;border-left:4px solid ${color}" onclick="navigate('dashboard')">
<div class="card-header"><h3>${s.name}</h3><span class="tag tag-${statusClass}">${s.status}</span></div>
<div class="metric-value" style="color:${color};font-size:28px">${scoreText(score)}</div>
<div style="margin-top:8px"><div style="background:#21262d;height:6px;border-radius:3px"><div style="width:${score === null ? 0 : score}%;height:6px;border-radius:3px;background:${color}"></div></div></div>
<div style="margin-top:4px;font-size:12px;color:#8b949e">${'★'.repeat(s.stars || 1)}${'☆'.repeat(5 - (s.stars || 1))}</div>
</div>`;
}).join('') || '<div class="empty-state"><div class="icon">🗺</div><p>暂无数据</p></div>'}
</div>
</div>`;

    const extraScript = `
// A cold page returns immediately while the backend performs one bounded refresh.
${refreshing ? "setTimeout(() => vscode.postMessage({command:'refreshPage', soft:true}), 3000);" : ''}
setInterval(() => vscode.postMessage({command:'refreshPage'}), 120000);`;

    return pageShell('marketmap', 'Market Map · 行业热力图', content, extraScript);
}
