# Capital structure arbitrage on bond spreads and equity vol: the method

## Every raw input the pipeline needs

This is the minimum data, field by field. Names match the arguments in `e2c_bond.py` wherever a field goes straight into a function. Everything else in this file is computed from these.

| Group | Field | Meaning | Unit | Type | Frequency | Typical source | Required | First used |
|---|---|---|---|---|---|---|---|---|
| Issuer | `issuer_id` | Links the issuer's bonds to its stock | none | str | daily | CUSIP to permno link | Yes | Step 1 |
| Issuer | `sector` | Sector, to drop financials and utilities | none | str | daily | Compustat | Yes | Step 1 |
| Issuer | `has_listed_equity` | A listed common stock exists | none | bool | daily | CRSP | Yes | Step 1 |
| Issuer | `rating` | Rating known on that date | none | str | daily | S&P or Moody's history | Yes | Step 36 |
| Bond terms | `bond_id` | CUSIP | none | str | once per bond | Bond terms file, such as Mergent FISD | Yes | Step 6 |
| Bond terms | `seniority` | Ranking | none | str | once per bond | Bond terms file | Yes | Step 2 |
| Bond terms | `currency` | Currency | none | str | once per bond | Bond terms file | Yes | Step 2 |
| Bond terms | `coupon_type` | Fixed or other | none | str | once per bond | Bond terms file | Yes | Step 2 |
| Bond terms | `coupon` | Annual coupon rate | decimal per year | float | once per bond | Bond terms file | Yes | Step 18 |
| Bond terms | `freq` | Coupons per year | per year | int | once per bond | Bond terms file | Yes | Step 18 |
| Bond terms | `maturity_date` | Gives `years_left` on 30/360 | date | datetime64 | once per bond | Bond terms file | Yes | Step 4 |
| Bond terms | `issue_date` | Gives `years_since_issue` | date | datetime64 | once per bond | Bond terms file | Yes | Step 5 |
| Bond terms | `amount_outstanding` | Face outstanding on that date | USD | float | daily | Bond terms file, with history | Yes | Step 5 |
| Bond terms | `call_type` | `none`, `make_whole` or `fixed_price` | none | str | once per bond | Bond terms file | Yes | Step 2 |
| Bond terms | `next_call_price` | Next call price, for `fixed_price` bonds | per 1 of face | float | daily | Bond terms file | If callable | Step 3 |
| Bond terms | `is_convertible, is_putable, is_sinking, is_perpetual, is_pik` | Option and structure flags | none | bool | once per bond | Bond terms file | Yes | Step 2 |
| Bond trades | `msg_seq, orig_msg_seq` | Report number, and the report this one changes | none | int | per trade report | Enhanced TRACE | Yes | Step 14 |
| Bond trades | `action` | Your vendor's status code, mapped to `new`, `cancel`, `correct` or `reverse` | none | str | per trade report | Enhanced TRACE | Yes | Step 14 |
| Bond trades | `is_duplicate_side` | Second report of an interdealer or agency trade | none | bool | per trade report | Enhanced TRACE | Yes | Step 14 |
| Bond trades | `execution_time, report_time` | When the trade happened and when it became public | timestamp | datetime64 | per trade report | Enhanced TRACE | Yes | Step 17 |
| Bond trades | `prices` | Trade price | percent of par | float | per trade report | Enhanced TRACE | Yes | Step 15 |
| Bond trades | `sizes` | Trade size | USD face | float | per trade report | Enhanced TRACE | Yes | Step 17 |
| Bond trades | `is_customer_buy` | The customer bought | none | bool | per trade report | Enhanced TRACE | Yes | Step 17 |
| Equity | `S` | Closing share price | USD per share | float | daily | CRSP daily | Yes | Step 21 |
| Equity | `daily_log_returns` | Total return, at least 1,000 days before the first trade | decimal | float | daily | CRSP daily | Yes | Step 11 |
| Equity | `dividend` | Cash dividend on its ex-date | USD per share | float | daily | CRSP daily | Yes | Step 64 |
| Equity | corporate actions | Stock dividends and spinoffs, with the price after | USD per share | float | per event | CRSP daily | Yes | Step 10 |
| Accounting | `total_liabilities` | Total liabilities | USD | float | per filing | Compustat or XBRL | Yes | Step 8 |
| Accounting | `shares_outstanding` | Common shares | shares | float | per filing | Compustat or XBRL | Yes | Step 8 |
| Accounting | `acceptance_date` | When the filing became public | date | datetime64 | per filing | EDGAR | Yes | Step 9 |
| Accounting | `period_end, form` | Fiscal period end, and 10-Q or 10-K | date, none | datetime64, str | per filing | EDGAR | Yes | Step 9 |
| Rates | `tenors, par_yields` | Treasury par curve | years, decimal | float array | daily | US Treasury or Fed H.15 | Yes | Step 13 |
| Rates | `r_5y` | 5-year Treasury yield, Yu's `r` | decimal | float | daily | US Treasury or Fed H.15 | Yes | Step 25 |
| Financing | `repo, hedge_repo` | Repo rates on the bond and the Treasury | decimal per year | float | daily | Your desk | Yes | Step 59 |
| Financing | `cash_rate` | Rate on cash and on stock funding | decimal per year | float | daily | Your desk | Yes | Step 60 |
| Financing | `bond_fee, stock_fee` | Borrow fees | decimal per year | float | daily | Your desk or a lending data vendor | Yes | Step 59 |
| Optional | `cds_market` | 5-year CDS spread | decimal | float | daily | Markit | No | Step 43 |
| Optional | `implied_vol` | 1-year at-the-money implied vol | decimal per year | float | daily | OptionMetrics | No | Step 12 |
| Optional | `forced_event` | Dates of calls, tenders, mergers, defaults | none | str | per event | Bond terms file, news | No | Step 67 |
| Optional | `factors` | Market factor excess returns | decimal | float | per month | Index providers | No | Step 76 |

Settings such as `alpha` and `capital` are not data. They are in `BacktestConfig`, under Objects.

---

## What this file is

**Status: this is a method, not a result.** Nothing here has been run on real data. Yu never tested a bond trade. He says so: "this paper does not consider bond-equity or bond-CDS trading strategies" (PDF p. 6). So every bond number below is mine, and none of it is Yu's result.

**How to replicate it.** Each step names one function in `e2c_bond.py`. Its inputs table lists that function's arguments by name, and its outputs table says which later step uses each result. `test_e2c_bond.py` parses this file and fails if a function, an argument or a step reference does not line up. To run everything at once, build a `BondPanel` and call `run_bond_backtest`.

**Tags.**
- **[PAPER]**: comes directly from Yu. Page references are to the April 2005 PDF.
- **[CREDITGRADES]**: comes from the CreditGrades Technical Document. "CGTD p." is the printed page.
- **[ADAPTATION]**: my own reasoning. Each one gives its reason.

A step with two tags has a paper rule with my detail added, and its text says which is which.

**Conventions.** Z-spread is continuously compounded. Day count is 30/360 on corporate bonds, ACT/ACT on Treasuries, and ACT/360 on repo and stock loan. Coupons are semiannual. Recovery is 50% of face. Spreads are decimals in the code and reported in bp. Prices are per 1 of face, and probabilities are decimals. Trade reports stay in percent of par, as TRACE prints them.

**Read this first.**
1. **Bond costs may take most of the edge.** A typical Yu trade earned about 1% to 3% on capital (Table 3, 180 days, with one cell far lower). My planning cost for a bond round trip is 1% to 3% on the same capital (Part 6). Check this before anything else.
2. **Expect a weaker result than Yu's.** Your literature review reports that the classic trade decayed after 2004/05, and one study finds negative Sharpe ratios for 2005 to 2009 (`wiki/analyses/capital-structure-arbitrage-literature-review.md`, line 62).

**The pipeline.**

| Part | What it does | Steps | Brief question |
|---|---|---|---|
| Part 1 | Choose the issuers and the bond | 1 to 7 | 2 |
| Part 2 | Build the inputs | 8 to 13 | 5 |
| Part 3 | Compute the market spread | 14 to 20 | 1 |
| Part 4 | Compute the model value of this bond | 21 to 29 | 3 |
| Part 5 | Calibrate | 30 to 33 | 4 |
| Part 6 | Measure transaction costs | 34 to 37 | 9 |
| Part 7 | Run the signal | 38 to 51 | 4, 6 |
| Part 8 | Construct the trade | 52 to 62 | 7 |
| Part 9 | Daily P&L, capital and return | 63 to 65 | 8 |
| Part 10 | Exit, holding period and stops | 66 to 68 | 10 |
| Part 11 | Run the book and report it | 69 to 76 |  |
| Part 12 | Check it is right before trusting any backtest | 77 to 97 | 13 |

Question 11 is under Point-in-time rules. Question 12 is the first table in this file.

## Objects

These are the types the functions pass around. Fields and defaults are as in `e2c_bond.py`.

| Object | Field | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|---|
| `Firm` | `S` | Share price | USD per share | float | daily |
| `Firm` | `D` | Debt per share | USD per share | float | per filing |
| `Firm` | `sigma_s` | Equity vol | decimal per year | float | daily |
| `Firm` | `L_bar` | Barrier level | ratio | float | once per bond |
| `Firm` | `lam` | Barrier noise | decimal | float | fixed |
| `Firm` | `S_ref` | Reference price. None uses `S` | USD per share | float or None | per trade |
| `Bond` | `coupon` | Annual coupon | decimal per year | float | once per bond |
| `Bond` | `maturity` | Years left | years | float | daily |
| `Bond` | `freq` | Coupons per year | per year | int | once per bond |
| `ZeroCurve` | `tenors`, `zeros` | Maturities and continuous zero rates. `df(t)` gives the discount factor | years, decimal | tuples | daily |
| `VolInversion` | `status`, `sigma_s`, `roots` | See `implied_vol_bond` | none, decimal | str, float, tuple | daily |
| `Position` | `side`, `face`, `shares`, `hedge_face` | Direction and the three positive sizes | +1 or -1, face, shares, face | int, float | per trade |
| `Marks` | `bond_clean`, `bond_accrued`, `stock`, `hedge_full` | Closing marks | per 1 of face, USD per share | float | daily |
| `Marks` | `bond_coupon`, `dividend`, `hedge_coupon` | Cash paid that day | per 1 of face, USD per share | float | daily |
| `Carry` | `repo`, `bond_fee`, `stock_fee`, `cash_rate`, `hedge_repo` | Annual rates | decimal per year | float | daily |
| `Carry` | `dt` | ACT/360 day fraction | years | float | daily |
| `BondPanel` | `coupon`, `freq` | The bond's terms | decimal per year, per year | float, int | once per bond |
| `BondPanel` | `years_left`, `clean` | Maturity. Clean price, NaN if none | years, per 1 of face | float array | daily |
| `BondPanel` | `S`, `D`, `sigma_s`, `dividend` | Stock, debt per share, the run's vol, cash dividend | USD per share, decimal per year | float array | daily |
| `BondPanel` | `zero_tenors`, `zeros`, `r_5y` | Curve maturities, zero rates (days by tenors), 5-year yield | years, decimal | tuple, float matrix, float array | daily |
| `BondPanel` | `repo`, `bond_fee`, `stock_fee`, `cash_rate`, `hedge_repo` | Financing rates | decimal per year | float array | daily |
| `BondPanel` | `day_fraction`, `calendar_day` | ACT/360 fraction since the last row. Day count of each row | years, days | float array | daily |
| `BondPanel` | `peer_gap`, `round_trip`, `tradable` | From `peer_median_gap`, `measured_round_trip` or `planning_round_trip`, and the Part 1 screens | log ratio, per 1 of face, none | float array, bool array | daily |
| `BondPanel` | `sibling_gap`, `cds_market`, `implied_vol`, `forced_event` | Optional, None if missing | log ratio, decimal, decimal per year, none | float array or None | daily |
| `CdsPanel` | `c`, `S`, `D`, `sigma_s`, `r`, `dividend`, `day_fraction`, `calendar_day` | Yu's inputs, one obligor | as above | float array | daily |
| `BacktestConfig` | `alpha`, `beta`, `space` | Triggers. `space` is `spread` or `vol`. Defaults 0.5, 0.20, `spread` | decimal, none | float, str | per run |
| `BacktestConfig` | `capital`, `max_hold`, `lag`, `calibration_days`, `overlapping` | Defaults 0.5, 180, 1, 20, False. Yu's 0.5, 180, 0, 10, True | as above | float, int, bool | per run |
| `BacktestConfig` | `R_b`, `lam`, `hold` | Defaults 0.5, 0.3, `asset_vol` | decimal, none | float, str | per run |
| `BacktestConfig` | `peer_adjust`, `use_cost_gate`, `rehedge`, `max_drawdown` | Defaults True, True, True, None | none, decimal | bool, float or None | per run |
| `BacktestConfig` | `cost_multiple`, `stock_half`, `hedge_half`, `bid_ask` | Defaults 1, 0.0005, 0.00005, 0.05 (CDS only) | ratio, share of price, per 1 of face, decimal | float | per run |
| `TradeResult` | `side`, `signal_day`, `entry_day`, `exit_day`, `reason` | What happened | +1 or -1, row, none | int, str | per trade |
| `TradeResult` | `face`, `shares`, `hedge_face` | Sizes | face, shares | float | per trade |
| `TradeResult` | `hpr`, `max_drawdown`, `converged`, `final_value` | Net P&L over capital, largest fall from peak, ended by convergence, last account value | decimal | float, bool | per trade |
| `TradeResult` | `legs`, `daily_returns` | Totals by leg and cost. Return by row | per 1 of CDS-equivalent notional, decimal | dict | per trade |
| `BacktestResult` | `trades`, `daily_returns`, `z_market`, `z_model`, `L_bar`, `fit_rmse`, `status` | See `run_bond_backtest` | as listed there | list, float arrays, float, str | per run |

**Helpers,** which are not steps of their own:

| Function | What it does |
|---|---|
| `flat_curve(r)` | A `ZeroCurve` at one rate. |
| `cash_flows(bond)` | Payment times and amounts, stepped back from maturity. The first coupon is whole. |
| `accrued_interest(bond)` | Coupon earned since the last payment, on 30/360. |
| `price_from_z(z, bond, curve)` | Full price at a Z-spread. |
| `calibrate_barrier(model_spreads, market_spreads, bounds)` | The least-squares fit behind `fit_barrier_on_bond` and `fit_barrier_on_cds`. |

---

## Part 1. Choose the issuers and the bond

Answers question 2. Run these daily, using only what is known that day.

**Maturity mismatch against the 5-year CDS logic.** You do not need to map the bond to 5 years. `risky_bond_price` prices the bond's own cash flows, so the model spread already has the bond's maturity. The bond rolls down each day, and the model rolls with it. `cds_equivalent_face` then sizes the trade to the spread risk of a 5-year CDS. **Main alternative:** interpolate a constant-maturity issuer spread and trade the nearest bond. That removes the roll, but it adds curve-fitting error on sparse prints.

### Step 1. Keep the eligible issuers [PAPER]

**Function:** `issuer_is_eligible(sector, has_listed_equity)`

Keep non-financial, non-utility issuers with listed common stock. Yu excludes the others because "their capital structure is more difficult to interpret" (PDF p. 16).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `sector` | Issuer's sector | none | `str` | daily |
| `has_listed_equity` | The issuer has a listed common stock | none | `bool` | daily |

**Formula**

