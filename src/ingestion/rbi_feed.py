"""RBI Foreign Exchange Reference Rates Ingestion Module.

Fetches, parses, and standardizes daily Reference Exchange Rates (USD, EUR, GBP, JPY against INR).
"""

from __future__ import annotations

import datetime
import hashlib
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

RBI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class RBIFXFeed:
    """Ingestion feed for daily RBI / FBIL Reference FX rates."""

    FEED_NAME = "rbi_fx"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(RBI_HEADERS)

    def fetch_live_feed(self, target_date: Optional[datetime.date] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Fetch RBI reference rates from FBIL / RBI public endpoint.

        Returns:
            Tuple of (DataFrame, metadata dictionary).
        """
        target_date = target_date or datetime.date.today()
        # Primary public FBIL reference rate URL
        url = "https://www.fbil.org.in/FBIL_CMS/rest/refRate/getRefRate"

        raw_bytes = b""
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 10:
                raw_bytes = resp.content
        except Exception as e:
            logger.debug(f"FBIL live rate error: {e}")

        if not raw_bytes:
            # Fallback RBI archive or structured query
            rbi_url = f"https://rbi.org.in/scripts/ReferenceRateArchive.aspx"
            try:
                resp = self.session.get(rbi_url, timeout=10)
                if resp.status_code == 200 and len(resp.content) > 10:
                    raw_bytes = resp.content
            except Exception as e:
                logger.debug(f"RBI archive rate error: {e}")

        if not raw_bytes:
            raise RuntimeError(f"Unable to fetch live RBI FX feed for date {target_date}")

        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        df = self._parse_raw_payload(raw_bytes, target_date)
        metadata = {
            "feed": self.FEED_NAME,
            "target_date": target_date.isoformat(),
            "raw_sha256": raw_hash,
            "raw_byte_length": len(raw_bytes),
            "raw_record_count": len(df),
        }
        return df, metadata

    def _parse_raw_payload(self, raw_bytes: bytes, target_date: datetime.date) -> pd.DataFrame:
        """Parse raw response from JSON or HTML tables."""
        records: List[Dict[str, Any]] = []
        try:
            data = pd.read_json(io.BytesIO(raw_bytes))
            if isinstance(data, pd.DataFrame) and not data.empty:
                for _, row in data.iterrows():
                    curr = str(row.get("currency", "")).upper()
                    rate = float(row.get("rate", 0.0))
                    if curr in ["USD", "EUR", "GBP", "JPY"] and rate > 0:
                        records.append(
                            {
                                "trade_date": target_date,
                                "currency": curr,
                                "rate": rate,
                                "base_currency": "INR",
                            }
                        )
        except Exception:
            # Try parsing HTML tables if HTML was returned
            try:
                tables = pd.read_html(io.BytesIO(raw_bytes))
                for t in tables:
                    for _, row in t.iterrows():
                        row_str = " ".join(row.astype(str))
                        for curr in ["USD", "EUR", "GBP", "JPY"]:
                            if curr in row_str:
                                for val in row.values:
                                    try:
                                        f_val = float(str(val).replace(",", ""))
                                        if 0.1 <= f_val <= 200.0:
                                            records.append(
                                                {
                                                    "trade_date": target_date,
                                                    "currency": curr,
                                                    "rate": f_val,
                                                    "base_currency": "INR",
                                                }
                                            )
                                            break
                                    except ValueError:
                                        pass
            except Exception as e:
                logger.debug(f"HTML table parse error: {e}")

        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(columns=["trade_date", "currency", "rate", "base_currency"])
        df = df.drop_duplicates(subset=["trade_date", "currency"])
        return df
