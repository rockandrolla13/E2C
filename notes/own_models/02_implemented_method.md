# How the user's own models computed the arbitrage

## The answer

The models did not compare a model spread with a market spread, name by name. They did this each week:

1. Turn each CDS spread into an implied asset vol with the CreditGrades closed form.
2. Compute a historical asset vol from a blend of equity vols.
3. Regress the log ratio of the two on log(S/D) across all names on that date.
4. Trade the names whose implied asset vol sits far from the fitted line.

So the signal is a cross-sectional residual in vol space. Market-wide moves in the ratio do not create trades.

I rebuilt the master backtest in Python from its pasted inputs. It matches the workbook to about 1e-12 on every weekly P&L line. It also reproduces all 21 scenario rows I reran, to 4 decimals. The code is `e2c_model.py`, and the step-by-step input and output spec is `05_io_spec.md`. These results are replication, not validation. The sample is a one-way credit rally with no hold-out, no costs in the headline number, and no execution lag.

## Reading key

| Short name | File |
|---|---|
| MASTER | `04_raw_data/12AdjE2C_Data_27_9_2005 (47.9MB, Alphadyne folder).xls` |
| SAMPLE | `03_backtests/SampleE2CBackTest.xls` |
| CG1.2 | `02_excel_models/E2C_CG1.2_RiskAnalysis.xls` |
| CG1.1 | `02_excel_models/E2C_CG1.1_RiskAnalysis.xls` |
| TEMPLATE | `04_raw_data/Template 27th Nov2005.xls` |

- **[PROVED]** means a cell formula or VBA line says it, or my rerun matches the cached numbers.
- **[INFERRED]** means I worked it out, and the file does not state it.
- E2C Data cells are quoted for row 2. Every data row has the same formula.
- Formula text comes from a LibreOffice conversion. Cached values come from the original file. No macro ran.

---

## The method, step by step

### Step 1. Weekly inputs [PROVED]

MASTER `E2C Data` holds 19,489 rows, 170 names and 151 Fridays, from 2002-09-27 to 2005-09-23. The inputs are pasted:

- Balance sheet: `C` BS_ST_BORROW, `D` BS_LT_BORROW, `E` BS_OTHER_ST_LIAB, `F` OTHER_LT_LIAB, `G` BS_MINORITY_INT, `I` BS_PFD_EQY.
- Market: `H` CUR_MKT_CAP, `J` PX_CLOSE_QTD, `AC` 5Y Spd.
- Vols: `P` 162 WEEKLY, `R:V` 30, 60, 90, 180, 360 DAILY, `W:Z` 3, 6, 12, 24 month put implied vol.
- Next week: `BD` NxDate, `BE` NxSp, `BF` NxS.
- Rate: `AD` =VLOOKUP($A2,Reg!$B$10:$AD$160,29), a weekly 5-year swap pasted in `Reg!AD`.

The field names and `AA US Equity` tickers look like Bloomberg. That source is [INFERRED]. No workbook names the CDS source for the master.

### Step 2. Debt per share [PROVED]

The pasted `K` DebtPerShare equals this formula on all 19,489 rows, with a maximum gap of 5e-13:

```
FinD = ST + LT + 0.5*(OtherST + OtherLT)
k0   = min(MinorityInt, 0.5*FinD)
k1   = min(Preferred, 0.5*MktCap)
DPS  = (FinD - k0) / ((MktCap + k1) / Price)
```

This is CreditGrades Appendix B, equations B.1 to B.7 (`CGtechdoc.pdf`, printed pp. 47 to 48). It is not the user's own variant, as I first wrote.

- Minority interest reduces debt. MRO and PD hit the 50% cap on 38 rows.
- No row hits the preferred cap.
- The VBA `DPS` function in CG1.2 has a bug in its preferred cap: `If k0 > 0.5 * MCap Then k1 = 0.5 * MCap` tests k0, not k1. The pasted column does not show that bug. On 50 rows k0 exceeds 0.5*MCap, and the data still matches the correct formula.

### Step 3. Equity vol [PROVED]

`AE2` =AVERAGE(R2:Z2). That is 30 to 360 day realised vol, plus put implied vols where present. The 162-week vol in column `P` is left out. The mix changed over versions. See the table under "Version differences".

Put vol coverage is not uniform. Rows with any put vol: 0% in 2002 and 2003, 35% in 2004, 100% in 2005 [PROVED by count]. So the blend changes character through the sample.

### Step 4. Historical asset vol [PROVED]

