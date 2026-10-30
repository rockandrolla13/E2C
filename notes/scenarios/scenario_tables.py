"""Scenario tables for the three least-certain choices in the bond method.

Inputs:  notes/paper_method/e2c_bond.py and worked_example.py (made-up base issuer and bond)
         notes/own_models/e2c_model.py and master_panel.csv.gz (real weekly CDS, 2002-09 to 2005-09)
Outputs: one CSV per table in tables/, plus tables/summary.json.

Run: python3 scenario_tables.py

Tables tagged BOND use made-up inputs. They show how the method responds, not what happens in markets.
Tables tagged REAL CDS use the real panel, but it is CDS, not bonds.
"""
import contextlib
import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "paper_method"), str(HERE.parent / "own_models")]
import e2c_bond as m  # noqa: E402
import e2c_model as w  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import worked_example as ex  # noqa: E402

OUT = HERE / "tables"
ALPHA = 0.5
FACE = 10e6
BP = 1e-4


def archetypes() -> dict:
    """Three made-up issuers on the same bond and barrier. Only the stock price and vol differ."""
    base = ex.f0
    return {"low spread": replace(base, S=base.S * 2.0, sigma_s=0.28),
            "base": base,
            "high spread": replace(base, S=base.S * 0.5, sigma_s=0.55)}


def signal_word(side: int) -> str:
    return {1: "long bond", -1: "short bond", 0: "no trade"}[int(side)]


# ------------------------------------------------------------------- Choice 1: illiquidity or mispricing

CASES = [  # name, true mispricing, market-wide premium, this-bond premium, sibling premium (all bp)
    ("Nothing happening", 0, 0, 0, 0),
    ("True mispricing, 100 bp", 100, 0, 0, 0),
    ("True mispricing, 200 bp", 200, 0, 0, 0),
    ("True richness, 60 bp", -60, 0, 0, 0),
    ("Market-wide stress, 100 bp", 0, 100, 0, 0),
    ("Market-wide stress, 200 bp", 0, 200, 0, 0),
    ("This bond illiquid, 100 bp", 0, 0, 100, 0),
    ("This bond illiquid, 200 bp", 0, 0, 200, 0),
    ("Whole issuer illiquid, 100 bp", 0, 0, 100, 100),
    ("Whole issuer illiquid, 200 bp", 0, 0, 200, 200),
    ("Mispricing 150 in stress 100", 150, 100, 0, 0),
    ("Mispricing 150 in stress 200", 150, 200, 0, 0),
    ("Mispricing 150 and bond illiquid 100", 150, 0, 100, 0),
]


def classify(z, mis, common, own, sib, alpha=ALPHA) -> dict:
    """Run each control on one case. All spreads and premia in decimals."""
    market, sibling, peers = z + mis + common + own, z + mis + common + sib, z + common
    gap = m.log_gap(market, z)
    sib_gap, peer_gap = m.log_gap(sibling, z), m.log_gap(peers, z)
    raw = m.entry_signal(market, z, alpha)
    peer = m.peer_adjusted_signal(gap, peer_gap, alpha)
    sib_ok = bool(m.sibling_confirms(gap, sib_gap))
    return dict(gap=gap, sib_gap=sib_gap, peer_gap=peer_gap, raw=raw, peer=peer, sib_ok=sib_ok,
                sibling_only=raw if sib_ok else 0, both=peer if sib_ok else 0,
                truth=m.entry_signal(z + mis, z, alpha))


def table_1a() -> pd.DataFrame:
    rows = []
    for arch, firm in archetypes().items():
        z = m.model_z_spread(ex.BOND0, firm, ex.CURVE, ex.R_B)
        for name, mis, common, own, sib in CASES:
            c = classify(z, mis * BP, common * BP, own * BP, sib * BP)
            rows.append(dict(issuer=arch, model_z_bp=z / BP, case=name, should_trade=signal_word(c["truth"]),
                             yu_raw=signal_word(c["raw"]), peer_only=signal_word(c["peer"]),
                             sibling_only=signal_word(c["sibling_only"]), both=signal_word(c["both"]),
                             both_correct=c["both"] == c["truth"], yu_correct=c["raw"] == c["truth"]))
    return pd.DataFrame(rows)


