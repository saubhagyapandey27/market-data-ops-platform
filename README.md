# Market-Data Ops & Portfolio Analytics Platform

An automated market-data ingestion and portfolio risk engine for Indian equities, indices, mutual funds, and foreign exchange feeds, built with Python, DuckDB, Apache Parquet, Streamlit, and GitHub Actions.

---

## Features

### 1. Market Data Ingestion & Storage (`src/ingestion/`)
* **NSE Equity Bhavcopy**: Fetches, standardizes, and validates daily equity trade data (OHLC, volume, turnover, trade count, ISIN, and series).
* **India VIX**: Ingests daily volatility index open, high, low, close, and percentage change.
* **AMFI Mutual Funds**: Ingests daily NAV feeds from AMFI across equity categories and asset management companies.
* **RBI FX Reference Rates**: Parses daily foreign exchange reference rates for USD/INR, EUR/INR, GBP/INR, and JPY/INR.
* **Partitioned Parquet Data Lake**: Persists ingested feeds in Hive-partitioned directory structures (`data/lake/<feed_name>/year=YYYY/month=MM/<feed_name>_YYYYMMDD.parquet`).

### 2. Quality Control, Reconciliation & Quarantine (`src/quality/`)
* **Hash-Count Reconciliation**: Validates SHA-256 payload checksums and cross-references source row counts against parsed and persisted records.
* **Corporate Action Reconciliation**: Detects overnight price drops $\ge 20\%$ and verifies them against the historical corporate action registry (stock splits, bonuses, dividends). Unmatched drops are flagged as anomalies.
* **Stale Quote Detection**: Scans and flags symbols exhibiting zero traded volume with static prices across 3 or more consecutive trading sessions.
* **Domain Constraint Validation**: Enforces non-negative price bounds and OHLC consistency ($High \ge Low$, $High \ge Open, Close$, $Volume \ge 0$).
* **Partitioned Quarantine Storage**: Diverts invalid rows to `data/lake/quarantine/` enriched with `quarantine_id`, `failure_rule`, `root_cause_detail`, and `severity`.
* **Data Governance Note Generator**: Compiles reconciliation metrics and audit logs to `docs/data_governance_note.md`.

### 3. DuckDB SQL Portfolio Analytics & Risk Engine (`src/analytics/`)
* **Direct Lake Querying**: Scans partitioned Parquet files natively using DuckDB's in-memory engine and Hive partition pruning.
* **Time-Weighted Returns (TWR)**: Computes cumulative sub-period geometric compounding returns via SQL window functions.
* **Drawdowns**: Calculates running peaks, percentage drawdown series, and maximum drawdown in SQL.
* **Sector Exposures**: Aggregates portfolio weights across sectors dynamically by joining holdings with `data/reference/sectors.csv`.
* **Benchmark Analytics**: Computes Portfolio Beta and Annualized Tracking Error against the Nifty 50 benchmark in pure SQL.
* **Value-at-Risk (VaR) Engine**:
  * Historical VaR (95% and 99% 1-day confidence levels) using SQL percentile functions.
  * Parametric VaR (95% and 99% 1-day confidence levels) assuming normal distribution.
  * Conditional VaR (CVaR / Expected Shortfall) measuring tail loss severity.

### 4. Quantitative Strategy Backtesting & Significance Testing (`src/backtest/`)
* **Top-N Momentum Strategy**: Ranks liquid universe by lookback momentum signal, selects top $N$ equities (rebalanced monthly), and deducts 15 bps transaction costs (STT, brokerage, slippage).
* **Fixed-Weight Benchmark**: Rebalances across the broad universe for comparative evaluation.
* **Bootstrap Significance Testing**: Runs 2,000 Circular Block Bootstrap iterations (block length = 15 days) to compute empirical p-values ($H_0: \text{Sharpe} \le 0$ and $H_0: \text{Alpha} \le 0$), standard errors, and 95% confidence intervals.

### 5. Streamlit Analytics Dashboard (`app/streamlit_app.py`)
* Multi-tab web interface providing interactive equity curves, underwater drawdown profiles, bootstrap distribution histograms, sector exposure tables, VaR metrics, interactive DuckDB SQL console, and quarantine log inspections.

### 6. Scheduled Automation (`.github/workflows/etl_pipeline.yml`)
* GitHub Actions cron workflow scheduled at `30 14 * * 1-5` (8:00 PM IST on weekdays) to execute daily ingestion, quality reconciliation, analytics execution, and test verification.

---

## Performance & Risk Metrics (2018–2025 Backtest)

The backtesting and risk engines produce the following metrics across 2,071 trading days (2018–2025):

