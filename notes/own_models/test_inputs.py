"""The adapter from the data layer to e2c_model.run_pipeline. Synthetic numbers are made up. The real panel stays in tmp folders."""
import logging
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("e2c_data", reason="e2c_data is not on this branch. Set PYTHONPATH to a main checkout, or install it. See inputs.py")

import e2c_model as m
import inputs
from e2c_data import PointInTimeView, TableSource, check_source, failures, make_synthetic_tables, write_tables
from e2c_data.source import DataUnavailable, LookAheadError
from inputs import ACCOUNT_ITEMS, INPUT_COLUMNS, build_workbook_inputs

HERE = Path(__file__).parent
LATE = datetime(2005, 12, 30, 21)
CLOSE = pd.Timedelta(21, "h")
RELATIVE_TOLERANCE = 1e-9  # the unit conversions multiply and divide, so the last bits may differ


class Mem:
    def __init__(self, tables):
        self.tables = tables

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind].copy()


def build(tables, start=date(2004, 1, 1), end=date(2004, 6, 30), when=LATE, **kw):
    return build_workbook_inputs(PointInTimeView(Mem(tables), when), start, end, **kw)


@pytest.fixture()
def tables():
    return make_synthetic_tables()


# ---- the real panel


def panel_to_tables(panel: pd.DataFrame) -> dict:
    """Master panel to e2c_data tables, for a round trip only.

    The panel has no available_at, so this converter makes one up: every row is public at 21:00 on its own date. Accounts become
    one row per change in a name's six items, with period_end and available_at taken from the week the change appears. So the
    round trip proves plumbing, not point-in-time correctness. The workbook's own timing is not point in time (Table 1).
    """
    p = panel.assign(date=pd.to_datetime(panel.date)).sort_values(["ticker", "date"])
    stamp = p.date + CLOSE
    first = p.groupby("ticker").date.transform("min")
    names = p[p.date == first]
    security_map = pd.DataFrame({"instrument_id": names.ticker, "instrument_type": "equity", "issuer_id": names.ticker,
                                 "valid_from": names.date, "valid_to": pd.NaT, "available_at": names.date + CLOSE, "ticker": names.ticker})
    universe = pd.DataFrame({"issuer_id": names.ticker, "start_date": names.date, "end_date": pd.NaT, "available_at": names.date + CLOSE})
    attributes = pd.DataFrame({"issuer_id": names.ticker, "date": names.date, "sector": names.sector, "available_at": names.date + CLOSE})
    equity = pd.DataFrame({"date": p.date, "equity_id": p.ticker, "stock_close": p.price, "mkt_cap": p.mkt_cap * 1e6, "available_at": stamp})
    for vendor, column in (("realised_vol_30d", "vol_30d"), ("realised_vol_60d", "vol_60d"), ("realised_vol_90d", "vol_90d"),
                           ("realised_vol_180d", "vol_180d"), ("realised_vol_360d", "vol_360d"), ("realised_vol_162w", "vol_162w"),
                           ("put_iv_3m", "put_3m"), ("put_iv_6m", "put_6m"), ("put_iv_12m", "put_12m"), ("put_iv_24m", "put_24m")):
        equity[vendor] = p[column] / 100
    cds = pd.DataFrame({"date": p.date, "issuer_id": p.ticker, "tenor": 5.0, "spread": p.spread_bp / 1e4, "available_at": stamp})
    filled = p[ACCOUNT_ITEMS].fillna(-1e300)  # a blank equals a blank when looking for changes
    changed = filled.ne(filled.groupby(p.ticker).shift(1)).any(axis=1)
    accounts = p.loc[changed, ["ticker", "date"] + ACCOUNT_ITEMS].rename(columns={"ticker": "issuer_id", "date": "period_end"})
    accounts = accounts.assign(available_at=accounts.period_end + CLOSE, **{c: accounts[c] * 1e6 for c in ACCOUNT_ITEMS})
    days = p.drop_duplicates("date")
    rates = pd.DataFrame({"date": days.date, "curve": "swap", "tenor": 5.0, "rate": days.swap_5y_pct / 100, "available_at": days.date + CLOSE})
    return dict(security_map=security_map, universe=universe, issuer_attributes=attributes, equity_prices=equity, cds_quotes=cds,
                accounts=accounts, rates=rates)


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    if not (HERE / "master_panel.csv.gz").exists():
        pytest.skip("master_panel.csv.gz is local only and is not in the repo")
    panel = pd.read_csv(HERE / "master_panel.csv.gz", low_memory=False)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["next_date"] = pd.to_datetime(panel["next_date"])
    root = tmp_path_factory.mktemp("panel_tables")
    write_tables(panel_to_tables(panel), root)
    when = panel.date.max() + CLOSE
    view = PointInTimeView(TableSource(root), when)
    rebuilt = build_workbook_inputs(view, panel.date.min().date(), panel.date.max().date())
    original = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    return dict(panel=panel, original=original, rebuilt=rebuilt, root=root, when=when,
                out_panel=m.run_pipeline(original[INPUT_COLUMNS], m.MASTER_PARAMS),
                out_rebuilt=m.run_pipeline(rebuilt, m.MASTER_PARAMS))


