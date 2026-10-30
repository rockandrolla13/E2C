"""Acceptance tests A1-A12 and B1-B6 of finkelstein_replication_plan.pdf, Section 9.

Expected values come from that table. r = 5% and p = 0 unless stated, because the deck does not print r for these slides.
"""
from datetime import date

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.optimize import brentq, least_squares
from scipy.special import ndtr as N

import fk_model as fk

D0 = date(2001, 6, 14)
T1 = (date(2003, 1, 17) - D0).days / 365.0   # 1.59 years
T2 = (date(2004, 1, 16) - D0).days / 365.0   # 2.59 years
# Slide 8: strike -> (market vol, deck's model vol)
GX1 = {5: (.960, .963), 7.5: (.884, .876), 10: (.822, .823), 12.5: (.799, .788), 15: (.776, .762)}
GX2 = {5: (.931, .916), 7.5: (.856, .835), 10: (.783, .783), 12.5: (.752, .750), 15: (.723, .724)}
R = .05


def par_spread(T, S0, B, sig, r, rec, freq=4, steps_per_year=96):
    """CDS par by steps 13 and 14. WP2 owns the CDS code. This is only what B4 needs. Lambda 0, so no remedy."""
    grid = np.linspace(0, T, int(round(T * steps_per_year)) + 1)
    q = fk.fk_curve(grid, S0, B, sig, 0.0)
    mid = .5 * (grid[1:] + grid[:-1])
    default_leg = np.sum(np.exp(-r * mid) * (q[:-1] - q[1:]))
    pay = np.arange(1, int(round(T * freq)) + 1) / freq
    annuity = np.sum(np.exp(-r * pay) * fk.fk_curve(pay, S0, B, sig, 0.0)) / freq + default_leg / (2 * freq)
    return (1 - rec) * default_leg / annuity


# ---------------------------------------------------------------- A. Limits and identities

def test_a1_survival_at_zero():
    assert float(fk.fk_survival(0.0, 15, 15, .3, 0.0)) == pytest.approx(1.0, abs=1e-4)
    assert float(fk.fk_survival(0.0, 15, 15, .3, .3)) == pytest.approx(.9867, abs=1e-4)
    assert float(fk.fk_survival(0.0, 30, 15, .3, .3)) == pytest.approx(.999867, abs=1e-4)


@pytest.mark.parametrize("lam", [0.0, .3])
def test_a2_survival_never_rises(lam):
    q = fk.fk_survival(np.linspace(.01, 30, 400), 30, 15, .3, lam)
    assert np.all(np.diff(q) <= 1e-15)


def test_a3_matches_e2c_bond_survival():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
    import e2c_bond as e2c
    S, Lbar, D, sig_s, lam = 30.0, .5, 28.0, .38, .3
    firm = e2c.Firm(S, D, sig_s, Lbar, lam)
    t = np.array([.25, 1, 5, 10.])
    ours = fk.fk_survival(t, S, Lbar * D, e2c.asset_vol(firm), lam)
    assert ours == pytest.approx(np.asarray(e2c.survival(t, firm)), abs=1e-12)


def test_a4_eq1_is_slide_11_averaged_over_barrier():
    S, Bb, sg, lam, T = 15., 15., .25, .3, 1.
    x, w = np.polynomial.hermite_e.hermegauss(200)
    w = w / w.sum()
    bx = Bb * np.exp(lam * x - .5 * lam ** 2)
    d, sd = (S + Bb) / bx, sg * np.sqrt(T)
    average = np.sum(w * (N(np.log(d) / sd - sd / 2) - d * N(-np.log(d) / sd - sd / 2)))
    assert average == pytest.approx(.934494, abs=1e-5)
    assert float(fk.fk_survival(T, S, Bb, sg, lam)) == pytest.approx(.934494, abs=1e-5)
    assert fk.des_survival(T, S + Bb, Bb, sg, .05, .05, lam) == pytest.approx(.936004, abs=1e-5)


def test_a5_knock_out_closed_form_against_integration():
    S0, K, T, sig, B = 10.5, 7.5, 1.59, .498, 6.0
    V0, H, sd = S0 + B, B + K * np.exp(-R * T), sig * np.sqrt(T)
    dens = lambda v, x: np.exp(-.5 * ((np.log(v / x) + .5 * sd ** 2) / sd) ** 2) / (v * sd * np.sqrt(2 * np.pi))
    direct = quad(lambda v: (H - v) * (dens(v, V0) - V0 / B * dens(v, B ** 2 / V0)), B, H, limit=200)[0]
    assert direct == pytest.approx(.90310541, abs=1e-7)
    assert fk.fk_put(S0, K, T, sig, B, R).diffusion == pytest.approx(.90310541, abs=1e-7)