def table_1b(draws=400, seed=11) -> pd.DataFrame:
    """Error rates over an equal-weight grid of cases with spread measurement noise. The grid is my choice."""
    rng = np.random.default_rng(seed)
    z = m.model_z_spread(ex.BOND0, ex.f0, ex.CURVE, ex.R_B)
    rows = []
    for noise in (0, 10, 25, 50):
        tally = {k: dict(tp=0, fn=0, fp=0, tn=0) for k in ("raw", "peer", "sibling_only", "both", "both_sibling_on_adjusted")}
        for mis in (-100, -60, 0, 0, 0, 100, 150, 200):
            for common in (0, 50, 100, 200):
                for own, sib in ((0, 0), (100, 0), (200, 0), (100, 100), (200, 200)):
                    for _ in range(1 if noise == 0 else draws):
                        e = rng.normal(0, noise, 3) * BP
                        s = [max(x, 1 * BP) for x in (z + mis * BP + common * BP + own * BP + e[0],
                                                      z + mis * BP + common * BP + sib * BP + e[1],
                                                      z + common * BP + e[2])]
                        gap, sib_gap, peer_gap = (m.log_gap(x, z) for x in s)
                        truth = m.entry_signal(z + mis * BP, z, ALPHA)
                        raw = m.entry_signal(s[0], z, ALPHA)
                        peer = m.peer_adjusted_signal(gap, peer_gap, ALPHA)
                        ok = bool(m.sibling_confirms(gap, sib_gap))
                        ok_adj = bool(m.sibling_confirms(gap - peer_gap, sib_gap - peer_gap))
                        for k, v in dict(raw=raw, peer=peer, sibling_only=raw if ok else 0, both=peer if ok else 0,
                                         both_sibling_on_adjusted=peer if ok_adj else 0).items():
                            t = tally[k]
                            if truth != 0:
                                t["tp" if v == truth else "fn"] += 1
                            else:
                                t["fp" if v != 0 else "tn"] += 1
        for k, t in tally.items():
            rows.append(dict(noise_bp=noise, control=k, true_mispricing_caught=t["tp"] / (t["tp"] + t["fn"]),
                             false_trade_rate=t["fp"] / (t["fp"] + t["tn"])))
    return pd.DataFrame(rows)


def table_1b2() -> pd.DataFrame:
    """No noise, no true mispricing: which cases still trade under each control, by premium type and stress."""
    z = m.model_z_spread(ex.BOND0, ex.f0, ex.CURVE, ex.R_B)
    rows = []
    for common in (0, 50, 100, 200):
        for own, sib, label in ((100, 0, "this bond only, 100"), (200, 0, "this bond only, 200"),
                                (100, 100, "whole issuer, 100"), (200, 200, "whole issuer, 200")):
            s_ = [z + (common + own) * BP, z + (common + sib) * BP, z + common * BP]
            gap, sib_gap, peer_gap = (m.log_gap(x, z) for x in s_)
            peer = m.peer_adjusted_signal(gap, peer_gap, ALPHA)
            rows.append(dict(market_premium_bp=common, premium_type=label, yu_raw=signal_word(m.entry_signal(s_[0], z, ALPHA)),
                             both_as_coded=signal_word(peer if m.sibling_confirms(gap, sib_gap) else 0),
                             both_sibling_on_adjusted=signal_word(peer if m.sibling_confirms(gap - peer_gap, sib_gap - peer_gap) else 0)))
    return pd.DataFrame(rows)


