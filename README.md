# E2C: capital structure arbitrage research

`main` holds this file, the literature review and the method guide. Each method lives on its own branch, so methods can be compared and combined by choice.

| Branch | What it holds | Folder when checked out | Runs on | Stage |
|---|---|---|---|---|
| `method/workbook` | Your old workbooks rebuilt: spec, code, tests | `notes/own_models` | CDS and stock | Matches the master workbook |
| `method/yu-bonds` | Yu (2005) extracted and adapted to bonds | `notes/paper_method` | Bonds and stock | Coded. Made-up data only |
| `method/finkelstein` | Finkelstein (2002) replication plan | `notes/finkelstein_plan` | Bonds, options, stock | Plan and check script. Model not built |
| `compare/scenarios` | Scenario tables. Merges workbook and yu-bonds, because it imports both | `notes/scenarios` | Both | Tables done |
| `docs/lit-and-guide` | Literature review and merged guide. No code. Merged into `main` | `notes/` | n/a | Done |

Every branch has one checkout under `worktrees/` (not tracked), so they can be open side by side.

`evidence/` and `ssrn-687436.pdf` stay local and untracked. They include former-employer files and third-party research. The `method/workbook` branch also holds a data panel derived from those files, so keep this repo private unless you have checked your rights.
