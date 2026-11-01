"""Tests of fk_f10.py and run_f10.py: F10 of finkelstein_replication_plan.pdf and what WP6a's done-when row needs.

Every panel is made up here, so these tests check the logic and say nothing about any market.
The real F10 runs only when E2C_F10_ROOT names a folder of real tables.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import fk_f10 as f
import run_f10 as r
from e2c_data.tables import write_tables
from fk_value import e2c

CLOSE = pd.Timedelta(17, "h")
STOCK_NOISE = .005
FAIR_SPREAD = -.0048   # with the base .045, the yield the model gives, so gaps straddle zero
SPREAD_SD = .001
START, END = pd.Timestamp("2007-01-01"), pd.Timestamp("2011-12-31")
PLANTED = f.F10Target(window=("2007-01", "2011-12"))
FAST = f.F10Settings(min_months=48, min_firms=25, liquidity_screen=False)


# ---------------------------------------------------------------- A made-up market in schema units

def price_per_100(coupon, years, y):
    t, cf = e2c.cash_flows(e2c.Bond(coupon, years, 2))
    return 100 * float(np.sum(cf * (1 + y / 2) ** (-2 * t)))


def make_tables(spread_path, months, n=30, seed=1, dead=True, stock_signal=0.0, dead_day="2011-06-30"):
    """One bond per firm, stock and leverage alike across firms, so the bond's spread drives the sort.

    stock_signal moves a stock down in the month after its bond is wide, which plants the stock premium.
    """
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2004-01-01", months[-1].end_time.normalize())
    issuers = [f"I{i:02d}" for i in range(n)]
    stock_rows, bond_rows, account_rows = [], [], []
    last_day = {i: days[-1] for i in issuers}
    if dead:
        last_day[issuers[-1]] = pd.Timestamp(dead_day)
    for i, firm in enumerate(issuers):
        noise = rng.normal(0, STOCK_NOISE, len(days))
        live = days[days <= last_day[firm]]
        level = np.zeros(len(days))
        for k, m in enumerate(months[1:]):
            level[days >= m.start_time] -= stock_signal * (spread_path[k, i] - spread_path[:, i].mean()) / SPREAD_SD
        stock_rows.append(pd.DataFrame(dict(date=live, equity_id=f"E{i:02d}", stock_close=50 * np.exp(noise[:len(live)] + level[:len(live)]),
                                            shares_out=1e8, available_at=live + CLOSE)))
        ends = pd.date_range("2003-03-31", "2011-12-31", freq="QE")
        ends = ends[ends <= last_day[firm]]
        account_rows.append(pd.DataFrame(dict(issuer_id=firm, period_end=ends, total_liabilities=6e9, dividends=5e7,
                                              interest=3e8, repurchases=0.0, available_at=ends + pd.Timedelta(45, "D") + CLOSE)))
        maturity = pd.Timestamp("2016-01-15")
        for k, m in enumerate(months):
            day = days[(days >= m.start_time) & (days <= m.end_time)][-1]
            if day > last_day[firm]:
                break
            years = ((maturity.year - day.year) * 360 + (maturity.month - day.month) * 30 + (maturity.day - day.day)) / 360
            full = price_per_100(.06, years, .045 + spread_path[k, i])
            bond_rows.append(dict(date=day, bond_id=f"B{i:02d}", clean_price=full, full_price=full,
                                  coupon_paid=3.0 if day.month in (1, 7) else 0.0, amount_out=(9e8 if i % 2 else 3e8),
                                  next_call_price=np.nan, available_at=day + CLOSE))
    bonds = pd.DataFrame(bond_rows)
    terms = pd.DataFrame([dict(bond_id=f"B{i:02d}", coupon=.06, freq=2, maturity_date=maturity, issue_date=pd.Timestamp("2003-01-15"),
                               seniority="senior_unsecured", currency="USD", coupon_type="fixed", call_type="none", is_convertible=False,
                               is_putable=False, is_sinking=False, is_perpetual=False, is_pik=False, is_floating=False,
                               available_at=pd.Timestamp("2003-01-15")) for i in range(n)])
    links = pd.concat([pd.DataFrame(dict(instrument_id=[f"E{i:02d}" for i in range(n)], instrument_type="equity", issuer_id=issuers)),
                       pd.DataFrame(dict(instrument_id=[f"B{i:02d}" for i in range(n)], instrument_type="bond", issuer_id=issuers))])
    links = links.assign(valid_from=pd.Timestamp("2003-01-01"), valid_to=pd.NaT, available_at=pd.Timestamp("2003-01-01"))
    universe = pd.DataFrame(dict(issuer_id=issuers, start_date=pd.Timestamp("2003-01-01"), end_date=pd.NaT, available_at=pd.Timestamp("2003-01-01")))
    events = pd.DataFrame(columns=["issuer_id", "event_date", "event_type", "realised_recovery", "delisting_return", "available_at"])
    if dead:
        day = last_day[issuers[-1]]
        ended = universe[universe.issuer_id == issuers[-1]].assign(end_date=day, end_reason="default", available_at=day + pd.Timedelta(1, "D"))
        universe = pd.concat([universe, ended], ignore_index=True)
        events = pd.DataFrame([dict(issuer_id=issuers[-1], event_date=day + pd.Timedelta(31, "D"), event_type="default", realised_recovery=35.0,
                                    delisting_return=-.9, available_at=day + pd.Timedelta(32, "D"))])
    rates = pd.concat([pd.DataFrame(dict(date=days, curve="treasury_par", tenor=t, rate=.04, available_at=days + CLOSE)) for t in (.25, 1., 2., 5., 10., 30.)])
    attrs = pd.DataFrame(dict(issuer_id=issuers, date=pd.Timestamp("2003-01-02"), sector="industrial", rating="BB", has_listed_equity=True,
                              available_at=pd.Timestamp("2003-01-02")))
    return dict(security_map=links, universe=universe, equity_prices=pd.concat(stock_rows, ignore_index=True),
                accounts=pd.concat(account_rows, ignore_index=True), rates=rates, bond_terms=terms, bond_prices=bonds,
                issuer_attributes=attrs, events=events)


def study_months(n=60):
    return pd.period_range("2007-01", periods=n, freq="M")


def signal_paths(months, n=30, seed=7):
    """Each month's spread is drawn afresh, so a wide bond tends to come back. That plants the premium."""
    return FAIR_SPREAD + SPREAD_SD * np.random.default_rng(seed).standard_normal((len(months), n))