```
issuer_ok = has_listed_equity and sector not in (financial, utility)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `issuer_ok` | The issuer may enter the universe | none | Step 51 |

### Step 2. Keep plain senior unsecured bonds [ADAPTATION]

**Function:** `bond_terms_are_eligible(seniority, currency, coupon_type, call_type, is_convertible, is_putable, is_sinking, is_perpetual, is_pik)`

Keep senior unsecured USD fixed-coupon bonds, with no option other than a call. Treat a make-whole call as a bullet. *Reason: Yu's CDS refers to senior unsecured debt, and his R = 0.5 is the senior unsecured rate (PDF pp. 14, 18). The price formula needs known cash flows. CGTD p. 32 warns that convertibles distort the basis.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `seniority` | Ranking of the bond | none | `str` | once per bond |
| `currency` | Currency of the bond | none | `str` | once per bond |
| `coupon_type` | `fixed` or other | none | `str` | once per bond |
| `call_type` | `none`, `make_whole` or `fixed_price` | none | `str` | once per bond |
| `is_convertible` | Convertible flag | none | `bool` | once per bond |
| `is_putable` | Put flag | none | `bool` | once per bond |
| `is_sinking` | Sinking fund flag | none | `bool` | once per bond |
| `is_perpetual` | No maturity date | none | `bool` | once per bond |
| `is_pik` | Pay-in-kind flag | none | `bool` | once per bond |

**Formula**

```
terms_ok = seniority is senior_unsecured, currency is USD, coupon_type is fixed,
           call_type is none, make_whole or fixed_price, and every option flag is False
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `terms_ok` | The bond's terms fit the price formula | none | Step 51 |

### Step 3. Screen fixed-price callable bonds [ADAPTATION]

**Function:** `callable_is_usable(call_type, clean_price, next_call_price, buffer)`

Use a fixed-price callable only if its clean price is at least 5 points under the next call price. Value it to maturity. *Reason: far from the call, it trades near a bullet. The 5 points is my judgement.* **Main alternative:** vendor OAS, with the model priced to the worst date. **Risk:** high-yield names often have only callable bonds, so this may remove many. Measure how many before you rely on it.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `call_type` | From the bond's terms | none | `str` | once per bond |
| `clean_price` | Market clean price | per 1 of face | `float` | daily |
| `next_call_price` | Next call price. Ignored unless `fixed_price` | per 1 of face | `float` | daily |
| `buffer` | Required distance. Default 0.05 | per 1 of face | `float` | fixed |

**Formula**

```
callable_ok = call_type is not fixed_price, or clean_price <= next_call_price - buffer
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `callable_ok` | The bond can be treated as a bullet today | none | Step 51 |

### Step 4. Screen on maturity [ADAPTATION]

**Function:** `maturity_is_eligible(years_left, issuer_has_core_bond)`

Require 3 to 7 years left. Accept 2 to 10 if the issuer has nothing in 3 to 7. *Reason: Yu's contract is 5-year, and the model's term structure is untested elsewhere.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `years_left` | Time to maturity | years | `float` | daily |
| `issuer_has_core_bond` | The issuer has a bond with 3 to 7 years left | none | `bool` | daily |

**Formula**

```
maturity_ok = 3 <= years_left <= 7, or (not issuer_has_core_bond and 2 <= years_left <= 10)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `maturity_ok` | The maturity is acceptable | none | Step 6 |

### Step 5. Screen on age and size [ADAPTATION]

**Function:** `age_and_size_are_eligible(years_since_issue, years_left, amount_outstanding)`

Require at least 3 months since issue, at least 1 year left, and at least USD 250mm outstanding. *Reason: new issues carry a concession, and very short or small bonds trade thinly. These cut-offs are my judgement.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `years_since_issue` | Time since issue | years | `float` | daily |
| `years_left` | Time to maturity | years | `float` | daily |
| `amount_outstanding` | Face outstanding on that date | USD | `float` | daily |

**Formula**

```
size_ok = years_since_issue >= 0.25 and years_left >= 1 and amount_outstanding >= 250e6
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `size_ok` | The age and size are acceptable | none | Step 6 |

### Step 6. Pick one bond and its sibling [ADAPTATION]

**Function:** `pick_bond_and_sibling(bond_ids, trades_60d)`

Among the issuer's bonds that pass the screens, pick the one with the most institutional trades over the last 60 days. Keep the next one as the sibling. *Reason: your literature review (line 117) reports that lead-lag results depend on bond choice, and that the most traded bond behaves differently.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond_ids` | Identifiers of the issuer's eligible bonds | none | `list of str` | daily |
| `trades_60d` | Trades of USD 100k or more in the last 60 days, per bond | count | `list of int` | daily |

**Formula**

```
bond    = the bond with the highest trades_60d
sibling = the bond with the next highest, or None
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `bond` | The bond the trade uses | none | Step 17 |
| `sibling` | The second bond, used only as a check | none | Step 42 |

### Step 7. Screen on recent trading [ADAPTATION]

**Function:** `passes_liquidity_screen(institutional_trades_5d, minimum)`

Require at least 10 trades of USD 100k or more in the last 5 business days. If a bond fails, open nothing that day. *Reason: Eq. (8) on a stale print is noise.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `institutional_trades_5d` | Trades of USD 100k or more in the last 5 business days | count | `int` | daily |
| `minimum` | Required count. Default 10 | count | `int` | fixed |

**Formula**

```
liquid = institutional_trades_5d >= minimum
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `liquid` | The bond is liquid enough today | none | Step 51 |

---

## Part 2. Build the inputs

Answers question 5 on equity vol.

**What Yu uses.** He uses the "1,000-day historical equity volatility" (PDF p. 17). He gives no formula. It enters only through asset vol in Eq. (13). The CGTD found 750 and 1,000 days closest to CDS-implied asset vol, and short windows worse (CGTD p. 18). So do not shorten the realised window to react faster. If you want faster reaction, use implied vol.

### Step 8. Compute debt per share [PAPER]

**Function:** `debt_per_share(total_liabilities, shares_outstanding)`

Divide total liabilities by common shares outstanding (PDF p. 17). **Main alternative:** the CGTD formula, financial debt plus half of other liabilities, less a minority adjustment (CGTD pp. 47-48). I keep Yu's because `D` enters only through `L̄D`, so the fit absorbs the level.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `total_liabilities` | Total liabilities from the filing | USD | `float` | per filing |
| `shares_outstanding` | Common shares from the filing | shares | `float` | per filing |

**Formula**

```
D = total_liabilities / shares_outstanding
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `D` | Debt per share | USD per share | Step 10, Step 21 |

### Step 9. Date each filing [ADAPTATION]

**Function:** `filing_usable_from(acceptance_date, period_end, form)`

Use a filing only from the next business day after its public acceptance. With no acceptance date, lag 45 days for a 10-Q and 90 days for a 10-K. Hold `D` fixed until the next filing is usable. *Reason: Yu lags one month from quarter end (PDF p. 14). That is earlier than many filings, so it can look ahead. The SEC deadlines here are from memory, so check them.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `acceptance_date` | Public acceptance date, or `NaT` if unknown. EDGAR gives UTC, so convert it first | date | `datetime64` | per filing |
| `period_end` | Fiscal period end | date | `datetime64` | per filing |
| `form` | `10-Q` or `10-K` | none | `str` | per filing |

**Formula**

```
usable_from = next business day after acceptance_date
if acceptance_date is NaT:
    usable_from = period_end + 45 days (10-Q) or + 90 days (10-K), rolled forward to a business day
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `usable_from` | First day that D from this filing may be used | date | Step 21 |

### Step 10. Adjust debt through a stock dividend or spinoff [PAPER]

**Function:** `debt_after_corporate_action(firm_before, S_after, T, R, r)`

On a stock dividend or spinoff, change `D` so that the model spread does not jump (footnote 14, PDF pp. 14-15). Cash dividends and stock splits need no adjustment to the model spread. Keep the adjusted `D` until the next filing.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `firm_before` | The firm just before the event | see Objects | `Firm` | per event |
| `S_after` | Share price just after the event | USD per share | `float` | per event |
| `T` | CDS maturity. Use 5 | years | `float` | fixed |
| `R` | CDS recovery | decimal | `float` | fixed |
| `r` | Risk-free rate | decimal | `float` | per event |

**Formula**

```
solve for D_after:  c(T; S_after, D_after) = c(T; S_before, D_before)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `D_after` | Debt per share to use after the event | USD per share | Step 21 |

### Step 11. Compute the 1,000-day equity vol [PAPER] [ADAPTATION]

**Function:** `historical_equity_vol(daily_log_returns, window, min_obs, periods_per_year)`

Yu specifies the 1,000-day horizon. The estimator is my reading: the sample standard deviation of daily total-return log changes, over the last 1,000 trading days to today's close, annualised. Require at least 750 days. *Reason: Yu gives no formula, and 750 is the shorter window the CGTD supports.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `daily_log_returns` | Daily log total returns up to today, adjusted for splits | decimal | `float array` | daily |
| `window` | Days used. Default 1,000 | days | `int` | fixed |
| `min_obs` | Fewest days allowed. Default 750 | days | `int` | fixed |
| `periods_per_year` | Annualising factor. Default 252 | days | `int` | fixed |

**Formula**

```
historical_vol = std(last window returns, ddof=1) * sqrt(periods_per_year)
NaN if fewer than min_obs returns
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `historical_vol` | Equity vol from history | decimal per year | Step 12 |

### Step 12. Choose the vol source for the run [ADAPTATION]

**Function:** `equity_vol_input(source, historical_vol, implied_vol)`

Run the whole method twice: once on historical vol, once on 1-year at-the-money implied vol. Refit `L̄` for each run. Never mix the two. *Reason: Yu names implied vol as an untried improvement (PDF p. 11). The CGTD says historical vol lags in a sudden move (CGTD p. 32), and its Tyco case reaches the market spread only with higher vol (CGTD p. 33). Cremers et al. (2008, PDF p. 2) find that implied vol level and skew beat historical vol for bond spreads. Caveat: implied vol runs above realised vol on average (Cremers, PDF p. 9), so the fitted `L̄` will be lower.* **Main alternative:** 1-year 25-delta put implied vol, as Bai and Wu use (PDF p. 6). It sits closer to default risk.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `source` | `historical` or `implied` | none | `str` | per run |
| `historical_vol` | From the previous step | decimal per year | `float` | daily |
| `implied_vol` | 1-year at-the-money implied vol, at the close | decimal per year | `float` | daily |

**Formula**

```
sigma_s = historical_vol if source is historical, else implied_vol
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `sigma_s` | The equity vol this run uses | decimal per year | Step 21 |

### Step 13. Build the Treasury zero curve [ADAPTATION]

**Function:** `zero_curve_from_par_yields(tenors, par_yields)`

Each day, bootstrap public par yields into continuously compounded zero rates. *Reason: Yu's flat `r` works for a 5-year CDS. A bond needs each cash flow discounted at its own date. The survival curve does not depend on `r`, so a full curve is allowed.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `tenors` | Par yield maturities | years | `float array` | daily |
| `par_yields` | Treasury par yields, semiannual | decimal | `float array` | daily |

**Formula**

```
for tenors under 0.5:   z(t) = ln(1 + y t) / t
on a 6-month grid:      DF_i = (1 − (y_i/2) Σ_{j<i} DF_j) / (1 + y_i/2)
                        z_i  = −ln(DF_i) / t_i
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `curve` | Zero curve, with `curve.df(t)` the discount factor | see Objects | Step 19, Step 27, Step 28 |

---

## Part 3. Compute the market spread

Answers question 1.

**Recommendation: Z-spread over the Treasury zero curve.**
- *Why Z:* it uses the bond's own cash flows and the whole curve. The model can produce the same number by the same solver.
- *Why not OAS:* OAS needs a rate-vol model, and vendor versions cannot be reproduced. For a bullet, OAS and Z are nearly the same anyway.
- *Why not yield spread:* it mixes in curve slope and coupon. Keep it as a sanity check only.
- *Why Treasury:* it matches Yu's `r` and it is public and dated.
- **Main alternative:** a SOFR zero curve, which is closer to CDS convention. Yu says the bond and CDS link needs a proper "risk-free" reference interest rate (PDF p. 6). Use it if you add CDS, and refit `L̄` when you switch.
- *Why the curve matters:* in the example, raising the curve 30 bp moves market Z by -30.0 bp and model Z by only -1.0 bp. So any drift between the curve and the true risk-free rate goes straight into the signal. `peer_adjusted_signal` is the control for that.

### Step 14. Drop cancelled, corrected and duplicate reports [ADAPTATION]

**Function:** `clean_trade_reports(msg_seq, orig_msg_seq, action, is_duplicate_side)`

Remove cancellations, reversals, what they and corrections replace, and duplicate sides. *Reason: Dickerson et al. (2026, PDF p. 8) make this the first filter, citing Dick-Nielsen (2014).* I did not have Dick-Nielsen's paper, so this follows Dickerson's summary. Map your vendor's status codes onto `action` yourself.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `msg_seq` | Report sequence number | none | `int array` | per trade report |
| `orig_msg_seq` | The report this one changes, 0 if none | none | `int array` | per trade report |
| `action` | `new`, `cancel`, `correct` or `reverse` | none | `str array` | per trade report |
| `is_duplicate_side` | Second report of an interdealer or agency trade | none | `bool array` | per trade report |

**Formula**

```
keep = action in (new, correct)
       and msg_seq not in the orig_msg_seq of any non-new report
       and not is_duplicate_side
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `keep` | Mask of reports to keep | none | Step 15 |

### Step 15. Correct misplaced decimals [ADAPTATION]

**Function:** `fix_decimal_shifts(prices, half_window)`

Correct prices entered with the decimal in the wrong place, using Dickerson et al.'s rules (Appendix A.1, PDF pp. 46-48). *Reason: a price of 925 for 92.5 would otherwise fire the signal.* The window uses later trades, so run it only on prints known by the signal day's close.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `prices` | Prices of kept reports, in time order | percent of par | `float array` | per trade report |
| `half_window` | Trades on each side of the anchor. Default 5 | count | `int` | fixed |

**Formula**

```
anchor = median of distinct prices in the window around the trade
raw    = abs(price − anchor) / anchor
if raw > 0.05, try factor f in (0.1, 0.01, 10, 100). Accept the smallest error where:
    error = abs(f·price − anchor) / anchor
    error <= 0.02, or abs(f·price − anchor) <= 8, or both within 15 points of par
    error <= 0.20 · raw
    5 <= f·price <= 300
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `fixed_prices` | Prices with decimal errors corrected | percent of par | Step 16 |

### Step 16. Flag spikes that revert [ADAPTATION]

**Function:** `flag_price_spikes(prices, threshold, forward, window, slack, alpha)`

Flag a price that jumps and comes back within 5 trades. This is the core of Dickerson et al.'s bounce-back filter (Appendix A.2, PDF pp. 47-49). I omit their flag reassignment and par-block rules. I add one condition: the price must stand away from its baseline, so the return to normal is not flagged as a second spike.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `prices` | Prices after the previous step | percent of par | `float array` | per trade report |
| `threshold` | Jump size. Default 35 | percent of par | `float` | fixed |
| `forward` | Trades scanned for reversion. Default 5 | count | `int` | fixed |
| `window` | Trailing trades for the baseline. Default 5 | count | `int` | fixed |
| `slack` | Tolerance on the threshold. Default 1 | percent of par | `float` | fixed |
| `alpha` | Fraction of threshold counted as back at baseline. Default 0.25 | decimal | `float` | fixed |

**Formula**

```
base = median of distinct unflagged prices in the trailing window
moved = price − base
candidate if abs(moved) > alpha·threshold and
    (abs(price change) >= threshold − slack, or abs(moved) >= threshold − slack, or price = 100)
flag if, within forward trades, a price returns within alpha·threshold of base,
    or a change of opposite sign reaches threshold − slack
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `flagged` | Mask of spikes to drop | none | Step 17 |

### Step 17. Compute the daily clean price [ADAPTATION]

**Function:** `daily_clean_price(prices, sizes, is_customer_buy, min_size)`

Take the volume-weighted price of trades of USD 100k or more, for customer buys and customer sells separately. Average the two. If only one side traded, use it and note the flag. *Reason: averaging the two sides reduces bid-ask bounce. Dickerson et al. use daily volume-weighted prices (PDF p. 8).*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `prices` | Clean, unflagged prices up to the equity close | percent of par | `float array` | per trade report |
| `sizes` | Trade sizes | USD face | `float array` | per trade report |
| `is_customer_buy` | The customer bought | none | `bool array` | per trade report |
| `min_size` | Smallest trade used. Default 100,000 | USD face | `float` | fixed |

**Formula**

```
clean = mean( VWAP of buys, VWAP of sells ) / 100
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `clean` | Daily clean price, NaN if no trade | per 1 of face | Step 18, Step 69 |
| `one_sided` | Only one side traded | none | Step 69 |

