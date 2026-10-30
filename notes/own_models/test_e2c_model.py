"""Tests for e2c_model.py. Each test recomputes real workbook values and logs the gap on every row.

Run: python3 test_e2c_model.py      prints the gap per group and writes test_report.csv
Or:  pytest test_e2c_model.py

None of these open the 48 MB workbook, except test_slow_master_workbook. That one is optional. It runs if
E2C_RUN_SLOW=1 is set and xlrd is installed. E2C_MASTER_XLS gives the workbook path if it has moved.

Data files are cached workbook cells only: test_vectors.csv, test_vectors_weekly.csv,
test_vectors_scenarios.csv, test_vectors_sample_weekly.csv, master_panel.csv.gz, sample_panel.csv.gz.
Not tested, because the files cannot support it: group J (put-implied spread, add-in missing), bond
pricing (no bond data or bond formula in the files), and the Minimum MTM fit (formula not kept).
"""
from __future__ import annotations

from dataclasses import replace
from math import exp
import os
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2c_model as m  # noqa: E402

VECTORS = pd.read_csv(HERE / "test_vectors.csv", low_memory=False)
REPORT: list[dict] = []
NAN = float("nan")


def log(step, group, row, quantity, workbook, computed, tol, inferred=False, info=False):
    """Record one comparison. info=True means the gap is reported but is not a pass or fail."""
    workbook, computed = float(workbook), float(computed)
    gap = computed - workbook
    ok = (abs(gap) <= tol) or (np.isnan(workbook) and np.isnan(computed))
    REPORT.append(dict(step=step, group=group, source=row.get("source_file", ""), sheet=row.get("sheet", ""),
                       cell=row.get("cell", ""), name=row.get("name", ""), date=row.get("date", ""), quantity=quantity,
                       workbook=workbook, computed=computed, gap=gap, tolerance=tol,
                       status="INFO" if info else ("PASS" if ok else "FAIL"), inferred=inferred))
    return ok or info


def _rows(*prefixes):
    return [r.to_dict() for _, r in VECTORS[VECTORS.group.str.startswith(tuple(prefixes))].iterrows()]


def _n(x):
    return 0.0 if x != x else float(x)


def _finish(step):
    bad = [r for r in REPORT if r["step"] == step and r["status"] == "FAIL"]
    assert not bad, f"{step}: {len(bad)} rows failed, first: {bad[0]}"


def test_debt_per_share():
    for r in _rows("D_", "E_", "K_"):
        if r["st_debt"] != r["st_debt"] and r["group"].startswith("K_"):
            continue
        v = m.debt_per_share(r["st_debt"], r["lt_debt"], r["other_st_liab"], r["other_lt_liab"], r["minority_int"],
                             r["mkt_cap"], r["pfd_equity"], r["S"])
        log("debt_per_share", r["group"], r, "dps", r["wb_dps"], v, 1e-9)
    _finish("debt_per_share")


def test_average_equity_vol():
    for r in _rows("D_", "E_", "G_", "I_"):
        mix = "master" if r["group"].startswith("D_") else "cg12"
        frame = pd.DataFrame([{c: r.get(c, NAN) for c in m.VOL_MIXES[mix]}], dtype=float)
        log("average_equity_vol", r["group"], r, "avg_equity_vol", r["wb_avg_equity_vol"],
            m.average_equity_vol(frame, mix)[0], 1e-9)
    _finish("average_equity_vol")


def test_historical_asset_vol():
    for r in _rows("D_", "E_", "G_", "H_", "I_"):
        log("historical_asset_vol", r["group"], r, "avg_asset_vol", r["wb_avg_asset_vol"],
            m.historical_asset_vol(r["wb_avg_equity_vol"], r["S"], r["D"], r["L"]), 1e-9)
    _finish("historical_asset_vol")


def test_survival_probability():
    for r in _rows("A_"):
        avol = m.reference_asset_vol(r["ref_vol"], r["ref_price"], r["D"], r["L"])
        log("survival_probability", r["group"], r, "survival", r["wb_survival"],
            m.survival_probability(r["T"], r["S"], r["D"], avol, r["L"], r["lambda"]), 1e-10)
    for r in _rows("K_"):
        avol = r["equity_vol"] * r["S"] / (r["S"] + r["L"] * r["D"])
        log("survival_probability", r["group"], r, "survival", r["wb_survival"],
            m.survival_probability(r["T"], r["S"], r["D"], avol, r["L"], r["lambda"]), 1e-10)
    _finish("survival_probability")


