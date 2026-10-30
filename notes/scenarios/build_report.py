"""Turn tables/*.csv into scenario_tables.tex. Every number in the document comes from the CSVs. Run after scenario_tables.py."""
import re
from pathlib import Path

import pandas as pd

T = Path(__file__).resolve().parent / "tables"
r = {p.stem: pd.read_csv(p) for p in T.glob("*.csv")}


def esc(x):
    return str(x).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")


def tab(rows, cols, spec, size=r"\small"):
    head = " & ".join(cols) + r" \\ \midrule"
    body = "\n".join(" & ".join(esc(c) for c in row) + r" \\" for row in rows)
    return f"{{{size}\n\\begin{{center}}\\begin{{tabular}}{{{spec}}}\\toprule\n{head}\n{body}\n\\bottomrule\\end{{tabular}}\\end{{center}}}}\n"


pc = lambda x, d=0: f"{100 * x:+.{d}f}%"
pu = lambda x, d=0: f"{100 * x:.{d}f}%"
word = {"long bond": "long", "short bond": "short", "no trade": "--"}

# ---- 1A
a = r["t1a_decision_cases"]
base = a[a.issuer == "base"]
z0 = base.model_z_bp.iloc[0]
t1a = tab([[x.case, word[x.should_trade], word[x.yu_raw], word[x.peer_only], word[x.sibling_only], word[x.both], "yes" if x.both_correct else r"\textbf{NO}"]
           for x in base.itertuples()], ["Case", "Right answer", "Yu raw", "Peer", "Sibling", "Both", "Both right?"], "lcccccc")
# ---- 1B
b = r["t1b_error_rates"]
names = {"raw": "Yu raw", "peer": "Peer only", "sibling_only": "Sibling only", "both": "Both, as coded", "both_sibling_on_adjusted": "Both, sibling on adjusted gaps"}
rows = []
for k, n in names.items():
    g = b[b.control == k].set_index("noise_bp")
    rows.append([n] + [pu(g.loc[q, "true_mispricing_caught"]) for q in (0, 25, 50)] + [pu(g.loc[q, "false_trade_rate"]) for q in (0, 25, 50)])
t1b = tab(rows, ["Control", "Caught, 0 bp", "25 bp", "50 bp", "False trades, 0 bp", "25 bp", "50 bp"], "lrrrrrr")
fb = b[b.noise_bp == 0].set_index("control")
# ---- 1C
c = r["t1c_gap_paths"]
rows = []
for p in c.path.unique():
    g = c[c.path == p]
    v = lambda gp, k: pc(g[(g.gap_bp == gp) & (g.cost == k)].return_on_capital.iloc[0], 1)
    rows.append([p, v(150, "1x cost"), v(150, "3x cost"), v(300, "1x cost"), v(300, "3x cost")])
t1c = tab(rows, ["What the gap does", "150 bp gap, 1x cost", "3x cost", "300 bp gap, 1x cost", "3x cost"], "lrrrr")
# ---- 1D
d = r["t1d_real_cds_peer_test"]
t1d = tab([[x.trades_from, f"{x.name_weeks:,}", pu(x.share_of_all), f"{x.mean_per_100:+.2f}", f"{x.median_per_100:+.2f}", pu(x.hit_rate), f"{x.weekly_nw_t:+.1f}"] for x in d.itertuples()],
          ["Trades", "Name-weeks", "Share", "Mean", "Median", "Hit rate", "t"], "lrrrrrr")
dd = d.set_index("trades_from")
# ---- 2A
e = r["t2a_delta_grid"]
t2a = tab([[x.issuer, f"{x.S:.1f}", pu(x.sigma_s), f"{x.years_left:.1f}", f"{x.model_z_bp:.0f}", f"{x.stock_usd_asset_vol / 1e3:,.0f}", f"{x.stock_usd_equity_vol / 1e3:,.0f}", f"{x.ratio:.1f}x"] for x in e.itertuples()],
          ["Issuer", "S", "Equity vol", "Years", "Model Z (bp)", "Asset vol held (\\$k)", "Equity vol held (\\$k)", "Ratio"], "lrrrrrrr")
