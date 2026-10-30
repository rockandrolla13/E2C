"""Acceptance tests D1-D7 of finkelstein_replication_plan.pdf, Section 9, with independent checks.

Expected values come from that table, Section 7.3 and Appendix A. Greeks here are per 100 of face, as the plan's tables are.
"""
from datetime import date

import numpy as np
import pytest
from scipy.special import ndtr as N

import fk_model as fk
import fk_risk as rk
import fk_value as v
from fk_value import e2c

CURVE = e2c.flat_curve(.05)

# Slides 21-25: $100 protection sold at 560 bp, 5y, R = 10%. Options 2y, K = 30 and K = 60.
S0, B0, SIG0, REC, COUPON, TENOR = 40., 15., .375, .10, .056, 5.
PUT_PRICE, CALL_PRICE = 5.22, 6.31
NOTIONAL = 100.    # stands in for the bond's value in the stock guard, since a CDS has no price to speak of

# GX on 14 June 2001, Appendix A.
D0 = date(2001, 6, 14)
GX_S, GX_B, GX_REC = 10.5, 6., .30
GX_T1 = (date(2003, 1, 17) - D0).days / 365.0
GX_T2 = (date(2004, 1, 16) - D0).days / 365.0
GX_SIG = v.flat_forward_sigma([(GX_T1, .498), (GX_T2, .465)])
GX_BOND = e2c.Bond(.095, (date(2009, 11, 15) - D0).days / 365.0, 2)


def seller(S=S0, lam=.3, **kw):
    return rk.cds_seller_greeks(TENOR, S, B0, SIG0, CURVE, REC, COUPON, lam=lam, face=100., **kw)


def deck_put(S=S0):
    return rk.put_greeks(S, 30., 2., SIG0, B0, .05, .02, price=PUT_PRICE)


def deck_call(S=S0):
    return rk.call_greeks(S, 60., 2., SIG0, B0, .05, .02, price=CALL_PRICE)


def gx_bond_greeks(s=GX_S):
    return rk.bond_greeks(GX_BOND, s, GX_B, GX_SIG, CURVE, GX_REC, face=100.)


def gx_put(K, s=GX_S):
    return rk.put_greeks(s, K, GX_T2, .465, GX_B, .05)


def gx_call(K, s=GX_S):
    return rk.call_greeks(s, K, GX_T2, .465, GX_B, .05)


# ---------------------------------------------------------------- D1

def test_d1_slide_21_holds_asset_vol_and_not_equity_vol():
    deck = -27.4
    asset_held = rk.solve_hedge(seller(lam=0.), stock=rk.stock_greeks(S0), rows=("delta",), reference_value=NOTIONAL).dollars[1]
    assert asset_held == pytest.approx(-26.9, abs=.05)
    assert abs(asset_held / deck - 1) <= .05

    sig_e = fk.equity_vol_from_asset(SIG0, S0, B0)

    def value_at_held_equity_vol(s):
        sig = sig_e * s / (s + B0)
        cds = v.fk_cds(TENOR, v.survival_function(s, B0, sig), CURVE, REC)
        return 100 * (COUPON * cds.annuity - (1 - REC) * cds.default_leg)

    equity_held = -(value_at_held_equity_vol(40.4) - value_at_held_equity_vol(39.6)) / .8 * S0
    assert equity_held == pytest.approx(-11.1, abs=.05)
    assert abs(equity_held / deck - 1) > .05


# ---------------------------------------------------------------- D2, D3

def slide_21_to_25():
    tgt, put, call, stock = seller(), deck_put(), deck_call(), rk.stock_greeks(S0)
    return dict(
        s21=rk.solve_hedge(tgt, stock=stock, rows=("delta",), reference_value=NOTIONAL),
        s22=rk.solve_hedge(tgt, put=put, stock=stock, rows=("delta", "vega"), reference_value=NOTIONAL),
        s23=rk.solve_hedge(tgt, put=put, stock=stock, rows=("delta", "jump"), reference_value=NOTIONAL),
        s24=rk.solve_hedge(tgt, put=put, stock=stock, call=call, rows=("delta", "vega", "jump"), reference_value=NOTIONAL),
        s25=rk.optimal_strike(tgt, S0, 2., SIG0, B0, .05, .02),
    )


