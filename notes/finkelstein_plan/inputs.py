"""Turn view tables into what fk_des.run_des_study takes. Only this file knows both the data layer and fk_des.

Inputs                                          Outputs
  build_des_inputs(view, start, end)              DesInputs(bonds, equities, accounts, rates), so that
                                                  fk_des.run_des_study(*inputs, config) runs

Conversions, schema to fk_des: bond prices per 100 to per 1, amounts USD to USD mm. Rates, coupons, shares and share
prices keep their units. maturity_years is 30/360, the plan's day count on corporates. Nothing here screens bonds, so
apply the plan's screens to the table first if a run needs them.

Accounts come from view.versions, so a restatement stays a separate row and fk_des picks the one usable on each date.
Prices, terms, actions and links come from view.read: the latest version known at the view's decision time.
Dividend and split_factor default to fk_des's 0.0 and 1.0 only on a day with no action. A missing amount stays NaN.

build_vintage_inputs is for a backtest over many dates. It takes each month's rows as known at the end of that month, so a
later price correction or link fix cannot reach an earlier sort. build_des_inputs, read from one late view, can let it.
"""
import logging
from datetime import date
from typing import NamedTuple, Sequence

import numpy as np
import pandas as pd

from e2c_data.schema import kind_spec
from e2c_data.source import DataUnavailable, restrict
from e2c_data.view import PointInTimeView
from fk_des import ACCOUNT_COLUMNS, BOND_COLUMNS, EQUITY_COLUMNS, RATE_COLUMNS

log = logging.getLogger("inputs")

PER_100_TO_PER_1 = 0.01
USD_TO_USD_MM = 1e-6
PAR_CURVE = "treasury_par"
_ACCOUNT_AMOUNTS = ["total_liabilities", "dividends", "interest", "repurchases"]
_SHARE_ACTIONS = ("split", "stock_dividend")


class DesInputs(NamedTuple):
    bonds: pd.DataFrame
    equities: pd.DataFrame
    accounts: pd.DataFrame
    rates: pd.DataFrame


def years_30_360(start: pd.Series, end: pd.Series) -> pd.Series:
    """Years between dates on US 30/360. A blank end stays NaN."""
    d1 = start.dt.day.clip(upper=30)
    d2 = end.dt.day.where(~((end.dt.day == 31) & (d1 == 30)), 30)
    days = 360 * (end.dt.year - start.dt.year) + 30 * (end.dt.month - start.dt.month) + (d2 - d1)
    return days / 360.0


def build_des_inputs(view, start: date, end: date, equity_lookback_years: int = 3, rate_lookback_days: int = 14) -> DesInputs:
    """Bonds and returns cover start to end. Stocks start earlier, to fill the 3-year vol. Rates start earlier for staleness."""
    links = view.read("security_map")
    return DesInputs(_bonds(view, start, end, links),
                     _equities(view, start, end, links, equity_lookback_years),
                     _accounts(view, end),
                     _rates(view, start, end, rate_lookback_days))


def _with_firm(rows: pd.DataFrame, id_column: str, links: pd.DataFrame, table: str) -> pd.DataFrame:
    """Add firm_id from the link covering each row's own date. A row with no link leaves, and is counted."""
    rows = rows.reset_index(drop=True).assign(_row=lambda d: d.index)
    m = rows.merge(links[["instrument_id", "issuer_id", "valid_from", "valid_to"]], how="inner",
                   left_on=id_column, right_on="instrument_id")
    m = m[(m.valid_from <= m.date) & (m.valid_to.isna() | (m.date <= m.valid_to))]
    clashes = int((m.groupby("_row").issuer_id.nunique() > 1).sum())
    if clashes:
        raise ValueError(f"{table}: {clashes} rows have two issuers on their date")
    lost = len(rows) - m._row.nunique()
    if lost:
        log.warning("%s: %d rows left out, no issuer link on their date", table, lost)
    return m.drop_duplicates("_row").drop(columns=["_row", "instrument_id", "valid_from", "valid_to"]).rename(columns={"issuer_id": "firm_id"})


