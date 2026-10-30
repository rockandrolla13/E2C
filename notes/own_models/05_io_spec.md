# E2C model: inputs, steps, outputs

## What this is

This is the user's own method as a pipeline. Each step gives its inputs, formula, outputs and one real row from the workbooks. `e2c_model.py` has one function per step, with the same name. `test_e2c_model.py` recomputes workbook values and writes each row's gap to `test_report.csv`.

**Run it.**

```python
import pandas as pd, e2c_model as m
panel = pd.read_csv("master_panel.csv.gz")     # or your own table with the raw input columns
out = m.run_pipeline(panel, m.MASTER_PARAMS)
print(out["summary"])          # also out["names"], out["weeks"], out["unsolved"]
```

**Marks used below.**

- **PROVED**: a workbook formula says it, or a recompute matches cached values.
- **INFERRED**: I worked it out. The files do not state it.
- **MISSING**: the files do not settle it.

**Short names.**

| Name | File |
|---|---|
| MASTER | `04_raw_data/12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls`. All cited cells are row 2 of `E2C Data` or date row 10 of `Reg` |
| SAMPLE | `03_backtests/SampleE2CBackTest.xls` |
| CG12 | `02_excel_models/E2C_CG1.2_RiskAnalysis.xls`, VBA module `ClosedForm` |
| TEMPLATE | `04_raw_data/Template 27th Nov2005.xls` |

**The credit input is the 5-year CDS mid. No file prices a bond.** See "Where the files stop" at the end.

---

## Table 1. Every raw input

One row per name per week. All cells are in the master workbook, `12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls`. `E2C Data` holds these as pasted values. The extract `master_panel.csv.gz` holds them under the names below.

**Count: 26 columns.** `run_pipeline` needs 24 of them for a MASTER run, since `sector` and `vol_162w` are not used. The 4 put vols may be blank. The 3 `next_` columns can be derived by S00, so the minimum is 21 columns.

| Name | Meaning | Unit | Type | Frequency | Where in the files | Status |
|---|---|---|---|---|---|---|
| date | Week of the observation. All 151 are Fridays | date | date | weekly | `E2C Data!A` | PROVED |
| ticker | Bloomberg-style ticker |  | text | weekly | `E2C Data!B` | PROVED |
| sector | Industry sector. Needed only by S10 |  | text | static | `E2C Data!M` | PROVED |
| st_debt | Short-term borrowing, BS_ST_BORROW | $M | float | quarterly, carried weekly | `E2C Data!C` | PROVED. Timing not point in time: 64% of long-term debt changes land within a week of a calendar quarter end |
| lt_debt | Long-term borrowing, BS_LT_BORROW | $M | float | as above | `E2C Data!D` | as above |
| other_st_liab | Other short-term liabilities, BS_OTHER_ST_LIAB | $M | float | as above | `E2C Data!E` | as above |
| other_lt_liab | Other long-term liabilities, OTHER_LT_LIAB | $M | float | as above | `E2C Data!F` | as above |
| minority_int | Minority interest, BS_MINORITY_INT | $M | float | as above | `E2C Data!G` | as above |
| pfd_equity | Preferred equity, BS_PFD_EQY | $M | float | as above | `E2C Data!I` | as above |
| mkt_cap | Market cap, CUR_MKT_CAP | $M | float | weekly | `E2C Data!H` | PROVED |
| price | Close, PX_CLOSE_QTD. **Dividends not included** | $ | float | weekly | `E2C Data!J` | PROVED |
| spread_bp | 5-year CDS mid | bp | float | weekly | `E2C Data!AC` | PROVED as input. **Source MISSING**. Column has no vendor name |
| vol_30d, vol_60d, vol_90d, vol_180d, vol_360d | Realised equity vol over that many days | percent | float | weekly | `E2C Data!R:V` | PROVED as input. **Estimator MISSING**. The file pastes values |
| vol_162w | 162-week realised vol. Used by the older mix, dropped from MASTER | percent | float | weekly | `E2C Data!P` | PROVED |
| put_3m, put_6m, put_12m, put_24m | Put implied vol, Bloomberg-style field names | percent | float | weekly, optional | `E2C Data!W:Z` | PROVED as input. **Moneyness MISSING**. Blank on all rows in 2002-03 and 65% of rows in 2004. Present on all rows in 2005 |
| swap_5y_pct | 5-year swap rate | percent | float | weekly | `Reg!AD`, by date | PROVED as input. **Source MISSING**. Header says "5Yr Swap" |
| next_date, next_spread_bp, next_price | The same name's next row. Used only for P&L. Blank at a name's last row | date, bp, $ |  | weekly | `E2C Data!BD, BE, BF` | PROVED: equal to the next row on every non-blank row |

## Table 2. Fixed parameters

MASTER values. Cells are in the master workbook, sheet `Reg`, unless stated. "No cell" means the value sits inside a pasted solver run, and the 19,489-row match confirms it.

| Parameter | Value | Unit | Cell | Status |
|---|---|---|---|---|
| tenor T | 5 | years | No cell in MASTER. CG12 `Control&Report!D4` | PROVED by match |
| L, global recovery | 0.5 | decimal | `E2C Data!AF2`, hard-coded | PROVED |
| lambda, barrier vol | 0.3 | decimal | No cell in MASTER. CG12 `Control&Report!D6` | PROVED by match |
| R, recovery | 0.4 | decimal | `Reg!H6` | PROVED |
| Newton start | 0.5 | decimal vol | CG12 VBA `ICG_RefVol`: `x0 = 0.5` | PROVED by match |
| Newton forward step | 0.01 | decimal vol | CG12 VBA `ICG_RefVol`: `x0 + 0.01` | PROVED by match |
| Newton stop | 0.0001, which is 1 bp of spread | decimal | CG12 VBA `ICG_RefVol`: `Abs(y0 - Spread) < 0.0001` | PROVED by match |
| Newton step limit | 200 | count | Mine. The VBA loops until it stops | INFERRED |
| Act/360 factors | 360/365 on the spread, 365/360 on the annuity |  | CG12 VBA `CG`, `Ann360`, `CDS` | PROVED |
| Residual scale, the ×30 | 30 | vol points | `Reg!O6` RefTrig. 0 means raw vol points | PROVED |
| Long trigger, short trigger, the ±6 | 6, 6 | residual units | `Reg!P6, Q6`. SAMPLE and TEMPLATE use 5 | PROVED |
| Target profit, the $200k | 0.2 | $M | `Reg!S6` TaTrd | PROVED |
| Target move, the 3 vol points | 3 | vol points | `Reg!T6` target | PROVED |
| Trade cap, the $10M | 10 | $M | `Reg!R6` limsize | PROVED |
| PIT weight | 0.95 | decimal | `Reg!U6` PITp | PROVED |
| TTC skew, TTC coeff | 0, 1 |  | `Reg!W6, X6`. SAMPLE and TEMPLATE use 0.28, 1 | PROVED |
| Spread floor, spread cap | 0, 10000 | bp | `Reg!K6, L6` | PROVED |
| Hedge switches | 1, 1 |  | `Reg!AL6, AM6` | PROVED |
| Funding, rebate spread | +0.5%, -0.5% on the swap | decimal | `E2C Data!BN2, BO2` | PROVED |
| Zero shock: credit, equity | -1, -1 |  | `Reg!BG6, BG5` | PROVED |
| LBO shock: credit, equity | -0.25, +0.40 |  | `Reg!BH6, BH5` | PROVED |
| Merger shock: credit, equity | +0.25, +0.20 |  | `Reg!BI6, BI5` | PROVED |
| Nationalisation shock: credit, equity | +0.25, -0.40 |  | `Reg!BJ6, BJ5`. "Natio" read as this, INFERRED | PROVED |
| Oct87 shock: spread, equity | +15%, -22% |  | `Reg!BL6, BL5` | PROVED |
| LTCM shock: spread, equity | +50%, -10% |  | `Reg!BM6, BM5` | PROVED |
| Apr03 shock: spread, equity | -25%, +7% |  | `Reg!BN6, BN5` | PROVED |
| Betas: credit, equity, market, E2C | 0.5, 0.5, 0.5, 0.68 |  | `Reg!BQ5, BU5, BY5, BY6` | PROVED. Calibration MISSING |
| VaR, margin, capital confidence | 99%, 99.85%, 99.9% |  | `Reg!BZ6, CD6, CG6` | PROVED. Calibration MISSING |
| Target vol | 10% |  | `Reg!CH6` | PROVED |
| Bid-offer | 5% of spread |  | `Reg!DH4` | PROVED. Source of the 5% MISSING |

