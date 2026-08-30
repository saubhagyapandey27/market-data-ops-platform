"""DuckDB SQL Analytics Engine Connection & View Registration.

Provides connection management and SQL interface over partitioned Parquet lakes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


class DuckDBEngine:
    """DuckDB SQL analytics connection and lake scanner."""

    def __init__(self, base_lake_dir: str = "data/lake", reference_dir: str = "data/reference"):
        self.base_lake_dir = Path(base_lake_dir)
        self.reference_dir = Path(reference_dir)
        self.conn = duckdb.connect(database=":memory:")
        self._register_views()

    def _register_views(self) -> None:
        """Register parquet directories and reference CSVs as DuckDB views."""
        # 1. Reference sectors
        sectors_csv = self.reference_dir / "sectors.csv"
        if sectors_csv.exists():
            self.conn.execute(
                f"CREATE OR REPLACE VIEW sectors_ref AS SELECT * FROM read_csv_auto('{sectors_csv.as_posix()}')"
            )

        # 2. Corporate actions
        ca_csv = self.reference_dir / "corporate_actions.csv"
        if ca_csv.exists():
            self.conn.execute(
                f"CREATE OR REPLACE VIEW corporate_actions_ref AS SELECT * FROM read_csv_auto('{ca_csv.as_posix()}')"
            )

        # 3. Parquet Lake views
        for feed in ["nse_bhavcopy", "india_vix", "amfi_nav", "rbi_fx"]:
            feed_dir = self.base_lake_dir / feed
            if feed_dir.exists() and list(feed_dir.glob("**/*.parquet")):
                glob_path = (feed_dir / "**/*.parquet").as_posix()
                try:
                    self.conn.execute(
                        f"CREATE OR REPLACE VIEW {feed} AS "
                        f"SELECT * FROM read_parquet('{glob_path}', hive_partitioning=true)"
                    )
                except Exception as e:
                    logger.debug(f"View creation error for {feed}: {e}")

    def reload_views(self) -> None:
        """Refresh views after new data ingestion."""
        self._register_views()

    def query(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """Execute SQL query and return result as pandas DataFrame."""
        if params:
            return self.conn.execute(sql, params).df()
        return self.conn.execute(sql).df()

    def register_dataframe(self, view_name: str, df: pd.DataFrame) -> None:
        """Register in-memory pandas DataFrame as a temporary SQL view."""
        self.conn.register(view_name, df)
