"""Tests for Portfolio Risk Engine (Historical & Parametric VaR, CVaR)."""

import numpy as np
import pandas as pd
import pytest

from src.analytics.duckdb_engine import DuckDBEngine
from src.analytics.risk_engine import PortfolioRiskEngine


def test_var_and_risk_metrics():
    engine = DuckDBEngine()
    risk_engine = PortfolioRiskEngine(engine)

    # Generate synthetic Gaussian returns
    np.random.seed(42)
    daily_returns = np.random.normal(0.001, 0.015, 1000)
    dates = pd.date_range("2020-01-01", periods=1000, freq="B").strftime("%Y-%m-%d")

    df_ret = pd.DataFrame({"trade_date": dates, "daily_return": daily_returns})

    var_res = risk_engine.compute_var_metrics(df_ret, portfolio_value=10_000_000.0)

    assert var_res["observations"] == 1000
    assert 0.015 <= var_res["historical_var_95_pct"] <= 0.035
    assert 0.025 <= var_res["historical_var_99_pct"] <= 0.050
    assert 0.015 <= var_res["parametric_var_95_pct"] <= 0.035
    assert 0.025 <= var_res["parametric_var_99_pct"] <= 0.050

    # 99% VaR should be greater than 95% VaR
    assert var_res["historical_var_99_pct"] > var_res["historical_var_95_pct"]
    assert var_res["parametric_var_99_pct"] > var_res["parametric_var_95_pct"]

    # Expected Shortfall (CVaR) should be greater than or equal to VaR
    assert var_res["expected_shortfall_95_pct"] >= var_res["historical_var_95_pct"]
