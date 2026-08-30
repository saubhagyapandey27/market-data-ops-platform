"""Quarantine Workflow Module.

Manages the persistence, metadata enrichment, and inspection of quarantined data rows.
"""

from __future__ import annotations

import datetime
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class QuarantineManager:
    """Handles segregation and partitioned storage of quarantined market data records."""

    def __init__(self, base_quarantine_path: str = "data/lake/quarantine"):
        self.base_quarantine_path = Path(base_quarantine_path)
        self.base_quarantine_path.mkdir(parents=True, exist_ok=True)

    def quarantine_records(
        self,
        feed_name: str,
        quarantine_df: pd.DataFrame,
        issues: List[Dict[str, Any]],
        trade_date: datetime.date,
    ) -> Optional[str]:
        """Enrich quarantined dataframe with audit metadata and write to partitioned Parquet lake."""
        if quarantine_df.empty and not issues:
            return None

        # Build enriched dataframe
        records = []
        if not quarantine_df.empty:
            for i, (_, row) in enumerate(quarantine_df.iterrows()):
                issue_meta = issues[i] if i < len(issues) else {}
                rec = row.to_dict()
                rec.update(
                    {
                        "quarantine_id": str(uuid.uuid4()),
                        "feed_name": feed_name,
                        "quarantine_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "quarantine_date": str(trade_date),
                        "failure_rule": issue_meta.get("failure_rule", "QUALITY_CHECK_FAILED"),
                        "root_cause_detail": issue_meta.get("root_cause_detail", "Record failed validation"),
                        "severity": issue_meta.get("severity", "WARNING"),
                    }
                )
                records.append(rec)
        elif issues:
            for issue in issues:
                records.append(
                    {
                        "quarantine_id": str(uuid.uuid4()),
                        "feed_name": feed_name,
                        "quarantine_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "quarantine_date": str(trade_date),
                        "symbol": issue.get("symbol", "N/A"),
                        "failure_rule": issue.get("failure_rule", "PIPELINE_ERROR"),
                        "root_cause_detail": issue.get("root_cause_detail", "Generic issue"),
                        "severity": issue.get("severity", "ERROR"),
                    }
                )

        if not records:
            return None

        df_enriched = pd.DataFrame(records)
        # Ensure year and month partitions
        year = trade_date.strftime("%Y")
        month = trade_date.strftime("%m")

        target_dir = self.base_quarantine_path / f"feed={feed_name}" / f"year={year}" / f"month={month}"
        target_dir.mkdir(parents=True, exist_ok=True)

        batch_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_file = target_dir / f"quarantine_{batch_id}.parquet"

        # Write to parquet
        df_enriched.to_parquet(target_file, index=False, engine="pyarrow")
        return str(target_file)

    def load_all_quarantine(self) -> pd.DataFrame:
        """Load all quarantine records from partitioned directory."""
        if not self.base_quarantine_path.exists():
            return pd.DataFrame()

        files = list(self.base_quarantine_path.glob("**/*.parquet"))
        if not files:
            return pd.DataFrame()

        dfs = [pd.read_parquet(f) for f in files]
        return pd.concat(dfs, ignore_index=True)
