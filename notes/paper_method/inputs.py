"""Turn view tables into what e2c_bond's backtests take. 02_bond_vol_method.md, raw inputs and Parts 1 to 3.

Inputs                                                Outputs
  build_bond_panel(view, bond_id, start, end)           BondInputs: panel, dates, ratings, report
  with_peer_gaps(list of BondInputs, config)            the same list, with peer_gap filled in
  build_cds_panel(view, issuer_id, start, end)          CdsInputs: panel, dates, report
  build_factors(view, start, end)                       Factors: months, names, returns

e2c_data is not on this branch. Install it with pip install "git+https://github.com/rockandrolla13/E2C@<tag>". No tag exists yet.

The panel takes clean prices, so this file cleans the trades with e2c_bond's own functions. Each day uses only the reports public
by that day's close (close_utc_hour), so a later correction or cancel never changes an earlier day. A trade is public at the later
of available_at and report_time. A print reported after its own day's close never prices any day. Decimal and spike checks see
the last LOOKBACK_DAYS of known prints.

Rows. Treasury curve dates in the window on which the bond has a dated link, its issuer has a dated stock link, and that stock has a
price. Issuer, stock, rating and sector follow the row's own date. A row with no debt, no vol or no life left also leaves, because
run_bond_backtest prices every row and raises on a NaN there. report["left_out"] counts each reason. Other blanks stay NaN and are counted.
Debt. Accounts from view.versions, usable from e2c_bond.filing_usable_from. The latest period wins, and a later filing of that
period replaces it. Shares come from the filing and are put on today's split basis, so a split does not move the model spread.
Step 10's stock dividend and spinoff adjustment is not built: those days are counted in report["unadjusted_actions"].
Vol. vol_source "historical" uses total_return with e2c_bond.historical_equity_vol. "implied" uses atm_iv_12m, and then the panel has
no implied_vol, because a run never mixes the two sources (step 12).
Round trip. measured_round_trip over 20 days, or planning_round_trip if that is not positive or can't be measured. The planning numbers
are unsourced, and report["round_trip"] counts each route. A day with no trades keeps the previous day's number.
tradable holds the Part 1 screens and a usable round trip. A blank field fails its screen, and report["screens_failed"] counts each.
peer_gap is NaN until with_peer_gaps runs. A NaN gives no signal, so run that, or set peer_adjust=False and say so.
Peers are same rating, same maturity bucket, on the day. A peer counts only after its own fit ended, or its gap would look ahead.
Not built: sibling_gap stays None. Prices, terms, actions and links use the latest version known at the view's decision time.
Units, schema to panel: bond prices per 100 to per 1. Rates, coupons, vols and share prices keep their units. years_left is 30/360.
"""
from dataclasses import replace
from datetime import date
from typing import NamedTuple

import numpy as np
import pandas as pd

import e2c_bond as m
from e2c_data.source import DataUnavailable

PER_100_TO_PER_1 = 0.01
PAR_CURVE = "treasury_par"
CASH_CURVE = "cash"
LOOKBACK_DAYS = 60
ROUND_TRIP_DAYS = 20
LIQUIDITY_BUSINESS_DAYS = 5
LIQUIDITY_MIN_SIZE = 100_000.0
MATURITY_BUCKETS = (0.0, 3.0, 7.0, 10.0, np.inf)
_EVENT_NAMES = {"call": "called", "tender": "tender", "merger": "merger", "default": "default", "delist": "delist"}
_SHARE_ACTIONS_NOT_ADJUSTED = ("stock_dividend", "spinoff")


class BondInputs(NamedTuple):
    panel: m.BondPanel
    dates: pd.DatetimeIndex
    ratings: np.ndarray
    report: dict


class CdsInputs(NamedTuple):
    panel: m.CdsPanel
    dates: pd.DatetimeIndex
    report: dict


class Factors(NamedTuple):
    months: pd.DatetimeIndex
    names: tuple
    returns: np.ndarray


def _close(dates: pd.Series, hour: int) -> pd.Series:
    return dates + pd.Timedelta(hour, "h")


def _optional(view, kind: str, *args, **kw) -> pd.DataFrame | None:
    try:
        return view.read(kind, *args, **kw)
    except DataUnavailable:
        return None


