import yfinance as yf
import pandas as pd
import duckdb
import os
import shutil

# 1. Setup the environment
data_dir = "data/daily_prices/ticker=AAPL"
if os.path.exists("data"):
    shutil.rmtree("data")
os.makedirs(data_dir, exist_ok=True)

# 2. Ingestion (using yfinance)
print("Downloading Apple daily price data via yfinance...")

# --- yfinance API EXPLANATION ---
# yfinance wraps the Yahoo Finance API. 
# Documentation for `yf.Ticker`: https://github.com/ranaroussi/yfinance?tab=readme-ov-file#the-ticker-module
ticker = yf.Ticker("AAPL")

# Documentation for `.history()` arguments: https://github.com/ranaroussi/yfinance?tab=readme-ov-file#fetching-data
# The `period` argument accepts very specific magic strings defined by the underlying Yahoo API:
# Valid periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
# The `interval` argument (defaults to "1d") also accepts magic strings:
# Valid intervals: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
df = ticker.history(period="10y") # Get 10 years of daily data

# 3. Transformation 
print("Cleaning data and formatting for parquet storage...")

# --- SCHEMA EXPLANATION ---
# Q: How do we know the yfinance DataFrame schema?
# A: `yf.Ticker.history()` is an industry-standard method that hooks into the Yahoo Finance API.
# It reliably returns a Pandas DataFrame with a very specific, strict schema:
#   - Index: 'Date' (DatetimeIndex, localized to the stock exchange's timezone, e.g. EST)
#   - Columns: 'Open', 'High', 'Low', 'Close', 'Volume', 'Dividends', 'Stock Splits'
# All column names are Title Case and strictly ordered as OHLCV. 
# We need to transform this schema to be database-friendly (lowercase, no spaces, standardized dates).

# Step 1: yfinance puts the Date in the index. Parquet/DuckDB prefer explicit columns.
df = df.reset_index()

# Step 2: The Date column is a timezone-aware pandas datetime (e.g. 2024-03-14 00:00:00-04:00).
# For daily price data, timezones cause massive headaches in SQL queries. 
# We strip the time and timezone down to a naive Python `datetime.date` object.
df['Date'] = pd.to_datetime(df['Date']).dt.date

# Step 3: Add the ticker column explicitly. 
# When DuckDB queries the massive `/ticker=AAPL/` partitioned directory, it will automatically
# infer the `ticker` column from the directory name, but adding it explicitly here guarantees safety.
df['Ticker'] = 'AAPL'

# Step 4: Reorder the columns to place primary identifiers (date, ticker) first.
df = df[['Date', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume', 'Dividends', 'Stock Splits']]

# Step 5: Convert the Yahoo Finance Title Case & Space schema into a standard snake_case SQL schema.
df.rename(columns={
    'Date': 'date', 'Ticker': 'ticker', 'Open': 'open', 'High': 'high', 
    'Low': 'low', 'Close': 'close', 'Volume': 'volume', 
    'Dividends': 'dividends', 'Stock Splits': 'stock_splits'
}, inplace=True)

# 4. Storage (Parquet)
parquet_path = f"{data_dir}/data.parquet"
print(f"Saving to Parquet at: {parquet_path}")
df.to_parquet(parquet_path, engine='pyarrow', compression='snappy')
print(f"Saved {len(df)} rows of data.")

# 5. Consumption (DuckDB)
print("\n--- DuckDB Test Query ---")
print("Initializing DuckDB in-memory engine and querying the raw parquet file.")
con = duckdb.connect(database=':memory:')

# Query directly off the disk without loading the whole file into pandas again
query = """
    SELECT 
        YEAR(date) as year,
        ROUND(AVG(close), 2) as avg_closing_price,
        MAX(high) as yearly_high,
        SUM(volume) as total_volume
    FROM read_parquet('data/daily_prices/**/*.parquet')
    GROUP BY YEAR(date)
    ORDER BY year DESC
    LIMIT 5;
"""

result_df = con.execute(query).df()
print(result_df)
print("\nPrototype pipeline completed successfully!")
