"""Run the workbook method on your data with one command. Results go to --out as CSV, plus summary.txt. Data rows are never printed.

Set E2C_DATA_ROOT to a table folder, or E2C_SOURCE to module:function. Example:
  E2C_DATA_ROOT=/data/tables python run_workbook.py --start 2003-01-01 --end 2005-12-30

Steps: check_source writes contract_report.csv and stops the run on a required failure unless --force. Then inputs.py builds the
weekly table, and run_pipeline runs three books: today (MASTER_PARAMS), hold_band (exit_trigger=3), and hold_band_cap20 (exit_trigger=3,
max_per_side=20). Each book has a gross Sharpe, a net Sharpe after trading_cost, and P&L without its top 5 names by total P&L.
Both Sharpes use weekly P&L over NAV, the workbook's own return. Net takes trading_cost out of the P&L, with NAV unchanged.

Known limits:
- A long backtest from one late decision time: only accounts are versioned through time. Prices, CDS quotes, swap rates, links and sectors
  use the latest version known at the decision time, so later corrections reach earlier dates.
- trading_cost is CDS only, with no stock cost, no execution lag and no exit cost at the last date.
- Without vendor vols the run leaves them blank, or derives realised vols with --derive-vols. A derived run cannot claim the workbook's numbers.

Exit codes: 0 done, 2 stopped on a contract failure, 3 data missing for the build.
"""
import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

TOP_NAMES = 5
EXIT_CONTRACT, EXIT_NO_DATA = 2, 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="last date, YYYY-MM-DD")
    p.add_argument("--decision-time", help="what the view may know. Default: --end at 21:00 UTC")
    p.add_argument("--out", default="results", help="output folder. Default: ./results")
    p.add_argument("--force", action="store_true", help="carry on after a required contract failure")
    p.add_argument("--derive-vols", action="store_true", help="derive realised vols that have no vendor value")
    return p


def book_rows(m, frame: pd.DataFrame) -> tuple[dict, dict]:
    """Each book's headline numbers, and its run_pipeline output."""
    books = {"today": m.MASTER_PARAMS, "hold_band": replace(m.MASTER_PARAMS, exit_trigger=3.0),
             "hold_band_cap20": replace(m.MASTER_PARAMS, exit_trigger=3.0, max_per_side=20)}
    rows, outputs = {}, {}
    for name, params in books.items():
        out = m.run_pipeline(frame, params)
        w, names = out["weeks"], out["names"]
        cost = m.trading_cost(names, params.bid_offer).reindex(w.index).fillna(0.0)
        net = m.weekly_return(w.pnl_total - cost, w.nav)["alpha"]
        by_name = names.groupby("ticker").pnl_total.sum().sort_values(ascending=False)
        rows[name] = dict(weeks=len(w), gross_sharpe=out["summary"]["sharpe"], net_sharpe=m.performance_summary(net)["sharpe"],
                          gross_pnl=float(w.pnl_total.sum()), cost=float(cost.sum()), net_pnl=float((w.pnl_total - cost).sum()),
                          pnl_without_top5=float(by_name.iloc[TOP_NAMES:].sum()), long_flags=int(names.long_flag.sum()),
                          short_flags=int(names.short_flag.sum()), unsolved=len(out["unsolved"]))
        outputs[name] = out
    return rows, outputs


def _summary(args, when, contract, forced, report, books: pd.DataFrame) -> str:
    lines = [f"window {args.start} to {args.end}, decision time {when}", f"contract: {contract}", f"forced past a failure: {forced}",
             f"input rows: {report['rows']}", f"left out: {report['left_out']}", "vol routes: " + ", ".join(f"{c} {r['route']} ({r['blank']} blank)" for c, r in report["vol_routes"].items()),
             "P&L is in $ thousands. Net Sharpe uses trading_cost, CDS only. pnl_without_top5 drops the 5 names with the highest total P&L.", "", books.to_string(float_format=lambda x: f"{x:.4f}")]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    import e2c_model as m
    from e2c_data import PointInTimeView, check_source, failures, open_source
    from e2c_data.source import DataUnavailable
    from inputs import build_workbook_inputs

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
        frame = build_workbook_inputs(view, start, end, derive_vols=args.derive_vols)
    except DataUnavailable as e:
        print(f"Stopped. Missing data: {type(e).__name__}: {e}")
        return EXIT_NO_DATA
    if frame.empty:
        print("Stopped. The build gave no rows.")
        return EXIT_NO_DATA
    rows, outputs = book_rows(m, frame)
    books = pd.DataFrame(rows).T
    books.to_csv(out / "books.csv", index_label="book")
    for name, output in outputs.items():
        output["weeks"].to_csv(out / f"weeks_{name}.csv")
        output["names"].to_csv(out / f"names_{name}.csv", index=False)
    (out / "summary.txt").write_text(_summary(args, when, contract, bool(len(bad)), frame.attrs["e2c_report"], books))
    print("Done:", len(frame), "input rows,", len(books), "books. See", out / "summary.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