## Table 3. Rules the files do not settle

| Item | Status |
|---|---|
| Which names enter | MISSING. The count grows from 79 to 170 with no stated rule |
| Which names leave | INFERRED. Sheet `Removed` lists VC, GM, F, CNP, TIN. The closed form has no root for GM, F, TIN and most CNP rows. VC mostly solves, so removal was by name |
| Balance sheet lag | MISSING. The data appears at the period end, before filing. A live version needs a lag rule |
| Execution time and lag | MISSING. Signal, entry spread and entry price share one Friday close |
| Entry and exit | MISSING as a rule. MASTER rebuilds the book weekly. The exit plan in `Capital Structure Arb-1.doc` (neutral, 6 months, 3× stop) was never built |
| Dividends and borrow beyond ±50 bp | MISSING |
| Sector mean date scope, and start date of S10 | INFERRED. `ranked by residual.xls` shows it on 2006-03-17 |
| Financials | INFERRED excluded. MASTER has no Financial-sector name, and no rule says why |
| Holiday weeks | MISSING. 2002-11-29 has 5 names, and the regression still runs |

---

## The pipeline

`02_implemented_method.md` describes 13 steps. This spec splits them further, so that each step has one function.

| 13-step list in `02_implemented_method.md` | Functions here |
|---|---|
| 1 Weekly inputs | Table 1, S00 `next_week_values` |
| 2 Debt per share | S01 `debt_per_share` |
| 3 Equity vol | S02 `average_equity_vol` |
| 4 Historical asset vol | S03 `historical_asset_vol` |
| 5 Implied asset vol | S04 `survival_probability`, S05 `model_spread` and siblings, S06 `implied_asset_vol` |
| 6 Regression | S07 `leverage_regression` |
| 7 Fair vol and residual | S08 `fair_asset_vol`, S09 `vol_residual`, S10 `sector_adjusted_residual` |
| 8 Signal | S11 `trade_signal` |
| 9 Size | S13 `trade_size` |
| 10 Hedge | S12 `cds_greeks`, S14 `equity_hedge` |
| 11 P&L | S15 `weekly_pnl` |
| 12 Capital and return | S16 `stress_tests`, S17 `name_risk`, S19 `book_capital`, S20 `weekly_return`, S22 `performance_summary` |
| 13 Costs | S18 `closed_trade_flag`, S21 `bid_offer_cost` |
| Older sizing, not in the 13 | S23 `reval_trade` |

`run_pipeline(inputs, params)` runs S00 to S09 and S11 to S22 in order. S10 and S23 are separate, because MASTER uses neither.

```
raw inputs -> S01 DPS -> S02 equity vol -> S03 hist asset vol
S04, S05 closed form -> S06 implied asset vol
S03 + S06 -> S07 regression (one date, all names) -> S08 fair vol -> S09 residual -> [S10 sector adjust] -> S11 signal
S12 greeks -> S13 size -> S14 hedge -> S15 P&L
S16 stress + S17 name risk -> S19 capital -> S20 return -> S22 summary
S18 closed flag -> S21 bid-offer
```

### S00 `next_week_values`

Find each name's next row, for the P&L only.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `date, ticker, spread_bp, price` | See Table 1 |  |  | weekly | `E2C Data!A, B, AC, J` |

**Formula**

```
sort by ticker and date, then take each column from the next row of the same ticker
```

Source: `E2C Data!BD, BE, BF` are pasted, and equal this on all 19,489 rows. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `next_date, next_spread_bp, next_price` | Next week | date, bp, $ | S15 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| date, spread_bp, price | 2004-01-16, 142.333, 53.68 |
| **next_date** (`BD`) | 2004-01-23 |
| **next_spread_bp** (`BE`) | 136.250 |
| **next_price** (`BF`) | 54.48 |

### S01 `debt_per_share`

Turn balance sheet items into debt per share.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `st_debt, lt_debt, other_st_liab, other_lt_liab, minority_int, pfd_equity` | See Table 1 | $M | float | quarterly | `E2C Data!C:G, I` |
| `mkt_cap` | Market cap | $M | float | weekly | `E2C Data!H` |
| `price` | Close | $ | float | weekly | `E2C Data!J` |

**Formula**

```
fin       = st_debt + lt_debt + 0.5*(other_st_liab + other_lt_liab)
minority  = min(minority_int, 0.5*fin)
preferred = min(pfd_equity, 0.5*mkt_cap)
dps       = (fin - minority) / ((mkt_cap + preferred) / price)
```

Source: `CGtechdoc.pdf` Appendix B, equations B.1 to B.7. `E2C Data!K` is pasted and matches on all 19,489 rows, largest gap 5e-13. Status: PROVED.

Do not copy VBA `DPS` from CG12. It has a wrong test: `If k0 > 0.5 * MCap Then k1 = 0.5 * MCap`. The pasted data does not show that fault.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `dps` | Debt per share | $ per share | S03, S05, S06, S07, S12 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694

| Field | Value |
|---|---|
| st_debt, lt_debt | 3,376.0, 21,163.0 |
| other_st_liab, other_lt_liab | 14,819.0, 10,672.0 |
| minority_int, pfd_equity | 4,760.0, 0.0 |
| mkt_cap, price | 109,033.31, 53.68 |
| **dps** (`K`) | 16.012676 |

### S02 `average_equity_vol`

Blend the equity vols into one number.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `vol_30d ... vol_360d` | Realised vols | percent | float | weekly | `E2C Data!R:V` |
| `put_3m ... put_24m` | Put implied vols, blank if none | percent | float | weekly | `E2C Data!W:Z` |
| `mix` | Which columns |  | text | fixed | `master` or `cg12` or `realised` |

**Formula**

```
avg_equity_vol = mean of the columns in the mix that are not blank
```

Source: `E2C Data!AE2` =AVERAGE(R2:Z2). Mix `cg12` is CG12 `Prototype!M2` =AVERAGE(D2:I2), which is 162W, 360D and four puts. SAMPLE and TEMPLATE use `cg12` too. Status: PROVED.

Evidence on which mix works is in `03_bond_and_vol.md`. In short: 162-week vol alone gives S.R. 0.15, realised only gives 2.49, and realised plus puts gives 2.51.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `avg_equity_vol` | Blended equity vol | percent | S03, S17 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694

| Field | Value |
|---|---|
| vol_30d, 60d, 90d, 180d, 360d | 15.229, 17.523, 22.836, 27.703, 37.209 |
| put_3m, 6m, 12m, 24m | blank, blank, blank, blank |
| **avg_equity_vol** (`AE`) | 24.100043 |

### S03 `historical_asset_vol`

Convert equity vol to asset vol.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `avg_equity_vol` | From S02 | percent | float | weekly | `E2C Data!AE` |
| `price` | Close | $ | float | weekly | `E2C Data!J` |
| `dps` | From S01 | $ per share | float | weekly | `E2C Data!K` |
| `L` | Global recovery | decimal | float | fixed | 0.5 |

**Formula**

```
avg_asset_vol = avg_equity_vol * price / (price + L*dps)
```

Source: `E2C Data!AF2` =AE2\*J2/(J2+0.5\*K2). Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `avg_asset_vol` | Historical asset vol | percent | S07, S08, S17 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694

| Field | Value |
|---|---|
| avg_equity_vol, price, dps | 24.100043, 53.68, 16.012676 |
| **avg_asset_vol** (`AF`) | 20.972072 |

### S04 `survival_probability`

Chance of no default by T.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `T` | Tenor | years | float | fixed | CG12 `Sheet1!C3` |
| `S` | Stock price | $ | float | each call | CG12 `Sheet1!C5` |
| `D` | Debt per share | $ | float | each call | CG12 `Sheet1!C6` |
| `asset_vol` | Asset vol | decimal | float | each call | CG12 `Sheet1!C24` |
| `L, lam` | Global recovery, barrier vol | decimal | float | fixed | CG12 `Sheet1!C9, C10` |

**Formula**

```
d = (1 + S/(L*D)) * exp(lam^2)
a = sqrt(asset_vol^2 * T + lam^2)
B(d,a) = N(ln d/a - a/2) - d*N(-ln d/a - a/2)
survival = B(d,a)
```