def test_d2_slide_21_to_25_allocations():
    q = v.survival_function(S0, B0, SIG0, .3)
    assert seller().jump == -90.0
    par = v.fk_cds(TENOR, q, CURVE, REC).par * 1e4
    h = slide_21_to_25()
    fit = h["s25"]
    fit_put = rk.put_greeks(S0, fit.strike, 2., SIG0, B0, .05, .02)
    # (plan's value, deck's value, mine). Tolerance on the deck is 8%. Tight on mine, at the plan's printed precision.
    rows = [(424, 422, par),
            (-26.3, -27.4, h["s21"].dollars[1]),
            (32.2, 32.86, h["s22"].dollars[0]), (29.7, 31.85, h["s22"].dollars[1]),
            (25.9, 26.4, h["s23"].dollars[0]), (18.8, 20.2, h["s23"].dollars[1]),
            (17.1, 17.54, h["s24"].dollars[0]), (-32.5, -33.27, h["s24"].dollars[1]), (14.5, 14.68, h["s24"].dollars[2]),
            (39.5, 39.2, fit.strike),
            (48.2, 49.13, fit.n_put * fit_put.value), (43.7, 46.41, fit.n_stock * S0)]
    for plan, deck, mine in rows:
        assert mine == pytest.approx(plan, abs=.5 if plan == 424 else .06)
        assert abs(mine / deck - 1) <= .08


def test_d3_signs_on_slides_22_to_25():
    h = slide_21_to_25()
    assert (np.sign(h["s22"].n_put), np.sign(h["s22"].n_stock)) == (1, 1)
    assert (np.sign(h["s23"].n_put), np.sign(h["s23"].n_stock)) == (1, 1)
    assert (np.sign(h["s24"].n_put), np.sign(h["s24"].n_stock), np.sign(h["s24"].n_call)) == (1, -1, 1)
    assert (np.sign(h["s25"].n_put), np.sign(h["s25"].n_stock)) == (1, 1)
    assert all(h[k].status == "ok" for k in h)


# ---------------------------------------------------------------- D4

@pytest.mark.parametrize("legs, rows", [
    ({"stock"}, ("delta",)),
    ({"put"}, ("delta",)),
    ({"put", "stock"}, ("delta", "vega")),
    ({"put", "stock"}, ("delta", "jump")),
    ({"put", "stock", "call"}, ("delta", "vega", "jump")),
])
def test_d4_net_greeks_are_zero_after_a_solve(legs, rows):
    all_legs = {"put": deck_put(), "stock": rk.stock_greeks(S0), "call": deck_call()}
    chosen = {k: all_legs[k] for k in legs}
    hedge = rk.solve_hedge(seller(), rows=rows, reference_value=NOTIONAL, **chosen)
    net = rk.net_greeks(seller(), hedge, **chosen)
    for row in rows:
        assert getattr(net, row) == pytest.approx(0.0, abs=1e-8)


def test_d4_slide_25_nets_to_zero_at_the_optimal_strike():
    tgt = seller()
    fit = rk.optimal_strike(tgt, S0, 2., SIG0, B0, .05, .02)
    put = rk.put_greeks(S0, fit.strike, 2., SIG0, B0, .05, .02)
    hedge = rk.Hedge(fit.n_put, fit.n_stock, 0.0, (), "ok", float("nan"))
    net = rk.net_greeks(tgt, hedge, put=put, stock=rk.stock_greeks(S0))
    assert (net.delta, net.vega, net.jump) == pytest.approx((0.0, 0.0, 0.0), abs=1e-8)


# ---------------------------------------------------------------- D5

D5_TABLE = [  # S, par bp, shares, dollars, jump, cover, gamma. Section 7.3
    (60, 202, .294, 17.64, 105.27, .168, -.011),
    (40, 408, .673, 26.93, 96.22, .280, -.030),
    (30, 620, 1.080, 32.39, 87.65, .370, -.054),
    (20, 1032, 1.826, 36.51, 73.52, .497, -.102),
    (15, 1423, 2.437, 36.56, 62.95, .581, -.146),
    (10, 2164, 3.332, 33.32, 48.68, .684, -.218),
    (5, 4259, 4.711, 23.56, 28.84, .817, -.342),
    (2, 10082, 5.824, 11.65, 13.06, .892, -.378),
]


