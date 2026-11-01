"""The runner, end to end on made-up tables in a tmp folder."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("e2c_data", reason="e2c_data is not on this branch. Set PYTHONPATH to a main checkout, or install it. See inputs.py")

import e2c_model as m
from e2c_data import make_synthetic_tables, write_tables
import run_workbook as r

ARGS = ["--start", "2003-01-01", "--end", "2005-12-30"]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    def write(tables):
        root = tmp_path / "tables"
        write_tables(tables, root)
        monkeypatch.delenv("E2C_SOURCE", raising=False)
        monkeypatch.setenv("E2C_DATA_ROOT", str(root))
        return tmp_path / "out"
    return write


def test_end_to_end_writes_three_books_and_prints_no_rows(data, capsys):
    out = data(make_synthetic_tables())
    assert r.main(ARGS + ["--out", str(out)]) == 0
    books = pd.read_csv(out / "books.csv", index_col="book")
    assert list(books.index) == ["today", "hold_band", "hold_band_cap20"]
    assert books[["gross_sharpe", "net_sharpe", "pnl_without_top5"]].notna().all().all()
    assert np.allclose(books.net_pnl, books.gross_pnl - books.cost)
    assert (books.cost > 0).all() and (books.net_sharpe < books.gross_sharpe).all()
    for name in books.index:
        assert (out / f"weeks_{name}.csv").exists() and (out / f"names_{name}.csv").exists()
    summary = (out / "summary.txt").read_text()
    assert "gross_sharpe" in summary and "vendor" in summary and "2005-12-30 21:00:00" in summary
    printed = capsys.readouterr().out
    for secret in ("TK1", "I001", "E001"):
        assert secret not in printed and secret not in summary
    assert len(printed.splitlines()) <= 3


def test_book_numbers_are_the_method_and_the_cost(data):
    t = make_synthetic_tables()
    out = data(t)
    assert r.main(ARGS + ["--out", str(out)]) == 0
    names = pd.read_csv(out / "names_today.csv", parse_dates=["date"])
    books = pd.read_csv(out / "books.csv", index_col="book")
    cost = m.trading_cost(names, m.MASTER_PARAMS.bid_offer).sum()
    assert books.loc["today", "cost"] == pytest.approx(cost)
    by = names.groupby("ticker").pnl_total.sum().sort_values(ascending=False)
    assert books.loc["today", "pnl_without_top5"] == pytest.approx(by.iloc[5:].sum())
    held = pd.read_csv(out / "names_hold_band_cap20.csv", parse_dates=["date"])
    assert held.groupby("date").long_flag.sum().max() <= 20 and held.groupby("date").short_flag.sum().max() <= 20


def test_stops_on_a_contract_failure_and_writes_only_the_report(data, capsys):
    t = make_synthetic_tables()
    t["rates"]["rate"] *= 100
    out = data(t)
    assert r.main(ARGS + ["--out", str(out)]) == r.EXIT_CONTRACT
    assert (out / "contract_report.csv").exists() and not (out / "summary.txt").exists() and not (out / "books.csv").exists()
    assert "units / rates" in capsys.readouterr().out


def test_force_carries_on_and_says_so(data):
    t = make_synthetic_tables()
    u = t["universe"]
    t["universe"] = u[u.end_date.isna()]  # dead names lose their ending, so survivorship fails and the data still builds
    out = data(t)
    assert r.main(ARGS + ["--out", str(out)]) == r.EXIT_CONTRACT
    assert r.main(ARGS + ["--out", str(out), "--force"]) == 0
    assert "forced past a failure: True" in (out / "summary.txt").read_text()


def test_missing_kind_for_the_build_stops_cleanly_under_force(data, capsys):
    t = make_synthetic_tables()
    del t["cds_quotes"]
    out = data(t)
    assert r.main(ARGS + ["--out", str(out), "--force"]) == r.EXIT_NO_DATA
    assert "Missing data" in capsys.readouterr().out


def test_decision_time_is_passed_to_the_view(data):
    out = data(make_synthetic_tables())
    assert r.main(["--start", "2003-01-01", "--end", "2004-06-25", "--decision-time", "2004-06-25 21:00", "--out", str(out)]) == 0
    assert pd.read_csv(out / "weeks_today.csv", parse_dates=["date"]).date.max() == pd.Timestamp("2004-06-25")


def test_end_past_the_decision_time_raises(data):
    from e2c_data.source import LookAheadError
    out = data(make_synthetic_tables())
    with pytest.raises(LookAheadError):
        r.main(ARGS + ["--decision-time", "2004-06-25 21:00", "--out", str(out)])


def test_help_states_the_versioning_limit_and_needs_no_e2c_data():
    done = subprocess.run([sys.executable, "-I", str(Path(r.__file__)), "--help"], capture_output=True, text=True)
    assert done.returncode == 0 and "only accounts are versioned through time" in " ".join(done.stdout.split())
