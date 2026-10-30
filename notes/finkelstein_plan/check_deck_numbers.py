#!/usr/bin/env python3
"""Check Finkelstein's deck numbers against the formulas on his slides.

Run:  python3 check_deck_numbers.py | tee check_deck_numbers.out

"Slide N" is the number printed on the slide. PDF page = slide + 1.
Inputs the deck does not state are marked ASSUMED where they are set.
It uses only numbers printed in the deck, plus one read-only import of e2c_bond.py.
Runtime is a few seconds.
"""
import sys
sys.dont_write_bytecode = True

from datetime import date
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq, least_squares
from scipy.special import ndtr as N

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))  # pinned copy, so this branch stands alone
import e2c_bond as e2c  # noqa: E402  Read only. That file belongs to another agent.


# --------------------------------------------------------------------------------------
# Deck formulas
# --------------------------------------------------------------------------------------

def survival(T, S0, B, sig, lam=0.0):
    """Slide 11 when lam = 0. Slide 18 Eq. (1) when lam > 0. sig is sigma_cum(T)."""
    T = np.asarray(T, dtype=float)
    d = (S0 + B) / B * np.exp(lam ** 2)
    A = np.sqrt(np.asarray(sig, dtype=float) ** 2 * T + lam ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(d) / A
        out = N(ratio - A / 2) - d * N(-ratio - A / 2)
    return np.where(A > 0, out, 1.0)


def survival_with_remedy(t, S, B, sig, lam):
    """Slide 19: Eq. (1) from T = 0.5. Flat intensity between 1 and Q(0.5) below that."""
    if t >= .5 or lam == 0:
        return float(survival(t, S, B, sig, lam))
    return float(survival(.5, S, B, sig, lam)) ** (t / .5)


def bs_put(S, K, T, vol, r, q=0.0):
    sd = vol * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q) * T + 0.5 * sd ** 2) / sd
    return K * np.exp(-r * T) * N(-(d1 - sd)) - S * np.exp(-q * T) * N(-d1)


def bs_implied_vol(price, S, K, T, r, q=0.0):
    return brentq(lambda v: bs_put(S, K, T, v, r, q) - price, 1e-4, 10.0)


def _put_above_barrier(x, H, B, sd):
    """E[(H - V_T)^+ ; V_T > B] for a driftless lognormal V_T starting from x."""
    def d1(K):
        return (np.log(x / K) + 0.5 * sd ** 2) / sd
    return (H * (N(-(d1(H) - sd)) - N(-(d1(B) - sd)))
            - x * (N(-d1(H)) - N(-d1(B))))


def model_put(S0, K, T, sig, B, r, p=0.0):
    """European put on the stock of slides 4 and 6: (price, default part, diffusion part).

    S_T = (V_T - B) exp((r-p)T) if V never touches B, else 0.
    The deck says this "can be done in a closed form" (slide 6) and prints no formula.
    This is the reflection principle, derived here. Section C tests it against slide 8.
    """
    V0 = S0 + B
    H = B + K * np.exp(-(r - p) * T)
    sd = sig * np.sqrt(T)
    ko = (_put_above_barrier(V0, H, B, sd)
          - (V0 / B) * _put_above_barrier(B ** 2 / V0, H, B, sd))
    diffusion = np.exp(-p * T) * ko
    default = K * np.exp(-r * T) * (1.0 - float(survival(T, S0, B, sig)))
    return default + diffusion, default, diffusion


def model_call(S0, K, T, sig, B, r, p=0.0):
    """Put-call parity. It holds because (V - B) stopped at B is a martingale."""
    return model_put(S0, K, T, sig, B, r, p)[0] + S0 * np.exp(-p * T) - K * np.exp(-r * T)


def cds_legs(T, S0, B, sig, r, freq=4, lam=0.0, accrual=True, steps_per_year=96, remedy=True):
    """Annuity and default leg per 1 of notional. The deck prints no CDS formula. ASSUMED form.

    Premium paid freq times a year in arrears. Default paid when it happens.
    sig is a constant or a function returning sigma_cum(T).
    """
    sig_at = sig if callable(sig) else (lambda t: sig)
    q_at = (lambda t: survival_with_remedy(t, S0, B, sig_at(max(t, .5)), lam)) if remedy else \
        (lambda t: float(survival(t, S0, B, sig_at(t), lam)))
    grid = np.linspace(0.0, T, int(round(T * steps_per_year)) + 1)
    q = np.array([1.0] + [q_at(t) for t in grid[1:]])
    mid = 0.5 * (grid[1:] + grid[:-1])
    default_leg = float(np.sum(np.exp(-r * mid) * (q[:-1] - q[1:])))
    pay = T - np.arange(int(np.ceil(T * freq - 1e-9)))[::-1] / freq
    annuity = float(np.sum(np.exp(-r * pay) * np.array([q_at(t) for t in pay])) / freq)
    if accrual:
        annuity += 0.5 / freq * default_leg
    return annuity, default_leg


def par_spread(T, S0, B, sig, r, R, **kw):
    a, d = cds_legs(T, S0, B, sig, r, **kw)
    return (1 - R) * d / a


def bond_full_price(coupon, maturity, S0, B, sig, r, R, freq=2, lam=0.0):
    """Full price per 100. Recovery of par paid at default. ASSUMED form. Same as e2c_bond."""
    sig_at = sig if callable(sig) else (lambda t: sig)
    n = int(np.ceil(maturity * freq - 1e-9))
    t = maturity - np.arange(n)[::-1] / freq
    cf = np.full(n, coupon / freq)
    cf[-1] += 100.0
    q = np.array([float(survival(x, S0, B, sig_at(x), lam)) for x in t])
    grid = np.linspace(0.0, maturity, int(maturity * 96) + 1)
    qg = np.array([1.0] + [float(survival(x, S0, B, sig_at(x), lam)) for x in grid[1:]])
    mid = 0.5 * (grid[1:] + grid[:-1])
    return float(np.sum(cf * np.exp(-r * t) * q)) + R * 100.0 * float(
        np.sum(np.exp(-r * mid) * (qg[:-1] - qg[1:])))


def accrued_30_360(coupon, d0, last=(5, 15)):
    days = (d0.month - last[0]) * 30 + (min(d0.day, 30) - last[1])
    return coupon * days / 360.0


def years(a, b):
    return (b - a).days / 365.0


def show(label, deck, mine, note=""):
    print(f"  {label:<50} deck {deck:>8}   mine {mine:>8}   {note}")


# --------------------------------------------------------------------------------------
# A. Slide 1
# --------------------------------------------------------------------------------------

