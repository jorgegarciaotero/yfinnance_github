# src/jobs/daily_scanner.py
"""
Daily job:
- Ejecuta el war_dip_scanner sobre enriched_prices_table
- Hace MERGE de los resultados en war_dip_results por (run_date, symbol)
- Permite monitorizar la evolución diaria del score de cada valor
"""

import os
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    DATASET,
    WAR_DIP_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_scanner")

SCANNER_SQL = Path(__file__).parents[1] / "sql" / "war_dip_scanner.bsql"

SCHEMA = [
    bigquery.SchemaField("run_date",             "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("symbol",               "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("sector",               "STRING"),
    bigquery.SchemaField("industry",             "STRING"),
    bigquery.SchemaField("last_date",            "DATE"),
    bigquery.SchemaField("close",                "FLOAT64"),
    bigquery.SchemaField("market_cap_bn",        "FLOAT64"),
    # Caídas recientes
    bigquery.SchemaField("chg_1d_pct",           "FLOAT64"),
    bigquery.SchemaField("chg_3d_pct",           "FLOAT64"),
    bigquery.SchemaField("chg_5d_pct",           "FLOAT64"),
    bigquery.SchemaField("chg_7d_pct",           "FLOAT64"),
    # Rendimiento previo
    bigquery.SchemaField("perf_6m_to_3m_pct",   "FLOAT64"),
    bigquery.SchemaField("perf_3m_to_peak_pct", "FLOAT64"),
    bigquery.SchemaField("perf_6m_total_pct",   "FLOAT64"),
    bigquery.SchemaField("perf_1y_total_pct",   "FLOAT64"),
    # Técnicos
    bigquery.SchemaField("rsi_14",               "FLOAT64"),
    bigquery.SchemaField("dist_sma200_pct",      "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_high",    "FLOAT64"),
    bigquery.SchemaField("momentum_10d_pct",     "FLOAT64"),
    bigquery.SchemaField("macd_line",            "FLOAT64"),
    bigquery.SchemaField("bollinger_pct",        "FLOAT64"),
    bigquery.SchemaField("trend_now",            "STRING"),
    bigquery.SchemaField("trend_3m",             "STRING"),
    bigquery.SchemaField("trend_6m",             "STRING"),
    bigquery.SchemaField("trend_1y",             "STRING"),
    bigquery.SchemaField("recommendation_key",   "STRING"),
    # Score desglosado
    bigquery.SchemaField("score_a1_trend_1y",    "FLOAT64"),
    bigquery.SchemaField("score_a2_trend_6m",    "FLOAT64"),
    bigquery.SchemaField("score_b1_dip_size",    "FLOAT64"),
    bigquery.SchemaField("score_b2_dip_gradual", "FLOAT64"),
    bigquery.SchemaField("score_c1_rsi",         "FLOAT64"),
    bigquery.SchemaField("score_c2_bollinger",   "FLOAT64"),
    bigquery.SchemaField("score_d_sma200",       "FLOAT64"),
    bigquery.SchemaField("score_e_analyst",      "FLOAT64"),
    bigquery.SchemaField("score_total",          "FLOAT64"),
]


def ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(WAR_DIP_TABLE)
        logger.info("war_dip_results table exists")
    except Exception:
        table = bigquery.Table(WAR_DIP_TABLE, schema=SCHEMA)
        client.create_table(table)
        logger.info("war_dip_results table created")


def run_scanner(client: bigquery.Client) -> list[dict]:
    sql = SCANNER_SQL.read_text(encoding="utf-8")
    logger.info("running war_dip_scanner query...")
    rows = [dict(r) for r in client.query(sql).result()]
    logger.info("scanner returned %d rows", len(rows))
    return rows


def merge_results(client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        logger.warning("no rows to merge, skipping")
        return

    stage = f"{PROJECT_ID}.{DATASET}._war_dip_stage"

    import pandas as pd
    df = pd.DataFrame(rows)

    client.load_table_from_dataframe(
        df,
        stage,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()

    # Columnas a actualizar/insertar (todo excepto las claves)
    update_cols = [f.name for f in SCHEMA if f.name not in ("run_date", "symbol")]
    set_clause    = ",\n        ".join(f"{c} = s.{c}" for c in update_cols)
    insert_cols   = ", ".join(f.name for f in SCHEMA)
    insert_vals   = ", ".join(f"s.{f.name}" for f in SCHEMA)

    merge_sql = f"""
    MERGE `{WAR_DIP_TABLE}` t
    USING `{stage}` s
      ON t.run_date = s.run_date AND t.symbol = s.symbol
    WHEN MATCHED THEN UPDATE SET
        {set_clause}
    WHEN NOT MATCHED THEN INSERT ({insert_cols})
    VALUES ({insert_vals})
    """

    client.query(merge_sql).result()
    logger.info("merge completed: %d rows upserted", len(rows))


def main() -> None:
    logger.info("starting daily_scanner")

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
    rows = run_scanner(client)
    merge_results(client, rows)
    logger.info("daily_scanner finished")


if __name__ == "__main__":
    main()
