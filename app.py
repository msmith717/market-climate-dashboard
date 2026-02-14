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

# ---------------------------
# Chart #2: Real yield curve (TIPS) — scrub-to-animate (time slider)
# ---------------------------
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

st.divider()
st.subheader("Real Yield Curve (TIPS) — Time Scrub (Weekly)")

TIPS_SERIES = {
    "5Y": "DFII5",
    "7Y": "DFII7",
    "10Y": "DFII10",
    "20Y": "DFII20",
    "30Y": "DFII30",
}

@st.cache_data(ttl=24 * 60 * 60)
def fetch_many(series_map: dict) -> pd.DataFrame:
    frames = []
    for label, sid in series_map.items():
        d = fetch_fred_series(sid).rename(columns={"value": label})
        frames.append(d[["date", label]])
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="date", how="outer")
    out = out.sort_values("date")
    return out

tips = fetch_many(TIPS_SERIES)

# 3-year window + weekly sampling
end2 = tips["date"].max()
start2 = end2 - pd.DateOffset(years=3)
tips = tips[tips["date"] >= start2].copy()

tips_w = (
    tips.set_index("date")
        .resample("W-FRI")
        .last()
        .dropna()
        .reset_index()
)

maturities = ["5Y", "7Y", "10Y", "20Y", "30Y"]
x_years = [5.0, 7.0, 10.0, 20.0, 30.0]

def row_to_curve(row: pd.Series) -> pd.DataFrame:
    c = pd.DataFrame({"x": x_years, "y": [row[m] for m in maturities]})
    return c.dropna()

# --- Build a stable index for playback ---
dates_ts = tips_w["date"].tolist()  # pandas Timestamps, length N
N = len(dates_ts)

# --- Fixed y-axis scale from the whole dataset (3Y weekly window) ---
y_cols = maturities
y_min = float(tips_w[y_cols].min().min())
y_max = float(tips_w[y_cols].max().max())
pad = 0.10 * (y_max - y_min) if y_max > y_min else 0.25
y_range = [y_min - pad, y_max + pad]

# --- Playback state ---
if "tips_playing" not in st.session_state:
    st.session_state.tips_playing = False
if "tips_idx" not in st.session_state:
    st.session_state.tips_idx = N - 1  # default = now

# --- Controls ---
c1, c2, c3 = st.columns([1, 1, 3])
with c1:
    if st.button("Start", use_container_width=True):
        st.session_state.tips_playing = True
with c2:
    if st.button("Stop", use_container_width=True):
        st.session_state.tips_playing = False
with c3:
    st.caption("Weekly playback. Use slider to jump to a specific week.")

# Autoplay tick
if st.session_state.tips_playing:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=900, key="tips_autoplay")  # ms; slow it down if you want
    st.session_state.tips_idx = (st.session_state.tips_idx + 1) % N

# Date slider (DISCRETE weekly dates; prevents snap-back)
dates_py = [d.to_pydatetime() for d in dates_ts]

selected_date = st.select_slider(
    "Week ending",
    options=dates_py,
    value=dates_py[st.session_state.tips_idx],
    format_func=lambda d: d.strftime("%Y-%m-%d"),
    disabled=st.session_state.tips_playing,
)

st.session_state.tips_idx = dates_py.index(selected_date)

# Map selected date back to index safely
# Find nearest match instead of exact index lookup
closest_idx = min(
    range(N),
    key=lambda i: abs(dates_py[i] - selected_date)
)

st.session_state.tips_idx = closest_idx

sel_date = dates_ts[st.session_state.tips_idx]
st.caption(f"Selected week ending: {sel_date.date()}  |  Now: {dates_ts[-1].date()}")

row_sel = tips_w.iloc[st.session_state.tips_idx]
row_now = tips_w.iloc[-1]

c_sel = row_to_curve(row_sel)
c_now = row_to_curve(row_now)

fig2 = go.Figure()

# NOW = black (dominant)
fig2.add_trace(go.Scatter(
    x=c_now["x"], y=c_now["y"],
    mode="lines",
    name="Now",
    line=dict(width=3, color="rgba(0,0,0,1.0)"),
))

# Selected week = gray
fig2.add_trace(go.Scatter(
    x=c_sel["x"], y=c_sel["y"],
    mode="lines+markers",
    name="Selected week",
    line=dict(width=3, color="rgba(120,120,120,1.0)"),
))

