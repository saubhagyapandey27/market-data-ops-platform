"""Tests for Data Quality & Reconciliation Controls (Hash-Count, CA, Stale Quotes, Quarantine)."""

import datetime
import pandas as pd
import pytest

from src.quality.quarantine import QuarantineManager
from src.quality.reconciliation import DataQualityReconciler


def test_hash_count_reconciliation():
    reconciler = DataQualityReconciler()
    df = pd.DataFrame(
        {
            "symbol": ["INFY", "TCS"],
            "trade_date": ["2024-01-01", "2024-01-01"],
            "close": [1500.0, 3800.0],
        }
    )
    raw_hash = "a" * 64
    count_matched, hash_valid, proc_hash = reconciler.reconcile_hash_and_counts(
        raw_count=2, parsed_df=df, raw_hash=raw_hash, feed_name="nse_bhavcopy"
    )
    assert count_matched is True
    assert hash_valid is True
    assert len(proc_hash) == 64


def test_domain_constraint_violations():
    reconciler = DataQualityReconciler()
    bad_df = pd.DataFrame(
        {
            "symbol": ["RELIANCE", "BADSTOCK"],
            "series": ["EQ", "EQ"],
            "trade_date": [datetime.date(2024, 1, 1), datetime.date(2024, 1, 1)],
            "open": [2500.0, -10.0],  # Negative price!
            "high": [2550.0, 50.0],
            "low": [2490.0, 100.0],  # Low > High!
            "close": [2540.0, 20.0],
            "volume": [1000, 50],
        }
    )

    clean_df, quaran_df, issues = reconciler.validate_domain_constraints(bad_df, "nse_bhavcopy")
    assert len(clean_df) == 1
    assert clean_df["symbol"].iloc[0] == "RELIANCE"
    assert len(quaran_df) == 1
    assert quaran_df["symbol"].iloc[0] == "BADSTOCK"
    assert len(issues) == 1
    assert issues[0]["failure_rule"] == "DOMAIN_CONSTRAINT_VIOLATION"


def test_corporate_actions_reconciliation():
    ca_df = pd.DataFrame(
        [
            {
                "symbol": "TATASTEEL",
                "ex_date": "2022-07-28",
                "action_type": "SPLIT",
                "ratio": "10:1",
            }
        ]
    )
    reconciler = DataQualityReconciler(corporate_actions_df=ca_df)

    # 1. Explained shock (TATASTEEL split)
    df_explained = pd.DataFrame(
        [
            {
                "symbol": "TATASTEEL",
                "trade_date": "2022-07-28",
                "prev_close": 960.0,
                "close": 96.0,  # 90% drop
            }
        ]
    )
    clean1, quaran1, issues1 = reconciler.reconcile_corporate_actions(df_explained)
    assert len(clean1) == 1
    assert len(quaran1) == 0

    # 2. Unexplained shock
    df_unexplained = pd.DataFrame(
        [
            {
                "symbol": "MYSTERIOUS_CO",
                "trade_date": "2022-07-28",
                "prev_close": 500.0,
                "close": 200.0,  # 60% drop without CA entry
            }
        ]
    )
    clean2, quaran2, issues2 = reconciler.reconcile_corporate_actions(df_unexplained)
    assert len(clean2) == 0
    assert len(quaran2) == 1
    assert issues2[0]["failure_rule"] == "UNEXPLAINED_PRICE_SHOCK"


def test_stale_quote_reconciliation():
    reconciler = DataQualityReconciler()
    history = pd.DataFrame(
        [
            {"symbol": "FROZEN_STK", "trade_date": "2024-01-01", "close": 100.0, "prev_close": 100.0, "volume": 0},
            {"symbol": "FROZEN_STK", "trade_date": "2024-01-02", "close": 100.0, "prev_close": 100.0, "volume": 0},
        ]
    )
    curr = pd.DataFrame(
        [
            {"symbol": "FROZEN_STK", "trade_date": "2024-01-03", "close": 100.0, "prev_close": 100.0, "volume": 0},
            {"symbol": "ACTIVE_STK", "trade_date": "2024-01-03", "close": 250.0, "prev_close": 245.0, "volume": 50000},
        ]
    )
    clean, quaran, issues = reconciler.reconcile_stale_quotes(history, curr, consecutive_days=3)
    assert len(clean) == 1
    assert clean["symbol"].iloc[0] == "ACTIVE_STK"
    assert len(quaran) == 1
    assert quaran["symbol"].iloc[0] == "FROZEN_STK"


def test_quarantine_storage_workflow(tmp_path):
    mgr = QuarantineManager(base_quarantine_path=str(tmp_path / "quarantine"))
    bad_df = pd.DataFrame([{"symbol": "BAD1", "close": -5.0}])
    issues = [{"failure_rule": "DOMAIN_VIOLATION", "root_cause_detail": "Negative close", "severity": "CRITICAL"}]
    file_path = mgr.quarantine_records(
        feed_name="nse_bhavcopy",
        quarantine_df=bad_df,
        issues=issues,
        trade_date=datetime.date(2024, 1, 15),
    )
    assert file_path is not None
    loaded_df = mgr.load_all_quarantine()
    assert len(loaded_df) == 1
    assert loaded_df["failure_rule"].iloc[0] == "DOMAIN_VIOLATION"
    assert loaded_df["severity"].iloc[0] == "CRITICAL"
