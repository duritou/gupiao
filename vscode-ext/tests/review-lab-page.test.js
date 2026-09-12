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
            trades: [{ symbol: '600036.SH', name: '招商银行', buy_date: '2026-09-10', sell_date: '2026-09-11',
                quantity: 100, entry_price: 41, exit_price: 42, net_pnl: 54.63 }],
            rejected: [], learning: ['仅供测试'], input_sha256: 'fixture', source: 'local',
            execution: 'assumed', fee_assumptions: 'fixture' },
        runs: ['friday-' + 'a'.repeat(32), 'friday-' + 'b'.repeat(32)],
    });
    assert.match(html, /测试复盘 · 最新结果/);
    assert.match(html, /54\.63 元/);
    assert.match(html, /模拟交易明细/);
    assert.match(html, /招商银行/);
    assert.match(html, /600036\.SH/);
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

test('review lab leads with narrative facts, evidence, and next-session checks', () => {
    const html = buildReviewLabPage({
        latest: { date: '2026-09-11', run_id: 'friday-' + 'd'.repeat(32), net_pnl: -12.3,
            trades: [], rejected: [], learning: [], input_sha256: 'fixture', source: 'local',
            execution: 'assumed', fee_assumptions: 'fixture', project_reviews: [],
            narrative: {
                headline: '市场宽度偏弱', facts: ['643 只上涨（事实）'],
                interpretations: ['推断：当天更接近普跌环境'],
                next_checks: ['下一交易日待验证：上涨家数是否回升'],
                evidence: [{ symbol: '000001.SZ', name: '平安银行', industry: '银行',
                    side: '强势样本', change_pct: 2.1, amount: 100000000, turnover: 1.2 }],
                industry_views: [{ view: '平均涨跌靠前', items: [{ industry: '银行', universe: 20,
                    breadth_pct: 60, mean_change_pct: 1.1, amount: 1000000000 }] }],
                quality: { null_core_rows: 0, extreme_change_rows: 1, industry_coverage_pct: 93.7 },
            },
        }, runs: [],
    });
    assert.match(html, /先看结论，再看数字/);
    assert.match(html, /市场宽度偏弱/);
    assert.match(html, /下一交易日待验证/);
    assert.match(html, /证据股票/);
    assert.match(html, /行业主线与弱项/);
});
