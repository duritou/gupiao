/** Dashboard v4.2 — Mission Control with Alert Intelligence.
 *
 * Layout:
 *   1. Portfolio Summary Cards (from Morning Brief)
 *   2. 🔥 Today Focus — AI-prioritized urgent alerts (P0/P1)
 *   3. Market Overview — breadth, volume, northbound
 *   4. Hot Sectors + Risk Warnings
 *   5. Top Opportunities (from Scanner)
 *   6. My Watchlist Snapshot
 */

import { pageShell } from '../webview/layout';
import { finiteScore, scoreText, scoreTone } from '../webview/score-display';

const REASON_LABELS: Record<string, string> = {
    fundamental_evidence_missing: '基本面证据待补充',
    fundamental_loss_risk: '基本面存在亏损风险',
    market_context_missing: '市场环境数据缺失',
    market_data_degraded: '行情数据质量降级',
    market_data_unavailable: '行情数据暂不可用',
    technical_data_stale: '技术数据已过期',
    technical_scan_incomplete: '技术扫描未完成',
    trading_calendar_unverified: '交易日历待确认',
    universe_metadata_incomplete: '股票基础信息不完整',
    deep_analysis_error: '深度分析未完成',
    final_review_blocked: '最终复核暂未通过',
};

const TECHNICAL_REASON_LABELS: Record<string, { high: string; low: string }> = {
    macd: { high: 'MACD走强', low: 'MACD偏弱' },
    rsi: { high: 'RSI状态健康', low: 'RSI偏弱' },
    kdj: { high: 'KDJ偏强', low: 'KDJ偏弱' },
    ma: { high: '均线趋势向上', low: '均线趋势偏弱' },
    volume: { high: '量能配合', low: '量能偏弱' },
};

function _escapeHtml(value: unknown): string {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _text(value: unknown): string {
    return typeof value === 'string' ? value.replace(/\r\n?/g, '\n').trim() : '';
}

function _reasonList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map(item => String(item || '').trim()).filter(Boolean);
    }
    const text = String(value || '').trim();
    return text ? [text] : [];
}

function _unique(values: string[]): string[] {
    return values.filter((value, index) => value && values.indexOf(value) === index);
}

function _reasonLabel(value: string): string {
    return REASON_LABELS[value] || value.replace(/_/g, ' ');
}

function _guardReasons(candidate: any): string[] {
    return _unique([
        ..._reasonList(candidate.blocked_reasons),
        ..._reasonList(candidate.score_guard_reasons),
    ]).map(_reasonLabel);
}

function _shortReason(value: string): string {
    const compact = value.replace(/\s+/g, ' ');
    return compact.length > 54 ? `${compact.slice(0, 54)}…` : compact;
}

function _technicalReasons(candidate: any): string[] {
    const breakdown = candidate.score_breakdown || {};
    const direction = String(candidate.direction || '').toLowerCase();
    return Object.entries(TECHNICAL_REASON_LABELS)
        .map(([key, labels]) => {
            const score = Number(breakdown[key]);
            if (!Number.isFinite(score)) return '';
            if (score >= 60 && direction !== 'sell') return labels.high;
            if (score <= 40 && direction === 'sell') return labels.low;
            return '';
        })
        .filter(Boolean)
        .slice(0, 3);
}

function _recommendationReasons(candidate: any, blocked: boolean): string[] {
    const deepThesis = _shortReason(_text(candidate.deep_thesis));
    const guardReasons = _guardReasons(candidate);
    const reasons = blocked
        ? [candidate.deep_rating ? `深度评级：${candidate.deep_rating}` : '', ...guardReasons, deepThesis]
        : [deepThesis, ..._technicalReasons(candidate)];
    return _unique(reasons).filter(Boolean).slice(0, 3);
}

function _technicalDetail(candidate: any): string {
    const breakdown = candidate.score_breakdown || {};
    const labels: Record<string, string> = {
        macd: 'MACD', rsi: 'RSI', kdj: 'KDJ', ma: '均线', volume: '量能',
    };
    return Object.keys(labels)
        .map(key => {
            const score = Number(breakdown[key]);
            return Number.isFinite(score) ? `${labels[key]}：${score.toFixed(1)}分` : '';
        })
        .filter(Boolean)
        .join(' · ');
}