`AF2` =AE2\*J2/(J2+0.5\*K2). This is σ_a = σ_s × S/(S + L·D), with L fixed at 0.5. It matches Lardy.

### Step 5. Implied asset vol from the spread [PROVED]

`AG` ImpAvol is pasted. Its source is VBA `ICG_RefVol` in module `ClosedForm` of CG1.2. In `Prototype!N2` the call is:

`=ICG_RefVol($L2/10000,maturity,$B2,$C2,0,0.5,lamda,recovery,0.045)`

The fifth argument RefS=0 means "the vol I solve for is the asset vol". The VBA line is `If RefS = 0 Then Avol = RefVol`.

The closed form, from `ClosedForm`:

```
d    = (1 + S/(L*D)) * exp(lambda^2)
Avol = RefVol*RefS/(RefS + L*D), or RefVol if RefS=0
a    = sqrt(Avol^2*T + lambda^2)
z    = sqrt(0.25 + 2*r/Avol^2)
B(d,x)   = N(ln d/x - x/2) - d*N(-ln d/x - x/2)
G(d,x,z) = d^(z+.5)*N(-ln d/x - z*x) + d^(-z+.5)*N(-ln d/x + z*x)
BT = B(d,a);  B0 = B(d,lambda)
HT = exp(r*(lambda/Avol)^2) * (G(d,a,z) - G(d,lambda,z))
Num = 1 - B0 + HT
Den = (B0 - BT*exp(-r*T) - HT)/r
CG     = (360/365)*(1-R)*Num/Den
Ann360 = (365/360)*Den
CDS(fee) = (1-R)*Num - fee*(365/360)*Den
```

Solver: Newton from x0=0.5, forward step 0.01, stopping when |CG - spread| < 0.0001. This tolerance is 1 bp in spread. It matters in two ways.

- To match the pasted vols you must keep it. With it, my port matches `AG` on all 19,489 rows, with a maximum gap of 5e-9 vol points. With an exact root, the mean gap is 0.044 vol points and the maximum is 0.74.
- 50 rows show ImpAvol of exactly 50. The solver stopped at its start value. Their median spread is 13.9 bp. I reran the whole backtest with exact roots. S.R. moves from 2.51 to 2.53, so the artefact does no harm to the result. An exact root is safe to use in new code.

Parameters in MASTER, all confirmed by the exact match:

| Input | Value |
|---|---|
| T | 5 |
| L | 0.5 |
| lambda | 0.3 |
| R | 0.4 (`Reg!H6`) |
| r | weekly 5y swap (`Reg!AD`), from 3.25% to 4.57% |

### Step 6. The regression [PROVED]

Per date, on all names that date:

```
ln(ImpAvol/AvgAvol) = ln(Coeff) + Skew * ln(S/D)
```

Cells, for date row 10 in `Reg`:

- `V10` =CORREL(ln(Imp/His), ln(S/D))
- `W10` Skew =V10\*R10/S10, which is the OLS slope
- `X10` Coeff =EXP(K10-W10\*L10), which is e to the OLS intercept
- `Y10` k =1/X10^(1/W10), the S/D where implied equals historical

My rerun matches `W` and `X` on all 151 dates to 2e-15.

So fair implied vol has the form Imp = Hist × Coeff × (S/D)^Skew. Coeff and Skew carry the leverage effect. The pattern says highly levered names show less implied asset vol than their history suggests. Low-leverage names show more.

**Stability over time [PROVED, my count on 150 dates, leaving out one bad date]:**

| | Mean | Stdev | Min | Max |
|---|---:|---:|---:|---:|
| Skew | 0.2265 | 0.0264 | 0.1624 | 0.3354 |
| Coeff | 1.1975 | 0.2044 | 0.7819 | 1.4802 |
| R-squared | 0.374 | 0.061 | 0.190 | 0.605 |
| Names | 130 | 36 | 26 | 170 |

By year:

| Year | Skew | Coeff | k | R-squared | Mean implied | Mean hist asset vol |
|---|---:|---:|---:|---:|---:|---:|
| 2002 | 0.196 | 0.845 | 2.43 | 0.296 | 31.0 | 34.3 |
| 2003 | 0.228 | 1.025 | 1.00 | 0.385 | 28.6 | 24.4 |
| 2004 | 0.239 | 1.319 | 0.33 | 0.390 | 30.7 | 19.3 |
| 2005 | 0.217 | 1.392 | 0.22 | 0.365 | 32.7 | 19.1 |

The slope barely moves. The level moves a lot. Implied asset vol stayed near 30 while historical asset vol halved. This is why a through-the-cycle fit fails and a point-in-time fit works. It also shows that the strategy is relative value only. It carries no view on the level.

