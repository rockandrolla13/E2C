"""The adapter from the data layer to e2c_bond's backtests. Every number here is made up. There is no real Yu panel on this branch."""
from dataclasses import replace
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("e2c_data", reason="e2c_data is not on this branch. Set PYTHONPATH to a main checkout, or install it. See inputs.py")

import e2c_bond as m
from e2c_data import PointInTimeView, TableSource, make_synthetic_tables, open_source, write_tables
from e2c_data.source import DataUnavailable, LookAheadError
from inputs import build_bond_panel, build_cds_panel, build_factors, with_peer_gaps, years_30_360

LATE = datetime(2005, 12, 30, 21)
START, END = date(2003, 1, 1), date(2005, 12, 30)
CLOSE = pd.Timedelta(21, "h")


class Mem:
    def __init__(self, tables):
        self.tables = tables

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind].copy()


def view_of(tables, when=LATE):
    return PointInTimeView(Mem(tables), when)


def daily_trades(bond_prices, half_point=0.25):
    """A customer buy and a customer sell each day around the clean price, reported an hour later. synthetic.py has one print a week."""
    rows, seq = [], 0
    for b, day, clean in zip(bond_prices.bond_id, bond_prices.date, bond_prices.clean_price):
        when = day + pd.Timedelta(10, "h")
        for buy, price in ((True, clean + half_point), (False, clean - half_point)):
            seq += 1
            rows.append(dict(bond_id=b, msg_seq=seq, execution_time=when, price=price, size=1e6, orig_msg_seq=np.nan, action="new", is_duplicate_side=False,
                             is_customer_buy=buy, report_time=when + pd.Timedelta(1, "h"), available_at=when + pd.Timedelta(1, "h")))
    return pd.DataFrame(rows)


@pytest.fixture()
def tables():
    t = make_synthetic_tables()
    keep = t["bond_prices"].bond_id.isin(["B0031", "B0041", "B0081", "B0021"])
    return {**t, "bond_trades": daily_trades(t["bond_prices"][keep & (t["bond_prices"].date >= pd.Timestamp("2005-03-01"))])}


def build(tables, bond="B0031", start=date(2005, 3, 1), end=date(2005, 8, 31), when=LATE, **kw):
    kw.setdefault("vol_source", "implied")
    kw.setdefault("hedge_id", "UST5Y")
    return build_bond_panel(view_of(tables, when), bond, start, end, **kw)


def at(built, day, field):
    return getattr(built.panel, field)[built.dates.get_loc(pd.Timestamp(day))]


# ---- end to end


def model_priced(tables, bond, gap, start=date(2005, 1, 3), end=END):
    """Replace one bond's prints: e2c_bond's model price at L_bar 0.8, plus e2c_bond's injected gap from row 30. Prints start ten days early to pass liquidity."""
    base = build_bond_panel(view_of(tables), bond, start, end, vol_source="implied", hedge_id="UST5Y")
    priced = m.inject_gap(m.panel_with_no_gap(base.panel, TRUE_L, R_B, LAM), TRUE_L, 30, gap, 30, R_B, LAM)
    before = pd.bdate_range(end=base.dates[0] - pd.Timedelta(1, "D"), periods=10)
    rows = pd.DataFrame({"bond_id": bond, "date": list(before) + list(base.dates), "clean_price": [priced.clean[0] * 100] * 10 + list(priced.clean * 100)})
    t = tables["bond_trades"]
    new = daily_trades(rows).assign(msg_seq=lambda d: d.msg_seq + int(t.msg_seq.max() if len(t) else 0))
    tables["bond_trades"] = pd.concat([t[t.bond_id != bond], new], ignore_index=True)


def test_end_to_end_from_a_folder_gives_trades(tmp_path, monkeypatch):
    """Default config. synthetic.py's prices are noise, so the traded bond is repriced on e2c_bond's model with its injected gap. B0041 stays as synthetic.py made it."""
    t = make_synthetic_tables()
    p = t["bond_prices"]
    t["bond_trades"] = daily_trades(p[p.bond_id.eq("B0041") & (p.date >= pd.Timestamp("2005-01-03"))])
    model_priced(t, "B0031", 0.02)
    write_tables(t, tmp_path)
    monkeypatch.delenv("E2C_SOURCE", raising=False)
    monkeypatch.setenv("E2C_DATA_ROOT", str(tmp_path))
    view = PointInTimeView(open_source(), LATE)
    config = m.BacktestConfig()
    built = with_peer_gaps([build_bond_panel(view, b, date(2005, 1, 3), END, vol_source="implied", hedge_id="UST5Y") for b in ("B0031", "B0041")], config)
    result = m.run_bond_backtest(built[0].panel, config)
    assert result.status == "ok" and len(result.trades) >= 1
    assert result.trades[0].side == 1 and all(np.isfinite(x.hpr) for x in result.trades)
    assert result.L_bar == pytest.approx(TRUE_L, abs=1e-2)


def test_synthetic_prices_alone_give_no_trades_under_the_default_config():
    """The finding, kept as a test: with daily prints added, synthetic.py's random prices are mostly under the curve, so the gap is undefined on most days."""
    t = make_synthetic_tables()
    p = t["bond_prices"]
    t["bond_trades"] = daily_trades(p[p.bond_id.eq("B0031")])
    built = with_peer_gaps([build_bond_panel(view_of(t), "B0031", START, END, vol_source="implied", hedge_id="UST5Y")], m.BacktestConfig())[0]
    result = m.run_bond_backtest(built.panel, m.BacktestConfig())
    assert result.trades == [] and np.nanmean(result.z_market <= 0) > 0.5


def test_synthetic_weekly_prints_fail_the_liquidity_screen_and_give_no_trades():
    """The finding, kept as a test: unchanged synthetic.py has about one print a week, so the default screen stops every day."""
    built = build_bond_panel(view_of(make_synthetic_tables()), "B0031", START, END, vol_source="implied", hedge_id="UST5Y")
    assert built.report["screens_failed"]["liquidity"] == built.report["rows"] and built.report["tradable_days"] == 0
    result = m.run_bond_backtest(replace(built.panel, peer_gap=np.zeros(len(built.dates))), m.BacktestConfig())
    assert result.status == "too_few_days" and result.trades == []


