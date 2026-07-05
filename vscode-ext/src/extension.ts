import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as http from 'http';

const BASE_URL = 'http://127.0.0.1:8888/api/v1';
let serverProcess: cp.ChildProcess | null = null;
let statusBar: vscode.StatusBarItem;

// ============================================================
// ACTIVATION
// ============================================================

export function activate(context: vscode.ExtensionContext) {
    console.log('AI Research Terminal activated');

    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(circle-outline) AI Research';
    statusBar.command = 'quantai.status';
    statusBar.show();
    context.subscriptions.push(statusBar);

    // 注册所有命令
    context.subscriptions.push(
        vscode.commands.registerCommand('quantai.startServer', startServer),
        vscode.commands.registerCommand('quantai.stopServer', stopServer),
        vscode.commands.registerCommand('quantai.scan', () => runScanner(context)),
        vscode.commands.registerCommand('quantai.analyze', () => analyzeStock(context)),
        vscode.commands.registerCommand('quantai.research', () => runResearch(context)),
        vscode.commands.registerCommand('quantai.backtest', () => runBacktest(context)),
        vscode.commands.registerCommand('quantai.knowledge', () => searchKnowledge(context)),
        vscode.commands.registerCommand('quantai.status', showStatus),
    );

    // 注册侧边栏
    const actionsProvider = new ActionsProvider();
    vscode.window.registerTreeDataProvider('quantai-actions', actionsProvider);
    const statusProvider = new StatusProvider();
    vscode.window.registerTreeDataProvider('quantai-status', statusProvider);

    // 自动检查后端
    checkAndStartServer();
}

export function deactivate() {
    stopServer();
}

// ============================================================
// SERVER MANAGEMENT
// ============================================================

async function checkAndStartServer() {
    const ok = await healthCheck();
    if (ok) {
        statusBar.text = '$(check) AI Research';
        statusBar.tooltip = '后端服务运行中';
        return;
    }
    vscode.window.showInformationMessage('后端未运行，正在启动 Python 服务...');
    await startServer();
}

async function startServer() {
    if (serverProcess) { return; }
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
        vscode.window.showErrorMessage('未找到工作区');
        return;
    }

    statusBar.text = '$(sync~spin) AI Research 启动中...';
    serverProcess = cp.spawn('poetry', ['run', 'uvicorn', 'src.api.app:app', '--host', '127.0.0.1', '--port', '8888'], {
        cwd: workspaceRoot,
        shell: true,
        stdio: 'pipe',
    });

    serverProcess.stdout?.on('data', (d: Buffer) => console.log(d.toString()));
    serverProcess.stderr?.on('data', (d: Buffer) => console.error(d.toString()));

    // 等待启动
    for (let i = 0; i < 15; i++) {
        await sleep(1000);
        if (await healthCheck()) {
            statusBar.text = '$(check) AI Research';
            statusBar.tooltip = '后端服务运行中';
            vscode.window.showInformationMessage('AI Research Terminal 后端已就绪');
            return;
        }
    }
    statusBar.text = '$(error) AI Research';
    vscode.window.showErrorMessage('后端启动超时');
}

function stopServer() {
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = null;
    }
    statusBar.text = '$(circle-outline) AI Research';
}

// ============================================================
// HTTP HELPERS
// ============================================================

function httpGet(url: string): Promise<any> {
    return new Promise((resolve, reject) => {
        http.get(url, (res) => {
            let data = '';
            res.on('data', (chunk: string) => data += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve(data); }
            });
        }).on('error', reject);
    });
}

function httpPost(url: string): Promise<any> {
    return new Promise((resolve, reject) => {
        const req = http.request(url, { method: 'POST' }, (res) => {
            let data = '';
            res.on('data', (chunk: string) => data += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve(data); }
            });
        });
        req.on('error', reject);
        req.end();
    });
}

async function healthCheck(): Promise<boolean> {
    try {
        await httpGet(`${BASE_URL}/system/health`);
        return true;
    } catch { return false; }
}

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

// ============================================================
// COMMANDS
// ============================================================

async function runScanner(context: vscode.ExtensionContext) {
    const poolSize = await vscode.window.showInputBox({ prompt: '股票池大小', value: '30' });
    if (!poolSize) { return; }
    const topN = await vscode.window.showInputBox({ prompt: '返回 Top N', value: '5' });
    if (!topN) { return; }

    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: '正在扫描全市场...' }, async () => {
        const data = await httpPost(`${BASE_URL}/scanner/run?pool_size=${poolSize}&top_n=${topN}`);
        showWebview(context, 'Scanner Results', formatScanResult(data));
    });
}

async function analyzeStock(context: vscode.ExtensionContext) {
    const code = await vscode.window.showInputBox({ prompt: '股票代码', value: '000001.SZ', placeHolder: '如 000001.SZ, 600519.SH' });
    if (!code) { return; }

    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `正在分析 ${code}...` }, async () => {
        const data = await httpGet(`${BASE_URL}/signals/compute/${code}?trend=up`);
        showWebview(context, `${code} 信号分析`, formatSignalResult(data));
    });
}

