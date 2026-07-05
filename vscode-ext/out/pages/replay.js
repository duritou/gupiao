"use strict";
/** Replay & Simulation Engine v7.1 — time machine for AI validation. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildReplayPage = buildReplayPage;
const layout_1 = require("../webview/layout");
const constants_1 = require("../constants");
function buildReplayPage(data) {
    const report = data.report || {};
    const ctx = report.context || {};
    const pipeline = report.pipeline_result || {};
    const comparison = report.model_comparison || {};
    const simulation = report.simulation || {};
    const summary = report.summary || '';
    const defaultDate = report.date || '2024-09-10';
    const content = `
<!-- Time Machine Header -->
<div style="text-align:center;padding:24px 24px 0">
<div style="font-size:36px;margin-bottom:8px">⏰</div>
<h1 style="font-size:20px;color:#A78BFA">Replay & Simulation Engine</h1>
<div style="font-size:12px;color:#8b949e;margin-top:4px">时间机器 — 回到过去，验证AI，实验策略</div>
</div>

<!-- Date Selector -->
<div style="padding:16px 24px;display:flex;gap:8px;align-items:center;justify-content:center">
<input id="replayDate" type="date" value="${defaultDate}" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#c9d1d9">
<button class="btn btn-primary" onclick="runReplay()">⚡ 运行回放</button>
<button class="btn" onclick="runCompare()">🔬 版本对比</button>
<button class="btn" onclick="runSimulate()">🧪 策略实验</button>
</div>

<!-- Status -->
<div id="replayStatus" style="padding:0 24px;text-align:center"></div>

<!-- Results Container -->
<div id="replayResults">
${report.date ? _renderReport(report) : `
<div class="empty-state" style="padding:48px">
<div class="icon">⏰</div>
<h2>选择日期开始回放</h2>
<p>输入任意历史日期，AI将精确复现当天的决策过程</p>
</div>`}
</div>`;
    const extraScript = `
async function runReplay() {
    const date = document.getElementById('replayDate').value;
    const status = document.getElementById('replayStatus');
    status.innerHTML = '<div class="loading">运行中</div>';

    try {
        const resp = await fetch('${constants_1.BASE_URL}/replay/report/' + date);
        const data = await resp.json();
        document.getElementById('replayResults').innerHTML = _renderReport(data);
        status.innerHTML = '';
    } catch(e) {
        status.innerHTML = '<span style="color:#f85149">运行失败: ' + e.message + '</span>';
    }
}

async function runCompare() {
    const date = document.getElementById('replayDate').value;
    const status = document.getElementById('replayStatus');
    status.innerHTML = '<div class="loading">对比中</div>';

    try {
        const resp = await fetch('${constants_1.BASE_URL}/replay/compare', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({target_date:date,versions:['v4.0','v4.2','v5.0','v6.0']})
        });
        const data = await resp.json();
        document.getElementById('replayResults').innerHTML = _renderCompare(data);
        status.innerHTML = '';
    } catch(e) {
        status.innerHTML = '<span style="color:#f85149">对比失败</span>';
    }
}

async function runSimulate() {
    const date = document.getElementById('replayDate').value;
    const status = document.getElementById('replayStatus');
    status.innerHTML = '<div class="loading">实验中</div>';

    try {
        const resp = await fetch('${constants_1.BASE_URL}/replay/simulate', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({target_date:date})
        });
        const data = await resp.json();
        document.getElementById('replayResults').innerHTML = _renderSimulation(data);
        status.innerHTML = '';
    } catch(e) {
        status.innerHTML = '<span style="color:#f85149">实验失败</span>';
    }
}`;
    return (0, layout_1.pageShell)('replay', 'Replay Engine · 时间机器', content, extraScript);
}
function _renderReport(r) {
    const ctx = r.context || {};
    const pipe = r.pipeline_result || {};
    const comp = r.model_comparison || {};
    const sim = r.simulation || {};
    return `
<div class="grid2" style="padding:16px 24px">
<!-- Frozen World -->
<div class="card">
<div class="card-header"><h3>🧊 冻结世界</h3><span class="text-sm text-muted">${r.date || ''}</span></div>
<div style="font-size:11px;font-family:monospace;color:#6B7280;margin-bottom:4px">Hash: ${ctx.context_hash || ''}</div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">指数</span><span style="font-size:13px">${ctx.index_level?.toFixed(0) || '?'} <span style="color:${ctx.index_change_pct >= 0 ? '#22C55E' : '#EF4444'}">${ctx.index_change_pct >= 0 ? '+' : ''}${ctx.index_change_pct?.toFixed(1) || 0}%</span></span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">涨跌比</span><span style="font-size:13px">${ctx.market_breadth_up || 0}/${ctx.market_breadth_down || 0}</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">北向</span><span style="font-size:13px;color:${ctx.northbound_flow >= 0 ? '#22C55E' : '#EF4444'}">${ctx.northbound_flow >= 0 ? '+' : ''}${ctx.northbound_flow?.toFixed(0) || 0}亿</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">股票池</span><span style="font-size:13px">${ctx.stock_pool_count || 0}只</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">AI版本</span><span style="font-size:13px;color:#58a6ff">${ctx.model_version || 'v6.0'}</span></div>
</div>

<!-- Pipeline Result -->
<div class="card">
<div class="card-header"><h3>⚡ 重放结果</h3><span class="text-sm text-muted">${pipe.is_deterministic === true ? '✓ 确定性已验证' : pipe.is_deterministic === false ? '✗ 不一致' : '⏳ 首次运行'}</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">扫描</span><span style="font-size:13px">${pipe.scanned || 0}只</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">候选</span><span style="font-size:13px">${pipe.candidates || 0}只</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">Top Pick</span><span style="font-weight:600">${pipe.top_pick?.stock_name || '--'} <span style="color:#22C55E">${pipe.top_pick?.fusion_score?.toFixed(0) || ''}</span></span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">Result Hash</span><span style="font-size:10px;font-family:monospace;color:#6B7280">${pipe.result_hash || ''}</span></div>
</div>
</div>

<!-- Model Comparison -->
<div style="padding:0 24px"><div class="card">
<div class="card-header"><h3>🔬 模型版本对比</h3></div>
<div style="font-size:13px;color:#22C55E;margin-bottom:8px">${comp.improvement || ''}</div>
${comp.accuracy_by_version ? Object.entries(comp.accuracy_by_version).map(([v, acc]) => {
        const pct = ((Number(acc)) * 100).toFixed(0);
        const isBest = v === comp.best_version;
        return `<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid #21262d">
<span style="width:50px;font-weight:600;color:${isBest ? '#22C55E' : '#8b949e'}">${v}</span>
<div style="flex:1;height:24px;background:#21262d;border-radius:4px;overflow:hidden">
<div style="height:24px;width:${Math.abs(Number(pct))}%;background:${isBest ? '#22C55E' : '#8b949e'};border-radius:4px;display:flex;align-items:center;padding-left:8px">
<span style="font-size:11px;font-weight:600;color:#fff">${Number(acc) >= 0 ? '+' : ''}${pct}%</span>
</div></div>
${isBest ? '<span style="font-size:10px;color:#22C55E">★最优</span>' : ''}
</div>`;
    }).join('') : ''}
</div></div>

<!-- Simulation -->
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>🧪 策略实验</h3></div>
<div class="grid4" style="padding:0">
${sim.scenario_results ? Object.entries(sim.scenario_results).slice(0, 5).map(([name, res]) => `
<div style="text-align:center;padding:8px">
<div style="font-weight:600;font-size:13px;margin-bottom:4px">${name}</div>
<div style="font-size:20px;font-weight:700;color:${res.total_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${res.total_return_pct >= 0 ? '+' : ''}${res.total_return_pct}%</div>
<div style="font-size:10px;color:#8b949e">回撤 ${res.max_drawdown_pct}% · 胜率 ${(res.win_rate * 100).toFixed(0)}%</div>
<div style="font-size:10px;color:${res.alpha_vs_baseline_pct >= 0 ? '#22C55E' : '#EF4444'}">Alpha ${res.alpha_vs_baseline_pct >= 0 ? '+' : ''}${res.alpha_vs_baseline_pct}</div>
</div>`).join('') : ''}
</div>
${sim.insights ? sim.insights.map((i) => `<div style="font-size:12px;color:#c9d1d9;margin-top:6px">💡 ${i}</div>`).join('') : ''}
</div></div>
`;
}
function _renderCompare(data) {
    const comp = data;
    return `
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>🔬 模型版本对比 · ${data.replay_date || ''}</h3></div>
<div style="font-size:13px;color:#22C55E;margin-bottom:12px">${comp.improvement_summary || ''}</div>
${comp.accuracy_change ? Object.entries(comp.accuracy_change).map(([v, acc]) => {
        const pct = (Number(acc) * 100 + 65).toFixed(0);
        return `<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #21262d">
<span style="font-weight:600;width:50px;color:${v === comp.best_version ? '#22C55E' : '#8b949e'}">${v}</span>
<div style="flex:1;height:28px;background:#21262d;border-radius:4px;overflow:hidden">
<div style="height:28px;width:${pct}%;background:${v === comp.best_version ? '#22C55E' : '#8b949e'};border-radius:4px;display:flex;align-items:center;padding-left:8px">
<span style="font-size:12px;font-weight:600;color:#fff">${pct}%</span>
</div></div>
${v === comp.best_version ? '<span style="font-size:10px;background:#1b3a1b;color:#22C55E;padding:2px 6px;border-radius:8px">最优</span>' : ''}
</div>`;
    }).join('') : '<div class="empty-state"><p>运行中...</p></div>'}
</div></div>`;
}
function _renderSimulation(data) {
    return `
<div style="padding:16px 24px"><div class="card">
<div class="card-header"><h3>🧪 策略实验 · ${data.replay_date || ''}</h3><span class="text-sm text-muted">${data.base_scenario || 'baseline'} vs 场景</span></div>
<div class="grid3" style="padding:0">
${data.results ? Object.entries(data.results).map(([name, res]) => `
<div style="text-align:center;padding:12px;background:#0B1220;border-radius:8px;border:1px solid ${name === data.best_scenario ? '#22C55E' : '#1F2937'}">
<div style="font-weight:600;font-size:14px;margin-bottom:6px;color:${name === data.best_scenario ? '#22C55E' : '#c9d1d9'}">${name}</div>
<div style="font-size:24px;font-weight:700;color:${res.total_return_pct >= 0 ? '#22C55E' : '#EF4444'}">${res.total_return_pct >= 0 ? '+' : ''}${res.total_return_pct}%</div>
<div style="font-size:11px;color:#8b949e;margin-top:2px">${res.total_trades}笔交易</div>
<div style="display:flex;justify-content:space-around;margin-top:8px;font-size:11px">
<span>回撤 <b style="color:#EF4444">${res.max_drawdown_pct}%</b></span>
<span>胜率 <b style="color:#22C55E">${(res.win_rate * 100).toFixed(0)}%</b></span>
</div>
<div style="margin-top:4px;font-size:11px;color:${res.alpha_vs_baseline_pct >= 0 ? '#22C55E' : '#EF4444'}">vs Base: ${res.alpha_vs_baseline_pct >= 0 ? '+' : ''}${res.alpha_vs_baseline_pct}%</div>
</div>`).join('') : ''}
</div>
${data.insights ? data.insights.map((i) => `<div style="font-size:12px;color:#c9d1d9;margin-top:8px">💡 ${i}</div>`).join('') : ''}
</div></div>`;
}
//# sourceMappingURL=replay.js.map