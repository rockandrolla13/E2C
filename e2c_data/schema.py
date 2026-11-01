"""What each kind of data looks like: columns, types, units, keys. Nothing here knows files, vendors or methods.

Rules for every kind:
- Rates, yields, spreads, coupons and vols are decimals (0.065 is 6.5%). Bond prices are per 100 face. Amounts are USD.
- `available_at` is the first moment a row was public, as naive UTC. It is never earlier than the real release.
- A restatement is a new row with the same key and a later `available_at`. Old rows stay.
- A value you do not have stays empty (NaN), never zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True)
class KindSpec:
    name: str
    date_column: str | None
    id_column: str
    key: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


class Column(NamedTuple):
    type: str  # text, date, float, int or bool
    unit: str


class Range(NamedTuple):
    """Every value must lie in [lo, hi]. The column's median must lie in [median_lo, median_hi]."""
    lo: float
    hi: float
    median_lo: float
    median_hi: float


def _c(type_: str, unit: str = "none") -> Column:
    return Column(type_, unit)


_DECIMAL = "decimal per year"
_FLAG = _c("bool", "flag")
_VOL = _c("float", _DECIMAL)
_MONEY = _c("float", "USD")
_PER_100 = _c("float", "per 100 face")

COLUMNS: dict[str, Column] = {
    # identity
    "instrument_id": _c("text"), "instrument_type": _c("text", "equity, bond, option or cds"),
    "issuer_id": _c("text"), "ticker": _c("text"), "valid_from": _c("date", "date"),
    "valid_to": _c("date", "date, inclusive. Empty means still valid"),
    "start_date": _c("date", "date"), "end_date": _c("date", "date. Empty means alive"),
    "end_reason": _c("text"), "available_at": _c("date", "timestamp, naive UTC"), "date": _c("date", "date"),
    # issuer attributes
    "sector": _c("text"), "rating": _c("text"), "has_listed_equity": _FLAG,
    # equity
    "equity_id": _c("text"), "stock_close": _c("float", "USD per share. Not adjusted, dividends not included"),
    "mkt_cap": _MONEY, "shares_out": _c("float", "shares"), "half_spread": _c("float", "share of price"),
    "total_return": _c("float", "decimal per day"),
    "realised_vol_30d": _VOL, "realised_vol_60d": _VOL, "realised_vol_90d": _VOL, "realised_vol_180d": _VOL,
    "realised_vol_360d": _VOL, "realised_vol_162w": _VOL,
    "put_iv_3m": _VOL, "put_iv_6m": _VOL, "put_iv_12m": _VOL, "put_iv_24m": _VOL, "atm_iv_12m": _VOL,
    # corporate actions
    "ex_date": _c("date", "date"), "action_type": _c("text", "cash_dividend, split, stock_dividend or spinoff"),
    "cash_amount": _c("float", "USD per share"), "split_factor": _c("float", "new shares per old share"),
    "price_after": _c("float", "USD per share"),
    # accounts
    "period_end": _c("date", "date"), "form": _c("text", "10-Q, 10-K or other"), "total_liabilities": _MONEY,
    "st_debt": _MONEY, "lt_debt": _MONEY, "other_st_liab": _MONEY, "other_lt_liab": _MONEY, "minority_int": _MONEY,
    "pfd_equity": _MONEY, "dividends": _MONEY, "interest": _MONEY, "repurchases": _MONEY,
    # rates and financing
    "curve": _c("text", "treasury_par, swap or cash"), "tenor": _c("float", "years"), "rate": _c("float", _DECIMAL),
    "price": _c("float", "per 100 face"), "repo_rate": _c("float", _DECIMAL), "bond_fee": _c("float", _DECIMAL),
    "stock_fee": _c("float", _DECIMAL), "hard_to_borrow": _FLAG,
    # credit
    "spread": _c("float", _DECIMAL), "recovery": _c("float", "decimal share of par"), "currency": _c("text"),
    "bond_id": _c("text"), "coupon": _c("float", _DECIMAL), "freq": _c("int", "payments per year"),
    "maturity_date": _c("date", "date. Empty means perpetual"), "issue_date": _c("date", "date"),
    "first_coupon": _c("date", "date"), "day_count": _c("text"), "seniority": _c("text"), "coupon_type": _c("text"),
    "call_type": _c("text", "none, make_whole or fixed_price"), "call_schedule": _c("text", "vendor call schedule"),
    "is_convertible": _FLAG, "is_putable": _FLAG, "is_sinking": _FLAG, "is_perpetual": _FLAG, "is_pik": _FLAG,
    "is_floating": _FLAG,
    "clean_price": _PER_100, "full_price": _PER_100, "accrued": _PER_100, "coupon_paid": _PER_100,
    "next_call_price": _PER_100, "entry_price": _PER_100, "amount_out": _MONEY,
    # bond trades
    "execution_time": _c("date", "timestamp, naive UTC"), "report_time": _c("date", "timestamp, naive UTC"),
    "msg_seq": _c("int", "report number"), "orig_msg_seq": _c("int", "the report this one changes"),
    "action": _c("text", "new, cancel, correct or reverse"), "is_duplicate_side": _FLAG, "is_customer_buy": _FLAG,
    "size": _c("float", "USD face"),
    # options
    "option_id": _c("text"), "expiry": _c("date", "date"), "strike": _c("float", "USD per share"),
    "right": _c("text", "C or P"), "bid": _c("float", "USD per share"), "ask": _c("float", "USD per share"),
    "quote_time": _c("date", "timestamp, naive UTC"), "volume": _c("float", "contracts"),
    "open_interest": _c("float", "contracts"), "exercise_style": _c("text", "American or European"),
    "multiplier": _c("float", "shares"), "vendor_iv": _c("float", _DECIMAL), "vendor_delta": _c("float", "ratio"),
    # events
    "event_date": _c("date", "date"),
    "event_type": _c("text", "merger, tender, call, default or delist"),
    "realised_recovery": _PER_100, "delisting_return": _c("float", "decimal"),
}