Through the cycle, pooled: `Reg!W7` 0.2749, `Reg!X7` 1.1859, correlation 0.6235 (R-squared 0.389).

One date is broken: 2002-11-29 has 5 names (Thanksgiving week, by the date) and gives Skew 0.386. The sheet still uses it.

**Single snapshots [PROVED by rerunning the regressions]:**

| Source | Spec | Result | Note |
|---|---|---|---|
| CG1.2 `Control&Report!C10,D10` | Skew, k | 0.2399, 0.403 | Pasted. Coeff = 0.403^-0.24 = 1.244 |
| `JP-Regressions.doc`, `jeanpierre.xls` | ImpAvol = a + b·AvgAVol | 10.546 + 1.116·x, R² 36.8%, N 255 | DW 1.19 |
| same | "ln(Imp/Hist)" on ln(S/D) | 0.1292 + 0.0991·x, R² 38.0% | Left side is **log base 10**. See below |
| `Leverage Ratio Comparative Results.doc`, `JP5Year.xls` | ln(Imp3Y/Hist) on ln(S/D) | 0.3976 + 0.2811·x, R² 43.6%, N 256 | Uses the 3-year implied vol |
| same | same on ln(S/(S+0.5D)) | 0.9905 + 1.4722·x, R² 52.5% | Better in this one snapshot only |
| `Regressions Data 6_30_05.doc`, `6_30_05_Data.xls` | ln(Imp/Hist) on ln(S/D) | 0.785 - 0.0111·x, R² 0.1%, N 108 | Wrong inputs. See below |
| `creditgrades 20100722.xls` | fitted constants | Imp/Hist = 1.266·(S/D)^0.194 | My fit of pasted EstVol: R² 1.000, USD and EUR use the same constants |

The log-base bug: `2Reference.xls!AG2` is `=LOG(AE2/AF2)`, base 10, while `AH2` is `=LN(I2/J2)`. Convert 0.0991 by 2.3026 and you get 0.228. That agrees with the master's 0.2265. The JP numbers are right once you see this.

The leverage measure: S/(S+0.5D) won in the single snapshot. I reran it across all 150 dates. It loses: mean R² 0.347 against 0.374, and better in 33% of weeks. A backtest on that regressor gives S.R. 1.19 against 2.51 on the same NAV. So keep ln(S/D).

### Step 7. Fair vol and residual [PROVED]

- `AL2`, `AM2`: VLOOKUP the date's Skew and Coeff.
- `AN2` EstVol =AF2\*(PITp\*AM2\*AI2^AL2+(1-PITp)\*coeff\*AI2^skew). PITp is `Reg!U6` = 0.95. The TTC pair is `Reg!W6` = 0 and `Reg!X6` = 1.
- `AO2` Residual =IF(RefTrig=0,AG2-AN2,LN(AG2/AN2)\*RefTrig). RefTrig is `Reg!O6` = 30.

So in MASTER the 5% TTC piece is simply "implied equals historical". The residual is a log gap, scaled to look like vol points at a 30 vol level.

Production differed. In TEMPLATE `Sheet8`, BOW on 2005-06-10 (date serial 38513): AvgAVol 0.17187, S/D 0.67487, SkewPIT 0.220898, CoeffPIT 1.252798. Fitted = 0.17187 × (0.95 × 1.252798 + 0.05 × 1) × 0.67487^(0.95 × 0.220898 + 0.05 × 0.28) = 0.195185, which matches the cell exactly on all 3 rows. Residual = 0.261937 - 0.195185 = 0.066752 in raw vol, with Trigger_Level 0.05. So production ran the SAMPLE settings: exponent blend, raw residual, trigger 5 vol points, TTC skew 0.28, flat r = 4.5%. Its vol mix was still 162W, 360D and puts (`AvgSVol` matches exactly).

By March 2006 production also removed a sector mean. In `ranked by residual.xls`, Adjusted Residual equals Average of Residual minus its sector mean, on all 204 names, with a largest gap of 2e-16. `Residual Drivers.xls` calls this `SingleNameAdjRes`, and `changes in industry residual.xls` tracks `INDUSTRY_RESIDUAL_AVERAGE`. The raw residual in that file averages exactly zero, so its own formula differs from S09. That formula did not survive.

### Step 8. Signal [PROVED]