def years_30_360(start: pd.Series, end: pd.Series) -> pd.Series:
    """Years between dates on US 30/360. A blank end stays NaN."""
    d1 = start.dt.day.clip(upper=30)
    d2 = end.dt.day.where(~((end.dt.day == 31) & (d1 == 30)), 30)
    return (360 * (end.dt.year - start.dt.year) + 30 * (end.dt.month - start.dt.month) + (d2 - d1)) / 360.0


def _covered(rows: pd.DataFrame, what: str) -> pd.DataFrame:
    """Rows joined to links, kept where the link covers the row's date. Two values on one day is an error."""
    k = rows[(rows.valid_from <= rows.date) & (rows.valid_to.isna() | (rows.date <= rows.valid_to))]
    clashes = int(k.groupby("date")[what].nunique().gt(1).sum())
    if clashes:
        raise ValueError(f"{clashes} days have two {what} values for one instrument")
    return k.drop_duplicates("date").drop(columns=["valid_from", "valid_to"])


def _market_rows(view, instrument: str, id_is_bond: bool, start: date, end: date, vol_window: int) -> tuple:
    """Rows with issuer, stock and close, for one bond or one issuer. Also the curve table, the days left out and the price history."""
    counts = {}
    links = view.read("security_map").reindex(columns=["instrument_id", "instrument_type", "issuer_id", "valid_from", "valid_to"])
    curve = view.read("rates", start, end, ids=[PAR_CURVE])
    wide = curve.pivot_table(index="date", columns="tenor", values="rate", aggfunc="last", dropna=False).sort_index()
    complete = wide.notna().all(axis=1)
    counts["no_curve"] = int((~complete).sum())
    wide = wide[complete]
    rows = pd.DataFrame({"date": wide.index})
    if id_is_bond:
        own = rows.merge(links[links.instrument_id == instrument], how="cross")
        issuer = _covered(own, "issuer_id")[["date", "issuer_id"]]
    else:
        issuer = rows.assign(issuer_id=instrument)
    counts["no_link"] = len(rows) - len(issuer)
    stocks = links[links.instrument_type == "equity"].rename(columns={"instrument_id": "equity_id"})
    joined = issuer.merge(stocks.drop(columns="instrument_type"), on="issuer_id")
    with_stock = _covered(joined, "equity_id")
    first = (pd.Timestamp(start) - pd.Timedelta(int(vol_window * 2), "D")).date()
    prices = view.read("equity_prices", first, end, ids=with_stock.equity_id.unique().tolist())
    prices = prices.reindex(columns=["date", "equity_id", "stock_close", "total_return", "atm_iv_12m"])
    out = with_stock.merge(prices, on=["date", "equity_id"])
    counts["no_stock"] = len(issuer) - len(out)
    return out.sort_values("date").reset_index(drop=True), wide, counts, prices


def _sigma(rows: pd.DataFrame, prices: pd.DataFrame, source: str, window: int, min_obs: int) -> np.ndarray:
    if source == "implied":
        return rows.atm_iv_12m.to_numpy(float)
    if source != "historical":
        raise ValueError(f"unknown vol source: {source}")
    out = np.full(len(rows), np.nan)
    series = {e: g.sort_values("date") for e, g in prices.groupby("equity_id")}
    for i, (equity, day) in enumerate(zip(rows.equity_id, rows.date)):
        g = series[equity]
        returns = np.log1p(g.total_return[g.date <= day].to_numpy(float))
        out[i] = m.historical_equity_vol(returns, window=window, min_obs=min_obs)
    return out


def _debt(view, rows: pd.DataFrame, end: date) -> np.ndarray:
    a = view.versions("accounts", end=end).reindex(columns=["issuer_id", "period_end", "available_at", "form", "total_liabilities", "shares_out"])
    a = a.assign(usable=[pd.Timestamp(m.filing_usable_from(x, p, f)) for x, p, f in zip(a.available_at, a.period_end, a.form)] if len(a) else pd.NaT)
    a = a.sort_values(["usable", "period_end", "available_at"])
    a = a[a.period_end >= a.groupby("issuer_id").period_end.cummax()]
    k = pd.merge_asof(rows[["date", "issuer_id", "equity_id"]].sort_values("date"), a, left_on="date", right_on="usable", by="issuer_id")
    actions = _optional(view, "corporate_actions", end=end)
    splits = 1.0
    if actions is not None:
        s = actions.reindex(columns=["equity_id", "ex_date", "split_factor"]).dropna(subset=["split_factor"])
        splits = np.array([s.split_factor[(s.equity_id == e) & (s.ex_date > p) & (s.ex_date <= d)].prod() if pd.notna(p) else np.nan
                           for e, p, d in zip(k.equity_id, k.period_end, k.date)])
    shares = k.shares_out.to_numpy(float) * splits
    return m.debt_per_share(k.total_liabilities.to_numpy(float), shares)