Source: VBA `E2C`, `B`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `survival` | Probability of no default by T | decimal | Reporting only. MASTER does not use it |

**Example:** CG12 `Sheet1` column F.

| Field | Value |
|---|---|
| T, S, D | 5, 10, 10 |
| RefVol, RefS, so asset_vol | 0.6, 10, 0.4 |
| L, lam | 0.5, 0.3 |
| **survival** (`F16`) | 0.64793502 |

### S05 `model_spread`, `risky_annuity`, `contingent_leg`, `cds_value`

The CreditGrades closed form for a CDS.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `T, S, D, asset_vol, L, lam` | As S04 |  | float | each call | CG12 `Sheet1` |
| `R` | Recovery of the instrument | decimal | float | fixed | CG12 `Sheet1!C11` |
| `r` | Rate | decimal | float | each call | CG12 `Sheet1!C12` |
| `fee` | Contract fee, for cds_value only | decimal | float | each call | CG12 `Sheet1!C4` |

**Formula**

```
z  = sqrt(0.25 + 2*r/asset_vol^2)
G(d,x,z) = d^(z+.5)*N(-ln d/x - z*x) + d^(.5-z)*N(-ln d/x + z*x)
BT = B(d,a);  B0 = B(d,lam)
HT = exp(r*(lam/asset_vol)^2) * (G(d,a,z) - G(d,lam,z))
Num = 1 - B0 + HT
Den = (B0 - BT*exp(-r*T) - HT) / r
model_spread   = (360/365) * (1-R) * Num / Den
risky_annuity  = (365/360) * Den
contingent_leg = (1-R) * Num
cds_value      = (1-R)*Num - fee*(365/360)*Den
```

Source: VBA `CG`, `Ann360`, `CLeg`, `CDS`, `G`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `model_spread` | Par spread | decimal | S06, S23 |
| `risky_annuity` | Annuity per 1 of fee | years | S12 |
| `contingent_leg` | Protection leg | per 1 notional | Reporting |
| `cds_value` | Value to protection buyer | per 1 notional | S12, S23 |

**Example:** CG12 `Sheet1` column F, with R = 0.5, r = 5%, fee = 1%.

| Field | Value |
|---|---|
| **model_spread** (`F18`) | 0.04032990 |
| **risky_annuity** (`F19`) | 3.811411 |
| **contingent_leg** (`F20`) | 0.153714 |
| **cds_value** (`F21`) | 0.115600 |

### S06 `implied_asset_vol`

Find the asset vol that the market spread implies. **This is where a spread becomes a vol.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `spread` | Market spread ÷ 10000 | decimal | float | weekly | `E2C Data!AC` |
| `T, L, lam, R` | Constants |  | float | fixed | Table 1 |
| `S, D` | Price, DPS | $ | float | weekly | `E2C Data!J, K` |
| `r` | Swap ÷ 100 | decimal | float | weekly | `Reg!AD` |
| `method` | `vba` or `exact` |  | text | fixed |  |

**Formula**

```
method vba (matches pasted values):
  x = 0.5
  repeat: y = model_spread(x)
          stop if |y - spread| < 0.0001
          slope = (model_spread(x + 0.01) - y) / 0.01
          x = x - (y - spread) / slope
method exact: solve model_spread(x) = spread by bracketing, 1.5% to 500%
no solution: return nan
```

Source: VBA `ICG_RefVol` with RefS = 0, as called in CG12 `Prototype!N2`. MASTER `E2C Data!AG` is pasted, and the recompute matches on all 19,489 rows with a largest gap of 5e-9 vol points. Status: PROVED.

The stop at 1 bp matters only for matching old values. Exact roots differ by 0.044 vol points on average, and S.R. moves from 2.51 to 2.53. Use `exact` for new work. 50 rows show a pasted vol of exactly 50, because the loop stopped at its start value.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `implied` | Implied asset vol × 100 | percent | S07, S09, S12, S13, S17 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| spread_bp, price, dps | 142.333, 53.68, 16.012676 |
| swap_5y_pct | 3.41 |
| **implied** (`AG`) | 45.937170 |

`implied_other` (S06b) solves the same way for DPS, recovery, spot, L or the RefVol form. It feeds no later step. Example: CG12 `Implied!N5:S5`.

### S07 `leverage_regression`

Fit one line across all names on one date. This line defines fair.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `ln_imp_hist` | ln(implied / avg_asset_vol), all names that date |  | float | weekly | `E2C Data!AJ` |
| `ln_s_over_d` | ln(price / dps), all names that date |  | float | weekly | `E2C Data!AK` |

**Formula**

```
correl = CORREL(ln_imp_hist, ln_s_over_d)
skew   = correl * STDEV(ln_imp_hist) / STDEV(ln_s_over_d)
coeff  = exp(mean(ln_imp_hist) - skew * mean(ln_s_over_d))
k      = 1 / coeff^(1/skew)
So: implied = hist * coeff * (S/D)^skew
```

Source: `Reg!V10, W10, X10, Y10`. Status: PROVED, all 151 dates.

Use ln(S/D). `JP5Year.xls` found ln(S/(S+0.5D)) better in one snapshot (R² 52.5% against 43.6%). Across 150 dates it is worse (34.7% against 37.4%). A backtest on it gives S.R. 1.19.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `skew` | Slope |  | S08 |
| `coeff` | e to the intercept |  | S08 |
| `k` | S/D where implied equals historical |  | Reporting |
| `correl`, `r2`, `n` | Fit quality |  | Reporting |

**Example:** 2004-01-16, MASTER `Reg` row 76.

| Field | Value |
|---|---|
| names | 91 |
| mean ln_imp_hist, mean ln_s_over_d (`K`, `L`) | 0.315588, 0.627596 |
| stdev of each (`R`, `S`) | 0.297701, 0.716754 |
| **correl** (`V`) | 0.705113 |
| **skew** (`W`) | 0.292866 |
| **coeff** (`X`) | 1.140865 |
| **k** (`Y`) | 0.637635 |

### S08 `fair_asset_vol`

Read fair implied vol off the line.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `avg_asset_vol` | From S03 | percent | float | weekly | `E2C Data!AF` |
| `s_over_d` | price / dps |  | float | weekly | `E2C Data!AI` |
| `skew_pit, coeff_pit` | From S07 |  | float | weekly | `E2C Data!AL, AM` |
| `pit_weight, ttc_skew, ttc_coeff, blend` | Constants |  |  | fixed | `Reg!U6, W6, X6` |

**Formula**

```
levels (MASTER):    avg_asset_vol * ( p*coeff_pit*sd^skew_pit + (1-p)*ttc_coeff*sd^ttc_skew )
exponents (SAMPLE, TEMPLATE):
                    avg_asset_vol * (p*coeff_pit + (1-p)*ttc_coeff) * sd^(p*skew_pit + (1-p)*ttc_skew)
```

Source: `E2C Data!AN2`, SAMPLE `E2C Data!AN2`, TEMPLATE `Sheet8!AK2`. Status: PROVED for both. They are different formulas and give slightly different numbers.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `fair_vol` | Fair implied asset vol | percent | S09 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| avg_asset_vol, s_over_d | 20.972072, 3.352344 |
| skew_pit, coeff_pit | 0.292866, 1.140865 |
| **fair_vol** (`AN`) | 33.441952 |

### S09 `vol_residual`

How far implied vol sits from fair.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `implied` | From S06 | percent | float | weekly | `E2C Data!AG` |
| `fair_vol` | From S08 | percent | float | weekly | `E2C Data!AN` |
| `ref_trigger` | 30, or 0 for raw | vol points | float | fixed | `Reg!O6` |

**Formula**

```
residual = ln(implied/fair_vol) * ref_trigger     if ref_trigger > 0
residual = implied - fair_vol                     if ref_trigger = 0
```

Source: `E2C Data!AO2`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `residual` | Rich or cheap | vol points at a 30 level | S10, S11, S18 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| implied, fair_vol | 45.937170, 33.441952 |
| **residual** (`AO`) | 9.523903 |

### S10 `sector_adjusted_residual` (optional, production 2006)

Remove the sector average from each residual.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `residual` | From S09, one date |  | float | weekly | `ranked by residual.xls`, sheet `data`, column C |
| `sector` | Sector |  | text | static | same sheet, column A |

**Formula**

```
adjusted = residual - mean(residual in the same sector, same date)
```

