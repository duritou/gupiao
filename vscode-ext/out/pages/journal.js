"use strict";
/** Decision Journal v5.0 — AI vs User: who was right?

 * Records every AI recommendation, user action, and outcome.
 * The most habit-forming page in the product.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildJournalPage = buildJournalPage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildJournalPage(data) {
    const journal = data.journal || {};
    const entries = journal.entries || [];
    const summary = data.summary || {};
    // Stats bar
    const totalE = summary.total_entries || 0;
    const aiCorrect = summary.ai_correct_count || 0;
    const aiWrong = summary.ai_wrong_count || 0;
    const followed = summary.user_followed_count || 0;
    const ignored = summary.user_ignored_count || 0;
    const fCorrect = summary.followed_and_correct || 0;
    const fWrong = summary.followed_and_wrong || 0;
    const iCorrect = summary.ignored_and_correct || 0;
    const missed = summary.missed_profit_total || 0;
    const content = `
<!-- Summary Stats Bar -->
<div class="grid4">
<div class="card" style="text-align:center">
<div style="font-size:28px;font-weight:700;color:#58a6ff">${totalE}</div>
<div class="text-sm text-muted">总记录</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #22C55E">
<div style="font-size:28px;font-weight:700;color:#22C55E">${aiCorrect}</div>
<div class="text-sm text-muted">AI正确</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #EF4444">
<div style="font-size:28px;font-weight:700;color:#EF4444">${aiWrong}</div>
<div class="text-sm text-muted">AI错误</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #F59E0B">
<div style="font-size:28px;font-weight:700;color:#F59E0B">${(aiCorrect / Math.max(totalE, 1) * 100).toFixed(0)}%</div>
<div class="text-sm text-muted">AI准确率</div>
</div>
</div>

<!-- Behavioral Insight -->
<div style="padding:0 24px;margin-bottom:12px">
<div class="card" style="border-left:3px solid #7C3AED">
<div style="display:flex;align-items:flex-start;gap:12px">
<div style="font-size:24px">💡</div>
<div>
<div style="font-size:14px;font-weight:600;color:#A78BFA;margin-bottom:4px">AI 行为洞察</div>
<div style="font-size:13px;color:#c9d1d9;line-height:1.5">${summary.top_lesson || '数据积累中...'}</div>
</div>
</div>
</div>

<!-- Action Breakdown -->
<div class="grid2" style="padding:0 24px">
<div class="card">
<h3>✅ 你跟了 & AI对了</h3>
<div class="metric-value up" style="font-size:28px">${fCorrect}</div>
<span class="text-sm text-muted">信任得到回报</span>
</div>
<div class="card">
<h3>❌ 你跟了 & AI错了</h3>
<div class="metric-value down" style="font-size:28px">${fWrong}</div>
<span class="text-sm text-muted">需要总结教训</span>
</div>
<div class="card">
<h3>💔 你没跟 & AI对了</h3>
<div class="metric-value warn" style="font-size:28px">${iCorrect}</div>
<span class="text-sm text-muted">错过了 ${missed > 0 ? '+' + missed.toFixed(0) + '%' : ''} 收益</span>
</div>
<div class="card">
<h3>🤷 你没跟 & AI错了</h3>
<div class="metric-value" style="font-size:28px;color:#8b949e">${totalE - fCorrect - fWrong - iCorrect}</div>
<span class="text-sm text-muted">你比AI更聪明</span>
</div>
</div>

<!-- Filter Bar -->
<div class="flex-row gap-8 p-24" style="padding-bottom:8px">
<span class="text-sm text-muted">筛选:</span>
<button class="btn btn-sm filter-btn active" data-filter="all" onclick="filterJournal('')">全部</button>
<button class="btn btn-sm filter-btn" data-filter="correct" onclick="filterJournal('correct')">✅ AI正确</button>
<button class="btn btn-sm filter-btn" data-filter="wrong" onclick="filterJournal('wrong')">❌ AI错误</button>
<button class="btn btn-sm filter-btn" data-filter="bought" onclick="filterJournal('','bought')">📈 跟随买入</button>
<button class="btn btn-sm filter-btn" data-filter="ignored" onclick="filterJournal('','ignored')">💤 未执行</button>
</div>

<!-- Journal Feed -->
<div style="padding:16px 24px">
<div id="journalFeed">
${entries.map((e) => _renderJournalEntry(e)).join('') || '<div class="empty-state"><div class="icon">📓</div><p>数据积累中，AI正在学习...</p></div>'}
</div>
</div>`;
    const extraScript = `
let currentVerdict = '';
let currentAction = '';

async function refreshJournal() {
    try {
        let url = '${constants_1.BASE_URL}/trust/journal?limit=30';
        if (currentVerdict) url += '&verdict=' + currentVerdict;
        if (currentAction) url += '&action=' + currentAction;
        const resp = await fetch(url);
        const data = await resp.json();
        const feed = document.getElementById('journalFeed');
        if (feed && data.entries) {
            feed.innerHTML = data.entries.map(e => _renderEntry(e)).join('') || '<div class="empty-state"><div class="icon">📓</div><p>暂无匹配记录</p></div>';
        }
    } catch(e) {}
}

function filterJournal(verdict, action) {
    currentVerdict = verdict || '';
    currentAction = action || '';
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.filter === (verdict || action));
    });
    vscode.postMessage({command:'navigate',page:'journal',verdict:currentVerdict,action:currentAction});
}

// Embedded render for dynamic refresh
function _renderEntry(e) {
    return ${JSON.stringify(_renderJournalEntry.toString())}.call ? ${_renderJournalEntry.toString()}(e) : '';
}

// Initial setup
document.querySelectorAll('.filter-btn').forEach(b => {
    b.addEventListener('click', function() { /* handled by onclick */ });
});`;
    return (0, layout_1.pageShell)('journal', 'Decision Journal · 决策日志', content, extraScript);
}
function _renderJournalEntry(e) {
    const s = e.snapshot || {};
    const dirLabel = s.direction === 'buy' ? '买入' : s.direction === 'sell' ? '卖出' : '持有';
    const dirColor = s.direction === 'buy' ? '#22C55E' : s.direction === 'sell' ? '#EF4444' : '#8b949e';
    const scoreColor = s.ai_score >= 80 ? '#22C55E' : s.ai_score >= 60 ? '#F59E0B' : '#EF4444';
    const daysAgo = _daysSince(s.created_at);
    return `
