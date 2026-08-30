"""SQL-based Portfolio Analytics Module.

Executes institutional portfolio analytics entirely in SQL via DuckDB:
Time-Weighted Returns (TWR), Drawdowns, Sector Exposures, Beta, and Tracking Error vs Nifty 50.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.analytics.duckdb_engine import DuckDBEngine


class SQLPortfolioAnalytics:
    """Computes portfolio analytics in pure SQL."""

    def __init__(self, duckdb_engine: Optional[DuckDBEngine] = None):
        self.engine = duckdb_engine or DuckDBEngine()

    def compute_time_weighted_returns(self, portfolio_returns_df: pd.DataFrame) -> pd.DataFrame:
        """Compute cumulative Time-Weighted Returns (TWR) series in SQL.

        Args:
            portfolio_returns_df: DataFrame with ['trade_date', 'daily_return'].

        Returns:
            DataFrame with ['trade_date', 'daily_return', 'twr_multiplier', 'cumulative_twr'].
        """
        self.engine.register_dataframe("port_ret_twr", portfolio_returns_df)

        sql = """
        WITH daily_indexed AS (
            SELECT 
                trade_date,
                daily_return,
                (1.0 + daily_return) AS gross_return,
                LN(1.0 + daily_return) AS log_return
            FROM port_ret_twr
            WHERE daily_return IS NOT NULL
        ),
        cumulative_calc AS (
            SELECT 
                trade_date,
                daily_return,
                gross_return,
                EXP(SUM(log_return) OVER (ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS twr_multiplier
            FROM daily_indexed
        )
        SELECT 
            trade_date,
            daily_return,
            twr_multiplier,
            (twr_multiplier - 1.0) AS cumulative_twr
        FROM cumulative_calc
        ORDER BY trade_date ASC
        """
        return self.engine.query(sql)

    def compute_drawdowns(self, twr_df: pd.DataFrame) -> pd.DataFrame:
        """Compute running peak, drawdown series, and drawdown durations in SQL.

        Args:
            twr_df: DataFrame with ['trade_date', 'twr_multiplier'] or ['trade_date', 'cumulative_twr'].

        Returns:
            DataFrame with ['trade_date', 'cumulative_value', 'running_peak', 'drawdown_pct'].
        """
        if "twr_multiplier" not in twr_df.columns:
            twr_df["twr_multiplier"] = 1.0 + twr_df["cumulative_twr"]

        self.engine.register_dataframe("twr_dd_table", twr_df)

        sql = """
        WITH peak_calc AS (
            SELECT 
                trade_date,
                twr_multiplier AS cumulative_value,
                MAX(twr_multiplier) OVER (
                    ORDER BY trade_date 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS running_peak
            FROM twr_dd_table
        )
        SELECT 
            trade_date,
            cumulative_value,
            running_peak,
            ((cumulative_value - running_peak) / running_peak) AS drawdown_pct
        FROM peak_calc
        ORDER BY trade_date ASC
        """
        return self.engine.query(sql)

    def compute_sector_exposures(self, holdings_df: pd.DataFrame) -> pd.DataFrame:
        """Compute portfolio sector exposure weights in SQL by joining reference sectors.

        Args:
            holdings_df: DataFrame with ['trade_date', 'symbol', 'weight', 'position_value'].

        Returns:
            DataFrame with ['trade_date', 'sector', 'sector_weight', 'sector_value'].
        """
        self.engine.register_dataframe("holdings_input", holdings_df)

        sql = """
        SELECT 
            h.trade_date,
            COALESCE(s.sector, 'Other') AS sector,
            ROUND(SUM(h.weight), 6) AS sector_weight,
            ROUND(SUM(h.position_value), 2) AS sector_value
        FROM holdings_input h
        LEFT JOIN sectors_ref s ON h.symbol = s.symbol
        GROUP BY h.trade_date, COALESCE(s.sector, 'Other')
        ORDER BY h.trade_date ASC, sector_weight DESC
        """
        return self.engine.query(sql)

    def compute_beta(
        self, portfolio_returns_df: pd.DataFrame, benchmark_returns_df: pd.DataFrame
    ) -> float:
        """Compute Portfolio Beta vs Nifty 50 benchmark in pure SQL."""
        self.engine.register_dataframe("port_ret_beta", portfolio_returns_df)
        self.engine.register_dataframe("bench_ret_beta", benchmark_returns_df)

        sql = """
        SELECT 
            COVAR_SAMP(p.daily_return, b.daily_return) / NULLIF(VAR_SAMP(b.daily_return), 0.0) AS beta
        FROM port_ret_beta p
        JOIN bench_ret_beta b ON p.trade_date = b.trade_date
        WHERE p.daily_return IS NOT NULL AND b.daily_return IS NOT NULL
        """
        res = self.engine.query(sql)
        val = res["beta"].iloc[0] if not res.empty and pd.notna(res["beta"].iloc[0]) else 1.0
        return float(val)

    def compute_tracking_error(
        self, portfolio_returns_df: pd.DataFrame, benchmark_returns_df: pd.DataFrame
    ) -> float:
        """Compute Annualized Tracking Error vs Nifty 50 benchmark in SQL."""
        self.engine.register_dataframe("port_ret_te", portfolio_returns_df)
        self.engine.register_dataframe("bench_ret_te", benchmark_returns_df)

        sql = """
        SELECT 
            SQRT(252.0) * STDDEV_SAMP(p.daily_return - b.daily_return) AS tracking_error
        FROM port_ret_te p
        JOIN bench_ret_te b ON p.trade_date = b.trade_date
        WHERE p.daily_return IS NOT NULL AND b.daily_return IS NOT NULL
        """
        res = self.engine.query(sql)
        val = res["tracking_error"].iloc[0] if not res.empty and pd.notna(res["tracking_error"].iloc[0]) else 0.0
        return float(val)

    def compute_full_portfolio_summary(
        self, portfolio_returns_df: pd.DataFrame, benchmark_returns_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """Compute all portfolio summary analytics in SQL."""
        self.engine.register_dataframe("p_sum", portfolio_returns_df)
        self.engine.register_dataframe("b_sum", benchmark_returns_df)

        twr_df = self.compute_time_weighted_returns(portfolio_returns_df)
        dd_df = self.compute_drawdowns(twr_df)

        max_dd = float(dd_df["drawdown_pct"].min()) if not dd_df.empty else 0.0
        cum_twr = float(twr_df["cumulative_twr"].iloc[-1]) if not twr_df.empty else 0.0
        beta = self.compute_beta(portfolio_returns_df, benchmark_returns_df)
        tracking_error = self.compute_tracking_error(portfolio_returns_df, benchmark_returns_df)

        # SQL stats: CAGR, Volatility, Sharpe
        sql = """
        WITH stats AS (
            SELECT 
                COUNT(*) AS total_trading_days,
                AVG(daily_return) AS mean_daily_ret,
                STDDEV_SAMP(daily_return) AS daily_vol,
                (POWER(1.0 + AVG(daily_return), 252.0) - 1.0) AS cagr_approx,
                (STDDEV_SAMP(daily_return) * SQRT(252.0)) AS annualized_vol
            FROM p_sum
        )
        SELECT 
            total_trading_days,
            mean_daily_ret,
            daily_vol,
            annualized_vol,
            (cagr_approx - 0.065) / NULLIF(annualized_vol, 0.0) AS approx_sharpe
        FROM stats
        """
        res = self.engine.query(sql).iloc[0].to_dict()

        return {
            "cumulative_twr": cum_twr,
            "max_drawdown": max_dd,
            "beta_vs_nifty": beta,
            "tracking_error_vs_nifty": tracking_error,
            "annualized_volatility": float(res.get("annualized_vol", 0.0)),
            "trading_days": int(res.get("total_trading_days", 0)),
        }
