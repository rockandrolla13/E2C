"""Acceptance tests C1-C8 and E1-E3 of finkelstein_replication_plan.pdf, Section 9.

Expected values come from that table. r = 5% unless stated. Prices are per 1 of face, as in e2c_bond.
"""
from datetime import date

import numpy as np
import pytest
from scipy.optimize import brentq

import fk_model as fk
import fk_value as v
from fk_value import e2c

R = .05
D0 = date(2001, 6, 14)
T1 = (date(2003, 1, 17) - D0).days / 365.0
T2 = (date(2004, 1, 16) - D0).days / 365.0
CURVE = e2c.flat_curve(R)
SIG = v.flat_forward_sigma([(T1, .498), (T2, .465)])
MATURITY, CDS_END = date(2009, 11, 15), date(2006, 1, 3)


def years(a, b):
    return (b - a).days / 365.0


def accrued(d):
    """30/360 from the 15 May coupon, per 1 of face. The GX 9.5% bond."""
    return .095 * ((d.month - 5) * 30 + (min(d.day, 30) - 15)) / 360


def gx_bond(d):
    return e2c.Bond(.095, years(d, MATURITY), 2)


def gx_q(s=10.5, sig=SIG):
    return v.survival_function(s, 6.0, sig)


# ---------------------------------------------------------------- C. Credit against the deck

def test_c1_slide_12_par_curve():
    tenors = (.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7, 9.5)
    expected = (.0093, .0484, .0759, .0829, .0854, .0867, .0875, .0871, .0852, .0827)
    chart = (.009, .048, .077, .0815, .084, .085, .0865, .086, .084, .082)
    q = gx_q()
    par = [v.fk_cds(t, q, CURVE, .3).par for t in tenors]
    assert par == pytest.approx(list(expected), abs=2e-4)
    assert max(abs(a - b) for a, b in zip(par, chart)) <= 20e-4


@pytest.mark.parametrize("d, s, mine, deck", [(D0, 10.5, .834, .82), (date(2001, 8, 31), 4.2, .599, .60), (date(2001, 10, 1), 1.8, .445, .43)])
def test_c2_slide_12_bond_clean_at_flat_42(d, s, mine, deck):
    clean = v.fk_bond_price(gx_bond(d), gx_q(s, .42), CURVE, .3) - accrued(d)
    assert clean == pytest.approx(mine, abs=.001)
    assert clean == pytest.approx(deck, abs=.015)


@pytest.mark.parametrize("rec, mine, chart", [(.3, .377, .37), (.1, .485, .475)])
def test_c3_slide_14_peak(rec, mine, chart):
    par = v.fk_cds(years(date(2001, 10, 1), CDS_END), gx_q(1.8, .42), CURVE, rec).par
    assert par == pytest.approx(mine, abs=.001)
    assert par == pytest.approx(chart, abs=.015)


def test_c4_slide_14_15_flat_hazard_fit():
    d = date(2001, 10, 1)
    bond, tc = gx_bond(d), years(d, CDS_END)
    results = []
    for price in (.45, .45 + accrued(d)):    # 45 read as full, then as clean
        fit = v.bond_implied_curve(price, bond, CURVE, .3)
        annuity = (1 - np.exp(-(R + fit.hazard) * tc)) / (R + fit.hazard)
        results.append((fit.par, (.03 - fit.par) * annuity * 100))
    assert sorted(r[0] for r in results) == pytest.approx([.307, .383], abs=.002)
    assert sorted(r[1] for r in results) == pytest.approx([-54.5, -49.6], abs=.2)
    assert min(r[0] for r in results) < .31 < max(r[0] for r in results)
    assert min(r[1] for r in results) < -53 < max(r[1] for r in results)


TENORS19 = (.5, 1, 2, 5, 10)
LEFT = {0: (.002, .019, .052, .077, .079), .2: (.008, .028, .057, .077, .078),
        .3: (.023, .040, .063, .077, .076), .4: (.048, .057, .069, .077, .075)}
RIGHT = {0: (.000, .001, .009, .027, .033), .2: (.015, .019, .025, .032, .034),
         .3: (.078, .055, .046, .040, .037), .4: (.170, .101, .068, .048, .040)}


