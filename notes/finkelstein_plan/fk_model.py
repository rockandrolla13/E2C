"""Finkelstein (2002) model: survival curve, puts and calls. Work package WP1.

Steps 12, 13, 13a and 16 of finkelstein_replication_plan.pdf, with Black-Scholes helpers.
No market data. Units: decimals for rates, vols and probabilities, years for time, per share for prices.

Inputs                                     Outputs
  S0     share price                         fk_survival   Q(T), step 12
  B      barrier per share (L_bar * D)       fk_curve      Q(T) with the short-end remedy, step 13
  sig    cumulative asset vol to T           fk_curve_grid grid, Q and hazard, step 13
  lam    barrier uncertainty                 des_survival  q(t), extended model, step 13a
  r, p   rate and payout                     fk_put        price, default part, diffusion part, step 16
  K, T   strike and maturity                 fk_call       call by parity
                                             fk_implied_vol  the model's Black-Scholes vol, step 16

Tags as in the plan: [DECK s.N] is Finkelstein's slide N. [ADAPTATION] is not Finkelstein's.
The deck prints no put formula, and fk_put is derived from the reflection principle.
"""
from typing import Callable, NamedTuple, Union

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr as N

Vol = Union[float, Callable[[float], float]]
REMEDY_T = 0.5    # [DECK s.19] Eq. (1) is used from this tenor
GRID_STEP = 1 / 48


class ModelPut(NamedTuple):
    """Put price, and its split. price = default + diffusion."""
    price: float
    default: float
    diffusion: float


# ---------------------------------------------------------------- Black-Scholes helpers

def bs_put(S: float, K: float, T: float, vol: float, r: float, q: float = 0.0) -> float:
    sd = vol * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q) * T + 0.5 * sd ** 2) / sd
    return float(K * np.exp(-r * T) * N(-(d1 - sd)) - S * np.exp(-q * T) * N(-d1))


def bs_implied_vol(price: float, S: float, K: float, T: float, r: float, q: float = 0.0) -> float:
    """Black-Scholes vol of a put price. Raises ValueError if no vol from 0.01% to 1000% gives the price."""
    return float(brentq(lambda v: bs_put(S, K, T, v, r, q) - price, 1e-4, 10.0, xtol=1e-12))


# ---------------------------------------------------------------- Vol conversions

def equity_vol_from_asset(sig: float, S: float, B: float) -> float:
    """[DECK s.6] Equity vol of the shifted lognormal: sig * (S + B) / S."""
    return sig * (S + B) / S


def forward_vol(T1: float, sig1: float, T2: float, sig2: float) -> float:
    """Forward asset vol between two cumulative vols. Needs a rising total variance. [DECK s.11]"""
    return float(np.sqrt((sig2 ** 2 * T2 - sig1 ** 2 * T1) / (T2 - T1)))


def asset_vol_fs(sigma_s: float, S: float, D: float) -> float:
    """Step 11 variant [ADAPTATION]. Feldhuetter and Schaefer (2018) rule, as Chen, Chen and Li (2026, p.2015) state it."""
    leverage = D / (S + D)
    for limit, factor in ((.25, 1.0), (.35, 1.05), (.45, 1.10), (.55, 1.20), (.75, 1.40)):
        if leverage < limit or (limit > .25 and leverage <= limit):
            return sigma_s * (1 - leverage) * factor
    return sigma_s * (1 - leverage) * 1.80


# ---------------------------------------------------------------- Step 12 and 13: survival