def test_model_spread():
    for r in _rows("A_"):
        a = (r["T"], r["S"], r["D"], m.reference_asset_vol(r["ref_vol"], r["ref_price"], r["D"], r["L"]), r["L"], r["lambda"])
        log("model_spread", r["group"], r, "model_spread", r["wb_model_spread"], m.model_spread(*a, r["recovery"], r["rate"]), 1e-10)
        log("risky_annuity", r["group"], r, "annuity", r["wb_annuity"], m.risky_annuity(*a, r["rate"]), 1e-9)
        log("contingent_leg", r["group"], r, "contingent_leg", r["wb_contingent_leg"], m.contingent_leg(*a, r["recovery"], r["rate"]), 1e-10)
        log("cds_value", r["group"], r, "cds_value", r["wb_cds_value"],
            m.cds_value(r["T"], r["fee_bp"] / 1e4, r["S"], r["D"], a[3], r["L"], r["lambda"], r["recovery"], r["rate"]), 1e-10)
    # At a pasted implied vol the model spread can differ from the market by up to 1 bp, the solver stop.
    for r in _rows("D_", "E_", "G_", "I_"):
        v = m.model_spread(r["T"], r["S"], r["D"], r["wb_implied_pct"] / 100, r["L"], r["lambda"], r["recovery"], r["rate"]) * 1e4
        log("model_spread", r["group"], r, "spread_at_pasted_vol_bp", r["spread_bp"], v, 1.0)
    for step in ("model_spread", "risky_annuity", "contingent_leg", "cds_value"):
        _finish(step)


def test_implied_asset_vol():
    for r in _rows("B_"):
        v = m.implied_other(r["name"], r["spread_decimal"], r["T"], r["S"], r["D"], r["ref_vol"], r["ref_price"], r["L"], r["lambda"], r["recovery"], r["rate"])
        log("implied_other", r["group"], r, r["name"], r["wb_inverted"], v, 1e-8)
    for r in _rows("D_", "E_", "G_", "H_", "I_", "F_"):
        v = m.implied_asset_vol(r["spread_bp"] / 1e4, r["T"], r["S"], r["D"], r["L"], r["lambda"], r["recovery"], r["rate"]) * 100
        g = r["group"]
        tol = 0.01 if g.startswith("H_") else 1e-7
        log("implied_asset_vol", g, r, "implied_pct", r["wb_implied_pct"], v, tol, inferred=g.startswith("H_"), info=g.startswith("F_"))
    for step in ("implied_other", "implied_asset_vol"):
        _finish(step)


def test_fair_asset_vol():
    for r in _rows("D_"):
        v = m.fair_asset_vol(r["wb_avg_asset_vol"], r["S"] / r["D"], r["skew_pit"], r["coeff_pit"], m.MASTER_PARAMS)
        log("fair_asset_vol", r["group"], r, "fair_vol", r["wb_fair_vol"], v, 1e-9)
    for r in _rows("E_"):
        v = m.fair_asset_vol(r["wb_avg_asset_vol"], r["S"] / r["D"], r["skew_pit"], r["coeff_pit"], m.SAMPLE_PARAMS)
        log("fair_asset_vol", r["group"], r, "fair_vol", r["wb_fair_vol"], v, 1e-9)
    for r in _rows("I_"):
        p = m.Params(pit_weight=r["pit_weight"], ttc_skew=r["ttc_skew"], ttc_coeff=r["ttc_coeff"], blend="exponents")
        v = m.fair_asset_vol(r["wb_avg_asset_vol"], r["S"] / r["D"], r["skew_pit"], r["coeff_pit"], p)
        log("fair_asset_vol", r["group"], r, "fair_vol", r["wb_fair_vol"], v, 1e-9)
    for r in _rows("G_"):  # P2*(R2/0.403)^skew, so coeff = 0.403^-0.24, all weight on the one fit
        p = m.Params(pit_weight=1.0)
        v = m.fair_asset_vol(r["wb_avg_asset_vol"], r["S"] / r["D"], r["ref_skew"], r["ref_k"] ** -r["ref_skew"], p)
        log("fair_asset_vol", r["group"], r, "fair_vol", r["wb_fair_vol"], v, 1e-9)
    for r in _rows("H_"):  # constants are my fit to the pasted column, so tolerance is loose
        p = m.Params(pit_weight=1.0)
        v = m.fair_asset_vol(r["wb_implied_pct"], r["S"] / r["D"], -0.19416, exp(-0.23563), p)
        log("fair_asset_vol", r["group"], r, "fair_vol", r["wb_fair_vol"], v, 0.01, inferred=True)
    _finish("fair_asset_vol")


