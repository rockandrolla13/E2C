"""Turn view tables into the weekly frame e2c_model.run_pipeline takes. 05_io_spec.md, Table 1.

Inputs                                          Outputs
  build_workbook_inputs(view, start, end)         The 26 columns of Table 1, one row per name per week.
                                                  frame.attrs["e2c_report"] says which route each vol took, and holds
                                                  the counts of rows left out. It never holds data rows.

e2c_data is not on this branch. Install it with pip install "git+https://github.com/rockandrolla13/E2C@<tag>". No tag exists yet.

Weekly sampling. A name's last row in each week ending Friday, labelled with that Friday. A week whose Friday is after end
is left out. A name needs both a stock row and a 5-year CDS quote in the week. A name has a row only in weeks it has both.
Accounts. Version known at Friday's close, from view.versions. The latest period wins, and a later filing of that period
replaces it. A late amendment of an older period does not displace newer accounts. Rows with no filing yet are left out,
because run_pipeline reads blank debt as 0.
Links. The issuer comes from the dated security_map link covering the day of the stock row.
Units, schema to workbook: decimals to percent points for vols and the swap, decimals to bp for spreads, USD to $M for amounts.
next_date, next_spread_bp, next_price. e2c_model.next_week_values on the finished frame, last. Nothing else reads them, and
run_pipeline uses them only for P&L. The last row of each name inside the window is blank.

Vols. Each column takes one route, reported in attrs:
  vendor   the source has values in this column. A blank cell stays blank and is counted. It is never filled in.
  derived  only with derive_vols=True, only for realised vols with no vendor value anywhere in the column.
           Sample standard deviation of daily log close returns, split-adjusted, no dividends, over 30, 60, 90, 180 or 360
           trading days, times sqrt(252), with every day of the window present. vol_162w is the same on weekly returns over
           162 weeks, times sqrt(52). The workbook's own estimator is MISSING (Table 1), so a derived vol is not the
           workbook's number. A run on derived vols cannot claim to reproduce the workbook's signals, sizes or Sharpe.
  none     no value. The column stays blank and is counted. Put vols are never derived, because their moneyness is MISSING.
"""
import logging
from datetime import date

import numpy as np
import pandas as pd

import e2c_model as m
from e2c_data.source import DataUnavailable

log = logging.getLogger("inputs")

INPUT_COLUMNS = ["date", "ticker", "sector", "st_debt", "lt_debt", "other_st_liab", "other_lt_liab", "minority_int", "pfd_equity",
                 "mkt_cap", "price", "spread_bp", "vol_30d", "vol_60d", "vol_90d", "vol_180d", "vol_360d", "vol_162w", "put_3m",
                 "put_6m", "put_12m", "put_24m", "swap_5y_pct", "next_date", "next_spread_bp", "next_price"]
ACCOUNT_ITEMS = ["st_debt", "lt_debt", "other_st_liab", "other_lt_liab", "minority_int", "pfd_equity"]
REALISED_WINDOWS = {"vol_30d": 30, "vol_60d": 60, "vol_90d": 90, "vol_180d": 180, "vol_360d": 360}
WEEKS_162 = 162
DECIMAL_TO_PERCENT = 100.0
DECIMAL_TO_BP = 1e4
USD_TO_M = 1e-6
_VENDOR_COLUMNS = {"vol_30d": "realised_vol_30d", "vol_60d": "realised_vol_60d", "vol_90d": "realised_vol_90d",
                   "vol_180d": "realised_vol_180d", "vol_360d": "realised_vol_360d", "vol_162w": "realised_vol_162w",
                   "put_3m": "put_iv_3m", "put_6m": "put_iv_6m", "put_12m": "put_iv_12m", "put_24m": "put_iv_24m"}


def build_workbook_inputs(view, start: date, end: date, derive_vols: bool = False, cds_tenor: float = 5.0, swap_curve: str = "swap",
                          swap_tenor: float = 5.0, close_utc_hour: int = 21) -> pd.DataFrame:
    """The frame for run_pipeline, Fridays from start to end. Close_utc_hour sets when Friday's accounts stop being news."""
    counts: dict = {}
    first = (pd.Timestamp(start) - pd.Timedelta(6, "D")).date()
    links = view.read("security_map")
    stocks = _in_weeks(view.read("equity_prices", first, end), "equity_id", start, end)
    x = _with_issuer(stocks, links, counts)
    x = _with_spread(x, view, first, end, cds_tenor, counts)
    x = _with_accounts(x, view, end, close_utc_hour, counts)
    x = _with_sector(x, view, end)
    x = _with_swap(x, view, first, end, swap_curve, swap_tenor, start, counts)
    x, routes = _with_vols(x, view, end, derive_vols)
    return _finished(x, routes, counts)


