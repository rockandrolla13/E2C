"""The adapter from the data layer to fk_des.run_des_study. EVERY NUMBER IS MADE UP. F10 stays skipped in test_fk_des."""
import logging
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

import fk_des as fd
from e2c_data import PointInTimeView, make_synthetic_tables, open_source, write_tables
from e2c_data.source import DataUnavailable, LookAheadError
from inputs import DesInputs, build_des_inputs, years_30_360

LATE = datetime(2005, 12, 30, 18)


class Mem:
    def __init__(self, tables):
        self.tables = tables

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind].copy()


def build(tables, start=date(2004, 1, 1), end=date(2004, 6, 30), when=LATE):
    return build_des_inputs(PointInTimeView(Mem(tables), when), start, end)


@pytest.fixture()
def tables():
    return make_synthetic_tables()


# ---- end to end


def test_end_to_end_from_a_table_folder(tmp_path, monkeypatch, tables):
    write_tables(tables, tmp_path)
    monkeypatch.delenv("E2C_SOURCE", raising=False)
    monkeypatch.setenv("E2C_DATA_ROOT", str(tmp_path))
    view = PointInTimeView(open_source(), LATE)
    study = fd.run_des_study(*build_des_inputs(view, date(2005, 1, 1), date(2005, 12, 30)))
    assert study.bond_des.status.eq("ok").any()
    assert study.firm_des.quintile.notna().any()
    assert study.returns.gross.notna().any()
    assert len(study.summary) > 0


def test_columns_are_exactly_what_fk_des_takes(tables):
    got = build(tables)
    assert isinstance(got, DesInputs) and got._fields == ("bonds", "equities", "accounts", "rates")
    assert set(got.bonds.columns) == set(fd.BOND_COLUMNS) | {"entry_price"}
    assert set(got.equities.columns) == set(fd.EQUITY_COLUMNS)
    assert set(got.accounts.columns) == set(fd.ACCOUNT_COLUMNS)
    assert set(got.rates.columns) == set(fd.RATE_COLUMNS)


def test_shape_one_row_per_bond_month_and_firm_day(tables):
    got = build(tables)
    assert not got.bonds.assign(m=got.bonds.date.dt.to_period("M")).duplicated(["bond_id", "m"]).any()
    assert not got.equities.duplicated(["firm_id", "date"]).any()


def test_bond_date_is_the_last_price_of_its_month(tables):
    got = build(tables)
    b = got.bonds[got.bonds.bond_id == "B0011"]
    assert list(b.date) == list(pd.to_datetime(["2004-01-30", "2004-02-27", "2004-03-31", "2004-04-30", "2004-05-31", "2004-06-30"]))


def test_equities_carry_history_for_the_vol_window(tables):
    assert build(tables, date(2005, 1, 3), date(2005, 2, 28)).equities.date.min() <= pd.Timestamp("2003-01-03")


def test_end_past_decision_time_raises(tables):
    with pytest.raises(LookAheadError):
        build(tables, end=date(2004, 6, 30), when=datetime(2004, 6, 1))


def test_missing_kind_raises_rather_than_inventing_zeros(tables):
    del tables["corporate_actions"]
    with pytest.raises(DataUnavailable):
        build(tables)


# ---- restatement


def _restate(tables, issuer, period, available, factor):
    a = tables["accounts"]
    row = a[(a.issuer_id == issuer) & (a.period_end == pd.Timestamp(period))].iloc[[0]]
    row = row.assign(available_at=pd.Timestamp(available), total_liabilities=row.total_liabilities * factor)
    return {**tables, "accounts": pd.concat([a, row], ignore_index=True)}


def _firm(study, firm):
    f = study.firm_des[study.firm_des.firm_id == firm]
    return f.set_index(f.month.astype(str)).des_bp


def test_both_versions_reach_fk_des_with_available_date(tables):
    t = _restate(tables, "I003", "2004-12-31", "2005-03-01 16:00", 5.0)
    a = build(t, date(2005, 1, 1), date(2005, 6, 30)).accounts
    got = a[(a.firm_id == "I003") & (a.period_end == pd.Timestamp("2004-12-31"))].sort_values("available_date")
    assert list(got.available_date) == list(pd.to_datetime(["2005-02-14", "2005-03-01"]))
    assert got.total_liabilities.iloc[1] == pytest.approx(5 * got.total_liabilities.iloc[0])


