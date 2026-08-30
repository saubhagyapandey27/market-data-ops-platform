"""Portfolio Risk Engine Module.

Computes Value-at-Risk (Historical and Parametric VaR at 95% and 99%),
Conditional VaR (Expected Shortfall), and tail risk metrics directly in SQL.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.analytics.duckdb_engine import DuckDBEngine


class PortfolioRiskEngine:
    """Computes portfolio risk metrics in SQL via DuckDB."""

    def __init__(self, duckdb_engine: Optional[DuckDBEngine] = None):
        self.engine = duckdb_engine or DuckDBEngine()

    def compute_var_metrics(
        self, portfolio_returns_df: pd.DataFrame, portfolio_value: float = 10_000_000.0
    ) -> Dict[str, Any]:
        """Compute 1-day Historical VaR, Parametric VaR, CVaR at 95% and 99% confidence levels in SQL.

        Args:
            portfolio_returns_df: DataFrame with ['trade_date', 'daily_return'].
            portfolio_value: Total portfolio value in INR.

        Returns:
            Dictionary containing VaR % and VaR INR figures.
        """
        self.engine.register_dataframe("port_ret_risk", portfolio_returns_df)

        sql = """
        WITH base_stats AS (
            SELECT 
                COUNT(*) AS n_obs,
                AVG(daily_return) AS mu,
                STDDEV_SAMP(daily_return) AS sigma,
                -PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY daily_return) AS hist_var_95_pct,
                -PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY daily_return) AS hist_var_99_pct
            FROM port_ret_risk
            WHERE daily_return IS NOT NULL
        ),
        cvar_calc AS (
            SELECT 
                -AVG(p.daily_return) AS hist_cvar_95_pct
            FROM port_ret_risk p, base_stats s
            WHERE p.daily_return <= -s.hist_var_95_pct
        ),
        cvar_99_calc AS (
            SELECT 
                -AVG(p.daily_return) AS hist_cvar_99_pct
            FROM port_ret_risk p, base_stats s
            WHERE p.daily_return <= -s.hist_var_99_pct
        )
        SELECT 
            s.n_obs,
            s.mu AS mean_daily_return,
            s.sigma AS daily_volatility,
            (s.sigma * SQRT(252.0)) AS annualized_volatility,
            s.hist_var_95_pct,
            s.hist_var_99_pct,
            -(s.mu - 1.644853 * s.sigma) AS param_var_95_pct,
            -(s.mu - 2.326348 * s.sigma) AS param_var_99_pct,
            COALESCE(c95.hist_cvar_95_pct, s.hist_var_95_pct) AS hist_cvar_95_pct,
            COALESCE(c99.hist_cvar_99_pct, s.hist_var_99_pct) AS hist_cvar_99_pct
        FROM base_stats s, cvar_calc c95, cvar_99_calc c99
        """
        res = self.engine.query(sql).iloc[0].to_dict()

        hist_var_95 = float(res.get("hist_var_95_pct", 0.0))
        hist_var_99 = float(res.get("hist_var_99_pct", 0.0))
        param_var_95 = float(res.get("param_var_95_pct", 0.0))
        param_var_99 = float(res.get("param_var_99_pct", 0.0))
        cvar_95 = float(res.get("hist_cvar_95_pct", 0.0))
        cvar_99 = float(res.get("hist_cvar_99_pct", 0.0))

        return {
            "historical_var_95_pct": hist_var_95,
            "historical_var_95_inr": hist_var_95 * portfolio_value,
            "historical_var_99_pct": hist_var_99,
            "historical_var_99_inr": hist_var_99 * portfolio_value,
            "parametric_var_95_pct": param_var_95,
            "parametric_var_95_inr": param_var_95 * portfolio_value,
            "parametric_var_99_pct": param_var_99,
            "parametric_var_99_inr": param_var_99 * portfolio_value,
            "expected_shortfall_95_pct": cvar_95,
            "expected_shortfall_95_inr": cvar_95 * portfolio_value,
            "expected_shortfall_99_pct": cvar_99,
            "expected_shortfall_99_inr": cvar_99 * portfolio_value,
            "daily_volatility": float(res.get("daily_volatility", 0.0)),
            "annualized_volatility": float(res.get("annualized_volatility", 0.0)),
            "mean_daily_return": float(res.get("mean_daily_return", 0.0)),
            "observations": int(res.get("n_obs", 0)),
        }