- `AP2` Long credit =IF(AND(AO2>LgTrig,SpFl<=AC2,AC2<=SpCp),1,0)
- `AQ2` Short credit =IF(AND(AO2<-ShTrig,SpFl<=AC2,AC2<=SpCp),1,0)
- `Reg!P6`, `Q6` triggers are 6. `Reg!K6`, `L6` spread filter is 0 to 10,000.

Implied above fair means the CDS spread is wide against equity. So sell protection and short the stock. Implied below fair means buy protection and buy the stock.

The workbook has no entry or exit logic. Each Friday it rebuilds the book from that Friday's residuals. A name stays in while it is beyond the trigger. Its size changes each week.

### Step 9. Size [PROVED]

- `AT` Vega is pasted: change in CDS value per +1 point of asset vol.
- `AW2` Target =(AP2+AQ2)\*AT2\*target\*IF(RefTrig=0,1,AG2/RefTrig). `target` is `Reg!T6` = 3 vol points.
- `AX2` SizeL =IF(AP2=1,MIN(limsize,TaTrd/ABS(AW2)),0). `AY2` is the same for shorts.
- `Reg!S6` TaTrd = $0.2M. `Reg!R6` limsize = $10M.

In plain words: size each trade so that a 3 point vol convergence earns $200k, up to $10M notional. In the rerun 78% of trades hit the $10M cap. Mean size is $9.3M.

### Step 10. Hedge [PROVED]

- `AS` Delta is pasted, in equity dollars per $1 of CDS notional. My port: -(CDS(S+0.01) - CDS(S)) × 100 × S, at fixed asset vol, with fee equal to the market spread. Match: 9e-9 relative on average, 1.4e-6 at worst. The small gap is pasting precision.
- `AZ2` DeltaL =AX2\*AS2. `BA2` DeltaS =AY2\*AS2.
- Mean delta on traded rows is 8.1%. The Tate & Lyle example in the Credit Strategies note uses 7%.
- Each week's delta is fresh. So the hedge rebalances weekly. There is no turnover cost on it.
- Switches `Reg!AL6` LgH and `AM6` ShH turn each hedge on or off.

Note that the greeks use the implied vol. The spec in `Capital Structure Arb-1.doc` says deltas should use Evol_PIT. The code did not do that.

### Step 11. P&L [PROVED]

All columns are in **$ thousands**, though headers say "$m". Size in $M times bp times annuity, over 10, gives $k. `Reg!CK10` then divides by 1000 to reach $M.

- `BG2` Long CDS =-AX2\*(BE2-AC2)\*AR2/10. `BH2` Short CDS =AY2\*(BE2-AC2)\*AR2/10. Annuity is fixed at entry.
- `BI2` Long's hedge =-AZ2\*LgH\*(BF2/J2-1)\*1000. `BJ2` Short's hedge =BA2\*ShH\*(BF2/J2-1)\*1000.
- `BL2`, `BM2` Carry =±Size\*(Spread/10)\*Days/360.
- `BN2` Funding on long stock =-BA2\*ShH\*(rate+0.5%)\*Days/360\*1000.
- `BO2` Rebate on short stock =AZ2\*LgH\*(rate-0.5%)\*Days/360\*1000.
- `Reg!BA10` Total sums the eight lines.

Dividends on the stock hedge are not in the P&L. `BF` is a price, and no dividend column exists [PROVED by absence]. The VBA has no dividend input either.

### Step 12. Capital and return [PROVED]

- Name stress: `BQ:BT` Zero, LBO, Merger, Natio. Parameters are in `Reg!BG5:BJ6`.
- Book stress: `BV:BX` Oct87, LTCM, Apr03. Parameters are in `Reg!BL5:BN6`.
- Vol per name: `AU2` SpreadVol =AG2\*(AE2/AF2)\*(AS2/AR2)/(AC2/10000). `CA2` credit 1 SD and `CB2` equity 1 SD.
- `Reg!BZ10` VaR splits systematic and idiosyncratic pieces with betas 0.5 and 0.68, at 99%.
- `Reg!CG10` EC =MAX(BZ10\*(3.09/2.33)\*SQRT(252), -3\*MIN(macro stress), -MIN(name stress)).
- `Reg!CH10` NAV =EC/3.09/10%. So NAV is the capital that gives a 10% vol target at 99.9%.
- `Reg!CK10` Alpha =Total/NAV/1000. `Reg!CM10` compounds it.
- `Reg!CK6` S.R. =CK8/CK7. CK8 =AVERAGE\*52. CK7 =STDEV\*SQRT(52). Returns are excess of funding by construction, and the header says "Excess spread".

