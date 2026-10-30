"""Tests of fk_des.py, work package WP6a. E3 and F10 of finkelstein_replication_plan.pdf, Section 9, then synthetic data.

E3's expected values come from the plan's table. F10 needs real data, so it is skipped and nothing here reproduces it.
Every panel below is made up by make_panel. Those tests check the logic, and they say nothing about any market.
"""
from datetime import date
from typing import NamedTuple

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq

import fk_des as fd
import fk_model as fk
import fk_value as v
from fk_value import e2c

TENORS = (.25, .5, 1., 2., 3., 5., 7., 10.)
FLAT = e2c.flat_curve(.05)
UPWARD = e2c.ZeroCurve((.5, 2., 5., 10.), (.01, .02, .035, .05))
BOND_SIDE, STOCK_SIDE = "bond", "stock"


# ---------------------------------------------------------------- A made-up market

class Panel(NamedTuple):
    bonds: pd.DataFrame
    equities: pd.DataFrame
    accounts: pd.DataFrame
    rates: pd.DataFrame
    truth: pd.DataFrame


def make_panel(seed: int, n_firms: int = 30, n_months: int = 12, gap_bp: float = 0.0, stock_k: float = 0.0,
               rho: float = .5, price_noise: float = 0.0, hist_days: int = 500, vol: float = .30) -> Panel:
    """A made-up market. None of these numbers comes from data.

    Firms: share price uniform on 15 to 40, debt per share uniform on 10 to 30, 100mm shares, equity vol 30%.
    Payout: a fixed cash amount, 3% of the first (S + D) a year. Rates: every par yield is 5%. No dividends in the stock.
    Bonds: one per firm, 7% semiannual, 5 years left in the first month, 100mm face.
    Market price: the model's price with the true vol, shifted by a planted gap g in Z-spread.
    g follows an AR(1) with persistence rho and standard deviation gap_bp, so a wide bond tends to tighten.
    Stocks: daily lognormal, with a drift of -stock_k * g over the month after the sort.
    price_noise is a one-off error in the month-end print. entry_price then holds the clean price.
    """
    rng = np.random.default_rng(seed)
    month_ends = pd.date_range("2015-01-01", periods=n_months, freq="BME")
    start = pd.bdate_range(end=month_ends[0], periods=hist_days)
    firm_ids = [f"F{i:03d}" for i in range(n_firms)]
    S = rng.uniform(15., 40., n_firms)
    D = rng.uniform(10., 30., n_firms)
    payout_per_share = .03 * (S + D)
    shares = 1e8
    curve = e2c.zero_curve_from_par_yields(TENORS, [.05] * len(TENORS))
    daily_sd = vol / np.sqrt(252)
    gap = gap_bp / 1e4
    g = rng.normal(0.0, gap, n_firms) if gap > 0 else np.zeros(n_firms)

    equity_rows, bond_rows, truth_rows = [], [], []

    def walk(days, drift_per_month):
        for i, firm in enumerate(firm_ids):
            x = rng.normal(drift_per_month[i] / 21, daily_sd, len(days))
            path = S[i] * np.exp(np.cumsum(x))
            equity_rows.extend((d, firm, p, 1.0, 0.0, shares) for d, p in zip(days, path))
            S[i] = path[-1]

    equity_rows.extend((start[0], firm, S[i], 1.0, 0.0, shares) for i, firm in enumerate(firm_ids))
    walk(start[1:], np.zeros(n_firms))
    previous_flows = None
    for t, me in enumerate(month_ends):
        T = 5.0 - t / 12
        bond = e2c.Bond(.07, T, 2)
        flows = int(np.ceil(T * 2 - 1e-9))
        coupon = .035 if previous_flows is not None and flows < previous_flows else 0.0
        previous_flows = flows
        r = float(-np.log(curve.df(T)) / T)
        for i, firm in enumerate(firm_ids):
            B = .5 * D[i]
            sig = fk.asset_vol_fs(vol, S[i], D[i])
            delta = min(payout_per_share[i] / (S[i] + D[i]), .15)
            q = lambda u, i=i, sig=sig, delta=delta, B=B: np.array(
                [fk.des_survival(float(x), S[i] + B, B, sig, r, delta, .3) for x in np.atleast_1d(u)])
            z = e2c.z_spread(v.fk_bond_price(bond, q, curve, .35, steps_per_year=12), bond, curve) + g[i]
            clean = e2c.price_from_z(z, bond, curve)
            shown = clean * (1 + rng.normal(0.0, price_noise)) if price_noise > 0 else clean
            bond_rows.append((me, f"B{firm}", firm, .07, 2, T, shown, coupon, 100.0, clean))
            truth_rows.append((me, firm, g[i] * 1e4))
        if t < n_months - 1:
            walk(pd.bdate_range(me + pd.Timedelta(days=1), month_ends[t + 1]), -stock_k * g)
            g = rho * g + rng.normal(0.0, gap * np.sqrt(1 - rho ** 2), n_firms) if gap > 0 else g

    bonds = pd.DataFrame(bond_rows, columns=["date", "bond_id", "firm_id", "coupon", "freq", "maturity_years",
                                             "full_price", "coupon_paid", "amount_out", "entry_price"])
    if price_noise == 0:
        bonds = bonds.drop(columns="entry_price")
    equities = pd.DataFrame(equity_rows, columns=["date", "firm_id", "stock_close", "split_factor", "dividend", "shares_out"])
    accounts = pd.DataFrame({"firm_id": firm_ids, "period_end": pd.Timestamp("2014-09-30"),
                             "available_date": pd.Timestamp("2014-11-15"), "total_liabilities": D * 100.0,
                             "dividends": payout_per_share * 100.0, "interest": 0.0, "repurchases": 0.0})
    rates = pd.DataFrame([(me, tenor, .05) for me in month_ends for tenor in TENORS], columns=["date", "tenor", "par_yield"])
    truth = pd.DataFrame(truth_rows, columns=["date", "firm_id", "g_bp"])
    return Panel(bonds, equities, accounts, rates, truth)