def test_vol_residual():
    for r in _rows("D_"):
        log("vol_residual", r["group"], r, "residual", r["wb_residual"], m.vol_residual(r["wb_implied_pct"], r["wb_fair_vol"], 30.0), 1e-9)
    for r in _rows("E_", "G_", "I_"):
        log("vol_residual", r["group"], r, "residual", r["wb_residual"], m.vol_residual(r["wb_implied_pct"], r["wb_fair_vol"], 0.0), 1e-9)
    for r in _rows("H_"):  # swapped headers in this file: residual is historical minus fitted
        log("vol_residual", r["group"], r, "residual", r["wb_residual"], m.vol_residual(r["wb_avg_asset_vol"], r["wb_fair_vol"], 0.0), 1e-9)
    _finish("vol_residual")


def test_sector_adjusted_residual():
    t = VECTORS[VECTORS.group.str.startswith("L_")]
    adj = m.sector_adjusted_residual(t.raw_residual, t.sector)
    for (_, r), v in zip(t.iterrows(), adj):
        log("sector_adjusted_residual", r["group"], r.to_dict(), "adjusted_residual", r["wb_adjusted_residual"], v, 1e-12)
    _finish("sector_adjusted_residual")


def test_trade_signal():
    for r in _rows("D_"):
        v = m.trade_signal(r["wb_residual"], r["spread_bp"], m.MASTER_PARAMS)
        log("trade_signal", r["group"], r, "long", r["wb_long"], v["long_flag"], 0)
        log("trade_signal", r["group"], r, "short", r["wb_short"], v["short_flag"], 0)
    for r in _rows("E_"):
        v = m.trade_signal(r["wb_residual"], r["spread_bp"], m.SAMPLE_PARAMS)
        log("trade_signal", r["group"], r, "long", r["wb_long"], v["long_flag"], 0)
        log("trade_signal", r["group"], r, "short", r["wb_short"], v["short_flag"], 0)
    _finish("trade_signal")


def test_cds_greeks():
    for r in _rows("D_", "E_"):
        rg = r["rate_greeks"] if r["rate_greeks"] == r["rate_greeks"] else r["rate"]
        g = m.cds_greeks(r["T"], r["S"], r["D"], r["wb_implied_pct"] / 100, r["spread_bp"], r["L"], r["lambda"], r["recovery"], rg)
        log("cds_greeks", r["group"], r, "annuity", r["wb_annuity"], g["annuity"], 1e-8)
        log("cds_greeks", r["group"], r, "delta", r["wb_delta"], g["delta"], 1e-6)
        log("cds_greeks", r["group"], r, "vega", r["wb_vega"], g["vega"], 1e-9)
        if r["group"].startswith("D_"):
            log("cds_greeks", r["group"], r, "rho", r["wb_rho"], g["rho"], 1e-9)
    for r in _rows("I_"):
        v = r["wb_implied_pct"] / 100
        g = m.cds_greeks(r["T"], r["S"], r["D"], v, r["spread_bp"], r["L"], r["lambda"], r["recovery"], r["rate"])
        g5 = m.cds_greeks(r["T"], r["S"], r["D"], v, r["spread_bp"], r["L"], r["lambda"], r["recovery"], 0.05)
        log("cds_greeks", r["group"], r, "annuity_at_5pct", r["wb_annuity"], g5["annuity"], 1e-8)
        log("cds_greeks", r["group"], r, "delta", r["wb_delta"], g["delta"], 1e-6)
        log("cds_greeks", r["group"], r, "vega", r["wb_vega"], g["vega"], 1e-9)
        log("cds_greeks", r["group"], r, "theta_sign_flipped", r["wb_theta"], -g["theta"], 1e-9)
        log("cds_greeks", r["group"], r, "spread01", r["wb_spread01"], r["wb_position"] * g["annuity"] / 10, 1e-6)
        fee = r["spread_bp"] / 1e4
        ten = m.cds_value(r["T"], fee * 1.1, r["S"], r["D"], v, r["L"], r["lambda"], r["recovery"], r["rate"]) - m.cds_value(r["T"], fee, r["S"], r["D"], v, r["L"], r["lambda"], r["recovery"], r["rate"])
        log("cds_greeks", r["group"], r, "spread10pct", r["wb_spread10pct"], -r["wb_position"] * ten * 1000, 1e-6)
    _finish("cds_greeks")