def table_1c() -> pd.DataFrame:
    """What the trade earns if the gap closes at different speeds. A premium that never closes is illiquidity."""
    base = m.synthetic_bond_panel(n_days=260, L_bar=0.8)
    cfg = m.BacktestConfig(calibration_days=20, peer_adjust=False, use_cost_gate=False, alpha=ALPHA)
    z0 = m.model_z_spread(m.Bond(base.coupon, float(base.years_left[30])),
                          m.Firm(30.0, 28.0, 0.38, 0.8), m.flat_curve(0.04), m.YU_RECOVERY)
    rows = []
    for gap_bp in (150, 300):
        for days, label in ((30, "closes in 30 days"), (60, "closes in 60 days"), (120, "closes in 120 days"),
                            (1e7, "never closes"), (-180, "doubles over 180 days")):
            panel = m.inject_gap(base, 0.8, 30, gap_bp * BP, days, m.YU_RECOVERY, m.YU_LAMBDA)
            res = m.run_bond_backtest(panel, cfg)
            for mult, tag in ((1.0, "1x cost"), (3.0, "3x cost")):
                r = m.run_bond_backtest(panel, replace(cfg, cost_multiple=mult)).trades
                if not r:
                    continue
                t = r[0]
                rows.append(dict(gap_bp=gap_bp, model_z_bp=z0 / BP, path=label, cost=tag,
                                 exit=t.reason, days_held=t.exit_day - t.entry_day,
                                 return_on_capital=t.hpr, trades=len(r),
                                 pnl_per_10mm_usd=t.hpr * cfg.capital * FACE / t.face if t.face else np.nan))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- Real CDS panel, shared set-up

def load_panel() -> pd.DataFrame:
    d = pd.read_csv(HERE.parent / "own_models" / "master_panel.csv.gz", parse_dates=["date", "next_date"])
    d = d.sort_values(["ticker", "date"]).reset_index(drop=True)
    d["r"] = d.swap_5y_pct / 100
    d["c"] = d.spread_bp * BP
    d["next_c"] = d.next_spread_bp * BP
    d["ret"] = d.next_price / d.price - 1
    d["iv"] = d.wb_implied / 100
    d["bucket"] = pd.cut(d.spread_bp, [0, 100, 300, 1e9], labels=["under 100 bp", "100 to 300 bp", "over 300 bp"])
    return d


def fit_lbar(g: pd.DataFrame, premium=0.0, R=m.YU_RECOVERY, lam=m.YU_LAMBDA, grid=None) -> float:
    """Yu's fit on the first ten weekly spreads, with asset vol from equity vol at each trial L."""
    grid = np.geomspace(*m.BARRIER_BOUNDS, 240) if grid is None else grid
    s, d_, v, r, c = (g[x].to_numpy()[:10] for x in ("price", "wb_dps", "eqv", "r", "c"))
    best, err = grid[0], np.inf
    for L in grid:
        av = v * s / (s + L * d_)
        e = np.nansum((w.model_spread(5.0, s, d_, av, L, lam, R, r) - (c + premium)) ** 2)
        if np.isfinite(e) and e < err:
            best, err = L, e
    return float(best)


def equity_vol_delta(d: pd.DataFrame) -> np.ndarray:
    """Workbook delta formula, but asset vol moves with S so that equity vol stays fixed."""
    h = 0.01
    L, R = 0.5, 0.4
    S, D, r = d.price.to_numpy(), d.wb_dps.to_numpy(), d.r.to_numpy()
    sa = d.iv.to_numpy()
    se = sa * (S + L * D) / S
    fee = d.c.to_numpy()
    up = w.cds_value(5.0, fee, S + h, D, se * (S + h) / (S + h + L * D), L, 0.3, R, r)
    now = w.cds_value(5.0, fee, S, D, sa, L, 0.3, R, r)
    return -(up - now) * 100 * S


def nw_t(x: np.ndarray, lags: int) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 5:
        return float("nan")
    u = x - x.mean()
    var = np.sum(u * u) / len(u)
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * np.sum(u[k:] * u[:-k]) / len(u)
    return float(x.mean() / np.sqrt(var / len(u)))


# ------------------------------------------------------------------- Choice 1 on real CDS