fig2.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Real Yield (%)",
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
fig2.update_yaxes(range=y_range)

st.plotly_chart(fig2, use_container_width=True)

with st.expander("TIPS scrub status"):
    st.write({
        "selected_week_ending": str(pd.to_datetime(row_sel["date"]).date()),
        "now_week_ending": str(pd.to_datetime(row_now["date"]).date()),
        "points_available": int(len(tips_w)),
        "series": TIPS_SERIES,
    })

# ---------------------------
# Chart #3: Nominal Treasury vs IG Corporate curve (proxy) — 12M / 6M / Now
# ---------------------------
import plotly.graph_objects as go

st.divider()
st.subheader("Nominal Treasury vs IG Corporate Curve (Proxy) — 12M / 6M / Now")

TREASURY_SERIES = {
    "1M": ("DGS1MO", 1/12),
    "3M": ("DGS3MO", 3/12),
    "6M": ("DGS6MO", 6/12),
    "1Y": ("DGS1", 1.0),
    "2Y": ("DGS2", 2.0),
    "3Y": ("DGS3", 3.0),
    "5Y": ("DGS5", 5.0),
    "7Y": ("DGS7", 7.0),
    "10Y": ("DGS10", 10.0),
    "20Y": ("DGS20", 20.0),
    "30Y": ("DGS30", 30.0),
}

IG_SERIES = {
    "1-3Y": ("BAMLC1A0C13YEY", 2.0),
    "3-5Y": ("BAMLC2A0C35YEY", 4.0),
    "5-7Y": ("BAMLC3A0C57YEY", 6.0),
    "7-10Y": ("BAMLC4A0C710YEY", 8.5),
    "10-15Y": ("BAMLC7A0C1015YEY", 12.5),
    "15+Y": ("BAMLC8A0C15PYEY", 20.0),
}

@st.cache_data(ttl=24 * 60 * 60)
def fetch_curve_wide(series_def: dict) -> pd.DataFrame:
    frames = []
    for label, (sid, x_years) in series_def.items():
        d = fetch_fred_series(sid).rename(columns={"value": label})
        frames.append(d[["date", label]])
    wide = frames[0]
    for f in frames[1:]:
        wide = wide.merge(f, on="date", how="outer")
    wide = wide.sort_values("date")
    return wide

def to_weekly_window(df: pd.DataFrame, years: int = 3) -> pd.DataFrame:
    end = df["date"].max()
    start = end - pd.DateOffset(years=years)
    w = df[df["date"] >= start].copy()
    w = (
        w.set_index("date")
         .resample("W-FRI")
         .last()
         .dropna()
         .reset_index()
    )
    return w

def nearest_row(df_weekly: pd.DataFrame, target_date: pd.Timestamp) -> pd.Series:
    idx = (df_weekly["date"] - target_date).abs().idxmin()
    return df_weekly.loc[idx]

def row_to_curve(row: pd.Series, series_def: dict) -> pd.DataFrame:
    labels = list(series_def.keys())
    x = [series_def[k][1] for k in labels]
    y = [row.get(k, None) for k in labels]
    c = pd.DataFrame({"x_years": x, "y": y}).dropna().sort_values("x_years")
    return c

# Build weekly datasets
treas_wide = fetch_curve_wide(TREASURY_SERIES)
ig_wide = fetch_curve_wide(IG_SERIES)

treas_w = to_weekly_window(treas_wide, years=3)
ig_w = to_weekly_window(ig_wide, years=3)

# Use latest common week-ending so lines align in time
current_date = min(treas_w["date"].max(), ig_w["date"].max())
date_6m = current_date - pd.DateOffset(months=6)
date_12m = current_date - pd.DateOffset(months=12)

# Pick nearest available rows for each dataset
treas_now = nearest_row(treas_w, current_date)
treas_6m = nearest_row(treas_w, date_6m)
treas_12m = nearest_row(treas_w, date_12m)

ig_now = nearest_row(ig_w, current_date)
ig_6m = nearest_row(ig_w, date_6m)
ig_12m = nearest_row(ig_w, date_12m)

# Curves
c_t_now = row_to_curve(treas_now, TREASURY_SERIES)
c_t_6m  = row_to_curve(treas_6m, TREASURY_SERIES)
c_t_12m = row_to_curve(treas_12m, TREASURY_SERIES)

