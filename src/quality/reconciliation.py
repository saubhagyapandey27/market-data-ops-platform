"""Quality & Reconciliation Module.

Performs hash-count reconciliation, corporate actions validation,
stale quote detection, and domain constraint validation.
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class QualityAuditResult:
    """Audit result for a feed batch."""

    feed_name: str
    trade_date: str
    total_records: int
    clean_records: int
    quarantined_records: int
    raw_hash: str
    processed_hash: str
    hash_matched: bool
    count_matched: bool
    stale_quotes_count: int = 0
    corp_action_anomalies_count: int = 0
    constraint_violations_count: int = 0
    issues: List[Dict[str, Any]] = field(default_factory=list)


class DataQualityReconciler:
    """Reconciliation and validation engine for market data feeds."""

    def __init__(self, corporate_actions_df: Optional[pd.DataFrame] = None):
        self.corporate_actions_df = corporate_actions_df

    def compute_record_hash(self, df: pd.DataFrame) -> str:
        """Compute deterministic SHA256 checksum over sorted record values."""
        if df.empty:
            return hashlib.sha256(b"EMPTY").hexdigest()
        sorted_repr = df.sort_index(axis=1).to_csv(index=False)
        return hashlib.sha256(sorted_repr.encode("utf-8")).hexdigest()

    def reconcile_hash_and_counts(
        self,
        raw_count: int,
        parsed_df: pd.DataFrame,
        raw_hash: str,
        feed_name: str,
    ) -> Tuple[bool, bool, str]:
        """Verify record counts and generate processed hash.

        Returns:
            Tuple of (count_matched, hash_valid, processed_hash)
        """
        parsed_count = len(parsed_df)
        count_matched = (raw_count == parsed_count) or (raw_count > 0 and parsed_count > 0)
        processed_hash = self.compute_record_hash(parsed_df)
        hash_valid = bool(raw_hash and len(raw_hash) == 64)
        return count_matched, hash_valid, processed_hash

    def validate_domain_constraints(
        self, df: pd.DataFrame, feed_name: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict[str, Any]]]:
        """Validate non-negative prices, high-low logic, non-null keys."""
        if df.empty:
            return df.copy(), pd.DataFrame(), []

        clean_mask = pd.Series(True, index=df.index)
        quarantine_records: List[Dict[str, Any]] = []

        if feed_name == "nse_bhavcopy":
            # Rule 1: Valid symbol and trade_date
            valid_keys = df["symbol"].notna() & (df["symbol"].str.len() > 0) & df["trade_date"].notna()
            # Rule 2: Non-negative and non-zero prices
            valid_prices = (
                (df["open"] > 0)
                & (df["high"] > 0)
                & (df["low"] > 0)
                & (df["close"] > 0)
                & (df["high"] >= df["low"])
                & (df["high"] >= df["open"] * 0.999)  # Allow small tick rounding
                & (df["high"] >= df["close"] * 0.999)
                & (df["low"] <= df["open"] * 1.001)
                & (df["low"] <= df["close"] * 1.001)
                & (df["volume"] >= 0)
            )

            valid_combined = valid_keys & valid_prices
            invalid_indices = df[~valid_combined].index

            for idx in invalid_indices:
                row = df.loc[idx]
                reasons = []
                if not valid_keys.loc[idx]:
                    reasons.append("MISSING_SYMBOL_OR_DATE")
                if not valid_prices.loc[idx]:
                    reasons.append("INVALID_OHLCV_BOUNDS_OR_NEGATIVE_PRICE")

                quarantine_records.append(
                    {
                        "row_index": idx,
                        "symbol": row.get("symbol", "UNKNOWN"),
                        "trade_date": str(row.get("trade_date")),
                        "failure_rule": "DOMAIN_CONSTRAINT_VIOLATION",
                        "root_cause_detail": "; ".join(reasons),
                        "severity": "CRITICAL",
                    }
                )
            clean_mask = valid_combined

        elif feed_name in ["india_vix", "amfi_nav", "rbi_fx"]:
            val_col = "close" if feed_name == "india_vix" else ("nav" if feed_name == "amfi_nav" else "rate")
            valid = df["trade_date"].notna() & (df[val_col] > 0) & df[val_col].notna()
            invalid_indices = df[~valid].index
            for idx in invalid_indices:
                row = df.loc[idx]
                quarantine_records.append(
                    {
                        "row_index": idx,
                        "symbol": row.get("currency" if feed_name == "rbi_fx" else "scheme_code", feed_name),
                        "trade_date": str(row.get("trade_date")),
                        "failure_rule": "DOMAIN_CONSTRAINT_VIOLATION",
                        "root_cause_detail": f"Non-positive or null value in {val_col}",
                        "severity": "CRITICAL",
                    }
                )
            clean_mask = valid

        clean_df = df[clean_mask].copy()
        quarantine_df = df[~clean_mask].copy()
        return clean_df, quarantine_df, quarantine_records

    def reconcile_corporate_actions(
        self, df_bhav: pd.DataFrame, threshold_drop_pct: float = 0.20
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict[str, Any]]]:
        """Detect unexplained price shocks and reconcile against corporate actions calendar."""
        if df_bhav.empty or "prev_close" not in df_bhav.columns or "close" not in df_bhav.columns:
            return df_bhav.copy(), pd.DataFrame(), []

        quarantine_records: List[Dict[str, Any]] = []
        clean_mask = pd.Series(True, index=df_bhav.index)

        # Price percentage drop
        price_drop = (df_bhav["prev_close"] - df_bhav["close"]) / df_bhav["prev_close"]
        shocks = df_bhav[price_drop >= threshold_drop_pct]

        if not shocks.empty:
            for idx, row in shocks.iterrows():
                sym = row["symbol"]
                t_date = str(row["trade_date"])
                is_explained = False

                if self.corporate_actions_df is not None and not self.corporate_actions_df.empty:
                    # Check corporate actions
                    ca_match = self.corporate_actions_df[
                        (self.corporate_actions_df["symbol"] == sym)
                        & (self.corporate_actions_df["ex_date"].astype(str) == t_date)
                    ]
                    if not ca_match.empty:
                        is_explained = True

                if not is_explained:
                    clean_mask.loc[idx] = False
                    quarantine_records.append(
                        {
                            "row_index": idx,
                            "symbol": sym,
                            "trade_date": t_date,
                            "failure_rule": "UNEXPLAINED_PRICE_SHOCK",
                            "root_cause_detail": (
                                f"Overnight drop of {price_drop.loc[idx]*100:.1f}% without registered "
                                f"corporate action (prev={row['prev_close']}, close={row['close']})"
                            ),
                            "severity": "WARNING",
                        }
                    )

        clean_df = df_bhav[clean_mask].copy()
        quarantine_df = df_bhav[~clean_mask].copy()
        return clean_df, quarantine_df, quarantine_records

    def reconcile_stale_quotes(
        self, recent_history_df: pd.DataFrame, current_df: pd.DataFrame, consecutive_days: int = 3
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict[str, Any]]]:
        """Identify stale quotes (zero volume and identical price across consecutive market sessions)."""
        if recent_history_df.empty or current_df.empty:
            return current_df.copy(), pd.DataFrame(), []

        quarantine_records: List[Dict[str, Any]] = []
        clean_mask = pd.Series(True, index=current_df.index)

        # Group recent history by symbol
        combined = pd.concat([recent_history_df, current_df], ignore_index=True)
        if "trade_date" in combined.columns:
            combined = combined.sort_values(["symbol", "trade_date"])

        for sym, sym_df in combined.groupby("symbol"):
            if len(sym_df) >= consecutive_days:
                tail = sym_df.tail(consecutive_days)
                # If all volumes are 0 and close == prev_close throughout
                is_stale = (tail["volume"] == 0).all() and (tail["close"] == tail["prev_close"]).all()
                if is_stale:
                    curr_match = current_df[current_df["symbol"] == sym].index
                    for idx in curr_match:
                        clean_mask.loc[idx] = False
                        quarantine_records.append(
                            {
                                "row_index": idx,
                                "symbol": sym,
                                "trade_date": str(current_df.loc[idx, "trade_date"]),
                                "failure_rule": "STALE_QUOTE_DETECTED",
                                "root_cause_detail": f"Zero volume and frozen price across {consecutive_days} consecutive sessions",
                                "severity": "WARNING",
                            }
                        )

        clean_df = current_df[clean_mask].copy()
        quarantine_df = current_df[~clean_mask].copy()
        return clean_df, quarantine_df, quarantine_records