def _asof_attributes(view, rows: pd.DataFrame, end: date, hour: int) -> pd.DataFrame:
    """Sector, listing and rating known by each row's close. A rating public later does not reach earlier rows."""
    empty = rows[["date"]].assign(sector=np.nan, rating=np.nan, has_listed_equity=np.nan)
    try:
        v = view.versions("issuer_attributes", end=end).reindex(columns=["issuer_id", "date", "available_at", "sector", "rating", "has_listed_equity"])
    except DataUnavailable:
        return empty
    v = v.assign(known=pd.concat([pd.to_datetime(v.date), pd.to_datetime(v.available_at)], axis=1).max(axis=1)).sort_values(["known", "date"]).drop(columns=["date", "available_at"])
    left = rows[["date", "issuer_id"]].assign(stamp=_close(rows.date, hour)).sort_values("stamp")
    return pd.merge_asof(left, v, left_on="stamp", right_on="known", by="issuer_id").sort_values("date")


def _prepared_trades(view, bond_id: str, end: date) -> pd.DataFrame | None:
    t = _optional(view, "bond_trades", end=end, ids=[bond_id])
    if t is None:
        return None
    t = t.reindex(columns=["msg_seq", "orig_msg_seq", "action", "is_duplicate_side", "is_customer_buy", "execution_time", "report_time", "price", "size", "available_at"])
    known = pd.concat([pd.to_datetime(t.available_at), pd.to_datetime(t.report_time)], axis=1).max(axis=1)
    t = t.assign(known=known, day=pd.to_datetime(t.execution_time).dt.normalize()).sort_values("execution_time")
    return t.reset_index(drop=True)


def _clean_prints(t: pd.DataFrame, day: pd.Timestamp, hour: int) -> pd.DataFrame:
    """The prints a reader had at this day's close, cleaned with e2c_bond's functions."""
    stamp = day + pd.Timedelta(hour, "h")
    t = t[(t.known <= stamp) & (t.day > day - pd.Timedelta(LOOKBACK_DAYS, "D"))]
    if t.empty:
        return t
    t = t[m.clean_trade_reports(t.msg_seq.to_numpy(), t.orig_msg_seq.to_numpy(), t.action.fillna("new").to_numpy(), t.is_duplicate_side.fillna(False).to_numpy(bool))]
    if t.empty:
        return t
    fixed = m.fix_decimal_shifts(t.price.to_numpy(float))
    return t.assign(price=fixed)[~m.flag_price_spikes(fixed)]


def _daily_from_trades(trades: pd.DataFrame | None, dates, hour: int) -> pd.DataFrame:
    """Clean price per 1 of face, measured round trip and count of large trades in five business days, one row per date."""
    out = pd.DataFrame({"clean": np.nan, "measured": np.nan, "liquid_trades": 0}, index=dates)
    if trades is None or trades.empty:
        return out
    trades = trades.dropna(subset=["is_customer_buy", "price", "size"])
    for day in dates:
        k = _clean_prints(trades, day, hour)
        if k.empty:
            continue
        buy = k.is_customer_buy.astype(bool)
        today = k.day == day
        if today.any():
            out.loc[day, "clean"] = m.daily_clean_price(k.price[today], k["size"][today], buy[today])[0]
        recent = k[k.day > day - pd.Timedelta(ROUND_TRIP_DAYS, "D")]
        b, s = recent[buy.loc[recent.index]], recent[~buy.loc[recent.index]]
        if len(b) and len(s):
            out.loc[day, "measured"] = m.measured_round_trip(b.price, b["size"], s.price, s["size"])
        back = np.busday_offset(day.date(), -LIQUIDITY_BUSINESS_DAYS + 1, roll="backward")
        large = (k["size"] >= LIQUIDITY_MIN_SIZE) & (k.day >= pd.Timestamp(back)) & (k.day <= day)
        out.loc[day, "liquid_trades"] = int(large.sum())
    return out


