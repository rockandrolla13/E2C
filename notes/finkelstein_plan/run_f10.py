"""F10 in one command: real tables in, verdict and tables out. See F10.md.

    export E2C_DATA_ROOT=/path/to/tables     # or E2C_SOURCE=your_package.module:make_source
    python run_f10.py --start 2002-01-01 --end 2021-12-31 --out results

Exit code: 0 after a run, whatever its verdict. 2 if the contract check stops it. Reports hold counts and aggregates, no data rows.
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

import fk_des as fd
import fk_f10 as f
from e2c_data.contract import check_source, failures
from e2c_data.factory import open_source
from e2c_data.source import DataUnavailable
from e2c_data.tables import TableSource  # noqa: F401  for callers holding a folder
from e2c_data.view import PointInTimeView
from inputs import build_vintage_inputs as _build

log = logging.getLogger("run_f10")
COMPOUNDINGS = {"continuous": None, "semiannual": 2}
VINTAGE_NOTE = "Every price, link, term and rate is taken as known at the end of its own month, so a later correction cannot reach an earlier sort."


class ContractFailed(RuntimeError):
    pass


class CompoundingRun(NamedTuple):
    verdict: f.Verdict
    premium: float
    premium_t: float
    stock_premium: float
    stock_t: float
    months: int
    median_firms: float
    gaps: tuple
    ratios: tuple
    net_large: float


class Report(NamedTuple):
    overall: str
    runs: dict
    forced: bool


def vintage_inputs(source, start, end, decision_time, liquidity=False):
    return _build(source, start, end, decision_time, liquidity)


def _window(series: pd.DataFrame, window: tuple) -> pd.DataFrame:
    return series[(series.month >= pd.Period(window[0], "M")) & (series.month <= pd.Period(window[1], "M"))]


def _bond_costs(day_costs: pd.DataFrame, screen: pd.DataFrame, settings: f.F10Settings) -> tuple:
    """Round-trip cost for large and small bonds, and where they came from."""
    if settings.bond_cost is not None:
        return settings.bond_cost, settings.bond_cost, "given on the command line"
    if not day_costs.empty and "is_customer_buy" in day_costs:
        costs = f.bond_day_costs(day_costs)
        if not costs.empty:
            sized = screen.assign(month=pd.to_datetime(screen.date).dt.to_period("M"), asset_id=screen.bond_id, value=screen.amount_out)
            labels = f.median_split(sized, "large", "small")
            c = costs.assign(month=pd.to_datetime(costs.day).dt.to_period("M")).merge(labels, left_on=["month", "bond_id"], right_on=["month", "asset_id"])
            by = c.groupby("label").cost.median()
            if {"large", "small"} <= set(by.index):
                return float(by["large"]), float(by["small"]), "measured from customer buy less sell, median bond-day"
    return f.PLAN_COST_LARGE, f.PLAN_COST_SMALL, "planning cost, not measured (Cao et al., 18 and 68 bp, plan T0)"


def _financing_rates(financing: pd.DataFrame, hedges: pd.DataFrame, leg: str) -> pd.DataFrame:
    if leg == "bond":
        return financing.rename(columns={"repo_rate": "repo", "bond_fee": "fee"})[["month", "asset_id", "repo", "fee"]]
    cash = hedges.assign(month=hedges.month - 1).set_index("month").repo
    return financing.assign(repo=financing.month.map(cash), fee=financing.stock_fee)[["month", "asset_id", "repo", "fee"]]


def _leg_tables(study, bonds_table, panel, config):
    bond_holdings, stock_holdings = f.holdings_from_study(study)
    return {"bond": (bond_holdings, fd.bond_month_returns(bonds_table), config.n_groups, 1),
            "stock": (stock_holdings, fd.stock_month_returns(panel, config.execution_lag_days), 1, config.n_groups)}


def _monthly_lines(study, legs, durations, hedges, financing, min_coverage=.9) -> pd.DataFrame:
    """fk_des's monthly return, with the financing drag and, for bonds, the overlay beside it."""
    frames = []
    for (leg, hold, weighting), g in study.returns.groupby(["leg", "hold", "weighting"]):
        holdings, rets, top, bottom = legs[leg]
        w = f.book_weights(holdings, rets, top, bottom, hold, weighting)
        drag = f.financing_drag(w, _financing_rates(financing, hedges, leg), min_coverage) if not financing.empty else pd.DataFrame(columns=["drag"])
        over = f.overlay_series(w, durations, hedges, min_coverage) if leg == "bond" else pd.DataFrame(columns=["overlay"])
        g = g.assign(financing=g.month.map(drag.drag) if len(drag) else np.nan, overlay=g.month.map(over.overlay) if len(over) else np.nan)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["leg", "hold", "weighting", "month", "gross", "cost", "net", "financing", "overlay"])


