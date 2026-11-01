"""The schema: 15 kinds, one table of columns, and every method input placed or listed as not placed."""
from e2c_data import schema
from e2c_data.schema import COLUMNS, KINDS, RANGES, REQUIRED_KINDS, KindSpec, all_columns, kind_spec

import pytest

# Method field -> (kind, column). Files: workbook 05_io_spec.md Table 1, Yu 02_bond_vol_method.md raw inputs,
# Finkelstein plan master table, fk_des column tuples.
WORKBOOK = {
    "date": ("equity_prices", "date"), "ticker": ("security_map", "ticker"), "sector": ("issuer_attributes", "sector"),
    "st_debt": ("accounts", "st_debt"), "lt_debt": ("accounts", "lt_debt"),
    "other_st_liab": ("accounts", "other_st_liab"), "other_lt_liab": ("accounts", "other_lt_liab"),
    "minority_int": ("accounts", "minority_int"), "pfd_equity": ("accounts", "pfd_equity"),
    "mkt_cap": ("equity_prices", "mkt_cap"), "price": ("equity_prices", "stock_close"),
    "spread_bp": ("cds_quotes", "spread"),
    "vol_30d": ("equity_prices", "realised_vol_30d"), "vol_60d": ("equity_prices", "realised_vol_60d"),
    "vol_90d": ("equity_prices", "realised_vol_90d"), "vol_180d": ("equity_prices", "realised_vol_180d"),
    "vol_360d": ("equity_prices", "realised_vol_360d"), "vol_162w": ("equity_prices", "realised_vol_162w"),
    "put_3m": ("equity_prices", "put_iv_3m"), "put_6m": ("equity_prices", "put_iv_6m"),
    "put_12m": ("equity_prices", "put_iv_12m"), "put_24m": ("equity_prices", "put_iv_24m"),
    "swap_5y_pct": ("rates", "rate"),
}
WORKBOOK_DERIVED = {"next_date", "next_spread_bp", "next_price"}  # the adapter shifts a name's next row

YU = {
    "issuer_id": ("security_map", "issuer_id"), "sector": ("issuer_attributes", "sector"),
    "has_listed_equity": ("issuer_attributes", "has_listed_equity"), "rating": ("issuer_attributes", "rating"),
    "bond_id": ("bond_terms", "bond_id"), "seniority": ("bond_terms", "seniority"),
    "currency": ("bond_terms", "currency"), "coupon_type": ("bond_terms", "coupon_type"),
    "coupon": ("bond_terms", "coupon"), "freq": ("bond_terms", "freq"),
    "maturity_date": ("bond_terms", "maturity_date"), "issue_date": ("bond_terms", "issue_date"),
    "amount_outstanding": ("bond_prices", "amount_out"), "call_type": ("bond_terms", "call_type"),
    "next_call_price": ("bond_prices", "next_call_price"), "is_convertible": ("bond_terms", "is_convertible"),
    "is_putable": ("bond_terms", "is_putable"), "is_sinking": ("bond_terms", "is_sinking"),
    "is_perpetual": ("bond_terms", "is_perpetual"), "is_pik": ("bond_terms", "is_pik"),
    "msg_seq": ("bond_trades", "msg_seq"), "orig_msg_seq": ("bond_trades", "orig_msg_seq"),
    "action": ("bond_trades", "action"), "is_duplicate_side": ("bond_trades", "is_duplicate_side"),
    "execution_time": ("bond_trades", "execution_time"), "report_time": ("bond_trades", "report_time"),
    "prices": ("bond_trades", "price"), "sizes": ("bond_trades", "size"),
    "is_customer_buy": ("bond_trades", "is_customer_buy"), "S": ("equity_prices", "stock_close"),
    "daily_log_returns": ("equity_prices", "total_return"), "dividend": ("corporate_actions", "cash_amount"),
    "corporate actions": ("corporate_actions", "price_after"), "total_liabilities": ("accounts", "total_liabilities"),
    "shares_outstanding": ("accounts", "shares_out"), "acceptance_date": ("accounts", "available_at"),
    "period_end": ("accounts", "period_end"), "form": ("accounts", "form"), "tenors": ("rates", "tenor"),
    "par_yields": ("rates", "rate"), "r_5y": ("rates", "rate"), "repo": ("financing", "repo_rate"),
    "hedge_repo": ("financing", "repo_rate"), "cash_rate": ("rates", "rate"), "bond_fee": ("financing", "bond_fee"),
    "stock_fee": ("financing", "stock_fee"), "cds_market": ("cds_quotes", "spread"),
    "implied_vol": ("equity_prices", "atm_iv_12m"), "forced_event": ("events", "event_type"),
    "factors": ("factor_returns", "excess_return"),
}

