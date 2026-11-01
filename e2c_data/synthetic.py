"""Made-up tables for every kind, written from the schema alone. EVERY NUMBER HERE IS MADE UP.

This imports no reader, so it can catch bugs in the table reader instead of repeating them. It holds the hard cases on
purpose: a default, a merger with a bond that moves to the acquirer, a restatement, a split, trade corrections.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from e2c_data.schema import KINDS, all_columns

_START, _END = pd.Timestamp("2003-01-01"), pd.Timestamp("2005-12-30")
_LISTED = pd.Timestamp("2000-01-03")
_CLOSE = pd.Timedelta(17, "h")
_N = 8
_DEFAULTED, _MERGED, _ACQUIRER = 7, 8, 1
_ENDS = {_DEFAULTED: pd.Timestamp("2003-11-14"), _MERGED: pd.Timestamp("2004-03-19")}
_SPLIT_NAME, _SPLIT_DATE = 2, pd.Timestamp("2004-09-15")
_RESTATED_NAME, _RESTATED_PERIOD = 1, pd.Timestamp("2004-03-31")
_SECTORS = ["Industrial", "Energy", "Consumer", "Telecom"]


def _issuer(i: int) -> str:
    return f"I{i:03d}"


def _equity(i: int) -> str:
    return f"E{i:03d}"


def _bonds(i: int) -> list[str]:
    return [f"B{i:03d}{n}" for n in (1, 2)]


def _alive(i: int, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return dates[dates <= _ENDS[i]] if i in _ENDS else dates


def make_synthetic_tables(seed: int = 0) -> dict[str, pd.DataFrame]:
    """Every kind, as `{kind: frame}`. Same seed, same tables."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(_START, _END)
    names = range(1, _N + 1)
    equity = _equity_prices(rng, names, dates)
    bonds = _bond_prices(rng, names, dates)
    tables = {
        "security_map": _security_map(names),
        "universe": _universe(names),
        "issuer_attributes": _issuer_attributes(names),
        "equity_prices": equity,
        "corporate_actions": _corporate_actions(names, dates),
        "accounts": _accounts(rng, names),
        "rates": _rates(rng, dates),
        "financing": _financing(rng, names, dates),
        "cds_quotes": _cds_quotes(rng, names, dates),
        "bond_terms": _bond_terms(names),
        "bond_prices": bonds,
        "bond_trades": _bond_trades(rng, bonds),
        "option_quotes": _option_quotes(rng, equity),
        "events": _events(),
    }
    return {kind: _shaped(kind, df) for kind, df in tables.items()}


