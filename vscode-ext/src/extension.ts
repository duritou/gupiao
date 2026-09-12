import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { ADAPTIVE_API_HOST, ADAPTIVE_API_PORT, BASE_URL } from './constants';
import { httpGet, httpPost, healthCheck, sleep, releaseCompatibility, frontendRelease } from './api/client';
import { cachePageResult, isPageDataError, PAGE_RETRY_COOLDOWN_MS, PageCacheEntry } from './page-cache';

import { createOrShowPanel, getPageTitle, pageShell, buildNav } from './webview/layout';
import { TerminalNavProvider, StatusProvider } from './sidebar/providers';
import { buildDashboardPage } from './pages/dashboard';
import { buildWatchlistPage } from './pages/watchlist';
import { buildResearchPage } from './pages/research';
import { buildMarketMapPage } from './pages/marketmap';
import { buildAlertsPage } from './pages/alerts';
import { buildBacktestPage } from './pages/backtest';
import { buildDailyBriefPage } from './pages/dailybrief';
import { buildNewsRadarPage } from './pages/newsradar';
import { buildReportsPage } from './pages/reports';
import { buildAnnouncementsPage } from './pages/announcements';
import { buildFinancialsPage } from './pages/financials';
import { buildValuationPage } from './pages/valuation';
import { buildFundflowPage } from './pages/fundflow';
import { buildDragonTigerPage } from './pages/dragon_tiger';
import { buildComparePage } from './pages/compare';
import { buildTimelinePage } from './pages/timeline';
import { buildPortfolioPage } from './pages/portfolio';
import { buildJournalPage } from './pages/journal';
import { buildResumePage } from './pages/resume';
import { buildProfilePage } from './pages/profile';
import { buildAIOSPage } from './pages/aios';
import { buildTaskMonitorPage } from './pages/taskmonitor';
import { buildReplayPage } from './pages/replay';
import { buildHealthPage } from './pages/health';
import { buildConnectorsPage } from './pages/connectors';
import { buildDecisionsPage } from './pages/decisions';

let serverProcess: cp.ChildProcess | null = null;
let serverRestartTimer: NodeJS.Timeout | null = null;
let serverRestartAttempts = 0;
let stoppingServer = false;
let isDeactivating = false;
let statusBar: vscode.StatusBarItem;
let statusProvider: StatusProvider | null = null;
let watchlist: string[] = [];
let extensionContext: vscode.ExtensionContext | null = null;
const pageCache = new Map<string, PageCacheEntry>();
let navigationVersion = 0;
let activePageExtraData: any = undefined;
let backendPathPromptShown = false;
const BACKEND_PATH_KEY = 'adaptiveInvestment.backendPath';

const PAGE_CACHE_TTL_MS: Record<string, number> = {
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
};
const DAILY_BRIEF_TIMEOUT_MS = 10_000;