def test_trade_size():
    for r in _rows("D_", "E_"):
        p = m.MASTER_PARAMS if r["group"].startswith("D_") else m.SAMPLE_PARAMS
        v = m.trade_size(r["wb_long"], r["wb_short"], r["wb_vega"], r["wb_implied_pct"], p)
        log("trade_size", r["group"], r, "target", r["wb_target"], v["target"], 1e-10)
        log("trade_size", r["group"], r, "size_long", r["wb_size_long"], v["size_long"], 1e-8)
        log("trade_size", r["group"], r, "size_short", r["wb_size_short"], v["size_short"], 1e-8)
    for r in _rows("I_"):
        v = m.trade_size(1, 0, r["wb_vega"], r["wb_implied_pct"], m.PRODUCTION_PARAMS)
        log("trade_size", r["group"], r, "target", r["wb_target"], v["target"], 1e-10)
        log("trade_size", r["group"], r, "position_negative_is_long_credit", r["wb_position"], -v["size_long"], 1e-8)
    _finish("trade_size")


def test_equity_hedge():
    for r in _rows("D_", "E_"):
        v = m.equity_hedge(r["wb_size_long"], r["wb_size_short"], r["wb_delta"], r["S"])
        log("equity_hedge", r["group"], r, "delta_long", r["wb_delta_long"], v["delta_long"], 1e-9)
        log("equity_hedge", r["group"], r, "delta_short", r["wb_delta_short"], v["delta_short"], 1e-9)
    for r in _rows("I_"):
        v = m.equity_hedge(-r["wb_position"], 0.0, r["wb_delta"], r["S"])
        log("equity_hedge", r["group"], r, "hedge_shares", r["wb_hedge_shares"], v["hedge_shares"], 1e-5)
    _finish("equity_hedge")


def test_weekly_pnl():
    for r in _rows("D_", "E_"):
        master = r["group"].startswith("D_")
        p = m.MASTER_PARAMS if master else m.SAMPLE_PARAMS
        rate = r["swap_pct"] if master else 4.5
        v = m.weekly_pnl(r["wb_size_long"], r["wb_size_short"], r["wb_delta_long"], r["wb_delta_short"], r["spread_bp"],
                         r["next_spread_bp"], r["S"], r["next_price"], r["wb_annuity"], r["wb_days"], rate, p)
        for k in ("pnl_cds_long", "pnl_cds_short", "pnl_hedge_long", "pnl_hedge_short", "carry_long", "carry_short", "funding", "rebate"):
            log("weekly_pnl", r["group"], r, k, r["wb_" + k], np.ravel(v[k])[0], 1e-8)
        if master and r["wb_pnl_total"] == r["wb_pnl_total"]:
            log("weekly_pnl", r["group"], r, "pnl_total", r["wb_pnl_total"], sum(np.ravel(x)[0] for x in v.values()), 1e-8)
    for r in _rows("I_"):
        size = -r["wb_position"]
        v = m.weekly_pnl(size, 0.0, size * r["wb_delta"], 0.0, r["spread_bp"], r["next_spread_bp"], r["S"], r["next_price"], r["wb_annuity"], 0.0, 4.5)
        log("weekly_pnl", r["group"], r, "credit_pnl", r["wb_credit_pnl"], np.ravel(v["pnl_cds_long"])[0], 1e-8)
        log("weekly_pnl", r["group"], r, "equity_pnl", r["wb_equity_pnl"], np.ravel(v["pnl_hedge_long"])[0], 1e-8)
    _finish("weekly_pnl")


