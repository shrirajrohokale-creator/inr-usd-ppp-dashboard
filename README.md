# India rupee monitor: PPP and risk

FINC 470 final project. A Streamlit dashboard that tracks the Indian rupee against the US dollar and answers:

> Is the rupee's behavior consistent with relative PPP, and how risky has holding INR been?

Data refreshes automatically through a scheduled GitHub Action. The dashboard only reads the saved CSVs and a refresh log.

## Data (4 series, all primary sources)

| Series id | What | Source | Frequency | Units |
|---|---|---|---|---|
| `imf_inr_per_usd` | INR per USD | IMF SDMX API, `IMF.STA/ER`, key `IND.XDC_USD.PA_RT.M` | Monthly (period average) | INR per 1 USD |
| `imf_cpi_india` | India CPI, all items | IMF SDMX API, `IMF.STA/CPI`, key `IND.CPI._T.IX.M` | Monthly | Index (IMF base year) |
| `imf_cpi_us` | US CPI, all items | IMF SDMX API, `IMF.STA/CPI`, key `USA.CPI._T.IX.M` | Monthly | Index (IMF base year) |
| `fred_dexinus` | INR per USD, noon buying rate | Federal Reserve Board H.10 (series DEXINUS, downloaded from FRED) | Daily business days, published weekly | INR per 1 USD |

## Charts and formulas (class convention: S = USD per INR)

| # | Chart | Formula (formula sheet #) |
|---|---|---|
| 1 | Spot S, INR per USD as secondary line, monthly % change | S = 1/e; (S_t − S_t−1)/S_t−1 or log(S_t/S_t−1) (#4, #5) |
| 2 | Real exchange rate, rebased to sample average = 100 | RER = S × P_India / P_US (#9) |
| 3 | Inflation India vs US (YoY) and the gap | π = P_t / P_t−12 − 1 |
| 4 | Relative PPP check | Predicted ΔS/S = (π_US − π_IN)/(1 + π_IN); realized = S_t/S_t−12 − 1 (#8) |
| 5 | Rolling volatility and 2σ band | σ_annual = σ_daily × √N; σ_month = σ_annual/√12; range = S × (1 ± 2σ_month), expected change 0 (#11, #12, slide 4) |

A rise in S is an INR appreciation. Each chart shows units, frequency, source link, transformation, and the latest observation date of every series it uses. The page header shows **last successful refresh** separately from those observation dates.

## Set up on GitHub

1. Create a repository and upload the contents of this folder (keep the `.github/workflows/` folder).
2. Repository **Settings → Actions → General → Workflow permissions**: choose **Read and write permissions**.
3. Open the **Actions** tab, select **Refresh data**, and click **Run workflow**. This fetches the data, commits `data/*.csv` and `data/refresh_log.json`, and writes a status table in the run summary.
4. Take a screenshot of the finished run and its summary table (evidence of a successful refresh).
5. After that it runs daily at 11:17 UTC. GitHub can pause scheduled workflows in repos with no recent activity; re-enable under Actions if that happens.

### View the dashboard

- **Locally:** `pip install -r requirements.txt` then `streamlit run app.py` (Python 3.12).
- **Hosted:** deploy the repo on Streamlit Community Cloud with main file `app.py`. It reloads when the Action commits new data.

## If the first run fails

Run `python fetch_data.py --probe` on your computer. It prints, for each series, first and latest date, row count, missing months, and the largest month-on-month moves (to spot CPI rebasing breaks). It writes nothing. Common causes:

- **IMF series name or coverage:** the IMF keys are carried over from the earlier Real Exchange Rate app, which worked live for UK/US. India has not been tested.
- **FRED CSV download:** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXINUS` should work without an API key. If FRED changes this, the fallback is the Fed's own H.10 XML download.

A failed fetch never overwrites existing data. The series is marked stale and the dashboard shows a warning. A refresh that finds no new data still counts as a success.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

18 offline tests cover the formulas (using hand-calculable numbers from the class examples) and the data layer (stale handling, truncated responses, no-new-data runs).

## Files

```
app.py                      Streamlit dashboard (reads data/ only)
calculations.py             All formulas
fetch_data.py               Fetches series, writes CSVs and refresh_log.json
data/                       CSVs and refresh_log.json (written by the Action)
.github/workflows/refresh.yml   Daily refresh
tests/                      pytest tests
VERIFICATION.md             Verification table and hand calculations to complete
```

## Limitations

- No interest rates, interest parity, or carry trade (no forward rates; scope kept to IMF and Federal Reserve data).
- IMF monthly rates are period averages. The daily Fed series is used for volatility.
- PPP uses realized, not expected, inflation, and is a long-run pull.
- The 2σ range assumes roughly normal changes and constant volatility.
- Series have different publication lags, so latest dates differ; derived charts end at the earliest of the series they use.

## AI use

Built with Claude Sonnet 5.5 (Nov 24, 2026). Not yet run against live data when this was packaged; complete `VERIFICATION.md` before adding "calculations checked manually" to the footer in `app.py` (`AI_USE_NOTE`).