### Step 18. Add accrued interest [ADAPTATION]

**Function:** `full_price(clean, bond)`

Add accrued interest to get the full price. Day count is 30/360.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `clean` | From the previous step | per 1 of face | `float` | daily |
| `bond` | The bond today | see Objects | `Bond` | daily |

**Formula**

```
accrued = coupon · (1/freq − time to next coupon)
P_full  = clean + accrued
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `P_full` | Market full price | per 1 of face | Step 19, Step 64 |

### Step 19. Solve for the market Z-spread [ADAPTATION]

**Function:** `z_spread(price, bond, curve)`

Find the spread over the zero curve that reprices the bond at its full price.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `price` | Full price, `P_full` | per 1 of face | `float` | daily |
| `bond` | The bond today | see Objects | `Bond` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |

**Formula**

```
price = Σ_i CF_i · DF(t_i) · exp(−Z_mkt · t_i)     solve for Z_mkt
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `Z_mkt` | Market Z-spread | decimal (report in bp) | Step 31, Step 38, Step 46, Step 20 |

### Step 20. Compute the bond's duration [ADAPTATION]

**Function:** `dollar_duration(bond, z, curve)`

Compute the price change per unit of yield, at constant spread. For a bullet this is both rate duration and spread duration, in price terms.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond today | see Objects | `Bond` | daily |
| `z` | `Z_mkt`, or 0 for a Treasury | decimal | `float` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |

**Formula**

```
D_b = Σ_i t_i · CF_i · DF(t_i) · exp(−z · t_i)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `D_b` | Dollar duration | years | Step 44, Step 53, Step 56 |

---

## Part 4. Compute the model value of this bond

Answers question 3. Steps through `cds_par_spread` are Yu's and CreditGrades's. The last three adapt them to a bond.

**How recovery differs from a CDS, and why it matters.**
- A CDS pays `1 − R` of notional. That does not depend on any bond's price.
- A bondholder loses `P − R_b`. A bond at 70 loses much less than a bond at 110.
- So a discount bond's spread sits below the CDS spread, and a premium bond's sits above it. On the example firm, the 5-year CDS is 170.6 bp. Model Z is 158.3 bp at a 2% coupon, 170.0 bp at 5.5%, and 179.9 bp at 9%.
- **Therefore never compare a bond's Z with a CDS spread or with a 5-year CreditGrades number.** That gap is arithmetic, not mispricing. CGTD p. 32 lists bonds away from par among the causes of basis.
- I use recovery of face. A bankruptcy claim is on par plus accrued, not on the current market price. I ignore recovery on accrued, which is small.
- **Main alternative:** recovery of market value, the idea behind the discount rate in Yu's "Value" variant (PDF p. 32). It removes the discount effect above, so it cannot explain the difference between a 70 bond and a 110 bond.

**What links a bond to the CDS (derived by me, confirmed in tests).** With a continuous coupon `C`, recovery of face and flat `r`:

```
P = 1 + (C − r − c) · A,   where A is the CDS annuity and c is the CDS spread
```

So a par bond has `C − r = c` exactly, and its Z-spread equals the CDS spread. Its equity delta also equals the CDS delta, with the sign flipped.

With semiannual coupons there is a small gap. Default falls between coupon dates, so the accrued coupon is lost. For a flat hazard `h = c/(1−R)`:

```
Z_par − c ≈ (r + c) · R · h / (2 · freq)
```

| CDS spread | Z minus CDS, semiannual | Formula | Monthly | Daily |
|---:|---:|---:|---:|---:|
| 4.2 bp | +0.05 bp | +0.04 bp | +0.01 bp | +0.00 bp |
| 112.2 bp | +1.51 bp | +1.44 bp | +0.24 bp | +0.01 bp |
| 410.8 bp | +8.67 bp | +8.33 bp | +1.40 bp | +0.05 bp |
| 815.8 bp | +25.66 bp | +24.80 bp | +4.14 bp | +0.14 bp |

The gap comes from the coupon timing and not from the credit model. Comparing Z with Z avoids it, because both sides have the same coupons.

### Step 21. Compute asset vol [PAPER] [CREDITGRADES]

**Function:** `asset_vol(firm)`

Convert equity vol to asset vol with today's price, Eq. (13). CGTD 3.1 does the same (CGTD p. 18). Set `S_ref` only to hold asset vol fixed, as in the hedge ratio.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `firm` | `S`, `D` (from the filing usable today), `sigma_s`, `L_bar`, `lam`, `S_ref` | see Objects | `Firm` | daily |

**Formula**

```
σ = σ_S · S / (S + L̄D)        with S_ref in place of S if it is set
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `sigma` | Asset vol | decimal per year | Step 23 |

### Step 22. Compute the distance to the barrier [PAPER] [CREDITGRADES]

**Function:** `barrier_distance(firm)`

Compute `d` from the firm value `V_0 = S + L̄D` (Yu p. 33, CGTD 2.29).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `firm` | As above | see Objects | `Firm` | daily |

**Formula**

```
d = ((S + L̄D) / (L̄D)) · exp(λ²)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `d` | Distance to the barrier | ratio | Step 23 |

### Step 23. Compute the survival curve [PAPER] [CREDITGRADES]

**Function:** `survival(t, firm)`

Compute survival to each time, Eq. (11), CGTD 2.28. `q(0)` is below 1 whenever `λ > 0`. Both sources say so (Yu footnote 22, CGTD p. 8). It is not a bug.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `t` | Horizons | years | `float or array` | daily |
| `firm` | As above | see Objects | `Firm` | daily |

**Formula**

```
A_t² = σ² t + λ²
q(t) = Φ(−A_t/2 + ln d / A_t) − d · Φ(−A_t/2 − ln d / A_t)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `q` | Survival probability | decimal | Step 24, Step 25, Step 27, Step 28, Step 33 |

### Step 24. Compute H(T) [PAPER] [CREDITGRADES]

**Function:** `discounted_default(T, firm, r)`

Compute the discounted default density (Yu p. 34, CGTD A.14). **Trap:** the closed form loses all its digits when `rξ` is large. The error reached 595 bp at S/D = 0.1 and `σ_S` = 6.4%. So the code switches to quadrature above `rξ = 30`.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `T` | Maturity | years | `float` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `r` | Flat rate, the 5-year Treasury yield | decimal | `float` | daily |

**Formula**

```
ξ = λ²/σ²     z = sqrt(1/4 + 2r/σ²)
G(u) = d^(z+1/2) Φ(−ln d/(σ√u) − zσ√u) + d^(−z+1/2) Φ(−ln d/(σ√u) + zσ√u)
H(T) = exp(rξ) · ( G(T+ξ) − G(ξ) )
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `H` | Discounted default density from 0 to T | decimal | Step 26 |

### Step 25. Compute the CDS annuity [PAPER] [CREDITGRADES]

**Function:** `cds_annuity(T, firm, r)`

Compute the value of 1 per year paid until default or `T`. This is Yu's Eq. (14) **with `G(ξ)` in place of his `G(T)`, which is a misprint** (see `01_paper_extraction.md`, Section 13).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `T` | Maturity. Use 5 for sizing | years | `float` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `r` | Flat rate | decimal | `float` | daily |

**Formula**

```
A(T) = ∫_0^T exp(−rs) q(s) ds = ( q(0) − q(T) exp(−rT) − H(T) ) / r
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `A` | Survival-weighted annuity | years | Step 26, Step 53, Step 34 |

### Step 26. Compute the CDS par spread [PAPER] [CREDITGRADES]

**Function:** `cds_par_spread(T, firm, R, r, act360)`

Compute the model CDS spread, Yu's Eq. (12), CGTD 2.15. `act360=True` scales by 360/365, the CGTD convention that Yu's formula does not state.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `T` | Maturity | years | `float` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `R` | CDS recovery | decimal | `float` | fixed |
| `r` | Flat rate | decimal | `float` | daily |
| `act360` | Scale by 360/365. Default False | none | `bool` | fixed |

**Formula**

```
c(0,T) = r (1−R) (1 − q(0) + H(T)) / (q(0) − q(T) exp(−rT) − H(T))
       = (1−R) (1 − q(0) + H(T)) / A(T)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `c_model` | Model CDS spread | decimal (report in bp) | Step 43, Step 47 |

### Step 27. Compute the default leg on any curve [ADAPTATION]

**Function:** `default_leg(T, firm, curve)`

Compute the present value of 1 paid at default. Same object as the numerator of Eq. (12), on a full curve. The test suite checks that the two agree on a flat curve.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `T` | Bond maturity | years | `float` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |

**Formula**

```
L = 1 − q(0) + Σ_j DF(s_mid,j) · (q(s_j−1) − q(s_j))     with steps of 1/48 year
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `L` | Default leg | decimal | Step 28 |

### Step 28. Compute the model's full price of this bond [ADAPTATION]

**Function:** `risky_bond_price(bond, firm, curve, R_b)`

Price the bond's own cash flows on the survival curve. Recovery is `R_b` of face, whatever the bond's price is. The `1 − q(0)` inside `L` is the default mass at time zero, kept so the bond matches Eq. (12).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond today | see Objects | `Bond` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |
| `R_b` | Bond recovery, a share of face | decimal | `float` | fixed |

**Formula**

```
P_model = Σ_i CF_i · DF(t_i) · q(t_i)  +  R_b · L(T)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `P_model` | Model full price | per 1 of face | Step 29, Step 54, Step 46 |

### Step 29. Convert to a model spread [ADAPTATION]

**Function:** `model_z_spread(bond, firm, curve, R_b)`

Solve for the Z-spread of `P_model`, using the same solver, curve and dates as the market spread. *Reason: this is what makes it like against like.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond today | see Objects | `Bond` | daily |
| `firm` | As above | see Objects | `Firm` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |
| `R_b` | Bond recovery | decimal | `float` | fixed |

**Formula**

```
P_model = Σ_i CF_i · DF(t_i) · exp(−Z_model · t_i)     solve for Z_model
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `Z_model` | Model Z-spread | decimal (report in bp) | Step 31, Step 38, Step 39, Step 44 |

---

## Part 5. Calibrate

Answers the first half of question 4.

**What the calibration absorbs.** One number fit at the start absorbs any constant level difference. That covers wrong `D`, wrong `R`, wrong vol level, the model's shape, and for a bond, its non-default premium on those days.

**What it does not absorb.** Everything that changes later:
- Market-wide liquidity shocks that widen bonds without moving stocks.
- Bond-specific flows: new issues, index deletions, forced selling after a downgrade.
- Moves in the bond-CDS basis.
- Stale or wrong prints.

The CGTD says the model has no inputs for these (CGTD p. 32). Your literature review adds that most investment-grade spread is not credit risk (line 81), so this matters most for investment grade.

**A side effect to watch.** The fit puts the premium into the barrier, and that changes the hedge. In the example, a +40 bp premium moves `L̄` from 0.84 to 1.08 and the delta by +13%. A -40 bp difference moves `L̄` to 0.63 and the delta by -16%.

Part 7 holds the extra controls a bond needs.

### Step 30. Fix recovery and barrier noise [PAPER]

**Function:** `yu_fixed_parameters()`

Fix `R_b = 0.5` and `λ = 0.3` (PDF p. 17). My standing convention for senior unsecured is 40%. I use 0.5 here because Yu specifies it. In the example, moving to 0.4 changes `L̄` from 0.84 to 0.69 and the delta by +5%.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `(none)` | No inputs | none | none | fixed |

**Formula**

```
R_b = 0.5
λ   = 0.3
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `R_b` | Bond recovery | decimal | Step 31 |
| `lam` | Standard deviation of log recovery | decimal | Step 31 |

### Step 31. Fit the barrier [PAPER] [ADAPTATION]

**Function:** `fit_barrier_on_bond(bonds, S, D, sigma_s, z_market, curves, R_b, lam)`

Fit `L̄` by least squares on the spread, over the bond's first eligible days. Never refit it (PDF pp. 18, 20). Yu fits 10 days of CDS. I use 20 liquid days of the bond, and run 10 as a sensitivity. *Reason: Yu fits a dealer composite. A bond's daily price is noisier, and one bad fit stays for the whole sample. The number 20 is my judgement.* If the bond changes, refit.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bonds` | The bond on each fit day | see Objects | `list of Bond` | once per bond |
| `S` | Share prices | USD per share | `float array` | once per bond |
| `D` | Debt per share | USD per share | `float array` | once per bond |
| `sigma_s` | Equity vols | decimal per year | `float array` | once per bond |
| `z_market` | Market Z on each fit day | decimal | `float array` | once per bond |
| `curves` | Zero curve on each fit day | see Objects | `list of ZeroCurve` | once per bond |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `lam` | Barrier noise | decimal | `float` | fixed |

**Formula**

```
L̄ = argmin Σ_days ( Z_model(L̄) − z_market )²     over 0.01 <= L̄ <= 3
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `L_bar` | Fitted barrier level, locked afterwards | ratio | Step 32, Step 33 |
| `rmse` | Fit error | decimal | Final output |

### Step 32. Read the fit [ADAPTATION]

**Function:** `fit_status(L_bar, bounds)`

Drop the bond if the fit hits a bound. Flag it for review if `L̄ > 1`. *Reason: a fit on a bound means the model cannot reach the market. `L̄ > 1` puts the barrier above debt, so the fit is probably absorbing something other than default risk.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `L_bar` | From the previous step | ratio | `float` | once per bond |
| `bounds` | Fit range. Default (0.01, 3) | ratio | `tuple` | fixed |

**Formula**

```
reject if L_bar is on a bound
review if L_bar > 1
ok otherwise
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `status` | `ok`, `review` or `reject` | none | Step 69 |

### Step 33. Drop firms too close to the barrier [ADAPTATION]

**Function:** `passes_barrier_filter(firm, max_atom)`

Drop an issuer-day where `1 − q(0) > 1%`. That trips at `S/(L̄D) < 1.06` when `λ = 0.3`. *Reason: near the barrier, the default mass at time zero sets a floor under the spread, and the model stops responding.* Yu has no such filter. His CCC bucket (LEV 0.82, about S/D = 0.22) would fail it.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `firm` | The firm today, with the fitted `L_bar` | see Objects | `Firm` | daily |
| `max_atom` | Largest allowed `1 − q(0)`. Default 0.01 | decimal | `float` | fixed |

**Formula**

```
barrier_ok = 1 − q(0) <= max_atom
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `barrier_ok` | The model still responds for this firm | none | Step 51 |

---

## Part 6. Measure transaction costs

Answers question 9. `trade_cost` in Part 8 charges these on a position.

**What Yu does.** He charges a 5% bid/ask on the CDS spread and nothing on stock (PDF pp. 13-14). In price terms, at 100 bp and a 4.3 annuity a round trip costs 0.215 points. At 300 bp and a 4.1 annuity it costs 0.615 points.

**What this means for you (my arithmetic, rough).** I assume spreads of 60 bp and 300 bp, and `F = 1`. Yu's mean 180-day returns in Table 3 are after his own CDS costs. Adding those back gives about 1.1% to 1.3% for investment grade and about 4% for speculative grade at `α = 0.5`. Against that, the planning table below takes about 1% and 2% to 3%. That leaves little for investment grade and only 1% to 2% for speculative grade, before the rate hedge. At `α = 2`, Yu's speculative mean is 0.05%, so that cell goes negative.

### Step 34. Express Yu's CDS cost in price [PAPER]

**Function:** `yu_cds_round_trip(spread, annuity, bid_ask)`

Turn Yu's 5% bid/ask into price terms, as the comparison for bond costs (PDF pp. 13-14). A buyer pays `1.025 c` and a seller receives `0.975 c`.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `spread` | CDS spread | decimal | `float` | daily |
| `annuity` | `A`, from `cds_annuity` | years | `float` | daily |
| `bid_ask` | Bid/ask as a share of the spread. Default 0.05 | decimal | `float` | fixed |

**Formula**

```
round_trip = bid_ask · spread · annuity
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `yu_round_trip` | Yu's CDS round trip | per 1 of notional | Final output |