def rms_to_chart(chart, s_over_b, sig):
    err = []
    for lam, row in chart.items():
        q = v.survival_function(s_over_b, 1.0, sig, lam)
        err += [v.fk_cds(t, q, CURVE, .3).par - c for t, c in zip(TENORS19, row)]
    return np.sqrt(np.mean(np.square(err))) * 1e4


def test_c5_slide_19_left():
    assert rms_to_chart(LEFT, 1.75, .41) == pytest.approx(50, abs=3)
    assert rms_to_chart(LEFT, 1.75, .42) == pytest.approx(17, abs=3)


def test_c6_slide_19_right():
    assert rms_to_chart(RIGHT, .8, .1778) == pytest.approx(29, abs=3)
    assert rms_to_chart(RIGHT, .8, .222) == pytest.approx(159, abs=5)


def test_c7_creditgrades_table_c1_by_e2c_bond():
    res = e2c.check_table_c1()
    assert res["cells_matching"] == 156
    assert res["largest_gap_bp"] == pytest.approx(.494, abs=.01)
    assert res["largest_gap_unscaled_bp"] == pytest.approx(11.59, abs=.05)


CELLS = {.5: [55, 85, 125, 175, 232, 297, 367, 441, 520, 602, 687, 774, 865],
         1.: [8, 22, 46, 82, 130, 188, 253, 326, 403, 486, 572, 662, 755],
         2.: [1, 3, 12, 30, 59, 101, 153, 214, 283, 358, 438, 523, 612],
         4.: [0, 0, 2, 7, 19, 41, 73, 117, 169, 230, 298, 373, 452],
         6.: [0, 0, 0, 2, 8, 20, 42, 74, 115, 166, 224, 290, 362]}


@pytest.mark.parametrize("remedy, largest", [(False, .48), (True, .99)])
def test_c8_table_c1_rows_by_eq1(remedy, largest):
    gaps = []
    for sd, row in CELLS.items():
        S, B = sd * 30, 15.
        for i, cell in enumerate(row):
            sg = (.2 + .05 * i) * S / (S + B)
            q = v.survival_function(S, B, sg, .3, remedy=remedy)
            par = v.fk_cds(5.0, q, CURVE, .5, freq=None, act360=True, steps_per_year=192).par
            gaps.append(abs(par * 1e4 - cell))
    assert max(gaps) == pytest.approx(largest, abs=.02)
    assert max(gaps) <= 1.0


# ---------------------------------------------------------------- Bond pricer against e2c_bond

@pytest.mark.parametrize("lam", [0.0, .3])
def test_bond_price_equals_risky_bond_price_at_flat_vol_with_remedy_off(lam):
    firm = e2c.Firm(30., 28., .38, .8, lam)
    bond = e2c.Bond(.055, 4.8)
    q = v.survival_function(30., .8 * 28., e2c.asset_vol(firm), lam, remedy=False)
    assert v.fk_bond_price(bond, q, CURVE, .5) == pytest.approx(e2c.risky_bond_price(bond, firm, CURVE, .5), abs=1e-12)


# ---------------------------------------------------------------- E. Worked example

@pytest.fixture
def gx():
    d = D0
    return dict(bond=gx_bond(d), full=.84 + accrued(d))


def test_e1_three_spreads_and_gaps(gx):
    z_mkt = e2c.z_spread(gx["full"], gx["bond"], CURVE)
    z_opt = v.fk_bond_z(gx["bond"], gx_q(), CURVE, .3)
    z_stk = v.stock_only_curve(10.5, 6.0, .42, gx["bond"], CURVE, .3).z
    assert np.array([z_mkt, z_opt, z_stk]) * 1e4 == pytest.approx([724, 787, 736], abs=1)
    g = v.three_gaps(z_mkt, z_opt, z_stk)
    assert [g.bond_option, g.option_stock, g.bond_stock] == pytest.approx([-.084, .066, -.017], abs=.001)
    assert g.bond_stock == pytest.approx(g.bond_option + g.option_stock, abs=1e-10)


