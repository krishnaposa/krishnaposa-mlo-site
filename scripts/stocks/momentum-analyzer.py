import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime

# --- SETTINGS ---
PORTFOLIO_FILE = "momentum-analyzer.json"
RS_ENTRY_THRESHOLD = 90
RS_EXIT_THRESHOLD = 70
TRAILING_STOP_PCT = 0.15
PORTFOLIO_SIZE = 20

# --- DATA PERSISTENCE ---
def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=4)

# --- CORE LOGIC ---
def get_rs_ratings(tickers):
    """Calculates percentile RS compared to peers over 1 year."""
    if not tickers: return pd.Series()
    # Adding SPY to the mix to provide a market baseline
    data = yf.download(tickers + ["SPY"], period="1y", interval="1d", progress=False)['Close']
    print(f"1 year data: {data}")
    returns = data.pct_change(fill_method=None).iloc[-1] # Simple 1yr return comparison
    returns = (data.iloc[-1] / data.iloc[0]) - 1
    return returns.rank(pct=True) * 100

def run_daily_update():
    portfolio = load_portfolio()['positions']
    
    if not portfolio:
        print("Portfolio is empty. Run a scan on Finviz to find Mid-Cap 52-Week High candidates.")
        return
    tickers = list(portfolio.keys())

    # Download latest data
    data = yf.download(tickers, period="5d", interval="1d", progress=False)['Close']
    print(f"5 days data: {data}")
    rs_ratings = get_rs_ratings(tickers)
    print(f"rs_ratings: {rs_ratings}")

    updates_made = False
    to_delete = []

    for ticker in tickers:
        current_price = float(data[ticker].iloc[-1])
        
        # Update Highest Price Seen (for Trailing Stop)
        if current_price > portfolio[ticker]['high_seen']:
            portfolio[ticker]['high_seen'] = current_price
            updates_made = True
            print(f"NEW HIGH: {ticker} hit ${current_price:.2f}. Stop moved to ${current_price * (1-TRAILING_STOP_PCT):.2f}")

        # EXIT CHECK 1: Trailing Stop
        stop_price = portfolio[ticker]['high_seen'] * (1 - TRAILING_STOP_PCT)
        if current_price <= stop_price:
            print(f"!!! SELL {ticker} !!! Trailing stop hit at ${current_price:.2f}")
            to_delete.append(ticker)
            continue

        # EXIT CHECK 2: RS Decay
        if rs_ratings[ticker] < RS_EXIT_THRESHOLD:
            print(f"!!! SELL {ticker} !!! RS Rating ({rs_ratings[ticker]:.1f}) dropped below {RS_EXIT_THRESHOLD}")
            to_delete.append(ticker)

    # Clean up portfolio
    for ticker in to_delete:
        del portfolio[ticker]
        updates_made = True

    print("Setting updates_made to False")
    updates_made = False

    if updates_made:
        save_portfolio(portfolio)
    else:
        print(f"Daily Check Complete: {datetime.now().strftime('%Y-%m-%d')}. No actions required.")

if __name__ == "__main__":
    run_daily_update()