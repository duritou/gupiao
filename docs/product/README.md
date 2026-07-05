# AI Research Terminal — Product Design System v2.0

> **AI 驱动的专业股票研究终端** — 产品设计规范。

---

## 文档索引

### 基础

| 文档 | 内容 |
|------|------|
| [Product Vision](Product%20Vision.md) | 产品定义、定位、对标产品、核心差异化 |
| [Design Principles](Design%20Principles.md) | 10 条设计原则，所有决策的依据 |
| [Design Tokens](Design%20Tokens.md) | 颜色、字体、间距、圆角、阴影、动效 |
| [User Flow](User%20Flow.md) | 用户的一天：从早盘到收盘复盘 |
| [Information Architecture](Information%20Architecture.md) | 页面层级、导航结构、快捷键、数据流 |

### 系统

| 文档 | 内容 |
|------|------|
| [Layout System](Layout%20System.md) | 三栏布局、各页面 Layout ASCII |
| [Component Library](Component%20Library.md) | 13 个共享 UI 组件的完整规格 |
| [Chart Specification](Chart%20Specification.md) | 10 种图表的交互和视觉规范 |
| [AI Output Specification](AI%20Output%20Specification.md) | 8 个固定模板，AI 填内容不生成结构 |

### 页面

| 文档 | 内容 |
|------|------|
| [Page Specs](Page%20Specs.md) | 11 个页面的完整定义 |
| [Interaction Guidelines](Interaction%20Guidelines.md) | 键盘、图表的交互规范和性能目标 |

---

## 快速开始

### 给 AI 的提示

当你用 Claude/GPT/Gemini 生成 UI 时，把以下文档作为上下文输入：

```
请参考以下设计规范生成 UI：

1. 颜色使用 Design Tokens.md 中的 CSS 变量
2. 布局遵循 Layout System.md 中的结构
3. 组件使用 Component Library.md 中定义的组件
4. 图表遵循 Chart Specification.md
5. AI 输出使用 AI Output Specification.md 中的固定模板
6. 交互遵循 Interaction Guidelines.md
```

### 给开发者的提示

- 所有新的 UI 代码必须对照本规范 Review
- 如果规范中没有的组件，先在规范中定义再加代码
- Design Token 有变化时更新 docs，代码跟随

---

## 版本

- **v2.0** — 2026-07-06 — Initial Product Design System
- 后续版本在 docs/adr/ 中记录变更

---

## 参考产品

- Bloomberg Terminal — 信息密度、键盘驱动
- TradingView — 图表交互、指标系统
- 同花顺 Level2 — A 股市场深度
- 东方财富 PC — 资金流向、F10
- Wind Terminal — 数据深度