def _normal(text) -> str:
    return str(text).strip().lower().replace(" ", "_").replace("-", "_") if pd.notna(text) else ""


def _sector_word(sector) -> str:
    word = _normal(sector)
    return "financial" if word.startswith("financ") else "utility" if word.startswith("utilit") else word


def _terms_ok(terms: pd.Series) -> bool:
    flags = ("is_convertible", "is_putable", "is_sinking", "is_perpetual", "is_pik")
    if any(pd.isna(terms.get(f)) for f in flags):
        return False
    return m.bond_terms_are_eligible(_normal(terms.get("seniority")), terms.get("currency"), _normal(terms.get("coupon_type")), _normal(terms.get("call_type")),
                                     *(bool(terms[f]) for f in flags))


def _asof_column(rows: pd.DataFrame, table: pd.DataFrame | None, column: str) -> np.ndarray:
    if table is None or column not in table:
        return np.full(len(rows), np.nan)
    return pd.merge_asof(rows[["date"]], table[["date", column]].dropna().sort_values("date"), on="date")[column].to_numpy(float)


def _same_day(rows: pd.DataFrame, table: pd.DataFrame | None, column: str) -> np.ndarray:
    if table is None or column not in table:
        return np.full(len(rows), np.nan)
    return rows[["date"]].merge(table[["date", column]].drop_duplicates("date"), on="date", how="left")[column].to_numpy(float)


def _issuer_has_core_bond(view, rows: pd.DataFrame, terms: pd.DataFrame) -> np.ndarray:
    links = view.read("security_map")
    bonds = links[links.instrument_type == "bond"].merge(terms[["bond_id", "maturity_date"]], left_on="instrument_id", right_on="bond_id")
    out = np.zeros(len(rows), dtype=bool)
    for i, (issuer, day) in enumerate(zip(rows.issuer_id, rows.date)):
        b = bonds[(bonds.issuer_id == issuer) & (bonds.valid_from <= day) & (bonds.valid_to.isna() | (bonds.valid_to >= day))]
        if len(b):
            left = years_30_360(pd.Series(day, index=b.index), b.maturity_date)
            out[i] = bool(((left >= 3.0) & (left <= 7.0)).any())
    return out


def _forced_events(view, rows: pd.DataFrame, issuer_col: str, bond_id: str | None, end: date) -> tuple | None:
    e = _optional(view, "events", end=end)
    if e is None or e.empty:
        return None
    e = e.reindex(columns=["issuer_id", "event_date", "event_type", "instrument_id"])
    out = [None] * len(rows)
    dates = rows.date.to_numpy()
    for issuer, when, kind, instrument in zip(e.issuer_id, e.event_date, e.event_type, e.instrument_id):
        if pd.notna(instrument) and instrument != bond_id:
            continue
        hits = np.flatnonzero((rows[issuer_col].to_numpy() == issuer) & (dates >= np.datetime64(when)))
        if len(hits) and (rows.date.iloc[hits[0]] - when).days <= 7:  # a date with no row lands on the next row
            out[hits[0]] = _EVENT_NAMES.get(kind, kind)
    return tuple(out) if any(x is not None for x in out) else None


def _optional_array(values: np.ndarray) -> np.ndarray | None:
    return values if np.isfinite(values).any() else None


def _unadjusted_actions(view, rows: pd.DataFrame, end: date) -> int:
    a = _optional(view, "corporate_actions", end=end)
    if a is None or rows.empty:
        return 0
    a = a.reindex(columns=["equity_id", "ex_date", "action_type"])
    a = a[a.action_type.isin(_SHARE_ACTIONS_NOT_ADJUSTED) & a.equity_id.isin(rows.equity_id) & (a.ex_date >= rows.date.min()) & (a.ex_date <= rows.date.max())]
    return len(a)


