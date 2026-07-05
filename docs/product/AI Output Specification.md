# AI Output Specification — AI Research Terminal

> AI 的所有输出必须使用结构化模板。禁止自由文本。
> AI 填内容，模板管结构。

---

## Core Rule

```
AI 输出 = 固定模板 + AI 填充数据 + 人做决策
```

**AI 禁止**:
- ❌ "我觉得可以买"
- ❌ "建议强烈关注"
- ❌ "这是一只好股票"
- ❌ 任何没有数据的判断
- ❌ 任何没有置信度的结论

**AI 必须**:
- ✓ 每个结论附带 Evidence
- ✓ 每个 Evidence 附带可信度
- ✓ 每个 Score 附带计算依据
- ✓ 每个 Risk 附带具体原因

---

## Template 1: AI Score Card

**位置**: Research 页面右侧面板顶部

```yaml
template: ai_score_card
fields:
  score:
    type: integer
    range: 0-100
    source: SignalFusion weighted average
  stars:
    type: integer
    range: 1-5
    mapping:
      80-100: 5
      65-79: 4
      50-64: 3
      35-49: 2
      0-34: 1
  recommendation:
    type: enum
    values: [STRONG_BUY, BUY, WATCH, REDUCE, SELL]
    mapping:
      85-100: STRONG_BUY
      70-84: BUY
      50-69: WATCH
      35-49: REDUCE
      0-34: SELL
  confidence:
    type: integer
    range: 0-100
    unit: "%"
    source: Signal agreement rate × score deviation
```

---

## Template 2: Evidence Chain

**位置**: AI Score Card 下方

```yaml
template: evidence_chain
max_items: 6
fields_per_item:
  icon:
    type: enum
    values: [check, warning, info, star]
  title:
    type: string
    max_length: 30
    example: "MACD形成金叉"
  description:
    type: string
    max_length: 80
    example: "DIF线从下方上穿DEA线，短期趋势转强"
  credibility:
    type: integer
    range: 0-100
    unit: "%"
  score_impact:
    type: float
    unit: "分"
    example: "+12" / "-5"
  source:
    type: enum
    values: [signal, knowledge, market, news, financial]
    example: "MACD Signal" / "Knowledge:半导体"
  timestamp:
    type: ISO datetime

rules:
  - 最少 3 条 evidence，最多 6 条
  - 按可信度降序排列
  - 可信度 < 60% 的 evidence 降级为 warning icon
  - signal 类型的 evidence 必须关联具体指标
```

**示例输出**:
```
✓ MACD形成金叉                    可信度 95%
  DIF上穿DEA，柱状图由绿转红
  来源: MACD Signal    贡献: +12分

✓ MA20上穿MA60                    可信度 88%
  短期均线上穿长期均线，多头趋势确认
  来源: MA Signal      贡献: +8分

✓ 半导体行业景气度提升              可信度 90%
  全球芯片需求增长15%，行业处于上行周期
  来源: Knowledge:半导体  贡献: +6分

✓ 今日成交量放大180%               可信度 82%
  高于20日均量，资金入场明显
  来源: Volume Signal   贡献: +5分
```

---

## Template 3: Risk Factors

**位置**: Evidence Chain 下方

```yaml
template: risk_factors
max_items: 5
fields_per_item:
  severity:
    type: enum
    values: [high, medium, low]
  description:
    type: string
    max_length: 50
    example: "PE高于行业平均水平"

rules:
  - 至少列出 1 条风险
  - high severity 风险必须标注具体数值
  - 不允许 "无风险" 输出
```

**示例输出**:
```
⚠ 风险因素
  ● PE 128.5，高于行业均值 45.2        [高风险]
  ● 短期涨幅 32%，追高风险较大           [中风险]
  ● 压力位 ¥275 附近                   [低风险]
  ● Q3 业绩预告尚未发布                  [低风险]
```

---

## Template 4: Radar Dimensions

**位置**: 右侧 AI 面板，Score 下方

