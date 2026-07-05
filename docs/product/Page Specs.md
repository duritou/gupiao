# Page Specifications — AI Research Terminal

> 每个页面的完整定义：目的、数据来源、布局、交互、状态。

---

## Page 1: Dashboard

**目的**: 用户每天打开软件的第一眼 — 30 秒了解市场全貌

**数据来源**:
- `GET /api/v1/market/overview` — 市场总览
- `POST /api/v1/scanner/run` — 今日机会
- `POST /api/v1/signals/batch` — 自选股评分

**刷新**: 60s 自动刷新（仅市场数据和自选股评分）

**布局**: 见 [Layout System.md — Dashboard Layout]

**必须展示**:
- [x] 4 个核心指标：上涨家数、下跌家数、成交额、北向资金
- [x] 今日热点板块（Top 5，含星级和状态）
- [x] 风险预警（类型 + 数量 + 严重程度）
- [x] 今日机会 Top 8（排名 + 名称 + 评分 + 方向）
- [x] 我的关注（自选股评分快照，最多 4 只）

**交互**:
- 点击热点板块 → Market Map 页面
- 点击机会股票 → Research 页面
- 点击自选股 → Research 页面

---

## Page 2: Watchlist

**目的**: 用户最高频使用的页面 — 持续监控自选股

**数据来源**:
- `POST /api/v1/signals/batch` — 批量评分
- `extensionContext.globalState` — 自选列表持久化

**刷新**: 30s 自动刷新（表格数据），页面不可见时暂停

**布局**: 见 [Layout System.md — Watchlist Layout]

**列定义**:
| # | 列 | 数据字段 | 格式 |
|---|-----|---------|------|
| 1 | 序号 | index | 数字 |
| 2 | 代码 | stock_code | 等宽字体 |
| 3 | 名称 | stock_name | 文本 |
| 4 | 最新价 | price | ¥1,420.00 |
| 5 | AI评分 | fusion_score | 整数，带颜色 |
| 6 | 趋势 | trend_arrow | ↑↑/↑/→/↓/↓↓ |
| 7 | 信号 | top_signal | Tag |
| 8 | 风险 | risk_level | 极低/低/中/高/极高 |

**交互**:
- 点击行 → Research 页面
- [+ 添加自选] → 输入框弹窗 → 添加 → 保存到 globalState
- 自动刷新有绿色脉冲指示器
- 评分变化时数字闪烁（绿色涨/红色跌，100ms）

**状态**:
- Empty: "暂无自选股，点击 + 添加自选 开始"
- Loading: Skeleton 表格（8 行占位）
- Error: "加载失败，请检查后端状态" + 重试按钮

---

## Page 3: Research (核心页面)

**目的**: 深度研究单个标的 — AI + 图表 + 数据一站式

**数据来源**:
- `GET /api/v1/detail/{code}?include=all` — 全量数据

**刷新**: 不自动刷新。用户手动切换 Tab / 周期。

**布局**: 见 [Layout System.md — Research Page Layout]

**内容结构** (从上到下):

### Top Bar
- 股票名称 + 代码 + 行业
- 当前价 + 涨跌幅 + 开盘 + 最高 + 最低
- 成交额 + 成交量 + 换手率 + PE + PB + 总市值 + 流通市值

### Tab Bar
```
[AI分析] [分时] [日K] [周K] [月K] [半年] [一年] [五年] [资金] [财务] [新闻] [公告] [研报]
```

### Main Area (70%)
- K 线图 (Candlestick)
- MA5/10/20/60 叠加
- 成交量
- MACD
- RSI
- KDJ
- BOLL (可选叠加)
- 4 个 Mini Trend Card (今日/本周/本月/近半年)

### Right Panel (30%)
- AI Score Card
- Radar Chart
- Evidence Chain (3-6 条)
- Risk Factors
- Key Indicators
- Fund Flow Chart

**Chart 交互**: 见 [Chart Specification.md]

**Tab 内容**:
- 资金 Tab: 北向/机构/大户/散户流向
- 财务 Tab: PE/PB/ROE/营收增长/利润增长 表格
- 新闻/公告/研报 Tab: 时间线列表

---

## Page 4: Market Map

**目的**: 行业轮动可视化 — 一眼看出哪些行业在涨

**数据来源**: `GET /api/v1/market/sectors`

**布局**:
```
3 列网格，每卡片: 行业名 + 评分 + 星级 + 进度条 + 状态标签
```

**排序**: 按评分降序

**颜色**: 强势 (≥70) 绿 · 震荡 (40-69) 黄 · 弱势 (<40) 红

**交互**: 点击行业卡片 → 过滤 Watchlist 或展示该行业龙头股

---

## Page 5: Compare

**目的**: 多股并排对比 — 快速决策

**数据来源**: `POST /api/v1/compare`

**布局**: 见 [Layout System.md — Compare Layout]

**输入**: 2 个股票代码输入框 + [对比] 按钮 + [+ 添加] 按钮（最多 6 只）

**对比维度**: AI评分 / MACD / RSI / 均线 / 成交量 / 估值 / 行业评分 / AI建议 / 风险等级

**交互**:
- 修改代码 → 点 [对比] → 刷新
- 点击表头股票名 → Research 页面
- Green checkmark = 看多，Red X = 看空

---

## Page 6: Timeline

**目的**: 看评分如何演变 + 为什么变化

**数据来源**: `GET /api/v1/timeline/{code}?days=30`

**布局**: 见 [Layout System.md — Timeline Layout]

**上半部分**: ASCII/Canvas 评分趋势图

**下半部分**: 最近 6 天变化列表，每天一个 Evidence 列表

**交互**:
- 输入股票代码 → [查看] → 刷新
- 点击日期 → 展开/折叠变化原因

---

## Page 7: Alert Center

**目的**: 实时接收信号预警

**数据来源**: `GET /api/v1/alerts/recent?limit=50`

**刷新**: 30s 自动刷新

**布局**: 见 [Layout System.md — Alert Center Layout]

**筛选**: [全部] [金叉/买入] [死叉/卖出] 按钮

**交互**:
- 点击 Alert → Research 页面
- 新 Alert 到达时 Toast 通知（右上角滑入）

---

## Page 8: Backtest

**目的**: 验证策略历史表现

**数据来源**: `POST /api/v1/backtest/run`

**布局**:
- 4 个核心指标: 年化收益 / 最大回撤 / 夏普比率 / 胜率
- 4 个辅助指标: 累计收益 / 初始资金 / 最终资金 / 交易次数
- 最近交易标记 (✔/✘ 网格)
- 交易明细表

---

## Page 9: Daily Brief

**目的**: 早盘简报 + 收盘复盘

**数据来源**: `GET /api/v1/dailybrief/latest`

**生成时机**: 每天 09:00 自动生成

**布局**: 见 [Layout System.md — Daily Brief Layout]

**交互**: 手动刷新按钮（重新生成）

---

## Page 10: Knowledge Base

**目的**: 行业知识库管理

**数据来源**: `GET /api/v1/knowledge/categories` + `/search`

**功能**:
- 搜索知识库
- 按分类浏览
- 查看单条知识详情

---

## Page 11: Settings

**目的**: 系统配置

**分区**:
- API 配置 (DeepSeek / OpenAI Key)
- 信号权重 (调整 MACD/RSI/KDJ 等权重)
- Prompt 管理 (查看/编辑/回滚 Prompt)
- 插件管理 (启用/禁用插件)
- 数据源配置
- 通知设置