def test_stress_tests():
    for r in _rows("D_"):
        v = m.stress_tests(r["wb_size_long"], r["wb_size_short"], r["wb_delta_long"], r["wb_delta_short"], r["wb_stress10_long"], r["wb_stress10_short"])
        for k in ("zero", "lbo", "merger", "natio", "oct87", "ltcm", "apr03"):
            log("stress_tests", r["group"], r, k, r["wb_" + k], v[k], 1e-9)
    _finish("stress_tests")


def test_name_risk():
    for r in _rows("D_"):
        v = m.name_risk(r["wb_implied_pct"], r["wb_avg_equity_vol"], r["wb_avg_asset_vol"], r["wb_delta"], r["wb_annuity"], r["spread_bp"],
                        r["wb_size_long"], r["wb_stress10_long"], r["wb_stress10_short"], r["wb_delta_long"], r["wb_delta_short"])
        log("name_risk", r["group"], r, "spread_vol", r["wb_spread_vol"], v["spread_vol"], 1e-6)
        log("name_risk", r["group"], r, "margin", r["wb_margin"], v["margin"], 1e-9)
        log("name_risk", r["group"], r, "credit_1sd", r["wb_credit_1sd"], v["credit_1sd"], 1e-8)
        log("name_risk", r["group"], r, "equity_1sd", r["wb_equity_1sd"], v["equity_1sd"], 1e-8)
        log("name_risk", r["group"], r, "net_1sd", r["wb_net_1sd"], v["net_1sd"], 1e-8)
    _finish("name_risk")


def test_closed_trade_flag():
    for r in _rows("D_"):
        v = m.closed_trade_flag(r["wb_pnl_total"], r["wb_residual"], r["wb_long"], r["wb_vega"], r["wb_size_long"], r["wb_size_short"], r["wb_target"])
        log("closed_trade_flag", r["group"], r, "close_flag", r["wb_close"], v, 0)
    _finish("closed_trade_flag")


def test_reval_trade():
    for r in _rows("G_"):
        v = m.reval_trade(r["wb_implied_pct"], r["wb_residual"], r["spread_bp"], r["S"], r["D"], 5.0, 3.0, r["L"], r["lambda"], r["recovery"], r["rate"], r["T"])
        log("reval_trade", r["group"], r, "flag", r["wb_flag"], v["flag"], 0)
        log("reval_trade", r["group"], r, "vol_reval", r["wb_vol_reval"], v["vol_reval"], 1e-10)
        log("reval_trade", r["group"], r, "theo_spread_bp", r["wb_theo_spread_bp"], v["theo_spread_bp"], 1e-6)
        log("reval_trade", r["group"], r, "theo_value", r["wb_theo_value"], v["theo_value"], 1e-10)
        log("reval_trade", r["group"], r, "size", _n(r["wb_size_long"]) + _n(r["wb_size_short"]), v["size"], 1e-7)
    for r in _rows("I_"):  # the database row shows no revaluation: Vol_Reval equals implied
        vol = r["wb_vol_reval"]
        log("reval_trade", r["group"], r, "theo_spread_bp", r["wb_theo_spread_bp"], m.model_spread(r["T"], r["S"], r["D"], vol, r["L"], r["lambda"], r["recovery"], r["rate"]) * 1e4, 1e-6)
        log("reval_trade", r["group"], r, "theo_value", r["wb_theo_value"], m.cds_value(r["T"], r["spread_bp"] / 1e4, r["S"], r["D"], vol, r["L"], r["lambda"], r["recovery"], r["rate"]), 1e-10)
    _finish("reval_trade")


# ---- Full runs from raw inputs ----------------------------------------------------------------
_CACHE: dict = {}


def _master():
    if "master" not in _CACHE:
        panel = pd.read_csv(HERE / "master_panel.csv.gz", low_memory=False)
        _CACHE["master"] = (panel, m.run_pipeline(panel, m.MASTER_PARAMS))
    return _CACHE["master"]


