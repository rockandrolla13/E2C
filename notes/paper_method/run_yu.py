"""Run Yu's method on bonds with one command. Results go to --out as CSV, plus summary.txt. Data rows are never printed.

Set E2C_DATA_ROOT to a table folder, or E2C_SOURCE to module:function. Example:
  E2C_DATA_ROOT=/data/tables python run_yu.py --start 2003-01-01 --end 2005-12-30 --hedge-id UST5Y

Steps: check_source writes contract_report.csv and stops the run on a required failure unless --force. Then inputs.py builds one panel per
bond, with_peer_gaps fills the peer gaps, and run_bond_backtest runs each bond on the default BacktestConfig. A bond that can't be built
or run is listed in bonds.csv with its reason, and the others carry on.

Known limits:
- A long backtest from one late decision time: only accounts are versioned through time. Prices, terms, actions and links use the latest
  version known at the decision time, so later corrections reach earlier dates. Trades are the exception: each day uses the reports public by its close.
- Each bond is run alone. The output is per bond and per trade, with no portfolio or capital across bonds.
- sibling_gap is not built, and step 10's stock dividend and spinoff adjustment is not built. run_cds_backtest is not run here.
- With historical vol, a row needs 750 daily total returns before it can stay. A missing hedge id leaves hedge_repo blank, so carry P&L goes blank.

Exit codes: 0 done, 2 stopped on a contract failure, 3 no bond could be built.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

EXIT_CONTRACT, EXIT_NO_DATA = 2, 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="last date, YYYY-MM-DD")
    p.add_argument("--decision-time", help="what the view may know. Default: --end at 21:00 UTC")
    p.add_argument("--out", default="results", help="output folder. Default: ./results")
    p.add_argument("--force", action="store_true", help="carry on after a required contract failure")
    p.add_argument("--bonds", help="comma-separated bond ids. Default: every bond in bond_terms")
    p.add_argument("--vol-source", default="historical", choices=["historical", "implied"], help="equity vol for the run. Default: historical")
    p.add_argument("--hedge-id", help="financing id of the hedge Treasury")
    p.add_argument("--vol-min-obs", type=int, default=750, help="fewest daily returns for historical vol. Default: 750")
    p.add_argument("--min-trades-5d", type=int, default=10, help="liquidity screen. Default: 10")
    return p


def _trade_rows(bond, dates, result) -> list[dict]:
    return [dict(bond_id=bond, side=t.side, signal_date=dates[t.signal_day], entry_date=dates[t.entry_day], exit_date=dates[t.exit_day], reason=t.reason,
                 face=t.face, shares=t.shares, hedge_face=t.hedge_face, hpr=t.hpr, max_drawdown=t.max_drawdown, converged=t.converged, final_value=t.final_value)
            for t in result.trades]


def _summary(args, when, contract, forced, bonds: pd.DataFrame, headline: dict) -> str:
    lines = [f"window {args.start} to {args.end}, decision time {when}", f"contract: {contract}", f"forced past a failure: {forced}", f"vol source: {args.vol_source}",
             f"bonds asked: {len(bonds)}", "bonds by status: " + ", ".join(f"{k} {v}" for k, v in bonds.status.value_counts().items()),
             f"rows {int(bonds.rows.sum())}, priced days {int(bonds.priced_days.sum())}, tradable days {int(bonds.tradable_days.sum())}",
             "trades: " + ", ".join(f"{k} {v:.4f}" if isinstance(v, float) else f"{k} {v}" for k, v in headline.items()),
             "N is trades, N1 converged, N2 drawdown over 20%, N3 negative. Returns are per trade on capital, with no portfolio across bonds."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    import e2c_bond as m
    from e2c_data import PointInTimeView, check_source, failures, open_source
    from e2c_data.source import DataUnavailable
    from inputs import build_bond_panel, with_peer_gaps

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(args.start).date(), pd.Timestamp(args.end).date()
    when = pd.Timestamp(args.decision_time) if args.decision_time else pd.Timestamp(args.end) + pd.Timedelta(21, "h")
    source = open_source()
    report = check_source(source, when)
    report.to_csv(out / "contract_report.csv", index=False)
    bad, warned = failures(report), failures(report, "warn")
    contract = f"{len(bad)} required failures, {len(warned)} warnings"
    print(contract, "| see", out / "contract_report.csv")
    for row in bad.itertuples():
        print(f"  failed: {row.check} / {row.kind}, count {row.count}")
    if len(bad) and not args.force:
        print("Stopped. Fix the source, or rerun with --force.")
        return EXIT_CONTRACT

    view = PointInTimeView(source, when)
    try:
        ids = args.bonds.split(",") if args.bonds else sorted(view.read("bond_terms").bond_id.unique())
    except DataUnavailable as e:
        print(f"Stopped. Missing data: {type(e).__name__}: {e}")
        return EXIT_NO_DATA
    built, rows = [], {}
    for bond in ids:
        row = dict(bond_id=bond, status="built", rows=0, priced_days=0, tradable_days=0, trades=0, L_bar=np.nan, fit_rmse=np.nan, mean_hpr=np.nan)
        try:
            b = build_bond_panel(view, bond, start, end, vol_source=args.vol_source, hedge_id=args.hedge_id, min_trades_5d=args.min_trades_5d, vol_min_obs=args.vol_min_obs)
            built.append((bond, b))
            row.update(rows=b.report["rows"], priced_days=b.report["priced_days"], tradable_days=b.report["tradable_days"])
            for reason, n in b.report["left_out"].items():
                row[f"left_out_{reason}"] = n
            for screen, n in b.report["screens_failed"].items():
                row[f"failed_{screen}"] = n
        except (DataUnavailable, ValueError) as e:
            row["status"] = f"not_built: {type(e).__name__}"
        rows[bond] = row
    if not built:
        pd.DataFrame(rows.values()).to_csv(out / "bonds.csv", index=False)
        print("Stopped. No bond could be built. See", out / "bonds.csv")
        return EXIT_NO_DATA

    config = m.BacktestConfig()
    filled = with_peer_gaps([b for _, b in built], config)
    trades = []
    for (bond, _), b in zip(built, filled):
        try:
            result = m.run_bond_backtest(b.panel, config)
        except ValueError as e:
            rows[bond]["status"] = f"run_failed: {type(e).__name__}"
            continue
        rows[bond].update(status=result.status, trades=len(result.trades), L_bar=result.L_bar, fit_rmse=result.fit_rmse,
                          mean_hpr=float(np.mean([t.hpr for t in result.trades])) if result.trades else np.nan)
        trades += _trade_rows(bond, b.dates, result)
    bonds = pd.DataFrame(rows.values())
    bonds.to_csv(out / "bonds.csv", index=False)
    pd.DataFrame(trades, columns=["bond_id", "side", "signal_date", "entry_date", "exit_date", "reason", "face", "shares", "hedge_face", "hpr", "max_drawdown", "converged", "final_value"]).to_csv(out / "trades.csv", index=False)
    frame = pd.DataFrame(trades)
    headline = dict(N=len(frame))
    if len(frame):
        headline.update(N1=int(frame.converged.sum()), N2=int((frame.max_drawdown > 0.20).sum()), N3=int((frame.hpr < 0).sum()),
                        mean=float(frame.hpr.mean()), min=float(frame.hpr.min()), max=float(frame.hpr.max()))
    (out / "summary.txt").write_text(_summary(args, when, contract, bool(len(bad)), bonds, headline))
    print("Done:", len(bonds), "bonds,", len(frame), "trades. See", out / "summary.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
