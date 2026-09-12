/** News Radar — 新闻雷达（实时新闻聚合）*/

import { pageShell } from '../webview/layout';

export function buildNewsRadarPage(data: any): string {
    const newsList = data.news || [];
    const totalCount = data.total_count || newsList.length;
    const updatedAt = data.updated_at || '';
    const meta = data._meta || {};
    const statusText = meta.available
        ? `数据源正常${meta.age_hours !== undefined ? ` · ${meta.age_hours}小时前更新` : ''}`
        : `${meta.stale ? '缓存已过期' : '数据源不可用'}${meta.error ? ': ' + meta.error : ''}`;

    const content = `
<div class="hero" style="text-align:center;padding:24px;background:linear-gradient(135deg,#161b22 0%,#1b2d3a 100%);border:1px solid #30363d;border-radius:8px;margin:16px 24px">
<div style="font-size:32px">📰</div>
<div style="font-size:20px;color:#58a6ff;font-weight:700">News Radar</div>
<div class="date" style="margin-top:4px">新闻聚合 · 数据来源：东方财富</div>
${updatedAt ? `<div style="font-size:12px;color:#8b949e;margin-top:8px">更新时间: ${updatedAt}</div>` : ''}
<div style="font-size:12px;color:${meta.available ? '#3fb950' : '#f85149'};margin-top:6px">${statusText}</div>
<button onclick="refreshNews()" style="margin-top:12px;padding:8px 20px;background:#0e639c;color:white;border:none;border-radius:4px;cursor:pointer;font-size:14px">🔄 刷新</button>
</div>

<div style="padding:0 24px">
${newsList.length > 0 ? `
<div class="card">
<h3>📋 最新资讯（显示 ${newsList.length} / ${totalCount} 条）</h3>
<div style="max-height:600px;overflow-y:auto">
${newsList.map((news: any, i: number) => `
<div style="padding:16px 0;border-bottom:1px solid #30363d;cursor:pointer" onclick="openNewsLink('${news.url || '#'}')">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
<div style="flex:1">
<div style="font-size:16px;font-weight:600;color:#c9d1d9;line-height:1.4;margin-bottom:6px">${news.title || '无标题'}</div>
<div style="font-size:13px;color:#8b949e">
<span>${news.source || '未知来源'}</span>
<span style="margin:0 8px">·</span>
<span>${news.time || ''}</span>
${news.stocks && news.stocks.length > 0 ? `<span style="margin-left:12px">${news.stocks.map((s: string) => `<span class="tag" style="background:#1a1a1a;padding:2px 8px;border-radius:4px;font-size:11px">${s}</span>`).join(' ')}</span>` : ''}
</div>
</div>
${news.url ? `<div style="color:#58a6ff;font-size:20px">→</div>` : ''}
</div>
</div>`).join('')}
</div>
</div>
` : `
<div class="card" style="text-align:center;padding:40px">
<div style="font-size:48px;margin-bottom:16px">📭</div>
<div style="font-size:16px;color:#8b949e">${meta.available ? '暂无新闻数据' : '新闻源暂不可用'}</div>
<div style="font-size:13px;color:#8b949e;margin-top:8px">${meta.error || '点击上方「刷新」按钮获取最新资讯'}</div>
</div>
`}

<div style="text-align:center;padding:16px;color:#8b949e;font-size:12px">
数据来源：东方财富 · <span style="cursor:pointer;color:#58a6ff" onclick="refreshNews()">手动刷新</span>
</div>
</div>`;

    const extraScript = `
async function refreshNews() {
    vscode.postMessage({command:'refreshNews'});
}

function openNewsLink(url) {
    if (url && url !== '#') {
        vscode.postMessage({command: 'openExternal', url: url});
    }
}`;

    return pageShell('newsradar', 'News Radar · 新闻雷达', content, extraScript);
}