def noise_paths(months, n=30, seed=11):
    """Spreads walk, so today's level says nothing about next month's move."""
    return FAIR_SPREAD + np.cumsum(.0005 * np.random.default_rng(seed).standard_normal((len(months), n)), axis=0)


def run_folder(tmp_path, tables, start=START, end=END, **kwargs):
    root = tmp_path / "tables"
    root.mkdir(parents=True, exist_ok=True)
    write_tables(tables, root)
    settings = kwargs.pop("settings", FAST)
    return r.run(r.TableSource(root), start, end, end + pd.Timedelta(1, "D"), tmp_path / "out", settings=settings, target=PLANTED, **kwargs)


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    months = study_months()
    paths = signal_paths(months)
    path = tmp_path_factory.mktemp("planted")
    return run_folder(path, make_tables(paths, months, stock_signal=.01)), paths, months, path / "out"


# ---------------------------------------------------------------- t-statistic

def test_newey_west_t_against_a_hand_calculation():
    x = np.array([.01, .03, -.02, .04])
    mean = x.mean()
    e = x - mean
    n = len(x)
    gamma0 = (e @ e) / n
    gamma1 = (e[1:] @ e[:-1]) / n
    variance = (gamma0 + 2 * (1 - 1 / 2) * gamma1) / n
    got = f.newey_west(x, lags=1)
    assert got.mean == pytest.approx(mean)
    assert got.se == pytest.approx(np.sqrt(variance))
    assert got.t == pytest.approx(mean / np.sqrt(variance))


def test_newey_west_with_no_lags_is_the_plain_t_with_n_divisor():
    x = np.array([.01, .02, .03, .06])
    assert f.newey_west(x, lags=0).t == pytest.approx(x.mean() / np.sqrt(x.var() / 4))


def test_newey_west_skips_nan_and_refuses_too_few():
    assert f.newey_west(np.array([.01, np.nan, .03]), lags=0).n == 2
    assert np.isnan(f.newey_west(np.array([.01]), lags=0).t)


# ---------------------------------------------------------------- Screens