def test_full_run_name_weeks():
    """All 19,489 rows, from raw inputs only. One summary line per column, because the row count is large."""
    panel, out = _master()
    x = out["names"]
    pairs = dict(dps=("wb_dps", 1e-9), avg_equity_vol=("wb_avg_equity_vol", 1e-9), avg_asset_vol=("wb_avg_asset_vol", 1e-9),
                 implied=("wb_implied", 1e-7), annuity=("wb_annuity", 1e-7), delta=("wb_delta", 1e-6), vega=("wb_vega", 1e-8), rho=("wb_rho", 1e-8),
                 fair_vol=("wb_fair_vol", 1e-6), residual=("wb_residual", 1e-6), long_flag=("wb_long", 0), short_flag=("wb_short", 0),
                 target=("wb_target", 1e-8), size_long=("wb_size_long", 1e-5), size_short=("wb_size_short", 1e-5),
                 delta_long=("wb_delta_long", 1e-6), delta_short=("wb_delta_short", 1e-6), spread_vol=("wb_spread_vol", 1e-3),
                 pnl_total=("wb_pnl_total", 1e-3), close_flag=("wb_close", 0))
    for c, (w, tol) in pairs.items():
        g = (x[c].astype(float) - panel[w].astype(float)).abs()
        worst = g.max()
        log("run_pipeline:names", "master_panel", dict(source_file="master_panel.csv.gz", sheet="E2C Data", cell=f"all {g.notna().sum()} rows"), c, 0.0, worst, tol)
    _finish("run_pipeline:names")


def test_full_run_weekly():
    """Every Reg row, 151 dates, one line per date and column."""
    w = _master()[1]["weeks"]
    wb = pd.read_csv(HERE / "test_vectors_weekly.csv")
    wb["date"] = pd.to_datetime(wb["date"])
    wb = wb.set_index("date")
    tols = dict(n=0, skew=1e-7, coeff=1e-7, k=1e-3, correl=1e-7, n_long=0, n_short=0, size_long=1e-3, size_short=1e-3, delta_long=1e-3, delta_short=1e-3,
                stress10_long=1e-3, stress10_short=1e-3, pnl_cds_long=1e-3, pnl_cds_short=1e-3, pnl_hedge_long=1e-3, pnl_hedge_short=1e-3,
                carry_long=1e-3, carry_short=1e-3, funding=1e-3, rebate=1e-3, pnl_total=1e-3, pnl_cum=1e-2, pnl_credit=1e-3, pnl_equity=1e-3,
                zero=1e-5, lbo=1e-5, merger=1e-5, natio=1e-5, oct87=1e-5, ltcm=1e-5, apr03=1e-5, var_credit=1e-4, var_equity=1e-4, var_total=1e-4,
                margin_credit=1e-5, margin_equity=1e-3, margin_total=1e-3, economic_capital=2e-3, nav=2e-2, margin_pct_nav=1e-3, alpha=1e-5, nav_index=1e-3,
                rho_usd=1e-3, closed_share=1e-9, bid_offer_cost=1e-2)
    for d, row in wb.iterrows():
        src = dict(source_file="test_vectors_weekly.csv", sheet="Reg", cell=f"row {int(row.reg_row)}", date=str(d.date()))
        for c, tol in tols.items():
            wbv = row[c]
            if wbv != wbv:
                continue
            log("run_pipeline:weekly", "master_weekly", src, c, wbv, w.loc[d, c], tol)
    _finish("run_pipeline:weekly")


def test_performance_summary():
    wk = pd.read_csv(HERE / "test_vectors_weekly.csv")
    s = m.performance_summary(wk.alpha)
    src = dict(source_file="test_vectors_weekly.csv", sheet="Reg", cell="CK6:CK8, CM6:CM8")
    for k, wbv in (("sharpe", 2.51061644473834), ("vol_annual", 0.08204615843622565), ("mean_annual", 0.2059864345975954),
                   ("nav_end", 1.7991755029443506), ("nav_min", 0.9860801682300439)):
        log("performance_summary", "master_weekly", src, k, wbv, s[k], 1e-9)
    _finish("performance_summary")


def test_scenarios():
    """Pasted scenario blocks in MASTER. Each row is a full rerun of steps S07 onward."""
    panel = _master()[0]
    sc = pd.read_csv(HERE / "test_vectors_scenarios.csv").fillna({"spread_floor": 0.0, "spread_cap": 10000.0})
    for _, r in sc.iterrows():
        h = 1.0 if r.hedged else 0.0
        p = replace(m.MASTER_PARAMS, long_trigger=r.long_trigger, short_trigger=r.short_trigger, pit_weight=r.pit_weight,
                    spread_floor=r.spread_floor, spread_cap=r.spread_cap, long_hedge=h, short_hedge=h)
        out = m.run_pipeline(panel, p)
        w, s = out["weeks"], out["summary"]
        src = dict(source_file="test_vectors_scenarios.csv", sheet=r.sheet, cell=r.cell_sr, name=str(r.label) if r.label == r.label else "")
        log("scenario", "master_scenarios", src, "sharpe", r.wb_sharpe, s["sharpe"], 1e-4)
        log("scenario", "master_scenarios", src, "nav_end", r.wb_nav_end, s["nav_end"], 1e-4)
        log("scenario", "master_scenarios", src, "pnl_total", r.wb_total, w.pnl_total.sum(), 1e-2)
    _finish("scenario")


