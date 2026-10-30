"""Tests for e2c_bond.py. Run: python3 -m pytest test_e2c_bond.py -v -s

Tests named test_repro_* compare with a number printed in a source. They print the published
number, the computed number and the gap.
"""
import inspect
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import quad

import e2c_bond as m

BASE = m.Firm(S=30.0, D=28.0, sigma_s=0.38, L_bar=0.6, lam=0.3)
CURVE = m.flat_curve(0.04)
BOND = m.Bond(coupon=0.055, maturity=5.0)


# ------------------------------------------------------------------ limit checks

def test_survival_at_zero_is_one_only_without_barrier_noise():
    """The brief asked for q(0) = 1. That holds at lam = 0 only. Yu footnote 22 says so."""
    assert m.survival(0.0, replace(BASE, lam=0.0)) == pytest.approx(1.0, abs=1e-12)
    near = m.Firm(S=5.0, D=10.0, sigma_s=0.5)
    far = m.Firm(S=30.0, D=10.0, sigma_s=0.5)
    print(f"\n  1-q(0): S/D=0.5 -> {1 - m.survival(0.0, near):.5f}, S/D=3 -> {1 - m.survival(0.0, far):.2e}")
    assert 0.005 < 1 - m.survival(0.0, near) < 0.03
    assert 1 - m.survival(0.0, far) < 1e-8


def test_barrier_filter_trips_at_about_s_over_barrier_1_06():
    def firm(x):
        return m.Firm(S=x, D=1.0, sigma_s=0.4, L_bar=1.0, lam=0.3)
    assert m.passes_barrier_filter(firm(1.07))
    assert not m.passes_barrier_filter(firm(1.05))


def test_survival_falls_with_horizon():
    q = m.survival(np.linspace(0, 30, 121), BASE)
    assert np.all(np.diff(q) < 0)
    assert q[-1] > 0


def test_survival_rises_with_s_over_d():
    q = [m.survival(5.0, replace(BASE, S=x * BASE.D)) for x in (0.25, 0.5, 1, 2, 4, 8)]
    assert np.all(np.diff(q) > 0)


def test_survival_falls_with_vol():
    q = [m.survival(5.0, replace(BASE, sigma_s=v)) for v in (0.1, 0.2, 0.4, 0.8, 1.6)]
    assert np.all(np.diff(q) < 0)


def test_model_depends_on_debt_only_through_barrier():
    a = m.Firm(S=20, D=10, sigma_s=0.4, L_bar=0.5)
    b = m.Firm(S=20, D=5, sigma_s=0.4, L_bar=1.0)
    assert m.cds_par_spread(5, a, 0.5, 0.05) == pytest.approx(m.cds_par_spread(5, b, 0.5, 0.05), rel=1e-12)


def test_zero_coupon_with_zero_recovery_has_z_equal_to_hazard():
    """With R = 0 and no coupons, P = DF(T) q(T), so Z = -ln(q(T)) / T exactly."""
    zero = m.Bond(coupon=0.0, maturity=5.0)
    z = m.model_z_spread(zero, BASE, CURVE, R_b=0.0)
    assert z == pytest.approx(-np.log(m.survival(5.0, BASE)) / 5.0, abs=1e-8)


def test_zero_coupon_price_splits_into_survival_and_recovery():
    zero = m.Bond(coupon=0.0, maturity=5.0)
    expected = CURVE.df(5.0) * m.survival(5.0, BASE) + 0.5 * m.default_leg(5.0, BASE, CURVE)
    assert m.risky_bond_price(zero, BASE, CURVE, 0.5) == pytest.approx(expected, abs=1e-12)


def test_bond_tends_to_riskless_price_far_from_default():
    safe = m.Firm(S=1e5, D=1.0, sigma_s=0.2, L_bar=0.5)
    t, cf = m.cash_flows(BOND)
    assert m.risky_bond_price(BOND, safe, CURVE, 0.5) == pytest.approx(np.sum(cf * CURVE.df(t)), abs=1e-9)
    assert m.model_z_spread(BOND, safe, CURVE, 0.5) == pytest.approx(0.0, abs=1e-8)


def test_cash_flows_and_accrued_on_a_stub():
    b = m.Bond(coupon=0.06, maturity=4.8)
    t, cf = m.cash_flows(b)
    assert t[0] == pytest.approx(0.3)
    assert t[-1] == pytest.approx(4.8)
    assert cf.sum() == pytest.approx(10 * 0.03 + 1.0)
    assert m.accrued_interest(b) == pytest.approx(0.06 * 0.2)


# ------------------------------------------------------------------ closed forms against integrals

def test_h_closed_form_matches_integral_of_density():
    r = 0.05
    density = lambda s: -(m.survival(s + 1e-5, BASE) - m.survival(s - 1e-5, BASE)) / 2e-5
    numeric = quad(lambda s: np.exp(-r * s) * density(s), 2e-5, 5.0, limit=200)[0]
    assert m.discounted_default(5.0, BASE, r) == pytest.approx(numeric, abs=2e-6)


def test_annuity_closed_form_matches_integral():
    r = 0.05
    numeric = quad(lambda s: np.exp(-r * s) * m.survival(s, BASE), 0, 5.0)[0]
    assert m.cds_annuity(5.0, BASE, r) == pytest.approx(numeric, abs=1e-9)


def test_yu_eq14_as_printed_is_a_misprint():
    """Printed Eq. (14) has G(T) where the correct form has G(xi). It breaks the riskless cap."""
    f, r, T = m.Firm(S=30, D=30, sigma_s=0.25 * 45 / 30, L_bar=0.5), 0.05, 5.0
    xi = f.lam ** 2 / m.asset_vol(f) ** 2
    q0, qT = m.survival(0.0, f), m.survival(T, f)
    printed = (q0 - qT * np.exp(-r * T) - np.exp(r * xi) * (m._g(T + xi, f, r) - m._g(T, f, r))) / r
    correct = m.cds_annuity(T, f, r)
    numeric = quad(lambda s: np.exp(-r * s) * m.survival(s, f), 0, T)[0]
    cap = (1 - np.exp(-r * T)) / r
    print(f"\n  Eq.14 as printed {printed:.4f} | with G(xi) {correct:.4f} | integral {numeric:.4f} | riskless cap {cap:.4f}")
    assert correct == pytest.approx(numeric, abs=1e-9)
    assert printed > cap


def test_default_leg_on_flat_curve_matches_closed_form():
    r = 0.04
    closed = 1 - m.survival(0.0, BASE) + m.discounted_default(5.0, BASE, r)
    assert m.default_leg(5.0, BASE, m.flat_curve(r)) == pytest.approx(closed, abs=2e-6)


def test_closed_form_switches_to_quadrature_where_it_loses_precision():
    """At S/D = 0.1 and low vol, the printed closed form is off by hundreds of bp."""
    vols = np.geomspace(0.02, 3.0, 150)
    spreads = [m.cds_par_spread(5, m.Firm(S=0.1, D=1.0, sigma_s=v), 0.5, 0.05) for v in vols]
    assert np.all(np.diff(spreads) > 0)


# ------------------------------------------------------------------ round trips

@pytest.mark.parametrize("sd,vol", [(0.75, 0.6), (1.0, 0.45), (2.0, 0.35), (4.0, 0.3), (1.5, 0.9)])
def test_round_trip_cds_spread_to_vol_to_spread(sd, vol):
    f = m.Firm(S=sd, D=1.0, sigma_s=vol, L_bar=0.5)
    c = m.cds_par_spread(5, f, 0.5, 0.05)
    out = m.implied_vol_cds(c, 5, replace(f, sigma_s=0.2), 0.5, 0.05)
    assert out.status == "ok"
    assert out.sigma_s == pytest.approx(vol, abs=1e-6)
    assert m.cds_par_spread(5, replace(f, sigma_s=out.sigma_s), 0.5, 0.05) == pytest.approx(c, abs=1e-9)


@pytest.mark.parametrize("vol", [0.25, 0.38, 0.6, 1.0])
def test_round_trip_bond_spread_to_vol_to_spread(vol):
    f = replace(BASE, sigma_s=vol)
    z = m.model_z_spread(BOND, f, CURVE, 0.5)
    out = m.implied_vol_bond(z, BOND, replace(f, sigma_s=0.2), CURVE, 0.5)
    assert out.status == "ok"
    assert out.sigma_s == pytest.approx(vol, abs=1e-5)