def screen_rows(**over):
    base = dict(date=pd.Timestamp("2010-01-29"), bond_id="B", firm_id="F", maturity_years=5.0, amount_out=500.0, clean_price=.95,
                next_call_price=np.nan, years_since_issue=2.0, seniority="senior_unsecured", currency="USD", coupon_type="fixed",
                call_type="none", is_convertible=False, is_putable=False, is_sinking=False, is_perpetual=False, is_pik=False,
                sector="industrial", has_listed_equity=True, trades_5d=20)
    return pd.DataFrame([{**base, **over}])


@pytest.mark.parametrize("over, screen", [
    (dict(is_convertible=True), "terms"), (dict(is_putable=True), "terms"), (dict(is_sinking=True), "terms"), (dict(is_perpetual=True), "terms"),
    (dict(is_pik=True), "terms"), (dict(seniority="subordinated"), "terms"), (dict(currency="EUR"), "terms"), (dict(coupon_type="floating"), "terms"),
    (dict(is_convertible=np.nan), "terms"),
    (dict(sector="Financial"), "issuer"), (dict(has_listed_equity=False), "issuer"),
    (dict(call_type="fixed_price", clean_price=.99, next_call_price=1.01), "callable"),
    (dict(maturity_years=1.5), "maturity"), (dict(maturity_years=11.0), "maturity"),
    (dict(years_since_issue=.1), "age_size"), (dict(amount_out=100.0), "age_size"),
    (dict(trades_5d=3), "liquidity"),
])
def test_each_screen_removes_the_right_bond(over, screen):
    keep, funnel = f.screen_bonds(screen_rows(**over))
    assert not keep.iloc[0]
    assert funnel.set_index("screen").removed[screen] == 1
    assert funnel.removed.sum() == 1


def test_a_bond_failing_two_screens_counts_once_at_the_first():
    funnel = f.screen_bonds(screen_rows(is_convertible=True, amount_out=100.0))[1].set_index("screen")
    assert funnel.removed["terms"] == 1 and funnel.removed["age_size"] == 0 and funnel.tested["age_size"] == 0


def test_a_blank_in_any_terms_field_fails():
    for field in ("seniority", "currency", "coupon_type", "call_type", "is_putable"):
        assert not f.screen_bonds(screen_rows(**{field: np.nan}))[0].iloc[0], field


def test_a_clean_bond_passes_every_screen():
    keep, funnel = f.screen_bonds(screen_rows())
    assert keep.iloc[0] and funnel.removed.sum() == 0 and not funnel.not_applied.any()


def test_a_callable_well_under_its_call_price_stays():
    assert f.screen_bonds(screen_rows(call_type="fixed_price", clean_price=.90, next_call_price=1.01))[0].iloc[0]


def test_maturity_outside_core_stays_only_if_the_issuer_has_no_core_bond():
    rows = pd.concat([screen_rows(bond_id="core", maturity_years=5.0), screen_rows(bond_id="long", maturity_years=9.0)], ignore_index=True)
    assert f.screen_bonds(rows)[0].tolist() == [True, False]
    assert f.screen_bonds(screen_rows(maturity_years=9.0))[0].iloc[0]


def test_an_absent_column_is_reported_as_not_applied_and_does_not_remove():
    rows = screen_rows().drop(columns=["is_convertible", "trades_5d", "sector"])
    keep, funnel = f.screen_bonds(rows)
    assert keep.iloc[0]
    not_applied = funnel.set_index("screen").not_applied
    assert "is_convertible" in not_applied["terms"] and "trades_5d" in not_applied["liquidity"] and "sector" in not_applied["issuer"]


# ---------------------------------------------------------------- Financing and fees

def weights_table():
    return pd.DataFrame(dict(month=pd.Period("2010-02"), asset_id=["L1", "L2", "S1"], side=["long", "long", "short"], weight=[.5, .5, 1.0]))


def fin_table(**over):
    t = pd.DataFrame(dict(month=pd.Period("2010-01"), asset_id=["L1", "L2", "S1"], repo=[.03, .03, .03], fee=[0.0, 0.0, .06]))
    return t.assign(**over)


def test_financing_against_a_hand_calculation():
    # Long pays repo. Short earns repo less fee. Monthly: .03/12 - (.03 - .06)/12 = .06/12.
    got = f.financing_drag(weights_table(), fin_table())
    assert got.drag[pd.Period("2010-02")] == pytest.approx(.06 / 12)


