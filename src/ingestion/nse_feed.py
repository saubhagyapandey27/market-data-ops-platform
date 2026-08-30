"""NSE Equity Bhavcopy Ingestion Module.

Fetches, validates, and standardizes daily NSE equity bhavcopy market data feeds.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import logging
import zipfile
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


class NSEBhavcopyFeed:
    """Ingestion feed for daily NSE Equity Bhavcopy."""

    FEED_NAME = "nse_bhavcopy"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(NSE_HEADERS)

    def fetch_live_feed(self, trade_date: datetime.date) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Fetch raw Bhavcopy from NSE archives or active portal for a given trade date.

        Returns:
            Tuple of (DataFrame, metadata dictionary with raw hash & record counts).
        """
        # Format 1: Historical sec_bhavdata_full (DDMMYYYY)
        # Format 2: cm{DD}{MON}{YYYY}bhav.csv.zip
        date_str_dmy = trade_date.strftime("%d%m%Y")
        day_str = trade_date.strftime("%d")
        month_abbr = trade_date.strftime("%b").upper()
        year_str = trade_date.strftime("%Y")

        url_options = [
            f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str_dmy}.csv",
            f"https://archives.nseindia.com/content/historical/EQUITIES/{year_str}/{month_abbr}/cm{day_str}{month_abbr}{year_str}bhav.csv.zip",
        ]

        raw_bytes = b""
        last_error = None

        for url in url_options:
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200 and len(resp.content) > 100:
                    raw_bytes = resp.content
                    break
            except Exception as e:
                last_error = e
                logger.debug(f"Failed fetching {url}: {e}")

        if not raw_bytes:
            raise RuntimeError(f"Unable to fetch NSE Bhavcopy for date {trade_date}: {last_error or 'HTTP 404/Empty'}")

        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        df = self._parse_raw_payload(raw_bytes, trade_date)
        metadata = {
            "feed": self.FEED_NAME,
            "trade_date": trade_date.isoformat(),
            "raw_sha256": raw_hash,
            "raw_byte_length": len(raw_bytes),
            "raw_record_count": len(df),
        }
        return df, metadata

    def _parse_raw_payload(self, raw_bytes: bytes, trade_date: datetime.date) -> pd.DataFrame:
        """Parse zip or csv bytes into standardized DataFrame."""
        if raw_bytes[:2] == b"PK":  # Zip file
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
                filename = z.namelist()[0]
                with z.open(filename) as f:
                    df_raw = pd.read_csv(f)
        else:
            df_raw = pd.read_csv(io.BytesIO(raw_bytes))

        # Standardize column headers (strip spaces & uppercase)
        df_raw.columns = [str(c).strip().upper() for c in df_raw.columns]
        return self._standardize_schema(df_raw, trade_date)

    def _standardize_schema(self, df_raw: pd.DataFrame, trade_date: datetime.date) -> pd.DataFrame:
        """Standardize column names and datatypes."""
        col_map = {
            "SYMBOL": "symbol",
            "SERIES": "series",
            "OPEN_PRICE": "open",
            "OPEN": "open",
            "HIGH_PRICE": "high",
            "HIGH": "high",
            "LOW_PRICE": "low",
            "LOW": "low",
            "CLOSE_PRICE": "close",
            "CLOSE": "close",
            "PREV_CLOSE": "prev_close",
            "PREVCLOSE": "prev_close",
            "TTL_TRD_QNTY": "volume",
            "TOTTRDQTY": "volume",
            "TURNOVER_LACS": "turnover",
            "TOTTRDVAL": "turnover",
            "NO_OF_TRADES": "trades",
            "TOTALTRADES": "trades",
            "ISIN": "isin",
        }

        df = pd.DataFrame()
        for raw_col, std_col in col_map.items():
            if raw_col in df_raw.columns and std_col not in df.columns:
                df[std_col] = df_raw[raw_col]

        # Fill default series and trades if missing
        if "series" not in df.columns:
            df["series"] = "EQ"
        else:
            df["series"] = df["series"].astype(str).str.strip()

        if "trades" not in df.columns:
            df["trades"] = 0

        if "isin" not in df.columns:
            df["isin"] = "INE000000000"

        # Trade date
        df["trade_date"] = pd.to_datetime(trade_date).date()

        # Type casts
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        for col in ["open", "high", "low", "close", "prev_close", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ["volume", "trades"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")

        # Keep primary EQ / BE series
        df = df[df["series"].isin(["EQ", "BE", "SM"])].copy()
        target_cols = [
            "trade_date",
            "symbol",
            "series",
            "open",
            "high",
            "low",
            "close",
            "prev_close",
            "volume",
            "turnover",
            "trades",
            "isin",
        ]
        return df[[c for c in target_cols if c in df.columns]]
