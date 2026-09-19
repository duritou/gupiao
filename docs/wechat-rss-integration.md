# 微信公众号复盘知识接入

Adaptive 不直接复用桌面微信登录，也不对微信公众号页面做高频抓取。推荐在本机单独运行一个 RSS bridge（例如 [WechRss](https://github.com/johamwon/wechrss)），完成微信读书扫码登录、在微信读书中关注目标公众号，并把该公众号的 RSS 地址填给 Adaptive。

在 `.env` 中设置：

```dotenv
WECHAT_RSS_ENABLED=true
WECHAT_RSS_URL=http://127.0.0.1:8080/feeds/1.xml
WECHAT_RSS_MAX_ARTICLES=50
```

启动后可在 Replay 页面点击“刷新公众号知识”，或调用：

```text
POST /api/v1/knowledge/wechat/sync
GET  /api/v1/knowledge/wechat/status
GET  /api/v1/knowledge/wechat/articles?limit=20
```

系统每天 06:30（北京时间）执行一次有界同步，文章以 URL 去重后写入 data/wechat/articles。WechRss 默认同步文章元数据；原文链接可能需要在 WechRss 页面手动分批补全。同步失败不会阻塞行情、选股或交易任务。

公众号文章在 VS Code 的“测试复盘”下按来源单独显示为“公众号复盘 · <账号名>”栏目：每个账号当前只展示最新一篇，其余文章进入历史文章折叠栏。Adaptive 会从 WechRss 的 `/api/sources` 自动发现所有已启用来源；如果只配置了 `WECHAT_RSS_URL` 但无法访问来源注册表，则回退到单个 Feed。开启 `WECHAT_RSS_AI_ENABLED=true` 后，每次出现新文章会调用已配置的 Codex CLI，分别生成各账号的方法论快照（总结、提炼原则、每日检查清单和本次进步），保存为同一归档目录下的 `_methodology_learning.json`。

仅在微信/微信读书中关注公众号，不会自动在 WechRss 建立来源；需要在 WechRss 页面逐个添加一次，之后 Adaptive 会自动发现并处理全部已启用来源。

该 AI 学习结果只服务于测试复盘展示，不写入生产 `learning_log`，不改变选股、评分、交易或主学习规则。页面上的“刷新并学习”会执行一次有界同步并更新快照；相同文章集合会自动跳过重复 AI 调用。

历史 Replay 会把发布时间不晚于所选日期的文章挂入冻结上下文；文章只作为复盘知识证据展示，不改变技术评分、排序和交易判定。这样可以避免把今天才看到的文章带入过去的回放。

首次配置仍需要在 RSS bridge 中单独扫码；Adaptive 不能读取桌面微信后台会话。微信读书接口出现人工验证或限频（例如 -2041）时，应在官方微信读书客户端完成验证并等待后再手动同步，不要循环重试或尝试绕过风控。若 RSS bridge 未运行，状态接口会明确返回失败或未配置，并保留已有文章归档。
