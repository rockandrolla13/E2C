# Bonds, spreads and equity vol in the old work

## The answer

**No workbook computes anything on a bond.** I searched every string in every workbook for bond, asset swap, Z-spread, OAS, CUSIP, yield and basis. The only hits are unrelated: a stress label, an industry name containing "Loan", two headers with the word "basis", and a strategy tag. Bonds exist only in the written plans.

**Equity vol is everywhere.** It is the core of the method, not an add-on. And the evidence says you can run on realised vol alone, with a modest loss.

**The method should carry to bonds better than Yu's would.** The signal is a cross-sectional regression with a free intercept each week. So an average gap between bond and CDS spreads goes into the intercept and creates no trades. That reasoning is mine. Nothing in the files tests it.

---

## 1. What uses what

| Item | Where | Status |
|---|---|---|
| Bond in the signal | `Capital Structure Arb-1.doc`: "analysis of residuals in price term p(mkt) - p(EVol) allows to include securities other than CDS (bonds, etc)" | Plan only |
| Bond in execution | Same note: "competitive execution with dealers (CDS, bonds)" | Plan only |
| Bond or CDS against equity | `Description of Credit Strategies`: "Equity versus Debt (E2C): bond or cds, vol versus cds" | Plan only |
| Bond basis | Same note. Z-spread minus match-to-maturity CDS. Sized equal notional or spread duration neutral. Scan for lowest dollar price and highest basis | Plan only. No data, no code |
| "Bonds/Spreads" | MASTER `Reg!BK6`. A row label for stress shocks to spreads | Not bonds |
| "E2C Basis" | MASTER `E2C Data!CE2`. Standardised sum of spread and stock moves | Not a bond basis |
| "BASIS (ASIA)1" | `Risk Sheet Feb 14.xls`, `Server CDS Trades!AK80`. A strategy tag on one CDS ticket | Not a calculation |
| Equity vol, realised | Every model | Core input |
| Equity vol, put implied | MASTER `W:Z`, CG1.1, CG1.2, 4Ref, Regression tools, TEMPLATE, 2010 sheet | Averaged with realised vol |
| Puts to implied spread | `ImpliedSpread2.xls` | Add-in missing. One cached stock |
| ATM vol, risk reversal, variance swap against CDS | `Minimimum MTM (w Options) E2C.xls` | Cached only |
| CDS against vol, sell-side | `RVPack-CapArb-2011-10-06` | Not the user's model |

MASTER is `04_raw_data/12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls`.

### Minimum MTM (w Options)

A dealer-style screen dated 8 June 2007 by its sheet name. It has 473 tickers. For each name it fits a theoretical CDS against four equity measures:

1. stock price,
2. 1-year ATM vol,
3. 1-year 80/120 risk reversal,
4. variance swap.

For each measure it holds the theoretical spread, the difference, a live z-score, an R-squared pass flag and a bid/offer band. It also has a side call, delta in shares (Black-Scholes and skew-adjusted), gamma, kappa, theta, variance swap notional, jump-to-default on the variance swap, CDS annuity, one-quarter roll-down and carry, and break-even realised vol.

Only cached values survive. The fit formula is gone. So this is a design record and not a test target.

What it shows, by my count:

- The R-squared flag passes for stock on 311 names, ATM vol on 308, variance swap on 313, and risk reversal on 229. So risk reversal fits least often. The threshold is not stated.
- Side calls: 185 Long Protection, 91 Short Protection, 186 no call, 11 errors.
- Median band width is about 13 bp against a median 5y CDS of 40.5 bp, which is around 30% of spread. If those bands reflect tradeable width, then this is far wider than the 5% in MASTER. The file does not say what the bands mean, so I cannot confirm it.

### ImpliedSpread2

Author `rkan`. It takes two puts per stock, a minimum-strike put and an ATM put, and fits vol and a default intensity through `CSCalibrateDefaultOption`, which is missing. A "stick price" of 0.5 sets the stock's value after default. Then `spd = 10000*(1-R)*(1-Exp(-lam))*360/365`.