def d5_rows():
    out = []
    for row in D5_TABLE:
        s = float(row[0])
        g = seller(S=s, lam=0., include_value=True)
        par = v.fk_cds(TENOR, v.survival_function(s, B0, SIG0), CURVE, REC).par * 1e4
        out.append((par, g.delta, g.delta * s, -g.jump, g.delta * s / -g.jump, g.gamma))
    return out


def test_d5_delta_path_shape():
    rows = d5_rows()
    shares, dollars, cover = zip(*[(r[1], r[2], r[4]) for r in rows])
    assert all(a < b for a, b in zip(shares, shares[1:]))
    assert max(dollars) == pytest.approx(36.6, rel=.01)
    assert int(np.argmax(dollars)) == 4     # S = 15, at the barrier
    assert cover[0] == pytest.approx(.168, rel=.01)
    assert cover[-1] == pytest.approx(.892, rel=.01)


def test_d5_full_table_at_printed_precision():
    for row, mine in zip(D5_TABLE, d5_rows()):
        assert mine[0] == pytest.approx(row[1], abs=.6)
        assert mine[1:] == pytest.approx(row[2:5] + (row[5], row[6]), abs=.006)


# ---------------------------------------------------------------- D6

def test_d6_guard_rejects_gx_three_leg_solve():
    tgt = gx_bond_greeks()
    hedge = rk.solve_hedge(tgt, put=gx_put(7.5), stock=rk.stock_greeks(GX_S), call=gx_call(15.),
                           rows=("delta", "vega", "jump"), reference_value=tgt.value)
    assert hedge.status == "short_option"
    assert hedge.n_put == pytest.approx(-12.66, abs=.01)
    assert hedge.dollars == pytest.approx((-31.8, -191.6, 88.3), abs=.1)
    assert hedge.condition == pytest.approx(759, abs=2)


def test_d6_short_call_is_rejected_as_well():
    tgt = seller()._replace(delta=-5.0)
    hedge = rk.solve_hedge(tgt, call=deck_call(), rows=("delta",), reference_value=NOTIONAL)
    assert hedge.n_call > 0
    tgt = seller()
    hedge = rk.solve_hedge(tgt, call=deck_call(), rows=("delta",), reference_value=NOTIONAL)
    assert hedge.n_call < 0 and hedge.status == "short_option"


def test_stock_guard_rejects_above_one_and_a_half_times_the_reference_and_passes_below():
    tgt, put, stock = seller(), deck_put(), rk.stock_greeks(S0)
    dollars = rk.solve_hedge(tgt, put=put, stock=stock, rows=("delta", "vega"), reference_value=NOTIONAL).dollars[1]
    at_cap = abs(dollars) / 1.5
    args = dict(put=put, stock=stock, rows=("delta", "vega"))
    assert rk.solve_hedge(tgt, reference_value=at_cap * .99, **args).status == "stock_too_large"
    assert rk.solve_hedge(tgt, reference_value=at_cap * 1.01, **args).status == "ok"


def test_guards_do_not_use_the_condition_number():
    """The plan: 759 on the failure and 509 on the deck's own slide 24, so it cannot separate them."""
    h = slide_21_to_25()["s24"]
    assert h.status == "ok" and h.condition > 100


def test_solve_rejects_a_matrix_that_is_not_square_and_reports_a_singular_one():
    with pytest.raises(ValueError):
        rk.solve_hedge(seller(), put=deck_put(), call=deck_call(), rows=("delta",), reference_value=NOTIONAL)
    stock = rk.stock_greeks(S0)
    hedge = rk.solve_hedge(seller(), stock=stock, rows=("vega",), reference_value=NOTIONAL)
    assert hedge.status == "singular" and np.isnan(hedge.n_stock)


# ---------------------------------------------------------------- D7