### Step 35. Measure the bond's round-trip cost [ADAPTATION]

**Function:** `measured_round_trip(buy_prices, buy_sizes, sell_prices, sell_sizes)`

Take customer-buy minus customer-sell volume-weighted price, over the last 20 days. Your HY project already builds this as `bid_ask_pts` (`FundamentalQuantmental/hy/backtest.py:15`). *Reason: bond costs are not proportional to spread, and a measured number beats any assumption.* Do not charge this if you execute at a one-sided customer price, because it is already in that price.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `buy_prices` | Customer-buy prices, last 20 days | percent of par | `float array` | per trade report |
| `buy_sizes` | Their sizes | USD face | `float array` | per trade report |
| `sell_prices` | Customer-sell prices, last 20 days | percent of par | `float array` | per trade report |
| `sell_sizes` | Their sizes | USD face | `float array` | per trade report |

**Formula**

```
round_trip = ( VWAP(buys) − VWAP(sells) ) / 100
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `round_trip` | Measured round-trip cost | per 1 of face | Step 37, Step 44, Step 61 |

### Step 36. Fall back on planning numbers [ADAPTATION]

**Function:** `planning_round_trip(rating, z)`

Where no measure exists, use this table. **These are my planning numbers. They are not from a source.** On capital, at `F = 1` and `K = 0.5`, they cost 1%, 2%, 3% and 6%. One anchor: your Dynkin card records a CDS cost of 25% of the bond cost (`FundamentalQuantmental/research/cards/dynkin-et-al-2021-chapter-implementations.md:781`). Against Yu's 0.215 points at 100 bp, that implies about 0.86 points for a bond.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `rating` | Rating at entry | none | `str` | per trade |
| `z` | `Z_mkt` at entry | decimal | `float` | per trade |

**Formula**

```
BBB or better              0.50 points
BB                         1.00 points
B                          1.50 points
CCC, or spread over 1,000 bp  3.00 points
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `round_trip` | Planning round-trip cost | per 1 of face | Step 37, Step 44, Step 61 |

### Step 37. Stress the cost [PAPER] [ADAPTATION]

**Function:** `stressed_cost(round_trip, multiple)`

Rerun at twice the cost. Yu does this in "Trans", which cuts his mean monthly return by 10 to 18 bp (Table 7). I add three times the cost in stress months, because bid-ask widens then (`docs/methodology.md:91`).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `round_trip` | From either step above | per 1 of face | `float` | daily |
| `multiple` | 1 in the base run, 2 in the stress run | ratio | `float` | per run |

**Formula**

```
stressed = round_trip · multiple
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `stressed` | Cost used in the run | per 1 of face | Step 61, Step 69 |

---

## Part 7. Run the signal

Answers the second half of question 4 and all of question 6.

**In spread space,** `entry_signal` is Yu's trigger. `peer_adjusted_signal`, `sibling_confirms` and `cds_confirms` are the extra controls for illiquidity and basis.

**I am least sure of `peer_adjusted_signal` and `sibling_confirms`.** Neither has been tested, and without CDS nothing here can separate basis from mispricing. **Main alternative:** regress the log gap on bond illiquidity and trade the residual. Your HY methodology already lists the fields: bid-ask, log amount outstanding, trace count, bond age (`FundamentalQuantmental/docs/methodology.md:622`). Check VIF if you do this, because those fields are correlated. I prefer the peer median first because it has no fitted coefficients to look ahead with.

**In vol space,** invert the model to find the equity vol that would justify the bond's spread. Then compare it with observed equity vol. Yu describes the idea (PDF p. 10) and the CGTD defines it for CDS (CGTD p. 13). The bond version is mine.

**Why a bond can have two implied vols and a CDS cannot.**
- For a CDS, raising vol lowers `q(t)` at every `t`. So the annuity falls, protection rises, and the spread rises. The root is unique.
- A bond with coupon under the risk-free rate can trade below recovery in the forward market. Then default helps the holder, and the price turns back up as vol rises.
- A bond with coupon at or above `r` cannot do this. In the Part 4 identity, its price falls as vol rises, in the continuous-coupon case. Every scan I ran on such bonds agrees.

**How the two signals relate.**
- For one bond on one day, they are the same signal on a different scale. If `Z_model` rises with vol, both change sign together, and the exit is identical. A test confirms this.
- Across names they differ. In the example, `α = 0.5` equals `β = 0.090` at S/D = 3, `β = 0.207` at S/D = 0.94, and `β = 0.317` at S/D = 0.6.
- So a fixed `α` is easy to reach for safe names. Yu's Table 3 fits this reading: at `α = 2`, his investment-grade names average 87 trades each and his speculative names 23 (my division).
- A fixed `β` treats names more evenly. That is the case for running both.

**Against option-implied vol.** Comparing `σ_imp` with option-implied vol is the trade in Guo (2016) as your literature review reports it (line 248), and in Shi et al. (2022, PDF p. 4). Shi et al. report a Sharpe of 2.97 before costs on CDS (PDF p. 2). They find the link holds with deep out-of-the-money puts and not at-the-money options (PDF p. 6). Treat that as a reason to test, not as an expected result.

### Step 38. Apply Yu's trigger [PAPER]

**Function:** `entry_signal(market, model, alpha)`

Apply Eq. (8), with `Z_mkt` as `c_t` and `Z_model` as `c'_t` (PDF p. 20). Test `α = 0.5, 1, 2`, as Yu does. If either spread is at or below zero there is no signal, which is my addition: a Treasury-based Z can be negative for very safe names.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `market` | `Z_mkt` | decimal | `float` | daily |
| `model` | `Z_model` | decimal | `float` | daily |
| `alpha` | Trigger | decimal | `float` | per run |

**Formula**

```
signal = +1 if market > (1 + α) · model     long bond, short stock
signal = −1 if model > (1 + α) · market     short bond, long stock
signal =  0 otherwise
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `signal` | Raw signal | +1, 0 or -1 | Step 51, Step 69 |

### Step 39. Compute the log gap [ADAPTATION]

**Function:** `log_gap(market, model)`

Write Eq. (8) as a gap: it fires when the size of this gap exceeds `ln(1 + α)`. Your HY methodology prefers the log form for the same reason (`docs/methodology.md:627`).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `market` | `Z_mkt` | decimal | `float` | daily |
| `model` | `Z_model` | decimal | `float` | daily |

**Formula**

```
gap = ln(market / model)     NaN if either is at or below zero
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `gap` | Log gap | log ratio | Step 40, Step 41, Step 42 |

### Step 40. Compute the peers' gap [ADAPTATION]

**Function:** `peer_median_gap(peer_gaps)`

Take the median log gap across same-rating, same-maturity-bucket peers today. *Reason: in a liquidity shock, every bond looks cheap against its model. Without this, the book becomes one large long-credit bet.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `peer_gaps` | Each peer's `gap` today | log ratio | `float array` | daily |

**Formula**

```
peer_gap = median(peer_gaps, ignoring NaN)     0 if there are no peers
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `peer_gap` | Common move | log ratio | Step 41 |

### Step 41. Remove the common move [ADAPTATION]

**Function:** `peer_adjusted_signal(gap, peer_gap, alpha)`

Apply Eq. (8) to the gap after removing the peers' median. Run the raw `entry_signal` too, as the comparison with Yu.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `gap` | This bond's log gap | log ratio | `float` | daily |
| `peer_gap` | From the previous step | log ratio | `float` | daily |
| `alpha` | Trigger | decimal | `float` | per run |

**Formula**

```
adjusted = gap − peer_gap
signal = sign(adjusted) if abs(adjusted) > ln(1 + α), else 0
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `signal` | Signal net of the common move | +1, 0 or -1 | Step 51 |

### Step 42. Check the sibling bond [ADAPTATION]

**Function:** `sibling_confirms(gap, sibling_gap)`

If a sibling exists and its log gap has the opposite sign, or is less than half the size, skip the trade. *Reason: a gap in one bond only is a flow in that bond, not a gap between debt and equity.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `gap` | This bond's log gap | log ratio | `float` | daily |
| `sibling_gap` | The sibling's log gap. NaN if there is none | log ratio | `float` | daily |

**Formula**

```
sibling_ok = no sibling, or (same sign and abs(sibling_gap) >= 0.5 · abs(gap))
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `sibling_ok` | The sibling agrees | none | Step 51 |

### Step 43. Check the CDS, if you have it [ADAPTATION]

**Function:** `cds_confirms(signal, cds_market, cds_model, alpha)`

Run Eq. (8) on the issuer's CDS as well. Trade the bond only when the CDS signal has the same sign. *Reason: if only the bond disagrees, that is a basis trade, which is a different strategy.* With no CDS, this check passes.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `signal` | This bond's signal | +1, 0 or -1 | `int` | daily |
| `cds_market` | 5-year CDS spread. NaN if none | decimal | `float` | daily |
| `cds_model` | `c_model` for the same firm | decimal | `float` | daily |
| `alpha` | Trigger | decimal | `float` | per run |

**Formula**

```
cds_ok = no CDS, or entry_signal(cds_market, cds_model, α) = signal
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `cds_ok` | The CDS agrees | none | Step 51 |

### Step 44. Apply a cost gate [ADAPTATION]

**Function:** `passes_cost_gate(market, model, duration, round_trip, multiple)`

Require full convergence to pay at least twice the round-trip cost. *Reason: a trade that cannot pay for itself on full convergence is not worth opening. Your HY methodology has the same rule (`docs/methodology.md:779`), and full convergence is rare in Yu (Table 3).*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `market` | `Z_mkt` | decimal | `float` | daily |
| `model` | `Z_model` | decimal | `float` | daily |
| `duration` | `D_b`, from `dollar_duration` | years | `float` | daily |
| `round_trip` | Round-trip cost | per 1 of face | `float` | daily |
| `multiple` | Required multiple. Default 2 | ratio | `float` | fixed |

**Formula**

```
cost_ok = abs(market − model) · duration >= multiple · round_trip
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `cost_ok` | The trade can pay for itself | none | Step 51 |

### Step 45. Check long-bond trades against implied vol [ADAPTATION]

**Function:** `implied_vol_confirms(signal, z_market, bond, firm, implied_vol, curve, R_b, alpha)`

When implied vol exists, recompute `Z_model` with it. Open a long-bond trade only if Eq. (8) still fires. *Reason: this is Yu's third possibility, that the vol estimate is too low (PDF p. 11). It also targets his worst outcome, selling protection into a blowout. Untested.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `signal` | This bond's signal | +1, 0 or -1 | `int` | daily |
| `z_market` | `Z_mkt` | decimal | `float` | daily |
| `bond` | The bond today | see Objects | `Bond` | daily |
| `firm` | The firm today | see Objects | `Firm` | daily |
| `implied_vol` | Implied vol. NaN if none | decimal per year | `float` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `alpha` | Trigger | decimal | `float` | per run |

**Formula**

```
vol_ok = signal is not +1, or no implied vol, or
         entry_signal(z_market, Z_model(σ_S = implied_vol), α) = signal
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `vol_ok` | Implied vol does not explain the gap | none | Step 51 |

### Step 46. Solve for the credit-implied equity vol [ADAPTATION]

**Function:** `implied_vol_bond(z_market, bond, firm, curve, R_b, recovery_buffer, grid)`

Find the equity vol at which the model price equals the market full price, holding `S`, `D`, `L̄`, `λ`, `R_b` and the curve fixed. Scan `σ_S` from 2% to 400% on a grid and find every root.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `z_market` | `Z_mkt` | decimal | `float` | daily |
| `bond` | The bond today | see Objects | `Bond` | daily |
| `firm` | The firm today | see Objects | `Firm` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `recovery_buffer` | Refuse prices under `R_b` plus this. Default 0.10. -1 turns it off | per 1 of face | `float` | fixed |
| `grid` | Vols to scan. Default 80 points from 0.02 to 4 | decimal per year | `float array` | fixed |

**Formula**

```
P_market = price at z_market
solve P_model(σ_S) = P_market at every sign change of the gap on the grid

status:
  near_recovery  P_market < R_b + recovery_buffer. Guards against the two-root case
  below_floor    no root, spread too low. Barrier noise gives a positive spread even at
                 near-zero vol (15.3 bp at S/D = 0.5). Also any negative Z
  above_ceiling  no root, spread too high. The model price cannot fall much below R_b.
                 A CDS has no such ceiling. Usually distress, or R_b too high
  multiple       two or more roots. A 2%, 20-year bond at 48, with r = 6%, has roots at
                 35.9% and 171.7%
  ok             one root
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `inversion` | `status`, `sigma_s` and `roots` | see Objects | Step 48, Step 49 |

### Step 47. Solve for the CDS-implied equity vol [CREDITGRADES]

**Function:** `implied_vol_cds(c_market, T, firm, R, r, lo, hi)`

The CDS version, as the CGTD defines it (p. 13). Use it when you have CDS, to compare with the bond's implied vol.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `c_market` | CDS spread | decimal | `float` | daily |
| `T` | Maturity | years | `float` | daily |
| `firm` | The firm today | see Objects | `Firm` | daily |
| `R` | CDS recovery | decimal | `float` | fixed |
| `r` | Flat rate | decimal | `float` | daily |
| `lo` | Lowest vol. Default 0.01 | decimal per year | `float` | fixed |
| `hi` | Highest vol. Default 5 | decimal per year | `float` | fixed |

**Formula**

```
solve c(T; σ_S) = c_market     the root is unique because c rises with σ_S
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `inversion` | `status`, `sigma_s` and `roots` | see Objects | Final output |

### Step 48. Read the inversion status [ADAPTATION]

**Function:** `vol_status_allows_trade(inversion)`

Only one clean root may trade. For any other status, log it and open nothing.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `inversion` | From `implied_vol_bond` | see Objects | `VolInversion` | daily |

**Formula**

```
vol_status_ok = inversion.status is ok
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `vol_status_ok` | The vol signal may be read | none | Step 49 |

### Step 49. Apply the trigger in vol space [ADAPTATION]

**Function:** `vol_entry_signal(sigma_imp, sigma_obs, beta)`

Apply the form of Eq. (8) to vols. Start with `β = 0.20` and test 0.10 and 0.30. These are my choice. Yu tested no such values. Use the same `σ_obs` as your run: 1,000-day or implied. Exit on the same crossing as in spread space.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `sigma_imp` | `inversion.sigma_s` | decimal per year | `float` | daily |
| `sigma_obs` | `sigma_s` of the run | decimal per year | `float` | daily |
| `beta` | Vol trigger | decimal | `float` | per run |

**Formula**

```
signal = +1 if σ_imp > (1 + β) · σ_obs     long bond, short stock
signal = −1 if σ_obs > (1 + β) · σ_imp     short bond, long stock
signal =  0 otherwise
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `signal` | Signal in vol space | +1, 0 or -1 | Step 51 |

### Step 50. Translate alpha into beta [ADAPTATION]

**Function:** `beta_equivalent_to_alpha(alpha, bond, firm, curve, R_b)`

