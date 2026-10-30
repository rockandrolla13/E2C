"""E2C capital structure arbitrage: reference implementation of the user's own 2005 models.

Each public function is one step of 05_io_spec.md, with the same name. A step takes plain numbers,
arrays or a DataFrame. It returns an array when it has one output, and a dict of named arrays when it
has several. run_pipeline(inputs, params) runs all the steps in order.

The formulas come from these workbooks, cited in each docstring:

  MASTER    04_raw_data/12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls
  SAMPLE    03_backtests/SampleE2CBackTest.xls
  CG12      02_excel_models/E2C_CG1.2_RiskAnalysis.xls, VBA module ClosedForm
  TEMPLATE  04_raw_data/Template 27th Nov2005.xls

Units follow the workbooks:
  spreads in bp in the pipeline, decimals in the closed form,
  vols in percent points in the pipeline, decimals in the closed form,
  sizes and deltas in $M, P&L in $ thousands (the workbook headers say "$m", which is wrong).

The only credit input is the 5-year CDS mid. No workbook prices a bond.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import log_ndtr, ndtr
from scipy.stats import norm

NEWTON_START = 0.5     # VBA ICG_RefVol: x0 = 0.5
NEWTON_STEP = 0.01     # VBA ICG_RefVol: forward difference of 0.01 in vol
NEWTON_STOP = 0.0001   # VBA ICG_RefVol: Abs(y0 - Spread) < 0.0001, which is 1 bp of spread
NEWTON_MAX_STEPS = 200 # Not in the VBA, which loops until it stops

REALISED = ["vol_30d", "vol_60d", "vol_90d", "vol_180d", "vol_360d"]
PUTS = ["put_3m", "put_6m", "put_12m", "put_24m"]
VOL_MIXES = {
    "master": REALISED + PUTS,                 # MASTER E2C Data!AE2 =AVERAGE(R2:Z2)
    "cg12": ["vol_162w", "vol_360d"] + PUTS,   # CG12 Prototype!M2 =AVERAGE(D2:I2). Also SAMPLE and TEMPLATE
    "realised": REALISED,                      # MASTER Evol-comp column His-No162W
}
RAW_INPUTS = ["date", "ticker", "st_debt", "lt_debt", "other_st_liab", "other_lt_liab", "minority_int", "pfd_equity",
              "mkt_cap", "price", "spread_bp", "swap_5y_pct"]
NEXT_WEEK = ["next_date", "next_spread_bp", "next_price"]
PNL_LINES = ["pnl_cds_long", "pnl_cds_short", "pnl_hedge_long", "pnl_hedge_short",
             "carry_long", "carry_short", "funding", "rebate"]


@dataclass(frozen=True)
class Params:
    """Fixed parameters. Defaults are MASTER. Each comment gives the cell that holds the value."""
    tenor: float = 5.0                 # No MASTER cell. CG12 Control&Report!D4. Confirmed by the 19,489-row match
    barrier_recovery: float = 0.5      # L. MASTER E2C Data!AF2, hard-coded
    barrier_vol: float = 0.3           # lambda. No MASTER cell. CG12 Control&Report!D6. Confirmed by the match
    recovery: float = 0.4              # R. MASTER Reg!H6
    vol_mix: str = "master"
    pit_weight: float = 0.95           # Reg!U6 PITp
    ttc_skew: float = 0.0              # Reg!W6 skew
    ttc_coeff: float = 1.0             # Reg!X6 coeff
    blend: str = "levels"              # MASTER blends fair vols. SAMPLE and TEMPLATE blend exponents
    ref_trigger: float = 30.0          # Reg!O6 RefTrig, the x30 scale. 0 means residual in raw vol points
    long_trigger: float = 6.0          # Reg!P6 LgTrig
    short_trigger: float = 6.0         # Reg!Q6 ShTrig
    spread_floor: float = 0.0          # Reg!K6 SpFl, bp
    spread_cap: float = 10000.0        # Reg!L6 SpCp, bp
    target_vega_points: float = 3.0    # Reg!T6 target
    target_trade_pnl: float = 0.2      # Reg!S6 TaTrd, $M
    trade_limit: float = 10.0          # Reg!R6 limsize, $M
    long_hedge: float = 1.0            # Reg!AL6 LgH
    short_hedge: float = 1.0           # Reg!AM6 ShH
    funding_spread: float = 0.005      # E2C Data!BN2: rate + 0.5%
    rebate_spread: float = 0.005       # E2C Data!BO2: rate - 0.5%
    swap_funding_bug: bool = False     # True reproduces SAMPLE!BN2, BO2, where the two legs are swapped
    flat_rate: float | None = None     # None uses each date's swap. SAMPLE and TEMPLATE use 0.045
    flat_rate_greeks: float | None = None  # SAMPLE uses 0.05 for annuity, delta and vega
    # Name stress, Reg!BG5:BJ6: (credit P&L per $ notional long, equity move)
    stress_zero: tuple = (-1.0, -1.0)
    stress_lbo: tuple = (-0.25, 0.4)
    stress_merger: tuple = (0.25, 0.2)
    stress_natio: tuple = (0.25, -0.4)
    # Book stress, Reg!BL5:BN6: (relative spread move, equity move)
    stress_oct87: tuple = (0.15, -0.22)
    stress_ltcm: tuple = (0.5, -0.1)
    stress_apr03: tuple = (-0.25, 0.07)
    # Risk, Reg!BQ5, BU5, BY5, BY6, BZ6, CD6, CG6, CH6, DH4
    beta_credit: float = 0.5
    beta_equity: float = 0.5
    beta_market: float = 0.5
    beta_e2c: float = 0.68
    var_confidence: float = 0.99
    margin_confidence: float = 0.9985
    ec_confidence: float = 0.999
    target_vol: float = 0.10
    bid_offer: float = 0.05


MASTER_PARAMS = Params()
# SAMPLE settings: Reg!Q6:W6, formulas AN2, BN2, BO2. Greeks at r = 5%, implied vol at r = 4.5%.
SAMPLE_PARAMS = Params(vol_mix="cg12", ttc_skew=0.28, blend="exponents", ref_trigger=0.0, long_trigger=5.0,
                       short_trigger=5.0, swap_funding_bug=True, flat_rate=0.045, flat_rate_greeks=0.05)
# TEMPLATE settings: Sheet8!CP2:CW2, Q2. Tested step by step only, since the file holds no panel for a full run.
# Its Risky_DV01 is the annuity at r = 5%, while its Delta and Vega use 4.5%.
PRODUCTION_PARAMS = Params(vol_mix="cg12", ttc_skew=0.28, blend="exponents", ref_trigger=0.0, long_trigger=5.0,
                           short_trigger=5.0, flat_rate=0.045)


# ------------------------------------------------------------------------------------------------
# Closed form building blocks. CG12 VBA module ClosedForm.
# ------------------------------------------------------------------------------------------------

def _b(d, a):
    """VBA B(d, a)."""
    ln_d = np.log(d)
    return ndtr(ln_d / a - a / 2) - d * ndtr(-ln_d / a - a / 2)


def _g(d, a, z):
    """VBA G(d, a, z). Written in logs so that very low vols do not overflow. Same value."""
    ln_d = np.log(d)
    return np.exp((z + 0.5) * ln_d + log_ndtr(-ln_d / a - z * a)) + np.exp((0.5 - z) * ln_d + log_ndtr(-ln_d / a + z * a))


def _terms(T, S, D, asset_vol, L, lam, r):
    """The terms BT, B0, HT that the VBA functions CG, Ann360, CLeg and CDS all compute."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        d = (1 + S / L / D) * np.exp(lam ** 2)
        a = np.sqrt(asset_vol ** 2 * T + lam ** 2)
        z = np.sqrt(0.25 + 2 * r / asset_vol ** 2)
        bt = _b(d, a)
        b0 = _b(d, lam)
        ht = np.exp(r * (lam / asset_vol) ** 2) * (_g(d, a, z) - _g(d, lam, z))
    return bt, b0, ht