def test_d7_put_only_slide_21():
    res = rk.put_only_hedge(seller(), deck_put())
    assert res.n_put == pytest.approx(2.90, rel=.01)
    assert res.dollars == pytest.approx(15.1, rel=.01)
    assert res.jump_cover == pytest.approx(.71, rel=.01)
    assert rk.put_only_ratio(seller(), deck_put()) == res.n_put


def test_d7_put_only_gx():
    tgt = gx_bond_greeks()
    res = rk.put_only_hedge(tgt, gx_put(7.5))
    assert res.n_put == pytest.approx(12.04, rel=.01)
    assert res.dollars == pytest.approx(30.3, rel=.01)
    assert res.jump_cover == pytest.approx(.95, rel=.01)


# ---------------------------------------------------------------- Appendix A and T1, T2: GX numbers the plan prints

def test_appendix_a_gx_bond_risk():
    g = gx_bond_greeks()
    assert g.value == pytest.approx(81.79, abs=.02)
    assert g.delta == pytest.approx(2.697, abs=.002)
    assert g.delta * GX_S == pytest.approx(28.32, abs=.02)
    assert g.vega == pytest.approx(-62.25, abs=.05)
    assert g.jump == pytest.approx(-51.79, abs=.02)


@pytest.mark.parametrize("K, put, delta, vega, jump, dj_n, dj_s, dv_n, dv_s", [
    (5., 1.485, -.149, 2.60, 2.908, 17.41, -1.2, 23.96, 9.1),
    (7.5, 2.515, -.224, 3.50, 4.073, 13.63, 3.7, 17.78, 13.5),
    (10., 3.735, -.297, 4.14, 5.049, 12.16, 9.6, 15.05, 18.6),
])
def test_appendix_a_gx_put_hedges(K, put, delta, vega, jump, dj_n, dj_s, dv_n, dv_s):
    p, s, tgt = gx_put(K), rk.stock_greeks(GX_S), gx_bond_greeks()
    assert (p.value, p.delta, p.vega, p.jump) == pytest.approx((put, delta, vega, jump), abs=.006)
    dj = rk.solve_hedge(tgt, put=p, stock=s, rows=("delta", "jump"), reference_value=tgt.value)
    dv = rk.solve_hedge(tgt, put=p, stock=s, rows=("delta", "vega"), reference_value=tgt.value)
    assert (dj.n_put, dj.dollars[1]) == pytest.approx((dj_n, dj_s), abs=.06)
    assert (dv.n_put, dv.dollars[1]) == pytest.approx((dv_n, dv_s), abs=.06)


def test_t1_hedge_covers_25_to_93_percent_of_the_jump_on_the_gx_bond():
    def cover(s):
        g = rk.bond_greeks(e2c.Bond(.095, 8., 2), s, GX_B, .42, CURVE, GX_REC, face=100.)
        return g.delta * s / -g.jump
    assert cover(30.) == pytest.approx(.254, abs=.003)
    assert cover(1.8) == pytest.approx(.928, abs=.003)


def test_t2_gx_vega_stays_open_and_net_short():
    tgt, p = gx_bond_greeks(), gx_put(7.5)
    hedge = rk.solve_hedge(tgt, put=p, stock=rk.stock_greeks(GX_S), rows=("delta", "jump"), reference_value=tgt.value)
    assert rk.net_greeks(tgt, hedge, put=p, stock=rk.stock_greeks(GX_S)).vega == pytest.approx(-14.5, abs=.1)


# ---------------------------------------------------------------- Independent of the formulas being tested

def bs_exact(S, K, T, vol, r, p):
    """Black-Scholes put greeks, in closed form. Vega is per 1.00 scale of vol, as the plan's is."""
    sd = vol * np.sqrt(T)
    d1 = (np.log(S / K) + (r - p) * T + .5 * sd ** 2) / sd
    pdf = np.exp(-.5 * d1 ** 2) / np.sqrt(2 * np.pi)
    return (np.exp(-p * T) * (N(d1) - 1), np.exp(-p * T) * pdf / (S * sd), S * np.exp(-p * T) * pdf * sd)


