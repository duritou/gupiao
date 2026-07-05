# Design Principles — AI Research Terminal

## 1. Data First, AI Second

数据占据 70% 以上屏幕面积。AI 在右侧独立面板解释数据。

```
┌──────────────────────────────┐
│  Data (70%)    │  AI (30%)  │
│                │            │
│  K-line        │  Score     │
│  Indicators    │  Evidence  │
│  Volume        │  Risk      │
│  Fund Flow     │  Knowledge │
└──────────────────────────────┘
```

**违反此原则**：AI 聊天占据主区域，K线变成附属品。

## 2. High Information Density, Low Cognitive Load

信息要多，但组织要清晰。

- 用网格布局，不是列表堆砌
- 用颜色编码，不是文字描述
- 用固定位置，不是滚动发现
- 用卡片分组，不是平铺

## 3. Professional, Not Decorative

- 无渐变背景
- 无圆角 > 8px
- 无阴影 > 4px
- 无 emoji 作为主要图标
- 无动画 > 200ms

**参考**: Bloomberg Terminal 的克制感。

## 4. Fixed Layout, Not Responsive Chaos

PC 优先。1920×1080 是基准分辨率。

- 左侧导航: 220px 固定宽度
- 主内容区: flex 填充
- 右侧 AI 面板: 320px 固定宽度
- 不支持 < 1280px 宽度

## 5. Keyboard First, Mouse Second

- `/` 聚焦搜索
- `1-9` 切换页面
- `Esc` 关闭弹窗
- `Space` 播放/暂停自动刷新
- `Ctrl+K` 命令面板

**参考**: Bloomberg Terminal 的键盘驱动。

## 6. AI Explains, Human Decides

- AI 输出永远是结构化的（Score、Evidence、Risk、Recommendation）
- AI 永远给出推理过程（Evidence Chain）
- AI 永远标注置信度
- 用户永远做最终决策

## 7. Real-Time When It Matters

- 自选股评分: 30s 刷新
- 预警信号: 实时推送
- 市场概览: 60s 刷新
- K线: 按需加载，不自动刷新
- AI 分析: 手动触发，不自动

## 8. Consistent Design Language

所有页面共享同一套 Design Token。不允许：

- 这个页面 #0B1220，那个页面 #0D1117
- 这个卡片 8px 圆角，那个卡片 12px 圆角
- 这个按钮 16px 字，那个按钮 14px 字

## 9. Evidence Over Opinion

AI 的每一条结论必须有来源：

```
❌ "这只股票可以买"
✅ "MACD金叉（可信度95%）+ MA多头排列（可信度88%）→ Score 91 → 推荐关注"
```

## 10. Transparent, Not Magic

- 评分逻辑可查看
- 权重可调整
- Prompt 可查看和修改
- 预测结果可回溯验证
- 错误可追踪到具体信号