Find the vol trigger that fires exactly where `α` fires, for this bond today. Use it to choose a sensible `β`, and to see how uneven a fixed `α` is across names.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `alpha` | Spread trigger | decimal | `float` | per run |
| `bond` | The bond today | see Objects | `Bond` | daily |
| `firm` | The firm today | see Objects | `Firm` | daily |
| `curve` | Zero curve today | see Objects | `ZeroCurve` | daily |
| `R_b` | Bond recovery | decimal | `float` | fixed |

**Formula**

```
β = σ_imp( (1 + α) · Z_model ) / σ_S − 1
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `beta_equivalent` | The matching vol trigger | decimal | Final output |

### Step 51. Decide the trade [ADAPTATION]

**Function:** `decide_entry(signal, tradable, barrier_ok, sibling_ok, cds_ok, cost_ok, vol_ok)`

Pass the signal only if every check passes. Feed in `issuer_ok`, `terms_ok`, `callable_ok` and `liquid` together as `tradable`. For a vol-space run, `signal` comes from `vol_entry_signal`.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `signal` | From `peer_adjusted_signal`, `entry_signal` or `vol_entry_signal` | +1, 0 or -1 | `int` | daily |
| `tradable` | All of the Part 1 screens | none | `bool` | daily |
| `barrier_ok` | From `passes_barrier_filter` | none | `bool` | daily |
| `sibling_ok` | From `sibling_confirms` | none | `bool` | daily |
| `cds_ok` | From `cds_confirms` | none | `bool` | daily |
| `cost_ok` | From `passes_cost_gate` | none | `bool` | daily |
| `vol_ok` | From `implied_vol_confirms` | none | `bool` | daily |

**Formula**

```
side = signal if every check is True, else 0
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `side` | +1 long bond, short stock. -1 short bond, long stock. 0 no trade | +1, 0 or -1 | Step 52, Step 57 |

---

## Part 8. Construct the trade

Answers question 7.

| | Long-bond trade | Short-bond trade |
|---|---|---|
| Signal | Market spread too wide | Market spread too tight |
| Yu's equivalent | Sell protection, short stock | Buy protection, buy stock |
| Bond | Long, financed in repo | Short, borrowed in reverse repo |
| Stock | Short, pays borrow fee and dividends | Long, funded at the cash rate, receives dividends |
| Treasury | Short, earns repo | Long, pays repo |
| Coupons | Receives | Pays |
| Worst case | Spreads keep widening, or a buyout lifts the stock and hurts the bond | Bond rallies while stock falls |

### Step 52. Trade on the next day [ADAPTATION]

**Function:** `execution_day(signal_day, lag)`

Trade at the next day's price, never at the signal day's price. *Reason: the same price error feeds both the signal and the return, and creates profit that does not exist (Dickerson et al., PDF pp. 11-12). This is the single most important guard against fooling yourself. Yu trades at the signal-day mark, which suits a composite quote better than a single bond print.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `signal_day` | Row of the signal | row | `int` | per trade |
| `lag` | Days to wait. Default 1. 0 exists only for `lag_sensitivity` | days | `int` | per run |

**Formula**

```
entry_day = signal_day + lag
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `entry_day` | Row of the trade | row | Step 69 |

### Step 53. Size the bond [ADAPTATION]

**Function:** `cds_equivalent_face(bond, z, curve, annuity_5y)`

Size the bond to the spread risk of a 5-year CDS. *Reason: Yu's 1 of notional has spread risk `A_5y`. A 7-year bond per 1 of face has much more. This keeps `K = 0.5` meaning the same thing.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond at entry | see Objects | `Bond` | per trade |
| `z` | `Z_mkt` at entry | decimal | `float` | per trade |
| `curve` | Zero curve at entry | see Objects | `ZeroCurve` | per trade |
| `annuity_5y` | `A` at T = 5 | years | `float` | per trade |

**Formula**

```
F = annuity_5y / D_b
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `F` | Bond face | per 1 of CDS-equivalent notional | Step 57 |

### Step 54. Compute the equity hedge ratio [ADAPTATION]

**Function:** `bond_equity_delta(bond, firm, curve, R_b, hold)`

Differentiate the model price with respect to the share price, at entry. **Yu does not say which vol stays fixed.** I hold asset vol fixed: the CGTD does this (CGTD p. 36, Figures 2.3 to 2.5), and it treats asset vol as stable (CGTD p. 19). **Main alternative:** hold equity vol fixed, which gives a delta 2.2 times smaller in the example (0.00251 against 0.00560). I am unsure of this choice. `empirical_hedge_slope` tests it on data.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond at entry | see Objects | `Bond` | per trade |
| `firm` | The firm at entry | see Objects | `Firm` | per trade |
| `curve` | Zero curve at entry | see Objects | `ZeroCurve` | per trade |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `hold` | `asset_vol` or `equity_vol`. Default `asset_vol` | none | `str` | per run |

**Formula**

```
delta = ( P_model(S + h) − P_model(S − h) ) / (2h)     h = 1% of S
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `delta` | Shares per 1 of face. Positive | shares | Step 57, Step 70 |

### Step 55. Choose the Treasury [ADAPTATION]

**Function:** `par_hedge_bond(years_left, curve, freq)`

Use a Treasury with the bond's maturity, priced at par on the curve. It stands in for the listed Treasury closest in maturity. **Main alternative:** a pay-fixed swap or Treasury futures.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `years_left` | The bond's maturity at entry | years | `float` | per trade |
| `curve` | Zero curve at entry | see Objects | `ZeroCurve` | per trade |
| `freq` | Coupons per year. Default 2 | per year | `int` | fixed |

**Formula**

```
coupon = freq · (1 − DF(T)) / Σ_i DF(t_i)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `hedge_bond` | The Treasury | see Objects | Step 56 |

### Step 56. Compute the rate hedge ratio [ADAPTATION]

**Function:** `rate_hedge_face(bond, z, hedge_bond, curve)`

Match the bond's rate risk with the Treasury. *Reason: Yu has no rate hedge because a CDS carries little rate risk. A bond does. In the example, 10 bp on rates moves the bond 0.38 points, the same as 10 bp on spread.* *Caveat: credit spreads tend to fall when rates rise, so measured rate duration on risky bonds can be below this number. Measure it before trusting the hedge on high yield.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond` | The bond | see Objects | `Bond` | per trade |
| `z` | `Z_mkt` | decimal | `float` | per trade |
| `hedge_bond` | From the previous step | see Objects | `Bond` | per trade |
| `curve` | Zero curve | see Objects | `ZeroCurve` | per trade |

**Formula**

```
hedge_ratio = D_b / D_t     D_t is the same sum for the Treasury, with z = 0
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `hedge_ratio` | Treasury face per 1 of bond face | ratio | Step 57, Step 58 |

### Step 57. Build the position [PAPER] [ADAPTATION]

**Function:** `build_position(side, face, delta, hedge_ratio)`

Set the three legs. Yu fixes the equity hedge at entry and does not rebalance it (PDF p. 11), and he finds that daily rebalancing does not help (Table 7). The sizes are my adaptation.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `side` | From `decide_entry` | +1 or -1 | `int` | per trade |
| `face` | `F` | per 1 of CDS-equivalent notional | `float` | per trade |
| `delta` | From `bond_equity_delta` | shares | `float` | per trade |
| `hedge_ratio` | From `rate_hedge_face` | ratio | `float` | per trade |

**Formula**

```
shares     = face · delta
hedge_face = face · hedge_ratio
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `pos` | `side`, `face`, `shares`, `hedge_face` | see Objects | Step 61, Step 64 |

### Step 58. Decide when to re-set the rate hedge [ADAPTATION]

**Function:** `rate_hedge_is_due(current_hedge_face, target_hedge_face, days_since_reset, max_drift, max_days)`

Re-set the Treasury monthly, or when it drifts over 5% from target. Yu's static rule applies to the equity only. *Reason: the bond's duration rolls down each day, and an unmanaged rate hedge adds noise. Rule of thumb, my judgement.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `current_hedge_face` | `hedge_face` now | per 1 of CDS-equivalent notional | `float` | daily |
| `target_hedge_face` | `F · hedge_ratio` today | per 1 of CDS-equivalent notional | `float` | daily |
| `days_since_reset` | Calendar days since the last re-set | days | `float` | daily |
| `max_drift` | Largest drift. Default 0.05 | decimal | `float` | fixed |
| `max_days` | Longest gap. Default 30 | days | `float` | fixed |

**Formula**

```
due = days_since_reset >= max_days, or abs(current / target − 1) > max_drift
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `due` | Re-set the Treasury today | none | Step 69 |

### Step 59. Finance the bond [ADAPTATION]

**Function:** `bond_financing_rate(side, repo, bond_fee)`

A long bond pays the repo rate on its full price. A short bond earns the repo rate less a borrow fee. *Reason: this makes the bond a zero-cost position, like a CDS at inception.* I did not verify market levels for repo, haircuts or bond borrow fees, so use your desk's figures. Asquith et al. (2013) study corporate bond lending, but I have not read it and do not quote it.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `side` | `pos.side` | +1 or -1 | `int` | per trade |
| `repo` | Repo rate | decimal per year | `float` | daily |
| `bond_fee` | Bond borrow fee | decimal per year | `float` | daily |

**Formula**

```
rho_b = repo if side = +1, else repo − bond_fee
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `rho_b` | Rate on the bond's financing | decimal per year | Step 64 |

### Step 60. Finance the stock [ADAPTATION]

**Function:** `stock_financing_rate(side, cash_rate, stock_fee)`

A short stock earns the cash rate less the borrow fee. A long stock pays the cash rate. Skip any name flagged hard to borrow. `side` is the bond's side, so `side = +1` means short stock.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `side` | `pos.side` | +1 or -1 | `int` | per trade |
| `cash_rate` | Cash rate | decimal per year | `float` | daily |
| `stock_fee` | Stock borrow fee | decimal per year | `float` | daily |

**Formula**

```
rho_s = cash_rate − stock_fee if side = +1, else cash_rate
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `rho_s` | Rate on the stock's financing | decimal per year | Step 64 |

### Step 61. Charge the cost of one side [ADAPTATION]

**Function:** `trade_cost(pos, marks, bond_half, stock_half, hedge_half)`

Charge half the round trip at entry and half at exit, on face `F`. Add 5 bp per side on the stock and 0.005 points per side on the Treasury. *Reason: Yu can ignore stock costs with a static hedge. On a bond trade they are still small, but they are real.*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `pos` | From `build_position` | see Objects | `Position` | per trade |
| `marks` | Marks on the trade day | see Objects | `Marks` | per trade |
| `bond_half` | Half of the stressed round trip | per 1 of face | `float` | per trade |
| `stock_half` | Default in the run 0.0005 | share of price | `float` | fixed |
| `hedge_half` | Default in the run 0.00005 | per 1 of face | `float` | fixed |

**Formula**

```
cost = face · bond_half + shares · S · stock_half + hedge_face · hedge_half
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `cost` | Cost of entering or of leaving | per 1 of CDS-equivalent notional | Step 62, Step 65 |

### Step 62. Open the margin account [PAPER] [ADAPTATION]

**Function:** `opening_account_value(capital, entry_cost)`

Yu sets capital at `K = 0.5` per 1 of notional, in a margin account that coupons, dividends and financing flow through (footnote 12, PDF p. 12). I take off the entry cost. `K = 0.1` is not usable here, because bond repo haircuts can exceed it.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `capital` | `K` | per 1 of CDS-equivalent notional | `float` | per run |
| `entry_cost` | `cost` at entry | per 1 of CDS-equivalent notional | `float` | per trade |

**Formula**

```
V_0 = capital − entry_cost
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `V_0` | Account value after entry | per 1 of CDS-equivalent notional | Step 65 |

---

## Part 9. Daily P&L, capital and return

Answers question 8.

**A CDS needs a model to be marked. A bond does not.** Yu's Eq. (6) marks the CDS with a model annuity. A bond has a price. So the bond leg's P&L is free of the model, and only the hedge ratios depend on it.

**Why this is an excess return.** Every leg is financed, and the capital sits apart. If `K` earns the risk-free rate, that interest cancels against the risk-free rate you subtract. So you can drop both. Yu uses "excess" but does not spell this out, so this is my reading of it.

**Why returns are comparable with Yu.** `K = 0.5` per unit of 5-year spread risk matches his capital base, and the return has the same form that his limited liability rule implies (PDF p. 20). The bond version does add rate-hedge noise and funding that his CDS does not have.

### Step 63. Count coupons paid [ADAPTATION]

**Function:** `coupons_paid(before, after)`

Work out the coupon cash between two dates. **Do not skip this.** The full price falls by the coupon on the payment date, and the holder receives it. My first version of the example missed this and understated the bond leg by 3 points.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `before` | The bond on the earlier date | see Objects | `Bond` | daily |
| `after` | The bond on the later date | see Objects | `Bond` | daily |

**Formula**

```
cash = coupon / freq · (payments left before − payments left after)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `coupon_cash` | Coupon paid in the window | per 1 of face | Step 64 |

### Step 64. Compute each leg's daily P&L [ADAPTATION]

**Function:** `daily_pnl(pos, prev, now, carry)`

Compute each leg from close `t−1` to close `t`. `s` is `pos.side`, `F` is `face`, `n` is `shares`, `h` is `hedge_face`. `P` is the bond's full price and `T` the Treasury's. `Δt` is the ACT/360 day fraction.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `pos` | From `build_position` | see Objects | `Position` | per trade |
| `prev` | Marks at close `t−1` | see Objects | `Marks` | daily |
| `now` | Marks at close `t`, with cash paid on day `t` | see Objects | `Marks` | daily |
| `carry` | Financing rates and `dt` for day `t` | see Objects | `Carry` | daily |

**Formula**

```
bond_price      =  s · F · (P_t − P_{t−1} + coupon_t)
bond_financing  = −s · F · P_{t−1} · rho_b · Δt
stock_price     = −s · n · (S_t − S_{t−1} + dividend_t)
stock_financing =  s · n · S_{t−1} · rho_s · Δt
hedge_price     = −s · h · (T_t − T_{t−1} + coupon^T_t)
hedge_financing =  s · h · T_{t−1} · repo^T · Δt
total           =  the sum of the six
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `legs` | The six legs and `total` | per 1 of CDS-equivalent notional | Step 65, Step 69 |

### Step 65. Update the account and the return [PAPER] [ADAPTATION]

**Function:** `next_account_value(value, pnl)`

Add the day's P&L, less any exit cost. Yu needs a positive account for the return to exist, which is why he liquidates at zero (PDF p. 20). I write his unstated return formula the way that sentence implies.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `value` | `V_{t−1}` | per 1 of CDS-equivalent notional | `float` | daily |
| `pnl` | `total` less any exit cost | per 1 of CDS-equivalent notional | `float` | daily |

**Formula**

```
V_t = V_{t−1} + pnl
r_t = pnl / V_{t−1}
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `V_t` | Account value | per 1 of CDS-equivalent notional | Step 66, Step 68 |
| `r_t` | Daily excess return | decimal | Step 71 |

---

## Part 10. Exit, holding period and stops

Answers question 10.

**Do Yu's rules carry over?** Mostly yes, but a bond needs more. Limited liability did not bind at `K = 0.5` in Yu's Table 3, where the worst single trade is -88.71%. It may bind for a bond.

**Stop.** Run the base case with no stop, as Yu does. Run one variant with a 20% drawdown stop, from the trade's peak value, filled at the next day's price. *Reason: Yu counts 20% drawdowns (`N2`) without acting on them (PDF p. 20), and he notes that hedge funds use such limits (footnote 18).* A stop may not fill at the mark on an illiquid bond, so rerun that variant with `cost_multiple=2`.

### Step 66. Apply Yu's exits [PAPER]

**Function:** `exit_reason(side, market, model, days_held, max_hold, value)`