def section_a():
    print("\nA. SLIDE 1: put prices, default probability, default cost")
    S, T = 15.0, 2.0
    show("ATM put, r=3% continuous, q=0", "4.92", f"{bs_put(S, 15, T, .72, .03):.3f}", "NO")
    show("OTM put, r=3% continuous, q=0", "2.72", f"{bs_put(S, 10.5, T, .77, .03):.3f}", "NO")
    show("ATM put, 3% annual compounding", "4.92", f"{bs_put(S, 15, T, .72, np.log(1.03)):.3f}", "NO")
    show("OTM put, 3% annual compounding", "2.72", f"{bs_put(S, 10.5, T, .77, np.log(1.03)):.3f}", "NO")
    print("  Which one input reproduces both puts?")
    print(f"    rate:     ATM needs {brentq(lambda x: bs_put(S, 15, T, .72, x) - 4.92, 0, .2):.4f}, "
          f"OTM needs {brentq(lambda x: bs_put(S, 10.5, T, .77, x) - 2.72, 0, .2):.4f}")
    print(f"    maturity: ATM needs {brentq(lambda x: bs_put(S, 15, x, .72, .03) - 4.92, .5, 3):.3f}, "
          f"OTM needs {brentq(lambda x: bs_put(S, 10.5, x, .77, .03) - 2.72, .5, 3):.3f}")
    print(f"    implied vol at r=3%: ATM {bs_implied_vol(4.92, S, 15, T, .03):.4f}, "
          f"OTM {bs_implied_vol(2.72, S, 10.5, T, .03):.4f}")
    fit = least_squares(lambda x: [bs_put(S, 15, T, .72, x[0]) - 4.92,
                                   bs_put(S, 10.5, T, .77, x[0]) - 2.72], [0.04])
    print(f"    best single r = {fit.x[0]:.4f}: gives {bs_put(S, 15, T, .72, fit.x[0]):.3f} "
          f"and {bs_put(S, 10.5, T, .77, fit.x[0]):.3f}")

    print("  Two-year default probability from CDS 530bp, R=30%")
    show("continuous premium, flat hazard", "13.6%", f"{1 - np.exp(-2 * .053 / .7):.2%}", "too high")
    for freq, name in ((4, "quarterly"), (2, "semiannual"), (1, "annual")):
        h = np.log(1 + .053 / .7 / freq) * freq
        pd = 1 - np.exp(-2 * h)
        show(f"{name} premium, default at period end", "13.6%", f"{pd:.2%}",
             "YES" if abs(pd - .136) < .0005 else "")

    print("  Default cost")
    show("15 x 0.136 / 1.03^2, the slide's own formula", "1.90", f"{15 * .136 / 1.03 ** 2:.3f}", "1.2% high")
    show("10.5 x 0.136 / 1.03^2, same formula at K=10.5", "1.42", f"{10.5 * .136 / 1.03 ** 2:.3f}", "NO, 5.2% low")
    show("10.5 x 0.136, no discount", "1.42", f"{10.5 * .136:.3f}", "nearest simple match")
    print(f"    Ratio 1.42/1.90 = {1.42 / 1.90:.3f}. Ratio of strikes = {10.5 / 15:.3f}. "
          "Any K x PD x DF rule forces these to be equal.")
    print(f"    Default share of the put: ATM {1.90 / 4.92:.1%}, OTM {1.42 / 2.72:.1%}.")

    print("  The whole of slide 1 from the model. (B, sig) solved, K=15 and K=10.5.")
    for r in (.03, .048, .05):
        def res(x):
            return [bs_implied_vol(model_put(15, 15, 2, x[1], x[0], r)[0], 15, 15, 2, r) - .72,
                    bs_implied_vol(model_put(15, 10.5, 2, x[1], x[0], r)[0], 15, 10.5, 2, r) - .77]
        B, s = least_squares(res, [5., .5], bounds=([.01, .05], [100, 2.])).x
        print(f"    From two option vols only, r={r}: B={B:.2f}, sig={s:.3f}, "
              f"2y PD={1 - float(survival(2, 15, B, s)):.4f} (deck 0.136), "
              f"2y par R=30%={par_spread(2, 15, B, s, r, .3) * 1e4:.0f}bp (deck 530)")
    for r in (.03, .05):
        def res(x):
            return [bs_implied_vol(model_put(15, 15, 2, x[1], x[0], r)[0], 15, 15, 2, r) - .72,
                    1 - float(survival(2, 15, x[0], x[1])) - .136]
        B, s = least_squares(res, [5., .5], bounds=([.01, .05], [100, 2.])).x
        vo = bs_implied_vol(model_put(15, 10.5, 2, s, B, r)[0], 15, 10.5, 2, r)
        print(f"    From ATM vol and PD=0.136, r={r}: B={B:.2f}, sig={s:.3f}. "
              f"Predicted OTM vol {vo:.1%} (deck 77%)")


# --------------------------------------------------------------------------------------
# B. Vol identities
# --------------------------------------------------------------------------------------

def section_b():
    print("\nB. SLIDES 6, 8, 19: vol identities")
    f = lambda sig, S, B: sig * (S + B) / S
    show("slide 6 chart at S=2, B=4, sig=55%", "~165%", f"{f(.55, 2, 4):.1%}", "YES")
    show("slide 6 chart at S=12, B=4, sig=55%", "~73%", f"{f(.55, 12, 4):.1%}", "YES")
    show("slide 8: 0.42 x debt per share 14.2", "6", f"{.42 * 14.2:.2f}", "YES")
    show("slide 19 left: sig_S from sig=41%, S/B=1.75", "64.5%", f"{f(.41, 1.75, 1):.1%}", "YES")
    show("slide 19 right: sig_S from sig=22.2%, S/B=0.8", "40%", f"{f(.222, .8, 1):.1%}", "NO")
    show("slide 19 right: sig from sig_S=40%, S/B=0.8", "22.2%", f"{.40 * .8 / 1.8:.1%}", "NO")
    show("slide 19 right: sig from sig_S=40%, B/S=0.8", "22.2%", f"{.40 / 1.8:.1%}", "YES: S/B and B/S mixed")


# --------------------------------------------------------------------------------------
# C. GX skew, slide 8
# --------------------------------------------------------------------------------------

D0 = date(2001, 6, 14)
GX_T1 = (years(D0, date(2003, 1, 17)), .498,
         {5: (.960, .963), 7.5: (.884, .876), 10: (.822, .823), 12.5: (.799, .788), 15: (.776, .762)})
GX_T2 = (years(D0, date(2004, 1, 16)), .465,
         {5: (.931, .916), 7.5: (.856, .835), 10: (.783, .783), 12.5: (.752, .750), 15: (.723, .724)})


def gx_gap(r, p=0.0):
    out = []
    for T, sig, table in (GX_T1, GX_T2):
        for K, (_, model) in table.items():
            out.append(bs_implied_vol(model_put(10.5, K, T, sig, 6.0, r, p)[0], 10.5, K, T, r, p) - model)
    return np.array(out)


