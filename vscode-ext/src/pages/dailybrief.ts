/** Daily Brief v2 — auto-generated morning report. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildDailyBriefPage(data: any): string {
    const brief = data.brief || {};
    const sentiment = brief.market_sentiment || {};
    const hotSectors = brief.hot_sectors || [];
    const opportunities = brief.top_opportunities || [];
    const risks = brief.risk_warnings || [];

    const stars = sentiment.stars || 4;
    const starStr = '★'.repeat(stars) + '☆'.repeat(5 - stars);

    const content = `
<div class="hero" style="text-align:center;padding:24px;background:linear-gradient(135deg,#161b22 0%,#1b2d3a 100%);border:1px solid #30363d;border-radius:8px;margin:16px 24px">
<div style="font-size:32px">☀</div>
<div style="font-size:20px;color:#58a6ff;font-weight:700">Good Morning</div>
<div class="date" style="margin-top:4px">${brief.date || new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}</div>
<div style="margin-top:12px;font-size:24px;color:#d2991d">${starStr}</div>
<div style="font-size:14px;color:#8b949e;margin-top:4px">市场情绪: ${sentiment.label || '积极'}</div>
</div>

<div style="padding:0 24px">
<div class="card"><h3>📊 市场概况</h3>
<p style="font-size:16px">${brief.market_summary || '数据加载中...'}</p>
<p class="text-muted mt-8">情绪${sentiment.score || 78}分 · ${(sentiment.score || 78) >= 70 ? '偏乐观' : '偏中性'}</p>
</div>

<div class="card"><h3>🔥 今日热点</h3>
<div class="flex-row gap-8" style="flex-wrap:wrap">
${hotSectors.map((s: any) => `<span class="tag tag-up" style="font-size:14px;padding:6px 14px">${'★'.repeat(s.stars || 1)} ${s.name} ${s.score}</span>`).join('') || '<span class="text-muted">加载中...</span>'}
</div></div>

<div class="card"><h3>💡 今日机会</h3>
${opportunities.map((o: any, i: number) => `
<div class="stock-row" onclick="analyzeStock('${o.stock_code}')">
<div><span class="stock-name">#${i + 1} ${o.stock_name || o.stock_code}</span><br><span class="stock-code">${o.stock_code}</span></div>
<div style="text-align:right">
<span class="${(o.score || 50) >= 70 ? 'up' : 'neutral'}" style="font-weight:700;font-size:18px">${(o.score || 50).toFixed(0)}分</span><br>
<span class="tag tag-up">${o.direction === 'buy' ? 'Strong Buy' : 'Buy'}</span>
</div></div>`).join('') || '<p class="text-muted">暂无机会推荐</p>'}
</div>

<div class="card"><h3>⚠ 风险提示</h3>
${risks.map((r: string) => `<p style="padding:6px 0;color:#d2991d">⚠ ${r}</p>`).join('') || '<p class="text-muted">暂无风险提示</p>'}
</div>

<div class="card" style="border-left:3px solid #58a6ff"><h3>💬 今日一句话</h3>
<p style="font-size:16px;color:#58a6ff;line-height:1.6">${brief.one_liner || '市场数据收集中，请稍后刷新。'}</p>
</div>

<div style="text-align:center;padding:16px;color:#8b949e;font-size:12px">
生成时间: ${brief.generated_at || '09:00'} · 每日自动更新 · <span style="cursor:pointer;color:#58a6ff" onclick="refreshBrief()">手动刷新</span>
</div>
</div>`;

    const extraScript = `
async function refreshBrief() {
    try {
        await fetch('${BASE_URL}/dailybrief/generate', {method:'POST'});
    } catch(e) {}
    location.reload();
}`;

    return pageShell('dailybrief', 'Daily Brief · 每日简报', content, extraScript);
}