def test_round_trip_price_to_z_to_price():
    z = 0.0213
    assert m.z_spread(m.price_from_z(z, BOND, CURVE), BOND, CURVE) == pytest.approx(z, abs=1e-9)


def test_barrier_calibration_recovers_a_known_barrier():
    truth = 0.62
    stocks = 30.0 + np.array([0.1, -0.1, 0.2, 0.0, -0.2, 0.1, 0.3, 0.0, -0.1, 0.2])
    make = lambda L, s: replace(BASE, S=float(s), L_bar=L)
    market = [m.model_z_spread(BOND, make(truth, s), CURVE, 0.5) for s in stocks]
    fit, rmse = m.calibrate_barrier(lambda L: [m.model_z_spread(BOND, make(L, s), CURVE, 0.5) for s in stocks], market)
    assert fit == pytest.approx(truth, abs=1e-3)
    assert rmse < 1e-6


# ------------------------------------------------------------------ inversion failure cases

def test_cds_inversion_reports_spread_below_floor():
    """Barrier noise gives a positive spread even at zero vol, so tighter quotes have no root."""
    f = m.Firm(S=5.0, D=10.0, sigma_s=0.3, L_bar=0.5)
    floor = m.cds_par_spread(5, replace(f, sigma_s=0.01), 0.5, 0.05)
    print(f"\n  CDS spread floor at S/D=0.5, vol 1%: {floor * 1e4:.1f} bp")
    assert m.implied_vol_cds(floor * 0.5, 5, f, 0.5, 0.05).status == "below_floor"


def test_bond_inversion_reports_spread_below_floor_on_negative_z():
    assert m.implied_vol_bond(-0.002, BOND, BASE, CURVE, 0.5).status == "below_floor"


def test_bond_inversion_reports_ceiling_when_price_is_under_every_model_price():
    z = m.z_spread(0.62, BOND, CURVE)
    assert m.implied_vol_bond(z, BOND, BASE, CURVE, 0.5, recovery_buffer=0.1).status == "ok"
    below_recovery = m.z_spread(0.45, BOND, CURVE)
    assert m.implied_vol_bond(below_recovery, BOND, BASE, CURVE, 0.5, recovery_buffer=-1.0).status == "above_ceiling"


def test_bond_inversion_refuses_a_price_near_recovery():
    """The guard is on by default. recovery_buffer=-1 turns it off in the two tests around this one."""
    z = m.z_spread(0.55, BOND, CURVE)
    assert m.implied_vol_bond(z, BOND, BASE, CURVE, 0.5).status == "near_recovery"


def test_bond_inversion_finds_two_roots_on_a_long_low_coupon_bond():
    """Coupon under the riskless rate, price under recovery on the way: price turns back up."""
    bond = m.Bond(coupon=0.02, maturity=20.0)
    curve = m.flat_curve(0.06)
    f = m.Firm(S=1.0, D=1.0, sigma_s=0.3, L_bar=0.5)
    z = m.z_spread(0.48, bond, curve)
    out = m.implied_vol_bond(z, bond, f, curve, 0.5, recovery_buffer=-1.0)
    print(f"\n  price 0.48, coupon 2%, 20y, r 6%: status {out.status}, roots {np.round(out.roots, 3)}")
    assert out.status == "multiple"
    assert len(out.roots) == 2


def test_cds_spread_rises_with_vol_so_a_cds_root_is_unique():
    for sd in (0.2, 0.5, 1, 3):
        vols = np.geomspace(0.03, 3.0, 100)
        c = [m.cds_par_spread(5, m.Firm(S=sd, D=1.0, sigma_s=v), 0.5, 0.05) for v in vols]
        assert np.all(np.diff(c) > 0)


# ------------------------------------------------------------------ bond against CDS

def test_identity_continuous_coupon_price_is_exact():
    """Continuous coupon, recovery of face, flat r: P = 1 + (C - r - c) * annuity, exactly."""
    r, C, R, T = 0.04, 0.07, 0.5, 5.0
    c = m.cds_par_spread(T, BASE, R, r)
    annuity = m.cds_annuity(T, BASE, r)
    price = C * annuity + np.exp(-r * T) * m.survival(T, BASE) + R * (1 - m.survival(0.0, BASE) + m.discounted_default(T, BASE, r))
    assert price == pytest.approx(1 + (C - r - c) * annuity, abs=1e-12)


def _par_coupon(firm, T, curve, R, freq):
    from scipy.optimize import brentq
    return brentq(lambda C: m.risky_bond_price(m.Bond(C, T, freq), firm, curve, R) - 1.0, 0.0, 1.0, xtol=1e-12)


@pytest.mark.parametrize("sd,vol", [(3.0, 0.3), (1.0, 0.38), (1.0, 0.6), (0.75, 0.8)])
def test_par_bond_z_spread_is_close_to_cds_spread(sd, vol):
    """The gap vanishes as coupons become continuous, and the rest is the lost accrued coupon.

    For a flat hazard h = c / (1 - R), algebra gives Z - c = (r + c) * R * h / (2 * freq).
    """
    f = m.Firm(S=sd, D=1.0, sigma_s=vol, L_bar=0.5)
    r, R, T = 0.04, 0.5, 5.0
    curve = m.flat_curve(r)
    c = m.cds_par_spread(T, f, R, r)
    gaps = {}
    for freq in (2, 12, 365):
        C = _par_coupon(f, T, curve, R, freq)
        gaps[freq] = (m.z_spread(1.0, m.Bond(C, T, freq), curve) - c) * 1e4
    formula = (r + c) * R * (c / (1 - R)) / (2 * 2) * 1e4
    print(f"\n  S/D {sd} vol {vol}: CDS {c * 1e4:.1f} bp; par Z minus CDS: semiannual {gaps[2]:+.2f} bp "
          f"(formula {formula:+.2f}), monthly {gaps[12]:+.2f} bp, daily {gaps[365]:+.2f} bp")
    assert abs(gaps[365]) < 0.5
    assert gaps[2] == pytest.approx(formula, abs=0.5 + 0.1 * formula)
    assert abs(gaps[12]) < abs(gaps[2]) or abs(gaps[2]) < 0.1


def test_discount_bond_z_is_below_and_premium_bond_z_is_above_the_cds_spread():
    """Recovery of face: a bond at a discount loses less in default than a par bond."""
    f = m.Firm(S=1.0, D=1.0, sigma_s=0.6, L_bar=0.5)
    r, R = 0.04, 0.5
    curve = m.flat_curve(r)
    c = m.cds_par_spread(5, f, R, r)
    low = m.model_z_spread(m.Bond(0.02, 5.0), f, curve, R)
    high = m.model_z_spread(m.Bond(0.14, 5.0), f, curve, R)
    print(f"\n  CDS {c * 1e4:.1f} bp | Z of 2% coupon {low * 1e4:.1f} bp | Z of 14% coupon {high * 1e4:.1f} bp")
    assert low < c < high


def test_par_bond_delta_equals_cds_delta_in_size():
    """From P = 1 + (C - r - c) A: at par, dP/dS = -A dc/dS, the CDS delta with its sign flipped."""
    r, R, T = 0.04, 0.5, 5.0
    curve = m.flat_curve(r)
    C = _par_coupon(BASE, T, curve, R, 365)
    bond_delta = m.bond_equity_delta(m.Bond(C, T, 365), BASE, curve, R)
    cds_delta = m.cds_equity_delta(T, BASE, R, r)
    print(f"\n  par bond delta {bond_delta:.6f} | CDS delta {cds_delta:.6f}")
    assert bond_delta == pytest.approx(-cds_delta, rel=0.01)


def test_delta_holding_asset_vol_is_larger_than_holding_equity_vol():
    fixed_asset = m.bond_equity_delta(BOND, BASE, CURVE, 0.5, hold="asset_vol")
    fixed_equity = m.bond_equity_delta(BOND, BASE, CURVE, 0.5, hold="equity_vol")
    print(f"\n  delta holding asset vol {fixed_asset:.5f} | holding equity vol {fixed_equity:.5f}")
    assert fixed_asset > fixed_equity > 0


