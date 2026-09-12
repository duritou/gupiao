"""BacktestEngine — 历史数据回测 + 模拟交易

在历史K线上运行信号引擎，模拟买卖，计算绩效。
输出: 交易记录 + 权益曲线 + 绩效指标
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.ai_os.trading_costs import (
    COMMISSION_RATE,
    STAMP_TAX_RATE,
    calculate_trade_costs,
    quantize_price,
)
from src.ai_os.trading_policy import PAPER_MAX_POSITION_PCT
from src.backtest.execution import assess_daily_open_fill


@dataclass
class Trade:
    """单笔交易记录"""
    stock_code: str
    entry_date: str
    exit_date: str = ""
    direction: str = "buy"         # buy / sell
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    entry_amount: float = 0.0
    exit_amount: float = 0.0
    buy_fee: float = 0.0
    sell_commission: float = 0.0
    stamp_tax: float = 0.0
    total_fees: float = 0.0
    gross_profit_pct: float = 0.0
    profit_pct: float = 0.0
    profit_amount: float = 0.0
    holding_days: int = 0
    signal_score: float = 0.0      # 入场时的信号评分
    exit_reason: str = ""
    entry_signal_date: str = ""
    exit_signal_date: str = ""


@dataclass
class OrderRejection:
    """Order that could not be filled under point-in-time A-share rules."""

    stock_code: str
    action: str
    signal_date: str
    intended_execution_date: str
    reason: str


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_return_pct: float = 0.0         # 总收益率
    annual_return_pct: float = 0.0        # 年化收益率
    max_drawdown_pct: float = 0.0         # 最大回撤
    sharpe_ratio: float = 0.0             # 夏普比率
    win_rate_pct: float = 0.0             # 胜率
    avg_win_pct: float = 0.0              # 平均盈利
    avg_loss_pct: float = 0.0             # 平均亏损
    profit_factor: float = 0.0            # 盈亏比
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100000.0
    final_capital: float = 100000.0
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    order_rejections: list[OrderRejection] = field(default_factory=list)


class BacktestEngine:
    """回测引擎 — 历史数据模拟交易

    简化假设:
      - 日线信号在下一交易日开盘成交
      - 使用配置的固定不利滑点
      - 手续费采用系统纸面交易费率，卖出额外计算印花税
      - 单次买入按账户资产的统一仓位上限成交
      - 传入 position_size 时保留固定金额模式，兼容旧版调用方
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        position_size: float | None = None,
        commission_rate: float = float(COMMISSION_RATE),
        stamp_tax_rate: float = float(STAMP_TAX_RATE),
        slippage_rate: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_rate = max(0.0, slippage_rate)

    async def run(
        self,
        stock_code: str,
        klines: list[dict],
        signal_scores: list[dict] | None = None,
        strategy_name: str = "default",
    ) -> BacktestResult:
        """运行回测

        Args:
            stock_code: 股票代码
            klines: OHLCV 数据 (按时间升序)
            signal_scores: 每日信号评分 [{"date":"...","score":75,"direction":"buy"},...]
                          如果为 None，则只计算 buy-and-hold
            strategy_name: 策略名称

        Returns:
            BacktestResult with trades + equity curve + metrics
        """
        if len(klines) < 2:
            return BacktestResult(strategy_name=strategy_name)

        # 建立日期→K线的索引
        kline_by_date = {k.get("timestamp", k.get("date", "")): k for k in klines}

        # 建立日期→信号的索引
        signal_by_date = {}
        if signal_scores:
            for s in signal_scores:
                d = s.get("date", s.get("timestamp", ""))
                signal_by_date[d] = s

        capital = self.initial_capital
        position = 0               # 持仓数量
        cost_basis = 0.0           # 持仓成本
        trades: list[Trade] = []
        rejections: list[OrderRejection] = []
        equity: list[dict] = []

        # 按日期排序
        dates = sorted(kline_by_date.keys())

        in_position = False
        entry_date = ""
        entry_price = 0.0
        entry_score = 0.0
        entry_amount = 0.0
        entry_fee = 0.0
        entry_total = 0.0
        entry_signal_date = ""
        entry_index = -1
        pending_order: dict | None = None

        for i, date in enumerate(dates):
            k = kline_by_date[date]
            close = float(k.get("close", k.get("Close", 0)) or 0)
            if close <= 0:
                continue

            signal = signal_by_date.get(date)

            # Daily-close signals become eligible only at the next session open.
            if pending_order is not None:
                previous_close = None
                if i > 0:
                    previous_bar = kline_by_date[dates[i - 1]]
                    previous_close = float(
                        previous_bar.get("close", previous_bar.get("Close", 0)) or 0
                    )
                action = str(pending_order["action"])
                assessment = assess_daily_open_fill(
                    action, stock_code, k, previous_close, self.slippage_rate
                )
                order_consumed = assessment.accepted
                if not assessment.accepted:
                    rejections.append(OrderRejection(
                        stock_code, action, str(pending_order["signal_date"]),
                        date, assessment.rejection_reason,
                    ))
                elif action == "BUY" and not in_position:
                    fill_price = quantize_price(float(assessment.fill_price))
                    marked_value = capital
                    budget = (
                        float(self.position_size)
                        if self.position_size is not None
                        else marked_value * PAPER_MAX_POSITION_PCT
                    )
                    shares = int(budget / fill_price / 100) * 100
                    gross = shares * fill_price
                    buy_costs = calculate_trade_costs(
                        gross,
                        "BUY",
                        commission_rate=self.commission_rate,
                        stamp_tax_rate=self.stamp_tax_rate,
                    )
                    buy_fee = buy_costs["total_fees"]
                    cost = gross + buy_fee
                    if shares > 0 and cost <= capital:
                        capital -= cost
                        position = shares
                        cost_basis = fill_price
                        in_position = True
                        entry_date = date
                        entry_price = fill_price
                        entry_score = float(pending_order["score"])
                        entry_amount = gross
                        entry_fee = buy_fee
                        entry_total = cost
                        entry_signal_date = str(pending_order["signal_date"])
                        entry_index = i
                    else:
                        rejections.append(OrderRejection(
                            stock_code, action, str(pending_order["signal_date"]),
                            date, "insufficient_cash_or_board_lot",
                        ))
                elif action == "SELL" and in_position and i > entry_index:
                    fill_price = quantize_price(float(assessment.fill_price))
                    exit_amount = position * fill_price
                    sell_costs = calculate_trade_costs(
                        exit_amount,
                        "SELL",
                        commission_rate=self.commission_rate,
                        stamp_tax_rate=self.stamp_tax_rate,
                    )
                    sell_commission = sell_costs["commission"]
                    stamp_tax = sell_costs["stamp_tax"]
                    revenue = exit_amount - sell_commission - stamp_tax
                    capital += revenue
                    net_profit = revenue - entry_total
                    trades.append(Trade(
                        stock_code=stock_code,
                        entry_date=entry_date,
                        exit_date=date,
                        entry_price=entry_price,
                        exit_price=fill_price,
                        quantity=position,
                        entry_amount=round(entry_amount, 2),
                        exit_amount=round(exit_amount, 2),
                        buy_fee=entry_fee,
                        sell_commission=sell_commission,
                        stamp_tax=stamp_tax,
                        total_fees=round(entry_fee + sell_commission + stamp_tax, 2),
                        gross_profit_pct=round((fill_price / entry_price - 1) * 100, 2),
                        profit_pct=round(net_profit / entry_total * 100, 2),
                        profit_amount=round(net_profit, 2),
                        holding_days=i - entry_index,
                        signal_score=entry_score,
                        exit_reason=str(pending_order.get("reason") or "signal_sell"),
                        entry_signal_date=entry_signal_date,
                        exit_signal_date=str(pending_order["signal_date"]),
                    ))
                    position = 0
                    cost_basis = 0
                    in_position = False
                    entry_index = -1
                else:
                    rejections.append(OrderRejection(
                        stock_code, action, str(pending_order["signal_date"]),
                        date, "t_plus_one_or_position_state",
                    ))
                if order_consumed:
                    pending_order = None

            # 交易逻辑
            if not in_position and signal:
                direction = signal.get("direction", "neutral")
                score = signal.get("score", 50)

                if direction == "buy" and score >= 60:
                    # 买入
                    pending_order = {
                        "action": "BUY",
                        "signal_date": date,
                        "score": score,
                        "reason": "signal_buy",
                    }

            elif in_position:
                signal_sell = bool(
                    signal
                    and signal.get("direction", "neutral") == "sell"
                    and float(signal.get("score", 50)) >= 60
                )
                stop_loss = close < cost_basis * 0.92
                should_sell = signal_sell or stop_loss
                if signal_sell:
                    exit_reason = f"signal_sell(score={float(signal.get('score', 50)):.0f})"
                elif stop_loss:
                    exit_reason = "stop_loss(-8%)"
                else:
                    exit_reason = ""

                if should_sell and i < len(dates) - 1:
                    pending_order = {
                        "action": "SELL",
                        "signal_date": date,
                        "score": score if signal else 50,
                        "reason": exit_reason,
                    }

            # 记录权益
            current_value = capital + (position * close if in_position else 0)
            equity.append({
                "date": date,
                "capital": round(capital, 2),
                "position_value": round(position * close, 2) if in_position else 0,
                "total": round(current_value, 2),
            })

        # There is no next-session open after the final bar. Close any
        # remaining position at the final close with the configured adverse
        # slippage so the trade ledger and final equity agree.
        if in_position and equity:
            last_date = dates[-1]
            last_bar = kline_by_date[last_date]
            last_close = float(last_bar.get("close", last_bar.get("Close", 0)) or 0)
            fill_price = quantize_price(last_close * (1 - self.slippage_rate))
            exit_amount = position * fill_price
            sell_costs = calculate_trade_costs(
                exit_amount,
                "SELL",
                commission_rate=self.commission_rate,
                stamp_tax_rate=self.stamp_tax_rate,
            )
            sell_commission = sell_costs["commission"]
            stamp_tax = sell_costs["stamp_tax"]
            revenue = exit_amount - sell_commission - stamp_tax
            capital += revenue
            net_profit = revenue - entry_total
            trades.append(Trade(
                stock_code=stock_code,
                entry_date=entry_date,
                exit_date=last_date,
                entry_price=entry_price,
                exit_price=fill_price,
                quantity=position,
                entry_amount=round(entry_amount, 2),
                exit_amount=round(exit_amount, 2),
                buy_fee=entry_fee,
                sell_commission=sell_commission,
                stamp_tax=stamp_tax,
                total_fees=round(entry_fee + sell_commission + stamp_tax, 2),
                gross_profit_pct=round((fill_price / entry_price - 1) * 100, 2),
                profit_pct=round(net_profit / entry_total * 100, 2),
                profit_amount=round(net_profit, 2),
                holding_days=max(0, len(dates) - 1 - entry_index),
                signal_score=entry_score,
                exit_reason="回测结束平仓",
                entry_signal_date=entry_signal_date,
                exit_signal_date=last_date,
            ))
            equity[-1] = {
                "date": last_date,
                "capital": round(capital, 2),
                "position_value": 0,
                "total": round(capital, 2),
            }
            position = 0
            in_position = False

        # 计算指标
        final_capital = equity[-1]["total"] if equity else capital
        metrics = self._calculate_metrics(final_capital, trades, equity, len(dates))

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=dates[0] if dates else "",
            end_date=dates[-1] if dates else "",
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 2),
            metrics=metrics,
            trades=trades,
            equity_curve=equity,
            order_rejections=rejections,
        )

    def _calculate_metrics(
        self, final_capital: float, trades: list[Trade],
        equity: list[dict], total_days: int,
    ) -> PerformanceMetrics:
        """计算绩效指标"""
        total_return = (final_capital / self.initial_capital - 1) * 100

        # 年化
        years = total_days / 252 if total_days > 0 else 1
        annual_return = ((1 + total_return / 100) ** (1 / max(years, 0.01)) - 1) * 100

        # 最大回撤
        max_dd = 0.0
        peak = 0.0
        for e in equity:
            val = e["total"]
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak * 100
                max_dd = max(max_dd, dd)

        # 胜率
        wins = [t for t in trades if t.profit_pct > 0]
        losses = [t for t in trades if t.profit_pct <= 0]
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        avg_win = sum(t.profit_pct for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.profit_pct for t in losses) / len(losses) if losses else 0

        # 盈亏比
        total_profit = sum(t.profit_amount for t in wins) if wins else 0
        total_loss = abs(sum(t.profit_amount for t in losses)) if losses else 1
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 夏普比率 (简化: 基于日收益率)
        sharpe = 0.0
        if len(equity) >= 2:
            daily_returns = []
            for i in range(1, len(equity)):
                r = (equity[i]["total"] / equity[i - 1]["total"] - 1)
                daily_returns.append(r)
            if daily_returns:
                avg_daily = sum(daily_returns) / len(daily_returns)
                variance = sum((r - avg_daily) ** 2 for r in daily_returns) / len(daily_returns)
                std_daily = variance ** 0.5
                if std_daily > 0:
                    sharpe = (avg_daily / std_daily) * (252 ** 0.5)

        return PerformanceMetrics(
            total_return_pct=round(total_return, 2),
            annual_return_pct=round(annual_return, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            win_rate_pct=round(win_rate, 1),
            avg_win_pct=round(avg_win, 2),
            avg_loss_pct=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2),
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
        )