// ============================================================
// ACTIVATION
// ============================================================
export function activate(context: vscode.ExtensionContext) {
    console.log('Adaptive Investment Intelligence Platform activated');
    isDeactivating = false;
    extensionContext = context;
    watchlist = context.globalState.get('watchlist', []);
    // 规范化已有代码(老数据可能无后缀如 000725, 后端只认 .SZ/.SH)
    const normalized = watchlist.map(normalizeCode).filter((c): c is string => c !== null);
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
            const state = await releaseCompatibility();
            releaseBar.text = state.matches
                ? `$(verified) v${frontendRelease.product_version}` : '$(warning) 版本不一致';
            releaseBar.tooltip = state.message;
        } catch {
            releaseBar.text = '$(warning) 版本待核验';
            releaseBar.tooltip = '后端不可达，尚不能确认前后端版本一致';
        }
        releaseBar.show();
    };
    void refreshRelease();
    const releaseTimer = setInterval(() => { void refreshRelease(); }, 30_000);
    context.subscriptions.push(releaseBar, { dispose: () => clearInterval(releaseTimer) });

    context.subscriptions.push(
        vscode.commands.registerCommand('quantai.terminal', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.dashboard', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.watchlist', () => showTerminal('watchlist')),
        vscode.commands.registerCommand('quantai.research', () => showStockResearch()),
        vscode.commands.registerCommand('quantai.marketmap', () => showTerminal('marketmap')),
        vscode.commands.registerCommand('quantai.alerts', () => showTerminal('alerts')),
        vscode.commands.registerCommand('quantai.backtest', () => showTerminal('backtest')),
        vscode.commands.registerCommand('quantai.dailybrief', () => showTerminal('dailybrief')),
        vscode.commands.registerCommand('quantai.newsradar', () => showTerminal('newsradar')),
        vscode.commands.registerCommand('quantai.reports', () => showTerminal('reports')),
        vscode.commands.registerCommand('quantai.announcements', () => showTerminal('announcements')),
        vscode.commands.registerCommand('quantai.financials', () => showTerminal('financials')),
        vscode.commands.registerCommand('quantai.valuation', () => showTerminal('valuation')),
        vscode.commands.registerCommand('quantai.fundflow', () => showTerminal('fundflow')),
        vscode.commands.registerCommand('quantai.dragonTiger', () => showTerminal('dragon_tiger')),
        vscode.commands.registerCommand('quantai.compare', () => showTerminal('compare')),
        vscode.commands.registerCommand('quantai.timeline', () => showTerminal('timeline')),
        vscode.commands.registerCommand('quantai.portfolio', () => showTerminal('portfolio')),
        vscode.commands.registerCommand('quantai.journal', () => showTerminal('journal')),
        vscode.commands.registerCommand('quantai.resume', () => showTerminal('resume')),
        vscode.commands.registerCommand('quantai.profile', () => showTerminal('profile')),
        vscode.commands.registerCommand('quantai.aios', () => showTerminal('aios')),
        vscode.commands.registerCommand('quantai.taskmonitor', () => showTerminal('taskmonitor')),
        vscode.commands.registerCommand('quantai.replay', () => showTerminal('replay')),
        vscode.commands.registerCommand('quantai.health', () => showTerminal('health')),
        vscode.commands.registerCommand('quantai.connectors', () => showTerminal('connectors')),
        vscode.commands.registerCommand('quantai.decisions', () => showTerminal('decisions')),
        vscode.commands.registerCommand('quantai.startServer', startServer),
        vscode.commands.registerCommand('quantai.stopServer', stopServer),
        vscode.commands.registerCommand('quantai.restartServer', restartServer),
        vscode.commands.registerCommand('quantai.configureBackend', configureBackend),
        vscode.commands.registerCommand('quantai.addWatch', addToWatchlist),
        vscode.commands.registerCommand('quantai.scan', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.analyze', () => showStockResearch()),
        vscode.commands.registerCommand('quantai.knowledge', () => showTerminal('dashboard')),
        vscode.commands.registerCommand('quantai.status', async () => {
            const ok = await backendIsOnline();
            vscode.window.showInformationMessage(ok ? 'AIIP: 后端运行中' : 'AIIP: 后端未启动');
        }),
    );

    vscode.window.registerTreeDataProvider('quantai-actions', new TerminalNavProvider());
    statusProvider = new StatusProvider();
    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('quantai-status', statusProvider),
        statusProvider,
    );

    checkAndStartServer();
}