Mean EC is $10.4M and mean NAV is $33.6M. The single-name default stress sets EC in 64% of weeks, and the VaR term sets it in 37%. The stress averages -$9.73M (`Reg!BG9`). Mean margin `Reg!CI9` is 44% of NAV, using `BZ2` =MAX(5%,3.5×spread) on longs only.

### Step 13. Costs [PROVED]

The headline total has no transaction cost. `Reg!DH` holds a separate bid-offer estimate, and nothing subtracts it:

- `CK2` CloseTrd flags a name-week whose P&L beats a target.
- `Reg!DF10` is the share of open trades flagged. Mean 7.5% a week, implying 14 weeks of hold (`Reg!DF4`).
- `Reg!DH10` =$DH$4\*DF10\*(AN10+AO10)/0.1. `DH4` is 5%. So cost is 5% of spread × annuity × notional on flagged trades.

The sum of `DH` is $8,845k against a gross total of $20,478k. That is 43% of gross.

---

## Backtest results

### MASTER, as the workbook reports it

| Metric | Value | Cell |
|---|---:|---|
| S.R. | 2.5106 | `Reg!CK6` |
| Mean, annual | 20.6% | `Reg!CK8` |
| Vol, annual | 8.2% | `Reg!CK7` |
| End NAV | 1.7992 | `Reg!CM6` |
| Min NAV | 0.9861 | `Reg!CM7` |
| Total P&L | $20,478k | `Reg!BA7` |
| Credit P&L | $16,869k | `Reg!BD7` |
| Equity P&L | $3,609k | `Reg!BE7` |

### Four canonical metrics [my calculation from the replica]

| Metric | Gross | After `Reg!DH` |
|---|---:|---:|
| Sharpe (no hold-out exists, so this is in-sample) | 2.51 | 1.51 |
| t-stat, 151 weeks | 4.28 | 2.58 |
| Max drawdown | -3.6% | -4.9% |
| Info ratio | same as Sharpe | same as Sharpe |

**OOS Sharpe does not exist.** Triggers, PIT weight and the vol mix were chosen on the full sample. A fixed-parameter split of the 151 weeks gives first half 2.67 and second half 2.34. That is not a test, because the parameters saw both halves.

### Scenario tables: workbook and my rerun agree on all rows

Pasted in `Summary`, `I-PIT`, `R-Trigger`, `SpFilter`.

| Scenario | S.R. | End NAV |
|---|---:|---:|
| Long and short, hedged (base) | 2.5106 | 1.7992 |
| Long and short, unhedged | 2.4612 | 1.6399 |
| Long credit only, unhedged | 2.0999 | 1.5283 |
| Long credit only, hedged | 1.1455 | 1.3840 |
| Short credit only, hedged | 0.9171 | 1.4285 |
| Short credit only, unhedged | -0.5177 | 0.8537 |
| Trigger 0 | 1.3494 | 1.5020 |
| Trigger 2 | 1.6357 | 1.5953 |
| Trigger 4 | 2.2655 | 1.8644 |
| Trigger 8 | 2.1426 | 1.5360 |
| Trigger 10 | 2.0870 | 1.4311 |
| Trigger 12 | 1.3234 | 1.2227 |
| PIT 100% | 2.3990 | 1.8018 |
| PIT 98% | 2.4120 | 1.7836 |
| PIT 90% | 2.3382 | 1.7101 |
| PIT 80% | 2.1172 | 1.6265 |
| Spread 0-50 bp | 2.0779 | 1.1835 |
| Spread 0-150 bp | 1.7441 | 1.3515 |
| Spread 50-250 bp | 0.9259 | 1.2064 |
| Spread 150+ bp | 1.7189 | 1.5575 |
| Spread 250+ bp | 1.5933 | 1.5738 |

Reading these:

- A trigger of 6 has the highest S.R. and sits in the middle of a smooth hump. That is reassuring about overfitting, though the hump was found in-sample.
- Hedging barely changes the long-short book's S.R. It lifts short credit and cuts long credit. So in this sample the two-sided book gave most of the protection.
- Long credit alone made money unhedged because credit rallied through the whole sample. Average spread fell from 194 bp in 2002 to 69 bp in 2005.

### My extra tests, which the workbook did not run

