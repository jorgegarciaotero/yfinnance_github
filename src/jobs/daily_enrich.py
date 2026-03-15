# src/jobs/daily_enrich.py
"""
Daily job:
- Regenera enriched_prices_table ejecutando enrich_prices.bsql
- Debe correr DESPUÉS de daily_prices.py
"""

import os
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import PROJECT_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_enrich")

ENRICH_SQL = Path(__file__).parents[1] / "sql" / "enrich_prices.bsql"


def main() -> None:
    logger.info("starting daily_enrich")

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
    sql = ENRICH_SQL.read_text(encoding="utf-8")

    logger.info("running enrich_prices.bsql...")
    client.query(sql).result()
    logger.info("daily_enrich finished")


if __name__ == "__main__":
    main()