async function runResearch(context: vscode.ExtensionContext) {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: '正在运行研究管线...' }, async () => {
        const data = await httpPost(`${BASE_URL}/research/run?pool_size=20&top_n=5&mode=pipeline`);
        showWebview(context, 'AI 研究报告', data.final_report || formatResearchResult(data));
    });
}

async function runBacktest(context: vscode.ExtensionContext) {
    const trend = await vscode.window.showQuickPick(['up', 'down'], { placeHolder: '选择回测趋势' });
    if (!trend) { return; }

    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: '正在运行回测...' }, async () => {
        const data = await httpPost(`${BASE_URL}/backtest/run?trend=${trend}&days=120`);
        showWebview(context, '回测结果', formatBacktestResult(data));
    });
}

async function searchKnowledge(context: vscode.ExtensionContext) {
    const query = await vscode.window.showInputBox({ prompt: '搜索知识库', placeHolder: '如 半导体, 银行, 货币政策' });
    if (!query) { return; }

    const data = await httpGet(`${BASE_URL}/knowledge/search?q=${encodeURIComponent(query)}`);
    showWebview(context, `知识库: ${query}`, formatKnowledgeResult(data));
}

async function showStatus() {
    try {
        const data = await httpGet(`${BASE_URL}/system/status`);
        vscode.window.showInformationMessage(
            `AI Research Terminal v${data.version} — ${(data.modules as string[]).length} 模块就绪`,
            '查看详情'
        ).then(sel => {
            if (sel === '查看详情') {
                const panel = vscode.window.createWebviewPanel('quantaiStatus', '系统状态',
                    vscode.ViewColumn.One, { enableScripts: true });
                panel.webview.html = `<html><body style="padding:20px;font-family:monospace">
                    <h2>AI Research Terminal</h2>
                    <p>Version: ${data.version}</p><h3>Modules:</h3><ul>
                    ${(data.modules as string[]).map((m: string) => `<li>${m}</li>`).join('')}</ul></body></html>`;
            }
        });
    } catch {
        vscode.window.showErrorMessage('后端服务未运行，请先启动服务');
    }
}

// ============================================================
// WEBVIEW
// ============================================================

