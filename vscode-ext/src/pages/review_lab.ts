import { pageShell } from '../webview/layout';

function escapeHtml(value: unknown): string {
    return String(value ?? '--').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char] || char));
}

function renderArticle(article: any, accountName: string, latest = false): string {
    if (!article) return '<p class="text-muted">暂无已同步文章。</p>';
    const title = escapeHtml(article.title || '未命名文章');
    const url = escapeHtml(article.url || '');
    const published = escapeHtml(String(article.published_at || '').slice(0, 19));
    const author = escapeHtml(article.account_name || accountName || '公众号');
    const text = escapeHtml(article.content_text || article.summary || '暂无摘要');
    const images: string[] = Array.isArray(article.content_images) ? article.content_images : [];
    const imageHtml = images.length
        ? `<div style="display:grid;gap:8px;margin-top:10px">${images.map(image => `<img src="${escapeHtml(image)}" alt="公众号文章配图" loading="lazy" style="max-width:100%;border-radius:5px;background:#111827">`).join('')}</div>`
        : '';
    return `<article style="padding:10px 0${latest ? '' : ';border-top:1px solid #21262d'}">
<div style="font-size:13px;font-weight:600"><a href="${url}" target="_blank" rel="noreferrer" style="color:#A78BFA;text-decoration:none">${title}</a></div>
<div style="font-size:10px;color:#6B7280;margin:4px 0">${published} · ${author}</div>
<div class="text-sm" style="line-height:1.75;white-space:pre-wrap">${text}</div>${imageHtml}</article>`;
}

function renderAccount(account: any): string {
    const accountName = String(account?.source_name || '公众号');
    const latest = account?.latest || null;
    const history: any[] = Array.isArray(account?.history) ? account.history : [];
    const methodology = account?.methodology || {};
    const principles: string[] = Array.isArray(methodology.principles) ? methodology.principles : [];
    const checklist: string[] = Array.isArray(methodology.checklist) ? methodology.checklist : [];
    const limitations: string[] = Array.isArray(methodology.limitations) ? methodology.limitations : [];
    const learningStatus = methodology.status === 'completed'
        ? '已完成独立方法论学习' : methodology.status === 'unchanged'
            ? '文章未变化，沿用上一版学习结果' : methodology.status === 'failed'
                ? '本次学习失败，保留上一版结果' : '尚未生成方法论总结';
    const contentStatus = latest?.has_content ? '正文已抓取' : '暂无正文，仅显示摘要';
    const list = (items: string[]) => items.length
        ? `<ul class="text-sm" style="margin:6px 0;padding-left:20px">${items.map(item => `<li style="margin:4px 0">${escapeHtml(item)}</li>`).join('')}</ul>`
        : '<p class="text-muted">暂无。</p>';
    const historyHtml = history.length
        ? history.map(article => `<details style="margin:8px 0;border-top:1px solid #21262d;padding-top:8px">
<summary style="cursor:pointer;color:#A78BFA;font-size:12px">${escapeHtml(article?.title || '未命名文章')} · ${escapeHtml(String(article?.published_at || '').slice(0, 10))}</summary>
${renderArticle(article, accountName)}</details>`).join('')
        : '<p class="text-muted">暂无历史文章。</p>';
    const learningHtml = methodology.summary_markdown
        ? `<div class="text-sm" style="line-height:1.7;white-space:pre-wrap">${escapeHtml(methodology.summary_markdown)}</div>`
        : '<p class="text-muted">同步文章后点击“刷新并学习”，生成作者复盘思路总结。</p>';
    return `<section class="card" style="margin:0 24px 16px;border-color:#7C3AED88">
<div class="flex-between" style="gap:12px;align-items:flex-start"><div><h3 style="margin-bottom:4px">公众号复盘 · ${escapeHtml(accountName)}</h3>
<div class="text-sm text-muted">仅保留公众号文章与方法论学习 · ${contentStatus}</div></div>
<button class="btn btn-primary" onclick="refreshWechat()">刷新并学习</button></div>
<div style="margin-top:12px;padding:10px 12px;background:#0B1220;border-radius:7px">${renderArticle(latest, accountName, true)}</div>
<details style="margin-top:10px"><summary style="cursor:pointer;color:#A78BFA">历史文章（${history.length}）</summary>
<div style="margin-top:5px">${historyHtml}</div></details>
<div style="margin-top:14px;border-top:1px solid #30363d;padding-top:12px"><div class="flex-between" style="gap:12px;align-items:center">
<h4 style="margin:0">AI 学习：作者复盘思路</h4><span class="text-sm text-muted">${escapeHtml(learningStatus)}</span></div>
${learningHtml}
<div class="grid2" style="padding:0;margin-top:10px"><div><strong class="text-sm">提炼原则</strong>${list(principles)}</div>
<div><strong class="text-sm">每日检查清单</strong>${list(checklist)}</div></div>
${methodology.learning_delta ? `<p class="text-sm" style="margin:8px 0"><strong>本次进步：</strong>${escapeHtml(methodology.learning_delta)}</p>` : ''}
${limitations.length ? `<p class="text-sm text-muted" style="margin:8px 0">边界：${limitations.map(item => escapeHtml(item)).join('；')}</p>` : ''}
${methodology.generated_at ? `<div class="text-sm text-muted" style="margin-top:8px">学习时间：${escapeHtml(String(methodology.generated_at).slice(0, 19))} · 样本：${escapeHtml(methodology.article_count || 0)} 篇</div>` : ''}</div></section>`;
}

export function buildReviewLabPage(data: any): string {
    const wechat = data?.wechat || {};
    const accounts: any[] = Array.isArray(wechat.accounts) && wechat.accounts.length
        ? wechat.accounts
        : [{
            source_name: wechat.source_name || '股痴流沙河',
            latest: wechat.latest,
            history: wechat.history || [],
            methodology: wechat.methodology || {},
        }];
    const content = `<div style="padding:22px 24px 8px"><div class="flex-between" style="align-items:flex-start;gap:16px;flex-wrap:wrap">
<div><h1 style="font-size:20px;color:#A78BFA;margin-bottom:4px">公众号复盘 · 方法论</h1>
<div style="font-size:12px;color:#8b949e">公众号文章归档、最新复盘与独立方法论学习</div></div>
<span style="font-size:11px;color:#22C55E;border:1px solid #14532D;background:#052E16;padding:4px 8px;border-radius:999px">✓ 仅公众号</span></div></div>
<div style="padding:0 24px 8px"><button class="btn btn-primary" onclick="refreshWechat()">刷新并学习</button></div>
${accounts.map(renderAccount).join('')}`;
    const extraScript = `function refreshWechat(){vscode.postMessage({command:'wechatRefresh'});}`;
    return pageShell('review_lab', '公众号复盘 · 方法论', content, extraScript);
}
