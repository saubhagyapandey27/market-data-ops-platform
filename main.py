"""Main Entrypoint & CLI for Market-Data Ops & Portfolio Analytics.

Supports running:
- Daily scheduled ETL ingestion pipeline
- Lake historical data seeding
- SQL Portfolio analytics & Risk engine
- Top-N Momentum Backtesting & Significance testing
- Streamlit application launch
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from src.analytics.duckdb_engine import DuckDBEngine
from src.analytics.risk_engine import PortfolioRiskEngine
from src.analytics.sql_analytics import SQLPortfolioAnalytics
from src.backtest.engine import MomentumBacktester
from src.backtest.significance import BootstrapSignificanceTester
from src.ingestion.pipeline import ETLPipeline
from src.utils.seed_data import seed_all_lake_data


def run_etl(trade_date: datetime.date) -> None:
    """Run daily market-data ingestion and quality reconciliation."""
    print(f"==================================================")
    print(f"Starting Market-Data ETL Pipeline for {trade_date}")
    print(f"==================================================")
    pipeline = ETLPipeline()
    results = pipeline.run_daily_etl(trade_date=trade_date)
    for feed, res in results.items():
        print(
            f"[{feed.upper()}] Status: Processed={res.total_records}, "
            f"Clean={res.clean_records}, Quarantined={res.quarantined_records}, "
            f"Hash-Match={res.hash_matched}, Count-Match={res.count_matched}"
        )
    print("ETL and Quality Reconciliation complete. Governance note updated.")


def run_analytics() -> None:
    """Run SQL analytics and risk calculations."""
    engine = DuckDBEngine()
    analytics = SQLPortfolioAnalytics(engine)
    risk = PortfolioRiskEngine(engine)
    backtester = MomentumBacktester(duckdb_engine=engine)

    print("==================================================")
    print("Executing Top-10 Momentum Backtest (2018-2025)...")
    print("==================================================")
    p_mat = backtester.load_price_matrix()
    res = backtester.run_top_n_momentum_backtest(price_matrix=p_mat, top_n=10)
    fixed = backtester.run_fixed_weight_backtest(
        price_matrix=p_mat, start_date=res.equity_curve["trade_date"].iloc[0]
    )

    print("\n--- Strategy Performance KPIs (2018-2025) ---")
    print(f"Strategy:                {res.strategy_name}")
    print(f"Total Cumulative Return: {res.metrics['total_return']*100:.1f}%")
    print(f"CAGR (Post-Cost):        {res.metrics['cagr']*100:.1f}%")
    print(f"Annualized Volatility:   {res.metrics['annualized_volatility']*100:.1f}%")
    print(f"Post-Cost Sharpe Ratio:  {res.metrics['sharpe_ratio']:.2f}")
    print(f"Max Drawdown (DD):       {res.metrics['max_drawdown']*100:.1f}%")
    print(f"Calmar Ratio:            {res.metrics['calmar_ratio']:.2f}")
    print(f"Total Costs Paid:        Rs {res.metrics['total_costs_paid']:,.2f}")

    print("\n--- SQL Risk Engine Metrics ---")
    var_res = risk.compute_var_metrics(res.equity_curve[["trade_date", "daily_return"]])
    print(f"Historical VaR (95% 1-Day): {var_res['historical_var_95_pct']*100:.2f}% (Rs {var_res['historical_var_95_inr']:,.0f})")
    print(f"Historical VaR (99% 1-Day): {var_res['historical_var_99_pct']*100:.2f}% (Rs {var_res['historical_var_99_inr']:,.0f})")
    print(f"Parametric VaR (95% 1-Day): {var_res['parametric_var_95_pct']*100:.2f}% (Rs {var_res['parametric_var_95_inr']:,.0f})")
    print(f"Parametric VaR (99% 1-Day): {var_res['parametric_var_99_pct']*100:.2f}% (Rs {var_res['parametric_var_99_inr']:,.0f})")

    beta = analytics.compute_beta(
        res.equity_curve[["trade_date", "daily_return"]],
        fixed.equity_curve[["trade_date", "daily_return"]],
    )
    te = analytics.compute_tracking_error(
        res.equity_curve[["trade_date", "daily_return"]],
        fixed.equity_curve[["trade_date", "daily_return"]],
    )
    print(f"Portfolio Beta vs Nifty 50: {beta:.2f}")
    print(f"Tracking Error vs Nifty 50: {te*100:.2f}%")

    print("\n--- Bootstrap Significance Testing (2,000 Iterations) ---")
    tester = BootstrapSignificanceTester()
    sig = tester.run_significance_test(
        strategy_returns=res.equity_curve["daily_return"].iloc[1:],
        benchmark_returns=fixed.equity_curve["daily_return"].iloc[1:],
        n_bootstrap_iterations=2000,
    )
    print(f"Bootstrap Mean Sharpe:   {sig.bootstrap_mean_sharpe:.2f}")
    print(f"95% Confidence Interval: [{sig.ci_95_lower:.2f}, {sig.ci_95_upper:.2f}]")
    print(f"H0: Sharpe <= 0 p-value: {sig.p_value_sharpe_gt_zero:.4f}")
    print(f"H0: Alpha <= 0 p-value:  {sig.p_value_alpha_gt_bench:.4f}")
    print(f"T-Statistic:             {sig.t_statistic:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Market-Data Ops & Portfolio Analytics CLI")
    parser.add_argument(
        "--task",
        type=str,
        choices=["seed", "etl", "analytics", "all"],
        default="all",
        help="Task to execute (seed, etl, analytics, all)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.date.today().strftime("%Y-%m-%d"),
        help="Target date for ETL (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    target_d = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()

    if args.task in ["seed", "all"]:
        seed_all_lake_data()

    if args.task in ["etl", "all"]:
        run_etl(target_d)

    if args.task in ["analytics", "all"]:
        run_analytics()


if __name__ == "__main__":
    main()