<div class="evidence-card" style="cursor:pointer;border-left:3px solid ${s.final_verdict === 'correct' ? '#22C55E' : s.final_verdict === 'wrong' ? '#EF4444' : '#6B7280'}">
<!-- Header -->
<div class="flex-between" style="margin-bottom:8px">
<div class="flex-row gap-8">
<span style="font-size:18px">${e.outcome_emoji || '⏳'}</span>
<span style="font-weight:600;font-size:14px">${s.stock_name || s.stock_code}</span>
<span class="stock-code">${s.stock_code}</span>
<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;background:#1b3a1b;color:${dirColor}">${dirLabel}</span>
</div>
<div class="flex-row gap-8">
<span style="color:#6B7280;font-size:11px">${daysAgo}</span>
<span style="font-weight:700;font-size:18px;color:${scoreColor}">${(s.ai_score || 50).toFixed(0)}分</span>
</div>
</div>

<!-- AI Recommendation -->
<div style="font-size:13px;color:#c9d1d9;margin-bottom:6px;line-height:1.5">${s.recommendation_text || ''}</div>

<!-- Evidence Signals -->
${s.signals && s.signals.length > 0 ? `
<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">
${s.signals.slice(0, 4).map((sig) => `<span style="font-size:10px;padding:2px 8px;border-radius:8px;background:#21262d;color:#8b949e">${sig.name} ${sig.score.toFixed(0)}</span>`).join('')}
</div>` : ''}

<!-- Action & Outcome Row -->
<div class="flex-between" style="margin-top:8px;padding-top:8px;border-top:1px solid #21262d">
<div class="flex-row gap-12">
<div>
<span class="text-sm text-muted">AI:</span>
<span style="font-size:12px;font-weight:600;color:${s.final_verdict === 'correct' ? '#22C55E' : s.final_verdict === 'wrong' ? '#EF4444' : '#8b949e'}">${s.final_verdict === 'correct' ? '✓ 正确' : s.final_verdict === 'wrong' ? '✗ 错误' : '⏳ 待验证'}</span>
</div>
<div>
<span class="text-sm text-muted">你:</span>
<span style="font-size:12px;font-weight:600;color:${s.user_action === 'ignored' ? '#F59E0B' : '#22C55E'}">${_actionLabel(s.user_action)}</span>
</div>
</div>
<div style="text-align:right">
${s.final_profit_pct !== 0 ? `<span style="font-size:14px;font-weight:700;color:${s.final_profit_pct >= 0 ? '#22C55E' : '#EF4444'}">${s.final_profit_pct >= 0 ? '+' : ''}${s.final_profit_pct.toFixed(1)}%</span>` : ''}
${s.ai_confidence ? `<span class="text-sm text-muted" style="margin-left:8px">置信${(s.ai_confidence * 100).toFixed(0)}%</span>` : ''}
</div>
</div>

<!-- Lesson -->
${e.lesson ? `
<div style="margin-top:6px;font-size:12px;color:#A78BFA;line-height:1.4">💡 ${e.lesson}</div>` : ''}

<!-- User notes -->
${s.user_notes ? `
<div style="margin-top:4px;font-size:11px;color:#6B7280;font-style:italic">📝 "${s.user_notes}"</div>` : ''}

<!-- AI Reflection -->
${s.ai_reflection ? `
<div style="margin-top:6px;font-size:11px;color:#9CA3AF;background:#0B1220;padding:8px;border-radius:4px">🤖 AI复盘: ${s.ai_reflection}</div>` : ''}
</div>`;
}
function _daysSince(iso) {
    if (!iso)
        return '';
    const now = new Date();
    const then = new Date(iso);
    const days = Math.floor((now.getTime() - then.getTime()) / 86400000);
    if (days === 0)
        return '今天';
    if (days === 1)
        return '昨天';
    if (days < 7)
        return `${days}天前`;
    if (days < 30)
        return `${Math.floor(days / 7)}周前`;
    if (days < 365)
        return `${Math.floor(days / 30)}月前`;
    return `${Math.floor(days / 365)}年前`;
}
function _actionLabel(action) {
    const labels = {
        bought: '✓ 已买入', sold: '✓ 已卖出', held: '✓ 继续持有',
        ignored: '✗ 未执行', partial: '◐ 部分执行', opposite: '↔ 反向操作',
    };
    return labels[action] || action || '—';
}
//# sourceMappingURL=journal.js.map