def reference_asset_vol(ref_vol, ref_price, D, L):
    """VBA: Avol = RefVol*RefS/(RefS + LBar*DPS). If RefS = 0, RefVol is already an asset vol."""
    return np.where(np.asarray(ref_price) == 0, ref_vol, ref_vol * np.asarray(ref_price) / (np.asarray(ref_price) + L * D))


# ------------------------------------------------------------------------------------------------
# Steps
# ------------------------------------------------------------------------------------------------

def next_week_values(inputs: pd.DataFrame) -> pd.DataFrame:
    """S00. Each name's next row: next_date, next_spread_bp, next_price. Equals MASTER E2C Data!BD:BF."""
    t = inputs.sort_values(["ticker", "date"])
    g = t.groupby("ticker")
    out = pd.DataFrame({"next_date": g["date"].shift(-1), "next_spread_bp": g["spread_bp"].shift(-1),
                        "next_price": g["price"].shift(-1)})
    return out.reindex(inputs.index)


def debt_per_share(st_debt, lt_debt, other_st_liab, other_lt_liab, minority_int, mkt_cap, pfd_equity, price):
    """S01. Debt per share, $. CreditGrades Appendix B, and MASTER E2C Data!K (pasted). Blanks count as 0."""
    fin = (np.nan_to_num(st_debt) + np.nan_to_num(lt_debt)
           + 0.5 * (np.nan_to_num(other_st_liab) + np.nan_to_num(other_lt_liab)))
    minority = np.minimum(np.nan_to_num(minority_int), 0.5 * fin)
    preferred = np.minimum(np.nan_to_num(pfd_equity), 0.5 * np.asarray(mkt_cap))
    return (fin - minority) / ((np.asarray(mkt_cap) + preferred) / np.asarray(price))