def test_round_trip_loses_and_adds_no_rows(real):
    assert len(real["rebuilt"]) == len(real["panel"]) == 19489
    keys = lambda f: set(zip(f.date, f.ticker))  # noqa: E731
    assert keys(real["rebuilt"]) == keys(real["panel"])
    assert real["rebuilt"].attrs["e2c_report"]["left_out"] == {"no_link": 0, "no_cds": 0, "no_accounts": 0, "no_swap": 0}


@pytest.mark.parametrize("column", [c for c in INPUT_COLUMNS if c not in ("date", "ticker", "sector", "next_date")])
def test_round_trip_number_columns(real, column):
    a, b = real["original"][column].astype(float), real["rebuilt"][column].astype(float)
    assert a.isna().equals(b.isna()), "same blanks"
    gap = (a - b).abs() / a.abs().clip(lower=1.0)
    assert gap.max(skipna=True) <= RELATIVE_TOLERANCE or a.isna().all()


@pytest.mark.parametrize("column", ["date", "ticker", "sector", "next_date"])
def test_round_trip_other_columns_are_identical(real, column):
    pd.testing.assert_series_equal(real["original"][column], real["rebuilt"][column], check_dtype=False, check_names=False)


def test_all_columns_in_table_1_order(real):
    assert list(real["rebuilt"].columns) == INPUT_COLUMNS and len(INPUT_COLUMNS) == 26


def test_panel_routes_are_all_vendor(real):
    routes = real["rebuilt"].attrs["e2c_report"]["vol_routes"]
    assert {r["route"] for r in routes.values()} == {"vendor"}
    assert routes["put_3m"]["blank"] == 10945 and routes["put_24m"]["blank"] == 15368


def _names(out):
    return out["names"].sort_values(["date", "ticker"]).reset_index(drop=True)


def test_results_match_on_the_real_panel(real):
    a, b = _names(real["out_panel"]), _names(real["out_rebuilt"])
    assert len(a) == len(b) and len(real["out_panel"]["unsolved"]) == len(real["out_rebuilt"]["unsolved"])
    for flag in ("long_flag", "short_flag", "close_flag"):
        assert (a[flag] == b[flag]).all(), flag
    for c in ("implied", "residual", "size_long", "size_short", "delta_long", "delta_short", "pnl_total"):
        assert np.allclose(a[c].astype(float), b[c].astype(float), rtol=1e-7, atol=1e-7, equal_nan=True), c
    wa, wb = real["out_panel"]["weeks"], real["out_rebuilt"]["weeks"]
    assert np.allclose(wa.alpha, wb.alpha, rtol=1e-9, atol=1e-10, equal_nan=True)
    assert np.allclose(wa.pnl_total, wb.pnl_total, rtol=1e-7, atol=1e-6)


def test_headline_numbers_match_the_workbook_cells(real):
    s, w = real["out_rebuilt"]["summary"], real["out_rebuilt"]["weeks"]
    assert s["sharpe"] == pytest.approx(real["out_panel"]["summary"]["sharpe"], abs=1e-9)
    assert s["sharpe"] == pytest.approx(2.51061644473834, abs=1e-6)  # Reg!CK6
    assert s["nav_end"] == pytest.approx(1.7991755029443506, abs=1e-6)  # Reg!CM6
    assert w.pnl_total.sum() == pytest.approx(20477.819198244164, abs=1e-3)  # Reg!BA7