def test_e2_same_gap_in_other_units(gx):
    q, bond, full = gx_q(), gx["bond"], gx["full"]
    kappa = v.hazard_multiplier(full, bond, q, CURVE, .3)
    assert kappa == pytest.approx(.908, abs=.002)
    assert v.bond_default_probability(q, kappa, T2) == pytest.approx(.258, abs=.002)
    rec = v.implied_recovery(full, bond, q, CURVE)
    assert rec.recovery == pytest.approx(.356, abs=.002)
    assert rec.in_bounds
    scale = v.bond_implied_vol(full, bond, 10.5, 6.0, SIG, CURVE, .3)
    assert scale.status == "ok"
    assert scale.scale == pytest.approx(.953, abs=.002)
    assert v.bond_implied_curve(full, bond, CURVE, .3).hazard == pytest.approx(.1077, abs=.002)


@pytest.mark.parametrize("payout, gap_bp, ratio", [(.03, -149, .919), (.05, -213, .888)])
def test_e3_des_form_on_gx(gx, payout, gap_bp, ratio):
    S, D, Lbar = 10.5, 14.2, .5
    sig = fk.asset_vol_fs(.822, S, D)
    assert sig == pytest.approx(.489, abs=.001)
    q = lambda t: np.array([fk.des_survival(float(x), S + Lbar * D, Lbar * D, sig, R, payout, .3) for x in np.atleast_1d(t)])
    price = v.fk_bond_price(gx["bond"], q, CURVE, .35)
    gap = e2c.z_spread(gx["full"], gx["bond"], CURVE) - e2c.z_spread(price, gx["bond"], CURVE)
    assert gap * 1e4 == pytest.approx(gap_bp, abs=2)
    assert price / gx["full"] == pytest.approx(ratio, abs=.002)


# ---------------------------------------------------------------- Edge cases

def test_bond_implied_vol_reports_prices_it_cannot_reach():
    bond = gx_bond(D0)
    assert v.bond_implied_vol(1.60, bond, 10.5, 6.0, SIG, CURVE, .3).status == "below_floor"
    assert v.bond_implied_vol(.31, bond, 10.5, 6.0, SIG, CURVE, .3).status == "near_recovery"


def test_implied_recovery_flags_out_of_bounds(gx):
    assert not v.implied_recovery(.05, gx["bond"], gx_q(), CURVE).in_bounds


def test_sigma_cum_is_flat_then_flat_forward():
    assert SIG(1.0) == .498 and SIG(T1) == .498
    assert SIG(T2) == pytest.approx(.465, abs=1e-12)
    assert SIG(9.0) ** 2 * 9.0 - SIG(T2) ** 2 * T2 == pytest.approx(fk.forward_vol(T1, .498, T2, .465) ** 2 * (9.0 - T2), abs=1e-12)


def test_flat_hazard_against_closed_forms():
    """Independent of the grids. Flat hazard h, flat rate r: known results for the CDS and the bond."""
    h, rec = .04, .4
    q = lambda t: np.exp(-h * np.asarray(t, dtype=float))
    cds = v.fk_cds(5.0, q, CURVE, rec, freq=None, steps_per_year=480)
    assert cds.par == pytest.approx((1 - rec) * h, abs=1e-6)
    assert cds.default_leg == pytest.approx(h / (R + h) * (1 - np.exp(-(R + h) * 5)), abs=1e-6)
    bond = e2c.Bond(.06, 5.0)
    t, cf = e2c.cash_flows(bond)
    exact = np.sum(cf * np.exp(-(R + h) * t)) + rec * h / (R + h) * (1 - np.exp(-(R + h) * 5))
    assert v.fk_bond_price(bond, q, CURVE, rec, steps_per_year=480) == pytest.approx(exact, abs=1e-6)
    fit = v.bond_implied_curve(exact, bond, CURVE, rec)
    assert fit.hazard == pytest.approx(h, abs=1e-5)
    assert v.hazard_multiplier(exact, bond, q, CURVE, rec) == pytest.approx(1.0, abs=1e-5)
    assert v.implied_recovery(exact, bond, q, CURVE, steps_per_year=480).recovery == pytest.approx(rec, abs=1e-5)
