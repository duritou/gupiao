"""Scanner Engine — 三层筛选管道

Layer 1 (Coarse):  排除 ST/次新/小市值/无成交
Layer 2 (Technical): MACD趋势 + 均线位置 + 成交量 + RSI 区间
Layer 3 (Score):    SignalFusion 评分 + 排序

输出: ResearchCandidate 列表
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.domain.models.research_candidate import ResearchCandidate, ScannerResult
from src.signals.builtin.technical import MACDSignal, MASignal, VolumeSignal, RSISignal
from src.signals.fusion import SignalFusion


@dataclass
class ScannerConfig:
    """Scanner 配置"""
    min_market_cap: float = 20.0           # 最小市值（亿）
    min_daily_amount: float = 50.0         # 最小日均成交额（百万元）
    exclude_st: bool = True
    exclude_new_ipo_days: int = 60
    coarse_target: int = 0                 # 0 = 不限制
    technical_target: int = 100
    score_top_n: int = 20

    # 技术筛选参数
    require_above_ma20: bool = True
    require_volume_ratio_min: float = 0.8
    require_rsi_min: int = 30
    require_rsi_max: int = 70


class ScannerEngine:
    """全市场扫描引擎"""

    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or ScannerConfig()
        self._fusion = SignalFusion([
            MACDSignal(), RSISignal(), MASignal(), VolumeSignal(),
        ])

    async def scan(
        self,
        stock_pool: list[dict],
        kline_data: dict[str, list[dict]] | None = None,
    ) -> ScannerResult:
        """执行全市场扫描

        Args:
            stock_pool: [{"code":"000001.SZ","name":"平安银行","market_cap":...,...}, ...]
            kline_data: {"000001.SZ": [OHLCV dicts], ...}  (可选，若无则只用 stock_pool)

        Returns:
            ScannerResult with ranked candidates
        """
        start = time.perf_counter()
        scan_date = ""
        total = len(stock_pool)

        # Layer 1: Coarse
        coarse_result = self._coarse_filter(stock_pool)
        after_coarse = len(coarse_result)

        # Layer 2: Technical
        technical_result = self._technical_filter(coarse_result, kline_data or {})
        after_technical = len(technical_result)

        # Layer 3: Score
        candidates = await self._score_and_rank(technical_result, kline_data or {})

        elapsed = (time.perf_counter() - start) * 1000

        return ScannerResult(
            scan_date=scan_date,
            total_scanned=total,
            after_coarse=after_coarse,
            after_technical=after_technical,
            after_scoring=len(candidates),
            candidates=candidates[:self.config.score_top_n],
            duration_ms=round(elapsed, 1),
        )

    # ===== Layer 1: Coarse Filter =====

    def _coarse_filter(self, stocks: list[dict]) -> list[dict]:
        """粗筛：排除不合格标的"""
        result = []
        for s in stocks:
            # ST
            if self.config.exclude_st and ("ST" in s.get("name", "") or "*ST" in s.get("name", "")):
                continue
            # 市值
            if s.get("market_cap", 0) < self.config.min_market_cap:
                continue
            # 成交额
            if s.get("avg_amount", 0) < self.config.min_daily_amount:
                continue
            # 停牌 (价格为0或负数)
            if s.get("price", 0) <= 0:
                continue
            result.append(s)
        return result

    # ===== Layer 2: Technical Filter =====

    def _technical_filter(
        self, stocks: list[dict], kline_data: dict[str, list[dict]]
    ) -> list[dict]:
        """技术筛选：基于K线数据快速过滤"""
        result = []
        for s in stocks:
            code = s.get("code", "")
            klines = kline_data.get(code, [])

            if not klines or len(klines) < 20:
                # 无K线数据的标的仍保留（让其通过评分层）
                result.append(s)
                continue

            if self._pass_technical_quick(klines):
                result.append(s)

            if self.config.technical_target and len(result) >= self.config.technical_target:
                break

        return result

    def _pass_technical_quick(self, klines: list[dict]) -> bool:
        """快速技术筛选（不调用完整信号计算，节省时间）"""
        if len(klines) < 20:
            return False

        closes = [k["close"] for k in klines]
        volumes = [k.get("volume", 0) for k in klines]
        current = closes[-1]

        # 站上 MA20
        if self.config.require_above_ma20:
            ma20 = sum(closes[-20:]) / 20
            if current < ma20:
                return False

        # 成交量
        if self.config.require_volume_ratio_min > 0:
            avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes[:-1]) / max(len(volumes) - 1, 1)
            if avg_vol > 0 and volumes[-1] / avg_vol < self.config.require_volume_ratio_min:
                return False

        # RSI 简易版
        if len(closes) >= 15:
            gains = sum(max(closes[i] - closes[i - 1], 0) for i in range(-14, 0))
            losses = sum(max(closes[i - 1] - closes[i], 0) for i in range(-14, 0))
            if losses > 0:
                rs = gains / losses
                rsi = 100 - 100 / (1 + rs)
                if rsi < self.config.require_rsi_min or rsi > self.config.require_rsi_max:
                    return False

        return True

    # ===== Layer 3: Score & Rank =====

    async def _score_and_rank(
        self, stocks: list[dict], kline_data: dict[str, list[dict]]
    ) -> list[ResearchCandidate]:
        """SignalFusion 评分 + 排序"""
        candidates = []

        for s in stocks:
            code = s.get("code", "")
            klines = kline_data.get(code, [])

            if not klines or len(klines) < 20:
                # 无K线数据：给中性分
                candidates.append(ResearchCandidate(
                    stock_code=code,
                    stock_name=s.get("name", ""),
                    fusion_score=50.0,
                    candidate_type="scanner",
                    passed_coarse=True,
                    passed_technical=True,
                    market_cap=s.get("market_cap", 0),
                    change_pct=s.get("change_pct", 0),
                ))
                continue

            fusion_result = await self._fusion.score(code, klines)

            candidate = ResearchCandidate(
                stock_code=code,
                stock_name=s.get("name", ""),
                fusion_score=fusion_result.final_score,
                score_breakdown=fusion_result.individual_scores,
                direction=fusion_result.direction.value,
                confidence=fusion_result.confidence,
                candidate_type="scanner",
                passed_coarse=True,
                passed_technical=True,
                market_cap=s.get("market_cap", 0),
                change_pct=s.get("change_pct", 0),
                reasons=fusion_result.reasons,
                tags=self._extract_tags(fusion_result),
            )
            candidates.append(candidate)

        # 排序
        candidates.sort(key=lambda c: c.fusion_score, reverse=True)
        for i, c in enumerate(candidates):
            c.rank = i + 1

        return candidates

    def _extract_tags(self, fusion_result) -> list[str]:
        """从融合结果中提取标签"""
        tags = []
        if fusion_result.direction.value == "buy":
            tags.append("看多")
        elif fusion_result.direction.value == "sell":
            tags.append("看空")
        if fusion_result.confidence > 0.7:
            tags.append("高置信")
        if fusion_result.buy_signals >= 3:
            tags.append("多信号共振")
        return tags
