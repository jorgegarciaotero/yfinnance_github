# BigQuery Dataset: `yfinance-gcp.yfinance_raw`

Financial data pipeline sourcing from Yahoo Finance. Covers ~2,700 stocks from S&P 500, Russell 2000 and STOXX 600, plus commodity ETFs (GLD, SLV, USO, CPER, PPLT, URA) and bond ETFs (TLT, IEF).

---

## Pipeline — Cloud Run Jobs (`europe-west1`)

All jobs use the image `europe-west1-docker.pkg.dev/yfinance-gcp/stock-jobs/stock-jobs:latest` with `command: python`.

### Execution order (daily, after market close)

```
daily-prices-job  →  daily-enrich-job  →  daily-sector-job  ┐
                                       └→  daily-anomaly-job ┴→  daily-news-job  →  daily-narrative-job
```

| Job | Script | Frequency | What it does |
|-----|--------|-----------|--------------|
| `daily-prices-job` | `src/jobs/daily_prices.py` | Daily | Downloads OHLCV prices from Yahoo Finance for all active symbols. MERGE into `daily_prices` by `(date, symbol)`. On first run: full backfill. |
| `daily-enrich-job` | `src/jobs/daily_enrich.py` | Daily (after prices) | Joins prices + company fundamentals + computes technical indicators (RSI, SMA, Bollinger, MACD, momentum). Full load if table is >7 days stale, otherwise incremental MERGE over a 30-day window. Writes to `enriched_prices_table`. |
| `daily-sector-job` | `src/jobs/daily_sector_opportunities.py` | Daily (after enrich) | Runs the sector opportunities SQL. For each sector produces top 10 picks × 3 setup types (Dip / Momentum / Value Reversal), each scored 0–100. DELETE + INSERT on `max_date` (idempotent). Writes to `sector_daily_opportunities`. |
| `daily-anomaly-job` | `src/jobs/daily_anomaly_radar.py` | Daily (after enrich) | Detects market anomalies in 3 categories (Spike / Oversold / Momentum). Scans only 40 days with LAG(). Top 5 per sector. Idempotent DELETE + INSERT. Writes to `anomaly_radar`. |
| `daily-news-job` | `src/jobs/daily_news_enrich.py` | Daily (after sector + anomaly) | Fetches news and social mentions for every symbol in today's radar + opportunities output. Sources: Yahoo Finance news (yfinance) and Reddit (r/stocks, r/investing, r/wallstreetbets). No API keys required. Writes to `company_news`. |
| `daily-narrative-job` | `src/jobs/daily_narrative.py` | Daily (after news) | For each symbol in today's radar + opportunities, picks the top news from `company_news` and calls Claude Haiku to generate a 3-sentence dealflow narrative. MERGEs `top_news_title`, `top_news_url`, `narrative` into both output tables. Requires `ANTHROPIC_API_KEY` secret. |
| `weekly-companies` | `src/jobs/weekly_companies.py` | Weekly (Sundays) | Refreshes the company universe (S&P 500, Russell 2000, STOXX 600, commodity ETFs, bond ETFs). Validates each symbol against Yahoo Finance and updates fundamental metadata. MERGE into `companies` by `(symbol, updated_at)` — accumulates weekly history. |

### Redeploy

```bash
bash deploy.sh
```

Builds the image via Cloud Build and updates all jobs. `daily-scanner-job` is automatically deleted if it exists (obsolete — was pointing to a removed script).

---

## `anomaly_radar` — Daily market anomaly detector

Daily market anomaly radar. Scans only the last 40 days of `enriched_prices_table` using LAG windows (minimum cost). Partitioned by `date`, clustered by `anomaly_type` and `sector`.

**Anomaly types:**
- `Volume/Price Spike` — strong price impulse (≥3% in 1d, ≥7% in 3d, or ≥10% in 7d) with volume ≥1.5× the 20-day average.
- `Critical Oversold` — RSI < 30 with drop ≥8% in 3d or ≥12% in 7d. Candidates for a temporary bounce.
- `Confirmed Momentum` — sustained sector leaders: +8% in 30d, +2% in 7d, no reversal in 3d.

**Score (0–100, varies by category):**

| Type | Component A | Component B |
|------|------------|------------|
| Spike | 50pts — best daily rate (5%/day = max) | 50pts — volume ratio (×1.5=0, ×5=max) |
| Critical Oversold | 50pts — RSI depth (RSI 0=max) | 50pts — drop magnitude (−28%=max) |
| Confirmed Momentum | 30pts 30d + 30pts 7d | 20pts 3d + 20pts 1d |

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Generation date (partition key) |
| `sector` | STRING | Stock sector |
| `industry` | STRING | Industry within the sector |
| `symbol` | STRING | Ticker |
| `anomaly_type` | STRING | `Volume/Price Spike`, `Critical Oversold`, or `Confirmed Momentum` |
| `close` | FLOAT | Closing price |
| `market_cap_bn` | FLOAT | Market capitalisation in billions USD |
| `rsi_14` | FLOAT | RSI 14-period |
| `change_1d_pct` | FLOAT | % change in 1 day |
| `change_3d_pct` | FLOAT | % change in 3 days |
| `change_7d_pct` | FLOAT | % change in 7 days |
| `change_30d_pct` | FLOAT | % change in ~21 trading days (~1 month) |
| `volume_ratio` | FLOAT | Today's volume / 20-day average (1.0 = normal) |
| `score` | FLOAT | Composite score 0–100 |
| `rank_in_sector` | INTEGER | Rank within sector + type (1 = best, max 5) |
| `reason` | STRING | One-line summary with key data points |
| `company_name` | STRING | Short company name (from companies table) |
| `company_url` | STRING | Yahoo Finance URL: `https://finance.yahoo.com/quote/{symbol}` |
| `company_summary` | STRING | Business description, truncated to 500 chars (from companies table) |
| `top_news_title` | STRING | Headline of the top recent news article (filled by `daily-narrative-job`) |
| `top_news_url` | STRING | Direct link to the top news article |
| `narrative` | STRING | 3-sentence LLM dealflow narrative: key catalyst → supporting evidence → outlook |

