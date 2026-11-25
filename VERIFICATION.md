# Verification

Complete this after the first successful refresh. Fill in the blanks, then screenshot or paste this file as evidence.

## A. Source checks (one observation per series)

Compare the dashboard value with the original source, not with another copy of the same download. The IMF is both a data source and a check, so use independent publishers where you can.

| Series | Dashboard date | Dashboard value | Original source | Source value | Match? | Notes |
|---|---|---|---|---|---|---|
| `fred_dexinus` (daily INR per USD) | 2026-11-20 | ____ | Fed H.10 release page, https://www.federalreserve.gov/releases/h10/current/ | 92.6700 (read during build from the Nov 23, 2026 release) | ____ | Re-read the Fed page yourself. |
| `imf_inr_per_usd` (monthly) | ____ | ____ | IMF data portal https://data.imf.org (same series), plus an independent rate, e.g. RBI/FBIL reference rates (confirm the page) | ____ | ____ | IMF is a monthly average; compare with the average of that month's daily Fed rates (see the "Data check" panel in the app). Expect a small gap, explain it. |
| `imf_cpi_india` | ____ | ____ | MoSPI all-India CPI (confirm which series: IMF may use a different base or linking) | ____ | ____ | Compare month-on-month or YoY % changes, not levels: base years differ. |
| `imf_cpi_us` | ____ | ____ | BLS CPI-U, all items | ____ | ____ | Same: compare % changes, not levels. |

## B. Hand calculations (spreadsheet), using real values from the dashboard CSVs

1. **Spot:** e = ____ INR per USD → S = 1/e = ____ USD per INR.
2. **RER:** S × P_India / P_US = ____ × ____ / ____ = ____. Rebased: 100 × RER / mean(RER over your sample) = ____. Dashboard shows ____.
3. **Inflation:** π_India = P_t / P_t−12 − 1 = ____; π_US = ____.
4. **PPP prediction:** (π_US − π_India)/(1 + π_India) = ____. Realized S_t/S_t−12 − 1 = ____. Deviation = ____.
5. **Volatility:** daily σ = ____ (std of daily % changes in S over the window). Annual σ = daily σ × √252 = ____. Monthly σ = annual/√12 = ____. Range = S × (1 ± 2σ_month) = ____ to ____.

The unit tests in `tests/test_calculations.py` use the same formulas with small numbers (for example e = 80, P_IN = 150, P_US = 120 → RER = 0.015625; π_US = 2%, π_IN = 6% → −3.77%; S = 0.11, σ = 10% → 0.088 to 0.132).

## C. Refresh evidence

- Screenshot of the GitHub Actions run (green) and its summary table: ____
- `data/refresh_log.json` showing `last_full_success_utc`, and each series' `last_success_utc` and `latest_observation_date` (they are different fields): ____
- A second run with no new data, showing `rows_added: 0` and status `ok`: ____

## D. Series coverage notes (from `python fetch_data.py --probe`)

| Series | First date | Latest date | Rows | Missing months | Any CPI break or large jump? |
|---|---|---|---|---|---|
| imf_inr_per_usd | | | | | |
| imf_cpi_india | | | | | |
| imf_cpi_us | | | | | |
| fred_dexinus | | | | n/a | |