def _usable_rows(rows: pd.DataFrame, counts: dict, debt: np.ndarray, sigma: np.ndarray, left: np.ndarray | None = None) -> tuple:
    """Keep rows the backtests can price, and count the rest by the first reason."""
    has_debt, has_vol = np.isfinite(debt) & (debt > 0), np.isfinite(sigma) & (sigma > 0)
    has_life = np.ones(len(rows), dtype=bool) if left is None else np.isfinite(left) & (left > 0)
    counts["no_debt"] = int((~has_debt).sum())
    counts["no_vol"] = int((has_debt & ~has_vol).sum())
    counts["no_life"] = int((has_debt & has_vol & ~has_life).sum())
    keep = has_debt & has_vol & has_life
    if not keep.any():
        raise DataUnavailable(f"no row has debt, vol and life left: {counts}")
    kept = [debt[keep], sigma[keep]] + ([] if left is None else [left[keep]])
    return rows[keep].reset_index(drop=True), kept


def build_bond_panel(view, bond_id: str, start: date, end: date, vol_source: str = "historical", hedge_id: str | None = None,
                     min_trades_5d: int = 10, close_utc_hour: int = 21, vol_window: int = 1000, vol_min_obs: int = 750) -> BondInputs:
    """One bond's panel from start to end. See the module docstring for every rule."""
    rows, wide, counts, prices = _market_rows(view, bond_id, True, start, end, vol_window)
    if rows.empty:
        raise DataUnavailable(f"{bond_id}: no day has a curve, a link and a stock price")
    terms_table = view.read("bond_terms")
    match = terms_table[terms_table.bond_id == bond_id]
    if match.empty:
        raise DataUnavailable(f"{bond_id}: no bond_terms row")
    terms = match.iloc[0]
    left = years_30_360(rows.date, pd.Series(terms.maturity_date, index=rows.index)).to_numpy(float)
    debt, sigma = _debt(view, rows, end), _sigma(rows, prices, vol_source, vol_window, vol_min_obs)
    rows, (debt, sigma, years_left) = _usable_rows(rows, counts, debt, sigma, left)
    day = rows.date
    since_issue = years_30_360(pd.Series(terms.issue_date, index=day.index), day).to_numpy(float)

    trades = _prepared_trades(view, bond_id, end)
    daily = _daily_from_trades(trades, day, close_utc_hour)
    clean = daily.clean.to_numpy(float)
    curves = [m.zero_curve_from_par_yields(wide.columns.to_numpy(float), wide.loc[d].to_numpy(float)) for d in day]
    attrs = _asof_attributes(view, rows, end, close_utc_hour)
    ratings = attrs.rating.to_numpy(object)
    round_trip, routes = _round_trips(daily.measured.to_numpy(float), clean, float(terms.coupon), int(terms.freq), years_left, curves, ratings)

    bond_rows = _optional(view, "bond_prices", None, end, ids=[bond_id])
    amount = _asof_column(rows, bond_rows, "amount_out")
    next_call = _asof_column(rows, bond_rows, "next_call_price") * PER_100_TO_PER_1
    core = _issuer_has_core_bond(view, rows, terms_table)
    screens = {
        "issuer": np.array([bool(x) and pd.notna(s) and m.issuer_is_eligible(_sector_word(s), True)
                            for x, s in zip(attrs.has_listed_equity.where(attrs.has_listed_equity.notna(), False), attrs.sector)]),
        "terms": np.full(len(rows), _terms_ok(terms)),
        "callable": np.array([m.callable_is_usable(_normal(terms.get("call_type")), c, n) for c, n in zip(clean, next_call)]),
        "maturity": np.array([m.maturity_is_eligible(y, bool(c)) for y, c in zip(years_left, core)]),
        "age_and_size": np.array([m.age_and_size_are_eligible(a, y, s) for a, y, s in zip(since_issue, years_left, amount)]),
        "liquidity": np.array([m.passes_liquidity_screen(int(n), min_trades_5d) for n in daily.liquid_trades]),
        "round_trip": np.isfinite(round_trip),
    }
    tradable = np.logical_and.reduce(list(screens.values()))

    financing = _optional(view, "financing", start, end)
    def fin(instrument, column):
        if financing is None or instrument is None or column not in financing:
            return np.full(len(rows), np.nan)
        return _same_day(rows, financing[financing.instrument_id == instrument], column)
    stock_fee = np.full(len(rows), np.nan)
    if financing is not None and "stock_fee" in financing:
        stock_fee = rows[["date", "equity_id"]].merge(financing.rename(columns={"instrument_id": "equity_id"})[["date", "equity_id", "stock_fee"]], on=["date", "equity_id"], how="left").stock_fee.to_numpy(float)
    rates = view.read("rates", start, end)
    cash = _same_day(rows, rates[rates.curve == CASH_CURVE], "rate")
    r_5y = _same_day(rows, rates[(rates.curve == PAR_CURVE) & (rates.tenor == 5.0)], "rate")
    implied = rows.atm_iv_12m.to_numpy(float)
    cds = _issuer_cds(view, rows, start, end)
    span = (day - day.iloc[0]).dt.days.to_numpy(float)

    panel = m.BondPanel(
        coupon=float(terms.coupon), freq=int(terms.freq), years_left=years_left, clean=clean, S=rows.stock_close.to_numpy(float),
        D=debt, sigma_s=sigma, dividend=_dividends(view, rows, end),
        zero_tenors=curves[0].tenors, zeros=np.array([c.zeros for c in curves]), r_5y=r_5y, repo=fin(bond_id, "repo_rate"), bond_fee=fin(bond_id, "bond_fee"),
        stock_fee=stock_fee, cash_rate=cash, hedge_repo=fin(hedge_id, "repo_rate"), day_fraction=np.diff(span, prepend=span[0]) / 360.0,
        calendar_day=span, peer_gap=np.full(len(rows), np.nan), round_trip=round_trip, tradable=tradable, sibling_gap=None,
        cds_market=_optional_array(cds), implied_vol=None if vol_source == "implied" else _optional_array(implied),
        forced_event=_forced_events(view, rows, "issuer_id", bond_id, end))
    report = {"rows": len(rows), "left_out": counts, "round_trip": routes, "screens_failed": {k: int((~v).sum()) for k, v in screens.items()},
              "blank": _blanks(panel), "priced_days": int(np.isfinite(clean).sum()), "tradable_days": int(tradable.sum()),
              "unadjusted_actions": _unadjusted_actions(view, rows, end), "vol_source": vol_source, "not_built": ["sibling_gap"]}
    return BondInputs(panel, pd.DatetimeIndex(day), ratings, report)