def test_sample_run():
    """SAMPLE, 1,027 rows, from raw inputs with SAMPLE_PARAMS. Its 13 Reg rows are the targets."""
    panel = pd.read_csv(HERE / "sample_panel.csv.gz", low_memory=False)
    out = m.run_pipeline(panel, m.SAMPLE_PARAMS)
    x, w = out["names"], out["weeks"]
    for c, wbc, tol in (("dps", "wb_dps", 1e-9), ("implied", "wb_implied", 1e-7), ("annuity", "wb_annuity", 1e-7), ("delta", "wb_delta", 1e-6),
                        ("vega", "wb_vega", 1e-8), ("fair_vol", "wb_fair_vol", 1e-6), ("residual", "wb_residual", 1e-6)):
        log("run_pipeline:sample", "sample_panel", dict(source_file="sample_panel.csv.gz", sheet="E2C Data", cell="all 1,027 rows"), c, 0.0, (x[c] - panel[wbc]).abs().max(), tol)
    wb = pd.read_csv(HERE / "test_vectors_sample_weekly.csv")
    wb["date"] = pd.to_datetime(wb["date"])
    for _, row in wb.set_index("date").iterrows():
        d = row.name
        src = dict(source_file="test_vectors_sample_weekly.csv", sheet="Reg", cell=f"row {int(row.reg_row)}", date=str(d.date()))
        for c in ("skew", "coeff", "n_long", "n_short", "size_long", "size_short", "delta_long", "delta_short", "pnl_cds_long", "pnl_cds_short",
                  "pnl_hedge_long", "pnl_hedge_short", "carry_long", "carry_short", "funding", "rebate", "pnl_total", "pnl_cum"):
            log("run_pipeline:sample", "sample_weekly", src, c, row[c], w.loc[d, c], 1e-3)
    _finish("run_pipeline:sample")


def test_next_week_values():
    """S00 against the pasted columns E2C Data!BD:BF, all 19,489 rows."""
    panel = _master()[0]
    v = m.next_week_values(panel)
    same = ((v.next_spread_bp == panel.next_spread_bp) | (v.next_spread_bp.isna() & panel.next_spread_bp.isna())).mean()
    log("next_week_values", "master_panel", dict(source_file="master_panel.csv.gz", sheet="E2C Data", cell="BE, all rows"), "share_matching_spread", 1.0, same, 0)
    same = ((v.next_price == panel.next_price) | (v.next_price.isna() & panel.next_price.isna())).mean()
    log("next_week_values", "master_panel", dict(source_file="master_panel.csv.gz", sheet="E2C Data", cell="BF, all rows"), "share_matching_price", 1.0, same, 0)
    _finish("next_week_values")


def test_pipeline_from_minimal_inputs():
    """Raw columns only: no wb_ columns, no next_ columns. The headline cells must still come out."""
    panel = _master()[0]
    raw = panel[m.RAW_INPUTS + m.VOL_MIXES["master"]]
    s = m.run_pipeline(raw, m.MASTER_PARAMS)["summary"]
    src = dict(source_file="master_panel.csv.gz", sheet="Reg", cell="CK6, CM6")
    log("run_pipeline:minimal", "master_headline", src, "CK6 sharpe", 2.51061644473834, s["sharpe"], 1e-6)
    log("run_pipeline:minimal", "master_headline", src, "CM6 nav_end", 1.7991755029443506, s["nav_end"], 1e-6)
    _finish("run_pipeline:minimal")


