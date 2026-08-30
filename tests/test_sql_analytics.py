"""Tests for Pure SQL Portfolio Analytics (DuckDB)."""

import pandas as pd
import pytest

from src.analytics.duckdb_engine import DuckDBEngine
from src.analytics.sql_analytics import SQLPortfolioAnalytics


@pytest.fixture
def analytics_setup():
    engine = DuckDBEngine()
    analytics = SQLPortfolioAnalytics(engine)
    return engine, analytics


def test_sql_time_weighted_returns(analytics_setup):
    _, analytics = analytics_setup
    ret_df = pd.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "daily_return": [0.01, 0.02, -0.01],
        }
    )
    twr_res = analytics.compute_time_weighted_returns(ret_df)
    assert len(twr_res) == 3
    # Cumulative: (1.01 * 1.02 * 0.99) - 1 = 1.019898 - 1 = 0.019898
    expected_cum = (1.01 * 1.02 * 0.99) - 1.0
    assert pytest.approx(twr_res["cumulative_twr"].iloc[-1], rel=1e-4) == expected_cum


def test_sql_drawdowns(analytics_setup):
    _, analytics = analytics_setup
    twr_df = pd.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "cumulative_twr": [0.0, 0.10, 0.05, -0.01],
            "twr_multiplier": [1.0, 1.10, 1.05, 0.99],
        }
    )
    dd_res = analytics.compute_drawdowns(twr_df)
    assert len(dd_res) == 4
    # Peak at idx 1 (1.10). At idx 2: (1.05 - 1.10)/1.10 = -0.04545
    assert pytest.approx(dd_res["drawdown_pct"].iloc[2], rel=1e-3) == (1.05 - 1.10) / 1.10
    # At idx 3: (0.99 - 1.10)/1.10 = -0.10
    assert pytest.approx(dd_res["drawdown_pct"].iloc[3], rel=1e-3) == (0.99 - 1.10) / 1.10


def test_sql_beta_and_tracking_error(analytics_setup):
    _, analytics = analytics_setup
    port_df = pd.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "daily_return": [0.02, -0.01, 0.03, -0.02],
        }
    )
    bench_df = pd.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "daily_return": [0.01, -0.005, 0.015, -0.01],
        }
    )
    beta = analytics.compute_beta(port_df, bench_df)
    te = analytics.compute_tracking_error(port_df, bench_df)

    assert pytest.approx(beta, rel=1e-2) == 2.0
    assert te > 0.0


def test_sql_sector_exposures(analytics_setup):
    _, analytics = analytics_setup
    holdings = pd.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
            "symbol": ["RELIANCE", "TCS", "INFY"],
            "weight": [0.5, 0.3, 0.2],
            "position_value": [500000.0, 300000.0, 200000.0],
        }
    )
    sector_res = analytics.compute_sector_exposures(holdings)
    assert len(sector_res) >= 2
    it_row = sector_res[sector_res["sector"] == "Information Technology"]
    assert len(it_row) == 1
    assert pytest.approx(it_row["sector_weight"].iloc[0], rel=1e-4) == 0.50  # TCS 0.3 + INFY 0.2
