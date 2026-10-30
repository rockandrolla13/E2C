"""Finkelstein (2002) hedges: greeks, solves, optimal strike and rebalancing. Work package WP3.

Steps 26-29 of finkelstein_replication_plan.pdf. No market data.
Bonds and CDS are per 1 of face unless you pass face, as in fk_value. The plan's tables use face=100.
Stock and options are per share.

Inputs                                        Outputs
  S, B, sig, lam  as in fk_model                fk_greeks         value, delta, gamma, vega, jump, step 26
  K, T, r, p      as in fk_model                cds_seller_greeks, bond_greeks, put_greeks, call_greeks, stock_greeks
  curve, bond     as in fk_value                put_only_ratio    -delta_P / delta_p, step 26
  price           a market option price, used   put_only_hedge    puts, dollars, share of jump covered
                  for value and jump only       solve_hedge       n_put, n_stock, n_call, status, step 27
  held, target    share counts                  net_greeks        target plus hedge
  days_since      calendar days since the last  optimal_strike    K*, n_put, n_stock, step 28
                                                rehedge_due       flag, step 29

Conventions. Delta and gamma bump S by 1% with sigma_cum, B and lam held, so V0 moves one for one with S.
Vega scales sigma_cum by 1 +/- 0.1%, so it is per 1.00 scale of vol, not per vol point.
Jump is the change in value if default happens now, and the stock goes to 0.
Tags as in the plan. Slide 20 names the sensitivities and does not define them, so these are my definitions.
"""
from typing import Callable, NamedTuple, Optional, Sequence

import numpy as np
from scipy.optimize import brentq

import fk_model as fk
import fk_value as v
from fk_value import e2c

S_BUMP = .01             # plan, step 26
VOL_BUMP = .001          # plan, step 26
STOCK_CAP = 1.5          # plan, step 27 [ADAPTATION]. My judgement
REHEDGE_BAND = .10       # plan, step 29 [ADAPTATION]. My judgement
REHEDGE_DAYS = 7         # plan, step 29 [OWN] weekly, read as calendar days
STRIKE_RANGE = (.625, 1.5)     # scan for K*, as multiples of S. The check script's 25 to 60 at S = 40
STRIKE_POINTS = 36
ROWS = ("delta", "vega", "jump")


class Greeks(NamedTuple):
    """Per unit held long. A CDS seller is the long side here. Vega is per 1.00 scale of vol."""
    value: float
    delta: float
    gamma: float
    vega: float
    jump: float


class PutOnly(NamedTuple):
    n_put: float
    dollars: float
    jump_cover: float


class Hedge(NamedTuple):
    """dollars is (put, stock, call). status is one of ok, short_option, stock_too_large, singular.

    A rejected solve keeps its counts, so the caller can report them.
    """
    n_put: float
    n_stock: float
    n_call: float
    dollars: tuple
    status: str
    condition: float


class StrikeFit(NamedTuple):
    """status is one of ok, no_root, multiple. On no_root and multiple the other fields are NaN."""
    status: str
    strike: float
    n_put: float
    n_stock: float


# ---------------------------------------------------------------- Step 26: greeks

def fk_greeks(value: Callable[[float, float], float], S: float, jump: Callable[[float], float],
              s_bump: float = S_BUMP, vol_bump: float = VOL_BUMP) -> Greeks:
    """Step 26. [DECK s.20] [ADAPTATION] value(s, c) prices at stock s with sigma_cum scaled by c. jump(value) is J."""
    h = S * s_bump
    mid, up, down = value(S, 1.0), value(S + h, 1.0), value(S - h, 1.0)
    vega = (value(S, 1 + vol_bump) - value(S, 1 - vol_bump)) / (2 * vol_bump)
    return Greeks(mid, (up - down) / (2 * h), (up - 2 * mid + down) / h ** 2, vega, jump(mid))


def _scaled(sig: fk.Vol, c: float) -> Callable[[float], float]:
    return (lambda t: c * sig(t)) if callable(sig) else (lambda _: c * sig)