```yaml
template: radar_chart
dimensions:
  - name: 技术面
    key: technical
    source: avg(MACD, RSI, MA, KDJ, BOLL scores)
    range: 0-100
  - name: 基本面
    key: fundamental
    source: weighted(PE, PB, ROE, revenue_growth, profit_growth)
    range: 0-100
  - name: 资金面
    key: capital
    source: weighted(northbound, institutional, retail flow)
    range: 0-100
  - name: 行业面
    key: industry
    source: sector score from knowledge base
    range: 0-100
  - name: 情绪面
    key: sentiment
    source: news sentiment + social media (future)
    range: 0-100
```

---

## Template 5: Key Indicators Summary

**位置**: 右侧 AI 面板底部

```yaml
template: key_indicators
fields:
  - name: MACD
    value: "金叉" | "死叉" | "中性"
    detail: "DIF: +0.12  DEA: +0.08"
  - name: RSI
    value: integer (0-100)
    detail: "超买" | "超卖" | "健康"
  - name: MA状态
    value: "多头排列" | "空头排列" | "横盘整理"
    detail: "MA5>MA20>MA60"
  - name: 成交量
    value: "放量" | "缩量" | "正常"
    detail: "较20日均量 +180%"
  - name: 北向资金
    value: "+2.3亿" | "-0.5亿"
    detail: "连续3日净流入"
  - name: 行业排名
    value: "#2 / 45"
    detail: "半导体行业"
```

---

## Template 6: Daily Brief

**位置**: Daily Brief 页面，每天 09:00 自动生成

```yaml
template: daily_brief
sections:
  - header:
      date: ISO date
      day_of_week: string
      sentiment_stars: 1-5
      sentiment_score: 0-100
      sentiment_label: "积极" | "中性" | "谨慎"

  - market_summary:
      up_count: integer
      down_count: integer
      total_volume: string (万亿)
      northbound: string (+亿 / -亿)
      indices:
        - name: 上证指数
          value: float
          change_pct: float
        - name: 深证成指
          value: float
          change_pct: float
        - name: 创业板指
          value: float
          change_pct: float

  - hot_sectors:
      max_items: 5
      fields: [name, stars, score]

  - top_opportunities:
      max_items: 3
      fields: [rank, stock_code, stock_name, score, direction, reason]

  - risk_warnings:
      max_items: 3
      type: string[]

  - one_liner:
      type: string
      max_length: 100
      generated_by: AI (LLM)

rules:
  - 09:00 自动生成
  - 数据来自当日 mock_data / 真实数据
  - one_liner 由 LLM 生成，其余字段由规则引擎生成
```

---

## Template 7: Alert Notification

**位置**: Alert Center 页面 + Toast 通知

```yaml
template: alert
fields:
  id: string
  time: "HH:MM"
  stock_code: string
  stock_name: string
  alert_type:
    type: enum
    values: [MACD金叉, MACD死叉, 放量突破, 跌破MA20, 跌破MA60,
             MA多头排列, RSI超卖, RSI超买, 北向加仓, 北向减仓,
             KDJ金叉, KDJ死叉, BOLL突破上轨, BOLL跌破下轨]
  score: integer
  direction: "up" | "down"
  read: boolean

rules:
  - 交易时段 (09:30-15:00) 实时生成
  - 同一股票同一类型 30 分钟内不重复
  - 新 Alert 出现时 Toast 通知
```

---

## Template 8: Compare Output

**位置**: Compare 页面

```yaml
template: compare
max_stocks: 6
fields_per_stock:
  - ai_score
  - direction
  - confidence
  - macd: "金叉" | "死叉" | "中性"
  - rsi: integer
  - ma_status: "多头" | "空头" | "横盘"
  - volume_status: "放量" | "缩量" | "正常"
  - valuation: "偏高" | "合理" | "偏低"
  - industry_score: integer
  - recommendation: string
  - risk_level: "极低" | "低" | "中" | "高" | "极高"
```

---

## Format Enforcement

**后端职责**: 生成结构化 JSON，不生成 Markdown/文本

**前端职责**: 根据 JSON 渲染为固定模板 UI

**LLM 职责**: 仅填充 `one_liner`（日报一句话）和 `evidence.description`（证据描述），其余字段由规则引擎计算

**绝对禁止**: LLM 直接生成 HTML、完整报告、或绕过固定模板的任何输出