def fk_survival(T, S0: float, B: float, sig, lam: float = 0.0):
    """Step 12. [DECK s.11] at lam = 0, [DECK s.18] Eq. (1) at lam > 0. Q(0) = 1 only at lam = 0."""
    T = np.asarray(T, dtype=float)
    d = (S0 + B) / B * np.exp(lam ** 2)
    A = np.sqrt(np.asarray(sig, dtype=float) ** 2 * T + lam ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(d) / A
        out = N(ratio - A / 2) - d * N(-ratio - A / 2)
    return np.where(A > 0, out, 1.0)


def fk_curve(T, S0: float, B: float, sig: Vol, lam: float = 0.0):
    """Step 13. [DECK s.19] Below T = 0.5 with lam > 0, flat intensity from 1 to Q(0.5).

    sig is a constant or a function of T giving sigma_cum(T). Below 0.5 the remedy uses sigma_cum(0.5).
    """
    sig_at = sig if callable(sig) else (lambda _: sig)
    T = np.asarray(T, dtype=float)
    out = np.array([float(fk_survival(t, S0, B, sig_at(t), lam)) if (t >= REMEDY_T or lam == 0)
                    else float(fk_survival(REMEDY_T, S0, B, sig_at(REMEDY_T), lam)) ** (t / REMEDY_T)
                    for t in T.ravel()], dtype=float)
    return out.reshape(T.shape)


def fk_curve_grid(T_max: float, S0: float, B: float, sig: Vol, lam: float = 0.0, step: float = GRID_STEP):
    """Step 13 outputs: grid to T_max, Q on it, and the hazard on each interval (one fewer value)."""
    n = int(np.ceil(T_max / step - 1e-9))
    grid = np.linspace(0.0, n * step, n + 1)
    q = fk_curve(grid, S0, B, sig, lam)
    hazard = np.log(q[:-1] / q[1:]) / np.diff(grid)
    return grid, q, hazard


_GL_X, _GL_W = np.polynomial.legendre.leggauss(200)


def des_survival(t: float, V0: float, barrier: float, sig: float, r: float, delta: float, lam: float) -> float:
    """Step 13a [ADAPTATION]. Chen, Chen and Li (2026), Eqs. (1)-(9): extended CreditGrades.

    V drifts at r - delta, and barriers above V0 are cut off, so it differs from Eq. (1).
    Use it only to replicate their published gap. Keep fk_survival for all option work.
    Here V0 = S0 + L_bar * D, and barrier = L_bar * D.
    """
    z_max = lam / 2 - np.log(barrier / V0) / lam
    if t <= 0:
        return float(N(z_max))
    z_min = min(-10.0, z_max - 1.0)
    z = 0.5 * (z_max - z_min) * (_GL_X + 1) + z_min
    pdf = np.exp(-0.5 * z ** 2) / np.sqrt(2 * np.pi)
    c = (r - delta) / sig ** 2 - 0.5
    y = -np.log(V0 / barrier) - lam ** 2 / 2 + lam * z
    sd = sig * np.sqrt(t)
    q = N(c * sd - y / sd) - np.exp(2 * c * y) * N(c * sd + y / sd)
    return float(0.5 * (z_max - z_min) * np.sum(_GL_W * pdf * q))


# ---------------------------------------------------------------- Step 16: options

def _put_above_barrier(x: float, H: float, B: float, sd: float) -> float:
    """E[(H - V_T)^+ ; V_T > B] for a driftless lognormal V_T starting from x. This is G(x) in the plan."""
    def d1(k: float) -> float:
        return (np.log(x / k) + 0.5 * sd ** 2) / sd
    return float(H * (N(-(d1(H) - sd)) - N(-(d1(B) - sd))) - x * (N(-d1(H)) - N(-d1(B))))


def fk_put(S0: float, K: float, T: float, sig: float, B: float, r: float, p: float = 0.0) -> ModelPut:
    """Step 16 at lam = 0. [DECK s.1, 6] for the idea. Closed form derived, since the deck prints none.

    The stock is (V_T - B) exp((r-p)T) if V never touches B, and otherwise 0.
    Default pays K at expiry here, so this is a European put. WP8 handles American exercise.
    """
    V0, H, sd = S0 + B, B + K * np.exp(-(r - p) * T), sig * np.sqrt(T)
    knock_out = _put_above_barrier(V0, H, B, sd) - (V0 / B) * _put_above_barrier(B ** 2 / V0, H, B, sd)
    diffusion = float(np.exp(-p * T) * knock_out)
    default = float(K * np.exp(-r * T) * (1.0 - float(fk_survival(T, S0, B, sig))))
    return ModelPut(default + diffusion, default, diffusion)


def fk_call(S0: float, K: float, T: float, sig: float, B: float, r: float, p: float = 0.0) -> float:
    """Call by parity. Parity holds because (V - B) stopped at B is a martingale."""
    return fk_put(S0, K, T, sig, B, r, p).price + S0 * np.exp(-p * T) - K * np.exp(-r * T)


def fk_implied_vol(S0: float, K: float, T: float, sig: float, B: float, r: float, p: float = 0.0) -> float:
    """Step 16. The Black-Scholes vol sigma^M(K, T) of the model put."""
    return bs_implied_vol(fk_put(S0, K, T, sig, B, r, p).price, S0, K, T, r, p)
