"use strict";
/** Webview panel management — create, show, navigate. */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.getCurrentPanel = getCurrentPanel;
exports.createOrShowPanel = createOrShowPanel;
exports.getPageTitle = getPageTitle;
exports.buildNav = buildNav;
exports.pageShell = pageShell;
const vscode = __importStar(require("vscode"));
const constants_1 = require("../constants");
let currentPanel = null;
function getCurrentPanel() {
    return currentPanel;
}
function createOrShowPanel(title, html, onMessage) {
    if (currentPanel) {
        currentPanel.dispose();
    }
    currentPanel = vscode.window.createWebviewPanel('quantaiTerminal', title, vscode.ViewColumn.One, { enableScripts: true, retainContextWhenHidden: true });
    currentPanel.webview.html = html;
    currentPanel.webview.onDidReceiveMessage(onMessage);
    currentPanel.onDidDispose(() => { currentPanel = null; });
    return currentPanel;
}
function getPageTitle(page) {
    return constants_1.PAGE_TITLES[page] || 'AI Research Terminal';
}
function buildNav(active) {
    return `<div class="nav">${constants_1.NAV_ITEMS.map(i => `<span class="nav-item${i.id === active ? ' active' : ''}" onclick="navigate('${i.id}')">${i.label}</span>`).join('')}</div>`;
}
function pageShell(active, title, content, extraScript = '') {
    const nav = buildNav(active);
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">${constants_1.TERMINAL_CSS}</head><body>
${nav}
<div class="header"><h1>${title}</h1><span class="date">${new Date().toLocaleDateString('zh-CN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</span></div>
${content}
<script>
const vscode = acquireVsCodeApi();
function navigate(page) { vscode.postMessage({command:'navigate',page}); }
function analyzeStock(code) { vscode.postMessage({command:'analyze',code}); }
function addToWatchlist() { vscode.postMessage({command:'addWatch'}); }
function compareStocks() { vscode.postMessage({command:'compare'}); }
function showTimeline() { vscode.postMessage({command:'timeline'}); }
${extraScript}
</script></body></html>`;
}
//# sourceMappingURL=layout.js.map