def _bonds(view, start: date, end: date, links: pd.DataFrame) -> pd.DataFrame:
    first = pd.Timestamp(start).to_period("M").to_timestamp().date()  # the whole first month, for its coupon
    p = view.read("bond_prices", first, end).reindex(columns=["date", "bond_id", "clean_price", "full_price", "accrued",
                                                              "coupon_paid", "entry_price", "amount_out"])
    p = _with_firm(p, "bond_id", links, "bonds").sort_values(["bond_id", "date"])
    month = p.date.dt.to_period("M")
    paid = p.groupby(["bond_id", month]).coupon_paid.transform(lambda s: s.sum(min_count=len(s)))
    p = p.assign(coupon_paid=paid * PER_100_TO_PER_1,
                 full_price=p.full_price.where(p.full_price.notna(), p.clean_price + p.accrued) * PER_100_TO_PER_1,
                 entry_price=p.entry_price * PER_100_TO_PER_1, amount_out=p.amount_out * USD_TO_USD_MM)
    last = p.groupby(["bond_id", month], sort=False).tail(1)
    terms = view.read("bond_terms")[["bond_id", "coupon", "freq", "maturity_date"]]
    b = last.merge(terms, on="bond_id", how="left")
    b = b.assign(maturity_years=years_30_360(b.date, b.maturity_date))
    columns = list(BOND_COLUMNS) + (["entry_price"] if b.entry_price.notna().any() else [])
    return b[columns].reset_index(drop=True)


def _equities(view, start: date, end: date, links: pd.DataFrame, lookback_years: int, actions_required: bool = True) -> pd.DataFrame:
    first = (pd.Timestamp(start) - pd.DateOffset(years=lookback_years)).date()
    q = view.read("equity_prices", first, end).reindex(columns=["date", "equity_id", "stock_close", "shares_out", "mkt_cap"])
    q = q.assign(shares_out=q.shares_out.where(q.shares_out.notna(), q.mkt_cap / q.stock_close))
    q = q.merge(_actions_by_price_day(view, first, end, q, actions_required), on=["equity_id", "date"], how="left")
    q = q.assign(dividend=q.dividend.where(q._action.notna(), 0.0), split_factor=q.split_factor.where(q._action.notna(), 1.0))
    return _with_firm(q, "equity_id", links, "equities")[list(EQUITY_COLUMNS)].sort_values(["firm_id", "date"]).reset_index(drop=True)


def _actions_by_price_day(view, first: date, end: date, prices: pd.DataFrame, required: bool = True) -> pd.DataFrame:
    """Dividend and split per stock per price day. An ex-date with no price moves to the next price of that stock."""
    a = view.read("corporate_actions", first, end) if required else _optional(view, "corporate_actions", first, end)
    if a is None or a.empty:
        return pd.DataFrame({"equity_id": pd.Series(dtype=object), "date": pd.Series(dtype="datetime64[ns]"), "dividend": pd.Series(dtype=float),
                             "split_factor": pd.Series(dtype=float), "_action": pd.Series(dtype=float)})
    a = a.reindex(columns=["equity_id", "ex_date", "action_type", "cash_amount", "split_factor"])
    shares_only = a.action_type.isin(_SHARE_ACTIONS)
    a = a.assign(cash_amount=a.cash_amount.where(a.cash_amount.notna() | ~shares_only, 0.0),
                 split_factor=a.split_factor.where(a.split_factor.notna() | shares_only, 1.0))
    days = prices[["equity_id", "date"]].drop_duplicates().sort_values("date")
    a = pd.merge_asof(a.sort_values("ex_date"), days, left_on="ex_date", right_on="date", by="equity_id", direction="forward")
    lost = int(a.date.isna().sum())
    if lost:
        log.warning("equities: %d corporate actions left out, no later price", lost)
    grouped = a.dropna(subset=["date"]).groupby(["equity_id", "date"])
    return pd.DataFrame({"dividend": grouped.cash_amount.apply(lambda s: s.sum(skipna=False)),
                         "split_factor": grouped.split_factor.apply(lambda s: s.prod(skipna=False)),
                         "_action": 1.0}).reset_index()