def gx_market_gap(x, r=.05):
    B, s1, s2 = x
    out = []
    for (T, _, table), s in zip((GX_T1, GX_T2), (s1, s2)):
        for K, (mkt, _) in table.items():
            out.append(bs_implied_vol(model_put(10.5, K, T, s, B, r)[0], 10.5, K, T, r) - mkt)
    return np.array(out)


def section_c():
    print("\nC. SLIDE 8: GX model vols. S=10.5, B=6. r not in the deck.")
    for r in (0.0, 0.02, 0.04, 0.05, 0.06):
        e = gx_gap(r)
        print(f"    r={r:.2f}, p=0: largest gap {np.abs(e).max() * 100:5.2f} vol pts, mean {np.abs(e).mean() * 100:5.2f}")
    r = least_squares(lambda x: gx_gap(x[0]), [0.04]).x[0]
    print(f"    Best r with p=0: {r:.4f}. Largest gap {np.abs(gx_gap(r)).max() * 100:.2f} vol pts.")
    print("    K      T   market  deck    mine    put    default  diffusion  default share")
    for T, sig, table in (GX_T1, GX_T2):
        for K, (mkt, model) in table.items():
            price, dflt, diff = model_put(10.5, K, T, sig, 6.0, .05)
            mine = bs_implied_vol(price, 10.5, K, T, .05)
            print(f"    {K:>4} {T:5.2f} {mkt:6.1%} {model:6.1%} {mine:6.1%}  {price:6.3f} {dflt:7.3f} "
                  f"{diff:9.3f} {dflt / price:9.1%}")
    T1, T2 = GX_T1[0], GX_T2[0]
    print(f"    Forward asset vol {T1:.2f}y to {T2:.2f}y: "
          f"{np.sqrt((.465 ** 2 * T2 - .498 ** 2 * T1) / (T2 - T1)):.1%}")
    print(f"    Slide 6 rule at ATM: 82.2% x 10.5/16.5 = {.822 * 10.5 / 16.5:.1%} vs 49.8%. "
          f"78.3% x 10.5/16.5 = {.783 * 10.5 / 16.5:.1%} vs 46.5%.")
    print("  Calibrate on MARKET vols only, one barrier across both maturities, r=5%")
    f = least_squares(gx_market_gap, [5., .5, .5], bounds=([.1, .05, .05], [50, 2, 2]))
    print(f"    B={f.x[0]:.3f} (deck 6), sig1={f.x[1]:.3f} (deck .498), sig2={f.x[2]:.3f} (deck .465), "
          f"rmse {np.sqrt(np.mean(f.fun ** 2)) * 100:.2f} vol pts")
    for B in (2, 4, 5, 6, 7, 8, 10, 15):
        g = least_squares(lambda x: gx_market_gap([B, x[0], x[1]]), [.5, .46], bounds=([.05, .05], [2, 2]))
        print(f"    B={B:>2}: rmse {np.sqrt(np.mean(g.fun ** 2)) * 100:.2f} vol pts, "
              f"PD({T2:.2f}y)={1 - float(survival(T2, 10.5, B, g.x[1])):.3f}")


# --------------------------------------------------------------------------------------
# D. Slide 7, slide 10
# --------------------------------------------------------------------------------------

def section_d():
    print("\nD. SLIDE 7 chart. S=10.5, T=1.5, ATM BS vol 82%, r=0 ASSUMED.")
    print("    Chart by eye. K/F=.05: B=10 1.53, B=5 1.33, B=1 1.01. K/F=.5: .97, .90, .84. K/F=2: .68, .76, .80.")
    xs = (.05, .1, .15, .2, .25, .3, .5, 1, 1.5, 2)
    print("    K/F  " + " ".join(f"{x:5.2f}" for x in xs))
    for B in (1.0, 5.0, 10.0):
        sig = brentq(lambda s: bs_implied_vol(model_put(10.5, 10.5, 1.5, s, B, 0)[0], 10.5, 10.5, 1.5, 0) - .82, .05, 1.5)
        v = [bs_implied_vol(model_put(10.5, x * 10.5, 1.5, sig, B, 0)[0], 10.5, x * 10.5, 1.5, 0) for x in xs]
        print(f"    B={B:>4} sig={sig:.3f}: " + " ".join(f"{x:5.2f}" for x in v))
    print("    Shape and K/F >= .5 agree. Below .3 my values sit above the chart, by about one 0.05 axis step.")
    print("    Hidden caption sigma=.53, B=4, S=5, t=1.5 would give ATM near "
          f"{.53 * 9 / 5:.0%}. It does not describe this chart.")

    print("\n  SLIDE 10: EXDS asset vol from ATM vol, B=6.9. Readings by eye. Reference T=1y ASSUMED. r=5% ASSUMED.")
    pts = [(1, 53, .87, .77), (50, 40, .80, .72), (75, 50, .78, .70), (105, 33, .90, .78),
           (150, 24, .88, .76), (180, 20, .90, .74), (200, 12, .95, .75), (240, 8, 1.05, .80)]
    def asset(S, atm, B):
        p = bs_put(S, S, 1.0, atm, .05)
        return brentq(lambda v: model_put(S, S, 1.0, v, B, .05)[0] - p, .01, 3)
    for day, S, atm, chart in pts:
        print(f"    day {day:>3} S={S:>3} ATM={atm:.2f} chart asset vol {chart:.2f}, model {asset(S, atm, 6.9):.3f}")
    for B in (1, 2, 3, 4, 6.9):
        v = [asset(S, atm, B) for _, S, atm, _ in pts]
        print(f"    B={B}: std of asset vol across the 8 dates = {np.std(v):.3f}")


# --------------------------------------------------------------------------------------
# E. GX curve, bond, CDS
# --------------------------------------------------------------------------------------

def gx_sigma_cum():
    """49.8% to 1.59y, 46.5% to 2.59y, flat forward after. Flat forward is ASSUMED."""
    T1, T2 = GX_T1[0], GX_T2[0]
    v1, v2 = .498 ** 2 * T1, .465 ** 2 * T2
    fwd = (v2 - v1) / (T2 - T1)
    def sig(t):
        if t <= T1:
            return .498
        return np.sqrt((v1 + fwd * (t - T1)) / t)
    return sig


def flat_hazard_price(h, coupon, T, R, r, freq=2):
    n = int(np.ceil(T * freq - 1e-9))
    t = T - np.arange(n)[::-1] / freq
    cf = np.full(n, coupon / freq)
    cf[-1] += 100
    return float(np.sum(cf * np.exp(-(r + h) * t))) + R * 100 * h / (r + h) * (1 - np.exp(-(r + h) * T))