def test_check_source_shows_the_panel_is_survivors_only_as_far_as_it_can_tell(real):
    """The panel holds no ended name, so this converter ends none. check_source says so. Nothing here fixes it."""
    report = check_source(TableSource(real["root"]), real["when"])
    bad = failures(report)
    assert list(zip(bad.check, bad.kind)) == [("survivorship", "universe")]
    assert bad["count"].iloc[0] == 170


# ---- end to end on synthetic tables


def test_end_to_end_on_synthetic_tables(tables):
    frame = build(tables, date(2003, 1, 1), date(2005, 12, 30))
    assert list(frame.columns) == INPUT_COLUMNS
    assert {r["route"] for r in frame.attrs["e2c_report"]["vol_routes"].values()} == {"vendor"}
    assert frame.drop(columns=["sector", "next_date", "next_spread_bp", "next_price"]).notna().all().all(), "synthetic.py carries them all"
    out = m.run_pipeline(frame, m.MASTER_PARAMS)
    assert len(out["names"]) > 0 and np.isfinite(out["summary"]["nav_end"])


def test_a_friday_only_grid(tables):
    frame = build(tables)
    assert frame.date.dt.dayofweek.eq(4).all()
    assert not frame.duplicated(["date", "ticker"]).any()


def test_a_week_ending_after_end_is_left_out(tables):
    assert build(tables, date(2004, 2, 2), date(2004, 2, 18)).date.max() == pd.Timestamp("2004-02-13")


def test_holiday_friday_uses_the_last_row_of_the_week_and_keeps_the_friday_label(tables):
    q = tables["equity_prices"]
    friday = pd.Timestamp("2004-04-09")
    thursday_close = q[q.equity_id.eq("E002") & q.date.eq(pd.Timestamp("2004-04-08"))].stock_close.iloc[0]
    tables["equity_prices"] = q[q.date != friday]
    c = tables["cds_quotes"]
    tables["cds_quotes"] = c[c.date != friday]
    frame = build(tables)
    assert frame[frame.ticker.eq("TK2") & frame.date.eq(friday)].price.iloc[0] == thursday_close


def test_end_past_decision_time_raises(tables):
    with pytest.raises(LookAheadError):
        build(tables, end=date(2004, 6, 30), when=datetime(2004, 6, 1))


def test_missing_needed_kinds_raise(tables):
    for kind in ("cds_quotes", "rates", "equity_prices", "security_map", "accounts"):
        t = dict(tables)
        del t[kind]
        with pytest.raises(DataUnavailable):
            build(t)


def test_missing_sector_stays_blank(tables):
    del tables["issuer_attributes"]
    assert build(tables).sector.isna().all()


# ---- next-row fields


def test_next_fields_are_the_same_names_next_row(tables):
    f = build(tables)
    t = f[f.ticker == "TK3"].reset_index(drop=True)
    assert t.next_date.iloc[0] == t.date.iloc[1] and t.next_price.iloc[0] == t.price.iloc[1] and t.next_spread_bp.iloc[0] == t.spread_bp.iloc[1]
    assert t[["next_date", "next_price", "next_spread_bp"]].iloc[-1].isna().all()


def test_next_fields_do_not_read_past_end(tables):
    f = build(tables, end=date(2004, 6, 25))
    assert f[f.date == f.date.max()].next_price.isna().all()


def test_next_fields_cannot_feed_the_signal(tables):
    """Scramble them. The signal, sizes and hedges stay, and only P&L moves."""
    f = build(tables, date(2003, 1, 1), date(2005, 12, 30))
    a = m.run_pipeline(f, m.MASTER_PARAMS)["names"]
    rng = np.random.default_rng(1)
    scrambled = f.assign(next_price=f.next_price * rng.uniform(0.5, 1.5, len(f)), next_spread_bp=f.next_spread_bp * rng.uniform(0.5, 1.5, len(f)))
    b = m.run_pipeline(scrambled, m.MASTER_PARAMS)["names"]
    for c in ("implied", "residual", "fair_vol", "long_flag", "short_flag", "target", "size_long", "size_short", "delta_long", "delta_short"):
        assert np.array_equal(a[c].astype(float), b[c].astype(float), equal_nan=True), c
    assert not np.allclose(a.pnl_total.astype(float), b.pnl_total.astype(float), equal_nan=True)


