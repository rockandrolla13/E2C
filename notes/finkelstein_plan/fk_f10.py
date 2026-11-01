"""What F10 and WP6a's done-when row need on top of fk_des.py: screens, financing, Treasury overlay, splits, t-statistics, verdict.

Pure logic: no file, no environment variable, no vendor. run_f10.py does the reading and writing.

[ADAPTATION] Chen, Chen and Li (2026) was not on hand. Published figures come from finkelstein_replication_plan.pdf,
Section 9 and F10's row. Where the plan is silent, the rule below is mine, was fixed before any real data was seen, and is
marked MINE. The paper's own screens, clean-return definition and standard errors are unknown here.

F10's rule in the plan: "Signs must match. Sizes as shape, if samples differ."
  Q1 gap below 0 and Q5 gap above 0. Q1 price ratio below 1 and Q5 above 1. Bond premium, top less bottom, above 0.
  Stock premium, bottom less top, above 0. All are read on the published window, 2002-01 to 2021-12, value-weighted, 1-month hold.
MINE, added to that rule:
  1. A sign on noise is no reproduction, so the bond premium also needs t >= 1.96.
  2. NOT JUDGED below 60 months in the window or a median of 25 sorted firms, which leaves 5 firms a quintile.
  3. t-statistics are Newey-West with 6 lags, because the plan states no method. The published t may use another.
  4. Overall verdict across the two compoundings is the weaker one, because the user has not chosen a compounding.
  5. The size gap to 3.24% is reported and does not decide the verdict, as the plan's rule says.

Other choices MINE: size split at each month's median face. Fee split at each month's median fee. Financing needs 90% of
each side's weight to have a rate, and scales the covered part up to 100%. Overlay hedge is a 5-year par Treasury, repo
at the curve's shortest yield. Planning costs are Cao et al.'s 18 bp (large) and 68 bp (small) from the plan's T0, used
only when no measurement exists and labelled as such. The all-bond book's cost is the mean of the two.
"""
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd

import fk_des as fd
from fk_value import e2c

NAN = float("nan")
REPRODUCED, NOT_REPRODUCED, NOT_JUDGED = "REPRODUCED", "NOT REPRODUCED", "NOT JUDGED"
PLAN_COST_LARGE, PLAN_COST_SMALL = .0018, .0068
MONTH = 1 / 12
SIDES = {"long": 1, "short": -1}
_MIN_TOTAL_RETURN = 1e-4   # a total loss stays a finite log return


class F10Target(NamedTuple):
    """The plan's figures. Section 9, and F10's row."""
    window: tuple = ("2002-01", "2021-12")
    premium: float = .0324
    premium_t: float = 2.69
    full_premium: float = .0528
    full_premium_t: float = 5.64
    stock_premium: float = .0656
    stock_premium_t: float = 3.79
    gaps: tuple = (-139.0, 271.0)
    ratios: tuple = (.94, 1.16)


class F10Settings(NamedTuple):
    min_months: int = 60
    min_firms: int = 25
    min_t: float = 1.96
    nw_lags: int = 6
    liquidity_screen: bool = True
    hedge_tenor: float = 5.0
    bond_cost: Optional[float] = None
    stock_cost: Optional[float] = None
    config: fd.DesConfig = fd.DesConfig()


class Estimate(NamedTuple):
    mean: float
    se: float
    t: float
    n: int


class Verdict(NamedTuple):
    verdict: str
    reason: str