def table_1d(d: pd.DataFrame, horizon=13) -> pd.DataFrame:
    """Does removing the sector median improve trades? Real CDS, no costs, overlapping 13-week holds."""
    d = d.copy()
    d["eqv"] = w.average_equity_vol(d) / 100
    rows = []
    for t, g in d.groupby("ticker"):
        if len(g) < 10 + horizon:
            continue
        L = fit_lbar(g)
        g = g.iloc[10:].copy()
        av = g.eqv * g.price / (g.price + L * g.wb_dps)
        g["model"] = w.model_spread(5.0, g.price.to_numpy(), g.wb_dps.to_numpy(), av.to_numpy(), L, 0.3, 0.5, g.r.to_numpy())
        g["gap"] = np.log(g.c / g.model)
        g["c_h"] = g.c.shift(-horizon)
        g["p_h"] = g.price.shift(-horizon)
        rows.append(g)
    p = pd.concat(rows).dropna(subset=["gap", "c_h", "p_h", "wb_annuity", "wb_delta"])
    p = p[np.isfinite(p.gap)].copy()
    p["peer"] = p.groupby(["date", "sector"]).gap.transform("median")
    p["adj"] = p.gap - p.peer
    p["market"] = p.groupby("date").gap.transform("median")
    th = np.log(1 + ALPHA)
    p["raw_side"] = np.select([p.gap > th, p.gap < -th], [1, -1], 0)
    p["adj_side"] = np.select([p.adj > th, p.adj < -th], [1, -1], 0)
    # +1: market spread too wide, so sell protection and short stock. Per 1 of notional, no costs.
    base = -p.wb_annuity * (p.c_h - p.c) + p.c * horizon / 52 - p.wb_delta * (p.p_h / p.price - 1)
    p["unit_pnl"] = base
    stress = p.market >= p.drop_duplicates("date").market.quantile(0.75)

    p["wb_side"] = np.select([p.wb_long.fillna(0) > 0, p.wb_short.fillna(0) > 0], [1, -1], 0)

    def row(name, mask, side):
        x = p[mask].assign(pnl=lambda f: f.unit_pnl * side[mask] * 100)
        wk = x.groupby("date").pnl.mean().sort_index().to_numpy()
        return dict(trades_from=name, name_weeks=len(x), share_of_all=len(x) / len(p), weeks=x.date.nunique(), mean_per_100=x.pnl.mean(),
                    median_per_100=x.pnl.median(), hit_rate=(x.pnl > 0).mean(), weekly_nw_t=nw_t(wk, horizon))

    out = [row("Yu raw signal, all", p.raw_side != 0, p.raw_side),
           row("Peer-adjusted signal, all", p.adj_side != 0, p.adj_side),
           row("Raw signal the peer control removes", (p.raw_side != 0) & (p.adj_side == 0), p.raw_side),
           row("Raw signal, stress weeks (top quartile of median gap)", (p.raw_side != 0) & stress, p.raw_side),
           row("Peer-adjusted, stress weeks", (p.adj_side != 0) & stress, p.adj_side),
           row("Your workbook signal, all", p.wb_side != 0, p.wb_side),
           row("Your workbook signal, long credit", p.wb_side == 1, p.wb_side),
           row("Your workbook signal, short credit", p.wb_side == -1, p.wb_side),
           row("Raw signal, wide side only (+1)", p.raw_side == 1, p.raw_side),
           row("Raw signal, tight side only (-1)", p.raw_side == -1, p.raw_side)]
    return pd.DataFrame(out)


# ------------------------------------------------------------------- Choice 2: which delta

def table_2a() -> pd.DataFrame:
    rows = []
    for arch, firm in archetypes().items():
        for years, coupon in ((2.0, 0.05), (4.8, 0.055), (9.0, 0.06)):
            b = m.Bond(coupon, years)
            a = m.bond_equity_delta(b, firm, ex.CURVE, ex.R_B, "asset_vol")
            e = m.bond_equity_delta(b, firm, ex.CURVE, ex.R_B, "equity_vol")
            rows.append(dict(issuer=arch, S=firm.S, sigma_s=firm.sigma_s, years_left=years,
                             model_z_bp=m.model_z_spread(b, firm, ex.CURVE, ex.R_B) / BP,
                             delta_asset_vol=a, delta_equity_vol=e, ratio=a / e,
                             stock_usd_asset_vol=a * firm.S * FACE, stock_usd_equity_vol=e * firm.S * FACE))
    return pd.DataFrame(rows)