def test_financing_is_nan_when_too_little_weight_has_a_rate():
    got = f.financing_drag(weights_table(), fin_table(repo=[.03, np.nan, .03]), min_coverage=.9)
    assert np.isnan(got.drag[pd.Period("2010-02")])


def test_financing_scales_up_covered_weight_at_or_above_the_floor():
    t = pd.DataFrame(dict(month=pd.Period("2010-02"), asset_id=["A", "B", "S"], side=["long", "long", "short"], weight=[.95, .05, 1.0]))
    fin = pd.DataFrame(dict(month=pd.Period("2010-01"), asset_id=["A", "B", "S"], repo=[.03, np.nan, .03], fee=[0.0, 0.0, .0]))
    assert f.financing_drag(t, fin).drag.iloc[0] == pytest.approx(.03 / 12 - .03 / 12)


def test_financing_uses_the_rate_known_before_the_return_month():
    fin = pd.concat([fin_table(), fin_table(fee=[0.0, 0.0, 9.0]).assign(month=pd.Period("2010-02"))])
    assert f.financing_drag(weights_table(), fin).drag.iloc[0] == pytest.approx(.06 / 12)


# ---------------------------------------------------------------- Treasury overlay

def test_overlay_return_against_a_hand_calculation():
    assert f.overlay_return(net_duration=2.0, hedge_duration=4.0, hedge_return=.01, repo=.024) == pytest.approx(-.5 * (.01 - .002))


def flat(y):
    return e2c.zero_curve_from_par_yields(np.array([1., 5., 10.]), np.array([y, y, y]))


def test_hedge_month_on_an_unchanged_curve_earns_about_its_yield():
    ret, duration = f.hedge_month(flat(.04), flat(.04), 5.0)
    assert ret == pytest.approx(.04 / 12, abs=3e-4)
    assert 4.0 < duration < 5.0


def test_hedge_month_loses_about_duration_times_the_yield_rise():
    ret, duration = f.hedge_month(flat(.04), flat(.05), 5.0)
    # A 1-point rise: convexity gives back about 0.1 point, and a par-yield rise is a bit under a zero-yield rise.
    assert ret - .04 / 12 == pytest.approx(-duration * .01, abs=.004)


def test_overlay_series_flattens_a_book_with_only_rate_risk():
    weights = weights_table()
    durations = pd.DataFrame(dict(month=pd.Period("2010-01"), asset_id=["L1", "L2", "S1"], duration=[6.0, 6.0, 2.0]))
    hedges = pd.DataFrame(dict(month=[pd.Period("2010-02")], hedge_return=[-.02], hedge_duration=[4.0], repo=[0.0]))
    got = f.overlay_series(weights, durations, hedges)
    assert got.overlay[pd.Period("2010-02")] == pytest.approx(-(6.0 - 2.0) / 4.0 * -.02)


# ---------------------------------------------------------------- The book's weights agree with fk_des

def test_book_weights_times_returns_give_t0_gross():
    import fk_des as fd
    holdings = pd.DataFrame(dict(month=pd.Period("2010-01"), asset_id=["A", "B", "C", "D"], group=[5, 5, 1, 1]))
    returns = pd.DataFrame(dict(month=pd.Period("2010-02"), asset_id=["A", "B", "C", "D"], ret=[.01, .03, .02, -.01],
                                ret_first=[.01, .03, .02, -.01], lag_value=[1.0, 3.0, 2.0, 2.0]))
    w = f.book_weights(holdings, returns, 5, 1, 1, "value")
    signed = w.weight * w.side.map({"long": 1, "short": -1})
    book = float((signed * w.asset_id.map(returns.set_index("asset_id").ret)).sum())
    assert book == pytest.approx(fd.t0_returns(holdings, returns, 5, 1, 1, "value", 0.0).gross.iloc[0])


# ---------------------------------------------------------------- Measured costs, splits

def test_measured_bond_cost_is_customer_buy_less_sell_over_mid():
    trades = pd.DataFrame(dict(bond_id="B", execution_time=pd.Timestamp("2010-01-05 10:00"), price=[100.5, 99.5], size=[1e6, 1e6], is_customer_buy=[True, False]))
    assert f.bond_day_costs(trades).cost.iloc[0] == pytest.approx(.01)


def test_measured_bond_cost_needs_both_sides_in_a_day():
    trades = pd.DataFrame(dict(bond_id="B", execution_time=pd.Timestamp("2010-01-05 10:00"), price=[100.5], size=[1e6], is_customer_buy=[True]))
    assert f.bond_day_costs(trades).empty


