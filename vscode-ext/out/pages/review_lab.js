"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildReviewLabPage = buildReviewLabPage;
const layout_1 = require("../webview/layout");
function escapeHtml(value) {
    return String(value ?? '--').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char] || char));
}
function renderTrade(trade) {
    return `<tr><td>${escapeHtml(trade.symbol)}</td><td>${escapeHtml(trade.buy_date)}</td>
<td>${escapeHtml(trade.sell_date)}</td><td>${escapeHtml(trade.quantity)}</td>
<td>${escapeHtml(trade.entry_price)}</td><td>${escapeHtml(trade.exit_price)}</td>
<td class="${Number(trade.net_pnl) >= 0 ? 'up' : 'down'}">${escapeHtml(trade.net_pnl)}</td></tr>`;
}
function buildReviewLabPage(data) {
    const latest = data.latest || null;
    const runs = Array.isArray(data.runs) ? data.runs : [];
    const trades = Array.isArray(latest?.trades) ? latest.trades : [];
    const rejected = Array.isArray(latest?.rejected) ? latest.rejected : [];
    const learning = Array.isArray(latest?.learning) ? latest.learning : [];
    const latestBlock = latest ? `
<div class="grid4" style="padding:16px 24px 0">
<div class="card"><h3>复盘日期</h3><div class="metric-value" style="font-size:22px">${escapeHtml(latest.date)}</div></div>
<div class="card"><h3>模拟净结果</h3><div class="metric-value ${Number(latest.net_pnl) >= 0 ? 'up' : 'down'}" style="font-size:22px">${escapeHtml(latest.net_pnl)} 元</div></div>
<div class="card"><h3>模拟成交</h3><div class="metric-value" style="font-size:22px">${trades.length} 笔</div></div>
<div class="card"><h3>运行标识</h3><div class="text-sm" style="overflow-wrap:anywhere">${escapeHtml(latest.run_id || data.selectedRunId || '--')}</div></div>
</div>
<div class="card" style="margin:16px 24px"><h3>本次闭环</h3>
<p class="text-sm">使用历史数据先决策、下一交易日模拟买入、再下一交易日模拟卖出；周五收盘没有倒推买点。</p>
<p class="text-sm text-muted">数据指纹：${escapeHtml(latest.input_sha256)} · 来源：${escapeHtml(latest.source)}</p>
<p class="text-sm text-muted">执行：${escapeHtml(latest.execution)} · 费用：${escapeHtml(latest.fee_assumptions)}</p></div>
<div class="card" style="margin:0 24px 16px"><h3>模拟交易明细</h3>
${trades.length ? `<table><thead><tr><th>标的</th><th>买入日</th><th>卖出日</th><th>数量</th><th>买价</th><th>卖价</th><th>净结果</th></tr></thead><tbody>${trades.map(renderTrade).join('')}</tbody></table>` : '<p class="text-muted">没有符合条件的模拟成交。</p>'}
${rejected.length ? `<p class="text-sm text-muted" style="margin-top:12px">未入场：${rejected.map(item => `${escapeHtml(item.symbol)}（${escapeHtml(item.reason)}）`).join('、')}</p>` : ''}</div>
<div class="card" style="margin:0 24px 16px"><h3>测试学习总结</h3>
${learning.length ? `<ul>${learning.map((item) => `<li style="margin:6px 0">${escapeHtml(item)}</li>`).join('')}</ul>` : '<p class="text-muted">暂无独立学习记录。</p>'}</div>`
        : `<div class="empty-state"><div class="icon">🧪</div><h2>暂无最新测试复盘</h2><p>没有生成结果，不会调用主流程补采或虚构结论。</p></div>`;
    const history = runs.length ? runs.map(run => `<tr><td>${escapeHtml(run)}</td><td><button class="btn btn-sm" onclick="openReviewHistory('${escapeHtml(run)}')">查看</button></td></tr>`).join('')
        : '<tr><td colspan="2" class="text-muted">暂无历史记录</td></tr>';
    const content = `<div style="padding:22px 24px 8px"><div class="flex-between" style="align-items:flex-start;gap:16px;flex-wrap:wrap">
<div><h1 style="font-size:20px;color:#A78BFA;margin-bottom:4px">测试复盘 · 最新结果</h1>
<div style="font-size:12px;color:#8b949e">独立只读模块 · 仅供参考 · 不参与主系统选股、交易或学习</div></div>
<span style="font-size:11px;color:#22C55E;border:1px solid #14532D;background:#052E16;padding:4px 8px;border-radius:999px">✓ Reference Only</span></div></div>
<div style="padding:0 24px 8px"><button class="btn btn-primary" onclick="openReviewLatest()">显示最新</button><button class="btn" style="margin-left:8px" onclick="refreshReviewLab()">刷新</button></div>
${latestBlock}<div class="card" style="margin:0 24px 24px"><h3>历史记录</h3><p class="text-sm text-muted">历史运行只读保存；不会覆盖最新结果，也不会回写生产数据库。</p>
<table><thead><tr><th>运行 ID</th><th>操作</th></tr></thead><tbody>${history}</tbody></table></div>`;
    const extraScript = `function openReviewHistory(runId){vscode.postMessage({command:'reviewLabHistory',runId});}
function openReviewLatest(){vscode.postMessage({command:'navigate',page:'review_lab'});}
function refreshReviewLab(){vscode.postMessage({command:'refreshPage'});}`;
    return (0, layout_1.pageShell)('review_lab', '测试复盘 · 最新结果', content, extraScript);
}
//# sourceMappingURL=review_lab.js.map