/** Research Page v3.3 — Chart Runtime + Score Breakdown + Explain. */

import { BASE_URL } from '../constants';
import { CHART_RUNTIME_JS } from '../chart/chart-runtime';
import { INDICATORS_JS } from '../chart/chart-indicators';
import { OVERLAYS_JS } from '../chart/chart-overlays';
import { TIMELINE_JS } from '../chart/chart-timeline';

export function buildResearchPage(code: string, detail: any): string {
    const d = detail || {};
    const evidence = d.evidence || [];
    const risks = d.risk_factors || [];
    const indicators = d.indicators || {};
    const scores = d.scores || {};
    const fundFlow = d.fund_flow || {};
    const news = d.news || [];
    const price = d.latest_price || 0;
    const changePct = d.price_change_pct || 0;
    const sc = (d.ai_score || 50) >= 70 ? 'up' : (d.ai_score || 50) >= 50 ? 'warn' : 'down';
    const stars = d.stars || 3;
    const starStr = '★'.repeat(stars) + '☆'.repeat(5 - stars);
    const recColor = d.direction === 'buy' ? '#22C55E' : d.direction === 'sell' ? '#EF4444' : '#9CA3AF';

    // Generate mock K-line data for the chart (in a real app, this comes from the API)
    const klineData = generateMockKlineData(120, price || 100);

    return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0B1220;color:#F3F4F6;overflow:hidden;height:100vh}
.top-bar{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;background:#111827;border-bottom:1px solid #1F2937;height:48px;flex-shrink:0}
.top-bar .back-btn{background:transparent;border:1px solid #1F2937;color:#9CA3AF;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:12px}
.top-bar .back-btn:hover{color:#F3F4F6;border-color:#374151}
.research-layout{display:flex;height:calc(100vh - 48px);gap:0}
.research-main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;padding:12px}
.research-ai-panel{width:320px;background:#111827;border-left:1px solid #1F2937;overflow-y:auto;padding:14px;flex-shrink:0}
.chart-container{flex:1;min-height:300px;position:relative;background:#0B1220;border:1px solid #1F2937;border-radius:6px;overflow:hidden;margin-bottom:8px}
.indicator-row{display:flex;gap:6px;padding:6px 0}
.period-btn{padding:3px 10px;border:1px solid #1F2937;border-radius:4px;background:#0B1220;color:#9CA3AF;cursor:pointer;font-size:11px;font-family:'JetBrains Mono',monospace}
.period-btn:hover{color:#F3F4F6;border-color:#374151}
.period-btn.active{color:#7C3AED;border-color:#7C3AED;background:#1A1030}
.stock-info-bar{display:flex;align-items:center;gap:16px;padding:10px 14px;background:#111827;border:1px solid #1F2937;border-radius:6px;margin-bottom:10px;flex-wrap:wrap}
.stock-info-bar .si-name{font-size:17px;font-weight:700;color:#F3F4F6}
.stock-info-bar .si-code{font-size:12px;color:#9CA3AF;font-family:'JetBrains Mono',monospace}
.stock-info-bar .si-price{font-size:20px;font-weight:700;font-family:'JetBrains Mono',monospace}
.stock-info-bar .si-change{font-size:13px;font-family:'JetBrains Mono',monospace}
.stock-info-bar .si-item{font-size:11px;color:#9CA3AF}
.stock-info-bar .si-item span{color:#F3F4F6;font-family:'JetBrains Mono',monospace}
.ai-score-hero{text-align:center;padding:16px 0;border-bottom:1px solid #1F2937;margin-bottom:14px}
.ai-score-hero .score-num{font-size:52px;font-weight:800;line-height:1}
.ai-score-hero .score-stars{font-size:18px;color:#F59E0B;margin:6px 0}
.ai-score-hero .score-rec{display:inline-block;padding:5px 18px;border-radius:9999px;font-size:13px;font-weight:600;margin-top:6px}
.ai-score-hero .score-conf{font-size:11px;color:#9CA3AF;margin-top:4px}
.ai-section{margin-bottom:14px}
.ai-section h4{font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#6B7280;margin-bottom:8px}
.ev-card{background:#0B1220;border:1px solid #1F2937;border-radius:6px;padding:10px 12px;margin-bottom:6px;border-left:3px solid #22C55E}
.ev-card.warn{border-left-color:#F59E0B}
.ev-card .ev-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}
.ev-card .ev-title{font-size:12px;font-weight:600}
.ev-card .ev-cred{font-size:11px;font-family:'JetBrains Mono',monospace;color:#22C55E}
.ev-card .ev-desc{font-size:11px;color:#9CA3AF;margin-top:2px}
.ev-card .ev-meta{font-size:10px;color:#6B7280;margin-top:3px}
.ev-card .ev-bar{height:3px;background:#1F2937;border-radius:2px;margin-top:4px}
.ev-card .ev-bar-fill{height:3px;border-radius:2px;background:#22C55E}
.risk-item{font-size:11px;padding:5px 0;border-bottom:1px solid #1F2937;color:#F59E0B}
.risk-item .risk-sev{font-size:10px;padding:1px 6px;border-radius:3px;margin-left:6px}
.risk-sev.high{background:#450A0A;color:#EF4444}
.risk-sev.medium{background:#422006;color:#F59E0B}
.risk-sev.low{background:#1E293B;color:#9CA3AF}
.indicator-item{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1F2937;font-size:11px}
.indicator-item .ind-label{color:#9CA3AF}
.indicator-item .ind-value{font-family:'JetBrains Mono',monospace}
.fund-bar{margin-bottom:10px}
.fund-bar .fb-label{font-size:11px;color:#9CA3AF;margin-bottom:3px;display:flex;justify-content:space-between}
.fund-bar .fb-track{height:6px;background:#1F2937;border-radius:3px;overflow:hidden}
.fund-bar .fb-fill{height:6px;border-radius:3px}
.up{color:#22C55E}.down{color:#EF4444}.warn{color:#F59E0B}.neutral{color:#9CA3AF}
</style></head><body>

<!-- Top Bar -->
<div class="top-bar">
<button class="back-btn" onclick="vscode.postMessage({command:'navigate',page:'watchlist'})">← 返回</button>
<div style="font-size:13px;color:#9CA3AF">Adaptive Investment Intelligence</div>
</div>

<!-- Three-Column Layout -->
<div class="research-layout">

<!-- MAIN: Chart + Indicators -->
<div class="research-main">

<!-- Stock Info -->
<div class="stock-info-bar">
<span class="si-name">${d.stock_name || code}</span>
<span class="si-code">${code}</span>
<span class="si-price ${changePct >= 0 ? 'up' : 'down'}">¥${price.toFixed(2)}</span>
<span class="si-change ${changePct >= 0 ? 'up' : 'down'}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</span>
<span class="si-item">开 <span>${(price * 0.995).toFixed(2)}</span></span>
<span class="si-item">高 <span style="color:#22C55E">${(price * 1.02).toFixed(2)}</span></span>
<span class="si-item">低 <span style="color:#EF4444">${(price * 0.99).toFixed(2)}</span></span>
<span class="si-item">成交 <span>${(price * 300).toFixed(0)}亿</span></span>
<span class="si-item">换手 <span>${(Math.random() * 5 + 1).toFixed(1)}%</span></span>
</div>

<!-- Period + Panel Toggles -->
<div class="indicator-row">
<button class="period-btn active" data-days="80">日K</button>
<button class="period-btn" data-days="50">周K</button>
<button class="period-btn" data-days="24">月K</button>
<button class="period-btn" data-days="120">半年</button>
<button class="period-btn" data-days="250">1年</button>
<span style="flex:1"></span>
<button class="period-btn" id="btn-macd" onclick="window._runtime&&_runtime.toggle('macd')" style="color:#3B82F6">MACD</button>
<button class="period-btn" id="btn-rsi" onclick="window._runtime&&_runtime.toggle('rsi')" style="color:#A78BFA">RSI</button>
<button class="period-btn" id="btn-kdj" onclick="window._runtime&&_runtime.toggle('kdj')" style="color:#F59E0B">KDJ</button>
<button class="period-btn" id="btn-vol" onclick="window._runtime&&_runtime.toggle('volume')" style="color:#9CA3AF">VOL</button>
<span style="flex:1"></span>
<button class="period-btn" id="btn-live" style="color:#22C55E" onclick="toggleLiveFeed()">Live</button>
<button class="period-btn" style="color:#7C3AED" onclick="addAIDemo()">+ AI</button>
</div>

<!-- K-Line Chart -->
<div class="chart-container" id="kline-chart-container"></div>

<!-- Research Timeline -->
<div id="research-timeline" style="height:44px;flex-shrink:0;margin-top:4px"></div>

</div>

<!-- RIGHT: AI Panel -->
<div class="research-ai-panel">

<!-- AI Score Hero -->
<div class="ai-score-hero">
<div class="score-stars">${starStr}</div>
<div class="score-num ${sc}">${(d.ai_score || 50).toFixed(0)}</div>
<div class="score-rec" style="background:${recColor}22;color:${recColor};border:1px solid ${recColor}44">${d.recommendation || '观望'}</div>
<div class="score-conf">置信度 ${((d.confidence || 0) * 100).toFixed(0)}% · ${d.buy_signals || 0}看多/${d.sell_signals || 0}看空</div>
</div>

<!-- Score Breakdown (loaded from API) -->
<div id="score-breakdown" style="margin-bottom:12px">
<div class="loading" style="padding:12px;text-align:center;color:#9CA3AF;font-size:11px">加载评分分解...</div>
</div>

<!-- Timeline Context (populated when clicking timeline markers) -->
<div id="timeline-context" class="ai-section" style="display:none;background:#1A1030;border:1px solid #4C1D95;border-radius:6px;padding:10px 12px;margin-bottom:12px">
<div style="font-size:10px;color:#A78BFA;margin-bottom:4px">📅 点击时间线事件查看详情</div>
</div>

<!-- Evidence Chain -->
<div class="ai-section">
<h4>🧾 证据链</h4>
${evidence.slice(0, 6).map((e: any) => `
<div class="ev-card${e.icon === 'warning' ? ' warn' : ''}">
<div class="ev-top"><span class="ev-title">${e.icon === 'check' ? '✓' : e.icon === 'warning' ? '⚠' : '•'} ${e.title}</span><span class="ev-cred">${(e.credibility * 100).toFixed(0)}%</span></div>
<div class="ev-desc">${e.description}</div>
<div class="ev-meta">${e.source} · ${e.score_impact > 0 ? '+' : ''}${e.score_impact}分</div>
<div class="ev-bar"><div class="ev-bar-fill" style="width:${(e.credibility * 100).toFixed(0)}%"></div></div>
</div>`).join('') || '<div style="color:#6B7280;font-size:11px">暂无证据</div>'}
</div>

<!-- Risk Factors -->
<div class="ai-section">
<h4>⚠ 风险因素</h4>
${risks.map((r: string) => {
    let sev = 'low', sevLabel = '低';
    if (r.includes('高') || r.includes('回调') || r.includes('追高')) { sev = 'high'; sevLabel = '高'; }
    else if (r.includes('震荡') || r.includes('关注') || r.includes('走势')) { sev = 'medium'; sevLabel = '中'; }
    return `<div class="risk-item">⚠ ${r}<span class="risk-sev ${sev}">${sevLabel}</span></div>`;
}).join('') || '<div style="color:#6B7280;font-size:11px">暂无风险提示</div>'}
</div>

<!-- Key Indicators -->
<div class="ai-section">
<h4>📊 关键指标</h4>
<div class="indicator-item"><span class="ind-label">MACD</span><span class="ind-value" style="color:${(indicators.macd?.signal === '金叉' || scores.macd >= 60) ? '#22C55E' : '#EF4444'}">${indicators.macd?.signal || (scores.macd >= 60 ? '金叉' : '死叉')}</span></div>
<div class="indicator-item"><span class="ind-label">RSI</span><span class="ind-value">${indicators.rsi?.value || (scores.rsi || 50).toFixed(0)} <span style="font-size:10px;color:#9CA3AF">${indicators.rsi?.status || '健康'}</span></span></div>
<div class="indicator-item"><span class="ind-label">均线</span><span class="ind-value" style="color:${(scores.ma >= 60) ? '#22C55E' : (scores.ma <= 40) ? '#EF4444' : '#F59E0B'}">${indicators.ma?.trend || (scores.ma >= 60 ? '多头排列' : '空头排列')}</span></div>
<div class="indicator-item"><span class="ind-label">成交量</span><span class="ind-value" style="color:${(scores.volume >= 60) ? '#22C55E' : '#9CA3AF'}">${scores.volume >= 60 ? '放量' : '正常'}</span></div>
<div class="indicator-item"><span class="ind-label">KDJ</span><span class="ind-value">${(scores.kdj >= 60) ? '<span style=color:#22C55E>金叉</span>' : (scores.kdj <= 40) ? '<span style=color:#EF4444>死叉</span>' : '<span style=color:#9CA3AF>中性</span>'}</div>
<div class="indicator-item"><span class="ind-label">BOLL</span><span class="ind-value">${(scores.boll >= 60) ? '<span style=color:#22C55E>上轨</span>' : (scores.boll <= 40) ? '<span style=color:#EF4444>下轨</span>' : '<span style=color:#9CA3AF>中轨</span>'}</div>
</div>

<!-- Fund Flow -->
<div class="ai-section">
<h4>💰 资金流向</h4>
${[
    {label:'北向资金',val:fundFlow.northbound||0,color:'#22C55E'},
    {label:'机构',val:fundFlow.institutional||0,color:'#3B82F6'},
    {label:'散户',val:fundFlow.retail||0,color:'#EF4444'},
].map(f => {
    const cls = f.val >= 0 ? 'up' : 'down';
    const pct = Math.min(100, Math.abs(f.val) * 8);
    return `<div class="fund-bar">
<div class="fb-label"><span>${f.label}</span><span class="${cls}" style="font-family:monospace;font-size:11px">${f.val > 0 ? '+' : ''}${f.val.toFixed(1)}亿</span></div>
<div class="fb-track"><div class="fb-fill" style="width:${pct}%;background:${f.color}"></div></div>
</div>`;
}).join('')}
</div>

<!-- Recent News -->
${news.length > 0 ? `
<div class="ai-section">
<h4>📰 相关资讯</h4>
${news.slice(0, 3).map((n: any) => `
<div style="padding:6px 0;border-bottom:1px solid #1F2937;font-size:11px">
<div style="color:#F3F4F6;margin-bottom:2px">${n.title}</div>
<div style="color:#6B7280">${n.date} · ${n.source} · <span style="color:${n.sentiment === 'positive' ? '#22C55E' : '#EF4444'}">${n.sentiment === 'positive' ? '利好' : '利空'}</span></div>
</div>`).join('')}
</div>` : ''}

</div><!-- END AI Panel -->

</div><!-- END Research Layout -->

<!-- K-Line Chart Script -->
<script>
${CHART_RUNTIME_JS}
${INDICATORS_JS}
${OVERLAYS_JS}
${TIMELINE_JS}

// Initialize Chart Runtime + Timeline
(async function() {
    const container = document.getElementById('kline-chart-container');
    if (!container) return;

    const klineData = ${JSON.stringify(klineData)};

    setTimeout(async () => {
        // Create runtime
        const runtime = new ChartRuntime('kline-chart-container', {
            dataFeed: new StaticFeed(klineData),
        });

        // Register all default indicators
        runtime.registerIndicator(new MainIndicator());
        runtime.registerIndicator(new VolumeIndicator());
        runtime.registerIndicator(new MACDIndicator());
        runtime.registerIndicator(new RSIIndicator());
        runtime.registerIndicator(new KDJIndicator());

        // Init (computes panels, sets data, renders)
        await runtime.init();

        window._runtime = runtime;

        // Initialize Timeline
        const timeline = new ResearchTimeline('research-timeline', runtime);
        window._timeline = timeline;

        // Timeline click → update right panel context
        timeline.onClick = function(ev) {
            // Show evidence context in AI panel
            const ctxEl = document.getElementById('timeline-context');
            if (ctxEl) {
                const color = TIMELINE_COLORS[ev.type] || '#9CA3AF';
                let html = '<div style="font-size:12px;font-weight:600;color:' + color + ';margin-bottom:4px">' + ev.date + '</div>';
                html += '<div style="font-size:13px;font-weight:700">' + (ev.title || ev.type) + '</div>';
                if (ev.description) html += '<div style="font-size:11px;color:#9CA3AF;margin-top:4px">' + ev.description + '</div>';
                if (ev.score > 0) html += '<div style="font-size:11px;margin-top:4px">Score <span style="color:' + color + '">' + ev.score.toFixed(0) + '</span></div>';
                if (ev.confidence > 0) html += '<div style="font-size:11px;color:#9CA3AF">Confidence ' + (ev.confidence * 100).toFixed(0) + '%</div>';
                if (ev.source && ev.source.length) {
                    html += '<div style="margin-top:6px;border-top:1px solid #1F2937;padding-top:4px;font-size:10px;color:#58a6ff">' + ev.source.join(' · ') + '</div>';
                }
                ctxEl.innerHTML = html;
                ctxEl.style.display = 'block';
            }
            // Also update indicator values in AI panel for this date
            if (runtime.engine.data.length > 0) {
                const idx = runtime.engine.data.findIndex(d => d.date >= ev.date);
                if (idx >= 0) {
                    runtime.engine._updateTooltip(idx);
                }
            }
        };

        // Demo: emit evidence through EvidenceBus
        window.addAIDemo = function() {
            const d = klineData;
            // Buy signal evidence
            runtime.emitEvidence(new Evidence({
                type: 'buy_signal', date: d[Math.floor(d.length * 0.55)].date,
                price: d[Math.floor(d.length * 0.55)].low, score: 92, confidence: 0.89,
                title: 'MACD金叉 + MA多头', description: '多指标共振看多',
                source: ['signal:macd', 'signal:ma', 'knowledge:semiconductor'],
            }));
            runtime.emitEvidence(new Evidence({
                type: 'buy_signal', date: d[Math.floor(d.length * 0.72)].date,
                price: d[Math.floor(d.length * 0.72)].low, score: 87, confidence: 0.85,
                title: 'RSI超卖反弹', description: 'RSI跌至30后反弹',
                source: ['signal:rsi', 'signal:volume'],
            }));
            // Support line evidence
            runtime.emitEvidence(new Evidence({
                type: 'support', date: d[Math.floor(d.length * 0.30)].date,
                price: d[Math.floor(d.length * 0.30)].low, confidence: 0.88,
                title: 'S1', description: '过去三次触及反弹',
                source: ['ai:analyst', 'backtest:regression'],
            }));
            // AI Recommendation
            runtime.emitEvidence(new Evidence({
                type: 'ai_rec', date: d[Math.floor(d.length * 0.68)].date,
                score: 91, confidence: 0.87,
                title: 'AI强烈关注', description: '多指标共振 + 行业景气上行',
                source: ['ai:analyst', 'knowledge:semiconductor', 'signal:macd'],
            }));
            // Backtest trade
            runtime.emitEvidence(new Evidence({
                type: 'backtest', date: d[Math.floor(d.length * 0.45)].date,
                confidence: 0.80, title: '回测交易 +18.3%',
                detail: {
                    entryDate: d[Math.floor(d.length * 0.45)].date,
                    entryPrice: d[Math.floor(d.length * 0.45)].close,
                    exitDate: d[Math.floor(d.length * 0.62)].date,
                    exitPrice: d[Math.floor(d.length * 0.62)].close,
                    profitPct: 18.3, holdingDays: 35,
                },
            }));
            // News event
            runtime.emitEvidence(new Evidence({
                type: 'news', date: d[Math.floor(d.length * 0.52)].date,
                confidence: 0.70, title: 'Q3业绩超预期',
                description: '营收增长35%，利润增长42%',
                source: ['news:earnings'],
            }));
            timeline.render();
        };

        // Period switcher
        document.querySelectorAll('.period-btn[data-days]').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                runtime.setPeriod(parseInt(this.dataset.days));
            });
        });

        // Load Score Breakdown
        loadBreakdown('${code}');

        // Live feed toggle
        window._isLive = false;
        window._liveFeed = null;
        window.toggleLiveFeed = async function() {
            const btn = document.getElementById('btn-live');
            if (!window._isLive) {
                // Switch to live
                btn.textContent = 'Live ●';
                btn.style.color = '#22C55E';
                window._liveFeed = new LiveFeed('${BASE_URL}', '${code}', 30000);
                await window._liveFeed.start();
                runtime.setFeed(window._liveFeed);
                if (window._timeline) window._timeline.render();
                window._isLive = true;
                // Check status
                try {
                    const s = await fetch('${BASE_URL}/market/live-status');
                    const st = await s.json();
                    if (!st.live_available) btn.textContent = 'Mock';
                } catch(e) {}
            } else {
                // Switch back to static
                btn.textContent = 'Live';
                btn.style.color = '#9CA3AF';
                if (window._liveFeed) window._liveFeed.stop();
                runtime.setFeed(new StaticFeed(klineData));
                runtime.refresh();
                if (window._timeline) window._timeline.render();
                window._isLive = false;
            }
        };

        // Auto-check live status
        try {
            const s = await fetch('${BASE_URL}/market/live-status');
            const st = await s.json();
            if (st.live_available) {
                document.getElementById('btn-live').textContent = 'Live ✓';
                document.getElementById('btn-live').style.color = '#22C55E';
            }
        } catch(e) {}
    }, 100);
})();

// ========== Score Breakdown Renderer ==========
async function loadBreakdown(code) {
    const container = document.getElementById('score-breakdown');
    if (!container) return;
    try {
        const resp = await fetch('${BASE_URL}/explain/breakdown/' + code);
        const data = await resp.json();
        renderBreakdown(container, data);
    } catch(e) {
        container.innerHTML = '<div style="font-size:11px;color:#EF4444;padding:8px">评分分解加载失败</div>';
    }
}

function renderBreakdown(container, bd) {
    const cats = bd.category_totals || {};
    const comps = bd.components || [];
    const grouped = {};
    comps.forEach(c => { if (!grouped[c.category]) grouped[c.category] = []; grouped[c.category].push(c); });

    const catNames = {signal:'技术信号',knowledge:'行业知识',market:'市场环境',risk:'风险评估',backtest:'回测验证'};
    const catColors = {signal:'#22C55E',knowledge:'#7C3AED',market:'#3B82F6',risk:'#F59E0B',backtest:'#60A5FA'};

    let html = '<div style="background:#111827;border:1px solid #1F2937;border-radius:6px;padding:10px 12px">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
    html += '<span style="font-size:12px;font-weight:600;color:#9CA3AF">评分分解</span>';
    html += '<span style="font-size:20px;font-weight:800;color:' + (bd.final_score>=70?'#22C55E':bd.final_score>=50?'#F59E0B':'#EF4444') + '">' + (bd.final_score||50).toFixed(0) + '</span>';
    html += '</div>';

    // Total bar
    const pct = bd.final_score || 50;
    html += '<div style="height:4px;background:#1F2937;border-radius:2px;margin-bottom:10px">';
    html += '<div style="height:4px;border-radius:2px;width:' + pct + '%;background:' + (pct>=70?'#22C55E':pct>=50?'#F59E0B':'#EF4444') + '"></div></div>';

    // Categories with expandable items
    for (const [cat, items] of Object.entries(grouped)) {
        const catTotal = cats[cat] || 0;
        const catColor = catColors[cat] || '#9CA3AF';
        const catName = catNames[cat] || cat;
        const catId = 'cat_' + cat + '_' + Math.random().toString(36).slice(2,6);
        const sign = catTotal >= 0 ? '+' : '';

        html += '<div style="margin-bottom:6px">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:4px 0" onclick="document.getElementById(\'' + catId + '\').style.display = document.getElementById(\'' + catId + '\').style.display === \'none\' ? \'block\' : \'none\'">';
        html += '<span style="font-size:11px;color:' + catColor + ';font-weight:600">' + catName + '</span>';
        html += '<span style="font-size:11px;font-family:JetBrains Mono;color:' + (catTotal>=0?'#22C55E':'#EF4444') + '">' + sign + catTotal.toFixed(0) + '</span>';
        html += '</div>';

        // Items (expandable)
        html += '<div id="' + catId + '" style="padding-left:12px;display:block">';
        items.forEach(c => {
            const cs = c.score || 0;
            const csSign = cs >= 0 ? '+' : '';
            const csColor = cs > 3 ? '#22C55E' : cs < -3 ? '#EF4444' : '#9CA3AF';
            const barW = Math.min(100, Math.abs(cs) * 2.5);
            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0;font-size:10px" title="' + (c.detail||'') + '">';
            html += '<span style="color:#9CA3AF">' + (c.name||'') + '</span>';
            html += '<div style="display:flex;align-items:center;gap:6px">';
            html += '<div style="width:40px;height:2px;background:#1F2937;border-radius:1px"><div style="height:2px;border-radius:1px;width:' + barW + '%;background:' + csColor + '"></div></div>';
            html += '<span style="font-family:JetBrains Mono;color:' + csColor + ';min-width:32px;text-align:right">' + csSign + cs.toFixed(0) + '</span>';
            html += '</div></div>';
        });
        html += '</div>';
        html += '</div>';
    }

    // Net total
    html += '<div style="border-top:1px solid #1F2937;padding-top:6px;display:flex;justify-content:space-between;font-size:11px">';
    html += '<span style="color:#9CA3AF">综合</span>';
    html += '<span style="font-family:JetBrains Mono;font-weight:700;color:' + (bd.final_score>=70?'#22C55E':bd.final_score>=50?'#F59E0B':'#EF4444') + '">' + (bd.final_score||50).toFixed(0) + ' / 100</span>';
    html += '</div>';
    html += '<div style="font-size:9px;color:#6B7280;margin-top:3px">置信度 ' + ((bd.confidence||0)*100).toFixed(0) + '% · ' + (bd.positive_count||0) + '利好 / ' + (bd.negative_count||0) + '利空</div>';

    html += '</div>';
    container.innerHTML = html;
}
</script>

<script>
const vscode = acquireVsCodeApi();
</script></body></html>`;
}

/** Generate deterministic mock K-line data for chart display. */
function generateMockKlineData(days: number, basePrice: number): Array<{date: string; open: number; high: number; low: number; close: number; volume: number}> {
    const data = [];
    let price = basePrice * 0.85;
    const now = new Date();
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        const dateStr = d.toISOString().slice(0, 10);

        // Trend toward basePrice with noise
        const target = basePrice + (basePrice - price) * 0.02;
        const noise = (Math.random() - 0.48) * price * 0.03;
        const close = price + (target - price) * 0.3 + noise;
        const open = close * (1 + (Math.random() - 0.5) * 0.02);
        const high = Math.max(open, close) * (1 + Math.random() * 0.02);
        const low = Math.min(open, close) * (1 - Math.random() * 0.02);
        const volume = Math.floor(Math.random() * 3000000 + 500000);

        data.push({
            date: dateStr,
            open: Math.round(open * 100) / 100,
            high: Math.round(high * 100) / 100,
            low: Math.round(low * 100) / 100,
            close: Math.round(close * 100) / 100,
            volume: volume,
        });
        price = close;
    }
    return data;
}
