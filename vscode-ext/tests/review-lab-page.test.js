const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return {};
    return originalLoad.call(this, request, parent, isMain);
};
const { buildReviewLabPage } = require('../out/pages/review_lab');
Module._load = originalLoad;

test('review lab renders latest result directly and keeps history in its own section', () => {
    const html = buildReviewLabPage({
        latest: { date: '2026-09-11', run_id: 'friday-' + 'a'.repeat(32), net_pnl: 54.63,
            trades: [{ symbol: '600036.SH', buy_date: '2026-09-10', sell_date: '2026-09-11',
                quantity: 100, entry_price: 41, exit_price: 42, net_pnl: 54.63 }],
            rejected: [], learning: ['仅供测试'], input_sha256: 'fixture', source: 'local',
            execution: 'assumed', fee_assumptions: 'fixture' },
        runs: ['friday-' + 'a'.repeat(32), 'friday-' + 'b'.repeat(32)],
    });
    assert.match(html, /测试复盘 · 最新结果/);
    assert.match(html, /54\.63 元/);
    assert.match(html, /模拟交易明细/);
    assert.match(html, /历史记录/);
    assert.match(html, /openReviewHistory/);
    assert.match(html, /function openReviewLatest/);
});

test('review lab has a clear empty latest state without fabricated values', () => {
    const html = buildReviewLabPage({ latest: null, runs: [] });
    assert.match(html, /暂无最新测试复盘/);
    assert.doesNotMatch(html, /54\.63/);
    assert.match(html, /没有生成结果/);
});

test('review lab renders seven project-specific observations and escapes text', () => {
    const reviews = Array.from({ length: 7 }, (_, index) => ({
        project: `project-${index}<x>`, status: index === 6 ? 'partial' : 'completed',
        title: `观察 ${index}`, findings: [`发现 ${index}<script>`],
        metrics: { universe: 10 + index }, limitations: ['仅供参考'],
    }));
    const html = buildReviewLabPage({
        latest: { date: '2026-09-11', run_id: 'friday-' + 'c'.repeat(32), net_pnl: 0,
            trades: [], rejected: [], learning: [], input_sha256: 'fixture', source: 'local',
            execution: 'assumed', fee_assumptions: 'fixture', project_reviews: reviews,
            source_data: { target_rows: 3, rows_by_date: { '2026-09-11': 3 } } },
        runs: [],
    });
    assert.match(html, /七种方法复盘/);
    assert.equal((html.match(/观察 [0-6]/g) || []).length, 7);
    assert.match(html, /发现 0&lt;script&gt;/);
    assert.doesNotMatch(html, /发现 0<script>/);
});
