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
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const constants_1 = require("./constants");
const client_1 = require("./api/client");
const page_cache_1 = require("./page-cache");
const layout_1 = require("./webview/layout");
const providers_1 = require("./sidebar/providers");
const dashboard_1 = require("./pages/dashboard");
const watchlist_1 = require("./pages/watchlist");
const research_1 = require("./pages/research");
const marketmap_1 = require("./pages/marketmap");
const alerts_1 = require("./pages/alerts");
const backtest_1 = require("./pages/backtest");
const dailybrief_1 = require("./pages/dailybrief");
const newsradar_1 = require("./pages/newsradar");
const reports_1 = require("./pages/reports");
const announcements_1 = require("./pages/announcements");
const financials_1 = require("./pages/financials");
const valuation_1 = require("./pages/valuation");
const fundflow_1 = require("./pages/fundflow");
const dragon_tiger_1 = require("./pages/dragon_tiger");
const compare_1 = require("./pages/compare");
const timeline_1 = require("./pages/timeline");
const portfolio_1 = require("./pages/portfolio");
const journal_1 = require("./pages/journal");
const resume_1 = require("./pages/resume");
const profile_1 = require("./pages/profile");
const aios_1 = require("./pages/aios");
const taskmonitor_1 = require("./pages/taskmonitor");
const replay_1 = require("./pages/replay");
const health_1 = require("./pages/health");
const connectors_1 = require("./pages/connectors");
const decisions_1 = require("./pages/decisions");
const review_lab_1 = require("./pages/review_lab");
const view_1 = require("./review-lab/view");
let serverProcess = null;
let serverRestartTimer = null;
let serverRestartAttempts = 0;
let stoppingServer = false;
let isDeactivating = false;
let statusBar;
let statusProvider = null;
let watchlist = [];
let extensionContext = null;
const pageCache = new Map();
let navigationVersion = 0;
let activePageExtraData = undefined;
let backendPathPromptShown = false;
const BACKEND_PATH_KEY = 'adaptiveInvestment.backendPath';
const PAGE_CACHE_TTL_MS = {
    dashboard: 60_000,
    watchlist: 30_000,
    alerts: 30_000,
    marketmap: 120_000,
    backtest: 300_000,
    compare: 120_000,
    timeline: 120_000,
    portfolio: 60_000,
    dailybrief: 120_000,
    journal: 60_000,
    resume: 300_000,
    profile: 300_000,
    aios: 60_000,
    health: 60_000,
    connectors: 300_000,
    decisions: 60_000,
    review_lab: 60_000,
};
const DAILY_BRIEF_TIMEOUT_MS = 10_000;
// ============================================================
// ACTIVATION
// ============================================================
function activate(context) {
    console.log('Adaptive Investment Intelligence Platform activated');
    isDeactivating = false;
    extensionContext = context;
    watchlist = context.globalState.get('watchlist', []);
    // 规范化已有代码(老数据可能无后缀如 000725, 后端只认 .SZ/.SH)
    const normalized = watchlist.map(normalizeCode).filter((c) => c !== null);
    if (JSON.stringify(normalized) !== JSON.stringify(watchlist)) {
        watchlist = normalized;
        context.globalState.update('watchlist', watchlist);
    }
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(pulse) AIIP';
    statusBar.command = 'quantai.terminal';
    statusBar.show();
    const releaseBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
    releaseBar.command = 'quantai.health';
    const refreshRelease = async () => {
        try {
            const state = await (0, client_1.releaseCompatibility)();
            releaseBar.text = state.matches
                ? `$(verified) v${client_1.frontendRelease.product_version}` : '$(warning) 版本不一致';
            releaseBar.tooltip = state.message;
        }
        catch {
            releaseBar.text = '$(warning) 版本待核验';
            releaseBar.tooltip = '后端不可达，尚不能确认前后端版本一致';
        }
        releaseBar.show();
    };
    void refreshRelease();
    const releaseTimer = setInterval(() => { void refreshRelease(); }, 30_000);
    context.subscriptions.push(releaseBar, { dispose: () => clearInterval(releaseTimer) });
    context.subscriptions.push(vscode.commands.registerCommand('quantai.terminal', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.dashboard', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.watchlist', () => showTerminal('watchlist')), vscode.commands.registerCommand('quantai.research', () => showStockResearch()), vscode.commands.registerCommand('quantai.marketmap', () => showTerminal('marketmap')), vscode.commands.registerCommand('quantai.alerts', () => showTerminal('alerts')), vscode.commands.registerCommand('quantai.backtest', () => showTerminal('backtest')), vscode.commands.registerCommand('quantai.dailybrief', () => showTerminal('dailybrief')), vscode.commands.registerCommand('quantai.newsradar', () => showTerminal('newsradar')), vscode.commands.registerCommand('quantai.reports', () => showTerminal('reports')), vscode.commands.registerCommand('quantai.announcements', () => showTerminal('announcements')), vscode.commands.registerCommand('quantai.financials', () => showTerminal('financials')), vscode.commands.registerCommand('quantai.valuation', () => showTerminal('valuation')), vscode.commands.registerCommand('quantai.fundflow', () => showTerminal('fundflow')), vscode.commands.registerCommand('quantai.dragonTiger', () => showTerminal('dragon_tiger')), vscode.commands.registerCommand('quantai.compare', () => showTerminal('compare')), vscode.commands.registerCommand('quantai.timeline', () => showTerminal('timeline')), vscode.commands.registerCommand('quantai.portfolio', () => showTerminal('portfolio')), vscode.commands.registerCommand('quantai.journal', () => showTerminal('journal')), vscode.commands.registerCommand('quantai.resume', () => showTerminal('resume')), vscode.commands.registerCommand('quantai.profile', () => showTerminal('profile')), vscode.commands.registerCommand('quantai.aios', () => showTerminal('aios')), vscode.commands.registerCommand('quantai.taskmonitor', () => showTerminal('taskmonitor')), vscode.commands.registerCommand('quantai.replay', () => showTerminal('replay')), vscode.commands.registerCommand('quantai.reviewLab', () => showTerminal('review_lab')), vscode.commands.registerCommand('quantai.reviewLabSimulate', () => (0, view_1.showReviewSimulation)(context)), vscode.commands.registerCommand('quantai.reviewLabHistorical', () => (0, view_1.showHistoricalReview)(context)), vscode.commands.registerCommand('quantai.health', () => showTerminal('health')), vscode.commands.registerCommand('quantai.connectors', () => showTerminal('connectors')), vscode.commands.registerCommand('quantai.decisions', () => showTerminal('decisions')), vscode.commands.registerCommand('quantai.startServer', startServer), vscode.commands.registerCommand('quantai.stopServer', stopServer), vscode.commands.registerCommand('quantai.restartServer', restartServer), vscode.commands.registerCommand('quantai.configureBackend', configureBackend), vscode.commands.registerCommand('quantai.addWatch', addToWatchlist), vscode.commands.registerCommand('quantai.scan', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.analyze', () => showStockResearch()), vscode.commands.registerCommand('quantai.knowledge', () => showTerminal('dashboard')), vscode.commands.registerCommand('quantai.status', async () => {
        const ok = await backendIsOnline();
        vscode.window.showInformationMessage(ok ? 'AIIP: 后端运行中' : 'AIIP: 后端未启动');
    }));
    vscode.window.registerTreeDataProvider('quantai-actions', new providers_1.TerminalNavProvider());
    statusProvider = new providers_1.StatusProvider();
    context.subscriptions.push(vscode.window.registerTreeDataProvider('quantai-status', statusProvider), statusProvider);
    checkAndStartServer();
}
function deactivate() {
    isDeactivating = true;
    stopServer();
    stopAlertPolling();
}
// ============================================================
// SERVER LIFECYCLE
// ============================================================
async function checkAndStartServer() {
    if (await backendIsOnline()) {
        serverRestartAttempts = 0;
        statusBar.text = '$(check) AIIP';
        statusProvider?.refresh();
        startAlertPolling();
        return;
    }
    await startServer();
}
async function startServer() {
    stoppingServer = false;
    const configuredRoot = extensionContext?.globalState.get(BACKEND_PATH_KEY) || '';
    const seeds = [
        configuredRoot,
        ...(vscode.workspace.workspaceFolders ?? []).map(folder => folder.uri.fsPath),
        extensionContext ? extensionContext.extensionPath : '',
        process.cwd(),
    ].filter((candidate, index, all) => Boolean(candidate) && all.indexOf(candidate) === index);
    const root = findBackendRoot(seeds);
    if (!root) {
        statusBar.text = '$(error) AIIP';
        statusProvider?.refresh();
        if (!backendPathPromptShown) {
            backendPathPromptShown = true;
            const action = await vscode.window.showWarningMessage('AIIP 未找到 Python 后端目录，数据与 AI 功能无法启动。', '选择后端目录');
            if (action === '选择后端目录' && await configureBackend()) {
                await startServer();
            }
        }
        return;
    }
    if (root !== configuredRoot) {
        await extensionContext?.globalState.update(BACKEND_PATH_KEY, root);
    }
    backendPathPromptShown = false;
    statusBar.text = '$(sync~spin) Starting...';
    if (serverProcess?.exitCode !== null || serverProcess?.killed) {
        serverProcess = null;
    }
    if (!(await backendIsOnline()) && !serverProcess) {
        const launch = getBackendLaunchSpec(root);
        const managed = process.platform === 'win32' && fs.existsSync(path.join(root, 'runtime', 'active-manifest.json'));
        const child = cp.spawn(launch.command, launch.args, {
            cwd: root, shell: launch.shell, windowsHide: true,
            stdio: managed ? 'ignore' : 'pipe', detached: managed,
        });
        if (managed)
            child.unref();
        serverProcess = managed ? null : child;
        child.stdout?.on('data', chunk => console.log(`[AIIP backend] ${String(chunk).trimEnd()}`));
        child.stderr?.on('data', chunk => console.error(`[AIIP backend] ${String(chunk).trimEnd()}`));
        child.once('error', error => {
            console.error('AIIP backend failed to start', error);
            if (serverProcess === child)
                serverProcess = null;
            statusBar.text = '$(error) AIIP';
            statusProvider?.refresh();
            scheduleServerRestart();
        });
        child.once('exit', (code, signal) => {
            if (serverProcess === child)
                serverProcess = null;
            console.log(`AIIP backend exited (code=${code}, signal=${signal})`);
            if (stoppingServer || isDeactivating)
                return;
            // A local child can exit because a SYSTEM-owned backend won the
            // port. Re-probe before reporting an outage or scheduling a loop.
            void backendIsOnline().then(online => {
                if (online) {
                    serverRestartAttempts = 0;
                    statusBar.text = '$(check) AIIP';
                    statusProvider?.refresh();
                    startAlertPolling();
                    return;
                }
                statusBar.text = '$(error) AIIP';
                statusProvider?.refresh();
                stopAlertPolling();
                scheduleServerRestart();
            });
        });
    }
    for (let i = 0; i < 30; i++) {
        await (0, client_1.sleep)(1000);
        if (await (0, client_1.healthCheck)()) {
            serverRestartAttempts = 0;
            statusBar.text = '$(check) AIIP';
            statusProvider?.refresh();
            startAlertPolling();
            return;
        }
    }
    statusBar.text = '$(error) AIIP';
    statusProvider?.refresh();
    scheduleServerRestart();
}
async function backendIsOnline() {
    if (await (0, client_1.healthCheck)())
        return true;
    // A service restart or Windows Defender scan can delay one probe. Confirm
    // the state before starting a second process or showing "not started".
    await (0, client_1.sleep)(250);
    return (0, client_1.healthCheck)();
}
function isBackendRoot(candidate) {
    return fs.existsSync(path.join(candidate, 'pyproject.toml'))
        && fs.existsSync(path.join(candidate, 'src', 'api', 'app.py'));
}
function findBackendRoot(seeds) {
    const queue = [];
    const visited = new Set();
    for (const seed of seeds) {
        if (!fs.existsSync(seed))
            continue;
        queue.push({ directory: path.resolve(seed), depth: 0 });
    }
    const ignored = new Set(['.git', '.venv', 'node_modules', 'out', '__pycache__']);
    while (queue.length > 0 && visited.size < 300) {
        const current = queue.shift();
        const directory = path.resolve(current.directory);
        if (visited.has(directory))
            continue;
        visited.add(directory);
        if (isBackendRoot(directory))
            return directory;
        if (current.depth >= 2)
            continue;
        let entries = [];
        try {
            entries = fs.readdirSync(directory, { withFileTypes: true });
        }
        catch {
            continue;
        }
        for (const entry of entries) {
            if (!entry.isDirectory() || ignored.has(entry.name))
                continue;
            queue.push({ directory: path.join(directory, entry.name), depth: current.depth + 1 });
        }
    }
    return null;
}
function getBackendLaunchSpec(root) {
    if (process.platform === 'win32' && fs.existsSync(path.join(root, 'runtime', 'active-manifest.json'))) {
        const launcher = path.resolve(root, '../scripts/start_adaptive_learning_backend.ps1');
        if (!fs.existsSync(launcher))
            throw new Error('托管后端启动器缺失，拒绝降级启动源码');
        return { command: 'powershell.exe', args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', launcher], shell: false };
    }
    const venvPython = process.platform === 'win32'
        ? path.join(root, '.venv', 'Scripts', 'python.exe')
        : path.join(root, '.venv', 'bin', 'python');
    if (fs.existsSync(venvPython)) {
        return {
            command: venvPython,
            args: [
                '-m', 'uvicorn', 'src.api.app:app',
                '--host', constants_1.ADAPTIVE_API_HOST,
                '--port', String(constants_1.ADAPTIVE_API_PORT),
            ],
            shell: false,
        };
    }
    return {
        command: 'poetry',
        args: [
            'run', 'uvicorn', 'src.api.app:app',
            '--host', constants_1.ADAPTIVE_API_HOST,
            '--port', String(constants_1.ADAPTIVE_API_PORT),
        ],
        shell: true,
    };
}
async function configureBackend() {
    const selected = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: '选择 Adaptive Investment 后端目录',
    });
    const root = selected?.[0]?.fsPath;
    if (!root)
        return false;
    if (!fs.existsSync(path.join(root, 'pyproject.toml'))
        || !fs.existsSync(path.join(root, 'src', 'api', 'app.py'))) {
        vscode.window.showErrorMessage('所选目录不是有效的 AIIP 后端（缺少 pyproject.toml 或 src/api/app.py）。');
        return false;
    }
    await extensionContext?.globalState.update(BACKEND_PATH_KEY, root);
    backendPathPromptShown = false;
    vscode.window.showInformationMessage(`AIIP 后端目录已保存：${root}`);
    return true;
}
function stopServer() {
    stoppingServer = true;
    if (serverRestartTimer) {
        clearTimeout(serverRestartTimer);
        serverRestartTimer = null;
    }
    const child = serverProcess;
    serverProcess = null;
    statusProvider?.refresh();
    if (!child || child.exitCode !== null)
        return;
    if (process.platform === 'win32' && child.pid) {
        cp.spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
            windowsHide: true,
            stdio: 'ignore',
        });
    }
    else {
        child.kill();
    }
}
function scheduleServerRestart() {
    if (isDeactivating || stoppingServer || serverRestartTimer || serverRestartAttempts >= 3)
        return;
    const delayMs = Math.min(15_000, 2000 * (2 ** serverRestartAttempts));
    serverRestartAttempts += 1;
    serverRestartTimer = setTimeout(() => {
        serverRestartTimer = null;
        void startServer();
    }, delayMs);
}
async function restartServer() {
    stopServer();
    // Kill orphaned companion processes from previous extension sessions.
    for (const port of [constants_1.ADAPTIVE_API_PORT]) {
        try {
            const { execSync } = require('child_process');
            const out = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, { timeout: 5000, encoding: 'utf8' });
            const pid = out.trim().split(/\s+/).pop();
            if (pid)
                execSync(`taskkill /F /PID ${pid}`);
        }
        catch { /* no orphan */ }
    }
    await (0, client_1.sleep)(1000);
    stoppingServer = false;
    serverRestartAttempts = 0;
    await startServer();
}
// ============================================================
// NAVIGATION & DATA FETCHING
// ============================================================
async function showTerminal(page, extraData) {
    const version = ++navigationVersion;
    activePageExtraData = extraData;
    const cacheKey = getPageCacheKey(page, extraData);
    const cached = pageCache.get(cacheKey);
    const ttlMs = PAGE_CACHE_TTL_MS[page] ?? 60_000;
    const now = Date.now();
    const isFresh = cached?.lastSuccessfulAt
        ? now - cached.lastSuccessfulAt < ttlMs
        : Boolean(cached?.fetchedAt && now - cached.fetchedAt < ttlMs);
    const retryAllowed = !cached?.retryAfter || now >= cached.retryAfter;
    if (cached?.data) {
        renderTerminalPage(page, cached.data, version);
        if (!isFresh && retryAllowed) {
            void refreshPageData(page, extraData, cacheKey, version);
        }
        return;
    }
    const loading = '<div class="loading">Loading data</div>';
    (0, layout_1.createOrShowPanel)((0, layout_1.getPageTitle)(page), (0, layout_1.pageShell)(page, (0, layout_1.getPageTitle)(page), loading), (msg) => handleMessage(msg, page));
    await refreshPageData(page, extraData, cacheKey, version);
}
function getPageCacheKey(page, extraData) {
    return `${page}:${JSON.stringify(extraData || {})}`;
}
async function refreshPageData(page, extraData, cacheKey, version, force = false) {
    const cached = pageCache.get(cacheKey);
    const pending = cached?.pending || fetchPageData(page, extraData, force);
    pageCache.set(cacheKey, {
        ...cached,
        data: cached?.data,
        fetchedAt: cached?.fetchedAt || 0,
        pending,
    });
    let data;
    try {
        data = await pending;
    }
    catch (error) {
        data = requestErrorData(error, '页面');
    }
    const displayData = (0, page_cache_1.cachePageResult)(cached, data, Date.now(), page_cache_1.PAGE_RETRY_COOLDOWN_MS);
    pageCache.set(cacheKey, displayData);
    if (version === navigationVersion) {
        renderTerminalPage(page, displayData.data, version);
    }
    return displayData.data;
}
function requestErrorData(error, label) {
    const message = error instanceof Error ? error.message : `${label}数据接口暂不可用`;
    const isTimeout = /timed out|timeout|超时|ETIMEDOUT/i.test(message);
    return {
        pageError: isTimeout ? `${label}请求超时：${message}` : `${label}请求失败：${message}`,
        pageErrorKind: isTimeout ? 'timeout' : 'request',
    };
}
function renderTerminalPage(page, data, version) {
    if (version !== navigationVersion)
        return;
    let html;
    try {
        html = buildPage(page, data);
    }
    catch (error) {
        console.error(`Failed to render AIIP page: ${page}`, error);
        html = (0, layout_1.pageShell)(page, (0, layout_1.getPageTitle)(page), `<div class="card" style="margin:24px;border-left:3px solid #f85149">
                <h3>页面渲染失败</h3>
                <p class="text-muted">数据格式异常，但其他功能仍可继续使用。</p>
                <button class="btn btn-primary" onclick="retryPage()">重试</button>
            </div>`, `function retryPage(){vscode.postMessage({command:'refreshPage'});}`);
    }
    (0, layout_1.createOrShowPanel)((0, layout_1.getPageTitle)(page), html, (msg) => handleMessage(msg, page));
}
function invalidatePageCache(...pages) {
    for (const key of Array.from(pageCache.keys())) {
        if (pages.some(page => key.startsWith(`${page}:`))) {
            pageCache.delete(key);
        }
    }
}
async function resolveDefaultStockCode(explicitCode) {
    const direct = explicitCode ? normalizeCode(explicitCode) : null;
    if (direct)
        return direct;
    if (watchlist.length > 0)
        return watchlist[0];
    const journal = await (0, client_1.httpGet)('/trust/journal?limit=1').catch(() => null);
    const journalCode = journal?.entries?.[0]?.stock_code;
    return normalizeCode(journalCode || '') || '';
}
async function fetchPageData(page, extraData, force = false) {
    try {
        switch (page) {
            case 'dashboard': {
                const journalForWatch = watchlist.length
                    ? null
                    : await (0, client_1.httpGet)('/trust/journal?limit=10').catch(() => null);
                const suggestedWatch = (journalForWatch?.entries || []).map((e) => e.stock_code).filter(Boolean);
                const watchCodes = watchlist.length ? watchlist : suggestedWatch;
                const [market, scanner, watchScores, liveQuotes, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality] = await Promise.all([
                    (0, client_1.httpGet)('/market/overview').catch(() => null),
                    (0, client_1.httpGet)('/scanner/latest?top_n=8').catch(() => null),
                    (0, client_1.httpPost)('/signals/batch', { codes: watchCodes, force }).catch(() => null),
                    (0, client_1.httpPost)('/market/quotes', { codes: watchCodes }).catch(() => null),
                    (0, client_1.httpGet)('/morning-brief/today').catch(() => null),
                    (0, client_1.httpGet)('/alerts/today').catch(() => null),
                    (0, client_1.httpGet)('/trust/track-record?days=30').catch(() => null),
                    (0, client_1.httpGet)('/trust/ai-alpha?days=90').catch(() => null),
                    (0, client_1.httpGet)('/user/profile/summary').catch(() => null),
                    (0, client_1.httpGet)('/market/data-quality').catch(() => null),
                ]);
                // Push VS Code notification for P0/P1 alerts
                checkUrgentAlerts(alerts);
                return { market, scanner, watchScores, liveQuotes, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality };
            }
            case 'journal': {
                const [journal, summary] = await Promise.all([
                    (0, client_1.httpGet)('/trust/journal?limit=100').catch(() => null),
                    (0, client_1.httpGet)('/trust/journal/summary').catch(() => null),
                ]);
                return {
                    journal,
                    summary,
                    journalError: journal ? undefined : '真实决策日志接口暂不可用',
                };
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
                return {
                    resume,
                    versions,
                    monthly,
                    strategies,
                    scoreRanges,
                    trackRecord,
                    resumeError: resume ? undefined : '信任档案接口暂不可用',
                };
            }
            case 'profile': {
                const profile = await (0, client_1.httpGet)('/user/profile').catch(() => null);
                return { profile };
            }
            case 'aios': {
                const endpoints = [
                    { key: 'status', label: '运行状态', path: '/ai-os/status', timeout: 30_000 },
                    { key: 'todayMemory', label: '今日记忆', path: '/ai-os/memory/today', timeout: 30_000 },
                    { key: 'weeklyMemory', label: '周度记忆', path: '/ai-os/memory/week', timeout: 20_000 },
                    { key: 'learningLog', label: '学习日志', path: '/ai-os/learning-log', timeout: 20_000 },
                    { key: 'events', label: '决策事件', path: '/ai-os/events?limit=30', timeout: 20_000 },
                ];
                const results = await Promise.all(endpoints.map(async (endpoint) => {
                    try {
                        return { ...endpoint, data: await (0, client_1.httpGet)(endpoint.path, endpoint.timeout) };
                    }
                    catch (error) {
                        console.warn(`AI OS ${endpoint.key} request failed`, error);
                        return { ...endpoint, data: null };
                    }
                }));
                const payload = {};
                const failed = [];
                for (const result of results) {
                    payload[result.key] = result.data;
                    if (result.data === null)
                        failed.push(result.label);
                }
                return {
                    ...payload,
                    aiosError: failed.length
                        ? `${failed.join('、')}接口暂不可用；历史数据未删除，请稍后刷新。`
                        : undefined,
                };
            }
            case 'taskmonitor': {
                const [status, executions, schedule] = await Promise.all([
                    (0, client_1.httpGet)('/tasks/status').catch(() => null),
                    (0, client_1.httpGet)('/tasks/executions/recent?limit=20').catch(() => null),
                    (0, client_1.httpGet)('/tasks/schedule').catch(() => null),
                ]);
                return { status, executions, schedule };
            }
            case 'replay': {
                const [dates, history] = await Promise.all([
                    (0, client_1.httpGet)('/replay/dates').catch(() => null),
                    (0, client_1.httpGet)('/replay/history?limit=20').catch(() => null),
                ]);
                return { dates, history };
            }
            case 'review_lab': {
                const index = await (0, client_1.httpGet)('/review-lab/runs').catch(() => ({ runs: [] }));
                const runs = Array.isArray(index.runs)
                    ? index.runs.filter((value) => typeof value === 'string' && /^friday-[a-f0-9]{32}$/.test(value)) : [];
                const requested = String(extraData?.runId || '').trim();
                const selectedRunId = /^friday-[a-f0-9]{32}$/.test(requested) ? requested : runs[0];
                const latest = selectedRunId
                    ? await (0, client_1.httpGet)(`/review-lab/runs/${encodeURIComponent(selectedRunId)}`, 5_000).catch(() => null)
                    : null;
                return { latest: latest ? { ...latest, run_id: selectedRunId } : null, runs, selectedRunId };
            }
            case 'health': {
                const [health, hithink] = await Promise.all([
                    (0, client_1.httpGet)('/market/system-health').catch(() => null),
                    (0, client_1.httpGet)('/system/providers/hithink').catch(() => null),
                ]);
                return { health, hithink };
            }
            case 'connectors': {
                const [dataStatus, registry] = await Promise.all([
                    (0, client_1.httpGet)('/market/data-status').catch(() => null),
                    (0, client_1.httpGet)('/market/registry').catch(() => null),
                ]);
                return { dataStatus, registry };
            }
            case 'decisions': {
                const decisions = await (0, client_1.httpGet)('/decision/today').catch(() => null);
                return { decisions };
            }
            case 'watchlist': {
                const journal = await (0, client_1.httpGet)('/trust/journal?limit=20').catch(() => null);
                const suggested = (journal?.entries || []).map((e) => e.stock_code).filter(Boolean);
                const stocks = watchlist.length ? watchlist : suggested;
                const [watchScores, liveQuotes] = stocks.length
                    ? await Promise.all([
                        (0, client_1.httpPost)('/signals/batch', { codes: stocks, force }).catch(() => null),
                        (0, client_1.httpPost)('/market/quotes', { codes: stocks }).catch(() => null),
                    ])
                    : [null, null];
                return { stocks, watchScores, liveQuotes };
            }
            case 'marketmap': {
                const refreshQuery = force ? '?refresh=true' : '';
                const sectors = await (0, client_1.httpGet)(`/market/sectors${refreshQuery}`, 3500).catch(() => null);
                return sectors || { sectors: [], is_live: false, data_source: 'unavailable' };
            }
            case 'alerts': {
                const alerts = await (0, client_1.httpGet)('/alerts/recent?limit=50').catch(() => null);
                return { alerts };
            }
            case 'backtest': {
                const backtest = await (0, client_1.httpPost)('/backtest/run?days=120', undefined, 120_000).catch(() => null);
                return { backtest };
            }
            case 'dailybrief': {
                try {
                    const brief = await (0, client_1.httpGet)('/dailybrief/latest', DAILY_BRIEF_TIMEOUT_MS);
                    if (!brief || typeof brief !== 'object') {
                        return {
                            pageError: '每日简报接口返回空结果',
                            pageErrorKind: 'empty',
                        };
                    }
                    return { brief };
                }
                catch (error) {
                    return requestErrorData(error, '每日简报');
                }
            }
            case 'newsradar': {
                const newsData = await (0, client_1.httpGet)('/newsradar/latest').catch(() => null);
                return newsData || { news: [], updated_at: '' };
            }
            case 'reports': {
                const mode = extraData?.mode || 'search';
                if (mode === 'my') {
                    const myReports = await (0, client_1.httpGet)('/myreports').catch(() => null);
                    return { mode: 'my', my_reports: myReports?.reports || [], _meta: myReports?._meta || {} };
                }
                else {
                    const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                    if (stockCode) {
                        const reportsData = await (0, client_1.httpGet)(`/reports?code=${stockCode}`).catch(() => null);
                        return { mode: 'search', stock_code: stockCode, reports: reportsData?.reports || [], count: reportsData?.count || 0, _meta: reportsData?._meta || {} };
                    }
                    return { mode: 'search', stock_code: '', reports: [], count: 0 };
                }
            }
            case 'announcements': {
                const mode = extraData?.mode || 'search';
                if (mode === 'search') {
                    const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                    if (stockCode) {
                        const annData = await (0, client_1.httpGet)(`/announcements?code=${stockCode}`).catch(() => null);
                        return { mode: 'search', stock_code: stockCode, announcements: annData?.announcements || [], count: annData?.count || 0, _meta: annData?._meta || {} };
                    }
                    return { mode: 'search', stock_code: '', announcements: [], count: 0 };
                }
                else {
                    const latestData = await (0, client_1.httpGet)('/announcements/latest?limit=50').catch(() => null);
                    return { mode: 'latest', announcements: latestData?.announcements || [], _meta: latestData?._meta || {} };
                }
            }
            case 'financials': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const financialsData = await (0, client_1.httpGet)(`/financials?code=${stockCode}`).catch(() => null);
                    return { stock_code: stockCode, financials: financialsData?.data || {}, _meta: financialsData?._meta || {} };
                }
                return { stock_code: '', financials: {} };
            }
            case 'valuation': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const valuationData = await (0, client_1.httpGet)(`/valuation?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, valuation: valuationData?.data || {}, _meta: valuationData?._meta || {} };
                }
                return { code: '', valuation: {} };
            }
            case 'fundflow': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const fundflowData = await (0, client_1.httpGet)(`/fundflow?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, fundflow: fundflowData?.data || {}, _meta: fundflowData?._meta || {} };
                }
                return { code: '', fundflow: {} };
            }
            case 'dragon_tiger': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const dragonTigerData = await (0, client_1.httpGet)(`/dragon-tiger?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, dragon_tiger: dragonTigerData?.data || {}, _meta: dragonTigerData?._meta || {} };
                }
                return { code: '', dragon_tiger: {} };
            }
            case 'portfolio': {
                const portfolio = await (0, client_1.httpGet)('/portfolio/overview').catch(() => null);
                return { portfolio };
            }
            case 'compare': {
                const journal = await (0, client_1.httpGet)('/trust/journal?limit=2').catch(() => null);
                const codes = (journal?.entries || []).map((e) => e.stock_code).filter(Boolean);
                const compare = codes.length >= 2 ? await (0, client_1.httpPost)('/compare', { codes }).catch(() => null) : null;
                return compare || {};
            }
            case 'timeline': {
                const requestedCode = String(extraData?.code || '').trim();
                const code = requestedCode
                    ? normalizeCode(requestedCode)
                    : await resolveDefaultStockCode();
                if (!code) {
                    return {
                        timeline: { stock_code: requestedCode.toUpperCase(), entries: [] },
                        timelineError: requestedCode
                            ? '股票代码格式无效，请输入6位代码，可选 .SH、.SZ 或 .BJ 后缀'
                            : '暂无可展示的股票，请先添加自选股或完成一次 AI 分析',
                    };
                }
                try {
                    const timeline = await (0, client_1.httpGet)(`/timeline/${encodeURIComponent(code)}?days=30`, 8_000);
                    return { timeline };
                }
                catch (error) {
                    console.warn(`Timeline request failed for ${code}`, error);
                    return {
                        timeline: { stock_code: code, entries: [] },
                        timelineError: '后端在 8 秒内未返回或接口暂不可用',
                    };
                }
            }
            default: return {};
        }
    }
    catch (error) {
        console.warn(`Failed to fetch AIIP page data: ${page}`, error);
        return { pageError: '页面数据接口暂不可用，历史数据未删除，请稍后重试' };
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
        case 'newsradar': return (0, newsradar_1.buildNewsRadarPage)(data);
        case 'reports': return (0, reports_1.buildReportsPage)(data);
        case 'announcements': return (0, announcements_1.buildAnnouncementsPage)(data);
        case 'financials': return (0, financials_1.buildFinancialsPage)(data);
        case 'valuation': return (0, valuation_1.buildValuationPage)(data);
        case 'fundflow': return (0, fundflow_1.buildFundflowPage)(data);
        case 'dragon_tiger': return (0, dragon_tiger_1.buildDragonTigerPage)(data);
        case 'portfolio': return (0, portfolio_1.buildPortfolioPage)(data);
        case 'journal': return (0, journal_1.buildJournalPage)(data);
        case 'resume': return (0, resume_1.buildResumePage)(data);
        case 'profile': return (0, profile_1.buildProfilePage)(data);
        case 'aios': return (0, aios_1.buildAIOSPage)(data);
        case 'taskmonitor': return (0, taskmonitor_1.buildTaskMonitorPage)(data);
        case 'replay': return (0, replay_1.buildReplayPage)(data);
        case 'health': return (0, health_1.buildHealthPage)(data);
        case 'connectors': return (0, connectors_1.buildConnectorsPage)(data);
        case 'decisions': return (0, decisions_1.buildDecisionsPage)(data);
        case 'compare': return (0, compare_1.buildComparePage)(data);
        case 'timeline': return (0, timeline_1.buildTimelinePage)(data);
        case 'review_lab': return (0, review_lab_1.buildReviewLabPage)(data);
        default: return (0, layout_1.pageShell)('dashboard', 'Adaptive Investment Intelligence', '<div class="empty-state"><div class="icon">🤖</div><h2>Adaptive Investment Intelligence</h2><p>选择一个页面开始</p></div>');
    }
}
function handleMessage(msg, currentPage) {
    switch (msg.command) {
        case 'navigate': {
            const extraData = msg.extraData ?? (msg.code ? { code: msg.code } : undefined);
            void showTerminal(msg.page, extraData);
            break;
        }
        case 'addWatch':
            addToWatchlist().then(() => showTerminal('watchlist'));
            break;
        case 'removeWatch':
            removeFromWatchlist(msg.code).then(() => showTerminal('watchlist'));
            break;
        case 'analyze':
            showStockResearchDirect(msg.code);
            break;
        case 'compare':
            showTerminal('compare');
            break;
        case 'timeline':
            void showTerminal('timeline', { code: msg.code });
            break;
        case 'switchReportsTab':
            showTerminal('reports', { mode: msg.mode });
            break;
        case 'searchReports':
            showTerminal('reports', { mode: 'search', stock_code: msg.code });
            break;
        case 'saveReport':
            handleSaveReport(msg.rid, msg.code, msg.title);
            break;
        case 'downloadReport':
            handleDownloadReport(msg.rid);
            break;
        case 'searchAnnouncements':
            showTerminal('announcements', { mode: 'search', stock_code: msg.code });
            break;
        case 'showLatestAnnouncements':
            showTerminal('announcements', { mode: 'latest' });
            break;
        case 'searchFinancials':
            showTerminal('financials', { stock_code: msg.code });
            break;
        case 'searchValuation':
            showTerminal('valuation', { stock_code: msg.code });
            break;
        case 'searchFundflow':
            showTerminal('fundflow', { stock_code: msg.code });
            break;
        case 'searchDragonTiger':
            showTerminal('dragon_tiger', { stock_code: msg.code });
            break;
        case 'refreshPage':
            void forceRefreshPage(currentPage, activePageExtraData, msg.soft !== true);
            break;
        case 'refreshNews':
            void refreshNewsRadar();
            break;
        case 'refreshBrief':
            void regenerateDailyBrief();
            break;
        case 'openExternal':
            void openExternalUrl(msg.url);
            break;
        case 'executeTask':
            void executeTaskManually(msg.taskName);
            break;
        case 'reviewLabHistory':
            void showTerminal('review_lab', { runId: msg.runId });
            break;
    }
}
async function executeTaskManually(taskName) {
    const result = await (0, client_1.httpPost)(`/tasks/execute/${encodeURIComponent(taskName)}`).catch(() => null);
    invalidatePageCache('taskmonitor', 'aios', 'dashboard', 'dailybrief', 'decisions');
    if (!result || result.error || result.status === 'failed') {
        const reason = result?.error || '任务请求失败';
        vscode.window.showWarningMessage(`${taskName}: ${reason}`);
    }
    else {
        vscode.window.showInformationMessage(`${taskName} 执行成功`);
    }
    await showTerminal('taskmonitor');
}
async function refreshNewsRadar() {
    const refreshed = await (0, client_1.httpPost)('/newsradar/refresh').catch(() => null);
    const version = ++navigationVersion;
    const data = refreshed || { news: [], updated_at: '', _meta: { available: false, error: '刷新请求失败' } };
    pageCache.set(getPageCacheKey('newsradar'), { data, fetchedAt: Date.now() });
    renderTerminalPage('newsradar', data, version);
}
async function regenerateDailyBrief() {
    const version = ++navigationVersion;
    const cacheKey = getPageCacheKey('dailybrief');
    const cached = pageCache.get(cacheKey);
    let data;
    try {
        const brief = await (0, client_1.httpPost)('/dailybrief/generate', undefined, DAILY_BRIEF_TIMEOUT_MS);
        data = brief && typeof brief === 'object'
            ? { brief }
            : { pageError: '每日简报生成接口返回空结果', pageErrorKind: 'empty' };
    }
    catch (error) {
        data = requestErrorData(error, '每日简报生成');
    }
    const entry = (0, page_cache_1.cachePageResult)(cached, data, Date.now());
    pageCache.set(cacheKey, entry);
    if (!(0, page_cache_1.isPageDataError)(data))
        invalidatePageCache('dashboard');
    renderTerminalPage('dailybrief', entry.data, version);
}
async function openExternalUrl(rawUrl) {
    try {
        const uri = vscode.Uri.parse(rawUrl);
        if (uri.scheme !== 'http' && uri.scheme !== 'https')
            throw new Error('unsupported scheme');
        await vscode.env.openExternal(uri);
    }
    catch {
        vscode.window.showWarningMessage('无法打开该链接');
    }
}
async function forceRefreshPage(page, extraData, force = true) {
    const version = ++navigationVersion;
    const cacheKey = getPageCacheKey(page, extraData);
    const cached = pageCache.get(cacheKey);
    await refreshPageData(page, extraData, cacheKey, version, force);
    if (cached?.data && pageCache.get(cacheKey)?.data?.pageError) {
        vscode.window.showWarningMessage(`${(0, layout_1.getPageTitle)(page)} 刷新失败，已保留上次数据`);
    }
}
async function handleSaveReport(rid, code, title) {
    try {
        const result = await (0, client_1.httpPost)('/myreports', { rid, code, title });
        if (result?.success) {
            vscode.window.showInformationMessage(`研报已收藏: ${title}`);
            invalidatePageCache('reports');
        }
        else {
            vscode.window.showErrorMessage('收藏研报失败');
        }
    }
    catch (error) {
        vscode.window.showErrorMessage('收藏研报失败');
    }
}
async function handleDownloadReport(rid) {
    try {
        const result = await (0, client_1.httpGet)(`/myreports/file/${rid}`);
        if (result?.url) {
            vscode.env.openExternal(vscode.Uri.parse(result.url));
        }
        else {
            vscode.window.showErrorMessage('获取研报下载链接失败');
        }
    }
    catch (error) {
        vscode.window.showErrorMessage('获取研报下载链接失败');
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
function normalizeCode(input) {
    const t = input.trim().toUpperCase().replace(/\s/g, '');
    if (/^\d{6}\.(SH|SZ|BJ)$/.test(t))
        return t; // 已规范
    const m = t.match(/^(\d{6})$/); // 纯6位 → 按前缀补市场后缀
    if (!m)
        return null;
    const c = m[1];
    if (c.startsWith('6') || c.startsWith('9') || c.startsWith('5'))
        return `${c}.SH`;
    if (c.startsWith('8') || c.startsWith('4'))
        return `${c}.BJ`;
    return `${c}.SZ`; // 0/1/2/3 → 深市
}
async function addToWatchlist() {
    const raw = await vscode.window.showInputBox({ prompt: '添加自选股(6位代码或 000001.SZ)', placeHolder: '000001.SZ' });
    if (!raw)
        return;
    const code = normalizeCode(raw);
    if (!code) {
        vscode.window.showWarningMessage(`无效代码: ${raw} (需6位数字)`);
        return;
    }
    if (!watchlist.includes(code)) {
        watchlist.push(code);
    }
    invalidatePageCache('dashboard', 'watchlist');
    if (extensionContext) {
        extensionContext.globalState.update('watchlist', watchlist);
    }
    vscode.window.showInformationMessage(`${code} 已添加到自选`);
}
async function removeFromWatchlist(code) {
    watchlist = watchlist.filter(c => c !== code);
    invalidatePageCache('dashboard', 'watchlist');
    if (extensionContext) {
        extensionContext.globalState.update('watchlist', watchlist);
    }
    vscode.window.showInformationMessage(`${code} 已从自选移除`);
}
// ============================================================
// ALERT INTELLIGENCE — Proactive notifications
// ============================================================
let lastAlertIds = new Set();
let seenTaskFailureIds = new Set();
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
    if (lastAlertIds.size > 200) {
        lastAlertIds = new Set(Array.from(lastAlertIds).slice(-200));
    }
    void extensionContext?.globalState.update('seenAlertIds', Array.from(lastAlertIds));
}
function startAlertPolling() {
    if (alertPollInterval)
        return;
    lastAlertIds = new Set(extensionContext?.globalState.get('seenAlertIds', []) || []);
    seenTaskFailureIds = new Set(extensionContext?.globalState.get('seenTaskFailures', []) || []);
    void pollProactiveAlerts();
    alertPollInterval = setInterval(pollProactiveAlerts, 120000); // Every 2 minutes
}
async function pollProactiveAlerts() {
    const [alertsData, taskFailures] = await Promise.all([
        (0, client_1.httpGet)('/alerts/today').catch(() => null),
        (0, client_1.httpGet)('/tasks/failures?hours=24').catch(() => null),
    ]);
    checkUrgentAlerts(alertsData);
    for (const failure of taskFailures?.failures || []) {
        if (seenTaskFailureIds.has(failure.id))
            continue;
        seenTaskFailureIds.add(failure.id);
        const message = `🔴 [关键任务失败] ${failure.task_name}: ${failure.error || failure.status}`;
        void vscode.window.showErrorMessage(message, '查看任务监控', '忽略').then(choice => {
            if (choice === '查看任务监控')
                void showTerminal('taskmonitor');
        });
    }
    if (seenTaskFailureIds.size > 200) {
        seenTaskFailureIds = new Set(Array.from(seenTaskFailureIds).slice(-200));
    }
    void extensionContext?.globalState.update('seenTaskFailures', Array.from(seenTaskFailureIds));
}
function stopAlertPolling() {
    if (alertPollInterval) {
        clearInterval(alertPollInterval);
        alertPollInterval = null;
    }
}
//# sourceMappingURL=extension.js.map