def _accounts(view, end: date) -> pd.DataFrame:
    a = view.versions("accounts", end=end).reindex(columns=["issuer_id", "period_end", "available_at"] + _ACCOUNT_AMOUNTS)
    a = a.rename(columns={"issuer_id": "firm_id"}).assign(available_date=pd.to_datetime(a.available_at).dt.normalize())
    a[_ACCOUNT_AMOUNTS] = a[_ACCOUNT_AMOUNTS] * USD_TO_USD_MM
    return a[list(ACCOUNT_COLUMNS)].reset_index(drop=True)


def _rates(view, start: date, end: date, lookback_days: int) -> pd.DataFrame:
    first = (pd.Timestamp(start) - pd.Timedelta(lookback_days, "D")).date()
    r = view.read("rates", first, end, ids=[PAR_CURVE]).rename(columns={"rate": "par_yield"})
    return r[list(RATE_COLUMNS)].reset_index(drop=True)


# ---------------------------------------------------------------- One read per month, as known at that month's end

_BIG_CUSTOMER_TRADE = 100_000.0
_TRADE_WINDOW_DAYS = 7     # calendar days that hold the screen's last five business days
_SCREEN_TERMS = ["bond_id", "issue_date", "seniority", "currency", "coupon_type", "call_type", "is_convertible", "is_putable", "is_sinking",
                 "is_perpetual", "is_pik"]


class VintageInputs(NamedTuple):
    inputs: DesInputs
    screen_rows: pd.DataFrame    # one row per bond per month: fk_f10.screen_bonds's fields
    financing: pd.DataFrame      # month, asset_id (bond_id or firm_id), repo_rate, bond_fee, stock_fee
    day_costs: pd.DataFrame      # the month's customer trades, for fk_f10.bond_day_costs. Empty if none were read
    stock_half_spread: float     # median known half spread, NaN if none
    months: int


class WholeTables:
    """Each kind is read once and kept, so that a monthly loop does not reload a file. bond_trades stays uncached."""

    def __init__(self, source) -> None:
        self.source = source
        self._tables: dict = {}

    def read(self, kind: str, start=None, end=None, ids: Sequence[str] | None = None) -> pd.DataFrame:
        if kind == "bond_trades":
            return self.source.read(kind, start, end, ids)
        if kind not in self._tables:
            self._tables[kind] = self.source.read(kind)
        return restrict(self._tables[kind], kind_spec(kind), start, end, ids)


def _optional(view, kind: str, start=None, end=None) -> pd.DataFrame | None:
    try:
        return view.read(kind, start, end)
    except DataUnavailable:
        return None


def _month_screen_rows(view, first: date, last: date, bonds: pd.DataFrame) -> pd.DataFrame:
    prices = view.read("bond_prices", first, last).sort_values("date").groupby("bond_id").tail(1)
    known = [c for c in ("bond_id", "clean_price", "next_call_price") if c in prices]
    rows = bonds[["date", "bond_id", "firm_id", "maturity_years", "amount_out"]].merge(prices[known], on="bond_id", how="left")
    rows["clean_price"] = rows.clean_price * PER_100_TO_PER_1
    if "next_call_price" in rows:
        rows["next_call_price"] = rows.next_call_price * PER_100_TO_PER_1
    terms = view.read("bond_terms")
    rows = rows.merge(terms[[c for c in _SCREEN_TERMS if c in terms]], on="bond_id", how="left")
    rows["years_since_issue"] = years_30_360(rows.issue_date, rows.date)
    attrs = _optional(view, "issuer_attributes", None, last)
    if attrs is not None and not attrs.empty:
        attrs = attrs.sort_values("date").groupby("issuer_id").tail(1).rename(columns={"issuer_id": "firm_id"})
        rows = rows.merge(attrs[[c for c in ("firm_id", "sector", "has_listed_equity") if c in attrs]], on="firm_id", how="left")
    return rows.drop(columns=["issue_date"])


def _month_financing(view, first: date, last: date, links: pd.DataFrame) -> pd.DataFrame | None:
    f = _optional(view, "financing", first, last)
    if f is None or f.empty:
        return None
    f = f.sort_values("date").groupby("instrument_id").tail(1)
    firm = links[links.instrument_type == "equity"].drop_duplicates("instrument_id", keep="last").set_index("instrument_id").issuer_id
    columns = {c: f[c] if c in f else np.nan for c in ("repo_rate", "bond_fee", "stock_fee")}
    return pd.DataFrame(dict(month=pd.Timestamp(last).to_period("M"), asset_id=f.instrument_id.map(firm).fillna(f.instrument_id), **columns))


