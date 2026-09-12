const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return {};
    return originalLoad.call(this, request, parent, isMain);
};

const { buildBacktestPage } = require('../out/pages/backtest');

test('zero metrics never render fabricated demo values', () => {
    const html = buildBacktestPage({
        backtest: {
            status: 'ok',
            initial_capital: 100000,
            final_capital: 100000,
            metrics: {
                annual_return_pct: 0,
                max_drawdown_pct: 0,
                sharpe_ratio: 0,
                win_rate_pct: 0,
                total_return_pct: 0,
                total_trades: 0,
                winning: 0,
                losing: 0,
            },
            trades: [],
        },
    });

    assert.match(html, /0\.0%/);
    assert.match(html, /¥100,000\.00/);
    assert.match(html, /本区间没有满足规则的已完成交易/);
    assert.doesNotMatch(html, /32\.5%|69%|122,500|>15</);
});

test('trade details and provenance are visible and auditable', () => {
    const html = buildBacktestPage({
        backtest: {
            status: 'ok',
            stock_code: '300765.SZ',
            stock_name: '石药创新',
            period: '2026-03-03 ~ 2026-08-24',
            bar_count: 120,
            initial_capital: 100000,
            final_capital: 101620,
            metrics: { total_trades: 1, winning: 1, losing: 0, win_rate_pct: 100 },
            data_quality: {
                status: 'verified', integrity_passed: true, is_synthetic: false,
                source_table: 'market_daily', upstream_source: 'baostock daily synchronization',
                first_date: '2026-03-03', last_date: '2026-08-24', freshness_days: 1,
                freshness_state: 'current', duplicate_dates: 0, invalid_ohlc_rows: 0,
                price_adjustment: 'none', input_checksum_sha256: 'a'.repeat(64),
            },
            methodology: {
                signals: ['MACD', 'RSI'], position_size: 10000,
                fee_policy: 'configured', execution_price: 'same-day daily close',
                limitations: ['research only'],
            },
            truth_audit: {
                record_type: 'historical_backtest_simulation',
                is_actual_paper_trading_record: false,
                paper_ledger_trade_count_for_symbol_period: 0,
                matched_paper_ledger_legs: 0,
                selection_decision_created_at: '2026-08-27T01:28:38+08:00',
                backtest_generated_at: '2026-08-27T08:55:03+08:00',
                causality_status: 'retrospective_selection_after_entry',
                plain_language: '本页成交由回测运行时使用历史K线事后模拟，不是当时写入纸面交易账本的成交。',
            },
            trades: [{
                record_type: 'historical_backtest_simulation',
                is_actual_paper_trade: false,
                actual_paper_buy_match: false,
                actual_paper_sell_match: false,
                actual_paper_round_trip_match: false,
                selection_decision_created_at: '2026-08-27T01:28:38+08:00',
                simulated_at: '2026-08-27T08:55:03+08:00',
                signal_date: '2026-07-28',
                causality_status: 'retrospective_selection_after_entry',
                stock_code: '300765.SZ', stock_name: '石药创新',
                entry_date: '2026-07-28', exit_date: '2026-08-24',
                entry_price: 38.9, exit_price: 45.24, quantity: 257,
                entry_amount: 9997.3, exit_amount: 11626.68, total_fees: 11.62,
                profit_amount: 1617.76, profit_pct: 16.18,
                entry_signal_score: 70, holding_days: 20, exit_reason: '回测结束平仓',
            }],
        },
    });

    for (const expected of [
        '行情数据已核验', 'market_daily', 'baostock daily synchronization',
        '历史K线事后回放', '选股决策晚于模拟买点', '无真实账本成交',
        '2026-08-27T01:28:38+08:00', '2026-08-27T08:55:03+08:00',
        '石药创新', '300765.SZ', '2026-07-28', '2026-08-24',
        '¥38.90', '257股', '¥11.62', '回测结束平仓',
    ]) {
        assert.match(html, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
});
