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
import { buildJournalPage } from './pages/journal';
import { buildResumePage } from './pages/resume';
import { buildProfilePage } from './pages/profile';
import { buildAIOSPage } from './pages/aios';
import { buildReplayPage } from './pages/replay';
import { buildHealthPage } from './pages/health';

let serverProcess: cp.ChildProcess | null = null;
let statusBar: vscode.StatusBarItem;
let watchlist: string[] = [];
let extensionContext: vscode.ExtensionContext | null = null;

// ============================================================
// ACTIVATION
// ============================================================
export function activate(context: vscode.ExtensionContext) {
    console.log('Adaptive Investment Intelligence Platform activated');
    extensionContext = context;
    watchlist = context.globalState.get('watchlist', ['000001.SZ', '600519.SH', '000858.SZ', '300750.SZ', '002475.SZ']);

    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(pulse) AIIP';
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
        vscode.commands.registerCommand('quantai.journal', () => showTerminal('journal')),
        vscode.commands.registerCommand('quantai.resume', () => showTerminal('resume')),
        vscode.commands.registerCommand('quantai.profile', () => showTerminal('profile')),
        vscode.commands.registerCommand('quantai.aios', () => showTerminal('aios')),
        vscode.commands.registerCommand('quantai.replay', () => showTerminal('replay')),
        vscode.commands.registerCommand('quantai.health', () => showTerminal('health')),
        vscode.commands.registerCommand('quantai.startServer', startServer),
        vscode.commands.registerCommand('quantai.stopServer', stopServer),
        vscode.commands.registerCommand('quantai.addWatch', addToWatchlist),
        vscode.commands.registerCommand('quantai.scan', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.analyze', () => showStockResearch()),
        vscode.commands.registerCommand('quantai.knowledge', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.status', async () => {
            const ok = await healthCheck();
            vscode.window.showInformationMessage(ok ? 'AIIP: 后端运行中' : 'AIIP: 后端未启动');
        }),
    );

    vscode.window.registerTreeDataProvider('quantai-actions', new TerminalNavProvider());
    vscode.window.registerTreeDataProvider('quantai-status', new StatusProvider());

    checkAndStartServer();
}

export function deactivate() { stopServer(); stopAlertPolling(); }

// ============================================================
// SERVER LIFECYCLE
// ============================================================
async function checkAndStartServer() {
    if (await healthCheck()) { statusBar.text = '$(check) AIIP'; startAlertPolling(); return; }
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
        if (await healthCheck()) { statusBar.text = '$(check) AIIP'; startAlertPolling(); return; }
    }
    statusBar.text = '$(error) AIIP';
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
                const [market, scanner, watchScores, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality] = await Promise.all([
                    httpGet('/market/overview').catch(() => null),
                    httpPost('/scanner/run?pool_size=30&top_n=8').catch(() => null),
                    httpPost('/signals/batch', { codes: watchlist }).catch(() => null),
                    httpGet('/morning-brief/today').catch(() => null),
                    httpGet('/alerts/today').catch(() => null),
                    httpGet('/trust/track-record?days=30').catch(() => null),
                    httpGet('/trust/ai-alpha?days=90').catch(() => null),
                    httpGet('/user/profile/summary').catch(() => null),
                    httpGet('/market/data-quality').catch(() => null),
                ]);
                // Push VS Code notification for P0/P1 alerts
                checkUrgentAlerts(alerts);
                return { market, scanner, watchScores, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality };
            }
            case 'journal': {
                const [journal, summary] = await Promise.all([
                    httpGet('/trust/journal?limit=30').catch(() => null),
                    httpGet('/trust/journal/summary').catch(() => null),
                ]);
                return { journal, summary };
            }
            case 'resume': {
                const [resume, versions, monthly, strategies, scoreRanges, trackRecord] = await Promise.all([
                    httpGet('/trust/resume').catch(() => null),
                    httpGet('/trust/model-evolution').catch(() => null),
                    httpGet('/trust/monthly').catch(() => null),
                    httpGet('/trust/strategies').catch(() => null),
                    httpGet('/trust/score-ranges').catch(() => null),
                    httpGet('/trust/track-record?days=30').catch(() => null),
                ]);
                return { resume, versions, monthly, strategies, scoreRanges, trackRecord };
            }
            case 'profile': {
                const profile = await httpGet('/user/profile').catch(() => null);
                return { profile };
            }
            case 'aios': {
                const [status, todayMemory, weeklyMemory, learningLog, events] = await Promise.all([
                    httpGet('/ai-os/status').catch(() => null),
                    httpGet('/ai-os/memory/today').catch(() => null),
                    httpGet('/ai-os/memory/week').catch(() => null),
                    httpGet('/ai-os/learning-log').catch(() => null),
                    httpGet('/ai-os/events?limit=30').catch(() => null),
                ]);
                return { status, todayMemory, weeklyMemory, learningLog, events };
            }
            case 'replay': return {};
            case 'health': {
                const health = await httpGet('/market/system-health').catch(() => null);
                return { health };
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
        case 'journal': return buildJournalPage(data);
        case 'resume': return buildResumePage(data);
        case 'profile': return buildProfilePage(data);
        case 'aios': return buildAIOSPage(data);
        case 'replay': return buildReplayPage(data);
        case 'health': return buildHealthPage(data);
        case 'compare': return buildComparePage(data);
        case 'timeline': return buildTimelinePage(data);
        default: return pageShell('dashboard', 'Adaptive Investment Intelligence', '<div class="empty-state"><div class="icon">🤖</div><h2>Adaptive Investment Intelligence</h2><p>选择一个页面开始</p></div>');
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

// ============================================================
// ALERT INTELLIGENCE — Proactive notifications
// ============================================================
let lastAlertIds: Set<string> = new Set();
let alertPollInterval: NodeJS.Timeout | null = null;

function checkUrgentAlerts(alertsData: any) {
    if (!alertsData) return;
    const focus = alertsData.today_focus || {};
    const urgent = focus.urgent || [];
    for (const alert of urgent) {
        if (!lastAlertIds.has(alert.id) && alert.status === 'new') {
            lastAlertIds.add(alert.id);
            const levelIcon = alert.level === 'P0' ? '🔴' : '🟢';
            const msg = `${levelIcon} [${alert.level}] ${alert.title}`;
            if (alert.level === 'P0') {
                vscode.window.showErrorMessage(msg, '查看', '忽略').then(choice => {
                    if (choice === '查看') showTerminal('alerts');
                });
            } else {
                vscode.window.showWarningMessage(msg, '查看', '忽略').then(choice => {
                    if (choice === '查看') showTerminal('alerts');
                });
            }
        }
    }
    // Track seen alert IDs
    for (const alert of urgent) {
        lastAlertIds.add(alert.id);
    }
}

function startAlertPolling() {
    if (alertPollInterval) return;
    alertPollInterval = setInterval(async () => {
        try {
            const alertsData = await httpGet('/alerts/today');
            checkUrgentAlerts(alertsData);
        } catch {}
    }, 120000); // Every 2 minutes
}

function stopAlertPolling() {
    if (alertPollInterval) {
        clearInterval(alertPollInterval);
        alertPollInterval = null;
    }
}