def average_equity_vol(inputs: pd.DataFrame, mix: str = "master"):
    """S02. Equity vol, percent: the plain mean of whichever vols exist. MASTER E2C Data!AE2."""
    return inputs[VOL_MIXES[mix]].mean(axis=1).to_numpy()


def historical_asset_vol(equity_vol, price, dps, L=0.5):
    """S03. Asset vol, same unit as equity_vol. MASTER E2C Data!AF2 =AE2*J2/(J2+0.5*K2)."""
    return np.asarray(equity_vol) * np.asarray(price) / (np.asarray(price) + L * np.asarray(dps))


def survival_probability(T, S, D, asset_vol, L=0.5, lam=0.3):
    """S04. Probability of no default by T, decimal. VBA E2C()."""
    d = (1 + S / L / D) * np.exp(lam ** 2)
    return _b(d, np.sqrt(asset_vol ** 2 * T + lam ** 2))


def model_spread(T, S, D, asset_vol, L=0.5, lam=0.3, R=0.4, r=0.045):
    """S05. Par CDS spread, decimal, Act/360. VBA CG()."""
    bt, b0, ht = _terms(T, S, D, asset_vol, L, lam, r)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (360 / 365) * (1 - R) * (1 - b0 + ht) / ((b0 - bt * np.exp(-r * T) - ht) / r)


def risky_annuity(T, S, D, asset_vol, L=0.5, lam=0.3, r=0.045):
    """S05. Risky annuity per 1 of fee, Act/360. VBA Ann360()."""
    bt, b0, ht = _terms(T, S, D, asset_vol, L, lam, r)
    return (365 / 360) * (b0 - bt * np.exp(-r * T) - ht) / r


def contingent_leg(T, S, D, asset_vol, L=0.5, lam=0.3, R=0.4, r=0.045):
    """S05. Protection leg value per 1 of notional. VBA CLeg()."""
    _, b0, ht = _terms(T, S, D, asset_vol, L, lam, r)
    return (1 - R) * (1 - b0 + ht)


def cds_value(T, fee, S, D, asset_vol, L=0.5, lam=0.3, R=0.4, r=0.045):
    """S05. Value to the protection buyer per 1 of notional. VBA CDS(). fee is decimal."""
    bt, b0, ht = _terms(T, S, D, asset_vol, L, lam, r)
    return (1 - R) * (1 - b0 + ht) - fee * (365 / 360) * (b0 - bt * np.exp(-r * T) - ht) / r


def implied_asset_vol(spread, T, S, D, L=0.5, lam=0.3, R=0.4, r=0.045, method="vba"):
    """S06. Asset vol, decimal, that gives this par spread (decimal). VBA ICG_RefVol with RefS = 0.

    method="vba" copies the VBA loop: start 0.5, forward step 0.01, stop within 1 bp of spread. It reproduces
    pasted vols. method="exact" finds the root. No solution gives nan, which is what GM, Ford and
    Temple-Inland do in MASTER sheet Removed.
    """
    spread, S, D, r = np.broadcast_arrays(*(np.asarray(v, float) for v in (spread, S, D, r)))
    result = np.full(spread.shape, np.nan)
    if method == "exact":
        for i in np.ndindex(spread.shape):
            f = lambda v: model_spread(T, S[i], D[i], v, L, lam, R, r[i]) - spread[i]
            try:
                result[i] = brentq(f, 0.015, 5.0, xtol=1e-10)
            except ValueError:
                pass
        return result if result.ndim else float(result)
    x = np.full(spread.shape, NEWTON_START)
    active = np.ones(spread.shape, bool)
    for _ in range(NEWTON_MAX_STEPS):
        y = model_spread(T, S, D, x, L, lam, R, r)
        done = active & (np.abs(y - spread) < NEWTON_STOP)
        result = np.where(done, np.abs(x), result)
        active = active & ~done & np.isfinite(y)
        if not active.any():
            break
        with np.errstate(divide="ignore", invalid="ignore"):
            slope = (model_spread(T, S, D, x + NEWTON_STEP, L, lam, R, r) - y) / NEWTON_STEP
            x = np.where(active, x - (y - spread) / slope, x)
    return result if result.ndim else float(result)