# ------------------------------------------------------------------ signal and exit

def test_entry_signal_follows_eq8():
    assert m.entry_signal(151, 100, 0.5) == 1
    assert m.entry_signal(150, 100, 0.5) == 0
    assert m.entry_signal(100, 151, 0.5) == -1
    assert m.entry_signal(100, 150, 0.5) == 0
    assert m.entry_signal(-5, 100, 0.5) == 0
    assert m.entry_signal(100, 0, 0.5) == 0


def test_log_gap_form_fires_on_the_same_days_as_eq8():
    for market, model in [(151, 100), (149, 100), (100, 151), (100, 149)]:
        fired = abs(m.log_gap(market, model)) > np.log(1.5)
        assert fired == (m.entry_signal(market, model, 0.5) != 0)


def test_vol_space_and_spread_space_agree_on_the_sign_and_the_crossing():
    """Model Z rises with vol here, so vol-implied > observed exactly when market Z > model Z."""
    model = m.model_z_spread(BOND, BASE, CURVE, 0.5)
    for factor in (0.5, 0.9, 1.1, 2.0):
        out = m.implied_vol_bond(model * factor, BOND, BASE, CURVE, 0.5)
        assert out.status == "ok"
        assert np.sign(out.sigma_s - BASE.sigma_s) == np.sign(factor - 1)


def test_exit_rules():
    assert m.exit_reason(1, 110, 100, 5, 180, -0.01) == "limited_liability"
    assert m.exit_reason(1, 99, 100, 5, 180, 0.5) == "convergence"
    assert m.exit_reason(-1, 101, 100, 5, 180, 0.5) == "convergence"
    assert m.exit_reason(1, 110, 100, 180, 180, 0.5) == "holding_period"
    assert m.exit_reason(1, 110, 100, 179, 180, 0.5) is None


def test_bond_exit_rules():
    kw = dict(side=1, market=110, model=100, days_held=5, max_hold=180, value=0.5)
    assert m.bond_exit_reason(**kw, years_left=0.9, days_since_price=1) == "under_one_year"
    assert m.bond_exit_reason(**kw, years_left=4, days_since_price=15) == "no_price_14_days"
    assert m.bond_exit_reason(**kw, years_left=4, days_since_price=1, forced_event="merger") == "merger"
    assert m.bond_exit_reason(**kw, years_left=4, days_since_price=1, max_drawdown=0.2, peak_value=0.7) == "drawdown_stop"
    assert m.bond_exit_reason(**kw, years_left=4, days_since_price=1) is None


def test_cost_gate():
    assert m.passes_cost_gate(0.03, 0.02, 4.0, 0.01)
    assert not m.passes_cost_gate(0.03, 0.02, 4.0, 0.03)


# ------------------------------------------------------------------ P&L

PREV = m.Marks(bond_clean=0.98, bond_accrued=0.01, stock=30.0, hedge_full=1.0)
NO_CARRY = m.Carry(repo=0, bond_fee=0, stock_fee=0, cash_rate=0, hedge_repo=0, dt=1 / 360)
LONG = m.Position(side=1, face=1.0, shares=0.01, hedge_face=0.9)
SHORT = m.Position(side=-1, face=1.0, shares=0.01, hedge_face=0.9)


def test_pnl_is_zero_when_nothing_moves_and_carry_is_zero():
    assert m.daily_pnl(LONG, PREV, PREV, NO_CARRY)["total"] == pytest.approx(0.0, abs=1e-15)


def test_pnl_legs_sum_to_total():
    now = m.Marks(0.985, 0.0102, 29.5, 1.002, dividend=0.1)
    carry = m.Carry(0.04, 0.005, 0.01, 0.04, 0.04, 1 / 360)
    legs = m.daily_pnl(LONG, PREV, now, carry)
    assert sum(v for k, v in legs.items() if k != "total") == pytest.approx(legs["total"], abs=1e-15)


def test_pnl_signs_for_each_direction():
    spread_tighter = m.Marks(0.99, 0.01, 30.0, 1.0)
    assert m.daily_pnl(LONG, PREV, spread_tighter, NO_CARRY)["bond_price"] > 0
    assert m.daily_pnl(SHORT, PREV, spread_tighter, NO_CARRY)["bond_price"] < 0
    stock_down = m.Marks(0.98, 0.01, 29.0, 1.0)
    assert m.daily_pnl(LONG, PREV, stock_down, NO_CARRY)["stock_price"] == pytest.approx(0.01)
    assert m.daily_pnl(SHORT, PREV, stock_down, NO_CARRY)["stock_price"] == pytest.approx(-0.01)


def test_coupon_day_is_a_wash_for_the_full_price():
    """The full price falls by the coupon on the payment date, and the holder gets the coupon."""
    now = m.Marks(bond_clean=0.98, bond_accrued=0.0, stock=30.0, hedge_full=1.0, bond_coupon=0.01)
    assert m.daily_pnl(LONG, PREV, now, NO_CARRY)["bond_price"] == pytest.approx(0.0, abs=1e-15)


def test_ex_dividend_day_is_a_wash_for_the_short():
    now = m.Marks(0.98, 0.01, 29.5, 1.0, dividend=0.5)
    assert m.daily_pnl(LONG, PREV, now, NO_CARRY)["stock_price"] == pytest.approx(0.0, abs=1e-15)


def test_financing_directions():
    c = m.Carry(repo=0.04, bond_fee=0.005, stock_fee=0.01, cash_rate=0.04, hedge_repo=0.04, dt=1.0)
    long_legs = m.daily_pnl(LONG, PREV, PREV, c)
    short_legs = m.daily_pnl(SHORT, PREV, PREV, c)
    assert long_legs["bond_financing"] == pytest.approx(-0.99 * 0.04)
    assert short_legs["bond_financing"] == pytest.approx(0.99 * 0.035)
    assert long_legs["stock_financing"] == pytest.approx(0.01 * 30 * 0.03)
    assert short_legs["stock_financing"] == pytest.approx(-0.01 * 30 * 0.04)
    assert long_legs["hedge_financing"] == pytest.approx(0.9 * 0.04)
    assert short_legs["hedge_financing"] == pytest.approx(-0.9 * 0.04)


def test_trade_cost_is_positive_and_adds_up():
    assert m.trade_cost(LONG, PREV, 0.005, 0.0005, 0.0001) == pytest.approx(0.005 + 0.01 * 30 * 0.0005 + 0.9 * 0.0001)


def test_account_value_and_return():
    v, ret = m.next_account_value(0.5, 0.01)
    assert (v, ret) == (pytest.approx(0.51), pytest.approx(0.02))


def test_monthly_index_equal_weights_live_trades_and_zeroes_empty_months():
    daily = np.array([[0.01, np.nan], [0.01, 0.03], [np.nan, np.nan], [np.nan, np.nan]])
    months = np.array([1, 1, 2, 2])
    out = m.monthly_index(daily, months)
    assert out[0] == pytest.approx(1.01 * 1.02 - 1)
    assert out[1] == 0.0


# ------------------------------------------------------------------ reproductions of published numbers

def test_repro_creditgrades_table_c1_all_156_cells():
    """CreditGrades Appendix C, printed p. 49: L=0.5, lam=0.3, R=0.5, r=5%, 5-year."""
    out = m.check_table_c1()
    print(f"\n  Table C.1: {out['cells_matching']}/156 cells match after rounding to whole bp. Largest gap {out['largest_gap_bp']:.3f} bp."
          f"\n  S/D=0.5, vol 80%: published {m.CG_TABLE_C1[0, -1]:.0f} bp, ours {out['grid_bp'][0, -1]:.2f} bp."
          f"\n  Without the Act/360 scaling the largest gap is {out['largest_gap_unscaled_bp']:.2f} bp.")
    assert out["cells_matching"] == 156
    assert out["largest_gap_bp"] <= 0.5
    assert out["largest_gap_unscaled_bp"] > 10


