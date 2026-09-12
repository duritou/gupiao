const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

let selectedDate = '2026-09-11';
let created = [];
const stub = {
    window: {
        showInputBox: async () => selectedDate,
        showQuickPick: async values => values[0],
        createWebviewPanel: (type, title, column, options) => {
            const panel = { type, title, column, options, webview: { html: '' }, dispose() {} };
            created.push(panel);
            return panel;
        },
    },
    ViewColumn: { Beside: 2 },
    workspace: { workspaceFolders: [] },
};
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return stub;
    return originalLoad.call(this, request, parent, isMain);
};
const { showReviewLab, showHistoricalReview } = require('../out/review-lab/view');
Module._load = originalLoad;

test('viewer reads only selected local results without mutating them', async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'review-lab-test-'));
    try {
        const folder = path.join(root, 'review-lab/results/2026-09-11');
        await fs.mkdir(folder, { recursive: true });
        const file = path.join(folder, 'guoyaohua__limit-up-sniper.json');
        const raw = JSON.stringify({ schema_version: 1, reference_only: true,
            date: '2026-09-11', project: 'guoyaohua/limit-up-sniper', status: 'partial',
            method: 'local_observation', source_revision: 'fixture', input_as_of: 'fixture-date',
            summary: '唯一测试结果', limitations: '没有真实行情' });
        await fs.writeFile(file, raw);
        await fs.writeFile(path.join(folder, 'Zeeechenn__MingCang.json'), 'bad-json');
        await fs.writeFile(path.join(folder, 'NNNightglow__replay.json'), 'x'.repeat(65537));
        const context = { globalStorageUri: { fsPath: root }, subscriptions: [] };
        await showReviewLab(context);
        assert.equal(created.length, 1);
        assert.equal(created[0].options.enableScripts, false);
        assert.deepEqual(created[0].options.localResourceRoots, []);
        assert.match(created[0].webview.html, /唯一测试结果/);
        assert.equal((created[0].webview.html.match(/结果无效或无法读取/g) || []).length, 2);
        assert.equal(await fs.readFile(file, 'utf8'), raw);
        assert.equal((await fs.readdir(folder)).length, 3);
        assert.equal(context.subscriptions.length, 1);
    } finally {
        await fs.rm(root, { recursive: true, force: true });
    }
});

test('cancelled or invalid date opens no panel', async () => {
    created = [];
    for (const date of [undefined, '../../escape', '2026-02-30']) {
        selectedDate = date;
        await showReviewLab({ globalStorageUri: { fsPath: 'unused' }, subscriptions: [] });
    }
    assert.equal(created.length, 0);
});

test('historical viewer uses local workspace result before any API request', async () => {
    created = [];
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'review-lab-local-first-'));
    const runId = 'friday-' + 'b'.repeat(32);
    try {
        await fs.mkdir(path.join(root, 'runtime/adaptive-review-lab', runId), { recursive: true });
        await fs.writeFile(path.join(root, 'runtime/adaptive-review-lab', runId, 'result.json'),
            JSON.stringify({ reference_only: true, schema_version: 1, net_pnl: 54.63 }));
        stub.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
        await showHistoricalReview({ subscriptions: [] });
        assert.equal(created.length, 1);
        assert.match(created[0].webview.html, /54\.63/);
    } finally {
        stub.workspace.workspaceFolders = [];
        await fs.rm(root, { recursive: true, force: true });
    }
});