CONFIG = fd.DesConfig(vol_min_obs=250, steps_per_year=12, bond_round_trip_cost=.004, stock_round_trip_cost=.002)
SMALL_CONFIG = CONFIG._replace(vol_min_obs=100)


def small_panel() -> Panel:
    return make_panel(3, n_firms=10, n_months=6, hist_days=260)


def run(panel: Panel, config: fd.DesConfig = SMALL_CONFIG) -> fd.DesStudy:
    return fd.run_des_study(panel.bonds, panel.equities, panel.accounts, panel.rates, config)


def returns_of(study: fd.DesStudy, leg: str, hold: int = 1, weighting: str = "equal") -> pd.DataFrame:
    r = study.returns
    return r[(r.leg == leg) & (r.hold == hold) & (r.weighting == weighting)].set_index("month")


def missing_count(study: fd.DesStudy, stage: str, reason: str) -> int:
    m = study.missing
    return int(m[(m.stage == stage) & (m.reason == reason)].n.sum())


@pytest.fixture(scope="module")
def planted():
    panel = make_panel(7, n_firms=40, n_months=18, gap_bp=150.0, stock_k=2.0)
    return panel, run(panel, CONFIG)


@pytest.fixture(scope="module")
def no_gap():
    panel = make_panel(11, n_firms=40, n_months=18)
    return panel, run(panel, CONFIG)


# ---------------------------------------------------------------- E3 and F10

def gx():
    d0, maturity = date(2001, 6, 14), date(2009, 11, 15)
    accrued = .095 * ((d0.month - 5) * 30 + (d0.day - 15)) / 360
    return e2c.Bond(.095, (maturity - d0).days / 365.0, 2), .84 + accrued


@pytest.mark.parametrize("payout, gap_bp, ratio", [(.03, -149, .919), (.05, -213, .888)])
def test_e3_bond_des_on_gx(payout, gap_bp, ratio):
    bond, full = gx()
    out = fd.bond_des(full, bond, 10.5, 14.2, .822, payout, FLAT)
    assert out.status == "ok"
    assert out.des_bp == pytest.approx(gap_bp, abs=2)
    assert out.price_ratio == pytest.approx(ratio, abs=.002)
    assert out.des_bp == pytest.approx(out.cs_d_bp - out.cs_e_bp, abs=1e-9)


@pytest.mark.parametrize("payout, gap_bp", [(.03, -158.5), (.05, -226.6)])
def test_e3_values_depend_on_yield_compounding(payout, gap_bp):
    """E3's numbers were made with Z-spreads. A continuous yield equals them on a flat curve, and a semiannual yield does not."""
    bond, full = gx()
    assert fd.bond_des(full, bond, 10.5, 14.2, .822, payout, FLAT, yield_freq=2).des_bp == pytest.approx(gap_bp, abs=1)


@pytest.mark.skip(reason="F10 needs real bond, stock and accounts data, which this machine does not have. "
                         "It is not reproduced here, and that includes the published 3.24% a year.")
def test_f10_replicate_chen_chen_li():
    raise AssertionError("Plug in production data and write this test against the plan's F10 row.")


# ---------------------------------------------------------------- Yields, spreads, one bond

@pytest.mark.parametrize("freq", [None, 2])
def test_cs_d_on_a_sloped_curve_against_a_direct_solve(freq):
    bond, full = e2c.Bond(.06, 7.0, 2), .95
    t, cf = e2c.cash_flows(bond)

    def direct(price):
        if freq is None:
            return brentq(lambda y: np.sum(cf * np.exp(-y * t)) - price, -.5, 5.)
        return brentq(lambda y: np.sum(cf * (1 + y / freq) ** (-freq * t)) - price, -.5, 5.)

    treasury = float(np.sum(cf * UPWARD.df(t)))
    out = fd.bond_des(full, bond, 30., 20., .4, .02, UPWARD, yield_freq=freq)
    assert out.cs_d_bp == pytest.approx((direct(full) - direct(treasury)) * 1e4, abs=1e-5)
    assert out.cs_e_bp == pytest.approx((direct(out.model_price) - direct(treasury)) * 1e4, abs=1e-5)
    assert out.des_bp == pytest.approx((direct(full) - direct(out.model_price)) * 1e4, abs=1e-5)


def test_bond_des_is_zero_at_the_model_price_and_positive_when_cheaper():
    bond = e2c.Bond(.07, 5.0, 2)
    model = fd.bond_des(1.0, bond, 25., 20., .35, .03, FLAT).model_price
    assert fd.bond_des(model, bond, 25., 20., .35, .03, FLAT).des_bp == pytest.approx(0.0, abs=1e-6)
    assert fd.bond_des(model * .98, bond, 25., 20., .35, .03, FLAT).des_bp > 0


def test_bond_des_uses_the_recovery_it_is_given():
    bond = e2c.Bond(.07, 5.0, 2)
    default = fd.bond_des(1.0, bond, 15., 20., .5, .03, FLAT)
    assert default.model_price == fd.bond_des(1.0, bond, 15., 20., .5, .03, FLAT, recovery=.35).model_price
    assert fd.bond_des(1.0, bond, 15., 20., .5, .03, FLAT, recovery=.5).model_price > default.model_price