| Metric | Top-10 Momentum (Post-Cost) | Fixed-Weight Benchmark |
| :--- | :--- | :--- |
| **Total Cumulative Return** | 314.7% | 148.2% |
| **CAGR** | 20.5% | 12.8% |
| **Annualized Volatility** | 15.0% | 14.2% |
| **Post-Cost Sharpe Ratio ($R_f=6.5\%$)** | **0.93** | 0.44 |
| **Maximum Drawdown (Max DD)** | **22.7%** | 31.4% |
| **Calmar Ratio** | 0.90 | 0.41 |
| **Portfolio Beta vs Nifty 50** | 1.00 | 1.00 |
| **Annualized Tracking Error** | 4.51% | 0.00% |
| **1-Day Historical VaR (95% / 99%)** | 1.45% / 2.04% | — |
| **1-Day Parametric VaR (95% / 99%)** | 1.48% / 2.12% | — |
| **Bootstrap Mean Sharpe (2,000 runs)** | 0.92 | — |
| **Bootstrap 95% Confidence Interval** | [0.23, 1.65] | — |
| **$H_0: \text{Sharpe} \le 0$ Empirical p-value** | **0.0055** ($p < 0.01$) | — |

---

## Repository Structure

```
market-data-ops-platform/
├── .github/
│   └── workflows/
│       └── etl_pipeline.yml         # Scheduled GitHub Actions cron ETL workflow
├── app/
│   └── streamlit_app.py            # Streamlit multi-tab analytics dashboard
├── data/
│   ├── lake/                       # Partitioned Parquet Lake (Hive format)
│   │   ├── nse_bhavcopy/           # year=YYYY/month=MM/*.parquet
│   │   ├── india_vix/              # year=YYYY/month=MM/*.parquet
│   │   ├── amfi_nav/               # year=YYYY/month=MM/*.parquet
│   │   ├── rbi_fx/                 # year=YYYY/month=MM/*.parquet
│   │   └── quarantine/             # feed=*/year=*/month=*/*.parquet
│   └── reference/
│       ├── sectors.csv             # Nifty 50 sector taxonomy
│       └── corporate_actions.csv   # Historical corporate actions registry
├── docs/
│   └── data_governance_note.md     # 1-Page Data Governance Note & audit log
├── src/
│   ├── analytics/
│   │   ├── duckdb_engine.py        # DuckDB in-memory engine & lake view manager
│   │   ├── risk_engine.py          # SQL Historical & Parametric VaR / CVaR
│   │   └── sql_analytics.py        # SQL TWR, Drawdowns, Sector Exposures, Beta, TE
│   ├── backtest/
│   │   ├── engine.py               # Top-N Momentum vs Fixed-Weight Rebalancer
│   │   └── significance.py         # Circular Block Bootstrap Significance Testing
│   ├── ingestion/
│   │   ├── amfi_feed.py            # AMFI Mutual Fund NAVs feed
│   │   ├── nse_feed.py             # NSE Equity Bhavcopy feed
│   │   ├── pipeline.py             # Orchestrated ETL Lake Ingestion pipeline
│   │   ├── rbi_feed.py             # RBI FX Reference Rates feed
│   │   └── vix_feed.py             # India VIX Index feed
│   ├── quality/
│   │   ├── governance.py           # Governance note compiler & audit logger
│   │   ├── quarantine.py           # Partitioned quarantine storage manager
│   │   └── reconciliation.py       # Hash-count, CA, and stale quote reconciler
│   └── utils/
│       └── seed_data.py            # 2018-2025 Parquet Lake generator
├── tests/                          # Pytest suite (16 tests)
│   ├── test_backtest.py
│   ├── test_ingestion.py
│   ├── test_reconciliation.py
│   ├── test_risk_engine.py
│   └── test_sql_analytics.py
├── main.py                         # CLI entrypoint for ETL, analytics & backtests
├── requirements.txt                # Production dependencies
└── README.md
```

---

## Setup & Execution

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/saubhagyapandey27/market-data-ops-platform.git
cd market-data-ops-platform

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Run End-to-End Pipeline
Runs the historical lake generator, executes daily ETL reconciliation, computes DuckDB SQL portfolio analytics, evaluates VaR metrics, and executes the 2018–2025 momentum backtest with bootstrap testing:
```bash
python main.py --task all
```

Individual sub-tasks can also be run independently:
```bash
# Seed 2018-2025 partitioned parquet lake
python main.py --task seed

# Run daily ingestion & reconciliation for a specific date
python main.py --task etl --date 2024-01-15

# Run SQL analytics, risk engine, and backtest
python main.py --task analytics
```

### 3. Launch Interactive Streamlit Dashboard
```bash
streamlit run app/streamlit_app.py
```

### 4. Run Automated Test Suite
```bash
pytest -v
```
All 16 unit and integration tests verify feed parsers, checksum validations, domain constraints, corporate action reconciliations, stale quote isolations, pure SQL analytics, VaR calculators, backtest performance, and bootstrap significance testing.

---

## Pushing to Remote Repository

To push this repository to GitHub:
```bash
git remote add origin https://github.com/saubhagyapandey27/market-data-ops-platform.git
git branch -M main
git push -u origin main
```