FINKELSTEIN = {
    "stock_close": ("equity_prices", "stock_close"), "split_factor": ("corporate_actions", "split_factor"),
    "dividend": ("corporate_actions", "cash_amount"), "shares_out": ("equity_prices", "shares_out"),
    "borrow_fee": ("financing", "stock_fee"), "hard_to_borrow": ("financing", "hard_to_borrow"),
    "stock_half_spread": ("equity_prices", "half_spread"), "equity_id": ("equity_prices", "equity_id"),
    "option_id": ("option_quotes", "option_id"), "bid": ("option_quotes", "bid"), "ask": ("option_quotes", "ask"),
    "quote_time": ("option_quotes", "quote_time"), "volume": ("option_quotes", "volume"),
    "open_interest": ("option_quotes", "open_interest"), "exercise_style": ("option_quotes", "exercise_style"),
    "multiplier": ("option_quotes", "multiplier"), "vendor_iv": ("option_quotes", "vendor_iv"),
    "vendor_delta": ("option_quotes", "vendor_delta"), "bond_id": ("bond_terms", "bond_id"),
    "issuer_id": ("security_map", "issuer_id"), "coupon": ("bond_terms", "coupon"), "freq": ("bond_terms", "freq"),
    "maturity": ("bond_terms", "maturity_date"), "issue_date": ("bond_terms", "issue_date"),
    "day_count": ("bond_terms", "day_count"), "first_coupon": ("bond_terms", "first_coupon"),
    "seniority": ("bond_terms", "seniority"), "call_schedule": ("bond_terms", "call_schedule"),
    "floating flag": ("bond_terms", "is_floating"), "amount_out": ("bond_prices", "amount_out"),
    "trade_price": ("bond_trades", "price"), "trade_size": ("bond_trades", "size"),
    "trade_time": ("bond_trades", "execution_time"), "report_time": ("bond_trades", "report_time"),
    "side": ("bond_trades", "is_customer_buy"), "rating": ("issuer_attributes", "rating"),
    "repo_rate": ("financing", "repo_rate"), "bond_fee": ("financing", "bond_fee"),
    "st_debt": ("accounts", "st_debt"), "lt_debt": ("accounts", "lt_debt"), "other_st": ("accounts", "other_st_liab"),
    "other_lt": ("accounts", "other_lt_liab"), "minority": ("accounts", "minority_int"),
    "preferred": ("accounts", "pfd_equity"), "total_liabilities": ("accounts", "total_liabilities"),
    "filing_time": ("accounts", "available_at"), "par_yields": ("rates", "rate"), "cash_rate": ("rates", "rate"),
    "treasury_price": ("rates", "price"), "events": ("events", "event_type"),
    "realised_recovery": ("events", "realised_recovery"), "cds_par": ("cds_quotes", "spread"),
}

FK_DES = {
    "date": ("bond_prices", "date"), "bond_id": ("bond_prices", "bond_id"), "firm_id": ("security_map", "issuer_id"),
    "coupon": ("bond_terms", "coupon"), "freq": ("bond_terms", "freq"), "full_price": ("bond_prices", "full_price"),
    "coupon_paid": ("bond_prices", "coupon_paid"), "amount_out": ("bond_prices", "amount_out"),
    "entry_price": ("bond_prices", "entry_price"), "stock_close": ("equity_prices", "stock_close"),
    "split_factor": ("corporate_actions", "split_factor"), "dividend": ("corporate_actions", "cash_amount"),
    "shares_out": ("equity_prices", "shares_out"), "period_end": ("accounts", "period_end"),
    "available_date": ("accounts", "available_at"), "total_liabilities": ("accounts", "total_liabilities"),
    "dividends": ("accounts", "dividends"), "interest": ("accounts", "interest"),
    "repurchases": ("accounts", "repurchases"), "tenor": ("rates", "tenor"), "par_yield": ("rates", "rate"),
}
FK_DES_DERIVED = {"maturity_years"}  # the adapter computes it from maturity_date and date


@pytest.mark.parametrize("name,table", [("workbook", WORKBOOK), ("yu", YU), ("finkelstein", FINKELSTEIN), ("fk_des", FK_DES)])
def test_every_method_field_has_a_home(name, table):
    missing = {f: place for f, place in table.items() if place[1] not in all_columns(KINDS[place[0]])}
    assert not missing, f"{name}: {missing}"


def test_exactly_the_approved_kinds():
    assert set(KINDS) == {"security_map", "universe", "issuer_attributes", "equity_prices", "corporate_actions",
                          "accounts", "rates", "financing", "cds_quotes", "bond_terms", "bond_prices", "bond_trades",
                          "option_quotes", "events", "factor_returns"}
    assert len(KINDS) == 15
    assert all(isinstance(s, KindSpec) for s in KINDS.values())
    assert REQUIRED_KINDS <= set(KINDS)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_kind_carries_available_at_and_is_self_consistent(kind):
    s = KINDS[kind]
    assert "available_at" in s.required
    assert set(s.key) <= set(s.required) and "available_at" not in s.key
    assert s.id_column in s.required
    assert s.date_column is None or s.date_column in s.required
    assert not set(s.required) & set(s.optional)


def test_every_column_has_a_type_and_unit():
    used = {c for s in KINDS.values() for c in all_columns(s)}
    assert used == set(COLUMNS)
    assert all(c.type in {"text", "date", "float", "int", "bool"} and c.unit for c in COLUMNS.values())


def test_ranges_only_name_real_float_or_int_columns():
    assert all(COLUMNS[c].type in {"float", "int"} for c in RANGES)
    for c in ("rate", "spread", "coupon", "vendor_iv", "clean_price", "total_liabilities"):
        assert c in RANGES


def test_factor_returns_is_optional_monthly_decimal():
    assert "factor_returns" not in REQUIRED_KINDS
    assert KINDS["factor_returns"].key == ("date", "factor") and COLUMNS["excess_return"].unit == "decimal per month"
    assert "excess_return" in RANGES


def test_documented_conventions():
    assert COLUMNS["rate"].unit.startswith("decimal") and COLUMNS["spread"].unit.startswith("decimal")
    assert COLUMNS["realised_vol_30d"].unit.startswith("decimal") and COLUMNS["clean_price"].unit == "per 100 face"
    assert COLUMNS["total_liabilities"].unit == "USD" and COLUMNS["amount_out"].unit == "USD"


def test_unknown_kind_is_a_clear_error():
    with pytest.raises(ValueError, match="nonsense"):
        kind_spec("nonsense")


def test_schema_imports_nothing_from_the_package():
    import ast, inspect
    tree = ast.parse(inspect.getsource(schema))
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if m.startswith("e2c_data")]