def implied_other(kind, spread, T, S, D, ref_vol, ref_price, L, lam, R, r):
    """S06b. CG12 sheet Implied: solve for one other input by the same Newton loop. One number at a time.

    kind: "refvol" (VBA ICG_RefVol with RefS not 0), "dps" (ICG_DPS), "rr" (ICG_RR), "spot" (ICG_Spot),
    "lbar" (ICG_LBar), "lrec" (ICG_LRec). The backtest does not use this. These are real workbook outputs.
    """
    def spread_at(x):
        vv = x if kind == "refvol" else ref_vol
        dd = x if kind == "dps" else D
        ss = x if kind == "spot" else S
        ll = x if kind in ("lbar", "lrec") else L
        rr = x if kind in ("rr", "lrec") else R
        return model_spread(T, ss, dd, reference_asset_vol(vv, ref_price, dd, ll), ll, lam, rr, r)

    x = {"refvol": NEWTON_START, "dps": S, "rr": 0.5, "spot": D, "lbar": 0.5, "lrec": 0.5}[kind]
    for _ in range(NEWTON_MAX_STEPS):
        y = spread_at(x)
        if abs(y - spread) < NEWTON_STOP:
            return float(x)
        x = x - (y - spread) / ((spread_at(x + NEWTON_STEP) - y) / NEWTON_STEP)
    return float("nan")


def leverage_regression(ln_imp_hist, ln_s_over_d) -> dict:
    """S07. OLS across all names on one date. MASTER Reg!V10, W10, X10, Y10.

    ln(Imp/Hist) = ln(coeff) + skew * ln(S/D). k is the S/D where implied equals historical.
    """
    y, x = np.asarray(ln_imp_hist, float), np.asarray(ln_s_over_d, float)
    correl = np.corrcoef(y, x)[0, 1]
    skew = correl * y.std(ddof=1) / x.std(ddof=1)
    coeff = np.exp(y.mean() - skew * x.mean())
    return dict(skew=skew, coeff=coeff, k=1 / coeff ** (1 / skew), correl=correl, r2=correl ** 2, n=len(y))


def fair_asset_vol(avg_asset_vol, s_over_d, skew_pit, coeff_pit, params: Params = MASTER_PARAMS):
    """S08. Fair implied asset vol, same unit as avg_asset_vol. MASTER E2C Data!AN2.

    blend="levels": AF*(PITp*AM*AI^AL + (1-PITp)*coeff*AI^skew). MASTER.
    blend="exponents": AF*(PITp*AM+(1-PITp)*coeff)*AI^(PITp*AL+(1-PITp)*skew). SAMPLE and TEMPLATE.
    """
    p, c, s = params.pit_weight, params.ttc_coeff, params.ttc_skew
    if params.blend == "exponents":
        return avg_asset_vol * (p * coeff_pit + (1 - p) * c) * s_over_d ** (p * skew_pit + (1 - p) * s)
    return avg_asset_vol * (p * coeff_pit * s_over_d ** skew_pit + (1 - p) * c * s_over_d ** s)


def vol_residual(implied, fair, ref_trigger=30.0):
    """S09. MASTER E2C Data!AO2 =IF(RefTrig=0,AG2-AN2,LN(AG2/AN2)*RefTrig). Raw vol points or scaled log gap."""
    return implied - fair if ref_trigger == 0 else np.log(implied / fair) * ref_trigger


def sector_adjusted_residual(residual, sector):
    """S10. Residual minus its sector mean on one date. Production, early 2006. ranked by residual.xls.

    Optional. MASTER does not use it, so run_pipeline leaves it out.
    """
    r = pd.Series(np.asarray(residual, float))
    return (r - r.groupby(np.asarray(sector)).transform("mean")).to_numpy()


def trade_signal(residual, spread_bp, params: Params = MASTER_PARAMS) -> dict:
    """S11. MASTER E2C Data!AP2, AQ2. long_flag: sell protection, short stock. short_flag: the reverse."""
    residual, spread_bp = np.asarray(residual, float), np.asarray(spread_bp, float)
    ok = (params.spread_floor <= spread_bp) & (spread_bp <= params.spread_cap)
    return dict(long_flag=((residual > params.long_trigger) & ok) * 1,
                short_flag=((residual < -params.short_trigger) & ok) * 1)


