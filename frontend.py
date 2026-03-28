import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import json
import time
from datetime import datetime
from websocket import create_connection, WebSocketException

API = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"

st.set_page_config(page_title="Trading API", layout="wide")

st.title("Trading API Interface")

# session state
if "token" not in st.session_state:
    st.session_state.token = None


# -------- AUTH --------
st.sidebar.header("Authentication")

username = st.sidebar.text_input("Username")
password = st.sidebar.text_input("Password", type="password")

col_reg, col_log = st.sidebar.columns(2)

if col_reg.button("Register"):
    r = requests.post(
        f"{API}/register", json={"username": username, "password": password}
    )
    st.sidebar.write(r.json())

if col_log.button("Login"):
    r = requests.post(f"{API}/login", json={"username": username, "password": password})
    data = r.json()

    if "access_token" in data:
        st.session_state.token = data["access_token"]
        st.sidebar.success("Logged in")

    st.sidebar.write(data)


# -------- INFO (auto-load) --------
st.header("Market Info")

try:
    info_data = requests.get(f"{API}/info", timeout=3).json()

    col_assets, col_pairs = st.columns(2)

    with col_assets:
        st.subheader("Assets")
        df_assets = pd.DataFrame({"Asset": info_data.get("assets", [])})
        df_assets.index = df_assets.index + 1
        df_assets.index.name = "#"
        st.dataframe(df_assets)

    with col_pairs:
        st.subheader("Trading Pairs")
        df_pairs = pd.DataFrame({"Pair": info_data.get("pairs", [])})
        df_pairs.index = df_pairs.index + 1
        df_pairs.index.name = "#"
        st.dataframe(df_pairs)

except Exception:
    st.warning("Could not connect to the API. Make sure the server is running.")

st.divider()

# -------- BALANCE --------
st.header("Account Balance")

if st.button("Get balance"):
    r = requests.get(
        f"{API}/balance", headers={"Authorization": f"Bearer {st.session_state.token}"}
    )
    data = r.json()
    if isinstance(data, dict) and "balances" in data:
        df_bal = pd.DataFrame(data["balances"])
        df_bal.columns = [c.capitalize() for c in df_bal.columns]
        df_bal.index = df_bal.index + 1
        df_bal.index.name = "#"
        st.dataframe(df_bal)
    else:
        st.dataframe(pd.json_normalize(data))

st.divider()

# -------- DEPOSIT --------
st.header("Deposit Funds")

col1, col2 = st.columns(2)

asset = col1.text_input("Asset", "USDT")
amount = col2.number_input("Amount", value=1000)

if st.button("Deposit"):
    r = requests.post(
        f"{API}/deposit",
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        json={"asset": asset, "amount": amount},
    )
    data = r.json()
    if isinstance(data, dict) and data.get("status") == "ok":
        st.success("Deposit successful")
    else:
        st.json(data)

st.divider()

# -------- ORDER --------
st.header("Place Order")

col1, col2, col3, col4 = st.columns(4)

symbol = col1.text_input("Symbol", "BTCUSDT")
side = col2.selectbox("Side", ["buy", "sell"])
price = col3.number_input("Price", value=30000.0)
qty = col4.number_input("Quantity", value=0.01)

token_id = st.text_input("Token ID (unique)", f"ord-{int(__import__('time').time())}")

if st.button("Send Order", type="primary"):
    r = requests.post(
        f"{API}/orders",
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        json={
            "token_id": token_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": qty,
        },
    )
    data = r.json()
    if isinstance(data, dict) and "status" in data:
        df_order = pd.DataFrame([data])
        st.dataframe(df_order)
    else:
        st.json(data)

st.divider()

# -------- LIVE MARKET DATA (WebSocket) --------
st.header("Live Market Data")

if st.session_state.token is None:
    st.info("Log in first to access live market data.")