export function deactivate() {
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
    const configuredRoot = extensionContext?.globalState.get<string>(BACKEND_PATH_KEY) || '';
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
            const action = await vscode.window.showWarningMessage(
                'AIIP 未找到 Python 后端目录，数据与 AI 功能无法启动。',
                '选择后端目录',
            );
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
        const child = cp.spawn(launch.command, launch.args, {
            cwd: root, shell: launch.shell, windowsHide: true, stdio: 'pipe',
        });
        serverProcess = child;
        child.stdout?.on('data', chunk => console.log(`[AIIP backend] ${String(chunk).trimEnd()}`));
        child.stderr?.on('data', chunk => console.error(`[AIIP backend] ${String(chunk).trimEnd()}`));
        child.once('error', error => {
            console.error('AIIP backend failed to start', error);
            if (serverProcess === child) serverProcess = null;
            statusBar.text = '$(error) AIIP';
            statusProvider?.refresh();
            scheduleServerRestart();
        });
        child.once('exit', (code, signal) => {
            if (serverProcess === child) serverProcess = null;
            console.log(`AIIP backend exited (code=${code}, signal=${signal})`);
            if (stoppingServer || isDeactivating) return;
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
        await sleep(1000);
        if (await healthCheck()) {
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

async function backendIsOnline(): Promise<boolean> {
    if (await healthCheck()) return true;
    // A service restart or Windows Defender scan can delay one probe. Confirm
    // the state before starting a second process or showing "not started".
    await sleep(250);
    return healthCheck();
}

function isBackendRoot(candidate: string): boolean {
    return fs.existsSync(path.join(candidate, 'pyproject.toml'))
        && fs.existsSync(path.join(candidate, 'src', 'api', 'app.py'));
}

function findBackendRoot(seeds: string[]): string | null {
    const queue: Array<{ directory: string; depth: number }> = [];
    const visited = new Set<string>();
    for (const seed of seeds) {
        if (!fs.existsSync(seed)) continue;
        queue.push({ directory: path.resolve(seed), depth: 0 });
    }
    const ignored = new Set(['.git', '.venv', 'node_modules', 'out', '__pycache__']);
    while (queue.length > 0 && visited.size < 300) {
        const current = queue.shift()!;
        const directory = path.resolve(current.directory);
        if (visited.has(directory)) continue;
        visited.add(directory);
        if (isBackendRoot(directory)) return directory;
        if (current.depth >= 2) continue;
        let entries: fs.Dirent[] = [];
        try {
            entries = fs.readdirSync(directory, { withFileTypes: true });
        } catch {
            continue;
        }
        for (const entry of entries) {
            if (!entry.isDirectory() || ignored.has(entry.name)) continue;
            queue.push({ directory: path.join(directory, entry.name), depth: current.depth + 1 });
        }
    }
    return null;
}

function getBackendLaunchSpec(root: string): {
    command: string;
    args: string[];
    shell: boolean;
} {
    const venvPython = process.platform === 'win32'
        ? path.join(root, '.venv', 'Scripts', 'python.exe')
        : path.join(root, '.venv', 'bin', 'python');
    if (fs.existsSync(venvPython)) {
        return {
            command: venvPython,
            args: [
                '-m', 'uvicorn', 'src.api.app:app',
                '--host', ADAPTIVE_API_HOST,
                '--port', String(ADAPTIVE_API_PORT),
            ],
            shell: false,
        };
    }
    return {
        command: 'poetry',
        args: [
            'run', 'uvicorn', 'src.api.app:app',
            '--host', ADAPTIVE_API_HOST,
            '--port', String(ADAPTIVE_API_PORT),
        ],
        shell: true,
    };
}

async function configureBackend(): Promise<boolean> {
    const selected = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: '选择 Adaptive Investment 后端目录',
    });
    const root = selected?.[0]?.fsPath;
    if (!root) return false;
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
    if (!child || child.exitCode !== null) return;
    if (process.platform === 'win32' && child.pid) {
        cp.spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
            windowsHide: true,
            stdio: 'ignore',
        });
    } else {
        child.kill();
    }
}

function scheduleServerRestart() {
    if (isDeactivating || stoppingServer || serverRestartTimer || serverRestartAttempts >= 3) return;
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
    for (const port of [ADAPTIVE_API_PORT]) {
        try {
            const { execSync } = require('child_process');
            const out = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, { timeout: 5000, encoding: 'utf8' });
            const pid = out.trim().split(/\s+/).pop();
            if (pid) execSync(`taskkill /F /PID ${pid}`);
        } catch { /* no orphan */ }
    }
    await sleep(1000);
    stoppingServer = false;
    serverRestartAttempts = 0;
    await startServer();
}

// ============================================================
// NAVIGATION & DATA FETCHING
// ============================================================
async function showTerminal(page: string, extraData?: any) {
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
    createOrShowPanel(getPageTitle(page), pageShell(page, getPageTitle(page), loading), (msg: any) => handleMessage(msg, page));
    await refreshPageData(page, extraData, cacheKey, version);
}

function getPageCacheKey(page: string, extraData?: any): string {
    return `${page}:${JSON.stringify(extraData || {})}`;
}