Source: `03_backtests/ranked by residual.xls`. All 204 names match, largest gap 2e-16. Status: arithmetic PROVED. MASTER does not use this step, so its effect on the backtest is MISSING. The residual in that file averages exactly zero, unlike S09, so its own formula is MISSING.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `adjusted` | Sector-neutral residual | as input | S11, if used |

**Example:** PKD US Equity, 2006-03-17.

| Field | Value |
|---|---|
| sector | Energy |
| residual | -0.158561 |
| sector mean | -0.096082 |
| **adjusted** (`data (2)`) | -0.062478 |

### S11 `trade_signal`

Decide the trade.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `residual` | From S09 |  | float | weekly | `E2C Data!AO` |
| `spread_bp` | Spread | bp | float | weekly | `E2C Data!AC` |
| `long_trigger, short_trigger, spread_floor, spread_cap` | Constants |  | float | fixed | `Reg!P6, Q6, K6, L6` |

**Formula**

```
long_flag  = 1 if residual >  long_trigger  and floor <= spread <= cap
short_flag = 1 if residual < -short_trigger and floor <= spread <= cap
```

Source: `E2C Data!AP2, AQ2`. Status: PROVED. Long flag means sell protection and short the stock. Short flag means buy protection and buy the stock.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `long_flag`, `short_flag` | Side | 0 or 1 | S13, S18 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| residual | 9.523903 |
| **long_flag, short_flag** (`AP, AQ`) | 1, 0 |

### S12 `cds_greeks`

Sensitivities of a CDS struck at the market spread, at the implied vol.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `T, S, D, L, lam, R, r` | As S05 |  | float | weekly | Table 1 |
| `asset_vol` | Implied ÷ 100 | decimal | float | weekly | `E2C Data!AG` |
| `spread_bp` | Market spread, used as fee | bp | float | weekly | `E2C Data!AC` |

**Formula**

```
annuity = risky_annuity(asset_vol)
delta   = -(cds_value(S + 0.01) - cds_value(S)) * 100 * S
vega    = cds_value(asset_vol + 0.01) - cds_value(asset_vol)
rho     = cds_value(r + 0.01) - cds_value(r)
theta   = cds_value(T - 1/12) - cds_value(T)
```

Source: pricer VBA `Delta`, `vega`, `Theta` in `E2c_Portfolio_Pricer_ADYNE.xls`, and CG12 `Prototype!AA2, AE2`. MASTER `AR, AS, AT, AV` are pasted. The recompute matches all 19,489 rows. Status: PROVED.

Three variants are in the data. SAMPLE solves vol at 4.5% but pastes greeks at 5%. TEMPLATE `Risky_DV01` is annuity at 5%, while its Delta and Vega are at 4.5%. TEMPLATE shows Vega and Theta signed for the long-credit side.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `annuity` | Risky annuity | years | S15, S17, stress10 |
| `delta` | Equity $ per $1 notional. This is the **hedge ratio** | decimal | S14, S17 |
| `vega` | Value change per +1 vol point | per 1 notional | S13, S18 |
| `rho` | Value change per +100 bp | per 1 notional | Reporting |
| `theta` | Value change per month | per 1 notional | Reporting |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| **annuity** (`AR`) | 4.510220 |
| **delta** (`AS`) | 0.102490 |
| **vega** (`AT`) | 0.006274 |
| **rho** (`AV`) | -0.000745 |

### S13 `trade_size`

Size so a 3 point vol move earns $200k, up to $10M.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `long_flag, short_flag` | From S11 |  | int | weekly | `E2C Data!AP, AQ` |
| `vega` | From S12 |  | float | weekly | `E2C Data!AT` |
| `implied` | From S06 | percent | float | weekly | `E2C Data!AG` |
| `target_vega_points, target_trade_pnl, trade_limit, ref_trigger` | Constants |  | float | fixed | `Reg!T6, S6, R6, O6` |

**Formula**

```
scale  = implied/ref_trigger, or 1 if ref_trigger = 0
target = (long_flag + short_flag) * vega * target_vega_points * scale
size   = min(trade_limit, target_trade_pnl / |target|)
size_long = size if long_flag else 0;  size_short = size if short_flag else 0
```

Source: `E2C Data!AW2, AX2, AY2`. Status: PROVED. 78% of trades hit the $10M cap.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `target` | Profit at target, per 1 notional | decimal | S18 |
| `size_long`, `size_short` | CDS notional | $M | S14, S15, S16, S17, S18 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| vega, implied | 0.006274, 45.937170 |
| **target** (`AW`) | 0.028819 |
| **size_long, size_short** (`AX, AY`) | 6.939836, 0.000000 |

### S14 `equity_hedge`

Turn the CDS size into a stock position.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `size_long, size_short` | From S13 | $M | float | weekly | `E2C Data!AX, AY` |
| `delta` | From S12 | decimal | float | weekly | `E2C Data!AS` |
| `price` | Close | $ | float | weekly | `E2C Data!J` |

**Formula**

```
delta_long  = size_long  * delta      (short this much stock)
delta_short = size_short * delta      (buy this much stock)
hedge_shares = (delta_short - delta_long) * 1e6 / price
```

Source: `E2C Data!AZ2, BA2`. Shares: TEMPLATE `Sheet8!CJ2` NUMBER_OF_SHARES. Status: PROVED. Weekly rebuild, so the hedge rebalances weekly.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `delta_long`, `delta_short` | Stock dollars | $M | S15, S16, S17 |
| `hedge_shares` | Signed shares | shares | Trading |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| size_long, delta, price | 6.939836, 0.102490, 53.68 |
| **delta_long** (`AZ`) | 0.711263 |
| **hedge_shares** (my calculation from `AZ`, `J`) | -13,250 |

### S15 `weekly_pnl`

One name, one week, in $ thousands. Workbook headers say "$m". That label is wrong.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `size_long, size_short, delta_long, delta_short` | From S13, S14 | $M | float | weekly | `E2C Data!AX:BA` |
| `spread_bp, next_spread_bp` | This week and next | bp | float | weekly | `E2C Data!AC, BE` |
| `price, next_price` | This week and next | $ | float | weekly | `E2C Data!J, BF` |
| `annuity` | From S12, fixed at entry | years | float | weekly | `E2C Data!AR` |
| `days` | next_date - date | days | float | weekly | `E2C Data!BK` |
| `rate_pct` | Swap | percent | float | weekly | `E2C Data!AD` |

**Formula**

```
pnl_cds_long    = -size_long  * (next_spread - spread) * annuity / 10
pnl_cds_short   =  size_short * (next_spread - spread) * annuity / 10
pnl_hedge_long  = -delta_long  * (next_price/price - 1) * 1000
pnl_hedge_short =  delta_short * (next_price/price - 1) * 1000
carry_long      =  size_long  * (spread/10) * days/360
carry_short     = -size_short * (spread/10) * days/360
funding         = -delta_short * (rate + 0.5%) * days/360 * 1000
rebate          =  delta_long  * (rate - 0.5%) * days/360 * 1000
pnl_total       = sum of the eight lines, for live trades
```

Source: `E2C Data!BG2:BJ2, BL2:BO2, CG2`. Status: PROVED. SAMPLE swaps funding and rebate. That is its bug, and `swap_funding_bug=True` reproduces it. Dividends are MISSING.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| the eight lines, `pnl_total` | P&L | $k | S18, weekly sums, S20 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| spread_bp → next_spread_bp | 142.333 → 136.250 |
| price → next_price | 53.68 → 54.48 |
| days, rate_pct | 7, 3.41 |
| **pnl_cds_long** (`BG`) | 19.039905 |
| **pnl_hedge_long** (`BI`) | -10.600039 |
| **carry_long** (`BL`) | 1.920659 |
| **funding** (`BN`), **rebate** (`BO`) | 0.000000, 0.402456 |
| **pnl_total** (`CG`) | 10.762981 |

### S16 `stress_tests`

Loss under fixed shocks.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `size_long, size_short, delta_long, delta_short` | From S13, S14 | $M | float | weekly | `E2C Data!AX:BA` |
| `stress10_long, stress10_short` | size × annuity × spread / 100, the P&L of a 10% spread move | $k | float | weekly | `E2C Data!BB2, BC2` |
| `shocks` | Below |  | tuple | fixed | `Reg!BG5:BN6` |

**Formula**

