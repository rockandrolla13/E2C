"""The published bond-against-stock gap (DES) and its monthly rank book, trade T0. Work package WP6a.

Steps 1, 2, 7, 11 variant, 13a, 24a and trade T0 of finkelstein_replication_plan.pdf.
Step 17's price cleaning stays upstream. Its Z-spread is not used, because the published gap is defined on yields.
Pure logic: no file, no environment variable, no vendor. Units: decimals, years, USD per share, USD mm for firm totals.
Prices are full prices per 1 of face, as in e2c_bond. Spreads are in bp. Recovery is 0.35 of face, paid at default.
Coupon frequency and maturity are inputs. Day count belongs upstream, since the full price already holds accrued interest.

Inputs                                        Outputs
  run_des_study(bonds, equities,                DesStudy.bond_des          DES, CS_D, CS_E, price ratio, status, per bond
                accounts, rates, config)        DesStudy.firm_des          firm DES, its inputs and quintile, per month
                                                DesStudy.sort_report       firms and status of each month's sort
                                                DesStudy.returns           long-short gross, cost, net, by month
                                                DesStudy.summary           means by leg, hold and weighting
                                                DesStudy.quintile_profile  mean DES and price ratio by quintile, for F10's shape
                                                DesStudy.missing           every NaN cause, with a count

One function per step: equity_panel 1, curve_asof 2, debt_per_share 7, accounts_asof 7, payout_delta 13a,
rolling_equity_vol 11, bond_des 24a, firm_des 24a, quintile_sort 24a, bond_month_returns and stock_month_returns T0,
t0_returns T0. A survival curve comes from fk_model.des_survival and a price from fk_value.fk_bond_price.

Input tables. One row per key. A missing value is NaN, and it stays NaN. Filter bonds with the plan's screens first.
  bonds: one row per bond per month. Key bond_id, month of date
    date            datetime  pricing date, the last in its month. Sort and return months come from it
    bond_id         str       bond
    firm_id         str       issuer, the link to the other tables
    coupon          float     decimal a year
    freq            int       coupons a year
    maturity_years  float     years left on date
    full_price      float     full price per 1 of face, cleaned by step 17
    coupon_paid     float     coupon paid in the month ending at date, per 1 of face. 0.0 if none
    amount_out      float     face outstanding, USD mm
    entry_price     float     optional. Full price on the execution day after date, per 1 of face
  equities: one row per firm per trading day. Key firm_id, date
    date            datetime  trading day
    firm_id         str       issuer
    stock_close     float     closing price as traded, USD/share, not adjusted
    split_factor    float     new shares per old share on the ex-date, 1.0 on any other day
    dividend        float     cash dividend by ex-date, USD/share. 0.0 if none
    shares_out      float     common shares known on date, count, on the same split basis as stock_close
  accounts: one row per filing
    firm_id            str       issuer
    period_end         datetime  end of the accounting period
    available_date     datetime  day the filing became public. NaT means the filing is never used
    total_liabilities  float     USD mm
    dividends          float     USD mm, trailing 12 months, not year to date
    interest           float     USD mm, trailing 12 months
    repurchases        float     USD mm, trailing 12 months
  rates: one row per date per tenor. A NaN makes that date's curve unusable, so leave out tenors that do not exist
    date       datetime  quote date
    tenor      float     years
    par_yield  float     Treasury par yield, decimal, semiannual

[ADAPTATION] All of this is an adaptation of Chen, Chen and Li (2026). Nothing here is in Finkelstein's deck.
No copy of that paper was on hand. Every detail comes from what the plan records about it (pp.2015-2016, p.2023).
Running the two legs together is the plan's own addition, so each leg is reported apart.

MISSING. The plan does not settle these. Each has my default, as a named parameter where one fits:
  1. Yield compounding. DesConfig.yield_freq = None, continuous. Only that reproduces E3, because E3 was made with
     Z-spreads, and on a flat curve the two gaps are equal. Semiannual yields give -159 and -227 bp on GX, not -149 and -213.
  2. Fewest returns for the 3-year vol. vol_min_obs = 504. Estimator: e2c_bond's sample standard deviation of daily x_t.
  3. The rate r in step 13a's drift. drift_tenor = None, the zero rate at the bond's maturity.
  4. What the 2-month accounting lag runs from. Here, from available_date. accounts_lag_months = 2.
     The oldest filing still in use: accounts_max_age_months = 18, counted from the day it became usable.
  5. Payout. The flows are taken as trailing 12 months, and a negative sum stops at payout_floor = 0.0.
  6. Breakpoints and thin months. All firms sorted that month, and no sort below min_firms = 5.
  7. Holds. Overlapping monthly cohorts, averaged. A month with fewer than hold cohorts averages those it has.
  8. Value weights. A name's value at the end of the month before each return, so weights drift with price.
     Bond value is amount_out * full_price. Stock value is stock_close * shares_out.
  9. Execution. Step 30 trades one day after the signal. execution_lag_days = 1 skips that day of the stock's first
     month. Bonds use entry_price. Without that column the signal's own price starts the return, which step 30 warns
     against, and DesStudy.missing says so.
  10. Stale data. max_stale_days = 7 for a stock price or a curve before the pricing date.
  11. Missing returns. A name with no return leaves that month's average and is counted. No delisting or default
      return is imputed, so a bond that stops pricing can flatter the book.
  12. Costs. Half the round trip on each unit of weight traded, side by side, with no netting across sides.
      Drift inside the month does not count as trading. The last exit is not charged.
  13. Bond return. Total return, not excess of a Treasury. The two sides cancel the cash rate, but not any duration gap.

Not built here: the FinD variant of step 7, the Treasury overlay, financing and borrow fees, sibling_confirms, the
impvol skip, hold-off bands, splits by bond size and fee, t-statistics. The plan's stop rule on large bonds needs real
data, and the bond leg can be rerun on a filtered table with its own cost. So can F10, which is not reproduced here.
"""
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import fk_model as fk
import fk_value as v
from fk_value import e2c