@pytest.mark.parametrize("kwargs, status", [
    (dict(full=float("nan")), "missing_price"),
    (dict(full=0.0), "missing_price"),
    (dict(S=float("nan")), "missing_stock"),
    (dict(D=float("nan")), "missing_debt"),
    (dict(D=0.0), "missing_debt"),
    (dict(sigma_s=float("nan")), "missing_vol"),
    (dict(delta=float("nan")), "missing_payout"),
    (dict(curve=None), "missing_curve"),
    (dict(bond=e2c.Bond(float("nan"), 5.0, 2)), "missing_terms"),
    (dict(bond=e2c.Bond(.07, 0.0, 2)), "missing_terms"),
    (dict(full=1e-6), "no_yield"),
])
def test_bond_des_reports_why_it_is_nan(kwargs, status):
    args = dict(full=1.0, bond=e2c.Bond(.07, 5.0, 2), S=25., D=20., sigma_s=.35, delta=.03, curve=FLAT)
    args.update(kwargs)
    out = fd.bond_des(args["full"], args["bond"], args["S"], args["D"], args["sigma_s"], args["delta"], args["curve"])
    assert out.status == status
    assert np.isnan(out.des_bp)


# ---------------------------------------------------------------- Inputs to the model

def test_debt_per_share_converts_millions():
    assert fd.debt_per_share(1420.0, 1e8) == pytest.approx(14.2)
    assert np.isnan(fd.debt_per_share(float("nan"), 1e8))
    assert np.isnan(fd.debt_per_share(1420.0, float("nan")))


def test_payout_delta_formula_and_cap():
    # (10 + 20 + 30) mm on 100mm shares is 0.60 a share, on S + D = 20
    assert fd.payout_delta(10., 20., 30., 1e8, 12., 8.) == pytest.approx(.03)
    assert fd.payout_delta(100., 200., 300., 1e8, 12., 8.) == .15
    assert fd.payout_delta(100., 200., 300., 1e8, 12., 8., cap=.2) == .2
    assert fd.payout_delta(-10., 0., 0., 1e8, 12., 8.) == 0.0
    assert fd.payout_delta(-10., 0., 0., 1e8, 12., 8., floor=-1.) == pytest.approx(-.005)


@pytest.mark.parametrize("args", [(float("nan"), 20., 30., 1e8, 12., 8.), (10., float("nan"), 30., 1e8, 12., 8.),
                                  (10., 20., float("nan"), 1e8, 12., 8.), (10., 20., 30., float("nan"), 12., 8.),
                                  (10., 20., 30., 1e8, float("nan"), 8.), (10., 20., 30., 1e8, 12., float("nan"))])
def test_payout_delta_keeps_nan(args):
    assert np.isnan(fd.payout_delta(*args))


def test_equity_panel_splits_and_dividends():
    days = pd.bdate_range("2020-01-01", periods=4)
    raw = pd.DataFrame({"date": days, "firm_id": "A", "stock_close": [100., 110., 55., 55.],
                        "split_factor": [1., 1., 2., 1.], "dividend": [0., 0., 0., 1.], "shares_out": 1e6})
    x = fd.equity_panel(raw).x.to_numpy()
    assert np.isnan(x[0])
    assert x[1] == pytest.approx(np.log(1.1))
    assert x[2] == pytest.approx(0.0)
    assert x[3] == pytest.approx(np.log(56 / 55))


def test_equity_panel_keeps_a_gap_as_nan():
    days = pd.bdate_range("2020-01-01", periods=4)
    raw = pd.DataFrame({"date": days, "firm_id": "A", "stock_close": [100., float("nan"), 110., 121.],
                        "split_factor": 1., "dividend": 0., "shares_out": 1e6})
    x = fd.equity_panel(raw).x.to_numpy()
    assert np.isnan(x[1]) and np.isnan(x[2])
    assert x[3] == pytest.approx(np.log(1.1))


def test_rolling_vol_window_and_asof():
    days = pd.bdate_range("2016-01-01", "2020-12-31")
    x = pd.Series(np.random.default_rng(1).normal(0., .01, len(days)), index=days)
    asof = pd.Timestamp("2020-06-30")
    inside = x[(x.index > pd.Timestamp("2017-06-30")) & (x.index <= asof)]
    assert fd.rolling_equity_vol(x, asof) == pytest.approx(inside.std(ddof=1) * np.sqrt(252))
    later = x.copy()
    later[later.index > asof] = .5
    older = later.copy()
    older[older.index <= pd.Timestamp("2017-06-30")] = -.5
    assert fd.rolling_equity_vol(older, asof) == pytest.approx(fd.rolling_equity_vol(x, asof))


def test_rolling_vol_needs_enough_observations():
    days = pd.bdate_range("2019-01-01", periods=100)
    x = pd.Series(.01 * np.resize([1., -1.], 100), index=days)
    assert np.isnan(fd.rolling_equity_vol(x, days[-1], min_obs=101))
    assert np.isfinite(fd.rolling_equity_vol(x, days[-1], min_obs=100))
    x.iloc[-1] = float("nan")
    assert np.isnan(fd.rolling_equity_vol(x, days[-1], min_obs=100))


def test_curve_asof_uses_the_latest_earlier_date_and_rejects_gaps():
    rates = pd.DataFrame([(d, t, y) for d, y in (("2020-01-31", .01), ("2020-02-28", .02)) for t in TENORS],
                         columns=["date", "tenor", "par_yield"]).assign(date=lambda f: pd.to_datetime(f.date))
    one = fd.curve_asof(rates, pd.Timestamp("2020-02-27"), max_stale_days=30)
    assert float(-np.log(one.df(2.0)) / 2.0) == pytest.approx(.01, abs=2e-4)
    two = fd.curve_asof(rates, pd.Timestamp("2020-02-28"), max_stale_days=30)
    assert float(-np.log(two.df(2.0)) / 2.0) == pytest.approx(.02, abs=2e-4)
    assert fd.curve_asof(rates, pd.Timestamp("2020-03-30"), max_stale_days=7) is None
    assert fd.curve_asof(rates, pd.Timestamp("2019-12-31"), max_stale_days=30) is None
    holed = rates.copy()
    holed.loc[(holed.date == "2020-02-28") & (holed.tenor == 2.), "par_yield"] = float("nan")
    assert fd.curve_asof(holed, pd.Timestamp("2020-02-28"), max_stale_days=30) is None


