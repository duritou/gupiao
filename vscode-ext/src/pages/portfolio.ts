/** Portfolio Page v1.0 — Position tracking + AI rescoring. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildPortfolioPage(data: any): string {
    const pf = data.portfolio || {};
    const positions = pf.positions || [];
    const plColor = (pf.total_pl || 0) >= 0 ? 'up' : 'down';
    const plSign = (pf.total_pl || 0) >= 0 ? '+' : '';

    const content = `
<!-- Portfolio Summary -->
<div class="grid4">
<div class="card"><h3>总资产</h3><div class="metric-value" style="font-size:24px">¥${((pf.total_value || 0) / 10000).toFixed(1)}万</div></div>
<div class="card"><h3>总盈亏</h3><div class="metric-value ${plColor}">${plSign}${(pf.total_pl || 0).toFixed(0)}</div><span class="text-sm ${plColor}">${plSign}${(pf.total_pl_pct || 0).toFixed(2)}%</span></div>
<div class="card"><h3>今日盈亏</h3><div class="metric-value ${(pf.daily_pl || 0) >= 0 ? 'up' : 'down'}" style="font-size:28px">${(pf.daily_pl || 0) >= 0 ? '+' : ''}${(pf.daily_pl || 0).toFixed(0)}</div><span class="text-sm">${pf.daily_pl_pct || 0 > 0 ? '+' : ''}${(pf.daily_pl_pct || 0).toFixed(2)}%</span></div>
<div class="card"><h3>AI评分</h3><div class="metric-value ${(pf.avg_ai_score || 50) >= 70 ? 'up' : (pf.avg_ai_score || 50) >= 50 ? 'warn' : 'down'}">${(pf.avg_ai_score || 50).toFixed(0)}</div><span class="text-sm text-muted">${pf.position_count || 0}只持仓</span></div>
</div>

<!-- AI Summary + Risk -->
<div class="grid2">
${pf.ai_summary ? `
<div class="card" style="border-left:3px solid #7C3AED">
<h3>AI 持仓分析</h3>
<p style="font-size:13px;line-height:1.6;color:#9CA3AF;margin-top:4px">${pf.ai_summary}</p>
</div>` : ''}
${pf.risk_summary ? `
<div class="card" style="border-left:3px solid #F59E0B">
<h3>风险评估</h3>
<p style="font-size:13px;color:#9CA3AF;margin-top:4px">${pf.risk_summary}</p>
${pf.top_performer ? `<div style="margin-top:8px;font-size:12px"><span style="color:#22C55E">最佳: ${pf.top_performer}</span></div>` : ''}
${pf.worst_performer ? `<div style="margin-top:4px;font-size:12px"><span style="color:#EF4444">最差: ${pf.worst_performer}</span></div>` : ''}
</div>` : ''}
</div>

<!-- Positions Table -->
<div style="padding:0 24px">
<div class="card">
<div class="card-header"><h3>持仓明细</h3><span class="text-sm text-muted">AI评分 · 每日更新</span></div>
<table>
<thead><tr>
<th>#</th><th>代码</th><th>名称</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>占比</th><th>AI评分</th><th>信号</th><th>风险</th>
</tr></thead>
<tbody>
${positions.map((p: any, i: number) => {
    const plClass = (p.profit_loss || 0) >= 0 ? 'up' : 'down';
    const plSign = (p.profit_loss || 0) >= 0 ? '+' : '';
    const scClass = (p.ai_score || 50) >= 70 ? 'up' : (p.ai_score || 50) >= 50 ? 'warn' : 'down';
    const riskColor = p.risk_level === '极低' || p.risk_level === '低' ? '#22C55E' :
                      p.risk_level === '中' ? '#F59E0B' : '#EF4444';
    const scChange = (p.last_score_change || 0);
    const changeArrow = scChange > 3 ? '↑' : scChange < -3 ? '↓' : '→';
    const changeColor = scChange > 0 ? '#22C55E' : scChange < 0 ? '#EF4444' : '#9CA3AF';

    return `<tr onclick="analyzeStock('${p.stock_code}')" style="cursor:pointer">
<td>${i + 1}</td>
<td class="stock-code">${p.stock_code}</td>
<td class="stock-name">${p.stock_name}</td>
<td>${p.shares}股</td>
<td>¥${(p.cost_price || 0).toFixed(2)}</td>
<td>¥${(p.current_price || 0).toFixed(2)}</td>
<td>¥${((p.market_value || 0) / 10000).toFixed(1)}万</td>
<td><span class="${plClass}" style="font-weight:600">${plSign}${(p.profit_loss || 0).toFixed(0)}</span><br><span class="text-sm ${plClass}">${plSign}${(p.profit_loss_pct || 0).toFixed(1)}%</span></td>
<td>${(p.weight_pct || 0).toFixed(1)}%</td>
<td><span class="${scClass}" style="font-weight:700;font-size:15px">${(p.ai_score || 50).toFixed(0)}</span> <span style="font-size:11px;color:${changeColor}">${changeArrow}</span></td>
<td><span class="tag tag-${p.ai_direction === 'buy' ? 'up' : p.ai_direction === 'sell' ? 'down' : 'info'}">${p.ai_signal || '-'}</span></td>
<td><span style="color:${riskColor};font-size:12px">${p.risk_level || '-'}</span></td>
</tr>`;
}).join('') || '<tr><td colspan="12" class="empty-state">暂无持仓数据</td></tr>'}
</tbody>
</table>
</div>
</div>

<div style="text-align:center;padding:16px" class="text-muted text-sm">
数据更新: ${pf.date || '--'} · AI评分每日自动刷新
</div>`;

    return pageShell('portfolio', 'Portfolio · 持仓中心', content, `
// Auto-refresh portfolio every 120s
setInterval(async () => {
    try { await fetch('${BASE_URL}/portfolio/overview'); } catch(e) {}
}, 120000);
`);
}