def test_repro_creditgrades_worldcom_scores():
    """CreditGrades p. 36: S=13 gives 249 bp and S=14 gives 224 bp at D=9, asset vol 40%."""
    at5, at52 = m.check_worldcom(0.05), m.check_worldcom(0.052)
    print(f"\n  WorldCom r=5.0%: published 249/224, ours {at5['score_13_bp']:.1f}/{at5['score_14_bp']:.1f}"
          f"\n  WorldCom r=5.2%: published 249/224, ours {at52['score_13_bp']:.1f}/{at52['score_14_bp']:.1f}")
    assert at5["score_13_bp"] == pytest.approx(249, abs=1)
    assert at5["score_14_bp"] == pytest.approx(224, abs=1)
    assert round(at52["score_13_bp"]) == 249
    assert round(at52["score_14_bp"]) == 224


def test_repro_creditgrades_worldcom_hedge_ratio():
    """CreditGrades p. 36: about four years of spread duration, 25 bp per $1 of stock, 7.7:1.

    The document uses the finite move from $13 to $14, so the main figure does too.
    """
    out = m.check_worldcom(0.05)
    print(f"\n  tightening {out['tightening_bp']:.1f} bp (published 25); annuity {out['annuity']:.2f} (about 4); "
          f"notional to stock {out['hedge_ratio']:.1f}:1 (published 7.7:1); local derivative {out['local_hedge_ratio']:.1f}:1; "
          f"holding equity vol instead {out['equity_vol_hedge_ratio']:.1f}:1")
    assert out["tightening_bp"] == pytest.approx(25, abs=1)
    assert out["annuity"] == pytest.approx(4.0, abs=0.1)
    assert out["hedge_ratio"] == pytest.approx(7.7, abs=0.3)


def test_repro_creditgrades_figure_2_2_read_from_the_chart():
    """Figure 2.2, printed p. 14. No table exists. Values were read by eye from the plot."""
    read = {0.1: 130, 0.2: 320, 0.3: 680, 0.4: 1120}
    for lam, published in read.items():
        f = m.Firm(S=1.0, D=2.0, sigma_s=0.5, L_bar=0.5, lam=lam)   # V0/(LD) = 2, sigma = 0.25
        ours = -np.log(m.survival(1.0, f)) * 1e4
        print(f"\n  lam={lam}: 1-year default rate, chart about {published} bp, ours {ours:.0f} bp", end="")
        assert ours == pytest.approx(published, abs=15)


def test_repro_creditgrades_figure_2_3_read_from_the_chart():
    """Figure 2.3, printed p. 15: contingent-leg delta at S=3, per USD 1,000, D=30, R=0.3.

    r is not stated. r=5% is assumed. Values were read by eye from the plot.
    """
    read = {0.20: -47, 0.25: -40, 0.30: -34, 0.35: -29, 0.40: -24.5}

    for sig, published in read.items():
        sigma_s = sig * 18 / 3
        f = m.Firm(S=3.0, D=30, sigma_s=sigma_s, L_bar=0.5, lam=0.3, S_ref=3.0)
        up = 0.7 * (1 - m.survival(0.0, replace(f, S=3.01)) + m.discounted_default(5.0, replace(f, S=3.01), 0.05))
        dn = 0.7 * (1 - m.survival(0.0, replace(f, S=2.99)) + m.discounted_default(5.0, replace(f, S=2.99), 0.05))
        ours = 1000 * (up - dn) / 0.02
        print(f"\n  asset vol {sig:.0%}: delta at S=3, chart about {published}, ours {ours:.1f}", end="")
        assert ours == pytest.approx(published, abs=1.5)


@pytest.mark.parametrize("mean,std,published", [
    (0.13, 1.13, 0.39), (0.13, 1.33, 0.35), (0.30, 1.27, 0.80), (0.67, 3.16, 0.74), (1.01, 4.63, 0.76), (0.93, 4.32, 0.74),
    (0.27, 1.27, 0.72), (0.25, 1.50, 0.57), (0.32, 1.29, 0.87), (0.16, 1.26, 0.45), (0.19, 1.39, 0.48), (0.33, 1.26, 0.89),
    (0.22, 1.31, 0.58), (0.23, 1.53, 0.52), (0.32, 1.31, 0.84), (0.17, 1.69, 0.36), (0.07, 1.58, 0.15), (0.19, 1.40, 0.47),
])
def test_repro_yu_sharpe_is_root_12_mean_over_std(mean, std, published):
    """Yu Tables 4 and 7. Rounded inputs give a range, and the published Sharpe must lie inside."""
    lo = np.sqrt(12) * (mean - 0.005) / (std + 0.005)
    hi = np.sqrt(12) * (mean + 0.005) / (std - 0.005)
    assert lo - 0.005 <= published <= hi + 0.005


def test_repro_yu_bid_ask_examples():
    """Yu pp. 11-12: 100 bp gives 102.5 and 97.5. 1,000 bp gives a 50 bp bid/ask."""
    half = lambda c: 0.05 * c / 2
    assert 100 + half(100) == 102.5
    assert 100 - half(100) == 97.5
    assert 2 * half(1000) == 50


def test_repro_yu_hanson_arithmetic():
    """Yu p. 1, an account from Euromoney: EUR 10m CDS, 95 to 140 bp, EUR 195,000 profit."""
    implied_annuity = 195_000 / (10_000_000 * (140 - 95) * 1e-4)
    equity_gain = 1_200_000 * (2.95 / 2.91 - 1)
    print(f"\n  Hanson: implied annuity {implied_annuity:.2f} years; equity gain, published 16,000, ours {equity_gain:,.0f}")
    assert 4.0 < implied_annuity < 4.6
    assert equity_gain == pytest.approx(16_000, abs=1_000)


def test_consistency_yu_altria_liquidation_is_about_minus_100_percent():
    """Yu p. 21: short CDS at 299, market at 529 four days later, capital 0.1, about -100%.

    Yu does not publish the inputs needed to reproduce this, so this is a size check only.
    Assumed: annuity from a 168 bp model spread with R=0.5 and r=3%, stock leg ignored.
    """
    hazard = 0.0168 / 0.5
    r = 0.03
    annuity = (1 - np.exp(-(hazard + r) * 5)) / (hazard + r)
    entry = 299 * 0.975
    exit_ = 529 * 1.025
    loss = (exit_ - entry) * 1e-4 * annuity - entry * 1e-4 * 4 / 365
    print(f"\n  Altria: loss {loss:.4f} on capital 0.10, or {-loss / 0.1:.0%} before the stock hedge; paper says -100%")
    assert 0.9 < loss / 0.1 < 1.2


# ------------------------------------------------------------------ Part 1: universe

def test_issuer_filter_follows_yu():
    assert m.issuer_is_eligible("industrial", True)
    assert not m.issuer_is_eligible("Financial", True)
    assert not m.issuer_is_eligible("utility", True)
    assert not m.issuer_is_eligible("industrial", False)


def test_bond_terms_filter():
    ok = dict(seniority="senior_unsecured", currency="USD", coupon_type="fixed", call_type="make_whole",
              is_convertible=False, is_putable=False, is_sinking=False, is_perpetual=False, is_pik=False)
    assert m.bond_terms_are_eligible(**ok)
    assert m.bond_terms_are_eligible(**{**ok, "call_type": "fixed_price"})
    for change in ({"seniority": "secured"}, {"currency": "EUR"}, {"coupon_type": "floating"}, {"is_convertible": True},
                   {"is_putable": True}, {"is_sinking": True}, {"is_perpetual": True}, {"is_pik": True}):
        assert not m.bond_terms_are_eligible(**{**ok, **change})


def test_callable_filter():
    assert m.callable_is_usable("make_whole", 1.10, float("nan"))
    assert m.callable_is_usable("fixed_price", 0.97, 1.03)
    assert not m.callable_is_usable("fixed_price", 1.00, 1.03)


def test_maturity_filter():
    assert m.maturity_is_eligible(5.0, True)
    assert not m.maturity_is_eligible(9.0, True)
    assert m.maturity_is_eligible(9.0, False)
    assert not m.maturity_is_eligible(12.0, False)


def test_age_and_size_filter():
    assert m.age_and_size_are_eligible(0.5, 4.0, 300e6)
    assert not m.age_and_size_are_eligible(0.1, 4.0, 300e6)
    assert not m.age_and_size_are_eligible(0.5, 0.9, 300e6)
    assert not m.age_and_size_are_eligible(0.5, 4.0, 200e6)


