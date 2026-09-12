/** Reference-only artifacts. No backend, provider, broker or learning-store imports. */
export const REVIEW_PROJECTS = [
    'guoyaohua/limit-up-sniper',
    'Zeeechenn/MingCang',
    'NNNightglow/replay',
    'dfqddd/A-Stock-Analysis',
    'MisakaMikoto128/china-astock-quant',
    'fkchaos/a-share-quant-sim',
    'yangchas/AShare-Runtime-Engine',
] as const;

export const REVIEW_LEARNING_GUIDE: ReadonlyArray<{
    project: typeof REVIEW_PROJECTS[number];
    learn: string;
    evaluation: string;
}> = [
    { project: 'guoyaohua/limit-up-sniper', learn: '首板、涨停基因、盘中确认、盘后复盘、错失机会分析',
        evaluation: '最适合学习短线复盘框架；作者说明迁移数据约 12 个交易日，不能证明盈利能力。' },
    { project: 'Zeeechenn/MingCang', learn: '研究→信号→持仓→复盘→记忆的闭环',
        evaluation: '适合借鉴 AI 学习机制；强调结果验证、人工确认和影子评估，不直接把观点变成交易信号。' },
    { project: 'NNNightglow/replay', learn: '指数、板块、个股、情绪、历史回放',
        evaluation: '适合学习盘后复盘界面和历史场景重建；stars 只代表热度，不代表收益。' },
    { project: 'dfqddd/A-Stock-Analysis', learn: '大盘、板块、资金流、情绪、每日自动复盘',
        evaluation: '适合参考数据采集和报告模板，策略有效性需要自行验证。' },
    { project: 'MisakaMikoto128/china-astock-quant', learn: 'T+1、100 股整手、手续费、滑点、模拟盘、walk-forward',
        evaluation: '适合增强交易执行和回测真实性；仍需防范未来函数和生存者偏差。' },
    { project: 'fkchaos/a-share-quant-sim', learn: '回测、walk-forward、纸面交易共用同一策略代码',
        evaluation: '适合借鉴研究和模拟使用同一套逻辑，减少两套实现造成的偏差。' },
    { project: 'yangchas/AShare-Runtime-Engine', learn: '盘前、竞价、开盘、盘中、盘后、夜间复盘的阶段化运行',
        evaluation: '更偏运行时架构，不是收益策略。' },
];

export interface ReviewArtifact {
    schema_version: 1;
    reference_only: true;
    date: string;
    project: string;
    status: 'completed' | 'partial' | 'skipped_busy' | 'no_data' | 'error';
    method: 'local_observation' | 'upstream_replay' | 'isolated_ai' | 'synthetic_simulation';
    source_revision: string;
    input_as_of: string;
    summary: string;
    limitations: string;
}

export function validDate(value: string): boolean {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function parseArtifact(raw: string, date: string, project: string): ReviewArtifact {
    const value = JSON.parse(raw);
    if (!value || value.schema_version !== 1 || value.reference_only !== true
        || !validDate(date) || value.date !== date || value.project !== project
        || !(REVIEW_PROJECTS as readonly string[]).includes(project)
        || !['completed', 'partial', 'skipped_busy', 'no_data', 'error'].includes(value.status)
        || !['local_observation', 'upstream_replay', 'isolated_ai', 'synthetic_simulation'].includes(value.method)) {
        throw new Error('复盘结果身份或版本不匹配');
    }
    for (const key of ['source_revision', 'input_as_of', 'summary', 'limitations']) {
        if (typeof value[key] !== 'string' || !value[key].trim() || value[key].length > 16000) {
            throw new Error('复盘结果缺少来源、输入日期或局限说明');
        }
    }
    return value as ReviewArtifact;
}

export function escapeHtml(value: string): string {
    return value.replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]!));
}

export function renderReview(date: string, entries: ReadonlyMap<string, ReviewArtifact | string>): string {
    const cards = REVIEW_PROJECTS.map(project => {
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