Exit on the first of limited liability, convergence, or the end of the holding period (PDF pp. 12, 20). The end of the sample also closes a trade. I read 180 days as calendar days, because Yu treats it as about six months (PDF p. 13). Yu does not state it.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `side` | `pos.side` | +1 or -1 | `int` | daily |
| `market` | `Z_mkt` | decimal | `float` | daily |
| `model` | `Z_model` | decimal | `float` | daily |
| `days_held` | Calendar days since entry | days | `float` | daily |
| `max_hold` | Holding period. Yu tests 30 and 180 | days | `float` | per run |
| `value` | `V_t` | per 1 of CDS-equivalent notional | `float` | daily |

**Formula**

```
limited_liability   if value < 0
convergence         if side · (market − model) <= 0
holding_period      if days_held >= max_hold
none                otherwise
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `reason` | Why to exit, or None | none | Step 67 |

### Step 67. Apply the exits a bond needs [ADAPTATION]

**Function:** `bond_exit_reason(side, market, model, days_held, max_hold, value, years_left, days_since_price, forced_event, max_drawdown, peak_value)`

Add these to Yu's exits. *A call or tender: the cash flows no longer match the price formula. Under 1 year left: the bond no longer fits the 5-year logic. No clean price for 14 days: Yu uses the same limit as a data filter (PDF p. 15) and says liquidity loss forces an exit. A merger: this is Yu's "sure case of divergence", spreads up and stock up (PDF p. 12). A default: Yu models none in the trade, and a bond must, because the holder bears it directly. Recalled bond borrow: a short cannot stay open.* Execute on the next day's price, except limited liability, which closes at once. A crossing on a thin day should not count. In `run_bond_backtest`, leave `clean` as NaN on thin days.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `side` | `pos.side` | +1 or -1 | `int` | daily |
| `market` | `Z_mkt` | decimal | `float` | daily |
| `model` | `Z_model` | decimal | `float` | daily |
| `days_held` | Calendar days since entry | days | `float` | daily |
| `max_hold` | Holding period | days | `float` | per run |
| `value` | `V_t` | per 1 of CDS-equivalent notional | `float` | daily |
| `years_left` | Time to maturity | years | `float` | daily |
| `days_since_price` | Calendar days since the last clean price | days | `float` | daily |
| `forced_event` | `called`, `tender`, `merger`, `default`, `borrow_recalled`, or None | none | `str or None` | daily |
| `max_drawdown` | Stop level. None in the base run | decimal | `float or None` | per run |
| `peak_value` | Highest `V_t` so far | per 1 of CDS-equivalent notional | `float or None` | daily |

**Formula**

```
limited_liability   if value < 0
the event's name    if forced_event
no_price_14_days    if days_since_price > 14
under_one_year      if years_left < 1
drawdown_stop       if value < peak_value · (1 − max_drawdown)
else exit_reason
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `reason` | Why to exit, or None | none | Step 69 |

### Step 68. Measure the drawdown [PAPER]

**Function:** `drawdown_from_peak(values)`

Compute the largest fall from a running peak. Yu counts trades over 20% as `N2` (PDF p. 20). His table only fits a peak-based measure: a final return of -4.63% at worst, with `N2 = 1` (see `01_paper_extraction.md`, Section 14).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `values` | `V_t` over the trade | per 1 of CDS-equivalent notional | `float array` | per trade |

**Formula**

```
drawdown = max( (running peak − V_t) / running peak )
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `max_drawdown` | Largest fall from peak | decimal | Step 73 |

---

## Part 11. Run the book and report it

Runs every step above and reports it in Yu's columns.

**Two books.** Yu's index adds a new position on every qualifying day, and his trigger at `α = 0.5` fires on about half of all days. You cannot do that in a bond, and paying costs on each one would be wrong. So set `overlapping=True` for the comparison with Yu, and `overlapping=False` for the strategy you could actually trade.

### Step 69. Run the whole method on one bond [PAPER] [ADAPTATION]

**Function:** `run_bond_backtest(panel, config)`

Run Yu's logic with the bond steps in place of the CDS ones. Yu's logic: fit once, read Eq. (8) daily, hold a static equity hedge, exit by his rules, return on capital. The bond steps are mine. Pass the Part 1 screens in `panel.tradable`.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | One bond's daily data | see Objects | `BondPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |

**Formula**

```
z_spread on every priced day
fit_barrier_on_bond on the first calibration_days tradable days, then fit_status
model_z_spread on every day
for each later day i:
    1. mark each live trade: daily_pnl, rate_hedge_is_due, bond_exit_reason,
       trade_cost if closing, next_account_value
    2. read the signal: entry_signal, peer_adjusted_signal or vol_entry_signal,
       then decide_entry. Schedule it for execution_day
    3. open what was scheduled for today: cds_equivalent_face, bond_equity_delta,
       par_hedge_bond, rate_hedge_face, build_position, trade_cost,
       opening_account_value
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `trades` | List of `TradeResult` | see Objects | Step 73, Step 75, Step 95, Final output |
| `daily_returns` | Matrix, days by trades, NaN when not live | decimal | Step 71, Final output |
| `z_market` | Market Z each day | decimal | Step 92, Final output |
| `z_model` | Model Z each day | decimal | Final output |
| `L_bar` | Fitted barrier | ratio | Final output |
| `fit_rmse` | Fit error | decimal | Final output |
| `status` | `ok`, `review`, `reject` or `too_few_days` | none | Final output |

### Step 70. Test the hedge on data [ADAPTATION]

**Function:** `empirical_hedge_slope(bond_changes, stock_changes)`

Regress daily changes in the bond's full price, hedged for rates, on stock changes over the prior year. Compare the slope with both model deltas. *Reason: this settles the choice in `bond_equity_delta` for your data. Your literature review reports that hedge ratios are where structural models work best (line 80, Schaefer and Strebulaev).*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `bond_changes` | Daily change in rate-hedged full price | per 1 of face | `float array` | daily |
| `stock_changes` | Daily change in share price | USD per share | `float array` | daily |

**Formula**

```
slope = OLS coefficient of bond_changes on stock_changes, with an intercept
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `slope` | Measured hedge ratio | shares per 1 of face | Final output |
| `slope_se` | Its standard error | shares per 1 of face | Final output |

### Step 71. Build the monthly index [PAPER]

**Function:** `monthly_index(daily_returns, month_ids)`

Each day, average the returns of live trades with equal weight. Compound to monthly. A month with no trade has zero return (PDF pp. 28-29).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `daily_returns` | From `run_bond_backtest`, trades joined across bonds | decimal | `float matrix` | daily |
| `month_ids` | Month of each row | none | `int array` | daily |

**Formula**

```
r_day   = mean of live trades' returns, 0 if none
r_month = Π_days (1 + r_day) − 1
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `monthly` | Monthly excess returns | decimal | Step 72, Step 74, Step 76 |

### Step 72. Compute the Sharpe ratio [PAPER]

**Function:** `annual_sharpe(monthly_excess)`

Annualise from monthly returns. This form lands within rounding of all 18 Sharpe values in Yu's Tables 4 and 7. The standard error of an annual Sharpe is about `sqrt(12 / months)`, which is 0.5 for Yu's 48 months. So a short sample cannot confirm or reject a Yu-sized effect.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `monthly_excess` | Monthly excess returns | decimal | `float array` | per month |

**Formula**

```
sharpe = sqrt(12) · mean / std(ddof=1)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `sharpe` | Annualised Sharpe | ratio | Step 74 |

### Step 73. Summarise the trades [PAPER]

**Function:** `trade_summary(trades)`

Report the columns of Yu's Tables 2 and 3.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `trades` | From `run_bond_backtest` | see Objects | `list of TradeResult` | per run |

**Formula**

```
N   trades
N1  trades ending in convergence
N2  trades with drawdown over 20%
N3  trades with a negative return
mean, min, max of the trade returns
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `summary` | `N`, `N1`, `N2`, `N3`, `mean`, `min`, `max` | count and decimal | Step 84, Step 96, Final output |

### Step 74. Summarise the months [PAPER]

**Function:** `monthly_summary(monthly)`

Report the columns of Yu's Table 4. `N` counts non-zero months. Median and share negative use every month. Yu's Spec row at `α = 2` (N = 25, Neg = 0.29, median 0) only fits that reading: 14/48.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `monthly` | From `monthly_index` | decimal | `float array` | per month |

**Formula**

```
N, mean, median, min, max, std, first-order autocorrelation,
share negative, Sharpe
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `monthly_stats` | The Table 4 columns | count and decimal | Final output |

### Step 75. Report by direction and rating [ADAPTATION]

**Function:** `summaries_by_group(trades, labels)`

Report `trade_summary` by direction, and by rating at entry. *Reason: Yu does not report by direction, and his worst risk sits in one direction (abstract, PDF p. 2).*

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `trades` | From `run_bond_backtest` | see Objects | `list of TradeResult` | per run |
| `labels` | A label per trade, such as side or rating | none | `list` | per trade |

**Formula**

```
one trade_summary per label
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `by_group` | Summary per group | count and decimal | Final output |

### Step 76. Regress on market factors [PAPER]

**Function:** `factor_regression(monthly, factors)`

Regress monthly returns on stock and bond market factors, as in Yu's Table 6 (PDF p. 31). His factors are excess returns on S&P Industrials, Lehman Baa and Ba Intermediate, and CSFB/Tremont Fixed Income Arbitrage.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `monthly` | From `monthly_index` | decimal | `float array` | per month |
| `factors` | Factor excess returns, one column each | decimal | `float matrix` | per month |

**Formula**

```
monthly = intercept + Σ_k beta_k · factor_k + error     OLS
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `fit` | `intercept`, `betas`, standard errors, `r2` | decimal | Final output |

---

## Part 12. Check it is right before trusting any backtest

Answers question 13. Run these in order, and stop at the first failure. The results here come from the test suite and the worked example.

### Step 77. Reproduce the published CreditGrades grid [CREDITGRADES]

**Function:** `check_table_c1()`

Reproduce CGTD Table C.1. **Done: 156 of 156 cells match after rounding, largest gap 0.494 bp**, with the ×360/365 scaling. Without it, the largest gap is 11.59 bp.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `(none)` | No inputs. The grid is in the code | none | none | fixed |

**Formula**

```
for each S/D and vol: cds_par_spread(5, Firm(S/D, 1, vol, 0.5, 0.3), 0.5, 0.05, act360=True)
compare with the published grid
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `result` | `cells_matching`, `largest_gap_bp`, `largest_gap_unscaled_bp`, `grid_bp` | count and bp | Final output |

### Step 78. Compute the CDS equity hedge ratio [PAPER]

**Function:** `cds_equity_delta(T, firm, R, r, hold)`

Compute Yu's Eqs. (7) and (15), corrected. Long protection buys `−δ` shares. Short protection shorts `−δ` shares.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `T` | Maturity | years | `float` | per trade |
| `firm` | The firm at entry | see Objects | `Firm` | per trade |
| `R` | CDS recovery | decimal | `float` | fixed |
| `r` | Flat rate | decimal | `float` | per trade |
| `hold` | `asset_vol` or `equity_vol`. Default `asset_vol` | none | `str` | per run |

**Formula**

```
δ = A(T) · ( c(S + h) − c(S − h) ) / (2h)     h = 1% of S
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `delta_cds` | Shares per 1 of notional. Negative | shares | Step 79, Step 83 |

### Step 79. Reproduce the WorldCom case [CREDITGRADES]

**Function:** `check_worldcom(r)`

Reproduce CGTD p. 36. **Done:** published 249 and 224 bp, mine 249.7 and 224.6 at r = 5%. At r = 5.2% they round exactly. The document does not state `r`. Hedge ratio: published 7.7:1, mine 7.5:1 from the same finite move. Holding equity vol instead gives 15.4:1.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `r` | Flat rate. Default 0.05 | decimal | `float` | fixed |

**Formula**

```
S = 13 and 14, D = 9, asset vol 40%, L̄ = 0.5, λ = 0.3, R = 0.5, act360=True
hedge ratio = 1 / ( tightening · annuity · 13 )
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `result` | Scores, tightening, annuity and three hedge ratios | bp and ratio | Final output |

### Step 80. Check the identities [ADAPTATION]

**Function:** `check_identities(firm, R, r, T)`

Confirm that the integral forms match the closed forms, `P = 1 + (C − r − c)A` holds, and the par-bond delta equals the CDS delta.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `firm` | Any firm | see Objects | `Firm` | fixed |
| `R` | Recovery | decimal | `float` | fixed |
| `r` | Flat rate | decimal | `float` | fixed |
| `T` | Maturity | years | `float` | fixed |

**Formula**

```
annuity_gap        = abs(cds_annuity − quadrature)
price_identity_gap = abs(P − (1 + (C − r − c) A))
par_delta_gap      = abs(bond delta / −CDS delta − 1)
par_z_minus_cds_bp = Z of a daily-coupon par bond minus c
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `result` | The four gaps | decimal and bp | Final output |

### Step 81. Fit the barrier on CDS [PAPER]

**Function:** `fit_barrier_on_cds(c_market, S, D, sigma_s, r, T, R, lam)`

Yu's own fit (PDF p. 18), for replicating him: least squares on the first ten daily CDS spreads.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `c_market` | CDS spreads on the fit days | decimal | `float array` | once per obligor |
| `S` | Share prices | USD per share | `float array` | once per obligor |
| `D` | Debt per share | USD per share | `float array` | once per obligor |
| `sigma_s` | Equity vols | decimal per year | `float array` | once per obligor |
| `r` | Flat rates | decimal | `float array` | once per obligor |
| `T` | CDS maturity | years | `float` | fixed |
| `R` | CDS recovery | decimal | `float` | fixed |
| `lam` | Barrier noise | decimal | `float` | fixed |

**Formula**

```
L̄ = argmin Σ_days ( c_model(L̄) − c_market )²
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `L_bar` | Fitted barrier | ratio | Step 83 |
| `rmse` | Fit error | decimal | Final output |

### Step 82. Mark a CDS contract [PAPER]

**Function:** `cds_contract_value(c_now, c_entry, T, firm, r)`

Yu's Eq. (6) with corrected Eq. (14). He approximates `c(t,T)` with the fresh `c(t,t+T)` quote and keeps `T` fixed (PDF p. 13). The survival curve is the model's, from historical vol.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `c_now` | Today's quote, at the side you would exit on | decimal | `float` | daily |
| `c_entry` | Spread at entry, at the side you entered on | decimal | `float` | per trade |
| `T` | Maturity, kept fixed | years | `float` | fixed |
| `firm` | The firm today | see Objects | `Firm` | daily |
| `r` | Flat rate | decimal | `float` | daily |

**Formula**

```
π = (c_now − c_entry) · A(T)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `pi` | Value of long protection | per 1 of notional | Step 83 |

### Step 83. Replicate Yu on CDS first [PAPER]

**Function:** `run_cds_backtest(panel, config, T)`

Run Yu's own trade, if you can get CDS. Use his settings: `calibration_days=10`, `overlapping=True`, `lag=0`. Your code must come close on CDS before the bond version means anything. My readings where Yu is silent: entry at the bid or ask, daily marks at the side you would exit on, no interest on the margin account. **I could reproduce no trade-level number from Yu myself, because he prints no `S`, `D` or `σ_S` for any date.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | One obligor's daily CDS data | see Objects | `CdsPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |
| `T` | CDS maturity. Default 5 | years | `float` | fixed |

**Formula**

```
c_entry = c · (1 − side · bid_ask/2)
c_mark  = c · (1 + side · bid_ask/2)
value   = −side · (c_mark − c_entry) · A(T; S_t)
premium =  side · c_entry · Δt
stock   = −side · shares · (S_t − S_{t−1} + dividend_t)
exit by exit_reason, return by next_account_value
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `result` | `BacktestResult`, the same as the bond run | see Objects | Step 84 |

### Step 84. Compare with Yu's Altria table [PAPER]

