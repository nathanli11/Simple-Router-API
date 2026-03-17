import streamlit as st
import requests

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="Trading API", layout="wide")

st.title("📈 Trading API Interface")

# session state
if "token" not in st.session_state:
    st.session_state.token = None


# -------- AUTH --------
st.sidebar.header("Authentication")

username = st.sidebar.text_input("Username")
password = st.sidebar.text_input("Password", type="password")

if st.sidebar.button("Register"):
    r = requests.post(f"{API}/register", json={
        "username": username,
        "password": password
    })
    st.sidebar.write(r.json())

if st.sidebar.button("Login"):
    r = requests.post(f"{API}/login", json={
        "username": username,
        "password": password
    })
    data = r.json()

    if "access_token" in data:
        st.session_state.token = data["access_token"]
        st.sidebar.success("Logged in")

    st.sidebar.write(data)


# -------- INFO --------
st.header("Market Info")

if st.button("Get market info"):
    r = requests.get(f"{API}/info")
    st.json(r.json())


# -------- BALANCE --------
st.header("Account Balance")

if st.button("Get balance"):
    r = requests.get(
        f"{API}/balance",
        headers={"Authorization": f"Bearer {st.session_state.token}"}
    )
    st.json(r.json())


# -------- DEPOSIT --------
st.header("Deposit Funds")

col1, col2 = st.columns(2)

asset = col1.text_input("Asset", "USDT")
amount = col2.number_input("Amount", value=1000)

if st.button("Deposit"):
    r = requests.post(
        f"{API}/deposit",
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        json={"asset": asset, "amount": amount}
    )
    st.json(r.json())


# -------- ORDER --------
st.header("Place Order")

col1, col2, col3, col4 = st.columns(4)

symbol = col1.text_input("Symbol", "BTCUSDT")
side = col2.selectbox("Side", ["buy", "sell"])
price = col3.number_input("Price", value=30000.0)
qty = col4.number_input("Quantity", value=0.01)

token_id = st.text_input("Token ID (unique)", f"ord-{int(__import__('time').time())}")

if st.button("Send Order"):
    r = requests.post(
        f"{API}/orders",
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        json={
            "token_id": token_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": qty
        }
    )
    st.json(r.json())