def test_a_restatement_not_public_yet_stays_out(tables):
    t = _restate(tables, "I003", "2004-12-31", "2005-03-01", 5.0)
    a = build(t, date(2005, 1, 1), date(2005, 2, 28), when=datetime(2005, 2, 28, 18)).accounts
    assert len(a[(a.firm_id == "I003") & (a.period_end == pd.Timestamp("2004-12-31"))]) == 1


def test_fk_des_uses_the_version_known_at_each_date(tables):
    """Filed 14 Feb, usable 14 Apr. Restated 1 Mar, usable 1 May. The next period is filed 15 May, usable 15 Jul."""
    window = (date(2005, 1, 1), date(2005, 8, 31))
    small = fd.run_des_study(*build(_restate(tables, "I003", "2004-12-31", "2005-03-01", 1.5), *window))
    large = fd.run_des_study(*build(_restate(tables, "I003", "2004-12-31", "2005-03-01", 3.0), *window))
    a, b = _firm(small, "I003"), _firm(large, "I003")
    # before 1 May neither run can see the restated number, so changing it changes nothing
    for month in ("2005-01", "2005-02", "2005-03", "2005-04"):
        assert a[month] == b[month] or (np.isnan(a[month]) and np.isnan(b[month])), month
    assert np.isfinite(a["2005-04"])
    # from 1 May until the next filing is usable, the restated number is the one in use
    for month in ("2005-05", "2005-06"):
        assert np.isfinite(a[month]) and abs(a[month] - b[month]) > 1.0, month
    # the next filing replaces it
    for month in ("2005-07", "2005-08"):
        assert a[month] == pytest.approx(b[month]), month


def test_a_restatement_of_an_older_period_is_ignored_by_fk_des(tables):
    """fk_des's own documented rule: a late amendment of an older period does not displace newer accounts."""
    window = (date(2005, 1, 1), date(2005, 4, 30))
    base = fd.run_des_study(*build(tables, *window))
    changed = fd.run_des_study(*build(_restate(tables, "I003", "2004-06-30", "2005-03-01", 3.0), *window))
    a, b = _firm(base, "I003"), _firm(changed, "I003")
    assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)


# ---- dated link


def test_a_bond_that_changes_issuer_maps_right_on_both_sides(tables):
    b = build(tables).bonds  # I008 merges into I001 on 2004-03-19
    b = b[b.bond_id == "B0081"].set_index("date").firm_id
    assert b[pd.Timestamp("2004-01-30")] == "I008" and b[pd.Timestamp("2004-02-27")] == "I008"
    assert b[pd.Timestamp("2004-03-31")] == "I001" and b[pd.Timestamp("2004-06-30")] == "I001"


def test_stock_of_a_merged_name_stops_and_keeps_its_firm(tables):
    e = build(tables).equities
    assert e[e.firm_id == "I008"].date.max() == pd.Timestamp("2004-03-19")


def test_two_issuers_at_once_is_an_error(tables):
    m = tables["security_map"]
    tables["security_map"] = pd.concat([m, m[m.instrument_id == "B0011"].assign(issuer_id="I002", valid_from=pd.Timestamp("2000-06-01"))])
    with pytest.raises(ValueError, match="two issuers"):
        build(tables)


def test_rows_with_no_link_leave_and_are_counted_without_names(tables, caplog):
    m = tables["security_map"]
    tables["security_map"] = m[m.instrument_id != "B0021"]
    with caplog.at_level(logging.WARNING, logger="inputs"):
        got = build(tables)
    assert "B0021" not in set(got.bonds.bond_id)
    assert "bonds" in caplog.text and "B0021" not in caplog.text


# ---- units


def _set(df, mask, **values):
    for k, v in values.items():
        df.loc[mask, k] = v