def test_historical_vol_needs_750_returns_so_synthetic_rows_leave_and_are_counted(tables):
    built = build(tables, start=START, end=END, vol_source="historical")
    assert built.report["left_out"]["no_vol"] > 700 and np.isfinite(built.panel.sigma_s).all()
    assert m.run_bond_backtest(replace(built.panel, peer_gap=np.zeros(len(built.dates))), m.BacktestConfig()).status == "too_few_days"


def test_end_past_decision_time_raises(tables):
    with pytest.raises(LookAheadError):
        build(tables, end=date(2005, 8, 31), when=datetime(2005, 8, 1))


@pytest.mark.parametrize("kind", ["rates", "security_map", "equity_prices", "accounts", "bond_terms", "corporate_actions"])
def test_missing_needed_kinds_raise(tables, kind):
    del tables[kind]
    with pytest.raises(DataUnavailable):
        build(tables)


# ---- result equality with the existing hand-built case


TRUE_L, R_B, LAM = 0.8, 0.5, 0.3
DATES = pd.date_range("2004-04-01", periods=90, freq="D")
MATURITY = pd.Timestamp("2009-01-15")
HAND_CONFIG = m.BacktestConfig(calibration_days=10)


def _thirty_360(day, end):
    d1, d2 = min(day.day, 30), end.day
    d2 = 30 if d2 == 31 and d1 == 30 else d2
    return (360 * (end.year - day.year) + 30 * (end.month - day.month) + d2 - d1) / 360


def hand_panel(gap):
    """e2c_bond's synthetic_bond_panel and inject_gap, as in test_known_gap_long_bond and _short_bond, with three changes the adapter's rules force.

    years_left is 30/360 on real dates, not 4.8 - i/360. zeros are the 2*ln(1.02) a 4% flat semiannual par curve bootstraps to, and r_5y is that par 4%.
    """
    z = 2 * np.log(1.02)
    p = m.synthetic_bond_panel(zero_rate=z)
    p = replace(p, years_left=np.array([_thirty_360(d, MATURITY) for d in DATES]), r_5y=np.full(90, 0.04))
    return m.inject_gap(m.panel_with_no_gap(p, TRUE_L, R_B, LAM), TRUE_L, 30, gap, 30, R_B, LAM)


def _stamp(dates):
    return dates + CLOSE


def hand_tables(p):
    """The panel as e2c_data tables, in a tmp folder only.

    The available_at stamps are made up by this converter: market rows at 21:00 on their own date, trades one hour after execution. Accounts and links are
    public well before the window. Each clean price becomes a customer buy 0.5 above and a customer sell 0.5 below, so the round trip is 0.01 as in the panel.
    Ten days of prints before the window pass the liquidity screen, because the panel is tradable from its first day.
    """
    d = pd.Series(DATES)
    n = len(d)
    links = pd.DataFrame({"instrument_id": ["B1", "E1"], "instrument_type": ["bond", "equity"], "issuer_id": ["I1", "I1"], "valid_from": pd.Timestamp("2000-01-03"),
                          "valid_to": pd.NaT, "available_at": pd.Timestamp("2000-01-03"), "ticker": [None, "T1"]})
    attrs = pd.DataFrame({"issuer_id": ["I1"], "date": [pd.Timestamp("2004-01-02")], "sector": ["Industrial"], "rating": ["BBB"], "has_listed_equity": [True], "available_at": [pd.Timestamp("2004-01-02")]})
    equity = pd.DataFrame({"date": d, "equity_id": "E1", "stock_close": p.S, "atm_iv_12m": p.sigma_s, "available_at": _stamp(d)})
    actions = pd.DataFrame(columns=["equity_id", "ex_date", "action_type", "cash_amount", "split_factor", "available_at"])
    accounts = pd.DataFrame({"issuer_id": ["I1"], "period_end": [pd.Timestamp("2003-12-31")], "available_at": [pd.Timestamp("2004-02-15")], "form": ["10-K"],
                             "total_liabilities": [28.0 * 1e8], "shares_out": [1e8]})
    tenors = (1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0)
    par = [pd.DataFrame({"date": d, "curve": "treasury_par", "tenor": t, "rate": 0.04, "available_at": _stamp(d)}) for t in tenors]
    cash = pd.DataFrame({"date": d, "curve": "cash", "tenor": 0.25, "rate": p.cash_rate, "available_at": _stamp(d)})
    financing = pd.concat([pd.DataFrame({"date": d, "instrument_id": "B1", "repo_rate": p.repo, "bond_fee": p.bond_fee, "available_at": _stamp(d)}),
                           pd.DataFrame({"date": d, "instrument_id": "E1", "stock_fee": p.stock_fee, "available_at": _stamp(d)}),
                           pd.DataFrame({"date": d, "instrument_id": "UST5Y", "repo_rate": p.hedge_repo, "available_at": _stamp(d)})], ignore_index=True)
    terms = pd.DataFrame({"bond_id": ["B1"], "coupon": [p.coupon], "freq": [p.freq], "maturity_date": [MATURITY], "issue_date": [pd.Timestamp("2000-01-15")], "available_at": [pd.Timestamp("2000-01-15")],
                          "seniority": ["senior unsecured"], "currency": ["USD"], "coupon_type": ["fixed"], "call_type": ["none"], "is_convertible": [False], "is_putable": [False],
                          "is_sinking": [False], "is_perpetual": [False], "is_pik": [False]})
    prices = pd.DataFrame({"date": d, "bond_id": "B1", "clean_price": p.clean * 100, "amount_out": 3e8, "available_at": _stamp(d)})
    before = pd.date_range(DATES[0] - pd.Timedelta(10, "D"), periods=10, freq="D")
    days = list(before) + list(DATES)
    cleans = [p.clean[0] * 100] * 10 + list(p.clean * 100)
    rows, seq = [], 0
    for day, clean in zip(days, cleans):
        when = day + pd.Timedelta(10, "h")
        for buy, price in ((True, clean + 0.5), (False, clean - 0.5)):
            seq += 1
            rows.append(dict(bond_id="B1", msg_seq=seq, execution_time=when, price=price, size=1e6, action="new", is_duplicate_side=False, is_customer_buy=buy,
                             report_time=when + pd.Timedelta(1, "h"), available_at=when + pd.Timedelta(1, "h")))
    return dict(security_map=links, issuer_attributes=attrs, equity_prices=equity, corporate_actions=actions, accounts=accounts, rates=pd.concat(par + [cash], ignore_index=True),
                financing=financing, bond_terms=terms, bond_prices=prices, bond_trades=pd.DataFrame(rows), universe=pd.DataFrame({"issuer_id": ["I1"], "start_date": [pd.Timestamp("2000-01-03")], "end_date": [pd.NaT], "available_at": [pd.Timestamp("2000-01-03")]}))