def table_2b() -> pd.DataFrame:
    """Long USD 10mm bond, short the hedge, one instant stock move. Bond repriced under each 'true' world."""
    firm, bond = ex.f0, ex.BOND0
    p0 = m.risky_bond_price(bond, firm, ex.CURVE, ex.R_B)
    deltas = {h: m.bond_equity_delta(bond, firm, ex.CURVE, ex.R_B, h) for h in ("asset_vol", "equity_vol")}
    deltas["no hedge"] = 0.0
    rows = []
    for world in ("asset_vol", "equity_vol"):
        for move in (-0.5, -0.3, -0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 0.3):
            s = firm.S * (1 + move)
            p1 = m.risky_bond_price(bond, m._bumped(firm, s, world), ex.CURVE, ex.R_B)
            for hedge, dl in deltas.items():
                rows.append(dict(true_world=world, stock_move=move, hedge=hedge,
                                 bond_pnl_k=(p1 - p0) * FACE / 1e3, stock_pnl_k=-dl * (s - firm.S) * FACE / 1e3,
                                 net_pnl_k=((p1 - p0) - dl * (s - firm.S)) * FACE / 1e3))
    for hedge, dl in deltas.items():
        rows.append(dict(true_world="default", stock_move=-1.0, hedge=hedge,
                         bond_pnl_k=(ex.R_B - p0) * FACE / 1e3, stock_pnl_k=dl * firm.S * FACE / 1e3,
                         net_pnl_k=((ex.R_B - p0) + dl * firm.S) * FACE / 1e3))
    return pd.DataFrame(rows)


def table_2c(d: pd.DataFrame) -> pd.DataFrame:
    """Which delta hedged real CDS moves better, over 1, 4 and 13 weeks? Long protection, long stock, no rebalance."""
    x = d.dropna(subset=["iv", "wb_delta", "wb_annuity", "c", "price"]).copy()
    x["d_eq"] = equity_vol_delta(x)
    x = x[np.isfinite(x.d_eq)]
    rows = []
    for h in (1, 4, 13):
        g0 = x.copy()
        g0["c_h"] = g0.groupby("ticker").c.shift(-h)
        g0["p_h"] = g0.groupby("ticker").price.shift(-h)
        g0["d_h"] = g0.groupby("ticker").date.shift(-h)
        g0 = g0.dropna(subset=["c_h", "p_h"])
        g0 = g0[(g0.d_h - g0.date).dt.days.between(7 * h - 2, 7 * h + 2)]
        g0["cds"] = g0.wb_annuity * (g0.c_h - g0.c) * 100
        g0["stk"] = (g0.p_h / g0.price - 1) * 100
        for name, g in [("All", g0)] + [(str(b), k) for b, k in g0.groupby("bucket", observed=True)]:
            var0, mad0 = g.cds.var(), g.cds.abs().mean()
            row = dict(weeks=h, spread_bucket=name, name_weeks=len(g), median_delta_asset_vol=g.wb_delta.median(),
                       median_delta_equity_vol=g.d_eq.median(), median_ratio=(g.wb_delta / g.d_eq).median(),
                       fitted_flat_slope=-np.sum(g.cds * g.stk) / np.sum(g.stk ** 2))
            for k, dl in (("asset_vol", g.wb_delta), ("equity_vol", g.d_eq)):
                net = g.cds + dl * g.stk
                row[f"var_cut_{k}"] = 1 - net.var() / var0
                row[f"abs_cut_{k}"] = 1 - net.abs().mean() / mad0
            rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- Choice 3: fitting L_bar to bond spreads

def fit_with_premium(premium: float, rec=None, lam=None) -> tuple:
    rec, lam = ex.R_B if rec is None else rec, ex.LAM if lam is None else lam
    return m.fit_barrier_on_bond(ex.fit_bonds, ex.FIT_S, np.full(20, ex.D0), np.full(20, ex.SIGMA_S),
                                 ex.fit_z + premium, ex.fit_curves, rec, lam)


def table_3a() -> pd.DataFrame:
    d0 = m.bond_equity_delta(ex.BOND0, ex.f0, ex.CURVE, ex.R_B)
    rows = []
    for bump in (-120, -80, -40, -20, 0, 20, 40, 80, 120, 200, 300):
        L, rmse = fit_with_premium(bump * BP)
        firm = replace(ex.f0, L_bar=L)
        dl = m.bond_equity_delta(ex.BOND0, firm, ex.CURVE, ex.R_B)
        rows.append(dict(premium_bp=bump, L_bar=L, fit_status=m.fit_status(L), fit_rmse_bp=rmse / BP,
                         delta=dl, delta_change=dl / d0 - 1, stock_usd_per_10mm=dl * firm.S * FACE,
                         hedge_error_usd_per_10mm=(dl - d0) * firm.S * FACE,
                         model_z_bp=m.model_z_spread(ex.BOND0, firm, ex.CURVE, ex.R_B) / BP,
                         implied_prob_default_5y=1 - float(m.survival(5.0, firm))))
    return pd.DataFrame(rows)


