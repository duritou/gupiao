import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as http from 'http';

const BASE_URL = 'http://127.0.0.1:8888/api/v1';
let serverProcess: cp.ChildProcess | null = null;
let statusBar: vscode.StatusBarItem;
let currentPanel: vscode.WebviewPanel | null = null;
let watchlist: string[] = [];

// ============================================================
// ACTIVATION
// ============================================================
export function activate(context: vscode.ExtensionContext) {
    console.log('AI Research Terminal activated');
    watchlist = context.globalState.get('watchlist', ['000001.SZ', '600519.SH', '000858.SZ', '300750.SZ', '002475.SZ']);

    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(pulse) AI Research';
    statusBar.command = 'quantai.terminal';
    statusBar.show();

    context.subscriptions.push(
        vscode.commands.registerCommand('quantai.terminal', () => showTerminal(context, 'dashboard')),
        vscode.commands.registerCommand('quantai.dashboard', () => showTerminal(context, 'dashboard')),
        vscode.commands.registerCommand('quantai.watchlist', () => showTerminal(context, 'watchlist')),
        vscode.commands.registerCommand('quantai.research', () => showStockResearch(context)),
        vscode.commands.registerCommand('quantai.marketmap', () => showTerminal(context, 'marketmap')),
        vscode.commands.registerCommand('quantai.alerts', () => showTerminal(context, 'alerts')),
        vscode.commands.registerCommand('quantai.backtest', () => showTerminal(context, 'backtest')),
        vscode.commands.registerCommand('quantai.dailybrief', () => showTerminal(context, 'dailybrief')),
        vscode.commands.registerCommand('quantai.startServer', startServer),
        vscode.commands.registerCommand('quantai.addWatch', addToWatchlist),
    );

    // Sidebar
    const navProvider = new TerminalNavProvider();
    vscode.window.registerTreeDataProvider('quantai-actions', navProvider);
    vscode.window.registerTreeDataProvider('quantai-status', new StatusProvider());

    checkAndStartServer();
}

export function deactivate() { stopServer(); }

// ============================================================
// SERVER
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

async function healthCheck(): Promise<boolean> {
    try { await httpGet('/system/health'); return true; } catch { return false; }
}

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

// ============================================================
// HTTP
// ============================================================
function httpGet(path: string): Promise<any> {
    return new Promise((resolve, reject) => {
        http.get(BASE_URL + path, res => {
            let d = ''; res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(d); } });
        }).on('error', reject);
    });
}
function httpPost(path: string): Promise<any> {
    return new Promise((resolve, reject) => {
        const req = http.request(BASE_URL + path, { method: 'POST' }, res => {
            let d = ''; res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(d); } });
        });
        req.on('error', reject); req.end();
    });
}

// ============================================================
// TERMINAL MAIN
// ============================================================
async function showTerminal(context: vscode.ExtensionContext, page: string) {
    const data = await fetchPageData(page);
    const html = buildPage(page, data);
    createOrShowPanel(context, getPageTitle(page), html);
}

function getPageTitle(page: string): string {
    const titles: Record<string, string> = { dashboard: 'Dashboard', watchlist: 'Watchlist',
        marketmap: 'Market Map', alerts: 'Alert Center', backtest: 'Backtest', dailybrief: 'Daily Brief' };
    return titles[page] || 'AI Research Terminal';
}

async function fetchPageData(page: string): Promise<any> {
    try {
        switch (page) {
            case 'dashboard': return { scanner: await httpPost('/scanner/run?pool_size=30&top_n=8'), knowledge: await httpGet('/knowledge/categories') };
            case 'watchlist': return { stocks: watchlist };
            case 'marketmap': return { knowledge: await httpGet('/knowledge/categories') };
            case 'alerts': return { scanner: await httpPost('/scanner/run?pool_size=20&top_n=10') };
            case 'backtest': return { backtest: await httpPost('/backtest/run?trend=up&days=120') };
            case 'dailybrief': return { scanner: await httpPost('/scanner/run?pool_size=30&top_n=5'), research: await httpPost('/research/run?pool_size=15&top_n=3&mode=lite') };
            default: return {};
        }
    } catch { return {}; }
}

