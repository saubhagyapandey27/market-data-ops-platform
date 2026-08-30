"""ETL Pipeline Orchestration Module.

Orchestrates automated ingestion of NSE Bhavcopy, India VIX, AMFI NAVs, and RBI FX,
enforcing hash-count checks, corporate action reconciliation, stale quote quarantine,
and partitioned Parquet lake writes.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.ingestion.amfi_feed import AMFINAVFeed
from src.ingestion.nse_feed import NSEBhavcopyFeed
from src.ingestion.rbi_feed import RBIFXFeed
from src.ingestion.vix_feed import IndiaVIXFeed
from src.quality.governance import GovernanceAuditor
from src.quality.quarantine import QuarantineManager
from src.quality.reconciliation import DataQualityReconciler, QualityAuditResult

logger = logging.getLogger(__name__)


class ETLPipeline:
    """Orchestrator for ingesting market data into partitioned Parquet lake with quality controls."""

    def __init__(
        self,
        base_lake_dir: str = "data/lake",
        corporate_actions_path: str = "data/reference/corporate_actions.csv",
        governance_note_path: str = "docs/data_governance_note.md",
    ):
        self.base_lake_dir = Path(base_lake_dir)
        self.base_lake_dir.mkdir(parents=True, exist_ok=True)

        ca_df = None
        ca_p = Path(corporate_actions_path)
        if ca_p.exists():
            ca_df = pd.read_csv(ca_p)

        self.reconciler = DataQualityReconciler(corporate_actions_df=ca_df)
        self.quarantine_mgr = QuarantineManager(base_quarantine_path=str(self.base_lake_dir / "quarantine"))
        self.governance_auditor = GovernanceAuditor(output_path=governance_note_path)

        # Feed handlers
        self.nse_feed = NSEBhavcopyFeed()
        self.vix_feed = IndiaVIXFeed()
        self.amfi_feed = AMFINAVFeed()
        self.rbi_feed = RBIFXFeed()

    def write_partitioned_parquet(self, df: pd.DataFrame, feed_name: str, trade_date: datetime.date) -> Path:
        """Write DataFrame into partitioned Parquet directory structure (year=YYYY/month=MM)."""
        year_str = trade_date.strftime("%Y")
        month_str = trade_date.strftime("%m")
        date_str = trade_date.strftime("%Y%m%d")

        partition_dir = self.base_lake_dir / feed_name / f"year={year_str}" / f"month={month_str}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        target_file = partition_dir / f"{feed_name}_{date_str}.parquet"
        df.to_parquet(target_file, index=False, engine="pyarrow")
        return target_file

    def process_feed_dataframe(
        self,
        raw_df: pd.DataFrame,
        feed_name: str,
        trade_date: datetime.date,
        raw_hash: str = "",
        raw_count: Optional[int] = None,
        recent_history_df: Optional[pd.DataFrame] = None,
    ) -> QualityAuditResult:
        """Execute full reconciliation pipeline on a feed dataframe and persist to lake."""
        if raw_count is None:
            raw_count = len(raw_df)

        count_matched, hash_valid, processed_hash = self.reconciler.reconcile_hash_and_counts(
            raw_count=raw_count, parsed_df=raw_df, raw_hash=raw_hash, feed_name=feed_name
        )

        # 1. Domain constraint validation
        clean_df, quarantine_df_1, issues_1 = self.reconciler.validate_domain_constraints(raw_df, feed_name)

        all_quarantine = [quarantine_df_1]
        all_issues = list(issues_1)
        stale_count = 0
        corp_anomalies_count = 0

        # 2. Corporate actions & Stale quote reconciliation (specific to equity bhavcopy)
        if feed_name == "nse_bhavcopy" and not clean_df.empty:
            clean_df, quarantine_df_2, issues_2 = self.reconciler.reconcile_corporate_actions(clean_df)
            all_quarantine.append(quarantine_df_2)
            all_issues.extend(issues_2)
            corp_anomalies_count = len(issues_2)

            if recent_history_df is not None and not recent_history_df.empty:
                clean_df, quarantine_df_3, issues_3 = self.reconciler.reconcile_stale_quotes(
                    recent_history_df=recent_history_df, current_df=clean_df
                )
                all_quarantine.append(quarantine_df_3)
                all_issues.extend(issues_3)
                stale_count = len(issues_3)

        combined_quarantine = (
            pd.concat([q for q in all_quarantine if not q.empty], ignore_index=True)
            if any(not q.empty for q in all_quarantine)
            else pd.DataFrame()
        )

        # Write quarantined rows if any
        if not combined_quarantine.empty:
            self.quarantine_mgr.quarantine_records(
                feed_name=feed_name,
                quarantine_df=combined_quarantine,
                issues=all_issues,
                trade_date=trade_date,
            )

        # Write clean rows to partitioned lake
        if not clean_df.empty:
            self.write_partitioned_parquet(clean_df, feed_name, trade_date)

        audit_result = QualityAuditResult(
            feed_name=feed_name,
            trade_date=str(trade_date),
            total_records=len(raw_df),
            clean_records=len(clean_df),
            quarantined_records=len(combined_quarantine),
            raw_hash=raw_hash,
            processed_hash=processed_hash,
            hash_matched=hash_valid,
            count_matched=count_matched,
            stale_quotes_count=stale_count,
            corp_action_anomalies_count=corp_anomalies_count,
            constraint_violations_count=len(issues_1),
            issues=all_issues,
        )
        return audit_result

    def run_daily_etl(
        self,
        trade_date: Optional[datetime.date] = None,
        custom_data_map: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict[str, QualityAuditResult]:
        """Run daily ingestion pipeline across all 4 feeds."""
        trade_date = trade_date or datetime.date.today()
        results: Dict[str, QualityAuditResult] = {}

        # 1. NSE Bhavcopy
        try:
            if custom_data_map and "nse_bhavcopy" in custom_data_map:
                df_nse = custom_data_map["nse_bhavcopy"]
                raw_hash = self.reconciler.compute_record_hash(df_nse)
                meta = {"raw_sha256": raw_hash, "raw_record_count": len(df_nse)}
            else:
                df_nse, meta = self.nse_feed.fetch_live_feed(trade_date)
            results["nse_bhavcopy"] = self.process_feed_dataframe(
                raw_df=df_nse,
                feed_name="nse_bhavcopy",
                trade_date=trade_date,
                raw_hash=meta.get("raw_sha256", ""),
                raw_count=meta.get("raw_record_count", len(df_nse)),
            )
        except Exception as e:
            logger.error(f"NSE Bhavcopy ETL error: {e}")

        # 2. India VIX
        try:
            if custom_data_map and "india_vix" in custom_data_map:
                df_vix = custom_data_map["india_vix"]
                raw_hash = self.reconciler.compute_record_hash(df_vix)
                meta = {"raw_sha256": raw_hash, "raw_record_count": len(df_vix)}
            else:
                df_vix, meta = self.vix_feed.fetch_live_feed(trade_date)
            results["india_vix"] = self.process_feed_dataframe(
                raw_df=df_vix,
                feed_name="india_vix",
                trade_date=trade_date,
                raw_hash=meta.get("raw_sha256", ""),
                raw_count=meta.get("raw_record_count", len(df_vix)),
            )
        except Exception as e:
            logger.error(f"India VIX ETL error: {e}")

        # 3. AMFI NAVs
        try:
            if custom_data_map and "amfi_nav" in custom_data_map:
                df_amfi = custom_data_map["amfi_nav"]
                raw_hash = self.reconciler.compute_record_hash(df_amfi)
                meta = {"raw_sha256": raw_hash, "raw_record_count": len(df_amfi)}
            else:
                df_amfi, meta = self.amfi_feed.fetch_live_feed(trade_date)
            results["amfi_nav"] = self.process_feed_dataframe(
                raw_df=df_amfi,
                feed_name="amfi_nav",
                trade_date=trade_date,
                raw_hash=meta.get("raw_sha256", ""),
                raw_count=meta.get("raw_record_count", len(df_amfi)),
            )
        except Exception as e:
            logger.error(f"AMFI NAV ETL error: {e}")

        # 4. RBI FX
        try:
            if custom_data_map and "rbi_fx" in custom_data_map:
                df_rbi = custom_data_map["rbi_fx"]
                raw_hash = self.reconciler.compute_record_hash(df_rbi)
                meta = {"raw_sha256": raw_hash, "raw_record_count": len(df_rbi)}
            else:
                df_rbi, meta = self.rbi_feed.fetch_live_feed(trade_date)
            results["rbi_fx"] = self.process_feed_dataframe(
                raw_df=df_rbi,
                feed_name="rbi_fx",
                trade_date=trade_date,
                raw_hash=meta.get("raw_sha256", ""),
                raw_count=meta.get("raw_record_count", len(df_rbi)),
            )
        except Exception as e:
            logger.error(f"RBI FX ETL error: {e}")

        # Update governance note
        quarantine_all = self.quarantine_mgr.load_all_quarantine()
        self.governance_auditor.generate_governance_note(quarantine_df=quarantine_all)
        return results
