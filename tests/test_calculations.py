"""Tests use small hand-calculable numbers (see VERIFICATION.md for the same examples)."""
import math

import numpy as np
import pandas as pd
import pytest

import calculations as calc


def months(n, start="2020-01-01"):
    return pd.date_range(start, periods=n, freq="MS")


def test_spot_and_rer_hand_example():
    # e = 80 INR/USD -> S = 0.0125 USD/INR; P_IN = 150, P_US = 120 -> RER = 0.0125*150/120 = 0.015625
    idx = months(1)
    panel = calc.build_monthly_panel(
        pd.Series([80.0], index=idx), pd.Series([150.0], index=idx), pd.Series([120.0], index=idx))
    assert panel["S"].iloc[0] == pytest.approx(0.0125)
    assert panel["RER"].iloc[0] == pytest.approx(0.015625)


def test_rebase_average_is_100_and_gaps_excluded():
    idx = months(4)
    inr = pd.Series([80.0, 80.0, np.nan, 100.0], index=idx)
    p_in = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    p_us = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    panel = calc.build_monthly_panel(inr, p_in, p_us)
    sample, star = calc.rebase_rer(panel, idx[0], idx[-1])
    # valid months: S = 0.0125, 0.0125, 0.01 -> mean = 0.011666...
    assert star == pytest.approx((0.0125 + 0.0125 + 0.01) / 3)
    valid = sample["valid_rer"]
    assert sample.loc[valid, "RER_index"].mean() == pytest.approx(100.0)
    assert np.isnan(sample["RER_index"].iloc[2])  # gap month stays a gap


def test_rebase_recomputes_when_sample_changes():
    idx = months(6)
    panel = calc.build_monthly_panel(
        pd.Series([80, 82, 84, 86, 88, 90.0], index=idx), pd.Series(100.0, index=idx), pd.Series(100.0, index=idx))
    _, star_all = calc.rebase_rer(panel, idx[0], idx[-1])
    _, star_part = calc.rebase_rer(panel, idx[3], idx[-1])
    assert star_all != pytest.approx(star_part)


def test_yoy_inflation():
    idx = months(13)
    price = pd.Series(np.linspace(100, 106, 13), index=idx)
    assert calc.yoy_inflation(price).iloc[-1] == pytest.approx(0.06)
    assert calc.yoy_inflation(price).iloc[:12].isna().all()


def test_ppp_prediction_matches_class_example():
    # Slide 3: pi(US)=2%, pi(FC)=6% -> exact change 1.02/1.06 - 1 = -3.77%
    assert calc.ppp_predicted_change(0.02, 0.06) == pytest.approx(1.02 / 1.06 - 1)
    assert calc.ppp_predicted_change(0.02, 0.06) == pytest.approx(-0.0377358, abs=1e-6)


def test_ppp_check_realized_vs_predicted_consistent_when_ppp_holds():
    # Build S so that PPP holds exactly: S_t = S_0 * (P_US_t / P_IN_t)
    idx = months(25)
    p_in = pd.Series(100 * 1.06 ** (np.arange(25) / 12), index=idx)
    p_us = pd.Series(100 * 1.02 ** (np.arange(25) / 12), index=idx)
    s = 0.0125 * p_us / p_in
    panel = calc.build_monthly_panel(1.0 / s, p_in, p_us)
    chk = calc.ppp_check(panel).dropna()
    assert (chk["deviation"].abs() < 1e-9).all()
    summ = calc.ppp_summary(calc.ppp_check(panel))
    assert summ["sign_agreement"] == pytest.approx(1.0)


def test_monthly_change_simple_and_log():
    s = pd.Series([0.0100, 0.0102], index=months(2))
    assert calc.monthly_change(s, "simple").iloc[1] == pytest.approx(0.02)
    assert calc.monthly_change(s, "log").iloc[1] == pytest.approx(math.log(1.02))


def test_sigma_scaling_and_band_match_slide_examples():
    # Class sheet #12: monthly sigma = annual / sqrt(12)
    assert calc.horizon_sigma(0.10, 12) == pytest.approx(0.10 / math.sqrt(12))
    # Slide 4: S=0.1100, sigma=10% -> range 0.0880 to 0.1320
    lo, hi = calc.band(0.11, 0.10)
    assert (lo, hi) == (pytest.approx(0.088), pytest.approx(0.132))


def test_rolling_vol_annualization():
    # Alternating +1%/-1% daily changes (approx): sample std ~ 0.01 -> annual ~ 0.01*sqrt(252)
    n = 300
    rets = np.where(np.arange(n) % 2 == 0, 0.01, -0.01)
    spot = pd.Series(0.0125 * np.cumprod(1 + rets), index=pd.bdate_range("2024-01-01", periods=n))
    vol = calc.rolling_annualized_vol(spot, window=252, n=252).dropna()
    assert vol.iloc[-1] == pytest.approx(0.01 * math.sqrt(252), rel=0.02)


def test_daily_spot_inverse():
    d = pd.Series([80.0, 100.0], index=pd.bdate_range("2024-01-01", periods=2))
    assert calc.daily_spot(d).tolist() == pytest.approx([0.0125, 0.01])


def test_cross_check_monthly_mean():
    daily = pd.Series([80.0, 82.0, 84.0, 90.0], index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-02-01"]))
    imf = pd.Series([82.0, 90.0], index=pd.to_datetime(["2024-01-01", "2024-02-01"]))
    out = calc.cross_check(imf, daily)
    assert out.loc["2024-01-01", "fred_daily_mean"] == pytest.approx(82.0)
    assert out.loc["2024-01-01", "fred_obs"] == 3
    assert out.loc["2024-01-01", "diff_pct"] == pytest.approx(0.0)