def test_a_later_week_changes_only_the_next_fields_of_the_week_before(tables):
    day = pd.Timestamp("2004-06-25")
    base = build(tables)
    q, c = tables["equity_prices"], tables["cds_quotes"]
    q.loc[q.equity_id.eq("E003") & q.date.eq(day), "stock_close"] *= 2
    c.loc[c.issuer_id.eq("I003") & c.date.eq(day), "spread"] *= 2
    changed = build(tables)
    earlier = base.date < day
    diff = [col for col in INPUT_COLUMNS if not base.loc[earlier, col].equals(changed.loc[earlier, col])]
    assert diff == ["next_spread_bp", "next_price"]


# ---- units


def _set(df, mask, **values):
    for k, v in values.items():
        df.loc[mask, k] = v


def test_known_values_come_through_in_workbook_units(tables):
    friday = pd.Timestamp("2004-02-27")
    q, c, a, r = tables["equity_prices"], tables["cds_quotes"], tables["accounts"], tables["rates"]
    _set(q, q.equity_id.eq("E002") & q.date.eq(friday), stock_close=40.0, mkt_cap=8e9, realised_vol_30d=0.35, realised_vol_162w=0.41, put_iv_12m=0.28)
    _set(c, c.issuer_id.eq("I002") & c.date.eq(friday) & c.tenor.eq(5.0), spread=0.0125)
    _set(c, c.issuer_id.eq("I002") & c.date.eq(friday) & c.tenor.eq(1.0), spread=0.0999)
    filed = a[a.issuer_id.eq("I002") & (a.available_at <= friday)].period_end.max()
    _set(a, a.issuer_id.eq("I002") & a.period_end.eq(filed), st_debt=1.5e9, lt_debt=2e9, other_st_liab=3e8, other_lt_liab=4e8, minority_int=5e7, pfd_equity=6e7)
    _set(r, r.curve.eq("swap") & r.date.eq(friday), rate=0.0425)
    row = build(tables).query("ticker == 'TK2' and date == @friday").iloc[0]
    assert row.price == 40.0 and row.mkt_cap == pytest.approx(8000.0) and row.spread_bp == pytest.approx(125.0)
    assert row.vol_30d == pytest.approx(35.0) and row.vol_162w == pytest.approx(41.0) and row.put_12m == pytest.approx(28.0)
    assert row.swap_5y_pct == pytest.approx(4.25)
    assert row.st_debt == pytest.approx(1500.0) and row.lt_debt == pytest.approx(2000.0) and row.other_st_liab == pytest.approx(300.0)
    assert row.other_lt_liab == pytest.approx(400.0) and row.minority_int == pytest.approx(50.0) and row.pfd_equity == pytest.approx(60.0)


def test_market_cap_falls_back_to_price_times_shares(tables):
    friday = pd.Timestamp("2004-02-27")
    q = tables["equity_prices"]
    _set(q, q.equity_id.eq("E002") & q.date.eq(friday), stock_close=40.0, mkt_cap=np.nan, shares_out=1e8)
    assert build(tables).query("ticker == 'TK2' and date == @friday").mkt_cap.iloc[0] == pytest.approx(4000.0)


def test_only_the_named_swap_tenor_and_curve_are_used(tables):
    f = build(tables, swap_curve="treasury_par", swap_tenor=30.0)
    assert (f.swap_5y_pct != build(tables).swap_5y_pct).all()
    r = tables["rates"]
    tables["rates"] = r[~r.curve.eq("swap")]
    blank = build(tables)
    assert blank.swap_5y_pct.isna().all() and blank.attrs["e2c_report"]["left_out"]["no_swap"] == len(blank)


# ---- accounts carried forward


