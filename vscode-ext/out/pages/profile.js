"use strict";
/** User Profile v6.0 — Adaptive Intelligence: what AI learned about you.
 *
 * Nothing is configured. Everything is discovered from your behavior.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildProfilePage = buildProfilePage;
const layout_1 = require("../webview/layout");
function buildProfilePage(data) {
    const profile = data.profile || {};
    const style = profile.investment_style || {};
    const risk = profile.risk_profile || {};
    const sectors = profile.sector_affinities || [];
    const strategies = profile.strategy_strengths || [];
    const patterns = profile.behavior_patterns || [];
    const alignment = profile.ai_alignment || {};
    const content = `
<!-- Hero -->
<div style="text-align:center;padding:32px 24px 16px">
<div style="font-size:40px;margin-bottom:8px">🧠</div>
<h1 style="font-size:22px;color:#A78BFA;margin-bottom:4px">AI 了解你</h1>
<div style="font-size:13px;color:#8b949e">基于 ${profile.total_decisions_analyzed || 0} 次决策自动学习 · 零人工配置</div>
</div>

<!-- Summary Paragraph -->
<div style="padding:0 24px;margin-bottom:12px"><div class="card" style="border-left:3px solid #7C3AED">
<div style="font-size:13px;color:#c9d1d9;line-height:1.7">${profile.user_summary || '数据积累中...'}</div>
</div></div>

<!-- Investment Style + Risk -->
<div class="grid2">
<div class="card">
<h3>📊 投资风格</h3>
<div style="text-align:center;padding:12px 0">
<div style="font-size:32px;font-weight:700;color:#58a6ff">${style.primary_style || '学习中'}</div>
<div style="font-size:12px;color:#8b949e">置信度 ${((style.confidence || 0) * 100).toFixed(0)}%</div>
</div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">平均持有</span><span style="font-weight:600">${(style.avg_holding_days || 0).toFixed(0)}天</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">持仓稳定性</span><span style="font-weight:600">${(style.holding_consistency || 0).toFixed(0)}/30</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">换手率</span><span style="font-weight:600">${((style.turnover_rate || 0) * 100).toFixed(0)}%</span></div>
</div>
<div class="card">
<h3>⚖ 风险偏好</h3>
<div style="text-align:center;padding:12px 0">
<div style="font-size:32px;font-weight:700;color:${risk.level === '激进型' ? '#EF4444' : risk.level === '保守型' ? '#22C55E' : '#F59E0B'}">${risk.level || '学习中'}</div>
<div style="font-size:12px;color:#8b949e">置信度 ${((risk.confidence || 0) * 100).toFixed(0)}%</div>
</div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">最大单仓位</span><span style="font-weight:600">${(risk.max_position_size_pct || 0).toFixed(0)}%</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">止损执行力</span><span style="font-weight:600">${((risk.stop_loss_adherence || 0) * 100).toFixed(0)}%</span></div>
<div class="flex-between" style="padding:4px 0"><span class="text-sm text-muted">容忍最大回撤</span><span style="font-weight:600">${(risk.max_drawdown_tolerated_pct || 0).toFixed(0)}%</span></div>
</div>
</div>

<!-- Sector Affinities -->
<div style="padding:0 24px"><div class="card">
<div class="card-header"><h3>🏭 行业能力圈</h3><span class="text-sm text-muted">AI自动发现</span></div>
${sectors.length > 0 ? sectors.map((s) => `
<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #21262d">
<div style="width:80px;font-size:13px;font-weight:600">${s.sector}</div>
<div style="flex:1">
<div style="display:flex;align-items:center;gap:8px">
<div style="flex:1;height:8px;background:#21262d;border-radius:4px">
<div style="height:8px;width:${(s.affinity_score * 100).toFixed(0)}%;background:${s.is_strength ? '#22C55E' : '#8b949e'};border-radius:4px"></div>
</div>
<span style="font-size:10px;color:#8b949e">${s.trade_count}次</span>
</div>
</div>
<div style="width:60px;text-align:right;font-size:13px;font-weight:600;color:${s.win_rate >= 0.6 ? '#22C55E' : '#8b949e'}">${(s.win_rate * 100).toFixed(0)}%</div>
<div style="width:70px;text-align:right;font-size:12px;color:${s.avg_return >= 0 ? '#22C55E' : '#EF4444'}">${s.avg_return >= 0 ? '+' : ''}${s.avg_return.toFixed(1)}%</div>
${s.is_strength ? '<span style="font-size:10px;color:#22C55E">★优势</span>' : ''}
</div>`).join('') : '<div class="empty-state"><p>数据积累中</p></div>'}
</div></div>

<!-- Strategy Strengths -->
${strategies.length > 0 ? `
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>🎯 策略适配度</h3><span class="text-sm text-muted">哪些信号你最擅长跟随</span></div>
${strategies.slice(0, 5).map((s) => `
<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid #21262d">
<span style="font-size:13px;flex:1">${s.strategy_name}</span>
<span style="font-size:11px;color:#8b949e">${s.times_correct}/${s.times_used}次</span>
<div style="width:60px;height:6px;background:#21262d;border-radius:3px">
<div style="height:6px;width:${(s.win_rate * 100).toFixed(0)}%;background:#22C55E;border-radius:3px"></div>
</div>
<span style="font-size:12px;font-weight:600;color:#22C55E;width:45px;text-align:right">${(s.win_rate * 100).toFixed(0)}%</span>
${s.is_best ? '<span style="font-size:9px;background:#1b3a1b;color:#22C55E;padding:2px 6px;border-radius:8px">最强</span>' : ''}
</div>`).join('')}
</div></div>` : ''}

<!-- Behavior Patterns -->
<div style="padding:0 24px"><div class="card">
<div class="card-header"><h3>🔍 行为特征</h3><span class="text-sm text-muted">AI自动识别</span></div>
${patterns.length > 0 ? patterns.map((p) => `
<div class="evidence-card" style="border-left:3px solid ${p.pattern_type === 'strength' ? '#22C55E' : '#F59E0B'}">
<div class="flex-between" style="margin-bottom:4px">
<span style="font-weight:600;font-size:13px;color:${p.pattern_type === 'strength' ? '#22C55E' : '#F59E0B'}">${p.pattern_type === 'strength' ? '✓ 优势' : '⚠ 待改善'} ${p.pattern_name}</span>
<span class="text-sm text-muted">${p.evidence_count}次观察</span>
</div>
<div style="font-size:12px;color:#c9d1d9;line-height:1.5">${p.description}</div>
</div>`).join('') : '<div class="empty-state"><p>数据积累中</p></div>'}
</div></div>

<!-- AI Alignment -->
${alignment.overall_follow_rate ? `
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>🤝 AI信任度</h3></div>
<div class="grid4" style="padding:0">
<div style="text-align:center;padding:12px">
<div style="font-size:24px;font-weight:700;color:#A78BFA">${(alignment.trust_score * 100).toFixed(0)}%</div>
<div class="text-sm text-muted">综合信任度</div>
</div>
<div style="text-align:center;padding:12px">
<div style="font-size:24px;font-weight:700;color:#58a6ff">${(alignment.overall_follow_rate * 100).toFixed(0)}%</div>
<div class="text-sm text-muted">总体跟随率</div>
</div>
<div style="text-align:center;padding:12px">
<div style="font-size:24px;font-weight:700;color:${alignment.trust_trend === '上升中' ? '#22C55E' : alignment.trust_trend === '下降中' ? '#EF4444' : '#8b949e'}">${alignment.trust_trend || '稳定'}</div>
<div class="text-sm text-muted">信任趋势</div>
</div>
<div style="text-align:center;padding:12px">
<div style="font-size:24px;font-weight:700;color:#F59E0B">${(alignment.follow_rate_high_confidence * 100).toFixed(0)}%</div>
<div class="text-sm text-muted">高置信跟随率</div>
</div>
</div>
${alignment.trust_gap_pct > 10 ? `
<div style="padding:8px;background:#3a351b;border-radius:6px;margin-top:8px;font-size:12px;color:#F59E0B">
💡 你错过了 ${alignment.trust_gap_pct.toFixed(0)}% 的AI正确建议收益。当AI置信度≥80%时，建议提高跟随比例。
</div>` : ''}
</div></div>` : ''}
`;
    return (0, layout_1.pageShell)('profile', 'AI Profile · 投资画像', content, '');
}
//# sourceMappingURL=profile.js.map