NAN = float("nan")
YIELD_BOUNDS = (-0.5, 20.0)   # as e2c_bond.z_spread
BOND_COLUMNS = ("date", "bond_id", "firm_id", "coupon", "freq", "maturity_years", "full_price", "coupon_paid", "amount_out")
EQUITY_COLUMNS = ("date", "firm_id", "stock_close", "split_factor", "dividend", "shares_out")
ACCOUNT_COLUMNS = ("firm_id", "period_end", "available_date", "total_liabilities", "dividends", "interest", "repurchases")
RATE_COLUMNS = ("date", "tenor", "par_yield")
RETURN_COLUMNS = ["month", "gross", "cost", "net", "n_long", "n_short", "n_cohorts", "n_missing"]


class DesConfig(NamedTuple):
    """Published settings first (plan steps 13a, 24a). Costs are decimals per round trip. NaN means not supplied, so net is NaN."""
    lbar: float = 0.5
    lam: float = 0.3
    recovery: float = 0.35
    payout_cap: float = 0.15
    payout_floor: float = 0.0
    vol_years: int = 3
    vol_min_obs: int = 504
    periods_per_year: int = 252
    accounts_lag_months: int = 2
    accounts_max_age_months: int = 18
    yield_freq: Optional[int] = None
    drift_tenor: Optional[float] = None
    n_groups: int = 5
    min_firms: int = 5
    holds: tuple = (1, 3, 6)
    weightings: tuple = ("equal", "value")
    bond_round_trip_cost: float = NAN
    stock_round_trip_cost: float = NAN
    execution_lag_days: int = 1
    max_stale_days: int = 7
    steps_per_year: int = v.STEPS_PER_YEAR


class BondDes(NamedTuple):
    """status is ok, or missing_price, _stock, _debt, _vol, _payout, _curve, _terms, or no_model_value, no_yield."""
    des_bp: float
    cs_d_bp: float
    cs_e_bp: float
    model_price: float
    price_ratio: float
    status: str


class DesStudy(NamedTuple):
    bond_des: pd.DataFrame
    firm_des: pd.DataFrame
    sort_report: pd.DataFrame
    returns: pd.DataFrame
    summary: pd.DataFrame
    quintile_profile: pd.DataFrame
    missing: pd.DataFrame


