"""Bootstrap Significance Testing Module.

Performs block bootstrap resampling to evaluate statistical significance of the
post-cost Sharpe ratio and alpha for Top-N Momentum vs Fixed Weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class BootstrapResult:
    """Results of bootstrap significance testing."""

    original_sharpe: float
    bootstrap_mean_sharpe: float
    bootstrap_std_error: float
    ci_95_lower: float
    ci_95_upper: float
    p_value_sharpe_gt_zero: float
    p_value_alpha_gt_bench: float
    t_statistic: float
    n_iterations: int
    bootstrap_sharpe_distribution: np.ndarray
    bootstrap_alpha_distribution: np.ndarray


class BootstrapSignificanceTester:
    """Stationary / Circular Block Bootstrap significance testing engine."""

    def __init__(self, risk_free_rate: float = 0.065, block_size: int = 15, random_seed: int = 42):
        self.rf = risk_free_rate
        self.rf_daily = (1.0 + self.rf) ** (1.0 / 252.0) - 1.0
        self.block_size = block_size
        self.random_seed = random_seed

    def _generate_block_bootstrap_indices(self, n_obs: int, n_samples: int) -> np.ndarray:
        """Generate circular block bootstrap resampled indices."""
        rng = np.random.default_rng(self.random_seed)
        num_blocks = int(np.ceil(n_obs / self.block_size))
        indices_matrix = np.zeros((n_samples, n_obs), dtype=int)

        for s in range(n_samples):
            start_points = rng.integers(0, n_obs, size=num_blocks)
            sampled_idx = []
            for sp in start_points:
                block = [(sp + k) % n_obs for k in range(self.block_size)]
                sampled_idx.extend(block)
            indices_matrix[s, :] = np.array(sampled_idx[:n_obs])

        return indices_matrix

    def run_significance_test(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
        n_bootstrap_iterations: int = 2000,
    ) -> BootstrapResult:
        """Run block bootstrap test over return series.

        Args:
            strategy_returns: Daily return series of strategy.
            benchmark_returns: Daily return series of benchmark (optional).
            n_bootstrap_iterations: Number of bootstrap resamples.

        Returns:
            BootstrapResult with empirical p-values and confidence intervals.
        """
        r_strat = strategy_returns.dropna().to_numpy()
        n_obs = len(r_strat)

        if benchmark_returns is not None:
            r_bench = benchmark_returns.dropna().to_numpy()
            min_len = min(len(r_strat), len(r_bench))
            r_strat = r_strat[:min_len]
            r_bench = r_bench[:min_len]
            n_obs = min_len
        else:
            r_bench = np.zeros_like(r_strat)

        # Baseline observed Sharpe
        excess_strat = r_strat - self.rf_daily
        strat_mean = np.mean(r_strat) * 252.0
        strat_vol = np.std(r_strat) * np.sqrt(252.0)
        orig_sharpe = float((strat_mean - self.rf) / strat_vol) if strat_vol > 0 else 0.0

        # Resample
        indices = self._generate_block_bootstrap_indices(n_obs, n_bootstrap_iterations)

        boot_sharpes = np.zeros(n_bootstrap_iterations)
        boot_alphas = np.zeros(n_bootstrap_iterations)

        for b in range(n_bootstrap_iterations):
            idx = indices[b]
            resampled_strat = r_strat[idx]
            resampled_bench = r_bench[idx]

            # Bootstrap Sharpe
            b_mean = np.mean(resampled_strat) * 252.0
            b_vol = np.std(resampled_strat) * np.sqrt(252.0)
            boot_sharpes[b] = (b_mean - self.rf) / b_vol if b_vol > 0 else 0.0

            # Bootstrap Alpha vs Benchmark
            b_bench_mean = np.mean(resampled_bench) * 252.0
            boot_alphas[b] = b_mean - b_bench_mean

        boot_mean_sharpe = float(np.mean(boot_sharpes))
        boot_std_err = float(np.std(boot_sharpes))
        ci_lower = float(np.percentile(boot_sharpes, 2.5))
        ci_upper = float(np.percentile(boot_sharpes, 97.5))

        # Empirical p-value H0: Sharpe <= 0
        p_val_sharpe = float(np.mean(boot_sharpes <= 0.0))

        # Empirical p-value H0: Alpha <= 0 vs benchmark
        p_val_alpha = float(np.mean(boot_alphas <= 0.0))

        # T-statistic
        t_stat = float(orig_sharpe / (boot_std_err + 1e-8))

        return BootstrapResult(
            original_sharpe=orig_sharpe,
            bootstrap_mean_sharpe=boot_mean_sharpe,
            bootstrap_std_error=boot_std_err,
            ci_95_lower=ci_lower,
            ci_95_upper=ci_upper,
            p_value_sharpe_gt_zero=p_val_sharpe,
            p_value_alpha_gt_bench=p_val_alpha,
            t_statistic=t_stat,
            n_iterations=n_bootstrap_iterations,
            bootstrap_sharpe_distribution=boot_sharpes,
            bootstrap_alpha_distribution=boot_alphas,
        )