def _fridays(dates: pd.Series) -> pd.Series:
    return dates.dt.to_period("W-FRI").dt.end_time.dt.normalize()


def _in_weeks(rows: pd.DataFrame, by: str, start: date, end: date | None = None) -> pd.DataFrame:
    """Last row of each name in each week. day keeps the row's own date, and friday labels the week."""
    rows = rows.drop(columns="available_at").assign(day=rows.date, friday=_fridays(rows.date))
    rows = rows[rows.friday >= pd.Timestamp(start)]
    if end is not None:
        rows = rows[rows.friday <= pd.Timestamp(end)]
    return rows.sort_values([by, "day"]).groupby([by, "friday"], sort=False).tail(1)


def _with_issuer(rows: pd.DataFrame, links: pd.DataFrame, counts: dict) -> pd.DataFrame:
    links = links.reindex(columns=["instrument_id", "issuer_id", "valid_from", "valid_to", "ticker"])
    rows = rows.reset_index(drop=True).assign(_row=lambda d: d.index)
    k = rows.merge(links, left_on="equity_id", right_on="instrument_id")
    k = k[(k.valid_from <= k.day) & (k.valid_to.isna() | (k.day <= k.valid_to))]
    clashes = int((k.groupby("_row").issuer_id.nunique() > 1).sum())
    if clashes:
        raise ValueError(f"{clashes} rows have two issuers on their date")
    counts["no_link"] = len(rows) - k._row.nunique()
    k = k.drop_duplicates("_row")
    return k.assign(ticker=k.ticker.where(k.ticker.notna(), k.equity_id)).drop(columns=["_row", "instrument_id", "valid_from", "valid_to"])


def _with_spread(x: pd.DataFrame, view, first: date, end: date, tenor: float, counts: dict) -> pd.DataFrame:
    q = view.read("cds_quotes", first, end)
    q = q[q.tenor == tenor].rename(columns={"date": "cds_date"})
    q = q.assign(friday=_fridays(q.cds_date)).sort_values(["issuer_id", "cds_date"]).groupby(["issuer_id", "friday"], sort=False).tail(1)
    out = x.merge(q[["issuer_id", "friday", "spread"]], on=["issuer_id", "friday"])
    counts["no_cds"] = len(x) - len(out)
    return out.assign(spread_bp=out.spread * DECIMAL_TO_BP)


def _with_accounts(x: pd.DataFrame, view, end: date, close_utc_hour: int, counts: dict) -> pd.DataFrame:
    a = view.versions("accounts", end=end).reindex(columns=["issuer_id", "period_end", "available_at"] + ACCOUNT_ITEMS)
    a = a.assign(available_at=pd.to_datetime(a.available_at)).dropna(subset=["available_at"]).sort_values(["available_at", "period_end"])
    a = a[a.period_end >= a.groupby("issuer_id").period_end.cummax()]
    a[ACCOUNT_ITEMS] = a[ACCOUNT_ITEMS] * USD_TO_M
    asof = x.friday + pd.Timedelta(close_utc_hour, "h")
    out = pd.merge_asof(x.assign(_asof=asof).sort_values("_asof"), a, left_on="_asof", right_on="available_at", by="issuer_id")
    counts["no_accounts"] = int(out.available_at.isna().sum())
    return out[out.available_at.notna()].drop(columns=["_asof", "period_end", "available_at"])


def _with_sector(x: pd.DataFrame, view, end: date) -> pd.DataFrame:
    try:
        s = view.read("issuer_attributes", end=end)[["issuer_id", "date", "sector"]].rename(columns={"date": "sector_date"})
    except DataUnavailable:
        return x.assign(sector=np.nan)  # only S10 uses sector, and MASTER does not run S10
    return pd.merge_asof(x.sort_values("friday"), s.sort_values("sector_date"), left_on="friday", right_on="sector_date", by="issuer_id")


def _with_swap(x: pd.DataFrame, view, first: date, end: date, curve: str, tenor: float, start: date, counts: dict) -> pd.DataFrame:
    r = view.read("rates", first, end, ids=[curve])
    r = _in_weeks(r[r.tenor == tenor], "curve", start)
    out = x.merge(r[["friday", "rate"]], on="friday", how="left")
    counts["no_swap"] = int(out.rate.isna().sum())
    return out.assign(swap_5y_pct=out.rate * DECIMAL_TO_PERCENT)


