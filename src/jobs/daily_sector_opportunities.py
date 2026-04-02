# src/jobs/daily_sector_opportunities.py
"""
Daily job:
- Runs sector_opportunities_incremental.bsql against enriched_prices_table
- Produces up to 10 stock opportunities per sector × 3 setup types:
    Dip (Tendencia Alcista) | Momentum (Líderes) | Value Reversal
- Each row includes a composite score (0-100) and a human-readable reason
- DELETE + INSERT on max_date (idempotent)
- Runs AFTER daily_enrich
"""

import os
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    DATASET,
    SECTOR_OPPORTUNITIES_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_sector_opportunities")

SECTOR_SQL = Path(__file__).parents[1] / "sql" / "sector_opportunities_incremental.bsql"

SCHEMA = [
    bigquery.SchemaField("date",               "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("sector",             "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("industry",           "STRING"),
    bigquery.SchemaField("symbol",             "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("setup_type",         "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("close",              "FLOAT64"),
    bigquery.SchemaField("market_cap_bn",      "FLOAT64"),
    bigquery.SchemaField("rsi_14",             "FLOAT64"),
    bigquery.SchemaField("momentum_10d_pct",   "FLOAT64"),
    bigquery.SchemaField("dist_sma200_pct",    "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_high",  "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_low",   "FLOAT64"),
    bigquery.SchemaField("pe_ratio",           "FLOAT64"),
    bigquery.SchemaField("recommendation_key", "STRING"),
    bigquery.SchemaField("score",              "FLOAT64"),
    bigquery.SchemaField("rank_in_sector",     "INT64"),
    bigquery.SchemaField("reason",             "STRING"),
]


def ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(SECTOR_OPPORTUNITIES_TABLE)
        logger.info("sector_daily_opportunities table exists")
    except Exception:
        table = bigquery.Table(SECTOR_OPPORTUNITIES_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="date")
        table.clustering_fields = ["sector", "setup_type"]
        client.create_table(table)
        logger.info("sector_daily_opportunities table created")


def run_sql(client: bigquery.Client) -> None:
    sql = SECTOR_SQL.read_text(encoding="utf-8")
    logger.info("running sector_opportunities query...")
    job = client.query(sql)
    job.result()
    logger.info("sector_opportunities job completed (job_id=%s)", job.job_id)


def main() -> None:
    logger.info("starting daily_sector_opportunities")

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
    run_sql(client)

    logger.info("daily_sector_opportunities finished")


if __name__ == "__main__":
    main()
