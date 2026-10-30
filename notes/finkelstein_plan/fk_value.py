"""Finkelstein (2002) model values: CDS, bonds, and bond-against-model measures. Work package WP2.

Steps 14, 15, 18-21, 23 and 24 of finkelstein_replication_plan.pdf. No market data.
Prices are per 1 of face, as in e2c_bond. The plan's tables are per 100.

Inputs                                        Outputs
  bond    e2c.Bond: coupon, maturity, freq      fk_cds            annuity, default leg, par, step 14
  curve   e2c.ZeroCurve                         fk_bond_price     model full price, step 15
  q       survival function, from               fk_bond_z         model Z-spread, step 15
          survival_function or your own         bond_implied_curve  flat hazard and par, step 18
  full    market full price                     hazard_multiplier kappa, step 19
  R_b     recovery of face                      implied_recovery  R*, step 20
  S, B, sig, lam  as in fk_model                bond_implied_vol  vol scale c and status, step 21
                                                stock_only_curve  price and Z on fixed inputs, step 23
                                                three_gaps        G_bp, G_ps, G_bs, step 24

Tags as in the plan. The deck prints no CDS or bond formula, so these forms are [ADAPTATION] of slides 12 and 14.
"""
import sys
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

import numpy as np
from scipy.optimize import brentq

import fk_model as fk

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
import e2c_bond as e2c  # noqa: E402  pinned copy, so this branch stands alone

Survival = Callable[[np.ndarray], np.ndarray]
STEPS_PER_YEAR = 48       # plan, step 13
RECOVERY_BOUNDS = (0.0, 0.8)   # plan, step 20. My judgement
RECOVERY_BUFFER = 0.10    # as e2c_bond.implied_vol_bond


class CdsValue(NamedTuple):
    annuity: float
    default_leg: float
    par: float


class HazardFit(NamedTuple):
    hazard: float
    par: float


class RecoveryFit(NamedTuple):
    recovery: float
    in_bounds: bool


class VolScale(NamedTuple):
    """status is one of ok, below_floor, above_ceiling, multiple, near_recovery, as in e2c_bond.VolInversion."""
    status: str
    scale: float
    roots: tuple


class StockOnly(NamedTuple):
    price: float
    z: float


class Gaps(NamedTuple):
    """Log gaps. Positive means the first market is wider. bond_stock = bond_option + option_stock."""
    bond_option: float
    option_stock: float
    bond_stock: float


# ---------------------------------------------------------------- Building a survival function

def flat_forward_sigma(points: Sequence[tuple]) -> Callable[[float], float]:
    """sigma_cum(T) from (T, cumulative vol) pairs in rising T.

    Flat before the first point. Linear in total variance between points, and flat forward after the last.
    The flat forward past the last option date is an assumption, not data.
    """
    times = np.array([p[0] for p in points], dtype=float)
    variance = np.array([p[1] ** 2 * p[0] for p in points], dtype=float)
    last_forward = (variance[-1] - variance[-2]) / (times[-1] - times[-2]) if len(points) > 1 else points[0][1] ** 2

    def sigma(t: float) -> float:
        if t <= times[0]:
            return float(points[0][1])
        if t >= times[-1]:
            return float(np.sqrt((variance[-1] + last_forward * (t - times[-1])) / t))
        return float(np.sqrt(np.interp(t, times, variance) / t))

    return sigma


def survival_function(S0: float, B: float, sig: fk.Vol, lam: float = 0.0, remedy: bool = True) -> Survival:
    """Q as a function of T. remedy=False keeps Eq. (1)'s mass at T = 0, which e2c_bond and Yu's Eq. (12) have."""
    sig_at = sig if callable(sig) else (lambda _: sig)

    def q(t):
        t = np.atleast_1d(np.asarray(t, dtype=float))
        if remedy:
            return fk.fk_curve(t, S0, B, sig, lam)
        return np.array([float(fk.fk_survival(x, S0, B, sig_at(x), lam)) for x in t])

    return q


def _grid(T: float, steps_per_year: int) -> np.ndarray:
    return np.linspace(0.0, T, max(steps_per_year, int(T * steps_per_year)) + 1)


def _default_leg(T: float, q: Survival, curve: e2c.ZeroCurve, steps_per_year: int) -> float:
    """PV of 1 paid at default before T, plus any mass at T = 0, paid today."""
    grid = _grid(T, steps_per_year)
    values = q(grid)
    middle = 0.5 * (grid[1:] + grid[:-1])
    return float(1 - values[0] + np.sum(curve.df(middle) * (values[:-1] - values[1:])))


# ---------------------------------------------------------------- Steps 14 and 15

def fk_cds(T: float, q: Survival, curve: e2c.ZeroCurve, R: float, freq: int | None = 4, accrual: bool = True,
           act360: bool = False, steps_per_year: int = 96) -> CdsValue:
    """Step 14. [DECK s.12] [LARDY] [CREDITGRADES]. Default paid when it happens.

    freq premiums a year in arrears, with half a period of accrual on default. freq=None pays continuously.
    act360 applies CreditGrades' x360/365 to the par spread.
    """
    leg = _default_leg(T, q, curve, steps_per_year)
    if freq is None:
        grid = _grid(T, steps_per_year)
        values = q(grid)
        middle = 0.5 * (grid[1:] + grid[:-1])
        annuity = float(np.sum(curve.df(middle) * 0.5 * (values[:-1] + values[1:]) * np.diff(grid)))
    else:
        pay = T - np.arange(int(np.ceil(T * freq - 1e-9)))[::-1] / freq
        annuity = float(np.sum(curve.df(pay) * q(pay)) / freq) + (0.5 / freq * leg if accrual else 0.0)
    par = (1 - R) * leg / annuity
    return CdsValue(annuity, leg, par * 360 / 365 if act360 else par)


