"""India rupee monitor: relative PPP and exchange-rate risk (FINC 470 final project).

Reads only the CSVs and refresh_log.json written by fetch_data.py. Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import calculations as calc

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
# Append "; calculations checked manually" only after you have completed VERIFICATION.md.
AI_USE_NOTE = "AI use: Claude Sonnet 5.5, Nov 24, 2026."

BLUE, ORANGE, GRAY, GREEN = "#1f77b4", "#d95f02", "#7f7f7f", "#2a9d8f"
QUESTION = ("Is the rupee's behavior consistent with relative PPP, "
            "and how risky has holding INR been?")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_log() -> dict:
    try:
        return json.loads((DATA_DIR / "refresh_log.json").read_text())
    except Exception:  # noqa: BLE001
        return {}


def load_series(series_id: str) -> pd.Series | None:
    path = DATA_DIR / f"{series_id}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["value"].sort_index()


def fmt_ts(ts: str | None) -> str:
    return ts.replace("T", " ").replace("Z", " UTC") if ts else "never"


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def style(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(height=height, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=-0.15))
    return fig


def fig_spot(p: pd.DataFrame, kind: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.06,
                        specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
    fig.add_trace(go.Scatter(x=p.index, y=p["S"], name="S (USD per INR)", line=dict(color=BLUE)),
                  row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=p.index, y=p["inr_per_usd"], name="INR per USD (secondary axis)",
                             line=dict(color=ORANGE, dash="dot")), row=1, col=1, secondary_y=True)
    chg = calc.monthly_change(p["S"], kind) * 100
    label = "Monthly % change in S (simple)" if kind == "simple" else "Monthly log change in S (x100)"
    fig.add_trace(go.Bar(x=chg.index, y=chg, name=label, marker_color=GRAY), row=2, col=1)
    fig.update_yaxes(title_text="USD per INR", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="INR per USD", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="%", row=2, col=1)
    return style(fig, 520)


def fig_rer(s: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=s.index, y=s["RER_index"], name="Real exchange rate index", line=dict(color=BLUE)))
    fig.add_hline(y=100, line_dash="dot", line_color=GRAY, annotation_text="sample average = 100")
    fig.update_yaxes(title_text="Index (sample average RER = 100)")
    return style(fig)


def fig_inflation(ppp: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["pi_IN"] * 100, name="India CPI inflation, YoY", line=dict(color=ORANGE)))
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["pi_US"] * 100, name="US CPI inflation, YoY", line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["gap_US_minus_IN"] * 100, name="Gap: US minus India",
                             line=dict(color=GRAY, dash="dash")))
    fig.add_hline(y=0, line_color=GRAY, line_width=1)
    fig.update_yaxes(title_text="% per year")
    return style(fig)


def fig_ppp(ppp: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["predicted_dS"] * 100, name="PPP-predicted 12-month change in S",
                             line=dict(color=ORANGE)))
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["realized_dS"] * 100, name="Realized 12-month change in S",
                             line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=ppp.index, y=ppp["deviation"] * 100, name="Realized minus predicted",
                             line=dict(color=GRAY, dash="dash")))
    fig.add_hline(y=0, line_color=GRAY, line_width=1)
    fig.update_yaxes(title_text="% change in S (USD per INR), 12 months")
    return style(fig)


def fig_vol(vol: pd.Series) -> go.Figure:
    fig = go.Figure(go.Scatter(x=vol.index, y=vol * 100, name="Rolling annualized volatility", line=dict(color=BLUE)))
    fig.update_yaxes(title_text="% per year")
    return style(fig, 320)


def fig_band(spot: pd.Series, lo: float, hi: float) -> go.Figure:
    recent = spot[spot.index >= spot.index.max() - pd.Timedelta(days=365)]
    target = recent.index.max() + pd.Timedelta(days=30)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=recent.index, y=recent, name="Daily S (USD per INR)", line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=[target, target], y=[lo, hi], mode="lines+markers", name="2σ range, one month ahead",
                             line=dict(color=ORANGE, width=4)))
    fig.add_trace(go.Scatter(x=[target], y=[float(recent.iloc[-1])], mode="markers",
                             name="Random-walk forecast (= latest spot)", marker=dict(color="black", size=9)))
    fig.update_yaxes(title_text="USD per INR")
    return style(fig, 340)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="India rupee monitor", layout="wide")
st.title("India rupee monitor: PPP and risk")
st.caption(QUESTION)

log = load_log()
series_log = log.get("series", {})
er_m = load_series("imf_inr_per_usd")
cpi_in = load_series("imf_cpi_india")
cpi_us = load_series("imf_cpi_us")
fred = load_series("fred_dexinus")

if not log or any(x is None for x in (er_m, cpi_in, cpi_us, fred)):
    st.error("No data yet. Run `python fetch_data.py` locally, or run the **Refresh data** workflow "
             "in the repository's Actions tab, then reload this page.")
    if series_log:
        st.dataframe(pd.DataFrame(series_log.values())[["id", "status", "error"]], hide_index=True)
    st.stop()

# ---- refresh status (separate from observation dates) ----------------------
stale = [e["id"] for e in series_log.values() if e.get("status") != "ok"]
c1, c2, c3 = st.columns(3)
c1.metric("Last successful refresh (all series)", fmt_ts(log.get("last_full_success_utc")))
c2.metric("Last refresh attempt", fmt_ts(log.get("last_run_utc")))
c3.metric("Series status", "All current" if not stale else f"{len(stale)} stale or failed")
if stale:
    st.warning("Showing last good data for: " + ", ".join(stale) + ". See the status table for the error.")
with st.expander("Series status: latest observation vs last refresh", expanded=False):
    tbl = pd.DataFrame([{
        "Series": e["name"], "Source": e["source"], "Frequency": e["frequency"], "Units": e["units"],
        "Latest observation": e.get("latest_observation_date"), "Last successful fetch (UTC)": fmt_ts(e.get("last_success_utc")),
        "Status": e.get("status"), "Rows": e.get("rows"),
    } for e in series_log.values()])
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.caption("The latest observation date is the newest data point published by the source. "
               "It is not the refresh time: a refresh can succeed without finding new data.")

# ---- panels ---------------------------------------------------------------------
panel = calc.build_monthly_panel(er_m, cpi_in, cpi_us)
ppp_all = calc.ppp_check(panel)
spot_d = calc.daily_spot(fred).dropna()

valid_months = panel.index[panel["valid_rer"]]
if len(valid_months) < 14:
    st.error("Not enough overlapping monthly data (need at least 14 valid months).")
    st.stop()
opts = [d.strftime("%Y-%m") for d in pd.date_range(valid_months.min(), valid_months.max(), freq="MS")]
default_start = "2010-01" if "2010-01" in opts else opts[0]

with st.sidebar:
    st.header("Settings")
    start_s, end_s = st.select_slider("Sample period (months)", options=opts, value=(default_start, opts[-1]))
    chg_kind = st.radio("Chart 1 monthly change", ["simple", "log"], horizontal=True,
                        help="simple = (S_t - S_t-1)/S_t-1 (#4); log = log(S_t/S_t-1) (#5)")
    window = st.selectbox("Volatility window (trading days)", [126, 252, 504], index=1)
    n_days = st.number_input("Trading days per year, N", min_value=200, max_value=260, value=calc.TRADING_DAYS)
start, end = pd.Timestamp(start_s + "-01"), pd.Timestamp(end_s + "-01")

sample = panel.loc[start:end]
rer_sample, rer_star = calc.rebase_rer(panel, start, end)
ppp = ppp_all.loc[start:end]


def sources(ids: list[str], units: str, freq: str, transform: str) -> None:
    lines = [f"**Units:** {units} · **Frequency:** {freq} · **Transformation:** {transform}", ""]
    for i in ids:
        e = series_log.get(i, {})
        lines.append(f"- {e.get('name', i)}: [{e.get('source', '')}]({e.get('source_url', '')}), "
                     f"latest observation **{e.get('latest_observation_date', 'n/a')}**")
    st.markdown("\n".join(lines))


# ---- Chart 1 -----------------------------------------------------------------------
st.header("1. Spot exchange rate")
st.plotly_chart(fig_spot(sample, chg_kind), width="stretch")
sources(["imf_inr_per_usd"], "S in USD per INR (left); INR per USD (right); changes in %",
        "Monthly (IMF period averages)",
        "S = 1/e where e = INR per USD; % change = (S_t − S_t−1)/S_t−1, or log(S_t/S_t−1)")

# ---- Chart 2 -----------------------------------------------------------------------
st.header("2. Real exchange rate")
st.plotly_chart(fig_rer(rer_sample), width="stretch")
st.caption(f"RER* (sample average, raw units) = {rer_star:.6f}. Above 100: the rupee is stronger in real terms "
           f"than its sample average; below 100: weaker.")
sources(["imf_inr_per_usd", "imf_cpi_india", "imf_cpi_us"], "Index, sample average = 100", "Monthly",
        "RER = S × P_India / P_US; rebased: 100 × RER / mean(RER over the selected valid months)")

# ---- Chart 3 -----------------------------------------------------------------------
st.header("3. Inflation: India vs US")
st.plotly_chart(fig_inflation(ppp), width="stretch")
sources(["imf_cpi_india", "imf_cpi_us"], "% per year", "Monthly",
        "YoY inflation = P_t / P_t−12 − 1; gap = π_US − π_India")

# ---- Chart 4 -----------------------------------------------------------------------
st.header("4. Relative PPP check")
st.plotly_chart(fig_ppp(ppp), width="stretch")
summ = calc.ppp_summary(ppp)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Months compared", summ["n"])
m2.metric("Correlation (predicted vs realized)", "n/a" if np.isnan(summ["corr"]) else f"{summ['corr']:.2f}")
m3.metric("Same direction", "n/a" if np.isnan(summ["sign_agreement"]) else f"{summ['sign_agreement'] * 100:.0f}%")
m4.metric("Mean absolute deviation", "n/a" if np.isnan(summ["mean_abs_dev"]) else f"{summ['mean_abs_dev'] * 100:.1f} pp")
st.caption("Descriptive only: 12-month windows overlap month to month, so these months are not independent observations.")
sources(["imf_inr_per_usd", "imf_cpi_india", "imf_cpi_us"], "% change in S (USD per INR) over 12 months", "Monthly",
        "Predicted = (π_US − π_India)/(1 + π_India) (#8, domestic = US); realized = S_t/S_t−12 − 1; "
        "realized inflation is used as the proxy for expected inflation")

# ---- Chart 5 -----------------------------------------------------------------------
st.header("5. Volatility and risk band")
vol_all = calc.rolling_annualized_vol(spot_d, window=int(window), n=int(n_days))
vol = vol_all.dropna()
if vol.empty:
    st.info("Not enough daily observations for the selected volatility window.")
else:
    st.plotly_chart(fig_vol(vol[vol.index >= start]), width="stretch")
    sig_a = float(vol.iloc[-1])
    sig_m = calc.horizon_sigma(sig_a, 12)
    spot_now = float(spot_d.iloc[-1])
    lo, hi = calc.band(spot_now, sig_m)
    k1, k2, k3 = st.columns(3)
    k1.metric(f"Latest spot ({spot_d.index[-1]:%Y-%m-%d})", f"{spot_now:.5f} USD/INR", f"{1 / spot_now:.2f} INR per USD",
              delta_color="off")
    k2.metric("Annualized σ / monthly σ", f"{sig_a * 100:.1f}% / {sig_m * 100:.1f}%")
    k3.metric("2σ range, one month ahead (USD/INR)", f"{lo:.5f} to {hi:.5f}",
              f"{1 / hi:.2f} to {1 / lo:.2f} INR per USD", delta_color="off")
    st.plotly_chart(fig_band(spot_d, lo, hi), width="stretch")
sources(["fred_dexinus"], "Volatility in % per year; spot in USD per INR", "Daily observations (business days)",
        "daily % change in S = (S_t − S_t−1)/S_t−1; annualized σ = daily σ × √N (N = trading days per year, #12); "
        "monthly σ = annual σ / √12; range = S × (1 ± 2σ_month) with expected change 0 (random walk, #11)")

# ---- Methods, limits, checks ---------------------------------------------------
with st.expander("Quotation convention and methods", expanded=False):
    st.markdown("""
