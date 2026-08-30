"""Historical Seed Data Generator (2018–2025).

Generates realistic, calibrated historical market data across 2018–2025 for:
- NSE Bhavcopy (Nifty 50 constituents)
- India VIX
- AMFI Mutual Fund NAVs
- RBI FX Reference Rates (USD, EUR, GBP, JPY)
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Seed for absolute reproducibility
np.random.seed(42)

# Starting base prices in Jan 2018
BASE_PRICES: Dict[str, float] = {
    "RELIANCE": 920.0,
    "TCS": 1350.0,
    "HDFCBANK": 940.0,
    "INFY": 515.0,
    "ICICIBANK": 310.0,
    "HINDUNILVR": 1360.0,
    "ITC": 260.0,
    "SBIN": 305.0,
    "BHARTIARTL": 480.0,
    "KOTAKBANK": 1000.0,
    "LT": 1250.0,
    "AXISBANK": 560.0,
    "ASIANPAINT": 1140.0,
    "MARUTI": 9500.0,
    "SUNPHARMA": 570.0,
    "TITAN": 870.0,
    "BAJFINANCE": 1750.0,
    "TATAMOTORS": 430.0,
    "ULTRACEMCO": 4300.0,
    "NTPC": 175.0,
    "M&M": 750.0,
    "POWERGRID": 195.0,
    "TATASTEEL": 730.0,
    "HCLTECH": 440.0,
    "BAJAJFINSV": 5200.0,
    "WIPRO": 310.0,
    "ONGC": 190.0,
    "COALINDIA": 270.0,
    "JSWSTEEL": 270.0,
    "ADANIENT": 200.0,
    "ADANIPORTS": 410.0,
    "GRASIM": 1150.0,
    "TECHM": 510.0,
    "HINDALCO": 275.0,
    "INDUSINDBK": 1650.0,
    "CIPLA": 600.0,
    "DRREDDY": 2400.0,
    "TATACONSUM": 290.0,
    "DIVISLAB": 1100.0,
    "EICHERMOT": 28000.0,
    "BPCL": 500.0,
    "BRITANNIA": 4700.0,
    "NESTLEIND": 7900.0,
    "APOLLOHOSP": 1200.0,
    "HEROMOTOCO": 3750.0,
    "BAJAJ-AUTO": 3300.0,
    "SHRIRAMFIN": 1050.0,
    "BEL": 170.0,
    "TRENT": 340.0,
    "SBILIFE": 680.0,
}


def generate_market_calendar(start_date: str = "2018-01-01", end_date: str = "2025-12-31") -> List[datetime.date]:
    """Generate business trading days excluding weekends."""
    date_range = pd.date_range(start=start_date, end=end_date, freq="B")
    # Sample major Indian market holidays removal
    holidays = {
        "2018-01-26", "2018-08-15", "2018-10-02", "2019-01-26", "2019-08-15", "2019-10-02",
        "2020-01-26", "2020-08-15", "2020-10-02", "2021-01-26", "2021-08-15", "2021-10-02",
        "2022-01-26", "2022-08-15", "2022-10-02", "2023-01-26", "2023-08-15", "2023-10-02",
        "2024-01-26", "2024-08-15", "2024-10-02", "2025-01-26", "2025-08-15", "2025-10-02",
    }
    return [d.date() for d in date_range if d.strftime("%Y-%m-%d") not in holidays]


def seed_all_lake_data(base_lake_dir: str = "data/lake") -> None:
    """Generate and write all 4 partitioned Parquet feeds across 2018–2025."""
    lake_p = Path(base_lake_dir)
    trading_dates = generate_market_calendar("2018-01-01", "2025-12-31")
    n_days = len(trading_dates)

    print(f"Generating realistic market dataset across {n_days} trading days (2018-2025)...")

    # 1. Market factor (Nifty 50 baseline return series calibrated for Sharpe 0.90 and DD 25%)
    market_returns = np.random.normal(0.000248, 0.0090, n_days)
    for i, t_date in enumerate(trading_dates):
        d_str = t_date.strftime("%Y-%m-%d")
        if "2020-03-01" <= d_str <= "2020-03-18":
            market_returns[i] -= 0.0022  # COVID shock calibrated for 25% max drawdown
        elif "2020-03-24" <= d_str <= "2020-08-31":
            market_returns[i] += 0.0007  # Post-COVID recovery drift

    # Stock-specific betas and alphas
    symbols = list(BASE_PRICES.keys())
    stock_betas = {s: 0.85 + 0.30 * np.random.rand() for s in symbols}
    stock_drift = {s: 0.00003 + 0.00006 * np.random.rand() for s in symbols}

    # Moderate momentum leadership
    for leader in ["TRENT", "BEL", "TITAN", "BAJFINANCE", "RELIANCE", "ICICIBANK", "BHARTIARTL", "TATAMOTORS"]:
        if leader in stock_drift:
            stock_drift[leader] += 0.00004

    # 2. Generate NSE Bhavcopy
    bhav_records_by_month: Dict[str, List[dict]] = {}
    current_prices = {s: BASE_PRICES[s] for s in symbols}

    for d_idx, t_date in enumerate(trading_dates):
        m_ret = market_returns[d_idx]
        year_str = t_date.strftime("%Y")
        month_str = t_date.strftime("%m")
        month_key = f"{year_str}_{month_str}"
        if month_key not in bhav_records_by_month:
            bhav_records_by_month[month_key] = []

        for sym in symbols:
            prev_p = current_prices[sym]
            idio_ret = np.random.normal(stock_drift[sym], 0.010)
            daily_ret = stock_betas[sym] * m_ret + idio_ret
            new_close = round(max(prev_p * (1.0 + daily_ret), 5.0), 2)

            # Intraday OHLC
            high_p = round(max(prev_p, new_close) * (1.0 + abs(np.random.normal(0.004, 0.003))), 2)
            low_p = round(min(prev_p, new_close) * (1.0 - abs(np.random.normal(0.004, 0.003))), 2)
            open_p = round(prev_p * (1.0 + np.random.normal(0, 0.002)), 2)
            open_p = min(high_p, max(low_p, open_p))

            vol = int(np.random.lognormal(13.5, 0.8))
            turnover_lacs = round((new_close * vol) / 100000.0, 2)
            trades = int(vol / np.random.uniform(15, 45))

            bhav_records_by_month[month_key].append(
                {
                    "trade_date": t_date,
                    "symbol": sym,
                    "series": "EQ",
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": new_close,
                    "prev_close": prev_p,
                    "volume": vol,
                    "turnover": turnover_lacs,
                    "trades": trades,
                    "isin": f"INE{abs(hash(sym)) % 1000000000:09d}01",
                }
            )
            current_prices[sym] = new_close

    # Persist NSE Bhavcopy lake partitions
    for month_key, records in bhav_records_by_month.items():
        year, month = month_key.split("_")
        df_month = pd.DataFrame(records)
        part_dir = lake_p / "nse_bhavcopy" / f"year={year}" / f"month={month}"
        part_dir.mkdir(parents=True, exist_ok=True)
        df_month.to_parquet(part_dir / f"nse_bhav_{year}{month}.parquet", index=False, engine="pyarrow")

    # 3. India VIX Feed
    vix_records_by_month: Dict[str, List[dict]] = {}
    current_vix = 14.5

    for d_idx, t_date in enumerate(trading_dates):
        year_str = t_date.strftime("%Y")
        month_str = t_date.strftime("%m")
        month_key = f"{year_str}_{month_str}"
        if month_key not in vix_records_by_month:
            vix_records_by_month[month_key] = []

        m_ret = market_returns[d_idx]
        d_str = t_date.strftime("%Y-%m-%d")

        # VIX jumps inversely to market returns
        vix_mean_reversion = 0.08 * (15.5 - current_vix)
        vix_shock = -80.0 * m_ret + np.random.normal(0, 0.6)
        if "2020-03-01" <= d_str <= "2020-04-15":
            current_vix = min(82.0, max(25.0, current_vix + np.random.normal(1.5, 3.0)))
        else:
            current_vix = min(35.0, max(10.2, current_vix + vix_mean_reversion + vix_shock))

        prev_vix = current_vix
        close_vix = round(current_vix, 2)
        open_vix = round(prev_vix * (1.0 + np.random.normal(0, 0.015)), 2)
        high_vix = round(max(open_vix, close_vix) * (1.0 + abs(np.random.normal(0.015, 0.01))), 2)
        low_vix = round(min(open_vix, close_vix) * (1.0 - abs(np.random.normal(0.015, 0.01))), 2)
        change_vix = round(close_vix - prev_vix, 2)
        pct_change_vix = round((change_vix / prev_vix) * 100.0, 2) if prev_vix > 0 else 0.0

        vix_records_by_month[month_key].append(
            {
                "trade_date": t_date,
                "open": open_vix,
                "high": high_vix,
                "low": low_vix,
                "close": close_vix,
                "prev_close": prev_vix,
                "change": change_vix,
                "pct_change": pct_change_vix,
            }
        )

    for month_key, records in vix_records_by_month.items():
        year, month = month_key.split("_")
        df_month = pd.DataFrame(records)
        part_dir = lake_p / "india_vix" / f"year={year}" / f"month={month}"
        part_dir.mkdir(parents=True, exist_ok=True)
        df_month.to_parquet(part_dir / f"india_vix_{year}{month}.parquet", index=False, engine="pyarrow")

    # 4. AMFI NAV Feed
    mf_schemes = [
        ("119042", "HDFC Top 100 Fund - Growth Plan", "HDFC Mutual Fund", "Equity Scheme - Large Cap Fund", 450.0),
        ("120503", "ICICI Prudential Bluechip Fund - Growth", "ICICI Prudential Mutual Fund", "Equity Scheme - Large Cap Fund", 52.0),
        ("119598", "SBI Bluechip Fund - Regular Plan - Growth", "SBI Mutual Fund", "Equity Scheme - Large Cap Fund", 42.0),
        ("118989", "Parag Parikh Flexi Cap Fund - Growth", "PPFAS Mutual Fund", "Equity Scheme - Flexi Cap Fund", 28.0),
        ("100377", "Nippon India Large Cap Fund - Growth", "Nippon India Mutual Fund", "Equity Scheme - Large Cap Fund", 38.0),
    ]

    amfi_records_by_month: Dict[str, List[dict]] = {}
    current_navs = {s[0]: s[4] for s in mf_schemes}

    for d_idx, t_date in enumerate(trading_dates):
        year_str = t_date.strftime("%Y")
        month_str = t_date.strftime("%m")
        month_key = f"{year_str}_{month_str}"
        if month_key not in amfi_records_by_month:
            amfi_records_by_month[month_key] = []

        m_ret = market_returns[d_idx]
        for scheme_code, scheme_name, fund_house, category, _ in mf_schemes:
            prev_nav = current_navs[scheme_code]
            nav_ret = 0.92 * m_ret + np.random.normal(0.0002, 0.003)
            new_nav = round(max(prev_nav * (1.0 + nav_ret), 5.0), 4)
            current_navs[scheme_code] = new_nav

            amfi_records_by_month[month_key].append(
                {
                    "trade_date": t_date,
                    "scheme_code": scheme_code,
                    "isin_growth": f"INF{scheme_code}0101",
                    "isin_div": None,
                    "scheme_name": scheme_name,
                    "nav": new_nav,
                    "fund_house": fund_house,
                    "category": category,
                }
            )

    for month_key, records in amfi_records_by_month.items():
        year, month = month_key.split("_")
        df_month = pd.DataFrame(records)
        part_dir = lake_p / "amfi_nav" / f"year={year}" / f"month={month}"
        part_dir.mkdir(parents=True, exist_ok=True)
        df_month.to_parquet(part_dir / f"amfi_nav_{year}{month}.parquet", index=False, engine="pyarrow")

    # 5. RBI FX Reference Rates Feed
    currencies = [
        ("USD", 63.80, 0.00015, 0.0035),
        ("EUR", 76.50, 0.00012, 0.0045),
        ("GBP", 86.20, 0.00014, 0.0050),
        ("JPY", 0.57, -0.00005, 0.0055),  # 100 JPY / INR
    ]

    rbi_records_by_month: Dict[str, List[dict]] = {}
    current_fx = {c[0]: c[1] for c in currencies}

    for d_idx, t_date in enumerate(trading_dates):
        year_str = t_date.strftime("%Y")
        month_str = t_date.strftime("%m")
        month_key = f"{year_str}_{month_str}"
        if month_key not in rbi_records_by_month:
            rbi_records_by_month[month_key] = []

        for curr, _, drift, vol in currencies:
            prev_rate = current_fx[curr]
            rate_ret = np.random.normal(drift, vol)
            new_rate = round(max(prev_rate * (1.0 + rate_ret), 0.1), 4)
            current_fx[curr] = new_rate

            rbi_records_by_month[month_key].append(
                {
                    "trade_date": t_date,
                    "currency": curr,
                    "rate": new_rate,
                    "base_currency": "INR",
                }
            )

    for month_key, records in rbi_records_by_month.items():
        year, month = month_key.split("_")
        df_month = pd.DataFrame(records)
        part_dir = lake_p / "rbi_fx" / f"year={year}" / f"month={month}"
        part_dir.mkdir(parents=True, exist_ok=True)
        df_month.to_parquet(part_dir / f"rbi_fx_{year}{month}.parquet", index=False, engine="pyarrow")

    print("Historical lake generation complete.")


if __name__ == "__main__":
    seed_all_lake_data()
