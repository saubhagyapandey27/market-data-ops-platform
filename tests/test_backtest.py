"""Tests for Momentum Backtester & Bootstrap Significance Testing (2018–2025)."""

import numpy as np
import pandas as pd
import pytest

from src.analytics.duckdb_engine import DuckDBEngine
from src.backtest.engine import MomentumBacktester
from src.backtest.significance import BootstrapSignificanceTester
from src.utils.seed_data import seed_all_lake_data


@pytest.fixture(scope="session")
def lake_environment(tmp_path_factory):
    lake_dir = tmp_path_factory.mktemp("test_lake")
    seed_all_lake_data(str(lake_dir))
    engine = DuckDBEngine(base_lake_dir=str(lake_dir))
    return engine


def test_momentum_and_fixed_weight_backtest(lake_environment):
    engine = lake_environment
    backtester = MomentumBacktester(duckdb_engine=engine, cost_bps=15.0)

    p_matrix = backtester.load_price_matrix()
    assert not p_matrix.empty
    assert len(p_matrix.columns) >= 40  # 50 symbols

    mom_res = backtester.run_top_n_momentum_backtest(price_matrix=p_matrix, top_n=10)
    assert not mom_res.equity_curve.empty
    assert "portfolio_value" in mom_res.equity_curve.columns
    assert "drawdown" in mom_res.equity_curve.columns

    fixed_res = backtester.run_fixed_weight_backtest(
        price_matrix=p_matrix, start_date=mom_res.equity_curve["trade_date"].iloc[0]
    )
    assert not fixed_res.equity_curve.empty

    # Verify performance metrics over 2018-2025
    # Sharpe should be ~0.9 (allow reasonable tolerance [0.75, 1.25])
    # Max DD should be ~25% (allow [0.18, 0.32])
    sharpe = mom_res.metrics["sharpe_ratio"]
    max_dd = mom_res.metrics["max_drawdown"]

    print(f"Observed Sharpe: {sharpe:.2f}, Max Drawdown: {max_dd:.2f}")
    assert 0.70 <= sharpe <= 1.30
    assert 0.15 <= max_dd <= 0.35


def test_bootstrap_significance_testing():
    tester = BootstrapSignificanceTester(risk_free_rate=0.065, block_size=10, random_seed=42)

    np.random.seed(42)
    # Positive excess return series
    strat_ret = pd.Series(np.random.normal(0.0009, 0.012, 1000))
    bench_ret = pd.Series(np.random.normal(0.0004, 0.012, 1000))

    res = tester.run_significance_test(
        strategy_returns=strat_ret, benchmark_returns=bench_ret, n_bootstrap_iterations=500
    )

    assert res.n_iterations == 500
    assert res.bootstrap_mean_sharpe > 0.0
    assert res.ci_95_lower < res.ci_95_upper
    assert res.p_value_sharpe_gt_zero < 0.05
    assert len(res.bootstrap_sharpe_distribution) == 500
