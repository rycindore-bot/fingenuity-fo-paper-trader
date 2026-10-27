# F&O Trading Copilot — Windows Starter

A beginner-friendly local Streamlit app for NIFTY and BANKNIFTY options paper trading.

## Safety scope

- Paper trading only. This project intentionally does not call Kite order-placement, order-modification, or order-cancellation endpoints.
- Mock mode works without API credentials and uses illustrative synthetic prices.
- Kite mode is a market-data adapter only. It reads spot quotes and the NFO instrument master. It does **not** fetch candle history in this starter version, so it is not suitable for live signal generation yet.
- The app does not automatically trigger stop-losses. The user manually closes paper trades in the interface.
- Risk controls are guardrails, not guarantees of maximum loss.

## Requirements

- Windows 10/11
- Python 3.10 or newer (64-bit recommended)
- Internet access to install Python packages
- Optional: an active Zerodha Kite Connect subscription and API credentials for market-data access

## Install and run

1. Install Python from https://www.python.org/downloads/windows/ . During installation, select **Add Python to PATH**.
2. Extract this ZIP to a normal folder, e.g. `C:\\F&O Trading Agent`.
3. Double-click `run_app.bat`. The first run creates a virtual environment and installs the required packages.
4. When Streamlit starts, open the local URL shown in the terminal (usually http://localhost:8501).
5. Choose **Mock data (works offline)** to test the dashboard. Mock prices are fictional and not trading signals.

If `py` is not recognized, install Python again and enable the Python Launcher, or open Command Prompt in this folder and use:
`python -m venv .venv`

## Optional Kite Connect market data

1. Create an app in the official Kite Connect developer portal: https://developers.kite.trade/
2. Read the official API docs: https://kite.trade/docs/connect/v3/
3. Complete Zerodha's documented login flow to obtain an access token.
4. In the app sidebar choose **Kite Connect (market data only)** and enter your API key and access token.
5. This starter uses `kite.quote()` and `kite.instruments("NFO")`. It deliberately does not store credentials in a file.
6. The adapter currently fetches only a spot snapshot and instrument metadata. To support real strategy evaluation, add a separately tested historical-candle/WebSocket feed and robust timestamp/session handling.

Do not paste API secrets, access tokens, passwords or TOTP values into chat, source control or shared files. Access tokens expire; use the official Zerodha authentication process.

## Paper trading

- Open the **Paper trade** tab.
- Enter a current option symbol and current lot size from the current instrument master (the lot size is not hard-coded).
- Enter entry, stop and target premiums.
- The app checks:
  - stop below entry and target above entry for long options;
  - planned risk including the configured cost estimate;
  - minimum 2:1 estimated reward/risk;
  - premium outlay against configured paper capital;
  - daily risk and trade-count limits.
- Close paper trades manually to record the exit price and total costs.
- Export the journal from the **Journal** tab as CSV.

The default estimated cost is only a placeholder for testing. Replace it with a realistic estimate for your brokerage plan and applicable charges. The app does not automatically obtain the option's live bid/ask or calculate a marketable execution price.

## Files created at runtime

- `trading_journal.db` — local SQLite database containing settings and paper trades.
- `fo_trading_journal.csv` — created when you download the journal.

Back up these files if you need to preserve the journal. They may contain sensitive trading records.

## Important limitations in this first version

- No broker order placement is implemented.
- No automated entry or stop-loss execution.
- No true tick-by-tick backtest or walk-forward validation.
- Kite mode does not yet load historical candles; the strategy watchlist should be treated as unavailable in that mode.
- Mock data is synthetic, deterministic and for testing the UI only.
- The configured daily lock is a software guardrail. It cannot protect against a system crash or make a real account safe because live orders are not enabled in this app.
