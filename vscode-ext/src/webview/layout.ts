/** Webview panel management — create, show, navigate. */

import * as vscode from 'vscode';
import { PAGE_TITLES, NAV_ITEMS, TERMINAL_CSS } from '../constants';

let currentPanel: vscode.WebviewPanel | null = null;
let currentMessageDisposable: vscode.Disposable | null = null;

export function getCurrentPanel(): vscode.WebviewPanel | null {
    return currentPanel;
}

export function createOrShowPanel(
    title: string,
    html: string,
    onMessage: (msg: any) => void,
): vscode.WebviewPanel {
    if (currentPanel) {
        currentPanel.title = title;
        currentPanel.reveal(vscode.ViewColumn.One);
    } else {
        currentPanel = vscode.window.createWebviewPanel(
            'quantaiTerminal', title,
            vscode.ViewColumn.One,
            { enableScripts: true, retainContextWhenHidden: true },
        );
        currentPanel.onDidDispose(() => {
            currentPanel = null;
            currentMessageDisposable?.dispose();
            currentMessageDisposable = null;
        });
    }

    currentPanel.webview.html = html;
    currentMessageDisposable?.dispose();
    currentMessageDisposable = currentPanel.webview.onDidReceiveMessage(onMessage);
    return currentPanel;
}

export function getPageTitle(page: string): string {
    return PAGE_TITLES[page] || 'Adaptive Investment Intelligence';
}

export function buildNav(active: string): string {
    return `<div class="nav">${NAV_ITEMS.map(i =>
        `<span class="nav-item${i.id === active ? ' active' : ''}" onclick="navigate('${i.id}')">${i.label}</span>`
    ).join('')}</div>`;
}

export function pageShell(active: string, title: string, content: string, extraScript: string = ''): string {
    const nav = buildNav(active);
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">${TERMINAL_CSS}</head><body>
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