def test_median_split_is_by_each_month_and_labels_both_sides():
    t = pd.DataFrame(dict(month=[pd.Period("2010-01")] * 4, asset_id=list("ABCD"), value=[1.0, 2.0, 3.0, 4.0]))
    assert f.median_split(t, "large", "small").label.tolist() == ["small", "small", "large", "large"]


def test_median_split_leaves_out_a_blank():
    t = pd.DataFrame(dict(month=[pd.Period("2010-01")] * 2, asset_id=list("AB"), value=[1.0, np.nan]))
    assert f.median_split(t, "large", "small").asset_id.tolist() == ["A"]


# ---------------------------------------------------------------- Dead names

def dead_inputs():
    bonds = pd.DataFrame(dict(date=pd.to_datetime(["2010-05-31"]), bond_id="B", firm_id="F", coupon=.06, freq=2, maturity_years=5.0,
                              full_price=.8, coupon_paid=0.0, amount_out=500.0))
    equities = pd.DataFrame(dict(date=pd.to_datetime(["2010-05-31"]), firm_id="F", stock_close=2.0, split_factor=1.0, dividend=0.0, shares_out=1e8))
    return bonds, equities


def test_a_default_adds_the_recovery_as_the_bonds_last_price():
    bonds, equities = dead_inputs()
    events = pd.DataFrame(dict(issuer_id=["F"], event_date=pd.to_datetime(["2010-08-10"]), event_type="default", realised_recovery=35.0, delisting_return=np.nan))
    b, e, counts = f.apply_end_events(bonds, equities, events)
    assert b.full_price.iloc[-1] == pytest.approx(.35)
    assert b.date.iloc[-1].to_period("M") == pd.Period("2010-06")
    assert counts["bond_recoveries"] == 1 and counts["stock_delistings"] == 0


def test_a_delisting_return_adds_a_last_stock_price():
    bonds, equities = dead_inputs()
    events = pd.DataFrame(dict(issuer_id=["F"], event_date=pd.to_datetime(["2010-06-02"]), event_type="merger", realised_recovery=np.nan, delisting_return=.2))
    b, e, counts = f.apply_end_events(bonds, equities, events)
    assert len(b) == 1 and e.stock_close.iloc[-1] == pytest.approx(2.4) and e.date.iloc[-1] > equities.date.iloc[-1]


def test_a_total_loss_stays_finite():
    bonds, equities = dead_inputs()
    events = pd.DataFrame(dict(issuer_id=["F"], event_date=pd.to_datetime(["2010-06-02"]), event_type="default", realised_recovery=np.nan, delisting_return=-1.0))
    assert f.apply_end_events(bonds, equities, events)[1].stock_close.iloc[-1] > 0


def test_a_bond_still_priced_after_the_event_gets_no_extra_row():
    bonds, equities = dead_inputs()
    events = pd.DataFrame(dict(issuer_id=["F"], event_date=pd.to_datetime(["2010-05-10"]), event_type="default", realised_recovery=35.0, delisting_return=np.nan))
    assert len(f.apply_end_events(bonds, equities, events)[0]) == 1


# ---------------------------------------------------------------- Verdict

def good_numbers(**over):
    base = dict(months=120, median_firms=100, gap_q1=-139.0, gap_q5=271.0, ratio_q1=.94, ratio_q5=1.16, premium=.03, premium_t=2.5, stock_premium=.04)
    return {**base, **over}


def test_all_signs_right_is_reproduced():
    assert f.judge(**good_numbers()).verdict == f.REPRODUCED


@pytest.mark.parametrize("over", [dict(gap_q1=10.0), dict(gap_q5=-5.0), dict(ratio_q1=1.01), dict(ratio_q5=.99), dict(premium=-.03),
                                  dict(premium_t=1.5), dict(stock_premium=-.01)])
def test_any_wrong_sign_is_not_reproduced(over):
    assert f.judge(**good_numbers(**over)).verdict == f.NOT_REPRODUCED


@pytest.mark.parametrize("over", [dict(months=30), dict(median_firms=10), dict(premium=np.nan), dict(gap_q1=np.nan)])
def test_too_little_to_judge(over):
    v = f.judge(**good_numbers(**over))
    assert v.verdict == f.NOT_JUDGED and v.reason


