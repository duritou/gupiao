const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');
const vm = require('node:vm');

class TreeItem {
    constructor(label, collapsibleState) {
        this.label = label;
        this.collapsibleState = collapsibleState;
    }
}

class ThemeIcon {
    constructor(id) {
        this.id = id;
    }
}

const vscodeStub = {
    TreeItem,
    ThemeIcon,
    TreeItemCollapsibleState: { None: 0 },
};

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return vscodeStub;
    return originalLoad.call(this, request, parent, isMain);
};

const { pageShell } = require('../out/webview/layout');
const { TerminalNavProvider } = require('../out/sidebar/providers');

test('page shell isolates global navigation from page-specific scripts', () => {
    const html = pageShell('timeline', 'Timeline', '<main>content</main>', 'function pageSpecific(){return true;}');
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);

    assert.equal(scripts.length, 2);
    assert.match(scripts[0], /function navigate\(page\)/);
    assert.doesNotMatch(scripts[0], /pageSpecific/);
    assert.match(scripts[1], /pageSpecific/);
    assert.doesNotThrow(() => new vm.Script(scripts[0]));
    assert.doesNotThrow(() => new vm.Script(scripts[1]));
    assert.match(html, /<button type="button" class="nav-item active" onclick="navigate\('timeline'\)"/);
});

test('sidebar has no blank rows and every item has a valid icon id', () => {
    const items = new TerminalNavProvider().getChildren();

    assert.ok(items.length > 0);
    assert.equal(items.some(item => !String(item.label || '').trim()), false);
    for (const item of items) {
        assert.ok(item.iconPath instanceof ThemeIcon, `${item.label} is missing a ThemeIcon`);
        assert.equal(item.iconPath.id, item.iconPath.id.trim(), `${item.label} has whitespace in its icon id`);
        assert.notEqual(item.iconPath.id, 'timeline', 'Timeline must use a supported codicon id');
    }
});

