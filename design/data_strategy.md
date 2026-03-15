# Stock Analysis Tool: Data Strategy & Tech Selection

## TL;DR: The Core Design Decisions
1.  **Data Sources:** `yfinance` (historical pricing/splits/dividends) and Financial Modeling Prep / Alpha Vantage (fundamental statements).
2.  **Analytical Storage (The Data):** [DuckDB](https://duckdb.org/) querying local partitioned [Apache Parquet](https://parquet.apache.org/) files. Chosen because financial data is purely columnar time-series (OLAP), making DuckDB infinitely faster than SQLite or Postgres for analysis.
3.  **State Management (The Metadata):** A local SQLite database (`metadata.db`). Chosen because tracking ingestion status and data versions requires transactional, row-level updates (OLTP) which Parquet cannot do.
4.  **Versioning Strategy:** **Integer Versioning + Unix Checkpoints**. Because corporate actions (splits) retroactively invalidate decades of historical prices, we cannot blindly append new daily data. Every dataset is stamped with a `data_version` (incremented on full invalidations/re-pulls) and a `checkpoint_id` (incremented on daily appends) to ensure downstream ML models never mix pre/post-split data.

---

## 1. Data Sources for Ingestion

-   **Yahoo Finance (`yfinance`)**
    -   **Cost:** Free, no API key required.
    -   **Usage:** Daily OHLCV market pricing, dividends, and stock splits. Fully adjusted for historical splits over decades.
-   **Financial Modeling Prep (FMP)**
    -   **Cost:** Generous free tier (250 req/day).
    -   **Usage:** High-quality fundamental data mapped directly from SEC 10-K/10-Q filings (Income Statements, Balance Sheets, Cash Flows).

## 2. Analytical Storage Architecture

The heavy lifting of the pipeline relies on the **DuckDB + Parquet** combination.

### High-Level Data Flow
1.  **Ingestion:** Python scripts fetch JSON/DataFrames from `yfinance`/FMP APIs.
2.  **Transformation:** `pandas`/`polars` clean the data and cast strict datatypes (Dates, BIGINTs).
3.  **Storage:** Saved locally as highly compressed `.parquet` files (e.g., `data/daily_prices/ticker=AAPL/v=3/...`).
4.  **Consumption:** Python spins up an in-memory `duckdb` connection to run lightning-fast SQL aggregations directly against the Parquet directory, returning DataFrames to the user.

### Analytical Schema Design
Every row of data written to disk is immutably stamped to guarantee downstream traceability:
-   `data_version` (BIGINT): The integer version denoting the foundational state.
-   `checkpoint_id` (BIGINT): The exact UNIX timestamp of ingestion.

**1. `company_metadata` (Dimension Table)**
-   `ticker` (VARCHAR, Primary Partition Key), `company_name` (VARCHAR), `sector` (VARCHAR), `industry` (VARCHAR), `market_cap` (BIGINT), `exchange` (VARCHAR), `cik` (VARCHAR)

**2. `daily_prices` (Fact Table)**
-   `date` (DATE, Primary Sort Key), `ticker` (VARCHAR, Primary Partition Key), `open`, `high`, `low`, `close` (DOUBLE), `adj_close` (DOUBLE), `volume` (BIGINT), `dividends_paid` (DOUBLE), `stock_splits` (DOUBLE)

**3. `income_statements` (Fact Table)**
-   `date` (DATE), `ticker` (VARCHAR), `period` (VARCHAR, e.g., 'Q1'), `revenue`, `cost_of_revenue`, `gross_profit`, `operating_expenses`, `net_income` (BIGINT), `eps` (DOUBLE)

## 3. Metadata & State Management (SQLite)

Because financial data updates across multiple dimensions (daily appends vs. retroactive split invalidations vs. prior-quarter earnings restatements), we must track the ingestion state in a transactional database (`~/.stock_analysis/metadata.db`).

### Versioning Scheme Decision
We use **Monotonically Increasing Integers (`data_version`) + Unix Timestamps (`checkpoint_timestamp`)**.
*Why not Semantic Versioning or Timestamps-as-versions?* Integers are the fastest data type for SQL joins. They cleanly separate the concept of a "Fundamental State Change" (integer bump) from a mere "daily update append" (timestamp bump), providing a sane, numeric lock for downstream machine learning models.

### Table 1: `dataset_state` (Current State)
| ticker | dataset_name      | data_version | checkpoint_timestamp | last_available_record | status  |
|--------|-------------------|--------------|----------------------|-----------------------|---------|
| AAPL   | daily_prices      | 2            | 1710531800           | 2026-03-14            | SUCCESS |

#### Ingestion Logic Flow
1.  **Fetch Delta:** Query SQLite for `AAPL daily_prices`. It sees `last_available_record = 2026-03-14`. Ask `yfinance` for the delta (the last 5 days).
2.  **Mutation Detection:** Did a stock split occur (`stock_splits > 0`) in those 5 days?
    -   **Scenario A (Incremental Append):** No splits. Append the 5-day delta to the existing `v=2` Parquet file. Update SQLite: `checkpoint_timestamp = NOW()`, `last_available_record = 2026-03-19`.
    -   **Scenario B (History Invalidation):** A split *did* occur. The historical `adj_close` prices on disk are wrong. Discard the file. Fetch `period="max"` from `yfinance`. Increment `data_version = 3`, update `checkpoint_timestamp = NOW()`. Save to a *new* partitioned directory: `data/.../v=3/...`.

### Table 2: `dataset_changelog` (Immutable Audit Trail)
To allow researchers to answer *"Why did my model break on AAPL v3?"*, every run logs an event.

| log_id | ticker | dataset_name | data_version | checkpoint_timestamp | event_type   | reason                                    |
|--------|--------|--------------|--------------|----------------------|--------------|-------------------------------------------|
| 2      | AAPL   | daily_prices | 1            | 1600086400           | APPEND       | Daily run                                 |
| 3      | AAPL   | daily_prices | 2            | 1710531800           | VERSION_BUMP | Stock split detected (ratio 4:1)          |

*(Schema: `log_id` SERIAL PK, `ticker` TEXT, `dataset_name` TEXT, `data_version` INTEGER, `checkpoint_timestamp` INTEGER, `event_type` TEXT, `reason` TEXT)*
