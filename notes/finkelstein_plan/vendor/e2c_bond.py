"""Capital structure arbitrage on a bond against equity: reference implementation.

Every step in 02_bond_vol_method.md names one function here, and that step's inputs table lists
the function's arguments by name. Tags in the docstrings:
  [PAPER]        Fan Yu, "How Profitable Is Capital Structure Arbitrage?", 3 April 2005.
  [CREDITGRADES] CreditGrades Technical Document, May 2002.
  [ADAPTATION]   In neither source. The reasoning is in 02_bond_vol_method.md.

Units: spreads, rates and vols are decimals (0.01 = 100 bp). Prices are per 1 of face, except
trade reports, which are in percent of par as TRACE prints them. Time is in years. Rates compound
continuously. Coupons and accrued interest use 30/360.

Page numbers in this file and its tests are printed pages. In the PDFs, Yu's page is printed + 2
and the CreditGrades page is printed + 6.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.special import log_ndtr, ndtr

_GL_X, _GL_W = np.polynomial.legendre.leggauss(96)
_CLOSED_FORM_MAX_R_XI = 30.0   # above this, e^{r xi}(G - G) loses all its digits
_ACT360 = 360.0 / 365.0
YU_RECOVERY = 0.5
YU_LAMBDA = 0.3
BARRIER_BOUNDS = (0.01, 3.0)


# --------------------------------------------------------------------------------------
# Objects the steps pass around
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Firm:
    """Inputs to the model on one day.

    S       share price.
    D       debt per share. The model uses D only through the product L_bar * D.
    sigma_s equity volatility.
    L_bar   mean global recovery. Yu fits it on the first ten days of spreads.
    lam     standard deviation of log recovery. Yu fixes 0.3.
    S_ref   reference price for the asset-vol conversion (CreditGrades 2.27).
            None means the current price S, which is Yu's Eq. (13).
    """
    S: float
    D: float
    sigma_s: float
    L_bar: float = 0.5
    lam: float = YU_LAMBDA
    S_ref: float | None = None


@dataclass(frozen=True)
class Bond:
    """A fixed-coupon bullet. maturity is years left. Face is 1."""
    coupon: float
    maturity: float
    freq: int = 2


@dataclass(frozen=True)
class ZeroCurve:
    """Continuously compounded zero rates, interpolated linearly in the rate."""
    tenors: tuple
    zeros: tuple

    def df(self, t):
        return np.exp(-np.interp(t, self.tenors, self.zeros) * np.asarray(t, dtype=float))


def flat_curve(r: float) -> ZeroCurve:
    return ZeroCurve((0.0, 100.0), (r, r))


@dataclass(frozen=True)
class VolInversion:
    """Result of inverting a spread for equity vol.

    status is one of:
      ok             one root, in sigma_s.
      below_floor    the market spread is under the model spread at the lowest vol.
      above_ceiling  the market spread is over the model spread at the highest vol.
      multiple       more than one vol gives the market spread, listed in roots.
      near_recovery  the bond trades too close to recovery for the inversion to mean anything.
    """
    status: str
    sigma_s: float = float("nan")
    roots: tuple = ()


@dataclass(frozen=True)
class Position:
    """side +1: long bond, short stock, short Treasury. side -1: the reverse.

    face, shares and hedge_face are all positive sizes.
    """
    side: int
    face: float
    shares: float
    hedge_face: float


@dataclass(frozen=True)
class Marks:
    """Closing marks on one day. Coupons and dividends are those paid on that day."""
    bond_clean: float
    bond_accrued: float
    stock: float
    hedge_full: float
    bond_coupon: float = 0.0
    dividend: float = 0.0
    hedge_coupon: float = 0.0

    @property
    def bond_full(self) -> float:
        return self.bond_clean + self.bond_accrued


@dataclass(frozen=True)
class Carry:
    """Annual financing rates for one day and the day fraction dt.

    repo        rate to finance a long bond, and the base rate on a short bond.
    bond_fee    borrow fee on a short bond, taken off the repo rate.
    stock_fee   borrow fee on a short stock, taken off cash_rate.
    cash_rate   rate on stock-sale proceeds and the cost of funding long stock.
    hedge_repo  repo rate on the Treasury hedge.
    """
    repo: float
    bond_fee: float
    stock_fee: float
    cash_rate: float
    hedge_repo: float
    dt: float


# --------------------------------------------------------------------------------------
# Part 1. Choose the issuers and the bond
# --------------------------------------------------------------------------------------

def issuer_is_eligible(sector: str, has_listed_equity: bool) -> bool:
    """Yu excludes financials and utilities (p. 14). Listed stock is needed for the model."""
    return has_listed_equity and sector.lower() not in ("financial", "utility")


def bond_terms_are_eligible(seniority: str, currency: str, coupon_type: str, call_type: str,
                            is_convertible: bool, is_putable: bool, is_sinking: bool,
                            is_perpetual: bool, is_pik: bool) -> bool:
    """Senior unsecured, USD, fixed coupon, no option but a call. [ADAPTATION]

    call_type is 'none', 'make_whole' or 'fixed_price'. A make-whole call counts as a bullet.
    """
    return (seniority == "senior_unsecured" and currency == "USD" and coupon_type == "fixed"
            and call_type in ("none", "make_whole", "fixed_price")
            and not (is_convertible or is_putable or is_sinking or is_perpetual or is_pik))


def callable_is_usable(call_type: str, clean_price: float, next_call_price: float,
                       buffer: float = 0.05) -> bool:
    """A fixed-price callable counts only when well under its call price. [ADAPTATION]"""
    return call_type != "fixed_price" or clean_price <= next_call_price - buffer


def maturity_is_eligible(years_left: float, issuer_has_core_bond: bool) -> bool:
    """3 to 7 years, or 2 to 10 if the issuer has nothing in 3 to 7. [ADAPTATION]"""
    if 3.0 <= years_left <= 7.0:
        return True
    return not issuer_has_core_bond and 2.0 <= years_left <= 10.0


def age_and_size_are_eligible(years_since_issue: float, years_left: float,
                              amount_outstanding: float) -> bool:
    """At least 3 months old, 1 year left and USD 250mm outstanding. [ADAPTATION]"""
    return years_since_issue >= 0.25 and years_left >= 1.0 and amount_outstanding >= 250e6


def pick_bond_and_sibling(bond_ids: list, trades_60d: list) -> tuple:
    """The most traded eligible bond, and the next one as its sibling. [ADAPTATION]"""
    order = np.argsort(-np.asarray(trades_60d), kind="stable")
    sibling = bond_ids[order[1]] if len(order) > 1 else None
    return bond_ids[order[0]], sibling


def passes_liquidity_screen(institutional_trades_5d: int, minimum: int = 10) -> bool:
    """Enough trades of USD 100k or more in the last five business days. [ADAPTATION]"""
    return institutional_trades_5d >= minimum


# --------------------------------------------------------------------------------------
# Part 2. Build the inputs
# --------------------------------------------------------------------------------------

def debt_per_share(total_liabilities: float, shares_outstanding: float) -> float:
    """Yu p. 15: total liabilities over common shares outstanding."""
    return total_liabilities / shares_outstanding


def filing_usable_from(acceptance_date, period_end, form: str):
    """First day a filing may be used. [ADAPTATION]

    The next business day after acceptance. With no acceptance date (NaT), the period end plus
    45 days for a 10-Q or 90 days for a 10-K. Yu instead lags one month from quarter end (p. 12).
    """
    acceptance_date = np.datetime64(acceptance_date, "D")
    if not np.isnat(acceptance_date):
        return np.busday_offset(acceptance_date, 1, roll="backward")
    days = 45 if form == "10-Q" else 90
    return np.busday_offset(np.datetime64(period_end, "D") + np.timedelta64(days, "D"), 0, roll="forward")


def debt_after_corporate_action(firm_before: Firm, S_after: float, T: float, R: float, r: float) -> float:
    """Debt per share that keeps the model spread unchanged through the event. Yu footnote 14."""
    target = cds_par_spread(T, firm_before, R, r)

    def gap(d: float) -> float:
        return cds_par_spread(T, replace(firm_before, S=S_after, D=d), R, r) - target

    return brentq(gap, firm_before.D * 0.001, firm_before.D * 100.0, xtol=1e-10)


def historical_equity_vol(daily_log_returns, window: int = 1000, min_obs: int = 750,
                          periods_per_year: int = 252) -> float:
    """Yu's 1,000-day equity vol (p. 15). [ADAPTATION] The estimator, which he does not state.

    Sample standard deviation over the last window returns, annualised. NaN if too few.
    """
    r = np.asarray(daily_log_returns, dtype=float)
    r = r[np.isfinite(r)][-window:]
    if len(r) < min_obs:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


def equity_vol_input(source: str, historical_vol: float, implied_vol: float) -> float:
    """The one vol a run uses. A run never mixes the two sources. [ADAPTATION]"""
    if source == "historical":
        return historical_vol
    if source == "implied":
        return implied_vol
    raise ValueError(f"unknown vol source: {source}")


def zero_curve_from_par_yields(tenors, par_yields) -> ZeroCurve:
    """Bootstrap semiannual par yields into continuous zero rates. [ADAPTATION]

    Tenors under six months are simple-interest bills. The rest use par yields interpolated
    linearly onto a six-month grid.
    """
    tenors = np.asarray(tenors, dtype=float)
    par_yields = np.asarray(par_yields, dtype=float)
    short = tenors < 0.5
    short_zeros = np.log(1 + par_yields[short] * tenors[short]) / tenors[short]
    grid = np.arange(0.5, tenors.max() + 1e-9, 0.5)
    par = np.interp(grid, tenors, par_yields)
    dfs = np.zeros(len(grid))
    for i, y in enumerate(par):
        dfs[i] = (1 - y / 2 * dfs[:i].sum()) / (1 + y / 2)
    return ZeroCurve(tuple(tenors[short]) + tuple(grid), tuple(short_zeros) + tuple(-np.log(dfs) / grid))


# --------------------------------------------------------------------------------------
# Part 3. Compute the market spread
# --------------------------------------------------------------------------------------

def clean_trade_reports(msg_seq, orig_msg_seq, action, is_duplicate_side):
    """Keep mask: drop cancels, reversals, what they and corrections replace, and duplicates. [ADAPTATION]

    action is 'new', 'cancel', 'correct' or 'reverse'. Map your vendor's status codes onto these.
    orig_msg_seq is the report that this one changes. is_duplicate_side marks the second report
    of an interdealer or agency trade. This follows the summary in Dickerson et al. (2026, p. 8).
    """
    msg_seq, orig_msg_seq = np.asarray(msg_seq), np.asarray(orig_msg_seq)
    action = np.asarray(action)
    changes = action != "new"
    keep = np.isin(action, ("new", "correct"))
    keep &= ~np.isin(msg_seq, orig_msg_seq[changes])
    keep &= ~np.asarray(is_duplicate_side, dtype=bool)
    return keep


def fix_decimal_shifts(prices, half_window: int = 5):
    """Correct prices entered with the decimal in the wrong place. Dickerson et al. A.1. [ADAPTATION]

    Prices in percent of par. The window uses later trades, so run it only on prints known by
    the signal day's close.
    """
    p = np.asarray(prices, dtype=float)
    out = p.copy()
    for i, price in enumerate(p):
        anchor = np.median(np.unique(p[max(0, i - half_window):i + half_window + 1]))
        raw_error = abs(price - anchor) / anchor
        if raw_error <= 0.05:
            continue
        best, best_error = None, np.inf
        for factor in (0.1, 0.01, 10.0, 100.0):
            candidate = factor * price
            error = abs(candidate - anchor) / anchor
            aligned = (error <= 0.02 or abs(candidate - anchor) <= 8.0
                       or (abs(anchor - 100.0) <= 15.0 and abs(candidate - 100.0) <= 15.0))
            if aligned and error <= 0.20 * raw_error and 5.0 <= candidate <= 300.0 and error < best_error:
                best, best_error = candidate, error
        if best is not None:
            out[i] = best
    return out


def flag_price_spikes(prices, threshold: float = 35.0, forward: int = 5, window: int = 5,
                      slack: float = 1.0, alpha: float = 0.25):
    """Flag prices that jump and quickly revert. The core of Dickerson et al. A.2. [ADAPTATION]

    Omits their flag reassignment and par-block rules. Adds one condition: the price must also
    stand away from its baseline, so that the return to normal is not flagged as a second spike.
    Prices in percent of par. Run it only on prints known by the signal day's close.
    """
    p = np.asarray(prices, dtype=float)
    flagged = np.zeros(len(p), dtype=bool)
    for i in range(1, len(p)):
        start = max(0, i - window)
        past = p[start:i][~flagged[start:i]]
        if len(past) == 0:
            continue
        base = np.median(np.unique(past))
        moved = p[i] - base
        if abs(moved) <= alpha * threshold:
            continue
        candidate = (abs(p[i] - p[i - 1]) >= threshold - slack or abs(moved) >= threshold - slack
                     or p[i] == 100.0)
        if not candidate:
            continue
        for j in range(i + 1, min(i + forward + 1, len(p))):
            step = p[j] - p[j - 1]
            opposite = np.sign(step) == -np.sign(moved) and abs(step) >= threshold - slack
            if opposite or abs(p[j] - base) <= alpha * threshold:
                flagged[i:j] = True
                break
    return flagged


def daily_clean_price(prices, sizes, is_customer_buy, min_size: float = 100_000.0) -> tuple:
    """Average of the buy and sell volume-weighted prices, per 1 of face. [ADAPTATION]

    Returns (price, one_sided). one_sided is True if only one side traded. NaN if no trade.
    """
    p, s = np.asarray(prices, dtype=float), np.asarray(sizes, dtype=float)
    buy = np.asarray(is_customer_buy, dtype=bool)
    big = s >= min_size
    sides = []
    for mask in (big & buy, big & ~buy):
        if mask.any():
            sides.append(np.average(p[mask], weights=s[mask]))
    if not sides:
        return float("nan"), False
    return float(np.mean(sides)) / 100.0, len(sides) == 1


def cash_flows(bond: Bond) -> tuple:
    """Payment times and amounts, stepped back from maturity. The first coupon is whole."""
    n = int(np.ceil(bond.maturity * bond.freq - 1e-9))
    times = bond.maturity - np.arange(n)[::-1] / bond.freq
    amounts = np.full(n, bond.coupon / bond.freq)
    amounts[-1] += 1.0
    return times, amounts


def accrued_interest(bond: Bond) -> float:
    """Coupon earned since the last payment date."""
    return bond.coupon * (1.0 / bond.freq - cash_flows(bond)[0][0])


def full_price(clean: float, bond: Bond) -> float:
    """Clean price plus accrued interest. [ADAPTATION]"""
    return clean + accrued_interest(bond)


def price_from_z(z: float, bond: Bond, curve: ZeroCurve) -> float:
    """Full price at Z-spread z: every cash flow discounted at zero rate plus z."""
    t, cf = cash_flows(bond)
    return float(np.sum(cf * curve.df(t) * np.exp(-z * t)))


def z_spread(price: float, bond: Bond, curve: ZeroCurve) -> float:
    """Z-spread of a full price, on the given curve, continuously compounded. [ADAPTATION]"""
    return brentq(lambda z: price_from_z(z, bond, curve) - price, -0.5, 20.0, xtol=1e-10)


# --------------------------------------------------------------------------------------
# Part 4. Compute the model value of this bond
# --------------------------------------------------------------------------------------

def asset_vol(firm: Firm) -> float:
    """Asset volatility. Yu Eq. (13), CreditGrades 2.26, 2.27 and 3.1."""
    s = firm.S if firm.S_ref is None else firm.S_ref
    return firm.sigma_s * s / (s + firm.L_bar * firm.D)


def barrier_distance(firm: Firm) -> float:
    """d = V0 / (L_bar D) * exp(lam^2) with V0 = S + L_bar D. Yu p. 33, CreditGrades 2.29."""
    barrier = firm.L_bar * firm.D
    return (firm.S + barrier) / barrier * np.exp(firm.lam ** 2)


def survival(t, firm: Firm):
    """Survival probability q(t). Yu Eq. (11), CreditGrades 2.28.

    q(0) is below 1 when lam > 0. Both sources say so (Yu footnote 22, CreditGrades p. 8).
    """
    d = barrier_distance(firm)
    a = np.sqrt(asset_vol(firm) ** 2 * np.asarray(t, dtype=float) + firm.lam ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(d) / a
    return ndtr(-a / 2 + ratio) - d * ndtr(-a / 2 - ratio)


def _g(u: float, firm: Firm, r: float) -> float:
    """G(u) of Yu p. 34, CreditGrades 2.16, in log space so that d^z cannot overflow."""
    if u <= 0:
        return 0.0
    sig = asset_vol(firm)
    log_d = np.log(barrier_distance(firm))
    z = np.sqrt(0.25 + 2 * r / sig ** 2)
    s = sig * np.sqrt(u)
    return float(np.exp((z + 0.5) * log_d + log_ndtr(-log_d / s - z * s))
                 + np.exp((0.5 - z) * log_d + log_ndtr(-log_d / s + z * s)))


def _closed_form_is_stable(firm: Firm, r: float) -> bool:
    xi = firm.lam ** 2 / asset_vol(firm) ** 2
    return r >= 1e-6 and r * xi <= _CLOSED_FORM_MAX_R_XI


def discounted_default(T: float, firm: Firm, r: float) -> float:
    """H(T), the discounted default density between 0 and T. Yu p. 34, CreditGrades A.14."""
    if _closed_form_is_stable(firm, r):
        xi = firm.lam ** 2 / asset_vol(firm) ** 2
        return float(np.exp(r * xi) * (_g(T + xi, firm, r) - _g(xi, firm, r)))
    return float(survival(0.0, firm) - survival(T, firm) * np.exp(-r * T)
                 - r * cds_annuity(T, firm, r))


def cds_annuity(T: float, firm: Firm, r: float) -> float:
    """Value of 1 per year paid until default or T: the integral of e^{-rs} q(s) ds.

    This is Yu Eq. (14) with G(xi) in place of Yu's G(T), which is a misprint. See
    01_paper_extraction.md. Quadrature takes over when the closed form loses precision.
    """
    if _closed_form_is_stable(firm, r):
        xi = firm.lam ** 2 / asset_vol(firm) ** 2
        h = np.exp(r * xi) * (_g(T + xi, firm, r) - _g(xi, firm, r))
        return float((survival(0.0, firm) - survival(T, firm) * np.exp(-r * T) - h) / r)
    s = 0.5 * T * (_GL_X + 1)
    return float(0.5 * T * np.sum(_GL_W * np.exp(-r * s) * survival(s, firm)))


def cds_par_spread(T: float, firm: Firm, R: float, r: float, act360: bool = False) -> float:
    """CDS par spread c(0, T). Yu Eq. (12), CreditGrades 2.15.

    act360=True scales by 360/365, the convention behind CreditGrades Table C.1.
    Yu's Eq. (12) has no such scaling.
    """
    protection = 1 - survival(0.0, firm) + discounted_default(T, firm, r)
    spread = (1 - R) * protection / cds_annuity(T, firm, r)
    return float(spread * _ACT360 if act360 else spread)


def default_leg(T: float, firm: Firm, curve: ZeroCurve) -> float:
    """PV of 1 paid at default before T, plus the atom 1 - q(0) paid today. [ADAPTATION]

    Same object as the numerator 1 - q(0) + H(T) of Yu Eq. (12), on any discount curve.
    """
    grid = np.linspace(0.0, T, max(48, int(T * 48)) + 1)
    q = survival(grid, firm)
    middle = 0.5 * (grid[1:] + grid[:-1])
    return float(1 - q[0] + np.sum(curve.df(middle) * (q[:-1] - q[1:])))


def risky_bond_price(bond: Bond, firm: Firm, curve: ZeroCurve, R_b: float) -> float:
    """Model full (dirty) price. [ADAPTATION]

    P = sum_i CF_i DF(t_i) q(t_i) + R_b * (1 - q(0) + integral of DF(s) (-q'(s)) ds)

    Recovery is R_b of face, whatever the bond's price is.
    """
    t, cf = cash_flows(bond)
    return float(np.sum(cf * curve.df(t) * survival(t, firm))
                 + R_b * default_leg(bond.maturity, firm, curve))


def model_z_spread(bond: Bond, firm: Firm, curve: ZeroCurve, R_b: float) -> float:
    """Model spread on the same convention as the market Z-spread. [ADAPTATION]"""
    return z_spread(risky_bond_price(bond, firm, curve, R_b), bond, curve)


# --------------------------------------------------------------------------------------
# Part 5. Calibrate
# --------------------------------------------------------------------------------------

def yu_fixed_parameters() -> tuple:
    """Yu p. 15: (R, lam) = (0.5, 0.3), fixed for all obligors and dates."""
    return YU_RECOVERY, YU_LAMBDA


def calibrate_barrier(model_spreads, market_spreads, bounds=BARRIER_BOUNDS) -> tuple:
    """Fit L_bar by least squares on the spread. Yu p. 16 does this on ten days of CDS.

    model_spreads(L_bar) returns the model spread on each calibration day.
    Returns (L_bar, root mean squared error).
    """
    market = np.asarray(market_spreads, dtype=float)

    def sse(l_bar: float) -> float:
        return float(np.sum((np.asarray(model_spreads(l_bar)) - market) ** 2))

    grid = np.geomspace(bounds[0], bounds[1], 30)
    i = int(np.argmin([sse(x) for x in grid]))
    lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
    fit = minimize_scalar(sse, bounds=(lo, hi), method="bounded", options={"xatol": 1e-6})
    return float(fit.x), float(np.sqrt(fit.fun / len(market)))


def fit_barrier_on_bond(bonds: list, S, D, sigma_s, z_market, curves: list, R_b: float,
                        lam: float) -> tuple:
    """Yu's fit, on a bond's Z-spread instead of a CDS spread. Returns (L_bar, rmse). [ADAPTATION]"""
    def model(l_bar: float) -> list:
        return [model_z_spread(b, Firm(float(s), float(d), float(v), l_bar, lam), c, R_b)
                for b, s, d, v, c in zip(bonds, S, D, sigma_s, curves)]

    return calibrate_barrier(model, z_market)


def fit_barrier_on_cds(c_market, S, D, sigma_s, r, T: float, R: float, lam: float) -> tuple:
    """Yu's fit (p. 16), on CDS spreads. Returns (L_bar, rmse)."""
    def model(l_bar: float) -> list:
        return [cds_par_spread(T, Firm(float(s), float(d), float(v), l_bar, lam), R, float(x))
                for s, d, v, x in zip(S, D, sigma_s, r)]

    return calibrate_barrier(model, c_market)


def fit_status(L_bar: float, bounds=BARRIER_BOUNDS) -> str:
    """'reject' on a bound, 'review' above 1, otherwise 'ok'. [ADAPTATION]"""
    if L_bar <= bounds[0] * 1.001 or L_bar >= bounds[1] * 0.999:
        return "reject"
    return "review" if L_bar > 1.0 else "ok"


def passes_barrier_filter(firm: Firm, max_atom: float = 0.01) -> bool:
    """False when the model says the firm has already defaulted with more than max_atom. [ADAPTATION]

    Near the barrier the atom 1 - q(0) sets a floor under the spread, so the model stops responding.
    """
    return float(1 - survival(0.0, firm)) <= max_atom


# --------------------------------------------------------------------------------------
# Part 6. Run the signal
# --------------------------------------------------------------------------------------

def entry_signal(market: float, model: float, alpha: float) -> int:
    """Yu Eq. (8).

    +1 when market > (1 + alpha) * model: long the bond, short the stock.
    -1 when model > (1 + alpha) * market: short the bond, long the stock.
    A spread at or below zero gives no signal, because the ratio has no meaning there.
    """
    if market <= 0 or model <= 0:
        return 0
    if market > (1 + alpha) * model:
        return 1
    if model > (1 + alpha) * market:
        return -1
    return 0


def log_gap(market: float, model: float) -> float:
    """ln(market / model). Eq. (8) fires when this exceeds ln(1 + alpha) in size. [ADAPTATION]"""
    if market <= 0 or model <= 0:
        return float("nan")
    return float(np.log(market / model))


def peer_median_gap(peer_gaps) -> float:
    """Median log gap of same-rating, same-maturity peers, 0 if there are none. [ADAPTATION]"""
    gaps = np.asarray(peer_gaps, dtype=float)
    gaps = gaps[np.isfinite(gaps)]
    return float(np.median(gaps)) if len(gaps) else 0.0


def peer_adjusted_signal(gap: float, peer_gap: float, alpha: float) -> int:
    """Eq. (8) after removing the peers' median gap. [ADAPTATION]"""
    adjusted = gap - peer_gap
    if not np.isfinite(adjusted) or abs(adjusted) <= np.log(1 + alpha):
        return 0
    return 1 if adjusted > 0 else -1


def sibling_confirms(gap: float, sibling_gap: float) -> bool:
    """The sibling's gap has the same sign and at least half the size. NaN means no sibling. [ADAPTATION]"""
    if not np.isfinite(sibling_gap):
        return True
    return np.sign(sibling_gap) == np.sign(gap) and abs(sibling_gap) >= 0.5 * abs(gap)


def cds_confirms(signal: int, cds_market: float, cds_model: float, alpha: float) -> bool:
    """Eq. (8) on the issuer's CDS gives the same sign. NaN means no CDS. [ADAPTATION]"""
    if not np.isfinite(cds_market):
        return True
    return entry_signal(cds_market, cds_model, alpha) == signal


def passes_cost_gate(market: float, model: float, duration: float, round_trip: float,
                     multiple: float = 2.0) -> bool:
    """Full convergence must pay at least multiple * round-trip cost. [ADAPTATION]"""
    return abs(market - model) * duration >= multiple * round_trip


def implied_vol_confirms(signal: int, z_market: float, bond: Bond, firm: Firm, implied_vol: float,
                         curve: ZeroCurve, R_b: float, alpha: float) -> bool:
    """A long-bond signal must survive using implied vol in the model. NaN means no option data. [ADAPTATION]"""
    if signal != 1 or not np.isfinite(implied_vol):
        return True
    z_model = model_z_spread(bond, replace(firm, sigma_s=implied_vol, S_ref=None), curve, R_b)
    return entry_signal(z_market, z_model, alpha) == signal


def implied_vol_bond(z_market: float, bond: Bond, firm: Firm, curve: ZeroCurve, R_b: float,
                     recovery_buffer: float = 0.10,
                     grid: np.ndarray = np.geomspace(0.02, 4.0, 80)) -> VolInversion:
    """Credit-implied equity vol from a bond's market Z-spread. [ADAPTATION]

    Unlike a CDS spread, a bond price can turn back up as vol rises once its forward value
    falls under recovery. So this scans the grid and reports every root. A price under
    R_b + recovery_buffer is refused. recovery_buffer=-1 turns that guard off.
    """
    target = price_from_z(z_market, bond, curve)
    if target < R_b + recovery_buffer:
        return VolInversion("near_recovery")

    def gap(sig: float) -> float:
        return risky_bond_price(bond, replace(firm, sigma_s=sig, S_ref=None), curve, R_b) - target

    gaps = [gap(s) for s in grid]
    roots = tuple(brentq(gap, grid[i], grid[i + 1], xtol=1e-8)
                  for i in range(len(grid) - 1) if gaps[i] * gaps[i + 1] < 0)
    if not roots:
        return VolInversion("below_floor" if gaps[0] < 0 else "above_ceiling")
    if len(roots) > 1:
        return VolInversion("multiple", float("nan"), roots)
    return VolInversion("ok", roots[0], roots)


def implied_vol_cds(c_market: float, T: float, firm: Firm, R: float, r: float,
                    lo: float = 0.01, hi: float = 5.0) -> VolInversion:
    """Equity vol that makes the model spread equal the CDS spread. CreditGrades p. 13.

    The spread rises with vol for every T, because q(t) falls with vol, so a root is unique.
    """
    def gap(sig: float) -> float:
        return cds_par_spread(T, replace(firm, sigma_s=sig, S_ref=None), R, r) - c_market

    if gap(lo) > 0:
        return VolInversion("below_floor")
    if gap(hi) < 0:
        return VolInversion("above_ceiling")
    root = brentq(gap, lo, hi, xtol=1e-10)
    return VolInversion("ok", root, (root,))


def vol_status_allows_trade(inversion: VolInversion) -> bool:
    """Only one clean root may trade. [ADAPTATION]"""
    return inversion.status == "ok"


def vol_entry_signal(sigma_imp: float, sigma_obs: float, beta: float) -> int:
    """Eq. (8)'s form in vol space. +1: long bond, short stock. -1: the reverse. [ADAPTATION]"""
    return entry_signal(sigma_imp, sigma_obs, beta)


def beta_equivalent_to_alpha(alpha: float, bond: Bond, firm: Firm, curve: ZeroCurve, R_b: float) -> float:
    """The vol trigger that fires exactly where alpha fires, for this bond today. [ADAPTATION]"""
    z = model_z_spread(bond, firm, curve, R_b)
    return implied_vol_bond(z * (1 + alpha), bond, firm, curve, R_b).sigma_s / firm.sigma_s - 1


def decide_entry(signal: int, tradable: bool, barrier_ok: bool, sibling_ok: bool, cds_ok: bool,
                 cost_ok: bool, vol_ok: bool) -> int:
    """The signal, if every check passes. Otherwise 0. [ADAPTATION]"""
    return signal if tradable and barrier_ok and sibling_ok and cds_ok and cost_ok and vol_ok else 0


# --------------------------------------------------------------------------------------
# Part 7. Construct the trade
# --------------------------------------------------------------------------------------

def execution_day(signal_day: int, lag: int = 1) -> int:
    """Trade after the signal, never on it. lag=0 exists only for check 'lag_sensitivity'. [ADAPTATION]"""
    return signal_day + lag


def dollar_duration(bond: Bond, z: float, curve: ZeroCurve) -> float:
    """-dP/dy at constant z. For a bullet this is both rate and spread duration in price. [ADAPTATION]"""
    t, cf = cash_flows(bond)
    return float(np.sum(t * cf * curve.df(t) * np.exp(-z * t)))


def cds_equivalent_face(bond: Bond, z: float, curve: ZeroCurve, annuity_5y: float) -> float:
    """Bond face with the same spread risk as 1 of 5-year CDS notional. [ADAPTATION]"""
    return annuity_5y / dollar_duration(bond, z, curve)


def _bumped(firm: Firm, s: float, hold: str) -> Firm:
    """Move the share price. hold='asset_vol' pins S_ref, as CreditGrades p. 36 does.

    hold='equity_vol' keeps sigma_s and lets asset vol move through Yu Eq. (13).
    Yu does not say which he uses.
    """
    if hold == "asset_vol":
        return replace(firm, S=s, S_ref=firm.S if firm.S_ref is None else firm.S_ref)
    if hold == "equity_vol":
        return replace(firm, S=s, S_ref=None)
    raise ValueError(f"unknown hold: {hold}")


def bond_equity_delta(bond: Bond, firm: Firm, curve: ZeroCurve, R_b: float,
                      hold: str = "asset_vol") -> float:
    """dP/dS of the model price, per 1 of face. Positive. [ADAPTATION]

    A long bond shorts this many shares. A short bond buys them.
    """
    h = 0.01 * firm.S
    up = risky_bond_price(bond, _bumped(firm, firm.S + h, hold), curve, R_b)
    down = risky_bond_price(bond, _bumped(firm, firm.S - h, hold), curve, R_b)
    return (up - down) / (2 * h)


def par_hedge_bond(years_left: float, curve: ZeroCurve, freq: int = 2) -> Bond:
    """A Treasury with the bond's maturity, at a coupon that prices it at par. [ADAPTATION]

    Stands in for the listed Treasury closest in maturity.
    """
    t, _ = cash_flows(Bond(0.0, years_left, freq))
    dfs = curve.df(t)
    return Bond(float(freq * (1 - dfs[-1]) / dfs.sum()), years_left, freq)


def rate_hedge_face(bond: Bond, z: float, hedge_bond: Bond, curve: ZeroCurve) -> float:
    """Treasury face per 1 of bond face with equal rate risk. [ADAPTATION]"""
    return dollar_duration(bond, z, curve) / dollar_duration(hedge_bond, 0.0, curve)


def build_position(side: int, face: float, delta: float, hedge_ratio: float) -> Position:
    """Sizes of all three legs. Yu fixes the equity hedge at entry (p. 9). [ADAPTATION]"""
    return Position(side, face, face * delta, face * hedge_ratio)


def rate_hedge_is_due(current_hedge_face: float, target_hedge_face: float, days_since_reset: float,
                      max_drift: float = 0.05, max_days: float = 30.0) -> bool:
    """Re-set the Treasury monthly, or when it drifts over 5% from target. [ADAPTATION]"""
    return (days_since_reset >= max_days
            or abs(current_hedge_face / target_hedge_face - 1) > max_drift)


def bond_financing_rate(side: int, repo: float, bond_fee: float) -> float:
    """A long bond pays repo. A short bond earns repo less the borrow fee. [ADAPTATION]"""
    return repo if side > 0 else repo - bond_fee


def stock_financing_rate(side: int, cash_rate: float, stock_fee: float) -> float:
    """A short stock earns cash less the fee. A long stock pays cash. side is the bond's side. [ADAPTATION]"""
    return cash_rate - stock_fee if side > 0 else cash_rate


def opening_account_value(capital: float, entry_cost: float) -> float:
    """Yu's margin account (footnote 12), after the cost of entering. [ADAPTATION]"""
    return capital - entry_cost


# --------------------------------------------------------------------------------------
# Part 8. Daily P&L, capital and return
# --------------------------------------------------------------------------------------

def coupons_paid(before: Bond, after: Bond) -> float:
    """Coupon cash paid between two dates, from the fall in remaining payments. [ADAPTATION]"""
    return before.coupon / before.freq * (len(cash_flows(before)[0]) - len(cash_flows(after)[0]))


def daily_pnl(pos: Position, prev: Marks, now: Marks, carry: Carry) -> dict:
    """P&L of each leg from one close to the next. [ADAPTATION]

    Every leg is financed, so the trade costs nothing up front, like a CDS. Capital sits apart
    in the margin account, so 'total' over the last account value is an excess return.
    """
    s = pos.side
    bond_rate = bond_financing_rate(s, carry.repo, carry.bond_fee)
    stock_rate = stock_financing_rate(s, carry.cash_rate, carry.stock_fee)
    legs = {
        "bond_price": s * pos.face * (now.bond_full - prev.bond_full + now.bond_coupon),
        "bond_financing": -s * pos.face * prev.bond_full * bond_rate * carry.dt,
        "stock_price": -s * pos.shares * (now.stock - prev.stock + now.dividend),
        "stock_financing": s * pos.shares * prev.stock * stock_rate * carry.dt,
        "hedge_price": -s * pos.hedge_face * (now.hedge_full - prev.hedge_full + now.hedge_coupon),
        "hedge_financing": s * pos.hedge_face * prev.hedge_full * carry.hedge_repo * carry.dt,
    }
    legs["total"] = sum(legs.values())
    return legs


def next_account_value(value: float, pnl: float) -> tuple:
    """New account value and the day's return. Yu needs value > 0 for the return to exist."""
    return value + pnl, pnl / value


# --------------------------------------------------------------------------------------
# Part 9. Transaction costs
# --------------------------------------------------------------------------------------

def yu_cds_round_trip(spread: float, annuity: float, bid_ask: float = 0.05) -> float:
    """Yu's CDS cost in price terms: bid_ask of the spread, for the annuity's life (pp. 11-12)."""
    return bid_ask * spread * annuity


def measured_round_trip(buy_prices, buy_sizes, sell_prices, sell_sizes) -> float:
    """Customer-buy minus customer-sell volume-weighted price, per 1 of face. [ADAPTATION]

    Prices in percent of par. Pool the last 20 days of trades.
    """
    return float(np.average(buy_prices, weights=buy_sizes)
                 - np.average(sell_prices, weights=sell_sizes)) / 100.0


def planning_round_trip(rating: str, z: float) -> float:
    """Round trip per 1 of face when none can be measured. My planning numbers, unsourced. [ADAPTATION]"""
    if z > 0.10 or rating in ("CCC", "CC", "C", "D"):
        return 0.03
    return {"BB": 0.01, "B": 0.015}.get(rating, 0.005)


def stressed_cost(round_trip: float, multiple: float) -> float:
    """Yu's 'Trans' test doubles the cost. Three times applies in stress months. [ADAPTATION]"""
    return round_trip * multiple


def trade_cost(pos: Position, marks: Marks, bond_half: float, stock_half: float,
               hedge_half: float) -> float:
    """Cost of one side of the trade, charged once at entry and once at exit. Positive. [ADAPTATION]

    bond_half and hedge_half are in price per 1 of face. stock_half is a fraction of the price.
    Yu charges the CDS side only and calls stock costs negligible (p. 12).
    """
    return (pos.face * bond_half + pos.shares * marks.stock * stock_half
            + pos.hedge_face * hedge_half)


# --------------------------------------------------------------------------------------
# Part 10. Exit, holding period and stops
# --------------------------------------------------------------------------------------

def exit_reason(side: int, market: float, model: float, days_held: float, max_hold: float,
                value: float) -> str | None:
    """Yu's exits, p. 18: limited liability, convergence, end of the holding period.

    Convergence is ct = c't. On daily data that means the gap has reached zero or changed sign.
    """
    if value < 0:
        return "limited_liability"
    if side * (market - model) <= 0:
        return "convergence"
    if days_held >= max_hold:
        return "holding_period"
    return None


def bond_exit_reason(side: int, market: float, model: float, days_held: float, max_hold: float,
                     value: float, years_left: float, days_since_price: float,
                     forced_event: str | None = None, max_drawdown: float | None = None,
                     peak_value: float | None = None) -> str | None:
    """Yu's exits plus the exits a bond needs. [ADAPTATION]

    forced_event names a call, tender, merger, default or recalled bond borrow.
    """
    if value < 0:
        return "limited_liability"
    if forced_event:
        return forced_event
    if days_since_price > 14:
        return "no_price_14_days"
    if years_left < 1.0:
        return "under_one_year"
    if max_drawdown is not None and peak_value and value < peak_value * (1 - max_drawdown):
        return "drawdown_stop"
    return exit_reason(side, market, model, days_held, max_hold, value)


def drawdown_from_peak(values) -> float:
    """Largest fall from a running peak, as a fraction of that peak. Yu counts those over 20%."""
    v = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(v)
    return float(np.max((peak - v) / peak)) if len(v) else 0.0


# --------------------------------------------------------------------------------------
# Part 11. Run the book and report it
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BondPanel:
    """One bond's daily data, every array one row per trading day. [ADAPTATION]

    clean is NaN on a day with no price. tradable carries the Part 1 screens. The last three
    arrays are optional (None): use them if you have a sibling bond, CDS, options or event dates.
    """
    coupon: float
    freq: int
    years_left: np.ndarray
    clean: np.ndarray
    S: np.ndarray
    D: np.ndarray
    sigma_s: np.ndarray
    dividend: np.ndarray
    zero_tenors: tuple
    zeros: np.ndarray
    r_5y: np.ndarray
    repo: np.ndarray
    bond_fee: np.ndarray
    stock_fee: np.ndarray
    cash_rate: np.ndarray
    hedge_repo: np.ndarray
    day_fraction: np.ndarray
    calendar_day: np.ndarray
    peer_gap: np.ndarray
    round_trip: np.ndarray
    tradable: np.ndarray
    sibling_gap: np.ndarray | None = None
    cds_market: np.ndarray | None = None
    implied_vol: np.ndarray | None = None
    forced_event: tuple | None = None


@dataclass(frozen=True)
class CdsPanel:
    """One obligor's daily CDS data, for replicating Yu. Every array one row per trading day."""
    c: np.ndarray
    S: np.ndarray
    D: np.ndarray
    sigma_s: np.ndarray
    r: np.ndarray
    dividend: np.ndarray
    day_fraction: np.ndarray
    calendar_day: np.ndarray


@dataclass(frozen=True)
class BacktestConfig:
    """Settings for a run. Defaults are the bond method. Yu's own are noted."""
    alpha: float = 0.5               # Yu tests 0.5, 1, 2
    capital: float = 0.5             # Yu: 0.5 per 1 of notional
    max_hold: float = 180.0          # calendar days. Yu: 30 or 180 days
    lag: int = 1                     # Yu: 0
    R_b: float = YU_RECOVERY
    lam: float = YU_LAMBDA
    calibration_days: int = 20       # Yu: 10
    overlapping: bool = False        # Yu: True
    hold: str = "asset_vol"
    space: str = "spread"            # or "vol"
    beta: float = 0.20
    peer_adjust: bool = True
    use_cost_gate: bool = True
    cost_multiple: float = 1.0
    stock_half: float = 0.0005
    hedge_half: float = 0.00005
    rehedge: bool = True
    max_drawdown: float | None = None
    bid_ask: float = 0.05            # CDS only


@dataclass
class TradeResult:
    """One closed trade. hpr is net P&L over capital. legs sums each P&L leg and each cost."""
    side: int
    signal_day: int
    entry_day: int
    exit_day: int
    reason: str
    face: float
    shares: float
    hedge_face: float
    hpr: float
    max_drawdown: float
    converged: bool
    legs: dict
    final_value: float
    daily_returns: dict


@dataclass
class BacktestResult:
    """Closed trades, the daily return matrix (days by trades, NaN when not live) and diagnostics."""
    trades: list
    daily_returns: np.ndarray
    z_market: np.ndarray
    z_model: np.ndarray
    L_bar: float
    fit_rmse: float
    status: str


@dataclass
class _LiveTrade:
    pos: Position
    hedge: Bond | None
    signal_day: int
    entry_day: int
    value: float
    last_reset: float
    legs: dict
    values: list
    daily_returns: dict
    reason: str | None = None
    exit_day: int | None = None


def _optional(values, i: int, missing=float("nan")):
    return missing if values is None else values[i]


def _empty_result(n: int, z_market, z_model, l_bar: float, rmse: float, status: str) -> BacktestResult:
    return BacktestResult([], np.empty((n, 0)), z_market, z_model, l_bar, rmse, status)


def _close_trade(trade: _LiveTrade, day: int, capital: float) -> TradeResult:
    return TradeResult(trade.pos.side, trade.signal_day, trade.entry_day, day, trade.reason,
                       trade.pos.face, trade.pos.shares, trade.pos.hedge_face,
                       (trade.value - capital) / capital, drawdown_from_peak(trade.values),
                       trade.reason == "convergence", trade.legs, trade.value, trade.daily_returns)


def _return_matrix(trades: list, n: int) -> np.ndarray:
    matrix = np.full((n, len(trades)), np.nan)
    for j, trade in enumerate(trades):
        for day, value in trade.daily_returns.items():
            matrix[day, j] = value
    return matrix


def run_bond_backtest(panel: BondPanel, config: BacktestConfig) -> BacktestResult:
    """The whole method on one bond. Yu's logic, with the bond steps in place of the CDS ones."""
    n = len(panel.S)
    bonds = [Bond(panel.coupon, float(panel.years_left[i]), panel.freq) for i in range(n)]
    curves = [ZeroCurve(panel.zero_tenors, tuple(panel.zeros[i])) for i in range(n)]
    filled = np.array(panel.clean, dtype=float)
    last_price = np.full(n, np.nan)
    for i in range(n):
        if np.isfinite(filled[i]):
            last_price[i] = panel.calendar_day[i]
        elif i > 0:
            filled[i], last_price[i] = filled[i - 1], last_price[i - 1]

    z_market = np.full(n, np.nan)
    for i in np.flatnonzero(np.isfinite(panel.clean)):
        z_market[i] = z_spread(full_price(panel.clean[i], bonds[i]), bonds[i], curves[i])
    z_model = np.full(n, np.nan)

    fit_days = [i for i in range(n) if np.isfinite(z_market[i]) and panel.tradable[i]][:config.calibration_days]
    if len(fit_days) < config.calibration_days:
        return _empty_result(n, z_market, z_model, float("nan"), float("nan"), "too_few_days")
    l_bar, rmse = fit_barrier_on_bond([bonds[i] for i in fit_days], panel.S[fit_days], panel.D[fit_days],
                                      panel.sigma_s[fit_days], z_market[fit_days], [curves[i] for i in fit_days],
                                      config.R_b, config.lam)
    status = fit_status(l_bar)
    firms = [Firm(float(panel.S[i]), float(panel.D[i]), float(panel.sigma_s[i]), l_bar, config.lam) for i in range(n)]
    z_model = np.array([model_z_spread(bonds[i], firms[i], curves[i], config.R_b) for i in range(n)])
    if status == "reject":
        return _empty_result(n, z_market, z_model, l_bar, rmse, status)

    def hedge_on(trade: _LiveTrade, i: int) -> Bond:
        aged = panel.years_left[trade.entry_day] - panel.years_left[i]
        return Bond(trade.hedge.coupon, float(trade.hedge.maturity - aged), trade.hedge.freq)

    def marks_on(trade: _LiveTrade, i: int, with_cash: bool) -> Marks:
        hedge_now = hedge_on(trade, i)
        cash = with_cash and i > trade.entry_day
        return Marks(float(filled[i]), accrued_interest(bonds[i]), float(panel.S[i]),
                     price_from_z(0.0, hedge_now, curves[i]),
                     coupons_paid(bonds[i - 1], bonds[i]) if cash else 0.0,
                     float(panel.dividend[i]) if cash else 0.0,
                     coupons_paid(hedge_on(trade, i - 1), hedge_now) if cash else 0.0)

    def half_cost(i: int) -> float:
        return stressed_cost(float(panel.round_trip[i]), config.cost_multiple) / 2

    def add(legs: dict, name: str, amount: float) -> None:
        legs[name] = legs.get(name, 0.0) + amount

    live, closed = [], []
    pending = {}
    for i in range(fit_days[-1] + 1, n):
        # 1. Mark every live trade to today's close and apply its exit rules.
        for trade in list(live):
            carry = Carry(float(panel.repo[i]), float(panel.bond_fee[i]), float(panel.stock_fee[i]),
                          float(panel.cash_rate[i]), float(panel.hedge_repo[i]), float(panel.day_fraction[i]))
            now = marks_on(trade, i, True)
            legs = daily_pnl(trade.pos, marks_on(trade, i - 1, False), now, carry)
            pnl = legs.pop("total")
            for name, amount in legs.items():
                add(trade.legs, name, amount)
            if config.rehedge:
                z_now = z_market[i] if np.isfinite(z_market[i]) else z_model[i]
                target = (rate_hedge_face(bonds[i], z_now, hedge_on(trade, i), curves[i]) * trade.pos.face)
                if rate_hedge_is_due(trade.pos.hedge_face, target, panel.calendar_day[i] - trade.last_reset):
                    cost = abs(target - trade.pos.hedge_face) * stressed_cost(config.hedge_half, config.cost_multiple)
                    add(trade.legs, "rehedge_cost", -cost)
                    pnl -= cost
                    trade.pos = replace(trade.pos, hedge_face=target)
                    trade.last_reset = panel.calendar_day[i]
            peak = max(trade.values)
            closing = trade.exit_day == i
            if trade.reason is None:
                trade.reason = bond_exit_reason(
                    trade.pos.side, z_market[i], z_model[i], panel.calendar_day[i] - panel.calendar_day[trade.entry_day],
                    config.max_hold, trade.value + pnl, float(panel.years_left[i]),
                    panel.calendar_day[i] - last_price[i], _optional(panel.forced_event, i, None),
                    config.max_drawdown, peak)
                if trade.reason is not None:
                    if trade.reason == "limited_liability" or config.lag == 0:
                        closing = True
                    else:
                        trade.exit_day = min(i + config.lag, n - 1)
                        closing = trade.exit_day == i
            if i == n - 1 and not closing:
                trade.reason = trade.reason or "end_of_sample"
                closing = True
            if closing:
                cost = trade_cost(trade.pos, now, half_cost(i), stressed_cost(config.stock_half, config.cost_multiple),
                                  stressed_cost(config.hedge_half, config.cost_multiple))
                add(trade.legs, "exit_cost", -cost)
                pnl -= cost
            trade.value, ret = next_account_value(trade.value, pnl)
            trade.values.append(trade.value)
            trade.daily_returns[i] = ret
            if closing:
                live.remove(trade)
                closed.append(_close_trade(trade, i, config.capital))

        # 2. Read today's signal. The trade happens on a later day.
        z_now, z_fit = z_market[i], z_model[i]
        busy = bool(live) or any(day >= i for day in pending)
        if np.isfinite(z_now) and (config.overlapping or not busy):
            gap = log_gap(z_now, z_fit)
            if config.space == "vol":
                inversion = implied_vol_bond(z_now, bonds[i], firms[i], curves[i], config.R_b)
                signal = (vol_entry_signal(inversion.sigma_s, firms[i].sigma_s, config.beta)
                          if vol_status_allows_trade(inversion) else 0)
            elif config.peer_adjust:
                signal = peer_adjusted_signal(gap, float(panel.peer_gap[i]), config.alpha)
            else:
                signal = entry_signal(z_now, z_fit, config.alpha)
            if signal != 0:
                duration = dollar_duration(bonds[i], z_now, curves[i])
                cds_market = float(_optional(panel.cds_market, i))
                cds_model = (cds_par_spread(5.0, firms[i], config.R_b, float(panel.r_5y[i]))
                             if np.isfinite(cds_market) else float("nan"))
                signal = decide_entry(
                    signal, bool(panel.tradable[i]), passes_barrier_filter(firms[i]),
                    sibling_confirms(gap, float(_optional(panel.sibling_gap, i))),
                    cds_confirms(signal, cds_market, cds_model, config.alpha),
                    not config.use_cost_gate or passes_cost_gate(z_now, z_fit, duration, stressed_cost(float(panel.round_trip[i]), config.cost_multiple)),
                    implied_vol_confirms(signal, z_now, bonds[i], firms[i], float(_optional(panel.implied_vol, i)), curves[i], config.R_b, config.alpha))
            if signal != 0 and execution_day(i, config.lag) < n:
                pending.setdefault(execution_day(i, config.lag), []).append((i, signal))

        # 3. Open what was signalled for today, at today's price.
        for signal_day, side in pending.pop(i, []):
            if not np.isfinite(z_market[i]):
                continue
            annuity = cds_annuity(5.0, firms[i], float(panel.r_5y[i]))
            face = cds_equivalent_face(bonds[i], z_market[i], curves[i], annuity)
            delta = bond_equity_delta(bonds[i], firms[i], curves[i], config.R_b, config.hold)
            hedge = par_hedge_bond(float(panel.years_left[i]), curves[i], panel.freq)
            ratio = rate_hedge_face(bonds[i], z_market[i], hedge, curves[i])
            pos = build_position(side, face, delta, ratio)
            trade = _LiveTrade(pos, hedge, signal_day, i, config.capital, float(panel.calendar_day[i]), {}, [], {})
            cost = trade_cost(pos, marks_on(trade, i, False), half_cost(i),
                              stressed_cost(config.stock_half, config.cost_multiple),
                              stressed_cost(config.hedge_half, config.cost_multiple))
            add(trade.legs, "entry_cost", -cost)
            trade.value = opening_account_value(config.capital, cost)
            trade.values.append(trade.value)
            trade.daily_returns[i] = -cost / config.capital
            live.append(trade)

    return BacktestResult(closed, _return_matrix(closed, n), z_market, z_model, l_bar, rmse, status)


def empirical_hedge_slope(bond_changes, stock_changes) -> tuple:
    """Regression slope of bond price changes on stock changes, and its standard error. [ADAPTATION]"""
    y, x = np.asarray(bond_changes, dtype=float), np.asarray(stock_changes, dtype=float)
    fit = factor_regression(y, x.reshape(-1, 1))
    return fit["betas"][0], fit["betas_se"][0]


def monthly_index(daily_returns: np.ndarray, month_ids: np.ndarray) -> np.ndarray:
    """Yu p. 26: equal-weight the live trades each day, then compound by month.

    daily_returns has one row per day and one column per trade, NaN when a trade is not live.
    A month with no live trade has zero excess return (Yu p. 27).
    """
    with np.errstate(all="ignore"):
        live = np.isfinite(daily_returns).any(axis=1)
    daily = np.zeros(len(daily_returns))
    daily[live] = np.nanmean(daily_returns[live], axis=1)
    months = np.unique(month_ids)
    return np.array([np.prod(1 + daily[month_ids == m]) - 1 for m in months])


def annual_sharpe(monthly_excess: np.ndarray) -> float:
    """Annualised Sharpe of monthly excess returns. Matches Yu Tables 4 and 7."""
    return float(np.sqrt(12) * np.mean(monthly_excess) / np.std(monthly_excess, ddof=1))


def trade_summary(trades: list) -> dict:
    """Yu Tables 2 and 3: N, converged, drawdown over 20%, negative, and mean, min, max return."""
    hpr = np.array([t.hpr for t in trades], dtype=float)
    return {"N": len(trades),
            "N1": sum(t.converged for t in trades),
            "N2": sum(t.max_drawdown > 0.20 for t in trades),
            "N3": int(np.sum(hpr < 0)),
            "mean": float(np.mean(hpr)) if len(hpr) else float("nan"),
            "min": float(np.min(hpr)) if len(hpr) else float("nan"),
            "max": float(np.max(hpr)) if len(hpr) else float("nan")}


def monthly_summary(monthly: np.ndarray) -> dict:
    """Yu Table 4. N counts non-zero months. Median and share negative use every month.

    Yu's Spec row with alpha 2 (N = 25, Neg = 0.29, median 0) fits only that reading: 14/48.
    """
    m = np.asarray(monthly, dtype=float)
    return {"N": int(np.sum(m != 0)), "mean": float(np.mean(m)), "median": float(np.median(m)),
            "min": float(np.min(m)), "max": float(np.max(m)), "std": float(np.std(m, ddof=1)),
            "corr": float(np.corrcoef(m[:-1], m[1:])[0, 1]), "neg": float(np.mean(m < 0)),
            "sharpe": annual_sharpe(m)}


def summaries_by_group(trades: list, labels: list) -> dict:
    """trade_summary per group, such as side or rating at entry. [ADAPTATION]"""
    return {g: trade_summary([t for t, x in zip(trades, labels) if x == g]) for g in dict.fromkeys(labels)}


def factor_regression(monthly, factors) -> dict:
    """Yu Table 6: least squares of monthly returns on factor returns, with standard errors."""
    y = np.asarray(monthly, dtype=float)
    x = np.column_stack([np.ones(len(y)), np.asarray(factors, dtype=float)])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    covariance = residual @ residual / (len(y) - x.shape[1]) * np.linalg.inv(x.T @ x)
    se = np.sqrt(np.diag(covariance))
    total = np.sum((y - y.mean()) ** 2)
    return {"intercept": float(beta[0]), "intercept_se": float(se[0]), "betas": beta[1:], "betas_se": se[1:],
            "r2": float(1 - residual @ residual / total)}


# --------------------------------------------------------------------------------------
# Part 12. Check it is right before trusting any backtest
# --------------------------------------------------------------------------------------

# CreditGrades Table C.1, printed p. 49: L = 0.5, lam = 0.3, R = 0.5, r = 5%, 5-year.
CG_TABLE_C1_RATIOS = (0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6)
CG_TABLE_C1_VOLS = (20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80)
CG_TABLE_C1 = np.array("""
55 85 125 175 232 297 367 441 520 602 687 774 865
8 22 46 82 130 188 253 326 403 486 572 662 755
2 8 22 48 85 134 193 260 333 412 495 583 675
1 3 12 30 59 101 153 214 283 358 438 523 612
0 2 7 20 43 78 124 180 244 315 392 474 561
0 1 4 13 32 62 103 154 214 282 355 434 518
0 0 3 9 24 50 86 133 190 254 325 401 483
0 0 2 7 19 41 73 117 169 230 298 373 452
0 0 1 5 15 34 63 103 152 211 276 348 425
0 0 1 4 12 28 55 91 138 194 257 326 401
0 0 1 3 10 24 48 82 126 179 240 307 381
0 0 0 2 8 20 42 74 115 166 224 290 362
""".split(), dtype=float).reshape(12, 13)

# Yu Table 2, printed p. 20. (capital, days, alpha): N, N1, N2, N3, mean %, min %, max %.
YU_TABLE_2 = {
    (0.1, 30, 0.5): (550, 0, 104, 260, 0.10, -104.56, 94.24),
    (0.1, 30, 1.0): (319, 0, 53, 142, 2.46, -44.66, 94.24),
    (0.1, 30, 2.0): (154, 0, 14, 56, 2.22, -20.08, 18.04),
    (0.1, 180, 0.5): (550, 76, 235, 140, 20.20, -104.56, 113.37),
    (0.1, 180, 1.0): (319, 8, 96, 61, 24.68, -25.10, 113.37),
    (0.1, 180, 2.0): (154, 0, 25, 19, 18.03, -2.68, 43.46),
    (0.5, 30, 0.5): (550, 0, 1, 252, 0.14, -10.68, 18.92),
    (0.5, 30, 1.0): (319, 0, 0, 138, 0.58, -8.87, 18.92),
    (0.5, 30, 2.0): (154, 0, 0, 54, 0.55, -3.91, 3.75),
    (0.5, 180, 0.5): (550, 76, 1, 134, 4.50, -4.63, 23.06),
    (0.5, 180, 1.0): (319, 8, 0, 60, 5.37, -4.52, 23.06),
    (0.5, 180, 2.0): (154, 0, 0, 18, 4.04, -5.32, 9.30),
}


def check_table_c1() -> dict:
    """Reproduce CreditGrades Table C.1 with and without the Act/360 scaling. [CREDITGRADES]"""
    def grid(act360: bool) -> np.ndarray:
        return np.array([[cds_par_spread(5, Firm(x, 1.0, v / 100, 0.5, 0.3), 0.5, 0.05, act360) * 1e4
                          for v in CG_TABLE_C1_VOLS] for x in CG_TABLE_C1_RATIOS])

    ours = grid(True)
    return {"cells_matching": int((np.round(ours) == CG_TABLE_C1).sum()),
            "largest_gap_bp": float(np.abs(ours - CG_TABLE_C1).max()),
            "largest_gap_unscaled_bp": float(np.abs(grid(False) - CG_TABLE_C1).max()),
            "grid_bp": ours}


def check_worldcom(r: float = 0.05) -> dict:
    """Reproduce CreditGrades p. 36: S = 13, 14, D = 9, asset vol 40%. [CREDITGRADES]

    The document does not state R, r, L or lam here. Assumed: its standard L = 0.5, lam = 0.3, R = 0.5.
    """
    def firm(s: float) -> Firm:
        return Firm(s, 9.0, 0.40 * 17.5 / 13, 0.5, 0.3, S_ref=13.0)

    def score(s: float, act360: bool) -> float:
        return cds_par_spread(5, firm(s), 0.5, r, act360) * 1e4

    annuity = cds_annuity(5, firm(13), r)
    tighter = score(13, False) - score(14, False)
    unpinned = Firm(13.0, 9.0, 0.40 * 17.5 / 13, 0.5, 0.3)
    return {"score_13_bp": score(13, True), "score_14_bp": score(14, True), "tightening_bp": tighter,
            "annuity": annuity, "hedge_ratio": 1 / (tighter * 1e-4 * annuity * 13),
            "local_hedge_ratio": 1 / (-cds_equity_delta(5, firm(13), 0.5, r, "asset_vol") * 13),
            "equity_vol_hedge_ratio": 1 / (-cds_equity_delta(5, unpinned, 0.5, r, "equity_vol") * 13)}


def check_identities(firm: Firm, R: float, r: float, T: float) -> dict:
    """Closed forms against integrals, and the bond and CDS links in Part 4. [ADAPTATION]"""
    s = 0.5 * T * (_GL_X + 1)
    integral = 0.5 * T * np.sum(_GL_W * np.exp(-r * s) * survival(s, firm))
    annuity = cds_annuity(T, firm, r)
    protection = 1 - survival(0.0, firm) + discounted_default(T, firm, r)
    c = cds_par_spread(T, firm, R, r)
    coupon = r + c + 0.01
    price = coupon * annuity + np.exp(-r * T) * survival(T, firm) + R * protection
    curve = flat_curve(r)
    par_coupon = brentq(lambda x: risky_bond_price(Bond(x, T, 365), firm, curve, R) - 1.0, 0.0, 1.0, xtol=1e-12)
    bond_delta = bond_equity_delta(Bond(par_coupon, T, 365), firm, curve, R)
    return {"annuity_gap": abs(annuity - integral),
            "price_identity_gap": abs(price - (1 + (coupon - r - c) * annuity)),
            "par_delta_gap": abs(bond_delta / -cds_equity_delta(T, firm, R, r) - 1),
            "par_z_minus_cds_bp": (z_spread(1.0, Bond(par_coupon, T, 365), curve) - c) * 1e4}


def cds_equity_delta(T: float, firm: Firm, R: float, r: float, hold: str = "asset_vol") -> float:
    """Yu Eqs. (7) and (15), corrected: annuity * dc/dS, per 1 of notional.

    Negative for long protection. Long protection buys -delta shares. Short protection shorts
    -delta shares.
    """
    h = 0.01 * firm.S
    up = cds_par_spread(T, _bumped(firm, firm.S + h, hold), R, r)
    down = cds_par_spread(T, _bumped(firm, firm.S - h, hold), R, r)
    return cds_annuity(T, firm, r) * (up - down) / (2 * h)


def cds_contract_value(c_now: float, c_entry: float, T: float, firm: Firm, r: float) -> float:
    """Value of long protection entered at c_entry. Yu Eq. (6) and corrected Eq. (14)."""
    return (c_now - c_entry) * cds_annuity(T, firm, r)


def run_cds_backtest(panel: CdsPanel, config: BacktestConfig, T: float = 5.0) -> BacktestResult:
    """Yu's own trade on CDS, to test your code against his tables.

    Use Yu's settings: calibration_days=10, overlapping=True, lag=0. side +1 sells protection and
    shorts stock. side -1 buys protection and buys stock. My readings where Yu is silent: entry at
    the bid or ask, daily marks at the side you would exit on, no interest on the margin account.
    """
    n = len(panel.c)
    fit = list(range(config.calibration_days))
    l_bar, rmse = fit_barrier_on_cds(panel.c[fit], panel.S[fit], panel.D[fit], panel.sigma_s[fit], panel.r[fit],
                                     T, config.R_b, config.lam)
    firms = [Firm(float(panel.S[i]), float(panel.D[i]), float(panel.sigma_s[i]), l_bar, config.lam) for i in range(n)]
    c_model = np.array([cds_par_spread(T, firms[i], config.R_b, float(panel.r[i])) for i in range(n)])
    half = config.bid_ask / 2
    live, closed = [], []

    def contract(trade: _LiveTrade, i: int) -> float:
        side = trade.pos.side
        mark = panel.c[i] * (1 + side * half)
        return -side * cds_contract_value(mark, trade.legs["_c_entry"], T, firms[i], float(panel.r[i]))

    for i in range(config.calibration_days, n):
        for trade in list(live):
            side = trade.pos.side
            premium = side * trade.legs["_c_entry"] * float(panel.day_fraction[i])
            stock = -side * trade.pos.shares * float(panel.S[i] - panel.S[i - 1] + panel.dividend[i])
            value_change = contract(trade, i) - trade.legs["_contract"]
            trade.legs["_contract"] += value_change
            for name, amount in (("cds_value", value_change), ("cds_premium", premium), ("stock_price", stock)):
                trade.legs[name] = trade.legs.get(name, 0.0) + amount
            pnl = value_change + premium + stock
            days_held = panel.calendar_day[i] - panel.calendar_day[trade.entry_day]
            reason = exit_reason(side, panel.c[i], c_model[i], days_held, config.max_hold, trade.value + pnl)
            if i == n - 1 and reason is None:
                reason = "end_of_sample"
            trade.value, ret = next_account_value(trade.value, pnl)
            trade.values.append(trade.value)
            trade.daily_returns[i] = ret
            if reason is not None:
                trade.reason = reason
                live.remove(trade)
                for key in ("_c_entry", "_contract"):
                    trade.legs.pop(key)
                closed.append(_close_trade(trade, i, config.capital))
        side = entry_signal(float(panel.c[i]), float(c_model[i]), config.alpha)
        if side != 0 and (config.overlapping or not live) and i < n - 1:
            shares = -cds_equity_delta(T, firms[i], config.R_b, float(panel.r[i]), config.hold)
            trade = _LiveTrade(Position(side, 1.0, shares, 0.0), None, i, i, config.capital, 0.0,
                               {"_c_entry": float(panel.c[i]) * (1 - side * half)}, [config.capital], {})
            trade.legs["_contract"] = contract(trade, i)
            trade.value = config.capital + trade.legs["_contract"]
            trade.legs["cds_value"] = trade.legs["_contract"]
            trade.daily_returns[i] = trade.legs["_contract"] / config.capital
            trade.values.append(trade.value)
            live.append(trade)
    return BacktestResult(closed, _return_matrix(closed, n), panel.c, c_model, l_bar, rmse, fit_status(l_bar))


def check_cds_replication(summary: dict, capital: float, days: int, alpha: float) -> dict:
    """Your trade_summary against Yu's Table 2, as yours minus his. Means are in percent. [PAPER]"""
    target = YU_TABLE_2[(capital, days, float(alpha))]
    return {"N": summary["N"] - target[0], "N1": summary["N1"] - target[1], "N2": summary["N2"] - target[2],
            "N3": summary["N3"] - target[3], "mean": summary["mean"] * 100 - target[4],
            "min": summary["min"] * 100 - target[5], "max": summary["max"] * 100 - target[6]}


def synthetic_bond_panel(n_days: int = 90, S: float = 30.0, D: float = 28.0, sigma_s: float = 0.38,
                         coupon: float = 0.055, years_left: float = 4.8, L_bar: float = 0.8,
                         R_b: float = YU_RECOVERY, lam: float = YU_LAMBDA, zero_rate: float = 0.04) -> BondPanel:
    """A made-up bond priced exactly on its model, with flat stock and rates, for the checks. [ADAPTATION]"""
    one = np.ones(n_days)
    panel = BondPanel(coupon=coupon, freq=2, years_left=years_left - np.arange(n_days) / 360.0, clean=one * 0.0,
                      S=one * S, D=one * D, sigma_s=one * sigma_s, dividend=one * 0.0,
                      zero_tenors=(0.0, 100.0), zeros=np.column_stack([one * zero_rate, one * zero_rate]),
                      r_5y=one * zero_rate, repo=one * 0.042, bond_fee=one * 0.004, stock_fee=one * 0.003,
                      cash_rate=one * 0.041, hedge_repo=one * 0.041, day_fraction=one / 360.0,
                      calendar_day=np.arange(n_days, dtype=float), peer_gap=one * 0.0, round_trip=one * 0.01,
                      tradable=np.ones(n_days, dtype=bool))
    return panel_with_no_gap(panel, L_bar, R_b, lam)


def panel_with_no_gap(panel: BondPanel, L_bar: float, R_b: float, lam: float) -> BondPanel:
    """The same panel, with each clean price set to its model price. [ADAPTATION]"""
    clean = np.zeros(len(panel.S))
    for i in range(len(clean)):
        bond = Bond(panel.coupon, float(panel.years_left[i]), panel.freq)
        curve = ZeroCurve(panel.zero_tenors, tuple(panel.zeros[i]))
        firm = Firm(float(panel.S[i]), float(panel.D[i]), float(panel.sigma_s[i]), L_bar, lam)
        clean[i] = risky_bond_price(bond, firm, curve, R_b) - accrued_interest(bond)
    return replace(panel, clean=clean)


def inject_gap(panel: BondPanel, L_bar: float, start_day: int, gap: float, close_days: float, R_b: float,
               lam: float) -> BondPanel:
    """Add a spread gap from start_day that shrinks in a line and just crosses zero. [ADAPTATION]"""
    clean = np.array(panel.clean, dtype=float)
    for i in range(start_day, len(clean)):
        elapsed = panel.calendar_day[i] - panel.calendar_day[start_day]
        shrunk = gap * (1 - elapsed / close_days)
        now = max(shrunk, -0.0001) if gap > 0 else min(shrunk, 0.0001)
        bond = Bond(panel.coupon, float(panel.years_left[i]), panel.freq)
        curve = ZeroCurve(panel.zero_tenors, tuple(panel.zeros[i]))
        firm = Firm(float(panel.S[i]), float(panel.D[i]), float(panel.sigma_s[i]), L_bar, lam)
        z = model_z_spread(bond, firm, curve, R_b) + now
        clean[i] = price_from_z(z, bond, curve) - accrued_interest(bond)
    return replace(panel, clean=clean)


def check_no_signal_without_gap(panel: BondPanel, config: BacktestConfig) -> int:
    """Number of trades when the market equals the model every day. Expect 0. [ADAPTATION]"""
    return len(run_bond_backtest(panel, config).trades)


def check_legs_add_up(result: BacktestResult, capital: float) -> float:
    """Largest gap between the sum of a trade's legs and costs and its change in value. [ADAPTATION]"""
    gaps = [abs(sum(t.legs.values()) - (t.final_value - capital)) for t in result.trades]
    return float(max(gaps)) if gaps else 0.0


def check_known_gap_profit(panel: BondPanel, result: BacktestResult) -> float:
    """Largest gap between each trade's bond price leg and its full-price change, worked out apart. [ADAPTATION]

    Adds up the bond and stock P&L from end prices, not day by day.
    """
    worst = 0.0
    for t in result.trades:
        a, b = t.entry_day, t.exit_day
        filled = np.array(panel.clean, dtype=float)
        for i in range(1, len(filled)):
            if not np.isfinite(filled[i]):
                filled[i] = filled[i - 1]
        start = Bond(panel.coupon, float(panel.years_left[a]), panel.freq)
        end = Bond(panel.coupon, float(panel.years_left[b]), panel.freq)
        bond = t.side * t.face * (filled[b] + accrued_interest(end) + coupons_paid(start, end)
                                  - filled[a] - accrued_interest(start))
        stock = -t.side * t.shares * (panel.S[b] - panel.S[a] + panel.dividend[a + 1:b + 1].sum())
        worst = max(worst, abs(bond - t.legs["bond_price"]), abs(stock - t.legs["stock_price"]))
    return float(worst)


def truncate_panel(panel: BondPanel, n_days: int) -> BondPanel:
    """The panel as it looked on day n_days - 1. [ADAPTATION]"""
    cut = {}
    for name, value in vars(panel).items():
        cut[name] = value[:n_days] if isinstance(value, np.ndarray) else value
    return BondPanel(**cut)


def check_no_lookahead(panel: BondPanel, config: BacktestConfig, cut_day: int) -> float:
    """Largest change in any daily return before cut_day when later data is removed. Expect 0. [ADAPTATION]"""
    full = run_bond_backtest(panel, config)
    short = run_bond_backtest(truncate_panel(panel, cut_day + 1), config)
    safe = cut_day - config.lag - 1
    worst = 0.0
    by_entry = {(t.signal_day, t.side): t for t in full.trades}
    for t in short.trades:
        other = by_entry.get((t.signal_day, t.side))
        if other is None:
            if t.entry_day < safe:
                return float("inf")
            continue
        for day, value in t.daily_returns.items():
            if day < safe:
                worst = max(worst, abs(value - other.daily_returns[day]))
    return float(worst)


def lag_sensitivity(panel: BondPanel, config: BacktestConfig, lags=(0, 1, 2, 5)) -> dict:
    """Mean trade return at each execution lag. A collapse from 0 to 1 means bounce, not edge. [ADAPTATION]"""
    return {lag: trade_summary(run_bond_backtest(panel, replace(config, lag=lag)).trades)["mean"] for lag in lags}


def placebo_panel(panel: BondPanel, other: BondPanel) -> BondPanel:
    """This bond against another issuer's stock. The debt-equity link should then earn nothing. [ADAPTATION]"""
    return replace(panel, S=other.S, D=other.D, sigma_s=other.sigma_s, dividend=other.dividend)


def attribute_pnl(trades: list) -> dict:
    """Total P&L by leg, with financing and costs apart. Spots a bond-only strategy. [ADAPTATION]"""
    totals = {}
    for t in trades:
        for name, amount in t.legs.items():
            totals[name] = totals.get(name, 0.0) + amount
    totals["net"] = sum(totals.values())
    return totals


def shape_against_yu(short_hold: dict, long_hold: dict, low_alpha: dict, high_alpha: dict) -> dict:
    """The patterns in Yu's Tables 2 and 3, from four trade_summary results. [PAPER]"""
    return {"more_convergence_with_longer_hold": long_hold["N1"] / long_hold["N"] >= short_hold["N1"] / short_hold["N"],
            "fewer_losers_with_longer_hold": long_hold["N3"] / long_hold["N"] <= short_hold["N3"] / short_hold["N"],
            "tighter_with_higher_trigger": high_alpha["max"] - high_alpha["min"] <= low_alpha["max"] - low_alpha["min"]}


def break_even_cost(panel: BondPanel, config: BacktestConfig, multiples=(0.0, 1.0, 2.0, 3.0)) -> dict:
    """Mean trade return at each cost multiple, and the multiple where it reaches zero. [ADAPTATION]"""
    means = [trade_summary(run_bond_backtest(panel, replace(config, cost_multiple=x, use_cost_gate=False)).trades)["mean"]
             for x in multiples]
    level = float("nan")
    for i in range(len(multiples) - 1):
        if means[i] > 0 >= means[i + 1]:
            level = multiples[i] + (multiples[i + 1] - multiples[i]) * means[i] / (means[i] - means[i + 1])
            break
    return {"multiples": tuple(multiples), "mean_returns": means, "break_even_multiple": level}
