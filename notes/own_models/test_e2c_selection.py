"""Tests for the hold band and the cap on names per side in e2c_model.py. These are additions. No workbook has them.

Run: pytest test_e2c_selection.py

The pinned panel numbers are in-sample, on a survivors-only panel. They guard the code, not the idea.
"""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import e2c_model as m

HERE = Path(__file__).resolve().parent
BAND = replace(m.MASTER_PARAMS, exit_trigger=3.0)
DATES = pd.date_range("2003-01-03", periods=8, freq="7D")


def path(residuals, ticker="A", gain=1.0, spread=100.0):
    """One name's rows. A None residual means no row that week."""
    rows = [(DATES[i], ticker, r, gain, spread) for i, r in enumerate(residuals) if r is not None]
    return pd.DataFrame(rows, columns=["date", "ticker", "residual", "gain", "spread_bp"])


def flags(frame, params):
    s = m.held_signal(frame.date, frame.ticker, frame.residual, frame.gain, frame.spread_bp, params)
    return (s["long_flag"] - s["short_flag"]).tolist()


def test_enters_past_the_trigger_and_holds_until_the_exit():
    assert flags(path([5, 7, 5, 3.5, 3, 5, 7]), BAND) == [0, 1, 1, 1, 0, 0, 1]


def test_short_side_mirrors_the_long_side():
    assert flags(path([-5, -7, -5, -3.5, -3, -5, -7]), BAND) == [0, -1, -1, -1, 0, 0, -1]


def test_flips_when_the_other_trigger_is_crossed():
    assert flags(path([7, -7, 7]), BAND) == [1, -1, 1]


def test_a_week_with_no_row_keeps_the_position():
    assert flags(path([7, None, 5, 2]), BAND) == [1, 1, 0]


def test_nan_residual_closes_the_position():
    assert flags(path([7, np.nan, 5]), BAND) == [1, 0, 0]


def test_spread_out_of_range_closes_and_blocks_entry():
    frame = path([7, 7, 7])
    frame["spread_bp"] = [100.0, 900.0, 100.0]
    assert flags(frame, replace(BAND, spread_cap=500.0)) == [1, 0, 1]


def test_cap_keeps_the_best_gain_per_cost_on_each_side():
    frame = pd.concat([path([7], "A", 1.0), path([7], "B", 3.0), path([7], "C", 2.0),
                       path([-7], "D", 1.0), path([-7], "E", 2.0)])
    got = dict(zip(frame.ticker, flags(frame, replace(BAND, max_per_side=2))))
    assert got == {"A": 0, "B": 1, "C": 1, "D": -1, "E": -1}


def test_cap_ranks_on_gain_not_on_residual_size():
    frame = pd.concat([path([20], "A", 1.0), path([7], "B", 5.0)])
    got = dict(zip(frame.ticker, flags(frame, replace(BAND, max_per_side=1))))
    assert got == {"A": 0, "B": 1}


def test_cap_does_not_replace_a_held_name_with_a_better_one():
    frame = pd.concat([path([7, 7], "A", 1.0), path([0, 7], "B", 9.0)])
    frame = frame.sort_values(["date", "ticker"])
    got = dict(zip(zip(frame.ticker, frame.date), flags(frame, replace(BAND, max_per_side=1))))
    assert got[("A", DATES[1])] == 1 and got[("B", DATES[1])] == 0


def test_a_held_name_with_no_row_still_uses_a_cap_slot():
    frame = pd.concat([path([7, None, 5], "A", 1.0), path([0, 7, 0], "B", 9.0)])
    frame = frame.sort_values(["date", "ticker"])
    got = dict(zip(zip(frame.ticker, frame.date), flags(frame, replace(BAND, max_per_side=1))))
    assert got[("B", DATES[1])] == 0


def test_flags_follow_the_input_row_order():
    frame = path([7, 5, 2])
    shuffled = frame.iloc[[2, 0, 1]]
    assert flags(shuffled, BAND) == [0, 1, 1]


