#!/usr/bin/env python3
"""Fetch the dashboard's source series and write data/*.csv + data/refresh_log.json.

Series (all primary sources):
  imf_inr_per_usd  IMF SDMX API, dataflow IMF.STA/ER,  key IND.XDC_USD.PA_RT.M  (monthly, INR per USD)
  imf_cpi_india    IMF SDMX API, dataflow IMF.STA/CPI, key IND.CPI._T.IX.M      (monthly index)
  imf_cpi_us       IMF SDMX API, dataflow IMF.STA/CPI, key USA.CPI._T.IX.M      (monthly index)
  fred_dexinus     Federal Reserve Board H.10 via FRED series DEXINUS            (daily, INR per USD)

Rules this script follows:
  * A failed fetch NEVER overwrites good data. The old CSV is kept and the series is marked "stale".
  * A response with far fewer rows than the stored file is treated as a failure.
  * No bundled snapshots or hard-coded values are ever substituted.
  * "last_success_utc" (when we last fetched OK) is stored separately from
    "latest_observation_date" (the newest data point in the series).

Usage:
  python fetch_data.py            # refresh everything, write CSVs and the log
  python fetch_data.py --probe    # read-only check of every source (no files written)
  python fetch_data.py --only fred_dexinus
Exit code is 1 if any series failed to refresh.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
LOG_PATH = DATA_DIR / "refresh_log.json"

IMF_BASE = "https://api.imf.org/external/sdmx/3.0"
IMF_AGENCY = "IMF.STA"
IMF_VERSIONS = ["+", "~"]  # "+" = latest stable version in SDMX 3.0
IMF_START = "1976-01"
IMF_HEADERS_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0, text/csv;q=0.9"}
IMF_HEADERS_JSON = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json;q=0.9"}
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
USER_AGENT = "india-fx-dashboard/1.0 (student project; contact via GitHub repo)"
TIMEOUT = 60
MIN_ROWS_RATIO = 0.9  # refuse to overwrite if the new pull has <90% of the stored rows

SERIES = [
    {
        "id": "imf_inr_per_usd",
        "name": "INR per USD, monthly average",
        "source": "IMF (SDMX API, dataflow IMF.STA/ER)",
        "source_url": "https://data.imf.org",
        "units": "INR per 1 USD",
        "frequency": "Monthly (period average)",
        "kind": "imf", "flow": "ER", "key": "IND.XDC_USD.PA_RT.M",
    },
    {
        "id": "imf_cpi_india",
        "name": "India CPI, all items",
        "source": "IMF (SDMX API, dataflow IMF.STA/CPI)",
        "source_url": "https://data.imf.org",
        "units": "Index (base year set by the IMF)",
        "frequency": "Monthly",
        "kind": "imf", "flow": "CPI", "key": "IND.CPI._T.IX.M",
    },
    {
        "id": "imf_cpi_us",
        "name": "US CPI, all items",
        "source": "IMF (SDMX API, dataflow IMF.STA/CPI)",
        "source_url": "https://data.imf.org",
        "units": "Index (base year set by the IMF)",
        "frequency": "Monthly",
        "kind": "imf", "flow": "CPI", "key": "USA.CPI._T.IX.M",
    },
    {
        "id": "fred_dexinus",
        "name": "INR per USD, daily noon buying rate",
        "source": "Federal Reserve Board, H.10 release (series DEXINUS, retrieved via FRED)",
        "source_url": "https://www.federalreserve.gov/releases/h10/",
        "units": "INR per 1 USD",
        "frequency": "Daily (business days; H.10 is published weekly)",
        "kind": "fred", "fred_id": "DEXINUS",
    },
]
SPEC_BY_ID = {s["id"]: s for s in SERIES}


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _http_get(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3):
    """GET with retries on network errors and 5xx. Returns (response | None, message)."""
    last = "no response"
    for attempt in range(retries):
        try:
            r = requests.get(
                url, params=params, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
            )
        except requests.RequestException as exc:
            last = f"network error: {exc}"
        else:
            if r.status_code < 500:
                return r, "ok"
            last = f"HTTP {r.status_code}"
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None, last


# --------------------------------------------------------------------------- #
# IMF parsing (carried over from the Real Exchange Rate app, which ran live)
# --------------------------------------------------------------------------- #
def _parse_period(value) -> pd.Timestamp:
    """'1976-M01' / '1976-01' -> first day of that month (monthly data only)."""
    m = re.match(r"^(\d{4})-?M?(\d{1,2})$", str(value).strip())
    if not m:
        return pd.NaT
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return pd.NaT
    return pd.Timestamp(year=year, month=month, day=1)


def _to_series(periods: pd.Series, values: pd.Series) -> pd.Series:
    idx = periods.map(_parse_period)
    s = pd.Series(pd.to_numeric(values, errors="coerce").to_numpy(), index=pd.DatetimeIndex(idx))
    s = s[s.index.notna()].dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def _parse_imf_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    cols = {c.upper().split(":")[0].strip(): c for c in df.columns}
    t_col, v_col = cols.get("TIME_PERIOD"), cols.get("OBS_VALUE")
    if t_col is None or v_col is None:
        return pd.Series(dtype=float)
    return _to_series(df[t_col], df[v_col])


def _parse_imf_json(payload: dict) -> pd.Series:
    """SDMX-JSON (2.0 style) for a single-series response."""
    data = payload.get("data", payload)
    structure = data["structures"][0] if "structures" in data else data["structure"]
    time_values = structure["dimensions"]["observation"][0]["values"]
    periods, values = [], []
    for ds in data["dataSets"]:
        for series in ds.get("series", {}).values():
            for idx, obs in series.get("observations", {}).items():
                tv = time_values[int(idx)]
                periods.append(tv.get("id") or tv.get("value"))
                values.append(obs[0])
    return _to_series(pd.Series(periods), pd.Series(values))


def fetch_imf(flow: str, key: str) -> pd.Series:
    last_msg = "no response"
    for version in IMF_VERSIONS:
        url = f"{IMF_BASE}/data/dataflow/{IMF_AGENCY}/{flow}/{version}/{key}"
        for headers in (IMF_HEADERS_CSV, IMF_HEADERS_JSON):
            r, msg = _http_get(url, params={"startPeriod": IMF_START}, headers=headers)
            if r is None:
                last_msg = msg
                continue
            if r.status_code == 404:
                last_msg = "no data (404)"
                break  # this version has no such series; try the next version
            if r.status_code != 200:
                last_msg = f"HTTP {r.status_code}"
                continue
            try:
                ctype = r.headers.get("Content-Type", "").lower()
                s = _parse_imf_json(r.json()) if "json" in ctype else _parse_imf_csv(r.text)
            except Exception as exc:  # noqa: BLE001
                last_msg = f"could not parse response ({exc})"
                continue
            if len(s):
                return s
            last_msg = "empty series"
    raise RuntimeError(f"IMF {flow}/{key}: {last_msg}")


# --------------------------------------------------------------------------- #
# FRED / Federal Reserve H.10
# --------------------------------------------------------------------------- #
def _parse_fred_csv(text: str, series_id: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    if df.shape[1] < 2:
        raise ValueError("unexpected FRED CSV layout")
    date_col = df.columns[0]  # 'observation_date' (new) or 'DATE' (old)
    val_col = series_id if series_id in df.columns else df.columns[1]
    s = pd.Series(
        pd.to_numeric(df[val_col], errors="coerce").to_numpy(),  # '.' (no data) -> NaN
        index=pd.to_datetime(df[date_col], errors="coerce"),
    )
    s = s[s.index.notna()].dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def fetch_fred(series_id: str) -> pd.Series:
    r, msg = _http_get(FRED_CSV_URL, params={"id": series_id})
    if r is None:
        raise RuntimeError(f"FRED {series_id}: {msg}")
    if r.status_code != 200:
        raise RuntimeError(f"FRED {series_id}: HTTP {r.status_code}")
    s = _parse_fred_csv(r.text, series_id)
    if s.empty:
        raise RuntimeError(f"FRED {series_id}: empty series")
    return s


def fetch(spec: dict) -> pd.Series:
    if spec["kind"] == "imf":
        return fetch_imf(spec["flow"], spec["key"])
    if spec["kind"] == "fred":
        return fetch_fred(spec["fred_id"])
    raise ValueError(f"unknown kind {spec['kind']}")


# --------------------------------------------------------------------------- #
# Validation, storage, log
# --------------------------------------------------------------------------- #
def validate(s: pd.Series) -> tuple[pd.Series, int]:
    """Return a clean, sorted, unique-index series and the number of non-positive values dropped."""
    if s.empty:
        raise ValueError("series is empty")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    bad = int((s <= 0).sum())
    s = s[s > 0]
    if s.empty:
        raise ValueError("no positive values")
    return s, bad


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _csv_path(series_id: str) -> Path:
    return DATA_DIR / f"{series_id}.csv"


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(pd.read_csv(path))
    except Exception:  # noqa: BLE001
        return 0


def _write_csv(s: pd.Series, path: Path) -> None:
    tmp = path.with_suffix(".csv.tmp")
    s.rename("value").rename_axis("date").to_csv(tmp, date_format="%Y-%m-%d")
    os.replace(tmp, path)


def load_log() -> dict:
    try:
        return json.loads(LOG_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _write_log(log: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, LOG_PATH)


def refresh_one(spec: dict, prev_entry: dict) -> tuple[dict, bool]:
    """Refresh one series. On any failure the stored CSV is left untouched."""
    now = now_iso()
    path = _csv_path(spec["id"])
    entry = {
        "id": spec["id"], "name": spec["name"], "source": spec["source"],
        "source_url": spec["source_url"], "units": spec["units"], "frequency": spec["frequency"],
        "file": f"data/{spec['id']}.csv",
        "last_attempt_utc": now,
        # carried over from the previous run until this run succeeds:
        "last_success_utc": prev_entry.get("last_success_utc"),
        "first_observation_date": prev_entry.get("first_observation_date"),
        "latest_observation_date": prev_entry.get("latest_observation_date"),
        "rows": prev_entry.get("rows"),
    }
    prev_rows = _count_rows(path)
    try:
        s, dropped = validate(fetch(spec))
        if prev_rows and len(s) < MIN_ROWS_RATIO * prev_rows:
            raise ValueError(f"fetched {len(s)} rows but {prev_rows} are stored; refusing to overwrite")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_csv(s, path)
    except Exception as exc:  # noqa: BLE001
        entry["status"] = "stale" if path.exists() else "failed"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry, False

    latest = s.index.max().strftime("%Y-%m-%d")
    entry.update(
        status="ok",
        error="",
        last_success_utc=now,
        first_observation_date=s.index.min().strftime("%Y-%m-%d"),
        latest_observation_date=latest,
        rows=int(len(s)),
        rows_added=int(len(s) - prev_rows) if prev_rows else int(len(s)),
        new_latest_observation=bool(latest != prev_entry.get("latest_observation_date")),
        notes=f"dropped {dropped} non-positive value(s)" if dropped else "",
    )
    return entry, True


def refresh(only: list[str] | None = None) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prev = load_log()
    prev_series = prev.get("series", {})
    started = now_iso()
    series_log, all_ok = {}, True
    for spec in SERIES:
        if only and spec["id"] not in only:
            if spec["id"] in prev_series:
                series_log[spec["id"]] = prev_series[spec["id"]]
            continue
        entry, ok = refresh_one(spec, prev_series.get(spec["id"], {}))
        series_log[spec["id"]] = entry
        all_ok = all_ok and ok
        print(f"[{entry['status']:6}] {spec['id']:18} latest={entry.get('latest_observation_date')} "
              f"rows={entry.get('rows')} {entry.get('error', '')}")
    finished = now_iso()
    full = all_ok and not only
    log = {
        "run_started_utc": started,
        "last_run_utc": finished,
        "all_series_ok": all_ok,
        # Only a run that refreshed EVERY series successfully counts as a full success.
        "last_full_success_utc": finished if full else prev.get("last_full_success_utc"),
        "series": series_log,
    }
    _write_log(log)
    return log


def write_step_summary(log: dict) -> None:
    """Append a markdown table to the GitHub Actions run summary (useful as evidence)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "### Data refresh",
        f"Last run (UTC): `{log['last_run_utc']}`  ",
        f"Last full success (UTC): `{log.get('last_full_success_utc')}`",
        "",
        "| Series | Status | Latest observation | Rows | Last success (UTC) |",
        "|---|---|---|---|---|",
    ]
    for e in log["series"].values():
        lines.append(f"| {e['id']} | {e['status']} | {e.get('latest_observation_date')} | "
                     f"{e.get('rows')} | {e.get('last_success_utc')} |")
        if e.get("error"):
            lines.append(f"|  | error: {e['error']} | | | |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Probe (read-only)
# --------------------------------------------------------------------------- #
def probe() -> int:
    """Print availability facts for every source. Writes nothing."""
    failures = 0
    for spec in SERIES:
        print(f"\n== {spec['id']}  ({spec['source']})")
        try:
            s, dropped = validate(fetch(spec))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"   FAILED: {type(exc).__name__}: {exc}")
            continue
        print(f"   first={s.index.min():%Y-%m-%d} latest={s.index.max():%Y-%m-%d} rows={len(s)} "
              f"non-positive dropped={dropped}")
        if spec["kind"] == "imf":
            full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
            missing = full.difference(s.index)
            print(f"   missing months inside range: {len(missing)}"
                  + (f" (first few: {[d.strftime('%Y-%m') for d in missing[:5]]})" if len(missing) else ""))
            chg = s.pct_change().abs().dropna().sort_values(ascending=False).head(3)
            print("   largest month-on-month moves (look for rebasing/series breaks): "
                  + ", ".join(f"{d:%Y-%m} {v * 100:.1f}%" for d, v in chg.items()))
        else:
            last_year = s[s.index >= s.index.max() - pd.Timedelta(days=365)]
            print(f"   observations in the last 365 days: {len(last_year)}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="read-only availability check")
    ap.add_argument("--only", nargs="+", choices=list(SPEC_BY_ID), help="refresh only these series")
    args = ap.parse_args(argv)
    if args.probe:
        return probe()
    log = refresh(args.only)
    write_step_summary(log)
    return 0 if log["all_series_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
