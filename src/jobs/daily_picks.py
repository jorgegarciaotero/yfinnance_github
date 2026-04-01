# src/jobs/daily_picks.py
"""
Daily job:
- Runs daily_picks.bsql against enriched_prices_table
- Produces top 20 stock opportunities (ALCISTA + DIP) with unified score 0-100
- MERGEs results into daily_picks by (date, symbol)
- Runs AFTER daily_enrich
"""

import os
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    DATASET,
    DAILY_PICKS_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_picks")

PICKS_SQL = Path(__file__).parents[1] / "sql" / "daily_picks.bsql"

SCHEMA = [
    bigquery.SchemaField("date",               "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("rank",               "INT64",   mode="REQUIRED"),
    bigquery.SchemaField("tipo",               "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("symbol",             "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("sector",             "STRING"),
    bigquery.SchemaField("industry",           "STRING"),
    bigquery.SchemaField("data_date",          "DATE"),
    bigquery.SchemaField("close",              "FLOAT64"),
    bigquery.SchemaField("market_cap_bn",      "FLOAT64"),
    bigquery.SchemaField("rsi_14",             "FLOAT64"),
    bigquery.SchemaField("momentum_10d_pct",   "FLOAT64"),
    bigquery.SchemaField("dist_sma200_pct",    "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_high",  "FLOAT64"),
    bigquery.SchemaField("chg_1d_pct",         "FLOAT64"),
    bigquery.SchemaField("chg_3d_pct",         "FLOAT64"),
    bigquery.SchemaField("chg_5d_pct",         "FLOAT64"),
    bigquery.SchemaField("perf_6m_pct",        "FLOAT64"),
    bigquery.SchemaField("perf_1y_pct",        "FLOAT64"),
    bigquery.SchemaField("recommendation_key", "STRING"),
    bigquery.SchemaField("score_a",            "FLOAT64"),
    bigquery.SchemaField("score_b",            "FLOAT64"),
    bigquery.SchemaField("score_c",            "FLOAT64"),
    bigquery.SchemaField("score_d",            "FLOAT64"),
    bigquery.SchemaField("score_total",        "FLOAT64"),
    bigquery.SchemaField("reason",             "STRING"),
]


def ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(DAILY_PICKS_TABLE)
        logger.info("daily_picks table exists")
    except Exception:
        table = bigquery.Table(DAILY_PICKS_TABLE, schema=SCHEMA)
        client.create_table(table)
        logger.info("daily_picks table created")


def run_picks(client: bigquery.Client) -> list[dict]:
    sql = PICKS_SQL.read_text(encoding="utf-8")
    logger.info("running daily_picks query...")
    rows = [dict(r) for r in client.query(sql).result()]
    logger.info("picks returned %d rows", len(rows))
    return rows


def merge_results(client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        logger.warning("no rows to merge, skipping")
        return

    import pandas as pd

    stage = f"{PROJECT_ID}.{DATASET}._daily_picks_stage"
    df = pd.DataFrame(rows)

    client.load_table_from_dataframe(
        df,
        stage,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()

    update_cols = [f.name for f in SCHEMA if f.name not in ("date", "symbol")]
    set_clause  = ",\n        ".join(f"{c} = s.{c}" for c in update_cols)
    insert_cols = ", ".join(f.name for f in SCHEMA)
    insert_vals = ", ".join(f"s.{f.name}" for f in SCHEMA)

    merge_sql = f"""
    MERGE `{DAILY_PICKS_TABLE}` t
    USING `{stage}` s
      ON t.date = s.date AND t.symbol = s.symbol
    WHEN MATCHED THEN UPDATE SET
        {set_clause}
    WHEN NOT MATCHED THEN INSERT ({insert_cols})
    VALUES ({insert_vals})
    """

    client.query(merge_sql).result()
    logger.info("merge completed: %d rows upserted", len(rows))



def main() -> None:
    logger.info("starting daily_picks")

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
    rows = run_picks(client)
    merge_results(client, rows)

    logger.info("daily_picks finished")


if __name__ == "__main__":
    main()
