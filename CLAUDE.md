# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# 0. 微信小程序开发铁则（最高优先级）

## 上下文与编码管控
- 对话轮次 ≥ 8 轮自动压缩，留存表结构 / 技术栈 / 核心逻辑 / 有效代码，先输出项目快照再编码。
- 单文件 > 280 行拆分输出，每完成一个功能模块刷新精简快照，清理冗余上下文再继续。
- 严禁全文搬运历史对话、重复粘贴整套原始需求文档、无压缩持续堆叠代码。

## 技术限制
- 纯微信小程序原生 WXML + JS，微信云开发 TCB，无独立服务器。
- 所有运算、校验、库存扣减放在云函数，前端只负责展示和传参。
- 仅使用 `suppliers` / `tires` / `purchase` / `sales` 四张集合，库存通过实时求和计算，不单独建库存表。

## 代码规范
- 云函数 Node 原生写法，无重型依赖。
- 代码带中文注释。
- 所有表单必须包含：校验逻辑、loading 状态、防重复点击。
- 图片存储走云存储。
- 离线场景使用 storage 缓存，联网后自动同步。

## 数据安全
- 增删改操作全部走云函数。
- 出库必须校验库存是否充足。
- 编辑/删除单据后自动重算库存。
- 规格花纹、供应商写入前自动去重。

## 交互标准
- 日期默认当日。
- 规格字段自动回填历史进价。
- 删除和出库操作需要二次确认。
- 多图上传需压缩处理。
- 跨表模糊搜索。
- 无数据时展示友好提示。

## 交付要求
- 按文件路径分块输出代码。
- 结尾附上云开发部署步骤。
- CSV 导出由云端生成链接，转发微信。

## 严禁
- 前端运算库存。
- 引入第三方框架。
- 对接外部后端。
- 多账号登录体系。
- 跳过库存校验。
- 用文字规格替代 tire 关联。
- **擅作主张修改无关代码/功能**：每个改动必须直接对应当前任务，不得"顺手"优化、重构、添加或删除与用户指令无关的代码。发现可改进之处只能告知用户，不可擅自修改。

## Git 远程仓库（双推送）

用户说「上传」「推送」「上传branch」「推代码」等指令时，**必须同时推送到两个远程仓库**：

| 远程 | 地址 | 分支 |
|------|------|------|
| `origin`（微信云 Git） | `https://git.weixin.qq.com/mster/master.git` | `master` |
| `github`（GitHub） | `https://github.com/duritou/gupiao.git` | `dapaijifen` |

推送命令：
```bash
git push origin master
git push github master:dapaijifen
```

> 注意：GitHub 端 `dapaijifen` 分支与本地 `master` 历史不同源，首次推送需 `--force`，后续正常推送。

---

# 1. LLM Coding Best Practices

Behavioral guidelines to reduce common LLM coding mistakes.
Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
1.  [Step] - verify: [check]
2.  [Step] - verify: [check]
3.  [Step] - verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

# 2. cloud.openapi 踩坑实录（通用教训）

本节来自车牌 OCR 功能（`cloud.openapi.ocr.printedText`）的实战踩坑，大部分教训适用于所有 `cloud.openapi` 调用。

## 2.1 图片/文件传参三板斧

| 方案 | 参数 | 结果 | 原因 |
|------|------|------|------|
| `cloud://` fileID 直传 | `imgUrl: 'cloud://xxx'` | `-609001` 图片无效 | `cloud.openapi` 不解析 `cloud://` 协议，底层 HTTP API 无法访问 |
| 前端 `readFile` base64 | `imgBase64: '...'` | `41005 media data missing` | `cloud.openapi` 包装层不支持 `imgBase64` 参数名（虽然腾讯云 API 原生支持 `ImageBase64`） |
| 临时 HTTP URL | `imgUrl: getTempFileURL()` | ✅ 成功 | `getTempFileURL` 生成带签名的 HTTPS 链接（2 小时有效），底层 API 可直接读取 |

**通用规则：所有需要外部 API 消费的云存储文件，必须先 `cloud.getTempFileURL()` 转成 HTTP URL。**

## 2.2 `type` 参数是地雷

`cloud.openapi.ocr.printedText({ imgUrl, type: 'photo' })` → `errCode: 0, result: {}`（空结果）
`cloud.openapi.ocr.printedText({ imgUrl })` → 正常返回文字

**规则：调用 `cloud.openapi` 先只用必填参数验证通路，确认可用后再加可选参数。不要"顺手"加参数。**

## 2.3 cloud.openapi 错误码速查

| errCode | 含义 | 解决 |
|---------|------|------|
| `-604100` | API 未注册/未在 config.json 声明 | 微信云开发控制台开通对应 API，云函数 `config.json` 的 `permissions.openapi` 添加对应接口名 |
| `-604101` | API 权限未开通 | 微信云开发控制台 → 云开发 → 设置 → 全局设置 → 开放 API 开关 |
| `-609001` | 图片无效或格式不支持 | 检查图片 URL 是否可访问、格式是否为 JPG/PNG、是否用了 `cloud://` 协议 |
| `101003` | 调用配额不足 | 微信云开发控制台购买调用次数 |
| `41005` | media data missing | 参数名不被 cloud.openapi 支持（如 `imgBase64`），改回 HTTP URL 方案 |
| `errCode: 0` + `result: {}` | API 调通了但无数据 | 检查可选参数是否干扰（如 `type`），检查图片是否确实有文字 |

## 2.4 Plugin 能力验证铁则

插件 `wxe567a849ff4f3f53` (OCR) 文档含糊写"支持 OCR 识别"，实际仅支持身份证/银行卡/名片，**不支持车牌**。且强制使用全屏 camera 组件，无法嵌入业务页面。

**规则：使用任何插件前必须确认 3 点：**
1. 具体支持的识别类型列表（不要假设"OCR = 什么都能识"）
2. 是否强制全屏组件（会打断业务流程）
3. 先写一个最小 demo 验证，不要直接接入主流程

## 2.5 WXML 语法硬限制

WXML 属性值**不能跨行**，否则编译报错 `unexpected character '\n'`。长 class 表达式必须写在同一行：

```html
<!-- ❌ 跨行 → 编译报错 -->
<view class="lp-cell {{index === 0 ? 'lp-cell-province' : ''}}
            {{index === 7 ? 'lp-cell-energy' : ''}}">

<!-- ✅ 单行 -->
<view class="lp-cell {{index === 0 ? 'lp-cell-province' : ''}} {{index === 7 ? 'lp-cell-energy' : ''}}">
```

## 2.6 cloud.openapi 调用通用原则

1. **先最小参数集打通，再加可选参数** — 每加一个参数都可能引入新问题
2. **fileID (`cloud://`) 只能内部用，外部 API 走 temp URL**
3. **`imgBase64` / `ImageBase64` 在 cloud.openapi 层不可用** — 该层只认 HTTP URL
4. **错误码分两层处理**：`catch` 捕获网络/权限异常，`errCode !== 0` 处理业务失败
5. **加满日志**：入参长度、原始 errCode、result 顶层 keys、result 完整 JSON — 调试时这些是救命稻草
6. **OCR 结果格式不唯一**：`result.items[].text` / `result.TextDetections[].DetectedText` / `result.words_result` / `result.text` — 都可能是正确的，依次尝试