async function refreshPageData(
    page: string,
    extraData: any,
    cacheKey: string,
    version: number,
    force = false,
) {
    const cached = pageCache.get(cacheKey);
    const pending = cached?.pending || fetchPageData(page, extraData, force);
    pageCache.set(cacheKey, {
        ...cached,
        data: cached?.data,
        fetchedAt: cached?.fetchedAt || 0,
        pending,
    });

    let data: any;
    try {
        data = await pending;
    } catch (error) {
        data = requestErrorData(error, '页面');
    }
    const displayData = cachePageResult(
        cached,
        data,
        Date.now(),
        PAGE_RETRY_COOLDOWN_MS,
    );
    pageCache.set(cacheKey, displayData);
    if (version === navigationVersion) {
        renderTerminalPage(page, displayData.data, version);
    }
    return displayData.data;
}

function requestErrorData(error: unknown, label: string): Record<string, string> {
    const message = error instanceof Error ? error.message : `${label}数据接口暂不可用`;
    const isTimeout = /timed out|timeout|超时|ETIMEDOUT/i.test(message);
    return {
        pageError: isTimeout ? `${label}请求超时：${message}` : `${label}请求失败：${message}`,
        pageErrorKind: isTimeout ? 'timeout' : 'request',
    };
}

function renderTerminalPage(page: string, data: any, version: number) {
    if (version !== navigationVersion) return;
    let html: string;
    try {
        html = buildPage(page, data);
    } catch (error) {
        console.error(`Failed to render AIIP page: ${page}`, error);
        html = pageShell(
            page,
            getPageTitle(page),
            `<div class="card" style="margin:24px;border-left:3px solid #f85149">
                <h3>页面渲染失败</h3>
                <p class="text-muted">数据格式异常，但其他功能仍可继续使用。</p>
                <button class="btn btn-primary" onclick="retryPage()">重试</button>
            </div>`,
            `function retryPage(){vscode.postMessage({command:'refreshPage'});}`,
        );
    }
    createOrShowPanel(getPageTitle(page), html, (msg: any) => handleMessage(msg, page));
}

function invalidatePageCache(...pages: string[]) {
    for (const key of Array.from(pageCache.keys())) {
        if (pages.some(page => key.startsWith(`${page}:`))) {
            pageCache.delete(key);
        }
    }
}

async function resolveDefaultStockCode(explicitCode?: string): Promise<string> {
    const direct = explicitCode ? normalizeCode(explicitCode) : null;
    if (direct) return direct;
    if (watchlist.length > 0) return watchlist[0];
    const journal = await httpGet('/trust/journal?limit=1').catch(() => null);
    const journalCode = journal?.entries?.[0]?.stock_code;
    return normalizeCode(journalCode || '') || '';
}