function showWebview(context: vscode.ExtensionContext, title: string, content: string) {
    const panel = vscode.window.createWebviewPanel(
        'quantaiResult', title, vscode.ViewColumn.One,
        { enableScripts: true, retainContextWhenHidden: true }
    );

    panel.webview.html = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><style>
body { font-family: var(--vscode-font-family); padding: 24px; color: var(--vscode-foreground); background: var(--vscode-editor-background); line-height: 1.7; }
h1 { color: var(--vscode-textLink-foreground); border-bottom: 2px solid var(--vscode-textLink-foreground); padding-bottom: 8px; }
h2 { color: var(--vscode-textPreformat-foreground); margin-top: 24px; }
.score-high { color: #4caf50; font-weight: bold; }
.score-mid { color: #ff9800; font-weight: bold; }
.score-low { color: #f44336; font-weight: bold; }
.tag { display: inline-block; padding: 2px 8px; margin: 2px; border-radius: 4px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); font-size: 12px; }
.card { border: 1px solid var(--vscode-panel-border); border-radius: 8px; padding: 16px; margin: 12px 0; }
pre { background: var(--vscode-textCodeBlock-background); padding: 16px; border-radius: 8px; overflow-x: auto; }
</style></head>
<body>${content}</body></html>`;
}

// ============================================================
// FORMATTERS
// ============================================================

function formatScanResult(data: any): string {
    const candidates = data.candidates || [];
    let html = `<h1>全市场扫描结果</h1>
<p>扫描 <b>${data.total_scanned}</b> 只 · 粗筛后 <b>${data.after_coarse}</b> 只 · 技术筛选后 <b>${data.after_technical}</b> 只 · 候选 <b>${data.candidates_found}</b> 只 · 耗时 ${data.duration_ms}ms</p>`;

    candidates.forEach((c: any) => {
        const scoreClass = c.fusion_score >= 70 ? 'score-high' : c.fusion_score >= 50 ? 'score-mid' : 'score-low';
        html += `<div class="card">
<h3>#${c.rank} ${c.stock_name} (${c.stock_code}) — <span class="${scoreClass}">${c.fusion_score?.toFixed(1)}分</span></h3>
<p>方向: <b>${c.direction}</b> · 置信度: ${(c.confidence * 100).toFixed(0)}%</p>
<p>${(c.tags || []).map((t: string) => `<span class="tag">${t}</span>`).join(' ')}</p>
<p>${Object.entries(c.score_breakdown || {}).map(([k, v]: [string, any]) =>
    `${k.toUpperCase()}: <b>${v?.toFixed(0)}</b>`).join(' &nbsp;|&nbsp; ')}</p>
</div>`;
    });
    return html;
}

function formatSignalResult(data: any): string {
    const sc = data.fusion_score >= 70 ? 'score-high' : data.fusion_score >= 50 ? 'score-mid' : 'score-low';
    return `<h1>${data.stock_code} 信号分析</h1>
<h2>综合评分: <span class="${sc}">${data.fusion_score?.toFixed(1)}</span></h2>
<p>方向: <b>${data.direction}</b> · 置信度: ${(data.confidence * 100).toFixed(0)}%</p>
<p>看多信号: ${data.buy_signals} · 看空信号: ${data.sell_signals}</p>
<h2>各维度评分</h2>
<div>${Object.entries(data.scores || {}).map(([k, v]: [string, any]) =>
    `<div style="margin:8px 0"><b>${k.toUpperCase()}</b>:
    <span style="display:inline-block;width:${v}px;height:16px;background:${v>=70?'#4caf50':v>=40?'#ff9800':'#f44336'};border-radius:4px;"></span> ${v?.toFixed(0)}</div>`
).join('')}</div>
<h2>信号详情</h2><ul>${(data.reasons || []).map((r: string) => `<li>${r}</li>`).join('')}</ul>`;
}

function formatResearchResult(data: any): string {
    return `<h1>${data.title || 'AI 研究报告'}</h1>
<p>${data.summary || ''}</p><p>${data.market_overview || ''}</p>
<h2>候选标的 (${data.candidates_count || 0})</h2>
${(data.candidates || []).map((c: any) => `<div class="card">
<h3>#${c.rank} ${c.stock_name} (${c.stock_code}) — ${c.score?.toFixed(1)}分</h3>
<p>方向: <b>${c.direction}</b> · 证据: ${c.evidence_count}条</p>
<p>${c.reasoning || ''}</p>
${(c.risks || []).map((r: string) => `<span class="tag" style="background:#f44336">${r}</span>`).join(' ')}
</div>`).join('')}`;
}

function formatBacktestResult(data: any): string {
    const m = data.metrics || {};
    return `<h1>回测结果</h1>
<p>周期: ${data.period} · 初始资金: ${data.initial_capital?.toLocaleString()}</p>
<h2>绩效指标</h2>
<table style="width:100%;border-collapse:collapse;">
<tr><td>总收益率</td><td><b>${m.total_return_pct?.toFixed(1)}%</b></td></tr>
<tr><td>年化收益率</td><td>${m.annual_return_pct?.toFixed(1)}%</td></tr>
<tr><td>最大回撤</td><td>${m.max_drawdown_pct?.toFixed(1)}%</td></tr>
<tr><td>夏普比率</td><td>${m.sharpe_ratio?.toFixed(2)}</td></tr>
<tr><td>胜率</td><td>${m.win_rate_pct?.toFixed(1)}%</td></tr>
<tr><td>交易次数</td><td>${m.total_trades} (赢${m.winning} 输${m.losing})</td></tr>
</table>
${(data.trades || []).length > 0 ? '<h2>交易明细</h2>' + (data.trades || []).slice(0, 10).map((t: any) =>
    `<div class="card">${t.entry} → ${t.exit} | 盈亏: <b>${t.profit_pct?.toFixed(1)}%</b> | 持有${t.holding_days}天 | ${t.exit_reason}</div>`
).join('') : '<p>无交易</p>'}`;
}

function formatKnowledgeResult(data: any): string {
    return `<h1>知识库搜索: ${data.query}</h1>
${(data.results || []).map((r: any) => `<div class="card">
<h3>${r.title} <span class="tag">${r.category}</span></h3>
<p>${r.summary || ''}</p>
<p>${(r.tags || []).map((t: string) => `<span class="tag">${t}</span>`).join(' ')}</p>
</div>`).join('')}`;
}

// ============================================================
// SIDEBAR
// ============================================================

class ActionsProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem) { return el; }
    getChildren(): vscode.TreeItem[] {
        return [
            cmdItem('$(search) 全市场扫描', 'quantai.scan'),
            cmdItem('$(graph) 分析股票', 'quantai.analyze'),
            cmdItem('$(notebook) 运行研究管线', 'quantai.research'),
            cmdItem('$(history) 运行回测', 'quantai.backtest'),
            cmdItem('$(book) 搜索知识库', 'quantai.knowledge'),
            cmdItem('$(info) 系统状态', 'quantai.status'),
        ];
    }
}

class StatusProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem) { return el; }
    async getChildren(): Promise<vscode.TreeItem[]> {
        const online = await healthCheck();
        return [
            new vscode.TreeItem(online ? '$(check) 后端服务: 运行中' : '$(circle-outline) 后端服务: 未启动'),
            new vscode.TreeItem(`$(server) API: ${BASE_URL}`),
            new vscode.TreeItem('$(folder) 数据: knowledge/'),
        ];
    }
}

function cmdItem(label: string, command: string): vscode.TreeItem {
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.command = { command, title: label };
    return item;
}