def section_e():
    print("\nE. SLIDE 12: GX curve. S=10.5, B=6, R=30%, lam=0, r=5% ASSUMED.")
    sig = gx_sigma_cum()
    read = {.5: .009, 1: .048, 1.5: .077, 2: .0815, 2.5: .084, 3: .085, 4: .0865, 5: .086, 7: .084, 9.5: .082}
    print("    Tenor  chart   bootstrapped   flat 46.5%")
    gaps = []
    for t, c in read.items():
        a, b = par_spread(t, 10.5, 6, sig, .05, .3), par_spread(t, 10.5, 6, .465, .05, .3)
        gaps.append(abs(a - c))
        print(f"    {t:>5} {c:7.2%} {a:10.2%} {b:12.2%}")
    print(f"    Largest gap, bootstrapped: {max(gaps) * 1e4:.0f} bp")
    print("    'Discount DI' read off the chart against par/(1-R):")
    for t, (di, cds) in {.5: (.013, .009), 1: (.069, .048), 1.5: (.110, .077), 2: (.116, .0815),
                         3: (.121, .085), 5: (.120, .086), 9.5: (.1095, .082)}.items():
        print(f"      T={t:>4}: DI {di:.2%}, par/0.7 {cds / .7:.2%}")

    print("\n  SLIDE 12: GX 9.5% 11/15/2009 bond, R=30%, r=5%, lam=0.")
    print("    date        S   market deck | boot full  boot clean | flat42 full  flat42 clean | accrued")
    for d0, S, mkt, model in ((D0, 10.5, 84, 82), (date(2001, 8, 31), 4.2, 60, 60), (date(2001, 10, 1), 1.8, 45, 43)):
        T = years(d0, date(2009, 11, 15))
        ac = accrued_30_360(9.5, d0)
        b, f = bond_full_price(9.5, T, S, 6.0, sig, .05, .30), bond_full_price(9.5, T, S, 6.0, .42, .05, .30)
        print(f"    {d0} {S:>4} {mkt:>5} {model:>5} | {b:8.1f} {b - ac:10.1f} | {f:10.1f} {f - ac:11.1f} | {ac:.2f}")

    print("\n  SLIDES 13-15: CDS to 1/3/06. B=6, sig=42%. r=5% ASSUMED.")
    T = years(date(2001, 10, 1), date(2006, 1, 3))
    for R, chart in ((.30, "~37%"), (.10, "~47%")):
        print(f"    S=1.8, R={R:.0%}: chart peak {chart}, mine {par_spread(T, 1.8, 6, .42, .05, R):.1%}")
    print(f"    S=27, 7/10/00, R=30%: chart ~2.5%, mine "
          f"{par_spread(years(date(2000, 7, 10), date(2006, 1, 3)), 27, 6, .42, .05, .30):.2%}")
    print("  Market CDS from the bond by a flat hazard fit. The deck does not state the fit. R=30%.")
    print("    Chart by eye: 8/31/01 about 18%, 10/1/01 about 31%. PV of a 300bp seller at the end about -53.")
    for d0, px in ((D0, 84), (date(2001, 8, 31), 60), (date(2001, 10, 1), 45)):
        Tb, Tc = years(d0, date(2009, 11, 15)), years(d0, date(2006, 1, 3))
        ac = accrued_30_360(9.5, d0)
        for lbl, pv in (("price as full", px), ("price as clean", px + ac)):
            h = brentq(lambda x: flat_hazard_price(x, 9.5, Tb, .3, .05) - pv, 1e-5, 5)
            ann = (1 - np.exp(-(.05 + h) * Tc)) / (.05 + h)
            print(f"    {d0} {lbl:<15} h={h:.4f}  par={.7 * h:.2%}  seller PV 300bp={(0.03 - .7 * h) * ann * 100:6.1f}")


# --------------------------------------------------------------------------------------
# F. Slide 19
# --------------------------------------------------------------------------------------

def section_f():
    print("\nF. SLIDE 19: par curves against lambda. R=30%, r=5% ASSUMED. Tenors 0.5,1,2,5,10.")
    tenors = (.5, 1, 2, 5, 10)
    left = {0: (.002, .019, .052, .077, .079), .2: (.008, .028, .057, .077, .078),
            .3: (.023, .040, .063, .077, .076), .4: (.048, .057, .069, .077, .075)}
    right = {0: (.000, .001, .009, .027, .033), .2: (.015, .019, .025, .032, .034),
             .3: (.078, .055, .046, .040, .037), .4: (.170, .101, .068, .048, .040)}
    for name, chart, cases in (("Left", left, ((1.75, .41), (1.75, .42))),
                               ("Right", right, ((.8, .222), (1.25, .222), (.8, .1778)))):
        for sb, sig in cases:
            err = []
            print(f"    {name}: S/B={sb}, sig={sig}")
            for lam, row in chart.items():
                v = [par_spread(t, sb, 1.0, sig, .05, .3, lam=lam) for t in tenors]
                err += [a - b for a, b in zip(v, row)]
                print(f"      lam={lam:<3}: " + " ".join(f"{x:.4f}" for x in v) + "   chart " + " ".join(f"{x:.3f}" for x in row))
            print(f"      rms gap to chart {np.sqrt(np.mean(np.square(err))) * 1e4:.0f} bp")


# --------------------------------------------------------------------------------------
# G. Limits and cross-checks
# --------------------------------------------------------------------------------------

