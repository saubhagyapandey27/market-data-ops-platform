"""India VIX Ingestion Module.

Fetches, validates, and standardizes India VIX market data feeds.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

VIX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}


class IndiaVIXFeed:
    """Ingestion feed for India VIX index data."""

    FEED_NAME = "india_vix"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(VIX_HEADERS)

    def fetch_live_feed(
        self, start_date: datetime.date, end_date: Optional[datetime.date] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Fetch historical/daily India VIX from NSE endpoint.

        Returns:
            Tuple of (DataFrame, metadata dictionary).
        """
        end_date = end_date or start_date
        url = (
            f"https://www.nseindia.com/api/historical/vixhistory?"
            f"from={start_date.strftime('%d-%m-%Y')}&to={end_date.strftime('%d-%m-%Y')}"
        )

        raw_bytes = b""
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 20:
                raw_bytes = resp.content
        except Exception as e:
            logger.debug(f"Live VIX endpoint error: {e}")

        if not raw_bytes:
            # Fallback direct csv link
            archive_url = "https://nsearchives.nseindia.com/content/indices/hist_vix_data.csv"
            try:
                resp = self.session.get(archive_url, timeout=10)
                if resp.status_code == 200:
                    raw_bytes = resp.content
            except Exception as e:
                logger.debug(f"Archive VIX endpoint error: {e}")

        if not raw_bytes:
            raise RuntimeError(f"Unable to fetch India VIX data for range {start_date} to {end_date}")

        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        df = self._parse_raw_payload(raw_bytes)
        metadata = {
            "feed": self.FEED_NAME,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "raw_sha256": raw_hash,
            "raw_byte_length": len(raw_bytes),
            "raw_record_count": len(df),
        }
        return df, metadata

    def _parse_raw_payload(self, raw_bytes: bytes) -> pd.DataFrame:
        """Parse raw bytes (CSV or JSON) to standardized DataFrame."""
        try:
            df_raw = pd.read_json(io.BytesIO(raw_bytes))
            if "data" in df_raw.columns:
                df_raw = pd.json_normalize(df_raw["data"])
        except Exception:
            df_raw = pd.read_csv(io.BytesIO(raw_bytes))

        df_raw.columns = [str(c).strip().upper() for c in df_raw.columns]
        return self._standardize_schema(df_raw)

    def _standardize_schema(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """Standardize column names and datatypes."""
        col_map = {
            "DATE": "trade_date",
            "TIMESTAMP": "trade_date",
            "EOD_TIMESTAMP": "trade_date",
            "OPEN": "open",
            "EOD_OPEN_INDEX_VAL": "open",
            "HIGH": "high",
            "EOD_HIGH_INDEX_VAL": "high",
            "LOW": "low",
            "EOD_LOW_INDEX_VAL": "low",
            "CLOSE": "close",
            "EOD_CLOSE_INDEX_VAL": "close",
            "PREV_CLOSE": "prev_close",
            "EOD_PREV_CLOSE": "prev_close",
            "CHANGE": "change",
            "PCT_CHANGE": "pct_change",
            "VIX_PTS_CHG": "change",
            "VIX_PCT_CHG": "pct_change",
        }

        df = pd.DataFrame()
        for raw_col, std_col in col_map.items():
            if raw_col in df_raw.columns and std_col not in df.columns:
                df[std_col] = df_raw[raw_col]

        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed").dt.date

        for col in ["open", "high", "low", "close", "prev_close", "change", "pct_change"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "change" not in df.columns and "close" in df.columns and "prev_close" in df.columns:
            df["change"] = df["close"] - df["prev_close"]

        if "pct_change" not in df.columns and "change" in df.columns and "prev_close" in df.columns:
            df["pct_change"] = (df["change"] / df["prev_close"]) * 100.0

        target_cols = ["trade_date", "open", "high", "low", "close", "prev_close", "change", "pct_change"]
        return df[[c for c in target_cols if c in df.columns]].dropna(subset=["trade_date", "close"])