- **Convention (class):** S = USD per unit of foreign currency, here **USD per INR**. A rise in S is an INR *appreciation*.
  Sources quote **INR per USD (e)**, so S = 1/e. INR per USD is shown as a secondary line in chart 1.
- **Real exchange rate:** RER = S × P_India / P_US (formula sheet #9). Because the two CPI indexes have different base years,
  only the rebased index (average = 100 over your chosen sample) is meaningful. Changing the sample changes the base.
- **Relative PPP (#8):** with S in USD per INR the domestic country is the US, so predicted ΔS/S = (π_US − π_India)/(1 + π_India).
  If India's inflation exceeds US inflation, PPP predicts a falling S (INR depreciation).
- **Volatility (#12):** σ of 1/N of a year = annual σ / √N. Daily σ is scaled up by √N (default N = 252).
  The ±2σ range (#11) around the latest spot assumes expected change = 0 (random walk, slide 4).
""")
with st.expander("Limitations", expanded=False):
    st.markdown("""
- Interest rates, interest parity and the carry trade are **not** covered (no forward rates; scope kept to IMF and Federal Reserve series).
- IMF monthly exchange rates are period averages, not end-of-month rates; the daily Federal Reserve series supports the volatility chart.
- PPP is tested with realized, not expected, inflation. PPP is a long-run pull, not a short-run rule.
- The 2σ range assumes roughly normal changes with constant volatility; real currencies have fat tails.
- The monthly IMF series and the daily Federal Reserve series are published at different times, so their latest dates differ.
  Derived charts end at the earliest latest-date of the series they use.
""")
with st.expander("Data check: IMF monthly average vs mean of Fed daily rates", expanded=False):
    cc = calc.cross_check(er_m, fred).tail(12)
    if cc.empty:
        st.write("No overlapping months.")
    else:
        view = cc.rename(columns={"imf_monthly": "IMF monthly (INR/USD)", "fred_daily_mean": "Fed daily mean (INR/USD)",
                                  "fred_obs": "Fed obs in month", "diff_pct": "Difference (%)"})
        view.index = view.index.strftime("%Y-%m")
        st.dataframe(view.style.format({"IMF monthly (INR/USD)": "{:.4f}", "Fed daily mean (INR/USD)": "{:.4f}",
                                        "Difference (%)": "{:+.2f}"}), width="stretch")
        st.caption("Two independent primary sources should be close but not identical (different publishers and "
                   "day conventions). A partial month has fewer Fed observations.")

export = sample.join(ppp, how="left").join(rer_sample[["RER_star", "RER_index"]], how="left")
st.download_button("Download monthly data for the selected sample (CSV)", export.to_csv().encode("utf-8"),
                   file_name=f"india_fx_monthly_{start_s}_{end_s}.csv", mime="text/csv")
st.caption(AI_USE_NOTE)
