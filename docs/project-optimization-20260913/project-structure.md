# 精简后的项目结构目标

```text
adaptive-investment-intelligence/
├── src/
│   ├── api/
│   │   ├── app.py                    # 唯一 API 组装与生命周期入口
│   │   └── routes/                   # 按业务域提供主路由；兼容路由单独标注
│   ├── ai_os/                        # 选股结果之后的编排、执行、学习和任务 owner
│   ├── domain/                       # 稳定领域模型，不依赖 UI 或兼容层
│   ├── infrastructure/               # 数据源、缓存、存储、运行时身份和外部适配
│   ├── explain/                      # 决策解释、证据与结果回写
│   ├── replay/                       # 冻结回放、策略比较和历史验证
│   └── knowledge/                    # 知识与公众号资料适配
├── vscode-ext/
│   ├── src/
│   │   ├── extension.ts              # 命令注册、页面路由和后端生命周期
│   │   ├── api/                      # 统一 HTTP 客户端
│   │   ├── pages/                    # 一个页面对应一个明确能力
│   │   ├── sidebar/                  # 只保留可用导航和状态展示
│   │   └── webview/                  # 页面壳、通用样式和通用交互
│   └── out/                          # 仅由 TypeScript 编译生成
├── scripts/                          # 发布、审计、迁移和一次性工具，不承载第二套业务实现
├── config/                           # 非密钥配置和版本契约
├── runtime/                          # 活动发布清单、锁和运行状态，不存业务数据库
├── docs/project-optimization-20260913/ # 本轮能力清单、计划和验收证据
└── tests/                            # API、AI OS、基础设施和集成契约测试
```

## 归属规则

- `src/api/routes/` 只负责协议转换和权限/参数校验；业务计算放在领域或服务层。
- `src/ai_os/` 每类任务只能有一个调度 owner；API 只能触发或查询，不能复制调度循环。
- `vscode-ext/src/pages/` 不直接实现数据规则；页面只组合 API 返回结果。
- `vscode-ext/out/` 不手工编辑，不作为新的源码入口。
- `vibe_compat`、旧命令和旧路由必须显式标为兼容层，不能再扩展新业务。