The cached stock runs 2004-07-01 to 2005-06-14. Correlation of implied spread with market 5y is 0.22, on one stock. The option data path is a server share. This is a Carr-Wu style idea [INFERRED], and it is the only attempt to get credit from equity options alone.

### RVPack

Kevin Henderson, October 2011. It holds JPM CEV outliers, CS Locus reports, CDS regressions at 3, 6 and 12 months, and sector z-scores of "Credit vs Equity" and "Credit vs Vol". It is useful only as a record of what the street watched.

---

## 2. Equity vol: which one, and what worked

### What each version used [PROVED by formula]

| Version | Formula | Inputs |
|---|---|---|
| CG1.1, CG1.2 | `Y2` =AVERAGE(O2:T2) | 162W, 360D, 3, 6, 12, 24M puts |
| 2Reference | `AC2` =AVERAGE(O2:X2) | 162W, 30, 60, 90, 180, 360D, 4 puts |
| 4Ref-e2c | `Y2` =AVERAGE(P2:T2) | 162W or 180D, 360D, 3, 6, 24M puts |
| 6_30_05_Data | `N2` =AVERAGE(H2:L2)/100 | Bug: mixes decimals and percents |
| SAMPLE | `AE`, pasted. Rerun fits | 162W, 360D, puts |
| TEMPLATE, Nov 2005 | `AvgSVol`, pasted. Rerun fits exactly | 162W, 360D, puts |
| MASTER | `AE2` =AVERAGE(R2:Z2) | 30, 60, 90, 180, 360D, 4 puts. **162W dropped** |
| 2010 sheet | pasted. My fit is exact | 30, 60, 90, 260, 360D, 3M, 6M puts |

MASTER dropped 162-week vol, on the evidence of the `Evol-comp` test below [INFERRED]. Production in November 2005 still used it. So the live book may have run a weaker mix than the final backtest.

### Evidence

MASTER sheet `Evol-comp` holds weekly NAV for 11 vol blends, pasted from a run with parameters I could not identify. I tried 4 settings and none matched. So I reran all of them through my replica at the final parameters.

Full sample, 151 weeks, gross of costs:

| Vol blend | Sheet End NAV | Rerun End NAV | Rerun S.R. | Mean R² |
|---|---:|---:|---:|---:|
| 30 to 360D + all puts (final) | 1.710 | 1.799 | **2.51** | 0.374 |
| 30 to 360D realised only | 1.723 | 1.810 | **2.49** | 0.343 |
| 30 to 360D + 3, 6M puts | 1.677 | 1.767 | 2.43 | n/a |
| 30 to 360D + 3 to 12M puts | 1.688 | 1.764 | 2.41 | n/a |
| 30 to 360D + 3M put | 1.716 | 1.768 | 2.40 | n/a |
| 30 to 180D realised | 1.697 | 1.725 | 2.22 | 0.317 |
| 30D only | n/a | 1.736 | 2.25 | 0.230 |
| 90D only | n/a | 1.635 | 2.09 | 0.307 |
| 162W, 360D, puts (CG1.2 mix) | 1.541 | 1.458 | 2.13 | 0.413 |
| 162W, 30 to 360D, puts | 1.375 | 1.584 | 1.92 | n/a |
| 162W + 30 to 360D realised | 1.440 | 1.463 | 1.57 | 0.364 |
| 360D only | n/a | 1.251 | 1.08 | 0.375 |
| 162W only | 1.137 | 1.009 | 0.15 | 0.306 |
| "All-Avg (except 162W)", read as 360D + puts | 1.730 | 1.411 | 1.89 | n/a |

The sheet does not define its column headers. I read them as shown, and the last row's reading may be wrong, since it misses the sheet by the most. The sheet ranks that column first, and I could not reproduce that.

Put vols exist on 0% of rows in 2002 and 2003, 35% in 2004 and 100% in 2005. So the full-sample table mostly tests realised vol. A clean test needs 2005 alone, 37 weeks:

| Vol blend, 2005 only | S.R. | Mean | Max DD | Mean R² |
|---|---:|---:|---:|---:|
| Puts only (where a name has none, realised) | 3.63 | 26.3% | -3.5% | 0.452 |
| 3M put (where none, realised) | 3.33 | 22.3% | -4.1% | 0.453 |
| 30 to 360D + puts | 3.05 | 26.4% | -2.5% | 0.365 |
| 30 to 360D realised | 2.54 | 23.8% | -4.7% | 0.269 |
| 30D | 2.28 | 21.0% | -4.8% | 0.179 |
| 360D | 1.17 | 12.3% | -6.2% | 0.289 |
| 162W | 0.21 | 0.9% | -3.3% | 0.300 |

### What this means

1. **Long-horizon vol fails.** 162-week vol gives S.R. 0.15. Yu uses 1,000-day vol, which is about the same horizon. If that transfers, then his vol choice is the weakest one here. The frameworks differ, so this is a pointer and not a proof.
2. **Blending horizons beats any one horizon.** The realised blend gets 2.49. The best single one gets 2.25.
3. **Option implied vol helps, but less than you might guess.** In 2005 the regression fit improves from R² 0.27 to 0.45, and S.R. rises from 2.5 to 3.6. Those are 37 weeks in a calm year. Treat it as a hint.
4. **You can start without options.** A realised blend of 30 to 360 days captures most of the value on three years of data. Adding options is an upgrade, not a precondition.

---

## 3. What carries over to bond spreads and equity vol

### Carries over

| Step | Why it transfers |
|---|---|
| DPS formula | Depends on the firm, not the instrument |
| Equity vol blend | Equity side only |
| Asset vol σ_s·S/(S+0.5D) | Same |
| Implied asset vol | Same idea. Invert the bond's spread or price. `notes/paper_method/e2c_bond.py` has `implied_vol_bond` |
| Weekly cross-section regression | Works on vol, whatever produced the vol. The free intercept should absorb an average bond-CDS gap [INFERRED] |
| Log residual and trigger | Same. The trigger needs re-testing, since bond vol is noisier |
| Sizing by target P&L per vega | Use the bond's price sensitivity to vol |
| Delta from the closed form | Same, with the bond price model |
| Stress and capital structure | Same form. Default loss becomes price minus recovery |
| The sector adjustment | Production subtracted a sector mean. No reason to drop it |

### Does not carry over

| Step | Why |
|---|---|
| Constant 5-year tenor | CDS is 5y. Bonds have their own maturity and they roll down. Either pick bonds near 5y or invert per bond |
| P&L `BG2` = size × Δspread × annuity | A bond's P&L is price change plus coupon minus funding. It has rate risk that needs a Treasury hedge. CDS `Rho` was small |
| Carry `BL2` = spread × days | Bond carry is coupon and roll-down minus repo |
| Short credit | Buying CDS protection is easy. Shorting a bond needs repo, and can be recalled. It costs more |
| The 5% cost in `Reg!DH4` | CDS-specific. The files hold no bond cost data |
| Weekly mid marks | Bonds trade irregularly, and the files hold no bond quotes. Stale marks would flatter Sharpe |
| R = 0.4 fixed | Bonds need seniority-specific recovery. Near recovery the inversion loses meaning |
| Financials | MASTER has no Financial sector name. `Results.xls` has 37 financials, but MASTER dropped them. Expect the same here |
| Captive finance names | GM, F, TIN: no solution exists. Expect failure on any name with large finance debt |

**The short leg matters.** On CDS, long credit hedged earns S.R. 1.15 and short credit hedged earns 0.92. Together they earn 2.51. A bond book that cannot short bonds gets one leg only. So its S.R. should be well below the combined number. Both legs are also inflated by the 2002 to 2005 rally, in opposite ways. Long credit is flattered. Short credit is hurt.

---

## 4. What the old workbooks teach that a paper would not

### Real sizes

- Model: $10M cap, $200k target per trade, 3 vol points. 78% of trades hit the cap.
- Backtest: about 26 long and 22 short at once, 47 open positions on average, $233M long and $207M short.
- Live book on 14 Feb 2006 (`Risk Sheet Feb 14.xls`): 90 positions, $415M gross, $20M net. 70 of 90 were $5M clips.
- Live book on 4 May 2006 (`E2c_Portfolio_Pricer_ADYNE.xls`): 51 positions, mostly $2M.
- Counterparties on 14 Feb 2006 CDS tickets: BOA 84, Barclays 8, Citi 8, Merrill 4.