def _coupon_leg(bond: e2c.Bond, q: Survival, curve: e2c.ZeroCurve) -> float:
    t, cf = e2c.cash_flows(bond)
    return float(np.sum(cf * curve.df(t) * q(t)))


def fk_bond_price(bond: e2c.Bond, q: Survival, curve: e2c.ZeroCurve, R_b: float, steps_per_year: int = STEPS_PER_YEAR) -> float:
    """Step 15. Full price: sum CF DF Q + R_b L(T). Recovery is of face, so a premium bond loses more."""
    return _coupon_leg(bond, q, curve) + R_b * _default_leg(bond.maturity, q, curve, steps_per_year)


def fk_bond_z(bond: e2c.Bond, q: Survival, curve: e2c.ZeroCurve, R_b: float, steps_per_year: int = STEPS_PER_YEAR) -> float:
    """Step 15. Model Z-spread, on the market Z-spread's convention."""
    return e2c.z_spread(fk_bond_price(bond, q, curve, R_b, steps_per_year), bond, curve)


# ---------------------------------------------------------------- Steps 18 to 21: one bond against the model

def bond_implied_curve(full: float, bond: e2c.Bond, curve: e2c.ZeroCurve, R_b: float) -> HazardFit:
    """Step 18. [DECK s.14] gives the idea, and a flat hazard is the simplest reading. par = (1 - R_b) h."""
    def gap(h: float) -> float:
        return fk_bond_price(bond, lambda t: np.exp(-h * np.asarray(t, dtype=float)), curve, R_b) - full
    h = float(brentq(gap, 1e-7, 10.0, xtol=1e-10))
    return HazardFit(h, (1 - R_b) * h)


def hazard_multiplier(full: float, bond: e2c.Bond, q: Survival, curve: e2c.ZeroCurve, R_b: float) -> float:
    """Step 19. kappa such that Q^kappa prices the bond. Above 1, the bond is wider than the curve implies."""
    def gap(k: float) -> float:
        return fk_bond_price(bond, lambda t: q(t) ** k, curve, R_b) - full
    return float(brentq(gap, 0.01, 50.0, xtol=1e-10))


def bond_default_probability(q: Survival, kappa: float, T: float) -> float:
    """Step 19. Carries the bond's level to the option's maturity: 1 - Q(T)^kappa."""
    return float(1 - q(np.array([T]))[0] ** kappa)


def implied_recovery(full: float, bond: e2c.Bond, q: Survival, curve: e2c.ZeroCurve,
                     steps_per_year: int = STEPS_PER_YEAR) -> RecoveryFit:
    """Step 20. R* such that step 15 equals the full price. The price is linear in recovery, so no search."""
    rec = (full - _coupon_leg(bond, q, curve)) / _default_leg(bond.maturity, q, curve, steps_per_year)
    return RecoveryFit(float(rec), bool(RECOVERY_BOUNDS[0] <= rec <= RECOVERY_BOUNDS[1]))


def bond_implied_vol(full: float, bond: e2c.Bond, S0: float, B: float, sig: fk.Vol, curve: e2c.ZeroCurve, R_b: float,
                     lam: float = 0.0, grid: np.ndarray = np.geomspace(0.02, 8.0, 80)) -> VolScale:
    """Step 21. c such that c * sigma_cum(.) prices the bond. A bond can have two roots near recovery, so scan."""
    if full < R_b + RECOVERY_BUFFER:
        return VolScale("near_recovery", float("nan"), ())
    sig_at = sig if callable(sig) else (lambda _: sig)

    def gap(c: float) -> float:
        return fk_bond_price(bond, survival_function(S0, B, lambda t: c * sig_at(t), lam), curve, R_b) - full

    gaps = [gap(c) for c in grid]
    roots = tuple(float(brentq(gap, grid[i], grid[i + 1], xtol=1e-8))
                  for i in range(len(grid) - 1) if gaps[i] * gaps[i + 1] < 0)
    if not roots:
        return VolScale("below_floor" if gaps[0] < 0 else "above_ceiling", float("nan"), ())
    if len(roots) > 1:
        return VolScale("multiple", float("nan"), roots)
    return VolScale("ok", roots[0], roots)


# ---------------------------------------------------------------- Steps 23 and 24

def stock_only_curve(S_t: float, B0: float, sig0: float, bond: e2c.Bond, curve: e2c.ZeroCurve, R_b: float,
                     lam: float = 0.0) -> StockOnly:
    """Step 23. [DECK s.12-15] Today's stock with barrier and flat vol fixed on a start date. Refit is the caller's."""
    price = fk_bond_price(bond, survival_function(S_t, B0, sig0, lam), curve, R_b)
    return StockOnly(price, e2c.z_spread(price, bond, curve))


def three_gaps(z_market: float, z_option: float, z_stock: float) -> Gaps:
    """Step 24 [ADAPTATION]. Two are independent. NaN if a spread is at or below zero."""
    return Gaps(e2c.log_gap(z_market, z_option), e2c.log_gap(z_option, z_stock), e2c.log_gap(z_market, z_stock))
