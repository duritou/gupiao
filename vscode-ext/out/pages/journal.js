"use strict";
/** Decision Journal — real AI decisions and verified outcomes. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildJournalPage = buildJournalPage;
const layout_1 = require("../webview/layout");
const score_display_1 = require("../webview/score-display");
function finiteNumber(value, fallback = 0) {
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
function normalizeEntry(raw) {
    const snapshot = raw?.snapshot || {};
    const source = Object.keys(snapshot).length ? snapshot : raw || {};
    const outcomeKnown = source.outcome_known === true || source.final_verdict === 'correct' || source.final_verdict === 'wrong';
    const wasCorrect = source.was_correct === true || source.final_verdict === 'correct';
    return {
        id: source.id ?? raw?.id ?? '',
        date: String(source.date || source.decision_date || source.created_at || '').slice(0, 10),
        stockCode: String(source.stock_code || ''),
        stockName: String(source.stock_name || source.stock_code || ''),
        score: (0, score_display_1.finiteScore)(source.ai_score),
        direction: source.direction === 'buy' ? 'buy' : source.direction === 'sell' ? 'sell' : 'neutral',
        recommendation: String(source.recommendation || source.recommendation_text || ''),
        outcomeKnown,
        wasCorrect,
        lesson: String(raw?.lesson || source.ai_reflection || ''),
    };
}
function buildJournalPage(data) {
    const journal = data?.journal || {};
    const entries = (Array.isArray(journal.entries) ? journal.entries : []).map(normalizeEntry);
    const summary = data?.summary || {};
    const total = finiteNumber(summary.total_decisions, finiteNumber(journal.total_entries, entries.length));
    const decisive = finiteNumber(summary.decisive_decisions);
    const neutral = finiteNumber(summary.neutral_decisions);
    const verified = finiteNumber(summary.verified_decisions);
    const decisiveVerified = finiteNumber(summary.decisive_verified_decisions);
    const decisiveCorrect = finiteNumber(summary.decisive_correct_decisions);
    const accuracyAvailable = summary.accuracy_available === true && decisiveVerified > 0;
    const accuracy = finiteNumber(summary.accuracy) * 100;
    const errorHtml = data?.journalError
        ? `<div class="card" style="border-left:3px solid #f85149"><div class="flex-between"><span>Journal 加载失败：${escapeHtml(data.journalError)}</span><button class="btn" onclick="retryJournal()">重试</button></div></div>`
        : '';
    const insight = accuracyAvailable
        ? `已验证 ${decisiveVerified} 次明确买卖判断，其中 ${decisiveCorrect} 次方向正确；观望记录 ${neutral} 条。准确率只统计明确买入/卖出，不把观望混入。`
        : `已有 ${total} 条真实决策，其中 ${decisive} 条为明确买卖判断；样本仍在等待后续行情验证。`;
    const content = `
<div style="padding:16px 24px">
${errorHtml}
<div class="grid4">
<div class="card" style="text-align:center"><div style="font-size:28px;font-weight:700;color:#58a6ff">${total}</div><div class="text-sm text-muted">真实决策</div></div>
<div class="card" style="text-align:center;border-left:3px solid #A78BFA"><div style="font-size:28px;font-weight:700;color:#A78BFA">${decisive}</div><div class="text-sm text-muted">明确买卖</div></div>
<div class="card" style="text-align:center;border-left:3px solid #22C55E"><div style="font-size:28px;font-weight:700;color:#22C55E">${verified}</div><div class="text-sm text-muted">已有结果</div></div>
<div class="card" style="text-align:center;border-left:3px solid #F59E0B"><div style="font-size:28px;font-weight:700;color:#F59E0B">${accuracyAvailable ? accuracy.toFixed(1) + '%' : '待验证'}</div><div class="text-sm text-muted">明确判断准确率</div></div>
</div>
<div class="card" style="border-left:3px solid #7C3AED"><div style="display:flex;align-items:flex-start;gap:12px"><div style="font-size:24px">💡</div><div><div style="font-size:14px;font-weight:600;color:#A78BFA;margin-bottom:4px">AI 学习进度</div><div style="font-size:13px;color:#c9d1d9;line-height:1.5">${escapeHtml(insight)}</div></div></div></div>
<div class="flex-row gap-8" style="margin:16px 0 8px;flex-wrap:wrap">
<span class="text-sm text-muted">筛选:</span>
<button class="btn btn-sm filter-btn active" data-filter="all" onclick="filterJournal('all')">全部</button>
<button class="btn btn-sm filter-btn" data-filter="correct" onclick="filterJournal('correct')">✅ 正确</button>
<button class="btn btn-sm filter-btn" data-filter="wrong" onclick="filterJournal('wrong')">❌ 错误</button>
<button class="btn btn-sm filter-btn" data-filter="pending" onclick="filterJournal('pending')">⏳ 待验证</button>
<button class="btn btn-sm filter-btn" data-filter="buy" onclick="filterJournal('buy')">📈 买入</button>
<button class="btn btn-sm filter-btn" data-filter="sell" onclick="filterJournal('sell')">📉 卖出</button>
<button class="btn btn-sm filter-btn" data-filter="neutral" onclick="filterJournal('neutral')">👀 观望</button>
<button class="btn btn-sm" onclick="retryJournal()">刷新</button>
</div>
<div id="journalFeed">${entries.map(renderJournalEntry).join('') || '<div class="empty-state"><div class="icon">📓</div><p>尚无真实决策记录，完成一次 AI 分析后会显示在这里。</p></div>'}</div>
<div id="journalNoMatches" class="empty-state" style="display:none"><div class="icon">🔎</div><p>当前筛选条件下没有记录</p></div>
</div>`;
    const extraScript = `
function filterJournal(filter) {
    let visible = 0;
    document.querySelectorAll('.journal-entry').forEach(card => {
        const matches = filter === 'all' || card.dataset.outcome === filter || card.dataset.direction === filter;
        card.style.display = matches ? '' : 'none';
        if (matches) visible += 1;
    });
    document.querySelectorAll('.filter-btn').forEach(button => button.classList.toggle('active', button.dataset.filter === filter));
    document.getElementById('journalNoMatches').style.display = visible === 0 ? '' : 'none';
}
function retryJournal() { vscode.postMessage({command:'refreshPage'}); }
`;
    return (0, layout_1.pageShell)('journal', 'Decision Journal · 决策日志', content, extraScript);
}
function renderJournalEntry(entry) {
    const directionLabel = entry.direction === 'buy' ? '买入' : entry.direction === 'sell' ? '卖出' : '观望';
    const directionColor = entry.direction === 'buy' ? '#22C55E' : entry.direction === 'sell' ? '#EF4444' : '#8b949e';
    const outcome = entry.outcomeKnown ? (entry.wasCorrect ? 'correct' : 'wrong') : 'pending';
    const outcomeLabel = outcome === 'correct' ? '✓ 正确' : outcome === 'wrong' ? '✗ 错误' : '⏳ 待验证';
    const outcomeColor = outcome === 'correct' ? '#22C55E' : outcome === 'wrong' ? '#EF4444' : '#6B7280';
    const score = (0, score_display_1.finiteScore)(entry.score);
    const scoreColor = score === null
        ? '#9CA3AF'
        : score >= 80 ? '#22C55E' : score >= 60 ? '#F59E0B' : '#EF4444';
    return `
<div class="evidence-card journal-entry" data-outcome="${outcome}" data-direction="${entry.direction}" style="border-left:3px solid ${outcomeColor}">
<div class="flex-between" style="margin-bottom:8px">
<div class="flex-row gap-8"><span style="font-size:18px">${outcome === 'correct' ? '✅' : outcome === 'wrong' ? '❌' : '⏳'}</span><span style="font-weight:600;font-size:14px">${escapeHtml(entry.stockName)}</span><span class="stock-code">${escapeHtml(entry.stockCode)}</span><span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;background:#21262d;color:${directionColor}">${directionLabel}</span></div>
<div class="flex-row gap-8"><span style="color:#6B7280;font-size:11px">${escapeHtml(entry.date)}</span><span class="${(0, score_display_1.scoreTone)(score)}" style="font-weight:700;font-size:18px;color:${scoreColor}">${(0, score_display_1.scoreText)(score, '分')}</span></div>
</div>
<div style="font-size:13px;color:#c9d1d9;margin-bottom:6px;line-height:1.5">${escapeHtml(entry.recommendation || '暂无文字建议')}</div>
<div class="flex-between" style="margin-top:8px;padding-top:8px;border-top:1px solid #21262d"><span style="font-size:12px;font-weight:600;color:${outcomeColor}">${outcomeLabel}</span><span class="text-sm text-muted">记录 #${escapeHtml(entry.id)}</span></div>
${entry.lesson ? `<div style="margin-top:6px;font-size:12px;color:#A78BFA;line-height:1.4">💡 ${escapeHtml(entry.lesson)}</div>` : ''}
</div>`;
}
//# sourceMappingURL=journal.js.map