def test_a6_small_barrier_is_black_scholes():
    assert fk.fk_put(10.5, 10, 1, .5, 1e-4, R).price == pytest.approx(1.5191, abs=1e-3)
    assert fk.bs_put(10.5, 10, 1, .5, R) == pytest.approx(1.5191, abs=1e-3)


def test_a7_small_strike_put_gives_default_probability():
    price = fk.fk_put(10.5, .001, T2, .465, 6, R).price
    assert price / (.001 * np.exp(-R * T2)) == pytest.approx(.2801, abs=1e-3)


def test_a8_small_strike_call_is_the_forward_value():
    assert fk.fk_call(10.5, 1e-6, 2, .5, 6, R, .02) == pytest.approx(10.0883, abs=1e-4)


def test_a9_slide_6_equity_vol_rule():
    assert fk.equity_vol_from_asset(.55, 2, 4) == pytest.approx(1.650, abs=1e-3)
    assert fk.equity_vol_from_asset(.55, 12, 4) == pytest.approx(.733, abs=1e-3)


def test_a10_remedy():
    S, B, sig, lam = 15., 15., .3, .3
    assert float(fk.fk_curve(0.0, S, B, sig, lam)) == pytest.approx(1.0, abs=1e-12)
    half = float(fk.fk_survival(.5, S, B, sig, lam))
    assert float(fk.fk_curve(.5, S, B, sig, lam)) == pytest.approx(half, abs=1e-12)
    assert float(fk.fk_curve(.5 - 1e-10, S, B, sig, lam)) == pytest.approx(half, abs=1e-9)
    grid = np.array([.05, .1, .2, .4])
    hazard = -np.log(fk.fk_curve(grid, S, B, sig, lam)) / grid
    assert hazard == pytest.approx(np.full(4, hazard[0]), abs=1e-12)


def test_a11_des_survival_at_zero_drift():
    assert fk.des_survival(1., 45., 15., .30, .05, .05, .3) == pytest.approx(.990967, abs=1e-5)
    assert fk.des_survival(1., 20., 15., .25, .05, .05, .3) == pytest.approx(.640711, abs=1e-5)


@pytest.mark.parametrize("s_over_d, share", [(4., .800), (1., .600), (.5, .467), (.25, .360)])
def test_a12_asset_vol_rule(s_over_d, share):
    assert fk.asset_vol_fs(1., s_over_d, 1.) == pytest.approx(share, abs=1e-3)


# ---------------------------------------------------------------- B. Options against the deck

@pytest.mark.parametrize("T, sig, table", [(T1, .498, GX1), (T2, .465, GX2)])
def test_b1_slide_8_model_vols(T, sig, table):
    for K, (_, deck) in table.items():
        assert fk.fk_implied_vol(10.5, K, T, sig, 6.0, R) == pytest.approx(deck, abs=.0015), K


def test_b2_fit_market_vols_of_slide_8():
    def gaps(x):
        out = []
        for T, s, table in ((T1, x[1], GX1), (T2, x[2], GX2)):
            out += [fk.fk_implied_vol(10.5, K, T, s, x[0], R) - v[0] for K, v in table.items()]
        return np.array(out)
    fit = least_squares(gaps, [5., .5, .5], bounds=([.1, .05, .05], [50, 2, 2]))
    assert fit.x[0] == pytest.approx(6.01, abs=.25)
    assert fit.x[1] == pytest.approx(.500, abs=.01)
    assert fit.x[2] == pytest.approx(.469, abs=.01)
    assert np.sqrt(np.mean(fit.fun ** 2)) * 100 == pytest.approx(.81, abs=.05)


def test_b3_forward_vol():
    assert fk.forward_vol(T1, .498, T2, .465) == pytest.approx(.407, abs=.001)