def _month_trades(view, first: date, last: date) -> tuple:
    """Big trades in the month's last days per bond, and customer buy and sell prices per bond per day."""
    t = _optional(view, "bond_trades", first, last)
    if t is None or t.empty:
        return None, None
    since = pd.Timestamp(last) - pd.Timedelta(_TRADE_WINDOW_DAYS, "D")
    counts = t[(t.execution_time > since) & (t["size"] >= _BIG_CUSTOMER_TRADE)].groupby("bond_id").size().rename("trades_5d")
    return counts, t[[c for c in ("bond_id", "execution_time", "price", "size", "is_customer_buy") if c in t]]


def build_vintage_inputs(source, start: date, end: date, decision_time, liquidity: bool = True, equity_lookback_years: int = 3) -> VintageInputs:
    """Each month's rows as known at the end of that month. Accounts keep every version, as fk_des picks by date."""
    cached = WholeTables(source)
    decision = pd.Timestamp(decision_time)
    parts: dict = {k: [] for k in ("bonds", "equities", "rates", "screen", "financing", "trades")}
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    spreads, used = [], 0
    for k, month in enumerate(months):
        first, last = max(month.start_time, pd.Timestamp(start)).date(), min(month.end_time.normalize(), pd.Timestamp(end).normalize(), decision.normalize()).date()
        if pd.Timestamp(first) > decision:
            break
        view = PointInTimeView(cached, min(month.end_time, decision))
        used += 1
        links = view.read("security_map")
        if not view.read("equity_prices", first, last).empty or k == 0:
            years = equity_lookback_years if k == 0 else 0
            parts["equities"].append(_equities(view, first, last, links, years, actions_required=False))   # run_f10 flags an absent table
            quotes = view.read("equity_prices", first, last)
            if "half_spread" in quotes:
                spreads.append(quotes.half_spread.dropna())
        parts["rates"].append(_rates(view, first, last, 14 if k == 0 else 0))
        if view.read("bond_prices", first, last).empty:
            continue
        bonds = _bonds(view, first, last, links)
        rows = _month_screen_rows(view, first, last, bonds)
        if liquidity:
            counts, trades = _month_trades(view, first, last)
            if counts is not None:
                rows = rows.merge(counts, how="left", left_on="bond_id", right_index=True).assign(trades_5d=lambda d: d.trades_5d.fillna(0))
                parts["trades"].append(trades)
        parts["bonds"].append(bonds)
        parts["screen"].append(rows)
        money = _month_financing(view, first, last, links)
        if money is not None:
            parts["financing"].append(money)
    final = PointInTimeView(cached, decision)
    end_day = min(pd.Timestamp(end).normalize(), decision.normalize()).date()
    equities = pd.concat(parts["equities"], ignore_index=True).drop_duplicates(["firm_id", "date"]).sort_values(["firm_id", "date"]).reset_index(drop=True)
    rates = pd.concat(parts["rates"], ignore_index=True).drop_duplicates(["date", "tenor"]).reset_index(drop=True)
    bonds = pd.concat(parts["bonds"], ignore_index=True) if parts["bonds"] else pd.DataFrame(columns=list(BOND_COLUMNS))
    screen = pd.concat(parts["screen"], ignore_index=True) if parts["screen"] else pd.DataFrame()
    screen = screen.loc[:, screen.notna().any()] if not screen.empty else screen   # a column nobody fills is an absent column
    financing = pd.concat(parts["financing"], ignore_index=True) if parts["financing"] else pd.DataFrame(columns=["month", "asset_id", "repo_rate", "bond_fee", "stock_fee"])
    trades = pd.concat(parts["trades"], ignore_index=True) if parts["trades"] else pd.DataFrame()
    half = float(pd.concat(spreads).median()) if spreads and sum(len(s) for s in spreads) else float("nan")
    return VintageInputs(DesInputs(bonds, equities, _accounts(final, end_day), rates), screen, financing, trades, half, used)