def _blanks(panel) -> dict:
    fields = ("clean", "S", "D", "sigma_s", "dividend", "r_5y", "repo", "bond_fee", "stock_fee", "cash_rate", "hedge_repo", "peer_gap", "round_trip", "c", "r")
    return {f: int(np.isnan(getattr(panel, f)).sum()) for f in fields if hasattr(panel, f)}


def _round_trips(measured, clean, coupon, freq, years_left, curves, ratings) -> tuple[np.ndarray, dict]:
    out = np.full(len(clean), np.nan)
    routes = {"measured": 0, "planning": 0, "carried": 0, "blank": 0}
    for i in range(len(clean)):
        if measured[i] > 0:
            out[i] = measured[i]
            routes["measured"] += 1
        elif np.isfinite(clean[i]) and pd.notna(ratings[i]):
            bond = m.Bond(coupon, float(years_left[i]), freq)
            out[i] = m.planning_round_trip(str(ratings[i]), m.z_spread(m.full_price(clean[i], bond), bond, curves[i]))
            routes["planning"] += 1
        elif i > 0 and np.isfinite(out[i - 1]):
            out[i] = out[i - 1]
            routes["carried"] += 1
        else:
            routes["blank"] += 1
    return out, routes


def _dividends(view, rows: pd.DataFrame, end: date) -> np.ndarray:
    """Cash on the ex-date. 0.0 only on a day with no action. A date with no row lands on the next row. Needs corporate_actions."""
    a = view.read("corporate_actions", end=end).reindex(columns=["equity_id", "ex_date", "action_type", "cash_amount"])
    a = a[a.action_type.eq("cash_dividend") | a.cash_amount.notna()].sort_values("ex_date")
    out = np.zeros(len(rows))
    for equity, when, cash in zip(a.equity_id, a.ex_date, a.cash_amount):
        hits = np.flatnonzero((rows.equity_id.to_numpy() == equity) & (rows.date.to_numpy() >= np.datetime64(when)))
        if len(hits):
            out[hits[0]] += cash
    return out


def _issuer_cds(view, rows: pd.DataFrame, start: date, end: date, tenor: float = 5.0) -> np.ndarray:
    q = _optional(view, "cds_quotes", start, end)
    if q is None:
        return np.full(len(rows), np.nan)
    q = q[q.tenor == tenor][["date", "issuer_id", "spread"]]
    return rows[["date", "issuer_id"]].merge(q, on=["date", "issuer_id"], how="left").spread.to_numpy(float)