def table_3b() -> pd.DataFrame:
    """No mispricing anywhere. The premium in the fit window differs from the premium later. Any signal is false."""
    z_true = m.model_z_spread(ex.BOND0, ex.f0, ex.CURVE, ex.R_B)
    rows = []
    for fit_p in (-40, 0, 40, 80, 120, 200):
        L, _ = fit_with_premium(fit_p * BP)
        z_fit = m.model_z_spread(ex.BOND0, replace(ex.f0, L_bar=L), ex.CURVE, ex.R_B)
        for later in (-40, 0, 40, 80, 120, 200, 300):
            mkt = z_true + later * BP
            rows.append(dict(fit_premium_bp=fit_p, later_premium_bp=later, model_z_bp=z_fit / BP, market_z_bp=mkt / BP,
                             gap_bp=(mkt - z_fit) / BP, signal_alpha_50=signal_word(m.entry_signal(mkt, z_fit, 0.5)),
                             signal_alpha_25=signal_word(m.entry_signal(mkt, z_fit, 0.25))))
    return pd.DataFrame(rows)


def table_3c(d: pd.DataFrame) -> pd.DataFrame:
    """Real names: add a premium to the first ten weekly CDS spreads, refit, and see the workbook delta move."""
    d = d.copy()
    d["eqv"] = w.average_equity_vol(d) / 100
    rows = []
    grid = np.geomspace(*m.BARRIER_BOUNDS, 240)
    for t, g in d.groupby("ticker"):
        if len(g) < 10 or g.c.iloc[:10].isna().any():
            continue
        g10 = g.iloc[:10]
        S, D, v, r, c = g10.price.iloc[-1], g10.wb_dps.iloc[-1], g10.eqv.iloc[-1], g10.r.iloc[-1], g10.c.mean()

        def delta(L):
            if not np.isfinite(L):
                return np.nan
            av = v * S / (S + L * D)
            return float(w.cds_greeks(5.0, S, D, av, c / BP, L, 0.3, 0.5, r)["delta"])

        L0 = fit_lbar(g, 0.0, grid=grid)
        d0 = delta(L0)
        for bump in (-40, -20, 20, 40, 80):
            if c + bump * BP <= 0:
                continue
            L1 = fit_lbar(g, bump * BP, grid=grid)
            d1 = delta(L1)
            rows.append(dict(ticker=t, spread_bp=c / BP, premium_bp=bump, L0=L0, L1=L1, change=d1 / d0 - 1,
                             at_bound=L1 <= grid[0] * 1.01 or L1 >= grid[-1] * 0.99))
    x = pd.DataFrame(rows)
    x["bucket"] = pd.cut(x.spread_bp, [0, 100, 300, 1e9], labels=["under 100 bp", "100 to 300 bp", "over 300 bp"])
    out = x.groupby(["bucket", "premium_bp"], observed=True).agg(
        names=("ticker", "nunique"), median_change=("change", "median"), p10=("change", lambda s: s.quantile(.1)),
        p90=("change", lambda s: s.quantile(.9)), median_L0=("L0", "median"), median_L1=("L1", "median"),
        share_at_bound=("at_bound", "mean")).reset_index()
    return out


def main() -> dict:
    OUT.mkdir(exist_ok=True)
    panel = load_panel()
    tables = dict(t1a_decision_cases=table_1a(), t1b_error_rates=table_1b(), t1b2_false_trades=table_1b2(), t1c_gap_paths=table_1c(),
                  t1d_real_cds_peer_test=table_1d(panel), t2a_delta_grid=table_2a(), t2b_hedge_pnl=table_2b(),
                  t2c_real_cds_hedge_test=table_2c(panel), t3a_premium_sweep=table_3a(),
                  t3b_false_signals=table_3b(), t3c_real_cds_premium=table_3c(panel))
    for k, t in tables.items():
        t.to_csv(OUT / f"{k}.csv", index=False)
    return tables


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)
    for k, t in main().items():
        print("\n==", k)
        print(t.round(4).to_string(index=False)[:6500])