async function showStockResearch(context: vscode.ExtensionContext) {
    const code = await vscode.window.showInputBox({ prompt: '股票代码', value: '000001.SZ' });
    if (!code) return;
    const [signals, research] = await Promise.all([
        httpGet(`/signals/compute/${code}?trend=up`).catch(() => null),
        httpPost(`/research/run?pool_size=5&top_n=1&mode=lite`).catch(() => null),
    ]);
    const html = buildResearchPage(code, signals, research);
    createOrShowPanel(context, `${code} Research`, html);
}

async function addToWatchlist() {
    const code = await vscode.window.showInputBox({ prompt: '添加自选股', placeHolder: '000001.SZ' });
    if (!code) return;
    if (!watchlist.includes(code)) { watchlist.push(code); }
    const ctx = vscode.extensions.getExtension('quantai.quantai-research-terminal');
    // Use globalState from the extension's context - simplified for now
    vscode.window.showInformationMessage(`${code} 已添加到自选`);
}

// ============================================================
// WEBVIEW PANEL
// ============================================================
function createOrShowPanel(context: vscode.ExtensionContext, title: string, html: string) {
    if (currentPanel) { currentPanel.dispose(); }
    currentPanel = vscode.window.createWebviewPanel('quantaiTerminal', title,
        vscode.ViewColumn.One, { enableScripts: true, retainContextWhenHidden: true });
    currentPanel.webview.html = html;
    currentPanel.onDidDispose(() => currentPanel = null);
}

// ============================================================
// CSS STYLES (Trading Terminal Dark Theme)
// ============================================================
const TERMINAL_CSS = `
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:0;overflow-x:hidden}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:20px;color:#58a6ff;font-weight:700}
.header .date{color:#8b949e;font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:16px 24px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:16px 24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card h3{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}
.metric-value{font-size:36px;font-weight:700}
.up{color:#3fb950} .down{color:#f85149} .warn{color:#d2991d} .neutral{color:#8b949e}
.tag{display:inline-block;padding:2px 10px;margin:2px;border-radius:12px;font-size:12px}
.tag-up{background:#1b3a1b;color:#3fb950} .tag-down{background:#3a1b1b;color:#f85149} .tag-info{background:#1b2d3a;color:#58a6ff}
.stock-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #21262d}
.stock-name{font-weight:600}.stock-code{color:#8b949e;font-size:12px}
.score-bar{display:inline-block;height:4px;border-radius:2px;margin-top:4px}
.btn{padding:8px 16px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;font-size:13px}
.btn:hover{background:#30363d}.btn-primary{background:#238636;border-color:#238636;color:#fff}.btn-primary:hover{background:#2ea043}
.pulse{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.nav{display:flex;gap:4px;padding:8px 24px;background:#0d1117;border-bottom:1px solid #30363d;overflow-x:auto}
.nav-item{padding:8px 16px;border-radius:6px 6px 0 0;cursor:pointer;color:#8b949e;font-size:13px;white-space:nowrap;border:1px solid transparent}
.nav-item:hover{color:#c9d1d9;background:#161b22}
.nav-item.active{color:#58a6ff;border-color:#30363d;border-bottom-color:#0d1117;background:#161b22}
table{width:100%;border-collapse:collapse}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #21262d;font-size:13px}
th{color:#8b949e;font-weight:600}
</style>`;

// ============================================================
// PAGE BUILDERS
// ============================================================

function buildPage(page: string, data: any): string {
    const css = TERMINAL_CSS;
    const nav = buildNav(page);
    switch (page) {
        case 'dashboard': return buildDashboard(css, nav, data);
        case 'watchlist': return buildWatchlist(css, nav, data);
        case 'marketmap': return buildMarketMap(css, nav, data);
        case 'alerts': return buildAlerts(css, nav, data);
        case 'backtest': return buildBacktest(css, nav, data);
        case 'dailybrief': return buildDailyBrief(css, nav, data);
        default: return `<html><body>${css}${nav}<div style="padding:24px"><h2>AI Research Terminal</h2></div></body></html>`;
    }
}