def _summary_rows(lines: pd.DataFrame, target, settings, compounding: str) -> list:
    rows = []
    for (leg, hold, weighting), g in lines.groupby(["leg", "hold", "weighting"]):
        for name, part in (("published window", _window(g, target.window)), ("whole run", g)):
            e = f.newey_west(part.gross, settings.nw_lags)
            rows.append(dict(compounding=compounding, leg=leg, hold=hold, weighting=weighting, sample=name, months=e.n, gross_annual=12 * e.mean, t=e.t,
                             net_annual=12 * part.net.mean(), financing_annual=12 * part.financing.mean(), overlay_annual=12 * part.overlay.mean()))
    return rows


def _split_rows(legs, screen, financing, target, settings, compounding, cost_large, cost_small, stock_cost) -> tuple:
    """Hold 1, value-weighted. Returns rows, and a note for each split that has no data."""
    rows, notes = [], []
    sized = screen.assign(month=pd.to_datetime(screen.date).dt.to_period("M"), asset_id=screen.bond_id, value=screen.amount_out)
    plans = [("bond", "size", f.median_split(sized, "large", "small"), dict(large=cost_large, small=cost_small))]
    for leg, column in (("bond", "bond_fee"), ("stock", "stock_fee")):
        have = financing.dropna(subset=[column]) if column in financing else pd.DataFrame()
        if have.empty:
            notes.append(f"{leg} fee split: not available, no {column} in the data")
            continue
        cost = (cost_large + cost_small) / 2 if leg == "bond" else stock_cost
        plans.append((leg, "fee", f.median_split(have.assign(value=have[column]), "high", "low"), dict(high=cost, low=cost)))
    for leg, split, labels, costs in plans:
        holdings, rets, top, bottom = legs[leg]
        marked = holdings.merge(labels, on=["month", "asset_id"])
        for label, cost in costs.items():
            part = marked[marked.label == label][["month", "asset_id", "group"]]
            t0 = fd.t0_returns(part, rets, top, bottom, 1, "value", cost)
            t0 = _window(t0, target.window) if len(t0) else t0
            e = f.newey_west(t0.gross if len(t0) else [], settings.nw_lags)
            rows.append(dict(compounding=compounding, leg=leg, split=split, label=label, months=e.n, gross_annual=12 * e.mean, t=e.t, round_trip_cost=cost,
                             net_annual=12 * t0.net.mean() if len(t0) else np.nan))
    return rows, notes


def _analyse(compounding, freq, bonds, equities, accounts, rates, screen, financing, durations, hedges, costs, stock_cost, settings, target):
    large, small, _ = costs
    config = settings.config._replace(yield_freq=freq, bond_round_trip_cost=(large + small) / 2, stock_round_trip_cost=stock_cost)
    study = fd.run_des_study(bonds, equities, accounts, rates, config)
    legs = _leg_tables(study, fd._with_month(fd._dated(bonds, "date")), fd.equity_panel(fd._dated(equities, "date")), config) if len(study.returns) else None
    lines = _monthly_lines(study, legs, durations, hedges, financing) if legs else pd.DataFrame(columns=["leg", "hold", "weighting", "month", "gross", "cost", "net", "financing", "overlay"])
    base = lambda leg: _window(lines[(lines.leg == leg) & (lines.hold == 1) & (lines.weighting == "value")], target.window)
    bond, stock = f.newey_west(base("bond").gross, settings.nw_lags), f.newey_west(base("stock").gross, settings.nw_lags)
    sorts = _window(study.sort_report, target.window) if len(study.sort_report) else study.sort_report
    firms = _window(study.firm_des.dropna(subset=["quintile"]), target.window)
    profile = fd._quintile_profile(firms).set_index("quintile") if len(firms) else pd.DataFrame(columns=["des_bp", "price_ratio"])
    q = lambda col, n: float(profile[col].get(n, np.nan)) if len(profile) else np.nan
    gaps, ratios = (q("des_bp", 1), q("des_bp", config.n_groups)), (q("price_ratio", 1), q("price_ratio", config.n_groups))
    median_firms = float(sorts.n_valid.median()) if len(sorts) else float("nan")
    verdict = f.judge(bond.n, median_firms, gaps[0], gaps[1], ratios[0], ratios[1], 12 * bond.mean, bond.t, 12 * stock.mean,
                      settings.min_months, settings.min_firms, settings.min_t)
    split_rows, notes = _split_rows(legs, screen, financing, target, settings, compounding, large, small, stock_cost) if legs else ([], [])
    net_large = next((r["net_annual"] for r in split_rows if r["split"] == "size" and r["label"] == "large"), float("nan"))
    run = CompoundingRun(verdict, 12 * bond.mean, bond.t, 12 * stock.mean, stock.t, bond.n, median_firms, gaps, ratios, net_large)
    profile_out = profile.reset_index().assign(compounding=compounding)
    missing = study.missing.assign(compounding=compounding)
    return run, lines.assign(compounding=compounding), _summary_rows(lines, target, settings, compounding), split_rows, notes, profile_out, missing


