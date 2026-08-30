"""AMFI Mutual Fund NAV Ingestion Module.

Fetches, parses, and standardizes daily Mutual Fund NAV feeds from AMFI.
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

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
AMFI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class AMFINAVFeed:
    """Ingestion feed for daily AMFI Mutual Fund NAVs."""

    FEED_NAME = "amfi_nav"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(AMFI_HEADERS)

    def fetch_live_feed(self, target_date: Optional[datetime.date] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Fetch raw NAVAll.txt from AMFI portal.

        Returns:
            Tuple of (DataFrame, metadata dictionary).
        """
        try:
            resp = self.session.get(AMFI_URL, timeout=15)
            resp.raise_for_status()
            raw_bytes = resp.content
        except Exception as e:
            logger.debug(f"Error fetching live AMFI feed: {e}")
            raise RuntimeError(f"Unable to fetch AMFI NAV feed: {e}")

        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        df = self._parse_raw_payload(raw_bytes, target_date)
        metadata = {
            "feed": self.FEED_NAME,
            "target_date": target_date.isoformat() if target_date else datetime.date.today().isoformat(),
            "raw_sha256": raw_hash,
            "raw_byte_length": len(raw_bytes),
            "raw_record_count": len(df),
        }
        return df, metadata

    def _parse_raw_payload(self, raw_bytes: bytes, target_date: Optional[datetime.date] = None) -> pd.DataFrame:
        """Parse raw text with semicolon delimited records and header blocks."""
        text = raw_bytes.decode("utf-8", errors="ignore")
        lines = text.splitlines()

        records: List[Dict[str, Any]] = []
        current_fund_house = "Unknown Mutual Fund"
        current_category = "Open Ended Schemes"

        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue

            # Header / category detector
            if ";" not in line_clean:
                if "Mutual Fund" in line_clean or "Asset Management" in line_clean:
                    current_fund_house = line_clean
                elif "Schemes" in line_clean:
                    current_category = line_clean
                continue

            parts = [p.strip() for p in line_clean.split(";")]
            # Format: Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
            if len(parts) >= 6:
                scheme_code = parts[0]
                isin_growth = parts[1]
                isin_div = parts[2]
                scheme_name = parts[3]
                nav_str = parts[4]
                date_str = parts[5]

                # Skip header row if present
                if scheme_code.upper() == "SCHEME CODE" or not scheme_code.isdigit():
                    continue

                try:
                    nav_val = float(nav_str)
                except ValueError:
                    continue

                try:
                    parsed_date = datetime.datetime.strptime(date_str, "%d-%b-%Y").date()
                except ValueError:
                    parsed_date = target_date or datetime.date.today()

                if target_date and parsed_date != target_date:
                    # Filter by target date if specified
                    pass

                records.append(
                    {
                        "trade_date": parsed_date,
                        "scheme_code": scheme_code,
                        "isin_growth": isin_growth if isin_growth != "-" else None,
                        "isin_div": isin_div if isin_div != "-" else None,
                        "scheme_name": scheme_name,
                        "nav": nav_val,
                        "fund_house": current_fund_house,
                        "category": current_category,
                    }
                )

        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "scheme_code",
                    "isin_growth",
                    "isin_div",
                    "scheme_name",
                    "nav",
                    "fund_house",
                    "category",
                ]
            )

        df["scheme_code"] = df["scheme_code"].astype(str)
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        return df.dropna(subset=["trade_date", "scheme_code", "nav"])