def test_known_values_come_through_converted(tables):
    p, t = tables["bond_prices"], tables["bond_terms"]
    day = p.bond_id.eq("B0011") & p.date.eq(pd.Timestamp("2004-02-27"))
    february = p.bond_id.eq("B0011") & p.date.dt.to_period("M").eq(pd.Period("2004-02"))
    _set(p, february, coupon_paid=0.0)
    _set(p, p.bond_id.eq("B0011") & p.date.eq(pd.Timestamp("2004-02-16")), coupon_paid=2.75)
    _set(p, day, full_price=101.5, entry_price=101.6, amount_out=3e8)
    _set(t, t.bond_id.eq("B0011"), coupon=0.055, freq=2, maturity_date=pd.Timestamp("2010-06-15"))
    a = tables["accounts"]
    q = a.issuer_id.eq("I002") & a.period_end.eq(pd.Timestamp("2004-03-31"))
    _set(a, q, total_liabilities=5e9, dividends=2.5e8, interest=1e8, repurchases=5e7)
    r = tables["rates"]
    _set(r, r.curve.eq("treasury_par") & r.tenor.eq(5.0) & r.date.eq(pd.Timestamp("2004-02-27")), rate=0.045)

    got = build(tables)
    row = got.bonds[got.bonds.bond_id.eq("B0011") & got.bonds.date.eq(pd.Timestamp("2004-02-27"))].iloc[0]
    assert row.full_price == pytest.approx(1.015) and row.entry_price == pytest.approx(1.016)
    assert row.coupon_paid == pytest.approx(0.0275) and row.amount_out == pytest.approx(300.0)
    assert row.coupon == pytest.approx(0.055) and row.freq == 2
    assert row.maturity_years == pytest.approx(2268 / 360)
    acc = got.accounts[got.accounts.firm_id.eq("I002") & got.accounts.period_end.eq(pd.Timestamp("2004-03-31"))].iloc[0]
    assert acc.total_liabilities == pytest.approx(5000.0) and acc.dividends == pytest.approx(250.0)
    assert acc.interest == pytest.approx(100.0) and acc.repurchases == pytest.approx(50.0)
    y = got.rates[got.rates.tenor.eq(5.0) & got.rates.date.eq(pd.Timestamp("2004-02-27"))].par_yield.iloc[0]
    assert y == pytest.approx(0.045)
    assert set(got.rates.tenor) == {1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0}, "treasury curve only"


def test_stock_values_and_actions_come_through(tables):
    e = build(tables, date(2004, 9, 1), date(2004, 9, 30)).equities
    src = tables["equity_prices"]
    day = pd.Timestamp("2004-09-15")
    row = e[e.firm_id.eq("I002") & e.date.eq(day)].iloc[0]
    want = src[src.equity_id.eq("E002") & src.date.eq(day)].iloc[0]
    assert row.split_factor == 2.0 and row.stock_close == want.stock_close and row.shares_out == want.shares_out
    other = e[e.firm_id.eq("I003") & e.date.eq(day)].iloc[0]
    assert other.split_factor == 1.0 and other.dividend == 0.0
    ca = tables["corporate_actions"]
    ex = ca[ca.equity_id.eq("E003") & ca.action_type.eq("cash_dividend")].ex_date.iloc[0]
    got = build(tables, ex.date(), ex.date()).equities
    assert got[got.firm_id.eq("I003") & got.date.eq(ex)].dividend.iloc[0] == pytest.approx(0.1)


def test_action_on_a_day_with_no_price_moves_to_the_next_price(tables):
    ca = tables["corporate_actions"]
    _set(ca, ca.action_type.eq("split"), ex_date=pd.Timestamp("2004-09-18"))  # a Saturday
    e = build(tables, date(2004, 9, 1), date(2004, 9, 30)).equities
    assert e[e.firm_id.eq("I002") & e.date.eq(pd.Timestamp("2004-09-20"))].split_factor.iloc[0] == 2.0


def test_full_price_falls_back_to_clean_plus_accrued(tables):
    p = tables["bond_prices"]
    day = p.bond_id.eq("B0011") & p.date.eq(pd.Timestamp("2004-02-27"))
    _set(p, day, full_price=np.nan, clean_price=100.0, accrued=1.25)
    got = build(tables).bonds
    assert got[got.bond_id.eq("B0011") & got.date.eq(pd.Timestamp("2004-02-27"))].full_price.iloc[0] == pytest.approx(1.0125)