else:
    ws_col1, ws_col2, ws_col3 = st.columns(3)
    ws_symbol = ws_col1.selectbox(
        "Pair", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"], key="ws_sym"
    )
    ws_exchange = ws_col2.selectbox("Exchange", ["all", "binance", "okx"], key="ws_ex")
    ws_interval = ws_col3.selectbox(
        "Kline Interval", ["1s", "10s", "1m", "5m"], key="ws_int"
    )
    ws_duration = st.slider(
        "Listen duration (seconds)", min_value=5, max_value=120, value=30, step=5
    )

    if st.button("Start Live Stream", type="primary"):
        progress_bar = st.progress(0, text="Connecting to WebSocket...")

        klines = []
        trades = []
        last_touch = None

        try:
            ws = create_connection(WS_URL, timeout=5)

            # Auth
            ws.send(json.dumps({"action": "auth", "token": st.session_state.token}))
            auth_resp = json.loads(ws.recv())
            if auth_resp.get("status") != "ok":
                st.error(f"WebSocket auth failed: {auth_resp}")
                ws.close()
            else:
                # Subscribe to klines, trades, best_touch
                ws.send(
                    json.dumps(
                        {
                            "action": "subscribe",
                            "stream": "klines",
                            "symbol": ws_symbol,
                            "exchange": ws_exchange,
                            "interval": ws_interval,
                        }
                    )
                )
                ws.send(
                    json.dumps(
                        {
                            "action": "subscribe",
                            "stream": "trades",
                            "symbol": ws_symbol,
                            "exchange": ws_exchange,
                        }
                    )
                )
                ws.send(
                    json.dumps(
                        {
                            "action": "subscribe",
                            "stream": "best_touch",
                            "symbol": ws_symbol,
                            "exchange": ws_exchange,
                        }
                    )
                )

                # Read subscription confirmations
                for _ in range(3):
                    ws.recv()

                ws.settimeout(1.0)
                start_time = time.time()
                end_time = start_time + ws_duration

                while time.time() < end_time:
                    elapsed = time.time() - start_time
                    pct = min(elapsed / ws_duration, 1.0)
                    remaining = max(0, int(ws_duration - elapsed))
                    progress_bar.progress(
                        pct,
                        text=f"Listening... {remaining}s remaining  |  {len(klines)} klines · {len(trades)} trades",
                    )

                    try:
                        raw = ws.recv()
                        msg = json.loads(raw)
                        msg_type = msg.get("type")
                        d = msg.get("data", {})

                        if msg_type == "klines":
                            ts_str = datetime.fromtimestamp(d.get("start", 0)).strftime(
                                "%H:%M:%S"
                            )
                            klines.append(
                                {
                                    "Time": ts_str,
                                    "Open": d.get("open"),
                                    "High": d.get("high"),
                                    "Low": d.get("low"),
                                    "Close": d.get("close"),
                                    "Volume": round(d.get("volume", 0), 6),
                                    "Exchange": d.get("exchange", ""),
                                }
                            )

                        elif msg_type == "trades":
                            ts_str = datetime.fromtimestamp(
                                d.get("timestamp", 0)
                            ).strftime("%H:%M:%S")
                            trades.append(
                                {
                                    "Time": ts_str,
                                    "Price": d.get("price"),
                                    "Qty": round(d.get("quantity", 0), 6),
                                    "Exchange": d.get("exchange", ""),
                                }
                            )

                        elif msg_type == "best_touch":
                            last_touch = {
                                "Symbol": d.get("symbol"),
                                "Best Bid": d.get("best_bid"),
                                "Bid Exchange": d.get("best_bid_exchange", ""),
                                "Best Ask": d.get("best_ask"),
                                "Ask Exchange": d.get("best_ask_exchange", ""),
                            }

                    except WebSocketException:
                        continue
                    except Exception:
                        continue

                ws.close()
                progress_bar.empty()

                # ---- Display results once ----
                st.success(
                    f"Stream ended — {len(klines)} klines, {len(trades)} trades collected in {ws_duration}s."
                )

                if last_touch:
                    st.subheader("Last Best Touch")
                    st.dataframe(pd.DataFrame([last_touch]), hide_index=True)

                if klines:
                    st.subheader(f"Klines ({len(klines)})")
                    df_k = pd.DataFrame(klines)

                    fig = go.Figure(
                        data=[
                            go.Candlestick(
                                x=df_k["Time"],
                                open=df_k["Open"],
                                high=df_k["High"],
                                low=df_k["Low"],
                                close=df_k["Close"],
                                increasing_line_color="#26a69a",
                                decreasing_line_color="#ef5350",
                            )
                        ]
                    )
                    fig.update_layout(
                        title=f"{ws_symbol} — {ws_interval} candles ({ws_exchange})",
                        yaxis_title="Price",
                        xaxis_title="Time",
                        template="plotly_dark",
                        xaxis_rangeslider_visible=False,
                        height=500,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                if trades:
                    st.subheader(f"Trades ({len(trades)})")
                    df_t = pd.DataFrame(trades[-100:])
                    df_t.index = range(max(1, len(trades) - 99), len(trades) + 1)
                    df_t.index.name = "#"
                    st.dataframe(df_t)

                if not klines and not trades and not last_touch:
                    st.warning(
                        "No data received. The exchanges may not be sending data right now."
                    )

        except Exception as e:
            st.error(f"WebSocket connection failed: {e}")