| Test | S.R. | Mean | Max DD | End |
|---|---:|---:|---:|---:|
| Base, gross | 2.51 | 20.6% | -3.6% | 1.80 |
| Cost: sheet's `DH` column | 1.51 | 11.9% | -4.9% | 1.40 |
| Trade only on entry and exit. Round trip 2.5% of spread. Equity 5 bp each way | 1.52 | 12.6% | -4.7% | 1.43 |
| Same, round trip 5% of spread | 0.62 | 5.1% | -7.1% | 1.15 |
| Same, round trip 10% of spread | -1.14 | -9.7% | -27.1% | 0.75 |
| Weekly resize, round trip 5% | 0.48 | 4.0% | -7.4% | 1.11 |
| One-week execution lag, gross | 1.47 | 13.2% | -7.8% | 1.45 |
| Add back VC and CNP rows that solve | 2.15 | 17.8% | -4.0% | 1.66 |

This is the most important table here. Actual entries are 5.3 a week. Actual average hold is 8.9 weeks, not the 14 the sheet assumes. At the real turnover, 5% of spread per round trip takes most of the edge. A one-week lag takes 40% of it.

The bid-offer file gives real widths: BellSouth 3 bp on a 30.5 bp mid (9.8%), Xerox 10 bp on 122 bp (8.2%), GMAC 10 bp on 405 bp (2.5%). Most trades are in names under 100 bp. So tight names probably cost more than 5%. That is a three-name sample, so it is weak evidence.

### Which names and times hurt

Total by name, $k [my calculation]:

- Winners: Sprint Nextel +2,426, Delphi +2,103, Goodyear +1,220, Maytag +942, Georgia-Pacific +916. Sprint and Delphi give 22% of total P&L.
- Losers: Solectron -803, Toys R Us -674, Arrow -544, Duke -477, Avnet -452, Altria -391.
- 70% of the 165 traded names made money. A name-week wins 54% of the time.
- By sector: Consumer Cyclical +9,202, which is 45% of the total. Industrial +35.
- Worst weeks: 2003-02-14 -$1,180k, mostly equity. 2005-05-06 -$818k, mostly credit. This second one is the GM and Ford downgrade period [INFERRED from the date].
- Delphi's trade was short credit from 245 bp to 1,407 bp. Credit made +3,264, and the long equity hedge lost -1,160. So being short credit with a stock hedge paid in a real default path.

### Backtest flaws to know about

1. **GM and Ford are out.** Sheet `Removed` holds 566 rows for VC, GM, F, CNP and TIN. The closed form has no solution for GM, F, TIN and most CNP rows, because their debt per share is dominated by captive finance. GM averages DPS 593 against a price of 39. Removal has a mechanical cause, but the effect is that the book never saw GM or Ford. Putting back the 140 VC and CNP rows that do solve drops S.R. from 2.51 to 2.15.
2. **Balance sheets are not point in time.** 64% of long-term debt changes land within a week of a calendar quarter end. AA's new debt appears on 2004-12-31, 2005-04-01 and 2005-07-01. Those dates fall before filing. `Results.xls` admits worse: Titles!B23 says "DPS at start = dps at end of period".
3. **Same-close execution.** Signal, entry spread and entry price all share the same Friday close.
4. **Single regime.** Three years of tightening. No crisis.
5. **Universe.** Only names with data on that date. Three names leave before the end: CZR, TOY, MAY. The count grows from 79 to 170. So the sample mixes changing universes, and I cannot rule out survivorship in how the 170 were chosen.
6. **Dividends** on the hedge are not modelled.
7. **Stale spreads.** 7.4% of rows show the same spread as the week before, and 10% in 2002. Stale marks flatter a weekly Sharpe. I did not size this effect.

---

## Version differences

| Item | CG1.1 | CG1.2 / CSA_v1.0 | SAMPLE | MASTER | TEMPLATE (production) | 2010 sheet |
|---|---|---|---|---|---|---|
| Closed form | ClosedForm VBA | same | pasted, same | pasted, same | database, same | pasted, same |
| Vol mix | 162W, 360D, 3 to 24M puts | same | 162W, 360D, puts | 30 to 360D, puts (no 162W) | 162W, 360D, puts | 30, 60, 90, 260, 360D, 3M, 6M |
| r for implied vol | 4.5% | 4.5% | 4.5% | weekly swap | 4.5% | about 2.05% (my fit) |
| r for greeks | 4.5% | 4.5% | 5% (mismatch) | weekly swap | 4.5%, but Risky_DV01 at 5% | n/a |
| R | 0.4 | 0.4 | 0.4 | 0.4 | 0.4 | 0.4 |
| Fair vol | P×(S/D/0.403)^0.24, hard-coded | same, named cells | PIT and TTC blended in exponents | PIT and TTC blended in levels | as SAMPLE, TTC skew 0.28 | fixed constants |
| Residual | raw | raw | raw | log × 30 | raw | raw, opposite sign |
| Trigger | ±5 | ±5 | ±5 | ±6 | ±5 | none, z-score column |
| Sizing | 1/value, cap 100 | same | target and vega | same plus vol scaling | target and vega | none |
| Hedge cost | none | none | swapped (below) | fixed | n/a | none |

