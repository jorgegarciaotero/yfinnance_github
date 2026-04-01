# src/gcs_export.py
"""
Helper to upload JSON cache files to GCS.
Called by pipeline jobs after writing to BigQuery.
"""

import json
import math
import logging
from datetime import date, datetime
from typing import Any

from google.cloud import storage

from src.config.settings import PROJECT_ID, GCS_BUCKET

logger = logging.getLogger("gcs_export")


class _Encoder(json.JSONEncoder):
    """Handles date, datetime, float nan/inf, and numpy/pandas scalar types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        # numpy int / float scalars
        try:
            import numpy as np
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                v = float(obj)
                return None if (math.isnan(v) or math.isinf(v)) else v
            if isinstance(obj, np.bool_):
                return bool(obj)
        except ImportError:
            pass
        return super().default(obj)

    def iterencode(self, o: Any, _one_shot: bool = False):
        # Replace nan/inf floats at encode time
        return super().iterencode(_sanitize(o), _one_shot)


def _sanitize(obj: Any) -> Any:
    """Recursively replace float nan/inf with None."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def upload_json(blob_name: str, payload: Any) -> None:
    """
    Serialize payload as JSON and upload to GCS_BUCKET/blob_name.

    Args:
        blob_name: Path inside the bucket, e.g. "cache/picks.json"
        payload:   JSON-serialisable object (dict, list, …)
    """
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)

    body = json.dumps(payload, cls=_Encoder, ensure_ascii=False)
    blob.upload_from_string(body, content_type="application/json")
    logger.info("uploaded gs://%s/%s (%d bytes)", GCS_BUCKET, blob_name, len(body))