@pytest.mark.parametrize("bad", [dict(exit_trigger=7.0), dict(exit_trigger=-1.0), dict(max_per_side=0)])
def test_bad_settings_raise(bad):
    with pytest.raises(ValueError):
        m.held_signal(DATES[:1], ["A"], [7.0], [1.0], [100.0], replace(m.MASTER_PARAMS, **bad))


def test_gain_per_cost_is_gain_over_cost_per_unit_of_notional():
    p = m.MASTER_PARAMS
    got = m.gain_per_cost(6.0, 0.01, 30.0, 4.0, 100.0, p)
    assert got == pytest.approx((0.01 * 30.0 / 30.0 * 6.0) / (4.0 * 100.0 / 1e4 * p.bid_offer))


def test_trading_cost_charges_half_the_round_trip_on_each_size_change():
    names = pd.DataFrame(dict(date=DATES[:3], ticker="A", size_long=[2.0, 2.0, 0.0], size_short=[0.0, 0.0, 0.0],
                              annuity=[4.0, 4.0, 4.0], spread_bp=[100.0, 100.0, 100.0]))
    got = m.trading_cost(names, 0.05)
    per_side = 2.0 * 1000 * 4.0 * 100.0 / 1e4 * 0.05 / 2      # $M notional to $ thousands
    assert got.tolist() == pytest.approx([per_side, 0.0, per_side])


def test_trading_cost_charges_a_flip_twice_and_skips_a_week_with_no_row():
    names = pd.DataFrame(dict(date=DATES[[0, 2]], ticker="A", size_long=[1.0, 0.0], size_short=[0.0, 1.0],
                              annuity=[1.0, 1.0], spread_bp=[100.0, 100.0]))
    got = m.trading_cost(names, 0.05)
    assert got.iloc[1] == pytest.approx(2 * got.iloc[0])


@pytest.fixture(scope="module")
def panel():
    return pd.read_csv(HERE / "master_panel.csv.gz", parse_dates=["date", "next_date"])


def net_sharpe(result, cost_rate=0.05):
    pnl = result["names"].groupby("date").pnl_total.sum()
    net = pnl - m.trading_cost(result["names"], cost_rate)
    return net.mean() / net.std() * np.sqrt(52)


def test_defaults_still_give_the_workbook_numbers(panel):
    result = m.run_pipeline(panel)
    assert result["summary"]["sharpe"] == pytest.approx(2.5106, abs=1e-4)
    assert "gain_per_cost" not in result["names"].columns


def test_exit_equal_to_the_trigger_gives_todays_book(panel):
    base = m.run_pipeline(panel)["names"]
    same = m.run_pipeline(panel, replace(m.MASTER_PARAMS, exit_trigger=6.0))["names"]
    assert (base.long_flag.to_numpy() == same.long_flag.to_numpy()).all()
    assert (base.short_flag.to_numpy() == same.short_flag.to_numpy()).all()
    assert same.pnl_total.sum() == pytest.approx(base.pnl_total.sum())


def test_hold_band_matches_the_separate_study(panel):
    # name_pick.py, written apart from this code: P&L 20,145, cost 8,711, net Sharpe 1.15.
    result = m.run_pipeline(panel, BAND)
    assert result["names"].pnl_total.sum() == pytest.approx(20145, abs=1)
    assert m.trading_cost(result["names"], 0.05).sum() == pytest.approx(8711, abs=1)
    assert net_sharpe(result) == pytest.approx(1.15, abs=0.005)


def test_next_week_fields_cannot_change_who_is_held(panel):
    params = replace(BAND, max_per_side=20)
    base = m.run_pipeline(panel, params)["names"]
    scrambled = panel.copy()
    rng = np.random.default_rng(0)
    for col in ("next_spread_bp", "next_price"):
        scrambled[col] = rng.permutation(scrambled[col].to_numpy())
    other = m.run_pipeline(scrambled, params)["names"]
    assert (base.long_flag.to_numpy() == other.long_flag.to_numpy()).all()
    assert (base.short_flag.to_numpy() == other.short_flag.to_numpy()).all()


def test_cap_is_respected_every_week(panel):
    names = m.run_pipeline(panel, replace(BAND, max_per_side=20))["names"]
    weekly = names.groupby("date")[["long_flag", "short_flag"]].sum()
    assert weekly.max().max() <= 20