@pytest.fixture(scope="module", params=[0.02, -0.009], ids=["long", "short"])
def hand(request, tmp_path_factory):
    config = HAND_CONFIG if request.param > 0 else replace(HAND_CONFIG, use_cost_gate=False)
    p = hand_panel(request.param)
    root = tmp_path_factory.mktemp("hand")
    write_tables(hand_tables(p), root)
    view = PointInTimeView(TableSource(root), DATES[-1] + CLOSE)
    built = with_peer_gaps([build_bond_panel(view, "B1", DATES[0].date(), DATES[-1].date(), vol_source="implied", hedge_id="UST5Y")], config)[0]
    return dict(p=p, built=built, config=config, a=m.run_bond_backtest(p, config), b=m.run_bond_backtest(built.panel, config))


@pytest.mark.parametrize("field,tol", [("years_left", 1e-12), ("clean", 1e-12), ("S", 0), ("D", 1e-12), ("sigma_s", 0), ("dividend", 0), ("r_5y", 0), ("repo", 0), ("bond_fee", 0), ("stock_fee", 0),
                                       ("cash_rate", 0), ("hedge_repo", 0), ("calendar_day", 0), ("peer_gap", 0), ("round_trip", 1e-12)])
def test_hand_panel_fields(hand, field, tol):
    assert np.allclose(getattr(hand["p"], field), getattr(hand["built"].panel, field), rtol=0, atol=tol)


def test_hand_panel_other_fields(hand):
    p, b = hand["p"], hand["built"].panel
    assert (p.coupon, p.freq) == (b.coupon, b.freq) and b.tradable.all() and b.sibling_gap is None and b.cds_market is None and b.implied_vol is None and b.forced_event is None
    assert np.allclose(p.day_fraction[1:], b.day_fraction[1:], rtol=0, atol=1e-15), "row 0 is 0 here and 1/360 in the panel, and no step reads row 0"
    assert np.allclose(b.zeros, 2 * np.log(1.02), rtol=0, atol=1e-12), "the tenors differ: a 0.5 to 30 grid here, (0, 100) in the panel, both flat"


def test_hand_backtest_outputs_match(hand):
    a, b = hand["a"], hand["b"]
    assert a.status == b.status == "ok" and len(a.trades) == len(b.trades) == 1
    assert b.L_bar == pytest.approx(a.L_bar, abs=1e-6) and b.fit_rmse == pytest.approx(a.fit_rmse, abs=1e-6)
    assert np.allclose(a.z_market, b.z_market, rtol=0, atol=1e-9, equal_nan=True) and np.allclose(a.z_model, b.z_model, rtol=0, atol=1e-7, equal_nan=True)
    assert np.allclose(a.daily_returns, b.daily_returns, rtol=0, atol=1e-6, equal_nan=True)
    x, y = a.trades[0], b.trades[0]
    assert (x.side, x.signal_day, x.entry_day, x.exit_day, x.reason) == (y.side, y.signal_day, y.entry_day, y.exit_day, y.reason)
    assert y.face == pytest.approx(x.face, abs=1e-6) and y.shares == pytest.approx(x.shares, abs=1e-6) and y.hpr == pytest.approx(x.hpr, abs=1e-6)
    assert set(x.legs) == set(y.legs)
    for leg in x.legs:
        assert y.legs[leg] == pytest.approx(x.legs[leg], abs=1e-6), leg


R_5Y, DAY_FRACTION = 0.0396, 1 / 360  # worked_example.py


def cds_hand():
    firm = m.Firm(30.0, 28.0, 0.38, 0.62)
    flat = m.cds_par_spread(5.0, firm, R_B, R_5Y)
    path = np.array([flat] * 15 + [flat * 2.0] * 8 + [flat * 0.99] * 7)
    one = np.ones(30)
    return m.CdsPanel(c=path, S=one * 30.0, D=one * 28.0, sigma_s=one * 0.38, r=one * R_5Y, dividend=one * 0.0, day_fraction=one * DAY_FRACTION, calendar_day=np.arange(30.0))


def test_cds_panel_and_result_match_worked_example_case(tmp_path):
    """The worked example's CDS case, in a tmp folder. Invented stamps: every market row is public at 21:00 on its own date. Only row 0's day_fraction differs."""
    p = cds_hand()
    d = pd.Series(pd.date_range("2004-04-01", periods=30, freq="D"))
    t = dict(security_map=pd.DataFrame({"instrument_id": ["E1"], "instrument_type": ["equity"], "issuer_id": ["I1"], "valid_from": [pd.Timestamp("2000-01-03")], "valid_to": [pd.NaT], "available_at": [pd.Timestamp("2000-01-03")]}),
             equity_prices=pd.DataFrame({"date": d, "equity_id": "E1", "stock_close": p.S, "atm_iv_12m": p.sigma_s, "available_at": _stamp(d)}),
             corporate_actions=pd.DataFrame(columns=["equity_id", "ex_date", "action_type", "cash_amount", "split_factor", "available_at"]),
             accounts=pd.DataFrame({"issuer_id": ["I1"], "period_end": [pd.Timestamp("2003-12-31")], "available_at": [pd.Timestamp("2004-02-15")], "form": ["10-K"], "total_liabilities": [2.8e9], "shares_out": [1e8]}),
             rates=pd.DataFrame({"date": d, "curve": "treasury_par", "tenor": 5.0, "rate": R_5Y, "available_at": _stamp(d)}),
             cds_quotes=pd.DataFrame({"date": d, "issuer_id": "I1", "tenor": 5.0, "spread": p.c, "available_at": _stamp(d)}))
    write_tables(t, tmp_path)
    built = build_cds_panel(PointInTimeView(TableSource(tmp_path), d.iloc[-1] + CLOSE), "I1", d.iloc[0].date(), d.iloc[-1].date(), vol_source="implied")
    for field in ("c", "S", "D", "sigma_s", "r", "dividend", "calendar_day"):
        assert np.allclose(getattr(p, field), getattr(built.panel, field), rtol=0, atol=1e-15), field
    assert np.allclose(p.day_fraction[1:], built.panel.day_fraction[1:], rtol=0, atol=1e-15)
    config = m.BacktestConfig(calibration_days=10, overlapping=False, lag=0, peer_adjust=False)
    a, b = m.run_cds_backtest(p, config), m.run_cds_backtest(built.panel, config)
    assert len(a.trades) == len(b.trades) == 1 and b.L_bar == pytest.approx(a.L_bar, abs=1e-9)
    assert (a.trades[0].side, a.trades[0].exit_day, a.trades[0].reason) == (b.trades[0].side, b.trades[0].exit_day, b.trades[0].reason)
    assert b.trades[0].hpr == pytest.approx(a.trades[0].hpr, abs=1e-9)