def cds_greeks(T, S, D, asset_vol, spread_bp, L=0.5, lam=0.3, R=0.4, r=0.045) -> dict:
    """S12. CDS struck at the market spread. Pasted in MASTER E2C Data!AR, AS, AT, AV.

    annuity: Ann360. delta: equity $ per $1 of notional, positive, the hedge ratio. vega: value change for
    +1 vol point. rho: value change for +100 bp. theta: value change when T falls by 1/12 year.
    TEMPLATE shows Vega and Theta from the long-credit side, so its signs are the opposite.
    """
    fee = np.asarray(spread_bp, float) / 1e4
    base = cds_value(T, fee, S, D, asset_vol, L, lam, R, r)
    return dict(annuity=risky_annuity(T, S, D, asset_vol, L, lam, r),
                delta=-(cds_value(T, fee, S + 0.01, D, asset_vol, L, lam, R, r) - base) * 100 * S,
                vega=cds_value(T, fee, S, D, asset_vol + 0.01, L, lam, R, r) - base,
                rho=cds_value(T, fee, S, D, asset_vol, L, lam, R, r + 0.01) - base,
                theta=cds_value(T - 1 / 12, fee, S, D, asset_vol, L, lam, R, r) - base)


def trade_size(long_flag, short_flag, vega, implied, params: Params = MASTER_PARAMS) -> dict:
    """S13. MASTER E2C Data!AW2, AX2, AY2. Notional in $M, so target_vega_points earns target_trade_pnl."""
    long_flag, short_flag = np.asarray(long_flag), np.asarray(short_flag)
    scale = 1.0 if params.ref_trigger == 0 else np.asarray(implied, float) / params.ref_trigger
    target = (long_flag + short_flag) * np.asarray(vega, float) * params.target_vega_points * scale
    with np.errstate(divide="ignore", invalid="ignore"):
        size = np.minimum(params.trade_limit, params.target_trade_pnl / np.abs(target))
    return dict(target=target, size_long=np.where(long_flag == 1, size, 0.0), size_short=np.where(short_flag == 1, size, 0.0))


def equity_hedge(size_long, size_short, delta, price) -> dict:
    """S14. MASTER E2C Data!AZ2, BA2, in $M. Shares: TEMPLATE NUMBER_OF_SHARES, negative means short stock."""
    delta_long, delta_short = np.asarray(size_long) * delta, np.asarray(size_short) * delta
    return dict(delta_long=delta_long, delta_short=delta_short, hedge_shares=(delta_short - delta_long) * 1e6 / price)


def weekly_pnl(size_long, size_short, delta_long, delta_short, spread_bp, next_spread_bp, price, next_price,
               annuity, days, rate_pct, params: Params = MASTER_PARAMS) -> dict:
    """S15. One name, one week, $ thousands. MASTER E2C Data!BG2:BJ2, BL2:BO2. A blank next value earns 0."""
    next_spread_bp, next_price = np.asarray(next_spread_bp, float), np.asarray(next_price, float)
    spread_bp, price = np.asarray(spread_bp, float), np.asarray(price, float)
    d_spread = np.where(np.isnan(next_spread_bp), 0.0, next_spread_bp - spread_bp)
    ret = np.where(np.isnan(next_price), 0.0, next_price / price - 1)
    r = np.asarray(rate_pct, float) / 100
    hedge_l, hedge_s = delta_long * params.long_hedge, delta_short * params.short_hedge
    funded, rebated = (hedge_l, hedge_s) if params.swap_funding_bug else (hedge_s, hedge_l)
    return dict(pnl_cds_long=-size_long * d_spread * annuity / 10,
                pnl_cds_short=size_short * d_spread * annuity / 10,
                pnl_hedge_long=-hedge_l * ret * 1000,
                pnl_hedge_short=hedge_s * ret * 1000,
                carry_long=size_long * (spread_bp / 10) * days / 360,
                carry_short=-size_short * (spread_bp / 10) * days / 360,
                funding=-funded * (r + params.funding_spread) * days / 360 * 1000,
                rebate=rebated * (r - params.rebate_spread) * days / 360 * 1000)


def stress_tests(size_long, size_short, delta_long, delta_short, stress10_long, stress10_short,
                 params: Params = MASTER_PARAMS) -> dict:
    """S16. MASTER E2C Data!BQ2:BT2 (name shocks), BV2:BX2 (book shocks). All $M."""
    net_size = size_long - size_short
    net_delta = delta_long * params.long_hedge - delta_short * params.short_hedge
    net_st = stress10_long - stress10_short
    out = {}
    for name in ("zero", "lbo", "merger", "natio"):
        credit, equity = getattr(params, f"stress_{name}")
        out[name] = credit * net_size - equity * net_delta
    for name in ("oct87", "ltcm", "apr03"):
        spread, equity = getattr(params, f"stress_{name}")
        out[name] = -spread * net_st / 100 - equity * net_delta
    return out


