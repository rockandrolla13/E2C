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
"""
import logging
from datetime import date
from typing import NamedTuple

import numpy as np
import pandas as pd

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


def _equities(view, start: date, end: date, links: pd.DataFrame, lookback_years: int) -> pd.DataFrame:
    first = (pd.Timestamp(start) - pd.DateOffset(years=lookback_years)).date()
    q = view.read("equity_prices", first, end).reindex(columns=["date", "equity_id", "stock_close", "shares_out", "mkt_cap"])
    q = q.assign(shares_out=q.shares_out.where(q.shares_out.notna(), q.mkt_cap / q.stock_close))
    q = q.merge(_actions_by_price_day(view, first, end, q), on=["equity_id", "date"], how="left")
    q = q.assign(dividend=q.dividend.where(q._action.notna(), 0.0), split_factor=q.split_factor.where(q._action.notna(), 1.0))
    return _with_firm(q, "equity_id", links, "equities")[list(EQUITY_COLUMNS)].sort_values(["firm_id", "date"]).reset_index(drop=True)


def _actions_by_price_day(view, first: date, end: date, prices: pd.DataFrame) -> pd.DataFrame:
    """Dividend and split per stock per price day. An ex-date with no price moves to the next price of that stock."""
    a = view.read("corporate_actions", first, end).reindex(columns=["equity_id", "ex_date", "action_type", "cash_amount", "split_factor"])
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