def test_pick_bond_and_sibling():
    assert m.pick_bond_and_sibling(["a", "b", "c"], [5, 50, 20]) == ("b", "c")
    assert m.pick_bond_and_sibling(["a"], [5]) == ("a", None)


def test_liquidity_screen():
    assert m.passes_liquidity_screen(10)
    assert not m.passes_liquidity_screen(9)


# ------------------------------------------------------------------ Part 2: inputs

def test_debt_per_share():
    assert m.debt_per_share(14_000e6, 500e6) == 28.0


def test_filing_usable_from():
    assert m.filing_usable_from("2024-05-07", "2024-03-31", "10-Q") == np.datetime64("2024-05-08")   # Tuesday
    assert m.filing_usable_from("2024-05-10", "2024-03-31", "10-Q") == np.datetime64("2024-05-13")   # Friday
    assert m.filing_usable_from("2024-05-11", "2024-03-31", "10-Q") == np.datetime64("2024-05-13")   # Saturday
    assert m.filing_usable_from("NaT", "2023-03-31", "10-Q") == np.datetime64("2023-05-15")
    assert m.filing_usable_from("NaT", "2023-12-31", "10-K") == np.datetime64("2024-04-01")          # rolls off a Saturday


def test_debt_after_corporate_action_keeps_the_model_spread():
    before = m.Firm(S=30.0, D=28.0, sigma_s=0.38, L_bar=0.8)
    d = m.debt_after_corporate_action(before, 27.0, 5.0, 0.5, 0.04)
    after = replace(before, S=27.0, D=d)
    assert m.cds_par_spread(5, after, 0.5, 0.04) == pytest.approx(m.cds_par_spread(5, before, 0.5, 0.04), abs=1e-9)
    assert d < 28.0


def test_historical_vol():
    r = np.tile([0.01, -0.01], 600)
    assert m.historical_equity_vol(r) == pytest.approx(0.01 * np.sqrt(1000 / 999) * np.sqrt(252), rel=1e-9)
    assert np.isnan(m.historical_equity_vol(r[:700]))
    assert np.isfinite(m.historical_equity_vol(r[:750]))
    regime = np.concatenate([np.tile([0.05, -0.05], 500), np.tile([0.01, -0.01], 500)])
    assert m.historical_equity_vol(regime) == pytest.approx(0.01 * np.sqrt(1000 / 999) * np.sqrt(252), rel=1e-9)


def test_equity_vol_input_refuses_an_unknown_source():
    assert m.equity_vol_input("implied", 0.3, 0.4) == 0.4
    assert m.equity_vol_input("historical", 0.3, 0.4) == 0.3
    with pytest.raises(ValueError):
        m.equity_vol_input("blend", 0.3, 0.4)


def test_zero_curve_flat_par_yields():
    curve = m.zero_curve_from_par_yields([0.25, 1, 2, 5, 10], [0.04] * 5)
    assert np.interp(5.0, curve.tenors, curve.zeros) == pytest.approx(2 * np.log(1.02), abs=1e-12)
    assert curve.zeros[0] == pytest.approx(np.log(1 + 0.04 * 0.25) / 0.25, abs=1e-12)


def test_zero_curve_prices_par_bonds_at_par():
    tenors, par = [0.5, 1, 2, 3, 5, 7, 10], [0.043, 0.041, 0.039, 0.0385, 0.0395, 0.041, 0.043]
    curve = m.zero_curve_from_par_yields(tenors, par)
    for t, y in zip(tenors, par):
        assert m.price_from_z(0.0, m.Bond(y, float(t)), curve) == pytest.approx(1.0, abs=1e-12)


# ------------------------------------------------------------------ Part 3: market spread

def test_clean_trade_reports():
    seq = [1, 2, 3, 4, 5, 6, 7, 8]
    orig = [0, 0, 2, 0, 4, 0, 6, 0]
    action = ["new", "new", "cancel", "new", "correct", "new", "reverse", "new"]
    dup = [False, False, False, False, False, False, False, True]
    keep = m.clean_trade_reports(seq, orig, action, dup)
    assert list(np.array(seq)[keep]) == [1, 5]


def test_clean_trade_reports_drops_a_correction_that_is_later_cancelled():
    keep = m.clean_trade_reports([1, 2, 3], [0, 1, 2], ["new", "correct", "cancel"], [False] * 3)
    assert not keep.any()


def test_fix_decimal_shifts():
    fixed = m.fix_decimal_shifts([98.5, 98.6, 985.0, 98.4, 98.7, 9.87, 98.5])
    assert fixed[2] == pytest.approx(98.5)
    assert fixed[5] == pytest.approx(98.7)
    assert fixed[0] == 98.5


def test_fix_decimal_shifts_leaves_a_real_fall_alone():
    real = [98.0, 97.0, 90.0, 89.0, 88.0, 87.0, 86.0]
    assert list(m.fix_decimal_shifts(real)) == real


def test_flag_price_spikes():
    spike = [100.0] * 5 + [60.0] + [100.0] * 4
    assert list(np.flatnonzero(m.flag_price_spikes(spike))) == [5]
    assert not m.flag_price_spikes([100.0] * 5 + [60.0] * 7).any()
    assert not m.flag_price_spikes([100.0, 99.0, 98.5, 99.5, 100.0]).any()


def test_daily_clean_price():
    price, one_sided = m.daily_clean_price([93.5, 92.5, 99.0], [1e6, 1e6, 1e3], [True, False, True])
    assert price == pytest.approx(0.93)
    assert not one_sided
    price, one_sided = m.daily_clean_price([93.5], [1e6], [True])
    assert price == pytest.approx(0.935)
    assert one_sided
    assert np.isnan(m.daily_clean_price([93.5], [1e3], [True])[0])


def test_full_price():
    b = m.Bond(0.06, 4.8)
    assert m.full_price(0.97, b) == pytest.approx(0.97 + 0.06 * 0.2)


# ------------------------------------------------------------------ Part 5: calibration

def test_fixed_parameters_and_fit_status():
    assert m.yu_fixed_parameters() == (0.5, 0.3)
    assert m.fit_status(0.62) == "ok"
    assert m.fit_status(1.2) == "review"
    assert m.fit_status(0.01) == "reject"
    assert m.fit_status(3.0) == "reject"


def test_fit_barrier_on_cds_recovers_a_known_barrier():
    s = np.array([30.0, 29.0, 31.0, 30.5])
    d, v, r = np.full(4, 28.0), np.full(4, 0.38), np.full(4, 0.04)
    c = [m.cds_par_spread(5, m.Firm(float(x), 28.0, 0.38, 0.62), 0.5, 0.04) for x in s]
    fit, rmse = m.fit_barrier_on_cds(c, s, d, v, r, 5.0, 0.5, 0.3)
    assert fit == pytest.approx(0.62, abs=1e-3)
    assert rmse < 1e-6


# ------------------------------------------------------------------ Part 6: signal

def test_peer_median_gap():
    assert m.peer_median_gap([0.1, float("nan"), 0.3, 0.2]) == pytest.approx(0.2)
    assert m.peer_median_gap([]) == 0.0


def test_peer_adjusted_signal_removes_a_common_move():
    assert m.peer_adjusted_signal(0.6, 0.0, 0.5) == 1
    assert m.peer_adjusted_signal(0.6, 0.5, 0.5) == 0
    assert m.peer_adjusted_signal(-0.6, 0.0, 0.5) == -1
    assert m.peer_adjusted_signal(float("nan"), 0.0, 0.5) == 0


def test_sibling_confirms():
    assert m.sibling_confirms(0.6, float("nan"))
    assert m.sibling_confirms(0.6, 0.3)
    assert not m.sibling_confirms(0.6, 0.2)
    assert not m.sibling_confirms(0.6, -0.5)


def test_cds_confirms():
    assert m.cds_confirms(1, float("nan"), float("nan"), 0.5)
    assert m.cds_confirms(1, 0.03, 0.01, 0.5)
    assert not m.cds_confirms(1, 0.012, 0.01, 0.5)