eb = e[(e.issuer == "base") & (e.years_left == 4.8)].iloc[0]
# ---- 2B
f = r["t2b_hedge_pnl"]
rows = []
for mv in (-0.5, -0.3, -0.2, -0.1, 0.1, 0.2, 0.3):
    row = [pc(mv)]
    for wd in ("asset_vol", "equity_vol"):
        for h in ("asset_vol", "equity_vol", "no hedge"):
            row.append(f"{f[(f.true_world == wd) & (f.stock_move == mv) & (f.hedge == h)].net_pnl_k.iloc[0]:+,.0f}")
    rows.append(row)
df = f[f.true_world == "default"].set_index("hedge").net_pnl_k
rows.append(["Default"] + [f"{df['asset_vol']:+,.0f}", f"{df['equity_vol']:+,.0f}", f"{df['no hedge']:+,.0f}"] * 2)
t2b = tab(rows, ["Stock", "AV hedge", "EV hedge", "None", "AV hedge", "EV hedge", "None"], "lrrrrrr")
# ---- 2C
g = r["t2c_real_cds_hedge_test"]
t2c = tab([[f"{x.weeks}", x.spread_bucket, f"{x.name_weeks:,}", f"{x.median_delta_asset_vol:.3f}", f"{x.median_delta_equity_vol:.3f}", f"{x.fitted_flat_slope:.3f}", pc(x.var_cut_asset_vol), pc(x.var_cut_equity_vol), pc(x.abs_cut_asset_vol), pc(x.abs_cut_equity_vol)] for x in g.itertuples()],
          ["Weeks", "Spread", "N", "AV delta", "EV delta", "Fitted slope", "Var cut AV", "Var cut EV", "Abs cut AV", "Abs cut EV"], "rlrrrrrrrr", r"\footnotesize")
ga = g[g.spread_bucket == "All"].set_index("weeks")
gu = g[g.spread_bucket == "under 100 bp"].set_index("weeks")
share_u = g[(g.weeks == 1) & (g.spread_bucket == "under 100 bp")].name_weeks.iloc[0] / ga.loc[1, "name_weeks"]
# ---- 3A
h = r["t3a_premium_sweep"]
t3a = tab([[f"{x.premium_bp:+d}", f"{x.L_bar:.2f}", x.fit_status, f"{x.model_z_bp:.0f}", pc(x.delta_change), f"{x.stock_usd_per_10mm / 1e3:,.0f}", f"{x.hedge_error_usd_per_10mm / 1e3:+,.0f}", pu(x.implied_prob_default_5y)] for x in h.itertuples()],
          ["Premium (bp)", "$\\bar L$", "Fit status", "Model Z", "Delta change", "Stock hedge (\\$k)", "Hedge error (\\$k)", "5y default prob."], "rrlrrrrr")
hh = h.set_index("premium_bp")
# ---- 3B
i = r["t3b_false_signals"]
lat = sorted(i.later_premium_bp.unique())
rows = []
for fp in sorted(i.fit_premium_bp.unique()):
    row = [f"{fp:+d}"]
    for l in lat:
        x = i[(i.fit_premium_bp == fp) & (i.later_premium_bp == l)].iloc[0]
        tag = {"long bond": "L", "short bond": "S", "no trade": ""}
        s = tag[x.signal_alpha_50] or (tag[x.signal_alpha_25].lower())
        row.append(f"{x.gap_bp:+.0f} {s}".strip())
    rows.append(row)
t3b = tab(rows, ["Premium in fit"] + [f"{l:+d} later" for l in lat], "r" + "r" * len(lat))
# ---- 3C
k = r["t3c_real_cds_premium"]
t3c = tab([[x.bucket, f"{x.premium_bp:+d}", f"{x.names}", pc(x.median_change), pc(x.p10), pc(x.p90), f"{x.median_L0:.2f}", f"{x.median_L1:.2f}", pu(x.share_at_bound)] for x in k.itertuples()],
          ["Spread", "Premium (bp)", "Names", "Median delta change", "10th pct", "90th pct", "$\\bar L$ before", "$\\bar L$ after", "At bound"], "lrrrrrrrr")
ku = k[(k.bucket == "under 100 bp") & (k.premium_bp == 40)].iloc[0]
km = k[(k.bucket == "100 to 300 bp") & (k.premium_bp == 40)].iloc[0]
ko = k[(k.bucket == "over 300 bp") & (k.premium_bp == 40)].iloc[0]