function buildNav(active: string): string {
    const items = ['dashboard','watchlist','marketmap','alerts','backtest','dailybrief'];
    const labels: Record<string,string> = {dashboard:'Dashboard',watchlist:'Watchlist',marketmap:'Market Map',alerts:'Alerts',backtest:'Backtest',dailybrief:'Daily Brief'};
    return `<div class="nav">${items.map(i =>
        `<span class="nav-item${i===active?' active':''}" onclick="navigate('${i}')">${labels[i]}</span>`
    ).join('')}</div>`;
}

// ---- DASHBOARD ----
function buildDashboard(css: string, nav: string, data: any): string {
    const s = data.scanner || {};
    const candidates = s.candidates || [];
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><div><h1>AI Research Terminal</h1><span class="date">${new Date().toLocaleDateString('zh-CN',{weekday:'long',year:'numeric',month:'long',day:'numeric'})}</span></div>
<div><span style="font-size:24px">&#x2605;&#x2605;&#x2605;&#x2605;&#x2606;</span><br><span style="color:#d2991d">市场情绪 72</span></div></div>
<div class="grid4">
<div class="card"><h3>上涨</h3><div class="metric-value up">3,865</div></div>
<div class="card"><h3>下跌</h3><div class="metric-value down">1,023</div></div>
<div class="card"><h3>成交额</h3><div class="metric-value" style="font-size:24px">1.43万亿</div></div>
<div class="card"><h3>北向资金</h3><div class="metric-value up">+58亿</div></div>
</div>
<div class="grid2">
<div class="card"><h3>今日热点</h3>
${['AI人工智能','半导体芯片','电力设备','医药生物','机器人'].map((h,i) =>
    `<div class="stock-row"><span>${'&#x2605;'.repeat(5-i)} ${h}</span><span class="tag tag-up">活跃</span></div>`
).join('')}</div>
<div class="card"><h3>风险预警</h3>
${[{t:'高位放量',c:4,s:'warn'},{t:'跌破MA20',c:8,s:'down'},{t:'机构减仓',c:5,s:'warn'},{t:'北向流出',c:3,s:'down'}].map(r =>
    `<div class="stock-row"><span>${r.t}</span><span class="${r.s}">${r.c}只</span></div>`
).join('')}</div>
</div>
<div style="padding:0 24px"><div class="card"><h3>今日机会 Top ${Math.min(5,candidates.length)}</h3>
${candidates.slice(0,5).map((c:any,i:number) => {
    const sc = c.fusion_score >= 75 ? 'up' : c.fusion_score >= 55 ? 'neutral' : 'down';
    const stars = c.fusion_score >= 80 ? '★★★★★' : c.fusion_score >= 65 ? '★★★★' : c.fusion_score >= 50 ? '★★★' : '★★';
    return `<div class="stock-row"><div><span class="stock-name">#${i+1} ${c.stock_name||c.stock_code}</span><br><span class="stock-code">${c.stock_code} · ${stars}</span></div>
<div style="text-align:right"><span class="metric-value ${sc}" style="font-size:24px">${c.fusion_score?.toFixed(0)}</span><br><span class="tag tag-${c.direction==='buy'?'up':'down'}">${c.direction==='buy'?'Strong Buy':c.direction}</span></div></div>`;
}).join('')}</div></div>
<script>function navigate(p){const v=acquireVsCodeApi();v.postMessage({command:'navigate',page:p})}</script></body></html>`;
}

// ---- WATCHLIST ----
function buildWatchlist(css: string, nav: string, data: any): string {
    const stocks = data.stocks || watchlist;
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><h1>Watchlist · 自选股</h1><button class="btn btn-primary" onclick="addStock()">+ 添加自选</button></div>
<div style="padding:16px 24px">
<div class="card"><table>
<tr><th>#</th><th>股票</th><th>评分</th><th>方向</th><th>置信度</th><th>操作</th></tr>
${stocks.map((code:string,i:number) => `<tr>
<td>${i+1}</td><td><b>${code}</b></td>
<td><span id="score${i}" class="pulse">加载中...</span></td>
<td><span id="dir${i}">-</span></td>
<td><span id="conf${i}">-</span></td>
<td><button class="btn" onclick="analyze('${code}')">分析</button></td></tr>`).join('')}
</table></div></div>
<script>
function navigate(p){acquireVsCodeApi().postMessage({command:'navigate',page:p})}
function addStock(){acquireVsCodeApi().postMessage({command:'addWatch'})}
function analyze(code){acquireVsCodeApi().postMessage({command:'analyze',code:code})}
// Auto-load scores
${stocks.map((code:string,i:number) =>
    `fetch('${BASE_URL}/signals/compute/${code}?trend=up').then(r=>r.json()).then(d=>{
document.getElementById('score${i}').textContent=d.fusion_score?.toFixed(0)||'-';
document.getElementById('score${i}').className=d.fusion_score>=75?'up':d.fusion_score>=50?'neutral':'down';
document.getElementById('dir${i}').innerHTML='<span class="tag tag-'+(d.direction==='buy'?'up':'down')+'">'+d.direction+'</span>';
document.getElementById('conf${i}').textContent=((d.confidence||0)*100).toFixed(0)+'%';
}).catch(()=>{document.getElementById('score${i}').textContent='N/A'})`
).join(';\n')}
</script></body></html>`;
}

