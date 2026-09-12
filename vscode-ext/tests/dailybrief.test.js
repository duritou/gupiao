const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return {};
    return originalLoad.call(this, request, parent, isMain);
};

const { buildDailyBriefPage, getDailyBriefState } = require('../out/pages/dailybrief');
const { cachePageResult, isPageDataError } = require('../out/page-cache');

test('request failure is visible and never rendered as an endless loading state', () => {
    const data = {
        pageError: '每日简报请求失败：HTTP 503',
        pageErrorKind: 'request',
    };

    assert.equal(getDailyBriefState(data), 'request');
    const html = buildDailyBriefPage(data);

    assert.match(html, /简报请求失败/);
    assert.match(html, /HTTP 503/);
    assert.doesNotMatch(html, /数据加载中|加载中\.\.\.|市场数据收集中，请稍后刷新/);
});

test('a failed refresh keeps the last successful brief and marks its timestamp', () => {
    const data = {
        brief: {
            date: '2026-09-09',
            generated_at: '2026-09-09T08:00:00',
            one_liner: '最近一次成功简报',
            data_status: { available: true, degraded: true, components: {} },
        },
        pageError: '每日简报请求超时：after 10000ms',
        pageErrorKind: 'timeout',
        pageState: 'stale',
        lastSuccessfulAt: '2026-09-09T08:00:00.000Z',
    };

    const html = buildDailyBriefPage(data);

    assert.match(html, /最近一次成功简报/);
    assert.match(html, /刷新失败，降级展示最近成功数据/);
    assert.match(html, /2026-09-09T08:00:00\.000Z/);
    assert.match(html, /每日简报请求超时/);
});

test('collecting and empty responses have distinct labels', () => {
    const collecting = buildDailyBriefPage({
        brief: { data_status: { state: 'collecting', available: false } },
    });
    const empty = buildDailyBriefPage({
        brief: { data_status: { state: 'empty', available: false } },
    });

    assert.equal(getDailyBriefState({ brief: { data_status: { state: 'collecting' } } }), 'collecting');
    assert.equal(getDailyBriefState({ brief: { data_status: { state: 'empty' } } }), 'empty');
    assert.match(collecting, /数据正在收集/);
    assert.match(empty, /暂无可用数据/);
    assert.notEqual(collecting, empty);
});

test('failed page data is not promoted to a successful cache entry', () => {
    const success = cachePageResult(undefined, { brief: { one_liner: 'old' } }, 1000);
    const failed = cachePageResult(
        success,
        { pageError: '请求失败', pageErrorKind: 'request' },
        2000,
        5000,
    );

    assert.equal(isPageDataError(failed.data), true);
    assert.equal(failed.fetchedAt, 1000);
    assert.equal(failed.lastSuccessfulAt, 1000);
    assert.equal(failed.data.brief.one_liner, 'old');
    assert.equal(failed.data.pageState, 'stale');
    assert.equal(failed.retryAfter, 7000);

    const recovered = cachePageResult(failed, { brief: { one_liner: 'new' } }, 3000);
    assert.equal(isPageDataError(recovered.data), false);
    assert.equal(recovered.data.brief.one_liner, 'new');
    assert.equal(recovered.lastSuccessfulAt, 3000);
});

test('first failure has no successful timestamp and is retry-cooldown bounded', () => {
    const failed = cachePageResult(undefined, { pageError: 'timeout', pageErrorKind: 'timeout' }, 1000, 5000);

    assert.equal(failed.fetchedAt, 0);
    assert.equal(failed.lastSuccessfulAt, 0);
    assert.equal(failed.data.pageState, 'error');
    assert.equal(failed.retryAfter, 6000);
});