def section_g():
    print("\nG. Limit checks")
    print(f"    Q(0), lam=0: {float(survival(1e-12, 30, 15, .3)):.6f}. Q(0), lam=.3, S/B=1: "
          f"{float(survival(0, 15, 15, .3, .3)):.4f}, S/B=2: {float(survival(0, 30, 15, .3, .3)):.6f}")
    print(f"    Q never rises with T: {bool(np.all(np.diff(survival(np.linspace(.01, 30, 200), 30, 15, .3)) <= 1e-15))}")
    print(f"    B -> 0, model put vs BS: {model_put(10.5, 10, 1, .5, 1e-4, .05)[0]:.5f} vs {bs_put(10.5, 10, 1, .5, .05):.5f}")
    for K in (1e-3, .1, 1, 2.5, 5, 7.5, 10):
        pr = model_put(10.5, K, 2.59, .465, 6, .05)[0]
        iv = bs_implied_vol(pr, 10.5, K, 2.59, .05)
        sd = iv * np.sqrt(2.59)
        delta = N((np.log(10.5 / K) + .05 * 2.59 + .5 * sd * sd) / sd) - 1
        print(f"    K={K:<6} P/(K DF) = {pr / (K * np.exp(-.05 * 2.59)):.4f}  PD = {1 - float(survival(2.59, 10.5, 6, .465)):.4f}"
              f"  BS delta = {delta:.3f}")
    # Closed form against direct integration of the killed density.
    S0, K, T, sig, B, r = 10.5, 7.5, 1.59, .498, 6.0, .05
    V0, H, sd = S0 + B, B + K * np.exp(-r * T), sig * np.sqrt(T)
    dens = lambda v, x: np.exp(-.5 * ((np.log(v / x) + .5 * sd ** 2) / sd) ** 2) / (v * sd * np.sqrt(2 * np.pi))
    ko = quad(lambda v: (H - v) * (dens(v, V0) - V0 / B * dens(v, B ** 2 / V0)), B, H, limit=200)[0]
    print(f"    Knock-out part by quadrature {ko:.8f}, closed form {model_put(S0, K, T, sig, B, r)[2]:.8f}")
    print(f"    Forward: model call at K -> 0 = {model_call(10.5, 1e-6, 2, .5, 6, .05, .02):.6f}, "
          f"S exp(-pT) = {10.5 * np.exp(-.04):.6f}")
    print("  Eq. (1) is the average of slide 11 over B, with no cut-off at B >= V0")
    xs, ws = np.polynomial.hermite_e.hermegauss(200)
    ws = ws / ws.sum()
    for S, Bb, sg, lam, T in ((30., 15., .30, .3, 1.), (15., 15., .25, .3, 1.), (5., 15., .25, .3, 1.)):
        V0 = S + Bb
        Bx = Bb * np.exp(lam * xs - .5 * lam ** 2)
        d, sd = V0 / Bx, sg * np.sqrt(T)
        full = np.sum(ws * (N(np.log(d) / sd - sd / 2) - d * N(-np.log(d) / sd - sd / 2)))
        cut = des_survival(T, V0, Bb, sg, .05, .05, lam)
        print(f"    S={S}, Bbar={Bb}, T={T}: no cut-off {full:.6f}, Eq.(1) {float(survival(T, S, Bb, sg, lam)):.6f}, "
              f"with cut-off {cut:.6f}")
    print("  American effect on the default part of a GX put, r=5%")
    for T, sg, K in ((GX_T1[0], .498, 5), (GX_T2[0], .465, 5), (GX_T2[0], .465, 10)):
        grid = np.linspace(0, T, 400)
        q = np.where(grid == 0, 1.0, survival(grid, 10.5, 6, sg))
        U = float(np.sum(np.exp(-.05 * .5 * (grid[1:] + grid[:-1])) * (q[:-1] - q[1:])))
        pd = 1 - q[-1]
        put = model_put(10.5, K, T, sg, 6, .05)[0]
        print(f"    T={T:.2f}, K={K}: K DF PD={K * np.exp(-.05 * T) * pd:.3f}, K U={K * U:.3f}, "
              f"extra {K * U - K * np.exp(-.05 * T) * pd:.3f} = {(K * U - K * np.exp(-.05 * T) * pd) / put:.1%} of put. "
              f"P/K={put / K:.4f} vs true U={U:.4f}")


# --------------------------------------------------------------------------------------
# H. CreditGrades, e2c_bond
# --------------------------------------------------------------------------------------

def section_h():
    print("\nH. CREDITGRADES Table C.1 with the deck's Eq. (1), and e2c_bond agreement")
    res = e2c.check_table_c1()
    print(f"    e2c_bond.check_table_c1: {res['cells_matching']} of 156 cells, "
          f"largest gap {res['largest_gap_bp']:.3f}bp, without 360/365 {res['largest_gap_unscaled_bp']:.2f}bp")
    f = e2c.Firm(S=30., D=30., sigma_s=.25 * 45 / 30, L_bar=.5, lam=.3)
    gaps = [abs(float(e2c.survival(T, f)) - float(survival(T, 30, 15, .25, .3))) for T in (.5, 1, 5, 10)]
    print(f"    Deck Eq.(1) vs e2c_bond.survival, largest gap {max(gaps):.2e}")
    cells = {.5: [55, 85, 125, 175, 232, 297, 367, 441, 520, 602, 687, 774, 865],
             1.: [8, 22, 46, 82, 130, 188, 253, 326, 403, 486, 572, 662, 755],
             2.: [1, 3, 12, 30, 59, 101, 153, 214, 283, 358, 438, 523, 612],
             4.: [0, 0, 2, 7, 19, 41, 73, 117, 169, 230, 298, 373, 452],
             6.: [0, 0, 0, 2, 8, 20, 42, 74, 115, 166, 224, 290, 362]}
    vols = [.2 + .05 * i for i in range(13)]

    def cont_par(S, B, sg, remedy):
        grid = np.linspace(0, 5, 961)
        qf = (lambda t: survival_with_remedy(t, S, B, sg, .3)) if remedy else (lambda t: float(survival(t, S, B, sg, .3)))
        q = np.array([qf(t) for t in grid])
        mid = .5 * (grid[1:] + grid[:-1])
        dl = 1 - q[0] + np.sum(np.exp(-.05 * mid) * (q[:-1] - q[1:]))
        ann = np.sum(np.exp(-.05 * mid) * .5 * (q[:-1] + q[1:]) * np.diff(grid))
        return .5 * dl / ann * 1e4
    atom, remedy = [], []
    for sd, row in cells.items():
        S, B = sd * 30, 15.
        for v, c in zip(vols, row):
            sg = v * S / (S + B)
            atom.append(abs(cont_par(S, B, sg, False) * 360 / 365 - c))
            remedy.append(abs(cont_par(S, B, sg, True) * 360 / 365 - c))
    print(f"    Five rows of C.1, x360/365: atom kept {max(atom):.2f}bp, slide 19 remedy {max(remedy):.2f}bp")


# --------------------------------------------------------------------------------------
# I. Delta path
# --------------------------------------------------------------------------------------

def section_i():
    print("\nI. Delta and jump to default as S falls")
    r, B, sig = .05, 15., .375
    cds = lambda s, v: (lambda a, d: 100 * (.056 * a - .9 * d))(*cds_legs(5, s, B, v, r))
    sS = sig * 55 / 40
    print(f"    Slide 21, $ of stock to short at S=40: asset vol held {(cds(40.4, sig) - cds(39.6, sig)) / .8 * 40:.2f}, "
          f"equity vol held {(cds(40.4, sS * 40.4 / 55.4) - cds(39.6, sS * 39.6 / 54.6)) / .8 * 40:.2f}, deck ~27.4")
    print("    CDS seller, $100, 560bp, B=15, sig=37.5%, R=10%, r=5%, lam=0")
    print("       S   par bp  shares   $hedge   JTD(90+PV)  hedge/JTD   gamma")
    for S in (60, 40, 30, 20, 15, 10, 5, 2):
        h = S * .01
        d, pv = (cds(S + h, sig) - cds(S - h, sig)) / (2 * h), cds(S, sig)
        g = (cds(S + h, sig) - 2 * cds(S, sig) + cds(S - h, sig)) / h ** 2
        print(f"    {S:>5} {par_spread(5, S, B, sig, r, .1) * 1e4:7.0f} {d:7.3f} {d * S:8.2f} {90 + pv:10.2f} {d * S / (90 + pv):9.1%} {g:8.3f}")
    print("    GX bond, 8y 9.5%, $100 face, B=6, sig=42%, R=30%, r=5%")
    print("       S   price  shares  $hedge  JTD(P-30)  hedge/JTD")
    P = lambda x: bond_full_price(9.5, 8., x, 6., .42, .05, .30)
    for S in (30, 20, 10.5, 7, 4.2, 1.8):
        h = S * .01
        d = (P(S + h) - P(S - h)) / (2 * h)
        print(f"    {S:>5} {P(S):6.1f} {d:7.3f} {d * S:7.2f} {P(S) - 30:9.1f} {d * S / (P(S) - 30):9.1%}")