def _accounts_row(tables, issuer, period, available, st_debt):
    a = tables["accounts"]
    row = a[a.issuer_id == issuer].iloc[[0]].assign(period_end=pd.Timestamp(period), available_at=pd.Timestamp(available), st_debt=st_debt)
    return {**tables, "accounts": pd.concat([a, row], ignore_index=True)}


def _st_debt(frame, ticker, friday):
    return frame[frame.ticker.eq(ticker) & frame.date.eq(pd.Timestamp(friday))].st_debt.iloc[0]


def test_accounts_carry_forward_from_the_day_they_are_public(tables):
    t = _accounts_row(tables, "I003", "2004-06-15", "2004-06-16 12:00", 7.7e9)
    f = build(t)
    assert _st_debt(f, "TK3", "2004-06-11") != pytest.approx(7700.0)
    assert _st_debt(f, "TK3", "2004-06-18") == pytest.approx(7700.0) and _st_debt(f, "TK3", "2004-06-25") == pytest.approx(7700.0)


def test_a_filing_after_fridays_close_waits_a_week(tables):
    t = _accounts_row(tables, "I003", "2004-06-15", "2004-06-18 22:00", 7.7e9)
    f = build(t)
    assert _st_debt(f, "TK3", "2004-06-18") != pytest.approx(7700.0) and _st_debt(f, "TK3", "2004-06-25") == pytest.approx(7700.0)


def test_a_restatement_uses_the_version_known_each_week(tables):
    t = _accounts_row(tables, "I003", "2004-06-15", "2004-06-16", 7.7e9)
    t = _accounts_row(t, "I003", "2004-06-15", "2004-06-23", 9.9e9)
    f = build(t)
    assert _st_debt(f, "TK3", "2004-06-18") == pytest.approx(7700.0) and _st_debt(f, "TK3", "2004-06-25") == pytest.approx(9900.0)


def test_a_late_amendment_of_an_older_period_does_not_displace_newer_accounts(tables):
    t = _accounts_row(tables, "I003", "2004-06-15", "2004-06-16", 7.7e9)
    t = _accounts_row(t, "I003", "2003-06-30", "2004-06-23", 9.9e9)
    assert _st_debt(build(t), "TK3", "2004-06-25") == pytest.approx(7700.0)


def test_a_name_with_no_filing_yet_leaves_and_is_counted(tables, caplog):
    a = tables["accounts"]
    tables["accounts"] = a[a.issuer_id != "I003"]
    with caplog.at_level(logging.WARNING, logger="inputs"):
        f = build(tables)
    assert "TK3" not in set(f.ticker)
    assert f.attrs["e2c_report"]["left_out"]["no_accounts"] > 0 and "no_accounts" in caplog.text and "I003" not in caplog.text


def test_a_blank_item_stays_blank(tables):
    a = tables["accounts"]
    _set(a, a.issuer_id.eq("I003"), minority_int=np.nan)
    assert build(tables).query("ticker == 'TK3'").minority_int.isna().all()


# ---- dated link


def _move_equity(tables, equity, old, new, on):
    m_ = tables["security_map"]
    keep = m_[m_.instrument_id != equity]
    first = m_[m_.instrument_id == equity].iloc[[0]]
    moved = pd.concat([first.assign(issuer_id=old, valid_to=pd.Timestamp(on) - pd.Timedelta(1, "D")),
                       first.assign(issuer_id=new, valid_from=pd.Timestamp(on), ticker="NEWTK")], ignore_index=True)
    return {**tables, "security_map": pd.concat([keep, moved], ignore_index=True)}


def test_a_stock_that_changes_issuer_maps_right_on_both_sides(tables):
    t = _move_equity(tables, "E003", "I003", "I004", "2004-03-22")
    f = build(t)
    cds = t["cds_quotes"].query("tenor == 5.0")
    before, after = pd.Timestamp("2004-03-19"), pd.Timestamp("2004-03-26")
    b = f[f.ticker.eq("TK3") & f.date.eq(before)].iloc[0]
    assert b.spread_bp == pytest.approx(cds[cds.issuer_id.eq("I003") & cds.date.eq(before)].spread.iloc[0] * 1e4)
    assert b.sector == t["issuer_attributes"].query("issuer_id == 'I003'").sector.iloc[0]
    n = f[f.ticker.eq("NEWTK") & f.date.eq(after)].iloc[0]
    assert n.spread_bp == pytest.approx(cds[cds.issuer_id.eq("I004") & cds.date.eq(after)].spread.iloc[0] * 1e4)
    assert n.sector == t["issuer_attributes"].query("issuer_id == 'I004'").sector.iloc[0]
    assert f[f.ticker.eq("TK3")].date.max() == before and f[f.ticker.eq("NEWTK")].date.min() == after