# ---------------------------------------------------------------- Steps 1 and 2: market inputs

def equity_panel(equities: pd.DataFrame) -> pd.DataFrame:
    """Step 1. Adds x, the daily log return with dividends, adjusted for splits only. A NaN price costs two returns."""
    p = equities.sort_values(["firm_id", "date"]).copy()
    previous = p.groupby("firm_id").stock_close.shift(1)
    x = np.log((p.stock_close + p.dividend).where(p.stock_close > 0) * p.split_factor / previous.where(previous > 0))
    return p.assign(x=x)


def curve_asof(rates: pd.DataFrame, on: pd.Timestamp, max_stale_days: int = 7) -> Optional[e2c.ZeroCurve]:
    """Step 2. The curve from the last quote date at or before on. None if too old, or if any par yield is NaN."""
    known = rates.date[rates.date <= on]
    if known.empty or (on - known.max()).days > max_stale_days:
        return None
    day = rates[rates.date == known.max()].sort_values("tenor")
    if day.par_yield.isna().any():
        return None
    return e2c.zero_curve_from_par_yields(day.tenor.to_numpy(), day.par_yield.to_numpy())


# ---------------------------------------------------------------- Steps 7, 11, 13a: firm inputs

def debt_per_share(total_liabilities: float, shares: float) -> float:
    """Step 7, default form. Liabilities in USD mm, shares as a count, the result in USD per share. NaN stays NaN."""
    if not shares > 0:
        return NAN
    return e2c.debt_per_share(total_liabilities * 1e6, shares)


def payout_delta(dividends: float, interest: float, repurchases: float, shares: float, S: float, D: float,
                 cap: float = 0.15, floor: float = 0.0) -> float:
    """Step 13a. (dividends + interest + repurchases) / (S + D), per share, capped. Flows in USD mm, NaN stays NaN."""
    if not (shares > 0 and S + D > 0):
        return NAN
    return float(np.clip((dividends + interest + repurchases) * 1e6 / shares / (S + D), floor, cap))


def rolling_equity_vol(x: pd.Series, asof: pd.Timestamp, years: int = 3, min_obs: int = 504, periods_per_year: int = 252) -> float:
    """Step 11 variant. Annualised vol of daily log returns over the years up to and including asof. NaN if too few."""
    inside = x[(x.index > asof - pd.DateOffset(years=years)) & (x.index <= asof)].to_numpy()
    return e2c.historical_equity_vol(inside, window=max(len(inside), 1), min_obs=min_obs, periods_per_year=periods_per_year)


def accounts_asof(accounts: pd.DataFrame, requests: pd.DataFrame, lag_months: int = 2, max_age_months: int = 18) -> pd.DataFrame:
    """Accounts usable on each requests row (firm_id, date). Usable means available_date + lag_months <= date.

    The latest period wins, and a later filing for one period replaces the earlier one. A late amendment of an older
    period does not displace newer accounts. A NaN in the chosen filing stays NaN, with no fallback to an older one.
    """
    a = accounts.dropna(subset=["available_date", "period_end"])
    a = a.assign(usable_from=a.available_date + pd.DateOffset(months=lag_months)).sort_values(["usable_from", "period_end"])
    a = a[a.period_end >= a.groupby("firm_id").period_end.cummax()]
    out = pd.merge_asof(requests.sort_values("date"), a, left_on="date", right_on="usable_from", by="firm_id")
    too_old = out.usable_from + pd.DateOffset(months=max_age_months) < out.date
    values = ["total_liabilities", "dividends", "interest", "repurchases"]
    out[values] = out[values].where(~too_old)
    return out


# ---------------------------------------------------------------- Step 24a: one bond

def _yield(price: float, bond: e2c.Bond, freq: Optional[int]) -> float:
    t, cf = e2c.cash_flows(bond)
    if freq is None:
        return brentq(lambda y: np.sum(cf * np.exp(-y * t)) - price, *YIELD_BOUNDS, xtol=1e-10)
    return brentq(lambda y: np.sum(cf * (1 + y / freq) ** (-freq * t)) - price, *YIELD_BOUNDS, xtol=1e-10)


