"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.REVIEW_PROJECTS = void 0;
exports.validDate = validDate;
exports.parseArtifact = parseArtifact;
exports.escapeHtml = escapeHtml;
exports.renderReview = renderReview;
/** Reference-only artifacts. No backend, provider, broker or learning-store imports. */
exports.REVIEW_PROJECTS = [
    'guoyaohua/limit-up-sniper',
    'Zeeechenn/MingCang',
    'NNNightglow/replay',
    'dfqddd/A-Stock-Analysis',
    'MisakaMikoto128/china-astock-quant',
    'fkchaos/a-share-quant-sim',
    'yangchas/AShare-Runtime-Engine',
];
function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value))
        return false;
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
function parseArtifact(raw, date, project) {
    const value = JSON.parse(raw);
    if (!value || value.schema_version !== 1 || value.reference_only !== true
        || !validDate(date) || value.date !== date || value.project !== project
        || !exports.REVIEW_PROJECTS.includes(project)
        || !['completed', 'partial', 'skipped_busy', 'no_data', 'error'].includes(value.status)
        || !['local_observation', 'upstream_replay', 'isolated_ai', 'synthetic_simulation'].includes(value.method)) {
        throw new Error('复盘结果身份或版本不匹配');
    }
    for (const key of ['source_revision', 'input_as_of', 'summary', 'limitations']) {
        if (typeof value[key] !== 'string' || !value[key].trim() || value[key].length > 16000) {
            throw new Error('复盘结果缺少来源、输入日期或局限说明');
        }
    }
    return value;
}
function escapeHtml(value) {
    return value.replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
}
function renderReview(date, entries) {
    const cards = exports.REVIEW_PROJECTS.map(project => {
        const entry = entries.get(project);
        const detail = typeof entry === 'string' ? `<p>${escapeHtml(entry)}</p>` : entry
            ? `<p>${entry.method === 'synthetic_simulation' ? '【合成数据模拟 · 非真实复盘】' : ''}</p>
               <p>状态：${escapeHtml(entry.status)} · 生成方式：${escapeHtml(entry.method)}</p>
               <p>来源版本：${escapeHtml(entry.source_revision)}<br>输入截止：${escapeHtml(entry.input_as_of)}</p>
               <pre>${escapeHtml(entry.summary)}</pre><p>局限：${escapeHtml(entry.limitations)}</p>`
            : '<p>暂无当天复盘结果；不代表项目已运行或没有交易机会。</p>';
        return `<section><h2>${escapeHtml(project)}</h2>${detail}</section>`;
    }).join('');
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
    <style>body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);
    background:var(--vscode-editor-background);padding:24px;max-width:1100px}
    section{border-top:1px solid var(--vscode-panel-border);padding:16px 0}
    pre{white-space:pre-wrap;overflow-wrap:anywhere}p{line-height:1.7}</style></head><body>
    <h1>测试复盘 · ${escapeHtml(date)}</h1>
    <p>独立只读查看 · 仅供参考 · 不参与选股、交易或主系统学习。</p>
    <p>自动运行尚未启用。计划北京时间 19:00 后、确认主系统空闲才运行；忙碌或状态未知时跳过。</p>
    <p>以下是待接入的开源方法，不是已验证盈利的交易员。无结果时不会生成模拟结论。
    重新执行“测试复盘”命令可选择日期并刷新。</p>${cards}</body></html>`;
}
//# sourceMappingURL=model.js.map