def newey_west(x, lags: int = 6) -> Estimate:
    """Mean of a series, with a Newey-West standard error and Bartlett weights. NaN entries leave, and close the gap."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return Estimate(float(x.mean()) if n else NAN, NAN, NAN, n)
    e = x - x.mean()
    variance = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        variance += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    se = float(np.sqrt(variance / n)) if variance > 0 else NAN
    return Estimate(float(x.mean()), se, float(x.mean()) / se if se == se else NAN, n)


# ---------------------------------------------------------------- Screens: e2c_bond Part 1, as the plan's step 17 says

_TERM_DEFAULTS = dict(seniority="senior_unsecured", currency="USD", coupon_type="fixed", call_type="none", is_convertible=False,
                      is_putable=False, is_sinking=False, is_perpetual=False, is_pik=False)
_SECTOR_WORDS = (("financ", "financial"), ("util", "utility"))


def _sector(word: str) -> str:
    word = word.lower()
    return next((name for stem, name in _SECTOR_WORDS if word.startswith(stem)), word)


def _column(rows: pd.DataFrame, name: str, default, absent: list) -> pd.Series:
    if name in rows:
        return rows[name]
    absent.append(name)
    return pd.Series([default] * len(rows), index=rows.index, dtype=object)


def _terms_pass(rows: pd.DataFrame, absent: list) -> pd.Series:
    fields = {name: _column(rows, name, default, absent) for name, default in _TERM_DEFAULTS.items()}
    table = pd.DataFrame(fields)
    ok = [not any(pd.isna(v) for v in row) and e2c.bond_terms_are_eligible(*row) for row in table[list(_TERM_DEFAULTS)].itertuples(index=False)]
    return pd.Series(ok, index=rows.index)


def _issuer_pass(rows: pd.DataFrame, absent: list) -> pd.Series:
    sector, listed = _column(rows, "sector", "industrial", absent), _column(rows, "has_listed_equity", True, absent)
    ok = [not pd.isna(s) and not pd.isna(l) and e2c.issuer_is_eligible(_sector(str(s)), bool(l)) for s, l in zip(sector, listed)]
    return pd.Series(ok, index=rows.index)


def _callable_pass(rows: pd.DataFrame, absent: list) -> pd.Series:
    kind = _column(rows, "call_type", "none", absent)
    price, call = _column(rows, "clean_price", NAN, absent), _column(rows, "next_call_price", NAN, absent)
    ok = [k != "fixed_price" or (e2c.callable_is_usable(k, p, c) if (p == p and c == c) else False) for k, p, c in zip(kind, price, call)]
    return pd.Series(ok, index=rows.index)


def _maturity_pass(rows: pd.DataFrame, alive: pd.Series) -> pd.Series:
    core = rows.maturity_years.between(3.0, 7.0) & alive
    has_core = core.groupby([rows.firm_id, rows.date]).transform("any")
    ok = [m == m and e2c.maturity_is_eligible(m, h) for m, h in zip(rows.maturity_years, has_core)]
    return pd.Series(ok, index=rows.index)


def _age_size_pass(rows: pd.DataFrame, absent: list) -> pd.Series:
    age = _column(rows, "years_since_issue", 99.0, absent)
    ok = [a == a and y == y and z == z and e2c.age_and_size_are_eligible(a, y, z * 1e6) for a, y, z in zip(age, rows.maturity_years, rows.amount_out)]
    return pd.Series(ok, index=rows.index)


def _liquidity_pass(rows: pd.DataFrame, absent: list) -> pd.Series:
    trades = _column(rows, "trades_5d", 99, absent)
    return pd.Series([t == t and e2c.passes_liquidity_screen(t) for t in trades], index=rows.index)


def screen_bonds(rows: pd.DataFrame) -> tuple:
    """A keep flag per row, and a funnel. A blank cell fails its screen. An absent column is named as not applied, and fails nobody.

    rows: date, bond_id, firm_id, maturity_years, amount_out (USD mm), clean_price (per 1), and whichever of the other fields exist.
    """
    keep = pd.Series(True, index=rows.index)
    funnel = []
    steps = (("issuer", _issuer_pass), ("terms", _terms_pass), ("callable", _callable_pass),
             ("maturity", None), ("age_size", _age_size_pass), ("liquidity", _liquidity_pass))
    for name, check in steps:
        absent: list = []
        passed = _maturity_pass(rows, keep) if check is None else check(rows, absent)
        removed = keep & ~passed
        funnel.append((name, int(keep.sum()), int(removed.sum()), ", ".join(absent)))
        keep &= passed
    return keep, pd.DataFrame(funnel, columns=["screen", "tested", "removed", "not_applied"])


# ---------------------------------------------------------------- The book's weights, as fk_des.t0_returns builds them

def book_weights(holdings: pd.DataFrame, returns: pd.DataFrame, long_group: int, short_group: int, hold: int, weighting: str) -> pd.DataFrame:
    """month, asset_id, side, weight of the live book. Each side sums to 1 in any month fk_des.t0_returns has a return."""
    columns = ["month", "asset_id", "side", "weight"]
    if holdings.empty or returns.empty:
        return pd.DataFrame(columns=columns)
    by_month = {m: g.set_index("asset_id") for m, g in returns.groupby("month")}
    members = {key: g.asset_id.tolist() for key, g in holdings.groupby(["month", "group"])}
    frames = []
    for m in pd.period_range(holdings.month.min() + 1, min(returns.month.max(), holdings.month.max() + hold), freq="M"):
        parts: dict = {"long": [], "short": []}
        for age in range(1, hold + 1):
            names_long, names_short = members.get((m - age, long_group)), members.get((m - age, short_group))
            if not names_long or not names_short:
                continue
            column = "ret_first" if age == 1 else "ret"
            long_ret, long_w, _ = fd._side(by_month.get(m), names_long, column, weighting)
            short_ret, short_w, _ = fd._side(by_month.get(m), names_short, column, weighting)
            if np.isfinite(long_ret) and np.isfinite(short_ret):
                parts["long"].append(long_w)
                parts["short"].append(short_w)
        for side, weights in parts.items():
            if weights:
                book = fd._book(weights, len(weights))
                frames.append(pd.DataFrame(dict(month=m, asset_id=book.index, side=side, weight=book.to_numpy())))
    return pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)


# ---------------------------------------------------------------- Financing and fees

def financing_drag(weights: pd.DataFrame, rates: pd.DataFrame, min_coverage: float = .9) -> pd.DataFrame:
    """Plan's P&L block: a long pays repo, a short earns repo less fee. Rates known at the end of the month before the return.

    weights: month, asset_id, side, weight. rates: month, asset_id, repo, fee. Output by month: drag per year's twelfth, and coverage.
    """
    if weights.empty:
        return pd.DataFrame(columns=["drag", "coverage"], index=pd.PeriodIndex([], freq="M"))
    known = rates.assign(month=rates.month + 1)[["month", "asset_id", "repo", "fee"]]
    w = weights.merge(known, on=["month", "asset_id"], how="left")
    long_side, short_side = w[w.side == "long"], w[w.side == "short"]
    rows = []
    for month in sorted(w.month.unique()):
        a, b = long_side[long_side.month == month], short_side[short_side.month == month]
        a_ok, b_ok = a.repo.notna(), b.repo.notna() & b.fee.notna()
        coverage = min(a.weight[a_ok].sum() / a.weight.sum(), b.weight[b_ok].sum() / b.weight.sum())
        if coverage < min_coverage:
            rows.append((month, NAN, coverage))
            continue
        paid = (a.weight[a_ok] * a.repo[a_ok]).sum() / a.weight[a_ok].sum()
        earned = (b.weight[b_ok] * (b.repo[b_ok] - b.fee[b_ok])).sum() / b.weight[b_ok].sum()
        rows.append((month, (paid - earned) * MONTH, coverage))
    return pd.DataFrame(rows, columns=["month", "drag", "coverage"]).set_index("month")


# ---------------------------------------------------------------- Treasury overlay on net duration

def overlay_return(net_duration: float, hedge_duration: float, hedge_return: float, repo: float) -> float:
    """Plan's Treasury line: short the hedge against the book's net duration, financed at repo."""
    return -net_duration / hedge_duration * (hedge_return - repo * MONTH)


def hedge_month(curve_before: e2c.ZeroCurve, curve_after: e2c.ZeroCurve, tenor: float) -> tuple:
    """Total return over a month of a par Treasury bought at the first curve, and its duration then."""
    grid = np.arange(.5, tenor + 1e-9, .5)
    coupon = 2 * (1 - float(curve_before.df(np.array([tenor]))[0])) / float(np.sum(curve_before.df(grid)))
    duration = e2c.dollar_duration(e2c.Bond(coupon, tenor, 2), 0.0, curve_before)
    t, cf = e2c.cash_flows(e2c.Bond(coupon, tenor - MONTH, 2))
    return float(np.sum(cf * curve_after.df(t))) - 1.0, float(duration)


def overlay_series(weights: pd.DataFrame, durations: pd.DataFrame, hedges: pd.DataFrame, min_coverage: float = .9) -> pd.DataFrame:
    """Overlay return by month. Durations known at the end of the month before. hedges: month, hedge_return, hedge_duration, repo."""
    if weights.empty or hedges.empty:
        return pd.DataFrame(columns=["overlay", "net_duration"], index=pd.PeriodIndex([], freq="M"))
    w = weights.merge(durations.assign(month=durations.month + 1), on=["month", "asset_id"], how="left")
    hedge = hedges.set_index("month")
    rows = []
    for month, g in w.groupby("month"):
        net = 0.0
        ok = month in hedge.index
        for side, sign in SIDES.items():
            s = g[g.side == side]
            known = s.duration.notna()
            if s.empty or s.weight[known].sum() / s.weight.sum() < min_coverage:
                ok = False
                break
            net += sign * (s.weight[known] * s.duration[known]).sum() / s.weight[known].sum()
        if not ok:
            rows.append((month, NAN, NAN))
            continue
        h = hedge.loc[month]
        rows.append((month, overlay_return(net, h.hedge_duration, h.hedge_return, h.repo), net))
    return pd.DataFrame(rows, columns=["month", "overlay", "net_duration"]).set_index("month")


def monthly_hedges(rates: pd.DataFrame, months, tenor: float = 5.0, max_stale_days: int = 7) -> pd.DataFrame:
    """Hedge return from each month's last date to the next one's, with repo at the shortest yield of the first date."""
    r = rates.assign(date=pd.to_datetime(rates.date))
    last = r.groupby(r.date.dt.to_period("M")).date.max()
    rows = []
    for month in months:
        before, after = last.get(month - 1), last.get(month)
        if before is None or after is None:
            continue
        a, b = fd.curve_asof(r, before, max_stale_days), fd.curve_asof(r, after, max_stale_days)
        if a is None or b is None:
            continue
        ret, duration = hedge_month(a, b, tenor)
        day = r[r.date == before].sort_values("tenor")
        rows.append((month, ret, duration, float(day.par_yield.iloc[0])))
    return pd.DataFrame(rows, columns=["month", "hedge_return", "hedge_duration", "repo"])


def bond_durations(bonds: pd.DataFrame, rates: pd.DataFrame, max_stale_days: int = 7) -> pd.DataFrame:
    """month, asset_id, duration in years, at each bond's own Z-spread. NaN if a curve or a spread is missing."""
    r = rates.assign(date=pd.to_datetime(rates.date))
    curves = {day: fd.curve_asof(r, day, max_stale_days) for day in pd.to_datetime(bonds.date).unique()}
    out = []
    for row in bonds.itertuples():
        curve = curves[pd.Timestamp(row.date)]
        duration = NAN
        if curve is not None and row.full_price > 0 and row.maturity_years > 0:
            bond = e2c.Bond(row.coupon, row.maturity_years, row.freq)
            z = e2c.z_spread(row.full_price, bond, curve)
            if z == z:
                duration = e2c.dollar_duration(bond, z, curve) / row.full_price
        out.append((pd.Timestamp(row.date).to_period("M"), row.bond_id, duration))
    return pd.DataFrame(out, columns=["month", "asset_id", "duration"])


