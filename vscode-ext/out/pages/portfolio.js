"use strict";
/** Portfolio Page v1.0 — Position tracking + AI rescoring. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildPortfolioPage = buildPortfolioPage;
const layout_1 = require("../webview/layout");
const score_display_1 = require("../webview/score-display");
function buildPortfolioPage(data) {
    const pf = data.portfolio || {};
    const positions = pf.positions || [];
    const trades = pf.trades || [];
    const orderRejections = pf.order_rejections || [];
    const plColor = (pf.total_pl || 0) >= 0 ? 'up' : 'down';
    const plSign = (pf.total_pl || 0) >= 0 ? '+' : '';
    const dailyPl = Number(pf.daily_pl || 0);
    const dailyPlPct = Number(pf.daily_pl_pct || 0);
    const dailySign = dailyPl >= 0 ? '+' : '';
    const valuationFresh = pf.valuation_status === 'fresh';
    const formatTradeTime = (value) => {
        if (!value) {
            return '--';
        }
        return value.replace('T', ' ').replace(/([+-]\d\d:\d\d|Z)$/, '').slice(0, 19);
    };
    const rejectionReason = (value) => ({
        quote_not_after_signal: '报价时间不晚于信号时间',
        stale_exchange_quote: '交易所报价已过期',
        quote_outside_market_session: '报价不在支持的连续竞价时段',
        quote_received_outside_market_session: '收到报价时已不在交易时段',
        future_dated_exchange_quote: '报价时间来自未来',
        data_cutoff_after_signal: '策略使用了信号之后的数据',
        quote_date_timestamp_mismatch: '行情日期与交易所时间不一致',
        unverified_execution_quote_source: '行情源未通过校验',
        missing_or_invalid_exchange_timestamp: '缺少有效交易所时间戳',
        missing_or_invalid_signal_timestamp: '缺少有效策略信号时间',
        execution_before_quote_received: '模拟成交早于报价到达',
        quote_processing_delay_exceeded: '报价到记账耗时超过10秒',
        market_closed: '当前不在可成交交易时段',
        weekend: '周末休市',
        execution_date_mismatch: '模拟成交日期与交易日不一致',
        invalid_execution_timestamp: '模拟成交时间无效',
        trading_calendar_unverified: '未能验证当日交易日历',
        market_holiday: 'A股休市日',
        no_verified_post_signal_quote: '未取得信号后的合格实时报价',
    }[value] || value || '未说明');
    const content = `
<!-- Portfolio Summary -->
<div class="grid4">
<div class="card"><h3>总资产</h3><div class="metric-value" style="font-size:24px">¥${((pf.total_value || 0) / 10000).toFixed(1)}万</div></div>
<div class="card"><h3>总盈亏</h3><div class="metric-value ${plColor}">${plSign}${(pf.total_pl || 0).toFixed(0)}</div><span class="text-sm ${plColor}">${plSign}${(pf.total_pl_pct || 0).toFixed(2)}%</span></div>
<div class="card"><h3>今日盈亏</h3><div class="metric-value ${dailyPl >= 0 ? 'up' : 'down'}" style="font-size:28px">${dailySign}${dailyPl.toFixed(0)}</div><span class="text-sm ${dailyPl >= 0 ? 'up' : 'down'}">${dailySign}${dailyPlPct.toFixed(2)}%</span></div>
<div class="card"><h3>AI评分</h3><div class="metric-value ${(0, score_display_1.scoreTone)((0, score_display_1.finiteScore)(pf.avg_ai_score))}">${(0, score_display_1.scoreText)(pf.avg_ai_score)}</div><span class="text-sm text-muted">${pf.position_count || 0}只持仓</span></div>
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
${positions.map((p, i) => {
        const plClass = (p.profit_loss || 0) >= 0 ? 'up' : 'down';
        const plSign = (p.profit_loss || 0) >= 0 ? '+' : '';
        const positionScore = (0, score_display_1.finiteScore)(p.ai_score);
        const scClass = (0, score_display_1.scoreTone)(positionScore);
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
<td><span class="${scClass}" style="font-weight:700;font-size:15px">${(0, score_display_1.scoreText)(positionScore)}</span> <span style="font-size:11px;color:${changeColor}">${changeArrow}</span></td>
<td><span class="tag tag-${p.ai_direction === 'buy' ? 'up' : p.ai_direction === 'sell' ? 'down' : 'info'}">${p.ai_signal || '-'}</span></td>
<td><span style="color:${riskColor};font-size:12px">${p.risk_level || '-'}</span></td>
</tr>`;
    }).join('') || '<tr><td colspan="12" class="empty-state">暂无持仓数据</td></tr>'}
</tbody>
</table>
</div>
</div>

<!-- Trade Timeline -->
<div style="padding:12px 24px 0">
<div class="card">
<div class="card-header">
<h3>模拟交易记录</h3>
<div style="display:flex;gap:8px">
<input id="tradeSearch" oninput="filterTrades()" placeholder="查询代码或名称" style="width:150px">
<select id="tradeAction" onchange="filterTrades()">
<option value="">全部方向</option><option value="BUY">买入</option><option value="SELL">卖出</option>
</select>
</div>
</div>
<div style="overflow-x:auto">
<table id="tradeTable">
<thead><tr>
<th>策略信号时间（非成交）</th><th>实际模拟成交时间</th><th>方向</th><th>股票</th><th>数量</th>
<th>成交价</th><th>成交额</th><th>佣金</th><th>印花税</th><th>费用合计</th><th>交易所报价时间</th><th>报价到达时间</th><th>行情源</th><th>时间可信度</th>
</tr></thead>
<tbody>
${trades.map((t) => {
        const action = String(t.action || '').toUpperCase();
        const sideClass = action === 'BUY' ? 'up' : 'down';
        const search = `${t.stock_code || ''} ${t.stock_name || ''}`.toLowerCase();
        return `<tr data-action="${action}" data-search="${search}">
<td>${formatTradeTime(t.signal_at)}</td>
<td>${formatTradeTime(t.execution_at || t.created_at)}</td>
<td><span class="${sideClass}" style="font-weight:700">${action === 'BUY' ? '买入' : '卖出'}</span></td>
<td><span class="stock-code">${t.stock_code || ''}</span><br><span class="text-sm">${t.stock_name || ''}</span></td>
<td>${Number(t.shares || 0)}股</td>
<td>¥${Number(t.price || 0).toFixed(3)}</td>
<td>¥${Number(t.gross_amount || t.value || 0).toFixed(2)}</td>
<td>¥${Number(t.commission || 0).toFixed(2)}</td>
<td>¥${Number(t.stamp_tax || 0).toFixed(2)}</td>
<td>¥${Number(t.total_fees || t.fee || 0).toFixed(2)}</td>
<td>${formatTradeTime(t.quote_exchange_at)}</td>
<td>${formatTradeTime(t.quote_fetched_at)}</td>
<td>${t.price_source || '--'}</td>
<td>${t.causality_status === 'verified_post_signal_quote' ? '信号后实时报价' : t.causality_status === 'verified_historical_bar_replay' ? '历史开盘价重放' : '待核验'}</td>
</tr>`;
    }).join('') || '<tr><td colspan="14" class="empty-state">暂无模拟成交</td></tr>'}
</tbody>
</table>
</div>
<div class="text-sm text-muted" style="margin-top:10px">
信号时间只表示策略何时产生判断，盘后信号不会在盘后成交；系统会等待下一可交易时段再执行。<br>
佣金：买入、卖出均按万5；印花税：仅卖出按万5。累计佣金 ¥${Number(pf.total_commission || 0).toFixed(2)}，累计印花税 ¥${Number(pf.total_stamp_tax || 0).toFixed(2)}。
</div>
</div>
</div>

<!-- Rejected Orders -->
<div style="padding:12px 24px 0">
<div class="card">
<div class="card-header"><h3>被拦截的模拟委托</h3><span class="text-sm text-muted">未成交，不计入收益</span></div>
<div style="overflow-x:auto">
<table>
<thead><tr><th>信号时间</th><th>拦截时间</th><th>方向</th><th>股票</th><th>候选价</th><th>交易所报价时间</th><th>拦截原因</th></tr></thead>
<tbody>
${orderRejections.map((r) => `<tr>
<td>${formatTradeTime(r.signal_at)}</td>
<td>${formatTradeTime(r.execution_at)}</td>
<td>${String(r.direction || '').toUpperCase() || '--'}</td>
<td><span class="stock-code">${r.stock_code || ''}</span><br><span class="text-sm">${r.stock_name || ''}</span></td>
<td>${Number(r.quote_price || 0) > 0 ? `¥${Number(r.quote_price).toFixed(3)}` : '--'}</td>
<td>${formatTradeTime(r.quote_exchange_at)}</td>
<td><span class="down">${rejectionReason(r.reason)}</span></td>
</tr>`).join('') || '<tr><td colspan="7" class="empty-state">暂无被拦截的模拟委托</td></tr>'}
</tbody>
</table>
</div>
</div>
</div>

<div style="text-align:center;padding:16px" class="text-muted text-sm">
行情日期: ${pf.price_date || '--'} · 覆盖率 ${((pf.price_coverage || 0) * 100).toFixed(0)}% · ${valuationFresh ? '数据新鲜' : '存在旧行情，请勿据此判断收益'}<br>
账本质量: ${pf.ledger_quality === 'forward_only_causal_simulation' ? '仅前瞻因果模拟' : pf.ledger_quality === 'verified_real_prices' ? '真实价格已验证' : '历史成交未验证'} · 成交规则: ${pf.price_policy || '--'}
<br>因果执行: ${pf.execution_policy === 'post_signal_fresh_exchange_quote_v1' ? '先生成信号，再取新报价；禁止未来数据' : '旧规则，待升级'}
</div>`;
    return (0, layout_1.pageShell)('portfolio', 'Portfolio · 持仓中心', content, `
// Auto-refresh and re-render portfolio every 120s.
setInterval(() => vscode.postMessage({command:'refreshPage'}), 120000);
function filterTrades() {
    const keyword = (document.getElementById('tradeSearch')?.value || '').trim().toLowerCase();
    const action = document.getElementById('tradeAction')?.value || '';
    document.querySelectorAll('#tradeTable tbody tr[data-action]').forEach((row) => {
        const matchesKeyword = !keyword || (row.dataset.search || '').includes(keyword);
        const matchesAction = !action || row.dataset.action === action;
        row.style.display = matchesKeyword && matchesAction ? '' : 'none';
    });
}
`);
}
//# sourceMappingURL=portfolio.js.map