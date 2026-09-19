# 全项目精简优化实施计划

原则：先收敛入口和职责，再收敛数据访问，最后清理工程产物；每批完成后独立验收。不得修改选股、评分、排序、Top N、交易或学习规则。

## 批次 A：基线与能力归属

- [ ] `docs/project-optimization-20260913/capability-inventory.md` | 建立前端入口、后端路由、后台任务、数据表和兼容别名的唯一能力清单，标注主入口/兼容入口/待下线项 | 优先级(P0)
- [ ] `scripts/audit_project_surface.py` | 静态扫描命令、导航、路由、定时任务和重复 API，输出可审计 JSON，不修改运行数据 | 优先级(P0)
- [ ] `tests/unit/api/test_route_surface.py` | 固化核心路由存在性、兼容路由和下线路由的基线 | 优先级(P0)

## 批次 B：后端入口收敛

- [ ] `src/api/routes/brief_utils.py`、`src/api/routes/morning_brief_routes.py`、`src/api/routes/dailybrief_routes.py` | 保留一个简报主实现，兼容入口只做薄转发并明确缓存/弃用语义 | 优先级(P0)
- [ ] `src/api/routes/alerts_routes.py`、`src/api/routes/journal_utils.py` | 统一预警和决策日志快照读取，避免多页面重复扫描数据库；不改变阈值和排序 | 优先级(P0)
- [ ] `src/api/app.py`、`src/api/routes/vibe_compat_routes.py`、`src/api/routes/unified_research_routes.py` | 标注兼容 API 边界，避免同一业务再注册第二套调度或状态管理 | 优先级(P0)
- [ ] `src/ai_os/task_executor.py`、`src/ai_os/scheduler.py`、`src/api/app.py` | 统一任务启动、恢复、健康检查和停止生命周期，保证每类后台任务只有一个 owner | 优先级(P0)
- [ ] `tests/unit/api/`、`tests/unit/ai_os/` | 验证并发请求只产生一次底层读取、任务只注册一次、服务重启不重复调度 | 优先级(P0)

## 批次 C：前后端能力对齐

- [ ] `vscode-ext/src/extension.ts`、`vscode-ext/src/constants.ts`、`vscode-ext/src/sidebar/providers.ts` | 建立页面/命令/路由单一映射，删除失效入口，保留必要兼容命令并标记迁移 | 优先级(P1)
- [ ] `vscode-ext/src/pages/`、`vscode-ext/src/webview/layout.ts` | 把首页摘要、日报、预警、决策中心的展示职责分层，避免同一数据完整复制到多个页面 | 优先级(P1)
- [ ] `vscode-ext/src/api/client.ts`、`vscode-ext/src/page-cache.ts` | 统一请求超时、缓存、重试和错误状态，不在页面内重复实现 | 优先级(P1)
- [ ] `tests/unit/`、`vscode-ext/` | 验证每个导航入口唯一、核心页面能加载、删除项不再打 API、Replay 等保留功能不受影响 | 优先级(P1)

## 批次 D：工程与运行时清理

- [ ] `scripts/`、`runtime/`、`config/` | 统一发布、配置和数据路径，清理重复启动器、旧端口默认值和过期发布入口；保留回滚能力 | 优先级(P1)
- [ ] `.gitignore`、`docs/`、`reports/`、`test-reports/` | 将临时报告、缓存、生成包和历史证据分层，避免源码树混入运行产物 | 优先级(P1)
- [ ] `vscode-ext/out/`、发布脚本 | 统一生成产物来源，禁止手工维护过期编译文件 | 优先级(P1)
- [ ] `scripts/audit_project_surface.py`、`tests/integration/` | 验证发布后端、实际数据库、端口、进程身份和前端版本一致 | 优先级(P1)

## 批次 E：长期约束

- [ ] `tests/unit/`、`tests/integration/` | 增加路由唯一性、重复调度、决策输出不变量和数据路径契约测试 | 优先级(P2)
- [ ] `docs/project-optimization-20260913/` | 记录每项删除/合并的替代入口、回滚方法和最终保留能力 | 优先级(P2)
- [ ] `dev-plan.md`、`project-structure.md`、`code-guideline.md` | 将已完成的精简边界同步回项目主规范，防止重复功能重新进入 | 优先级(P2)
