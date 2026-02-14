import os
import time
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Market Climate Dashboard (MVP)", layout="wide")

st.title("Market Climate Dashboard (MVP)")
st.caption("Deployment-first. Visuals later.")

# --- Secrets / API key handling ---
FRED_API_KEY = st.secrets.get("FRED_API_KEY", os.getenv("FRED_API_KEY", ""))
if not FRED_API_KEY:
    st.error("Missing FRED_API_KEY. Add it in Streamlit Cloud → App → Settings → Secrets.")
    st.stop()

# --- FRED fetch (simple) ---
@st.cache_data(ttl=24 * 60 * 60)
def fetch_fred_series(series_id: str) -> pd.DataFrame:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()["observations"]
    df = pd.DataFrame(data)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date")
    return df

# --- Minimal chart: Real Trade Weighted U.S. Dollar Index (Broad) (RTWEXBGS) ---
series_id = "RTWEXBGS"
df = fetch_fred_series(series_id)

# --- Calm the series: 3-year window + weekly sampling ---
end = df["date"].max()
start = end - pd.DateOffset(years=3)
df = df[df["date"] >= start].copy()

# RTWEXBGS is monthly, but this keeps the pattern consistent across charts later.
# "W-FRI" anchors weeks to Friday.
df = (
    df.set_index("date")
      .resample("W-FRI")
      .last()
      .dropna()
      .reset_index()
)

st.subheader("Real Trade-Weighted U.S. Dollar Index (Broad) — RTWEXBGS (Last 3Y, Weekly)")
fig = px.line(df, x="date", y="value")
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

with st.expander("Status"):
    st.write({"series_id": series_id, "points": len(df), "last_date": str(df["date"].max().date())})

# Optional: crude rotation placeholder (kept OFF for MVP stability)