c_ig_now = row_to_curve(ig_now, IG_SERIES)
c_ig_6m  = row_to_curve(ig_6m, IG_SERIES)
c_ig_12m = row_to_curve(ig_12m, IG_SERIES)

fig3 = go.Figure()

# Treasury (solid, grayscale)
fig3.add_trace(go.Scatter(
    x=c_t_12m["x_years"], y=c_t_12m["y"], mode="lines",
    name="Treasury 12M", line=dict(width=3, color="rgba(0,0,0,0.15)")
))
fig3.add_trace(go.Scatter(
    x=c_t_6m["x_years"], y=c_t_6m["y"], mode="lines",
    name="Treasury 6M", line=dict(width=3, color="rgba(0,0,0,0.35)")
))
fig3.add_trace(go.Scatter(
    x=c_t_now["x_years"], y=c_t_now["y"], mode="lines",
    name="Treasury Now", line=dict(width=3, color="rgba(0,0,0,1.0)")
))

# IG (solid, blue)
fig3.add_trace(go.Scatter(
    x=c_ig_12m["x_years"], y=c_ig_12m["y"], mode="lines",
    name="IG 12M", line=dict(width=3, color="rgba(0,90,255,0.15)")
))
fig3.add_trace(go.Scatter(
    x=c_ig_6m["x_years"], y=c_ig_6m["y"], mode="lines",
    name="IG 6M", line=dict(width=3, color="rgba(0,90,255,0.35)")
))
fig3.add_trace(go.Scatter(
    x=c_ig_now["x_years"], y=c_ig_now["y"], mode="lines",
    name="IG Now", line=dict(width=3, color="rgba(0,90,255,1.0)")
))

fig3.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Yield (%)",
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig3, use_container_width=True)

with st.expander("Nominal vs IG status"):
    st.write({
        "week_ending_used": str(pd.to_datetime(current_date).date()),
        "treasury_week_ending": str(pd.to_datetime(treas_w["date"].max()).date()),
        "ig_week_ending": str(pd.to_datetime(ig_w["date"].max()).date()),
        "treasury_points": int(len(c_t_now)),
        "ig_points": int(len(c_ig_now)),
    })

# ---------------------------
# Chart #4: Credit spread curve (IG - Treasury) — 12M / 6M / Now
# ---------------------------
st.divider()
st.subheader("Credit Spread Curve (IG − Treasury) — 12M / 6M / Now")

SPREAD_MATCH = [
    ("1-3Y",  "2Y"),
    ("3-5Y",  "5Y"),
    ("5-7Y",  "7Y"),
    ("7-10Y", "10Y"),
    ("10-15Y","20Y"),
    ("15+Y",  "20Y"),
]

def spread_curve(ig_row, t_row):
    rows = []
    for ig_label, t_label in SPREAD_MATCH:
        ig_y = ig_row.get(ig_label)
        t_y = t_row.get(t_label)
        if ig_y is None or t_y is None:
            continue
        rows.append({
            "x_years": IG_SERIES[ig_label][1],
            "spread": float(ig_y) - float(t_y)
        })
    df = pd.DataFrame(rows)
    return df.sort_values("x_years")

s_now = spread_curve(ig_now, treas_now)
s_6m  = spread_curve(ig_6m, treas_6m)
s_12m = spread_curve(ig_12m, treas_12m)

fig4 = go.Figure()

fig4.add_trace(go.Scatter(
    x=s_12m["x_years"],
    y=s_12m["spread"],
    mode="lines",
    name="Spread 12M",
    line=dict(width=3, color="rgba(0,0,0,0.15)")
))

fig4.add_trace(go.Scatter(
    x=s_6m["x_years"],
    y=s_6m["spread"],
    mode="lines",
    name="Spread 6M",
    line=dict(width=3, color="rgba(0,0,0,0.35)")
))

fig4.add_trace(go.Scatter(
    x=s_now["x_years"],
    y=s_now["spread"],
    mode="lines",
    name="Spread Now",
    line=dict(width=3, color="rgba(0,0,0,1.0)")
))

fig4.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Spread (percentage points)",
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
)

st.plotly_chart(fig4, use_container_width=True)

with st.expander("Spread curve status"):
    st.write({
        "week_ending_used": str(pd.to_datetime(current_date).date()),
        "points_now": int(len(s_now))
    })
