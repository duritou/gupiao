"""内置技术信号 — MACD / RSI / KDJ / MA / Volume / BOLL

每个信号输入 OHLCV list[dict]，输出 SignalResult(score 0-100, direction).
"""

from __future__ import annotations

from src.signals.base import BaseSignal, SignalResult, SignalDirection, SignalCategory


def _closes(data: list[dict]) -> list[float]:
    return [d["close"] for d in data]


def _highs(data: list[dict]) -> list[float]:
    return [d["high"] for d in data]


def _lows(data: list[dict]) -> list[float]:
    return [d["low"] for d in data]


def _volumes(data: list[dict]) -> list[int]:
    return [d.get("volume", 0) for d in data]


def _ema(values: list[float], period: int) -> list[float]:
    """指数移动平均"""
    if len(values) < period:
        return [values[-1]] * len(values) if values else []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return [result[0]] * (period - 1) + result  # 补齐前 N-1 个


def _sma(values: list[float], period: int) -> list[float]:
    """简单移动平均"""
    if len(values) < period:
        return [values[-1]] * len(values) if values else []
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(sum(values[:i + 1]) / (i + 1))
        else:
            result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def _max(values: list[float], period: int) -> list[float]:
    result = []
    for i in range(len(values)):
        start = max(0, i - period + 1)
        result.append(max(values[start:i + 1]))
    return result


def _min(values: list[float], period: int) -> list[float]:
    result = []
    for i in range(len(values)):
        start = max(0, i - period + 1)
        result.append(min(values[start:i + 1]))
    return result


# ===== MACD =====

class MACDSignal(BaseSignal):
    """MACD 信号 — DIF/DEA 金叉死叉 + 零轴位置 + 背离"""

    name = "macd"
    category = SignalCategory.TECHNICAL
    default_weight = 1.0

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.slow + self.signal_period:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        closes = _closes(data)
        ema_fast = _ema(closes, self.fast)
        ema_slow = _ema(closes, self.slow)
        dif = [f - s for f, s in zip(ema_fast, ema_slow)]
        dea = _ema(dif, self.signal_period)
        macd_bar = [(d - e) * 2 for d, e in zip(dif, dea)]

        score = 50.0
        reasons = []

        # 金叉/死叉（最近3根）
        if len(dif) >= 3 and len(dea) >= 3:
            if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
                score += 15
                reasons.append("金叉")
            elif dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
                score -= 15
                reasons.append("死叉")

        # 零轴位置
        if dif[-1] > 0:
            score += 10
            reasons.append("零轴上方")
        else:
            score -= 5

        # MACD 柱变化
        if len(macd_bar) >= 2:
            if macd_bar[-1] > macd_bar[-2] and macd_bar[-2] < 0:
                score += 5
                reasons.append("绿柱缩短")
            elif macd_bar[-1] < macd_bar[-2] and macd_bar[-2] > 0:
                score -= 5
                reasons.append("红柱缩短")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons) or "MACD中性",
                            {"dif": round(dif[-1], 4), "dea": round(dea[-1], 4),
                             "bar": round(macd_bar[-1], 4)})


# ===== RSI =====

class RSISignal(BaseSignal):
    """RSI 信号 — 超买超卖 + 背离"""

    name = "rsi"
    category = SignalCategory.TECHNICAL
    default_weight = 0.8

    def __init__(self, period: int = 14):
        self.period = period

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.period + 1:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        closes = _closes(data)
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains[:self.period]) / self.period
        avg_loss = sum(losses[:self.period]) / self.period

        rsi_values = []
        for i in range(self.period, len(gains)):
            avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi_values.append(100 - 100 / (1 + rs))

        if not rsi_values:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "无法计算RSI")

        rsi = rsi_values[-1]
        score = 50.0
        reasons = []

        if rsi < 30:
            score += 20
            reasons.append(f"超卖(RSI={rsi:.0f})")
        elif rsi > 70:
            score -= 20
            reasons.append(f"超买(RSI={rsi:.0f})")
        elif 40 <= rsi <= 60:
            reasons.append(f"中性(RSI={rsi:.0f})")
        elif rsi > 50:
            score += 5
            reasons.append(f"偏强(RSI={rsi:.0f})")
        else:
            score -= 5
            reasons.append(f"偏弱(RSI={rsi:.0f})")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons), {"rsi": round(rsi, 2)})


# ===== KDJ =====

class KDJJSignal(BaseSignal):
    """KDJ 信号"""

    name = "kdj"
    category = SignalCategory.TECHNICAL
    default_weight = 0.7

    def __init__(self, period: int = 9, k_period: int = 3, d_period: int = 3):
        self.period = period
        self.k_period = k_period
        self.d_period = d_period

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.period:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        highs = _highs(data)
        lows = _lows(data)
        closes = _closes(data)

        k_values, d_values = [], []
        for i in range(self.period - 1, len(data)):
            highest = max(highs[i - self.period + 1:i + 1])
            lowest = min(lows[i - self.period + 1:i + 1])
            rsv = ((closes[i] - lowest) / (highest - lowest) * 100) if highest != lowest else 50
            k_values.append(rsv if not k_values else k_values[-1] * (self.k_period - 1) / self.k_period + rsv / self.k_period)
            d_values.append(k_values[-1] if not d_values else d_values[-1] * (self.d_period - 1) / self.d_period + k_values[-1] / self.d_period)

        if not k_values:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "")

        k, d = k_values[-1], d_values[-1]
        j = 3 * k - 2 * d
        score = 50.0
        reasons = []

        if k < 20 and d < 20:
            score += 20
            reasons.append("超卖区")
        elif k > 80 and d > 80:
            score -= 15
            reasons.append("超买区")

        if len(k_values) >= 2 and len(d_values) >= 2:
            if k_values[-2] <= d_values[-2] and k > d:
                score += 10
                reasons.append("KD金叉")
            elif k_values[-2] >= d_values[-2] and k < d:
                score -= 10
                reasons.append("KD死叉")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons) or "KDJ中性",
                            {"k": round(k, 2), "d": round(d, 2), "j": round(j, 2)})


