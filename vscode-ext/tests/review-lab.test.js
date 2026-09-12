const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { REVIEW_PROJECTS, parseArtifact, validDate, renderReview } = require('../out/review-lab/model');

const sample = () => ({
    schema_version: 1, reference_only: true, date: '2026-09-11',
    project: REVIEW_PROJECTS[0], status: 'partial', method: 'local_observation',
    source_revision: 'test-fixture-only', input_as_of: '2026-09-11T15:00:00+08:00',
    summary: '<script>alert(1)</script>', limitations: '仅测试，无行情数据',
});

test('review dates reject path traversal and impossible calendar days', () => {
    for (const value of ['../../secret', '2026-02-29', '2026-13-01', '2026-9-1']) {
        assert.equal(validDate(value), false);
    }
    assert.equal(validDate('2024-02-29'), true);
});

test('artifact rejects wrong identity and missing provenance', () => {
    const value = sample();
    assert.equal(parseArtifact(JSON.stringify(value), value.date, value.project).status, 'partial');
    for (const patch of [{ reference_only: false }, { date: '2026-09-10' },
        { project: '../other' }, { schema_version: 2 }, { method: 'unknown' },
        { source_revision: '' }, { limitations: '' }, { summary: 'x'.repeat(16001) }]) {
        assert.throws(() => parseArtifact(JSON.stringify({ ...value, ...patch }), value.date, value.project));
    }
});

test('all projects remain separate and missing results are not fabricated', () => {
    const html = renderReview('2026-09-11', new Map());
    assert.equal((html.match(/<section>/g) || []).length, 7);
    for (const project of REVIEW_PROJECTS) assert.ok(html.includes(project));
    assert.match(html, /自动运行尚未启用/);
    assert.match(html, /暂无当天复盘结果/);
});

test('result content cannot become executable markup', () => {
    const value = sample();
    const html = renderReview(value.date, new Map([[value.project, value]]));
    assert.doesNotMatch(html, /<script>/);
    assert.match(html, /&lt;script&gt;/);
    assert.match(html, /default-src 'none'/);
});

test('viewer has no backend or process dependencies and disables scripts', () => {
    const source = fs.readFileSync(path.join(__dirname, '../src/review-lab/view.ts'), 'utf8');
    assert.doesNotMatch(source, /httpPost|child_process|setInterval|writeFile|sqlite/);
    assert.match(source, /httpGet\(`\/review-lab\/runs\//);
    assert.match(source, /enableScripts: false/);
    assert.match(source, /globalStorageUri/);
});