### Real capital

Single-name default sets capital in 64% of weeks. Mean NAV is $33.6M against about $440M gross. A paper's "$0.5 per $1 notional" misses this logic completely. Here, NAV is whatever makes the worst single default a tolerable share of capital.

### Real costs

- `BidOffer Analysis 04.xls`: BellSouth 3 bp on 30.5 (9.8%), Xerox 10 bp on 122 (8.2%), GMAC 10 bp on 405 (2.5%). Those are one to three days of dealer runs, except BellSouth at 51 days.
- GMAC had 197 quotes from 9 dealers on one day.
- `Reg!DH4` assumed 5% of spread on trades flagged closed. Real entries are 5.3 a week, and real hold is 8.9 weeks, not the assumed 14.
- At 5% per round trip with real turnover, S.R. falls from 2.51 to 0.62. At 10% it is negative.
- BellSouth, a tight name, shows a width near 10%. Most backtest trades are in names under 100 bp.

### Model against book

`DifferenceBetweenE2CBookAndRegression20060517.xls`, by my count: 141 positions in the union. 75 agree in sign. 19 are only in the book. 46 are only in the model. 1 has the opposite sign. Book gross 457 and model gross 452. So traders followed the model on roughly half the positions. The book carried human judgement. The notes confirm this: "signals from three angles: Structural, Fundamental Overlay, Statistical". A backtest of the formula does not describe what was traded.

### Live P&L snapshots

Both are small and negative, and neither says what period the estimate covers:

| Date | Est. P&L | VRE YTD | Cell |
|---|---:|---:|---|
| 14 Feb 2006 | -$113,916 | -$130,167 | `Risk Sheet!Y2`, `AA2` |
| 4 May 2006 | -$62,193 | -$33,661 | `Olap Reports!X8`, `Z8` |

These are only two dates, for one book. They are not a track record. But they do sit next to a backtest claiming 20% a year, and the gap deserves a question to the user.

### Data problems

- GM, Ford, Visteon, CenterPoint and Temple-Inland removed. The closed form has no solution for most rows.
- 39 European names show DPS = 0 in `E2C_PIT_Analysis.xls` sheet `3Yr`, such as Accor and BAE.
- `Reference.xls`: of 593 tickers, 131 have blank 5y CDS, and 83 show zero.
- Put vols start only in 2004.
- The week of 2002-11-29 has 5 names, and the regression still runs.
- Sheet names in `Clean Quarter Data.xls` have the wrong year.
- 1,560 of 20,789 rows in `Results.xls` fail with "parSpd is too low to calibrate".
- 50 master rows show a vol of exactly 50, from the solver's start value.
- Balance sheet data arrives at the period end, before the company files.

### Names and times that failed

- Solectron, -$803k. Short credit 74 weeks. The stock hedge lost $700k as the stock fell, and the spread only went from 420 to 315.
- Toys R Us, -$674k. Long credit 47 weeks.
- Duke, -$477k. Short credit 55 weeks while the spread fell from 149 to 42. This is the classic error: short credit into a rally.
- Albertsons, live trade in TEMPLATE `Single Name Risk Report 1`. Long credit entered 2005-09-09. The spread rose 87 bp that week and the trade lost $310k. After 10 weeks it stood at -$186k.
- Week of 2005-05-06: -$818k, the second-worst week. By date it fits the GM and Ford downgrades, though those names were not in the book.
- Consumer Cyclical gives 45% of total P&L. Industrial gives 0.2%. Sprint and Delphi give 22%. So results lean on few names and one sector.

### The biggest lesson

The formula is easy and it is exact. The edge is thin against costs and delay. The evidence:

- Gross S.R. is 2.51.
- A one-week lag cuts it to 1.47.
- Real-turnover costs at 5% cut it to 0.62.

Bonds cost more to trade than CDS, trade less often, and take longer to short. So the honest prior for a bond version is far below these numbers. The first test should be net of measured bond costs, and with a lag.
