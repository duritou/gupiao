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

test('learning guide keeps all seven projects separate with explicit boundaries', () => {
    const html = buildReviewLabPage({ latest: null, runs: [] });
    assert.equal((html.match(/项目学习方向与评价/g) || []).length, 1);
    for (const project of ['guoyaohua/limit-up-sniper', 'Zeeechenn/MingCang',
        'NNNightglow/replay', 'dfqddd/A-Stock-Analysis',
        'MisakaMikoto128/china-astock-quant', 'fkchaos/a-share-quant-sim',
        'yangchas/AShare-Runtime-Engine']) assert.ok(html.includes(project));
    assert.match(html, /不能证明盈利能力/);
    assert.match(html, /stars 只代表热度/);
    assert.match(html, /不是这些仓库实际运行后的收益结论/);
});