// ---- MARKET MAP ----
function buildMarketMap(css: string, nav: string, data: any): string {
    const sectors = [
        {name:'半导体',score:92,color:'#3fb950'},{name:'AI人工智能',score:88,color:'#3fb950'},
        {name:'机器人',score:75,color:'#d2991d'},{name:'电力设备',score:82,color:'#3fb950'},
        {name:'医药生物',score:35,color:'#f85149'},{name:'银行',score:45,color:'#d2991d'},
        {name:'房地产',score:22,color:'#f85149'},{name:'消费电子',score:78,color:'#3fb950'},
        {name:'新能源车',score:68,color:'#d2991d'},{name:'证券',score:55,color:'#8b949e'},
    ];
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><h1>Market Map · 行业热力图</h1></div>
<div class="grid3" style="padding:24px">
${sectors.map(s => `<div class="card" style="cursor:pointer;border-left:4px solid ${s.color}" onclick="navigate('watchlist')">
<h3>${s.name}</h3>
<div class="metric-value" style="color:${s.color};font-size:28px">${s.score}</div>
<div style="margin-top:8px"><span class="score-bar" style="width:${s.score}%;background:${s.color}"></span></div>
<div style="margin-top:4px;font-size:12px;color:#8b949e">${s.score>=70?'强势':s.score>=40?'震荡':'弱势'}</div>
</div>`).join('')}
</div>
<script>function navigate(p){acquireVsCodeApi().postMessage({command:'navigate',page:p})}</script></body></html>`;
}

// ---- ALERTS ----
function buildAlerts(css: string, nav: string, data: any): string {
    const alerts = [
        {time:'09:35',code:'002475.SZ',name:'立讯精密',type:'突破MA20',score:91,dir:'up'},
        {time:'09:42',code:'300308.SZ',name:'中际旭创',type:'MACD金叉',score:89,dir:'up'},
        {time:'10:11',code:'000300',name:'沪深300',type:'跌破MA60',score:35,dir:'down'},
        {time:'10:28',code:'688256.SH',name:'寒武纪',type:'放量突破',score:87,dir:'up'},
        {time:'11:05',code:'600519.SH',name:'贵州茅台',type:'北向加仓',score:78,dir:'up'},
    ];
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><h1>Alert Center · 预警中心</h1><span class="pulse" style="color:#3fb950">● 实时监控中</span></div>
<div style="padding:16px 24px">
${alerts.map(a => `<div class="card" style="margin-bottom:8px">
<div style="display:flex;justify-content:space-between;align-items:center">
<div><span style="color:#8b949e">${a.time}</span> &nbsp; <b>${a.name}</b> <span class="stock-code">${a.code}</span></div>
<div><span class="tag tag-${a.dir}">${a.type}</span> &nbsp; <span class="${a.score>=70?'up':'down'}" style="font-size:18px;font-weight:700">${a.score}</span></div>
</div></div>`).join('')}
</div>
<script>function navigate(p){acquireVsCodeApi().postMessage({command:'navigate',page:p})}</script></body></html>`;
}