def _missing(full, bond, S, D, sigma_s, delta, curve) -> Optional[str]:
    if not full > 0:
        return "missing_price"
    if not (bond.maturity > 0 and bond.freq > 0 and np.isfinite(bond.coupon)):
        return "missing_terms"
    if not S > 0:
        return "missing_stock"
    if not D > 0:
        return "missing_debt"
    if not sigma_s > 0:
        return "missing_vol"
    if not np.isfinite(delta):
        return "missing_payout"
    return "missing_curve" if curve is None else None


def bond_des(full: float, bond: e2c.Bond, S: float, D: float, sigma_s: float, delta: float, curve: Optional[e2c.ZeroCurve],
             lbar: float = 0.5, lam: float = 0.3, recovery: float = 0.35, yield_freq: Optional[int] = None,
             drift_tenor: Optional[float] = None, steps_per_year: int = v.STEPS_PER_YEAR) -> BondDes:
    """Step 24a. DES = CS_D - CS_E, in bp. Each spread is a yield less the yield of a synthetic Treasury with the same flows.

    CS_D uses the market price. CS_E uses step 15's price on step 13a's survival. The Treasury is the same in both, so it
    cancels in DES. Positive DES means the bond is wider than the stock implies.
    """
    status = _missing(full, bond, S, D, sigma_s, delta, curve)
    if status is not None:
        return BondDes(NAN, NAN, NAN, NAN, NAN, status)
    barrier = lbar * D
    tenor = bond.maturity if drift_tenor is None else drift_tenor
    r, sig = float(-np.log(curve.df(tenor)) / tenor), fk.asset_vol_fs(sigma_s, S, D)

    def q(t):
        return np.array([fk.des_survival(float(x), S + barrier, barrier, sig, r, delta, lam) for x in np.atleast_1d(t)])

    with np.errstate(over="ignore", invalid="ignore"):
        model = v.fk_bond_price(bond, q, curve, recovery, steps_per_year)
    if not model > 0:
        return BondDes(NAN, NAN, NAN, NAN, NAN, "no_model_value")
    t, cf = e2c.cash_flows(bond)
    try:
        y_market, y_model = _yield(full, bond, yield_freq), _yield(model, bond, yield_freq)
        y_treasury = _yield(float(np.sum(cf * curve.df(t))), bond, yield_freq)
    except ValueError:
        return BondDes(NAN, NAN, NAN, model, model / full, "no_yield")
    return BondDes((y_market - y_model) * 1e4, (y_market - y_treasury) * 1e4, (y_model - y_treasury) * 1e4, model, model / full, "ok")


# ---------------------------------------------------------------- Step 24a: firm and sort

def firm_des(des_bp, lagged_value) -> float:
    """Average of a firm's bonds, weighted by lagged bond value. A bond without both is left out. NaN if none has both."""
    des, value = np.asarray(des_bp, dtype=float), np.asarray(lagged_value, dtype=float)
    use = np.isfinite(des) & (value > 0)
    return float(np.average(des[use], weights=value[use])) if use.any() else NAN


def quintile_sort(values: pd.Series, n_groups: int = 5, min_firms: int = 5) -> pd.Series:
    """One month's sort. Group n_groups has the highest values. NaN stays out. All NaN if fewer than min_firms have a value."""
    valid = values.dropna()
    if len(valid) < min_firms:
        return pd.Series(NAN, index=values.index, dtype=float)
    return np.ceil(valid.rank() * n_groups / len(valid)).reindex(values.index)


# ---------------------------------------------------------------- T0: returns by name

