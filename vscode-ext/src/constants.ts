/** Shared constants for the AI Research Terminal extension. */

export const BASE_URL = 'http://127.0.0.1:8888/api/v1';

export const NAV_ITEMS: { id: string; label: string }[] = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'watchlist', label: 'Watchlist' },
    { id: 'marketmap', label: 'Market Map' },
    { id: 'compare', label: 'Compare' },
    { id: 'timeline', label: 'Timeline' },
    { id: 'alerts', label: 'Alerts' },
    { id: 'backtest', label: 'Backtest' },
    { id: 'dailybrief', label: 'Daily Brief' },
];

export const PAGE_TITLES: Record<string, string> = {
    dashboard: 'Dashboard', watchlist: 'Watchlist', marketmap: 'Market Map',
    compare: 'Compare', timeline: 'Timeline', alerts: 'Alert Center',
    backtest: 'Backtest', dailybrief: 'Daily Brief',
};

export const TERMINAL_CSS = `
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:0;overflow-x:hidden}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.header h1{font-size:20px;color:#58a6ff;font-weight:700}
.header .date{color:#8b949e;font-size:13px}
.header .subtitle{color:#8b949e;font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:16px 24px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:16px 24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:8px}
.card h3{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.metric-value{font-size:36px;font-weight:700}
.up{color:#3fb950} .down{color:#f85149} .warn{color:#d2991d} .neutral{color:#8b949e}
.tag{display:inline-block;padding:2px 10px;margin:2px;border-radius:12px;font-size:12px;white-space:nowrap}
.tag-up{background:#1b3a1b;color:#3fb950} .tag-down{background:#3a1b1b;color:#f85149}
.tag-info{background:#1b2d3a;color:#58a6ff} .tag-warn{background:#3a351b;color:#d2991d}
.stock-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #21262d;cursor:pointer}
.stock-row:hover{background:#1c2128}
.stock-name{font-weight:600}.stock-code{color:#8b949e;font-size:12px}
.score-bar{display:inline-block;height:4px;border-radius:2px;margin-top:4px}
.btn{padding:8px 16px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;font-size:13px}
.btn:hover{background:#30363d}.btn-primary{background:#238636;border-color:#238636;color:#fff}.btn-primary:hover{background:#2ea043}
.btn-danger{background:#da3633;border-color:#da3633;color:#fff}.btn-danger:hover{background:#f85149}
.btn-sm{padding:4px 10px;font-size:11px}
.pulse{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.nav{display:flex;gap:4px;padding:8px 24px;background:#0d1117;border-bottom:1px solid #30363d;overflow-x:auto}
.nav-item{padding:8px 16px;border-radius:6px 6px 0 0;cursor:pointer;color:#8b949e;font-size:13px;white-space:nowrap;border:1px solid transparent}
.nav-item:hover{color:#c9d1d9;background:#161b22}
.nav-item.active{color:#58a6ff;border-color:#30363d;border-bottom-color:#0d1117;background:#161b22}
table{width:100%;border-collapse:collapse}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #21262d;font-size:13px}
th{color:#8b949e;font-weight:600;white-space:nowrap}
tr:hover{background:#1c2128}
input,select{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#c9d1d9;font-size:13px}
input:focus,select:focus{outline:none;border-color:#58a6ff}
.flex-row{display:flex;align-items:center;gap:8px}
.flex-between{display:flex;justify-content:space-between;align-items:center}
.gap-4{gap:4px}.gap-8{gap:8px}.gap-12{gap:12px}.gap-16{gap:16px}
.mt-8{margin-top:8px}.mt-12{margin-top:12px}.mt-16{margin-top:16px}
.mb-8{margin-bottom:8px}.mb-16{margin-bottom:16px}
.p-16{padding:16px}.p-24{padding:24px}
.text-sm{font-size:12px}.text-muted{color:#8b949e}
.evidence-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;margin-bottom:8px}
.evidence-card .ev-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.evidence-card .ev-title{font-weight:600;font-size:14px}
.evidence-card .ev-desc{color:#8b949e;font-size:12px;margin-top:4px}
.evidence-card .ev-source{color:#58a6ff;font-size:11px;margin-top:4px}
.evidence-card .cred-bar{height:3px;border-radius:2px;background:#21262d;margin-top:4px}
.evidence-card .cred-fill{height:3px;border-radius:2px}
.compare-table{display:grid;gap:1px;background:#30363d;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.compare-row{display:grid;background:#161b22;padding:12px 16px}
.compare-cell{padding:8px;text-align:center}
.timeline-chart{font-family:'Courier New',monospace;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;overflow-x:auto;white-space:pre;line-height:1.6}
.section-title{font-size:16px;font-weight:600;color:#58a6ff;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #21262d}
.toast{position:fixed;top:16px;right:16px;padding:12px 20px;border-radius:8px;font-size:13px;z-index:1000;animation:slideIn 0.3s ease}
.toast-success{background:#1b3a1b;border:1px solid #3fb950;color:#3fb950}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
.loading{color:#8b949e;text-align:center;padding:24px}
.loading::after{content:'...';animation:dots 1.5s steps(4,end) infinite}
@keyframes dots{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}
.empty-state{text-align:center;padding:48px;color:#8b949e}
.empty-state .icon{font-size:48px;margin-bottom:16px}
/* Three-Column Layout (Research Page) */
.research-layout{display:flex;height:calc(100vh - 90px);gap:0}
.research-main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.research-ai-panel{width:320px;background:#111827;border-left:1px solid #1F2937;overflow-y:auto;padding:16px;flex-shrink:0}
.research-ai-panel .ai-section{margin-bottom:16px}
.chart-container{flex:1;min-height:400px;position:relative;background:#0B1220;border:1px solid #1F2937;border-radius:6px;overflow:hidden}
.indicator-row{display:flex;gap:8px;padding:8px 0}
.mini-charts{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:12px 0}
.mini-chart-card{background:#111827;border:1px solid #1F2937;border-radius:6px;padding:10px}
.mini-chart-card .mini-title{font-size:10px;color:#9CA3AF;text-transform:uppercase;margin-bottom:4px}
.mini-chart-card .mini-value{font-size:16px;font-weight:700}
.mini-chart-card .mini-chart{height:40px;margin-top:4px}
.stock-info-bar{display:flex;align-items:center;gap:16px;padding:12px 16px;background:#111827;border:1px solid #1F2937;border-radius:6px;margin-bottom:12px;flex-wrap:wrap}
.stock-info-bar .si-name{font-size:18px;font-weight:700;color:#F3F4F6}
.stock-info-bar .si-code{font-size:13px;color:#9CA3AF;font-family:JetBrains Mono,monospace}
.stock-info-bar .si-price{font-size:22px;font-weight:700;font-family:JetBrains Mono,monospace}
.stock-info-bar .si-change{font-size:14px;font-family:JetBrains Mono,monospace}
.stock-info-bar .si-item{font-size:11px;color:#9CA3AF}
.stock-info-bar .si-item span{color:#F3F4F6;font-family:JetBrains Mono,monospace}
/* AI Panel Components */
.ai-score-hero{text-align:center;padding:20px 0;border-bottom:1px solid #1F2937;margin-bottom:16px}
.ai-score-hero .score-num{font-size:56px;font-weight:800;line-height:1}
.ai-score-hero .score-stars{font-size:20px;color:#F59E0B;margin:8px 0}
.ai-score-hero .score-rec{display:inline-block;padding:6px 20px;border-radius:9999px;font-size:14px;font-weight:600;margin-top:8px}
.ai-score-hero .score-conf{font-size:11px;color:#9CA3AF;margin-top:6px}
.ev-card{background:#0B1220;border:1px solid #1F2937;border-radius:6px;padding:10px 12px;margin-bottom:8px;border-left:3px solid #22C55E}
.ev-card.warn{border-left-color:#F59E0B}
.ev-card .ev-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.ev-card .ev-title{font-size:13px;font-weight:600}
.ev-card .ev-cred{font-size:11px;font-family:JetBrains Mono,monospace}
.ev-card .ev-desc{font-size:11px;color:#9CA3AF;margin-top:2px}
.ev-card .ev-meta{font-size:10px;color:#6B7280;margin-top:4px}
.ev-card .ev-bar{height:3px;background:#1F2937;border-radius:2px;margin-top:4px}
.ev-card .ev-bar-fill{height:3px;border-radius:2px}
/* Radar Placeholder */
.radar-placeholder{width:160px;height:160px;margin:0 auto 16px;position:relative;display:flex;align-items:center;justify-content:center}
.radar-placeholder svg{width:100%;height:100%}
/* Period Selector */
.period-selector{display:flex;gap:2px;padding:4px 0}
.period-btn{padding:4px 10px;border:1px solid #1F2937;border-radius:4px;background:#0B1220;color:#9CA3AF;cursor:pointer;font-size:11px;font-family:JetBrains Mono,monospace}
.period-btn:hover{color:#F3F4F6;border-color:#374151}
.period-btn.active{color:#7C3AED;border-color:#7C3AED;background:#1A1030}
</style>`;