# ===== MA =====

class MASignal(BaseSignal):
    """均线信号 — 多头/空头排列 + 突破"""

    name = "ma"
    category = SignalCategory.TECHNICAL
    default_weight = 0.7

    def __init__(self, short: int = 5, mid: int = 20, long: int = 60):
        self.short = short
        self.mid = mid
        self.long = long

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.long:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        closes = _closes(data)
        ma_short = _sma(closes, self.short)[-1]
        ma_mid = _sma(closes, self.mid)[-1]
        ma_long = _sma(closes, self.long)[-1]
        current = closes[-1]

        score = 50.0
        reasons = []

        # 均线排列
        if ma_short > ma_mid > ma_long:
            score += 20
            reasons.append("多头排列")
        elif ma_short < ma_mid < ma_long:
            score -= 15
            reasons.append("空头排列")

        # 价格与均线关系
        if current > ma_mid:
            score += 5
            reasons.append(f"站上MA{self.mid}")
        else:
            score -= 5
            reasons.append(f"跌破MA{self.mid}")

        if len(closes) >= 2:
            if closes[-2] <= ma_mid and current > ma_mid:
                score += 10
                reasons.append(f"突破MA{self.mid}")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons) or "均线中性",
                            {"ma_short": round(ma_short, 2), "ma_mid": round(ma_mid, 2),
                             "ma_long": round(ma_long, 2)})


# ===== Volume =====

class VolumeSignal(BaseSignal):
    """成交量信号 — 放量/缩量/量价配合"""

    name = "volume"
    category = SignalCategory.VOLUME
    default_weight = 0.8

    def __init__(self, period: int = 20):
        self.period = period

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.period + 1:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        closes = _closes(data)
        volumes = _volumes(data)

        avg_vol = sum(volumes[-self.period - 1:-1]) / self.period if self.period > 0 else 1
        current_vol = volumes[-1]
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        price_up = closes[-1] > closes[-2] if len(closes) >= 2 else False

        score = 50.0
        reasons = []

        if vol_ratio > 2.0 and price_up:
            score += 20
            reasons.append(f"放量上涨({vol_ratio:.1f}x)")
        elif vol_ratio > 2.0 and not price_up:
            score -= 15
            reasons.append(f"放量下跌({vol_ratio:.1f}x)")
        elif vol_ratio > 1.5 and price_up:
            score += 10
            reasons.append(f"温和放量上涨({vol_ratio:.1f}x)")
        elif vol_ratio < 0.5:
            score -= 5
            reasons.append(f"极度缩量({vol_ratio:.1f}x)")
        else:
            reasons.append(f"量能正常({vol_ratio:.1f}x)")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons), {"vol_ratio": round(vol_ratio, 2)})


# ===== BOLL =====

class BOLLSignal(BaseSignal):
    """布林带信号 — 带宽 + 位置"""

    name = "boll"
    category = SignalCategory.TECHNICAL
    default_weight = 0.6

    def __init__(self, period: int = 20, std: float = 2.0):
        self.period = period
        self.std = std

    async def compute(self, stock_code: str, data: list[dict]) -> SignalResult:
        if len(data) < self.period:
            return SignalResult(self.name, self.category, 50, SignalDirection.NEUTRAL, "数据不足")

        closes = _closes(data)
        mid = _sma(closes, self.period)

        import math
        upper, lower = [], []
        for i in range(len(closes)):
            if i < self.period - 1:
                upper.append(closes[i])
                lower.append(closes[i])
            else:
                window = closes[i - self.period + 1:i + 1]
                avg = sum(window) / self.period
                variance = sum((x - avg) ** 2 for x in window) / self.period
                std_dev = math.sqrt(variance)
                upper.append(avg + self.std * std_dev)
                lower.append(avg - self.std * std_dev)

        current = closes[-1]
        mid_val = mid[-1]
        upper_val = upper[-1]
        lower_val = lower[-1]
        bandwidth = (upper_val - lower_val) / mid_val * 100 if mid_val > 0 else 0

        score = 50.0
        reasons = []

        position = (current - lower_val) / (upper_val - lower_val) if upper_val != lower_val else 0.5

        if position < 0.2:
            score += 15
            reasons.append("触及下轨")
        elif position > 0.8:
            score -= 10
            reasons.append("触及上轨")
        elif 0.4 <= position <= 0.6:
            reasons.append("中轨附近")

        if bandwidth < 5:
            score += 5
            reasons.append("带宽收窄(可能变盘)")

        direction = SignalDirection.BUY if score >= 60 else (
            SignalDirection.SELL if score <= 40 else SignalDirection.NEUTRAL
        )
        return SignalResult(self.name, self.category, max(0, min(100, score)), direction,
                            "; ".join(reasons) or "布林带中性",
                            {"upper": round(upper_val, 2), "mid": round(mid_val, 2),
                             "lower": round(lower_val, 2), "bandwidth": round(bandwidth, 1)})