**Function:** `check_cds_replication(summary, capital, days, alpha)`

Compare your Altria result with Table 2. Target at capital 0.5 and 180 days: `N = 550, 319, 154`, and means 4.50, 5.37, 4.04. Targets for all obligors are in `01_paper_extraction.md`, Table 3.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `summary` | `trade_summary` of your run | count and decimal | `dict` | per run |
| `capital` | 0.1 or 0.5 | per 1 of notional | `float` | per run |
| `days` | 30 or 180 | days | `int` | per run |
| `alpha` | 0.5, 1 or 2 | decimal | `float` | per run |

**Formula**

```
difference = yours − Yu's, for each column of Table 2
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `gaps` | Difference per column | count and percent | Final output |

### Step 85. Make a test bond [ADAPTATION]

**Function:** `synthetic_bond_panel(n_days, S, D, sigma_s, coupon, years_left, L_bar, R_b, lam, zero_rate)`

Make a bond priced exactly on its model, with flat stock and rates, for the checks below.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `n_days` | Rows. Default 90 | days | `int` | fixed |
| `S` | Share price. Default 30 | USD per share | `float` | fixed |
| `D` | Debt per share. Default 28 | USD per share | `float` | fixed |
| `sigma_s` | Equity vol. Default 0.38 | decimal per year | `float` | fixed |
| `coupon` | Default 0.055 | decimal per year | `float` | fixed |
| `years_left` | Default 4.8 | years | `float` | fixed |
| `L_bar` | Default 0.8 | ratio | `float` | fixed |
| `R_b` | Default 0.5 | decimal | `float` | fixed |
| `lam` | Default 0.3 | decimal | `float` | fixed |
| `zero_rate` | Flat zero rate. Default 0.04 | decimal | `float` | fixed |

**Formula**

```
clean_t = P_model(t) − accrued_t
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `panel` | A `BondPanel` of made-up data | see Objects | Step 86, Step 88, Step 94 |

### Step 86. Remove any gap [ADAPTATION]

**Function:** `panel_with_no_gap(panel, L_bar, R_b, lam)`

Set each clean price to its model price, on any panel.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `L_bar` | Barrier to price at | ratio | `float` | fixed |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `lam` | Barrier noise | decimal | `float` | fixed |

**Formula**

```
clean_t = P_model(t) − accrued_t
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `panel` | The panel with `Z_mkt` equal to `Z_model` | see Objects | Step 87 |

### Step 87. Check for no signal when there is no gap [ADAPTATION]

**Function:** `check_no_signal_without_gap(panel, config)`

Run the method on a panel with no gap. **Expect 0 trades. Done: 0.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | From `panel_with_no_gap` | see Objects | `BondPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |

**Formula**

```
count = number of trades from run_bond_backtest(panel, config)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `count` | Trades. Expect 0 | count | Final output |

### Step 88. Inject a known gap [ADAPTATION]

**Function:** `inject_gap(panel, L_bar, start_day, gap, close_days, R_b, lam)`

Add a spread gap that shrinks in a line and just crosses zero, with no stock or rate move.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `L_bar` | Barrier the panel was priced at | ratio | `float` | fixed |
| `start_day` | Row of the gap | row | `int` | fixed |
| `gap` | Size. Positive widens the market | decimal | `float` | fixed |
| `close_days` | Calendar days to close | days | `float` | fixed |
| `R_b` | Bond recovery | decimal | `float` | fixed |
| `lam` | Barrier noise | decimal | `float` | fixed |

**Formula**

```
Z_mkt(t) = Z_model(t) + gap · (1 − elapsed / close_days), stopping 1 bp past zero
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `panel` | The panel with the gap | see Objects | Step 89, Step 90, Step 92, Step 93, Step 97 |

### Step 89. Check that the legs add up [ADAPTATION]

**Function:** `check_legs_add_up(result, capital)`

Each trade's legs and costs must equal its change in account value. **Done: largest gap 4e-17.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `result` | From `run_bond_backtest` | see Objects | `BacktestResult` | per run |
| `capital` | `K` | per 1 of CDS-equivalent notional | `float` | per run |

**Formula**

```
gap = abs( Σ legs − (final_value − capital) )
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `largest_gap` | Largest gap. Expect about 0 | per 1 of CDS-equivalent notional | Final output |

### Step 90. Check a known gap gives a known profit [ADAPTATION]

**Function:** `check_known_gap_profit(panel, result)`

Work out each trade's bond and stock P&L from end prices alone, and compare with the daily sums. **Done: largest gap 6e-17.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | From `inject_gap` | see Objects | `BondPanel` | daily |
| `result` | From `run_bond_backtest` | see Objects | `BacktestResult` | per run |

**Formula**

```
bond  = s · F · (P_exit − P_entry + coupons)
stock = −s · n · (S_exit − S_entry + dividends)
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `largest_gap` | Largest gap. Expect about 0 | per 1 of CDS-equivalent notional | Final output |

### Step 91. Cut the data at a date [ADAPTATION]

**Function:** `truncate_panel(panel, n_days)`

Keep the first `n_days` rows, as the panel looked on that day.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `n_days` | Rows to keep | days | `int` | fixed |

**Formula**

```
every array[: n_days]
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `panel` | The shorter panel | see Objects | Step 92 |

### Step 92. Check for no look-ahead [ADAPTATION]

**Function:** `check_no_lookahead(panel, config, cut_day)`

Run the backtest to a cut date and on the full data. All returns before the cut must match exactly. **Done: 0.0 at four cut dates.**

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |
| `cut_day` | Row to cut at | row | `int` | fixed |

**Formula**

```
largest abs(return in the full run − return in the cut run), before cut_day − lag − 1
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `largest_change` | Expect exactly 0 | decimal | Final output |

### Step 93. Test the execution lag [ADAPTATION]

**Function:** `lag_sensitivity(panel, config, lags)`

Rerun with entry at the signal-day price, then later. If the profit vanishes between lag 0 and lag 1, it was bounce. Dickerson et al. report that this bias can make up most of a price-based premium (PDF pp. 3, 18).

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |
| `lags` | Default (0, 1, 2, 5) | days | `tuple of int` | fixed |

**Formula**

```
mean trade return from run_bond_backtest at each lag
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `by_lag` | Mean return per lag | decimal | Final output |

### Step 94. Run a placebo [ADAPTATION]

**Function:** `placebo_panel(panel, other)`

Match the bond to another issuer's stock. Expect no signal value. If the fake pairing makes money, the profit is coming from bond mean reversion, not from the debt-equity gap.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | This bond | see Objects | `BondPanel` | daily |
| `other` | A panel from another issuer | see Objects | `BondPanel` | daily |

**Formula**

```
S, D, sigma_s, dividend come from other. Everything else stays
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `panel` | The mismatched panel. Run it through `run_bond_backtest` | see Objects | Final output |

### Step 95. Attribute the P&L [ADAPTATION]

**Function:** `attribute_pnl(trades)`

Split the return into bond, stock, rate hedge, financing and costs. If the bond leg alone explains the profit, you have a bond reversal strategy and the equity is decoration. Compare it against plain bond short-term reversal.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `trades` | From `run_bond_backtest` | see Objects | `list of TradeResult` | per run |

**Formula**

```
total per leg across trades, and net = the sum
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `totals` | P&L by leg and `net` | per 1 of CDS-equivalent notional | Final output |

### Step 96. Compare the shape with Yu [PAPER]

**Function:** `shape_against_yu(short_hold, long_hold, low_alpha, high_alpha)`

Expect more convergence and fewer losing trades with a longer hold, and tighter distributions with a higher trigger (Tables 2, 3). If yours goes the other way, look for a bug first.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `short_hold` | `trade_summary` at the shorter hold | count and decimal | `dict` | per run |
| `long_hold` | `trade_summary` at the longer hold | count and decimal | `dict` | per run |
| `low_alpha` | `trade_summary` at the lower trigger | count and decimal | `dict` | per run |
| `high_alpha` | `trade_summary` at the higher trigger | count and decimal | `dict` | per run |

**Formula**

```
N1/N rises with the hold
N3/N falls with the hold
max − min falls with the trigger
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `patterns` | True or False for each pattern | none | Final output |

### Step 97. Find the break-even cost [ADAPTATION]

**Function:** `break_even_cost(panel, config, multiples)`

Rerun at several cost multiples, and report where the mean return reaches zero.

**Inputs**

| Name | Meaning | Unit | Type | Frequency |
|---|---|---|---|---|
| `panel` | Any bond panel | see Objects | `BondPanel` | daily |
| `config` | Settings for the run | see Objects | `BacktestConfig` | per run |
| `multiples` | Default (0, 1, 2, 3) | ratio | `tuple of float` | fixed |

**Formula**

```
mean trade return at each multiple
linear interpolation to zero
```

**Outputs**

| Name | Meaning | Unit | Used in |
|---|---|---|---|
| `result` | `multiples`, `mean_returns`, `break_even_multiple` | ratio and decimal | Final output |

---

## Final outputs

These are everything the pipeline hands back, once the steps are done.

| Name | Meaning | Unit | Type | Frequency | Produced by |
|---|---|---|---|---|---|
| `z_market`, `z_model` | Market and model Z-spread | decimal (report in bp) | float array | daily | Step 69 (`run_bond_backtest`) |
| `L_bar`, `fit_rmse`, `status` | Fitted barrier, fit error, and `ok`, `review`, `reject` or `too_few_days` | ratio, decimal, none | float, float, str | once per bond | Step 69 (`run_bond_backtest`) |
| `inversion` | Credit-implied vol and its status | see Objects | VolInversion | daily | Step 46 (`implied_vol_bond`) |
| `beta_equivalent` | The vol trigger that matches `α` for this bond | decimal | float | daily | Step 50 (`beta_equivalent_to_alpha`) |
| `side`, `signal_day`, `entry_day`, `exit_day`, `reason` | Each trade's direction, dates and exit | +1 or -1, row, none | int, str | per trade | Step 69 (`run_bond_backtest`) |
| `face`, `shares`, `hedge_face` | Each trade's sizes | per 1 of CDS-equivalent notional, shares | float | per trade | Step 69 (`run_bond_backtest`) |
| `hpr` | Holding period return: net P&L over capital | decimal | float | per trade | Step 69 (`run_bond_backtest`) |
| `max_drawdown`, `converged` | Largest fall from peak, and ended by convergence | decimal, none | float, bool | per trade | Step 69 (`run_bond_backtest`) |
| `legs` | P&L by leg and each cost | per 1 of CDS-equivalent notional | dict | per trade | Step 69 (`run_bond_backtest`) |
| `daily_returns` | Daily excess return, days by trades | decimal | float matrix | daily | Step 69 (`run_bond_backtest`) |
| `slope`, `slope_se` | Measured hedge ratio and its error | shares per 1 of face | float | per bond | Step 70 (`empirical_hedge_slope`) |
| `monthly` | Monthly excess returns of the index | decimal | float array | per month | Step 71 (`monthly_index`) |
| `sharpe` | Annualised Sharpe | ratio | float | per run | Step 72 (`annual_sharpe`) |
| `summary` | `N`, `N1`, `N2`, `N3`, `mean`, `min`, `max`, as in Yu's Tables 2 and 3 | count, decimal | dict | per run | Step 73 (`trade_summary`) |
| `monthly_stats` | The columns of Yu's Table 4 | count, decimal | dict | per run | Step 74 (`monthly_summary`) |
| `by_group` | The summary by direction and by rating | count, decimal | dict | per run | Step 75 (`summaries_by_group`) |
| `fit` | Intercept, betas, errors and R², as in Yu's Table 6 | decimal | dict | per run | Step 76 (`factor_regression`) |
| `totals` | P&L attribution across trades | per 1 of CDS-equivalent notional | dict | per run | Step 95 (`attribute_pnl`) |
| `by_lag` | Mean trade return at each execution lag | decimal | dict | per run | Step 93 (`lag_sensitivity`) |
| `break_even_multiple` | The cost multiple where the mean return reaches zero | ratio | float | per run | Step 97 (`break_even_cost`) |
| `gaps` | Your CDS run minus Yu's Table 2 | count, percent | dict | per run | Step 84 (`check_cds_replication`) |
| `yu_round_trip` | Yu's CDS round trip, for comparison with the bond cost | per 1 of notional | float | daily | Step 34 (`yu_cds_round_trip`) |
| check results | Pass or fail of each check in Part 12 | as listed there | int, float, dict | per run | Step 77 to Step 97 |

---

## Point-in-time rules

Answers question 11.

| Item | Rule | Why |
|---|---|---|
| Debt and shares | From the day after the filing's acceptance (`filing_usable_from`) | Yu's one-month lag runs ahead of many filings. Your WRDS note says the median Compustat snapshot lags the 10-Q by 27 days |
| Compustat fields | Do not use a current view that holds latest values. Use first-reported values | Restated numbers were not known at the time |
| EDGAR time | Convert the acceptance time from UTC | The API reports UTC, according to your WRDS note |
| Vol | The window ends at the signal-day close, and the trade happens the next day | No overlap with the return |
| `L̄` | Fit only on days before the first trade, then lock it | Yu does this. Any refit must use only past days |
| `α`, `β` | Fix them in advance, or pick them on an early period and test on a later one | Yu fixes `α`. Choosing the best after the fact is look-ahead |
| Peer median | Same-day, from bonds eligible that day | No future membership |
| Universe | Rebuild daily from what is known that day | Yu's 252-day continuity filter uses future data (PDF p. 15). Do not copy it |
| Ratings | The rating known on the signal date | Yu's end-of-sample rating is look-ahead (PDF p. 16) |
| Survivors | Keep bonds that later default, get called or mature | Otherwise losses vanish from the sample |
| Clock | Use only prints reported by the equity close | A print is public only at its report time |
| Trade filters | Run `fix_decimal_shifts` and `flag_price_spikes` only on prints known by that close | Both look at neighbouring trades |
| Return filters | No winsorising with full-sample thresholds | Dickerson et al. (PDF p. 5) show that this inflates premia |

---

## Worked example. ALL INPUTS ARE MADE UP.

**This illustrates the arithmetic only. It is not evidence the trade works.** I chose the price paths, including both the good exit and the bad one. Regenerate it with `python3 worked_example.py`. A test fails if any step is missing from it.

**The setting.** One made-up issuer and one made-up bond, a 5.5% semiannual bullet with 4.8 years left. Part 5's fit runs on the first 20 days, so the Part 4 lines use its `L̄` on the last fit day. The signal comes 84 calendar days later, after a new filing. Rows follow the step order.