_AT = "available_at"
KINDS: dict[str, KindSpec] = {s.name: s for s in (
    KindSpec("security_map", None, "instrument_id", ("instrument_id", "valid_from"),
             ("instrument_id", "instrument_type", "issuer_id", "valid_from", "valid_to", _AT), ("ticker",)),
    KindSpec("universe", None, "issuer_id", ("issuer_id", "start_date"),
             ("issuer_id", "start_date", "end_date", _AT), ("end_reason",)),
    KindSpec("issuer_attributes", "date", "issuer_id", ("issuer_id", "date"),
             ("issuer_id", "date", "sector", _AT), ("rating", "has_listed_equity")),
    KindSpec("equity_prices", "date", "equity_id", ("equity_id", "date"),
             ("date", "equity_id", "stock_close", _AT),
             ("mkt_cap", "shares_out", "half_spread", "total_return", "realised_vol_30d", "realised_vol_60d",
              "realised_vol_90d", "realised_vol_180d", "realised_vol_360d", "realised_vol_162w", "put_iv_3m",
              "put_iv_6m", "put_iv_12m", "put_iv_24m", "atm_iv_12m")),
    KindSpec("corporate_actions", "ex_date", "equity_id", ("equity_id", "ex_date", "action_type"),
             ("equity_id", "ex_date", "action_type", _AT), ("cash_amount", "split_factor", "price_after")),
    KindSpec("accounts", "period_end", "issuer_id", ("issuer_id", "period_end"),
             ("issuer_id", "period_end", _AT),
             ("form", "total_liabilities", "st_debt", "lt_debt", "other_st_liab", "other_lt_liab", "minority_int",
              "pfd_equity", "dividends", "interest", "repurchases", "shares_out")),
    KindSpec("rates", "date", "curve", ("date", "curve", "tenor"), ("date", "curve", "tenor", "rate", _AT), ("price",)),
    KindSpec("financing", "date", "instrument_id", ("date", "instrument_id"), ("date", "instrument_id", _AT),
             ("repo_rate", "bond_fee", "stock_fee", "hard_to_borrow")),
    KindSpec("cds_quotes", "date", "issuer_id", ("date", "issuer_id", "tenor"),
             ("date", "issuer_id", "tenor", "spread", _AT), ("recovery", "currency")),
    KindSpec("bond_terms", None, "bond_id", ("bond_id",),
             ("bond_id", "coupon", "freq", "maturity_date", "issue_date", _AT),
             ("first_coupon", "day_count", "seniority", "currency", "coupon_type", "call_type", "call_schedule",
              "is_convertible", "is_putable", "is_sinking", "is_perpetual", "is_pik", "is_floating")),
    KindSpec("bond_prices", "date", "bond_id", ("date", "bond_id"), ("date", "bond_id", "clean_price", _AT),
             ("full_price", "accrued", "coupon_paid", "next_call_price", "entry_price", "amount_out")),
    KindSpec("bond_trades", "execution_time", "bond_id", ("bond_id", "msg_seq"),
             ("bond_id", "msg_seq", "execution_time", "price", "size", _AT),
             ("orig_msg_seq", "action", "is_duplicate_side", "is_customer_buy", "report_time")),
    KindSpec("option_quotes", "date", "equity_id", ("date", "option_id"),
             ("date", "option_id", "equity_id", "expiry", "strike", "right", "bid", "ask", _AT),
             ("quote_time", "volume", "open_interest", "exercise_style", "multiplier", "vendor_iv", "vendor_delta")),
    KindSpec("events", "event_date", "issuer_id", ("issuer_id", "event_date", "event_type"),
             ("issuer_id", "event_date", "event_type", _AT), ("instrument_id", "realised_recovery", "delisting_return")),
)}

