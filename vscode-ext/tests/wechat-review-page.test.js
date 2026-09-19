const assert = require('node:assert/strict');
const Module = require('node:module');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { buildReviewLabPage } = require('../out/pages/review_lab');

const html = buildReviewLabPage({
  wechat: {
    accounts: [{
      source_name: '示例公众号',
      latest: { title: '盘后复盘', url: 'https://example.com', published_at: '2026-09-13T18:00:00', summary: '总结' },
      history: [],
      methodology: { status: 'completed', summary_markdown: '方法论摘要', principles: ['先看事实'], checklist: ['检查风险'] },
    }],
  },
});

assert.match(html, /公众号复盘 · 方法论/);
assert.match(html, /刷新并学习/);
assert.match(html, /盘后复盘/);
assert.doesNotMatch(html, /模拟净结果|七种方法复盘|测试复盘 · 最新结果|本次闭环/);