def test_put_greeks_reach_closed_form_black_scholes_as_the_barrier_vanishes():
    S, K, T, vol, r, p = 10.5, 10., 1., .5, .05, .02
    g = rk.put_greeks(S, K, T, vol, 1e-9, r, p)
    delta, gamma, vega = bs_exact(S, K, T, vol, r, p)
    assert g.delta == pytest.approx(delta, abs=1e-3)
    assert g.gamma == pytest.approx(gamma, abs=1e-3)
    assert g.vega == pytest.approx(vega, abs=1e-3)


def test_put_call_parity_on_the_greeks():
    S, K, T, sig, r, p = S0, 45., 2., SIG0, .05, .02
    put, call = rk.put_greeks(S, K, T, sig, B0, r, p), rk.call_greeks(S, K, T, sig, B0, r, p)
    assert call.delta - put.delta == pytest.approx(np.exp(-p * T), abs=1e-9)
    assert call.gamma == pytest.approx(put.gamma, abs=1e-7)
    assert call.vega == pytest.approx(put.vega, abs=1e-9)
    assert call.value - put.value == pytest.approx(S * np.exp(-p * T) - K * np.exp(-r * T), abs=1e-12)


@pytest.mark.parametrize("make", [
    lambda s_bump, vol_bump: rk.cds_seller_greeks(TENOR, S0, B0, SIG0, CURVE, REC, COUPON, lam=.3, face=100., s_bump=s_bump, vol_bump=vol_bump),
    lambda s_bump, vol_bump: rk.bond_greeks(GX_BOND, GX_S, GX_B, GX_SIG, CURVE, GX_REC, face=100., s_bump=s_bump, vol_bump=vol_bump),
    lambda s_bump, vol_bump: rk.put_greeks(GX_S, 7.5, GX_T2, .465, GX_B, .05, s_bump=s_bump, vol_bump=vol_bump),
    lambda s_bump, vol_bump: rk.call_greeks(GX_S, 15., GX_T2, .465, GX_B, .05, s_bump=s_bump, vol_bump=vol_bump),
])
def test_greeks_settle_as_the_bump_shrinks(make):
    coarse, fine = make(.01, .001), make(.0025, .00025)
    assert fine.delta == pytest.approx(coarse.delta, rel=2e-3)
    assert fine.gamma == pytest.approx(coarse.gamma, rel=5e-3)
    assert fine.vega == pytest.approx(coarse.vega, rel=2e-3)


def test_bumps_are_one_percent_of_S_and_a_tenth_of_a_percent_of_vol():
    """Written out by hand from the pricer, with no fk_risk bump code."""
    S, K, T, sig = GX_S, 7.5, GX_T2, .465
    f = lambda s, c=1.: fk.fk_put(s, K, T, c * sig, GX_B, .05).price
    h = S * .01
    g = gx_put(K)
    assert g.delta == pytest.approx((f(S + h) - f(S - h)) / (2 * h), abs=1e-12)
    assert g.gamma == pytest.approx((f(S + h) - 2 * f(S) + f(S - h)) / h ** 2, abs=1e-10)
    assert g.vega == pytest.approx((f(S, 1.001) - f(S, .999)) / .002, abs=1e-10)


def test_hedged_book_reprices_flat_and_pays_out_as_solved():
    """Reprice the whole book at new S and new vol, from the pricers alone. Then pay out the default by hand."""
    K, Kc = 30., 60.
    S, sig, r, p, T = S0, SIG0, .05, .02, 2.
    tgt = rk.cds_seller_greeks(TENOR, S, B0, sig, CURVE, REC, COUPON, face=100.)
    put, call = rk.put_greeks(S, K, T, sig, B0, r, p), rk.call_greeks(S, Kc, T, sig, B0, r, p)
    h = rk.solve_hedge(tgt, put=put, stock=rk.stock_greeks(S), call=call, rows=("delta", "vega", "jump"), reference_value=NOTIONAL)
    assert h.status == "ok"

    def book(s, c=1.):
        cds = v.fk_cds(TENOR, v.survival_function(s, B0, c * sig), CURVE, REC)
        return (100 * (COUPON * cds.annuity - (1 - REC) * cds.default_leg)
                + h.n_put * fk.fk_put(s, K, T, c * sig, B0, r, p).price + h.n_stock * s
                + h.n_call * fk.fk_call(s, Kc, T, c * sig, B0, r, p))

    ds, dc = .1, .0005    # not the bumps inside fk_risk
    assert (book(S + ds) - book(S - ds)) / (2 * ds) == pytest.approx(0.0, abs=2e-3)
    assert (book(S, 1 + dc) - book(S, 1 - dc)) / (2 * dc) == pytest.approx(0.0, abs=2e-2)

    on_default = -90. + h.n_put * (K * np.exp(-r * T) - put.value) - h.n_stock * S - h.n_call * call.value
    assert on_default == pytest.approx(0.0, abs=1e-8)


