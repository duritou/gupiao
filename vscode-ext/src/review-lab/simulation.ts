/** Tiny deterministic fixtures only. This is not an upstream strategy implementation. */
import { REVIEW_PROJECTS, ReviewArtifact, validDate } from './model';

export type SimulatedActivity = 'idle' | 'busy' | 'unknown';
export interface SimulatedBar { symbol: string; previous: number; close: number }
export const SYNTHETIC_BARS: readonly SimulatedBar[] = [
    { symbol: 'SYNTHETIC_A', previous: 10, close: 11 },
    { symbol: 'SYNTHETIC_B', previous: 20, close: 19 },
    { symbol: 'SYNTHETIC_C', previous: 5, close: 5 },
];

export function simulateReview(
    date: string,
    activity: () => SimulatedActivity,
    bars: readonly SimulatedBar[] = SYNTHETIC_BARS,
): ReviewArtifact[] {
    if (!validDate(date)) throw new Error('无效模拟日期');
    if (bars.length > 100 || bars.some(bar => !Number.isFinite(bar.previous)
        || !Number.isFinite(bar.close) || bar.previous <= 0 || bar.close <= 0)) {
        throw new Error('无效或超限模拟数据');
    }
    // Checks occur before each tiny calculation. This is an injected test gate, not a live lease.
    let cancelled = false;
    return REVIEW_PROJECTS.map((project, index) => {
        let state: SimulatedActivity = 'unknown';
        try { state = activity(); } catch { /* Unknown must fail closed. */ }
        cancelled ||= state !== 'idle';
        const result: ReviewArtifact = {
            schema_version: 1, reference_only: true, date, project,
            status: cancelled ? 'skipped_busy' : bars.length ? 'completed' : 'no_data',
            method: 'synthetic_simulation', source_revision: 'review-lab-synthetic-v1',
            input_as_of: `${date}（合成场景日期，不是行情时间）`,
            summary: '',
            limitations: '仅合成输入和本地演示计算；未执行上游项目、未调用 AI、未验证投资收益。'
                + '空闲状态由测试注入，不证明生产空闲检测或抢占已实现。',
        };
        if (cancelled) {
            result.summary = `模拟门禁拒绝运行：${state}；本轮撤销后不恢复，不做市场计算。`;
            return result;
        }
        if (!bars.length) {
            result.summary = '没有模拟输入，未补采，未生成结论。';
            return result;
        }
        const returns = bars.map(bar => (bar.close / bar.previous - 1) * 100);
        const up = returns.filter(value => value > 0).length;
        const down = returns.filter(value => value < 0).length;
        const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
        const observations = [
            `极端涨幅观察：最大日变化 ${Math.max(...returns).toFixed(2)}%；缺少盘口，不能认定可成交涨停。`,
            `证据链观察：${bars.length} 条合成价格记录；无成交回执，不形成可信交易记忆。`,
            `市场回放观察：上涨 ${up}、下跌 ${down}、平盘 ${bars.length - up - down}。`,
            `日终摘要观察：样本等权日变化 ${mean.toFixed(2)}%；非账户收益。`,
            '交易约束观察：只有单日价格，无次日成交与成本，无法验证 T+1 买卖。',
            '样本外观察：只有单日样本，无法运行滚动验证或声称策略有效。',
            `阶段快照观察：仅日终 ${bars.length} 条记录；竞价和盘中阶段缺失。`,
        ];
        result.summary = `【演示，不代表该项目算法】${observations[index]}`;
        return result;
    });
}
