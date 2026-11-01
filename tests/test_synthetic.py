"""Synthetic tables: every kind, every column, valid, repeatable, and written from the schema alone."""
import ast
import inspect

import pandas as pd

from e2c_data import synthetic
from e2c_data.schema import KINDS, all_columns
from e2c_data.synthetic import make_synthetic_tables


def test_imports_schema_only():
    mods = set()
    for n in ast.walk(ast.parse(inspect.getsource(synthetic))):
        if isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
        elif isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
    package = {m for m in mods if m.startswith("e2c_data")}
    assert package == {"e2c_data.schema"}


def test_every_kind_and_column_present():
    t = make_synthetic_tables()
    assert set(t) == set(KINDS)
    for kind, df in t.items():
        assert not df.empty, kind
        assert set(df.columns) == set(all_columns(KINDS[kind])), kind


def test_keys_are_unique_within_a_version():
    for kind, df in make_synthetic_tables().items():
        assert not df.duplicated(list(KINDS[kind].key) + ["available_at"]).any(), kind


def test_repeatable_and_seed_matters():
    a, b, c = make_synthetic_tables(seed=1), make_synthetic_tables(seed=1), make_synthetic_tables(seed=2)
    pd.testing.assert_frame_equal(a["equity_prices"], b["equity_prices"])
    assert not a["equity_prices"].stock_close.equals(c["equity_prices"].stock_close)


def test_holds_the_hard_cases_the_view_and_contract_need():
    t = make_synthetic_tables()
    acc = t["accounts"]
    assert acc.duplicated(["issuer_id", "period_end"]).any(), "a restatement"
    assert t["universe"].end_date.notna().sum() >= 2, "dead names"
    moved = t["security_map"].groupby("instrument_id").issuer_id.nunique()
    assert (moved > 1).any(), "an instrument that changes issuer"
    assert t["events"].event_type.isin(["default", "merger"]).sum() >= 2
    assert t["bond_trades"].action.isin(["correct", "cancel"]).any()


def test_dead_name_stops_trading():
    t = make_synthetic_tables()
    dead = t["universe"].dropna(subset=["end_date"]).iloc[0]
    equity = t["security_map"].query("issuer_id == @dead.issuer_id and instrument_type == 'equity'").instrument_id.iloc[0]
    assert t["equity_prices"].query("equity_id == @equity").date.max() <= dead.end_date