def _shaped(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    return df.reindex(columns=list(all_columns(KINDS[kind]))).reset_index(drop=True)


def _security_map(names) -> pd.DataFrame:
    rows = []

    def add(instrument, kind, i, frm, ended=None, ticker=None):
        # the end of a link only becomes known when it happens, so it is a second version of the row
        rows.append(dict(instrument_id=instrument, instrument_type=kind, issuer_id=_issuer(i), valid_from=frm,
                         valid_to=pd.NaT, available_at=frm, ticker=ticker))
        if ended is not None:
            rows.append({**rows[-1], "valid_to": ended, "available_at": ended + _CLOSE})

    for i in names:
        add(_equity(i), "equity", i, _LISTED, _ENDS.get(i), f"TK{i}")
        for b in _bonds(i):
            add(b, "bond", i, _LISTED, _ENDS.get(i))
    moved_on = _ENDS[_MERGED] + pd.Timedelta(1, "D")
    for b in _bonds(_MERGED):
        add(b, "bond", _ACQUIRER, moved_on)
    return pd.DataFrame(rows)


def _universe(names) -> pd.DataFrame:
    rows = []
    for i in names:
        base = dict(issuer_id=_issuer(i), start_date=_LISTED, end_date=pd.NaT, end_reason=None, available_at=_LISTED)
        rows.append(base)
        if i in _ENDS:
            reason = "default" if i == _DEFAULTED else "merger"
            rows.append({**base, "end_date": _ENDS[i], "end_reason": reason, "available_at": _ENDS[i] + _CLOSE})
    return pd.DataFrame(rows)


def _issuer_attributes(names) -> pd.DataFrame:
    rows = []
    for i in names:
        sector = _SECTORS[i % len(_SECTORS)]
        rows.append(dict(issuer_id=_issuer(i), date=_START, sector=sector, rating="BBB", has_listed_equity=True,
                         available_at=_START + _CLOSE))
        change = pd.Timestamp("2004-06-30")
        if i not in _ENDS and i % 2 == 0:
            rows.append(dict(issuer_id=_issuer(i), date=change, sector=sector, rating="BB", has_listed_equity=True,
                             available_at=change + _CLOSE))
    return pd.DataFrame(rows)


def _equity_prices(rng, names, dates) -> pd.DataFrame:
    frames = []
    for i in names:
        d = _alive(i, dates)
        sigma = rng.uniform(0.2, 0.5)
        ret = rng.normal(0.0002, sigma / np.sqrt(252), len(d))
        total = np.exp(np.cumsum(ret))
        factor = np.where(d >= _SPLIT_DATE, 2.0, 1.0) if i == _SPLIT_NAME else np.ones(len(d))
        close = rng.uniform(20, 60) * total / factor
        shares = 1e8 * factor
        vol = lambda: sigma * rng.uniform(0.9, 1.1, len(d))  # noqa: E731
        frames.append(pd.DataFrame({
            "date": d, "equity_id": _equity(i), "stock_close": close, "mkt_cap": close * shares, "shares_out": shares,
            "half_spread": 0.0005, "total_return": np.expm1(ret), "realised_vol_30d": vol(), "realised_vol_60d": vol(),
            "realised_vol_90d": vol(), "realised_vol_180d": vol(), "realised_vol_360d": vol(),
            "realised_vol_162w": vol(), "put_iv_3m": vol(), "put_iv_6m": vol(), "put_iv_12m": vol(), "put_iv_24m": vol(),
            "atm_iv_12m": vol(), "available_at": d + _CLOSE}))
    return pd.concat(frames, ignore_index=True)


def _corporate_actions(names, dates) -> pd.DataFrame:
    rows = []
    for i in names:
        for ex in _alive(i, dates)[::63]:
            rows.append(dict(equity_id=_equity(i), ex_date=ex, action_type="cash_dividend", cash_amount=0.1,
                             split_factor=np.nan, price_after=np.nan, available_at=ex - pd.Timedelta(14, "D")))
    rows.append(dict(equity_id=_equity(_SPLIT_NAME), ex_date=_SPLIT_DATE, action_type="split", cash_amount=np.nan,
                     split_factor=2.0, price_after=np.nan, available_at=_SPLIT_DATE - pd.Timedelta(21, "D")))
    return pd.DataFrame(rows)


def _accounts(rng, names) -> pd.DataFrame:
    rows = []
    quarters = pd.date_range("2002-03-31", _END, freq="QE")
    for i in names:
        level = rng.uniform(1e9, 2e10)
        for q in quarters:
            at = q + pd.Timedelta(45, "D")
            if i in _ENDS and at > _ENDS[i]:
                break
            tl = level * rng.uniform(0.95, 1.05)
            rows.append(dict(issuer_id=_issuer(i), period_end=q, available_at=at, form="10-K" if q.month == 12 else "10-Q",
                             total_liabilities=tl, st_debt=0.1 * tl, lt_debt=0.5 * tl, other_st_liab=0.1 * tl,
                             other_lt_liab=0.2 * tl, minority_int=0.01 * tl, pfd_equity=0.0, dividends=0.01 * tl,
                             interest=0.012 * tl, repurchases=0.005 * tl, shares_out=1e8))
    restated = next(r for r in rows if r["issuer_id"] == _issuer(_RESTATED_NAME) and r["period_end"] == _RESTATED_PERIOD)
    rows.append({**restated, "total_liabilities": restated["total_liabilities"] * 1.1,
                 "available_at": pd.Timestamp("2005-02-01")})
    return pd.DataFrame(rows)


def _rates(rng, dates) -> pd.DataFrame:
    level = 0.04 + np.cumsum(rng.normal(0, 0.0003, len(dates))).clip(-0.02, 0.03)
    frames = []
    for curve, tenor, add in [("treasury_par", t, 0.002 * t / 5) for t in (1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0)] + [
            ("swap", 5.0, 0.004), ("cash", 0.25, -0.01)]:
        price = 100.0 - 4.5 * (level + add - 0.04) * 100 if curve == "treasury_par" and tenor == 5.0 else np.nan
        frames.append(pd.DataFrame({"date": dates, "curve": curve, "tenor": tenor, "rate": (level + add).clip(0.001),
                                    "price": price, "available_at": dates + _CLOSE}))
    return pd.concat(frames, ignore_index=True)


def _financing(rng, names, dates) -> pd.DataFrame:
    frames = [pd.DataFrame({"date": dates, "instrument_id": "UST5Y", "repo_rate": 0.02, "available_at": dates + _CLOSE})]
    for i in names:
        d = _alive(i, dates)
        frames.append(pd.DataFrame({"date": d, "instrument_id": _equity(i), "stock_fee": rng.uniform(0.002, 0.01, len(d)),
                                    "hard_to_borrow": False, "available_at": d + _CLOSE}))
        for b in _bonds(i):
            bd = dates if i == _MERGED else d
            frames.append(pd.DataFrame({"date": bd, "instrument_id": b, "repo_rate": 0.02,
                                        "bond_fee": rng.uniform(0.002, 0.01, len(bd)), "available_at": bd + _CLOSE}))
    return pd.concat(frames, ignore_index=True)


def _cds_quotes(rng, names, dates) -> pd.DataFrame:
    frames = []
    for i in names:
        d = _alive(i, dates)
        path = rng.uniform(0.01, 0.03) * np.exp(np.cumsum(rng.normal(0, 0.01, len(d))))
        for tenor, mult in ((1.0, 0.8), (5.0, 1.0)):
            frames.append(pd.DataFrame({"date": d, "issuer_id": _issuer(i), "tenor": tenor,
                                        "spread": (path * mult).clip(0.0005, 1.5), "recovery": 0.4, "currency": "USD",
                                        "available_at": d + _CLOSE}))
    return pd.concat(frames, ignore_index=True)


def _bond_terms(names) -> pd.DataFrame:
    rows = []
    for i in names:
        for n, b in enumerate(_bonds(i)):
            rows.append(dict(bond_id=b, coupon=0.05 + 0.005 * i / 2, freq=2,
                             maturity_date=pd.Timestamp(f"{2008 + 2 * n + i % 3}-06-15"), issue_date=pd.Timestamp("1999-06-15"),
                             available_at=_LISTED, first_coupon=pd.Timestamp("1999-12-15"), day_count="30/360",
                             seniority="senior unsecured", currency="USD", coupon_type="fixed", call_type="none",
                             call_schedule=None, is_convertible=False, is_putable=False, is_sinking=False,
                             is_perpetual=False, is_pik=False, is_floating=False))
    return pd.DataFrame(rows)


def _bond_prices(rng, names, dates) -> pd.DataFrame:
    frames = []
    for i in names:
        for b in _bonds(i):
            d = dates if i == _MERGED else _alive(i, dates)  # a merged issuer's bonds trade on under the acquirer
            clean = (rng.uniform(90, 105) + np.cumsum(rng.normal(0, 0.2, len(d)))).clip(40, 160)
            coupon = 100 * (0.05 + 0.005 * i / 2) / 2
            paid = np.where((d.month.isin([6, 12])) & (d.day == 15), coupon, 0.0)
            months = (d.month % 6 + (d.day - 15) / 30) % 6
            accrued = coupon * months / 6
            frames.append(pd.DataFrame({
                "date": d, "bond_id": b, "clean_price": clean, "full_price": clean + accrued, "accrued": accrued,
                "coupon_paid": paid, "next_call_price": np.nan, "entry_price": clean + 0.1, "amount_out": 3e8,
                "available_at": d + _CLOSE}))
    return pd.concat(frames, ignore_index=True)


def _bond_trades(rng, bonds: pd.DataFrame) -> pd.DataFrame:
    weekly = bonds[bonds.date.dt.dayofweek == 2]
    rows, seq = [], 0
    for b, day, price in zip(weekly.bond_id, weekly.date, weekly.clean_price):
        seq += 1
        when = day + pd.Timedelta(10, "h")
        base = dict(bond_id=b, msg_seq=seq, execution_time=when, price=price, size=float(rng.choice([1e5, 1e6, 5e6])),
                    orig_msg_seq=np.nan, action="new", is_duplicate_side=False, is_customer_buy=bool(rng.integers(2)),
                    report_time=when + pd.Timedelta(15, "min"), available_at=when + pd.Timedelta(15, "min"))
        rows.append(base)
        if seq % 20 == 0:
            seq += 1
            later = when + pd.Timedelta(2, "h")
            rows.append({**base, "msg_seq": seq, "orig_msg_seq": base["msg_seq"], "action": "correct",
                         "price": price + 0.25, "report_time": later, "available_at": later})
    return pd.DataFrame(rows)


def _option_quotes(rng, equity: pd.DataFrame) -> pd.DataFrame:
    month_ends = equity.groupby([equity.equity_id, equity.date.dt.to_period("M")]).tail(1)
    rows = []
    for e, day, s, iv in zip(month_ends.equity_id, month_ends.date, month_ends.stock_close, month_ends.atm_iv_12m):
        for days in (91, 182):
            expiry = day + pd.Timedelta(days, "D")
            for moneyness in (0.8, 1.0, 1.2):
                strike = round(s * moneyness, 2)
                for right in "CP":
                    intrinsic = max(s - strike, 0.0) if right == "C" else max(strike - s, 0.0)
                    mid = intrinsic + 0.4 * s * iv * np.sqrt(days / 365) * np.exp(-abs(moneyness - 1) * 5)
                    rows.append(dict(date=day, option_id=f"{e}-{expiry:%Y%m%d}-{strike}-{right}", equity_id=e, expiry=expiry,
                                     strike=strike, right=right, bid=max(mid - 0.05, 0.0), ask=mid + 0.05,
                                     quote_time=day + pd.Timedelta(16, "h"), volume=float(rng.integers(0, 500)),
                                     open_interest=float(rng.integers(0, 5000)), exercise_style="American", multiplier=100.0,
                                     vendor_iv=iv, vendor_delta=np.nan, available_at=day + _CLOSE))
    return pd.DataFrame(rows)


def _events() -> pd.DataFrame:
    return pd.DataFrame([
        dict(issuer_id=_issuer(_DEFAULTED), event_date=_ENDS[_DEFAULTED], event_type="default", instrument_id=None,
             realised_recovery=35.0, delisting_return=-0.8, available_at=_ENDS[_DEFAULTED] + _CLOSE),
        dict(issuer_id=_issuer(_MERGED), event_date=_ENDS[_MERGED], event_type="merger", instrument_id=None,
             realised_recovery=np.nan, delisting_return=0.2, available_at=_ENDS[_MERGED] + _CLOSE),
    ])