def name_risk(implied, equity_vol, avg_asset_vol, delta, annuity, spread_bp, size_long, stress10_long,
              stress10_short, delta_long, delta_short, params: Params = MASTER_PARAMS) -> dict:
    """S17. MASTER E2C Data!AU2, BZ2, CA2, CB2, CC2. Spread vol in percent. The others in $M."""
    spread_vol = implied * (equity_vol / avg_asset_vol) * (delta / annuity) / (spread_bp / 1e4)
    margin = np.maximum(0.05, 3.5 * spread_bp / 1e4) * size_long
    credit_1sd = 10 * (spread_vol / 100) * (stress10_long - stress10_short) / 1000
    equity_1sd = (equity_vol / 100) * (-delta_long * params.long_hedge + delta_short * params.short_hedge)
    return dict(spread_vol=spread_vol, margin=margin, credit_1sd=credit_1sd, equity_1sd=equity_1sd,
                net_1sd=credit_1sd + equity_1sd)


def closed_trade_flag(pnl, residual, long_flag, vega, size_long, size_short, target, params: Params = MASTER_PARAMS):
    """S18. MASTER E2C Data!CK2. 1 if a live trade's week P&L beat its target, a proxy for a closed trade."""
    pnl, residual, long_flag = np.asarray(pnl, float), np.asarray(residual, float), np.asarray(long_flag)
    size = np.asarray(size_long) + np.asarray(size_short)
    trig = np.where(long_flag == 1, params.long_trigger, params.short_trigger)
    hurdle = np.minimum(np.minimum(1000 * (np.abs(residual) - trig) * np.asarray(vega) * size,
                                   1000 * params.target_trade_pnl), 1000 * np.asarray(target) * size)
    with np.errstate(invalid="ignore"):
        return (pnl > hurdle) * 1


def book_capital(week: pd.DataFrame, params: Params = MASTER_PARAMS) -> pd.DataFrame:
    """S19. VaR, margin, economic capital, NAV by date. MASTER Reg!BP:BZ, CC:CI. Inputs in $M."""
    root252 = np.sqrt(252)
    z_var, z_margin, z_ec = (norm.ppf(c) for c in (params.var_confidence, params.margin_confidence, params.ec_confidence))
    out = pd.DataFrame(index=week.index)
    credit_s, credit_i = week.credit_sum / root252, week.credit_rss / root252
    equity_s, equity_i = week.equity_sum / root252, week.equity_rss / root252
    net_s, net_i = week.net_sum / root252, week.net_rss / root252
    bc, be, bm, b2 = params.beta_credit, params.beta_equity, params.beta_market, params.beta_e2c
    out["var_credit"] = np.sqrt((bc * credit_s) ** 2 + (1 - bc ** 2) * credit_i ** 2) * z_var
    out["var_equity"] = np.sqrt((be * equity_s) ** 2 + (1 - be ** 2) * equity_i ** 2) * z_var
    out["var_total"] = np.sqrt((bm * net_s) ** 2 + (b2 ** 2 - bm ** 2) * net_i ** 2
                               + (1 - b2 ** 2) * (credit_i ** 2 + equity_i ** 2)) * z_var
    out["margin_equity"] = out.var_equity * (z_margin / z_var) * np.sqrt(5)
    out["margin_total"] = week.margin_credit + out.margin_equity
    out["economic_capital"] = np.maximum.reduce([out.var_total * (z_ec / z_var) * root252,
                                                 -3 * week[["oct87", "ltcm", "apr03"]].min(axis=1),
                                                 -week[["zero", "lbo", "merger", "natio"]].min(axis=1)])
    out["nav"] = out.economic_capital / z_ec / params.target_vol
    out["margin_pct_nav"] = np.where(out.nav > 0, out.margin_total / out.nav.where(out.nav > 0), 0.0)
    return out


