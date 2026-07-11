# Data Migration Progress — Mock → Real

## Goal: 20/20 production-backed routes

| # | Route File | Status | Data Source |
|---|-----------|--------|-------------|
| 1 | `detail_routes.py` | ✅ Real | SourceManager (baostock) |
| 2 | `market_routes.py` | ✅ Real | SourceManager |
| 3 | `scanner_routes.py` | ✅ Real | RealDataProvider → baostock |
| 4 | `signals_routes.py` | ✅ Real | RealDataProvider → baostock |
| 5 | `decision_routes.py` | ✅ Real (/today, /allocate) | RealDataProvider → baostock |
| 6 | `trust_routes.py` | ✅ Honest | 显示"数据积累中" |
| 7 | `user_routes.py` | ✅ Honest | 显示"数据积累中" |
| 8 | `portfolio_routes.py` | ❌ Mock | `mock_signal_result`, `generate_klines` |
| 9 | `alerts_routes.py` | ❌ Mock | `generate_intelligent_alerts` |
| 10 | `compare_routes.py` | ❌ Mock | `generate_klines`, `mock_signal_result` |
| 11 | `timeline_routes.py` | ❌ Mock | `generate_timeline` |
| 12 | `dailybrief_routes.py` | ❌ Mock | `generate_daily_brief` |
| 13 | `research_routes.py` | ❌ Mock | `generate_stock_pool`, `generate_klines` |
| 14 | `explain_routes.py` | ❌ Mock | `generate_klines`, `mock_signal_result` |
| 15 | `knowledge_graph_routes.py` | ❌ Mock | Hardcoded events |
| 16 | `ai_os_routes.py` | ❌ Mock | Hardcoded 22 events |
| 17 | `replay_routes.py` | ❌ Mock | `generate_klines`, `mock_signal_result` |
| 18 | `backtest_routes.py` | ❌ Mock | `math.sin` inline |
| 19 | `morning_brief_routes.py` | ❌ Mock | Multiple mock functions |
| 20 | `alerts_routes.py` | ⏸️ Paused | 待真实事件触发 |

## Progress: 7/20

## Feature Freeze (effective immediately)
- No new engines
- No new pages
- No new API endpoints
- Only data migration work

## Data Source Priority
1. ✅ Tushare (trust=0.96) — most reliable A-share + financial data  ← NEW
2. ✅ baostock (T-1 daily close) — A-share fallback
3. ✅ Finnhub/FMP/TwelveData/Polygon/AlphaVantage — global APIs
4. ⏳ AkShare — real-time (blocked by anti-scraping, low priority)
