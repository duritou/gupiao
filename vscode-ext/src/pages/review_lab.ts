import { pageShell } from '../webview/layout';
import { REVIEW_LEARNING_GUIDE } from '../review-lab/model';

function escapeHtml(value: unknown): string {
    return String(value ?? '--').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char] || char));
}

function renderTrade(trade: any): string {
    return `<tr><td>${escapeHtml(trade.symbol)}</td><td>${escapeHtml(trade.buy_date)}</td>
<td>${escapeHtml(trade.sell_date)}</td><td>${escapeHtml(trade.quantity)}</td>
<td>${escapeHtml(trade.entry_price)}</td><td>${escapeHtml(trade.exit_price)}</td>
<td class="${Number(trade.net_pnl) >= 0 ? 'up' : 'down'}">${escapeHtml(trade.net_pnl)}</td></tr>`;
}

function renderMetric(key: string, value: any): string {
    if (value && typeof value === 'object') return '';
    return `<span style="display:inline-block;margin:3px 6px 3px 0;padding:3px 7px;border:1px solid #30363d;border-radius:999px;color:#c9d1d9;font-size:11px">${escapeHtml(key)}：${escapeHtml(value)}</span>`;
}

function renderProjectReview(item: any): string {
    const findings = Array.isArray(item?.findings) ? item.findings : [];
    const limitations = Array.isArray(item?.limitations) ? item.limitations : [];
    const metrics = item?.metrics && typeof item.metrics === 'object' ? item.metrics : {};
    const metricHtml = Object.entries(metrics).map(([key, value]) => renderMetric(key, value)).join('');
    const facts = Array.isArray(item?.facts) ? item.facts : [];
    const watchNext = Array.isArray(item?.watch_next) ? item.watch_next : [];
    const status = item?.status === 'completed' ? 'completed' : 'partial / data limited';
    return `<section style="border-top:1px solid #30363d;padding:14px 0">
<div class="flex-between" style="gap:12px;align-items:flex-start"><div><strong>${escapeHtml(item?.project)}</strong><div class="text-sm text-muted">${escapeHtml(item?.title)}</div></div>
<span class="text-sm ${item?.status === 'completed' ? 'up' : 'text-muted'}">${escapeHtml(status)}</span></div>
${metricHtml ? `<div style="margin:7px 0">${metricHtml}</div>` : ''}
${facts.length ? `<div class="text-sm"><strong>数据事实</strong><ul style="margin:5px 0;padding-left:20px">${facts.map((fact: unknown) => `<li style="margin:4px 0">${escapeHtml(fact)}</li>`).join('')}</ul></div>` : ''}
${findings.length ? `<ul class="text-sm" style="margin:7px 0;padding-left:20px">${findings.map((finding: unknown) => `<li style="margin:4px 0">${escapeHtml(finding)}</li>`).join('')}</ul>` : '<p class="text-sm text-muted">暂无观察结论。</p>'}
${item?.interpretation ? `<p class="text-sm"><strong>复盘推断：</strong>${escapeHtml(item.interpretation)}</p>` : ''}
${watchNext.length ? `<p class="text-sm"><strong>下一步验证：</strong>${watchNext.map((value: unknown) => escapeHtml(value)).join('；')}</p>` : ''}
${limitations.length ? `<p class="text-sm text-muted" style="margin:7px 0">边界：${limitations.map((value: unknown) => escapeHtml(value)).join('；')}</p>` : ''}</section>`;
}

function renderIndustryViews(views: any[]): string {
    const groups = views.filter(view => Array.isArray(view?.items) && view.items.length);
    if (!groups.length) return '<p class="text-muted">行业字段不足，无法形成行业横截面。</p>';
    return groups.map(view => `<div style="margin:10px 0"><strong>${escapeHtml(view.view)}</strong>
<div style="overflow-x:auto"><table><thead><tr><th>行业</th><th>样本</th><th>上涨占比</th><th>平均涨跌</th><th>成交额</th></tr></thead><tbody>
${view.items.slice(0, 5).map((item: any) => `<tr><td>${escapeHtml(item.industry)}</td><td>${escapeHtml(item.universe)}</td><td>${escapeHtml(item.breadth_pct)}%</td><td class="${Number(item.mean_change_pct) >= 0 ? 'up' : 'down'}">${escapeHtml(item.mean_change_pct)}%</td><td>${escapeHtml((Number(item.amount) / 1e8).toFixed(1))} 亿</td></tr>`).join('')}
</tbody></table></div></div>`).join('');
}