# --------------------------------------------------------------------------------------
# J. Hedge allocations, slides 21-25
# --------------------------------------------------------------------------------------

DECK_ALLOC = {"par": 422, "s21": -27.4, "s22p": 32.86, "s22s": 31.85, "s23p": 26.4, "s23s": 20.2,
              "s24p": 17.54, "s24s": -33.27, "s24c": 14.68, "K": 39.2, "s25p": 49.13, "s25s": 46.41}


def allocations(r, p, lam, jtd_extra, S0=40., B0=15., sig0=.375, R=.10, coupon=.056, T=5.):
    """Dollar allocation per slides 21-25, using the deck's option prices 5.22 and 6.31.

    Options are priced at lam = 0. The deck prints no option formula with lam.
    jtd_extra is what the seller loses at default beyond (1-R)*100. 'pv' means the contract value.
    """
    def cds(s, v):
        a, d = cds_legs(T, s, B0, v, r, lam=lam)
        return 100 * (coupon * a - (1 - R) * d)
    bs, bv = .4, 1e-4
    dc = (cds(S0 + bs, sig0) - cds(S0 - bs, sig0)) / (2 * bs)
    vc = (cds(S0, sig0 + bv) - cds(S0, sig0 - bv)) / (2 * bv)
    put = lambda K: (lambda s, v: model_put(s, K, 2, v, B0, r, p)[0])
    call = lambda s, v: model_call(s, 60, 2, v, B0, r, p)
    greek = lambda f: ((f(S0 + bs, sig0) - f(S0 - bs, sig0)) / (2 * bs), (f(S0, sig0 + bv) - f(S0, sig0 - bv)) / (2 * bv))
    dp, vp = greek(put(30))
    dq, vq = greek(call)
    pv = cds(S0, sig0)
    jc = -(90 + (pv if jtd_extra == "pv" else jtd_extra))
    jp = 30 * np.exp(-2 * r) - 5.22
    a, d = cds_legs(T, S0, B0, sig0, r, lam=lam)
    o = {"par": .9 * d / a * 1e4, "s21": -dc * 40}
    n = -vc / vp
    o["s22p"], o["s22s"] = n * 5.22, -(dc + n * dp) * 40
    x = np.linalg.solve([[dp, 1.], [jp, -40.]], [-dc, -jc])
    o["s23p"], o["s23s"] = x[0] * 5.22, x[1] * 40
    x = np.linalg.solve([[dp, 1., dq], [vp, 0, vq], [jp, -40., -6.31]], [-dc, -vc, -jc])
    o["s24p"], o["s24s"], o["s24c"] = x[0] * 5.22, x[1] * 40, x[2] * 6.31

    def strike_gap(K):
        f = put(K)
        dd, vv = greek(f)
        price = f(S0, sig0)
        nk = -vc / vv
        ns = -(dc + nk * dd)
        return nk * (K * np.exp(-2 * r) - price) - ns * 40 + jc, nk, ns, price
    K = brentq(lambda k: strike_gap(k)[0], 25, 60)
    _, nk, ns, price = strike_gap(K)
    o["K"], o["s25p"], o["s25s"] = K, nk * price, ns * 40
    return o, pv


def section_j():
    print("\nJ. SLIDES 21-25: $100 protection sold at 560bp, R=10%, S=40, B=15, sig=37.5%")
    keys = list(DECK_ALLOC)
    print("    " + " " * 34 + " ".join(f"{k:>6}" for k in keys) + "  worst")
    print("    " + f"{'deck (some read off charts)':<34}" + " ".join(f"{DECK_ALLOC[k]:6.2f}" for k in keys))
    fit = least_squares(lambda x: [model_put(40, 30, 2, .375, 15, x[0], x[1])[0] - 5.22,
                                   model_call(40, 60, 2, .375, 15, x[0], x[1]) - 6.31], [.05, 0.])
    print(f"    Rate and yield that fit both option prices exactly, lam=0: r={fit.x[0]:.4f}, p={fit.x[1]:.4f}")
    for r, p, lam, je in ((fit.x[0], fit.x[1], 0., "pv"), (.05, .02, 0., "pv"), (.05, .02, .3, 0.),
                          (.05, .02, .25, 2.), (.05, .025, .25, 1.)):
        o, pv = allocations(r, p, lam, je)
        worst = max(abs(o[k] / DECK_ALLOC[k] - 1) for k in keys)
        print("    " + f"{f'r={r:.3f} p={p:.3f} lam={lam} jtd+={je}':<34}" + " ".join(f"{o[k]:6.2f}" for k in keys) + f"  {worst:.1%}")
    r, p = .05, .02
    put = lambda s_, v: model_put(s_, 30, 2, v, 15, r, p)[0]
    call = lambda s_, v: model_call(s_, 60, 2, v, 15, r, p)
    grk = lambda f: ((f(40.4, .375) - f(39.6, .375)) / .8, (f(40, .3751) - f(40, .3749)) / .0002)
    dp, vp = grk(put)
    dq, vq = grk(call)
    print(f"    Condition number of the deck's slide 24 matrix: "
          f"{np.linalg.cond([[dp, 1., dq], [vp, 0., vq], [30 * np.exp(-2 * r) - 5.22, -40., -6.31]]):.0f}")
    print("    Put and call at r=5%, p=2%, lam=0: "
          f"{model_put(40, 30, 2, .375, 15, .05, .02)[0]:.3f} (deck 5.22), {model_call(40, 60, 2, .375, 15, .05, .02):.3f} (deck 6.31)")


# --------------------------------------------------------------------------------------
# K. Worked example on the deck's own numbers: GX on 14 June 2001
# --------------------------------------------------------------------------------------

