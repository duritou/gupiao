# Design Tokens — AI Research Terminal

> 所有 AI 生成的 UI 必须严格使用此处定义的 Token。不允许自行创造颜色、字号、间距。

---

## Color System

### Background

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-root` | `#0B1220` | 页面根背景 |
| `--bg-panel` | `#111827` | 卡片、面板 |
| `--bg-elevated` | `#1A2332` | 悬浮面板、弹窗 |
| `--bg-input` | `#0F1729` | 输入框背景 |
| `--bg-hover` | `#1E293B` | 行悬停 |

### Border

| Token | Value | Usage |
|-------|-------|-------|
| `--border-default` | `#1F2937` | 默认边框 |
| `--border-subtle` | `#374151` | 分割线 |
| `--border-active` | `#3B82F6` | 选中/聚焦边框 |

### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#F3F4F6` | 正文 |
| `--text-secondary` | `#9CA3AF` | 次要文字 |
| `--text-muted` | `#6B7280` | 辅助信息 |
| `--text-link` | `#60A5FA` | 链接 |

### Semantic (Finance)

| Token | Value | Meaning |
|-------|-------|---------|
| `--up` | `#22C55E` | 上涨 (A股绿) |
| `--down` | `#EF4444` | 下跌 (A股红) |
| `--flat` | `#9CA3AF` | 平盘 |

### Semantic (AI)

| Token | Value | Meaning |
|-------|-------|---------|
| `--ai-primary` | `#7C3AED` | AI 主色 |
| `--ai-light` | `#A78BFA` | AI 辅助 |
| `--ai-bg` | `#1A1030` | AI 面板背景 |

### Semantic (Alert)

| Token | Value | Meaning |
|-------|-------|---------|
| `--warning` | `#F59E0B` | 警告 |
| `--danger` | `#EF4444` | 危险 |
| `--success` | `#22C55E` | 成功 |
| `--info` | `#3B82F6` | 信息 |

### Tag / Badge

| Token | Background | Text | Border |
|-------|-----------|------|--------|
| `--tag-buy` | `#052E16` | `#22C55E` | `#166534` |
| `--tag-sell` | `#450A0A` | `#EF4444` | `#991B1B` |
| `--tag-neutral` | `#1E293B` | `#9CA3AF` | `#374151` |
| `--tag-ai` | `#1A1030` | `#A78BFA` | `#4C1D95` |
| `--tag-warning` | `#422006` | `#F59E0B` | `#92400E` |

---

## Typography

### Font Family

| Usage | Font |
|-------|------|
| UI 中文 | `'PingFang SC', 'Microsoft YaHei', sans-serif` |
| UI 英文 | `'Inter', 'Segoe UI', system-ui, sans-serif` |
| 数字/价格 | `'JetBrains Mono', 'SF Mono', 'Consolas', monospace` |
| 代码/数据 | `'JetBrains Mono', monospace` |

### Scale

| Token | Size | Line Height | Usage |
|-------|------|-------------|-------|
| `--text-xs` | 11px | 16px | 辅助、标签 |
| `--text-sm` | 13px | 20px | 表格、列表 |
| `--text-base` | 14px | 22px | 正文 |
| `--text-lg` | 16px | 24px | 小标题 |
| `--text-xl` | 20px | 28px | 面板标题 |
| `--text-2xl` | 24px | 32px | 页面标题 |
| `--text-3xl` | 36px | 44px | AI Score |
| `--text-4xl` | 48px | 56px | Hero 数字 |

### Weight

| Token | Value | Usage |
|-------|-------|-------|
| `--font-normal` | 400 | 正文 |
| `--font-medium` | 500 | 强调 |
| `--font-semibold` | 600 | 标题、数字 |
| `--font-bold` | 700 | Score、重要指标 |

---

## Spacing

### Scale (4px base)

```
4, 8, 12, 16, 24, 32, 48, 64
```

### Rules

- 禁止使用非 4 的倍数的间距值
- 禁止: `padding: 13px`, `margin: 19px`, `gap: 7px`
- 卡片内边距统一 `16px`
- 页面内边距统一 `24px`
- 区块间距统一 `16px`

### Layout Widths

| Element | Width |
|---------|-------|
| 左侧导航 | 220px |
| 右侧 AI 面板 | 320px |
| 主内容区 | flex 填充 |
| 最小窗口宽度 | 1280px |

---

## Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 4px | 标签、徽章 |
| `--radius-md` | 6px | 按钮、输入框 |
| `--radius-lg` | 8px | 卡片、面板 |
| `--radius-full` | 9999px | 药丸形状 |

---

## Elevation / Shadow

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-none` | none | 默认 |
| `--shadow-card` | `0 1px 3px rgba(0,0,0,0.3)` | 卡片 |
| `--shadow-dropdown` | `0 4px 12px rgba(0,0,0,0.4)` | 下拉菜单 |
| `--shadow-modal` | `0 8px 24px rgba(0,0,0,0.5)` | 弹窗 |

---

## Motion

| Token | Duration | Easing | Usage |
|-------|----------|--------|-------|
| `--duration-instant` | 0ms | — | 无动画 |
| `--duration-fast` | 100ms | ease-out | Hover |
| `--duration-normal` | 200ms | ease-in-out | 页面切换、面板展开 |
| `--duration-slow` | 400ms | ease-in-out | 图表动画 |

### Rules

- 数字变化: 100ms 颜色闪烁（绿涨红跌）
- 页面切换: 200ms 淡化
- 列表加载: Skeleton 占位，无动画
- 不使用的动画: 弹跳、旋转、脉冲（除实时指示器）

---

## Iconography

- 使用 VS Code Codicons（`$(icon-name)`）
- 不使用 emoji 作为功能图标
- 图标颜色跟随文字颜色
- 图标大小: 16px (默认), 20px (导航)

---

## Data Format

| 数据 | 格式 | 示例 |
|------|------|------|
| 价格 | `¥1,420.00` | 小数点后 2 位 |
| 涨跌幅 | `+3.25%` / `-1.08%` | 带符号，2 位小数 |
| 成交额 | `1.43万亿` / `856亿` | 中文单位 |
| 成交量 | `125.6万手` | 中文单位 |
| 市值 | `2.38万亿` / `456亿` | 中文单位 |
| Score | `92` | 整数，0-100 |
| 置信度 | `91%` | 整数百分比 |
| 日期 | `2026-07-06` | ISO 格式 |
| 时间 | `14:35:22` | 24 小时制 |
