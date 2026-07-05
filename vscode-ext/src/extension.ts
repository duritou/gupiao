import * as vscode from 'vscode';
import * as cp from 'child_process';
import { BASE_URL } from './constants';
import { httpGet, httpPost, healthCheck, sleep } from './api/client';
import { createOrShowPanel, getPageTitle, pageShell, buildNav } from './webview/layout';
import { TerminalNavProvider, StatusProvider } from './sidebar/providers';
import { buildDashboardPage } from './pages/dashboard';
import { buildWatchlistPage } from './pages/watchlist';
import { buildResearchPage } from './pages/research';
import { buildMarketMapPage } from './pages/marketmap';
import { buildAlertsPage } from './pages/alerts';
import { buildBacktestPage } from './pages/backtest';
import { buildDailyBriefPage } from './pages/dailybrief';
import { buildComparePage } from './pages/compare';
import { buildTimelinePage } from './pages/timeline';
import { buildPortfolioPage } from './pages/portfolio';

let serverProcess: cp.ChildProcess | null = null;
let statusBar: vscode.StatusBarItem;
let watchlist: string[] = [];
let extensionContext: vscode.ExtensionContext | null = null;

// ============================================================
// ACTIVATION
// ============================================================
export function activate(context: vscode.ExtensionContext) {
    console.log('AI Research Terminal v2.0 activated');
    extensionContext = context;
    watchlist = context.globalState.get('watchlist', ['000001.SZ', '600519.SH', '000858.SZ', '300750.SZ', '002475.SZ']);

    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(pulse) AI Research';
    statusBar.command = 'quantai.terminal';
    statusBar.show();

    context.subscriptions.push(
        vscode.commands.registerCommand('quantai.terminal', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.dashboard', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.watchlist', () => showTerminal('watchlist')),
        vscode.commands.registerCommand('quantai.research', () => showStockResearch()),
        vscode.commands.registerCommand('quantai.marketmap', () => showTerminal('marketmap')),
        vscode.commands.registerCommand('quantai.alerts', () => showTerminal('alerts')),
        vscode.commands.registerCommand('quantai.backtest', () => showTerminal('backtest')),
        vscode.commands.registerCommand('quantai.dailybrief', () => showTerminal('dailybrief')),
        vscode.commands.registerCommand('quantai.compare', () => showTerminal('compare')),
        vscode.commands.registerCommand('quantai.timeline', () => showTerminal('timeline')),
        vscode.commands.registerCommand('quantai.portfolio', () => showTerminal('portfolio')),
        vscode.commands.registerCommand('quantai.startServer', startServer),
        vscode.commands.registerCommand('quantai.stopServer', stopServer),
        vscode.commands.registerCommand('quantai.addWatch', addToWatchlist),
        vscode.commands.registerCommand('quantai.scan', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.analyze', () => showStockResearch()),
        vscode.commands.registerCommand('quantai.knowledge', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.status', async () => {
            const ok = await healthCheck();
            vscode.window.showInformationMessage(ok ? 'AI Research Terminal: 后端运行中' : 'AI Research Terminal: 后端未启动');
        }),
    );

    vscode.window.registerTreeDataProvider('quantai-actions', new TerminalNavProvider());
    vscode.window.registerTreeDataProvider('quantai-status', new StatusProvider());

    checkAndStartServer();
}

export function deactivate() { stopServer(); }

// ============================================================
// SERVER LIFECYCLE
// ============================================================
async function checkAndStartServer() {
    if (await healthCheck()) { statusBar.text = '$(check) AI Research'; return; }
    await startServer();
}

async function startServer() {
    if (serverProcess) return;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!root) return;
    statusBar.text = '$(sync~spin) Starting...';
    serverProcess = cp.spawn('poetry', ['run', 'uvicorn', 'src.api.app:app', '--host', '127.0.0.1', '--port', '8888'], {
        cwd: root, shell: true, stdio: 'pipe',
    });
    for (let i = 0; i < 20; i++) {
        await sleep(1000);
        if (await healthCheck()) { statusBar.text = '$(check) AI Research'; return; }
    }
    statusBar.text = '$(error) AI Research';
}

function stopServer() { if (serverProcess) { serverProcess.kill(); serverProcess = null; } }

