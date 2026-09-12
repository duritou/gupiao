"use strict";
/**
 * 财务数据页面
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildFinancialsPage = buildFinancialsPage;
function buildFinancialsPage(data) {
    const stockCode = data.stock_code || '';
    const financials = data.financials || {};
    const meta = data._meta || {};
    const hasData = Object.keys(financials).length > 0;
    const statusText = meta.available
        ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
        : (meta.error || (stockCode ? '财务数据源不可用' : '请输入股票代码查询'));
    return `
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            padding: 20px;
            background: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
        }
        .hero {
            background: linear-gradient(135deg, #1e88e5 0%, #0d47a1 100%);
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .hero h1 {
            margin: 0 0 12px 0;
            font-size: 28px;
            font-weight: 600;
            color: #ffffff;
        }
        .search-bar {
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }
        .search-bar input {
            flex: 1;
            padding: 10px 14px;
            border: 1px solid #3c3c3c;
            border-radius: 6px;
            background: #2d2d2d;
            color: #d4d4d4;
            font-size: 14px;
        }
        .search-bar button {
            padding: 10px 20px;
            background: #1e88e5;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .metric-card {
            background: #252526;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #1e88e5;
        }
        .metric-label {
            font-size: 12px;
            color: #888;
            margin-bottom: 8px;
        }
        .metric-value {
            font-size: 24px;
            font-weight: 600;
            color: #d4d4d4;
        }
        .metric-change {
            font-size: 13px;
            margin-top: 4px;
        }
        .positive { color: #4caf50; }
        .negative { color: #f44336; }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #888;
        }
    </style>
</head>
<body>
    <div class="hero">
        <h1>💰 财务数据</h1>
        <div style="margin-top:10px;font-size:12px;color:${meta.available ? '#7ee787' : '#ffb86c'}">${statusText}</div>
    </div>

    <div class="search-bar">
        <input
            type="text"
            id="stockCodeInput"
            placeholder="输入股票代码（如：000001）"
            value="${stockCode}"
            onkeypress="if(event.key==='Enter') searchFinancials()"
        />
        <button onclick="searchFinancials()">查询</button>
    </div>

    ${hasData ? `
        <div style="margin-bottom: 16px; color: #888; font-size: 13px;">
            ${stockCode} - 财报期：${financials.period || '未知'}
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">营业收入</div>
                <div class="metric-value">${financials.revenue || '-'}</div>
                <div class="metric-change ${parseFloat(financials.revenue_yoy) > 0 ? 'positive' : 'negative'}">
                    同比 ${financials.revenue_yoy || '-'}
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-label">净利润</div>
                <div class="metric-value">${financials.net_profit || '-'}</div>
                <div class="metric-change ${parseFloat(financials.net_profit_yoy) > 0 ? 'positive' : 'negative'}">
                    同比 ${financials.net_profit_yoy || '-'}
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-label">每股收益 (EPS)</div>
                <div class="metric-value">${financials.eps || '-'}</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">净资产收益率 (ROE)</div>
                <div class="metric-value">${financials.roe || '-'}</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">每股净资产 (BVPS)</div>
                <div class="metric-value">${financials.bvps || '-'}</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">销售净利率</div>
                <div class="metric-value">${financials.net_margin || '-'}</div>
            </div>
        </div>
    ` : `
        <div class="empty-state">
            <div style="font-size: 48px; margin-bottom: 16px; opacity: 0.5;">📊</div>
            <div>${stockCode ? (meta.available ? '该股票暂无财务数据' : statusText) : '请输入股票代码查询财务数据'}</div>
        </div>
    `}

    <script>
        const vscode = acquireVsCodeApi();

        function searchFinancials() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                alert('请输入股票代码');
                return;
            }
            vscode.postMessage({ command: 'searchFinancials', code: code });
        }
    </script>
</body>
</html>
    `;
}
//# sourceMappingURL=financials.js.map