function _renderRecommendationReasons(candidate: any, id: string, blocked: boolean): string {
    const reasons = _recommendationReasons(candidate, blocked);
    const details: Array<{ label: string; value: string }> = [];
    const thesis = _text(candidate.deep_thesis);
    const analysis = _text(candidate.deep_analysis);
    const plan = _text(candidate.deep_trader_plan);
    const review = _unique([
        _text(candidate.final_review_reason),
        _text(candidate.final_review_risk),
    ]);
    const evidenceReasons = _reasonList(candidate.market_evidence_reasons).map(_reasonLabel);

    if (thesis) details.push({ label: 'AI投资主线', value: thesis });
    if (analysis && analysis !== thesis) details.push({ label: '完整分析', value: analysis });
    if (plan) details.push({ label: '交易计划', value: plan });
    if (review.length) details.push({ label: '最终复核', value: review.join('\n') });
    const readableGuardReasons = _guardReasons(candidate);
    if (readableGuardReasons.length) {
        details.push({ label: '当前限制', value: readableGuardReasons.join('、') });
    }
    if (evidenceReasons.length) details.push({ label: '数据说明', value: evidenceReasons.join('、') });
    const technicalDetail = _technicalDetail(candidate);
    if (technicalDetail) details.push({ label: '量化信号', value: technicalDetail });
    if (_text(candidate.deep_analysis_error)) {
        details.push({ label: '分析状态', value: _text(candidate.deep_analysis_error) });
    }

    return `
<div class="recommendation-reasons" onclick="event.stopPropagation()">
<div class="reason-label">理由</div>
<div class="reason-tags">${(reasons.length ? reasons : ['综合信号待进一步确认']).map(reason =>
        `<span class="reason-tag">${_escapeHtml(reason)}</span>`).join('')}</div>
${details.length ? `<details class="recommendation-details" id="${id}" onclick="event.stopPropagation()">
<summary>查看完整理由</summary>
<div class="recommendation-detail-body">${details.map(detail => `
<div class="recommendation-detail-item"><div class="recommendation-detail-label">${_escapeHtml(detail.label)}</div><div class="recommendation-detail-text">${_escapeHtml(detail.value)}</div></div>`).join('')}</div>
</details>` : ''}
</div>`;
}