```
net_size  = size_long - size_short;  net_delta = delta_long - delta_short
name shock:  credit_shock*net_size - equity_shock*net_delta
  zero (-1,-1)  lbo (-0.25,+0.40)  merger (+0.25,+0.20)  natio (+0.25,-0.40)
book shock:  -spread_shock*(stress10_long - stress10_short)/100 - equity_shock*net_delta
  oct87 (+15%,-22%)  ltcm (+50%,-10%)  apr03 (-25%,+7%)
```

Source: `E2C Data!BQ2:BT2, BV2:BX2`. Status: PROVED. Weekly: name shocks take the worst name, `Reg!BG10:BJ10`. Book shocks sum, `Reg!BL10:BN10`.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `zero, lbo, merger, natio` | Name shock P&L | $M | S19 |
| `oct87, ltcm, apr03` | Book shock P&L | $M | S19 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| stress10_long (`BB`) | 44.550497 |
| **zero, lbo** (`BQ, BR`) | -6.228574, -2.019464 |
| **merger, natio** (`BS, BT`) | 1.592707, 2.019464 |
| **oct87, ltcm, apr03** (`BV:BX`) | 0.089652, -0.151626, 0.061588 |

### S17 `name_risk`

Spread vol, margin and one-standard-deviation moves per name.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `implied, avg_equity_vol, avg_asset_vol` | From S06, S02, S03 | percent | float | weekly | `E2C Data!AG, AE, AF` |
| `delta, annuity` | From S12 |  | float | weekly | `E2C Data!AS, AR` |
| `spread_bp` | Spread | bp | float | weekly | `E2C Data!AC` |
| `sizes, deltas, stress10` | From S13, S14, S16 |  | float | weekly | `E2C Data!AX:BC` |

**Formula**

```
spread_vol = implied * (avg_equity_vol/avg_asset_vol) * (delta/annuity) / (spread_bp/10000)
margin     = max(5%, 3.5*spread_bp/10000) * size_long
credit_1sd = 10 * (spread_vol/100) * (stress10_long - stress10_short) / 1000
equity_1sd = (avg_equity_vol/100) * (delta_short - delta_long)
net_1sd    = credit_1sd + equity_1sd
```

Source: `E2C Data!AU2, BZ2, CA2, CB2, CC2`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `spread_vol` | Annual spread vol | percent | credit_1sd |
| `margin` | Credit margin | $M | S19 |
| `credit_1sd, equity_1sd, net_1sd` | Annual 1 SD P&L | $M | S19 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| **spread_vol** (`AU`) | 84.278762 |
| **margin** (`BZ`) | 0.346992 |
| **credit_1sd, equity_1sd, net_1sd** (`CA:CC`) | 0.375466, -0.171415, 0.204051 |

### S18 `closed_trade_flag`

Flag a live trade whose week P&L beat its target. The workbook uses this as a stand-in for a closed trade.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `pnl_total` | From S15 | $k | float | weekly | `E2C Data!CG` |
| `residual, long_flag, vega, size_long, size_short, target` | From S09, S11, S12, S13 |  | float | weekly | `E2C Data!AO, AP, AT, AX, AY, AW` |

**Formula**

```
hurdle = min( 1000*(|residual| - trigger)*vega*size, 1000*target_trade_pnl, 1000*target*size )
close_flag = 1 if pnl_total exists and pnl_total > hurdle
```

Source: `E2C Data!CK2`. Status: PROVED as a formula. Whether it represents real exits is MISSING. Real average hold is 8.9 weeks by my count, not the 14 it implies.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `close_flag` | Closed, by this proxy | 0 or 1 | S21 |

**Example:** MO US Equity (Altria), 2004-01-16, MASTER `E2C Data` row 6694.

| Field | Value |
|---|---|
| pnl_total | 10.762981 |
| **close_flag** (`CK`) | 0 |

### S19 `book_capital`

Weekly VaR, margin, economic capital and NAV.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `credit_sum, equity_sum, net_sum` | Sum of the 1 SD columns on the date | $M | float | weekly | `Reg!BP, BT, BX` × √252 |
| `credit_rss, equity_rss, net_rss` | Root of summed squares | $M | float | weekly | `Reg!BQ, BU, BY` × √252 |
| `zero ... natio, oct87 ... apr03` | From S16 | $M | float | weekly | `Reg!BG:BN` |
| `margin_credit` | Sum of margin | $M | float | weekly | `Reg!CC` |

**Formula**

```
var_credit = sqrt((b_cr*credit_sum)^2 + (1-b_cr^2)*credit_rss^2) / sqrt(252) * z99
var_equity = sqrt((b_eq*equity_sum)^2 + (1-b_eq^2)*equity_rss^2) / sqrt(252) * z99
var_total  = sqrt((b_m*net_sum)^2 + (b_e2c^2-b_m^2)*net_rss^2 + (1-b_e2c^2)*(credit_rss^2+equity_rss^2)) / sqrt(252) * z99
margin_equity = var_equity * (z99.85/z99) * sqrt(5)
economic_capital = max( var_total*(z99.9/z99)*sqrt(252), -3*min(oct87,ltcm,apr03), -min(zero,lbo,merger,natio) )
nav = economic_capital / z99.9 / 10%
```

Source: `Reg!BR10, BV10, BZ10, CD10, CE10, CG10, CH10, CI10`. Status: PROVED. All betas and confidence levels are constants. Their calibration is MISSING.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `var_credit, var_equity, var_total` | Daily 99% VaR | $M | economic_capital |
| `margin_equity, margin_total, margin_pct_nav` | Margin | $M, decimal | Reporting |
| `economic_capital` | Capital | $M | nav |
| `nav` | Capital base | $M | S20 |

**Example:** 2004-01-16, `Reg` row 76.

| Field | Value |
|---|---|
| **var_credit, var_equity, var_total** (`BR, BV, BZ`) | 0.191211, 0.166778, 0.245338 |
| **margin_credit, margin_equity, margin_total** (`CC, CD, CE`) | 9.846992, 0.475746, 10.322738 |
| **economic_capital** (`CG`) | 9.728089 |
| **nav** (`CH`) | 31.480122 |

### S20 `weekly_return`

Weekly return on NAV, and the NAV index.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `total_pnl` | Sum of name pnl_total on the date | $k | float | weekly | `Reg!BA` |
| `nav` | From S19 | $M | float | weekly | `Reg!CH` |

**Formula**

```
alpha = total_pnl / nav / 1000      (0 if nav = 0)
nav_index = previous nav_index * (1 + alpha), starting from 1
```

Source: `Reg!CK10, CM10`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `alpha` | Weekly return, excess of funding | decimal | S22 |
| `nav_index` | Compounded |  | S22 |

**Example:** 2004-01-16, `Reg` row 76.

| Field | Value |
|---|---|
| total_pnl (`BA`), nav (`CH`) | 91.331318, 31.480122 |
| **alpha** (`CK`) | 0.002901 |
| **nav_index** (`CM`) | 1.356676 |

### S21 `bid_offer_cost`

The workbook's cost estimate. **The total P&L does not subtract it.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `closed_share` | Share of live trades flagged by S18 | decimal | float | weekly | `Reg!DF` |
| `stress10_sum` | stress10_long + stress10_short | $k | float | weekly | `Reg!AN, AO` |
| `bid_offer` | 5% of spread | decimal | float | fixed | `Reg!DH4` |

**Formula**

```
bid_offer_cost = bid_offer * closed_share * stress10_sum / 0.1
```

Source: `Reg!DH10`. Status: PROVED as a formula. The 5% rate is an assumption, and its source is MISSING. `BidOffer Analysis 04.xls` shows 9.8% for BellSouth, 8.2% for Xerox, 2.5% for GMAC.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `bid_offer_cost` | Estimated cost | $k | Reporting |

**Example:** 2004-01-16, `Reg` row 76.

| Field | Value |
|---|---|
| closed_share (`DF`) | 0.000000 |
| stress10_long, stress10_short (`AN, AO`) | 460.740498, 367.505490 |
| **bid_offer_cost** (`DH`) | 0.000000 |

### S22 `performance_summary`

Headline numbers from the weekly returns.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `alpha` | From S20, all weeks | decimal | float | weekly | `Reg!CK10:CK160` |

**Formula**

```
mean_annual = mean(alpha)*52
vol_annual  = stdev(alpha)*sqrt(52)
sharpe      = mean_annual/vol_annual
nav_end, nav_min, nav_max from the compounded index
t_stat, max_drawdown: mine, not in the workbook
```