def _with_month(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(month=frame.date.dt.to_period("M"))


def bond_month_returns(bonds: pd.DataFrame) -> pd.DataFrame:
    """(P_t + coupon_t) / P_{t-1} - 1 over consecutive months only. ret_first starts from entry_price, if the column exists."""
    b = _with_month(bonds)
    entry = b.entry_price if "entry_price" in b else b.full_price
    previous = pd.DataFrame({"bond_id": b.bond_id, "month": b.month + 1, "previous": b.full_price, "entry": entry,
                             "lag_value": b.amount_out * b.full_price})
    out = b.merge(previous, on=["bond_id", "month"], how="left")
    paid = out.full_price + out.coupon_paid
    return pd.DataFrame({"month": out.month, "asset_id": out.bond_id, "ret": paid / out.previous - 1,
                         "ret_first": paid / out.entry - 1, "lag_value": out.lag_value})


def _compound(days: pd.DataFrame) -> pd.Series:
    groups = days.assign(bad=days.x.isna()).groupby(["firm_id", "month"])
    return np.expm1(groups.x.sum().where(~groups.bad.max()))


def stock_month_returns(panel: pd.DataFrame, execution_lag_days: int = 1) -> pd.DataFrame:
    """Compounds step 1's x by month, NaN if any day is NaN. ret_first skips the first execution_lag_days of the month."""
    p = _with_month(panel)
    day = p.groupby(["firm_id", "month"]).cumcount()
    last = p.drop_duplicates(["firm_id", "month"], keep="last")
    lag_value = pd.DataFrame({"firm_id": last.firm_id, "month": last.month + 1, "lag_value": last.stock_close * last.shares_out / 1e6})
    out = _compound(p).rename("ret").to_frame().join(_compound(p[day >= execution_lag_days]).rename("ret_first")).reset_index()
    out = out.merge(lag_value, on=["firm_id", "month"], how="left").rename(columns={"firm_id": "asset_id"})
    return out[["month", "asset_id", "ret", "ret_first", "lag_value"]]


# ---------------------------------------------------------------- T0: long-short book

def _side(table: Optional[pd.DataFrame], names: list, column: str, weighting: str) -> tuple:
    """Return, weights and missing count of one side of one cohort in one month. NaN if no name has a return."""
    if table is None:
        return NAN, pd.Series(dtype=float), len(names)
    held = table.reindex(names)
    use = held[column].notna()
    if weighting == "value":
        use &= held.lag_value > 0
    if not use.any():
        return NAN, pd.Series(dtype=float), len(names)
    w = held.lag_value[use] if weighting == "value" else pd.Series(1.0, index=held.index[use])
    w = w / w.sum()
    return float((w * held[column][use]).sum()), w, int((~use).sum())


def _book(parts: list, n: int) -> pd.Series:
    return pd.concat(parts).groupby(level=0).sum() / n


def _traded(new: pd.Series, old: pd.Series) -> float:
    return float(new.sub(old, fill_value=0.0).abs().sum())


def t0_returns(holdings: pd.DataFrame, returns: pd.DataFrame, long_group: int, short_group: int, hold: int, weighting: str,
               round_trip_cost: float) -> pd.DataFrame:
    """T0, one leg. Each month's gross return averages the long-short return of the last hold cohorts.

    holdings has month (of formation), asset_id, group. returns has month, asset_id, ret, ret_first, lag_value.
    A cohort earns ret_first in its first month, the month after formation, and ret after that.
    cost = round_trip_cost / 2 * weight traded on both sides, so a full turnover of both sides costs 2 round trips.
    A month with no cohort, or none with both sides priced, is NaN, and the next month buys the whole book again.
    """
    if weighting not in ("equal", "value"):
        raise ValueError(f"unknown weighting: {weighting}")
    if round_trip_cost < 0:
        raise ValueError("round_trip_cost must not be negative")
    if holdings.empty or returns.empty:
        return pd.DataFrame(columns=RETURN_COLUMNS)
    by_month = {m: g.set_index("asset_id") for m, g in returns.groupby("month")}
    members = {key: g.asset_id.tolist() for key, g in holdings.groupby(["month", "group"])}
    first, last = holdings.month.min(), holdings.month.max()
    old_long, old_short = pd.Series(dtype=float), pd.Series(dtype=float)
    rows = []
    for m in pd.period_range(first + 1, min(returns.month.max(), last + hold), freq="M"):
        spreads, long_parts, short_parts, n_missing = [], [], [], 0
        for age in range(1, hold + 1):
            long_names, short_names = members.get((m - age, long_group)), members.get((m - age, short_group))
            if not long_names or not short_names:
                continue
            column = "ret_first" if age == 1 else "ret"
            long_ret, long_w, long_gone = _side(by_month.get(m), long_names, column, weighting)
            short_ret, short_w, short_gone = _side(by_month.get(m), short_names, column, weighting)
            n_missing += long_gone + short_gone
            if np.isfinite(long_ret) and np.isfinite(short_ret):
                spreads.append(long_ret - short_ret)
                long_parts.append(long_w)
                short_parts.append(short_w)
        if not spreads:
            rows.append((m, NAN, NAN, NAN, 0, 0, 0, n_missing))
            old_long, old_short = pd.Series(dtype=float), pd.Series(dtype=float)
            continue
        new_long, new_short = _book(long_parts, len(spreads)), _book(short_parts, len(spreads))
        gross = float(np.mean(spreads))
        cost = round_trip_cost / 2 * (_traded(new_long, old_long) + _traded(new_short, old_short))
        rows.append((m, gross, cost, gross - cost, len(new_long), len(new_short), len(spreads), n_missing))
        old_long, old_short = new_long, new_short
    return pd.DataFrame(rows, columns=RETURN_COLUMNS)


# ---------------------------------------------------------------- The whole study

def _require(frame: pd.DataFrame, columns: tuple, name: str) -> None:
    absent = [c for c in columns if c not in frame]
    if absent:
        raise ValueError(f"{name} lacks columns: {absent}")


def _dated(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    return frame.assign(**{c: pd.to_datetime(frame[c]).astype("datetime64[ns]") for c in columns})


def _firm_inputs(bonds: pd.DataFrame, panel: pd.DataFrame, accounts: pd.DataFrame, config: DesConfig) -> pd.DataFrame:
    """Everything a firm brings to step 24a on each pricing date. No row here looks past its date."""
    requests = bonds[["firm_id", "date"]].drop_duplicates()
    stock = pd.merge_asof(requests.sort_values("date"), panel[["date", "firm_id", "stock_close", "shares_out"]].sort_values("date"),
                          on="date", by="firm_id", tolerance=pd.Timedelta(days=config.max_stale_days))
    books = accounts_asof(accounts, requests, config.accounts_lag_months, config.accounts_max_age_months)
    f = stock.merge(books, on=["firm_id", "date"], how="left")
    returns = {firm: g.set_index("date").x for firm, g in panel.groupby("firm_id")}
    f["S"] = f.stock_close
    f["D"] = [debt_per_share(a, b) for a, b in zip(f.total_liabilities, f.shares_out)]
    f["delta"] = [payout_delta(a, b, c, d, e, g, config.payout_cap, config.payout_floor)
                  for a, b, c, d, e, g in zip(f.dividends, f.interest, f.repurchases, f.shares_out, f.S, f.D)]
    f["sigma_s"] = [rolling_equity_vol(returns[firm], day, config.vol_years, config.vol_min_obs, config.periods_per_year)
                    if firm in returns else NAN for firm, day in zip(f.firm_id, f.date)]
    return f[["firm_id", "date", "S", "D", "delta", "sigma_s"]]


def _bond_table(bonds: pd.DataFrame, inputs: pd.DataFrame, rates: pd.DataFrame, config: DesConfig) -> pd.DataFrame:
    curves = {day: curve_asof(rates, day, config.max_stale_days) for day in bonds.date.unique()}
    b = bonds.merge(inputs, on=["firm_id", "date"], how="left")
    results = [bond_des(row.full_price, e2c.Bond(row.coupon, row.maturity_years, row.freq), row.S, row.D, row.sigma_s, row.delta,
                        curves[row.date], config.lbar, config.lam, config.recovery, config.yield_freq, config.drift_tenor,
                        config.steps_per_year) for row in b.itertuples()]
    return pd.concat([b[["date", "month", "bond_id", "firm_id"]], pd.DataFrame(results, columns=BondDes._fields)], axis=1)


def _firm_table(bond_table: pd.DataFrame, inputs: pd.DataFrame, config: DesConfig) -> pd.DataFrame:
    rows = [(month, firm, g.date.max(), firm_des(g.des_bp, g.lag_value), firm_des(g.price_ratio, g.lag_value), len(g),
             int((g.des_bp.notna() & (g.lag_value > 0)).sum())) for (month, firm), g in bond_table.groupby(["month", "firm_id"])]
    f = pd.DataFrame(rows, columns=["month", "firm_id", "date", "des_bp", "price_ratio", "n_bonds", "n_bonds_used"])
    f = f.merge(inputs, on=["firm_id", "date"], how="left")
    f["quintile"] = f.groupby("month").des_bp.transform(lambda s: quintile_sort(s, config.n_groups, config.min_firms))
    return f


def _sort_report(bond_table: pd.DataFrame, firm_table: pd.DataFrame, config: DesConfig) -> pd.DataFrame:
    rows = []
    for month in pd.period_range(bond_table.month.min(), bond_table.month.max(), freq="M"):
        firms = firm_table[firm_table.month == month]
        n_valid = int(firms.des_bp.notna().sum())
        status = "empty" if firms.empty else "too_few_firms" if n_valid < config.min_firms else "ok"
        rows.append((month, len(firms), n_valid, status))
    return pd.DataFrame(rows, columns=["month", "n_firms", "n_valid", "status"])


def _all_returns(bond_holdings, bond_rets, stock_holdings, stock_rets, config: DesConfig) -> pd.DataFrame:
    top = config.n_groups
    legs = (("bond", bond_holdings, bond_rets, top, 1, config.bond_round_trip_cost),
            ("stock", stock_holdings, stock_rets, 1, top, config.stock_round_trip_cost))
    frames = [t0_returns(holdings, rets, long_group, short_group, hold, weighting, cost).assign(leg=leg, hold=hold, weighting=weighting)
              for leg, holdings, rets, long_group, short_group, cost in legs for hold in config.holds for weighting in config.weightings]
    return pd.concat(frames, ignore_index=True)[["leg", "hold", "weighting"] + RETURN_COLUMNS]


def _summary(returns: pd.DataFrame) -> pd.DataFrame:
    rows = [(leg, hold, weighting, int(g.gross.notna().sum()), int(g.gross.isna().sum()), g.gross.mean(), g.net.mean(), g.cost.mean(),
             12 * g.gross.mean(), 12 * g.net.mean()) for (leg, hold, weighting), g in returns.groupby(["leg", "hold", "weighting"])]
    return pd.DataFrame(rows, columns=["leg", "hold", "weighting", "months", "nan_months", "gross_mean", "net_mean", "cost_mean",
                                       "gross_annual", "net_annual"])


def _quintile_profile(firm_table: pd.DataFrame) -> pd.DataFrame:
    """Time-series mean of each month's cross-sectional mean, for F10's shape."""
    monthly = firm_table.dropna(subset=["quintile"]).groupby(["month", "quintile"])[["des_bp", "price_ratio"]].mean().reset_index()
    return monthly.groupby("quintile").agg(des_bp=("des_bp", "mean"), price_ratio=("price_ratio", "mean"), months=("month", "count")).reset_index()


def _missing_report(bonds, accounts, bond_table, sort_report, returns) -> pd.DataFrame:
    rows = [("bond", status, n, "") for status, n in bond_table.status[bond_table.status != "ok"].value_counts().items()]
    dropped = int((bond_table.des_bp.notna() & ~(bond_table.lag_value > 0)).sum())
    if dropped:
        rows.append(("firm", "no_lagged_value", dropped, ""))
    rows += [("sort", status, n, "") for status, n in sort_report.status[sort_report.status != "ok"].value_counts().items()]
    if accounts.available_date.isna().any():
        rows.append(("accounts", "no_available_date", int(accounts.available_date.isna().sum()), ""))
    if "entry_price" not in bonds:
        rows.append(("bond_entry", "same_price_in_signal_and_return", len(bonds), ""))
    for (leg, hold, weighting), g in returns.groupby(["leg", "hold", "weighting"]):
        detail = f"hold={hold},{weighting}"
        rows.append((f"{leg}_returns", "missing_return", int(g.n_missing.sum()), detail))
        rows.append((f"{leg}_returns", "nan_month", int(g.gross.isna().sum()), detail))
    out = pd.DataFrame(rows, columns=["stage", "reason", "n", "detail"])
    return out[out.n > 0].reset_index(drop=True)


def _empty_study() -> DesStudy:
    return DesStudy(pd.DataFrame(columns=["date", "month", "bond_id", "firm_id", *BondDes._fields, "lag_value"]),
                    pd.DataFrame(columns=["month", "firm_id", "date", "des_bp", "price_ratio", "n_bonds", "n_bonds_used",
                                          "S", "D", "delta", "sigma_s", "quintile"]),
                    pd.DataFrame(columns=["month", "n_firms", "n_valid", "status"]),
                    pd.DataFrame(columns=["leg", "hold", "weighting"] + RETURN_COLUMNS),
                    pd.DataFrame(columns=["leg", "hold", "weighting", "months", "nan_months", "gross_mean", "net_mean",
                                          "cost_mean", "gross_annual", "net_annual"]),
                    pd.DataFrame(columns=["quintile", "des_bp", "price_ratio", "months"]),
                    pd.DataFrame(columns=["stage", "reason", "n", "detail"]))


def run_des_study(bonds: pd.DataFrame, equities: pd.DataFrame, accounts: pd.DataFrame, rates: pd.DataFrame,
                  config: DesConfig = DesConfig()) -> DesStudy:
    """Steps 1, 2, 7, 11, 13a and 24a, then T0, from the tables in the module docstring. Nothing reads past its pricing date.

    Bond leg: long the top quintile's bonds, short the bottom's. Stock leg: long the bottom's stocks, short the top's.
    Firms are sorted. A bond joins its firm's group if its own DES is finite on the sort date.
    """
    _require(bonds, BOND_COLUMNS, "bonds")
    _require(equities, EQUITY_COLUMNS, "equities")
    _require(accounts, ACCOUNT_COLUMNS, "accounts")
    _require(rates, RATE_COLUMNS, "rates")
    if bonds.empty:
        return _empty_study()
    bonds = _with_month(_dated(bonds, "date"))
    if bonds.duplicated(["bond_id", "month"]).any():
        raise ValueError("bonds has two rows for one bond_id in one month")
    equities = _dated(equities, "date")
    if equities.duplicated(["firm_id", "date"]).any():
        raise ValueError("equities has two rows for one firm_id on one date")
    accounts, rates = _dated(accounts, "period_end", "available_date"), _dated(rates, "date")

    panel = equity_panel(equities)
    inputs = _firm_inputs(bonds, panel, accounts, config)
    bond_rets = bond_month_returns(bonds)
    stock_rets = stock_month_returns(panel, config.execution_lag_days)
    bond_table = _bond_table(bonds, inputs, rates, config)
    bond_table = bond_table.merge(bond_rets.rename(columns={"asset_id": "bond_id"})[["month", "bond_id", "lag_value"]],
                                  on=["month", "bond_id"], how="left")
    firm_table = _firm_table(bond_table, inputs, config)
    sort_report = _sort_report(bond_table, firm_table, config)

    groups = firm_table.dropna(subset=["quintile"])[["month", "firm_id", "quintile"]].rename(columns={"quintile": "group"})
    held_bonds = bond_table[bond_table.des_bp.notna()].merge(groups, on=["month", "firm_id"])
    bond_holdings = held_bonds.rename(columns={"bond_id": "asset_id"})[["month", "asset_id", "group"]]
    stock_holdings = groups.rename(columns={"firm_id": "asset_id"})[["month", "asset_id", "group"]]
    returns = _all_returns(bond_holdings, bond_rets, stock_holdings, stock_rets, config)
    return DesStudy(bond_table, firm_table, sort_report, returns, _summary(returns), _quintile_profile(firm_table),
                    _missing_report(bonds, accounts, bond_table, sort_report, returns))