def weekly_return(total_pnl, nav) -> dict:
    """S20. MASTER Reg!CK10 =IF(CH10>0,BA10/CH10/1000,0) and CM10 =CM9*(1+CK10). Decimal return, NAV index."""
    total_pnl, nav = np.asarray(total_pnl, float), np.asarray(nav, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.where(nav > 0, total_pnl / nav / 1000, 0.0)
    return dict(alpha=alpha, nav_index=np.cumprod(1 + alpha))


def bid_offer_cost(closed_share, stress10_sum, bid_offer=0.05):
    """S21. MASTER Reg!DH10 =$DH$4*DF10*(AN10+AO10)/0.1, $ thousands. The total P&L does not subtract it."""
    return bid_offer * np.asarray(closed_share) * np.asarray(stress10_sum) / 0.1


def performance_summary(alpha) -> dict:
    """S22. MASTER Reg!CK6 =CK8/CK7, CK7 =STDEV*SQRT(52), CK8 =AVERAGE*52, CM6:CM8. Weekly decimal returns in.

    t_stat and max_drawdown are my additions. The workbook does not compute them.
    """
    a = np.asarray(alpha, float)
    nav = np.cumprod(1 + a)
    return dict(sharpe=a.mean() * 52 / (a.std(ddof=1) * np.sqrt(52)), mean_annual=a.mean() * 52,
                vol_annual=a.std(ddof=1) * np.sqrt(52), nav_end=nav[-1], nav_min=nav.min(), nav_max=nav.max(),
                t_stat=a.mean() / a.std(ddof=1) * np.sqrt(len(a)),
                max_drawdown=(nav / np.maximum.accumulate(nav) - 1).min(), weeks=len(a))


def reval_trade(implied_pct, residual, spread_bp, S, D, trigger=5.0, reval=3.0, L=0.5, lam=0.3, R=0.4, r=0.045, T=5.0) -> dict:
    """S23. Older sizing, CG12 Prototype!W2:AC2, AL2. MASTER does not use it. One number at a time.

    Move vol by reval points toward fair, then find the theoretical spread and contract value.
    Size is 1/value, capped at 100, so the expected gain is 1.
    """
    flag = -1 if residual < -trigger else (1 if residual > trigger else 0)
    vol = (implied_pct - flag * reval) / 100
    value = -flag * cds_value(T, spread_bp / 1e4, S, D, vol, L, lam, R, r)
    return dict(flag=flag, vol_reval=vol, theo_spread_bp=float(model_spread(T, S, D, vol, L, lam, R, r)) * 1e4,
                theo_value=float(value), size=min(1 / float(value), 100) if flag != 0 else 0.0)


# ------------------------------------------------------------------------------------------------
# The whole pipeline
# ------------------------------------------------------------------------------------------------

def run_pipeline(inputs: pd.DataFrame, params: Params = MASTER_PARAMS) -> dict:
    """Raw inputs in, named outputs out. Column names are in 05_io_spec.md, Table 1.

    Returns a dict:
      names:    one row per name and week, every per-name output
      weeks:    one row per date, every weekly output
      summary:  performance_summary of the weekly returns
      unsolved: input rows with no implied vol, dropped before the regression

    If next_date, next_spread_bp or next_price are absent, S00 derives them from the table.
    """
    p = params
    missing = [c for c in RAW_INPUTS + VOL_MIXES[p.vol_mix] if c not in inputs.columns]
    if missing:
        raise ValueError(f"inputs lack columns: {missing}")
    x = inputs.copy()
    if not set(NEXT_WEEK) <= set(x.columns):
        x[NEXT_WEEK] = next_week_values(x)
    x["date"], x["next_date"] = pd.to_datetime(x["date"]), pd.to_datetime(x["next_date"])

    # S01 to S06
    x["dps"] = debt_per_share(x.st_debt, x.lt_debt, x.other_st_liab, x.other_lt_liab, x.minority_int, x.mkt_cap, x.pfd_equity, x.price)
    rate_pct = x.swap_5y_pct.to_numpy(float) if p.flat_rate is None else np.full(len(x), p.flat_rate * 100)
    rate_greeks = rate_pct / 100 if p.flat_rate_greeks is None else np.full(len(x), p.flat_rate_greeks)
    x["implied"] = implied_asset_vol(x.spread_bp.to_numpy(float) / 1e4, p.tenor, x.price.to_numpy(float), x.dps.to_numpy(float),
                                     p.barrier_recovery, p.barrier_vol, p.recovery, rate_pct / 100) * 100
    keep = x.implied.notna().to_numpy()
    unsolved = x[~keep]
    x, rate_pct, rate_greeks = x[keep].copy(), rate_pct[keep], rate_greeks[keep]
    x["avg_equity_vol"] = average_equity_vol(x, p.vol_mix)
    x["avg_asset_vol"] = historical_asset_vol(x.avg_equity_vol, x.price, x.dps, p.barrier_recovery)

    # S12, at the implied vol
    greeks = cds_greeks(p.tenor, x.price.to_numpy(float), x.dps.to_numpy(float), x.implied.to_numpy() / 100, x.spread_bp.to_numpy(float),
                        p.barrier_recovery, p.barrier_vol, p.recovery, rate_greeks)
    for k in ("annuity", "delta", "vega", "rho"):
        x[k] = greeks[k]

    # S07 to S09, one regression per date
    x["s_over_d"] = x.price / x.dps
    x["ln_imp_hist"], x["ln_s_over_d"] = np.log(x.implied / x.avg_asset_vol), np.log(x.s_over_d)
    fits = pd.DataFrame({d: leverage_regression(g.ln_imp_hist, g.ln_s_over_d) for d, g in x.groupby("date")}).T
    x["skew_pit"], x["coeff_pit"] = x.date.map(fits["skew"]), x.date.map(fits["coeff"])
    x["fair_vol"] = fair_asset_vol(x.avg_asset_vol, x.s_over_d, x.skew_pit, x.coeff_pit, p)
    x["residual"] = vol_residual(x.implied, x.fair_vol, p.ref_trigger)

    # S11, S13, S14, S15
    signal = trade_signal(x.residual, x.spread_bp, p)
    x["long_flag"], x["short_flag"] = signal["long_flag"], signal["short_flag"]
    size = trade_size(x.long_flag, x.short_flag, x.vega, x.implied, p)
    x["target"], x["size_long"], x["size_short"] = size["target"], size["size_long"], size["size_short"]
    hedge = equity_hedge(x.size_long.to_numpy(), x.size_short.to_numpy(), x.delta.to_numpy(), x.price.to_numpy(float))
    x["delta_long"], x["delta_short"], x["hedge_shares"] = hedge["delta_long"], hedge["delta_short"], hedge["hedge_shares"]
    x["stress10_long"] = x.size_long * x.annuity * x.spread_bp / 100   # E2C Data!BB2
    x["stress10_short"] = x.size_short * x.annuity * x.spread_bp / 100  # E2C Data!BC2
    x["days"] = (x.next_date - x.date).dt.days.fillna(0).astype(float)
    pnl = weekly_pnl(x.size_long.to_numpy(), x.size_short.to_numpy(), x.delta_long.to_numpy(), x.delta_short.to_numpy(), x.spread_bp,
                     x.next_spread_bp, x.price, x.next_price, x.annuity.to_numpy(), x.days.to_numpy(), rate_pct, p)
    for k, v in pnl.items():
        x[k] = v
    live = (x.carry_long.abs() + x.carry_short.abs()) > 0
    x["pnl_total"] = np.where(live, x[PNL_LINES].sum(axis=1), np.nan)   # E2C Data!CG2

    # S16, S17, S18
    for k, v in stress_tests(x.size_long, x.size_short, x.delta_long, x.delta_short, x.stress10_long, x.stress10_short, p).items():
        x[k] = v
    for k, v in name_risk(x.implied, x.avg_equity_vol, x.avg_asset_vol, x.delta, x.annuity, x.spread_bp, x.size_long,
                          x.stress10_long, x.stress10_short, x.delta_long, x.delta_short, p).items():
        x[k] = v
    x["close_flag"] = closed_trade_flag(x.pnl_total, x.residual, x.long_flag, x.vega, x.size_long, x.size_short, x.target, p)
    x["rho_usd"] = -(x.size_long - x.size_short) * x.rho * 1000         # E2C Data!CI2

    # Weekly sums, Reg sheet
    g = x.groupby("date")
    w = g.agg(n=("price", "size"), n_long=("long_flag", "sum"), n_short=("short_flag", "sum"),
              size_long=("size_long", "sum"), size_short=("size_short", "sum"),
              delta_long=("delta_long", "sum"), delta_short=("delta_short", "sum"),
              stress10_long=("stress10_long", "sum"), stress10_short=("stress10_short", "sum"),
              zero=("zero", "min"), lbo=("lbo", "min"), merger=("merger", "min"), natio=("natio", "min"),
              oct87=("oct87", "sum"), ltcm=("ltcm", "sum"), apr03=("apr03", "sum"),
              margin_credit=("margin", "sum"), closed=("close_flag", "sum"), rho_usd=("rho_usd", "sum"),
              credit_sum=("credit_1sd", "sum"), equity_sum=("equity_1sd", "sum"), net_sum=("net_1sd", "sum"),
              **{k: (k, "sum") for k in PNL_LINES})
    for name, col in (("credit_rss", "credit_1sd"), ("equity_rss", "equity_1sd"), ("net_rss", "net_1sd")):
        w[name] = g[col].apply(lambda s: np.sqrt((s ** 2).sum()))
    w = w.join(fits.drop(columns="n").astype(float))
    w["pnl_total"] = w[PNL_LINES].sum(axis=1)
    w["pnl_cum"] = w.pnl_total.cumsum()
    w["pnl_credit"] = w.pnl_cds_long + w.pnl_cds_short + w.carry_long + w.carry_short
    w["pnl_equity"] = w.pnl_hedge_long + w.pnl_hedge_short + w.funding + w.rebate

    # S19 to S22
    w = w.join(book_capital(w, p))
    ret = weekly_return(w.pnl_total, w.nav)
    w["alpha"], w["nav_index"] = ret["alpha"], ret["nav_index"]
    trades = w.n_long + w.n_short
    w["closed_share"] = (w.closed / trades.where(trades > 0)).fillna(0.0)
    w["bid_offer_cost"] = bid_offer_cost(w.closed_share, w.stress10_long + w.stress10_short, p.bid_offer)
    return dict(names=x, weeks=w, summary=performance_summary(w.alpha), unsolved=unsolved)
