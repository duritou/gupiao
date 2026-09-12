"""Small, causal paper replay with explicit illustrative execution assumptions."""
from __future__ import annotations

from typing import Any
import math


def replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Use Wednesday information, Thursday entry, Friday exit; never place real orders."""
    dates = sorted({row['trade_date'] for row in rows})
    if len(dates) != 3:
        raise ValueError('Exactly three observed sessions are required')
    cash = 100000.0
    trades = []
    rejected = []
    for code in sorted({row['ts_code'] for row in rows}):
        bars = sorted([row for row in rows if row['ts_code'] == code],
                      key=lambda row: row['trade_date'])
        if len(bars) != 3:
            rejected.append({'symbol': code, 'reason': 'missing_session'})
            continue
        signal, buy, sell = bars
        if any(not math.isfinite(float(b[k] or 0)) or float(b[k] or 0) <= 0
               for b in bars for k in ('open', 'close', 'volume')):
            rejected.append({'symbol': code, 'reason': 'invalid_or_suspended'})
            continue
        if signal['close'] <= signal['open']:
            rejected.append({'symbol': code, 'reason': 'prior_session_not_positive'})
            continue
        # Skip suspicious limit/adjustment gaps; do not fabricate a tradable auction.
        if any(abs(b['open'] / p['close'] - 1) >= 0.09
               for p, b in ((signal, buy), (buy, sell))):
            rejected.append({'symbol': code, 'reason': 'gap_or_limit_uncertain'})
            continue
        quantity = 100
        entry = round(buy['open'] * 1.001, 4)
        exit_price = round(sell['open'] * 0.999, 4)
        cost = round(entry * quantity + max(5, entry * quantity * 0.0003), 2)
        proceeds = round(exit_price * quantity - max(5, exit_price * quantity * 0.0003)
                         - exit_price * quantity * 0.0005, 2)
        if min(cash, 100000 / 3) < cost:
            rejected.append({'symbol': code, 'reason': 'insufficient_cash'})
            continue
        cash = round(cash - cost + proceeds, 2)
        trades.append({'symbol': code, 'quantity': quantity, 'signal_date': dates[0],
                       'buy_date': dates[1], 'sell_date': dates[2],
                       'entry_price': entry, 'exit_price': exit_price,
                       'cost': cost, 'proceeds': proceeds, 'net_pnl': round(proceeds - cost, 2)})
    return {'initial_cash': 100000, 'cash': cash, 'positions': [], 'trades': trades,
            'rejected': rejected, 'net_pnl': round(cash - 100000, 2),
            'execution': 'assumed_daily_open_not_verified_fills',
            'learning': [f'本次合格模拟往返 {len(trades)} 笔；禁止由小样本推断策略有效。',
                         '先决策、下一交易日买入、再下一交易日卖出；未使用周五收盘倒推买点。',
                         '开盘成交、滑点和费用是模型假设；无盘口无法验证成交。',
                         '学习仅为本地规则总结，未调用 AI 或更新生产记忆。'],
            'fee_assumptions': '佣金万三/最低5元，卖出税万五，双边滑点千一；简化模型，非完整费率核验'}
