# QuantAI Research Terminal

**Adaptive Investment Intelligence** — a VSCode extension for verifiable investment research on A-shares.

## Features

- **Watchlist 自选股** — auto-refreshing watchlist with AI scores / signals / risk. Add by 6-digit code (auto-normalized to `.SZ/.SH/.BJ`), remove via the ✕ button.
- **Market Overview** — indices (上证/深证/创业板/科创50), market breadth, sector ranking.
- **Stock Research** — per-stock deep report with K-line, indicators, AI verdict.
- **Decision Journal** — every AI decision recorded with track record & calibration.
- **Daily Brief / Alerts / Backtest / Replay** — full research workflow.

## Data

Multi-provider market data with auto-failover: iFind → Tencent → akshare (quote/kline), baostock (daily bars), with explicit provenance on every data point.

## Development

```bash
npm install
npm run compile      # tsc -p ./
# F5 in VSCode → "Run AI Research Extension" launches Extension Development Host
```

> After changing any `src/**` code: `npm run compile` → close the Dev Host window → F5 again. Reload Window is NOT enough (retainContextWhenHidden + require cache).