def test_shares_fall_back_to_market_cap_over_price(tables):
    q = tables["equity_prices"]
    day = q.equity_id.eq("E003") & q.date.eq(pd.Timestamp("2004-02-27"))
    _set(q, day, shares_out=np.nan, stock_close=40.0, mkt_cap=8e9)
    e = build(tables).equities
    assert e[e.firm_id.eq("I003") & e.date.eq(pd.Timestamp("2004-02-27"))].shares_out.iloc[0] == pytest.approx(2e8)


def test_missing_values_stay_nan(tables):
    p = tables["bond_prices"]
    february = p.bond_id.eq("B0011") & p.date.dt.to_period("M").eq(pd.Period("2004-02"))
    _set(p, february, coupon_paid=np.nan)
    a = tables["accounts"]
    _set(a, a.issuer_id.eq("I002") & a.period_end.eq(pd.Timestamp("2004-03-31")), dividends=np.nan)
    got = build(tables)
    assert np.isnan(got.bonds[got.bonds.bond_id.eq("B0011") & got.bonds.date.eq(pd.Timestamp("2004-02-27"))].coupon_paid.iloc[0])
    assert np.isnan(got.accounts[got.accounts.firm_id.eq("I002") & got.accounts.period_end.eq(pd.Timestamp("2004-03-31"))].dividends.iloc[0])


def test_a_cash_dividend_with_no_amount_stays_nan(tables):
    ca = tables["corporate_actions"]
    first = ca[ca.equity_id.eq("E003") & ca.action_type.eq("cash_dividend")].index[0]
    ca.loc[first, "cash_amount"] = np.nan
    ex = ca.loc[first, "ex_date"]
    e = build(tables, ex.date(), ex.date()).equities
    assert np.isnan(e[e.firm_id.eq("I003") & e.date.eq(ex)].dividend.iloc[0])


def test_entry_price_left_out_when_the_source_has_none(tables):
    tables["bond_prices"]["entry_price"] = np.nan
    assert "entry_price" not in build(tables).bonds.columns


def test_perpetual_bond_has_nan_maturity(tables):
    t = tables["bond_terms"]
    _set(t, t.bond_id.eq("B0011"), maturity_date=pd.NaT)
    assert build(tables).bonds.query("bond_id == 'B0011'").maturity_years.isna().all()


@pytest.mark.parametrize("a,b,want", [("2004-02-27", "2010-06-15", 2268 / 360), ("2004-01-31", "2004-03-31", 60 / 360),
                                      ("2004-06-15", "2004-06-15", 0.0), ("2004-01-31", "2004-02-15", 15 / 360)])
def test_years_30_360(a, b, want):
    got = years_30_360(pd.Series([pd.Timestamp(a)]), pd.Series([pd.Timestamp(b)]))
    assert got.iloc[0] == pytest.approx(want)


def test_rates_start_before_the_window_so_the_first_date_has_a_curve(tables):
    r = build(tables, date(2004, 2, 2), date(2004, 2, 27)).rates
    assert r.date.min() <= pd.Timestamp("2004-01-20")


def test_a_mid_month_start_still_counts_the_whole_month_of_coupon(tables):
    p = tables["bond_prices"]
    february = p.bond_id.eq("B0011") & p.date.dt.to_period("M").eq(pd.Period("2004-02"))
    _set(p, february, coupon_paid=0.0)
    _set(p, p.bond_id.eq("B0011") & p.date.eq(pd.Timestamp("2004-02-03")), coupon_paid=2.75)
    b = build(tables, date(2004, 2, 20), date(2004, 2, 27)).bonds
    assert b[b.bond_id.eq("B0011")].coupon_paid.iloc[0] == pytest.approx(0.0275)


def test_a_split_with_no_factor_stays_nan(tables):
    ca = tables["corporate_actions"]
    ca.loc[ca.action_type.eq("split"), "split_factor"] = np.nan
    e = build(tables, date(2004, 9, 1), date(2004, 9, 30)).equities
    assert np.isnan(e[e.firm_id.eq("I002") & e.date.eq(pd.Timestamp("2004-09-15"))].split_factor.iloc[0])
