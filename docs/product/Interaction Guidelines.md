# Interaction Guidelines — AI Research Terminal

> 终端级交互规范。参考 Bloomberg Terminal 的键盘驱动 + TradingView 的图表交互。

---

## Navigation

### Page Switching
- 左侧导航点击 → 200ms 淡化切换
- `Alt+1~9` → 键盘切换页面
- 页面状态不丢失（Watchlist 选中的行、Research 的 Tab）

### Breadcrumb
- 不实现面包屑导航
- 左侧导航高亮足够表示当前位置

---

## Keyboard Shortcuts

### Global
| 快捷键 | 功能 |
|--------|------|
| `Alt+1` | Dashboard |
| `Alt+2` | Watchlist |
| `Alt+3` | Market Map |
| `Alt+4` | Research |
| `Alt+5` | Compare |
| `Alt+6` | Timeline |
| `Alt+7` | Alerts |
| `Alt+8` | Backtest |
| `Alt+9` | Daily Brief |
| `/` | 聚焦搜索框 |
| `Esc` | 关闭弹窗 / 取消操作 / 返回 |
| `Ctrl+R` | 手动刷新当前页 |
| `Space` | 暂停/恢复自动刷新 |
| `Ctrl+K` | 命令面板 |

### Research Page
| 快捷键 | 功能 |
|--------|------|
| `1-9` | 切换 Tab (AI分析/分时/日K/周K/...) |
| `←` / `→` | K线平移 |
| `+` / `-` | K线缩放 |
| `Alt` | 锁定十字光标 |
| 双击 | 重置 K 线视图 |

---

## Chart Interaction

### K-Line
- **缩放**: 鼠标滚轮 → 水平缩放
- **平移**: 拖拽 → 水平平移
- **十字光标**: 鼠标移动 → 竖线贯穿所有指标 + 浮动 OHLC 提示
- **锁定**: 按 `Alt` → 十字光标锁定在最后位置
- **重置**: 双击 → 回到默认视图

### Indicator Overlay
- 点击指标标签 (MA5/MA10/...) → 切换显示/隐藏
- 点击周期标签 (日K/周K/...) → 切换周期
- 所有指标状态记忆在 Tab 切换时保持

---

## Auto-Refresh

### Rules
- 仅在页面可见时刷新（`document.hidden` 时暂停）
- 仅在交易时段 (09:30-15:00 工作日) 全速刷新
- 非交易时段降速: Dashboard 5min, Watchlist 2min, Alerts 5min

### Visual Indicator
- 页面底部状态栏显示:
  ```
  ● 已连接  最后更新: 14:35:22  自动刷新: 30s
  ```
- 绿色圆点 = 自动刷新活跃
- 灰色圆点 = 自动刷新暂停
- 红色圆点 = 连接断开

### Data Change Animation
- Score 变化: 100ms 颜色闪烁（新值绿色闪，旧值红色闪）
- Alert 新增: 从顶部滑入，300ms ease-out
- 价格变化: 无动画（避免干扰盯盘）
- 列表重排: 无动画（瞬间更新）

---

## Loading States

### Skeleton
- 首次加载: 显示 Skeleton 占位（卡片形状的灰色块）
- 数据刷新: 不显示 Loading（静默更新，避免闪烁）
- Loading 不阻塞交互（用户可以在加载时切换页面）

### Error States
```
┌─────────────────────────────────┐
│                                 │
│         ⚠                       │
│    后端服务未启动                 │
│                                 │
│  请检查 Python 后端是否运行       │
│                                 │
│       [重试]  [启动后端]         │
│                                 │
└─────────────────────────────────┘
```

---

## Empty States

### Dashboard (无数据)
- "运行扫描以发现机会" + [运行扫描] 按钮

### Watchlist (无自选)
- "暂无自选股" + [+ 添加自选] 按钮

### Alert Center (无预警)
- "暂无预警" + "预警将在交易时段自动出现"

### Research (无数据)
- 显示股票基本信息 + "加载失败" 或 "暂无数据"

---

## Toast Notifications

### Types
- **Success**: 绿色 + ✓ 图标（"寒武纪 已添加到自选"）
- **Error**: 红色 + ✗ 图标（"加载失败，请重试"）
- **Alert**: 紫色 + 股票信息（"寒武纪 MACD金叉 91 ▲"）

### Behavior
- 右上角固定
- 3 秒后自动消失
- 点击 Toast → 跳转相关页面
- 最多同时显示 3 个
- 滑入动画 200ms ease-out

---

## Context Menu (右键)

### Table Row
```
[查看详情]  → Research 页面
[添加到自选]
[设置预警]
[对比...]   → Compare 页面
```

### K-Line Chart
```
[添加指标]     → MA/EMA/BOLL/SAR
[切换周期]     → 日K/周K/月K
[截图]        → 复制到剪贴板
[重置视图]
```

---

## Drag & Drop (v2.1)

- Watchlist 行拖拽排序
- 暂无其他拖拽交互

---

## Accessibility

- 所有颜色区分同时有色盲安全图标 (▲/▼ 替代纯颜色)
- 所有交互元素有键盘替代方案
- 屏幕阅读器: 股票代码、价格、评分有 aria-label

---

## Performance Targets

| 操作 | 目标 | 最差 |
|------|------|------|
| 页面切换 | < 200ms | < 500ms |
| K线渲染 (5000根) | < 100ms | < 300ms |
| Watchlist 刷新 | < 500ms | < 2s |
| Alert 通知延迟 | < 1s | < 5s |
| 搜索响应 | < 200ms | < 1s |
| 初始加载 (Dashboard) | < 1s | < 3s |