def cds_seller_greeks(T: float, S: float, B: float, sig: fk.Vol, curve: e2c.ZeroCurve, R: float, coupon: float,
                      lam: float = 0.0, face: float = 1.0, include_value: bool = False,
                      s_bump: float = S_BUMP, vol_bump: float = VOL_BUMP) -> Greeks:
    """Step 26. Protection sold at coupon. Jump is -(1 - R) of face.

    include_value adds the contract value to the jump, as in the plan's Section 7.3 table.
    Leaving it out fits slides 23-25 best. [ADAPTATION]
    """
    def value(s: float, c: float) -> float:
        cds = v.fk_cds(T, v.survival_function(s, B, _scaled(sig, c), lam), curve, R)
        return face * (coupon * cds.annuity - (1 - R) * cds.default_leg)

    return fk_greeks(value, S, lambda mid: -face * (1 - R) - (mid if include_value else 0.0), s_bump, vol_bump)


def bond_greeks(bond: e2c.Bond, S: float, B: float, sig: fk.Vol, curve: e2c.ZeroCurve, R_b: float, lam: float = 0.0,
                face: float = 1.0, s_bump: float = S_BUMP, vol_bump: float = VOL_BUMP) -> Greeks:
    """Step 26. Long bond at the model's full price. Jump is -(P - R_b) of face. Recovery is of face, as in step 15."""
    def value(s: float, c: float) -> float:
        return face * v.fk_bond_price(bond, v.survival_function(s, B, _scaled(sig, c), lam), curve, R_b)

    return fk_greeks(value, S, lambda mid: -(mid - face * R_b), s_bump, vol_bump)


def put_greeks(S: float, K: float, T: float, sig: float, B: float, r: float, p: float = 0.0, price: Optional[float] = None,
               s_bump: float = S_BUMP, vol_bump: float = VOL_BUMP) -> Greeks:
    """Step 26. Jump is K exp(-rT) - Put. lam = 0, as in fk_put. price replaces the model's value and jump, not the bumps."""
    jump = lambda mid: float(K * np.exp(-r * T) - mid)
    g = fk_greeks(lambda s, c: fk.fk_put(s, K, T, c * sig, B, r, p).price, S, jump, s_bump, vol_bump)
    return g if price is None else g._replace(value=price, jump=jump(price))


def call_greeks(S: float, K: float, T: float, sig: float, B: float, r: float, p: float = 0.0, price: Optional[float] = None,
                s_bump: float = S_BUMP, vol_bump: float = VOL_BUMP) -> Greeks:
    """Step 26. Jump is -Call. lam = 0, as in fk_call. price replaces the model's value and jump, not the bumps."""
    jump = lambda mid: -mid
    g = fk_greeks(lambda s, c: fk.fk_call(s, K, T, c * sig, B, r, p), S, jump, s_bump, vol_bump)
    return g if price is None else g._replace(value=price, jump=jump(price))


def stock_greeks(S: float) -> Greeks:
    """Step 26. [DECK s.1] The stock goes to 0 in default. Carr and Wu's post-default level is a stress for the caller."""
    return Greeks(S, 1.0, 0.0, 0.0, -S)


def put_only_ratio(target: Greeks, put: Greeks) -> float:
    """Step 26. -delta_P / delta_p, after Avino and Salvador (p.10). Puts to hold, with no stock. [ADAPTATION]"""
    return -target.delta / put.delta


def put_only_hedge(target: Greeks, put: Greeks) -> PutOnly:
    """Step 26. The put-only ratio, what it costs, and the share of the target's jump it covers."""
    n = put_only_ratio(target, put)
    return PutOnly(n, n * put.value, n * put.jump / -target.jump)


# ---------------------------------------------------------------- Step 27: solve