def test_implied_vol_confirms():
    z_model = m.model_z_spread(BOND, BASE, CURVE, 0.5)
    z = z_model * 1.8
    assert m.implied_vol_confirms(1, z, BOND, BASE, float("nan"), CURVE, 0.5, 0.5)
    assert m.implied_vol_confirms(1, z, BOND, BASE, BASE.sigma_s, CURVE, 0.5, 0.5)
    assert not m.implied_vol_confirms(1, z, BOND, BASE, BASE.sigma_s * 1.6, CURVE, 0.5, 0.5)
    assert m.implied_vol_confirms(-1, z, BOND, BASE, BASE.sigma_s * 1.6, CURVE, 0.5, 0.5)


def test_vol_status_and_vol_signal():
    assert m.vol_status_allows_trade(m.VolInversion("ok", 0.4, (0.4,)))
    assert not m.vol_status_allows_trade(m.VolInversion("multiple"))
    assert m.vol_entry_signal(0.5, 0.38, 0.2) == 1
    assert m.vol_entry_signal(0.3, 0.38, 0.2) == -1
    assert m.vol_entry_signal(0.4, 0.38, 0.2) == 0
    assert m.vol_entry_signal(float("nan"), 0.38, 0.2) == 0


def test_beta_equivalent_to_alpha_fires_at_the_same_point_and_grows_near_default():
    f = m.Firm(S=30.0, D=28.0, sigma_s=0.38, L_bar=0.8)
    beta = m.beta_equivalent_to_alpha(0.5, BOND, f, CURVE, 0.5)
    implied = (1 + beta) * f.sigma_s
    z = m.model_z_spread(BOND, replace(f, sigma_s=implied), CURVE, 0.5)
    assert z == pytest.approx(1.5 * m.model_z_spread(BOND, f, CURVE, 0.5), abs=1e-6)
    betas = [m.beta_equivalent_to_alpha(0.5, BOND, replace(f, S=x * 28.0), CURVE, 0.5) for x in (3.0, 1.0, 0.7)]
    print(f"\n  alpha 0.5 equals beta: S/D=3 {betas[0]:.3f}, S/D=1 {betas[1]:.3f}, S/D=0.7 {betas[2]:.3f}")
    assert betas[0] < betas[1] < betas[2]


def test_decide_entry_needs_every_check():
    assert m.decide_entry(1, True, True, True, True, True, True) == 1
    for i in range(6):
        flags = [True] * 6
        flags[i] = False
        assert m.decide_entry(-1, *flags) == 0


# ------------------------------------------------------------------ Part 7: trade

def test_execution_day():
    assert m.execution_day(10) == 11
    assert m.execution_day(10, 0) == 10


def test_par_hedge_bond_prices_at_par():
    curve = m.zero_curve_from_par_yields([0.5, 1, 2, 5, 10], [0.043, 0.041, 0.039, 0.0395, 0.043])
    assert m.price_from_z(0.0, m.par_hedge_bond(4.8, curve), curve) == pytest.approx(1.0, abs=1e-12)


def test_build_position_and_rate_hedge():
    pos = m.build_position(1, 1.1, 0.005, 0.95)
    assert (pos.shares, pos.hedge_face) == (pytest.approx(0.0055), pytest.approx(1.045))
    assert m.rate_hedge_face(BOND, 0.02, BOND, CURVE) < 1.0
    assert m.rate_hedge_is_due(1.0, 1.0, 30)
    assert m.rate_hedge_is_due(1.0, 1.1, 1)
    assert not m.rate_hedge_is_due(1.0, 1.02, 1)


def test_financing_rates_and_opening_value():
    assert m.bond_financing_rate(1, 0.04, 0.005) == 0.04
    assert m.bond_financing_rate(-1, 0.04, 0.005) == 0.035
    assert m.stock_financing_rate(1, 0.04, 0.01) == 0.03
    assert m.stock_financing_rate(-1, 0.04, 0.01) == 0.04
    assert m.opening_account_value(0.5, 0.01) == 0.49


def test_coupons_paid_counts_payments_in_a_window():
    assert m.coupons_paid(m.Bond(0.06, 4.56), m.Bond(0.06, 4.44)) == pytest.approx(0.03)
    assert m.coupons_paid(m.Bond(0.06, 4.44), m.Bond(0.06, 4.30)) == 0.0


# ------------------------------------------------------------------ Part 9: costs

def test_cost_functions():
    assert m.yu_cds_round_trip(0.01, 4.3) == pytest.approx(0.00215)
    assert m.measured_round_trip([93.5], [1e6], [92.5], [1e6]) == pytest.approx(0.01)
    assert m.planning_round_trip("A", 0.01) == 0.005
    assert m.planning_round_trip("BB", 0.03) == 0.01
    assert m.planning_round_trip("B", 0.05) == 0.015
    assert m.planning_round_trip("BB", 0.11) == 0.03
    assert m.planning_round_trip("CCC", 0.05) == 0.03
    assert m.stressed_cost(0.01, 2.0) == 0.02


# ------------------------------------------------------------------ Part 10: exits

def test_limited_liability_comes_before_every_other_exit():
    assert m.bond_exit_reason(1, 110, 100, 5, 180, -0.01, 4.0, 20, "merger") == "limited_liability"


def test_drawdown_from_peak():
    assert m.drawdown_from_peak([0.5, 0.6, 0.45, 0.7]) == pytest.approx(0.25)
    assert m.drawdown_from_peak([0.5, 0.6]) == 0.0


# ------------------------------------------------------------------ Part 11: the book

TRUE_L = 0.8
CONFIG = m.BacktestConfig(calibration_days=10)


@pytest.fixture(scope="module")
def flat_panel():
    return m.synthetic_bond_panel()


@pytest.fixture(scope="module")
def wide_panel(flat_panel):
    return m.inject_gap(flat_panel, TRUE_L, 30, 0.02, 30, 0.5, 0.3)


def test_backtest_recovers_the_barrier_used_to_make_the_data(flat_panel):
    r = m.run_bond_backtest(flat_panel, CONFIG)
    assert r.L_bar == pytest.approx(TRUE_L, abs=1e-3)
    assert r.status == "ok"


def test_no_trades_when_market_equals_model(flat_panel):
    assert m.check_no_signal_without_gap(flat_panel, CONFIG) == 0


def test_known_gap_long_bond(wide_panel):
    r = m.run_bond_backtest(wide_panel, CONFIG)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.side == 1
    assert t.signal_day == 30
    assert t.entry_day == 31
    assert t.reason == "convergence"
    assert t.hpr > 0
    assert m.check_legs_add_up(r, CONFIG.capital) < 1e-12
    assert m.check_known_gap_profit(wide_panel, r) < 1e-12


def test_known_gap_short_bond(flat_panel):
    panel = m.inject_gap(flat_panel, TRUE_L, 30, -0.009, 30, 0.5, 0.3)
    r = m.run_bond_backtest(panel, replace(CONFIG, use_cost_gate=False))
    assert [t.side for t in r.trades] == [-1]
    assert r.trades[0].reason == "convergence"
    assert r.trades[0].legs["bond_price"] > 0


def test_equity_hedge_is_short_for_long_bond_and_long_for_short_bond(flat_panel):
    moved = replace(flat_panel, S=flat_panel.S + np.where(np.arange(90) > 40, 1.0, 0.0))
    long_run = m.run_bond_backtest(m.inject_gap(moved, TRUE_L, 30, 0.02, 200, 0.5, 0.3), replace(CONFIG, peer_adjust=False))
    assert long_run.trades[0].legs["stock_price"] < 0
    short_run = m.run_bond_backtest(m.inject_gap(moved, TRUE_L, 30, -0.009, 200, 0.5, 0.3), replace(CONFIG, peer_adjust=False, use_cost_gate=False))
    assert short_run.trades[0].legs["stock_price"] > 0


def test_coupon_inside_a_trade_is_not_lost(flat_panel):
    repriced = m.panel_with_no_gap(replace(flat_panel, years_left=4.56 - np.arange(90) / 360.0), TRUE_L, 0.5, 0.3)
    panel = m.inject_gap(repriced, TRUE_L, 12, 0.02, 40, 0.5, 0.3)
    r = m.run_bond_backtest(panel, CONFIG)
    t = r.trades[0]
    assert t.entry_day < 20 < t.exit_day
    assert m.check_known_gap_profit(panel, r) < 1e-12
    assert t.legs["bond_price"] > 0