def test_overall_takes_the_weakest_run():
    assert f.overall([f.REPRODUCED, f.NOT_REPRODUCED]) == f.NOT_REPRODUCED
    assert f.overall([f.REPRODUCED, f.NOT_JUDGED]) == f.NOT_JUDGED
    assert f.overall([f.REPRODUCED, f.REPRODUCED]) == f.REPRODUCED


def test_stop_rule_fires_at_or_below_zero_and_not_on_nan():
    assert f.stop_rule(0.0) == "STOP"
    assert f.stop_rule(-.01) == "STOP"
    assert f.stop_rule(.01) == "CONTINUE"
    assert f.stop_rule(np.nan) == "NOT JUDGED"


# ---------------------------------------------------------------- The whole run

def independent_premium(tables, paths, months, target_months):
    """Top minus bottom quintile by the planted spread, value-weighted, from the price table alone."""
    p = tables["bond_prices"].assign(month=lambda d: d.date.dt.to_period("M"))
    issuers = sorted(p.bond_id.unique())
    out = []
    price = p.pivot(index="month", columns="bond_id", values="full_price")
    paid = p.pivot(index="month", columns="bond_id", values="coupon_paid")
    size = p.pivot(index="month", columns="bond_id", values="amount_out")
    for k in range(len(months) - 1):
        m, n = months[k], months[k + 1]
        s = pd.Series(paths[k], index=issuers).reindex(price.loc[m].dropna().index)
        ranks = np.ceil(s.rank(method="first") * 5 / len(s))
        ret = (price.loc[n] + paid.loc[n]) / price.loc[m] - 1
        val = size.loc[m] * price.loc[m]
        side = lambda q: (ret[ranks[ranks == q].index] * val[ranks[ranks == q].index]).sum() / val[ranks[ranks == q].index].sum()
        out.append(side(5) - side(1))
    return 12 * float(np.mean(out))


def test_planted_premium_is_recovered_and_reproduced(planted):
    report, paths, months, _ = planted
    tables = make_tables(paths, months, stock_signal=.01)
    known = independent_premium(tables, paths, months, months)
    for run in report.runs.values():
        assert run.verdict.verdict == f.REPRODUCED
        assert run.premium == pytest.approx(known, abs=.015)
    assert report.overall == f.REPRODUCED


def test_both_compoundings_appear(planted):
    report, *_ , out = planted
    assert set(report.runs) == {"continuous", "semiannual"}
    assert set(pd.read_csv(out / "summary_table.csv").compounding) == {"continuous", "semiannual"}
    text = (out / "summary.txt").read_text()
    assert "continuous" in text and "semiannual" in text


def test_summary_states_target_replicated_gap_t_and_verdict(planted):
    text = (planted[3] / "summary.txt").read_text()
    for word in ("Published", "Replicated", "Gap", "t=", "VERDICT", "REPRODUCED"):
        assert word in text


def test_summary_carries_the_hindsight_rows_and_the_vintage_rule(planted):
    text = (planted[3] / "summary.txt").read_text()
    assert "hindsight" in text
    assert "as known at the end of its own month" in text


def test_writes_every_table_and_no_name_level_rows(planted):
    out = planted[3]
    for name in ("summary.txt", "summary_table.csv", "monthly_returns.csv", "quintile_profile.csv", "splits.csv", "screens.csv", "contract.csv", "missing.csv"):
        assert (out / name).exists(), name
    for csv in out.glob("*.csv"):
        columns = set(pd.read_csv(csv, nrows=1).columns)
        assert not columns & {"bond_id", "firm_id", "asset_id", "issuer_id", "ticker"}, csv.name


def test_splits_report_size_and_say_when_fees_are_absent(planted):
    splits = pd.read_csv(planted[3] / "splits.csv")
    assert {"large", "small"} <= set(splits[splits.split == "size"].label)
    text = (planted[3] / "summary.txt").read_text()
    assert "fee split: not available" in text


def test_stop_rule_line_names_the_cost_source(planted):
    text = (planted[3] / "summary.txt").read_text()
    assert "Stop rule" in text and "planning cost, not measured" in text


def test_a_missing_corporate_actions_table_is_flagged(planted):
    assert "No corporate_actions table" in (planted[3] / "summary.txt").read_text()


