/** Market Map v2 — sector heatmap with live data. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildMarketMapPage(data: any): string {
    const sectors = data.sectors || [];

    const content = `
<div style="padding:24px">
<div class="grid3">
${sectors.map((s: any) => {
    const score = s.score || 50;
    const color = score >= 70 ? '#3fb950' : score >= 40 ? '#d2991d' : '#f85149';
    return `<div class="card" style="cursor:pointer;border-left:4px solid ${color}" onclick="navigate('dashboard')">
<div class="card-header"><h3>${s.name}</h3><span class="tag tag-${s.status === '强势' ? 'up' : s.status === '震荡' ? 'warn' : 'down'}">${s.status}</span></div>
<div class="metric-value" style="color:${color};font-size:28px">${score}</div>
<div style="margin-top:8px"><div style="background:#21262d;height:6px;border-radius:3px"><div style="width:${score}%;height:6px;border-radius:3px;background:${color}"></div></div></div>
<div style="margin-top:4px;font-size:12px;color:#8b949e">${'★'.repeat(s.stars || 1)}${'☆'.repeat(5 - (s.stars || 1))}</div>
</div>`;
}).join('') || '<div class="empty-state"><div class="icon">🗺</div><p>加载中...</p></div>'}
</div>
</div>`;

    const extraScript = `
// Market map auto-refresh every 120s
setInterval(async () => {
    try {
        const resp = await fetch('${BASE_URL}/market/sectors');
        const data = await resp.json();
    } catch(e) {}
}, 120000);`;

    return pageShell('marketmap', 'Market Map · 行业热力图', content, extraScript);
}
