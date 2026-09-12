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
