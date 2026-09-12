/**
 * 估值数据页面
 * 显示股票的估值指标（PE/PB/PS/市值等）
 */

export function buildValuationPage(data: any): string {
    const valuation = data?.valuation || {};
    const code = data?.code || '';
    const meta = data?._meta || {};
    const formatNumber = (value: any) => {
        const number = Number(value);
        return Number.isFinite(number) ? number.toFixed(2) : '--';
    };
    const statusText = meta.is_proxy
        ? `${meta.warning || '当前展示行情代理指标'} · 获取时间 ${meta.fetched_at || '--'}`
        : meta.available
        ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
        : (meta.error || (code ? '估值数据源不可用' : '请输入股票代码查询'));

    return `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: var(--vscode-font-family);
            color: var(--vscode-foreground);
            padding: 20px;
            margin: 0;
        }
        .search-section {
            margin-bottom: 20px;
            padding: 15px;
            background: var(--vscode-editor-background);
            border-radius: 4px;
        }
        .search-box {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .search-box input {
            flex: 1;
            padding: 8px 12px;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 3px;
            font-size: 13px;
        }
        .search-box button {
            padding: 8px 16px;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 13px;
        }
        .search-box button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        .valuation-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .valuation-card {
            padding: 15px;
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
        }
        .card-label {
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            margin-bottom: 8px;
        }
        .card-value {
            font-size: 20px;
            font-weight: 600;
            color: var(--vscode-foreground);
        }
        .card-unit {
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            margin-left: 4px;
        }
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--vscode-descriptionForeground);
        }
        .stock-header {
            margin-bottom: 20px;
            padding: 15px;
            background: var(--vscode-editor-background);
            border-radius: 4px;
        }
        .stock-code {
            font-size: 18px;
            font-weight: 600;
            color: var(--vscode-foreground);
        }
        .stock-name {
            font-size: 14px;
            color: var(--vscode-descriptionForeground);
            margin-top: 4px;
        }
    </style>
</head>
<body>
    <div style="margin-bottom:12px;font-size:12px;color:${meta.available ? '#73c991' : '#cca700'}">${statusText}</div>
    <div class="search-section">
        <div class="search-box">
            <input type="text" id="stockCodeInput" placeholder="输入股票代码（如 000001）" value="${code}">
            <button onclick="searchValuation()">查询估值</button>
        </div>
    </div>

    ${Object.keys(valuation).length > 0 ? `
        <div class="stock-header">
            <div class="stock-code">${code}</div>
            <div class="stock-name">${valuation.name || '股票估值数据'}</div>
        </div>

        <div class="valuation-grid">
            ${valuation.price !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">最新价</div>
                    <div class="card-value">${formatNumber(valuation.price)}<span class="card-unit">元</span></div>
                </div>
            ` : ''}

            ${valuation.change_pct !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">涨跌幅</div>
                    <div class="card-value">${formatNumber(valuation.change_pct)}<span class="card-unit">%</span></div>
                </div>
            ` : ''}

            ${valuation.pe !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">市盈率 (PE)</div>
                    <div class="card-value">${formatNumber(valuation.pe)}<span class="card-unit">倍</span></div>
                </div>
            ` : ''}

            ${valuation.pb !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">市净率 (PB)</div>
                    <div class="card-value">${formatNumber(valuation.pb)}<span class="card-unit">倍</span></div>
                </div>
            ` : ''}

            ${valuation.ps !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">市销率 (PS)</div>
                    <div class="card-value">${formatNumber(valuation.ps)}<span class="card-unit">倍</span></div>
                </div>
            ` : ''}

            ${valuation.market_cap !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">总市值</div>
                    <div class="card-value">${formatNumber(Number(valuation.market_cap) / 100000000)}<span class="card-unit">亿</span></div>
                </div>
            ` : ''}

            ${valuation.float_market_cap !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">流通市值</div>
                    <div class="card-value">${formatNumber(Number(valuation.float_market_cap) / 100000000)}<span class="card-unit">亿</span></div>
                </div>
            ` : ''}

            ${valuation.pe_ttm !== undefined ? `
                <div class="valuation-card">
                    <div class="card-label">市盈率TTM</div>
                    <div class="card-value">${formatNumber(valuation.pe_ttm)}<span class="card-unit">倍</span></div>
                </div>
            ` : ''}
        </div>
    ` : `
        <div class="empty-state">
            ${code ? (meta.available ? '该股票暂无估值数据' : statusText) : '请输入股票代码查询估值数据'}
        </div>
    `}

    <script>
        const vscode = acquireVsCodeApi();

        function searchValuation() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                return;
            }
            vscode.postMessage({
                command: 'searchValuation',
                code: code
            });
        }

        // 回车键搜索
        document.getElementById('stockCodeInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                searchValuation();
            }
        });
    </script>
</body>
</html>
    `;
}