def section_k():
    print("\nK. Worked example: GX on 6/14/01. S=10.5, B=6, R=30%, r=5%, p=0, lam=0. Bond price 84 read as clean.")
    r, S, B, R = .05, 10.5, 6., .30
    T = years(D0, date(2009, 11, 15))
    bond, curve = e2c.Bond(.095, T, 2), e2c.flat_curve(r)
    sig = gx_sigma_cum()
    full = 84 + accrued_30_360(9.5, D0)

    def price(qf, rec=R):
        t, cf = e2c.cash_flows(bond)
        pv = np.sum(cf * np.exp(-r * t) * np.array([qf(x) for x in t]))
        g = np.linspace(0, T, int(T * 96) + 1)
        q = np.array([qf(x) for x in g])
        return pv + rec * np.sum(np.exp(-r * .5 * (g[1:] + g[:-1])) * (q[:-1] - q[1:]))

    q_opt = lambda t: 1.0 if t <= 0 else float(survival(t, S, B, sig(t)))
    q_stk = lambda t: 1.0 if t <= 0 else float(survival(t, S, B, .42))
    p_opt, p_stk = price(q_opt), price(q_stk)
    z_mkt, z_opt, z_stk = e2c.z_spread(full / 100, bond, curve), e2c.z_spread(p_opt, bond, curve), e2c.z_spread(p_stk, bond, curve)
    print(f"    Full price: market {full:.2f}, options curve {p_opt * 100:.2f}, stock with fixed 42% {p_stk * 100:.2f}")
    print(f"    Z-spread bp: market {z_mkt * 1e4:.0f}, options curve {z_opt * 1e4:.0f}, stock with fixed 42% {z_stk * 1e4:.0f}")
    g_bp, g_ps = np.log(z_mkt / z_opt), np.log(z_opt / z_stk)
    print(f"    G_bp={g_bp:.3f}, G_ps={g_ps:.3f}, G_bs={np.log(z_mkt / z_stk):.3f}, sum check {g_bp + g_ps:.3f}. "
          f"Yu's lowest trigger ln(1.5)={np.log(1.5):.3f}")
    kappa = brentq(lambda k: price(lambda t: q_opt(t) ** k) - full / 100, .2, 5)
    rstar = brentq(lambda x: price(q_opt, x) - full / 100, -1, 1)
    c = brentq(lambda c: price(lambda t: 1.0 if t <= 0 else float(survival(t, S, B, c * sig(t)))) - full / 100, .3, 3)
    h = brentq(lambda x: flat_hazard_price(x, 9.5, T, .3, r) - full, 1e-5, 5)
    T2 = GX_T2[0]
    print(f"    kappa={kappa:.3f}, R*={rstar:.3f}, c={c:.3f}, flat h={h:.4f}")
    print(f"    PD({T2:.2f}y): options {1 - q_opt(T2):.3f}, bond by kappa {1 - q_opt(T2) ** kappa:.3f}, bond by flat h {1 - np.exp(-h * T2):.3f}")
    print(f"    Asset vol to {T2:.2f}y: options {sig(T2):.3f}, bond-implied {c * sig(T2):.3f}")

    def bond_value(s, scale=1.):
        return 100 * price(lambda t: 1.0 if t <= 0 else float(survival(t, s, B, scale * sig(t))))
    bs, bv = .105, 1e-3
    d_b = (bond_value(S + bs) - bond_value(S - bs)) / (2 * bs)
    v_b = (bond_value(S, 1 + bv) - bond_value(S, 1 - bv)) / (2 * bv)
    j_b = bond_value(S) - 30
    print(f"    Long $100 face: value {bond_value(S):.2f}, delta {d_b:.3f} shares (${d_b * S:.2f}), "
          f"vega {v_b:.2f} per 1.00 scale of vol, jump to default -{j_b:.2f}")

    def put(K, s, scale=1.):
        return model_put(s, K, T2, scale * .465, B, r)[0]
    print(f"    Hedges with {T2:.2f}y puts. n_put and n_stock, $ in brackets.")
    for K in (5, 7.5, 10):
        p = put(K, S)
        d = (put(K, S + bs) - put(K, S - bs)) / (2 * bs)
        v = (put(K, S, 1 + bv) - put(K, S, 1 - bv)) / (2 * bv)
        j = K * np.exp(-r * T2) - p
        x = np.linalg.solve([[d, 1.], [j, -S]], [-d_b, j_b])
        n = -v_b / v
        ns = -(d_b + n * d)
        th = (model_put(S, K, T2 - 1 / 252, .465, B, r)[0] - p) * 252
        print(f"      K={K:<4} put {p:.3f}, delta {d:.3f}, vega {v:.2f}, jump {j:.3f}, theta/yr {th:.3f}. "
              f"Delta+JTD: {x[0]:.2f} (${x[0] * p:.1f}), {x[1]:.3f} (${x[1] * S:.1f}). "
              f"Delta+vega: {n:.2f} (${n * p:.1f}), {ns:.3f} (${ns * S:.1f}).")
    print(f"    Bond carry before hedge: coupon 9.50 less financing {r * full:.2f} = {9.5 - r * full:.2f} per year")
    K, Kc = 7.5, 15.
    p = put(K, S)
    d = (put(K, S + bs) - put(K, S - bs)) / (2 * bs)
    v = (put(K, S, 1 + bv) - put(K, S, 1 - bv)) / (2 * bv)
    j = K * np.exp(-r * T2) - p
    call = lambda s, scale=1.: put(Kc, s, scale) + s - Kc * np.exp(-r * T2)
    c0 = call(S)
    dc = (call(S + bs) - call(S - bs)) / (2 * bs)
    vc = (call(S, 1 + bv) - call(S, 1 - bv)) / (2 * bv)
    A = np.array([[d, 1., dc], [v, 0., vc], [j, -S, -c0]])
    x = np.linalg.solve(A, [-d_b, -v_b, j_b])
    print(f"    Three legs, put K=7.5, stock, call K=15: {x[0]:.2f} puts (${x[0] * p:.1f}), {x[1]:.2f} shares (${x[1] * S:.1f}), "
          f"{x[2]:.2f} calls (${x[2] * c0:.1f}). Condition number {np.linalg.cond(A):.0f}. A short put here means the solve fails its sign check.")
    up = put(5, S) / 5
    lam = brentq(lambda l: l * (1 - np.exp(-(r + l) * T2)) / (r + l) - up, 1e-5, 5)
    print(f"    Carr-Wu on the K=5 put: U_p={up:.4f}, hazard {lam:.4f}, PD {1 - np.exp(-lam * T2):.3f}. "
          f"Model PD {1 - q_opt(T2):.3f}. The gap is the diffusion part of the put.")


# --------------------------------------------------------------------------------------
# L. Later literature against the deck's numbers
# --------------------------------------------------------------------------------------

_GL_X, _GL_W = np.polynomial.legendre.leggauss(200)


