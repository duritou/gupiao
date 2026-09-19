# Engineering Rules — AI Research Terminal

> **版本**: v1.0  
> **状态**: Architecture Frozen — 所有新增能力先进入 Backlog  
> **适用范围**: 所有开发者（含 AI 辅助编码）

---

## 架构边界（不可违反）

1. **Domain 不依赖 Infrastructure** — Domain 层零外部依赖，纯 Python
2. **Domain 不 import ORM** — Domain Model 永远不引用 SQLAlchemy / ORM 类
3. **Repository 不出现业务逻辑** — Repository 只做 CRUD + Mapper 转换
4. **Event 不可变** — EventEnvelope 发布后不能修改，新字段走 schema_version 演进
5. **Prompt 必须注册** — 不允许硬编码字符串，必须通过 PromptRegistry
6. **Plugin 必须通过 Validator** — 所有 Plugin 加载前经过版本约束/能力声明校验
7. **新数据源必须实现 DataSourcePlugin** — 丢 `plugins/datasource/` 即识别
8. **VSCode 不请求网络** — 插件只通过 IPC 调 Python Server，不直接访问外部 API

---

## 质量规则

9. **所有新增功能必须包含测试** — 模块完成即补 test，不等 Phase 12 集中补
10. **CI 从第一天运行** — ruff + mypy + pytest + coverage，每次 Push 自动执行
11. **小步提交** — 按功能拆提交，不一次提交整个 Phase
12. **Git 提交规范** — `feat(module): description` / `test(module): description` / `docs: description`

---

## 变更规则

13. **文档必须描述在跑的系统** — 2026-09-19 删除了 12 份描述 v1.0 架构（Plugin
    Registry / Market Gateway / Event Bus / 端口-适配器）的文档：那套架构建于
    2026-07-05/06，从未接线，几天后即被放弃。**任何描述一套不存在架构的文档
    都是负债** —— 它会让人（包括 AI 助手）按错误的心智模型改代码。
14. **新想法先进 Backlog** — 记录在 `docs/project-optimization-20260913/` 或
    新建文档；不要再引用已删除的 `architecture-v1.1-backlog.md`
15. **不要提前优化** — SQLite + 单机进程即可，跑通再换。注意：曾计划的内存
    EventBus 与 Arq 队列**从未接线且已删除**，不要按那份设计写代码
16. **Feature 先进入 Backlog，再进入 Roadmap** — 不在 Roadmap 上的功能不开发

---

## 数据伦理（不可违反）

17. **只调用合法 API** — 官方 API / 用户授权 API / 开源项目（遵守 License）/ 用户本地数据
18. **禁止破解** — 不破解客户端 / 不 Hook / 不注入 / 不 OCR / 不绕过权限 / 不非授权接口
19. **许可配置定期审核** — `config/license_policies.yaml` 每季度人工审核一次

---

## 开发顺序

```
Phase 0  → 基础设施 (EventBus + Metrics + ORM + 配置 + 日志 + CI)
Phase 1  → Plugin Registry
Phase 2  → Market Gateway
Phase 3  → Repository
Phase 4  → Knowledge
Phase 5  → Signals
Phase 6  → Scanner
Phase 7  → Research Pipeline + Memory
Phase 8  → AI Agent Layer
Phase 9  → Backtest + Trading
Phase 10 → VSCode Extension
Phase 11 → Notification
Phase 12 → 测试 + 文档 + 发布
Phase 13 → Web (后期)
```

---

> **Phase 0 开始。**
