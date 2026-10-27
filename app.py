import os
import math
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from kiteconnect import KiteConnect
except Exception:
    KiteConnect = None

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "trading_journal.db"
STARTING_CAPITAL = 10000.0
RISK_PER_TRADE = 100.0
DAILY_LOSS_LIMIT = 200.0
MAX_TRADES_PER_DAY = 2
ESTIMATED_ROUND_TRIP_COST_PER_LOT = 40.0  # editable estimate, not a broker quote

st.set_page_config(page_title="F&O Trading Copilot", page_icon="📈", layout="wide")

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                underlying TEXT NOT NULL,
                option_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                expiry TEXT,
                strike REAL,
                lot_size INTEGER NOT NULL,
                lots INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                exit_price REAL,
                status TEXT NOT NULL,
                setup TEXT NOT NULL,
                planned_risk REAL NOT NULL,
                gross_pnl REAL,
                estimated_costs REAL,
                net_pnl REAL,
                notes TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('starting_capital','10000')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('risk_per_trade','100')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('daily_loss_limit','200')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('max_trades_per_day','2')")

def get_settings():
    with db() as con:
        rows = con.execute("SELECT key,value FROM settings").fetchall()
    return {r["key"]: float(r["value"]) for r in rows}

def save_settings(capital, risk, daily_loss, max_trades):
    with db() as con:
        for key, value in {
            "starting_capital": capital,
            "risk_per_trade": risk,
            "daily_loss_limit": daily_loss,
            "max_trades_per_day": max_trades,
        }.items():
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))

def load_trades():
    with db() as con:
        rows = con.execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def current_day_trades():
    with db() as con:
        rows = con.execute("SELECT * FROM trades WHERE trade_date=? ORDER BY id DESC",
                           (date.today().isoformat(),)).fetchall()
    return [dict(r) for r in rows]

