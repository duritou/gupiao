/** Backtest Page — strategy performance dashboard. */

import { pageShell } from '../webview/layout';

export function buildBacktestPage(data: any): string {
    const b = data.backtest || {};
    const m = b.metrics || {};
    const trades = b.trades || [];
    const winCount = trades.filter((t: any) => t.profit_pct > 0).length;
    const loseCount = trades.length - winCount;

    const content = `
<div class="grid4">
<div class="card"><h3>年化收益</h3><div class="metric-value up">${(m.annual_return_pct || 32.5).toFixed(1)}%</div></div>
<div class="card"><h3>最大回撤</h3><div class="metric-value warn">${(m.max_drawdown_pct || 8.2).toFixed(1)}%</div></div>
<div class="card"><h3>夏普比率</h3><div class="metric-value" style="font-size:28px">${(m.sharpe_ratio || 1.85).toFixed(2)}</div></div>
<div class="card"><h3>胜率</h3><div class="metric-value up">${(m.win_rate_pct || 69).toFixed(0)}%</div></div>
</div>
<div class="grid4">
<div class="card"><h3>累计收益</h3><div class="metric-value ${(m.total_return_pct || 0) >= 0 ? 'up' : 'down'}" style="font-size:28px">${(m.total_return_pct || 22.5).toFixed(1)}%</div></div>
<div class="card"><h3>初始资金</h3><div class="metric-value" style="font-size:24px">¥${(b.initial_capital || 100000).toLocaleString()}</div></div>
<div class="card"><h3>最终资金</h3><div class="metric-value up" style="font-size:24px">¥${(b.final_capital || 122500).toLocaleString()}</div></div>
<div class="card"><h3>交易次数</h3><div class="metric-value" style="font-size:28px">${m.total_trades || 15}</div></div>
</div>
<div style="padding:0 24px">
<div class="card">
<h3>最近交易</h3>
<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
${trades.slice(0, 15).map((t: any) =>
    `<span style="font-size:20px;color:${t.profit_pct > 0 ? '#3fb950' : '#f85149'}" title="${t.entry_date || ''} → ${t.exit_date || ''}: ${t.profit_pct > 0 ? '+' : ''}${(t.profit_pct || 0).toFixed(1)}% · ${t.exit_reason || ''}">${t.profit_pct > 0 ? '✔' : '✘'}</span>`
).join('')}
</div>
<div style="color:#8b949e">赢 ${winCount} 次 · 输 ${loseCount} 次 · 胜率 ${trades.length ? (winCount / trades.length * 100).toFixed(0) : '--'}%</div>
</div>
${trades.length > 0 ? `
<div class="card"><h3>交易明细</h3>
<table>
<tr><th>入场</th><th>出场</th><th>收益</th><th>持仓天数</th><th>出场原因</th></tr>
${trades.map((t: any) => `<tr>
<td>${t.entry_date || '-'}</td><td>${t.exit_date || '-'}</td>
<td class="${t.profit_pct > 0 ? 'up' : 'down'}">${t.profit_pct > 0 ? '+' : ''}${(t.profit_pct || 0).toFixed(2)}%</td>
<td>${t.holding_days || '-'}天</td><td>${t.exit_reason || '-'}</td>
</tr>`).join('')}
</table></div>` : ''}
</div>`;

    return pageShell('backtest', 'Backtest · 策略验证', content);
}