function renderNarrative(narrative: any): string {
    if (!narrative) return '';
    const facts = Array.isArray(narrative.facts) ? narrative.facts : [];
    const interpretations = Array.isArray(narrative.interpretations) ? narrative.interpretations : [];
    const nextChecks = Array.isArray(narrative.next_checks) ? narrative.next_checks : [];
    const evidence = Array.isArray(narrative.evidence) ? narrative.evidence : [];
    const quality = narrative.quality || {};
    return `<div class="card" style="margin:0 24px 16px"><h3>先看结论，再看数字</h3>
<p class="text-sm" style="font-size:14px;line-height:1.8">${escapeHtml(narrative.headline || '暂无结论')}</p>
<div class="grid2"><div><h4>数据事实</h4><ul class="text-sm">${facts.map((fact: unknown) => `<li style="margin:6px 0">${escapeHtml(fact)}</li>`).join('')}</ul></div>
<div><h4>复盘推断（非事实）</h4><ul class="text-sm">${interpretations.map((item: unknown) => `<li style="margin:6px 0">${escapeHtml(item)}</li>`).join('')}</ul></div></div>
<h4>下一交易日待验证</h4><ul class="text-sm">${nextChecks.map((item: unknown) => `<li style="margin:6px 0">${escapeHtml(item)}</li>`).join('')}</ul>
<p class="text-sm text-muted">质量边界：核心字段空值 ${escapeHtml(quality.null_core_rows)} 行；极端涨跌 ${escapeHtml(quality.extreme_change_rows)} 行；行业覆盖 ${escapeHtml(quality.industry_coverage_pct)}%。</p></div>
<div class="card" style="margin:0 24px 16px"><h3>证据股票（已排除极端涨跌）</h3>
${evidence.length ? `<table><thead><tr><th>标的</th><th>行业</th><th>方向</th><th>涨跌幅</th><th>成交额</th><th>换手率</th></tr></thead><tbody>${evidence.map((item: any) => `<tr><td>${escapeHtml(item.symbol)} ${escapeHtml(item.name)}</td><td>${escapeHtml(item.industry)}</td><td>${escapeHtml(item.side)}</td><td class="${Number(item.change_pct) >= 0 ? 'up' : 'down'}">${escapeHtml(item.change_pct)}%</td><td>${escapeHtml((Number(item.amount) / 1e8).toFixed(1))} 亿</td><td>${escapeHtml(item.turnover)}%</td></tr>`).join('')}</tbody></table>` : '<p class="text-muted">暂无可核验股票证据。</p>'}</div>
<div class="card" style="margin:0 24px 16px"><h3>行业主线与弱项</h3>${renderIndustryViews(Array.isArray(narrative.industry_views) ? narrative.industry_views : [])}</div>`;
}