Source: `Reg!CK6, CK7, CK8, CM6, CM7, CM8`. Status: PROVED. It is in-sample and gross of cost and lag. There is no hold-out, so OOS Sharpe is MISSING.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `sharpe, mean_annual, vol_annual, nav_end, nav_min, nav_max` | Performance |  | Final output |
| `t_stat, max_drawdown, weeks` | My additions |  | Final output |

**Example:** MASTER base case.

| Field | Value |
|---|---|
| **sharpe** (`CK6`) | 2.510616 |
| **mean_annual** (`CK8`) | 0.205986 |
| **vol_annual** (`CK7`) | 0.082046 |
| **nav_end, nav_min** (`CM6, CM7`) | 1.799176, 0.986080 |
| t_stat, max_drawdown (mine) | 4.28, -3.6% |

### S23 `reval_trade` (older sizing, CG12 and CG1.1 only)

Revalue vol 3 points toward fair, then size to the expected gain. MASTER replaced this with S13.

**Inputs**

| Name | Meaning | Unit | Type | Frequency | Where in the files |
|---|---|---|---|---|---|
| `implied_pct` | From S06 | percent | float | each snapshot | `Prototype!O` |
| `residual` | Raw residual | vol points | float | each snapshot | `Prototype!V` |
| `spread_bp, S, D` | Market |  | float | each snapshot | `Prototype!L, B, C` |
| `trigger, reval` | 5, 3 | vol points | float | fixed | `Control&Report!D7, D8` |

**Formula**

```
flag = -1 if residual < -trigger; +1 if residual > trigger; else 0
vol_reval = (implied_pct - flag*reval)/100, or implied_pct/100 if flag = 0
theo_spread_bp = model_spread(vol_reval)*10000
theo_value = -flag*cds_value(fee=spread, vol_reval)
size = min(1/theo_value, 100)
```

Source: CG12 `Prototype!W2, X2, Y2, Z2, AC2, AL2`. Status: PROVED.

**Outputs**

| Name | Meaning | Unit | Used by |
|---|---|---|---|
| `flag, vol_reval, theo_spread_bp, theo_value, size` | Trade values |  | None in MASTER |

**Example:** AGU CN, CG12 `Prototype` row 2. Date not stated.

| Field | Value |
|---|---|
| spread_bp, S, D | 34.25, 28.00, 5.505873 |
| implied_pct, residual | 41.163785, -8.228177 |
| **flag** (`W`) | -1 |
| **vol_reval** (`X`) | 0.441638 |
| **theo_spread_bp** (`Y`) | 53.900711 |
| **theo_value** (`Z`) | 0.008832 |
| **size** (`AC`) | 100.0 |

---

## Table 4. Every final output

**Per name, per week.** Columns of `run_pipeline(...)["names"]`.

| Output | Meaning | Unit | Step | Workbook column |
|---|---|---|---|---|
| `dps` | Debt per share | $ | S01 | `K` |
| `avg_equity_vol` | Blended equity vol | percent | S02 | `AE` |
| `avg_asset_vol` | Historical asset vol | percent | S03 | `AF` |
| `implied` | Implied asset vol | percent | S06 | `AG` |
| `fair_vol` | Fair implied vol | percent | S08 | `AN` |
| `residual` | Signal value | vol points | S09 | `AO` |
| `long_flag`, `short_flag` | Signal | 0 or 1 | S11 | `AP`, `AQ` |
| `annuity` | Risky annuity | years | S12 | `AR` |
| `delta` | **Hedge ratio**, stock $ per $1 CDS | decimal | S12 | `AS` |
| `vega`, `rho` | Sensitivities | per 1 notional | S12 | `AT`, `AV` |
| `target` | Target profit per 1 notional | decimal | S13 | `AW` |
| `size_long`, `size_short` | CDS notional | $M | S13 | `AX`, `AY` |
| `delta_long`, `delta_short` | Stock dollars | $M | S14 | `AZ`, `BA` |
| `hedge_shares` | Signed shares | shares | S14 | TEMPLATE `CJ` |
| eight P&L lines | CDS, hedge, carry, funding, rebate | $k | S15 | `BG:BJ`, `BL:BO` |
| `pnl_total` | Week P&L | $k | S15 | `CG` |
| stress columns | Seven shocks | $M | S16 | `BQ:BT`, `BV:BX` |
| `spread_vol`, `margin`, `credit_1sd`, `equity_1sd`, `net_1sd` | Risk | percent, $M | S17 | `AU`, `BZ:CC` |
| `close_flag` | Closed proxy | 0 or 1 | S18 | `CK` |

The model spread at a chosen vol comes from S05: `model_spread(T, S, D, vol)`. MASTER has no column for it. CG12 has it in `Prototype!Y`.

**Per week.** Columns of `run_pipeline(...)["weeks"]`.

| Output | Meaning | Unit | Step | `Reg` column |
|---|---|---|---|---|
| `skew`, `coeff`, `k`, `correl`, `r2` | Regression |  | S07 | `W`, `X`, `Y`, `V` |
| `n`, `n_long`, `n_short` | Counts |  | S11 | `C`, `AF`, `AG` |
| `size_long`, `size_short`, `delta_long`, `delta_short` | Book | $M | S13, S14 | `AJ:AM` |
| `stress10_long`, `stress10_short` | 10% spread stress | $k | S16 | `AN`, `AO` |
| P&L lines, `pnl_total`, `pnl_cum`, `pnl_credit`, `pnl_equity` | P&L | $k | S15 | `AQ:AT`, `AV:AY`, `BA`, `BB`, `BD`, `BE` |
| `zero`, `lbo`, `merger`, `natio` | Worst name | $M | S16 | `BG:BJ` |
| `oct87`, `ltcm`, `apr03` | Book shock | $M | S16 | `BL:BN` |
| `var_credit`, `var_equity`, `var_total` | Daily VaR | $M | S19 | `BR`, `BV`, `BZ` |
| `margin_credit`, `margin_equity`, `margin_total`, `margin_pct_nav` | Margin | $M | S19 | `CC:CE`, `CI` |
| `economic_capital`, `nav` | Capital | $M | S19 | `CG`, `CH` |
| `alpha`, `nav_index` | Return | decimal | S20 | `CK`, `CM` |
| `closed_share`, `bid_offer_cost` | Cost estimate | decimal, $k | S21 | `DF`, `DH` |

**Whole run.** `run_pipeline(...)["summary"]`: `sharpe, mean_annual, vol_annual, nav_end, nav_min, nav_max, t_stat, max_drawdown, weeks`, from S22. `run_pipeline(...)["unsolved"]` lists input rows with no implied vol.

**Not coded.** Diagnostics with no later use: `Reg!CO, CP, CR, CT:DA, DD`, `E2C Data!CE`, `Reg!BS, BW, CA`.

---

## Where the files stop: equity vol

| Item | Supported by the files? |
|---|---|
| Realised vol as input | Yes, pasted. Estimator MISSING |
| Put implied vol as input | Yes, pasted, from 2004 onward. Moneyness MISSING |
| Which blend works | Yes. Tested in `Evol-comp`, and reran in `03_bond_and_vol.md` |
| Variance swap, ATM vol, risk reversal against CDS | `Minimimum MTM (w Options) E2C.xls`. Cached values only. Fit formula MISSING. Not coded |
| Spread implied from two puts | `ImpliedSpread2.xls`. Add-in `CSCalibrateDefaultOption` MISSING. Cached values for one stock. Not coded, not tested |

---

## [ADAPTATION] Bond spreads

**[ADAPTATION] Everything in this section is outside the user's files.** No workbook computes on a bond. Two sentences in `Capital Structure Arb-1.doc` plan it: "analysis of residuals in price term p(mkt) - p(EVol) allows to include securities other than CDS (bonds, etc)", and "competitive execution with dealers (CDS, bonds)". `e2c_model.py` has no bond code. The tests have no bond row. Function names below are in `notes/paper_method/e2c_bond.py`, which comes from Yu and CreditGrades, not from these workbooks. I have not run this path, and I did not edit that file.

### [ADAPTATION] Inputs that change

