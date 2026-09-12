"use strict";
/** Backtest Page — auditable strategy performance dashboard. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildBacktestPage = buildBacktestPage;
const layout_1 = require("../webview/layout");
function numberValue(value, fallback = 0) {
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
function money(value) {
    return `¥${numberValue(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function percent(value, digits = 1) {
    return `${numberValue(value).toFixed(digits)}%`;
}
function buildBacktestPage(data) {
    const b = data?.backtest || {};
    const m = b?.metrics || {};
    const trades = Array.isArray(b?.trades) ? b.trades : [];
    const quality = b?.data_quality || {};
    const methodology = b?.methodology || {};
    const audit = b?.truth_audit || {};
    const totalTrades = numberValue(m.total_trades, trades.length);
    const winCount = numberValue(m.winning, trades.filter((trade) => numberValue(trade?.profit_pct) > 0).length);
    const loseCount = numberValue(m.losing, Math.max(0, totalTrades - winCount));
    const totalReturn = numberValue(m.total_return_pct);
    const verified = quality.status === 'verified' && quality.integrity_passed === true && quality.is_synthetic === false;
    const statusMessage = b.status && b.status !== 'ok'
        ? `<div class="card" style="border-left:3px solid #d29922"><strong>回测未完成：</strong>${escapeHtml(b.message || b.status)}。页面不会使用演示数据填充。</div>`
        : '';
    const checksum = String(quality.input_checksum_sha256 || '');
    const limitations = Array.isArray(methodology.limitations) ? methodology.limitations : [];
    const isActualPaperRecord = audit.is_actual_paper_trading_record === true;
    const truthLabel = isActualPaperRecord ? '当时真实纸面成交' : '历史K线事后回放';
    const causalityLabel = audit.causality_status === 'retrospective_selection_after_entry'
        ? '选股决策晚于模拟买点，属于事后回放'
        : '历史回测，不代表实时成交';
    const content = `
<div style="padding:16px 24px 0">
${statusMessage}
<div class="card" style="border-left:3px solid ${verified ? '#3fb950' : '#d29922'}">
  <div class="flex-between" style="gap:16px;align-items:flex-start">
    <div>
      <div><span class="stock-name" style="font-size:18px">${escapeHtml(b.stock_name || b.stock_code || '暂无标的')}</span> <span class="stock-code">${escapeHtml(b.stock_code)}</span></div>
      <div class="text-sm text-muted" style="margin-top:6px">单股票技术回测 · ${escapeHtml(b.period || '无有效区间')} · ${numberValue(b.bar_count || quality.bar_count)} 根真实日K线</div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
      <span class="tag ${verified ? 'tag-up' : 'tag-warn'}">${verified ? '行情数据已核验' : '数据需要核验'}</span>
      <span class="tag ${isActualPaperRecord ? 'tag-up' : 'tag-warn'}">${truthLabel}</span>
    </div>
  </div>
  <div class="alert ${isActualPaperRecord ? 'alert-success' : 'alert-warn'}" style="margin-top:12px">
    <strong>真实性结论：</strong>${escapeHtml(audit.plain_language || '本页为历史回测，不等于纸面交易账本。')}<br>
    <span class="text-sm">${escapeHtml(causalityLabel)} · 选股决策 ${escapeHtml(audit.selection_decision_created_at || audit.selection_decision_date || '-')} · 回测运行 ${escapeHtml(audit.backtest_generated_at || b.generated_at || '-')} · 同期纸面账本 ${numberValue(audit.paper_ledger_trade_count_for_symbol_period)} 笔</span>
  </div>
</div>
</div>

<div class="grid4">
<div class="card"><h3>年化收益</h3><div class="metric-value ${numberValue(m.annual_return_pct) >= 0 ? 'up' : 'down'}">${percent(m.annual_return_pct)}</div></div>
<div class="card"><h3>最大回撤</h3><div class="metric-value warn">${percent(m.max_drawdown_pct)}</div></div>
<div class="card"><h3>夏普比率</h3><div class="metric-value" style="font-size:28px">${numberValue(m.sharpe_ratio).toFixed(2)}</div></div>
<div class="card"><h3>胜率</h3><div class="metric-value ${numberValue(m.win_rate_pct) >= 50 ? 'up' : 'warn'}">${totalTrades > 0 ? percent(m.win_rate_pct, 0) : '—'}</div></div>
</div>
<div class="grid4">
<div class="card"><h3>累计收益</h3><div class="metric-value ${totalReturn >= 0 ? 'up' : 'down'}" style="font-size:28px">${percent(totalReturn)}</div></div>
<div class="card"><h3>初始资金</h3><div class="metric-value" style="font-size:24px">${money(b.initial_capital)}</div></div>
<div class="card"><h3>最终资金</h3><div class="metric-value ${numberValue(b.final_capital) >= numberValue(b.initial_capital) ? 'up' : 'down'}" style="font-size:24px">${money(b.final_capital)}</div></div>
<div class="card"><h3>已完成交易</h3><div class="metric-value" style="font-size:28px">${totalTrades}</div><div class="text-sm text-muted">赢 ${winCount} · 输 ${loseCount}</div></div>
</div>

<div style="padding:0 24px">
<div class="grid2" style="padding:0;margin-bottom:8px">
  <div class="card">
    <h3>数据真实性与血缘</h3>
    <table>
      <tr><td>行情是否合成</td><td>${quality.is_synthetic === false ? '否，使用真实历史行情' : '无法确认'}</td></tr>
      <tr><td>成交记录类型</td><td>${escapeHtml(truthLabel)}</td></tr>
      <tr><td>纸面账本匹配</td><td>${numberValue(audit.matched_paper_ledger_legs)} 个成交腿 / 同期 ${numberValue(audit.paper_ledger_trade_count_for_symbol_period)} 笔账本记录</td></tr>
      <tr><td>因果校验</td><td>${escapeHtml(causalityLabel)}</td></tr>
      <tr><td>选股决策时间</td><td>${escapeHtml(audit.selection_decision_created_at || audit.selection_decision_date || '-')}</td></tr>
      <tr><td>回测生成时间</td><td>${escapeHtml(audit.backtest_generated_at || b.generated_at || '-')}</td></tr>
      <tr><td>本地表 / 上游</td><td>${escapeHtml(quality.source_table || '-')} / ${escapeHtml(quality.upstream_source || '-')}</td></tr>
      <tr><td>覆盖区间</td><td>${escapeHtml(quality.first_date || '-')} → ${escapeHtml(quality.last_date || '-')}</td></tr>
      <tr><td>新鲜度</td><td>${quality.freshness_days == null ? '-' : `${numberValue(quality.freshness_days)} 天`} · ${escapeHtml(quality.freshness_state || '-')}</td></tr>
      <tr><td>完整性</td><td>重复日期 ${numberValue(quality.duplicate_dates)} · 无效OHLC ${numberValue(quality.invalid_ohlc_rows)}</td></tr>
      <tr><td>价格口径</td><td>${escapeHtml(quality.price_adjustment || '-')}</td></tr>
      <tr><td>输入校验值</td><td><code title="${escapeHtml(checksum)}">${escapeHtml(checksum ? checksum.slice(0, 20) + '…' : '-')}</code></td></tr>
    </table>
  </div>
  <div class="card">
    <h3>回测口径与限制</h3>
    <table>
      <tr><td>范围</td><td>单股票，不等于AI完整组合</td></tr>
      <tr><td>信号</td><td>${escapeHtml((methodology.signals || []).join(' + ') || '-')}</td></tr>
      <tr><td>买入规则</td><td>${escapeHtml(methodology.buy_rule || '-')}</td></tr>
      <tr><td>成交价格</td><td>${escapeHtml(methodology.execution_price || '-')}</td></tr>
      <tr><td>单次仓位</td><td>${money(methodology.position_size)}</td></tr>
      <tr><td>费用策略</td><td>${escapeHtml(methodology.fee_policy || '-')}</td></tr>
      <tr><td>滑点</td><td>${numberValue(methodology.slippage)}（固定研究假设，已模拟）</td></tr>
    </table>
    ${limitations.length ? `<div class="alert alert-warn" style="margin-top:12px">${limitations.map((item) => `• ${escapeHtml(item)}`).join('<br>')}</div>` : ''}
  </div>
</div>

<div class="card">
<h3>历史回放交易明细（不是纸面账本）</h3>
<div class="alert alert-warn" style="margin-bottom:12px">
  <strong>重要：</strong>本表由当前策略在历史K线上事后重放生成。“模拟买入日/模拟卖出日”只是回测假设，不能证明系统当时实际买入或卖出；真实纸面成交请以持仓中心和交易账本为准。
</div>
${trades.length ? `<div style="overflow-x:auto"><table>
<tr><th>股票</th><th>记录类型</th><th>选股决策时间</th><th>回测生成时间</th><th>账本匹配</th><th>买入信号日</th><th>模拟买入日</th><th>模拟买入价</th><th>数量</th><th>买入金额</th><th>模拟卖出日</th><th>模拟卖出价</th><th>卖出金额</th><th>总费用</th><th>净盈亏</th><th>净收益</th><th>评分</th><th>持有</th><th>卖出原因</th></tr>
${trades.map((trade) => `<tr>
<td><strong>${escapeHtml(trade.stock_name || '-')}</strong><br><span class="stock-code">${escapeHtml(trade.stock_code || '-')}</span></td>
<td>${trade.is_actual_paper_trade === true ? '当时纸面成交' : '历史回放'}<br><span class="text-sm text-muted">${trade.causality_status === 'retrospective_selection_after_entry' ? '事后选股' : '非实时成交'}</span></td>
<td>${escapeHtml(trade.selection_decision_created_at || trade.selection_decision_date || '-')}</td>
<td>${escapeHtml(trade.simulated_at || '-')}</td>
<td>${trade.actual_paper_round_trip_match === true ? '买卖均匹配' : trade.actual_paper_buy_match === true || trade.actual_paper_sell_match === true ? '部分匹配' : '无真实账本成交'}</td>
<td>${escapeHtml(trade.signal_date || trade.entry_signal_date || '-')}</td><td>${escapeHtml(trade.entry_date || '-')}</td><td>${money(trade.entry_price)}</td><td>${numberValue(trade.quantity)}股</td><td>${money(trade.entry_amount)}</td>
<td>${escapeHtml(trade.exit_date || '-')}</td><td>${money(trade.exit_price)}</td><td>${money(trade.exit_amount)}</td><td>${money(trade.total_fees)}</td>
<td class="${numberValue(trade.profit_amount) >= 0 ? 'up' : 'down'}">${money(trade.profit_amount)}</td>
<td class="${numberValue(trade.profit_pct) >= 0 ? 'up' : 'down'}">${numberValue(trade.profit_pct) >= 0 ? '+' : ''}${percent(trade.profit_pct, 2)}</td>
<td>${numberValue(trade.entry_signal_score).toFixed(1)}</td><td>${numberValue(trade.holding_days)}天</td><td>${escapeHtml(trade.exit_reason || '-')}</td>
</tr>`).join('')}
</table></div>` : '<div class="empty-state"><p>本区间没有满足规则的已完成交易；指标保持真实的0，不显示演示值。</p></div>'}
</div>
</div>`;
    return (0, layout_1.pageShell)('backtest', 'Backtest · 可核验策略回测', content);
}
//# sourceMappingURL=backtest.js.map