export function buildDashboardPage(data: any): string {
    const market = data.market || {};
    const m = market.market_breadth || {};
    const nb = market.northbound || {};
    const regime = market.market_regime || {};
    const regimeState = String(regime.state || 'unknown');
    const regimeLabels: Record<string, string> = {
        strong: '强势',
        lean_strong: '偏强',
        range: '震荡',
        lean_weak: '偏弱',
        weak: '弱势',
        unknown: '未知',
    };
    const regimeLabel = regimeLabels[regimeState] || '未知';
    const regimeScore = Number(regime.score);
    const regimeConfidence = Number(regime.confidence);
    const regimeAvailable = regimeState !== 'unknown' && Number.isFinite(regimeScore);
    const regimeColor = regimeState === 'strong' || regimeState === 'lean_strong'
        ? '#22C55E'
        : regimeState === 'weak' || regimeState === 'lean_weak' ? '#EF4444' : '#F59E0B';
    // Keep the dashboard useful across backend versions and during a brief
    // provenance probe failure.  The breadth payload is authoritative when it
    // carries a complete numeric snapshot, even if the separate quality probe
    // has not returned yet.
    const breadthAvailable = market._data?.breadth?.available === true
        || (Number.isFinite(Number(m.up)) && Number.isFinite(Number(m.down))
            && Number.isFinite(Number(m.covered_stocks)));
    const scanner = data.scanner || {};
    const candidates = (scanner.candidates || []).slice(0, 6);
    const blockedCandidates = (scanner.blocked_candidates || []).slice(0, 6);
    const continuityWatchlist = (scanner.continuity_watchlist || []).slice(0, 6);
    const scannedCount = Number(scanner.total_scanned || 0);
    const requestedPool = Number(scanner.universe_count || scanner.pool_size || 0);
    const coverageComplete = scanner.coverage_complete === true;
    const coverageLabel = requestedPool > 0
        ? `${scannedCount}/${requestedPool} 只`
        : `${scannedCount} 只`;
    const rankingNote = scanner.data_note || '仅代表已扫描样本的技术指标排序';
    const watchScores = data.watchScores?.signals || [];
    const liveQuotes = data.liveQuotes?.quotes || [];
    const watchQuoteMap: Record<string, any> = {};
    liveQuotes.forEach((q: any) => { watchQuoteMap[q.stock_code] = q; });
    const brief = data.brief || {};
    // Dashboard is the summary surface; full lists stay on Daily Brief and
    // Alerts so the same stock information is not expanded in multiple places.
    const risks = (market.risk_summary?.length ? market.risk_summary : brief.risk_warnings || []).slice(0, 3);
    const pf = brief.portfolio || {};
    const alertFeed = data.alerts || {};
    const todayFocus = alertFeed.today_focus || {};
    const urgentAlerts = todayFocus.urgent || [];
    const importantAlerts = todayFocus.important || [];
    const trackRecord = data.trackRecord || {};
    const aiAlpha = data.aiAlpha || {};
    const userProfile = data.userProfile || {};
    const greeting = userProfile.greeting || '';
    const dataHealth = data.dataQuality || {};
    const effectiveAvailable = dataHealth.live_available === true || breadthAvailable;
    const healthStatus: string = effectiveAvailable
        ? dataHealth.degraded ? 'degraded' : 'healthy'
        : 'down';
    const healthIcon = healthStatus === 'healthy' ? '🟢' : healthStatus === 'degraded' ? '🟡' : '🔴';

    const activeProviders = (dataHealth.sources || []).filter((s: any) => s.available);
    const providerLabel = activeProviders.map((s: any) => s.name).join(' + ') || 'unavailable';
    const qualityPct = dataHealth.live_available ? 'LIVE' : breadthAvailable ? 'CACHED' : 'OFFLINE';
    const qualityColor = healthStatus === 'healthy' ? '#22C55E' : healthStatus === 'degraded' ? '#F59E0B' : '#EF4444';
    const portfolioScore = finiteScore(pf.avg_score);
    const portfolioTrend = finiteScore(pf.score_trend);

    const content = `
<style>
.recommendation-reasons{margin-top:8px;max-width:760px;cursor:default}
.reason-label{display:inline-block;color:#8b949e;font-size:11px;margin-right:6px}
.reason-tags{display:inline-flex;flex-wrap:wrap;gap:4px;vertical-align:middle}
.reason-tag{display:inline-block;padding:2px 8px;border:1px solid #30363d;border-radius:10px;background:#1b2d3a;color:#9ecbff;font-size:11px;line-height:1.4}
.recommendation-details{margin-top:7px;border-top:1px solid #21262d;padding-top:6px}
.recommendation-details summary{display:inline-block;color:#58a6ff;font-size:11px;cursor:pointer;list-style:none}
.recommendation-details summary::-webkit-details-marker{display:none}
.recommendation-details summary::before{content:'＋';margin-right:3px;color:#8b949e}
.recommendation-details[open] summary::before{content:'－'}
.recommendation-detail-body{margin-top:7px;padding:8px 10px;background:#0d1117;border:1px solid #21262d;border-radius:6px}
.recommendation-detail-item+.recommendation-detail-item{margin-top:8px;padding-top:8px;border-top:1px solid #21262d}
.recommendation-detail-label{color:#a78bfa;font-size:11px;margin-bottom:3px}
.recommendation-detail-text{color:#c9d1d9;font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
</style>
<!-- Data Quality + Greeting Bar -->
<div style="padding:8px 24px;display:flex;justify-content:space-between;align-items:center">
${greeting ? '<div style="font-size:12px;color:#A78BFA;line-height:1.5">🤖 ' + greeting + '</div>' : '<div></div>'}
<div style="font-size:11px;display:flex;align-items:center;gap:6px">
<span>${healthIcon}</span>
<span style="color:#8b949e">${providerLabel}</span>
<span style="color:${qualityColor}">${qualityPct}</span>
</div>
</div>

<!-- ═══════════ Portfolio Summary Cards ═══════════ -->
${pf.position_count > 0 || scanner.total_scanned > 0 ? `
<div class="grid4">
<div class="card" style="border-left:3px solid #7C3AED"><h3>今日扫描</h3><div class="metric-value" style="font-size:24px">${scanner.total_scanned || 0}</div><span class="text-sm text-muted">真实日线研究池</span></div>
<div class="card"><h3>候选机会</h3><div class="metric-value up">${scanner.candidates_found || candidates.length}</div><span class="text-sm text-muted">已完成信号计算</span></div>
<div class="card" style="border-left:3px solid ${portfolioScore === null ? '#6B7280' : portfolioScore >= 70 ? '#22C55E' : '#F59E0B'}"><h3>AI评分</h3><div class="metric-value ${scoreTone(portfolioScore)}">${scoreText(portfolioScore)}</div><span class="text-sm text-muted">${portfolioTrend === null ? '趋势不可用' : `${portfolioTrend >= 0 ? '↑' : '↓'}${Math.abs(portfolioTrend).toFixed(0)} vs 昨日`}</span></div>
<div class="card"><h3>市场情绪</h3><div class="metric-value" style="color:#F59E0B;font-size:24px">${brief.market?.sentiment_label === 'unknown' ? 'N/A' : (brief.market?.sentiment_score ?? '--')}</div><span class="text-sm text-muted">${brief.market?.sentiment_label === 'unknown' ? '市场宽度数据不可用' : brief.market?.sentiment_label || '--'}</span></div>
</div>
` : ''}

<!-- ═══════════ 🔥 Today Focus (Alert Intelligence) ═══════════ -->
<div style="padding:0 24px;margin-bottom:8px">
<div class="card" style="border:1px solid ${urgentAlerts.length > 0 ? '#F59E0B' : '#30363d'};${urgentAlerts.length > 0 ? 'background:linear-gradient(135deg,#1a1800 0%,#161b22 100%);' : ''}">
<div class="card-header">
<h3 style="font-size:15px;color:#F59E0B">🔥 Today Focus · 今日重点摘要</h3>
<span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('alerts')">完整预警 →</span>
</div>
${urgentAlerts.length > 0 || importantAlerts.length > 0 ? `
<div style="display:flex;flex-direction:column;gap:8px">
${urgentAlerts.slice(0, 2).map((a: any) => _renderFocusAlert(a, true)).join('')}
${importantAlerts.slice(0, Math.max(0, 3 - urgentAlerts.length)).map((a: any) => _renderFocusAlert(a, false)).join('')}
</div>` : `
<div class="empty-state" style="padding:24px"><p>今日暂无紧急预警 · AI持续监控中</p></div>`}
${alertFeed.one_liner ? `
<div style="margin-top:12px;padding-top:12px;border-top:1px solid #21262d;font-size:13px;color:#A78BFA;line-height:1.5">💬 ${alertFeed.one_liner}</div>` : ''}
${brief.one_liner ? `
<div style="margin-top:8px;font-size:13px;color:#8B5CF6;line-height:1.5">💬 ${brief.one_liner} <span style="cursor:pointer;color:#58a6ff" onclick="navigate('dailybrief')">查看每日简报 →</span></div>` : ''}
</div></div>

<!-- ═══════════ Market Overview ═══════════ -->
<div class="grid4">
<div class="card"><h3>上涨</h3><div class="metric-value up">${breadthAvailable ? m.up.toLocaleString() : 'N/A'}</div><span class="text-sm text-muted">${breadthAvailable ? `涨停 ${m.limit_up}` : '数据源暂不可用'}</span></div>
<div class="card"><h3>下跌</h3><div class="metric-value down">${breadthAvailable ? m.down.toLocaleString() : 'N/A'}</div><span class="text-sm text-muted">${breadthAvailable ? `跌停 ${m.limit_down}` : '数据源暂不可用'}</span></div>
<div class="card"><h3>成交额</h3><div class="metric-value" style="font-size:24px">${breadthAvailable && market.total_volume ? market.total_volume + '万亿' : 'N/A'}</div></div>
<div class="card"><h3>北向资金</h3><div class="metric-value ${nb.direction === 'inflow' ? 'up' : nb.direction === 'outflow' ? 'down' : 'neutral'}">${breadthAvailable && nb.net_flow ? (nb.net_flow > 0 ? '+' : '') + nb.net_flow + '亿' : 'N/A'}</div></div>
<div class="card"><h3>市场环境</h3><div class="metric-value" style="color:${regimeColor};font-size:24px">${regimeAvailable ? regimeLabel : 'N/A'}</div><span class="text-sm text-muted">${regimeAvailable ? `评分 ${regimeScore.toFixed(0)} · 置信度 ${(regimeConfidence * 100).toFixed(0)}%` : '宽度数据不可用'}</span></div>
</div>

<!-- ═══════════ Risk Summary ═══════════ -->
<div class="grid2">
<div class="card"><div class="card-header"><h3>风险预警摘要</h3><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('alerts')">完整预警 →</span></div>
${risks.map((r: any) => `<div class="stock-row">
<span>${r.type}</span><span class="${r.severity === 'high' ? 'down' : 'warn'}">${r.count}只</span>
</div>`).join('') || '<div class="empty-state"><p>暂无风险预警</p></div>'}
</div>
</div>

<!-- ═══════════ Top Opportunities ═══════════ -->
<div style="padding:0 24px"><div class="card">
<div class="card-header">
<div><h3>📊 样本技术排名 Top ${candidates.length}</h3>
<div class="text-sm text-muted" style="margin-top:4px">${rankingNote}</div></div>
<span style="display:flex;align-items:center;gap:8px"><span class="tag tag-${coverageComplete ? 'up' : 'warn'}">覆盖 ${coverageLabel}${scanner.cached ? ' · 缓存' : ''}</span><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('decisions')">决策详情 →</span></span>
</div>
${candidates.map((c: any, i: number) => {
    const candidateScore = finiteScore(c.fusion_score);
    const sc = scoreTone(candidateScore);
    const stars = candidateScore === null ? '☆☆☆☆☆' : candidateScore >= 80 ? '★★★★★' : candidateScore >= 65 ? '★★★★' : candidateScore >= 50 ? '★★★' : '★★';
    const name = c.stock_name || c.stock_code || '--';
    return `<div class="stock-row" onclick="analyzeStock('${c.stock_code}')">
<div style="min-width:0;flex:1;padding-right:16px"><span class="stock-name">样本 #${i + 1} ${name}</span><br><span class="stock-code">${c.stock_code} · ${stars} · ${c.data_source || '来源未知'}</span>${_renderRecommendationReasons(c, `candidate-reason-${i}`, false)}</div>
<div style="text-align:right"><span class="metric-value ${sc}" style="font-size:24px">${scoreText(candidateScore)}</span><br>
<span class="text-sm text-muted">研究分 ${scoreText(c.primary_score ?? c.action_score)} · 机会排名分 ${scoreText(c.ranking_score)}</span><br>
<span class="tag tag-${c.direction === 'buy' ? 'up' : c.direction === 'sell' ? 'down' : 'info'}">${c.display_state_label || (c.direction === 'buy' ? '技术偏强' : c.direction === 'sell' ? '技术偏弱' : '技术中性')}</span></div>
</div>`;
}).join('') || `<div class="empty-state"><div class="icon">🔍</div><p>${blockedCandidates.length > 0 ? '本次扫描没有通过证据门槛的有效推荐' : '运行扫描以发现机会'}</p></div>`}
</div></div>

<!-- ═══════════ Restricted Deep Reviews ═══════════ -->
${blockedCandidates.length > 0 ? `
<div style="padding:0 24px;margin-top:16px"><div class="card" style="border-left:3px solid #F59E0B">
<div class="card-header">
<div><h3>🧪 AI深度复核（受限）</h3>
<div class="text-sm text-muted" style="margin-top:4px">已完成深度分析，但因数据或风险门槛未形成买卖推荐</div></div>
<span class="tag tag-warn">不可直接交易</span>
</div>
${blockedCandidates.map((c: any) => `
<div class="stock-row" onclick="analyzeStock('${c.stock_code}')">
<div style="min-width:0;flex:1;padding-right:16px"><span class="stock-name">${c.stock_name || c.stock_code}</span><br><span class="stock-code">${c.stock_code} · ${c.deep_rating || '已深度复核'} · ${c.decision_status || '受限'}</span>${_renderRecommendationReasons(c, `blocked-reason-${c.rank}`, true)}</div>
<div style="text-align:right"><span class="metric-value neutral" style="font-size:20px">研究 ${scoreText(finiteScore(c.primary_score ?? c.action_score ?? c.fusion_score))}</span><br>
<span class="text-sm text-muted">机会排名 ${scoreText(finiteScore(c.ranking_score))} · ${c.display_state_label || '证据门槛未通过'} · ${_guardReasons(c).slice(0, 2).join('、') || '需补充证据'}</span></div>
</div>`).join('')}
</div></div>` : ''}

<!-- ═══════════ Continuity Watchlist ═══════════ -->
${continuityWatchlist.length > 0 ? `
<div style="padding:0 24px;margin-top:16px"><div class="card" style="border-left:3px solid #60A5FA">
<details>
<summary style="cursor:pointer;list-style:none"><div class="card-header" style="margin-bottom:0">
<div><h3>🔁 历史连续观察（非本次结果）</h3>
<div class="text-sm text-muted" style="margin-top:4px">仅在展开后查看前几次运行的延续观察对象</div></div>
<span class="tag tag-info">仅观察 · 不自动交易</span>
</div></summary>
<div class="text-sm text-muted" style="margin:10px 0">以下股票来自历史运行批次，不属于当前最终决策名单；不会触发模拟交易。</div>
${continuityWatchlist.map((c: any) => `
<div class="stock-row" onclick="analyzeStock('${c.stock_code}')">
<div><span class="stock-name">${c.stock_name || c.stock_code}</span><br><span class="stock-code">${c.stock_code} · 前次排名 #${c.previous_rank} · ${c.previous_decision_date}</span></div>
<div style="text-align:right"><span class="metric-value neutral" style="font-size:20px">前次 ${scoreText(finiteScore(c.previous_ranking_score))}</span><br>
<span class="text-sm text-muted">当前 ${scoreText(finiteScore(c.current_action_score))} · ${c.current_decision_status || '未入当前扫描'}</span></div>
</div>`).join('')}
</details>
</div></div>` : ''}

<!-- ═══════════ My Watchlist Snapshot ═══════════ -->
${watchScores.length > 0 ? `
<div style="padding:0 24px;margin-top:16px"><div class="card">
<div class="card-header"><h3>📈 我的关注摘要</h3><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('watchlist')">完整自选 →</span></div>
<div class="grid4">
${watchScores.slice(0, 4).map((s: any) => {
    const watchScore = finiteScore(s.fusion_score);
    const sc = scoreTone(watchScore);
    const signalName = String(s.stock_name || '').trim();
    const quote = watchQuoteMap[s.stock_code] || {};
    const quoteName = String(quote.stock_name || quote.name || '').trim();
    const displayName = signalName && signalName !== s.stock_code
        ? signalName
        : quoteName || '名称不可用';
    return `<div style="text-align:center;padding:8px;cursor:pointer" onclick="analyzeStock('${s.stock_code}')">
<div class="stock-name">${displayName}</div>
<div style="font-size:20px;font-weight:700" class="${sc}">${scoreText(watchScore)}</div>
<div class="text-sm text-muted">技术分</div>
<div class="text-sm"><span class="${s.direction === 'buy' ? 'up' : s.direction === 'sell' ? 'down' : 'neutral'}">${s.trend_arrow || '→'} ${s.top_signal || ''}</span></div>
</div>`;
}).join('')}
</div></div></div>` : ''}

<!-- ═══════════ AI Alpha — Value Attribution (v5.0 final) ═══════════ -->
${aiAlpha.total_suggestions > 0 ? `
<div style="padding:0 24px;margin-top:8px;margin-bottom:8px"><div class="card" style="border:1px solid #7C3AED;background:linear-gradient(135deg,#0f0a1a 0%,#161b22 100%)">
<div class="card-header">
<h3 style="color:#A78BFA">🤖 AI 价值验证 · ${aiAlpha.period_label || '最近90天'}</h3>
<span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('resume')">完整档案 →</span>
</div>

<!-- Hero Metric: AI Alpha -->
<div style="text-align:center;padding:16px 0">
<div style="font-size:12px;color:#8b949e;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">AI Alpha · 超额收益</div>
<div style="font-size:48px;font-weight:800;color:${aiAlpha.ai_alpha_pct >= 0 ? '#22C55E' : '#EF4444'};line-height:1">
${aiAlpha.ai_alpha_pct >= 0 ? '+' : ''}${aiAlpha.ai_alpha_pct.toFixed(1)}%
</div>
<div style="font-size:12px;color:#8b949e;margin-top:4px">跟随AI vs 自主决策的收益差</div>
</div>

<!-- 3-column breakdown -->
<div class="grid3" style="padding:0">
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #1F2937">
<div style="font-size:11px;color:#8b949e;margin-bottom:4px">跟随 AI</div>
<div style="font-size:24px;font-weight:700;color:#22C55E">${aiAlpha.follow_ai_return_pct >= 0 ? '+' : ''}${aiAlpha.follow_ai_return_pct.toFixed(1)}%</div>
<div style="font-size:10px;color:#6B7280">${aiAlpha.followed_correct_count}胜/${aiAlpha.followed_wrong_count}负</div>
</div>
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #1F2937">
<div style="font-size:11px;color:#8b949e;margin-bottom:4px">自主决策</div>
<div style="font-size:24px;font-weight:700;color:${aiAlpha.self_decision_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${aiAlpha.self_decision_return_pct >= 0 ? '+' : ''}${aiAlpha.self_decision_return_pct.toFixed(1)}%</div>
<div style="font-size:10px;color:#6B7280">未跟随AI的收益</div>
</div>
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid #7C3AED">
<div style="font-size:11px;color:#A78BFA;margin-bottom:4px">执行率</div>
<div style="font-size:24px;font-weight:700;color:#A78BFA">${(aiAlpha.execution_rate * 100).toFixed(0)}%</div>
<div style="font-size:10px;color:#6B7280">${aiAlpha.executed_count}/${aiAlpha.total_suggestions}条建议被执行</div>
</div>
</div>

<!-- Detail row: missed + avoided -->
<div class="grid2" style="padding:0;margin-top:8px">
<div style="padding:8px 12px;font-size:11px;text-align:center">
<span style="color:#F59E0B">💔 错过机会 </span>
<span style="color:#F59E0B;font-weight:600">${aiAlpha.missed_opportunity_count}次</span>
<span style="color:#8b949e"> · 损失 </span>
<span style="color:#F59E0B;font-weight:600">+${aiAlpha.missed_profit_total_pct.toFixed(1)}%</span>
</div>
<div style="padding:8px 12px;font-size:11px;text-align:center">
<span style="color:#22C55E">🛡 避免亏损 </span>
<span style="color:#22C55E;font-weight:600">${aiAlpha.avoided_loss_count}次</span>
<span style="color:#8b949e"> · 保住 </span>
<span style="color:#22C55E;font-weight:600">${aiAlpha.avoided_loss_total_pct.toFixed(1)}%</span>
</div>
</div>
</div></div>` : (trackRecord.total_recommendations > 0 ? `
<div style="padding:0 24px;margin-top:8px;margin-bottom:8px"><div class="card" style="border-left:3px solid #7C3AED">
<div class="card-header"><h3>🤖 AI Track Record</h3><span class="text-sm text-muted" style="cursor:pointer" onclick="navigate('resume')">AI完整档案 →</span></div>
<div class="grid4">
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:${trackRecord.accuracy_available ? '#22C55E' : '#F59E0B'}">${trackRecord.accuracy_available ? (trackRecord.accuracy * 100).toFixed(0) + '%' : '待验证'}</div><div class="text-sm text-muted">方向准确率</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22C55E">${trackRecord.correct_count}/${trackRecord.verified_decisions}</div><div class="text-sm text-muted">正确/已验证</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22C55E">${trackRecord.current_streak}次</div><div class="text-sm text-muted">连续命中</div></div>
<div style="text-align:center"><div style="font-size:20px;font-weight:700;color:${trackRecord.avg_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${trackRecord.avg_return_pct >= 0 ? '+' : ''}${trackRecord.avg_return_pct.toFixed(1)}%</div><div class="text-sm text-muted">平均收益</div></div>
</div>
</div></div>` : '')}

<div style="padding:16px 24px;text-align:center" class="text-muted text-sm">
🔄 自动刷新: 60秒 · 页面数据时间: <span id="lastUpdate">${new Date().toLocaleTimeString('zh-CN')}</span>
</div>`;

    const extraScript = `
let dashInterval;
async function refreshDashboard() {
    vscode.postMessage({command:'refreshPage'});
}
function startAutoRefresh() { clearInterval(dashInterval); dashInterval = setInterval(refreshDashboard, 60000); }
function stopAutoRefresh() { clearInterval(dashInterval); }
document.addEventListener('visibilitychange', () => { document.hidden ? stopAutoRefresh() : startAutoRefresh(); });
    startAutoRefresh();
if (!${breadthAvailable}) {
    const state = vscode.getState() || {};
    if (!state.dashboardRecoveryRefreshRequested) {
        vscode.setState({ ...state, dashboardRecoveryRefreshRequested: true });
        setTimeout(refreshDashboard, 1500);
    }
}`;

    return pageShell('dashboard', 'Dashboard · Mission Control', content, extraScript);
}

