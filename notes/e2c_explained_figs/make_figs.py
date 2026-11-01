"""Figures and numbers for e2c_explained.tex. Nothing here is tracked data: the panel stays on method/workbook.

Run from any folder:
  python make_figs.py <folder with e2c_model.py and master_panel.csv.gz> <folder with fk_model.py and fk_risk.py>
Writes PDF figures and numbers.json next to this file. All panel results are in-sample on a survivors-only panel.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
wb, fk_dir = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(wb), str(fk_dir)]
import e2c_model as m
import fk_model as fk
import fk_risk as rk
import fk_value as v
from fk_value import e2c

LONG, SHORT, GREY, BAD = "#0f766e", "#c2410c", "#64748b", "#b91c1c"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
panel = pd.read_csv(wb / "master_panel.csv.gz", parse_dates=["date", "next_date"])
P = m.MASTER_PARAMS
BAND, CAP = replace(P, exit_trigger=3.0), replace(P, exit_trigger=3.0, max_per_side=20)
out = {}
base = m.run_pipeline(panel, P)
names = base["names"]
mo = names[(names.ticker == "MO US Equity") & (names.date == "2004-01-16")].iloc[0]


def sharpe(x):
    return float(x.mean() / x.std() * np.sqrt(52))


def book(params):
    r = m.run_pipeline(panel, params)
    x, w = r["names"], r["weeks"]
    pnl, cost = x.groupby("date").pnl_total.sum(), m.trading_cost(x, 0.05)
    nav_net = m.weekly_return(w.pnl_total - cost.reindex(w.index).fillna(0), w.nav)["alpha"]
    on = x[(x.long_flag == 1) | (x.short_flag == 1)]
    top = on.groupby("ticker").pnl_total.sum().sort_values(ascending=False)
    return dict(names=len(on) / len(pnl), gross=float(pnl.sum()), cost=float(cost.sum()), raw_gross=sharpe(pnl), nav_gross=float(r["summary"]["sharpe"]),
                raw_net=sharpe(pnl - cost), nav_net=float(m.performance_summary(nav_net)["sharpe"]), top5=float(top.head(5).sum() / pnl.sum()),
                capped=float(((on.size_long + on.size_short) >= P.trade_limit).mean()))


out["today"], out["band"], out["cap"] = book(P), book(BAND), book(CAP)

# The first ranking counted every trade as if it reached the target P&L, so a trade at the size limit looked better than it is.
true_gain = m.gain_per_cost


def first_rank(residual, vega, implied, annuity, spread_bp, params):
    one = np.ones(len(np.asarray(vega)))
    size = m.trade_size(one, 0 * one, vega, implied, params)["size_long"]
    gain = np.abs(np.asarray(residual, float)) / params.target_vega_points * params.target_trade_pnl
    return gain / (size * np.asarray(annuity, float) * np.asarray(spread_bp, float) / 1e4 * params.bid_offer)


m.gain_per_cost = first_rank
out["cap_first_rank"] = book(CAP)
runs = []
for seed in range(20):
    rng = np.random.default_rng(seed)
    m.gain_per_cost = lambda residual, *a: rng.random(len(np.asarray(residual)))
    runs.append(book(CAP)["raw_net"])
m.gain_per_cost = true_gain
out["random_cap"] = dict(mean=float(np.mean(runs)), low=float(min(runs)), high=float(max(runs)))

# Does gap size pick next week's winners?
all_on = m.run_pipeline(panel, replace(P, long_trigger=0.0, short_trigger=0.0))["names"]
past = all_on[all_on.residual.abs() > 6].copy()
past["size_of_gap"] = past.residual.abs()
ic = past.groupby("date").apply(lambda g: g.size_of_gap.corr(g.pnl_total, method="spearman")).dropna()
out["gap_rank"] = dict(mean=float(ic.mean()), t=float(ic.mean() / ic.std() * np.sqrt(len(ic))))


# Does the book only follow the market?
def hac(y, X, lags=4):
    X = np.c_[np.ones(len(X)), X]
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    inv = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for k in range(1, lags + 1):
        G = (X[k:] * e[k:, None]).T @ (X[:-k] * e[:-k, None])
        S += (1 - k / (lags + 1)) * (G + G.T)
    return b, b / np.sqrt(np.diag(inv @ S @ inv)), e


n = names.assign(ret=names.next_price / names.price - 1, ds=names.next_spread_bp - names.spread_bp)
g = n.groupby("date")
mkt = pd.DataFrame(dict(pnl=g.pnl_total.sum(), stock=g.ret.mean(), credit=g.ds.median())).dropna()
b, t, e = hac(mkt.pnl.to_numpy(), mkt[["stock", "credit"]].to_numpy())
out["market"] = dict(weeks=len(mkt), sharpe_after=float(b[0] / e.std() * np.sqrt(52)), share_left=float(b[0] / mkt.pnl.mean()))
for side, flag in (("long_credit", "long_flag"), ("short_credit", "short_flag")):
    y = n.pnl_total.where(n[flag] == 1, 0).groupby(n.date).sum().reindex(mkt.index).to_numpy()
    b, t, e = hac(y, mkt[["stock", "credit"]].to_numpy())
    out["market"][side] = dict(alpha_t=float(t[0]), r2=float(1 - e.var() / y.var()))

# Worked row
spread_at = lambda vol: float(m.model_spread(5.0, mo.price, mo.dps, vol / 100, 0.5, 0.3, 0.4, mo.swap_5y_pct / 100)) * 1e4
out["mo"] = {c: float(mo[c]) for c in ("st_debt lt_debt other_st_liab other_lt_liab minority_int mkt_cap price spread_bp swap_5y_pct dps avg_equity_vol "
                                       "avg_asset_vol implied s_over_d skew_pit coeff_pit fair_vol residual annuity delta vega target size_long delta_long "
                                       "hedge_shares next_spread_bp next_price days pnl_cds_long pnl_hedge_long carry_long rebate pnl_total").split()}
out["mo"]["spread_at_fair"], out["mo"]["spread_at_hist"], out["mo"]["spread_at_implied"] = spread_at(mo.fair_vol), spread_at(mo.avg_asset_vol), spread_at(mo.implied)

# Figure: reading a CDS quote as an asset vol
vols = np.linspace(12, 62, 201)
fig, ax = plt.subplots(figsize=(6.3, 2.9))
ax.plot(vols, [spread_at(x) for x in vols], color=GREY, lw=1.8)
for vol, label, colour, dy in ((mo.fair_vol, "fair vol from the regression\n33.4 points: equity says {:.0f} bp".format(spread_at(mo.fair_vol)), LONG, 42),
                               (mo.implied, "implied vol 45.9 points:\nthe market quote, 142.3 bp", SHORT, -62)):
    s = spread_at(vol)
    ax.plot([vol, vol], [0, s], color=colour, ls=":")
    ax.plot([12, vol], [s, s], color=colour, ls=":")
    ax.scatter([vol], [s], color=colour, zorder=3)
    ax.annotate(label, (vol, s), (vol + (-15 if dy > 0 else 2), s + dy), color=colour, arrowprops=dict(arrowstyle="-", color=colour, lw=.6))
ax.annotate("", (mo.implied, 12), (mo.fair_vol, 12), arrowprops=dict(arrowstyle="<->", color=BAD))
ax.text((mo.implied + mo.fair_vol) / 2, 18, "gap", color=BAD, ha="center")
ax.set(xlabel="5-year asset vol (points)", ylabel="CreditGrades CDS spread (bp)", xlim=(12, 62), ylim=(0, None))
ax.set_title("MO, 16 Jan 2004: the same curve turns a quote into a vol, and a vol into a spread", fontsize=9, loc="left")
fig.tight_layout(); fig.savefig(HERE / "inversion.pdf"); plt.close(fig)

# Figure: hold band on one real name
def trades(res, entry, exit_):
    side, path = 0, []
    for x in res:
        if side == 1 and x <= exit_ or side == -1 and x >= -exit_ or np.isnan(x):
            side = 0
        if side == 0 and not np.isnan(x):
            side = 1 if x > entry else -1 if x < -entry else 0
        path.append(side)
    return np.array(path)


def starts(path):
    return int(np.sum((path != 0) & (np.r_[0, path[:-1]] != path)))


score = {}
for tk, f in names.sort_values("date").groupby("ticker"):
    if len(f) == 151:
        a, c = trades(f.residual.to_numpy(), 6, 6), trades(f.residual.to_numpy(), 6, 3)
        if (a == 1).any() and (a == -1).any():
            score[tk] = starts(a) - starts(c)
pick = max(score, key=score.get)
f = names[names.ticker == pick].sort_values("date")
out["band_name"] = dict(ticker=pick, today=starts(trades(f.residual.to_numpy(), 6, 6)), band=starts(trades(f.residual.to_numpy(), 6, 3)),
                        days_today=int((trades(f.residual.to_numpy(), 6, 6) != 0).sum()), days_band=int((trades(f.residual.to_numpy(), 6, 3) != 0).sum()))
fig, axes = plt.subplots(2, 1, figsize=(6.3, 4.3), sharex=True)
for ax, exit_, title in ((axes[0], 6, "Today: out as soon as the gap dips inside 6"), (axes[1], 3, "Hold band: in past 6, out only at 3")):
    res, path = f.residual.to_numpy(), trades(f.residual.to_numpy(), 6, exit_)
    ax.plot(f.date, res, color=GREY, lw=1)
    ax.fill_between(f.date, res.min() - 1, res.max() + 1, where=path == 1, color=LONG, alpha=.16, step="mid", lw=0)
    ax.fill_between(f.date, res.min() - 1, res.max() + 1, where=path == -1, color=SHORT, alpha=.16, step="mid", lw=0)
    enter = (path != 0) & (np.r_[0, path[:-1]] != path)
    ax.scatter(f.date[enter], res[enter], color="k", s=14, zorder=3, label="trade entered")
    for level, ls in ((6, "--"), (-6, "--")) + (((3, ":"), (-3, ":")) if exit_ == 3 else ()):
        ax.axhline(level, color=BAD if ls == "--" else "k", ls=ls, lw=.7)
    ax.set_title(f"{title}: {starts(path)} entries, {(path != 0).sum()} weeks held", fontsize=9, loc="left")
    ax.set_ylabel("residual")
    ax.set_ylim(res.min() - 1, res.max() + 1)
axes[0].legend(frameon=False, fontsize=8, loc="lower right", title="green: sold protection, orange: bought protection", title_fontsize=8)
first_cluster = f.date.iloc[np.flatnonzero(trades(f.residual.to_numpy(), 6, 6) != 0)[3]]
axes[0].annotate("gap wobbles around -6:\nin and out, cost each time", (first_cluster, -6), (f.date.iloc[30], 1.5), fontsize=8, color=BAD, arrowprops=dict(arrowstyle="-", color=BAD, lw=.6))
axes[1].annotate("same gap, one long hold", (first_cluster, -3), (f.date.iloc[30], 1.5), fontsize=8, color=LONG, arrowprops=dict(arrowstyle="-", color=LONG, lw=.6))
fig.tight_layout(); fig.savefig(HERE / "hold_band.pdf"); plt.close(fig)

# Figure: where the money goes
labels = ["Today\n6/6", "Hold band\n6/3", "Band plus\n20 per side"]
keys = ["today", "band", "cap"]
fig, ax = plt.subplots(figsize=(6.3, 2.7))
x = np.arange(3)
ax.bar(x - .2, [out[k]["gross"] for k in keys], .38, color=GREY, label="P&L before costs")
ax.bar(x + .2, [out[k]["cost"] for k in keys], .38, color=BAD, label="CDS cost at 5% of spread, round trip")
for i, k in enumerate(keys):
    ax.text(i, max(out[k]["gross"], out[k]["cost"]) + 700, f"Sharpe after costs {out[k]['raw_net']:.2f}\n{out[k]['names']:.0f} names a week", ha="center", fontsize=8)
ax.set_xticks(x, labels); ax.set_ylabel("$ thousands, 151 weeks"); ax.set_ylim(0, 31000); ax.legend(frameon=False, fontsize=8, loc="upper center", ncol=2)
fig.tight_layout(); fig.savefig(HERE / "costs.pdf"); plt.close(fig)

# Figure: a put splits into default and diffusion. Slides 21-25 setting: S 40, B 15, vol 0.375, r 5%, p 2%, 2 years.
S, B, sig, r, p, T = 40.0, 15.0, 0.375, 0.05, 0.02, 2.0
Ks = np.linspace(10, 50, 81)
parts = [fk.fk_put(S, K, T, sig, B, r, p) for K in Ks]
fig, ax = plt.subplots(figsize=(6.3, 2.7))
ax.stackplot(Ks, [q[1] for q in parts], [q[2] for q in parts], colors=[BAD, LONG], alpha=.55, labels=["default part: pays K if the firm defaults", "diffusion part: stock falls, no default"])
ax.axvline(30, color="k", ls=":", lw=.8)
at30 = fk.fk_put(S, 30.0, T, sig, B, r, p)
ax.annotate(f"K = 30: {at30[0]:.2f} = {at30[1]:.2f} default + {at30[2]:.2f} diffusion", (30, at30[0]), (11, at30[0] + 3.6), arrowprops=dict(arrowstyle="-", lw=.6))
ax.set(xlabel="strike K", ylabel="model put value ($ per share)", xlim=(10, 50)); ax.legend(frameon=False, fontsize=8, loc="upper left")
fig.tight_layout(); fig.savefig(HERE / "put_split.pdf"); plt.close(fig)
out["put"] = dict(price=float(at30[0]), default=float(at30[1]), diffusion=float(at30[2]))

curve = e2c.flat_curve(.05)
tgt = rk.cds_seller_greeks(5.0, S, B, sig, curve, .10, .056, lam=.3, face=100.)
put = rk.put_greeks(S, 30., T, sig, B, r, p, price=5.22)
hedge = rk.solve_hedge(tgt, reference_value=100., rows=("delta", "jump"), put=put, stock=rk.stock_greeks(S))
net = rk.net_greeks(tgt, hedge, put=put, stock=rk.stock_greeks(S))
out["hedge"] = dict(tgt_delta=tgt.delta, tgt_jump=tgt.jump, tgt_vega=tgt.vega, put_delta=put.delta, put_jump=put.jump, put_vega=put.vega, n_put=hedge.n_put, n_stock=hedge.n_stock,
                    status=hedge.status, dollars_put=hedge.dollars[0], dollars_stock=hedge.dollars[1], net_delta=net.delta, net_jump=net.jump, net_vega=net.vega)
gaps = v.three_gaps(500.0, 400.0, 300.0)
out["gaps"] = dict(zip(("bp", "ps", "bs"), map(float, gaps)))
(HERE / "numbers.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps(out, indent=1, default=float))
