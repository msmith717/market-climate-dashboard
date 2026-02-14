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
# Chart #2: Real yield curve (TIPS) — latest weekly curve + ghost curves
# ---------------------------
import plotly.graph_objects as go

st.divider()
st.subheader("Real Yield Curve (TIPS) — Latest Week + Ghost Curves")

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

# 3-year window + weekly sampling (consistent with your philosophy)
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
maturity_num = [5.0, 7.0, 10.0, 20.0, 30.0]

def row_to_curve(row: pd.Series) -> pd.DataFrame:
    c = pd.DataFrame({"x": maturity_num, "y": [row[m] for m in maturities]})
    return c.dropna()

# Build ghost dates: one curve per month (use the last weekly point in each month)
tips_w["month"] = tips_w["date"].dt.to_period("M").astype(str)
ghost_rows = tips_w.groupby("month", as_index=False).tail(1)

# Keep ghost curves to a manageable count (last 12 months by default)
GHOST_MONTHS = 12
ghost_rows = ghost_rows.tail(GHOST_MONTHS)

latest_row = tips_w.iloc[-1]
week_ending = tips_w["date"].max()

fig2 = go.Figure()

# --- Build reference curves: 12m ago, 6m ago, current ---

def get_curve_nearest(date_target):
    # Find the closest available weekly date
    idx = (tips_w["date"] - date_target).abs().idxmin()
    return tips_w.loc[idx]

current_date = tips_w["date"].max()
six_months_ago = current_date - pd.DateOffset(months=6)
twelve_months_ago = current_date - pd.DateOffset(months=12)

row_current = get_curve_nearest(current_date)
row_6m = get_curve_nearest(six_months_ago)
row_12m = get_curve_nearest(twelve_months_ago)

fig2 = go.Figure()

# 12 months ago (light gray)
c_12m = row_to_curve(row_12m)
fig2.add_trace(go.Scatter(
    x=c_12m["x"], y=c_12m["y"],
    mode="lines",
    name="12M Ago",
    line=dict(width=3, color="lightgray"),
))

# 6 months ago (medium gray)
c_6m = row_to_curve(row_6m)
fig2.add_trace(go.Scatter(
    x=c_6m["x"], y=c_6m["y"],
    mode="lines",
    name="6M Ago",
    line=dict(width=3, color="gray"),
))

# Current (black)
c_current = row_to_curve(row_current)
fig2.add_trace(go.Scatter(
    x=c_current["x"], y=c_current["y"],
    mode="lines+markers",
    name="Current",
    line=dict(width=3, color="black"),
))

fig2.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Real Yield (%)",
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)

fig2.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Real Yield (%)",
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig2, use_container_width=True)

with st.expander("TIPS ghost status"):
    st.write({
        "week_ending": str(pd.to_datetime(week_ending).date()),
        "ghost_months_plotted": int(len(ghost_rows)),
        "ghost_months_setting": GHOST_MONTHS,
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
    "15+Y": ("BAMLC8A0C15PYEY", 17.5),
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