def test_dead_name_is_counted_in_the_summary(planted):
    assert "bond_recoveries=1" in (planted[3] / "summary.txt").read_text()


def test_no_signal_panel_is_not_reproduced(tmp_path):
    months = study_months()
    report = run_folder(tmp_path, make_tables(noise_paths(months), months))
    assert report.overall == f.NOT_REPRODUCED


def test_tiny_sample_is_not_judged(tmp_path):
    months = pd.period_range("2007-01", periods=12, freq="M")
    report = run_folder(tmp_path, make_tables(signal_paths(months), months, dead_day="2007-06-29"), end=pd.Timestamp("2007-12-31"))
    assert report.overall == f.NOT_JUDGED
    assert "months" in report.runs["continuous"].verdict.reason


def test_a_survivors_only_panel_stops_the_run(tmp_path):
    months = pd.period_range("2007-01", periods=12, freq="M")
    with pytest.raises(r.ContractFailed, match="survivorship"):
        run_folder(tmp_path, make_tables(signal_paths(months), months, dead=False), end=pd.Timestamp("2007-12-31"))


def tiny_tables(**over):
    months = pd.period_range("2007-01", periods=12, freq="M")
    t = make_tables(signal_paths(months), months, dead_day="2007-06-29")
    t.update(over)
    return t


def tiny_vintage(tmp_path, tables):
    return r.vintage_inputs(r.TableSource(_write(tables, tmp_path)), pd.Timestamp("2007-01-01"), pd.Timestamp("2007-12-31"), pd.Timestamp("2008-01-01"))


def test_screen_rows_hold_prices_per_1(tmp_path):
    t = tiny_tables()
    rows = tiny_vintage(tmp_path, t).screen_rows
    assert rows.clean_price.iloc[0] == pytest.approx(t["bond_prices"].sort_values("date").clean_price.iloc[0] / 100, rel=.2)
    assert rows.clean_price.max() < 2.0


def test_a_terms_column_nobody_fills_counts_as_absent(tmp_path):
    t = tiny_tables()
    t["bond_terms"] = t["bond_terms"].assign(is_convertible=np.nan)
    rows = tiny_vintage(tmp_path, t).screen_rows
    assert "is_convertible" not in rows and "is_putable" in rows


def test_financing_of_a_stock_is_keyed_by_issuer_and_of_a_bond_by_bond(tmp_path):
    day = pd.Timestamp("2007-03-30")
    money = pd.DataFrame(dict(date=day, instrument_id=["E03", "B03"], repo_rate=[np.nan, .03], bond_fee=[np.nan, .01], stock_fee=[.02, np.nan], available_at=day + CLOSE))
    fin = tiny_vintage(tmp_path, tiny_tables(financing=money)).financing.set_index("asset_id")
    assert fin.stock_fee["I03"] == pytest.approx(.02)
    assert fin.bond_fee["B03"] == pytest.approx(.01)
    assert fin.month["I03"] == pd.Period("2007-03")


def test_all_bonds_screened_out_leaves_nothing_to_judge(tmp_path):
    t = tiny_tables()
    t["bond_terms"] = t["bond_terms"].assign(is_convertible=True)
    report = run_folder(tmp_path, t, end=pd.Timestamp("2007-12-31"))
    assert report.runs["continuous"].months == 0 and report.overall == f.NOT_JUDGED
    screens = pd.read_csv(tmp_path / "out" / "screens.csv").set_index("screen")
    assert screens.removed["terms"] == screens.tested["terms"] > 0


def test_the_verdict_reads_the_value_weighted_one_month_row(planted):
    report, *_, out = planted
    rows = pd.read_csv(out / "summary_table.csv")
    rows = rows[(rows.compounding == "continuous") & (rows.leg == "bond") & (rows.hold == 1) & (rows["sample"] == "published window")].set_index("weighting")
    assert report.runs["continuous"].premium == pytest.approx(rows.gross_annual["value"])
    assert rows.gross_annual["value"] != pytest.approx(rows.gross_annual["equal"], abs=1e-6)


def test_the_two_compoundings_are_really_different_runs(planted):
    profile = pd.read_csv(planted[3] / "quintile_profile.csv")
    top = profile[profile.quintile == 5].set_index("compounding").des_bp
    assert top["continuous"] != pytest.approx(top["semiannual"], abs=1e-3)