# ---------------------------------------------------------------- Costs and splits

def bond_day_costs(trades: pd.DataFrame) -> pd.DataFrame:
    """Round-trip cost per bond per day with customer buys and sells: mean buy less mean sell, over the midpoint."""
    columns = ["bond_id", "day", "cost"]
    t = trades.dropna(subset=["is_customer_buy", "price"])
    if t.empty:
        return pd.DataFrame(columns=columns)
    t = t.assign(day=pd.to_datetime(t.execution_time).dt.normalize(), buy=t.is_customer_buy.astype(bool))
    wide = t.groupby(["bond_id", "day", "buy"]).price.mean().unstack("buy").reindex(columns=[True, False]).dropna().reset_index()
    if wide.empty:
        return pd.DataFrame(columns=columns)
    return wide.assign(cost=(wide[True] - wide[False]) / ((wide[True] + wide[False]) / 2))[columns]


def median_split(table: pd.DataFrame, upper: str, lower: str) -> pd.DataFrame:
    """month, asset_id, label. At or above the month's median is upper. A blank value leaves."""
    t = table.dropna(subset=["value"])
    median = t.groupby("month").value.transform("median")
    return t.assign(label=np.where(t.value >= median, upper, lower))[["month", "asset_id", "label"]]


def holdings_from_study(study: fd.DesStudy) -> tuple:
    """The holdings run_des_study built: bonds, then stocks."""
    groups = study.firm_des.dropna(subset=["quintile"])[["month", "firm_id", "quintile"]].rename(columns={"quintile": "group"})
    held = study.bond_des[study.bond_des.des_bp.notna()].merge(groups, on=["month", "firm_id"])
    return (held.rename(columns={"bond_id": "asset_id"})[["month", "asset_id", "group"]],
            groups.rename(columns={"firm_id": "asset_id"})[["month", "asset_id", "group"]])