def accounts_frame(rows):
    columns = ["firm_id", "period_end", "available_date", "total_liabilities", "dividends", "interest", "repurchases"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["period_end"] = pd.to_datetime(frame.period_end)
    frame["available_date"] = pd.to_datetime(frame.available_date)
    return frame


def asof_liabilities(accounts, on, lag=2, max_age=18):
    request = pd.DataFrame({"firm_id": ["A"], "date": [pd.Timestamp(on)]})
    return float(fd.accounts_asof(accounts, request, lag, max_age).total_liabilities.iloc[0])


def test_accounts_lag_applies_to_the_available_date():
    a = accounts_frame([("A", "2019-12-31", "2020-02-15", 10., 0., 0., 0.), ("A", "2020-03-31", "2020-05-15", 20., 0., 0., 0.)])
    assert np.isnan(asof_liabilities(a, "2020-04-14"))
    assert asof_liabilities(a, "2020-04-15") == 10.
    assert asof_liabilities(a, "2020-07-14") == 10.
    assert asof_liabilities(a, "2020-07-15") == 20.
    assert asof_liabilities(a, "2020-05-15", lag=0) == 20.
    assert np.isnan(asof_liabilities(a, "2020-05-14", lag=3))
    assert asof_liabilities(a, "2020-05-15", lag=3) == 10.


def test_accounts_latest_period_wins_and_a_nan_filing_stays_nan():
    amended_old_period = accounts_frame([("A", "2020-03-31", "2020-05-15", 20., 0., 0., 0.),
                                         ("A", "2019-12-31", "2020-06-15", 11., 0., 0., 0.)])
    assert asof_liabilities(amended_old_period, "2020-09-01") == 20.
    restated = accounts_frame([("A", "2020-03-31", "2020-05-15", 20., 0., 0., 0.), ("A", "2020-03-31", "2020-06-15", 21., 0., 0., 0.)])
    assert asof_liabilities(restated, "2020-09-01") == 21.
    holed = accounts_frame([("A", "2019-12-31", "2020-02-15", 10., 0., 0., 0.), ("A", "2020-03-31", "2020-05-15", float("nan"), 0., 0., 0.)])
    assert np.isnan(asof_liabilities(holed, "2020-09-01"))


def test_accounts_too_old_or_undated_are_not_used():
    a = accounts_frame([("A", "2019-12-31", "2020-02-15", 10., 0., 0., 0.)])
    assert asof_liabilities(a, "2020-04-15", max_age=1) == 10.
    assert np.isnan(asof_liabilities(a, "2020-05-16", max_age=1))
    undated = accounts_frame([("A", "2019-12-31", None, 10., 0., 0., 0.)])
    assert np.isnan(asof_liabilities(undated, "2021-01-01"))


# ---------------------------------------------------------------- Firm DES and the sort

def test_firm_des_weights_and_nan():
    assert fd.firm_des([100., 200.], [1., 3.]) == pytest.approx(175.)
    assert fd.firm_des([100., float("nan")], [1., 3.]) == pytest.approx(100.)
    assert fd.firm_des([100., 200.], [float("nan"), 3.]) == pytest.approx(200.)
    assert np.isnan(fd.firm_des([100., 200.], [float("nan"), float("nan")]))
    assert np.isnan(fd.firm_des([float("nan")], [1.]))
    assert np.isnan(fd.firm_des([], []))


def test_quintile_sort_top_gets_the_highest_des():
    values = pd.Series(np.arange(10.), index=list("abcdefghij"))
    q = fd.quintile_sort(values)
    assert q.tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_quintile_sort_nan_and_too_few():
    values = pd.Series([1., float("nan"), 3., 4., 5., 6.], index=list("abcdef"))
    q = fd.quintile_sort(values)
    assert np.isnan(q["b"])
    assert q["f"] == 5 and q["a"] == 1
    assert fd.quintile_sort(values.iloc[:4]).isna().all()
    assert fd.quintile_sort(values, min_firms=6).isna().all()
    assert fd.quintile_sort(pd.Series(dtype=float)).empty


# ---------------------------------------------------------------- Monthly returns by name

def test_bond_month_returns_with_coupon_gap_and_entry_price():
    months = pd.to_datetime(["2020-01-31", "2020-02-28", "2020-03-31", "2020-05-29"])
    bonds = pd.DataFrame({"date": months, "bond_id": "X", "firm_id": "A", "full_price": [1.00, 1.01, .99, 1.0],
                          "coupon_paid": [0., 0., .03, 0.], "amount_out": [50., 50., 60., 60.]})
    out = fd.bond_month_returns(bonds).set_index("month")
    assert out.ret[pd.Period("2020-02")] == pytest.approx(.01)
    assert out.ret[pd.Period("2020-03")] == pytest.approx(1.02 / 1.01 - 1)
    assert out.lag_value[pd.Period("2020-03")] == pytest.approx(50 * 1.01)
    assert np.isnan(out.ret[pd.Period("2020-01")])
    assert np.isnan(out.ret[pd.Period("2020-05")])
    assert out.ret_first[pd.Period("2020-02")] == out.ret[pd.Period("2020-02")]
    with_entry = bonds.assign(entry_price=[1.005, float("nan"), 1.0, 1.0])
    out = fd.bond_month_returns(with_entry).set_index("month")
    assert out.ret_first[pd.Period("2020-02")] == pytest.approx(1.01 / 1.005 - 1)
    assert out.ret[pd.Period("2020-02")] == pytest.approx(.01)
    assert np.isnan(out.ret_first[pd.Period("2020-03")])


def test_stock_month_returns_compound_and_skip_the_execution_day():
    days = pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-03", "2020-02-04", "2020-02-28", "2020-03-02"])
    raw = pd.DataFrame({"date": days, "firm_id": "A", "stock_close": [10., 10., 11., 12., 13., float("nan")],
                        "split_factor": 1., "dividend": 0., "shares_out": 1e6})
    out = fd.stock_month_returns(fd.equity_panel(raw), execution_lag_days=1).set_index("month")
    feb = pd.Period("2020-02")
    assert out.ret[feb] == pytest.approx(.3)
    assert out.ret_first[feb] == pytest.approx(13 / 11 - 1)
    assert out.lag_value[feb] == pytest.approx(10 * 1.0)  # 10 USD a share times 1mm shares, in USD mm
    assert np.isnan(out.ret[pd.Period("2020-01")])
    assert np.isnan(out.ret[pd.Period("2020-03")])
    no_lag = fd.stock_month_returns(fd.equity_panel(raw), execution_lag_days=0).set_index("month")
    assert no_lag.ret_first[feb] == pytest.approx(.3)


# ---------------------------------------------------------------- T0 by hand

M = [pd.Period(f"2020-0{i}") for i in range(1, 6)]


def toy_holdings(*cohorts):
    return pd.DataFrame([(month, name, group) for month, members in cohorts for group, names in members.items() for name in names],
                        columns=["month", "asset_id", "group"])


def toy_returns(rows):
    return pd.DataFrame(rows, columns=["month", "asset_id", "ret", "ret_first", "lag_value"])


TOY_RET = toy_returns([(M[1], "A", .02, .02, 1.), (M[1], "B", .04, .04, 3.), (M[1], "C", .01, .01, 1.), (M[1], "D", -.01, -.01, 1.)])


def test_t0_equal_and_value_weights_by_hand():
    h = toy_holdings((M[0], {5: "AB", 1: "CD"}))
    equal = fd.t0_returns(h, TOY_RET, 5, 1, 1, "equal", .01).set_index("month").loc[M[1]]
    assert equal.gross == pytest.approx(.03)
    assert equal.cost == pytest.approx(.01)   # all of both sides bought, half a round trip on 2 of gross
    assert equal.net == pytest.approx(.02)
    value = fd.t0_returns(h, TOY_RET, 5, 1, 1, "value", .01).set_index("month").loc[M[1]]
    assert value.gross == pytest.approx(.035)


def test_t0_stock_side_is_long_the_bottom_quintile():
    h = toy_holdings((M[0], {5: "AB", 1: "CD"}))
    assert fd.t0_returns(h, TOY_RET, 1, 5, 1, "equal", 0.).set_index("month").gross[M[1]] == pytest.approx(-.03)


def test_t0_cost_follows_turnover():
    rets = toy_returns([(m, n, .01, .01, 1.) for m in M[1:4] for n in "ABCDEFGH"])
    stay = toy_holdings((M[0], {5: "AB", 1: "CD"}), (M[1], {5: "AB", 1: "CD"}), (M[2], {5: "EF", 1: "GH"}))
    cost = fd.t0_returns(stay, rets, 5, 1, 1, "equal", .01).set_index("month").cost
    assert cost[M[1]] == pytest.approx(.01)
    assert cost[M[2]] == pytest.approx(0.0)
    assert cost[M[3]] == pytest.approx(.02)   # both sides sold and bought, a full round trip on 2 of gross


def test_t0_hold_averages_cohorts_and_uses_ret_first_only_for_age_one():
    h = toy_holdings((M[0], {5: "A", 1: "B"}), (M[1], {5: "C", 1: "D"}))
    rets = toy_returns([(M[1], "A", .10, .08, 1.), (M[1], "B", .00, .00, 1.),
                        (M[2], "A", .05, .99, 1.), (M[2], "B", .00, .99, 1.), (M[2], "C", .03, .02, 1.), (M[2], "D", .01, .00, 1.)])
    out = fd.t0_returns(h, rets, 5, 1, 2, "equal", 0.).set_index("month")
    assert out.gross[M[1]] == pytest.approx(.08)
    assert out.n_cohorts[M[1]] == 1
    assert out.gross[M[2]] == pytest.approx(.5 * (.05 + .02))
    assert out.n_cohorts[M[2]] == 2


def test_t0_a_missing_return_is_dropped_never_zero():
    h = toy_holdings((M[0], {5: "AB", 1: "CD"}))
    rets = TOY_RET.copy()
    rets.loc[rets.asset_id == "B", ["ret", "ret_first"]] = float("nan")
    row = fd.t0_returns(h, rets, 5, 1, 1, "equal", 0.).set_index("month").loc[M[1]]
    assert row.gross == pytest.approx(.02)
    assert row.n_missing == 1
    rets.loc[rets.asset_id == "A", ["ret", "ret_first"]] = float("nan")
    row = fd.t0_returns(h, rets, 5, 1, 1, "equal", 0.).set_index("month").loc[M[1]]
    assert np.isnan(row.gross) and np.isnan(row.cost) and np.isnan(row.net)


def test_t0_nan_cost_gives_nan_net_and_negative_cost_is_refused():
    h = toy_holdings((M[0], {5: "AB", 1: "CD"}))
    row = fd.t0_returns(h, TOY_RET, 5, 1, 1, "equal", float("nan")).set_index("month").loc[M[1]]
    assert row.gross == pytest.approx(.03) and np.isnan(row.net)
    with pytest.raises(ValueError):
        fd.t0_returns(h, TOY_RET, 5, 1, 1, "equal", -.01)
    with pytest.raises(ValueError):
        fd.t0_returns(h, TOY_RET, 5, 1, 1, "nonsense", .01)


def test_t0_with_no_holdings_is_empty():
    out = fd.t0_returns(toy_holdings(), TOY_RET, 5, 1, 1, "equal", .01)
    assert out.empty and "gross" in out.columns


# ---------------------------------------------------------------- The whole study: planted gap

def test_planted_gap_is_recovered_in_des(planted):
    panel, study = planted
    joined = study.firm_des.merge(panel.truth, on=["date", "firm_id"])
    assert len(joined) == 40 * 18
    joined = joined.dropna(subset=["des_bp"])   # the first month has no lagged value
    assert len(joined) == 40 * 17
    assert np.corrcoef(joined.des_bp, joined.g_bp)[0, 1] > .9
    assert joined.groupby("quintile").g_bp.mean().is_monotonic_increasing


@pytest.mark.parametrize("hold", [1, 3, 6])
@pytest.mark.parametrize("weighting", ["equal", "value"])
def test_planted_gap_top_bonds_beat_bottom_and_bottom_stocks_beat_top(planted, hold, weighting):
    _, study = planted
    for leg in (BOND_SIDE, STOCK_SIDE):
        gross = returns_of(study, leg, hold, weighting).gross.dropna()
        assert gross.mean() > 0
        assert gross.mean() / (gross.std(ddof=1) / np.sqrt(len(gross))) > 2


def test_summary_matches_the_monthly_returns(planted):
    _, study = planted
    row = study.summary[(study.summary.leg == BOND_SIDE) & (study.summary.hold == 3) & (study.summary.weighting == "value")].iloc[0]
    monthly = returns_of(study, BOND_SIDE, 3, "value")
    assert row.gross_mean == pytest.approx(monthly.gross.mean())
    assert row.net_mean == pytest.approx(monthly.net.mean())
    assert row.gross_annual == pytest.approx(12 * monthly.gross.mean())
    assert row.months == monthly.gross.notna().sum()


def test_quintile_profile_rises_with_the_quintile(planted):
    _, study = planted
    profile = study.quintile_profile.set_index("quintile")
    assert profile.des_bp.is_monotonic_increasing
    assert profile.price_ratio.is_monotonic_increasing
    assert len(profile) == 5


# ---------------------------------------------------------------- The whole study: no gap

def test_no_gap_des_near_zero(no_gap):
    _, study = no_gap
    assert study.firm_des.des_bp.abs().mean() < 5   # only the error in the estimated vol is left
    assert study.firm_des.des_bp.mean() == pytest.approx(0.0, abs=2)


@pytest.mark.parametrize("hold", [1, 3, 6])
def test_no_gap_long_short_returns_near_zero(no_gap, hold):
    _, study = no_gap
    bond = returns_of(study, BOND_SIDE, hold).gross.dropna()
    stock = returns_of(study, STOCK_SIDE, hold).gross.dropna()
    assert abs(bond.mean()) < .003
    assert abs(stock.mean() / (stock.std(ddof=1) / np.sqrt(len(stock)))) < 2.5


# ---------------------------------------------------------------- No look-ahead

def test_changing_data_after_t_cannot_change_the_sort_at_t():
    panel = small_panel()
    base = run(panel)
    t = pd.Timestamp(sorted(panel.bonds.date.unique())[3])
    later_bonds = panel.bonds.date > t
    later_stock = panel.equities.date > t
    bonds = panel.bonds.copy()
    bonds.loc[later_bonds, "full_price"] *= np.random.default_rng(0).uniform(.5, 1.2, later_bonds.sum())
    bonds.loc[later_bonds, "amount_out"] *= 3
    equities = panel.equities.copy()
    equities.loc[later_stock, "stock_close"] *= np.random.default_rng(1).uniform(.5, 1.5, later_stock.sum())
    equities.loc[later_stock, "shares_out"] *= 2
    rates = panel.rates.copy()
    rates.loc[rates.date > t, "par_yield"] = .12
    filing = panel.accounts.assign(period_end=t, available_date=t + pd.Timedelta(days=1), total_liabilities=1e6)
    changed = fd.run_des_study(bonds, equities, pd.concat([panel.accounts, filing]), rates, SMALL_CONFIG)
    columns = ["des_bp", "quintile", "D", "S", "sigma_s", "delta", "price_ratio"]
    upto = lambda s: s.firm_des[s.firm_des.date <= t].reset_index(drop=True)[columns]
    pd.testing.assert_frame_equal(upto(base), upto(changed))
    after = lambda s: s.firm_des[s.firm_des.date > t].des_bp.to_numpy()
    assert not np.allclose(after(base), after(changed), equal_nan=True)


def test_a_return_is_earned_only_after_the_sort():
    """Move only month m's prices for the bonds. The return for the book formed at m must not be month m's own."""
    panel = small_panel()
    base = run(panel)
    months = sorted(base.firm_des.month.unique())
    m = months[3]
    top = set(base.firm_des[(base.firm_des.month == months[2]) & (base.firm_des.quintile == 5)].firm_id)
    bonds = panel.bonds.copy()
    is_m = bonds.date.dt.to_period("M") == m
    bonds.loc[is_m & bonds.firm_id.isin(top), "full_price"] *= 1.05
    changed = fd.run_des_study(bonds, panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)
    gross = lambda s: returns_of(s, BOND_SIDE).gross
    assert gross(changed)[m] - gross(base)[m] > .03
    assert months[2] not in gross(changed).index or gross(changed).get(months[2]) == pytest.approx(gross(base).get(months[2]))


def test_stock_data_after_t_cannot_change_a_firm_input_through_the_vol_window():
    panel = small_panel()
    t = pd.Timestamp(sorted(panel.bonds.date.unique())[2])
    base = run(panel).firm_des
    equities = panel.equities.copy()
    equities.loc[equities.date > t, "stock_close"] *= 5
    changed = fd.run_des_study(panel.bonds, equities, panel.accounts, panel.rates, SMALL_CONFIG).firm_des
    assert base[base.date == t].sigma_s.tolist() == changed[changed.date == t].sigma_s.tolist()


def test_a_missing_stock_day_uses_the_last_earlier_close_and_never_a_later_one():
    panel = small_panel()
    t = pd.Timestamp(sorted(panel.bonds.date.unique())[2])
    firm = panel.equities.firm_id == "F000"
    days = panel.equities[firm & (panel.equities.date <= t)].sort_values("date")
    gone_one = fd.run_des_study(panel.bonds, panel.equities[~(firm & (panel.equities.date == t))], panel.accounts, panel.rates,
                                SMALL_CONFIG).firm_des
    row = gone_one[(gone_one.firm_id == "F000") & (gone_one.date == t)].iloc[0]
    assert row.S == days.stock_close.iloc[-2]
    stale = panel.equities[~(firm & (panel.equities.date > t - pd.Timedelta(days=12)) & (panel.equities.date <= t))]
    too_old = fd.run_des_study(panel.bonds, stale, panel.accounts, panel.rates, SMALL_CONFIG)
    assert np.isnan(too_old.firm_des[(too_old.firm_des.firm_id == "F000") & (too_old.firm_des.date == t)].S.iloc[0])
    assert missing_count(too_old, "bond", "missing_stock") == 1


def test_late_accounts_date_pushes_back_their_use():
    panel = small_panel()
    dates = sorted(pd.Timestamp(d) for d in panel.bonds.date.unique())

    def debt_with_filing(available):
        filing = panel.accounts.assign(period_end=pd.Timestamp("2014-12-31"), available_date=pd.Timestamp(available),
                                       total_liabilities=panel.accounts.total_liabilities * 2)
        study = fd.run_des_study(panel.bonds, panel.equities, pd.concat([panel.accounts, filing]), panel.rates, SMALL_CONFIG)
        one = study.firm_des[study.firm_des.firm_id == "F000"].set_index("date").D
        return [one[d] for d in dates]

    base = float(panel.accounts.total_liabilities.iloc[0]) / 100.0
    on_time = debt_with_filing("2015-02-15")
    assert on_time[:2] == pytest.approx([base] * 2)   # January, February
    assert on_time[2] == pytest.approx(base)          # March: usable from 15 April
    assert on_time[3] == pytest.approx(2 * base)      # April
    late = debt_with_filing("2015-03-16")
    assert late[3] == pytest.approx(base)             # April: usable from 16 May
    assert late[4] == pytest.approx(2 * base)         # May


# ---------------------------------------------------------------- NaN, empty and thin months

def test_nan_bond_price_stays_nan_and_is_reported():
    panel = small_panel()
    bonds = panel.bonds.copy()
    month_3 = sorted(bonds.date.unique())[3]
    bonds.loc[(bonds.firm_id == "F000") & (bonds.date == month_3), "full_price"] = float("nan")
    study = fd.run_des_study(bonds, panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)
    row = study.bond_des[(study.bond_des.firm_id == "F000") & (study.bond_des.date == month_3)].iloc[0]
    assert np.isnan(row.des_bp) and row.status == "missing_price"
    firm = study.firm_des[(study.firm_des.firm_id == "F000") & (study.firm_des.date == month_3)].iloc[0]
    assert np.isnan(firm.des_bp) and np.isnan(firm.quintile)
    assert missing_count(study, "bond", "missing_price") == 1
    assert not (study.bond_des.des_bp == 0).any()


@pytest.mark.parametrize("change, status", [
    (lambda p: p.accounts.assign(total_liabilities=lambda f: f.total_liabilities.where(f.firm_id != "F001")), "missing_debt"),
    (lambda p: p.accounts.assign(dividends=lambda f: f.dividends.where(f.firm_id != "F001")), "missing_payout"),
    (lambda p: p.accounts[p.accounts.firm_id != "F001"], "missing_debt"),
])
def test_nan_accounts_leave_the_firm_unsorted(change, status):
    panel = small_panel()
    study = fd.run_des_study(panel.bonds, panel.equities, change(panel), panel.rates, SMALL_CONFIG)
    firm = study.firm_des[study.firm_des.firm_id == "F001"]
    assert firm.des_bp.isna().all() and firm.quintile.isna().all()
    assert missing_count(study, "bond", status) == 6
    other = study.firm_des[(study.firm_des.firm_id == "F002") & (study.firm_des.month > study.firm_des.month.min())]
    assert other.des_bp.notna().all()   # the first month has no lagged value


def test_nan_stock_and_rates_are_reported():
    panel = small_panel()
    dates = [pd.Timestamp(d) for d in sorted(panel.bonds.date.unique())]
    base = run(panel).firm_des
    top = base[(base.date == dates[1]) & (base.quintile == 5)].firm_id.iloc[0]
    equities = panel.equities.copy()
    equities.loc[(equities.firm_id == top) & (equities.date == dates[2]), "stock_close"] = float("nan")
    rates = panel.rates.copy()
    rates.loc[rates.date == dates[4], "par_yield"] = float("nan")
    study = fd.run_des_study(panel.bonds, equities, panel.accounts, rates, SMALL_CONFIG)
    assert missing_count(study, "bond", "missing_stock") == 1
    assert missing_count(study, "bond", "missing_curve") == 10
    assert study.firm_des[study.firm_des.date == dates[4]].des_bp.isna().all()
    assert missing_count(study, "stock_returns", "missing_return") > 0   # a top-quintile stock with no return that month
    assert study.sort_report.set_index("month").status[dates[4].to_period("M")] == "too_few_firms"


def test_missing_first_lagged_value_keeps_the_bond_out_of_the_firm_average():
    panel = small_panel()
    study = run(panel)
    first = study.firm_des[study.firm_des.month == study.firm_des.month.min()]
    assert first.des_bp.isna().all()
    assert missing_count(study, "firm", "no_lagged_value") == 10
    assert (study.firm_des[study.firm_des.month > study.firm_des.month.min()].des_bp.notna()).all()


def test_costs_reduce_returns():
    panel = small_panel()
    study = run(panel)
    for leg, rt in ((BOND_SIDE, SMALL_CONFIG.bond_round_trip_cost), (STOCK_SIDE, SMALL_CONFIG.stock_round_trip_cost)):
        r = returns_of(study, leg).dropna(subset=["gross"])
        assert (r.net <= r.gross + 1e-15).all()
        assert (r.gross - r.net).iloc[0] == pytest.approx(rt)   # first month buys both sides
        assert r.cost.max() <= 2 * rt + 1e-12
    bigger = run(panel, SMALL_CONFIG._replace(bond_round_trip_cost=.04))
    assert returns_of(bigger, BOND_SIDE).net.sum() < returns_of(study, BOND_SIDE).net.sum()
    assert returns_of(bigger, BOND_SIDE).gross.sum() == pytest.approx(returns_of(study, BOND_SIDE).gross.sum())


def test_no_cost_supplied_means_net_is_nan():
    panel = small_panel()
    study = run(panel, SMALL_CONFIG._replace(bond_round_trip_cost=float("nan"), stock_round_trip_cost=float("nan")))
    assert returns_of(study, BOND_SIDE).net.isna().all()
    assert returns_of(study, BOND_SIDE).gross.notna().any()


def test_an_empty_month_gives_no_book_and_no_zero_return():
    panel = small_panel()
    dates = sorted(panel.bonds.date.unique())
    bonds = panel.bonds[panel.bonds.date != dates[3]]
    study = fd.run_des_study(bonds, panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)
    month = pd.Timestamp(dates[3]).to_period("M")
    assert study.sort_report.set_index("month").status[month] == "empty"
    r = returns_of(study, BOND_SIDE)
    assert np.isnan(r.gross[month])          # no bond return can be measured in the empty month
    assert np.isnan(r.gross[month + 1])      # and no book was formed in it, and no price to measure from
    assert np.isnan(returns_of(study, STOCK_SIDE).gross[month + 1])
    assert missing_count(study, "sort", "empty") == 1
    assert missing_count(study, "bond_returns", "nan_month") >= 2


def test_a_thin_month_is_not_sorted_and_is_reported():
    panel = small_panel()
    dates = sorted(panel.bonds.date.unique())
    keep = (panel.bonds.date != dates[3]) | panel.bonds.firm_id.isin(["F000", "F001", "F002"])
    study = fd.run_des_study(panel.bonds[keep], panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)
    month = pd.Timestamp(dates[3]).to_period("M")
    report = study.sort_report.set_index("month")
    assert report.status[month] == "too_few_firms"
    assert report.n_valid[month] == 3
    assert study.firm_des[study.firm_des.month == month].quintile.isna().all()
    assert np.isnan(returns_of(study, BOND_SIDE).gross[month + 1])
    assert missing_count(study, "sort", "too_few_firms") >= 1


def test_no_bonds_at_all_returns_empty_tables():
    panel = small_panel()
    study = fd.run_des_study(panel.bonds.iloc[:0], panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)
    assert study.bond_des.empty and study.firm_des.empty and study.returns.empty
    assert study.summary.empty and study.sort_report.empty


def test_no_stock_or_no_rates_at_all_is_reported():
    panel = small_panel()
    no_stock = fd.run_des_study(panel.bonds, panel.equities.iloc[:0], panel.accounts, panel.rates, SMALL_CONFIG)
    assert missing_count(no_stock, "bond", "missing_stock") == 60
    assert no_stock.firm_des.quintile.isna().all() and no_stock.returns.empty
    no_rates = fd.run_des_study(panel.bonds, panel.equities, panel.accounts, panel.rates.iloc[:0], SMALL_CONFIG)
    assert missing_count(no_rates, "bond", "missing_curve") == 60
    assert no_rates.quintile_profile.empty


def test_a_price_error_in_the_signal_inflates_the_return_unless_entry_is_a_later_price():
    """Plan step 30: a price error enters both signal and return. entry_price stops that."""
    panel = make_panel(21, n_firms=30, n_months=10, price_noise=.02)
    with_entry = returns_of(run(panel, CONFIG), BOND_SIDE).gross.mean()
    without = fd.run_des_study(panel.bonds.drop(columns="entry_price"), panel.equities, panel.accounts, panel.rates, CONFIG)
    assert returns_of(without, BOND_SIDE).gross.mean() > .03
    assert abs(with_entry) < .005
    assert missing_count(without, "bond_entry", "same_price_in_signal_and_return") > 0


# ---------------------------------------------------------------- The input contract

@pytest.mark.parametrize("table, column", [("bonds", "full_price"), ("bonds", "coupon_paid"), ("equities", "shares_out"),
                                           ("accounts", "available_date"), ("rates", "tenor")])
def test_a_missing_column_is_refused_by_name(table, column):
    panel = small_panel()
    tables = dict(bonds=panel.bonds, equities=panel.equities, accounts=panel.accounts, rates=panel.rates)
    tables[table] = tables[table].drop(columns=column)
    with pytest.raises(ValueError, match=column):
        fd.run_des_study(tables["bonds"], tables["equities"], tables["accounts"], tables["rates"], SMALL_CONFIG)


def test_two_rows_for_one_bond_in_one_month_are_refused():
    panel = small_panel()
    with pytest.raises(ValueError, match="bond_id"):
        fd.run_des_study(pd.concat([panel.bonds, panel.bonds.iloc[:1]]), panel.equities, panel.accounts, panel.rates, SMALL_CONFIG)


def test_inputs_are_not_changed():
    panel = small_panel()
    before = [t.copy() for t in panel[:4]]
    run(panel)
    for was, now in zip(before, panel[:4]):
        pd.testing.assert_frame_equal(was, now)
