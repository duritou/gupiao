"use strict";
/**
 * 龙虎榜页面
 * 显示股票的龙虎榜数据
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildDragonTigerPage = buildDragonTigerPage;
function buildDragonTigerPage(data) {
    const dragonTiger = data?.dragon_tiger || {};
    const code = data?.code || '';
    const meta = data?._meta || {};
    const statusText = meta.available
        ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
        : (meta.error || (code ? '龙虎榜数据源不可用' : '请输入股票代码查询'));
    const records = dragonTiger.records || [];
    const seats = dragonTiger.seats || { buy: [], sell: [] };
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
        .records-section {
            margin-bottom: 20px;
        }
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--vscode-foreground);
            margin-bottom: 10px;
            padding-left: 5px;
        }
        .record-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .record-item {
            padding: 12px 15px;
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .record-date {
            font-size: 13px;
            font-weight: 600;
            color: var(--vscode-foreground);
        }
        .record-reason {
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            margin-top: 4px;
        }
        .seats-section {
            margin-top: 20px;
        }
        .seats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .seats-panel {
            padding: 15px;
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
        }
        .panel-title {
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 10px;
        }
        .panel-title.buy {
            color: #f14c4c;
        }
        .panel-title.sell {
            color: #73c991;
        }
        .seat-item {
            display: flex;
            justify-content: space-between;
            padding: 8px;
            background: var(--vscode-input-background);
            border-radius: 3px;
            font-size: 12px;
            margin-bottom: 6px;
        }
        .seat-name {
            flex: 1;
            color: var(--vscode-foreground);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .seat-amount {
            color: var(--vscode-descriptionForeground);
            margin-left: 10px;
        }
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--vscode-descriptionForeground);
        }
    </style>
</head>
<body>
    <div style="margin-bottom:12px;font-size:12px;color:${meta.available ? '#73c991' : '#cca700'}">${statusText}</div>
    <div class="search-section">
        <div class="search-box">
            <input type="text" id="stockCodeInput" placeholder="输入股票代码（如 000001）" value="${code}">
            <button onclick="searchDragonTiger()">查询龙虎榜</button>
        </div>
    </div>

    ${records.length > 0 ? `
        <div class="stock-header">
            <div class="stock-code">${code}</div>
            <div class="stock-name">${dragonTiger.name || '龙虎榜数据'}</div>
        </div>

        <div class="records-section">
            <div class="section-title">上榜记录</div>
            <div class="record-list">
                ${records.map((record) => `
                    <div class="record-item">
                        <div>
                            <div class="record-date">${record.date || '--'}</div>
                            <div class="record-reason">${record.reason || '上榜'}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>

        ${(seats.buy && seats.buy.length > 0) || (seats.sell && seats.sell.length > 0) ? `
            <div class="seats-section">
                <div class="section-title">营业部汇总 Top5</div>
                <div class="seats-grid">
                    <div class="seats-panel">
                        <div class="panel-title buy">买入营业部</div>
                        ${(seats.buy || []).slice(0, 5).map((seat) => `
                            <div class="seat-item">
                                <div class="seat-name" title="${seat.name}">${seat.name}</div>
                                <div class="seat-amount">${((seat.buy_amt || 0) / 10000).toFixed(2)}万</div>
                            </div>
                        `).join('') || '<div class="seat-item"><div class="seat-name">暂无数据</div></div>'}
                    </div>
                    <div class="seats-panel">
                        <div class="panel-title sell">卖出营业部</div>
                        ${(seats.sell || []).slice(0, 5).map((seat) => `
                            <div class="seat-item">
                                <div class="seat-name" title="${seat.name}">${seat.name}</div>
                                <div class="seat-amount">${((seat.sell_amt || 0) / 10000).toFixed(2)}万</div>
                            </div>
                        `).join('') || '<div class="seat-item"><div class="seat-name">暂无数据</div></div>'}
                    </div>
                </div>
            </div>
        ` : ''}
    ` : `
        <div class="empty-state">
            ${code ? (meta.available ? '该股票近期没有龙虎榜记录' : statusText) : '请输入股票代码查询龙虎榜数据'}
        </div>
    `}

    <script>
        const vscode = acquireVsCodeApi();

        function searchDragonTiger() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                return;
            }
            vscode.postMessage({
                command: 'searchDragonTiger',
                code: code
            });
        }

        // 回车键搜索
        document.getElementById('stockCodeInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                searchDragonTiger();
            }
        });
    </script>
</body>
</html>
    `;
}
//# sourceMappingURL=dragon_tiger.js.map