"""Pure calculation functions for the India/US dashboard (no I/O, no Streamlit).

Class conventions (formula sheet numbers in brackets):
  S   = USD per 1 INR. A rise in S is an INR appreciation.        e = INR per USD, S = 1/e
  RER = S x P_India / P_US                                        [#9]
  % change in S: (S_t - S_t-1)/S_t-1, or log(S_t/S_t-1)           [#4, #5]
  Relative PPP:  dS/S = (pi_domestic - pi_foreign)/(1 + pi_foreign) [#8]
                 domestic = US, foreign = India (because S is USD per INR)
  Annual sigma -> 1/N-of-year sigma = annual / sqrt(N)            [#12]
  95% interval: mean +/- 2 sigma                                  [#11]
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Monthly panel, real exchange rate
# --------------------------------------------------------------------------- #
def build_monthly_panel(inr_per_usd: pd.Series, cpi_india: pd.Series, cpi_us: pd.Series) -> pd.DataFrame:
    """Monthly frame with a complete month-start index (gaps become NaN)."""
    df = pd.concat({"inr_per_usd": inr_per_usd, "P_IN": cpi_india, "P_US": cpi_us}, axis=1).sort_index()
    if df.empty:
        return df
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="MS"))
    df.index.name = "month"
    df["S"] = 1.0 / df["inr_per_usd"].where(df["inr_per_usd"] > 0)  # USD per INR
    ok = (df[["inr_per_usd", "P_IN", "P_US"]] > 0).all(axis=1)
    df["valid_rer"] = ok
    df["RER"] = (df["S"] * df["P_IN"] / df["P_US"]).where(ok)  # [#9]
    return df


def rebase_rer(panel: pd.DataFrame, start, end) -> tuple[pd.DataFrame, float]:
    """RER* = mean RER over valid months in [start, end]; index = 100 x RER / RER*."""
    s = panel.loc[start:end].copy()
    valid = s["valid_rer"] & s["RER"].notna()
    star = float(s.loc[valid, "RER"].mean()) if valid.any() else float("nan")
    s["RER_star"] = star
    s["RER_index"] = 100.0 * s["RER"] / star
    return s, star


def yoy_inflation(price: pd.Series) -> pd.Series:
    """12-month price growth: P_t / P_t-12 - 1. Needs a complete monthly index (see build_monthly_panel)."""
    return price.pct_change(12, fill_method=None)


def monthly_change(s: pd.Series, kind: str = "simple") -> pd.Series:
    """Month-on-month change in S: 'simple' = (S_t - S_t-1)/S_t-1 [#4]; 'log' = log(S_t/S_t-1) [#5]."""
    if kind == "log":
        return np.log(s / s.shift(1))
    return s.pct_change(1, fill_method=None)


# --------------------------------------------------------------------------- #
# Relative PPP check
# --------------------------------------------------------------------------- #
def ppp_predicted_change(pi_us, pi_in):
    """Relative PPP [#8] with domestic = US, foreign = India: (pi_US - pi_IN)/(1 + pi_IN)."""
    return (pi_us - pi_in) / (1.0 + pi_in)


def ppp_check(panel: pd.DataFrame) -> pd.DataFrame:
    """Predicted vs realized 12-month % change in S (realized inflation used as the proxy for expected)."""
    pi_in = yoy_inflation(panel["P_IN"])
    pi_us = yoy_inflation(panel["P_US"])
    out = pd.DataFrame({"pi_IN": pi_in, "pi_US": pi_us})
    out["gap_US_minus_IN"] = pi_us - pi_in
    out["predicted_dS"] = ppp_predicted_change(pi_us, pi_in)
    out["realized_dS"] = panel["S"].pct_change(12, fill_method=None)
    out["deviation"] = out["realized_dS"] - out["predicted_dS"]
    return out


def ppp_summary(check: pd.DataFrame) -> dict:
    """Descriptive statistics only. Overlapping 12-month windows mean observations are not independent."""
    d = check[["predicted_dS", "realized_dS"]].dropna()
    n = len(d)
    if n < 3:
        return {"n": n, "corr": float("nan"), "sign_agreement": float("nan"), "mean_abs_dev": float("nan")}
    return {
        "n": n,
        "corr": float(d["predicted_dS"].corr(d["realized_dS"])),
        "sign_agreement": float((np.sign(d["predicted_dS"]) == np.sign(d["realized_dS"])).mean()),
        "mean_abs_dev": float((d["realized_dS"] - d["predicted_dS"]).abs().mean()),
    }


# --------------------------------------------------------------------------- #
# Daily data: volatility and random-walk band
# --------------------------------------------------------------------------- #
def daily_spot(inr_per_usd_daily: pd.Series) -> pd.Series:
    """S = 1/e (USD per INR) from the daily INR-per-USD series."""
    return 1.0 / inr_per_usd_daily.where(inr_per_usd_daily > 0)


def rolling_annualized_vol(spot: pd.Series, window: int = 252, n: int = TRADING_DAYS) -> pd.Series:
    """Rolling sample std of daily % changes in S, scaled to a year with sqrt(N) [#12 inverted].

    Changes are between consecutive published observations (holidays are skipped, so some
    changes span more than one calendar day)."""
    r = spot.pct_change(1, fill_method=None)
    return r.rolling(window).std(ddof=1) * math.sqrt(n)


def horizon_sigma(sigma_annual: float, periods_per_year: int = 12) -> float:
    """Sigma for 1/N of a year = annual sigma / sqrt(N) [#12]. N = 12 for one month."""
    return sigma_annual / math.sqrt(periods_per_year)


def band(spot: float, sigma_horizon: float, k: float = 2.0, expected_change: float = 0.0) -> tuple[float, float]:
    """Random-walk range: S x (1 + E[change] +/- k sigma). Expected change = 0 by default."""
    return spot * (1 + expected_change - k * sigma_horizon), spot * (1 + expected_change + k * sigma_horizon)


# --------------------------------------------------------------------------- #
# Cross-check: IMF monthly average vs mean of Fed daily rates
# --------------------------------------------------------------------------- #
def cross_check(imf_monthly: pd.Series, fred_daily: pd.Series) -> pd.DataFrame:
    g = fred_daily.groupby(fred_daily.index.to_period("M"))
    m = pd.DataFrame({"fred_daily_mean": g.mean(), "fred_obs": g.count()})
    m.index = m.index.to_timestamp()
    df = pd.DataFrame({"imf_monthly": imf_monthly}).join(m, how="inner")
    df["diff_pct"] = 100.0 * (df["fred_daily_mean"] / df["imf_monthly"] - 1.0)
    return df
