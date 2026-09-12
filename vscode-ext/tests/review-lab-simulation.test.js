const assert = require('node:assert/strict');
const test = require('node:test');
const { simulateReview } = require('../out/review-lab/simulation');
const { parseArtifact, renderReview } = require('../out/review-lab/model');
const date = '2026-09-12';

test('synthetic run produces seven validated, conspicuously labelled observations', () => {
    const results = simulateReview(date, () => 'idle');
    assert.equal(results.length, 7);
    for (const entry of results) {
        assert.equal(parseArtifact(JSON.stringify(entry), date, entry.project).status, 'completed');
        assert.equal(entry.method, 'synthetic_simulation');
    }
    assert.match(results[0].summary, /10.00%/);
    assert.match(results[2].summary, /上涨 1、下跌 1、平盘 1/);
    assert.match(results[3].summary, /1.67%/);
    const html = renderReview(date, new Map(results.map(entry => [entry.project, entry])));
    assert.equal((html.match(/【合成数据模拟 · 非真实复盘】/g) || []).length, 7);
});

test('busy, unknown, and failed checks all refuse calculations', () => {
    for (const gate of [() => 'busy', () => 'unknown', () => { throw Error('unavailable'); }]) {
        assert.ok(simulateReview(date, gate).every(entry => entry.status === 'skipped_busy'));
    }
});

test('mid-run cancellation sticks even when subsequent check becomes idle', () => {
    let index = 0;
    const result = simulateReview(date, () => ++index === 3 ? 'busy' : 'idle');
    assert.deepEqual(result.map(entry => entry.status), [
        'completed', 'completed', 'skipped_busy', 'skipped_busy',
        'skipped_busy', 'skipped_busy', 'skipped_busy',
    ]);
});

test('empty input stays empty and invalid input is refused', () => {
    assert.ok(simulateReview(date, () => 'idle', []).every(entry => entry.status === 'no_data'));
    assert.throws(() => simulateReview('bad', () => 'idle'));
    assert.throws(() => simulateReview(date, () => 'idle', [{ previous: 0, close: 1 }]));
    assert.throws(() => simulateReview(date, () => 'idle', [{ previous: 1, close: NaN }]));
});