def des_survival(t, V0, ld, sig, r, delta, lam):
    """Chen, Chen and Li (2026), Eqs. (6)-(9): barrier integrated exactly, up to the cut-off Z."""
    z_max = lam / 2 - np.log(ld / V0) / lam
    if t <= 0:
        return float(N(z_max))
    z_min = min(-10., z_max - 1.)
    z = .5 * (z_max - z_min) * (_GL_X + 1) + z_min
    pdf = np.exp(-.5 * z ** 2) / np.sqrt(2 * np.pi)
    c = (r - delta) / sig ** 2 - .5
    y = -np.log(V0 / ld) - lam ** 2 / 2 + lam * z
    sd = sig * np.sqrt(t)
    q = N(c * sd - y / sd) - np.exp(2 * c * y) * N(c * sd + y / sd)
    return float(.5 * (z_max - z_min) * np.sum(_GL_W * pdf * q))


def asset_vol_fs(sigma_s, S, D):
    """Feldhuetter and Schaefer (2018) rule as Chen, Chen and Li (2026, p.2015) state it."""
    r0 = D / (S + D)
    factor = 1.0 if r0 < .25 else 1.05 if r0 <= .35 else 1.10 if r0 <= .45 else 1.20 if r0 <= .55 else 1.40 if r0 <= .75 else 1.80
    return sigma_s * (1 - r0) * factor


def section_l():
    print("\nL. Later literature against the deck's numbers")
    print("  Chen, Chen and Li (2026) survival at zero drift against my cut-off average in section G")
    for S, Bb, sg, lam in ((30., 15., .30, .3), (15., 15., .25, .3), (5., 15., .25, .3)):
        print(f"    S={S}, Bbar={Bb}: {des_survival(1., S + Bb, Bb, sg, .05, .05, lam):.6f}, "
              f"Eq.(1) {float(survival(1., S, Bb, sg, lam)):.6f}")
    print("  Asset vol as a share of equity vol: Feldhuetter-Schaefer rule against CreditGrades with Lbar=.5")
    for sd in (4., 1., .5, .25):
        print(f"    S/D={sd}: rule {asset_vol_fs(1., sd, 1.):.3f}, CreditGrades {sd / (sd + .5):.3f}")

    print("  DES-form gap on GX, 6/14/01. D=14.2, Lbar=.5, lam=.3, recovery .35, r=5%. ATM 82.2% stands in for 3-year vol.")
    r, S, D = .05, 10.5, 14.2
    T = years(D0, date(2009, 11, 15))
    bond, curve = e2c.Bond(.095, T, 2), e2c.flat_curve(r)
    full = 84 + accrued_30_360(9.5, D0)
    z_mkt = e2c.z_spread(full / 100, bond, curve)
    sig = asset_vol_fs(.822, S, D)
    print(f"    Asset vol {sig:.3f}. Market Z {z_mkt * 1e4:.0f} bp.")
    for delta in (.05, .03, .10):
        t, cf = e2c.cash_flows(bond)
        pv = np.sum(cf * np.exp(-r * t) * np.array([des_survival(x, S + 7.1, 7.1, sig, r, delta, .3) for x in t]))
        g = np.linspace(0, T, int(T * 48) + 1)
        q = np.array([des_survival(x, S + 7.1, 7.1, sig, r, delta, .3) for x in g])
        price = pv + .35 * np.sum(np.exp(-r * .5 * (g[1:] + g[:-1])) * (q[:-1] - q[1:]))
        z = e2c.z_spread(price, bond, curve)
        print(f"    payout {delta:.2f}, drift {r - delta:+.2f}: model price {price * 100:.1f}, model Z {z * 1e4:.0f} bp, "
              f"DES-form gap {(z_mkt - z) * 1e4:+.0f} bp, model/market price {price * 100 / full:.3f}")
    print("    Paper's quintile means: gap -139, +45, +103, +156, +271 bp. Price ratio 0.94 to 1.16.")

    print("  Avino-Salvador style hedge: puts only, matched on delta, against default-loss and slide 23")
    r, p = .05, .02
    def cds(s, v):
        a, d = cds_legs(5, s, 15., v, r, lam=.3)
        return 100 * (.056 * a - .9 * d)
    put = lambda s_, v: model_put(s_, 30, 2, v, 15., r, p)[0]
    d_c = (cds(40.4, .375) - cds(39.6, .375)) / .8
    v_c = (cds(40, .3751) - cds(40, .3749)) / .0002
    d_p = (put(40.4, .375) - put(39.6, .375)) / .8
    v_p = (put(40, .3751) - put(40, .3749)) / .0002
    jump_p = 30 * np.exp(-2 * r) - 5.22
    n_mtm = d_c / -d_p
    n_dl = 90 / jump_p
    print(f"    Slide 21 example, 2y K=30 put at 5.22. Marked to market: {n_mtm:.2f} puts (${n_mtm * 5.22:.1f}), "
          f"covers {n_mtm * jump_p / 90:.0%} of the 90 jump, net vega {v_c + n_mtm * v_p:.1f}.")
    print(f"    Default loss, puts only: {n_dl:.2f} puts (${n_dl * 5.22:.1f}), net delta {d_c + n_dl * d_p:.3f}, net vega {v_c + n_dl * v_p:.1f}.")
    print(f"    Slide 23, deck's chart: ~$26.4 of puts plus ~$20.2 of stock.")
    sig_gx = gx_sigma_cum()
    T2 = GX_T2[0]

    def bond_value(s, scale=1.):
        q_f = lambda x: 1.0 if x <= 0 else float(survival(x, s, 6., scale * sig_gx(x)))
        t, cf = e2c.cash_flows(bond)
        g = np.linspace(0, T, int(T * 96) + 1)
        q = np.array([q_f(x) for x in g])
        return 100 * (np.sum(cf * np.exp(-.05 * t) * np.array([q_f(x) for x in t]))
                      + .30 * np.sum(np.exp(-.05 * .5 * (g[1:] + g[:-1])) * (q[:-1] - q[1:])))
    d_b = (bond_value(10.605) - bond_value(10.395)) / .21
    v_b = (bond_value(10.5, 1.001) - bond_value(10.5, .999)) / .002
    j_b = bond_value(10.5) - 30
    for K in (5, 7.5, 10):
        f = lambda s_, sc=1.: model_put(s_, K, T2, sc * .465, 6., .05)[0]
        pr = f(10.5)
        d_k = (f(10.605) - f(10.395)) / .21
        v_k = (f(10.5, 1.001) - f(10.5, .999)) / .002
        jk = K * np.exp(-.05 * T2) - pr
        n = d_b / -d_k
        print(f"    GX bond $100 face, {T2:.2f}y K={K}: marked to market {n:.2f} puts (${n * pr:.1f}), "
              f"covers {n * jk / j_b:.0%} of the {j_b:.1f} jump, net vega {v_b + n * v_k:.1f}.")


if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    section_h()
    section_i()
    section_j()
    section_k()
    section_l()
