"use strict";
/**
 * 资金流向页面
 * 显示股票的资金流入流出数据
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildFundflowPage = buildFundflowPage;
function buildFundflowPage(data) {
    const fundflow = data?.fundflow || {};
    const code = data?.code || '';
    const meta = data?._meta || {};
    const statusText = meta.is_proxy
        ? `${meta.warning || '当前展示资金流代理指标'} · 获取时间 ${meta.fetched_at || '--'}`
        : meta.available
            ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
            : (meta.error || (code ? '资金流数据源不可用' : '请输入股票代码查询'));
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
        .fundflow-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .fundflow-card {
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
        }
        .card-value.positive {
            color: #f14c4c;
        }
        .card-value.negative {
            color: #73c991;
        }
        .card-value.neutral {
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
            <button onclick="searchFundflow()">查询资金流</button>
        </div>
    </div>

    ${Object.keys(fundflow).length > 0 ? `
        <div class="stock-header">
            <div class="stock-code">${code}</div>
            <div class="stock-name">${fundflow.name || '股票资金流向'}</div>
        </div>

        <div class="fundflow-grid">
            ${fundflow.main_net !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">主力资金净流入</div>
                    <div class="card-value ${fundflow.main_net > 0 ? 'positive' : fundflow.main_net < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.main_net > 0 ? '+' : ''}${(fundflow.main_net / 10000)?.toFixed(2) || '--'}<span class="card-unit">万</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.super_large_net !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">超大单净流入</div>
                    <div class="card-value ${fundflow.super_large_net > 0 ? 'positive' : fundflow.super_large_net < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.super_large_net > 0 ? '+' : ''}${(fundflow.super_large_net / 10000)?.toFixed(2) || '--'}<span class="card-unit">万</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.large_net !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">大单净流入</div>
                    <div class="card-value ${fundflow.large_net > 0 ? 'positive' : fundflow.large_net < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.large_net > 0 ? '+' : ''}${(fundflow.large_net / 10000)?.toFixed(2) || '--'}<span class="card-unit">万</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.medium_net !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">中单净流入</div>
                    <div class="card-value ${fundflow.medium_net > 0 ? 'positive' : fundflow.medium_net < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.medium_net > 0 ? '+' : ''}${(fundflow.medium_net / 10000)?.toFixed(2) || '--'}<span class="card-unit">万</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.small_net !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">小单净流入</div>
                    <div class="card-value ${fundflow.small_net > 0 ? 'positive' : fundflow.small_net < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.small_net > 0 ? '+' : ''}${(fundflow.small_net / 10000)?.toFixed(2) || '--'}<span class="card-unit">万</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.main_net_pct !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">${fundflow.proxy_type === 'active_trade_ratio' ? '主动买卖盘差额占比（代理）' : '主力净流入占比'}</div>
                    <div class="card-value ${fundflow.main_net_pct > 0 ? 'positive' : fundflow.main_net_pct < 0 ? 'negative' : 'neutral'}">
                        ${fundflow.main_net_pct > 0 ? '+' : ''}${fundflow.main_net_pct?.toFixed(2) || '--'}<span class="card-unit">%</span>
                    </div>
                </div>
            ` : ''}

            ${fundflow.outer_volume_lots !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">外盘成交量</div>
                    <div class="card-value neutral">${Number(fundflow.outer_volume_lots || 0).toFixed(0)}<span class="card-unit">手</span></div>
                </div>
            ` : ''}

            ${fundflow.inner_volume_lots !== undefined ? `
                <div class="fundflow-card">
                    <div class="card-label">内盘成交量</div>
                    <div class="card-value neutral">${Number(fundflow.inner_volume_lots || 0).toFixed(0)}<span class="card-unit">手</span></div>
                </div>
            ` : ''}
        </div>
    ` : `
        <div class="empty-state">
            ${code ? (meta.available ? '该股票暂无资金流数据' : statusText) : '请输入股票代码查询资金流数据'}
        </div>
    `}

    <script>
        const vscode = acquireVsCodeApi();

        function searchFundflow() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                return;
            }
            vscode.postMessage({
                command: 'searchFundflow',
                code: code
            });
        }

        // 回车键搜索
        document.getElementById('stockCodeInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                searchFundflow();
            }
        });
    </script>
</body>
</html>
    `;
}
//# sourceMappingURL=fundflow.js.map