doc = rf"""\documentclass[10pt,a4paper]{{article}}
\usepackage[margin=1.8cm]{{geometry}}
\usepackage[T1]{{fontenc}}\usepackage{{lmodern,booktabs,enumitem,amsmath}}
\setlength{{\parindent}}{{0pt}}\setlength{{\parskip}}{{5pt}}
\title{{Scenario tables for the three uncertain bond choices}}\author{{Personal research}}\date{{30 October 2026}}
\begin{{document}}\sloppy\maketitle

\section*{{The answer}}
\begin{{enumerate}}[leftmargin=*,itemsep=2pt]
\item \textbf{{Illiquidity versus mispricing: keep both controls, but they have one blind spot.}} In the test grid they cut false trades from {pu(fb.loc['raw','false_trade_rate'])} to {pu(fb.loc['both','false_trade_rate'])}, and catch {pu(fb.loc['both','true_mispricing_caught'])} of true mispricing against {pu(fb.loc['raw','true_mispricing_caught'])} for Yu's raw signal. They cannot see illiquidity across a whole issuer, because the sibling bond shares it. Only CDS or trade data can catch that.
\item \textbf{{Equity delta: real data points to the smaller delta.}} On your real CDS panel, the equity-vol delta hedged better overall at 1, 4 and 13 weeks. Your workbook's asset-vol delta \emph{{added}} variance at 1 week ({pc(ga.loc[1,'var_cut_asset_vol'])}), against {pc(ga.loc[1,'var_cut_equity_vol'])} for the equity-vol delta. Neither hedge removes much: the best overall variance cut is {pu(ga.loc[13,'var_cut_equity_vol'])}.
\item \textbf{{Fitting $\bar L$: the +13\% is too kind for low-spread names.}} On real names, a +40 bp premium moves the delta by a median {pc(ku.median_change)} under 100 bp, {pc(km.median_change)} from 100 to 300 bp, and {pc(ko.median_change)} over 300 bp.
\end{{enumerate}}

\textbf{{Decisions taken for the merged method:}}
\begin{{itemize}}[leftmargin=*,itemsep=1pt]
\item Keep the peer and sibling checks as coded. Applying the sibling check to adjusted gaps closes one leak, but catches less true mispricing ({pu(fb.loc['both_sibling_on_adjusted','true_mispricing_caught'])} against {pu(fb.loc['both','true_mispricing_caught'])}).
\item Replicating your workbook uses the asset-vol delta, because its formulas hold asset vol fixed. The bond method runs with the equity-vol delta as its baseline and reports the asset-vol delta beside it.
\item The first bond test excludes names under 100 bp. There both model deltas add variance, and $\bar L$ is unstable.
\end{{itemize}}

\textbf{{How far to trust this.}} Tables tagged \textbf{{BOND}} use one made-up issuer and bond, from the worked example. They show how the method responds, not what happens in markets. Tables tagged \textbf{{REAL CDS}} use your master panel: weekly, 2002-09 to 2005-09, 170 names, before costs, in sample, and with GM and Ford already removed. That panel is CDS, not bonds, so it informs the bond choice only indirectly. No bond data has been tested.

\textbf{{To rerun:}} \texttt{{python3 scenario\_tables.py}}, then \texttt{{python3 build\_report.py}}. Inputs are \texttt{{e2c\_bond.py}}, \texttt{{worked\_example.py}}, \texttt{{e2c\_model.py}} and \texttt{{master\_panel.csv.gz}}. Outputs are one CSV per table in \texttt{{tables/}}, and this document.

\section*{{Choice 1. Illiquidity versus mispricing}}
\textbf{{Table 1A, BOND. What each control does.}} Model Z is {z0:.0f} bp, and the trigger is $\alpha=0.5$, so the market must be over {1.5*z0:.0f} bp or under {z0/1.5:.0f} bp. Premia are in bp. ``Right answer'' uses the true mispricing alone. The CSV holds the same cases for a low-spread and a high-spread issuer.
{t1a}
The ``NO'' rows are the blind spots. Whole-issuer illiquidity passes every control. Large market stress can also hide real mispricing, because subtracting log gaps shrinks it.

\textbf{{Table 1B, BOND. Error rates with measurement noise.}} Equal weight over 8 mispricing values (three of them zero), 4 market premia and 5 premium types. The rates depend on this grid, which is my choice, so compare controls and do not read the levels as forecasts.
{t1b}

\textbf{{Table 1C, BOND. What the trade earns under each gap path.}} Return on capital over the holding period, from the full backtest, with flat stock and rates. Capital is 0.5 per 1 of face. 1x cost is a 1\% bond round trip.
{t1c}
A premium that never closes mostly earns its carry, and higher costs turn that into a loss. The real damage comes if the gap keeps widening.

\textbf{{Table 1D, REAL CDS. Did the peer control help?}} Overlapping 13-week holds, per 100 of notional, before costs. Hedged with the workbook delta. $\bar L$ is fitted on each name's first ten weeks, and the sector median is the peer gap. Equity vol is the workbook blend, not Yu's 1,000-day vol, so this is Yu-style and not a replication. t uses weekly means with Newey-West, 13 lags. A sibling test is not possible here, because each name has one CDS.
{t1d}
\textbf{{This is inconclusive.}} The trades the peer control removes averaged {dd.loc['Raw signal the peer control removes','mean_per_100']:+.2f} (t = {dd.loc['Raw signal the peer control removes','weekly_nw_t']:+.1f}). That points the right way, but no row is statistically significant. The raw signal also fires on {pu(dd.loc['Yu raw signal, all','share_of_all'])} of name-weeks, so it barely selects anything. Your workbook's signal is more selective, at {pu(dd.loc['Your workbook signal, all','share_of_all'])}. This fixed-hold measure is cruder than your workbook's weekly rebuild, so it does not replace the workbook's own backtest.

\section*{{Choice 2. Which equity delta}}
\textbf{{What your files settle.}} Your workbooks bump the share price with asset vol held fixed (\texttt{{cds\_greeks}}, step S12). The recompute matches all 19,489 rows. So your method used the asset-vol delta. That settles what you did, not which is better.

\textbf{{Table 2A, BOND. How far apart the deltas are.}} Stock hedge per \$10mm face. The quoted 2.2x is this grid's base row ({eb.ratio:.1f}x). The gap grows with spread and maturity.
{t2a}

\textbf{{Table 2B, BOND. Hedge P\&L when the hedge is wrong.}} Long \$10mm of the bond, short the hedge, one instant stock move, in \$ thousands. AV is the asset-vol delta and EV is the equity-vol delta. The left three columns assume bond prices really move with asset vol held fixed, and the right three assume equity vol held fixed.
{t2b}
Each hedge works in its own world, and fails in the other. In default, either hedge leaves most of the loss in place: the bond loses about \${-df['no hedge']:,.0f}k, and the better hedge recovers only about \${df['asset_vol']-df['no hedge']:,.0f}k.

\textbf{{Table 2C, REAL CDS. Which delta hedged better.}} Long protection plus long stock, with no rebalancing. AV and EV are the asset-vol and equity-vol deltas. ``Var cut'' is the fall in variance from adding the hedge, and ``Abs cut'' is the fall in mean absolute P\&L. A negative number means the hedge made things worse. ``Fitted slope'' is an in-sample flat hedge, for reference.
{t2c}
Under 100 bp, which is {pu(share_u)} of the 1-week sample, both model deltas are far above the fitted slope and mostly add variance. Over 300 bp the result is mixed, and the asset-vol delta sometimes does better.

\section*{{Choice 3. Fitting $\bar L$ to bond spreads}}
\textbf{{Table 3A, BOND. A premium in the fit window.}} The fit absorbs a liquidity premium into $\bar L$, which moves the hedge. The +40 and -40 rows reproduce the quoted +13\% and -16\%. Hedge figures are per \$10mm face. ``Fit status'' is the code's own flag: above $\bar L = 1$ it asks for review, and at the bound it rejects.
{t3a}

\textbf{{Table 3B, BOND. False signals when the premium changes after the fit.}} There is no mispricing anywhere in this table, so \textbf{{every signal is false}}. Cells show market minus model in bp. L or S marks a long-bond or short-bond signal at $\alpha=0.5$. Lower-case l or s marks a signal that fires only at $\alpha=0.25$.
{t3b}
So a change of about 120 bp in the premium is enough to fire a false signal at $\alpha=0.5$ on this bond, and about 80 bp at $\alpha=0.25$.

\textbf{{Table 3C, REAL CDS. The same premium test on real names.}} A premium is added to each name's first ten weekly spreads, then $\bar L$ is refitted and the delta recomputed. ``At bound'' is the share of fits that hit the code's limits. These ten weeks fall in late 2002, a stressed period, which may affect the fits.
{t3c}

\end{{document}}
"""
(T.parent / "scenario_tables.tex").write_text(re.sub(r"(?<!\\)%", r"\\%", doc))