async function fetchPageData(page: string, extraData?: any, force = false): Promise<any> {
    try {
        switch (page) {
            case 'dashboard': {
                const journalForWatch = watchlist.length
                    ? null
                    : await httpGet('/trust/journal?limit=10').catch(() => null);
                const suggestedWatch = (journalForWatch?.entries || []).map((e: any) => e.stock_code).filter(Boolean);
                const watchCodes = watchlist.length ? watchlist : suggestedWatch;
                const [market, scanner, watchScores, liveQuotes, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality] = await Promise.all([
                    httpGet('/market/overview').catch(() => null),
                    httpGet('/scanner/latest?top_n=8').catch(() => null),
                    httpPost('/signals/batch', { codes: watchCodes, force }).catch(() => null),
                    httpPost('/market/quotes', { codes: watchCodes }).catch(() => null),
                    httpGet('/morning-brief/today').catch(() => null),
                    httpGet('/alerts/today').catch(() => null),
                    httpGet('/trust/track-record?days=30').catch(() => null),
                    httpGet('/trust/ai-alpha?days=90').catch(() => null),
                    httpGet('/user/profile/summary').catch(() => null),
                    httpGet('/market/data-quality').catch(() => null),
                ]);
                // Push VS Code notification for P0/P1 alerts
                checkUrgentAlerts(alerts);
                return { market, scanner, watchScores, liveQuotes, brief, alerts, trackRecord, aiAlpha, userProfile, dataQuality };
            }
            case 'journal': {
                const [journal, summary] = await Promise.all([
                    httpGet('/trust/journal?limit=100').catch(() => null),
                    httpGet('/trust/journal/summary').catch(() => null),
                ]);
                return {
                    journal,
                    summary,
                    journalError: journal ? undefined : '真实决策日志接口暂不可用',
                };
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
                const profile = await httpGet('/user/profile').catch(() => null);
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
                const results = await Promise.all(endpoints.map(async endpoint => {
                    try {
                        return { ...endpoint, data: await httpGet(endpoint.path, endpoint.timeout) };
                    } catch (error) {
                        console.warn(`AI OS ${endpoint.key} request failed`, error);
                        return { ...endpoint, data: null };
                    }
                }));
                const payload: Record<string, any> = {};
                const failed = [];
                for (const result of results) {
                    payload[result.key] = result.data;
                    if (result.data === null) failed.push(result.label);
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
                    httpGet('/tasks/status').catch(() => null),
                    httpGet('/tasks/executions/recent?limit=20').catch(() => null),
                    httpGet('/tasks/schedule').catch(() => null),
                ]);
                return { status, executions, schedule };
            }
            case 'replay': {
                const [dates, history] = await Promise.all([
                    httpGet('/replay/dates').catch(() => null),
                    httpGet('/replay/history?limit=20').catch(() => null),
                ]);
                return { dates, history };
            }
            case 'health': {
                const health = await httpGet('/market/system-health').catch(() => null);
                return { health };
            }
            case 'connectors': {
                const [dataStatus, registry] = await Promise.all([
                    httpGet('/market/data-status').catch(() => null),
                    httpGet('/market/registry').catch(() => null),
                ]);
                return { dataStatus, registry };
            }
            case 'decisions': {
                const decisions = await httpGet('/decision/today').catch(() => null);
                return { decisions };
            }
            case 'watchlist': {
                const journal = await httpGet('/trust/journal?limit=20').catch(() => null);
                const suggested = (journal?.entries || []).map((e: any) => e.stock_code).filter(Boolean);
                const stocks = watchlist.length ? watchlist : suggested;
                const [watchScores, liveQuotes] = stocks.length
                    ? await Promise.all([
                        httpPost('/signals/batch', { codes: stocks, force }).catch(() => null),
                        httpPost('/market/quotes', { codes: stocks }).catch(() => null),
                    ])
                    : [null, null];
                return { stocks, watchScores, liveQuotes };
            }
            case 'marketmap': {
                const refreshQuery = force ? '?refresh=true' : '';
                const sectors = await httpGet(`/market/sectors${refreshQuery}`, 3500).catch(() => null);
                return sectors || { sectors: [], is_live: false, data_source: 'unavailable' };
            }
            case 'alerts': {
                const alerts = await httpGet('/alerts/recent?limit=50').catch(() => null);
                return { alerts };
            }
            case 'backtest': {
                const backtest = await httpPost('/backtest/run?days=120', undefined, 120_000).catch(() => null);
                return { backtest };
            }
            case 'dailybrief': {
                try {
                    const brief = await httpGet('/dailybrief/latest', DAILY_BRIEF_TIMEOUT_MS);
                    if (!brief || typeof brief !== 'object') {
                        return {
                            pageError: '每日简报接口返回空结果',
                            pageErrorKind: 'empty',
                        };
                    }
                    return { brief };
                } catch (error) {
                    return requestErrorData(error, '每日简报');
                }
            }
            case 'newsradar': {
                const newsData = await httpGet('/newsradar/latest').catch(() => null);
                return newsData || { news: [], updated_at: '' };
            }
            case 'reports': {
                const mode = extraData?.mode || 'search';
                if (mode === 'my') {
                    const myReports = await httpGet('/myreports').catch(() => null);
                    return { mode: 'my', my_reports: myReports?.reports || [], _meta: myReports?._meta || {} };
                } else {
                    const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                    if (stockCode) {
                        const reportsData = await httpGet(`/reports?code=${stockCode}`).catch(() => null);
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
                        const annData = await httpGet(`/announcements?code=${stockCode}`).catch(() => null);
                        return { mode: 'search', stock_code: stockCode, announcements: annData?.announcements || [], count: annData?.count || 0, _meta: annData?._meta || {} };
                    }
                    return { mode: 'search', stock_code: '', announcements: [], count: 0 };
                } else {
                    const latestData = await httpGet('/announcements/latest?limit=50').catch(() => null);
                    return { mode: 'latest', announcements: latestData?.announcements || [], _meta: latestData?._meta || {} };
                }
            }
            case 'financials': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const financialsData = await httpGet(`/financials?code=${stockCode}`).catch(() => null);
                    return { stock_code: stockCode, financials: financialsData?.data || {}, _meta: financialsData?._meta || {} };
                }
                return { stock_code: '', financials: {} };
            }
            case 'valuation': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const valuationData = await httpGet(`/valuation?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, valuation: valuationData?.data || {}, _meta: valuationData?._meta || {} };
                }
                return { code: '', valuation: {} };
            }
            case 'fundflow': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const fundflowData = await httpGet(`/fundflow?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, fundflow: fundflowData?.data || {}, _meta: fundflowData?._meta || {} };
                }
                return { code: '', fundflow: {} };
            }
            case 'dragon_tiger': {
                const stockCode = await resolveDefaultStockCode(extraData?.stock_code);
                if (stockCode) {
                    const dragonTigerData = await httpGet(`/dragon-tiger?code=${stockCode}`).catch(() => null);
                    return { code: stockCode, dragon_tiger: dragonTigerData?.data || {}, _meta: dragonTigerData?._meta || {} };
                }
                return { code: '', dragon_tiger: {} };
            }
            case 'portfolio': {
                const portfolio = await httpGet('/portfolio/overview').catch(() => null);
                return { portfolio };
            }
            case 'compare': {
                const journal = await httpGet('/trust/journal?limit=2').catch(() => null);
                const codes = (journal?.entries || []).map((e: any) => e.stock_code).filter(Boolean);
                const compare = codes.length >= 2 ? await httpPost('/compare', { codes }).catch(() => null) : null;
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
                    const timeline = await httpGet(
                        `/timeline/${encodeURIComponent(code)}?days=30`,
                        8_000,
                    );
                    return { timeline };
                } catch (error) {
                    console.warn(`Timeline request failed for ${code}`, error);
                    return {
                        timeline: { stock_code: code, entries: [] },
                        timelineError: '后端在 8 秒内未返回或接口暂不可用',
                    };
                }
            }
            default: return {};
        }
    } catch (error) {
        console.warn(`Failed to fetch AIIP page data: ${page}`, error);
        return { pageError: '页面数据接口暂不可用，历史数据未删除，请稍后重试' };
    }
}