def test_stock_greeks():
    assert tuple(rk.stock_greeks(S0)) == (S0, 1.0, 0.0, 0.0, -S0)


def test_jumps_by_instrument():
    assert seller().jump == -90.0
    g = seller(include_value=True)
    assert g.jump == pytest.approx(-90.0 - g.value, abs=1e-12)
    bond = gx_bond_greeks()
    assert bond.jump == pytest.approx(-(bond.value - 30.0), abs=1e-12)
    put = deck_put()
    assert (put.value, put.jump) == (PUT_PRICE, pytest.approx(30 * np.exp(-.1) - PUT_PRICE, abs=1e-12))
    call = deck_call()
    assert (call.value, call.jump) == (CALL_PRICE, -CALL_PRICE)
    assert rk.put_greeks(S0, 30., 2., SIG0, B0, .05, .02).value == pytest.approx(5.194, abs=.001)
    assert rk.call_greeks(S0, 60., 2., SIG0, B0, .05, .02).value == pytest.approx(6.258, abs=.001)


def test_face_scales_everything():
    one = rk.bond_greeks(GX_BOND, GX_S, GX_B, GX_SIG, CURVE, GX_REC)
    hundred = gx_bond_greeks()
    assert tuple(hundred) == pytest.approx(tuple(100 * x for x in one), rel=1e-12)
    cds_one = rk.cds_seller_greeks(TENOR, S0, B0, SIG0, CURVE, REC, COUPON, lam=.3)
    assert tuple(seller()) == pytest.approx(tuple(100 * x for x in cds_one), rel=1e-12)


def test_cds_at_its_own_par_coupon_is_worth_nothing():
    par = v.fk_cds(TENOR, v.survival_function(S0, B0, SIG0), CURVE, REC).par
    assert rk.cds_seller_greeks(TENOR, S0, B0, SIG0, CURVE, REC, par).value == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------- Step 28 edge

def test_optimal_strike_reports_no_root():
    tgt = seller()._replace(jump=-1e6)
    fit = rk.optimal_strike(tgt, S0, 2., SIG0, B0, .05, .02)
    assert fit.status == "no_root" and np.isnan(fit.strike) and np.isnan(fit.n_put)


# ---------------------------------------------------------------- Step 29

@pytest.mark.parametrize("held, target, days, rule, due", [
    (100, 105, 1, "band", False),
    (100, 110, 1, "band", False),     # exactly 10% is inside the band
    (100, 111, 1, "band", True),
    (100, 89, 1, "band", True),
    (100, 91, 1, "band", False),
    (100, -5, 1, "band", True),       # a sign flip is always outside
    (-100, -111, 1, "band", True),
    (-100, -105, 1, "band", False),
    (100, 100, 7, "band", True),
    (100, 100, 6, "band", False),
    (0, 5, 1, "band", True),          # nothing held, so any target is outside
    (0, 0, 1, "band", False),
    (100, 100, 7, "weekly", True),
    (100, 200, 6, "weekly", False),
    (100, 200, 400, "static", False),
])
def test_rehedge_due(held, target, days, rule, due):
    assert rk.rehedge_due(held, target, days, rule=rule) is due


def test_rehedge_rejects_an_unknown_rule():
    with pytest.raises(ValueError):
        rk.rehedge_due(100, 100, 1, rule="daily")
