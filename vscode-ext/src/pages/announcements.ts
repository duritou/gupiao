/**
 * 公告中心页面
 */

export function buildAnnouncementsPage(data: any): string {
    const stockCode = data.stock_code || '';
    const announcements = data.announcements || [];
    const count = data.count || 0;
    const mode = data.mode || 'search'; // 'latest' or 'search'
    const meta = data._meta || {};
    const sourceStatus = meta.available
        ? `数据源正常 · 获取时间 ${meta.fetched_at || '--'}`
        : (meta.error || '公告数据源不可用');

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
            background: linear-gradient(135deg, #6a4c93 0%, #4a2c6d 100%);
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
            border-color: #6a4c93;
        }
        .search-bar button {
            padding: 10px 20px;
            background: #6a4c93;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        .search-bar button:hover {
            background: #5a3c83;
        }
        .search-bar button.secondary {
            background: #3c3c3c;
        }
        .search-bar button.secondary:hover {
            background: #4c4c4c;
        }
        .announcements-container {
            background: #252526;
            border-radius: 8px;
            padding: 20px;
        }
        .announcement-item {
            padding: 16px;
            border-bottom: 1px solid #3c3c3c;
            cursor: pointer;
            transition: background 0.2s;
        }
        .announcement-item:hover {
            background: #2d2d2d;
        }
        .announcement-item:last-child {
            border-bottom: none;
        }
        .announcement-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }
        .announcement-title {
            font-size: 15px;
            font-weight: 500;
            color: #d4d4d4;
            flex: 1;
        }
        .announcement-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
            margin-left: 12px;
            white-space: nowrap;
        }
        .badge-important {
            background: #d32f2f;
            color: white;
        }
        .badge-regular {
            background: #1976d2;
            color: white;
        }
        .badge-other {
            background: #616161;
            color: white;
        }
        .announcement-meta {
            display: flex;
            gap: 16px;
            font-size: 13px;
            color: #888;
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
        <h1>📢 公告中心</h1>
        <div class="subtitle">按股票代码查询公司公告</div>
        <div style="margin-top:10px;font-size:12px;color:${meta.available ? '#7ee787' : '#ffb86c'}">${sourceStatus}</div>
    </div>

    <div class="search-bar">
        <input
            type="text"
            id="stockCodeInput"
            placeholder="输入股票代码查询公告（如：000001）"
            value="${stockCode}"
            onkeypress="if(event.key==='Enter') searchAnnouncements()"
        />
        <button onclick="searchAnnouncements()">搜索</button>
    </div>

    <div class="announcements-container">
        ${announcements.length > 0 ? `
            <div style="margin-bottom: 16px; color: #888; font-size: 13px;">
                ${mode === 'search' ? `${stockCode} - 找到 ${count} 条公告` : `最新公告 (${announcements.length} 条)`}
            </div>
            ${announcements.map((ann: any) => {
                const typeClass = ann.importance === 'high' ? 'badge-important' :
                                 ann.type === '定期报告' ? 'badge-regular' : 'badge-other';
                return `
                    <div class="announcement-item">
                        <div class="announcement-header">
                            <div class="announcement-title">${ann.title || '无标题'}</div>
                            <span class="announcement-badge ${typeClass}">${ann.type || '公告'}</span>
                        </div>
                        <div class="announcement-meta">
                            <span>📅 ${ann.publish_date || '未知日期'}</span>
                            ${ann.stock_code ? `<span>📈 ${ann.stock_code}</span>` : ''}
                            ${ann.stock_name ? `<span>${ann.stock_name}</span>` : ''}
                        </div>
                    </div>
                `;
            }).join('')}
        ` : `
            <div class="empty-state">
                <div class="empty-state-icon">📄</div>
                <div>${!meta.available && meta.error ? meta.error : stockCode ? '未找到相关公告' : mode === 'search' ? '请输入股票代码查询公告' : '暂无最新公告'}</div>
            </div>
        `}
    </div>

    <script>
        const vscode = acquireVsCodeApi();

        function searchAnnouncements() {
            const code = document.getElementById('stockCodeInput').value.trim();
            if (!code) {
                alert('请输入股票代码');
                return;
            }
            vscode.postMessage({ command: 'searchAnnouncements', code: code });
        }

    </script>
</body>
</html>
    `;
}