function buildPage(page: string, data: any): string {
    switch (page) {
        case 'dashboard': return buildDashboardPage(data);
        case 'watchlist': return buildWatchlistPage(data);
        case 'marketmap': return buildMarketMapPage(data);
        case 'alerts': return buildAlertsPage(data);
        case 'backtest': return buildBacktestPage(data);
        case 'dailybrief': return buildDailyBriefPage(data);
        case 'newsradar': return buildNewsRadarPage(data);
        case 'reports': return buildReportsPage(data);
        case 'announcements': return buildAnnouncementsPage(data);
        case 'financials': return buildFinancialsPage(data);
        case 'valuation': return buildValuationPage(data);
        case 'fundflow': return buildFundflowPage(data);
        case 'dragon_tiger': return buildDragonTigerPage(data);
        case 'portfolio': return buildPortfolioPage(data);
        case 'journal': return buildJournalPage(data);
        case 'resume': return buildResumePage(data);
        case 'profile': return buildProfilePage(data);
        case 'aios': return buildAIOSPage(data);
        case 'taskmonitor': return buildTaskMonitorPage(data);
        case 'replay': return buildReplayPage(data);
        case 'health': return buildHealthPage(data);
        case 'connectors': return buildConnectorsPage(data);
        case 'decisions': return buildDecisionsPage(data);
        case 'compare': return buildComparePage(data);
        case 'timeline': return buildTimelinePage(data);
        default: return pageShell('dashboard', 'Adaptive Investment Intelligence', '<div class="empty-state"><div class="icon">🤖</div><h2>Adaptive Investment Intelligence</h2><p>选择一个页面开始</p></div>');
    }
}