def solve_hedge(target: Greeks, *, reference_value: float, rows: Sequence[str], put: Optional[Greeks] = None,
                stock: Optional[Greeks] = None, call: Optional[Greeks] = None) -> Hedge:
    """Step 27. [DECK s.21-24] Solve M n = -g on rows, a choice from delta, vega and jump, with one leg per row.

    Guards [ADAPTATION]: a negative put or call count, then a stock position above STOCK_CAP times reference_value.
    reference_value is the bond's value. A CDS has no such price, so pass its notional.
    The condition number is reported and not filtered on, since it cannot separate good solves from bad.
    """
    legs = [(name, leg) for name, leg in (("put", put), ("stock", stock), ("call", call)) if leg is not None]
    if len(legs) != len(rows):
        raise ValueError(f"need one leg per row, got {len(legs)} legs and {len(rows)} rows")
    M = np.array([[getattr(leg, row) for _, leg in legs] for row in rows], dtype=float)
    g = np.array([getattr(target, row) for row in rows], dtype=float)
    condition = float(np.linalg.cond(M))
    try:
        x = np.linalg.solve(M, -g)
    except np.linalg.LinAlgError:
        nan = float("nan")
        return Hedge(nan, nan, nan, (nan, nan, nan), "singular", condition)
    n = {name: float(count) for (name, _), count in zip(legs, x)}
    n_put, n_stock, n_call = n.get("put", 0.0), n.get("stock", 0.0), n.get("call", 0.0)
    dollars = (n_put * put.value if put else 0.0, n_stock * stock.value if stock else 0.0, n_call * call.value if call else 0.0)
    if n_put < 0 or n_call < 0:
        status = "short_option"
    elif abs(dollars[1]) > STOCK_CAP * reference_value:
        status = "stock_too_large"
    else:
        status = "ok"
    return Hedge(n_put, n_stock, n_call, dollars, status, condition)


def net_greeks(target: Greeks, hedge: Hedge, put: Optional[Greeks] = None, stock: Optional[Greeks] = None,
               call: Optional[Greeks] = None) -> Greeks:
    """Target plus hedge, field by field. Zero on the solved rows, and the rest is what stays open."""
    total = np.array(target, dtype=float)
    for n, leg in ((hedge.n_put, put), (hedge.n_stock, stock), (hedge.n_call, call)):
        if leg is not None:
            total = total + n * np.array(leg, dtype=float)
    return Greeks(*map(float, total))


# ---------------------------------------------------------------- Step 28: optimal strike

def optimal_strike(target: Greeks, S: float, T: float, sig: float, B: float, r: float, p: float = 0.0) -> StrikeFit:
    """Step 28. [DECK s.25] K* where the delta and vega solution with one put also zeroes the jump.

    Slide 25 gives no definition, and this is my reading. It prices the put at the model's value at each K.
    """
    def solved(K: float) -> tuple:
        put = put_greeks(S, K, T, sig, B, r, p)
        n = -target.vega / put.vega
        ns = -(target.delta + n * put.delta)
        return n * put.jump - ns * S + target.jump, n, ns

    def gap(K: float) -> float:
        return solved(K)[0]

    grid = np.linspace(STRIKE_RANGE[0] * S, STRIKE_RANGE[1] * S, STRIKE_POINTS)
    gaps = [gap(K) for K in grid]
    roots = [float(brentq(gap, grid[i], grid[i + 1], xtol=1e-10))
             for i in range(len(grid) - 1) if gaps[i] * gaps[i + 1] < 0]
    if len(roots) != 1:
        nan = float("nan")
        return StrikeFit("no_root" if not roots else "multiple", nan, nan, nan)
    _, n, ns = solved(roots[0])
    return StrikeFit("ok", roots[0], float(n), float(ns))


# ---------------------------------------------------------------- Step 29: rebalancing

def rehedge_due(held: float, target: float, days_since: int, rule: str = "band", band: float = REHEDGE_BAND) -> bool:
    """Step 29. rule is band [DECK s.20] [ADAPTATION], weekly [OWN] or static [YU].

    Band rebalances weekly, or when target / held - 1 is beyond the band. Written without the division, so held may be 0.
    The S move reaches this rule through target. Costs are charged in the P&L of step 32.
    """
    if rule == "static":
        return False
    weekly = days_since >= REHEDGE_DAYS
    if rule == "weekly":
        return weekly
    if rule == "band":
        return weekly or abs(target - held) > band * abs(held)
    raise ValueError(f"unknown rule {rule}")