// ============================================================
// NAVIGATION & DATA FETCHING
// ============================================================
async function showTerminal(page: string, extraData?: any) {
    const data = await fetchPageData(page, extraData);
    const html = buildPage(page, data);
    createOrShowPanel(getPageTitle(page), html, (msg: any) => handleMessage(msg, page));
}

async function fetchPageData(page: string, extraData?: any): Promise<any> {
    try {
        switch (page) {
            case 'dashboard': {
                const [market, scanner, watchScores] = await Promise.all([
                    httpGet('/market/overview').catch(() => null),
                    httpPost('/scanner/run?pool_size=30&top_n=8').catch(() => null),
                    httpPost('/signals/batch', { codes: watchlist }).catch(() => null),
                ]);
                return { market, scanner, watchScores };
            }
            case 'watchlist': {
                const watchScores = await httpPost('/signals/batch', { codes: watchlist }).catch(() => null);
                return { stocks: watchlist, watchScores };
            }
            case 'marketmap': {
                const sectors = await httpGet('/market/sectors').catch(() => null);
                return { sectors: sectors?.sectors || [] };
            }
            case 'alerts': {
                const alerts = await httpGet('/alerts/recent?limit=50').catch(() => null);
                return { alerts };
            }
            case 'backtest': {
                const backtest = await httpPost('/backtest/run?trend=up&days=120').catch(() => null);
                return { backtest };
            }
            case 'dailybrief': {
                const brief = await httpGet('/dailybrief/latest').catch(() => null);
                return { brief };
            }
            case 'portfolio': {
                const portfolio = await httpGet('/portfolio/overview').catch(() => null);
                return { portfolio };
            }
            case 'compare': return {};
            case 'timeline': {
                const code = extraData?.code || '600519.SH';
                const timeline = await httpGet(`/timeline/${code}?days=30`).catch(() => null);
                return { timeline };
            }
            default: return {};
        }
    } catch { return {}; }
}

function buildPage(page: string, data: any): string {
    switch (page) {
        case 'dashboard': return buildDashboardPage(data);
        case 'watchlist': return buildWatchlistPage(data);
        case 'marketmap': return buildMarketMapPage(data);
        case 'alerts': return buildAlertsPage(data);
        case 'backtest': return buildBacktestPage(data);
        case 'dailybrief': return buildDailyBriefPage(data);
        case 'portfolio': return buildPortfolioPage(data);
        case 'compare': return buildComparePage(data);
        case 'timeline': return buildTimelinePage(data);
        default: return pageShell('dashboard', 'AI Research Terminal', '<div class="empty-state"><div class="icon">🤖</div><h2>AI Research Terminal</h2><p>选择一个页面开始</p></div>');
    }
}

function handleMessage(msg: any, currentPage: string) {
    switch (msg.command) {
        case 'navigate': showTerminal(msg.page); break;
        case 'addWatch': addToWatchlist().then(() => showTerminal('watchlist')); break;
        case 'analyze': showStockResearchDirect(msg.code); break;
        case 'compare': showTerminal('compare'); break;
        case 'timeline': showTerminal('timeline', { code: msg.code }); break;
    }
}

// ============================================================
// STOCK RESEARCH
// ============================================================
async function showStockResearch() {
    const code = await vscode.window.showInputBox({ prompt: '股票代码', value: '000001.SZ' });
    if (!code) return;
    await showStockResearchDirect(code);
}

async function showStockResearchDirect(code: string) {
    const detail = await httpGet(`/detail/${code}?include=all`).catch(() => null);
    const html = buildResearchPage(code, detail);
    createOrShowPanel(`${code} Research`, html, (msg: any) => handleMessage(msg, 'research'));
}

// ============================================================
// WATCHLIST MANAGEMENT
// ============================================================
async function addToWatchlist() {
    const code = await vscode.window.showInputBox({ prompt: '添加自选股', placeHolder: '000001.SZ' });
    if (!code) return;
    if (!watchlist.includes(code)) { watchlist.push(code); }
    if (extensionContext) {
        extensionContext.globalState.update('watchlist', watchlist);
    }
    vscode.window.showInformationMessage(`${code} 已添加到自选`);
}
