"""AI Pipeline Runner — the daily decision loop.

Closes the loop that makes every Dashboard/Portfolio/Journal/Resume work:

  Market Data → Scanner → Signals → Decisions → Journal → Stats

Previously: each step existed but nothing connected them.
Now: run_pipeline() orchestrates the full daily flow.

Usage:
  runner = AIPipelineRunner()
  await runner.run_daily_pipeline()  # → produces today's decisions

Output:
  - Decisions saved to SQLite (decision_journal table)
  - Trust/Resume/Journal pages read from real data
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class PipelineResult:
    """Result of one pipeline run."""
    run_date: str = ""
    stocks_scanned: int = 0
    signals_computed: int = 0
    decisions_generated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    top_picks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_date": self.run_date,
            "stocks_scanned": self.stocks_scanned,
            "signals_computed": self.signals_computed,
            "decisions_generated": self.decisions_generated,
            "errors": self.errors[:5],
            "duration_seconds": round(self.duration_seconds, 1),
            "top_picks": self.top_picks[:10],
        }


class AIPipelineRunner:
    """Orchestrates the daily AI decision pipeline.

    Single entry point. Call run_daily_pipeline() once per day.
    Results are persisted: Dashboard/Decision/Journal read from DB.
    """

    # Default stock universe — scanned every day
    async def run_daily_pipeline(
        self,
        codes: list[str] = None,
        save_to_journal: bool = True,
    ) -> PipelineResult:
        """Run the full daily AI decision pipeline.

        1. Fetch real K-line data for each stock
        2. Compute signals (MACD/RSI/KDJ/MA/Volume)
        3. Generate decisions (BUY/SELL/HOLD with scores)
        4. Save to decision journal (persistent)
        5. Return top picks for dashboard

        Args:
            codes: Stock codes to scan. None = default universe.
            save_to_journal: Whether to persist decisions to DB.

        Returns:
            PipelineResult with summary stats and top picks.
        """
        from src.infrastructure.market_data.real_data_provider import real_data
        from src.infrastructure.storage.market_database import market_db

        universe_by_code = {}
        if codes is None:
            universe = await real_data.get_stock_universe()
            universe_by_code = {s["code"]: s for s in universe if s.get("code")}
            codes = list(universe_by_code)

        result = PipelineResult(run_date=date.today().isoformat())
        t0 = time.time()
        decisions = []

        for code in codes:
            try:
                name = universe_by_code.get(code, {}).get("name", code)
                bars = await real_data.get_daily_bars(code, days=250)
                result.stocks_scanned += 1

                if not bars or len(bars) < 20:
                    continue

                sig = real_data.compute_signals(code, name, bars)
                result.signals_computed += 1

                # Only generate decisions for strong signals
                if abs(sig.fusion_score - 50) < 5:
                    continue

                rec = (
                    "强烈买入" if sig.fusion_score >= 80 else
                    "买入" if sig.fusion_score >= 65 else
                    "观望" if sig.fusion_score >= 50 else
                    "减仓" if sig.fusion_score >= 35 else "卖出"
                )

                decision = {
                    "date": date.today().isoformat(),
                    "stock_code": code,
                    "stock_name": name,
                    "ai_score": sig.fusion_score,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "recommendation": rec,
                    "fusion_score": sig.fusion_score,
                    "macd_score": sig.macd_score,
                    "rsi_score": sig.rsi_score,
                    "kdj_score": sig.kdj_score,
                    "ma_score": sig.ma_score,
                    "volume_score": sig.volume_score,
                    "buy_signals": sum(
                        1 for s in [
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score, sig.volume_score,
                        ] if s >= 65
                    ),
                    "sell_signals": sum(
                        1 for s in [
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score, sig.volume_score,
                        ] if s <= 35
                    ),
                    "evidence": (
                        f"MACD/RSI/KDJ/MA/Volume from {sig.data_days} real bars"
                    ),
                }

                if save_to_journal:
                    market_db.save_decision(decision)

                decisions.append(decision)
                result.decisions_generated += 1

            except Exception as e:
                result.errors.append(f"{code}: {str(e)[:80]}")

        # Sort by score, top picks for dashboard
        decisions.sort(key=lambda d: -d["ai_score"])
        result.top_picks = [
            {
                "stock_code": d["stock_code"],
                "stock_name": d["stock_name"],
                "ai_score": round(d["ai_score"], 1),
                "direction": d["direction"],
                "recommendation": d["recommendation"],
            }
            for d in decisions
        ]

        result.duration_seconds = time.time() - t0
        return result


# Singleton
pipeline_runner = AIPipelineRunner()