**CS_Model_v1.0.** A separate macro draft from August 2005. It uses `(Prsurv_T * Exp(-r_0 * T))`, and `Prsurv_T` is never set, so it is 0. Its CDS output is wrong. It also uses asset-specific recovery in the asset value. Do not use it.

**ImpliedSpread2.** A different idea. It fits vol and default intensity from two puts through `CSCalibrateDefaultOption`, which is missing. Then `spd = 10000*(1-R)*(1-Exp(-lam))*360/365` in `CalcImpliedSpreadFromPut`. The cached stock shows implied 5y spread correlation of only 0.22 with market 5y. That is one stock, on a 1-year put horizon.

**Results.xls.** 20,789 rows from a library named CFtw5. Its error text reads "parSpd is too low to calibrate implied assetVol". 1,560 rows failed. Its vols differ from the VBA by 0.33 points on average.

**SAMPLE funding swap.** `BN2` =-AZ2\*0.05\*... charges funding on the short-stock leg. `BO2` =BA2\*0.04\*... pays rebate on the long-stock leg. They are the wrong way round. MASTER fixes this. On 1,027 rows the effect is small: -$45k net as filed and -$50k corrected.

**SAMPLE exponent blend.** `AN2` =AF2\*(PITp\*AM2+(1-PITp)\*coeff)\*AI2^(PITp\*AL2+(1-PITp)\*skew). MASTER blends the two fair vols instead.

**Formula bugs in side tools:**

- `PointInTime.xls!N2` =E2\*(B2/B2+(0.5\*C2)). Excel reads B2/B2 first, so this is E2×(1+0.5×C2).
- `CSA Regression_Portfolio Tool v1.0` and `6_30_05_Data.xls`: `LN(B2/B2+L_bar*C2)` has the same fault. That explains the positive mean of 2.26 for a variable that must be negative in `Descriptive Statistics for Data 6_30_05.doc`.
- `6_30_05_Data.xls!N2` =AVERAGE(H2:L2)/100 mixes decimal realised vols with percent implied vols. `P2` solves with RefS=B2, so it is implied equity vol, not asset vol. Together these explain the R² of 0.1%.
- `Quarter Mark_to_Market Data.xls`: VLOOKUP without FALSE returns wrong names. `P3` =IF(3<>C3,"x","") compares the number 3.

---

## Planned against built

`Capital Structure Arb-1.doc` planned more than the workbooks built.

| Plan | Built in MASTER? |
|---|---|
| IVol = a + b·HVol3y + c·(S/DPS) | No. The form became ln(Imp/Hist) on ln(S/D) |
| PIT and TTC regressions | Yes |
| 3 buckets at 1 SD of residual | No. Fixed trigger of 6 |
| Profit threshold of 10% of asset vol | No. Target of 3 vol points |
| Must move into bucket within 1 month | No. No path test |
| Exit at neutral, at 6 months, or stop at 3× target | No. Weekly rebuild. No stop |
| Rebalance delta each period | Yes, weekly |
| Deltas on Evol_PIT | No. Deltas use implied vol |
| Costs, financing, repo | Partly. Financing yes. Costs off to the side |
| Residual in price terms to admit bonds | No. No bond data anywhere |
| 3y, 5y, 10y implied vol | 5y only in MASTER. 3y in `JP5Year` and `E2C_PIT_Analysis` |

`CSA Portfolio Optimisation.pdf` proposes a dynamic programme. Nothing implements it.

---

## Difference from Lardy and Yu

**Lardy (Jan 2002).** Same closed form with L = 0.5 and λ = 0.3. His 89% R² comes from a level regression with a flat, in-sample asset vol per name (142 names, 2000-01-06 to 2001-08-31). The deck says so on its own page 19. It shows that the model fits when each name gets its own vol. It does not show a trade. The user's workbooks replace the per-name flat vol with a weekly cross-section. That is the new idea.

**Yu (2005), per `notes/paper_method/01_paper_extraction.md`.**