def test_legs_long_top_bonds_and_bottom_stocks(monkeypatch):
    empty = pd.DataFrame()
    monkeypatch.setattr(f, "holdings_from_study", lambda study: (empty, empty))
    monkeypatch.setattr(r.fd, "bond_month_returns", lambda b: empty)
    monkeypatch.setattr(r.fd, "stock_month_returns", lambda p, lag: empty)
    legs = r._leg_tables(None, empty, empty, r.fd.DesConfig())
    assert legs["bond"][2:] == (5, 1) and legs["stock"][2:] == (1, 5)


def test_stock_cash_rate_is_the_one_known_at_the_fee_date():
    financing = pd.DataFrame(dict(month=[pd.Period("2010-01")], asset_id=["F"], repo_rate=[np.nan], bond_fee=[np.nan], stock_fee=[.02]))
    hedges = pd.DataFrame(dict(month=[pd.Period("2010-01"), pd.Period("2010-02")], hedge_return=[0.0, 0.0], hedge_duration=[4.0, 4.0], repo=[.09, .03]))
    got = r._financing_rates(financing, hedges, "stock")
    assert got.repo.iloc[0] == pytest.approx(.03) and got.fee.iloc[0] == pytest.approx(.02)


def bad_tables():
    months = pd.period_range("2007-01", periods=12, freq="M")
    t = make_tables(signal_paths(months), months, dead=False)
    t["equity_prices"] = t["equity_prices"].assign(available_at=lambda d: d.date - pd.Timedelta(5, "D"))
    return t


def test_contract_failure_stops_the_run_and_names_no_row(tmp_path, capsys):
    with pytest.raises(r.ContractFailed) as e:
        run_folder(tmp_path, bad_tables(), end=pd.Timestamp("2007-12-31"))
    assert "look_ahead" in str(e.value)
    assert (tmp_path / "out" / "contract.csv").exists()
    assert not (tmp_path / "out" / "summary.txt").exists()


def test_force_runs_past_a_contract_failure_and_says_so(tmp_path):
    report = run_folder(tmp_path, bad_tables(), end=pd.Timestamp("2007-12-31"), force=True)
    assert "FORCED" in (tmp_path / "out" / "summary.txt").read_text()
    assert report.overall == f.NOT_JUDGED


def test_a_later_correction_does_not_reach_an_earlier_sort(tmp_path):
    months = pd.period_range("2007-01", periods=12, freq="M")
    t = make_tables(signal_paths(months), months, dead=False)
    day = t["bond_prices"].date.iloc[0]
    corrected = t["bond_prices"].iloc[[0]].assign(clean_price=50.0, full_price=50.0, available_at=pd.Timestamp("2009-01-01"))
    t["bond_prices"] = pd.concat([t["bond_prices"], corrected], ignore_index=True)
    bonds = r.vintage_inputs(r.TableSource(_write(t, tmp_path)), pd.Timestamp("2007-01-01"), pd.Timestamp("2007-12-31"), pd.Timestamp("2010-01-01")).inputs.bonds
    first = bonds[(bonds.bond_id == "B00") & (bonds.date == day)]
    assert first.full_price.iloc[0] > .6


def _write(tables, tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    write_tables(tables, root)
    return root


def test_cli_stops_with_exit_code_2_on_a_contract_failure(tmp_path, monkeypatch):
    root = _write(bad_tables(), tmp_path)
    monkeypatch.setenv("E2C_DATA_ROOT", str(root))
    monkeypatch.delenv("E2C_SOURCE", raising=False)
    code = r.main(["--start", "2007-01-01", "--end", "2007-12-31", "--decision-time", "2008-01-01", "--out", str(tmp_path / "o")])
    assert code == 2


# ---------------------------------------------------------------- The real thing

@pytest.mark.skipif(not os.environ.get("E2C_F10_ROOT"), reason="Set E2C_F10_ROOT to a folder of real tables. F10 is not reproduced on made-up data.")
def test_f10_replicate_chen_chen_li(tmp_path):
    root = Path(os.environ["E2C_F10_ROOT"])
    start = pd.Timestamp(os.environ.get("E2C_F10_START", "2002-01-01"))
    end = pd.Timestamp(os.environ.get("E2C_F10_END", "2021-12-31"))
    report = r.run(r.TableSource(root), start, end, end + pd.Timedelta(1, "D"), tmp_path)
    assert report.overall == f.REPRODUCED, (tmp_path / "summary.txt").read_text()