def _text(report, target, settings, cost_note, screens, contract, counts, stock_cost, notes, vintage, start, end, decision, flags) -> str:
    out = ["F10: Chen, Chen and Li (2026) on this sample. Plan's rule: signs must match, sizes as shape if samples differ.",
           f"Run {start.date()} to {end.date()}, decision time {decision}. Published window {target.window[0]} to {target.window[1]}.", ""]
    if report.forced:
        out += ["FORCED: this run went past failed contract checks. Do not rely on it.", ""]
    out += [f"VERDICT: {report.overall}", ""]
    for name, run in report.runs.items():
        out += [f"{name} yields: {run.verdict.verdict}. {run.verdict.reason}.",
                f"  Bond premium, value-weighted, 1-month hold, gross. Published {target.premium:.2%} t={target.premium_t}. Replicated {run.premium:.2%} t={run.premium_t:.2f}. "
                f"Gap {run.premium - target.premium:+.2%}. Months {run.months}.",
                f"  Stock premium. Published {target.stock_premium:.2%} t={target.stock_premium_t}, 1980 to 2022. Replicated {run.stock_premium:.2%} t={run.stock_t:.2f}.",
                f"  Q1 and Q5 gap, bp. Published {target.gaps[0]:.0f} and {target.gaps[1]:.0f}. Replicated {run.gaps[0]:.0f} and {run.gaps[1]:.0f}.",
                f"  Q1 and Q5 price ratio. Published {target.ratios[0]} and {target.ratios[1]}. Replicated {run.ratios[0]:.3f} and {run.ratios[1]:.3f}.",
                f"  Median firms sorted a month: {run.median_firms:.0f}.",
                f"  Stop rule, net large-bond return {run.net_large:.2%} a year: {f.stop_rule(run.net_large)}.", ""]
    out += [f"Context: the full-sample published bond premium is {target.full_premium:.2%} t={target.full_premium_t}, 1980 to 2022. No copy of the paper was on hand, so its screens and standard errors are not known here.",
            f"t-statistics: Newey-West, {settings.nw_lags} lags. The plan states no method, so this is my choice.",
            f"Bond cost: {cost_note}. Stock round-trip cost: {stock_cost if stock_cost == stock_cost else 'none measured or given, so stock net is blank'}.",
            VINTAGE_NOTE + " Accounts keep every version and are picked by date.",
            f"Months read: {vintage.months}.", "",
            "Dead names: " + ", ".join(f"{k}={v}" for k, v in counts.items()) + ". Without these a name that stops pricing is left out of that month, which can flatter the book."]
    out += notes
    out += flags
    out += ["", "Screens, bond-months tested and removed:"]
    out += [f"  {s.screen}: tested {s.tested}, removed {s.removed}" + (f", NOT APPLIED for {s.not_applied}" if s.not_applied else "") for s in screens.itertuples()]
    warn = contract[contract.level == "warn"]
    fails = contract[(contract.level == "required") & ~contract.passed]
    out += ["", "Contract warnings, count of rows or names:"]
    out += [f"  {w.check} / {w.kind}: {w.count} {w.note}".rstrip() for w in warn.itertuples()] or ["  none"]
    if len(fails):
        out += ["Contract failures:"] + [f"  {w.check} / {w.kind}: {w.count} {w.note}".rstrip() for w in fails.itertuples()]
    out += ["", "Tables in this folder: summary_table.csv, monthly_returns.csv, quintile_profile.csv, splits.csv, screens.csv, contract.csv, missing.csv."]
    return "\n".join(out) + "\n"


