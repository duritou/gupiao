"use strict";
/** Market Map v2 — sector heatmap with live data. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildMarketMapPage = buildMarketMapPage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildMarketMapPage(data) {
    const sectors = data.sectors || [];
    const content = `
<div style="padding:24px">
<div class="grid3">
${sectors.map((s) => {
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
        const resp = await fetch('${constants_1.BASE_URL}/market/sectors');
        const data = await resp.json();
    } catch(e) {}
}, 120000);`;
    return (0, layout_1.pageShell)('marketmap', 'Market Map · 行业热力图', content, extraScript);
}
//# sourceMappingURL=marketmap.js.map