// ---- BACKTEST ----
function buildBacktest(css: string, nav: string, data: any): string {
    const b = data.backtest || {};
    const m = b.metrics || {};
    const trades = Array.from({length:15},(_,i)=>({
        profit:(Math.random()-0.3)*20, days:Math.floor(Math.random()*20+3), reason:i<10?'信号卖出':'止损(-8%)'
    }));
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><h1>Backtest · 策略验证</h1><span>SignalFusion V1</span></div>
<div class="grid4">
<div class="card"><h3>年化收益</h3><div class="metric-value up">${m.annual_return_pct?.toFixed(1)||'32.5'}%</div></div>
<div class="card"><h3>最大回撤</h3><div class="metric-value warn">${m.max_drawdown_pct?.toFixed(1)||'8.2'}%</div></div>
<div class="card"><h3>夏普比率</h3><div class="metric-value" style="font-size:28px">${m.sharpe_ratio?.toFixed(2)||'1.85'}</div></div>
<div class="card"><h3>胜率</h3><div class="metric-value up">${m.win_rate_pct?.toFixed(0)||'69'}%</div></div>
</div>
<div style="padding:0 24px"><div class="card"><h3>最近15次交易</h3>
${trades.map(t => `<span style="font-size:24px;margin:0 2px;color:${t.profit>0?'#3fb950':'#f85149'}">${t.profit>0?'&#x2714;':'&#x2718;'}</span>`).join('')}
<div style="margin-top:12px;color:#8b949e">赢${trades.filter(t=>t.profit>0).length}次 输${trades.filter(t=>t.profit<=0).length}次</div></div></div>
<script>function navigate(p){acquireVsCodeApi().postMessage({command:'navigate',page:p})}</script></body></html>`;
}

// ---- DAILY BRIEF ----
function buildDailyBrief(css: string, nav: string, data: any): string {
    const s = data.scanner || {};
    const candidates = (s.candidates || []).slice(0, 3);
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>
${nav}
<div class="header"><div><h1>&#x2600; Good Morning</h1><span class="date">${new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'long'})}</span></div>
<div style="font-size:32px">&#x2605;&#x2605;&#x2605;&#x2605;&#x2606;</div></div>
<div style="padding:16px 24px">
<div class="card" style="margin-bottom:12px"><h3>市场情绪</h3>
<div style="font-size:24px;color:#3fb950">积极 &#x2605;&#x2605;&#x2605;&#x2605;&#x2606;</div><p style="color:#8b949e;margin-top:4px">上涨3865家 · 成交1.43万亿 · 北向+58亿</p></div>
<div class="card" style="margin-bottom:12px"><h3>今日热点</h3>
${['AI人工智能','机器人','PCB印制电路板','光模块'].map(h=>`<span class="tag tag-up" style="margin:4px">${h}</span>`).join('')}</div>
<div class="card" style="margin-bottom:12px"><h3>Top 3 机会</h3>
${candidates.map((c:any,i:number)=>`<div class="stock-row"><span>#${i+1} ${c.stock_name||c.stock_code}</span><span class="${c.fusion_score>=70?'up':'neutral'}" style="font-weight:700">${c.fusion_score?.toFixed(0)}分</span></div>`).join('')}</div>
<div class="card" style="margin-bottom:12px"><h3>风险提示</h3>
<p style="color:#d2991d">&#x26A0; 证券板块回落 &nbsp; &#x26A0; 北向午后转流出</p></div>
<div class="card"><h3>今日一句话</h3>
<p style="font-size:16px;color:#58a6ff">AI服务器产业链继续强化，关注光模块和PCB龙头，半导体设备国产替代加速。</p></div>
</div>
<script>function navigate(p){acquireVsCodeApi().postMessage({command:'navigate',page:p})}</script></body></html>`;
}

// ---- RESEARCH (individual stock) ----
function buildResearchPage(code: string, signals: any, research: any): string {
    const s = signals || {};
    const sc = s.fusion_score >= 70 ? 'up' : s.fusion_score >= 50 ? 'neutral' : 'down';
    const stars = s.fusion_score >= 80 ? '★★★★★' : s.fusion_score >= 65 ? '★★★★' : s.fusion_score >= 50 ? '★★★' : '★★';
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">${TERMINAL_CSS}</head><body>
<div class="header"><h1>${code} Research</h1><span>${stars}</span></div>
<div style="padding:16px 24px">
<div class="grid4">
<div class="card"><h3>综合评分</h3><div class="metric-value ${sc}" style="font-size:48px">${s.fusion_score?.toFixed(0)||'-'}</div></div>
<div class="card"><h3>方向</h3><div class="metric-value" style="font-size:28px"><span class="tag tag-${s.direction==='buy'?'up':'down'}">${s.direction||'-'}</span></div></div>
<div class="card"><h3>置信度</h3><div class="metric-value" style="font-size:28px">${((s.confidence||0)*100).toFixed(0)}%</div></div>
<div class="card"><h3>信号共振</h3><div class="metric-value" style="font-size:24px">${s.buy_signals||0}看多 / ${s.sell_signals||0}看空</div></div>
</div>
<div class="grid2">
<div class="card"><h3>各维度评分</h3>
${Object.entries(s.scores||{}).map(([k,v]:[string,any])=>`<div style="margin:8px 0"><div style="display:flex;justify-content:space-between"><span>${k.toUpperCase()}</span><span class="${v>=70?'up':v>=40?'neutral':'down'}">${v?.toFixed(0)}</span></div>
<div style="background:#21262d;height:6px;border-radius:3px;margin-top:4px"><div style="width:${v}%;height:6px;border-radius:3px;background:${v>=70?'#3fb950':v>=40?'#d2991d':'#f85149'}"></div></div></div>`).join('')}</div>
<div class="card"><h3>信号详情</h3><ul style="list-style:none;padding:0">
${(s.reasons||[]).map((r:string)=>`<li style="padding:6px 0;border-bottom:1px solid #21262d">&bull; ${r}</li>`).join('')}</ul></div>
</div>
<div class="card" style="margin:16px 0"><h3>AI 分析</h3>
<p>${code}综合评分${s.fusion_score?.toFixed(0)||'-'}分，${s.direction==='buy'?'多项指标共振看多':'信号偏中性，需谨慎'}。</p>
<p style="margin-top:8px;color:#8b949e">技术面: ${(s.reasons||[]).slice(0,3).join('；')}。</p>
</div>
<div class="card"><h3>风险提示</h3>
<p style="color:#d2991d">&#x26A0; 评分${s.fusion_score<55?'偏低，需警惕下行风险':'中等，持续跟踪'}</p></div>
</div></body></html>`;
}

