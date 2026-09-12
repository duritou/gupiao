"use strict";
/** Point-in-time Replay — exact journal date, historical bars, observed outcomes. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildReplayPage = buildReplayPage;
const constants_1 = require("../constants");
const layout_1 = require("../webview/layout");
function buildReplayPage(data) {
    const datesPayload = data.dates || {};
    const replayDates = datesPayload.dates || [];
    const models = datesPayload.models || [];
    const historyRuns = data.history?.runs || [];
    const defaultDate = datesPayload.default_date || replayDates[0]?.date || '';
    const defaultModel = models.find(model => model.id === 'balanced-v2')?.id
        || models[0]?.id || 'balanced-v2';
    const dateOptions = replayDates.map(item => `
<option value="${_escapeHtml(item.date)}">${item.stocks}只决策 · 后续${item.future_sessions}日</option>`).join('');
    const modelOptions = models.map(model => `
<option value="${_escapeHtml(model.id)}"${model.id === defaultModel ? ' selected' : ''}>${_escapeHtml(model.label)} · ${_escapeHtml(model.id)}</option>`).join('');
    const content = `
<div style="padding:22px 24px 8px">
<div class="flex-between" style="align-items:flex-start;gap:16px;flex-wrap:wrap">
<div>
<h1 style="font-size:20px;color:#A78BFA;margin-bottom:4px">Replay · 历史决策验证</h1>
<div style="font-size:12px;color:#8b949e">严格冻结到所选日期；未来K线只用于事后验证，不参与信号计算</div>
</div>
<span style="font-size:11px;color:#22C55E;border:1px solid #14532D;background:#052E16;padding:4px 8px;border-radius:999px">✓ Lookahead Safe</span>
</div>
</div>

<div style="padding:10px 24px 8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<input id="replayDate" list="replayDateOptions" type="date" value="${_escapeHtml(defaultDate)}" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#c9d1d9">
<datalist id="replayDateOptions">${dateOptions}</datalist>
<select id="replayModel" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;color:#c9d1d9">${modelOptions}</select>
<select id="replayHorizon" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;color:#c9d1d9">
<option value="1">验证1日</option><option value="3">验证3日</option><option value="5" selected>验证5日</option><option value="10">验证10日</option>
</select>
<button class="btn btn-primary" onclick="runReplay()">运行完整回放</button>
<button class="btn" onclick="runCompare()">策略口径对比</button>
<button class="btn" onclick="runSimulate()">持仓场景实验</button>
</div>
<div id="replayDateInfo" style="padding:0 24px 8px;font-size:11px;color:#8b949e"></div>
<div id="replayStatus" style="padding:0 24px;text-align:center"></div>
<div id="replayResults">
${defaultDate ? `
<div class="card" style="margin:12px 24px">
<div class="card-header"><h3>可回放日期</h3><span class="text-sm text-muted">${replayDates.length} 个决策日</span></div>
${_renderDateCoverage(replayDates)}
</div>
${_renderHistory(historyRuns)}` : _statusBlock('no_data', '当前决策日志中没有可回放日期。')}
</div>`;
    const datesJson = JSON.stringify(replayDates).replace(/</g, '\\u003c');
    const extraScript = `
${_escapeHtml.toString()}
${_fmtPct.toString()}
${_statusBlock.toString()}
${_renderDateCoverage.toString()}
${_renderHistory.toString()}
${_renderCandidateTable.toString()}
${_renderComparisonPanel.toString()}
${_renderSimulationPanel.toString()}
${_renderReport.toString()}
${_renderCompare.toString()}
${_renderSimulation.toString()}

const replayDates = ${datesJson};

function selectedReplayParams() {
    return {
        date: document.getElementById('replayDate').value,
        model: document.getElementById('replayModel').value,
        horizon: Number(document.getElementById('replayHorizon').value || 5),
    };
}

function updateReplayDateInfo() {
    const selected = document.getElementById('replayDate').value;
    const meta = replayDates.find(item => item.date === selected);
    const target = document.getElementById('replayDateInfo');
    if (!meta) {
        target.innerHTML = '<span style="color:#F59E0B">该日期没有决策快照，系统会明确返回无数据，不会借用其他日期。</span>';
        return;
    }
    const evalText = meta.evaluation_ready
        ? '<span style="color:#22C55E">可做5日验证</span>'
        : meta.partial_evaluation_ready
            ? '<span style="color:#F59E0B">仅可做短周期验证</span>'
            : '<span style="color:#8b949e">结果尚待后续行情</span>';
    target.innerHTML = '行情截点 ' + meta.market_data_date + ' · ' + meta.stocks + '只股票 · '
        + meta.decisive + '个原始方向信号 · 后续' + meta.future_sessions + '个交易日 · ' + evalText;
}

async function replayFetch(path, options, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs || 90000);
    try {
        const response = await fetch('${constants_1.BASE_URL}' + path, {...(options || {}), signal: controller.signal});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || ('HTTP ' + response.status));
        return payload;
    } finally {
        clearTimeout(timer);
    }
}

async function runReplay() {
    const params = selectedReplayParams();
    const status = document.getElementById('replayStatus');
    if (!params.date) { status.innerHTML = '<span style="color:#F59E0B">请选择日期</span>'; return; }
    status.innerHTML = '<div class="loading">正在冻结历史数据并重算信号</div>';
    try {
        const query = '?horizon_days=' + params.horizon + '&model_version=' + encodeURIComponent(params.model);
        const payload = await replayFetch('/replay/report/' + params.date + query, {}, 120000);
        document.getElementById('replayResults').innerHTML = _renderReport(payload);
        status.innerHTML = '';
    } catch (error) {
        status.innerHTML = '<span style="color:#f85149">回放失败：' + _escapeHtml(error.message || String(error)) + '</span>';
    }
}

async function runCompare() {
    const params = selectedReplayParams();
    const status = document.getElementById('replayStatus');
    status.innerHTML = '<div class="loading">正在同一冻结股票池上对比三套评分口径</div>';
    try {
        const payload = await replayFetch('/replay/compare', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                target_date: params.date,
                versions: ['technical-v1','balanced-v2','defensive-v2'],
                horizon_days: params.horizon,
                pool_size: 200,
            }),
        }, 120000);
        document.getElementById('replayResults').innerHTML = _renderCompare(payload);
        status.innerHTML = '';
    } catch (error) {
        status.innerHTML = '<span style="color:#f85149">对比失败：' + _escapeHtml(error.message || String(error)) + '</span>';
    }
}

async function runSimulate() {
    const params = selectedReplayParams();
    const status = document.getElementById('replayStatus');
    status.innerHTML = '<div class="loading">正在用真实后续K线评估持仓场景</div>';
    try {
        const payload = await replayFetch('/replay/simulate', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({target_date: params.date, pool_size: 200}),
        }, 120000);
        document.getElementById('replayResults').innerHTML = _renderSimulation(payload);
        status.innerHTML = '';
    } catch (error) {
        status.innerHTML = '<span style="color:#f85149">实验失败：' + _escapeHtml(error.message || String(error)) + '</span>';
    }
}

document.getElementById('replayDate').addEventListener('change', updateReplayDateInfo);
updateReplayDateInfo();`;
    return (0, layout_1.pageShell)('replay', 'Replay · 历史决策验证', content, extraScript);
}
function _escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[character]));
}
function _fmtPct(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(Number(value)))
        return '--';
    const number = Number(value);
    return `${number >= 0 ? '+' : ''}${number.toFixed(digits)}%`;
}
function _statusBlock(status, message) {
    const color = status === 'ok' ? '#22C55E' : status === 'outcomes_pending' ? '#F59E0B' : '#EF4444';
    return `<div class="card" style="margin:16px 24px;border-color:${color}55">
<div style="font-size:13px;color:${color};font-weight:600">${_escapeHtml(status)}</div>
<div style="font-size:12px;color:#c9d1d9;margin-top:6px">${_escapeHtml(message)}</div></div>`;
}
function _renderDateCoverage(dates) {
    return `<div style="display:flex;gap:8px;flex-wrap:wrap">
${dates.slice(0, 14).map(item => `<div style="padding:7px 9px;background:#0B1220;border:1px solid #1F2937;border-radius:6px;font-size:11px">
<div style="font-weight:600;color:#c9d1d9">${_escapeHtml(item.date)}</div>
<div style="color:#8b949e">${item.stocks}只 · 后续${item.future_sessions}日</div>
</div>`).join('')}</div>`;
}
function _renderHistory(runs) {
    if (!runs.length)
        return '';
    return `<div class="card" style="margin:12px 24px">
<div class="card-header"><h3>最近运行记录</h3><span class="text-sm text-muted">跨重启保存</span></div>
${runs.slice(0, 10).map(run => `<div class="flex-between" style="padding:6px 0;border-bottom:1px solid #21262d;font-size:11px">
<span><b>${_escapeHtml(run.mode)}</b> · ${_escapeHtml(run.replay_date)} · ${_escapeHtml(run.model_version || '--')}</span>
<span style="color:${run.status === 'ok' ? '#22C55E' : '#F59E0B'}">${_escapeHtml(run.status)} · ${_escapeHtml(String(run.created_at || '').slice(0, 19))}</span>
</div>`).join('')}</div>`;
}
function _renderCandidateTable(rows, horizon) {
    if (!rows?.length)
        return '<div style="font-size:12px;color:#8b949e">没有可重算的候选。</div>';
    return `<div style="overflow:auto"><table style="width:100%;border-collapse:collapse;font-size:11px">
<thead><tr style="color:#8b949e;text-align:left"><th>排名</th><th>股票</th><th>重算分</th><th>原分</th><th>方向</th><th>${horizon}日结果</th></tr></thead>
<tbody>${rows.slice(0, 15).map(row => `<tr style="border-top:1px solid #21262d">
<td style="padding:6px">${row.rank}</td>
<td style="padding:6px"><b>${_escapeHtml(row.stock_name)}</b><br><span style="color:#6B7280">${_escapeHtml(row.stock_code)}</span></td>
<td style="padding:6px;color:${row.fusion_score >= 65 ? '#22C55E' : '#c9d1d9'}">${Number(row.fusion_score).toFixed(1)}</td>
<td style="padding:6px">${Number(row.original_score || 0).toFixed(1)} <span style="color:#6B7280">(${Number(row.score_delta || 0) >= 0 ? '+' : ''}${Number(row.score_delta || 0).toFixed(1)})</span></td>
<td style="padding:6px">${_escapeHtml(row.direction)}</td>
<td style="padding:6px;color:${Number(row.forward_return_pct) >= 0 ? '#22C55E' : '#EF4444'}">${row.outcome_available ? _fmtPct(row.forward_return_pct, 2) : '待数据'}</td>
</tr>`).join('')}</tbody></table></div>`;
}
function _renderComparisonPanel(comparison) {
    const metrics = comparison?.metrics || {};
    const entries = Object.entries(metrics);
    return `<div class="card">
<div class="card-header"><h3>策略口径对比</h3><span class="text-sm text-muted">同一冻结股票池</span></div>
<div style="font-size:12px;color:${comparison?.status === 'ok' ? '#22C55E' : '#F59E0B'};margin-bottom:10px">${_escapeHtml(comparison?.improvement || comparison?.improvement_summary || '')}</div>
<div class="grid3" style="padding:0">${entries.map(([id, metric]) => `<div style="padding:10px;background:#0B1220;border:1px solid ${id === comparison.best_version ? '#22C55E' : '#1F2937'};border-radius:7px">
<div style="font-size:12px;font-weight:600;color:${id === comparison.best_version ? '#22C55E' : '#c9d1d9'}">${_escapeHtml(metric.label || id)}</div>
<div style="font-size:22px;font-weight:700;margin:6px 0">${metric.accuracy === null || metric.accuracy === undefined ? '--' : (Number(metric.accuracy) * 100).toFixed(1) + '%'}</div>
<div style="font-size:10px;color:#8b949e">验证 ${metric.evaluated_count} · 方向 ${metric.actionable_count} · 均值 ${_fmtPct(metric.avg_forward_return_pct, 2)}</div>
</div>`).join('')}</div></div>`;
}
function _renderSimulationPanel(simulation) {
    const results = simulation?.scenario_results || simulation?.results || {};
    const entries = Object.entries(results);
    return `<div class="card">
<div class="card-header"><h3>真实路径场景实验</h3><span class="text-sm text-muted">含0.2%往返成本</span></div>
${!entries.length ? '<div style="color:#8b949e;font-size:12px">暂无可评估场景。</div>' : `<div class="grid3" style="padding:0">${entries.map(([name, result]) => `<div style="padding:10px;background:#0B1220;border:1px solid ${name === simulation.best_scenario ? '#22C55E' : '#1F2937'};border-radius:7px">
<div style="font-size:12px;font-weight:600">${_escapeHtml(name)}</div>
<div style="font-size:21px;font-weight:700;color:${Number(result.total_return_pct) >= 0 ? '#22C55E' : '#EF4444'};margin:5px 0">${_fmtPct(result.total_return_pct, 2)}</div>
<div style="font-size:10px;color:#8b949e">${result.total_trades}笔 · 胜率 ${(Number(result.win_rate || 0) * 100).toFixed(0)}% · 回撤 ${Number(result.max_drawdown_pct || 0).toFixed(2)}%</div>
<div style="font-size:10px;color:#8b949e;margin-top:3px">Alpha ${_fmtPct(result.alpha_vs_baseline_pct, 2)}</div>
</div>`).join('')}</div>`}
${(simulation?.insights || []).map((insight) => `<div style="font-size:11px;color:#c9d1d9;margin-top:7px">💡 ${_escapeHtml(insight)}</div>`).join('')}</div>`;
}
function _renderReport(report) {
    if (report.status !== 'ok' && report.status !== 'insufficient_history') {
        return _statusBlock(report.status || 'no_data', report.message || '没有可回放数据。');
    }
    const context = report.context || {};
    const pipeline = report.pipeline_result || {};
    return `<div style="padding:14px 24px">
<div class="grid2" style="padding:0">
<div class="card"><div class="card-header"><h3>冻结环境</h3><span class="text-sm text-muted">${_escapeHtml(report.date)}</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">行情截点</span><b>${_escapeHtml(context.market_data_date || '--')}</b></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">涨/跌/平</span><span>${context.market_breadth_up || 0}/${context.market_breadth_down || 0}/${context.market_breadth_flat || 0}</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">市场覆盖</span><span>${context.market_coverage || 0}只</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">情绪宽度</span><span>${Number(context.market_sentiment || 0).toFixed(1)}</span></div>
<div style="font-size:10px;color:#22C55E;margin-top:7px">✓ 精确决策日 · ✓ K线截断 · ✓ 无未来函数</div></div>
<div class="card"><div class="card-header"><h3>重算结果</h3><span class="text-sm text-muted">${_escapeHtml(pipeline.model_label || pipeline.model_version || '')}</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">成功重算</span><span>${pipeline.scanned || 0}只</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">方向信号</span><span>${pipeline.candidates || 0}个</span></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">${pipeline.horizon_days || 5}日准确率</span><b>${pipeline.accuracy === null || pipeline.accuracy === undefined ? '待数据' : (Number(pipeline.accuracy) * 100).toFixed(1) + '% (' + pipeline.correct_count + '/' + pipeline.evaluated_count + ')'}</b></div>
<div class="flex-between" style="padding:3px 0"><span class="text-sm text-muted">确定性</span><span>${pipeline.is_deterministic === true ? '✓ 与上次一致' : pipeline.is_deterministic === false ? '✗ 结果变化' : '首次运行'}</span></div>
<div style="font-size:10px;color:#6B7280;margin-top:7px">Result ${_escapeHtml(pipeline.result_hash || '')}</div></div>
</div>
<div class="card"><div class="card-header"><h3>候选明细</h3><span class="text-sm text-muted">重算分 vs 当时记录分</span></div>${_renderCandidateTable(pipeline.candidate_rows || [], pipeline.horizon_days || 5)}</div>
${_renderComparisonPanel(report.model_comparison || {})}
${_renderSimulationPanel(report.simulation || {})}
</div>`;
}
function _renderCompare(data) {
    if (data.status === 'no_journal_data' || data.status === 'no_market_data') {
        return _statusBlock(data.status, data.improvement_summary || '没有可对比数据。');
    }
    return `<div style="padding:16px 24px">${_renderComparisonPanel(data)}</div>`;
}
function _renderSimulation(data) {
    return `<div style="padding:16px 24px">${_renderSimulationPanel(data)}</div>`;
}
//# sourceMappingURL=replay.js.map