def test_two_issuers_at_once_is_an_error(tables):
    m_ = tables["security_map"]
    other = m_[m_.instrument_id == "E003"].assign(issuer_id="I004", valid_from=pd.Timestamp("2000-06-01"))
    tables["security_map"] = pd.concat([m_, other], ignore_index=True)
    with pytest.raises(ValueError, match="two issuers"):
        build(tables)


def test_rows_with_no_link_leave_and_are_counted(tables):
    m_ = tables["security_map"]
    tables["security_map"] = m_[m_.instrument_id != "E003"]
    f = build(tables)
    assert "TK3" not in set(f.ticker) and f.attrs["e2c_report"]["left_out"]["no_link"] > 0


# ---- vol routes


VENDOR_REALISED = ["realised_vol_30d", "realised_vol_60d", "realised_vol_90d", "realised_vol_180d", "realised_vol_360d", "realised_vol_162w"]
PUT = ["put_iv_3m", "put_iv_6m", "put_iv_12m", "put_iv_24m"]


def _no_vendor(tables, columns):
    return {**tables, "equity_prices": tables["equity_prices"].drop(columns=columns)}


def test_vendor_route_takes_the_vendor_number(tables):
    friday = pd.Timestamp("2004-02-27")
    q = tables["equity_prices"]
    _set(q, q.equity_id.eq("E002") & q.date.eq(friday), realised_vol_60d=0.1234)
    f = build(tables)
    assert f.query("ticker == 'TK2' and date == @friday").vol_60d.iloc[0] == pytest.approx(12.34)
    assert f.attrs["e2c_report"]["vol_routes"]["vol_60d"] == dict(route="vendor", values=len(f), blank=0)


def test_no_vendor_and_no_derive_leaves_blank_and_counts(tables, caplog):
    with caplog.at_level(logging.WARNING, logger="inputs"):
        f = build(_no_vendor(tables, VENDOR_REALISED + PUT))
    for c in ("vol_30d", "vol_360d", "vol_162w", "put_3m"):
        assert f[c].isna().all() and f.attrs["e2c_report"]["vol_routes"][c] == dict(route="none", values=0, blank=len(f))
    assert "vol_30d: route none" in caplog.text


def test_a_blank_vendor_cell_is_never_filled_even_with_derive_on(tables):
    q = tables["equity_prices"]
    friday = pd.Timestamp("2005-06-24")
    _set(q, q.equity_id.eq("E002") & q.date.eq(friday), realised_vol_30d=np.nan)
    f = build(tables, date(2005, 1, 1), date(2005, 6, 30), derive_vols=True)
    assert np.isnan(f.query("ticker == 'TK2' and date == @friday").vol_30d.iloc[0])
    r = f.attrs["e2c_report"]["vol_routes"]["vol_30d"]
    assert r["route"] == "vendor" and r["blank"] == 1


def test_derived_route_matches_the_documented_rule(tables):
    t = _no_vendor(tables, VENDOR_REALISED)
    friday = pd.Timestamp("2005-06-24")
    f = build(t, date(2005, 1, 1), date(2005, 6, 30), derive_vols=True)
    report = f.attrs["e2c_report"]["vol_routes"]
    assert report["vol_30d"]["route"] == "derived" and report["vol_162w"]["route"] == "derived"
    close = tables["equity_prices"].query("equity_id == 'E003'").set_index("date").stock_close
    ret = np.log(close / close.shift(1))[:friday]
    for column, n in (("vol_30d", 30), ("vol_360d", 360)):
        want = ret.iloc[-n:].std(ddof=1) * np.sqrt(252) * 100
        assert f.query("ticker == 'TK3' and date == @friday")[column].iloc[0] == pytest.approx(want)