/** Render a single Today Focus alert card. */
function _renderFocusAlert(a: any, isUrgent: boolean): string {
    const levelColor = a.level === 'P0' ? '#EF4444' : a.level === 'P1' ? '#F59E0B' : '#8b949e';
    const levelBg = a.level === 'P0' ? '#3a1b1b' : a.level === 'P1' ? '#3a351b' : '#21262d';
    const levelBadge = `<span style="display:inline-block;padding:1px 6px;border-radius:3px;background:${levelBg};color:${levelColor};font-size:10px;font-weight:700;font-family:monospace">${a.level}</span>`;
    const directionIcon = a.direction === 'buy' ? '🟢' : a.direction === 'sell' ? '🔴' : '⚪';

    const clickAction = a.stock_code
        ? `onclick="analyzeStock('${a.stock_code}')"`
        : '';

    return `
<div class="evidence-card" style="cursor:${a.stock_code ? 'pointer' : 'default'};border-left:3px solid ${levelColor};${isUrgent ? 'background:#1a1a10;' : ''}" ${clickAction}>
<div class="flex-between">
<div class="flex-row gap-8">
${levelBadge}
<span style="font-size:14px;font-weight:600">${a.title}</span>
</div>
<div class="flex-row gap-8">
<span style="color:#8b949e;font-size:11px">${_timeAgo(a.created_at)}</span>
${a.status === 'new' ? '<span style="color:#58a6ff;font-size:10px">● NEW</span>' : ''}
</div>
</div>
${a.evidence && a.evidence.length > 0 ? `
<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px">
${a.evidence.slice(0, 3).map((e: any) =>
    `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:#21262d;color:#8b949e">✓ ${e.title}</span>`
).join('')}
</div>` : ''}
${a.ai_confidence ? `
<div style="margin-top:6px;display:flex;gap:16px;font-size:11px;color:#8b949e">
<span>置信度 ${(a.ai_confidence * 100).toFixed(0)}%</span>
${a.historical_accuracy ? `<span>历史准确率 ${(a.historical_accuracy * 100).toFixed(0)}%</span>` : ''}
</div>` : ''}
</div>`;
}

function _timeAgo(iso: string): string {
    if (!iso) return '';
    const now = new Date();
    const then = new Date(iso);
    const mins = Math.floor((now.getTime() - then.getTime()) / 60000);
    if (mins < 1) return '刚刚';
    if (mins < 60) return `${mins}分钟前`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}小时前`;
    return `${Math.floor(hours / 24)}天前`;
}
