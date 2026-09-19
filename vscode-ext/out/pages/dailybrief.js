"use strict";
/** Daily Brief v2 — auto-generated morning report. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.getDailyBriefState = getDailyBriefState;
exports.buildDailyBriefPage = buildDailyBriefPage;
const layout_1 = require("../webview/layout");
const score_display_1 = require("../webview/score-display");
function getDailyBriefState(data) {
    if (data?.pageError) {
        return data.pageErrorKind === 'timeout' ? 'timeout' : 'request';
    }
    const brief = data?.brief;
    if (!brief || typeof brief !== 'object' || Object.keys(brief).length === 0)
        return 'empty';
    const declared = brief.data_status?.state;
    if (declared === 'collecting')
        return 'collecting';
    if (declared === 'empty')
        return 'empty';
    if (brief.data_status?.available === false)
        return 'empty';
    return brief.data_status?.degraded ? 'degraded' : 'ready';
}
function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char] || char));
}
function buildDailyBriefPage(data) {
    const brief = data.brief || {};
    const sentiment = brief.market_sentiment || {};
    const marketRegime = brief.market_regime || {};
    const pipelineAcceptance = brief.pipeline_acceptance || {};
    const pipelineRunId = String(pipelineAcceptance.run_id || '').trim();
    const decisionDate = String(brief.decision_date || pipelineAcceptance.decision_date || brief.date || '').trim();
    const opportunities = (brief.top_opportunities || []).filter((item) => {
        if (item.recommendation_tier === 'technical_watchlist')
            return false;
        if (decisionDate && item.decision_date && item.decision_date !== decisionDate)
            return false;
        if (pipelineRunId && item.run_id && item.run_id !== pipelineRunId)
            return false;
        return true;
    });
    const patternWatchlist = brief.pattern_watchlist || [];
    const risks = brief.risk_warnings || [];
    const shortTermSentiment = brief.short_term_sentiment || {};
    const topVolumeStocks = brief.top_volume_stocks || [];
    const dataStatus = brief.data_status || {};
    const components = dataStatus.components || {};
    const state = getDailyBriefState(data);
    const lastSuccessfulAt = data.lastSuccessfulAt || '';
    const hasStaleData = state === 'request' || state === 'timeout'
        ? Boolean(data.pageState === 'stale' && lastSuccessfulAt && data.brief)
        : false;
    const stars = Number(sentiment.stars || 0);
    const starStr = '★'.repeat(stars) + '☆'.repeat(5 - stars);
    const statusText = hasStaleData
        ? `刷新失败，降级展示最近成功数据（${escapeHtml(lastSuccessfulAt)}）`
        : state === 'timeout'
            ? '简报请求超时'
            : state === 'request'
                ? '简报请求失败'
                : state === 'collecting'
                    ? '数据正在收集'
                    : state === 'empty'
                        ? '暂无可用数据'
                        : dataStatus.degraded
                            ? '部分数据源不可用'
                            : '全部数据源正常';
    const stateBanner = state === 'request' || state === 'timeout'
        ? `<div style="color:#f85149">${escapeHtml(data.pageError)}</div>`
        : state === 'collecting'
            ? '<div style="color:#d29922">后端已报告正在收集数据，当前没有可展示的完整快照。</div>'
            : state === 'empty'
                ? '<div style="color:#d29922">当前没有可用的简报数据，请在数据源完成后重试。</div>'
                : '';
    const marketSummaryFallback = state === 'collecting'
        ? '市场数据正在收集，暂未形成可用快照。'
        : state === 'empty'
            ? '暂无市场概况数据。'
            : '市场概况暂不可用。';
    const oneLinerFallback = state === 'collecting'
        ? '市场数据正在收集，暂未形成今日结论。'
        : state === 'empty'
            ? '暂无今日简报结论。'
            : '今日简报结论暂不可用。';
    const regimeCard = `
<div class="card"><h3>Market Regime / Market Environment</h3>
<p style="font-size:16px;font-weight:700">${marketRegime.state || 'unknown'} · ${Number(marketRegime.score ?? 50).toFixed(0)}/100</p>
<p class="text-muted mt-8">confidence ${Number(marketRegime.confidence || 0).toFixed(2)}${marketRegime.as_of_date ? ` · as of ${marketRegime.as_of_date}` : ''}</p>
</div>`;
    const content = `
<div class="hero" style="text-align:center;padding:24px;background:linear-gradient(135deg,#161b22 0%,#1b2d3a 100%);border:1px solid #30363d;border-radius:8px;margin:16px 24px">
<div style="font-size:32px">☀</div>
<div style="font-size:20px;color:#58a6ff;font-weight:700">Good Morning</div>
<div class="date" style="margin-top:4px">${brief.date || new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}</div>
<div style="margin-top:12px;font-size:24px;color:#d2991d">${starStr}</div>
<div style="font-size:14px;color:#8b949e;margin-top:4px">市场情绪: ${sentiment.label || '未知'}</div>
<div style="font-size:12px;color:${dataStatus.degraded || hasStaleData ? '#d29922' : '#3fb950'};margin-top:8px">
${statusText} · 市场 ${components.market ? '✓' : '✗'} · 决策日志 ${components.decision_journal ? '✓' : '✗'} · Vibe ${components.vibe_sentiment || components.vibe_volume ? '✓' : '✗'}
</div>
${decisionDate ? `<div style="font-size:11px;color:#8b949e;margin-top:5px">决策日期 ${escapeHtml(decisionDate)}${pipelineRunId ? ` · 批次 ${escapeHtml(pipelineRunId.slice(0, 12))}` : ''}</div>` : ''}
${stateBanner ? `<div style="font-size:12px;margin-top:10px">${stateBanner}</div>` : ''}
</div>

<div style="padding:0 24px">
${regimeCard}
<div class="card"><h3>📊 市场概况</h3>
<p style="font-size:16px">${brief.market_summary || marketSummaryFallback}</p>
<p class="text-muted mt-8">${sentiment.score > 0 ? `情绪${sentiment.score}分 · ${sentiment.score >= 70 ? '偏乐观' : '偏中性'}` : '市场情绪数据不可用'}</p>
</div>

<div class="card"><h3>💡 今日机会</h3>
${opportunities.map((o, i) => `
<div class="stock-row" onclick="analyzeStock('${o.stock_code}')">
<div><span class="stock-name">#${i + 1} ${o.stock_name || o.stock_code}</span><br><span class="stock-code">${o.stock_code}</span></div>
<div style="text-align:right">
<span class="${(0, score_display_1.scoreTone)((0, score_display_1.finiteScore)(o.score))}" style="font-weight:700;font-size:18px">${(0, score_display_1.scoreText)(o.score, '分')}</span><br>
<span class="tag tag-up">${o.direction === 'buy' ? 'Strong Buy' : 'Buy'}</span>
</div></div>`).join('') || '<p class="text-muted">暂无机会推荐</p>'}
</div>

<div class="card" style="border-left:3px solid #d29922"><h3>📐 两阳夹一阴 · 额外观察</h3>
<p class="text-muted" style="font-size:12px;margin-bottom:12px">这部分不替换原流程5只股票，也不会直接触发买入。</p>
${patternWatchlist.map((item, i) => {
        const change = Number(item.change_pct || 0);
        const changeColor = change >= 0 ? '#3fb950' : '#f85149';
        const latestFlow = Number(item.latest_main_net || 0) / 10000;
        const fiveFlow = Number(item.five_day_main_net || 0) / 10000;
        const volumeRatio = Number(item.volume_ratio_latest_vs_middle || 0);
        const dates = (item.pattern_dates || []).map((value) => escapeHtml(value)).join(' → ');
        return `
<div class="stock-row" onclick="analyzeStock('${escapeHtml(item.stock_code || '')}')">
<div><span class="stock-name">#${i + 1} ${escapeHtml(item.stock_name || item.stock_code)}</span><br>
<span class="stock-code">${escapeHtml(item.stock_code || '')} · ${escapeHtml(item.data_date || '')}</span><br>
<span style="font-size:11px;color:#8b949e">${dates}</span></div>
<div style="text-align:right;font-size:12px">
<span style="font-weight:700;color:${changeColor}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span><br>
<span style="color:#8b949e">放量 ${volumeRatio.toFixed(2)}倍</span><br>
<span style="color:#8b949e">资金 +${latestFlow.toFixed(0)}万 / 5日 +${fiveFlow.toFixed(0)}万</span>
</div></div>`;
    }).join('') || '<p class="text-muted">暂无通过数据完整性核验的形态候选</p>'}
</div>

<div class="card"><h3>⚠ 风险提示</h3>
${risks.map((r) => `<p style="padding:6px 0;color:#d2991d">⚠ ${r}</p>`).join('') || '<p class="text-muted">暂无风险提示</p>'}
</div>

${shortTermSentiment.lianban_stocks && shortTermSentiment.lianban_stocks.length > 0 ? `
<div class="card"><h3>🔥 连板股看板</h3>
<p class="text-muted" style="font-size:12px;margin-bottom:12px">数据来源：东财公开榜单（客观数据，非推荐）</p>
<div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
${shortTermSentiment.lianban_ladder ? Object.entries(shortTermSentiment.lianban_ladder).map(([boards, count]) => `<div style="background:#1a1a1a;padding:12px 16px;border-radius:6px;border:1px solid #30363d;min-width:80px;text-align:center">
    <div style="font-size:24px;font-weight:700;color:#58a6ff">${count}</div>
    <div style="font-size:12px;color:#8b949e;margin-top:4px">${boards}</div>
  </div>`).join('') : ''}
<div style="background:#1a1a1a;padding:12px 16px;border-radius:6px;border:1px solid #d2991d;min-width:80px;text-align:center">
  <div style="font-size:24px;font-weight:700;color:#d2991d">${shortTermSentiment.max_boards || 0}</div>
  <div style="font-size:12px;color:#8b949e;margin-top:4px">最高连板</div>
</div>
</div>
<div style="max-height:300px;overflow-y:auto">
${shortTermSentiment.lianban_stocks.slice(0, 20).map((s, i) => `
<div class="stock-row" onclick="analyzeStock('${s.code}')">
  <div>
    <span class="stock-name">#${i + 1} ${s.name || s.code}</span>
    <span style="margin-left:8px;background:#d2991d;color:#000;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">${s.boards}板</span>
    <br><span class="stock-code">${s.code}</span>
  </div>
  <div style="text-align:right;font-size:12px;color:#8b949e">
    成交额: ${s.amount ? (s.amount / 100000000).toFixed(2) + '亿' : '-'}
  </div>
</div>`).join('')}
</div>
</div>` : ''}

${topVolumeStocks && topVolumeStocks.length > 0 ? `
<div class="card"><h3>💰 成交额TOP20</h3>
<p class="text-muted" style="font-size:12px;margin-bottom:12px">数据来源：东财公开榜单（市场活跃度指标）</p>
<div style="max-height:400px;overflow-y:auto">
${topVolumeStocks.map((s, i) => {
        const pctNum = parseFloat(s.pct || 0);
        const pctColor = pctNum > 0 ? '#3fb950' : pctNum < 0 ? '#f85149' : '#8b949e';
        const amountYi = s.amount ? (s.amount / 100000000).toFixed(2) : '0';
        const mcapYi = s.mcap ? (s.mcap / 100000000).toFixed(0) : '0';
        return `
<div class="stock-row" onclick="analyzeStock('${s.code}')">
  <div>
    <span class="stock-name">#${i + 1} ${s.name || s.code}</span>
    <br><span class="stock-code">${s.code}</span>
  </div>
  <div style="text-align:right">
    <span style="font-size:16px;font-weight:700;color:${pctColor}">${pctNum > 0 ? '+' : ''}${pctNum.toFixed(2)}%</span>
    <br><span style="font-size:12px;color:#8b949e">成交 ${amountYi}亿 · 市值 ${mcapYi}亿</span>
  </div>
</div>`;
    }).join('')}
</div>
</div>` : ''}

<div class="card" style="border-left:3px solid #58a6ff"><h3>💬 今日一句话</h3>
<p style="font-size:16px;color:#58a6ff;line-height:1.6">${brief.one_liner || oneLinerFallback}</p>
</div>

<div style="text-align:center;padding:16px;color:#8b949e;font-size:12px">
生成时间: ${brief.generated_at || '暂无'} · 每日自动更新 · <span style="cursor:pointer;color:#58a6ff" onclick="refreshBrief()">手动刷新</span>
</div>
</div>`;
    const extraScript = `
async function refreshBrief() {
    vscode.postMessage({command:'refreshBrief'});
}`;
    return (0, layout_1.pageShell)('dailybrief', 'Daily Brief · 每日简报', content, extraScript);
}
//# sourceMappingURL=dailybrief.js.map