def test_limited_liability_closes_the_trade(flat_panel):
    panel = m.inject_gap(flat_panel, TRUE_L, 30, 0.01, 1000, 0.5, 0.3)
    worse = np.array(panel.clean)
    worse[40:] = worse[40:] - 0.2
    r = m.run_bond_backtest(replace(panel, clean=worse), replace(CONFIG, capital=0.1, peer_adjust=False))
    assert r.trades[0].reason == "limited_liability"
    assert r.trades[0].hpr < -1


def test_no_price_for_14_days_forces_exit(wide_panel):
    clean = np.array(wide_panel.clean)
    clean[35:] = np.nan
    r = m.run_bond_backtest(replace(wide_panel, clean=clean), CONFIG)
    assert r.trades[0].reason == "no_price_14_days"


def test_under_one_year_forces_exit(flat_panel):
    repriced = m.panel_with_no_gap(replace(flat_panel, years_left=1.2 - np.arange(90) / 360.0), TRUE_L, 0.5, 0.3)
    r = m.run_bond_backtest(m.inject_gap(repriced, TRUE_L, 30, 0.04, 200, 0.5, 0.3), CONFIG)
    assert r.trades[0].reason == "under_one_year"


def test_forced_event_exits(wide_panel):
    events = [None] * 90
    events[40] = "merger"
    r = m.run_bond_backtest(replace(wide_panel, forced_event=tuple(events)), CONFIG)
    assert r.trades[0].reason == "merger"
    assert r.trades[0].exit_day == 41


def test_holding_period_exit(flat_panel):
    panel = m.inject_gap(flat_panel, TRUE_L, 30, 0.02, 1000, 0.5, 0.3)
    r = m.run_bond_backtest(panel, replace(CONFIG, max_hold=10))
    assert r.trades[0].reason == "holding_period"


def test_screens_block_entry(wide_panel):
    closed = replace(wide_panel, tradable=np.arange(90) < 25)
    assert m.run_bond_backtest(closed, CONFIG).trades == []
    assert m.run_bond_backtest(replace(wide_panel, peer_gap=np.full(90, 0.5)), CONFIG).trades == []
    assert m.run_bond_backtest(replace(wide_panel, round_trip=np.full(90, 0.2)), CONFIG).trades == []
    assert m.run_bond_backtest(replace(wide_panel, sibling_gap=np.full(90, -0.5)), CONFIG).trades == []
    assert m.run_bond_backtest(replace(wide_panel, cds_market=np.full(90, 0.001)), CONFIG).trades == []
    assert m.run_bond_backtest(replace(wide_panel, implied_vol=np.full(90, 0.95)), CONFIG).trades == []


def test_barrier_filter_blocks_entry_near_default():
    panel = m.synthetic_bond_panel(S=8.0, D=28.0, sigma_s=0.8, L_bar=0.5)
    gapped = m.inject_gap(panel, 0.5, 30, 0.06, 30, 0.5, 0.3)
    assert m.run_bond_backtest(gapped, CONFIG).trades == []
    assert m.run_bond_backtest(gapped, replace(CONFIG, calibration_days=10)).status != "too_few_days"


def test_too_few_days_to_fit(wide_panel):
    clean = np.full(90, np.nan)
    clean[:5] = wide_panel.clean[:5]
    assert m.run_bond_backtest(replace(wide_panel, clean=clean), CONFIG).status == "too_few_days"


def test_vol_space_opens_the_same_trade(wide_panel):
    r = m.run_bond_backtest(wide_panel, replace(CONFIG, space="vol"))
    assert [t.side for t in r.trades] == [1]
    assert r.trades[0].reason == "convergence"


def test_overlapping_book_opens_one_trade_per_qualifying_day(wide_panel):
    single = m.run_bond_backtest(wide_panel, CONFIG)
    many = m.run_bond_backtest(wide_panel, replace(CONFIG, overlapping=True))
    assert len(single.trades) == 1
    assert len(many.trades) > 5
    assert len(set(t.entry_day for t in many.trades)) == len(many.trades)


def test_rehedging_costs_money_and_stays_consistent(wide_panel):
    on = m.run_bond_backtest(wide_panel, replace(CONFIG, overlapping=False))
    off = m.run_bond_backtest(wide_panel, replace(CONFIG, rehedge=False))
    assert "rehedge_cost" in on.trades[0].legs
    assert "rehedge_cost" not in off.trades[0].legs
    assert m.check_legs_add_up(on, CONFIG.capital) < 1e-12


def test_no_lookahead_in_the_backtest(wide_panel):
    for cut in (35, 45, 62, 75):
        assert m.check_no_lookahead(wide_panel, CONFIG, cut) == 0.0


def test_lag_sensitivity_returns_each_lag(wide_panel):
    out = m.lag_sensitivity(wide_panel, CONFIG, (0, 1, 2))
    print(f"\n  mean trade return by lag on the injected gap: {out}")
    assert out[0] > out[1] > out[2]


def test_placebo_panel_swaps_only_the_equity(flat_panel, wide_panel):
    other = replace(flat_panel, S=flat_panel.S * 1.5)
    placebo = m.placebo_panel(wide_panel, other)
    assert placebo.S[0] == 45.0
    assert placebo.clean[0] == wide_panel.clean[0]


def test_attribute_pnl_sums_to_net(wide_panel):
    r = m.run_bond_backtest(wide_panel, CONFIG)
    totals = m.attribute_pnl(r.trades)
    assert totals["net"] == pytest.approx(r.trades[0].final_value - CONFIG.capital, abs=1e-12)


def test_break_even_cost_falls_on_the_line(flat_panel):
    panel = m.inject_gap(flat_panel, TRUE_L, 30, 0.012, 30, 0.5, 0.3)
    out = m.break_even_cost(panel, replace(CONFIG, peer_adjust=False, alpha=0.05), (0.0, 1.0, 10.0, 40.0))
    print(f"\n  break-even cost multiple on a small injected gap: {out['break_even_multiple']:.2f}")
    assert out["mean_returns"][0] > 0 > out["mean_returns"][-1]
    assert 1.0 < out["break_even_multiple"] < 40.0


def test_truncate_panel_keeps_the_scalars(wide_panel):
    cut = m.truncate_panel(wide_panel, 40)
    assert len(cut.S) == 40
    assert cut.coupon == wide_panel.coupon
    assert cut.zeros.shape[0] == 40


# ------------------------------------------------------------------ Part 11: reporting

def _trade(hpr, drawdown=0.0, converged=False):
    return m.TradeResult(1, 0, 1, 2, "x", 1.0, 0.0, 0.0, hpr, drawdown, converged, {}, 0.5, {})


def test_trade_summary_follows_yu_columns():
    out = m.trade_summary([_trade(0.1, 0.3, True), _trade(-0.2), _trade(0.05)])
    assert (out["N"], out["N1"], out["N2"], out["N3"]) == (3, 1, 1, 1)
    assert out["min"] == -0.2
    assert out["max"] == 0.1
    assert out["mean"] == pytest.approx(-0.05 / 3)


def test_summaries_by_group():
    out = m.summaries_by_group([_trade(0.1), _trade(-0.2)], ["long", "short"])
    assert out["short"]["N3"] == 1
    assert out["long"]["N"] == 1


def test_monthly_summary_counts_zero_months_in_median_and_negative():
    months = np.array([0.0] * 23 + [0.01] * 11 + [-0.01] * 14)
    out = m.monthly_summary(months)
    assert out["N"] == 25
    assert out["median"] == 0.0
    assert out["neg"] == pytest.approx(14 / 48)
    assert out["sharpe"] == pytest.approx(m.annual_sharpe(months))


def test_factor_regression_and_hedge_slope_recover_known_values():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((400, 2))
    y = 0.2 + 0.5 * x[:, 0] - 0.3 * x[:, 1] + 0.01 * rng.standard_normal(400)
    out = m.factor_regression(y, x)
    assert out["intercept"] == pytest.approx(0.2, abs=0.01)
    assert out["betas"][0] == pytest.approx(0.5, abs=0.01)
    assert out["betas"][1] == pytest.approx(-0.3, abs=0.01)
    assert out["r2"] > 0.99
    slope, se = m.empirical_hedge_slope(2.0 * x[:, 0] + 0.1 * x[:, 1], x[:, 0])
    assert slope == pytest.approx(2.0, abs=0.03)
    assert se < 0.02


