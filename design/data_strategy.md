# Stock Analysis Tool: Data Strategy & Tech Selection

## 1. Free Data Sources for Ingestion

For building a robust local data warehouse of company data, the following free sources are excellent starting points:

1. **Yahoo Finance (`yfinance` Python library)**
   - **Cost:** Free, no API key required.
   - **Strengths:** Excellent for historical market pricing, dividends, and stock splits. Also provides basic company profiles and financials (though financials can sometimes be brittle due to website scraping).
2. **Financial Modeling Prep (FMP)**
   - **Cost:** Generous free tier (up to 250 API requests per day).
   - **Strengths:** Extremely high quality fundamental data structure. Parses SEC filings directly into clean tabular data. Highly recommended for income statements, balance sheets, and cash flows.
3. **Alpha Vantage**
   - **Cost:** Free tier available (25 API requests per day).
   - **Strengths:** Great for technical indicators and global market data.
4. **FRED (Federal Reserve Economic Data)**
   - **Cost:** Free API key.
   - **Strengths:** Perfect for macroeconomic data (interest rates, unemployment, inflation) that you might want to overlay with your company analysis.

## 2. Data Source Schema & Historical Extensiveness

### Row-wise Richness (Historical Extensiveness)
- **Pricing:** `yfinance` offers daily, weekly, and monthly pricing spanning as far back as the ticker has existed (e.g., down to the 1920s or 1960s for older indices and companies). It maintains full split and dividend adjustments over decades.
- **Fundamentals:** FMP and Alpha Vantage generally provide between 5 to 10+ years of historical quarterly and annual financial statements on their free tiers.
  
### Column-wise Richness (Schema Design)
To support a robust analysis engine, your data schema should be highly modular. I recommend standardizing these core tables:

1. **`company_metadata`**: `ticker`, `company_name`, `sector`, `industry`, `market_cap`, `exchange`, `cik`.
2. **`daily_prices`**: `date`, `ticker`, `open`, `high`, `low`, `close`, `adj_close`, `volume`, `dividends_paid`, `stock_splits`.
3. **`income_statements`**: `date`, `ticker`, `period` (Q1/Q2/Annual), `revenue`, `cost_of_revenue`, `gross_profit`, `operating_expenses`, `net_income`, `eps`.
4. **`balance_sheets`**: `date`, `ticker`, `period`, `total_assets`, `total_liabilities`, `total_debt`, `total_equity`, `cash_and_equivalents`.
5. **`cash_flows`**: `date`, `ticker`, `period`, `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `free_cash_flow`.

## 3. Storage Design

The optimal storage solution must be freemium-based (ideally totally free), reliable, easily parsable for debugging, and natively compatible with the Python data ecosystem.

The winning local combination is **DuckDB + Parquet Files**.

### Why DuckDB over SQLite or PostgreSQL?
- **Analytical Performance:** Financial data is OLAP (analytical) not OLTP (transactional). You rarely update single rows; instead, you query massive columns of numbers over long date ranges (e.g., "average volume over 5 years"). DuckDB is a columnar database designed specifically for analytics, running orders of magnitude faster than SQLite.
- **Local & Free:** It runs entirely in-process in Python, requiring zero server configuration. No paid cloud DBs to manage.
- **Python Synergy:** Native integration with Pandas, Polars, and PyArrow. You can literally write SQL queries that execute directly against a Python DataFrame without copying data in memory.
- **Debuggability:** DuckDB allows you to query directories of raw [Apache Parquet](https://parquet.apache.org/) files on disk as if they were tables.

### High-Level Data Flow
1. **Ingestion (Python/Requests):** Scripts fetch raw data from `yfinance`/FMP APIs.
2. **Transformation (Pandas/Polars):** Scripts parse the JSON into DataFrames, clean it, handle missing values, and cast precise datatypes (dates, floats).
3. **Storage (Disk):** The transformed tables are saved locally as `.parquet` files (e.g., `data/daily_prices/ticker=AAPL/data.parquet`). Parquet retains schema types natively and is highly compressed.
4. **Consumption (Python + DuckDB):** An internal Python query class accepts arguments or SQL strings, spins up a DuckDB connection, performs lightning-fast reads on the Parquet directory, and returns a rich DataFrame for the end user to analyze.
