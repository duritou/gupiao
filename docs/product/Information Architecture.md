# Information Architecture — AI Research Terminal

## Page Hierarchy

```
AI Research Terminal
│
├── 1. Dashboard          (首页 · 市场总览)
│
├── 2. Watchlist          (自选股 · 实时监控)
│   └── → Research Page   (点击任意股票)
│
├── 3. Market Map         (行业热力图)
│   └── → Research Page   (点击行业 → 龙头股)
│
├── 4. Research           (个股深度研究)
│   ├── Tab: AI 分析
│   ├── Tab: K线 (分时/日K/周K/月K)
│   ├── Tab: 资金流向
│   ├── Tab: 财务报表
│   ├── Tab: 新闻/公告/研报
│   └── Tab: 知识库
│
├── 5. Compare            (多股对比)
│
├── 6. Timeline           (评分演变)
│
├── 7. Alert Center       (预警中心)
│
├── 8. Backtest           (策略回测)
│
├── 9. Daily Brief        (每日简报)
│
├── 10. Knowledge Base    (知识库管理)
│
└── 11. Settings          (设置)
    ├── API 配置
    ├── 信号权重
    ├── Prompt 管理
    ├── 插件管理
    └── 数据源配置
```

## Navigation Structure

### Primary Navigation (左侧常驻)

```
┌─────────────────┐
│  📊 Dashboard    │  ← 默认页
│  ⭐ Watchlist    │  ← 最高频
│  🗺 Market Map   │
│  🔬 Research     │  ← 核心页
│  ⚖ Compare      │
│  📈 Timeline     │
│  🔔 Alerts       │  ← 高频
│  ⏮ Backtest     │
│  📰 Daily Brief  │
│  📚 Knowledge    │
│  ⚙ Settings      │
└─────────────────┘
```

### Secondary Navigation (页面内 Tab)

Research 页面内部:
```
[AI分析] [K线] [资金] [财务] [新闻] [公告] [研报]
```

### Breadcrumb

```
Dashboard > 半导体 > 寒武纪
Watchlist > 贵州茅台
```

## Page States

每个页面有三种状态:

| State | 触发条件 | 展示 |
|-------|---------|------|
| **Loading** | 首次加载 / 数据请求中 | Skeleton 占位 |
| **Ready** | 数据加载成功 | 正常内容 |
| **Empty** | 无数据 | 引导提示 |
| **Error** | 请求失败 / 后端离线 | 错误提示 + 重试按钮 |

## Data Flow

```
Python Backend (localhost:8888)
    │
    │  REST API (JSON)
    │
    ▼
VS Code Extension Host
    │
    │  postMessage
    │
    ▼
Webview (HTML/CSS/JS)
    │
    │  DOM Update
    │
    ▼
User Sees UI
```

### Auto-Refresh Strategy

| 页面 / 区域 | 刷新频率 | 方式 |
|------------|---------|------|
| Dashboard 市场数据 | 60s | setInterval → API → DOM update |
| Watchlist 评分 | 30s | setInterval → batch API → DOM update |
| Alert Center | 30s | setInterval → API → 新 Alert 淡入 |
| Research K线 | 手动 | 用户切换周期 → API |
| AI 分析 | 手动 | 用户点击"刷新分析" |
| Daily Brief | 1次/天 | 09:00 自动生成 |

## Keyboard Shortcuts

| 快捷键 | 功能 |
|--------|------|
| `Alt+1` | Dashboard |
| `Alt+2` | Watchlist |
| `Alt+3` | Market Map |
| `Alt+4` | Research |
| `Alt+5` | Compare |
| `Alt+6` | Alerts |
| `/` | 搜索股票 |
| `Esc` | 关闭弹窗 / 返回 |
| `Ctrl+R` | 手动刷新当前页 |
| `Space` | 暂停/恢复自动刷新 |