function handleMessage(msg: any, currentPage: string) {
    switch (msg.command) {
        case 'navigate': {
            const extraData = msg.extraData ?? (msg.code ? { code: msg.code } : undefined);
            void showTerminal(msg.page, extraData);
            break;
        }
        case 'addWatch': addToWatchlist().then(() => showTerminal('watchlist')); break;
        case 'removeWatch': removeFromWatchlist(msg.code).then(() => showTerminal('watchlist')); break;
        case 'analyze': showStockResearchDirect(msg.code); break;
        case 'compare': showTerminal('compare'); break;
        case 'timeline': void showTerminal('timeline', { code: msg.code }); break;
        case 'switchReportsTab': showTerminal('reports', { mode: msg.mode }); break;
        case 'searchReports': showTerminal('reports', { mode: 'search', stock_code: msg.code }); break;
        case 'saveReport': handleSaveReport(msg.rid, msg.code, msg.title); break;
        case 'downloadReport': handleDownloadReport(msg.rid); break;
        case 'searchAnnouncements': showTerminal('announcements', { mode: 'search', stock_code: msg.code }); break;
        case 'showLatestAnnouncements': showTerminal('announcements', { mode: 'latest' }); break;
        case 'searchFinancials': showTerminal('financials', { stock_code: msg.code }); break;
        case 'searchValuation': showTerminal('valuation', { stock_code: msg.code }); break;
        case 'searchFundflow': showTerminal('fundflow', { stock_code: msg.code }); break;
        case 'searchDragonTiger': showTerminal('dragon_tiger', { stock_code: msg.code }); break;
        case 'refreshPage':
            void forceRefreshPage(currentPage, activePageExtraData, msg.soft !== true);
            break;
        case 'refreshNews': void refreshNewsRadar(); break;
        case 'refreshBrief': void regenerateDailyBrief(); break;
        case 'openExternal': void openExternalUrl(msg.url); break;
        case 'executeTask': void executeTaskManually(msg.taskName); break;
    }
}

async function executeTaskManually(taskName: string) {
    const result = await httpPost(`/tasks/execute/${encodeURIComponent(taskName)}`).catch(() => null);
    invalidatePageCache('taskmonitor', 'aios', 'dashboard', 'dailybrief', 'decisions');
    if (!result || result.error || result.status === 'failed') {
        const reason = result?.error || '任务请求失败';
        vscode.window.showWarningMessage(`${taskName}: ${reason}`);
    } else {
        vscode.window.showInformationMessage(`${taskName} 执行成功`);
    }
    await showTerminal('taskmonitor');
}

async function refreshNewsRadar() {
    const refreshed = await httpPost('/newsradar/refresh').catch(() => null);
    const version = ++navigationVersion;
    const data = refreshed || { news: [], updated_at: '', _meta: { available: false, error: '刷新请求失败' } };
    pageCache.set(getPageCacheKey('newsradar'), { data, fetchedAt: Date.now() });
    renderTerminalPage('newsradar', data, version);
}

async function regenerateDailyBrief() {
    const version = ++navigationVersion;
    const cacheKey = getPageCacheKey('dailybrief');
    const cached = pageCache.get(cacheKey);
    let data: any;
    try {
        const brief = await httpPost('/dailybrief/generate', undefined, DAILY_BRIEF_TIMEOUT_MS);
        data = brief && typeof brief === 'object'
            ? { brief }
            : { pageError: '每日简报生成接口返回空结果', pageErrorKind: 'empty' };
    } catch (error) {
        data = requestErrorData(error, '每日简报生成');
    }
    const entry = cachePageResult(cached, data, Date.now());
    pageCache.set(cacheKey, entry);
    if (!isPageDataError(data)) invalidatePageCache('dashboard');
    renderTerminalPage('dailybrief', entry.data, version);
}

async function openExternalUrl(rawUrl: string) {
    try {
        const uri = vscode.Uri.parse(rawUrl);
        if (uri.scheme !== 'http' && uri.scheme !== 'https') throw new Error('unsupported scheme');
        await vscode.env.openExternal(uri);
    } catch {
        vscode.window.showWarningMessage('无法打开该链接');
    }
}

