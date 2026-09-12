### 判定：PASS

范围：合成输入的手动复盘模拟；不是上游策略、真实 AI 或生产调度验收。

- `npm run compile`：通过。
- `node --test tests/*.test.js`：22 passed，0 failed。
- `node tests/run-review-lab-demo.js`：成功生成、读回并校验 28 份 JSON 和 4 个 HTML。
- 空闲：7 completed；忙碌：7 skipped_busy；未知：7 skipped_busy。
- 中途撤销：前 2 completed，其余 5 skipped_busy，即使后续门禁空闲也不恢复。
- 缺数据、无效日期、零价格、非有限价格拒绝路径通过。

实际产物：C:/Users/duritou/AppData/Local/Temp/adaptive-review-simulation-GSYBaS/
每种场景独立子目录，未写入插件 daily results 或生产数据库。

样例价格 10→11、20→19、5→5：上涨/下跌/平盘各 1，等权变化 1.67%。
这不是账户收益，不含买卖成交、费用、T+1 验证；七张卡片是本地演示视角，
不是七个项目真实执行的结论。未请求行情/AI/券商接口，未安装 VSIX 或重启后端。

新增手动命令 quantai.reviewLabSimulate，内存生成并展示，不持久化每日结果。
真实空闲租约、低优先级后台进程、定时触发尚未实现。
本轮未重跑 Python 全套；上一阶段 899 passed 不作为本轮重新运行的证据。
