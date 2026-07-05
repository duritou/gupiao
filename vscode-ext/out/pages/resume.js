"use strict";
/** AI Resume v5.0 — Cumulative trust profile proving AI capability. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildResumePage = buildResumePage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildResumePage(data) {
    const resume = data.resume || {};
    const versions = data.versions?.versions || [];
    const monthly = data.monthly?.monthly || [];
    const strategies = data.strategies?.strategies || [];
    const scoreRanges = data.scoreRanges?.ranges || [];
    const trackRecord = data.trackRecord || {};
    const accPct = ((resume.overall_accuracy || 0) * 100).toFixed(0);
    const content = `
<!-- Hero -->
<div style="text-align:center;padding:32px 24px 24px">
<div style="font-size:48px;margin-bottom:8px">🤖</div>
<h1 style="font-size:24px;color:#58a6ff;margin-bottom:4px">AI Research Terminal</h1>
<div style="font-size:14px;color:#8b949e">成立于 ${resume.established || '2026-06'} · 累计研究 ${(resume.total_studies || 0).toLocaleString()} 次</div>
</div>

<!-- Big Numbers -->
<div class="grid4">
<div class="card" style="text-align:center;border-left:3px solid #7C3AED">
<div style="font-size:32px;font-weight:700;color:#A78BFA">${(resume.total_recommendations || 0).toLocaleString()}</div>
<div class="text-sm text-muted">推荐股票</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #22C55E">
<div style="font-size:32px;font-weight:700;color:#22C55E">${(resume.correct_count || 0).toLocaleString()}</div>
<div class="text-sm text-muted">命中</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #F59E0B">
<div style="font-size:32px;font-weight:700;color:#F59E0B">${accPct}%</div>
<div class="text-sm text-muted">准确率</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #58a6ff">
<div style="font-size:32px;font-weight:700;color:#58a6ff">+${(resume.cumulative_user_return || 0).toFixed(0)}%</div>
<div class="text-sm text-muted">帮助用户收益</div>
</div>
</div>

<!-- Streaks + Performance -->
<div class="grid2" style="padding:16px 24px">
<div class="card">
<h3>连胜记录</h3>
<div style="display:flex;justify-content:space-around;text-align:center;padding:12px 0">
<div>
<div style="font-size:36px;font-weight:700;color:#22C55E">${resume.longest_streak || 0}</div>
<div class="text-sm text-muted">最长连续命中</div>
</div>
<div>
<div style="font-size:36px;font-weight:700;color:#22C55E">${resume.current_streak || 0}</div>
<div class="text-sm text-muted">当前连续命中</div>
</div>
</div>
</div>
<div class="card">
<h3>收益表现</h3>
<div style="display:flex;justify-content:space-around;text-align:center;padding:12px 0">
<div>
<div style="font-size:28px;font-weight:700;color:#22C55E">+${(resume.avg_return_per_rec || 0).toFixed(1)}%</div>
<div class="text-sm text-muted">平均收益/条</div>
</div>
<div>
<div style="font-size:28px;font-weight:700;color:#22C55E">${(trackRecord.beat_index_pct || 0).toFixed(0)}%</div>
<div class="text-sm text-muted">跑赢沪深300</div>
</div>
</div>
</div>
</div>

<!-- Best Strategy -->
<div style="padding:0 24px;margin-bottom:8px">
<div class="card" style="border-left:3px solid #22C55E">
<div class="card-header"><h3>🏆 最佳策略</h3></div>
<div style="font-size:16px;font-weight:600;color:#22C55E">${resume.best_strategy || '--'}</div>
<div class="text-sm text-muted">准确率 ${((resume.best_strategy_accuracy || 0) * 100).toFixed(0)}%</div>
</div>
</div>

<!-- Score Range Accuracy -->
<div style="padding:0 24px"><div class="card">
<div class="card-header"><h3>AI评分准确率分布</h3></div>
<div style="display:flex;flex-direction:column;gap:8px">
${scoreRanges.map((r) => `
<div style="display:flex;align-items:center;gap:12px">
<div style="width:80px;font-size:12px;font-weight:600;text-align:right">${r.range_label}</div>
<div style="flex:1;height:22px;background:#21262d;border-radius:4px;overflow:hidden;position:relative">
<div style="height:100%;width:${(r.accuracy * 100).toFixed(0)}%;background:${r.accuracy >= 0.7 ? '#22C55E' : r.accuracy >= 0.5 ? '#F59E0B' : '#EF4444'};border-radius:4px;transition:width 0.5s"></div>
<span style="position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:600;color:#fff">${(r.accuracy * 100).toFixed(0)}%</span>
</div>
<div style="width:50px;font-size:11px;color:#8b949e;text-align:right">${r.total}次</div>
</div>`).join('') || '<div class="empty-state"><p>数据积累中</p></div>'}
</div>
</div></div>

<!-- Strategy Breakdown -->
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>策略准确率排行</h3></div>
${strategies.slice(0, 6).map((s, i) => `
<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid #21262d">
<div style="width:20px;font-size:12px;color:#8b949e;text-align:center">#${i + 1}</div>
<div style="flex:1;font-size:13px;font-weight:600">${s.strategy}</div>
<div style="width:80px;display:flex;align-items:center;gap:4px">
<div style="flex:1;height:6px;background:#21262d;border-radius:3px">
<div style="height:6px;width:${(s.accuracy * 100).toFixed(0)}%;background:#22C55E;border-radius:3px"></div>
</div>
</div>
<div style="width:50px;text-align:right;font-size:13px;font-weight:600;color:${s.accuracy >= 0.7 ? '#22C55E' : '#8b949e'}">${(s.accuracy * 100).toFixed(0)}%</div>
<div style="width:40px;text-align:right;font-size:12px;color:${s.avg_return >= 0 ? '#22C55E' : '#EF4444'}">${s.avg_return >= 0 ? '+' : ''}${s.avg_return.toFixed(1)}%</div>
</div>`).join('') || '<div class="empty-state"><p>数据积累中</p></div>'}
</div></div>

<!-- Model Evolution -->
${versions.length > 0 ? `
<div style="padding:0 24px;margin-bottom:8px"><div class="card">
<div class="card-header"><h3>📈 AI版本演进</h3></div>
<div style="display:flex;align-items:flex-end;gap:16px;height:120px;padding:16px 0">
${versions.map((v) => {
        const h = Math.max(20, Math.round(v.accuracy * 100));
        return `<div style="flex:1;text-align:center">
<div style="font-size:12px;font-weight:600;color:#8b949e;margin-bottom:4px">${(v.accuracy * 100).toFixed(0)}%</div>
<div style="height:${h}px;background:${v.change_vs_prev >= 0 ? '#22C55E' : '#EF4444'};border-radius:4px 4px 0 0;margin:0 8px;position:relative">
${v.change_vs_prev !== 0 ? `<div style="position:absolute;top:-18px;left:50%;transform:translateX(-50%);font-size:10px;color:${v.change_vs_prev >= 0 ? '#22C55E' : '#EF4444'}">${v.change_vs_prev >= 0 ? '↑' : '↓'}${Math.abs(v.change_vs_prev * 100).toFixed(0)}%</div>` : ''}
</div>
<div style="font-size:11px;color:#58a6ff;margin-top:4px;font-weight:600">${v.version}</div>
<div style="font-size:10px;color:#8b949e">${v.total_recs}条推荐</div>
</div>`;
    }).join('')}
</div>
</div></div>` : ''}

<!-- Monthly Accuracy Trend -->
${monthly.length > 0 ? `
<div style="padding:0 24px;margin-bottom:16px"><div class="card">
<div class="card-header"><h3>月度准确率趋势</h3></div>
<div style="font-family:monospace;font-size:11px;color:#8b949e;line-height:2;text-align:center">
${_renderSparkline(monthly)}
</div>
<div style="display:flex;justify-content:space-between;margin-top:4px">
${monthly.map((m) => `<span style="font-size:10px;color:#6B7280">${m.month.slice(5)}</span>`).join('')}
</div>
</div></div>` : ''}
`;
    const extraScript = `
// Auto-load data on page open
async function refreshResume() {
    try {
        await Promise.all([
            fetch('${constants_1.BASE_URL}/trust/resume'),
            fetch('${constants_1.BASE_URL}/trust/model-evolution'),
            fetch('${constants_1.BASE_URL}/trust/monthly'),
            fetch('${constants_1.BASE_URL}/trust/strategies'),
            fetch('${constants_1.BASE_URL}/trust/score-ranges'),
            fetch('${constants_1.BASE_URL}/trust/track-record?days=30'),
        ]);
    } catch(e) {}
}
refreshResume();`;
    return (0, layout_1.pageShell)('resume', 'AI Resume · 信任档案', content, extraScript);
}
function _renderSparkline(monthly) {
    if (!monthly.length)
        return '数据不足';
    const accs = monthly.map(m => m.accuracy);
    const min = Math.min(...accs);
    const max = Math.max(...accs);
    const range = max - min || 1;
    const chars = '▁▂▃▄▅▆▇█';
    return accs.map(a => {
        const idx = Math.floor(((a - min) / range) * (chars.length - 1));
        const color = a >= 0.75 ? '#22C55E' : a >= 0.65 ? '#F59E0B' : '#EF4444';
        return `<span style="color:${color};font-size:16px">${chars[Math.min(idx, chars.length - 1)]}</span>`;
    }).join(' ');
}
//# sourceMappingURL=resume.js.map