| Input in Table 1 | [ADAPTATION] Replacement | `e2c_bond.py` |
|---|---|---|
| `spread_bp`, 5y CDS mid | Z-spread of the bond, from a clean daily price | `clean_trade_reports`, `fix_decimal_shifts`, `flag_price_spikes`, `daily_clean_price`, `full_price`, `z_spread` |
| None | Bond terms: coupon, maturity, frequency, seniority | `Bond`, `cash_flows`, `accrued_interest` |
| `swap_5y_pct` | A zero curve | `zero_curve_from_par_yields`, `flat_curve`, `ZeroCurve` |
| R = 0.4 | Bond recovery R_b, by seniority | Argument `R_b` |
| Funding and rebate at swap ±50 bp | Repo, bond fee, stock fee | `bond_financing_rate`, `stock_financing_rate` |
| 5% of spread | Measured bond round-trip cost | `measured_round_trip`, `planning_round_trip`, `trade_cost` |
| None | Choice of bond and universe | `issuer_is_eligible`, `bond_terms_are_eligible`, `maturity_is_eligible`, `pick_bond_and_sibling`, `passes_liquidity_screen` |
| Balance sheet dates | A filing lag, which fills a MISSING rule above | `filing_usable_from` |
| Unchanged | Balance sheet fields, market cap, price, equity vols | None needed |

### [ADAPTATION] Steps that change

| Step here | [ADAPTATION] With a bond | `e2c_bond.py` | Status |
|---|---|---|---|
| S00, S01, S02, S03 | No change. Keep S01 and S02: `e2c_bond.debt_per_share` and `historical_equity_vol` use a different debt formula and a 1,000-day default | None | Applies |
| S04 | Same survival curve | `survival` | Applies |
| S05 | Bond price in place of CDS spread | `risky_bond_price`, `default_leg`, `model_z_spread` | Replaced |
| S06 | Invert the Z-spread. It returns equity vol and can return several roots or a refusal, so convert with `asset_vol` and check status | `implied_vol_bond`, `VolInversion`, `vol_status_allows_trade`, `asset_vol` | Replaced |
| S07, S08, S09 | Same form, on the bond's implied asset vol. Trigger and scale need new tests. The nearest idea there is a peer median in spread space, which is not this regression | Compare `peer_median_gap`, `peer_adjusted_signal` | Applies, untested |
| S10 | No change | None | Applies, untested |
| S11 | Same rule. Could add a cost gate. MASTER has no exit rule, and that file offers one | `passes_cost_gate`, `decide_entry`, `bond_exit_reason` | Applies, untested |
| S12 | Duration replaces annuity. Bond delta replaces CDS delta. Adds a rate hedge. **No bond vega function exists there**, so bump `risky_bond_price` in vol | `dollar_duration`, `bond_equity_delta`, `rate_hedge_face`, `par_hedge_bond`, `cds_equivalent_face` | Replaced. Vega MISSING |
| S13 | Same formula, with bond vega per face. The $200k and 3 vol points are CDS calibrated | None | Applies, untested |
| S14 | Same idea, on bond delta | `bond_equity_delta`, `build_position` | Replaced |
| S15 | Price change, coupon, repo, rate hedge. Replaces all eight lines | `daily_pnl`, `Position`, `Marks`, `Carry`, `coupons_paid` | Replaced |
| S16 | Default loss is price minus R_b, not notional. Shock sizes are for CDS | None | Needs new numbers |
| S17 | Replace annuity with duration in spread vol. Margin rule is for CDS | `dollar_duration` | Needs new numbers |
| S18, S21 | Replace the proxy with measured costs on real entries and exits | `trade_cost`, `measured_round_trip` | Replaced |
| S19, S20, S22 | Capital logic could stay. That file instead uses an account value and monthly returns | Compare `opening_account_value`, `next_account_value`, `monthly_index`, `annual_sharpe` | Choice open |
| S23 | Not used | None | Dropped |

The method detail is in `notes/paper_method/02_bond_vol_method.md`.

---

## Test results

`E2C_RUN_SLOW=1 python3 test_e2c_model.py` on 2026-10-30. Workbook values come from `test_vectors*.csv` and the two panel files. The full-run tests start from raw inputs only. Only the slow test opens the 48 MB workbook. Without `E2C_RUN_SLOW=1` it is skipped.

**11,465 comparisons: 11,458 pass, 0 fail, 7 information only.** The 7 information rows are `Results.xls`, an external engine that differs by up to 0.98 vol points.

**By group.**

| Group | Comparisons | Largest gap | Fails | Info |
|---|---|---|---|---|
| CG1.2 `Sheet1` grid | 35 | 2.3e-11 | 0 | 0 |
| CG1.2 `Implied` | 6 | 1.1e-09 | 0 | 0 |
| MASTER, 30 rows across spreads | 1,179 | 0.95 | 0 | 0 |
| MASTER, 49 trade rows | 1,956 | 0.97 | 0 | 0 |
| SAMPLE, 20 rows | 500 | 0.91 | 0 | 0 |
| `Results.xls`, external engine, information only | 7 | 0.98 | 0 | 7 |
| CG1.2 `Prototype`, 16 rows | 176 | 0.86 | 0 | 0 |
| 2010 sheet, 8 rows, rate and fit INFERRED | 32 | 0.0015 | 0 | 0 |
| TEMPLATE, 3 rows | 57 | 0.19 | 0 | 0 |
| `Creditgrades_model.xlsm`, 20 rows | 21 | 1.1e-16 | 0 | 0 |
| `ranked by residual.xls`, 204 names | 204 | 2.8e-17 | 0 | 0 |
| MASTER `Reg!CK6, CM6, BA7`, from the extract | 5 | 6.1e-05 | 0 | 0 |
| MASTER all 19,489 rows, one line per column | 22 | 0.00017 | 0 | 0 |
| MASTER scenario blocks, 24 | 72 | 0.00017 | 0 | 0 |
| MASTER `Reg`, 151 dates | 6,949 | 6.1e-05 | 0 | 0 |
| MASTER `Reg!CK6, CM6, BA7`, opening the workbook (slow) | 3 | 6.1e-05 | 0 | 0 |
| SAMPLE all 1,027 rows, one line per column | 7 | 1.8e-08 | 0 | 0 |
| SAMPLE `Reg`, 13 dates | 234 | 8e-06 | 0 | 0 |

**By group and step.**