export function buildReviewLabPage(data: any): string {
    const latest = data.latest || null;
    const runs: string[] = Array.isArray(data.runs) ? data.runs : [];
    const trades = Array.isArray(latest?.trades) ? latest.trades : [];
    const rejected: any[] = Array.isArray(latest?.rejected) ? latest.rejected : [];
    const learning = Array.isArray(latest?.learning) ? latest.learning : [];
    const projectReviews: any[] = Array.isArray(latest?.project_reviews) ? latest.project_reviews : [];
    const latestBlock = latest ? `
<div class="grid4" style="padding:16px 24px 0">
<div class="card"><h3>复盘日期</h3><div class="metric-value" style="font-size:22px">${escapeHtml(latest.date)}</div></div>
<div class="card"><h3>模拟净结果</h3><div class="metric-value ${Number(latest.net_pnl) >= 0 ? 'up' : 'down'}" style="font-size:22px">${escapeHtml(latest.net_pnl)} 元</div></div>
<div class="card"><h3>模拟成交</h3><div class="metric-value" style="font-size:22px">${trades.length} 笔</div></div>
<div class="card"><h3>运行标识</h3><div class="text-sm" style="overflow-wrap:anywhere">${escapeHtml(latest.run_id || data.selectedRunId || '--')}</div></div>
</div>
<div class="card" style="margin:16px 24px"><h3>本次闭环</h3>
<p class="text-sm">使用历史数据先决策、下一交易日模拟买入、再下一交易日模拟卖出；周五收盘没有倒推买点。</p>
<p class="text-sm text-muted">数据指纹：${escapeHtml(latest.input_sha256)} · 来源：${escapeHtml(latest.source)}</p>
<p class="text-sm text-muted">执行：${escapeHtml(latest.execution)} · 费用：${escapeHtml(latest.fee_assumptions)}</p>
${latest.source_data ? `<p class="text-sm text-muted">数据快照：${escapeHtml(latest.source_data.target_rows)} 行 · 三日覆盖：${escapeHtml(JSON.stringify(latest.source_data.rows_by_date || {}))}</p>` : ''}</div>
${renderNarrative(latest?.narrative)}
<div class="card" style="margin:0 24px 16px"><h3>七种方法复盘</h3>
<p class="text-sm text-muted">同一份周五日线快照按你提供的七个项目方向分别观察；这是本地方法映射，不是上游仓库代码实际运行。</p>
${projectReviews.length ? projectReviews.map(renderProjectReview).join('') : '<p class="text-muted">这条历史结果尚未包含七项目分析，请刷新生成最新复盘。</p>'}</div>
<div class="card" style="margin:0 24px 16px"><h3>模拟交易明细</h3>
${trades.length ? `<table><thead><tr><th>标的</th><th>买入日</th><th>卖出日</th><th>数量</th><th>买价</th><th>卖价</th><th>净结果</th></tr></thead><tbody>${trades.map(renderTrade).join('')}</tbody></table>` : '<p class="text-muted">没有符合条件的模拟成交。</p>'}
${rejected.length ? `<p class="text-sm text-muted" style="margin-top:12px">未入场：${rejected.map(item => `${escapeHtml(item.symbol)}（${escapeHtml(item.reason)}）`).join('、')}</p>` : ''}</div>
<div class="card" style="margin:0 24px 16px"><h3>测试学习总结</h3>
${learning.length ? `<ul>${learning.map((item: string) => `<li style="margin:6px 0">${escapeHtml(item)}</li>`).join('')}</ul>` : '<p class="text-muted">暂无独立学习记录。</p>'}</div>`
        : `<div class="empty-state"><div class="icon">🧪</div><h2>暂无最新测试复盘</h2><p>没有生成结果，不会调用主流程补采或虚构结论。</p></div>`;
    const history = runs.length ? runs.map(run => `<tr><td>${escapeHtml(run)}</td><td><button class="btn btn-sm" onclick="openReviewHistory('${escapeHtml(run)}')">查看</button></td></tr>`).join('')
        : '<tr><td colspan="2" class="text-muted">暂无历史记录</td></tr>';
    const learningGuide = `<div class="card" style="margin:0 24px 16px"><h3>项目学习方向与评价</h3>
<p class="text-sm text-muted">以下是方法借鉴清单，不是这些仓库实际运行后的收益结论。</p>
<div style="overflow-x:auto"><table><thead><tr><th>项目</th><th>适合学习什么</th><th>评价与边界</th></tr></thead><tbody>
${REVIEW_LEARNING_GUIDE.map(item => `<tr><td style="min-width:190px">${escapeHtml(item.project)}</td><td>${escapeHtml(item.learn)}</td><td>${escapeHtml(item.evaluation)}</td></tr>`).join('')}
</tbody></table></div></div>`;
    const content = `<div style="padding:22px 24px 8px"><div class="flex-between" style="align-items:flex-start;gap:16px;flex-wrap:wrap">
<div><h1 style="font-size:20px;color:#A78BFA;margin-bottom:4px">测试复盘 · 最新结果</h1>
<div style="font-size:12px;color:#8b949e">独立只读模块 · 仅供参考 · 不参与主系统选股、交易或学习</div></div>
<span style="font-size:11px;color:#22C55E;border:1px solid #14532D;background:#052E16;padding:4px 8px;border-radius:999px">✓ Reference Only</span></div></div>
<div style="padding:0 24px 8px"><button class="btn btn-primary" onclick="openReviewLatest()">显示最新</button><button class="btn" style="margin-left:8px" onclick="refreshReviewLab()">刷新</button></div>
${latestBlock}${learningGuide}<div class="card" style="margin:0 24px 24px"><h3>历史记录</h3><p class="text-sm text-muted">历史运行只读保存；不会覆盖最新结果，也不会回写生产数据库。</p>
<table><thead><tr><th>运行 ID</th><th>操作</th></tr></thead><tbody>${history}</tbody></table></div>`;
    const extraScript = `function openReviewHistory(runId){vscode.postMessage({command:'reviewLabHistory',runId});}
function openReviewLatest(){vscode.postMessage({command:'navigate',page:'review_lab'});}
function refreshReviewLab(){vscode.postMessage({command:'refreshPage'});}`;
    return pageShell('review_lab', '测试复盘 · 最新结果', content, extraScript);
}
