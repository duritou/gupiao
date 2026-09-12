"use strict";
/**
 * 研报管理页面
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildReportsPage = buildReportsPage;
function buildReportsPage(data) {
    const stockCode = data.stock_code || '';
    const reports = data.reports || [];
    const myReports = data.my_reports || [];
    const count = data.count || 0;
    const mode = data.mode || 'search'; // 'search' or 'my'
    const meta = data._meta || {};
    const sourceStatus = meta.available
        ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
        : (meta.error || (stockCode ? '研报数据源不可用' : '请输入股票代码查询'));
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
            background: linear-gradient(135deg, #2d5aa6 0%, #1a3d7a 100%);
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
        .hero .subtitle {
            color: rgba(255, 255, 255, 0.85);
            font-size: 14px;
        }
        .search-bar {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            align-items: center;
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
        .search-bar input:focus {
            outline: none;
            border-color: #007acc;
        }
        .search-bar button {
            padding: 10px 20px;
            background: #007acc;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        .search-bar button:hover {
            background: #005a9e;
        }
        .tab-bar {
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            border-bottom: 1px solid #3c3c3c;
        }
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            color: #d4d4d4;
            font-size: 14px;
        }
        .tab.active {
            border-bottom-color: #007acc;
            color: #007acc;
            font-weight: 500;
        }
        .reports-container {
            background: #252526;
            border-radius: 8px;
            padding: 20px;
        }
        .report-item {
            padding: 16px;
            border-bottom: 1px solid #3c3c3c;
            cursor: pointer;
            transition: background 0.2s;
        }
        .report-item:hover {
            background: #2d2d2d;
        }
        .report-item:last-child {
            border-bottom: none;
        }
        .report-title {
            font-size: 15px;
            font-weight: 500;
            color: #d4d4d4;
            margin-bottom: 8px;
        }
        .report-meta {
            display: flex;
            gap: 16px;
            font-size: 13px;
            color: #888;
            margin-bottom: 8px;
        }
        .report-actions {
            display: flex;
            gap: 8px;
            margin-top: 8px;
        }
        .report-actions button {
            padding: 6px 12px;
            background: #3c3c3c;
            color: #d4d4d4;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        .report-actions button:hover {
            background: #4c4c4c;
        }
        .report-actions button.primary {
            background: #007acc;
            color: white;
        }
        .report-actions button.primary:hover {
            background: #005a9e;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #888;
        }
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
    </style>
</head>
<body>
    <div class="hero">
        <h1>📊 研报管理</h1>
        <div class="subtitle">查询、收藏和管理研究报告</div>
        <div style="margin-top:10px;font-size:12px;color:${meta.available ? '#7ee787' : '#ffb86c'}">${sourceStatus}</div>
    </div>

    <div class="tab-bar">
        <div class="tab ${mode === 'search' ? 'active' : ''}" onclick="switchTab('search')">搜索研报</div>
        <div class="tab ${mode === 'my' ? 'active' : ''}" onclick="switchTab('my')">我的收藏</div>
    </div>

    ${mode === 'search' ? `
        <div class="search-bar">
            <input
                type="text"
                id="stockCodeInput"
                placeholder="输入股票代码（如：000001）"
                value="${stockCode}"
                onkeypress="if(event.key==='Enter') searchReports()"
            />
            <button onclick="searchReports()">搜索</button>
        </div>

        <div class="reports-container">
            ${reports.length > 0 ? `
                <div style="margin-bottom: 16px; color: #888; font-size: 13px;">
                    找到 ${count} 份研报
                </div>
                ${reports.map((report) => `
                    <div class="report-item">
                        <div class="report-title">${report.title || '无标题'}</div>
                        <div class="report-meta">
                            <span>📅 ${report.publish_date || '未知日期'}</span>
                            <span>✍️ ${report.author || '未知作者'}</span>
                            <span>🏢 ${report.institution || '未知机构'}</span>
                        </div>
                        <div class="report-actions">
                            <button class="primary" onclick="saveReport('${report.id}', '${stockCode}', '${(report.title || '').replace(/'/g, "\\'")}')">⭐ 收藏</button>
                        </div>
                    </div>
                `).join('')}
            ` : `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div>${!meta.available && meta.error ? meta.error : stockCode ? '未找到相关研报' : '请输入股票代码搜索研报'}</div>
                </div>
            `}
        </div>
    ` : `
        <div class="reports-container">
            ${myReports.length > 0 ? `
                <div style="margin-bottom: 16px; color: #888; font-size: 13px;">
                    共收藏 ${myReports.length} 份研报
                </div>
                ${myReports.map((report) => `
                    <div class="report-item">
                        <div class="report-title">${report.title || '无标题'}</div>
                        <div class="report-meta">
                            <span>📈 ${report.code || '未知代码'}</span>
                            <span>📅 ${report.saved_at || '未知时间'}</span>
                        </div>
                        <div class="report-actions">
                            <button class="primary" onclick="downloadReport('${report.rid}')">📥 下载</button>
                        </div>
                    </div>
                `).join('')}
            ` : `
                <div class="empty-state">
                    <div class="empty-state-icon">⭐</div>
                    <div>还没有收藏任何研报</div>
                </div>
            `}
        </div>
    `}

    <script>
        const vscode = acquireVsCodeApi();

        function switchTab(mode) {
            vscode.postMessage({ command: 'switchReportsTab', mode: mode });
        }

        function searchReports() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                alert('请输入股票代码');
                return;
            }
            vscode.postMessage({ command: 'searchReports', code: code });
        }

        function saveReport(rid, code, title) {
            vscode.postMessage({
                command: 'saveReport',
                rid: rid,
                code: code,
                title: title
            });
        }

        function downloadReport(rid) {
            vscode.postMessage({ command: 'downloadReport', rid: rid });
        }
    </script>
</body>
</html>
    `;
}
//# sourceMappingURL=reports.js.map