def insert_trade(t):
    with db() as con:
        con.execute("""
            INSERT INTO trades (
                created_at, trade_date, mode, underlying, option_type, symbol, expiry,
                strike, lot_size, lots, quantity, entry_price, stop_price, target_price,
                exit_price, status, setup, planned_risk, gross_pnl, estimated_costs,
                net_pnl, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec="seconds"), date.today().isoformat(), t["mode"],
            t["underlying"], t["option_type"], t["symbol"], t.get("expiry",""),
            t.get("strike"), t["lot_size"], t["lots"], t["quantity"], t["entry_price"],
            t["stop_price"], t["target_price"], None, "OPEN", t["setup"], t["planned_risk"],
            None, None, None, t.get("notes","")
        ))

def close_trade(trade_id, exit_price, costs):
    with db() as con:
        row = con.execute("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,)).fetchone()
        if not row:
            raise ValueError("Open trade not found.")
        gross = (float(exit_price) - float(row["entry_price"])) * int(row["quantity"])
        net = gross - float(costs)
        con.execute("""
            UPDATE trades SET exit_price=?, status='CLOSED', gross_pnl=?, estimated_costs=?,
            net_pnl=? WHERE id=?
        """, (float(exit_price), gross, float(costs), net, trade_id))

def risk_status(settings):
    rows = current_day_trades()
    closed = [r for r in rows if r["status"] == "CLOSED"]
    realised = sum(float(r["net_pnl"] or 0) for r in closed)
    open_risk = sum(float(r["planned_risk"] or 0) for r in rows if r["status"] == "OPEN")
    accepted = len(rows)
    loss_used = max(0.0, -realised) + open_risk
    locked = (loss_used >= settings["daily_loss_limit"] or
              accepted >= settings["max_trades_per_day"])
    return rows, realised, open_risk, accepted, loss_used, locked

def mock_market_data():
    # Deterministic illustrative market data; NOT live market prices or a recommendation.
    now = datetime.now().replace(second=0, microsecond=0)
    data = []
    for underlying, base, drift in [("NIFTY", 25000.0, 0.9), ("BANKNIFTY", 54000.0, 1.4)]:
        closes = []
        price = base
        for i in range(40):
            change = math.sin(i * 0.72) * 7 + drift + math.cos(i * 0.31) * 2
            price += change
            closes.append(price)
        for i, close in enumerate(closes):
            op = closes[i-1] if i else close - 2
            high = max(op, close) + 4 + (i % 3)
            low = min(op, close) - 4 - (i % 2)
            data.append({
                "underlying": underlying,
                "time": (now - timedelta(minutes=5*(39-i))).strftime("%H:%M"),
                "open": round(op, 2), "high": round(high, 2),
                "low": round(low, 2), "close": round(close, 2),
                "volume": 1000 + i * 37 + (i % 5) * 100,
                "vwap": round(sum(closes[:i+1])/(i+1), 2),
            })
    return pd.DataFrame(data)

def kite_market_data(api_key, access_token, selected_underlyings):
    if KiteConnect is None:
        raise RuntimeError("kiteconnect package is not installed. Run: pip install -r requirements.txt")
    if not api_key or not access_token:
        raise RuntimeError("Enter your Kite API key and access token in the sidebar.")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    instruments = kite.instruments("NFO")
    inst = pd.DataFrame(instruments)
    if inst.empty:
        raise RuntimeError("Kite returned no NFO instruments.")
    now = datetime.now()
    rows = []
    # For this beginner version, fetch the latest available completed 5-minute candles
    # for each underlying index using the NSE index instruments when present in the NFO master is not reliable.
    # Use Kite's quote endpoint for index spot values, and option instruments for contract metadata.
    quote_keys = ["NSE:NIFTY 50", "NSE:NIFTY BANK"]
    quotes = kite.quote(quote_keys)
    spot_map = {}
    for qkey in quote_keys:
        q = quotes.get(qkey, {})
        spot_map[qkey] = q.get("last_price")
    for underlying in selected_underlyings:
        qkey = "NSE:NIFTY 50" if underlying == "NIFTY" else "NSE:NIFTY BANK"
        spot = spot_map.get(qkey)
        if not spot:
            continue
        rows.append({
            "underlying": underlying, "time": now.strftime("%H:%M"),
            "open": spot, "high": spot, "low": spot, "close": spot,
            "volume": 0, "vwap": spot
        })
    return pd.DataFrame(rows), inst

def build_signals(market_df):
    signals = []
    if market_df is None or market_df.empty:
        return pd.DataFrame()
    for underlying, group in market_df.groupby("underlying"):
        group = group.sort_values("time")
        if len(group) < 20:
            signals.append({
                "Underlying": underlying, "Signal": "WAIT",
                "Reason": "Not enough candle history to evaluate the setup.",
                "Reference price": float(group.iloc[-1]["close"])
            })
            continue
        recent = group.iloc[-1]
        prior = group.iloc[-2]
        avg20 = group["close"].tail(20).mean()
        above_vwap = float(recent["close"]) > float(recent.get("vwap", avg20))
        bullish = float(recent["close"]) > float(prior["high"]) and above_vwap and float(recent["close"]) > avg20
        bearish = float(recent["close"]) < float(prior["low"]) and not above_vwap and float(recent["close"]) < avg20
        if bullish:
            signal, reason = "POTENTIAL CE SETUP", "Close above previous candle high, VWAP and 20-candle mean."
        elif bearish:
            signal, reason = "POTENTIAL PE SETUP", "Close below previous candle low, VWAP and 20-candle mean."
        else:
            signal, reason = "WAIT", "No complete breakout-and-trend condition."
        signals.append({"Underlying": underlying, "Signal": signal, "Reason": reason,
                        "Reference price": round(float(recent["close"]), 2)})
    return pd.DataFrame(signals)

init_db()
settings = get_settings()

st.title("📈 F&O Trading Copilot")
st.caption("Local paper-trading simulator • NIFTY & BANKNIFTY • No live order placement")

with st.sidebar:
    st.header("Configuration")
    data_mode = st.radio("Market data mode", ["Mock data (works offline)", "Kite Connect (market data only)"])
    st.caption("Mock prices are illustrative and must never be treated as live signals.")
    if data_mode == "Kite Connect (market data only)":
        st.warning("This adapter reads quotes and contract metadata only. It does not fetch historical candles or place orders.")
        api_key = st.text_input("Kite API key", type="password")
        access_token = st.text_input("Kite access token", type="password")
    else:
        api_key, access_token = "", ""
    st.divider()
    st.subheader("Risk settings")
    capital = st.number_input("Paper starting capital (₹)", min_value=1000.0, max_value=10000000.0,
                              value=float(settings["starting_capital"]), step=1000.0)
    risk_limit = st.number_input("Risk per trade (₹)", min_value=10.0, max_value=10000.0,
                                 value=float(settings["risk_per_trade"]), step=10.0)
    daily_limit = st.number_input("Daily loss lock (₹)", min_value=10.0, max_value=100000.0,
                                  value=float(settings["daily_loss_limit"]), step=10.0)
    max_trades = st.number_input("Max accepted trades/day", min_value=1, max_value=20,
                                 value=int(settings["max_trades_per_day"]), step=1)
    if st.button("Save risk settings", use_container_width=True):
        save_settings(capital, risk_limit, daily_limit, max_trades)
        st.success("Risk settings saved.")
        st.rerun()

tab_dash, tab_trade, tab_journal, tab_setup = st.tabs(["Dashboard", "Paper trade", "Journal", "Setup & safety"])

with tab_dash:
    st.subheader("Market overview")
    selected = st.multiselect("Indices to monitor", ["NIFTY", "BANKNIFTY"], default=["NIFTY", "BANKNIFTY"])
    if st.button("Refresh market data", type="primary"):
        st.session_state["refresh_market"] = True
    if data_mode == "Mock data (works offline)":
        market_df = mock_market_data()
        instrument_df = None
    else:
        try:
            market_df, instrument_df = kite_market_data(api_key, access_token, selected)
            st.info("Kite quote mode currently shows spot snapshots only. Signals require candles; therefore this adapter will safely return WAIT until candle history is connected.")
        except Exception as e:
            market_df, instrument_df = pd.DataFrame(), None
            st.error(f"Market-data connection error: {e}")
    if selected:
        market_df = market_df[market_df["underlying"].isin(selected)] if not market_df.empty else market_df
    if not market_df.empty:
        for underlying in selected:
            part = market_df[market_df["underlying"] == underlying]
            if not part.empty:
                last = part.iloc[-1]
                st.metric(f"{underlying} reference price", f"₹{float(last['close']):,.2f}")
        if data_mode.startswith("Mock"):
            st.markdown("**Illustrative mock candles (5-minute intervals)**")
            chart_df = market_df.pivot(index="time", columns="underlying", values="close")
            st.line_chart(chart_df)
        signals = build_signals(market_df)
        st.subheader("Strategy watchlist")
        st.dataframe(signals, use_container_width=True, hide_index=True)
    else:
        st.info("No market data available. In Kite mode, verify API access and try again.")
    rows, realised, open_risk, accepted, loss_used, locked = risk_status(settings)
    a,b,c,d = st.columns(4)
    a.metric("Today's realised net P&L", f"₹{realised:,.2f}")
    b.metric("Open planned risk", f"₹{open_risk:,.2f}")
    c.metric("Trades accepted today", f"{accepted}/{int(settings['max_trades_per_day'])}")
    d.metric("Risk lock", "LOCKED" if locked else "OPEN")
    if locked:
        st.error("Risk lock active. New paper trades are blocked for today.")
    else:
        st.success("Risk gate is open, subject to the individual trade checks.")

with tab_trade:
    st.subheader("Create a simulated options trade")
    st.caption("Use prices from your own verified quote feed. Mock mode is for software testing only.")
    rows, realised, open_risk, accepted, loss_used, locked = risk_status(settings)
    if locked:
        st.error("Risk gate is locked for today. You cannot open another trade.")
    with st.form("paper_trade_form"):
        col1, col2, col3 = st.columns(3)
        underlying = col1.selectbox("Underlying", ["NIFTY", "BANKNIFTY"])
        option_type = col2.selectbox("Option type", ["CE", "PE"])
        setup = col3.selectbox("Setup", ["Trend pullback", "Opening-range breakout", "Manual paper test"])
        symbol = st.text_input("Option symbol", placeholder="Enter current contract symbol")
        expiry = st.text_input("Expiry (YYYY-MM-DD)", placeholder="Optional")
        strike = st.number_input("Strike price", min_value=0.0, step=50.0, value=0.0)
        c1,c2,c3 = st.columns(3)
        entry = c1.number_input("Entry premium (₹)", min_value=0.05, value=100.0, step=0.05)
        stop = c2.number_input("Stop premium (₹)", min_value=0.05, value=95.0, step=0.05)
        target = c3.number_input("Target premium (₹)", min_value=0.05, value=110.0, step=0.05)
        c4,c5,c6 = st.columns(3)
        lot_size = c4.number_input("Current lot size", min_value=1, max_value=100000, value=1, step=1,
                                   help="Enter the lot size from the current Kite instrument master. It is deliberately not hard-coded.")
        lots = c5.number_input("Number of lots", min_value=1, max_value=100, value=1, step=1)
        estimated_costs = c6.number_input("Estimated round-trip costs per lot (₹)", min_value=0.0,
                                          value=ESTIMATED_ROUND_TRIP_COST_PER_LOT, step=5.0)
        notes = st.text_input("Notes (optional)")
        submit = st.form_submit_button("Validate and open paper trade", type="primary", disabled=locked)
    if submit:
        errors = []
        if not symbol.strip():
            errors.append("Enter the current option symbol.")
        if stop >= entry:
            errors.append("For this long-option simulator, stop premium must be below entry premium.")
        if target <= entry:
            errors.append("Target premium must be above entry premium.")
        if not (stop < entry < target):
            errors.append("Price levels are inconsistent.")
        quantity = int(lot_size) * int(lots)
        planned_risk = (float(entry) - float(stop)) * quantity + float(estimated_costs) * int(lots)
        planned_reward = (float(target) - float(entry)) * quantity - float(estimated_costs) * int(lots)
        if planned_risk > settings["risk_per_trade"]:
            errors.append(f"Risk check failed: planned risk ₹{planned_risk:.2f} exceeds ₹{settings['risk_per_trade']:.2f}.")
        if planned_reward < 2 * planned_risk:
            errors.append("Reward-to-risk check failed: estimated net reward must be at least 2x planned risk.")
        if quantity * float(entry) > settings["starting_capital"]:
            errors.append("Premium outlay exceeds the configured paper capital.")
        rows, realised, open_risk, accepted, loss_used, locked = risk_status(settings)
        if locked or accepted >= settings["max_trades_per_day"]:
            errors.append("Daily trade limit / risk lock has been reached.")
        if loss_used + planned_risk > settings["daily_loss_limit"]:
            errors.append("This trade would exceed the daily loss budget after adding open risk.")
        if errors:
            for err in errors:
                st.error(err)
        else:
            insert_trade({
                "mode": "PAPER", "underlying": underlying, "option_type": option_type,
                "symbol": symbol.strip(), "expiry": expiry.strip(), "strike": float(strike) or None,
                "lot_size": int(lot_size), "lots": int(lots), "quantity": quantity,
                "entry_price": float(entry), "stop_price": float(stop), "target_price": float(target),
                "setup": setup, "planned_risk": planned_risk, "notes": notes
            })
            st.success(f"Paper trade opened. Quantity: {quantity}; planned risk: ₹{planned_risk:.2f}.")
            st.rerun()

    st.divider()
    st.subheader("Close an open paper trade")
    trades = load_trades()
    if not trades.empty:
        open_trades = trades[trades["status"] == "OPEN"]
    else:
        open_trades = pd.DataFrame()
    if open_trades.empty:
        st.info("No open paper trades.")
    else:
        options = {f"#{int(r.id)} {r.symbol} | {r.underlying} {r.option_type} | qty {int(r.quantity)}": int(r.id)
                   for r in open_trades.itertuples()}
        selected_trade = st.selectbox("Select open trade", list(options.keys()))
        x1,x2 = st.columns(2)
        exit_price = x1.number_input("Exit premium (₹)", min_value=0.05, value=100.0, step=0.05, key="exit_price")
        exit_costs = x2.number_input("Actual/estimated total costs (₹)", min_value=0.0, value=40.0, step=5.0, key="exit_costs")
        if st.button("Close selected paper trade"):
            close_trade(options[selected_trade], exit_price, exit_costs)
            st.success("Paper trade closed and journal updated.")
            st.rerun()

with tab_journal:
    st.subheader("Trade journal")
    journal = load_trades()
    if journal.empty:
        st.info("No trades recorded yet. Create a paper trade to populate the journal.")
    else:
        display_cols = ["id","created_at","mode","underlying","option_type","symbol","expiry","strike",
                        "lot_size","lots","quantity","entry_price","stop_price","target_price","exit_price",
                        "status","setup","planned_risk","gross_pnl","estimated_costs","net_pnl","notes"]
        st.dataframe(journal[display_cols], use_container_width=True, hide_index=True)
        closed = journal[journal["status"] == "CLOSED"].copy()
        if not closed.empty:
            net = pd.to_numeric(closed["net_pnl"], errors="coerce").fillna(0)
            wins = int((net > 0).sum())
            total = len(closed)
            win_rate = wins / total * 100
            gross_profit = float(net[net > 0].sum())
            gross_loss = abs(float(net[net < 0].sum()))
            profit_factor = gross_profit / gross_loss if gross_loss else None
            m1,m2,m3 = st.columns(3)
            m1.metric("Closed trades", total)
            m2.metric("Win rate", f"{win_rate:.1f}%")
            m3.metric("Net P&L", f"₹{net.sum():,.2f}")
            st.write("Profit factor:", f"{profit_factor:.2f}" if profit_factor is not None else "Not meaningful yet")
        csv = journal.to_csv(index=False).encode("utf-8")
        st.download_button("Download journal as CSV", data=csv, file_name="fo_trading_journal.csv", mime="text/csv")

with tab_setup:
    st.subheader("Strategy and safety notes")
    st.markdown("""
**Strategy candidate filters (not a profitability claim):**
- Trend-pullback candidate: 5-minute trend context, price relative to VWAP, then confirmation candle.
- Opening-range breakout candidate: define first 15-minute range, wait for a close beyond the range, and reject extended or low-liquidity moves.
- The current mock chart is illustrative. The first version does not claim to generate trade-ready live signals from the Kite quote adapter.
- A setup is not an order. A human must review any candidate before a simulated trade is created.

**Safety architecture:**
- This app intentionally has no code to place, modify, or cancel broker orders.
- Kite mode only requests quotes and the NFO instrument master.
- Paper orders and the journal are stored locally in `trading_journal.db`.
- Daily risk lock blocks new entries based on realised losses plus open planned risk, and the trade-count cap.
- Stop-loss execution is not automated in this starter version. You must close a simulated trade manually at a price you choose.
- Risk limits are guardrails, not guarantees. Gaps, slippage, option spreads and costs can cause actual live losses to exceed planned amounts.
""")
    st.subheader("Kite connection checklist")
    st.markdown("""
1. Create a Kite Connect app and obtain your API key.
2. Complete Kite's login flow to obtain an access token. Tokens expire; follow Zerodha's official authentication documentation.
3. Enter the API key and access token in the sidebar only on your own trusted PC.
4. Never share tokens or screenshots containing secrets.
5. Confirm market-data subscription and current contract details with Zerodha.
""")
    st.warning("Do not use mock data to make real trading decisions. No live trading is enabled in this application.")

st.caption("Local prototype • Educational use only • Not investment advice")
