/** Compare Page — side-by-side stock comparison. */

import { pageShell } from '../webview/layout';
import { BASE_URL } from '../constants';

export function buildComparePage(data: any): string {
    const stocks = data.stocks || [];

    const content = `
<div style="padding:16px 24px">
<div class="card">
<div class="flex-row gap-8" style="margin-bottom:16px;flex-wrap:wrap">
    <input type="text" id="codeA" placeholder="股票代码A" value="600519.SH" style="width:160px">
    <span style="color:#8b949e;font-size:18px">vs</span>
    <input type="text" id="codeB" placeholder="股票代码B" value="000858.SZ" style="width:160px">
    <button class="btn btn-primary" onclick="runCompare()">对比</button>
    <button class="btn" onclick="addCompare()">+ 添加</button>
</div>
</div>

<div id="compareResult">
${stocks.length >= 2 ? buildCompareTable(stocks) : `
<div class="empty-state"><div class="icon">⚖</div><p>输入两个股票代码开始对比</p></div>`}
</div>
</div>`;

    const extraScript = `
async function runCompare() {
    const codeA = document.getElementById('codeA').value.trim();
    const codeB = document.getElementById('codeB').value.trim();
    if (!codeA || !codeB) return;
    const resultEl = document.getElementById('compareResult');
    resultEl.innerHTML = '<div class="loading">对比中</div>';
    try {
        const resp = await fetch('${BASE_URL}/compare', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({codes: [codeA, codeB]})
        });
        const data = await resp.json();
        const stocks = data.stocks || [];
        resultEl.innerHTML = stocks.length >= 2 ? buildCompareHTML(stocks) : '<div class="empty-state"><p>对比失败</p></div>';
    } catch(e) {
        resultEl.innerHTML = '<div class="empty-state"><p>对比失败，请检查后端状态</p></div>';
    }
}
function addCompare() {
    const container = document.querySelector('.flex-row');
    const count = container.querySelectorAll('input').length;
    if (count >= 4) return;
    const input = document.createElement('input');
    input.placeholder = '股票代码' + (count + 1);
    input.style.width = '160px';
    container.insertBefore(input, container.lastElementChild);
    if (count >= 2) {
        const vs = document.createElement('span');
        vs.style.cssText = 'color:#8b949e;font-size:18px';
        vs.textContent = 'vs';
        container.insertBefore(vs, container.lastElementChild);
    }
}
function buildCompareHTML(stocks) {
    const labels = ['AI评分','MACD','RSI','均线','成交量','估值','行业评分','AI建议','风险等级','置信度'];
    const keys = ['ai_score','macd','rsi','ma','volume','valuation','industry_score','recommendation','risk_level','confidence'];
    const confidenceIdx = keys.indexOf('confidence');
    let html = '<div class="compare-table" style="grid-template-columns:120px ' + '1fr '.repeat(stocks.length) + '">';
    // Header
    html += '<div class="compare-row" style="grid-template-columns:120px ' + '1fr '.repeat(stocks.length) + ';background:#21262d;font-weight:700">';
    html += '<div class="compare-cell" style="color:#8b949e">指标</div>';
    stocks.forEach((s) => {
        html += '<div class="compare-cell" style="cursor:pointer" onclick="analyzeStock(\'' + s.stock_code + '\')"><div>' + s.stock_name + '</div><div class="text-sm text-muted">' + s.stock_code + '</div></div>';
    });
    html += '</div>';
    // Rows
    keys.forEach((key, i) => {
        html += '<div class="compare-row" style="grid-template-columns:120px ' + '1fr '.repeat(stocks.length) + '">';
        html += '<div class="compare-cell" style="color:#8b949e;text-align:left;font-weight:600">' + labels[i] + '</div>';
        stocks.forEach((s) => {
            const val = s[key];
            let display = String(val != null ? val : '-');
            let cls = '';
            if (key === 'ai_score') {
                display = String(val || 50);
                cls = val >= 70 ? 'up' : val >= 50 ? 'neutral' : 'down';
            } else if (key === 'macd') {
                cls = String(val).includes('✓') ? 'up' : String(val).includes('✗') ? 'down' : 'neutral';
            } else if (key === 'direction' || key === 'recommendation') {
                cls = val === 'buy' || val === '买入' ? 'up' : val === 'sell' || val === '回避' ? 'down' : 'neutral';
            } else if (key === 'confidence') {
                display = ((val || 0) * 100).toFixed(0) + '%';
                cls = val >= 0.7 ? 'up' : val >= 0.5 ? 'neutral' : 'down';
            }
            html += '<div class="compare-cell ' + cls + '">' + display + '</div>';
        });
        html += '</div>';
    });
    html += '</div>';
    return html;
}
// Run compare on load if data is empty
${!stocks.length ? 'runCompare();' : ''}
`;

    return pageShell('compare', 'Compare · 股票对比', content, extraScript);
}

function buildCompareTable(stocks: any[]): string {
    const labels = ['AI评分','MACD','RSI','均线','成交量','估值','行业评分','AI建议','风险等级'];
    const keys = ['ai_score','macd','rsi','ma','volume','valuation','industry_score','recommendation','risk_level'];
    let html = `<div class="compare-table" style="grid-template-columns:120px ${'1fr '.repeat(stocks.length)}">`;
    // Header
    html += `<div class="compare-row" style="grid-template-columns:120px ${'1fr '.repeat(stocks.length)};background:#21262d;font-weight:700">`;
    html += '<div class="compare-cell" style="color:#8b949e">指标</div>';
    stocks.forEach((s: any) => {
        html += `<div class="compare-cell" style="cursor:pointer" onclick="analyzeStock('${s.stock_code}')"><div>${s.stock_name}</div><div class="text-sm text-muted">${s.stock_code}</div></div>`;
    });
    html += '</div>';
    // Rows
    keys.forEach((key, i) => {
        html += `<div class="compare-row" style="grid-template-columns:120px ${'1fr '.repeat(stocks.length)}">`;
        html += `<div class="compare-cell" style="color:#8b949e;text-align:left;font-weight:600">${labels[i]}</div>`;
        stocks.forEach((s: any) => {
            const val = s[key];
            let display = String(val != null ? val : '-');
            let cls = '';
            if (key === 'ai_score') { cls = val >= 70 ? 'up' : val >= 50 ? 'neutral' : 'down'; display = String(val || 50); }
            else if (key === 'macd') { cls = String(val).includes('✓') ? 'up' : String(val).includes('✗') ? 'down' : 'neutral'; }
            html += `<div class="compare-cell ${cls}">${display}</div>`;
        });
        html += '</div>';
    });
    html += '</div>';
    return html;
}