def test_cds_panel_on_synthetic_tables(tables):
    built = build_cds_panel(view_of(tables), "I003", START, END, vol_source="implied")
    assert built.report["blank"]["c"] == 0 and built.report["left_out"]["no_cds"] == 0
    result = m.run_cds_backtest(built.panel, m.BacktestConfig(calibration_days=10, overlapping=True, lag=0, peer_adjust=False))
    assert result.status == "reject" and len(result.trades) > 0, "synthetic.py's CDS quotes are noise. run_cds_backtest flags the fit and still trades"
    assert at(built, "2004-06-30", "S") == tables["equity_prices"].query("equity_id == 'E003' and date == '2004-06-30'").stock_close.iloc[0]


def test_cds_panel_needs_quotes(tables):
    del tables["cds_quotes"]
    with pytest.raises(DataUnavailable):
        build_cds_panel(view_of(tables), "I003", START, END, vol_source="implied")


# ---- trade timing


def _extra_trade(tables, bond, when, reported, price, **kw):
    t = tables["bond_trades"]
    row = dict(bond_id=bond, msg_seq=int(t.msg_seq.max()) + 1, execution_time=pd.Timestamp(when), price=price, size=1e6, orig_msg_seq=np.nan, action="new",
               is_duplicate_side=False, is_customer_buy=True, report_time=pd.Timestamp(reported), available_at=pd.Timestamp(reported))
    row.update(kw)
    tables["bond_trades"] = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    return row["msg_seq"]


DAY = "2005-06-15"