def _with_vols(x: pd.DataFrame, view, end: date, derive_vols: bool) -> tuple[pd.DataFrame, dict]:
    routes = {}
    for column, vendor in _VENDOR_COLUMNS.items():
        values = x[vendor] * DECIMAL_TO_PERCENT if vendor in x and x[vendor].notna().any() else None
        routes[column] = "vendor" if values is not None else "none"
        x[column] = np.nan if values is None else values
    empty = [c for c in list(REALISED_WINDOWS) + ["vol_162w"] if routes[c] == "none"]
    if derive_vols and empty:
        derived = _derived_vols(view, x, end)
        for c in empty:
            x[c] = derived[c].to_numpy()
            routes[c] = "derived"
    return x, routes


def _derived_vols(view, x: pd.DataFrame, end: date) -> pd.DataFrame:
    """Realised vols in percent, for each row of x. See the module docstring for the rule."""
    closes = view.read("equity_prices", end=end, ids=x.equity_id.unique().tolist())[["equity_id", "date", "stock_close"]]
    closes = closes.merge(_split_days(view, end), on=["equity_id", "date"], how="left").sort_values(["equity_id", "date"])
    g = closes.groupby("equity_id")
    closes["ret"] = np.log(closes.stock_close * closes.split_factor.fillna(1.0) / g.stock_close.shift(1))
    for column, n in REALISED_WINDOWS.items():
        closes[column] = g.ret.transform(lambda s, n=n: s.rolling(n, min_periods=n).std()) * np.sqrt(252) * DECIMAL_TO_PERCENT
    closes["vol_162w"] = _weekly_vol(closes)
    keep = ["equity_id", "date"] + list(REALISED_WINDOWS) + ["vol_162w"]
    return x[["equity_id", "day"]].merge(closes[keep], left_on=["equity_id", "day"], right_on=["equity_id", "date"], how="left")


def _split_days(view, end: date) -> pd.DataFrame:
    try:
        a = view.read("corporate_actions", end=end).reindex(columns=["equity_id", "ex_date", "action_type", "split_factor"])
    except DataUnavailable:
        log.warning("derived vols: no corporate_actions, so returns are not split-adjusted")
        return pd.DataFrame({"equity_id": pd.Series(dtype=object), "date": pd.Series(dtype="datetime64[ns]"), "split_factor": pd.Series(dtype=float)})
    a = a[a.split_factor.notna()].rename(columns={"ex_date": "date"})
    return a.groupby(["equity_id", "date"], as_index=False).split_factor.prod()


def _weekly_vol(closes: pd.DataFrame) -> pd.Series:
    """Weekly log returns from the split-adjusted daily returns, over 162 weeks, set on each week's last row."""
    level = closes.groupby("equity_id").ret.transform(lambda s: s.fillna(0.0).cumsum())
    friday = _fridays(closes.date)
    last = ~closes.assign(friday=friday).duplicated(["equity_id", "friday"], keep="last")
    weekly = level[last].groupby(closes.equity_id[last]).diff()
    vol = weekly.groupby(closes.equity_id[last]).transform(lambda s: s.rolling(WEEKS_162, min_periods=WEEKS_162).std()) * np.sqrt(52) * DECIMAL_TO_PERCENT
    return vol.reindex(closes.index)


def _finished(x: pd.DataFrame, routes: dict, counts: dict) -> pd.DataFrame:
    x = x.assign(date=x.friday, price=x.stock_close, mkt_cap=_market_cap_m(x))
    if x.duplicated(["date", "ticker"]).any():
        raise ValueError("two rows for one ticker in one week")
    x = x.sort_values(["date", "ticker"]).reset_index(drop=True)
    x[m.NEXT_WEEK] = m.next_week_values(x)  # last, so nothing above can read them
    out = x[INPUT_COLUMNS].copy()
    report = {"vol_routes": {c: dict(route=routes[c], values=int(out[c].notna().sum()), blank=int(out[c].isna().sum())) for c in routes},
              "rows": len(out), "left_out": counts}
    out.attrs["e2c_report"] = report
    for c, r in report["vol_routes"].items():
        if r["route"] != "vendor" or r["blank"]:
            log.warning("%s: route %s, %d blank of %d", c, r["route"], r["blank"], len(out))
    for reason, n in counts.items():
        if n:
            log.warning("%s: %d rows", reason, n)
    return out


def _market_cap_m(x: pd.DataFrame) -> pd.Series:
    cap = x.mkt_cap if "mkt_cap" in x else pd.Series(np.nan, index=x.index)
    shares = x.shares_out if "shares_out" in x else pd.Series(np.nan, index=x.index)
    return cap.where(cap.notna(), x.stock_close * shares) * USD_TO_M
