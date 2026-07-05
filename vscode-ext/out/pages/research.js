"use strict";
/** AI Detail Page v2 — AI-first stock analysis with evidence cards. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildResearchPage = buildResearchPage;
function buildResearchPage(code, detail) {
    const d = detail || {};
    const evidence = d.evidence || [];
    const risks = d.risk_factors || [];
    const indicators = d.indicators || {};
    const financials = d.financials || {};
    const fundFlow = d.fund_flow || {};
    const news = d.news || [];
    const scores = d.scores || {};
    const sc = (d.ai_score || 50) >= 70 ? 'up' : (d.ai_score || 50) >= 50 ? 'neutral' : 'down';
    const stars = d.stars || 3;
    const starStr = '★'.repeat(stars) + '☆'.repeat(5 - stars);
    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:16px 24px;overflow-x:hidden}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.header h1{font-size:22px;color:#58a6ff}.header .stars{color:#d2991d;font-size:18px}
.back-btn{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px}
.back-btn:hover{background:#30363d}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}
.hero{text-align:center;padding:24px;background:linear-gradient(135deg,#161b22 0%,#1b2d3a 100%);border:1px solid #30363d;border-radius:12px;margin-bottom:16px}
.hero .score{font-size:64px;font-weight:800}
.hero .rec{font-size:20px;margin-top:4px}
.metric-value{font-size:36px;font-weight:700}
.up{color:#3fb950}.down{color:#f85149}.warn{color:#d2991d}.neutral{color:#8b949e}
.tag{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px}
.tag-up{background:#1b3a1b;color:#3fb950}.tag-down{background:#3a1b1b;color:#f85149}.tag-info{background:#1b2d3a;color:#58a6ff}
.evidence-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;margin-bottom:8px;border-left:3px solid #3fb950}
.evidence-card.warn-card{border-left-color:#d2991d}
.ev-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.ev-title{font-weight:600;font-size:14px}.ev-desc{color:#8b949e;font-size:12px;margin-top:4px}
.ev-source{color:#58a6ff;font-size:11px;margin-top:4px}
.cred-bar{height:4px;border-radius:2px;background:#21262d;margin-top:6px}
.cred-fill{height:4px;border-radius:2px}
.tabs{display:flex;gap:4px;margin:16px 0;border-bottom:1px solid #30363d;padding-bottom:0}
.tab{padding:8px 16px;cursor:pointer;color:#8b949e;border-bottom:2px solid transparent;font-size:13px}
.tab:hover{color:#c9d1d9}
.tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.tab-content{display:none}.tab-content.active{display:block}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.flex-between{display:flex;justify-content:space-between;align-items:center}
.text-sm{font-size:12px}.text-muted{color:#8b949e}.mt-8{margin-top:8px}.mt-12{margin-top:12px}
</style></head><body>
<div class="header">
<div><button class="back-btn" onclick="vscode.postMessage({command:'navigate',page:'watchlist'})">← 返回</button></div>
<div style="text-align:right"><h1>${d.stock_name || code}</h1><span class="stock-code">${code}</span></div>
</div>

<!-- Hero: AI Analysis FIRST -->
<div class="hero">
<div class="stars">${starStr}</div>
<div class="score ${sc}">${(d.ai_score || 50).toFixed(0)}</div>
<div class="rec"><span class="tag tag-${d.direction === 'buy' ? 'up' : d.direction === 'sell' ? 'down' : 'info'}" style="font-size:16px;padding:4px 16px">推荐: ${d.recommendation || '--'}</span></div>
<div class="text-sm text-muted mt-8">置信度 ${((d.confidence || 0) * 100).toFixed(0)}% · ${d.buy_signals || 0}看多 / ${d.sell_signals || 0}看空</div>
</div>

<!-- Buy/Sell Reasons -->
<div class="card">
<h3 style="color:#3fb950;margin-bottom:12px">✅ 买入理由</h3>
${evidence.filter((e) => e.icon === 'check').map((e) => `
<div class="evidence-card">
<div class="ev-header"><span class="ev-title">✓ ${e.title}</span><span style="color:#3fb950;font-weight:600">可信度 ${(e.credibility * 100).toFixed(0)}%</span></div>
<div class="ev-desc">${e.description}</div>
<div class="ev-source">来源: ${e.source} · 贡献: ${e.score_impact > 0 ? '+' : ''}${e.score_impact}分</div>
<div class="cred-bar"><div class="cred-fill" style="width:${(e.credibility * 100).toFixed(0)}%;background:#3fb950"></div></div>
</div>`).join('') || '<p class="text-muted">暂无买入信号</p>'}
</div>

${risks.length > 0 ? `
<div class="card">
<h3 style="color:#d2991d;margin-bottom:12px">⚠ 风险因素</h3>
${risks.map((r) => `<div class="evidence-card warn-card">
<div class="ev-title" style="color:#d2991d">⚠ ${r}</div>
</div>`).join('')}
</div>` : ''}

<!-- Tabs for technical details -->
<div class="tabs">
<span class="tab active" onclick="switchTab('signals')">📊 技术指标</span>
<span class="tab" onclick="switchTab('evidence')">🧾 证据链</span>
<span class="tab" onclick="switchTab('funds')">💰 资金</span>
<span class="tab" onclick="switchTab('financials')">📊 财务</span>
<span class="tab" onclick="switchTab('news')">📰 新闻</span>
</div>

<div id="tab-signals" class="tab-content active">
<div class="card">
<h3>各维度评分</h3>
${Object.entries(scores).map(([k, v]) => {
        const val = Number(v) || 50;
        const color = val >= 65 ? '#3fb950' : val >= 45 ? '#d2991d' : '#f85149';
        return `<div style="margin:8px 0"><div class="flex-between"><span>${k.toUpperCase()}</span><span style="color:${color}">${val.toFixed(0)}</span></div>
<div style="background:#21262d;height:6px;border-radius:3px;margin-top:4px"><div style="width:${val}%;height:6px;border-radius:3px;background:${color}"></div></div></div>`;
    }).join('')}
</div>
${indicators.macd ? `
<div class="grid2">
<div class="card">
<h3>MACD</h3>
<div class="text-sm text-muted">DIF: ${indicators.macd.dif || '-'} · DEA: ${indicators.macd.dea || '-'}</div>
<div class="mt-8"><span class="tag tag-${indicators.macd.signal === '金叉' ? 'up' : 'down'}">${indicators.macd.signal || '-'}</span></div>
</div>
<div class="card">
<h3>RSI</h3>
<div class="metric-value" style="font-size:28px;color:${(indicators.rsi?.value || 50) > 70 ? '#f85149' : (indicators.rsi?.value || 50) < 30 ? '#3fb950' : '#c9d1d9'}">${indicators.rsi?.value || '-'}</div>
<div class="text-sm text-muted">${indicators.rsi?.status || '-'}</div>
</div>
</div>` : ''}
</div>

<div id="tab-evidence" class="tab-content">
<div class="card">
<h3>完整证据链</h3>
${evidence.map((e) => `
<div class="evidence-card">
<div class="ev-header"><span class="ev-title">${e.icon === 'check' ? '✓' : e.icon === 'warning' ? '⚠' : '•'} ${e.title}</span><span style="color:#58a6ff;font-weight:600">可信度 ${(e.credibility * 100).toFixed(0)}%</span></div>
<div class="ev-desc">${e.detail || e.description}</div>
<div class="ev-source">来源: ${e.source} · ${e.timestamp || ''}</div>
<div class="cred-bar"><div class="cred-fill" style="width:${(e.credibility * 100).toFixed(0)}%;background:#58a6ff"></div></div>
</div>`).join('') || '<p class="text-muted">暂无证据</p>'}
</div>
</div>

<div id="tab-funds" class="tab-content">
<div class="grid4">
<div class="card"><h3>北向资金</h3><div class="metric-value ${(fundFlow.northbound || 0) >= 0 ? 'up' : 'down'}" style="font-size:24px">${fundFlow.northbound != null ? (fundFlow.northbound > 0 ? '+' : '') + fundFlow.northbound + '亿' : '-'}</div></div>
<div class="card"><h3>机构</h3><div class="metric-value ${(fundFlow.institutional || 0) >= 0 ? 'up' : 'down'}" style="font-size:24px">${fundFlow.institutional != null ? (fundFlow.institutional > 0 ? '+' : '') + fundFlow.institutional + '亿' : '-'}</div></div>
<div class="card"><h3>散户</h3><div class="metric-value ${(fundFlow.retail || 0) >= 0 ? 'up' : 'down'}" style="font-size:24px">${fundFlow.retail != null ? (fundFlow.retail > 0 ? '+' : '') + fundFlow.retail + '亿' : '-'}</div></div>
</div>
</div>

<div id="tab-financials" class="tab-content">
<div class="grid4">
<div class="card"><h3>PE</h3><div class="metric-value" style="font-size:28px">${financials.pe || '-'}</div></div>
<div class="card"><h3>PB</h3><div class="metric-value" style="font-size:28px">${financials.pb || '-'}</div></div>
<div class="card"><h3>ROE</h3><div class="metric-value ${(financials.roe || 0) >= 15 ? 'up' : 'neutral'}" style="font-size:28px">${financials.roe || '-'}%</div></div>
<div class="card"><h3>营收增长</h3><div class="metric-value ${(financials.revenue_growth || 0) >= 0 ? 'up' : 'down'}" style="font-size:28px">${financials.revenue_growth || '-'}%</div></div>
</div>
</div>

<div id="tab-news" class="tab-content">
<div class="card">
<h3>相关新闻</h3>
${news.map((n) => `<div class="flex-between" style="padding:10px 0;border-bottom:1px solid #21262d">
<div><span class="tag tag-${n.sentiment === 'positive' ? 'up' : 'down'}">${n.sentiment === 'positive' ? '利好' : '利空'}</span> ${n.title}</div>
<div class="text-sm text-muted">${n.date} · ${n.source}</div>
</div>`).join('') || '<p class="text-muted">暂无新闻</p>'}
</div>
</div>

<script>
const vscode = acquireVsCodeApi();
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('.tab[onclick*="' + name + '"]').classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
}
</script></body></html>`;
}
//# sourceMappingURL=research.js.map