---

## `sector_daily_opportunities` — Sector-based daily investment setups

**The main output table.** Updated every trading day after market close. For each sector, extracts up to 10 companies in three distinct setup categories, each with a composite score (0–100) and a plain-English reason. Partitioned by `date`, clustered by `sector` and `setup_type` for efficient queries.

**Setup categories:**
- `Dip (Bullish Trend)` — confirmed Bullish trend with RSI in oversold zone (30–45) and negative momentum. Best dip-buying entries within an uptrend.
- `Momentum (Leaders)` — sector leaders near their 52-week highs with strong momentum (>+2% in 10d) and RSI in momentum zone (55–75).
- `Value Reversal` — deep corrections (>−30% from 52w high) with low PE ratio (<20) and analyst buy/strong_buy consensus.

**Score (0–100, 4 components × 25 pts):**

| Setup | A | B | C | D |
|-------|---|---|---|---|
| Dip | RSI oversold depth | Health vs SMA200 | Analyst consensus | Market cap quality |
| Momentum | Momentum 10d strength | RSI sweet spot (bell at 65) | Closeness to 52w high | Analyst consensus |
| Value Reversal | PE quality (lower = better) | Upside potential depth | Analyst consensus | Market cap quality |

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Date the opportunities were generated (partition key) |
| `sector` | STRING | Sector (e.g. Technology, Financials) |
| `industry` | STRING | Industry within the sector |
| `symbol` | STRING | Stock ticker (e.g. AAPL, ASML.AS) |
| `setup_type` | STRING | `Dip (Bullish Trend)`, `Momentum (Leaders)`, or `Value Reversal` |
| `close` | FLOAT | Closing price |
| `market_cap_bn` | FLOAT | Market capitalisation in billions USD |
| `rsi_14` | FLOAT | RSI 14-period (0–100). <30 oversold, >70 overbought |
| `momentum_10d_pct` | FLOAT | Price change % over last 10 trading days |
| `dist_sma200_pct` | FLOAT | % distance from SMA200 (positive = above) |
| `pct_from_52w_high` | FLOAT | % drop from 52-week high (negative value) |
| `pct_from_52w_low` | FLOAT | % gain from 52-week low (positive value) |
| `pe_ratio` | FLOAT | Price-to-earnings ratio (close / trailing_eps) |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `score` | FLOAT | Composite score 0–100 (higher = better opportunity within its category) |
| `rank_in_sector` | INTEGER | Rank within its sector + setup_type (1 = best, max 10) |
| `reason` | STRING | Plain-English explanation of why this stock was selected |
| `company_name` | STRING | Short company name (from companies table) |
| `company_url` | STRING | Yahoo Finance URL: `https://finance.yahoo.com/quote/{symbol}` |
| `company_summary` | STRING | Business description, truncated to 500 chars (from companies table) |
| `top_news_title` | STRING | Headline of the top recent news article (filled by `daily-narrative-job`) |
| `top_news_url` | STRING | Direct link to the top news article |
| `narrative` | STRING | 3-sentence LLM dealflow narrative: key catalyst → supporting evidence → outlook |

---

## `company_news` — Daily news and social media mentions

News articles and community discussions fetched daily for every symbol appearing in `anomaly_radar` or `sector_daily_opportunities`. Partitioned by `date`, clustered by `symbol` and `source`.

**Sources (all free, no API key required):**
- `yahoo_finance` — recent news articles via yfinance. Covers mainstream financial media (Reuters, Bloomberg, Motley Fool, etc.)
- `reddit` — top posts from the past week in r/stocks, r/investing, r/wallstreetbets via the public Reddit JSON API.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Fetch date (partition key) |
| `symbol` | STRING | Stock ticker |
| `source` | STRING | `yahoo_finance` or `reddit` |
| `title` | STRING | Article or post title |
| `url` | STRING | Direct link to the article or Reddit post |
| `published_at` | TIMESTAMP | When the article/post was published (UTC) |
| `summary` | STRING | Article summary or Reddit post body (truncated to 600 chars) |
| `score` | INTEGER | Reddit upvotes; NULL for Yahoo Finance |
| `num_comments` | INTEGER | Reddit comment count; NULL for Yahoo Finance |
| `publisher` | STRING | News publisher (Yahoo) or subreddit (Reddit) |

---

## `enriched_prices_table` — Prices + technical & fundamental indicators

Full price history for all tracked stocks enriched with technical indicators and fundamental data. Updated daily. Source for `sector_daily_opportunities`.

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
| `source` | STRING | Index source: `sp500`, `russell2000`, `stoxx600`, `commodities` |
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