| Step | Function | Result |
|---|---|---|
| 1 | `issuer_is_eligible` | Industrial issuer with listed stock: True. |
| 2 | `bond_terms_are_eligible` | Senior unsecured, USD, fixed, make-whole call, no other option: True. |
| 3 | `callable_is_usable` | Make-whole call, so the test does not apply: True. |
| 4 | `maturity_is_eligible` | 4.8 years left: True. |
| 5 | `age_and_size_are_eligible` | 1.5 years old, 4.8 left, USD 750mm: True. |
| 6 | `pick_bond_and_sibling` | 60-day trades 140, 90, 30: bond BOND_A, sibling BOND_B. |
| 7 | `passes_liquidity_screen` | 14 institutional trades in five days: True. |
| 8 | `debt_per_share` | USD 14,000mm over 500mm shares: D = 28.00. |
| 9 | `filing_usable_from` | 10-Q accepted Tue 2024-05-07: usable from 2024-05-08. |
| 10 | `debt_after_corporate_action` | Spinoff takes the stock from 30 to 27: D moves from 28.00 to 25.20, and the model spread does not move. |
| 11 | `historical_equity_vol` | 1,000 daily returns: 0.3800. |
| 12 | `equity_vol_input` | Source 'historical', with implied vol 0.42 on hand: 0.3800. |
| 13 | `zero_curve_from_par_yields` | Par yields 4.35% to 4.60%: zero rates at 1, 5, 10 years 4.1062%, 3.9241%, 4.3133%. |
| 14 | `clean_trade_reports` | 13 reports in. 10 kept. Dropped: one cancel, the report it cancels, one duplicate side. |
| 15 | `fix_decimal_shifts` | Price 925.00 corrected to 92.50. Others unchanged. |
| 16 | `flag_price_spikes` | Flagged 1 print: 50.00, which reverted on the next print. |
| 17 | `daily_clean_price` | Buys 93.50, sells 92.50, one small trade ignored: clean price 0.9300, one-sided False. |
| 18 | `full_price` | Accrued 0.02383: full price 0.95383. |
| 19 | `z_spread` | Market Z-spread 329.9 bp. |
| 20 | `dollar_duration` | Stock 27.20, clean 0.9330, Z 322.1 bp: duration 3.806. |
| 21 | `asset_vol` | Last fit day, S = 30.20: asset vol 0.2135. |
| 22 | `barrier_distance` | d = 2.4975. |
| 23 | `survival` | q(0), q(1), q(3), q(5) = 0.99643, 0.9798, 0.9155, 0.8392. |
| 24 | `discounted_default` | H(5) = 0.14064. |
| 25 | `cds_annuity` | 5-year annuity 4.2255. |
| 26 | `cds_par_spread` | 5-year model CDS spread 170.6 bp. |
| 27 | `default_leg` | Default leg to 4.747 years 0.13658. |
| 28 | `risky_bond_price` | Model full price 1.00606. Market 1.00670. |
| 29 | `model_z_spread` | Model Z 170.0 bp. Market Z 168.5 bp. |
| 30 | `yu_fixed_parameters` | R_b = 0.5, lam = 0.3. |
| 31 | `fit_barrier_on_bond` | 20 days, market Z averaging 171.0 bp: L_bar = 0.8410, fit error 2.3 bp. |
| 32 | `fit_status` | L_bar 0.8410: ok. |
| 33 | `passes_barrier_filter` | New filing D = 28.80, stock 27.00: 1 - q(0) = 0.0078, passes = True. |
| 34 | `yu_cds_round_trip` | Yu's own cost at 100 bp and a 4.3 annuity: 0.215 points. |
| 35 | `measured_round_trip` | Buys 93.50, sells 92.50: 1.00 points. |
| 36 | `planning_round_trip` | If it could not be measured, rating BBB at 322.1 bp: 0.50 points. BB: 1.00 points. |
| 37 | `stressed_cost` | Twice the cost: 2.00 points. |
| 38 | `entry_signal` | Market Z 329.9 bp, model Z 197.0 bp, ratio 1.674 against 1.5: signal +1. |
| 38 | `entry_signal` | The other direction, a later day: stock 25.50, clean 101.50. Market Z 115.1 bp, model Z 205.3 bp, ratio 1.783: signal -1, which is short bond, long stock, long Treasury. |
| 39 | `log_gap` | ln(market / model) = 0.515. Trigger ln(1.5) = 0.405. |
| 40 | `peer_median_gap` | Six peers, one with no price: median 0.050. |
| 41 | `peer_adjusted_signal` | 0.515 - 0.050 = 0.465: signal +1. |
| 42 | `sibling_confirms` | Sibling gap 0.40, same sign and at least half the size: True. |
| 43 | `cds_confirms` | No CDS in this example, so no veto: True. With a 3.5% CDS quote against the model's 198.5 bp: True. |
| 44 | `passes_cost_gate` | Full convergence pays 5.04 points against 2 x 1.00: True. |
| 45 | `implied_vol_confirms` | Implied vol 0.40: True. Implied vol 0.50 would veto it: True. |
| 46 | `implied_vol_bond` | Status ok. Credit-implied vol 0.4905 against observed 0.3850, ratio 1.274. Price 1.60 gives below_floor. Price 0.58 gives near_recovery. |
| 47 | `implied_vol_cds` | The CDS version, on the model's own 198.5 bp: 0.3850. |
| 48 | `vol_status_allows_trade` | Status ok: True. |
| 49 | `vol_entry_signal` | 0.4905 against 0.3850, trigger 1 + beta = 1.2: signal +1. |
| 50 | `beta_equivalent_to_alpha` | alpha = 0.5 equals beta = 0.090 at S/D = 3, 0.207 at S/D = 0.94, 0.317 at S/D = 0.6. |
| 51 | `decide_entry` | Every check passes: side +1, which is long bond, short stock, short Treasury. |
| 52 | `execution_day` | Signal on trading day 60: trade on day 61, at that day's price. |
| 53 | `cds_equivalent_face` | Annuity 4.158 over duration 3.806: face 1.0924. |
| 54 | `bond_equity_delta` | 0.00560 shares per 1 of face holding asset vol. 0.00251 holding equity vol, 2.2 times smaller. |
| 55 | `par_hedge_bond` | Treasury with 4.564 years left, coupon 3.5635%, priced at par. |
| 56 | `rate_hedge_face` | 0.9096 of Treasury face per 1 of bond face. |
| 57 | `build_position` | Long 1.0924 face. Short 0.00611 shares, value 0.1663, or 15.2% of face. Short 0.9937 Treasury face. |
| 58 | `rate_hedge_is_due` | Today's hedge is on target: False. After 30 days: True. |
| 59 | `bond_financing_rate` | Long bond pays 4.20%. A short bond would earn 3.80%. |
| 60 | `stock_financing_rate` | Short stock earns 3.80%. Long stock would pay 4.10%. |
| 61 | `trade_cost` | Entry cost 0.00559: bond 0.00546, stock 0.00008, Treasury 0.00005. |
| 62 | `opening_account_value` | Capital 0.5 less entry cost: 0.49441. |
| 63 | `coupons_paid` | Bond, next day: 0.0000. Over the next 45 days: 0.0275. |
| 64 | `daily_pnl` | Stock 27.05, clean 93.45, rates up 3 bp. bond_price +0.001805, bond_financing -0.000122, stock_price +0.000917, stock_financing +0.000018, hedge_price +0.001132, hedge_financing +0.000113, total +0.003863. |
| 64 | `daily_pnl` | Good path, whole hold: bond leg +0.06647 (includes coupon 0.0275), stock leg -0.00777, rate hedge -0.00404, costs -0.01119. Net +0.04347, or +8.69% on capital. |
| 64 | `daily_pnl` | Bad path, same entry: stock up to 30.00, clean down to 86.00. Bond leg -0.07772, stock leg -0.01633. Net -0.10522, or -21.04% on capital. |
| 64 | `daily_pnl` | The other direction, one day, stock 25.35 with a 0.05 dividend, clean 101.30: bond_price +0.001951, bond_financing +0.000115, stock_price -0.000630, stock_financing -0.000018, hedge_price +0.000119, hedge_financing -0.000120, total +0.001417. |
| 65 | `next_account_value` | Account 0.49827. Day's excess return 0.7814%. |
| 66 | `exit_reason` | 45 days on: stock 28.60, clean 99.20, rates down 10 bp. Market Z 183.2 bp, model Z 187.6 bp: convergence. |
| 67 | `bond_exit_reason` | The same day with the bond rules: convergence. Had a merger been announced: merger. |
| 68 | `drawdown_from_peak` | Account path 0.494, 0.498, 0.520, 0.470, 0.544: largest fall 9.6%. |
| 69 | `run_bond_backtest` | 90 days, flat stock and rates, a 200 bp gap on day 30 that closes in 30 days. Fitted L_bar 0.8000. One trade: side +1, signal day 30, entry day 31, exit day 61, convergence, return +15.44% on capital. |
| 70 | `empirical_hedge_slope` | 250 made-up days built with a true slope 0.0055: slope 0.00556, standard error 0.00021, against the model delta 0.00560. |
| 71 | `monthly_index` | Three months from that one trade: [ 0.      0.1584 -0.0035]. |
| 72 | `annual_sharpe` | 12 made-up months: 1.18. |
| 73 | `trade_summary` | N 1, N1 1, N2 0, N3 0, mean +15.44%, min +15.44%, max +15.44%. |
| 74 | `monthly_summary` | The 12 months: N 10, mean 0.0022, median 0.0025, min -0.0110, max 0.0120, std 0.0064, corr -0.6818, neg 0.2500, sharpe 1.1818. |
| 75 | `summaries_by_group` | Overlapping book on the same gap, by side: [(1, 18, 0.1018)]. |
| 76 | `factor_regression` | The 12 months on two made-up factors: intercept -0.0001 (0.0006), betas [0.505 0.099], R2 0.92. |
| 77 | `check_table_c1` | 156 of 156 cells match after rounding. Largest gap 0.494 bp. Without the Act/360 scaling 11.59 bp. |
| 78 | `cds_equity_delta` | CreditGrades WorldCom inputs: -0.01106 shares per 1 of notional. |
| 79 | `check_worldcom` | Published 249 and 224 bp, ours 249.7 and 224.6. Published hedge 7.7:1, ours 7.5:1. Holding equity vol 15.4:1. |
| 80 | `check_identities` | Annuity gap 3.6e-15. Price identity gap 0.0e+00. Par delta gap 1.0e-04. Par Z minus CDS +0.013 bp. |
| 81 | `fit_barrier_on_cds` | Ten days of made-up CDS at 129.8 bp: L_bar 0.6200, error 0.0 bp. |
| 82 | `cds_contract_value` | Long protection entered at 100 bp, now 150 bp: +0.02163. |
| 83 | `run_cds_backtest` | Made-up CDS doubles on day 15, then falls under the model on day 23: side +1, exit day 23, convergence, return +10.62% on capital. |
| 84 | `check_cds_replication` | Yours minus Yu's Altria row. Meaningless on made-up data, and shown only for the form: N -549, mean +6.12. |
| 85 | `synthetic_bond_panel` | 90 made-up days, flat stock and rates, clean 0.9908 on day 0. |
| 86 | `panel_with_no_gap` | Every clean price set to its model price: largest change 0.0e+00. |
| 87 | `check_no_signal_without_gap` | Trades with no gap: 0. |
| 88 | `inject_gap` | 200 bp added on day 30: clean falls from 0.9913 to 0.9113. |
| 89 | `check_legs_add_up` | Largest gap between the legs and the change in value: 4.2e-17. |
| 90 | `check_known_gap_profit` | Largest gap against the end-price sum: 5.6e-17. |
| 91 | `truncate_panel` | Panel cut to 45 days. |
| 92 | `check_no_lookahead` | Largest change in a past return when later data is removed: 0.0e+00. |
| 93 | `lag_sensitivity` | Mean return by execution lag: lag 0: +15.96%, lag 1: +15.44%, lag 2: +14.82%, lag 5: +12.99%. This gap is real by design, so the profit does not vanish at lag 1. |
| 94 | `placebo_panel` | Same bond against another stock: fitted L_bar 1.2000, trades 1. Here the fit moves the barrier, and the injected gap still shows. |
| 95 | `attribute_pnl` | entry_cost -0.00566, bond_price +0.09170, bond_financing -0.00376, stock_price +0.00000, stock_financing +0.00048, hedge_price -0.00336, hedge_financing +0.00344, rehedge_cost -0.00000, exit_cost -0.00566, net +0.07718. |
| 96 | `shape_against_yu` | Four made-up summaries: {'more_convergence_with_longer_hold': True, 'fewer_losers_with_longer_hold': True, 'tighter_with_higher_trigger': True}. |
| 97 | `break_even_cost` | A 120 bp gap: mean return [0.1064, 0.0845, -0.1123, -0.7686] at cost multiples (0.0, 1.0, 10.0, 40.0). Break-even at 4.9 times the cost. |

**What the example shows.**
- The equity hedge lost money on the good path and on the bad path. In the bad path, both legs lose. That is Yu's "sure case of divergence".
- The bond leg drives almost all of the P&L. That is why `attribute_pnl` matters.
- The 15.2% equity position is close to two practitioner figures: Hanson's 12% (Yu, PDF p. 3), and about 14% on the CGTD WorldCom inputs. Holding equity vol would give about 6.8%. This is weak support, because these are different firms.
- The backtest at the end is a test of the code. Its 15.44% is a gap I injected, not a result.

**Sensitivities on the fitted model,** quoted in the steps above:

```
Base: L_bar 0.8410, model Z 170.0 bp, delta 0.00471.
Fit to Z +40 bp: L_bar 1.0760, delta 0.00534 (+13%).
Fit to Z -40 bp: L_bar 0.6323, delta 0.00394 (-16%).
R_b = 0.4: L_bar 0.6943, delta 0.00496 (+5%).
R_b = 0.3: L_bar 0.5959, delta 0.00515 (+9%).
lam = 0.2: L_bar 1.0430, delta 0.00506 (+7%).
lam = 0.4: L_bar 0.7054, delta 0.00438 (-7%).
Curve up 30 bp, prices and L_bar unchanged: market Z 168.5 bp -> 138.5 bp. Model Z 170.0 bp -> 169.0 bp.
Stock down 10%, equity vol fixed: model Z +16.4 bp. Asset vol fixed: +37.8 bp.
Equity vol 38% -> 60%, same stock: model Z 459.4 bp.
Coupon 2.0%: model full price 85.79, model Z 158.3 bp.
Coupon 5.5%: model full price 100.61, model Z 170.0 bp.
Coupon 9.0%: model full price 115.42, model Z 179.9 bp.
5-year CDS on the same firm: 170.6 bp.
```

---

## Appendix. Test results

`python3 -m pytest test_e2c_bond.py -v -s` gives **161 passed in 13.86s**.

**Reproductions of published numbers.**

| Source | Published | Mine | Gap |
|---|---|---|---|
| CGTD Table C.1, all 156 cells (Yu's model, ×360/365) | Whole bp grid | 156 of 156 round to the published value | Largest 0.494 bp |
| CGTD Table C.1, S/D = 0.5, vol 80% | 865 bp | 864.58 bp | 0.42 bp |
| CGTD p. 36, WorldCom, S = 13 and S = 14, r = 5% assumed | 249, 224 bp | 249.7, 224.6 bp | 0.7, 0.6 bp |
| CGTD p. 36, tightening per $1 of stock | 25 bp | 25.4 bp | 0.4 bp |
| CGTD p. 36, hedge ratio | 7.7:1 | 7.5:1 | 0.2 |
| CGTD Figure 2.2, 1-year rate (read by eye) | about 130, 320, 680, 1,120 bp | 128, 320, 678, 1,119 bp | Within reading error |
| CGTD Figure 2.3, delta at S = 3 (read by eye, r = 5% assumed) | about -47, -40, -34, -29, -24.5 | -47.5, -40.1, -33.9, -28.8, -24.6 | Within reading error |
| Yu Tables 4, 7, Sharpe from mean and std (18 rows) | Column values | All inside the rounding range | Rounding only |
| Yu p. 1, Hanson equity gain | 16,000 | 16,495 | 3%. The share prices are rounded |

**Not reproduced.**
- **No trade-level number in Yu can be reproduced.** He prints no `S`, `D` or `σ_S` for any date.
- **The Altria liquidation is a size check only.** On a made-up firm with his spread path, `run_cds_backtest` gives -108% at capital 0.1, against his "-100%". He does not publish the inputs, so nothing closer is possible.
- **Lardy's deck was not in the files I was given,** so I used Figure 2.2 instead.

**Corrections to the brief.**
- **"Survival is 1 at T = 0" is false for this model.** `q(0) < 1` whenever `λ > 0`. Yu's footnote 22 and CGTD p. 8 both say so. The test asserts `q(0) = 1` at `λ = 0`, and states the size otherwise: `1 − q(0)` = 0.01325 at S/D = 0.5 and 3e-11 at S/D = 3.

**What the tests do not cover.** The backtest loop has run only on synthetic data. Its checks prove that the code does what this file says. They do not prove that the trade makes money.