def test_a_trade_reported_after_the_decision_time_does_not_reach_the_panel(tables):
    base = at(build(tables, end=date(2005, 6, 15), when=datetime(2005, 6, 15, 21)), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 15:00", "2005-06-16 09:00", 150.0)
    assert at(build(tables, end=date(2005, 6, 15), when=datetime(2005, 6, 15, 21)), DAY, "clean") == base


def test_a_trade_reported_after_its_days_close_never_prices_that_day_even_from_a_later_view(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 15:00", "2005-06-16 09:00", 110.0)
    assert at(build(tables), DAY, "clean") == base


def test_a_trade_reported_before_the_close_does_price_the_day(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 15:00", "2005-06-15 16:00", base * 100 + 3, size=5e7)
    assert at(build(tables), DAY, "clean") != base


def test_report_time_wins_over_an_earlier_available_at(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 15:00", "2005-06-16 09:00", base * 100 + 3, size=5e7, available_at=pd.Timestamp("2005-06-15 16:00"))
    assert at(build(tables), DAY, "clean") == base


@pytest.mark.parametrize("action", ["cancel", "correct"])
def test_a_later_cancel_or_correction_does_not_change_an_earlier_day(tables, action):
    base = build(tables)
    t = tables["bond_trades"]
    original = t[(t.bond_id == "B0031") & (t.execution_time.dt.normalize() == pd.Timestamp(DAY))].msg_seq.iloc[0]
    _extra_trade(tables, "B0031", "2005-06-15 10:00", "2005-06-20 09:00", 130.0, orig_msg_seq=original, action=action)
    assert at(build(tables), DAY, "clean") == at(base, DAY, "clean")
    assert at(build(tables), DAY, "round_trip") == at(base, DAY, "round_trip")


def test_a_cancel_public_the_same_day_does_change_it(tables):
    base = build(tables)
    t = tables["bond_trades"]
    original = t[(t.bond_id == "B0031") & (t.execution_time.dt.normalize() == pd.Timestamp(DAY)) & t.is_customer_buy].msg_seq.iloc[0]
    _extra_trade(tables, "B0031", "2005-06-15 10:00", "2005-06-15 12:00", 130.0, orig_msg_seq=original, action="cancel")
    assert at(build(tables), DAY, "clean") == pytest.approx(at(base, DAY, "clean") - 0.0025)


def test_e2c_bond_cleaning_is_applied(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 12:00", "2005-06-15 13:00", base * 100 + 0.25, is_duplicate_side=True, size=9e8)
    assert at(build(tables), DAY, "clean") == base, "a duplicate side leaves"
    _extra_trade(tables, "B0031", "2005-06-15 12:30", "2005-06-15 13:00", (base * 100 + 0.25) / 10, size=1e6)
    moved = at(build(tables), DAY, "clean")
    assert moved == pytest.approx(base, abs=1e-3), "a decimal shift is fixed before it can move the day by 30 points"


def test_small_prints_do_not_price_the_day(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 12:00", "2005-06-15 13:00", base * 100 + 3, size=99_000.0)
    assert at(build(tables), DAY, "clean") == base


def test_a_day_with_no_trades_has_no_price(tables):
    t = tables["bond_trades"]
    tables["bond_trades"] = t[t.execution_time.dt.normalize() != pd.Timestamp(DAY)]
    assert np.isnan(at(build(tables), DAY, "clean"))


# ---- accounts


def _filing(tables, issuer, period, available, liabilities, shares=1e8, form="10-Q"):
    row = dict(issuer_id=issuer, period_end=pd.Timestamp(period), available_at=pd.Timestamp(available), form=form, total_liabilities=liabilities, shares_out=shares)
    tables["accounts"] = pd.concat([tables["accounts"], pd.DataFrame([row])], ignore_index=True)


def test_a_filing_is_used_from_the_next_business_day(tables):
    _filing(tables, "I003", "2005-06-20", "2005-06-24 12:00", 5e9)  # a Friday
    b = build(tables)
    assert at(b, "2005-06-24", "D") != pytest.approx(50.0) and at(b, "2005-06-27", "D") == pytest.approx(50.0)


def test_a_restatement_only_reaches_days_after_it_is_usable(tables):
    _filing(tables, "I003", "2005-06-20", "2005-06-22", 5e9)
    _filing(tables, "I003", "2005-06-20", "2005-07-06", 7e9)
    b = build(tables)
    assert at(b, "2005-07-06", "D") == pytest.approx(50.0) and at(b, "2005-07-07", "D") == pytest.approx(70.0)


def test_a_restatement_not_yet_public_stays_out_of_an_earlier_view(tables):
    _filing(tables, "I003", "2005-06-20", "2005-06-22", 5e9)
    _filing(tables, "I003", "2005-06-20", "2005-07-06", 7e9)
    b = build(tables, end=date(2005, 7, 1), when=datetime(2005, 7, 1, 21))
    assert at(b, "2005-07-01", "D") == pytest.approx(50.0)


def test_a_late_amendment_of_an_older_period_does_not_displace_newer_accounts(tables):
    _filing(tables, "I003", "2005-06-20", "2005-06-22", 5e9)
    _filing(tables, "I003", "2004-03-31", "2005-07-06", 7e9)
    assert at(build(tables), "2005-07-07", "D") == pytest.approx(50.0)


def test_a_split_after_the_filing_keeps_debt_on_the_share_basis(tables):
    """I002 splits 2:1 on 2004-09-15. The filing's shares are before it, so debt per share halves on that day."""
    b = build(tables, "B0021", date(2004, 9, 1), date(2004, 9, 30))
    assert at(b, "2004-09-15", "D") == pytest.approx(at(b, "2004-09-14", "D") / 2)


def test_debt_with_no_shares_leaves_and_is_counted(tables):
    a = tables["accounts"]
    a.loc[a.issuer_id.eq("I003") & a.period_end.ge(pd.Timestamp("2005-03-31")), "shares_out"] = np.nan
    b = build(tables)
    assert b.report["left_out"]["no_debt"] > 0 and np.isfinite(b.panel.D).all()


def test_stock_dividend_is_counted_not_adjusted(tables):
    ca = tables["corporate_actions"]
    row = dict(equity_id="E003", ex_date=pd.Timestamp("2005-06-15"), action_type="spinoff", cash_amount=np.nan, split_factor=np.nan, available_at=pd.Timestamp("2005-06-01"))
    tables["corporate_actions"] = pd.concat([ca, pd.DataFrame([row])], ignore_index=True)
    assert build(tables).report["unadjusted_actions"] == 1


# ---- dated link


def test_a_bond_that_changes_issuer_takes_the_right_stock_and_debt_on_both_sides(tables):
    """I008 merges into I001 on 2004-03-19, and its bonds trade on under I001."""
    b = build(tables, "B0081", date(2004, 3, 1), date(2004, 4, 15))
    q = tables["equity_prices"]
    assert at(b, "2004-03-19", "S") == q.query("equity_id == 'E008' and date == '2004-03-19'").stock_close.iloc[0]
    assert at(b, "2004-03-22", "S") == q.query("equity_id == 'E001' and date == '2004-03-22'").stock_close.iloc[0]
    a = tables["accounts"].query("issuer_id == 'I001' and available_at < '2004-03-22'").sort_values("period_end").iloc[-1]
    assert at(b, "2004-03-22", "D") == pytest.approx(a.total_liabilities / a.shares_out)
    c = tables["financing"].query("instrument_id == 'E001' and date == '2004-03-22'").stock_fee.iloc[0]
    assert at(b, "2004-03-22", "stock_fee") == c


def test_two_issuers_at_once_is_an_error(tables):
    s = tables["security_map"]
    tables["security_map"] = pd.concat([s, s[s.instrument_id == "B0031"].assign(issuer_id="I004", valid_from=pd.Timestamp("2000-06-01"))], ignore_index=True)
    with pytest.raises(ValueError, match="two issuer_id"):
        build(tables)


def test_days_with_no_link_leave_and_are_counted(tables):
    s = tables["security_map"]
    s.loc[s.instrument_id.eq("B0031"), "valid_to"] = pd.Timestamp("2005-06-30")
    b = build(tables)
    assert b.dates.max() == pd.Timestamp("2005-06-30") and b.report["left_out"]["no_link"] > 0


# ---- rating and screens


def test_a_downgrade_does_not_reach_earlier_dates(tables):
    """I002 goes to BB with effect 2004-06-30. Public a week later here, so the week between stays BBB."""
    a = tables["issuer_attributes"]
    a.loc[a.issuer_id.eq("I002") & a.date.eq(pd.Timestamp("2004-06-30")), "available_at"] = pd.Timestamp("2004-07-07 12:00")
    b = build(tables, "B0021", date(2004, 6, 1), date(2004, 7, 30))
    rating = pd.Series(b.ratings, index=b.dates)
    assert rating["2004-06-29"] == "BBB" and rating["2004-07-06"] == "BBB" and rating["2004-07-07"] == "BB" and rating["2004-07-30"] == "BB"


def test_rating_moves_the_planning_round_trip_only_from_that_date(tables):
    t = tables["bond_trades"]
    tables["bond_trades"] = t[t.bond_id.eq("B0021") & t.is_customer_buy]
    a = tables["issuer_attributes"]
    tables["issuer_attributes"] = pd.concat([a, a[a.issuer_id.eq("I003")].iloc[[0]].assign(date=pd.Timestamp("2005-06-20"), rating="B", available_at=pd.Timestamp("2005-06-20"))], ignore_index=True)
    x = tables["bond_trades"]
    tables["bond_trades"] = pd.concat([x.assign(bond_id="B0031")], ignore_index=True)
    b = build(tables)
    assert b.report["round_trip"]["planning"] > 0
    assert at(b, "2005-06-17", "round_trip") == pytest.approx(0.005) and at(b, "2005-06-20", "round_trip") == pytest.approx(0.015)


@pytest.mark.parametrize("sector", ["Financial", "Financials", "Utilities", "Utility"])
def test_financials_and_utilities_fail_the_issuer_screen(tables, sector):
    a = tables["issuer_attributes"]
    a.loc[a.issuer_id.eq("I003"), "sector"] = sector
    b = build(tables)
    assert not b.panel.tradable.any() and b.report["screens_failed"]["issuer"] == b.report["rows"]


def test_no_listed_equity_fails_the_issuer_screen(tables):
    a = tables["issuer_attributes"]
    a.loc[a.issuer_id.eq("I003"), "has_listed_equity"] = False
    assert build(tables).report["screens_failed"]["issuer"] > 0


def test_a_missing_attributes_table_fails_the_screen_and_is_counted(tables):
    del tables["issuer_attributes"]
    b = build(tables)
    assert not b.panel.tradable.any() and pd.isna(b.ratings).all()


@pytest.mark.parametrize("column,value", [("is_convertible", True), ("is_pik", True), ("seniority", "subordinated"), ("currency", "EUR"), ("coupon_type", "floating"), ("is_sinking", np.nan)])
def test_bad_terms_fail_the_terms_screen(tables, column, value):
    t = tables["bond_terms"]
    t[column] = t[column].astype(object)
    t.loc[t.bond_id.eq("B0031"), column] = value
    b = build(tables)
    assert b.report["screens_failed"]["terms"] == b.report["rows"]


def test_senior_unsecured_vocabulary_is_normalised(tables):
    assert tables["bond_terms"].seniority.iloc[0] == "senior unsecured" and build(tables).report["screens_failed"]["terms"] == 0


def test_fixed_price_call_near_the_price_fails_the_screen(tables):
    t, p = tables["bond_terms"], tables["bond_prices"]
    t["call_type"] = t["call_type"].astype(object)
    t.loc[t.bond_id.eq("B0031"), "call_type"] = "fixed_price"
    p.loc[p.bond_id.eq("B0031"), "next_call_price"] = p.loc[p.bond_id.eq("B0031"), "clean_price"]
    assert build(tables).report["screens_failed"]["callable"] > 0
    p.loc[p.bond_id.eq("B0031"), "next_call_price"] = 300.0
    assert build(tables).report["screens_failed"]["callable"] == build(tables).report["rows"] - build(tables).report["priced_days"]


def test_small_or_young_bond_fails_the_screen(tables):
    p, t = tables["bond_prices"], tables["bond_terms"]
    p.loc[p.bond_id.eq("B0031"), "amount_out"] = 2e8
    assert build(tables).report["screens_failed"]["age_and_size"] == build(tables).report["rows"]
    p.loc[p.bond_id.eq("B0031"), "amount_out"] = 3e8
    t.loc[t.bond_id.eq("B0031"), "issue_date"] = pd.Timestamp("2005-05-01")
    assert 0 < build(tables).report["screens_failed"]["age_and_size"] < build(tables).report["rows"]


def test_maturity_screen_uses_the_issuers_other_bonds(tables):
    t = tables["bond_terms"]
    t.loc[t.bond_id.eq("B0031"), "maturity_date"] = pd.Timestamp("2014-06-15")  # 9 years
    t.loc[t.bond_id.eq("B0032"), "maturity_date"] = pd.Timestamp("2010-06-15")  # 5 years, a core bond
    assert build(tables).report["screens_failed"]["maturity"] == build(tables).report["rows"]
    t.loc[t.bond_id.eq("B0032"), "maturity_date"] = pd.Timestamp("2014-06-15")
    assert build(tables).report["screens_failed"]["maturity"] == 0


def test_liquidity_counts_large_prints_over_five_business_days(tables):
    b = build(tables, min_trades_5d=10)
    assert b.report["screens_failed"]["liquidity"] < 10
    assert build(tables, min_trades_5d=11).report["screens_failed"]["liquidity"] == b.report["rows"]


# ---- units and blanks


def test_known_values_come_through_converted(tables):
    p, q, f, r, t = tables["bond_prices"], tables["equity_prices"], tables["financing"], tables["rates"], tables["bond_terms"]
    day = pd.Timestamp(DAY)
    x = tables["bond_trades"]
    x.loc[x.bond_id.eq("B0031") & x.execution_time.dt.normalize().eq(day) & x.is_customer_buy, "price"] = 100.75
    x.loc[x.bond_id.eq("B0031") & x.execution_time.dt.normalize().eq(day) & ~x.is_customer_buy, "price"] = 100.25
    q.loc[q.equity_id.eq("E003") & q.date.eq(day), ["stock_close", "atm_iv_12m"]] = [40.0, 0.37]
    f.loc[f.instrument_id.eq("B0031") & f.date.eq(day), ["repo_rate", "bond_fee"]] = [0.021, 0.006]
    f.loc[f.instrument_id.eq("E003") & f.date.eq(day), "stock_fee"] = 0.007
    f.loc[f.instrument_id.eq("UST5Y") & f.date.eq(day), "repo_rate"] = 0.022
    r.loc[r.curve.eq("cash") & r.date.eq(day), "rate"] = 0.031
    r.loc[r.curve.eq("treasury_par") & r.tenor.eq(5.0) & r.date.eq(day), "rate"] = 0.043
    t.loc[t.bond_id.eq("B0031"), ["coupon", "maturity_date"]] = [0.055, pd.Timestamp("2010-06-15")]
    a = tables["accounts"].query("issuer_id == 'I003' and available_at < '2005-06-14'").sort_values("period_end").iloc[-1]
    b = build(tables)
    assert at(b, DAY, "clean") == pytest.approx(1.005) and at(b, DAY, "S") == 40.0 and at(b, DAY, "sigma_s") == 0.37
    assert at(b, DAY, "repo") == 0.021 and at(b, DAY, "bond_fee") == 0.006 and at(b, DAY, "stock_fee") == 0.007 and at(b, DAY, "hedge_repo") == 0.022
    assert at(b, DAY, "cash_rate") == 0.031 and at(b, DAY, "r_5y") == 0.043 and at(b, DAY, "D") == pytest.approx(a.total_liabilities / a.shares_out)
    assert b.panel.coupon == 0.055 and b.panel.freq == 2 and at(b, DAY, "years_left") == pytest.approx(5.0)
    assert at(b, DAY, "round_trip") == pytest.approx(0.005, abs=0.005)
    assert b.panel.tradable.dtype == bool


def test_day_fraction_is_act_360_since_the_last_row(tables):
    b = build(tables, end=date(2005, 3, 31))
    assert at(b, "2005-03-07", "day_fraction") == pytest.approx(3 / 360) and b.panel.day_fraction[0] == 0.0
    assert b.panel.calendar_day[0] == 0.0 and at(b, "2005-03-07", "calendar_day") == 6.0


def test_curve_is_e2c_bonds_bootstrap(tables):
    r = tables["rates"].query("curve == 'treasury_par' and date == @DAY").sort_values("tenor")
    want = m.zero_curve_from_par_yields(r.tenor.to_numpy(), r.rate.to_numpy())
    b = build(tables)
    assert b.panel.zero_tenors == want.tenors and np.allclose(b.panel.zeros[b.dates.get_loc(pd.Timestamp(DAY))], want.zeros)


def test_a_day_with_a_blank_curve_leaves_and_is_counted(tables):
    r = tables["rates"]
    r.loc[r.curve.eq("treasury_par") & r.tenor.eq(7.0) & r.date.eq(pd.Timestamp(DAY)), "rate"] = np.nan
    b = build(tables)
    assert pd.Timestamp(DAY) not in b.dates and b.report["left_out"]["no_curve"] == 1


def test_dividend_on_the_ex_date_only(tables):
    ca = tables["corporate_actions"].query("equity_id == 'E003' and action_type == 'cash_dividend' and ex_date >= '2005-03-01'").iloc[0]
    b = build(tables)
    assert at(b, ca.ex_date, "dividend") == pytest.approx(0.1) and b.panel.dividend.sum() > 0.09 and at(b, ca.ex_date - pd.Timedelta(1, "D") if (ca.ex_date.dayofweek > 0) else ca.ex_date - pd.Timedelta(3, "D"), "dividend") == 0.0


def test_a_cash_dividend_with_no_amount_stays_blank_and_is_counted(tables):
    ca = tables["corporate_actions"]
    row = ca[ca.equity_id.eq("E003") & ca.ex_date.ge(pd.Timestamp("2005-03-01")) & ca.action_type.eq("cash_dividend")].index[0]
    ca.loc[row, "cash_amount"] = np.nan
    assert build(tables).report["blank"]["dividend"] == 1


@pytest.mark.parametrize("kind,field", [("financing", "repo"), ("financing", "stock_fee")])
def test_no_financing_stays_blank_and_is_counted(tables, kind, field):
    del tables[kind]
    b = build(tables)
    assert np.isnan(getattr(b.panel, field)).all() and b.report["blank"][field] == b.report["rows"]


def test_no_hedge_id_leaves_hedge_repo_blank(tables):
    b = build(tables, hedge_id=None)
    assert b.report["blank"]["hedge_repo"] == b.report["rows"]


def test_implied_vol_is_a_check_only_on_a_historical_run(tables):
    q = tables["equity_prices"]
    assert build(tables, vol_source="implied").panel.implied_vol is None
    h = build(tables, start=date(2005, 12, 1), end=END, vol_source="historical")
    assert h.panel.implied_vol is not None and np.allclose(h.panel.implied_vol, q[(q.equity_id == "E003") & q.date.isin(h.dates)].atm_iv_12m)


def test_historical_vol_uses_e2c_bonds_estimator_on_log_total_returns(tables):
    b = build(tables, start=date(2005, 6, 1), end=date(2005, 6, 30), vol_source="historical", vol_min_obs=250)
    q = tables["equity_prices"].query("equity_id == 'E003' and date <= @DAY").sort_values("date")
    want = m.historical_equity_vol(np.log1p(q.total_return.to_numpy()), window=1000, min_obs=250)
    assert at(b, DAY, "sigma_s") == pytest.approx(want)


def test_blank_total_return_leaves_and_is_counted(tables):
    q = tables["equity_prices"]
    q["total_return"] = np.nan
    with pytest.raises(DataUnavailable):
        build(tables, vol_source="historical")


def test_unknown_vol_source_is_an_error(tables):
    with pytest.raises(ValueError, match="vol source"):
        build(tables, vol_source="made_up")


def test_cds_and_events_are_optional(tables):
    b = build(tables)
    assert b.panel.cds_market is not None and at(b, DAY, "cds_market") == tables["cds_quotes"].query("issuer_id == 'I003' and tenor == 5.0 and date == @DAY").spread.iloc[0]
    del tables["cds_quotes"]
    del tables["events"]
    c = build(tables)
    assert c.panel.cds_market is None and c.panel.forced_event is None


def test_forced_event_lands_on_the_issuers_row(tables):
    b = build(tables, "B0071", date(2003, 10, 1), date(2003, 11, 14))
    assert b.panel.forced_event[-1] == "default" and b.panel.forced_event[0] is None
    tables["events"] = pd.concat([tables["events"], pd.DataFrame([dict(issuer_id="I003", event_date=pd.Timestamp("2005-06-18"), event_type="call", instrument_id="B0031", available_at=pd.Timestamp("2005-06-18"))])], ignore_index=True)
    c = build(tables)
    assert c.panel.forced_event[c.dates.get_loc(pd.Timestamp("2005-06-20"))] == "called", "a Saturday lands on Monday, and call maps to e2c_bond's word"
    assert build(tables, "B0032").panel.forced_event is None, "another bond of the same issuer is not called"


# ---- peers


def test_peer_gap_is_blank_until_with_peer_gaps_runs(tables):
    b = build(tables)
    assert np.isnan(b.panel.peer_gap).all() and b.report["blank"]["peer_gap"] == b.report["rows"]


def test_no_peers_gives_zero(tables):
    b = with_peer_gaps([build(tables)], m.BacktestConfig())[0]
    assert (b.panel.peer_gap == 0.0).all() and b.report["blank"]["peer_gap"] == 0


def test_peer_gap_is_the_median_of_same_rating_same_bucket_after_each_peers_fit(tables):
    config = m.BacktestConfig()
    names = ["B0031", "B0041"]
    t = tables["issuer_attributes"]
    t.loc[t.issuer_id.isin(["I003", "I004"]), "rating"] = "BBB"
    tt = tables["bond_terms"]
    tt.loc[tt.bond_id.isin(names), "maturity_date"] = pd.Timestamp("2010-06-15")
    for b in names:
        model_priced(tables, b, 0.01, date(2005, 3, 1), date(2005, 8, 31))
    built = [build(tables, b) for b in names]
    filled = with_peer_gaps(built, config)
    other = m.run_bond_backtest(built[1].panel, replace(config, peer_adjust=False))
    fit = [i for i in range(len(built[1].dates)) if np.isfinite(other.z_market[i]) and built[1].panel.tradable[i]][:config.calibration_days]
    day = fit[-1] + 1
    while not np.isfinite(other.z_market[day]):
        day += 1
    when = built[1].dates[day]
    want = m.log_gap(other.z_market[day], other.z_model[day])
    i = built[0].dates.get_loc(when)
    assert filled[0].panel.peer_gap[i] == pytest.approx(want)
    assert (filled[0].panel.peer_gap[built[0].dates <= built[1].dates[fit[-1]]] == 0.0).all(), "a peer counts only after its own fit ended"


def _two_priced_bonds(tables, second_maturity="2010-06-15"):
    names = ["B0031", "B0041"]
    a = tables["issuer_attributes"]
    a.loc[a.issuer_id.isin(["I003", "I004"]), "rating"] = "BBB"
    terms = tables["bond_terms"]
    terms.loc[terms.bond_id.eq("B0031"), "maturity_date"] = pd.Timestamp("2010-06-15")
    terms.loc[terms.bond_id.eq("B0041"), "maturity_date"] = pd.Timestamp(second_maturity)
    for b in names:
        model_priced(tables, b, 0.01, date(2005, 3, 1), date(2005, 8, 31))
    return names


def test_other_rating_is_not_a_peer(tables):
    names = _two_priced_bonds(tables)
    assert (with_peer_gaps([build(tables, b) for b in names], m.BacktestConfig())[0].panel.peer_gap != 0.0).any()
    a = tables["issuer_attributes"]
    a.loc[a.issuer_id.eq("I004"), "rating"] = "BB"
    assert (with_peer_gaps([build(tables, b) for b in names], m.BacktestConfig())[0].panel.peer_gap == 0.0).all()


def test_other_maturity_bucket_is_not_a_peer(tables):
    names = _two_priced_bonds(tables, "2013-06-15")  # 5 years and 8 years, both priced, so the second has a real gap
    built = [build(tables, b) for b in names]
    assert m.run_bond_backtest(built[1].panel, replace(m.BacktestConfig(), peer_adjust=False)).status != "reject"
    assert (with_peer_gaps(built, m.BacktestConfig())[0].panel.peer_gap == 0.0).all()


# ---- factors


def test_factors_come_through_for_factor_regression(tables):
    f = build_factors(view_of(tables), date(2003, 1, 1), date(2005, 12, 30))
    assert f.returns.shape == (36, 4) and len(f.names) == 4 and f.months[0] == pd.Timestamp("2003-01-01")
    want = tables["factor_returns"].query("factor == @f.names[0]").sort_values("date").excess_return.to_numpy()
    assert np.allclose(f.returns[:, 0], want)
    monthly = 0.5 * f.returns[:, 0] + 0.001
    fit = m.factor_regression(monthly, f.returns)
    assert fit["betas"][0] == pytest.approx(0.5) and fit["intercept"] == pytest.approx(0.001)


def test_factors_keep_a_blank_month_blank(tables):
    t = tables["factor_returns"]
    t.loc[t.index[0], "excess_return"] = np.nan
    f = build_factors(view_of(tables), date(2003, 1, 1), date(2005, 12, 30))
    assert np.isnan(f.returns).sum() == 1


def test_missing_factors_raise(tables):
    del tables["factor_returns"]
    with pytest.raises(DataUnavailable):
        build_factors(view_of(tables), date(2003, 1, 1), date(2005, 12, 30))


def test_factors_do_not_read_past_decision_time(tables):
    f = build_factors(view_of(tables, datetime(2004, 6, 30, 21)), date(2003, 1, 1), date(2004, 6, 30))
    assert f.months.max() == pd.Timestamp("2004-06-01")


@pytest.mark.parametrize("a,b,want", [("2004-02-27", "2010-06-15", 2268 / 360), ("2004-01-31", "2004-02-15", 15 / 360)])
def test_years_30_360(a, b, want):
    assert years_30_360(pd.Series([pd.Timestamp(a)]), pd.Series([pd.Timestamp(b)])).iloc[0] == pytest.approx(want)


# ---- closing the mutation survivors


def test_a_spike_that_reverts_the_same_day_is_flagged_out(tables):
    base = at(build(tables), DAY, "clean")
    _extra_trade(tables, "B0031", "2005-06-15 09:30", "2005-06-15 09:45", base * 100 + 45, size=5e7)
    assert at(build(tables), DAY, "clean") == pytest.approx(base)


def test_round_trip_pools_twenty_days(tables):
    base = at(build(tables), DAY, "round_trip")
    t = tables["bond_trades"]
    t.loc[t.bond_id.eq("B0031") & t.execution_time.dt.normalize().eq(pd.Timestamp("2005-06-10")) & t.is_customer_buy, "price"] += 3.0
    assert at(build(tables), DAY, "round_trip") > base
    assert at(build(tables), "2005-07-15", "round_trip") == pytest.approx(0.005)


def test_small_prints_do_not_count_for_liquidity(tables):
    t = tables["bond_trades"]
    t.loc[t.bond_id.eq("B0031"), "size"] = 50_000.0
    b = build(tables)
    assert b.report["screens_failed"]["liquidity"] == b.report["rows"]


def test_a_negative_measured_round_trip_falls_back_to_planning(tables):
    t = tables["bond_trades"]
    t.loc[t.bond_id.eq("B0031"), "is_customer_buy"] = ~t.loc[t.bond_id.eq("B0031"), "is_customer_buy"].astype(bool)
    b = build(tables)
    assert b.report["round_trip"]["measured"] == 0 and b.report["round_trip"]["planning"] > 0 and at(b, DAY, "round_trip") == pytest.approx(0.005)


def test_a_long_gap_in_trades_carries_the_last_round_trip_and_counts_it(tables):
    t = tables["bond_trades"]
    day = t.execution_time.dt.normalize()
    tables["bond_trades"] = t[~(t.bond_id.eq("B0031") & (day >= pd.Timestamp("2005-06-01")) & (day <= pd.Timestamp("2005-07-15")))]
    b = build(tables)
    assert b.report["round_trip"]["carried"] > 0 and at(b, "2005-07-05", "round_trip") == pytest.approx(0.005)