# Every method needs these. The others depend on the method, so a source may leave them out.
REQUIRED_KINDS = frozenset({"security_map", "universe", "equity_prices", "accounts", "rates"})

# These kinds are announced ahead of their date, so available_at may come before it.
ANNOUNCED_EARLY = frozenset({"events", "corporate_actions"})

# Events that end a name. A name with one of these must have an end_date in the universe.
TERMINAL_EVENTS = frozenset({"default", "merger", "delist"})

_INF = float("inf")
_VOL_RANGE = Range(0.0, 5.0, 0.01, 2.0)
_PRICE_RANGE = Range(0.0, 300.0, 5.0, 250.0)
_FEE_RANGE = Range(-0.05, 1.0, -0.02, 0.3)
_AMOUNT_RANGE = Range(0.0, _INF, 1e6, _INF)  # a median under USD 1M means the table holds millions

# Plausible values. These catch the unit mistakes: percent for decimal, per 1 for per 100, millions for USD.
RANGES: dict[str, Range] = {
    "rate": Range(-0.02, 0.30, -0.02, 0.20), "spread": Range(-0.001, 2.0, 0.0, 0.5),
    "coupon": Range(0.0, 0.30, 0.0, 0.20), "recovery": Range(0.0, 1.0, 0.0, 1.0),
    "repo_rate": _FEE_RANGE, "bond_fee": _FEE_RANGE, "stock_fee": _FEE_RANGE,
    "vendor_iv": _VOL_RANGE, "realised_vol_30d": _VOL_RANGE, "realised_vol_60d": _VOL_RANGE,
    "realised_vol_90d": _VOL_RANGE, "realised_vol_180d": _VOL_RANGE, "realised_vol_360d": _VOL_RANGE,
    "realised_vol_162w": _VOL_RANGE, "put_iv_3m": _VOL_RANGE, "put_iv_6m": _VOL_RANGE, "put_iv_12m": _VOL_RANGE,
    "put_iv_24m": _VOL_RANGE, "atm_iv_12m": _VOL_RANGE,
    "clean_price": _PRICE_RANGE, "full_price": _PRICE_RANGE, "entry_price": _PRICE_RANGE, "price": _PRICE_RANGE,
    "next_call_price": _PRICE_RANGE, "realised_recovery": Range(0.0, 150.0, 0.0, 150.0),
    "total_return": Range(-1.0, 5.0, -0.1, 0.1), "delisting_return": Range(-1.0, 5.0, -1.0, 5.0),
    "tenor": Range(0.0, 100.0, 0.0, 100.0), "strike": Range(0.0, _INF, 0.0, _INF),
    "stock_close": Range(0.0, _INF, 0.0, _INF), "split_factor": Range(0.0, _INF, 0.0, _INF),
    "total_liabilities": _AMOUNT_RANGE, "mkt_cap": _AMOUNT_RANGE, "amount_out": _AMOUNT_RANGE,
}


def all_columns(spec: KindSpec) -> tuple[str, ...]:
    return spec.required + spec.optional


def kind_spec(kind: str) -> KindSpec:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}. Kinds: {sorted(KINDS)}")
    return KINDS[kind]