# ------------------------------------------------------------------ Part 12: Yu's own CDS trade

def _cds_panel(c, s=30.0):
    n = len(c)
    one = np.ones(n)
    return m.CdsPanel(c=np.array(c, dtype=float), S=one * s, D=one * 28.0, sigma_s=one * 0.38, r=one * 0.04,
                      dividend=one * 0.0, day_fraction=one / 360.0, calendar_day=np.arange(n, dtype=float))


YU_CONFIG = m.BacktestConfig(calibration_days=10, overlapping=True, lag=0, bid_ask=0.0, peer_adjust=False)


def test_cds_backtest_no_gap_means_no_trades():
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    c = m.cds_par_spread(5, firm, 0.5, 0.04)
    r = m.run_cds_backtest(_cds_panel([c] * 40), YU_CONFIG)
    assert r.L_bar == pytest.approx(0.62, abs=1e-3)
    assert r.trades == []


def test_cds_short_protection_gains_when_market_converges_down():
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    c = m.cds_par_spread(5, firm, 0.5, 0.04)
    path = [c] * 15 + [c * 2.0] + [c * 1.8] * 5 + [c * 0.99] * 5
    r = m.run_cds_backtest(_cds_panel(path), replace(YU_CONFIG, overlapping=False))
    t = r.trades[0]
    assert t.side == 1
    assert t.reason == "convergence"
    assert t.hpr > 0
    annuity = m.cds_annuity(5, firm, 0.04)
    expected = (2.0 - 0.99) * c * annuity + 2.0 * c * 6 / 360   # enters day 15, exits day 21
    assert t.final_value - YU_CONFIG.capital == pytest.approx(expected, rel=1e-6)
    assert m.check_legs_add_up(r, YU_CONFIG.capital) < 1e-12


def test_cds_long_protection_when_market_is_under_the_model():
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    c = m.cds_par_spread(5, firm, 0.5, 0.04)
    path = [c] * 15 + [c * 0.5] * 5 + [c * 1.01] * 5
    r = m.run_cds_backtest(_cds_panel(path), replace(YU_CONFIG, overlapping=False))
    assert r.trades[0].side == -1
    assert r.trades[0].legs["cds_value"] > 0
    assert r.trades[0].legs["cds_premium"] < 0


def test_cds_bid_ask_costs_money_at_entry():
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    c = m.cds_par_spread(5, firm, 0.5, 0.04)
    path = [c] * 15 + [c * 2.0] * 15
    no_cost = m.run_cds_backtest(_cds_panel(path), replace(YU_CONFIG, overlapping=False))
    cost = m.run_cds_backtest(_cds_panel(path), replace(YU_CONFIG, overlapping=False, bid_ask=0.05))
    assert cost.trades[0].hpr < no_cost.trades[0].hpr


def test_cds_altria_style_blowout_is_liquidated_at_low_capital():
    """Yu p. 21, in shape only: 299 to 529 bp in four days on capital 0.1 is about -100%."""
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    c = m.cds_par_spread(5, firm, 0.5, 0.04)
    path = [c] * 15 + [0.0299, 0.0340, 0.0370, 0.0358, 0.0529, 0.0529]
    r = m.run_cds_backtest(_cds_panel(path), replace(YU_CONFIG, overlapping=False, capital=0.1, bid_ask=0.05))
    t = r.trades[0]
    print(f"\n  CDS blowout, capital 0.1: reason {t.reason}, return {t.hpr:.1%}")
    assert t.side == 1
    assert t.reason == "limited_liability"
    assert -1.3 < t.hpr < -1.0


def test_check_cds_replication_is_zero_on_yu_own_numbers():
    target = m.YU_TABLE_2[(0.5, 180, 0.5)]
    summary = {"N": target[0], "N1": target[1], "N2": target[2], "N3": target[3],
               "mean": target[4] / 100, "min": target[5] / 100, "max": target[6] / 100}
    gaps = m.check_cds_replication(summary, 0.5, 180, 0.5)
    assert all(abs(v) < 1e-9 for v in gaps.values())


def test_shape_against_yu_on_his_own_table_3():
    """INV, capital 0.5: his own numbers must pass the pattern check on N1 and N3."""
    def row(n, n1, n3, low, high):
        return {"N": n, "N1": n1, "N3": n3, "min": low, "max": high}
    out = m.shape_against_yu(row(57621, 372, 28512, -75.16, 50.97), row(57621, 5615, 17872, -88.71, 104.41),
                             row(18173 * 2, 142, 10000, -45.69, 104.41), row(18173, 142, 4140, -13.37, 104.41))
    assert out["more_convergence_with_longer_hold"]
    assert out["fewer_losers_with_longer_hold"]
    assert out["tighter_with_higher_trigger"]


def test_check_identities_are_small():
    out = m.check_identities(BASE, 0.5, 0.04, 5.0)
    assert out["annuity_gap"] < 1e-9
    assert out["price_identity_gap"] < 1e-12
    assert out["par_delta_gap"] < 0.01
    assert abs(out["par_z_minus_cds_bp"]) < 0.5


# ------------------------------------------------------------------ the document and the code agree

DOC = Path(__file__).with_name("02_bond_vol_method.md")
HELPERS = {"flat_curve", "cash_flows", "accrued_interest", "price_from_z", "calibrate_barrier"}


def _steps():
    text = DOC.read_text(encoding="utf8")
    body = text[text.index("## Part 1."):text.index("## Final outputs")]
    pieces = re.split(r"^### Step (\d+)\. ", body, flags=re.M)[1:]
    steps = {}
    for number, chunk in zip(pieces[0::2], pieces[1::2]):
        steps[int(number)] = chunk
    return steps


def _table_names(chunk, heading):
    block = chunk[chunk.index(f"**{heading}**"):]
    rows = []
    for line in block.splitlines()[1:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return rows[2:]


def test_doc_steps_are_numbered_without_gaps():
    numbers = sorted(_steps())
    assert numbers == list(range(1, len(numbers) + 1))
    print(f"\n  document has {len(numbers)} steps")


def test_doc_every_step_has_function_tag_tables_and_formula():
    for number, chunk in _steps().items():
        header = chunk.splitlines()[0]
        assert re.search(r"\[(PAPER|CREDITGRADES|ADAPTATION)\]", header), number
        assert "**Function:**" in chunk, number
        assert "**Inputs**" in chunk, number
        assert "**Formula**" in chunk, number
        assert "**Outputs**" in chunk, number


def test_doc_inputs_tables_list_every_function_argument_by_name():
    for number, chunk in _steps().items():
        name = re.search(r"\*\*Function:\*\* `(\w+)\(", chunk).group(1)
        func = getattr(m, name)
        args = set(inspect.signature(func).parameters)
        listed = {row[0].strip("`") for row in _table_names(chunk, "Inputs")}
        assert args <= listed, (number, name, args - listed)
        assert listed <= args or not args, (number, name, listed - args)
        assert all(len(row) == 5 and all(row) for row in _table_names(chunk, "Inputs")), (number, name)


def test_doc_outputs_point_to_later_steps():
    steps = _steps()
    for number, chunk in steps.items():
        rows = _table_names(chunk, "Outputs")
        assert rows, number
        for row in rows:
            assert len(row) == 4 and all(row), (number, row)
            used = row[3]
            later = [int(x) for x in re.findall(r"Step (\d+)", used)]
            assert later or "Final output" in used, (number, row)
            assert all(number < x <= len(steps) for x in later), (number, row)


def test_doc_covers_every_public_function():
    named = {re.search(r"\*\*Function:\*\* `(\w+)\(", c).group(1) for c in _steps().values()}
    public = {n for n, f in vars(m).items()
              if inspect.isfunction(f) and f.__module__ == m.__name__ and not n.startswith("_")}
    assert public - named - HELPERS == set()
    assert HELPERS <= public
    assert len(named) == len(_steps())


def test_worked_example_walks_every_step():
    run = subprocess.run([sys.executable, "worked_example.py"], cwd=DOC.parent, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    shown = set(re.findall(r"^\[(\w+)\]", run.stdout, flags=re.M))
    named = {re.search(r"\*\*Function:\*\* `(\w+)\(", c).group(1) for c in _steps().values()}
    assert named - shown == set()
