# E2C: capital structure arbitrage research

`main` holds this file, the literature review, the method guide, the data layer `e2c_data`, and the Finkelstein method with its F10 runner. The other methods live on their own branches, so methods can be compared and combined by choice.

| Branch | What it holds | Folder when checked out | Runs on | Stage |
|---|---|---|---|---|
| `method/workbook` | Your old workbooks rebuilt: spec, code, tests | `notes/own_models` | CDS and stock | Matches the master workbook. Adapter, hold-band options and `run_workbook.py` added |
| `method/yu-bonds` | Yu (2005) extracted and adapted to bonds | `notes/paper_method` | Bonds and stock | Coded, with adapter and `run_yu.py`. Made-up data only |
| `method/finkelstein` | Finkelstein (2002) replication plan and code. Merged into `main` | `notes/finkelstein_plan` | Bonds, options, stock | WP1, WP2, WP3, WP6a and the [F10 runner](notes/finkelstein_plan/F10.md) coded. Made-up data only |
| `compare/scenarios` | Scenario tables. Merges workbook and yu-bonds, because it imports both | `notes/scenarios` | Both | Tables done |
| `docs/lit-and-guide` | Literature review and merged guide. No code. Merged into `main` | `notes/` | n/a | Done |

Every branch has one checkout under `worktrees/` (not tracked), so they can be open side by side.

`evidence/` and `ssrn-687436.pdf` stay local and untracked. They include former-employer files and third-party research. The `method/workbook` branch also holds a data panel derived from those files. This repo is public, so check your rights to that panel.

For what each method does, in plain English and in technical detail, read [`notes/e2c_explained.pdf`](notes/e2c_explained.pdf).

## Run on your production machine

Nothing here has run on real data. The first real results come from these steps. All commands start in the repo root.

**1. Install, about 5 minutes.**

```bash
git clone https://github.com/rockandrolla13/E2C.git && cd E2C
python -m venv .venv && source .venv/bin/activate
pip install -e ".[parquet,test]" scipy
git worktree add worktrees/workbook method/workbook
git worktree add worktrees/yu-bonds method/yu-bonds
```

Finkelstein and F10 are on `main`. Workbook and Yu stay on their own branches, and all three import the installed `e2c_data`.

**2. Plug in your data.** Pick one:

- Export tables to a folder, one `<kind>.parquet` or `<kind>.csv` per data kind, then `export E2C_DATA_ROOT=/path/to/tables`.
- Write a module with a no-argument function that returns an object with `read(kind, start, end, ids)`, then `export E2C_SOURCE=your_package.module:make_source`.

`e2c_data/schema.py` lists the 15 kinds, their columns and units. Rates, spreads and vols are decimals. Bond prices are per 100 face. Amounts are USD. Every row needs `available_at`, the first moment the value was public.

**3. Run. Each runner checks your data first.**

```bash
cd notes/finkelstein_plan && python run_f10.py --start 2002-01-01 --end 2021-12-31 --out results && cd -
cd worktrees/workbook/notes/own_models && python run_workbook.py --start 2003-01-01 --end 2005-12-30 --out results && cd -
cd worktrees/yu-bonds/notes/paper_method && python run_yu.py --start 2003-01-01 --end 2005-12-30 --hedge-id YOUR_TREASURY_ID --bonds ID1,ID2 --out results && cd -
```

Replace the dates with your sample. Read `results/summary.txt` first. Exit code 2 means a required data check failed, and the contract report in `results/` names it. `--force` runs past it, and the summary says so.

**Check these before you trust a result:**

1. **Dead names.** A survivors-only universe stops the run on purpose. Hindsight warnings in the report need your review.
2. **Definitions.** `dividends`, `interest` and `repurchases` are trailing 12 months. `treasury_par` is semiannual. F10 needs `seniority`, `currency` and `coupon_type` in the exact words in [`F10.md`](notes/finkelstein_plan/F10.md). Other words remove bonds, and only the funnel in `screens.csv` shows it.
3. **Look-ahead.** F10 reads each table as known at each month end. The workbook and Yu runners version only accounts through time, apart from Yu trades. Later price or link corrections can reach earlier dates there.
4. **Run time.** F10 takes about 8 hours per million bond-months. Yu took about 8 seconds per bond for 3 years here. Start with a short window and a few bonds.
5. **Yu carry.** Without `--hedge-id`, carry P&L comes out blank and the run does not stop.

**Keep off this public repo:** your adapter, your tables and `results/`. `results/` is ignored by git. The adapter and tables belong outside this folder.
