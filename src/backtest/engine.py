"""BacktestEngine — 历史数据回测 + 模拟交易

在历史K线上运行信号引擎，模拟买卖，计算绩效。
输出: 交易记录 + 权益曲线 + 绩效指标
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    profit_pct: float = 0.0
    profit_amount: float = 0.0
    holding_days: int = 0
    signal_score: float = 0.0      # 入场时的信号评分
    exit_reason: str = ""


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


class BacktestEngine:
    """回测引擎 — 历史数据模拟交易

    简化假设:
      - 以日线收盘价成交
      - 无滑点
      - 手续费 0.03% (万一)
      - 单次买入固定金额 (默认 10000)
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        position_size: float = 10000.0,
        commission_rate: float = 0.0003,
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.commission_rate = commission_rate

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
        equity: list[dict] = []

        # 按日期排序
        dates = sorted(kline_by_date.keys())

        in_position = False
        entry_date = ""
        entry_price = 0.0
        entry_score = 0.0

        for i, date in enumerate(dates):
            k = kline_by_date[date]
            close = k.get("close", k.get("Close", 0))
            if close <= 0:
                continue

            signal = signal_by_date.get(date)

            # 交易逻辑
            if not in_position and signal:
                direction = signal.get("direction", "neutral")
                score = signal.get("score", 50)

                if direction == "buy" and score >= 60:
                    # 买入
                    shares = int(self.position_size / close)
                    cost = shares * close * (1 + self.commission_rate)
                    if cost <= capital:
                        capital -= cost
                        position = shares
                        cost_basis = close
                        in_position = True
                        entry_date = date
                        entry_price = close
                        entry_score = score

            elif in_position:
                should_sell = False
                exit_reason = ""

                if signal:
                    direction = signal.get("direction", "neutral")
                    score = signal.get("score", 50)
                    if direction == "sell" and score >= 60:
                        should_sell = True
                        exit_reason = f"信号卖出(评分{score:.0f})"

                # 止损: -8%
                if not should_sell and close < cost_basis * 0.92:
                    should_sell = True
                    exit_reason = "止损(-8%)"

                # 最后一天强制平仓
                if not should_sell and i == len(dates) - 1:
                    should_sell = True
                    exit_reason = "回测结束平仓"

                if should_sell:
                    revenue = position * close * (1 - self.commission_rate)
                    capital += revenue
                    profit_pct = (close / entry_price - 1) * 100

                    trades.append(Trade(
                        stock_code=stock_code,
                        entry_date=entry_date,
                        exit_date=date,
                        direction="buy",
                        entry_price=entry_price,
                        exit_price=close,
                        quantity=position,
                        profit_pct=round(profit_pct, 2),
                        profit_amount=round(revenue - position * entry_price, 2),
                        holding_days=len(dates[:i + 1]) - len(dates[:dates.index(entry_date)]),
                        signal_score=entry_score,
                        exit_reason=exit_reason,
                    ))

                    position = 0
                    cost_basis = 0
                    in_position = False

            # 记录权益
            current_value = capital + (position * close if in_position else 0)
            equity.append({
                "date": date,
                "capital": round(capital, 2),
                "position_value": round(position * close, 2) if in_position else 0,
                "total": round(current_value, 2),
            })

        # 计算指标
        metrics = self._calculate_metrics(capital, trades, equity, len(dates))

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=dates[0] if dates else "",
            end_date=dates[-1] if dates else "",
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            metrics=metrics,
            trades=trades,
            equity_curve=equity,
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
