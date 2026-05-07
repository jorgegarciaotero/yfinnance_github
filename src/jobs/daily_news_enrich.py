# src/jobs/daily_news_enrich.py
"""
Daily job: News & Social Media Enrichment
- Queries today's unique symbols from anomaly_radar + sector_daily_opportunities
- Fetches recent mentions from two free sources:
    1. Yahoo Finance news  — via yfinance (no API key)
    2. Reddit              — public JSON API, r/stocks + r/investing + r/wallstreetbets (no API key)
- Stores up to 5 items per symbol per source in company_news table
- DELETE + INSERT on max_date (idempotent)
- Runs AFTER daily_anomaly and daily_sector jobs
"""

import os
import time
import logging
from datetime import datetime, timezone

import requests
import yfinance as yf
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    ANOMALY_RADAR_TABLE,
    SECTOR_OPPORTUNITIES_TABLE,
    COMPANY_NEWS_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_news_enrich")

REDDIT_HEADERS = {"User-Agent": "yfinnance-news-bot/1.0 (educational project)"}
REDDIT_URL = "https://www.reddit.com/r/stocks+investing+wallstreetbets/search.json"
MAX_ITEMS_PER_SOURCE = 5
REDDIT_DELAY_SECS = 1.2   # stay well within Reddit's 60 req/min public limit

SCHEMA = [
    bigquery.SchemaField("date",         "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("symbol",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("source",       "STRING",    mode="REQUIRED"),  # yahoo_finance | reddit
    bigquery.SchemaField("title",        "STRING"),
    bigquery.SchemaField("url",          "STRING"),
    bigquery.SchemaField("published_at", "TIMESTAMP"),
    bigquery.SchemaField("summary",      "STRING"),
    bigquery.SchemaField("score",        "INT64"),        # Reddit upvotes; NULL for Yahoo
    bigquery.SchemaField("num_comments", "INT64"),        # Reddit comments; NULL for Yahoo
    bigquery.SchemaField("publisher",    "STRING"),       # Yahoo publisher; subreddit for Reddit
]


# ── BigQuery helpers ──────────────────────────────────────────────────────────

def ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(COMPANY_NEWS_TABLE)
        logger.info("company_news table exists")
    except Exception:
        table = bigquery.Table(COMPANY_NEWS_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="date")
        table.clustering_fields = ["symbol", "source"]
        client.create_table(table)
        logger.info("company_news table created")


def get_today_symbols(client: bigquery.Client) -> tuple[list[str], str]:
    """Return (symbols, max_date_str) for today's radar + opportunities output."""
    sql = f"""
    SELECT DISTINCT symbol, CAST(MAX(date) OVER () AS STRING) AS max_date
    FROM (
      SELECT symbol, date FROM `{ANOMALY_RADAR_TABLE}`
      WHERE date = (SELECT MAX(date) FROM `{ANOMALY_RADAR_TABLE}`)
      UNION DISTINCT
      SELECT symbol, date FROM `{SECTOR_OPPORTUNITIES_TABLE}`
      WHERE date = (SELECT MAX(date) FROM `{SECTOR_OPPORTUNITIES_TABLE}`)
    )
    """
    rows = list(client.query(sql).result())
    if not rows:
        return [], ""
    symbols = [r["symbol"] for r in rows]
    max_date = rows[0]["max_date"]
    return symbols, max_date


def delete_existing(client: bigquery.Client, max_date: str) -> None:
    sql = f"DELETE FROM `{COMPANY_NEWS_TABLE}` WHERE date = '{max_date}'"
    client.query(sql).result()
    logger.info("deleted existing rows for %s", max_date)


def insert_rows(client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(COMPANY_NEWS_TABLE, rows)
    if errors:
        logger.warning("BigQuery insert errors: %s", errors)
    else:
        logger.info("inserted %d rows", len(rows))


# ── Yahoo Finance news ────────────────────────────────────────────────────────

def fetch_yahoo_news(symbol: str, max_date: str) -> list[dict]:
    rows = []
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        for item in news[:MAX_ITEMS_PER_SOURCE]:
            published_at = None
            ts = item.get("providerPublishTime")
            if ts:
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            content = item.get("content") or {}
            title = (
                item.get("title")
                or content.get("title")
                or ""
            )
            url = (
                item.get("link")
                or item.get("url")
                or content.get("canonicalUrl", {}).get("url")
                or ""
            )
            publisher = (
                item.get("publisher")
                or content.get("provider", {}).get("displayName")
                or ""
            )
            summary = (
                item.get("summary")
                or content.get("summary")
                or ""
            )
            if summary:
                summary = summary[:600]

            if not title or not url:
                continue

            rows.append({
                "date":         max_date,
                "symbol":       symbol,
                "source":       "yahoo_finance",
                "title":        title,
                "url":          url,
                "published_at": published_at,
                "summary":      summary or None,
                "score":        None,
                "num_comments": None,
                "publisher":    publisher or None,
            })
    except Exception as exc:
        logger.warning("[yahoo] %s — %s", symbol, exc)
    return rows


# ── Reddit public API ─────────────────────────────────────────────────────────

def fetch_reddit_posts(symbol: str, max_date: str) -> list[dict]:
    rows = []
    try:
        resp = requests.get(
            REDDIT_URL,
            headers=REDDIT_HEADERS,
            params={
                "q":           symbol,
                "sort":        "top",
                "t":           "week",
                "limit":       MAX_ITEMS_PER_SOURCE,
                "restrict_sr": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
        for child in children:
            post = child.get("data", {})
            title = post.get("title", "")
            if not title:
                continue

            permalink = post.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink else post.get("url", "")
            selftext = post.get("selftext", "") or ""
            summary = selftext[:600] if selftext and selftext != "[removed]" else None
            published_at = None
            ts = post.get("created_utc")
            if ts:
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            rows.append({
                "date":         max_date,
                "symbol":       symbol,
                "source":       "reddit",
                "title":        title,
                "url":          url,
                "published_at": published_at,
                "summary":      summary,
                "score":        post.get("score"),
                "num_comments": post.get("num_comments"),
                "publisher":    post.get("subreddit_name_prefixed") or post.get("subreddit"),
            })
    except Exception as exc:
        logger.warning("[reddit] %s — %s", symbol, exc)
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("starting daily_news_enrich")

    json_path = os.path.join("src", "config", "service-account.json")
    if os.path.exists(json_path):
        try:
            import json as _json
            with open(json_path) as f:
                creds = _json.load(f)
            if creds.get("private_key") and creds.get("client_email"):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        except Exception:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    client = bigquery.Client(project=PROJECT_ID)
    ensure_table(client)

    symbols, max_date = get_today_symbols(client)
    if not symbols:
        logger.info("no symbols found for today — skipping")
        return

    logger.info("found %d symbols for %s", len(symbols), max_date)
    delete_existing(client, max_date)

    all_rows: list[dict] = []

    for i, symbol in enumerate(symbols):
        logger.info("[%d/%d] fetching news for %s", i + 1, len(symbols), symbol)

        all_rows.extend(fetch_yahoo_news(symbol, max_date))

        all_rows.extend(fetch_reddit_posts(symbol, max_date))
        time.sleep(REDDIT_DELAY_SECS)

        # flush every 20 symbols to avoid huge in-memory batches
        if len(all_rows) >= 200:
            insert_rows(client, all_rows)
            all_rows = []

    insert_rows(client, all_rows)
    logger.info("daily_news_enrich finished")


if __name__ == "__main__":
    main()
