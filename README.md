# E2C: capital structure arbitrage research

`main` holds this file, the literature review, the method guide and the Finkelstein method. The other methods live on their own branches, so methods can be compared and combined by choice.

| Branch | What it holds | Folder when checked out | Runs on | Stage |
|---|---|---|---|---|
| `method/workbook` | Your old workbooks rebuilt: spec, code, tests | `notes/own_models` | CDS and stock | Matches the master workbook |
| `method/yu-bonds` | Yu (2005) extracted and adapted to bonds | `notes/paper_method` | Bonds and stock | Coded. Made-up data only |
| `method/finkelstein` | Finkelstein (2002) replication plan and code. Merged into `main` | `notes/finkelstein_plan` | Bonds, options, stock | WP1, WP2, WP3 and WP6a logic coded. Made-up data only |
| `compare/scenarios` | Scenario tables. Merges workbook and yu-bonds, because it imports both | `notes/scenarios` | Both | Tables done |
| `docs/lit-and-guide` | Literature review and merged guide. No code. Merged into `main` | `notes/` | n/a | Done |

Every branch has one checkout under `worktrees/` (not tracked), so they can be open side by side.

`evidence/` and `ssrn-687436.pdf` stay local and untracked. They include former-employer files and third-party research. The `method/workbook` branch also holds a data panel derived from those files. This repo is public, so check your rights to that panel.