async function forceRefreshPage(page: string, extraData?: any, force = true) {
    const version = ++navigationVersion;
    const cacheKey = getPageCacheKey(page, extraData);
    const cached = pageCache.get(cacheKey);
    await refreshPageData(page, extraData, cacheKey, version, force);
    if (cached?.data && pageCache.get(cacheKey)?.data?.pageError) {
        vscode.window.showWarningMessage(`${getPageTitle(page)} 刷新失败，已保留上次数据`);
    }
}

async function handleSaveReport(rid: string, code: string, title: string) {
    try {
        const result = await httpPost('/myreports', { rid, code, title });
        if (result?.success) {
            vscode.window.showInformationMessage(`研报已收藏: ${title}`);
            invalidatePageCache('reports');
        } else {
            vscode.window.showErrorMessage('收藏研报失败');
        }
    } catch (error) {
        vscode.window.showErrorMessage('收藏研报失败');
    }
}

async function handleDownloadReport(rid: string) {
    try {
        const result = await httpGet(`/myreports/file/${rid}`);
        if (result?.url) {
            vscode.env.openExternal(vscode.Uri.parse(result.url));
        } else {
            vscode.window.showErrorMessage('获取研报下载链接失败');
        }
    } catch (error) {
        vscode.window.showErrorMessage('获取研报下载链接失败');
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
function normalizeCode(input: string): string | null {
    const t = input.trim().toUpperCase().replace(/\s/g, '');
    if (/^\d{6}\.(SH|SZ|BJ)$/.test(t)) return t;        // 已规范
    const m = t.match(/^(\d{6})$/);                       // 纯6位 → 按前缀补市场后缀
    if (!m) return null;
    const c = m[1];
    if (c.startsWith('6') || c.startsWith('9') || c.startsWith('5')) return `${c}.SH`;
    if (c.startsWith('8') || c.startsWith('4')) return `${c}.BJ`;
    return `${c}.SZ`;  // 0/1/2/3 → 深市
}

async function addToWatchlist() {
    const raw = await vscode.window.showInputBox({ prompt: '添加自选股(6位代码或 000001.SZ)', placeHolder: '000001.SZ' });
    if (!raw) return;
    const code = normalizeCode(raw);
    if (!code) { vscode.window.showWarningMessage(`无效代码: ${raw} (需6位数字)`); return; }
    if (!watchlist.includes(code)) { watchlist.push(code); }
    invalidatePageCache('dashboard', 'watchlist');
    if (extensionContext) {
        extensionContext.globalState.update('watchlist', watchlist);
    }
    vscode.window.showInformationMessage(`${code} 已添加到自选`);
}

async function removeFromWatchlist(code: string) {
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
let lastAlertIds: Set<string> = new Set();
let seenTaskFailureIds: Set<string> = new Set();
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
    if (lastAlertIds.size > 200) {
        lastAlertIds = new Set(Array.from(lastAlertIds).slice(-200));
    }
    void extensionContext?.globalState.update('seenAlertIds', Array.from(lastAlertIds));
}

function startAlertPolling() {
    if (alertPollInterval) return;
    lastAlertIds = new Set(extensionContext?.globalState.get<string[]>('seenAlertIds', []) || []);
    seenTaskFailureIds = new Set(extensionContext?.globalState.get<string[]>('seenTaskFailures', []) || []);
    void pollProactiveAlerts();
    alertPollInterval = setInterval(pollProactiveAlerts, 120000); // Every 2 minutes
}

async function pollProactiveAlerts() {
    const [alertsData, taskFailures] = await Promise.all([
        httpGet('/alerts/today').catch(() => null),
        httpGet('/tasks/failures?hours=24').catch(() => null),
    ]);
    checkUrgentAlerts(alertsData);
    for (const failure of taskFailures?.failures || []) {
        if (seenTaskFailureIds.has(failure.id)) continue;
        seenTaskFailureIds.add(failure.id);
        const message = `🔴 [关键任务失败] ${failure.task_name}: ${failure.error || failure.status}`;
        void vscode.window.showErrorMessage(message, '查看任务监控', '忽略').then(choice => {
            if (choice === '查看任务监控') void showTerminal('taskmonitor');
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
