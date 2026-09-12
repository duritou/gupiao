"use strict";
/** AI Resume v5.0 — Cumulative trust profile proving AI capability. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildResumePage = buildResumePage;
const layout_1 = require("../webview/layout");
function finiteNumber(value, fallback = 0) {
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}
function signedPercent(value, digits = 1) {
    const number = finiteNumber(value);
    return `${number > 0 ? '+' : ''}${number.toFixed(digits)}%`;
}
function buildResumePage(data) {
    const resume = data?.resume || {};
    const versions = data.versions?.versions || [];
    const monthly = data.monthly?.monthly || [];
    const strategies = data.strategies?.strategies || [];
    const scoreRanges = data.scoreRanges?.ranges || [];
    const trackRecord = data.trackRecord || {};
    const accPct = resume.accuracy_available
        ? `${(finiteNumber(resume.overall_accuracy) * 100).toFixed(1)}%`
        : '待验证';
    const errorHtml = data?.resumeError
        ? `<div class="card" style="border-left:3px solid #f85149">AI Resume 加载失败：${String(data.resumeError)}</div>`
        : '';
    const content = `
<style>
.resume-page{padding-bottom:16px}.resume-page .resume-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;padding:16px 24px}
.resume-page .resume-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;padding:16px 24px}
.resume-page .resume-stat-row{display:flex;justify-content:space-around;gap:16px;text-align:center;padding:12px 0;flex-wrap:wrap}
.resume-page .resume-stat-row>div{min-width:120px;flex:1}.resume-page .resume-number{font-size:32px;font-weight:700;line-height:1.15;overflow-wrap:anywhere}
.resume-page .strategy-name{flex:1;min-width:0;font-size:13px;font-weight:600;overflow-wrap:anywhere}
.resume-page .model-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:16px;padding:8px 0}
.resume-page .model-item{text-align:center;min-width:0}.resume-page .model-bar-area{height:80px;display:flex;align-items:flex-end;justify-content:center;margin:6px 8px}
.resume-page .model-bar{width:100%;max-width:72px;min-height:4px;border-radius:4px 4px 0 0}
@media(max-width:520px){.resume-page .resume-metrics,.resume-page .resume-columns{grid-template-columns:1fr;padding-left:16px;padding-right:16px}.resume-page .resume-number{font-size:28px}}
</style>
<div class="resume-page">
${errorHtml}
<!-- Hero -->
<div style="text-align:center;padding:32px 24px 24px">
<div style="font-size:48px;margin-bottom:8px">🤖</div>
<h1 style="font-size:24px;color:#58a6ff;margin-bottom:4px">Adaptive Investment Intelligence</h1>
<div style="font-size:14px;color:#8b949e">成立于 ${resume.established || '2026-06'} · 累计研究 ${(resume.total_studies || 0).toLocaleString()} 次</div>
</div>

<!-- Big Numbers -->
<div class="resume-metrics">
<div class="card" style="text-align:center;border-left:3px solid #7C3AED">
<div class="resume-number" style="color:#A78BFA">${finiteNumber(resume.total_recommendations).toLocaleString()}</div>
<div class="text-sm text-muted">推荐股票</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #22C55E">
<div class="resume-number" style="color:#22C55E">${finiteNumber(resume.correct_count).toLocaleString()}</div>
<div class="text-sm text-muted">命中</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #F59E0B">
<div class="resume-number" style="color:#F59E0B">${accPct}</div>
<div class="text-sm text-muted">方向准确率</div>
</div>
<div class="card" style="text-align:center;border-left:3px solid #58a6ff">
<div class="resume-number" style="color:${finiteNumber(resume.cumulative_user_return) >= 0 ? '#22C55E' : '#EF4444'}">${signedPercent(resume.cumulative_user_return, 1)}</div>
<div class="text-sm text-muted">模拟组合收益</div>
</div>
</div>

<!-- Streaks + Performance -->
<div class="resume-columns">
<div class="card">
<h3>连胜记录</h3>
<div class="resume-stat-row">
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
<div class="resume-stat-row">
<div>
<div style="font-size:28px;font-weight:700;color:${finiteNumber(resume.avg_return_per_rec) >= 0 ? '#22C55E' : '#EF4444'}">${signedPercent(resume.avg_return_per_rec)}</div>
<div class="text-sm text-muted">平均收益/条</div>
</div>
<div>
<div style="font-size:28px;font-weight:700;color:${finiteNumber(trackRecord.beat_index_pct) >= 0 ? '#22C55E' : '#EF4444'}">${signedPercent(trackRecord.beat_index_pct, 0)}</div>
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
${scoreRanges.map((r) => {
        const accuracy = finiteNumber(r.accuracy);
        return `
<div style="display:flex;align-items:center;gap:12px">
<div style="width:80px;font-size:12px;font-weight:600;text-align:right">${r.range_label}</div>
<div style="flex:1;height:22px;background:#21262d;border-radius:4px;overflow:hidden;position:relative">
<div style="height:100%;width:${(accuracy * 100).toFixed(0)}%;background:${accuracy >= 0.7 ? '#22C55E' : accuracy >= 0.5 ? '#F59E0B' : '#EF4444'};border-radius:4px;transition:width 0.5s"></div>
<span style="position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:600;color:#fff">${(accuracy * 100).toFixed(0)}%</span>
</div>
<div style="width:50px;font-size:11px;color:#8b949e;text-align:right">${r.total}次</div>
</div>`;
    }).join('') || '<div class="empty-state"><p>数据积累中</p></div>'}
</div>
</div></div>

<!-- Strategy Breakdown -->
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>策略准确率排行</h3></div>
${strategies.slice(0, 6).map((s, i) => {
        const accuracy = finiteNumber(s.accuracy);
        const avgReturn = finiteNumber(s.avg_return);
        return `
<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid #21262d">
<div style="width:20px;font-size:12px;color:#8b949e;text-align:center">#${i + 1}</div>
<div class="strategy-name">${s.strategy}</div>
<div style="width:80px;display:flex;align-items:center;gap:4px">
<div style="flex:1;height:6px;background:#21262d;border-radius:3px">
<div style="height:6px;width:${(accuracy * 100).toFixed(0)}%;background:#22C55E;border-radius:3px"></div>
</div>
</div>
<div style="width:50px;text-align:right;font-size:13px;font-weight:600;color:${accuracy >= 0.7 ? '#22C55E' : '#8b949e'}">${(accuracy * 100).toFixed(0)}%</div>
<div style="width:52px;text-align:right;font-size:12px;color:${avgReturn >= 0 ? '#22C55E' : '#EF4444'}">${signedPercent(avgReturn)}</div>
</div>`;
    }).join('') || '<div class="empty-state"><p>数据积累中</p></div>'}
</div></div>

<!-- Model Evolution -->
${versions.length > 0 ? `
<div style="padding:0 24px;margin-bottom:8px"><div class="card">
<div class="card-header"><h3>📈 AI版本演进</h3></div>
<div class="model-grid">
${versions.map((v) => {
        const accuracy = finiteNumber(v.accuracy);
        const change = finiteNumber(v.change_vs_prev);
        const available = v.accuracy_available === true;
        const h = available ? Math.max(8, Math.round(accuracy * 80)) : 4;
        return `<div class="model-item">
<div style="font-size:12px;font-weight:600;color:${available ? '#c9d1d9' : '#8b949e'}">${available ? (accuracy * 100).toFixed(1) + '%' : '待验证'}</div>
<div class="model-bar-area"><div class="model-bar" style="height:${h}px;background:${available ? '#22C55E' : '#30363d'}"></div></div>
<div style="font-size:11px;color:#58a6ff;margin-top:4px;font-weight:600">${v.version}</div>
<div style="font-size:10px;color:#8b949e">${v.total_recs}条推荐</div>
${available && change !== 0 ? `<div style="font-size:10px;color:${change >= 0 ? '#22C55E' : '#EF4444'};margin-top:2px">较上版 ${signedPercent(change * 100, 0)}</div>` : ''}
</div>`;
    }).join('')}
</div>
</div></div>` : ''}

<!-- Monthly Accuracy Trend -->
${monthly.some((m) => m.accuracy_available) ? `
<div style="padding:0 24px;margin-bottom:16px"><div class="card">
<div class="card-header"><h3>月度准确率趋势</h3></div>
<div style="font-family:monospace;font-size:11px;color:#8b949e;line-height:2;text-align:center">
${_renderSparkline(monthly)}
</div>
<div style="display:flex;justify-content:space-between;margin-top:4px">
${monthly.map((m) => `<span style="font-size:10px;color:#6B7280">${m.month.slice(5)}</span>`).join('')}
</div>
</div></div>` : ''}
</div>
`;
    const extraScript = `
// This page is mostly daily data; refresh and re-render when it remains open.
setInterval(() => vscode.postMessage({command:'refreshPage'}), 300000);`;
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