### 判定：PASS

范围仅为结果读取修复；托管进程切换等待用户 Reload，不声明完整部署验收通过。

- 独立目录改为工作区 runtime/adaptive-review-lab，与启动用户环境解耦。
- 原产物保留，复制到新目录；未重新交易或学习。
- 专项 5 passed，前端编译及 22 测试通过。
- 实际 GET /review-lab/runs 返回 friday-009da541cf334d12b54ef9f1c801e48d。
- 实际 GET 详情返回 2026-09-11，cash=100054.63，net_pnl=54.63。
- 新 VSIX release-20260912-140914-fbb54ccb 已安装。
- 自动部署被旧插件抢启的源码 uvicorn 阻止；未宣称托管验证通过。
- 已校验新 manifest 并绑定为下次托管启动目标，清理本次已退出部署进程的维护标记。
- 需要用户 Reload 替换旧扩展宿主；之后必须再核验 managed/release_id。