# ---------------------------------------------------------------- Dead names

def apply_end_events(bonds: pd.DataFrame, equities: pd.DataFrame, events: pd.DataFrame) -> tuple:
    """Add the last return a dead name earned, which fk_des would otherwise lose (its default 11).

    A bond with no price in the month after its last, and an event after that last price, gets realised_recovery as its last
    price, one month on. A stock gets delisting_return on the next business day. Both only move returns after the name's last
    known price, so no sort uses them. Events after the last price with no amount add nothing, and those names stay missing.
    """
    new_bonds, new_stocks = [], []
    if not events.empty:
        last_bonds = bonds.sort_values("date").groupby("bond_id", sort=False).tail(1)
        last_stocks = equities.sort_values("date").groupby("firm_id", sort=False).tail(1).set_index("firm_id")
        for e in events.sort_values("event_date").drop_duplicates("issuer_id").itertuples():
            month = pd.Timestamp(e.event_date).to_period("M")
            if e.realised_recovery == e.realised_recovery:
                for b in last_bonds[last_bonds.firm_id == e.issuer_id].to_dict("records"):
                    if pd.Timestamp(b["date"]).to_period("M") < month:
                        day = (pd.Timestamp(b["date"]).to_period("M") + 1).end_time.normalize()
                        new_bonds.append({**b, "date": day, "full_price": e.realised_recovery / 100, "coupon_paid": 0.0,
                                          **({"entry_price": NAN} if "entry_price" in b else {})})
            if e.delisting_return == e.delisting_return and e.issuer_id in last_stocks.index:
                s = last_stocks.loc[e.issuer_id]
                if pd.Timestamp(s.date) < pd.Timestamp(e.event_date):
                    new_stocks.append({**s.to_dict(), "firm_id": e.issuer_id, "date": pd.Timestamp(s.date) + pd.offsets.BDay(1),
                                       "stock_close": s.stock_close * max(1 + e.delisting_return, _MIN_TOTAL_RETURN),
                                       "split_factor": 1.0, "dividend": 0.0})
    b = pd.concat([bonds, pd.DataFrame(new_bonds)], ignore_index=True) if new_bonds else bonds
    s = pd.concat([equities, pd.DataFrame(new_stocks)], ignore_index=True) if new_stocks else equities
    return b, s, dict(bond_recoveries=len(new_bonds), stock_delistings=len(new_stocks))