| Group | Step | Comparisons | Largest gap | Tolerance | Fails |
|---|---|---|---|---|---|
| CG1.2 `Sheet1` grid | `cds_value` | 7 | 7.9e-13 | 1e-10 | 0 |
| CG1.2 `Sheet1` grid | `contingent_leg` | 7 | 5.6e-13 | 1e-10 | 0 |
| CG1.2 `Sheet1` grid | `model_spread` | 7 | 3e-13 | 1e-10 | 0 |
| CG1.2 `Sheet1` grid | `risky_annuity` | 7 | 2.3e-11 | 1e-09 | 0 |
| CG1.2 `Sheet1` grid | `survival_probability` | 7 | 6.7e-16 | 1e-10 | 0 |
| CG1.2 `Implied` | `implied_other` | 6 | 1.1e-09 | 1e-08 | 0 |
| MASTER, 30 rows across spreads | `average_equity_vol` | 30 | 1.4e-14 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `cds_greeks` | 120 | 8.8e-09 | 1e-06 | 0 |
| MASTER, 30 rows across spreads | `closed_trade_flag` | 30 | 0 | 0 | 0 |
| MASTER, 30 rows across spreads | `debt_per_share` | 30 | 5e-14 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `equity_hedge` | 60 | 0 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `fair_asset_vol` | 30 | 3.6e-15 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `historical_asset_vol` | 30 | 0 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `implied_asset_vol` | 30 | 8.5e-10 | 1e-07 | 0 |
| MASTER, 30 rows across spreads | `model_spread` | 30 | 0.95 | 1 | 0 |
| MASTER, 30 rows across spreads | `name_risk` | 150 | 0 | 1e-06 | 0 |
| MASTER, 30 rows across spreads | `stress_tests` | 210 | 0 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `trade_signal` | 60 | 0 | 0 | 0 |
| MASTER, 30 rows across spreads | `trade_size` | 90 | 0 | 1e-08 | 0 |
| MASTER, 30 rows across spreads | `vol_residual` | 30 | 0 | 1e-09 | 0 |
| MASTER, 30 rows across spreads | `weekly_pnl` | 249 | 7.1e-15 | 1e-08 | 0 |
| MASTER, 49 trade rows | `average_equity_vol` | 49 | 1.4e-14 | 1e-09 | 0 |
| MASTER, 49 trade rows | `cds_greeks` | 196 | 6e-09 | 1e-06 | 0 |
| MASTER, 49 trade rows | `closed_trade_flag` | 49 | 0 | 0 | 0 |
| MASTER, 49 trade rows | `debt_per_share` | 49 | 5.7e-14 | 1e-09 | 0 |
| MASTER, 49 trade rows | `equity_hedge` | 98 | 0 | 1e-09 | 0 |
| MASTER, 49 trade rows | `fair_asset_vol` | 49 | 0 | 1e-09 | 0 |
| MASTER, 49 trade rows | `historical_asset_vol` | 49 | 0 | 1e-09 | 0 |
| MASTER, 49 trade rows | `implied_asset_vol` | 49 | 7.4e-10 | 1e-07 | 0 |
| MASTER, 49 trade rows | `model_spread` | 49 | 0.97 | 1 | 0 |
| MASTER, 49 trade rows | `name_risk` | 245 | 0 | 1e-06 | 0 |
| MASTER, 49 trade rows | `stress_tests` | 343 | 0 | 1e-09 | 0 |
| MASTER, 49 trade rows | `trade_signal` | 98 | 0 | 0 | 0 |
| MASTER, 49 trade rows | `trade_size` | 147 | 0 | 1e-08 | 0 |
| MASTER, 49 trade rows | `vol_residual` | 49 | 0 | 1e-09 | 0 |
| MASTER, 49 trade rows | `weekly_pnl` | 437 | 1.4e-14 | 1e-08 | 0 |
| SAMPLE, 20 rows | `average_equity_vol` | 20 | 0 | 1e-09 | 0 |
| SAMPLE, 20 rows | `cds_greeks` | 60 | 1.1e-08 | 1e-06 | 0 |
| SAMPLE, 20 rows | `debt_per_share` | 20 | 4.6e-14 | 1e-09 | 0 |
| SAMPLE, 20 rows | `equity_hedge` | 40 | 0 | 1e-09 | 0 |
| SAMPLE, 20 rows | `fair_asset_vol` | 20 | 0 | 1e-09 | 0 |
| SAMPLE, 20 rows | `historical_asset_vol` | 20 | 0 | 1e-09 | 0 |
| SAMPLE, 20 rows | `implied_asset_vol` | 20 | 3.4e-10 | 1e-07 | 0 |
| SAMPLE, 20 rows | `model_spread` | 20 | 0.91 | 1 | 0 |
| SAMPLE, 20 rows | `trade_signal` | 40 | 0 | 0 | 0 |
| SAMPLE, 20 rows | `trade_size` | 60 | 0 | 1e-08 | 0 |
| SAMPLE, 20 rows | `vol_residual` | 20 | 0 | 1e-09 | 0 |
| SAMPLE, 20 rows | `weekly_pnl` | 160 | 2.2e-16 | 1e-08 | 0 |
| `Results.xls`, external engine, information only | `implied_asset_vol` | 7 | 0.98 | 1e-07 | 0 |
| CG1.2 `Prototype`, 16 rows | `average_equity_vol` | 16 | 0 | 1e-09 | 0 |
| CG1.2 `Prototype`, 16 rows | `fair_asset_vol` | 16 | 1.4e-14 | 1e-09 | 0 |
| CG1.2 `Prototype`, 16 rows | `historical_asset_vol` | 16 | 0 | 1e-09 | 0 |
| CG1.2 `Prototype`, 16 rows | `implied_asset_vol` | 16 | 7.5e-11 | 1e-07 | 0 |
| CG1.2 `Prototype`, 16 rows | `model_spread` | 16 | 0.86 | 1 | 0 |
| CG1.2 `Prototype`, 16 rows | `reval_trade` | 80 | 1e-10 | 1e-06 | 0 |
| CG1.2 `Prototype`, 16 rows | `vol_residual` | 16 | 7.7e-13 | 1e-09 | 0 |
| 2010 sheet, 8 rows, rate and fit INFERRED | `fair_asset_vol` | 8 | 0.00018 | 0.01 | 0 |
| 2010 sheet, 8 rows, rate and fit INFERRED | `historical_asset_vol` | 8 | 0 | 1e-09 | 0 |
| 2010 sheet, 8 rows, rate and fit INFERRED | `implied_asset_vol` | 8 | 0.0015 | 0.01 | 0 |
| 2010 sheet, 8 rows, rate and fit INFERRED | `vol_residual` | 8 | 0 | 1e-09 | 0 |
| TEMPLATE, 3 rows | `average_equity_vol` | 3 | 7.1e-15 | 1e-09 | 0 |
| TEMPLATE, 3 rows | `cds_greeks` | 18 | 2.5e-09 | 1e-06 | 0 |
| TEMPLATE, 3 rows | `equity_hedge` | 3 | 4.5e-13 | 1e-05 | 0 |
| TEMPLATE, 3 rows | `fair_asset_vol` | 3 | 3.6e-15 | 1e-09 | 0 |
| TEMPLATE, 3 rows | `historical_asset_vol` | 3 | 3.6e-15 | 1e-09 | 0 |
| TEMPLATE, 3 rows | `implied_asset_vol` | 3 | 1.2e-09 | 1e-07 | 0 |
| TEMPLATE, 3 rows | `model_spread` | 3 | 0.19 | 1 | 0 |
| TEMPLATE, 3 rows | `reval_trade` | 6 | 3.2e-09 | 1e-06 | 0 |
| TEMPLATE, 3 rows | `trade_size` | 6 | 0 | 1e-08 | 0 |
| TEMPLATE, 3 rows | `vol_residual` | 3 | 4.4e-15 | 1e-09 | 0 |
| TEMPLATE, 3 rows | `weekly_pnl` | 6 | 1.1e-13 | 1e-08 | 0 |
| `Creditgrades_model.xlsm`, 20 rows | `debt_per_share` | 1 | 0 | 1e-09 | 0 |
| `Creditgrades_model.xlsm`, 20 rows | `survival_probability` | 20 | 1.1e-16 | 1e-10 | 0 |
| `ranked by residual.xls`, 204 names | `sector_adjusted_residual` | 204 | 2.8e-17 | 1e-12 | 0 |
| MASTER `Reg!CK6, CM6, BA7`, from the extract | `run_pipeline:headline` | 3 | 6.1e-05 | 0.001 | 0 |
| MASTER `Reg!CK6, CM6, BA7`, from the extract | `run_pipeline:minimal` | 2 | 6e-09 | 1e-06 | 0 |
| MASTER all 19,489 rows, one line per column | `next_week_values` | 2 | 0 | 0 | 0 |
| MASTER all 19,489 rows, one line per column | `run_pipeline:names` | 20 | 0.00017 | 0.001 | 0 |
| MASTER scenario blocks, 24 | `scenario` | 72 | 0.00017 | 0.01 | 0 |
| MASTER `Reg`, 151 dates | `performance_summary` | 5 | 1.3e-15 | 1e-09 | 0 |
| MASTER `Reg`, 151 dates | `run_pipeline:weekly` | 6,944 | 6.1e-05 | 0.02 | 0 |
| MASTER `Reg!CK6, CM6, BA7`, opening the workbook (slow) | `slow:workbook` | 3 | 6.1e-05 | 0.001 | 0 |
| SAMPLE all 1,027 rows, one line per column | `run_pipeline:sample` | 7 | 1.8e-08 | 1e-06 | 0 |
| SAMPLE `Reg`, 13 dates | `run_pipeline:sample` | 234 | 8e-06 | 0.001 | 0 |

Raw stdout is in `test_output.txt`. Every row is in `test_report.csv`. On `run_pipeline:names`, `next_week_values` and `run_pipeline:sample` lines, the "computed" value is the largest gap over that column.

The largest gaps sit on looser checks. `model_spread` includes the check that the spread at a pasted vol sits within the solver's 1 bp stop. `fair_asset_vol` and `implied_asset_vol` include the 2010 sheet, where the rate and fit constants are my estimates (marked INFERRED in the report).

**Left out of the tests, because the files cannot support them:** bond pricing, the put-implied spread (group J), the Minimum MTM fit, and `CS_Model_v1.0.xls` (its macro has a bug). Rules marked MISSING have nothing to test.

**A note on what passing means.** The tests prove the code reproduces the workbooks. They do not prove the strategy works. The headline S.R. of 2.51 is in-sample, with no lag and no cost. See `02_implemented_method.md`.

