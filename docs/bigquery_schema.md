# BigQuery Dataset: `yfinance-gcp.yfinance_raw`

Financial data pipeline sourcing from Yahoo Finance. Covers ~2,700 stocks from S&P 500, Russell 2000 and STOXX 600.

---

## `daily_picks` — Top 20 daily opportunities

**The main output table.** Updated every trading day after market close. Contains the top 20 stock opportunities ranked by score (0–100), classified as ALCISTA (strong uptrend entry) or DIP (macro correction on a solid uptrend). The `reason` column explains in plain English why each stock was selected.

Filters applied: market cap ≥ $5B · Bullish trend now and 3 months ago · Analysts: buy or strong_buy only · Max –35% from 52-week high · Within 10% of SMA200.

Score breakdown (25 pts each): **A** momentum/prior strength · **B** RSI timing · **C** structural health vs SMA200 · **D** analyst consensus.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Date the picks were generated |
| `rank` | INTEGER | Position in today's ranking (1 = best) |
| `tipo` | STRING | `ALCISTA` (uptrend entry) or `DIP` (macro correction) |
| `symbol` | STRING | Stock ticker (e.g. AAPL, ASML.AS) |
| `sector` | STRING | Sector (e.g. Technology, Financials) |
| `industry` | STRING | Industry within the sector |
| `data_date` | DATE | Last trading day with available data |
| `close` | FLOAT | Closing price |
| `market_cap_bn` | FLOAT | Market cap in billions USD |
| `rsi_14` | FLOAT | RSI 14-period (0–100). <30 oversold, >70 overbought |
| `momentum_10d_pct` | FLOAT | Price change % over last 10 trading days |
| `dist_sma200_pct` | FLOAT | % distance from SMA200 (positive = above) |
| `pct_from_52w_high` | FLOAT | % drop from 52-week high (negative value) |
| `chg_1d_pct` | FLOAT | Price change % in last 1 day |
| `chg_3d_pct` | FLOAT | Price change % in last 3 days |
| `chg_5d_pct` | FLOAT | Price change % in last 5 days |
| `perf_6m_pct` | FLOAT | Performance % in the 6 months before the dip (DIP type) |
| `perf_1y_pct` | FLOAT | Performance % in the 1 year before the dip (DIP type) |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy` or `buy` |
| `score_a` | FLOAT | Score component A: momentum / prior strength (0–25) |
| `score_b` | FLOAT | Score component B: RSI timing (0–25) |
| `score_c` | FLOAT | Score component C: structural health vs SMA200 (0–25) |
| `score_d` | FLOAT | Score component D: analyst consensus (0–25) |
| `score_total` | FLOAT | Total score (0–100) |
| `reason` | STRING | Plain-English explanation of why this stock was selected |

---

## `enriched_prices_table` — Prices + technical & fundamental indicators

Full price history for all tracked stocks enriched with technical indicators and fundamental data. Updated daily. This is the analytical core of the pipeline — source for `daily_picks`.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Trading date |
| `symbol` | STRING | Stock ticker |
| `close` | FLOAT | Closing price |
| `volume` | INTEGER | Volume traded |
| `sector` | STRING | Sector (from companies) |
| `industry` | STRING | Industry (from companies) |
| `market_cap` | INTEGER | Market capitalisation in USD |
| `shares_outstanding` | INTEGER | Total shares outstanding |
| `trailing_eps` | FLOAT | Earnings per share (last 12 months) |
| `pe_ratio` | FLOAT | Price-to-earnings ratio (close / trailing_eps) |
| `beta` | FLOAT | Volatility relative to the market |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `rsi_14` | FLOAT | RSI 14-period (0–100) |
| `pct_from_52w_high` | FLOAT | % drop from 52-week high (negative) |
| `pct_from_52w_low` | FLOAT | % gain from 52-week low (positive) |
| `bollinger_high` | FLOAT | Bollinger upper band |
| `bollinger_low` | FLOAT | Bollinger lower band |
| `bollinger_pct` | FLOAT | Position within Bollinger bands (0 = lower band, 1 = upper band) |
| `long_term_trend` | STRING | `Bullish` if SMA50 > SMA200, `Bearish` otherwise |
| `macd_line` | FLOAT | MACD proxy (SMA12 – SMA26). Positive = bullish momentum |
| `momentum_10d` | FLOAT | Return over last 10 trading days (decimal, e.g. 0.08 = +8%) |
| `dist_sma_200` | FLOAT | Distance from SMA200 (decimal, e.g. 0.10 = 10% above) |

---

## `daily_prices` — Raw OHLCV prices

Raw price data downloaded daily from Yahoo Finance. One row per stock per trading day. No indicators — source for all technical calculations in `enriched_prices_table`.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Trading date |
| `symbol` | STRING | Stock ticker |
| `open` | FLOAT | Opening price |
| `high` | FLOAT | Daily high |
| `low` | FLOAT | Daily low |
| `close` | FLOAT | Closing price |
| `adj_close` | FLOAT | Adjusted closing price (accounts for splits and dividends) |
| `volume` | INTEGER | Volume traded |

---

## `companies` — Company fundamentals

Fundamental metadata for each tracked company, refreshed every Sunday. Accumulates one snapshot per week per symbol (historical record). Used to enrich `enriched_prices_table` with fundamentals.

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | STRING | Stock ticker |
| `source` | STRING | Index source: `sp500`, `russell2000`, `stoxx600` |
| `short_name` | STRING | Short company name |
| `long_name` | STRING | Full legal company name |
| `business_summary` | STRING | Business description from Yahoo Finance |
| `provider` | STRING | Data provider (always `yahoo`) |
| `is_active` | BOOLEAN | Whether the symbol is currently active on Yahoo Finance |
| `last_checked` | TIMESTAMP | Last time the symbol was validated |
| `last_seen` | DATE | Last date the symbol was seen active |
| `quote_type` | STRING | Instrument type (e.g. `EQUITY`) |
| `exchange` | STRING | Exchange code (e.g. `NMS`, `LSE`) |
| `exchange_timezone` | STRING | Exchange timezone (e.g. `America/New_York`) |
| `currency` | STRING | Trading currency (e.g. `USD`, `EUR`) |
| `market` | STRING | Market identifier |
| `country` | STRING | Country of incorporation |
| `sector` | STRING | Sector (e.g. Technology, Financials) |
| `industry` | STRING | Industry within the sector |
| `market_cap` | INTEGER | Market capitalisation in USD |
| `shares_outstanding` | INTEGER | Total shares outstanding |
| `float_shares` | INTEGER | Floating shares (publicly tradeable) |
| `avg_volume_3m` | INTEGER | Average daily volume over last 3 months |
| `avg_volume_10d` | INTEGER | Average daily volume over last 10 days |
| `beta` | FLOAT | Volatility relative to the market |
| `trailing_eps` | FLOAT | Earnings per share (last 12 months) |
| `forward_eps` | FLOAT | Estimated earnings per share (next 12 months) |
| `book_value` | FLOAT | Book value per share |
| `dividend_rate` | FLOAT | Annual dividend per share |
| `ex_dividend_date` | INTEGER | Ex-dividend date (Unix timestamp) |
| `forward_pe` | FLOAT | Forward price-to-earnings ratio |
| `dividend_yield` | FLOAT | Dividend yield (decimal, e.g. 0.03 = 3%) |
| `return_on_equity` | FLOAT | Return on equity (ROE) |
| `target_mean_price` | FLOAT | Analyst mean price target |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `updated_at` | DATE | Date of this weekly snapshot |