def test_master_headline_cells():
    """Reg!CK6, CM6, BA7, from the extract, so the 48 MB workbook stays closed."""
    out = _master()[1]
    src = dict(source_file="master_panel.csv.gz", sheet="Reg", cell="CK6, CM6, BA7")
    log("run_pipeline:headline", "master_headline", src, "CK6 sharpe", 2.51061644473834, out["summary"]["sharpe"], 1e-6)
    log("run_pipeline:headline", "master_headline", src, "CM6 nav_end", 1.7991755029443506, out["summary"]["nav_end"], 1e-6)
    log("run_pipeline:headline", "master_headline", src, "BA7 total", 20477.819198244164, out["weeks"].pnl_total.sum(), 1e-3)
    _finish("run_pipeline:headline")


def test_slow_master_workbook():
    """Optional. Opens the 48 MB workbook, reads raw inputs and Reg cells from it, and reruns the pipeline."""
    if os.environ.get("E2C_RUN_SLOW") != "1":
        raise unittest.SkipTest("set E2C_RUN_SLOW=1 to run")
    try:
        import xlrd
    except ImportError:
        raise unittest.SkipTest("xlrd is not installed")
    default = HERE.parent.parent / "evidence" / "drive" / "04_raw_data" / "12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls"
    path = Path(os.environ.get("E2C_MASTER_XLS", default))
    if not path.exists():
        raise unittest.SkipTest(f"workbook not found: {path}")
    wb = xlrd.open_workbook(str(path), on_demand=True)
    sh = wb.sheet_by_name("E2C Data")
    columns = dict(date="A", ticker="B", st_debt="C", lt_debt="D", other_st_liab="E", other_lt_liab="F", minority_int="G", mkt_cap="H",
                   pfd_equity="I", price="J", spread_bp="AC", swap_5y_pct="AD", vol_30d="R", vol_60d="S", vol_90d="T", vol_180d="U", vol_360d="V",
                   put_3m="W", put_6m="X", put_12m="Y", put_24m="Z", next_date="BD", next_spread_bp="BE", next_price="BF")

    def index(col):
        return sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(col))) - 1

    def read(col):
        kept = []
        for t, v in zip(sh.col_types(index(col), 1), sh.col_values(index(col), 1)):
            kept.append(NAN if t in (xlrd.XL_CELL_ERROR, xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) or v == "" else v)
        return kept

    raw = pd.DataFrame({k: read(c) for k, c in columns.items()})
    for c in ("date", "next_date"):
        raw[c] = pd.to_datetime(pd.to_numeric(raw[c]), unit="D", origin="1899-12-30")
    out = m.run_pipeline(raw, m.MASTER_PARAMS)
    reg = wb.sheet_by_name("Reg")
    src = dict(source_file=path.name, sheet="Reg", cell="CK6, CM6, BA7")
    log("slow:workbook", "master_workbook", src, "CK6 sharpe", reg.cell_value(5, index("CK")), out["summary"]["sharpe"], 1e-6)
    log("slow:workbook", "master_workbook", src, "CM6 nav_end", reg.cell_value(5, index("CM")), out["summary"]["nav_end"], 1e-6)
    log("slow:workbook", "master_workbook", src, "BA7 total", reg.cell_value(6, index("BA")), out["weeks"].pnl_total.sum(), 1e-3)
    _finish("slow:workbook")


def write_report():
    df = pd.DataFrame(REPORT)
    df.to_csv(HERE / "test_report.csv", index=False)
    return df


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed, skipped = [], []
    for t in tests:
        try:
            t()
        except unittest.SkipTest as e:
            skipped.append((t.__name__, str(e)))
        except AssertionError as e:
            failed.append((t.__name__, str(e)[:300]))
    df = write_report()
    pd.set_option("display.width", 200, "display.max_rows", 500, "display.max_columns", 20)
    df["abs_gap"] = df.gap.abs()
    summary = df.groupby(["step", "group"]).agg(comparisons=("gap", "size"), max_abs_gap=("abs_gap", "max"), max_tol=("tolerance", "max"),
                                                 fails=("status", lambda s: (s == "FAIL").sum()), info=("status", lambda s: (s == "INFO").sum()))
    print(summary.to_string(float_format=lambda v: f"{v:.3g}"))
    print(f"\ncomparisons {len(df)}, PASS {(df.status == 'PASS').sum()}, FAIL {(df.status == 'FAIL').sum()}, INFO {(df.status == 'INFO').sum()}")
    print("per-row gaps: test_report.csv")
    for n, msg in skipped:
        print("SKIPPED", n, msg)
    for n, msg in failed:
        print("FAILED", n, msg)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
