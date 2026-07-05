"use strict";
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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const cp = __importStar(require("child_process"));
const client_1 = require("./api/client");
const layout_1 = require("./webview/layout");
const providers_1 = require("./sidebar/providers");
const dashboard_1 = require("./pages/dashboard");
const watchlist_1 = require("./pages/watchlist");
const research_1 = require("./pages/research");
const marketmap_1 = require("./pages/marketmap");
const alerts_1 = require("./pages/alerts");
const backtest_1 = require("./pages/backtest");
const dailybrief_1 = require("./pages/dailybrief");
const compare_1 = require("./pages/compare");
const timeline_1 = require("./pages/timeline");
const portfolio_1 = require("./pages/portfolio");
const journal_1 = require("./pages/journal");
const resume_1 = require("./pages/resume");
const profile_1 = require("./pages/profile");
let serverProcess = null;
let statusBar;
let watchlist = [];
let extensionContext = null;
// ============================================================
// ACTIVATION
// ============================================================
function activate(context) {
    console.log('Adaptive Investment Intelligence Platform activated');
    extensionContext = context;
    watchlist = context.globalState.get('watchlist', ['000001.SZ', '600519.SH', '000858.SZ', '300750.SZ', '002475.SZ']);
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(pulse) AIIP';
    statusBar.command = 'quantai.terminal';
    statusBar.show();
    context.subscriptions.push(vscode.commands.registerCommand('quantai.terminal', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.dashboard', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.watchlist', () => showTerminal('watchlist')), vscode.commands.registerCommand('quantai.research', () => showStockResearch()), vscode.commands.registerCommand('quantai.marketmap', () => showTerminal('marketmap')), vscode.commands.registerCommand('quantai.alerts', () => showTerminal('alerts')), vscode.commands.registerCommand('quantai.backtest', () => showTerminal('backtest')), vscode.commands.registerCommand('quantai.dailybrief', () => showTerminal('dailybrief')), vscode.commands.registerCommand('quantai.compare', () => showTerminal('compare')), vscode.commands.registerCommand('quantai.timeline', () => showTerminal('timeline')), vscode.commands.registerCommand('quantai.portfolio', () => showTerminal('portfolio')), vscode.commands.registerCommand('quantai.journal', () => showTerminal('journal')), vscode.commands.registerCommand('quantai.resume', () => showTerminal('resume')), vscode.commands.registerCommand('quantai.profile', () => showTerminal('profile')), vscode.commands.registerCommand('quantai.startServer', startServer), vscode.commands.registerCommand('quantai.stopServer', stopServer), vscode.commands.registerCommand('quantai.addWatch', addToWatchlist), vscode.commands.registerCommand('quantai.scan', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.analyze', () => showStockResearch()), vscode.commands.registerCommand('quantai.knowledge', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.status', async () => {
        const ok = await (0, client_1.healthCheck)();
        vscode.window.showInformationMessage(ok ? 'AIIP: 后端运行中' : 'AIIP: 后端未启动');
    }));
    vscode.window.registerTreeDataProvider('quantai-actions', new providers_1.TerminalNavProvider());
    vscode.window.registerTreeDataProvider('quantai-status', new providers_1.StatusProvider());
    checkAndStartServer();
}
function deactivate() { stopServer(); stopAlertPolling(); }
// ============================================================
// SERVER LIFECYCLE
// ============================================================
async function checkAndStartServer() {
    if (await (0, client_1.healthCheck)()) {
        statusBar.text = '$(check) AIIP';
        startAlertPolling();
        return;
    }
    await startServer();
}
async function startServer() {
    if (serverProcess)
        return;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!root)
        return;
    statusBar.text = '$(sync~spin) Starting...';
    serverProcess = cp.spawn('poetry', ['run', 'uvicorn', 'src.api.app:app', '--host', '127.0.0.1', '--port', '8888'], {
        cwd: root, shell: true, stdio: 'pipe',
    });
    for (let i = 0; i < 20; i++) {
        await (0, client_1.sleep)(1000);
        if (await (0, client_1.healthCheck)()) {
            statusBar.text = '$(check) AIIP';
            startAlertPolling();
            return;
        }
    }
    statusBar.text = '$(error) AIIP';
}
function stopServer() { if (serverProcess) {
    serverProcess.kill();
    serverProcess = null;
} }
// ============================================================
// NAVIGATION & DATA FETCHING
// ============================================================
async function showTerminal(page, extraData) {
    const data = await fetchPageData(page, extraData);
    const html = buildPage(page, data);
    (0, layout_1.createOrShowPanel)((0, layout_1.getPageTitle)(page), html, (msg) => handleMessage(msg, page));
}
async function fetchPageData(page, extraData) {
    try {
        switch (page) {
            case 'dashboard': {
                const [market, scanner, watchScores, brief, alerts, trackRecord, aiAlpha, userProfile] = await Promise.all([
                    (0, client_1.httpGet)('/market/overview').catch(() => null),
                    (0, client_1.httpPost)('/scanner/run?pool_size=30&top_n=8').catch(() => null),
                    (0, client_1.httpPost)('/signals/batch', { codes: watchlist }).catch(() => null),
                    (0, client_1.httpGet)('/morning-brief/today').catch(() => null),
                    (0, client_1.httpGet)('/alerts/today').catch(() => null),
                    (0, client_1.httpGet)('/trust/track-record?days=30').catch(() => null),
                    (0, client_1.httpGet)('/trust/ai-alpha?days=90').catch(() => null),
                    (0, client_1.httpGet)('/user/profile/summary').catch(() => null),
                ]);
                // Push VS Code notification for P0/P1 alerts
                checkUrgentAlerts(alerts);
                return { market, scanner, watchScores, brief, alerts, trackRecord, aiAlpha, userProfile };
            }
            case 'journal': {
                const [journal, summary] = await Promise.all([
                    (0, client_1.httpGet)('/trust/journal?limit=30').catch(() => null),
                    (0, client_1.httpGet)('/trust/journal/summary').catch(() => null),
                ]);
                return { journal, summary };
            }
            case 'resume': {
                const [resume, versions, monthly, strategies, scoreRanges, trackRecord] = await Promise.all([
                    (0, client_1.httpGet)('/trust/resume').catch(() => null),
                    (0, client_1.httpGet)('/trust/model-evolution').catch(() => null),
                    (0, client_1.httpGet)('/trust/monthly').catch(() => null),
                    (0, client_1.httpGet)('/trust/strategies').catch(() => null),
                    (0, client_1.httpGet)('/trust/score-ranges').catch(() => null),
                    (0, client_1.httpGet)('/trust/track-record?days=30').catch(() => null),
                ]);
                return { resume, versions, monthly, strategies, scoreRanges, trackRecord };
            }
            case 'profile': {
                const profile = await (0, client_1.httpGet)('/user/profile').catch(() => null);
                return { profile };
            }
            case 'watchlist': {
                const watchScores = await (0, client_1.httpPost)('/signals/batch', { codes: watchlist }).catch(() => null);
                return { stocks: watchlist, watchScores };
            }
            case 'marketmap': {
                const sectors = await (0, client_1.httpGet)('/market/sectors').catch(() => null);
                return { sectors: sectors?.sectors || [] };
            }
            case 'alerts': {
                const alerts = await (0, client_1.httpGet)('/alerts/recent?limit=50').catch(() => null);
                return { alerts };
            }
            case 'backtest': {
                const backtest = await (0, client_1.httpPost)('/backtest/run?trend=up&days=120').catch(() => null);
                return { backtest };
            }
            case 'dailybrief': {
                const brief = await (0, client_1.httpGet)('/dailybrief/latest').catch(() => null);
                return { brief };
            }
            case 'portfolio': {
                const portfolio = await (0, client_1.httpGet)('/portfolio/overview').catch(() => null);
                return { portfolio };
            }
            case 'compare': return {};
            case 'timeline': {
                const code = extraData?.code || '600519.SH';
                const timeline = await (0, client_1.httpGet)(`/timeline/${code}?days=30`).catch(() => null);
                return { timeline };
            }
            default: return {};
        }
    }
    catch {
        return {};
    }
}
function buildPage(page, data) {
    switch (page) {
        case 'dashboard': return (0, dashboard_1.buildDashboardPage)(data);
        case 'watchlist': return (0, watchlist_1.buildWatchlistPage)(data);
        case 'marketmap': return (0, marketmap_1.buildMarketMapPage)(data);
        case 'alerts': return (0, alerts_1.buildAlertsPage)(data);
        case 'backtest': return (0, backtest_1.buildBacktestPage)(data);
        case 'dailybrief': return (0, dailybrief_1.buildDailyBriefPage)(data);
        case 'portfolio': return (0, portfolio_1.buildPortfolioPage)(data);
        case 'journal': return (0, journal_1.buildJournalPage)(data);
        case 'resume': return (0, resume_1.buildResumePage)(data);
        case 'profile': return (0, profile_1.buildProfilePage)(data);
        case 'compare': return (0, compare_1.buildComparePage)(data);
        case 'timeline': return (0, timeline_1.buildTimelinePage)(data);
        default: return (0, layout_1.pageShell)('dashboard', 'Adaptive Investment Intelligence', '<div class="empty-state"><div class="icon">🤖</div><h2>Adaptive Investment Intelligence</h2><p>选择一个页面开始</p></div>');
    }
}
function handleMessage(msg, currentPage) {
    switch (msg.command) {
        case 'navigate':
            showTerminal(msg.page);
            break;
        case 'addWatch':
            addToWatchlist().then(() => showTerminal('watchlist'));
            break;
        case 'analyze':
            showStockResearchDirect(msg.code);
            break;
        case 'compare':
            showTerminal('compare');
            break;
        case 'timeline':
            showTerminal('timeline', { code: msg.code });
            break;
    }
}
// ============================================================
// STOCK RESEARCH
// ============================================================
async function showStockResearch() {
    const code = await vscode.window.showInputBox({ prompt: '股票代码', value: '000001.SZ' });
    if (!code)
        return;
    await showStockResearchDirect(code);
}
async function showStockResearchDirect(code) {
    const detail = await (0, client_1.httpGet)(`/detail/${code}?include=all`).catch(() => null);
    const html = (0, research_1.buildResearchPage)(code, detail);
    (0, layout_1.createOrShowPanel)(`${code} Research`, html, (msg) => handleMessage(msg, 'research'));
}
// ============================================================
// WATCHLIST MANAGEMENT
// ============================================================
async function addToWatchlist() {
    const code = await vscode.window.showInputBox({ prompt: '添加自选股', placeHolder: '000001.SZ' });
    if (!code)
        return;
    if (!watchlist.includes(code)) {
        watchlist.push(code);
    }
    if (extensionContext) {
        extensionContext.globalState.update('watchlist', watchlist);
    }
    vscode.window.showInformationMessage(`${code} 已添加到自选`);
}
// ============================================================
// ALERT INTELLIGENCE — Proactive notifications
// ============================================================
let lastAlertIds = new Set();
let alertPollInterval = null;
function checkUrgentAlerts(alertsData) {
    if (!alertsData)
        return;
    const focus = alertsData.today_focus || {};
    const urgent = focus.urgent || [];
    for (const alert of urgent) {
        if (!lastAlertIds.has(alert.id) && alert.status === 'new') {
            lastAlertIds.add(alert.id);
            const levelIcon = alert.level === 'P0' ? '🔴' : '🟢';
            const msg = `${levelIcon} [${alert.level}] ${alert.title}`;
            if (alert.level === 'P0') {
                vscode.window.showErrorMessage(msg, '查看', '忽略').then(choice => {
                    if (choice === '查看')
                        showTerminal('alerts');
                });
            }
            else {
                vscode.window.showWarningMessage(msg, '查看', '忽略').then(choice => {
                    if (choice === '查看')
                        showTerminal('alerts');
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
    if (alertPollInterval)
        return;
    alertPollInterval = setInterval(async () => {
        try {
            const alertsData = await (0, client_1.httpGet)('/alerts/today');
            checkUrgentAlerts(alertsData);
        }
        catch { }
    }, 120000); // Every 2 minutes
}
function stopAlertPolling() {
    if (alertPollInterval) {
        clearInterval(alertPollInterval);
        alertPollInterval = null;
    }
}
//# sourceMappingURL=extension.js.map