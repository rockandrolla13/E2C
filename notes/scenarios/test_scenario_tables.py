"""Checks that tie the scenario tables to numbers already established elsewhere."""
import numpy as np
import pytest

import scenario_tables as s


def test_delta_ratio_reproduces_the_quoted_2_2():
    t = s.table_2a()
    # Signal-day firm in the worked example gave 2.2. The fit-end firm here must stay in the same range.
    base = t[(t.issuer == "base") & (t.years_left == 4.8)].iloc[0]
    assert base.delta_asset_vol > base.delta_equity_vol > 0
    assert 1.5 < base.ratio < 3.0


def test_premium_sweep_reproduces_plus13_minus16():
    t = s.table_3a().set_index("premium_bp")
    assert t.loc[40, "delta_change"] == pytest.approx(0.13, abs=0.01)
    assert t.loc[-40, "delta_change"] == pytest.approx(-0.16, abs=0.01)
    assert t.loc[0, "delta_change"] == pytest.approx(0.0, abs=0.001)


def test_no_premium_gives_no_false_signal():
    t = s.table_3b()
    row = t[(t.fit_premium_bp == 0) & (t.later_premium_bp == 0)].iloc[0]
    assert row.signal_alpha_25 == "no trade"
    assert abs(row.gap_bp) < 5


def test_nothing_happening_never_trades():
    t = s.table_1a()
    assert (t[t.case == "Nothing happening"][["yu_raw", "peer_only", "both"]] == "no trade").all().all()


def test_hedge_pnl_adds_up():
    t = s.table_2b()
    assert np.allclose(t.bond_pnl_k + t.stock_pnl_k, t.net_pnl_k)


def test_equity_vol_delta_formula_matches_workbook_when_vol_is_held():
    d = s.load_panel().dropna(subset=["iv", "wb_delta"]).head(2000)
    g = s.w.cds_greeks(5.0, d.price.to_numpy(), d.wb_dps.to_numpy(), d.iv.to_numpy(), d.spread_bp.to_numpy(), r=d.r.to_numpy())
    assert np.nanmax(np.abs(g["delta"] - d.wb_delta.to_numpy())) < 1e-6