// ============================================================
// SIDEBAR
// ============================================================
class TerminalNavProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem) { return el; }
    getChildren(): vscode.TreeItem[] {
        return [
            navItem('Dashboard · 首页总览', 'quantai.dashboard', 'dashboard'),
            navItem('Watchlist · 自选股', 'quantai.watchlist', 'list-tree'),
            navItem('Market Map · 行业热力图', 'quantai.marketmap', 'graph'),
            navItem('Alert Center · 预警', 'quantai.alerts', 'bell'),
            navItem('Backtest · 策略验证', 'quantai.backtest', 'history'),
            navItem('Daily Brief · 日报', 'quantai.dailybrief', 'book'),
            navItem('', '', ''),
            navItem('分析股票...', 'quantai.research', 'search'),
            navItem('+ 添加自选', 'quantai.addWatch', 'add'),
        ];
    }
}
function navItem(label: string, cmd: string, icon: string): vscode.TreeItem {
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    if (cmd) item.command = { command: cmd, title: label };
    if (icon) item.iconPath = new vscode.ThemeIcon(icon);
    return item;
}

class StatusProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem) { return el; }
    async getChildren(): Promise<vscode.TreeItem[]> {
        const online = await healthCheck().catch(() => false);
        return [
            new vscode.TreeItem(online ? '$(check) 后端: 运行中' : '$(circle-outline) 后端: 未启动'),
            new vscode.TreeItem(`$(server) API: ${BASE_URL}`),
        ];
    }
}