def _bucket(years: np.ndarray) -> np.ndarray:
    return np.digitize(years, MATURITY_BUCKETS)


def with_peer_gaps(built: list, config: m.BacktestConfig) -> list:
    """Fill peer_gap from each peer's own fit. Run each bond once with no peer adjustment, to get its z_market, z_model and fit end."""
    frames = []
    first_pass = replace(config, peer_adjust=False)
    for k, b in enumerate(built):
        result = m.run_bond_backtest(b.panel, first_pass)
        fit_days = [i for i in range(len(b.dates)) if np.isfinite(result.z_market[i]) and b.panel.tradable[i]][:config.calibration_days]
        gaps = np.array([m.log_gap(x, y) if np.isfinite(x) and np.isfinite(y) else np.nan for x, y in zip(result.z_market, result.z_model)])
        if len(fit_days) < config.calibration_days or result.status == "reject":
            gaps[:] = np.nan
        else:
            gaps[:fit_days[-1] + 1] = np.nan
        frames.append(pd.DataFrame({"k": k, "date": b.dates, "gap": gaps, "rating": b.ratings, "bucket": _bucket(b.panel.years_left)}))
    all_gaps = pd.concat(frames, ignore_index=True)
    out = []
    for k, b in enumerate(built):
        peer = np.zeros(len(b.dates))
        others = all_gaps[all_gaps.k != k]
        for i, (day, rating, bucket) in enumerate(zip(b.dates, b.ratings, _bucket(b.panel.years_left))):
            same = others[(others.date == day) & (others.rating == rating) & (others.bucket == bucket)] if pd.notna(rating) else others.iloc[0:0]
            peer[i] = m.peer_median_gap(same.gap.to_numpy(float))
        report = {**b.report, "blank": {**b.report["blank"], "peer_gap": 0}}
        out.append(b._replace(panel=replace(b.panel, peer_gap=peer), report=report))
    return out


def build_cds_panel(view, issuer_id: str, start: date, end: date, vol_source: str = "historical", tenor: float = 5.0,
                    vol_window: int = 1000, vol_min_obs: int = 750) -> CdsInputs:
    """One obligor's panel for run_cds_backtest. A day needs a stock price, a CDS quote and a 5-year Treasury yield."""
    rows, _, counts, prices = _market_rows(view, issuer_id, False, start, end, vol_window)
    c = _issuer_cds(view, rows, start, end, tenor)
    rates = view.read("rates", start, end)
    r = _same_day(rows, rates[(rates.curve == PAR_CURVE) & (rates.tenor == 5.0)], "rate")
    keep = np.isfinite(c)
    counts["no_cds"] = int((~keep).sum())
    rows, c, r = rows[keep].reset_index(drop=True), c[keep], r[keep]
    if rows.empty:
        raise DataUnavailable(f"{issuer_id}: no day has a curve, a stock price and a CDS quote")
    debt, sigma = _debt(view, rows, end), _sigma(rows, prices, vol_source, vol_window, vol_min_obs)
    usable = np.isfinite(debt) & (debt > 0) & np.isfinite(sigma) & (sigma > 0)
    rows, (debt, sigma) = _usable_rows(rows, counts, debt, sigma)
    c, r = c[usable], r[usable]
    span = (rows.date - rows.date.iloc[0]).dt.days.to_numpy(float)
    panel = m.CdsPanel(c=c, S=rows.stock_close.to_numpy(float), D=debt, sigma_s=sigma, r=r,
                       dividend=_dividends(view, rows, end), day_fraction=np.diff(span, prepend=span[0]) / 360.0, calendar_day=span)
    return CdsInputs(panel, pd.DatetimeIndex(rows.date), {"rows": len(rows), "left_out": counts, "blank": _blanks(panel), "vol_source": vol_source})


def build_factors(view, start: date, end: date) -> Factors:
    """Monthly factor returns, one column per factor, for e2c_bond.factor_regression. A blank stays NaN."""
    f = view.read("factor_returns", start, end)
    wide = f.assign(month=f.date.dt.to_period("M").dt.to_timestamp()).pivot_table(index="month", columns="factor", values="excess_return", dropna=False).sort_index()
    return Factors(pd.DatetimeIndex(wide.index), tuple(wide.columns), wide.to_numpy(float))