@pytest.mark.parametrize("r, b, pd, par", [(.03, 6.95, .1496, 544), (.05, 6.80, .1440, 519)])
def test_b4_slide_1_from_two_vols(r, b, pd, par):
    def res(x):
        return [fk.fk_implied_vol(15, 15, 2, x[1], x[0], r) - .72, fk.fk_implied_vol(15, 10.5, 2, x[1], x[0], r) - .77]
    B, sig = least_squares(res, [5., .5], bounds=([.01, .05], [100, 2.])).x
    assert B == pytest.approx(b, abs=.05)
    assert 1 - float(fk.fk_survival(2, 15, B, sig)) == pytest.approx(pd, abs=.001)
    assert par_spread(2, 15, B, sig, r, .3) * 1e4 == pytest.approx(par, abs=2)


@pytest.mark.parametrize("r, mine", [(.03, .766), (.05, .767)])
def test_b5_slide_1_predicted_otm_vol(r, mine):
    def res(x):
        return [fk.fk_implied_vol(15, 15, 2, x[1], x[0], r) - .72, 1 - float(fk.fk_survival(2, 15, x[0], x[1])) - .136]
    B, sig = least_squares(res, [5., .5], bounds=([.01, .05], [100, 2.])).x
    vol = fk.fk_implied_vol(15, 10.5, 2, sig, B, r)
    assert vol == pytest.approx(mine, abs=.001)
    assert vol == pytest.approx(.77, abs=.005)


@pytest.mark.parametrize("B, expected", [(10., (.99, .82, .74, .70)), (5., (.94, .82, .77, .74)), (1., (.85, .82, .81, .80))])
def test_b6_slide_7_skew(B, expected):
    sig = brentq(lambda s: fk.fk_implied_vol(10.5, 10.5, 1.5, s, B, 0.0) - .82, .05, 1.5)
    vols = [fk.fk_implied_vol(10.5, x * 10.5, 1.5, sig, B, 0.0) for x in (.5, 1, 1.5, 2)]
    assert vols == pytest.approx(list(expected), abs=.01)


# ---------------------------------------------------------------- Identities the plan's table implies

def test_put_splits_into_its_parts_and_call_obeys_parity():
    p = fk.fk_put(10.5, 7.5, 1.59, .498, 6.0, R, .01)
    assert p.price == pytest.approx(p.default + p.diffusion, abs=1e-14)
    assert p.default == pytest.approx(7.5 * np.exp(-R * 1.59) * (1 - float(fk.fk_survival(1.59, 10.5, 6.0, .498))), abs=1e-14)
    call = fk.fk_call(10.5, 7.5, 1.59, .498, 6.0, R, .01)
    assert call - p.price == pytest.approx(10.5 * np.exp(-.01 * 1.59) - 7.5 * np.exp(-R * 1.59), abs=1e-12)


def test_bs_implied_vol_round_trip():
    assert fk.bs_implied_vol(fk.bs_put(15, 12, 2, .6, .03, .01), 15, 12, 2, .03, .01) == pytest.approx(.6, abs=1e-8)


def test_put_against_monte_carlo_with_no_reflection_formula():
    """Independent of the closed form. Simulates V, kills paths by a Brownian-bridge barrier test, prices the payoff."""
    S0, K, T, sig, B, r = 10.5, 10.0, 1.59, .498, 6.0, .05
    rng = np.random.default_rng(20020628)
    paths, steps = 400_000, 64
    dt = T / steps
    logv = np.full(paths, np.log(S0 + B))
    alive = np.ones(paths, dtype=bool)
    for _ in range(steps):
        z = rng.standard_normal(paths)
        new = logv - .5 * sig ** 2 * dt + sig * np.sqrt(dt) * z
        a, b = logv - np.log(B), new - np.log(B)
        crossed = (a <= 0) | (b <= 0) | (rng.random(paths) < np.exp(-2 * np.clip(a, 0, None) * np.clip(b, 0, None) / (sig ** 2 * dt)))
        alive &= ~crossed
        logv = new
    stock = np.where(alive, (np.exp(logv) - B) * np.exp(r * T), 0.0)
    payoff = np.exp(-r * T) * np.maximum(K - stock, 0.0)
    se = payoff.std() / np.sqrt(paths)
    assert fk.fk_put(S0, K, T, sig, B, r).price == pytest.approx(payoff.mean(), abs=4 * se)
    assert float(fk.fk_survival(T, S0, B, sig)) == pytest.approx(alive.mean(), abs=4 * np.sqrt(alive.mean() * (1 - alive.mean()) / paths))
