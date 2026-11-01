"""The runner, end to end on made-up tables in a tmp folder."""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("e2c_data", reason="e2c_data is not on this branch. Set PYTHONPATH to a main checkout, or install it. See inputs.py")

from e2c_data import make_synthetic_tables, write_tables
from test_inputs import daily_trades, model_priced
import run_yu as r

ARGS = ["--start", "2005-01-03", "--end", "2005-12-30", "--vol-source", "implied", "--hedge-id", "UST5Y", "--bonds", "B0031,B0041"]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    def write(tables):
        root = tmp_path / "tables"
        write_tables(tables, root)
        monkeypatch.delenv("E2C_SOURCE", raising=False)
        monkeypatch.setenv("E2C_DATA_ROOT", str(root))
        return tmp_path / "out"
    return write


def traded_tables():
    """B0031 is priced on the model with an injected gap, because synthetic.py's prices are noise. B0041 keeps those prices, with daily prints."""
    t = make_synthetic_tables()
    p = t["bond_prices"]
    t["bond_trades"] = daily_trades(p[p.bond_id.eq("B0041") & (p.date >= pd.Timestamp("2005-01-03"))])
    model_priced(t, "B0031", 0.02)
    return t


def test_end_to_end_writes_results_and_prints_no_rows(data, capsys):
    out = data(traded_tables())
    assert r.main(ARGS + ["--out", str(out)]) == 0
    trades, bonds = pd.read_csv(out / "trades.csv"), pd.read_csv(out / "bonds.csv").set_index("bond_id")
    assert len(trades) >= 1 and set(trades.bond_id) >= {"B0031"} and trades.hpr.notna().all()
    assert bonds.loc["B0031", "status"] == "ok" and bonds.loc["B0031", "trades"] >= 1 and bonds.loc["B0031", "tradable_days"] > 0
    assert list(bonds.index) == ["B0031", "B0041"]
    summary = (out / "summary.txt").read_text()
    assert f"N {len(trades)}" in summary and "bonds asked: 2" in summary and "B0031" not in summary
    printed = capsys.readouterr().out
    assert "B0031" not in printed and len(printed.splitlines()) <= 3


def test_default_finds_every_bond_and_lists_those_it_cannot_build(data):
    t = make_synthetic_tables()
    s = t["security_map"]
    t["security_map"] = pd.concat([s, s[s.instrument_id == "B0011"].assign(issuer_id="I002", valid_from=pd.Timestamp("2000-06-01"))], ignore_index=True)
    out = data(t)
    assert r.main(["--start", "2005-10-03", "--end", "2005-12-30", "--vol-source", "implied", "--hedge-id", "UST5Y", "--force", "--out", str(out)]) == 0
    bonds = pd.read_csv(out / "bonds.csv").set_index("bond_id")
    assert len(bonds) == 16 and bonds.loc["B0011", "status"] == "not_built: ValueError"
    assert bonds.status.eq("too_few_days").sum() > 0, "synthetic.py's weekly prints fail the liquidity screen, so these bonds give no trades"
    assert pd.read_csv(out / "trades.csv").empty


def test_stops_on_a_contract_failure_and_writes_only_the_report(data, capsys):
    t = make_synthetic_tables()
    t["rates"]["rate"] *= 100
    out = data(t)
    assert r.main(ARGS + ["--out", str(out)]) == r.EXIT_CONTRACT
    assert (out / "contract_report.csv").exists() and not (out / "summary.txt").exists() and not (out / "bonds.csv").exists()
    assert "units / rates" in capsys.readouterr().out


def test_force_carries_on_and_says_so(data):
    t = traded_tables()
    u = t["universe"]
    t["universe"] = u[u.end_date.isna()]
    out = data(t)
    assert r.main(ARGS + ["--out", str(out)]) == r.EXIT_CONTRACT
    assert r.main(ARGS + ["--out", str(out), "--force"]) == 0
    assert "forced past a failure: True" in (out / "summary.txt").read_text()


def test_no_bond_built_stops_cleanly(data):
    t = make_synthetic_tables()
    del t["bond_terms"]
    out = data(t)
    assert r.main(ARGS + ["--out", str(out), "--force"]) == r.EXIT_NO_DATA


def test_help_states_the_versioning_limit_and_needs_no_e2c_data():
    done = subprocess.run([sys.executable, "-I", str(Path(r.__file__)), "--help"], capture_output=True, text=True)
    assert done.returncode == 0 and "only accounts are versioned through time" in " ".join(done.stdout.split())
