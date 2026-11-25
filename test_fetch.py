"""Offline tests for the data layer (no network)."""
import json

import pandas as pd
import pytest

import fetch_data as fd


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fd, "LOG_PATH", tmp_path / "refresh_log.json")
    return tmp_path


def _series(n=100, start="2000-01-01", freq="MS", base=50.0):
    return pd.Series([base + i for i in range(n)], index=pd.date_range(start, periods=n, freq=freq))


def test_parse_imf_csv():
    text = "DATAFLOW,TIME_PERIOD,OBS_VALUE\nx,1976-M01,100\nx,1976-M02,101\nx,1976-M03,\n"
    s = fd._parse_imf_csv(text)
    assert list(s.index) == [pd.Timestamp("1976-01-01"), pd.Timestamp("1976-02-01")]
    assert s.tolist() == [100.0, 101.0]


def test_parse_fred_csv_handles_missing_dots_and_both_header_styles():
    for header in ("observation_date", "DATE"):
        text = f"{header},DEXINUS\n2026-11-16,93.9200\n2026-11-17,.\n2026-11-20,92.6700\n"
        s = fd._parse_fred_csv(text, "DEXINUS")
        assert s.tolist() == [93.92, 92.67]
        assert s.index[-1] == pd.Timestamp("2026-11-20")


def test_successful_refresh_writes_csv_and_log(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: _series())
    log = fd.refresh()
    assert log["all_series_ok"] is True
    assert log["last_full_success_utc"]
    for spec in fd.SERIES:
        assert (tmp_data / f"{spec['id']}.csv").exists()
        e = log["series"][spec["id"]]
        assert e["status"] == "ok" and e["rows"] == 100
        # refresh time and observation date are separate fields
        assert e["last_success_utc"].endswith("Z") and e["latest_observation_date"] == "2008-04-01"
    assert json.loads((tmp_data / "refresh_log.json").read_text())["all_series_ok"] is True


def test_failed_fetch_keeps_old_data_and_marks_stale(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: _series())
    first = fd.refresh()
    before = (tmp_data / "imf_cpi_us.csv").read_text()

    def boom(spec):
        raise RuntimeError("source down")

    monkeypatch.setattr(fd, "fetch", boom)
    second = fd.refresh()
    assert second["all_series_ok"] is False
    assert second["last_full_success_utc"] == first["last_full_success_utc"]  # not advanced
    e = second["series"]["imf_cpi_us"]
    assert e["status"] == "stale" and "source down" in e["error"]
    assert e["last_success_utc"] == first["series"]["imf_cpi_us"]["last_success_utc"]
    assert (tmp_data / "imf_cpi_us.csv").read_text() == before  # untouched


def test_truncated_response_does_not_overwrite(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: _series(100))
    fd.refresh()
    before = (tmp_data / "fred_dexinus.csv").read_text()
    monkeypatch.setattr(fd, "fetch", lambda spec: _series(10))
    log = fd.refresh()
    assert log["series"]["fred_dexinus"]["status"] == "stale"
    assert (tmp_data / "fred_dexinus.csv").read_text() == before


def test_refresh_with_no_new_data_still_counts_as_success(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: _series())
    fd.refresh()
    log = fd.refresh()
    e = log["series"]["imf_cpi_india"]
    assert log["all_series_ok"] is True
    assert e["rows_added"] == 0 and e["new_latest_observation"] is False


def test_first_run_failure_is_marked_failed_not_faked(tmp_data, monkeypatch):
    def boom(spec):
        raise RuntimeError("blocked")

    monkeypatch.setattr(fd, "fetch", boom)
    log = fd.refresh()
    assert all(e["status"] == "failed" for e in log["series"].values())
    assert not list(tmp_data.glob("*.csv"))  # no placeholder data created
    assert log["last_full_success_utc"] is None
