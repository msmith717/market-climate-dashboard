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
# Chart #2: Real yield curve (TIPS) — latest weekly curve
# ---------------------------
st.divider()
st.subheader("Real Yield Curve (TIPS) — Latest Week")

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

# Latest curve point set
latest_row = tips_w.iloc[-1]
curve = pd.DataFrame({
    "Maturity": ["5Y", "7Y", "10Y", "20Y", "30Y"],
    "Yield": [latest_row["5Y"], latest_row["7Y"], latest_row["10Y"], latest_row["20Y"], latest_row["30Y"]],
})

# Ensure maturity sorts correctly on x-axis
curve["Maturity_Num"] = curve["Maturity"].str.replace("Y", "", regex=False).astype(float)
curve = curve.sort_values("Maturity_Num")

fig2 = px.line(curve, x="Maturity_Num", y="Yield", markers=True)
fig2.update_layout(
    xaxis_title="Maturity (Years)",
    yaxis_title="Real Yield (%)",
    margin=dict(l=10, r=10, t=10, b=10),
)
st.plotly_chart(fig2, use_container_width=True)

with st.expander("TIPS curve status"):
    st.write(
        {
            "latest_week_ending": str(tips_w["date"].max().date()),
            "points_used": len(tips_w),
            "series": TIPS_SERIES,
        }
    )
# ---------------------------
# Chart #3: Nominal Treasury vs Investment-Grade (IG) curve proxy — latest weekly
# ---------------------------
import plotly.graph_objects as go

st.divider()
st.subheader("Nominal Treasury vs IG Corporate Curve (Proxy) — Latest Week")

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
def fetch_curve_series(series_def: dict) -> pd.DataFrame:
    frames = []
    for label, (sid, x_years) in series_def.items():
        d = fetch_fred_series(sid).rename(columns={"value": label})
        d["x_years"] = x_years
        frames.append(d[["date", label, "x_years"]])
    # Merge wide on date; keep x_years separately
    wide = frames[0][["date", list(series_def.keys())[0]]]
    for f in frames[1:]:
        col = [c for c in f.columns if c not in ("date", "x_years")][0]
        wide = wide.merge(f[["date", col]], on="date", how="outer")
    wide = wide.sort_values("date")
    return wide

def latest_weekly_row(wide: pd.DataFrame, years: int = 3) -> pd.Series:
    end = wide["date"].max()
    start = end - pd.DateOffset(years=years)
    w = wide[wide["date"] >= start].copy()
    w = (
        w.set_index("date")
         .resample("W-FRI")
         .last()
         .dropna()
         .reset_index()
    )
    return w.iloc[-1], w["date"].max()

# Fetch and build latest Treasury curve
treas_wide = fetch_curve_series({k: (v[0], v[1]) for k, v in TREASURY_SERIES.items()})
treas_last, treas_week = latest_weekly_row(treas_wide, years=3)

treas_curve = pd.DataFrame({
    "x_years": [v[1] for v in TREASURY_SERIES.values()],
    "label": list(TREASURY_SERIES.keys()),
    "y": [treas_last[k] for k in TREASURY_SERIES.keys()],
}).dropna().sort_values("x_years")

# Fetch and build latest IG curve proxy
ig_wide = fetch_curve_series({k: (v[0], v[1]) for k, v in IG_SERIES.items()})
ig_last, ig_week = latest_weekly_row(ig_wide, years=3)

ig_curve = pd.DataFrame({
    "x_years": [v[1] for v in IG_SERIES.values()],
    "label": list(IG_SERIES.keys()),
    "y": [ig_last[k] for k in IG_SERIES.keys()],
}).dropna().sort_values("x_years")

# Use the later of the two weeks (they should typically match)
week_ending = max(treas_week, ig_week)

fig3 = go.Figure()
fig3.add_trace(go.Scatter(
    x=treas_curve["x_years"], y=treas_curve["y"],
    mode="lines+markers", name="Treasury (Nominal)"
))
fig3.add_trace(go.Scatter(
    x=ig_curve["x_years"], y=ig_curve["y"],
    mode="lines+markers", name="IG Corporate (Proxy)"
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
        "week_ending": str(pd.to_datetime(week_ending).date()),
        "treasury_points": int(len(treas_curve)),
        "ig_points": int(len(ig_curve)),
    })