def run(source, start, end, decision_time, out, settings: f.F10Settings = f.F10Settings(), target: f.F10Target = f.F10Target(), force: bool = False) -> Report:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    start, end, decision = pd.Timestamp(start), pd.Timestamp(end), pd.Timestamp(decision_time)
    contract = check_source(source, decision)
    contract.to_csv(out / "contract.csv", index=False)
    bad = failures(contract)
    if len(bad) and not force:
        names = ", ".join(f"{r.check}/{r.kind} ({r.count})" for r in bad.itertuples())
        raise ContractFailed(f"required contract checks failed: {names}. See contract.csv, or pass --force.")

    v = _build(source, start, end, decision, settings.liquidity_screen)
    bonds, equities = v.inputs.bonds, v.inputs.equities
    try:
        events = PointInTimeView(source, decision).read("events", None, end.date())
    except DataUnavailable:
        events = pd.DataFrame(columns=["issuer_id", "event_date", "realised_recovery", "delisting_return"])
    events = events.reindex(columns=["issuer_id", "event_date", "realised_recovery", "delisting_return"])
    flags = []
    try:
        source.read("corporate_actions")
    except DataUnavailable:
        flags.append("No corporate_actions table: every day counts as no dividend and no split, so stock returns and vol are wrong around those days.")
    if events.empty:
        flags.append("No events table or no events: dead names earn no final return here, which can flatter the book.")
    if len(v.screen_rows):
        keep, screens = f.screen_bonds(v.screen_rows)
        kept = v.screen_rows[keep][["bond_id", "date"]]
        bonds = bonds.assign(date=pd.to_datetime(bonds.date)).merge(kept.assign(date=pd.to_datetime(kept.date)), on=["bond_id", "date"])
    else:
        screens = pd.DataFrame(columns=["screen", "tested", "removed", "not_applied"])
    bonds, equities, counts = f.apply_end_events(bonds, equities, events)
    if "entry_price" in bonds:
        blank = bonds.entry_price.isna()
        if blank.any():
            flags.append(f"entry_price blank on {int(blank.sum())} bond-months: those start from the signal's own price, which can flatter returns.")
            bonds = bonds.assign(entry_price=bonds.entry_price.where(~blank, bonds.full_price))
    else:
        flags.append("No entry_price: bond returns start from the signal's own price, which can flatter returns through bounce.")
    months = pd.period_range(start, end, freq="M")
    hedges = f.monthly_hedges(v.inputs.rates, months, settings.hedge_tenor)
    durations = f.bond_durations(bonds, v.inputs.rates) if len(bonds) else pd.DataFrame(columns=["month", "asset_id", "duration"])
    costs = _bond_costs(v.day_costs, v.screen_rows, settings)
    measured_stock = 2 * v.stock_half_spread
    stock_cost = settings.stock_cost if settings.stock_cost is not None else measured_stock

    runs, lines, summaries, splits, profiles, missing, notes = {}, [], [], [], [], [], []
    for name, freq in COMPOUNDINGS.items():
        run_, line, summary, split, note, profile, miss = _analyse(name, freq, bonds, equities, v.inputs.accounts, v.inputs.rates, v.screen_rows, v.financing,
                                                                   durations, hedges, costs, stock_cost, settings, target)
        runs[name] = run_
        lines.append(line); summaries += summary; splits += split; profiles.append(profile); missing.append(miss)
        notes = note
    report = Report(f.overall([r.verdict.verdict for r in runs.values()]), runs, bool(len(bad)))
    pd.DataFrame(summaries, columns=["compounding", "leg", "hold", "weighting", "sample", "months", "gross_annual", "t", "net_annual", "financing_annual", "overlay_annual"]).to_csv(out / "summary_table.csv", index=False)
    pd.concat(lines, ignore_index=True).to_csv(out / "monthly_returns.csv", index=False)
    pd.concat(profiles, ignore_index=True).to_csv(out / "quintile_profile.csv", index=False)
    pd.DataFrame(splits, columns=["compounding", "leg", "split", "label", "months", "gross_annual", "t", "round_trip_cost", "net_annual"]).to_csv(out / "splits.csv", index=False)
    screens.to_csv(out / "screens.csv", index=False)
    pd.concat(missing, ignore_index=True).to_csv(out / "missing.csv", index=False)
    (out / "summary.txt").write_text(_text(report, target, settings, costs[2], screens, contract, counts, stock_cost, notes, v, start, end, decision, flags))
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run F10 on real tables, through e2c_data.")
    p.add_argument("--start", default="2002-01-01")
    p.add_argument("--end", default="2021-12-31")
    p.add_argument("--decision-time", default=None, help="what the run may know. Default: the day after --end")
    p.add_argument("--out", default="results")
    p.add_argument("--force", action="store_true", help="run past failed contract checks. The summary says so")
    p.add_argument("--no-liquidity-screen", action="store_true", help="skip reading bond_trades. The summary says the screen was not applied")
    p.add_argument("--bond-cost", type=float, default=None, help="round-trip cost, decimal, overriding measured or planning cost")
    p.add_argument("--stock-cost", type=float, default=None, help="round-trip cost, decimal, overriding measured half spreads")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    end = pd.Timestamp(a.end)
    decision = pd.Timestamp(a.decision_time) if a.decision_time else end + pd.Timedelta(1, "D")
    settings = f.F10Settings(liquidity_screen=not a.no_liquidity_screen, bond_cost=a.bond_cost, stock_cost=a.stock_cost)
    try:
        run(open_source(), pd.Timestamp(a.start), end, decision, a.out, settings, force=a.force)
    except ContractFailed as e:
        print(e, file=sys.stderr)
        return 2
    print((Path(a.out) / "summary.txt").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