| | Yu | User's MASTER |
|---|---|---|
| Fair value | model spread with 1,000-day vol | regression line in vol space |
| Name calibration | fits L̄ on first 10 days | none. L = 0.5 for all |
| Cross-section | none | the core of the method |
| Signal | spread ratio beyond 1+α | log vol gap beyond a trigger |
| Delta | fixed at entry | refreshed weekly |
| Exit | convergence, hold, stop | weekly rebuild |
| Sizing | equal weight, capital 0.5 per 1 | target P&L per vega, $10M cap, EC-based NAV |
| R | 0.5 | 0.4 |
| Vol | 1,000-day | 30 to 360 day plus puts |

The biggest difference: Yu asks if a name is cheap against its own history. The user's model asks if a name is cheap against other names at the same leverage today.

---

## Replication gaps per group

Source: first-pass vectors, saved as `_work/vectors_v1_with_paper_gaps.csv`. All numbers are the largest absolute gap in the group. The current per-row gaps from `test_e2c_model.py` are in `test_report.csv`, and `05_io_spec.md` summarises them.

| Group | Rows | Implied vol, points | Model spread at pasted vol, bp | Annuity | Delta | Vega | Note |
|---|---:|---:|---:|---:|---:|---:|---|
| A CG1.2 Sheet1 | 7 | n/a | 3e-9 | 2e-11 | 4e-11 | n/a | Exact |
| B CG1.2 Implied | 6 | 1e-9 | n/a | n/a | n/a | n/a | Exact, with VBA start values |
| D MASTER | 30 | 9e-10 | 0.95 | 7e-11 | 9e-9 | 1e-12 | Spread gap is the solver's 1 bp stop |
| E SAMPLE | 10 | 3e-10 | 0.67 | 6e-11 | 1e-8 | 5e-12 | Greeks at r = 5% |
| F Results.xls | 7 | 0.98 | 70 | n/a | n/a | n/a | External engine. Expected |
| G CG1.2 Prototype | 8 | 7e-11 | 0.62 | n/a | 4e-10 | n/a | ThCDS gap 7e-11 bp |
| H 2010 sheet | 8 | 0.0015 | 0.97 | n/a | n/a | n/a | r fitted to 2.05% |
| I TEMPLATE | 3 | 1e-9 | 0.19 | 0.054 | 2e-9 | 2e-12 | Annuity gap closes to 1e-11 at r = 5%: Risky_DV01 is the annuity at 5% |

**Whole-file checks on MASTER, all 19,489 rows:**

| Column | Largest gap |
|---|---:|
| DPS | 5e-13 |
| AvgHVol, AvgAvol | 7e-15 |
| ImpAvol | 5e-9 points |
| Annuity | 4e-11 relative |
| Delta | 1.4e-6 relative |
| Vega | 2e-9 relative |
| Rho | 1.5e-7 relative |
| `Reg` P&L lines, weekly | 9e-13 |
| `Reg!BB` cumulative | 5e-12 |
| `Reg!CK` alpha | 3e-7 before exact normal quantiles were set |
| `Reg!CM` NAV | 5e-6 before exact normal quantiles were set |

SAMPLE: I recomputed `Reg!AZ22` as 1,265.7896 from pasted inputs. Gap 3e-7.

**Paper agent's code, `notes/paper_method/e2c_bond.py`.** I ran it on the vectors and did not edit it.

- Spread: same closed form. Gap at most 3e-9 bp, using `act360=True`.
- Annuity: same once multiplied by 365/360. Gap at most 2e-11.
- Delta: gap at most 0.0009 on MASTER and SAMPLE rows, or 0.0099 on the external engine rows. It uses a central difference at 1% of price, and the VBA uses a forward step of 0.01. Both are fine.
- Implied vol: gap up to 0.33 vol points on MASTER rows, because the paper code finds the exact root. Largest at spreads under 25 bp. To match cached vols, use `ICG_RefVol_VBA` in `_work/scripts/cg_vba.py`. For new work the exact root is better, and the backtest does not depend on it.
- It has no R = 0.4 default and no 365/360 annuity factor. Pass these in. Its `Firm.S_ref=None` equals RefS = S, not RefS = 0. To feed an asset vol directly, set sigma_s = avol × (S + L·D)/S.

---

## Files

To rerun: make a venv, install `xlrd openpyxl pandas numpy scipy`, then run the scripts from `_work/`. `_work/scripts/load_master.py` builds the pickles.

- `e2c_model.py`, `test_e2c_model.py`, `05_io_spec.md`: the code, its tests, and the spec.
- `_work/scripts/cg_vba.py`, `_work/scripts/engine.py`: first-pass ports. Superseded by `e2c_model.py`.
- `_work/vba/`: VBA source as text from every workbook with macros.
- `_work/analysis1.out`, `_work/analysis2.out`: scenario, name and year output.