# ---------------------------------------------------------------- Verdict

def judge(months: int, median_firms: float, gap_q1: float, gap_q5: float, ratio_q1: float, ratio_q5: float, premium: float, premium_t: float,
          stock_premium: float, min_months: int = 60, min_firms: int = 25, min_t: float = 1.96) -> Verdict:
    """F10's sign rule, plus MINE 1 and 2 of the module docstring."""
    if months < min_months:
        return Verdict(NOT_JUDGED, f"{months} months in the window, below {min_months}")
    if not median_firms >= min_firms:
        return Verdict(NOT_JUDGED, f"median {median_firms} firms sorted, below {min_firms}")
    named = dict(gap_q1=gap_q1, gap_q5=gap_q5, ratio_q1=ratio_q1, ratio_q5=ratio_q5, premium=premium, premium_t=premium_t, stock_premium=stock_premium)
    blank = [k for k, v in named.items() if not np.isfinite(v)]
    if blank:
        return Verdict(NOT_JUDGED, "could not compute: " + ", ".join(blank))
    wrong = [text for text, ok in (("Q1 gap not below 0", gap_q1 < 0), ("Q5 gap not above 0", gap_q5 > 0), ("Q1 price ratio not below 1", ratio_q1 < 1),
                                   ("Q5 price ratio not above 1", ratio_q5 > 1), ("bond premium not above 0", premium > 0),
                                   (f"bond premium t below {min_t}", premium_t >= min_t), ("stock premium not above 0", stock_premium > 0)) if not ok]
    return Verdict(NOT_REPRODUCED, "; ".join(wrong)) if wrong else Verdict(REPRODUCED, "all signs match, bond premium t passes")


def overall(verdicts: list) -> str:
    if NOT_JUDGED in verdicts:
        return NOT_JUDGED
    return NOT_REPRODUCED if NOT_REPRODUCED in verdicts else REPRODUCED


def stop_rule(net_large_annual: float) -> str:
    """The plan's stop: net bond return at measured costs zero or negative at the large-bond end."""
    if not np.isfinite(net_large_annual):
        return "NOT JUDGED"
    return "STOP" if net_large_annual <= 0 else "CONTINUE"