def test_derived_162_week_vol_uses_weekly_returns(tables, monkeypatch):
    """Synthetic data has 156 weeks, so 162 weeks stay blank, and the rule is checked on 40."""
    t = _no_vendor(tables, VENDOR_REALISED)
    assert inputs.WEEKS_162 == 162
    assert build(t, date(2005, 12, 1), date(2005, 12, 30), derive_vols=True).vol_162w.isna().all()
    monkeypatch.setattr(inputs, "WEEKS_162", 40)
    f = build(t, date(2005, 12, 1), date(2005, 12, 30), derive_vols=True)
    friday = pd.Timestamp("2005-12-30")
    close = tables["equity_prices"].query("equity_id == 'E003'").set_index("date").stock_close
    weekly = np.log(close.resample("W-FRI").last()).diff()[:friday]
    want = weekly.iloc[-40:].std(ddof=1) * np.sqrt(52) * 100
    assert f.query("ticker == 'TK3' and date == @friday").vol_162w.iloc[0] == pytest.approx(want)


def test_derived_vols_need_a_full_window(tables):
    f = build(_no_vendor(tables, VENDOR_REALISED), date(2003, 1, 1), date(2003, 3, 28), derive_vols=True)
    assert f.vol_360d.isna().all() and f.attrs["e2c_report"]["vol_routes"]["vol_360d"]["blank"] == len(f)
    assert f.query("date == '2003-03-28'").vol_30d.notna().all() and f.query("date == '2003-01-10'").vol_30d.isna().all()


def test_derived_vols_are_split_adjusted(tables):
    t = _no_vendor(tables, VENDOR_REALISED)
    f = build(t, date(2004, 9, 1), date(2004, 10, 29), derive_vols=True)
    assert f.query("ticker == 'TK2' and date == '2004-09-24'").vol_30d.iloc[0] < 100.0, "the 2:1 split on 15 Sep is not a return"


def test_put_vols_are_never_derived(tables):
    f = build(_no_vendor(tables, VENDOR_REALISED + PUT), date(2005, 1, 1), date(2005, 6, 30), derive_vols=True)
    for c in ("put_3m", "put_6m", "put_12m", "put_24m"):
        assert f.attrs["e2c_report"]["vol_routes"][c]["route"] == "none" and f[c].isna().all()


def test_a_derived_run_goes_through_run_pipeline(tables):
    f = build(_no_vendor(tables, VENDOR_REALISED + PUT), date(2005, 1, 1), date(2005, 12, 30), derive_vols=True)
    assert len(m.run_pipeline(f, m.MASTER_PARAMS)["names"]) > 0


# ---- closing the mutation survivors


def test_a_longer_cds_tenor_is_not_taken_for_the_five_year(tables):
    c = tables["cds_quotes"]
    tables["cds_quotes"] = pd.concat([c, c[c.tenor.eq(5.0)].assign(tenor=10.0, spread=0.0999)], ignore_index=True)
    assert build(tables).spread_bp.lt(999.0).all()


def test_a_longer_swap_tenor_is_not_taken_for_the_five_year(tables):
    r = tables["rates"]
    tables["rates"] = pd.concat([r, r[r.curve.eq("swap")].assign(tenor=10.0, rate=0.0999)], ignore_index=True)
    assert build(tables).swap_5y_pct.lt(9.99).all()


def test_a_name_with_no_cds_leaves_and_is_counted(tables):
    c = tables["cds_quotes"]
    tables["cds_quotes"] = c[c.issuer_id != "I003"]
    f = build(tables)
    assert "TK3" not in set(f.ticker) and f.attrs["e2c_report"]["left_out"]["no_cds"] > 0


def test_a_link_with_no_ticker_uses_the_equity_id(tables):
    tables["security_map"] = tables["security_map"].drop(columns="ticker")
    assert "E003" in set(build(tables).ticker)


def test_two_stocks_with_one_ticker_is_an_error(tables):
    s = tables["security_map"]
    s.loc[s.instrument_id.eq("E004"), "ticker"] = "TK3"
    with pytest.raises(ValueError, match="one ticker"):
        build(tables)
