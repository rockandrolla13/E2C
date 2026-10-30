# Finkelstein (2002): what the deck says, page by page

**Source.** Vladimir Finkelstein, Goldman, Sachs & Co., "Assessing default probabilities from equity markets". File: `E2C/evidence/drive/01_model_notes/Finkelstein.pdf`. 28 PDF pages. The PDF metadata gives a creation date of 28 June 2002. The disclaimer on PDF page 28 says "Copyright © 2002".

**Page numbers.** The title page has no number. So **PDF page = slide number + 1**. "Slide 1" in this file is the page the brief calls "Page 1". It is PDF page 2.

**How I read it.** I read all 28 pages as images, rendered with `pdftoppm` into `pages/`. I used the text layer only to check spelling.

**Marks.**
- `~` means I read the value off a chart by eye. Treat it as approximate.
- "Printed" means the number is printed on the slide.
- Chart x-axes marked 1, 51, 101 are trading-day counts from the start of the period.

**Checks.** `check_deck_numbers.py` recomputes the numbers below. Its output is in `check_deck_numbers.out`. Section letters in this file refer to that output.

---

## PDF page 1. Title

"Assessing default probabilities from equity markets". Vladimir Finkelstein. No date on the page.

---

## Slide 1 (PDF 2). A couple of observations

**Text, in order.**
1. "In default stock goes to zero, bond goes to recovery value."
2. "Equity put option is part default protection." The slide calls this "a typical HY name".
3. High yield spreads are more correlated with equities than swap yields.
4. There is "strong empirical evidence" of a link between credit spreads and equity volatility in extreme conditions.

**The put example. All printed.**

| Item | ATM put | 30% OTM put |
|---|---:|---:|
| S | 15 | 15 |
| K | 15 | 10.5 |
| T | 2 | 2 |
| Black-Scholes vol | 72% | 77% |
| IR | 3% | 3% (not repeated, inferred) |
| Put price | 4.92 | 2.72 |
| Contribution from default | 1.90 | 1.42 |

**The credit example. All printed.**
- CDS par spread 530 bp. Recovery R = 30%. "This implies two year default probability of 13.6%".
- `15*0.136/(1+0.03)^2 = 1.90`. "When buying ATM put for 4.92, one pays 1.90 for default protection alone."

**The table. All printed.**

| | Jul-98 | Oct-98 | Dec-98 |
|---|---:|---:|---:|
| S&P 500 | 1200 | 1000 | 1200 |
| HY Spread Index (bps) | 400 | 725 | 625 |
| S&P Volatility (%) | 26 | 34 | 31 |

**Check result (section A).** Several of these numbers do not reproduce. See "Numbers that do not reproduce" below.

---

## Slide 2 (PDF 3). Motivation

1. "Establish a trading framework linking credit and equity derivatives."
2. For traded names, consider managing the risk of credit derivatives books using equity and equity derivatives liquidity.
3. For illiquid names, consider pricing credit derivatives *and* managing their risk from equity and equity derivatives.
4. "On a flip side, pricing and risk management of equity derivatives (especially low strikes) should take into account default events and information from credit derivatives market."

No numbers.

---

## Slide 3 (PDF 4). Brief history

- Merton 1974: stock as a call on the firm's assets. Call maturity equals debt maturity.
- KMV: calibrates asset value and vol, computes distance to default, and estimates EDF from historical defaults.
- Black & Cox 1976, Leland 1994: assets as perpetual debt plus equity. Stock as a perpetual down-and-out call.
- **"Lardy, Finkelstein, Yang, Khuong-Huu"**: a direct link from equity price and implied vol to default probability. New features: "Uncertainty of recovery value of liabilities" and "Closed form formula for any tenor".

So this deck presents the same closed form as Lardy's E2C and names the same four people. Lardy's printed slide 36 names them too.

---

## Slide 4 (PDF 5). The model framework

**Text.** The aim is "a simple and transparent model". Black-Scholes has zero probability of a stock hitting zero. So use a "Shifted Lognormal Model".

**Equations.**

```
S_t = [V_t − B] · exp( ∫_0^t (r − p) dt )    if V_τ > B for 0 ≤ τ ≤ t
    = 0                                       otherwise

V_t = (S_0 + B) · exp( ∫_0^t σ_t dW_t − ½ ∫_0^t σ_t² dt )
```

**Symbols.**
- `S_t`: stock price.
- `V_t`: "Asset Value". The slide says the name is chosen "to build a link to asset based models". It is a lognormal variable with zero drift.
- `B`: "Default (Knock-Out) Boundary for Asset Value". Constant in this slide.
- `r`: "stock financing rate".
- `p`: "dividend yield".
- `σ_t`: asset volatility, time dependent.
- `W_t`: Brownian motion.
- `τ`: running time in the survival condition.

---

## Slide 5 (PDF 6). Stock as shifted lognormal with a knock-out

A diagram. "Asset Value has a zero drift".
- Asset paths start at `V_0`. One path hits `B` at a yellow cross labelled "Default Event".
- The gap from `B` up to the path is labelled `S_t exp(−∫_0^t (r−p) dτ)`.
- The distribution at "Time T" has width labelled `2 V_0 sqrt(∫_0^T σ² dt)`.

---

## Slide 6 (PDF 7). Equity volatility skew

**Equations.**

```
σ_S(S_t) = σ · (S_t + B) / S_t

σ_cum(T) = ( (1/T) ∫_0^T σ_t² dt )^(1/2)  ≈  σ_ATM,S(S_0) · S_0 / (S_0 + B)
```

**Symbols.** `σ_S`: local stock percentage vol. `σ_cum(T)`: cumulative asset vol to `T`. `σ_ATM,S(S_0)`: at-the-money stock vol.

**Text.** "For accurate option pricing need to price 'down-and-out' knock-out options on Asset Value. This can be done in a closed form." **The closed form is not printed.**

**Chart: Local Vol as a Function of Stock Price.** B = 4, σ = 55% (printed).

| S | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Local vol | ~165% | ~128% | ~110% | ~99% | ~92% | ~82% | ~77% | ~73% |

These match the formula (section B).

---

## Slide 7 (PDF 8). Black-Scholes implied volatility

**Text.** Default produces a skew. "For a higher ratio of default barrier to a stock price, the skew is more pronounced."

**Chart: Equity Volatility Skew.** Y axis 0 to 1.8. X axis Strike/Forward, 0 to 2.5. Series B = 10, B = 5, B = 1.

| Strike/Forward | ~0.05 | ~0.1 | ~0.5 | ~1 | ~1.5 | ~2 |
|---|---:|---:|---:|---:|---:|---:|
| B = 10 | ~1.53 | ~1.38 | ~0.97 | ~0.82 | ~0.73 | ~0.68 |
| B = 5 | ~1.33 | ~1.18 | ~0.90 | ~0.82 | ~0.78 | ~0.76 |
| B = 1 | ~1.01 | ~0.95 | ~0.84 | ~0.82 | ~0.80 | ~0.80 |

**Printed under the chart.** "Share Price = 10.5, 1.5y ATM B-S Vol = 82%".

**A hidden caption.** The chart box partly covers the text "σ = 0.53, B = 4, S = 5, t = 1.5". The text layer confirms it. Those values give an ATM vol near 95%, not 82%. So this caption seems to be a leftover from an earlier chart.

---

## Slide 8 (PDF 9). Example: GX on 6/14/01

**Printed.** B = 6, S = 10.5. "Volatility skew is explained reasonably well for two maturities of long term options using the same default barrier level." GX is Global Crossing by my reading of the ticker. The deck does not spell out the name.

| Strike | Market, to 1/17/03 | Model, asset vol 49.80% | Market, to 1/16/04 | Model, asset vol 46.50% |
|---:|---:|---:|---:|---:|
| 5 | 96.0% | 96.3% | 93.1% | 91.6% |
| 7.5 | 88.4% | 87.6% | 85.6% | 83.5% |
| 10 | 82.2% | 82.3% | 78.3% | 78.3% |
| 12.5 | 79.9% | 78.8% | 75.2% | 75.0% |
| 15 | 77.6% | 76.2% | 72.3% | 72.4% |

**Printed.** "Compare the level of default barrier to Debt per Share = 14.2 for GX. B = 0.42 * Debt per Share."

**Check (section C).** My closed form reproduces all ten model vols within 0.14 vol points at r = 5% and p = 0. The deck does not state `r` or `p`. A fit on the market vols alone gives B = 6.01.

---

## Slide 9 (PDF 10). Estimating default barrier

- "If low strikes puts were liquid, the volatility skew would be a good indicator of the default barrier level."
- "In the absence of low strikes quotes", use the product of current debt per share `D` and expected global recovery of the firm's liabilities `L̄`.

```
B = L̄ · D
```

- "This choice of Default Barrier implies a specific equity volatility skew."
- "L̄ is usually around 0.5."

---

## Slide 10 (PDF 11). How stable is asset volatility?

**Printed.** "Estimates have been done using continuously ATM option". "Example: EXDS 6/12/00 – 6/11/01, B = 6.9".

**Left chart.** "Asset Vol from ReferenceOption" and "ATM Equity Volatility". X axis "Time (days)".

| Day | ~1 | ~50 | ~75 | ~105 | ~150 | ~200 | ~240 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| ATM equity vol | ~87% | ~80% | ~78% | ~90% | ~88% | ~95% | ~105% |
| Asset vol | ~77% | ~72% | ~70% | ~78% | ~76% | ~75% | ~80% |

Both series drop to 0 on the last point. That looks like an end-of-data artefact in the chart.

**Right chart.** Stock Price. X axis "Time (weeks)".

| Week | 1 | ~4 | ~11 | ~19 | ~23 | ~31 | ~41 | 51 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S | ~53 | ~40 | ~68 | ~33 | ~24 | ~18 | ~10 | ~7 |

**Check (section D).** The asset vol line matches at the start. It does not match at the end with B = 6.9. See below.

---

## Slide 11 (PDF 12). Deriving survival probabilities

**Text.** "Default probability is given by probability of knock-out of the Asset Value at the Default Barrier." The model gives "the full term structure of survival probabilities in a closed form".

**Equations.**

```
Q(T) = N( ln(d)/(σ_cum(T)√T) − σ_cum(T)√T/2 ) − d · N( −ln(d)/(σ_cum(T)√T) − σ_cum(T)√T/2 )

σ_cum(T) = sqrt( (1/T) ∫_0^T σ_t² dt ),     d = (S_0 + B) / B
```

**Symbols.** `Q(T)`: survival probability to `T`. `N`: normal CDF. `d`: asset value over barrier.

**Text.**
- "Volatility is calibrated using equity options."
- "Default barrier is given either by equity volatility skew (if observable) or is estimated using information on the firm's liabilities."

---

## Slide 12 (PDF 13). Example: GX equity-generated credit curve

**Text.**
- "Using local asset volatilities boot-strapped from equity option prices and the same values for Default Barrier and stock price obtain survival probabilities (SP)."
- "Using SP and assuming particular Recovery Rate calculate CDS par spreads and bond prices."

**Chart: Equity-Generated GX Par Spread Curve.** Series "Discount DI" and "Par CDS Spread". X axis "Tenor (yr)" with labels 0.5, 1.5, ... 9.5 and points every half year.

| Tenor | 0.5 | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 5 | 7 | 9.5 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Par CDS | ~0.9% | ~4.8% | ~7.7% | ~8.15% | ~8.4% | ~8.5% | ~8.6% | ~8.65% | ~8.6% | ~8.4% | ~8.2% |
| Discount DI | ~1.3% | ~6.9% | ~11.0% | ~11.6% | ~11.9% | ~12.1% | ~12.2% | ~12.2% | ~12.0% | ~11.6% | ~10.95% |

**"Discount DI" is not defined.** It tracks par spread / (1 − 0.30) out to about 3 years. At 9.5 years it sits about 0.75 points below that ratio. My reading of "DI" as a default intensity is unverified.

**Printed. The GX 11/15/2009 bond, coupon 9.5.**

| Date | S | Market price | Model price | Note |
|---|---:|---:|---:|---|
| 6/14/01 | 10.5 | 84 | 82 | "with 30% recovery" |
| 8/31/01 | 4.2 | 60 | 60 | "Using the same model parameters" |
| 10/01/01 | 1.8 | 45 | 43 | same |

The slide does not say if these prices are clean or full.

---

## Slide 13 (PDF 14). Example: GX pricing CDS

**Printed.** "Period 7/10/00 – 10/01/01". "For the model use B = 6, Asset Volatility = 42% (calibrated to equity volatility at the start)".

**Chart: Stock Price.** X axis is trading days.

| Day | 1 | ~38 | ~65 | ~100 | ~130 | ~165 | ~185 | ~215 | ~235 | ~275 | ~300 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S | ~27 | ~35 | ~22 | ~13 | ~25 | ~15 | ~10 | ~15.5 | ~7 | ~5 | ~3.5 |

---

## Slide 14 (PDF 15). GX CDS par spread for maturity 01/03/06: model vs market

**Printed.** "To generate market CDS curve use GX 11/15/2009 bond [coupon 9.5%, R = 30% (market consensus at the time) or R=10% (GS mark)]."

**This is the deck's only bond-against-model test, and the "market" series comes from a bond.** The deck does not say how it turned the bond price into a CDS curve.

**Chart.** Series "CDS Par Spread", "CDS Model Par Spread R=30%", "CDS Model Par Spread R=10%".

| Day | ~1 | ~100 | ~185 | ~235 | ~275 | ~287 | ~304 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| Market | ~2.5% | ~5% | ~6% | ~11.5% | ~12% | ~15% | ~31% |
| Model R=30% | ~2.5% | ~5.5% | ~9% | ~11% | ~16% | ~23% | ~37% |
| Model R=10% | ~2.5% | ~7.5% | ~11% | ~14% | ~20% | ~30% | ~47.5% |

All three lines fall to 0 at the last point. That looks like an end-of-data artefact.

---

## Slide 15 (PDF 16). CDS PV through time

The slide title is spelled "CDS PV trough time". **Printed.** "CDS: coupon = 300 bp, Maturity = 01/03/06, R = 30% or R = 10%".

**Chart.** Series "CDS PV", "CDS Model PV R=30%", "CDS Model PV R=10%". Y axis 20 to −80.

| Day | ~40 | ~100 | ~135 | ~185 | ~235 | ~275 | ~295 | ~304 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Market | ~+3 | ~−8 | ~−1 | ~−10 | ~−26 | ~−28 | ~−40 | ~−53 |
| Model R=30% | ~+7 | ~−9 | ~+2 | ~−19 | ~−25 | ~−33 | ~−45 | ~−52 |
| Model R=10% | ~+5 | ~−17 | ~−1 | ~−27 | ~−35 | ~−41 | ~−58 | ~−70 |

The sign is negative when spreads widen past 300 bp. So this is the value of **selling** protection at 300 bp. That is my reading. The slide does not say.

---

## Slide 16 (PDF 17). Uncertainty of default barrier

- For a given expected barrier, "there is a substantial uncertainty concerning its actual (realized) level".
- "This uncertainty should affect short maturities the most". It widens short-term spreads, since the asset value could be much closer to the barrier than expected.
- "Without this adjustment spread curves are too steep even for high spread levels (see the previous slide), which is not realistic."
- "Averaging over a Default Barrier can be done consistently for a wide range of distributions."

---

## Slide 17 (PDF 18). Stock as shifted lognormal with a knock-out

The slide 5 diagram again. A second small distribution sits at the barrier, with width labelled `2λB`.

---

## Slide 18 (PDF 19). Survival probability for a log-normal default barrier

**Text.** "For tenors > 6m and stocks that are not super-depressed (at the brink of bankruptcy) there is a pretty good closed-form approximation".

**Equations.**

```
B = B̄ · exp( λx − ½λ² ),     x ~ N(0,1)

(1)  Q(T) = N( ln(d̄)/A_T − A_T/2 ) − d̄ · N( −ln(d̄)/A_T − A_T/2 )

     A_T = sqrt( σ_cum²(T) · T + λ² ),     d̄ = (S_0 + B̄)/B̄ · exp(λ²)
```

**Symbols.** `B̄`: expected barrier. `λ`: percentage standard deviation of the barrier. `x`: standard normal. `A_T`: total standard deviation to `T`. `d̄`: adjusted distance.

**Note by me.** Eq. (1) equals slide 11 averaged over the lognormal barrier, with no cut-off for barriers above `V_0`. I checked this to six decimals (section G). So the "approximation" is the inclusion of the region `B ≥ V_0`. The error is small unless `S_0/B̄` is small.

---

## Slide 19 (PDF 20). Uncertainty of DB and the shape of the CDS par curve

**Printed.**
- "With an approximation (1) survival probability at T = 0 can be less than 100%."
- "A remedy: use (1) for T>0.5yr and interpolate between 1 and Q(0.5) using flat default intensity."

**Left chart. Printed parameters: σ_S = 64.5%, σ = 41%, R = 30%, S/B = 1.75.**

| Tenor | ~0.5 | ~1 | ~2 | ~5 | ~10 |
|---|---:|---:|---:|---:|---:|
| λ = 0 | ~0.002 | ~0.019 | ~0.052 | ~0.077 | ~0.079 |
| λ = 0.2 | ~0.008 | ~0.028 | ~0.057 | ~0.077 | ~0.078 |
| λ = 0.3 | ~0.023 | ~0.040 | ~0.063 | ~0.077 | ~0.076 |
| λ = 0.4 | ~0.048 | ~0.057 | ~0.069 | ~0.077 | ~0.075 |

**Right chart. Printed parameters: σ_S = 40%, σ = 22.2%, R = 30%, S/B = 0.8.**

| Tenor | ~0.5 | ~1 | ~2 | ~5 | ~10 |
|---|---:|---:|---:|---:|---:|
| λ = 0 | ~0.000 | ~0.001 | ~0.009 | ~0.027 | ~0.033 |
| λ = 0.2 | ~0.015 | ~0.019 | ~0.025 | ~0.032 | ~0.034 |
| λ = 0.3 | ~0.078 | ~0.055 | ~0.046 | ~0.040 | ~0.037 |
| λ = 0.4 | ~0.170 | ~0.101 | ~0.068 | ~0.048 | ~0.040 |

**Check (section F).** The right chart fits S/B = 0.8 with σ = 17.8%, not the printed 22.2%. See below.

---

## Slide 20 (PDF 21). Risk management

- Sensitivities: "Equity Delta", "Equity Gamma", "Equity Vega", "Jump to default".
- Hedging instruments: "Stock", "Stock Puts & Calls of different strikes and maturities".
- "Transaction costs should be taken into consideration as the hedging strategy is not static."
- "Recovery Value of a bond/CDS is a big assumption. In Credit Derivatives this is not a unique case of this exposure to be important. Example: extinguishing CDS."
- "Equity Delta and Vega of CDS resemble those of OTM equity put option."

---

## Slide 21 (PDF 22). Hedging delta

**Printed.**
- "Consider selling $100 of 5yr default protection for quarterly coupon of 560 bp and 10% recovery."
- Stock Price = 40. Default Barrier = 15. Asset Volatility = 37.5%. 5yr CDS par spread = 422 bp.
- Potential hedges: Stock (price 40). 2yr Put strike 30 (price 5.22). 2yr Call strike 60 (price 6.31).
- "Equity delta can be hedged by shorting stock."

**Chart: Capital Allocation.** Stock ~−27.4. The "1" on the bar is a category label.

---

## Slide 22 (PDF 23). Hedging delta and vega

"To hedge Vega and Delta buy a Put to hedge Vega and neutralize Delta by using stock."

**Chart: Capital Allocation.** Put ~32.86. Stock ~31.85. Both positive.

---

## Slide 23 (PDF 24). Hedging delta and jump to default

"To hedge Jump to Default and Delta need to buy Puts and Stock."

**Chart: Capital Allocation.** Put ~26.4. Stock ~20.2. Both positive.

---

## Slide 24 (PDF 25). Hedging delta, vega and jump to default

"To hedge these three exposures simultaneously one needs to take long positions both in Put and Call and short stock."

**Chart: Capital Allocation. Printed.** Put 17.54. Stock −33.27. Call 14.68.

---

## Slide 25 (PDF 26). Hedging delta, vega and jump to default

"If a wide range of strikes is available, solve for an optimal strike and use just one option plus stock as a hedge." "Optimal strike = 39.2".

**Chart: Capital Allocation. Printed.** Put 49.13. Stock 46.41. Both positive.

---

## Slide 26 (PDF 27). Conclusions

1. "For credit derivatives the 'equity connection' brings a systematic approach to risk management and relative value analysis using traded securities with reasonable liquidity."
2. "The approach is based on observable market prices and leads to implied (not realized) default probabilities."
3. "In many cases a significant risk reduction can be achieved."
4. **Bold on the slide:** "The residual noise between the formula's credit spread and the market is diversifiable like a white noise."
5. "Basis risk and transaction costs always are a problem, but a manageable one."

---

## PDF page 28. Disclaimer

Goldman, Sachs & Co. disclaimer, "Copyright © 2002". No method content. It says the firm makes markets in fixed income securities of issuers discussed.

---

## Numbers that do not reproduce

| Slide | Deck | Mine | Likely reason, unverified |
|---|---:|---:|---|
| 1 | ATM put 4.92 | 5.24 at the printed 3% | The price fits r near 4.8%, not 3%. Both puts together fit r = 4.78% (4.91, 2.73). The rest of the deck fits r near 5% |
| 1 | OTM put 2.72 | 2.93 at the printed 3% | Same |
| 1 | 1.90 | 1.92 from the slide's own formula | Rounding, or a rate near 3.6% |
| 1 | 1.42 | 1.35 from the same formula | Any `K × PD × DF` rule makes 1.42/1.90 equal 10.5/15. It is 0.747 against 0.700. Undiscounted, 10.5 × 0.136 = 1.43 |
| 7 | Low-strike vols, K/F below 0.3 | Higher by about 0.1 to 0.2 | My values match if the chart's strike axis is read one step (0.05) lower. K/F of 0.5 and above match |
| 7 | Hidden caption | Gives ATM near 95% | Leftover text |
| 10 | Asset vol ~80% on day 240 | 54% with B = 6.9, ATM 105%, S ≈ 8 | Unknown. Asset vol stays flattest near B = 2 to 3, not at the printed 6.9. So the stability claim is not confirmed |
| 12 | Third bond model price 43 | 46.3 full, 42.7 clean, with the bootstrapped vol | The slide does not say clean or full. No one convention hits all three dates |
| 19 right | σ = 22.2% | 17.8% from σ_S = 40%, S/B = 0.8 | 22.2% = 40%/1.8, which treats 0.8 as B/S. The chart itself fits S/B = 0.8 with σ = 17.8% (29 bp rms against 159 bp) |
| 21 | 5y par 422 bp | 408 bp at λ = 0, r = 5% | λ is not stated. λ near 0.28 gives 422 |

## Numbers that reproduce

| Slide | Deck | Mine | Conditions |
|---|---:|---:|---|
| 1 | PD 13.6% | 13.58% | Annual premium, default at period end |
| 1 | OTM vol 77% | 76.6% to 76.7% | From ATM vol 72% and PD 0.136. Model solves B near 6.0 to 6.2 |
| 1 | CDS 530 bp | 519 to 544 bp | From the two option vols alone, r from 5% down to 3% |
| 6 | Chart | Exact | Formula |
| 8 | B = 0.42 D | 5.96 | Arithmetic |
| 8 | Ten model vols | Within 0.14 vol points | r = 5%, p = 0 |
| 8 | B = 6 | 6.01 | Fit to market vols only |
| 12 | Par curve | Within 17 bp | r = 5%, λ = 0, R = 30%, bootstrapped vol, flat forward after the last maturity |
| 12 | Bond 82, 60, 43 | 83.4, 59.9, 44.5 | Clean, flat 42%, r = 5%. Each within 1.5 points |
| 14 | Model peaks ~37%, ~47.5% | 37.7%, 48.5% | S = 1.8, σ = 42%, r = 5% |
| 14-15 | Market ~31%, PV ~−53 | 30.7% to 38.3%, −49.6 to −54.5 | Flat hazard fit to the bond |
| 19 left | Curves | 17 bp rms at σ = 42%, 50 bp at the printed 41% | r = 5% |
| 21 | Stock ~−27.4 | −26.9 at λ = 0, −26.3 at λ = 0.3 | Asset vol held fixed. Equity vol held fixed gives −11.1 |
| 21-25 | All 12 numbers | Worst 7.2% off, plain inputs. Worst 3.4% off, tuned | r = 5%, p = 2%, λ = 0.3 on CDS, λ = 0 on options, jump = (1 − R) × 100 |

---

## What the deck leaves unspecified

**Model.**
1. The closed form for the knock-out option (slide 6). I derived it by reflection. It reproduces slide 8.
2. Option pricing when `λ > 0`. Slides 17 to 19 cover survival only.
3. A default value of `λ`. Slide 19 shows 0 to 0.4 and picks none.
4. How `σ_t` is bootstrapped (slide 12). Interpolation and the extrapolation past the last option maturity are not stated.
5. What "continuously ATM option" and "ReferenceOption" mean on slide 10, including their maturity.
6. The rates. `r` is called a "stock financing rate" on slide 4 and "IR" on slide 1. No discount curve is given.

**Calibration.**
7. The objective for fitting `B` to the skew, the strikes used and the weights.
8. The definition of debt per share `D`. Slide 8 gives 14.2 for GX with no formula.
9. Whether `B` and `σ` are refit through time. Slides 12 to 15 hold them fixed. Slide 10 uses a fixed `B`.
10. American or European treatment of listed options, and dividends beyond the yield `p`.

**Credit.**
11. The CDS pricing formula: premium timing, accrual, day count, recovery timing.
12. How a bond price becomes a "market CDS curve" (slide 14).
13. The bond pricing formula: recovery of par or market, clean or full.
14. The source of `R`. Slide 14 shows that the choice of 30% or 10% matters. Slide 20 calls it "a big assumption".

**Hedging.**
15. Definitions of delta, gamma, vega and jump to default. Whether the contract value counts in the jump. Which vol is held fixed.
16. Option prices in default: discounted strike, or strike paid at once.
17. The rebalancing rule. Slide 20 says only that the hedge "is not static".
18. How "optimal strike" is defined. My reading: the strike where one put plus stock zeroes delta, vega and jump together. It lands near 39.2.

**Trading.**
19. **All of it.** There is no signal definition, entry, exit, sizing, stop, capital, return, cost number or backtest. Slide 2 says "trading framework". Slide 26 says "relative value analysis". That is the whole of the trading content.
20. Evidence for slide 26's "white noise" claim. The deck shows only GX and EXDS. Lardy's printed slides 26 and 27 carry the evidence, not this deck.

---

## Where this deck agrees with Lardy and CreditGrades, and where it differs

**It agrees on these.**
1. **The survival formula.** At flat vol, slide 18's Eq. (1) equals Lardy's printed slide 5 and CreditGrades 2.28. It also equals `e2c_bond.survival`, with a largest gap of 0 in my check (section H). Slide 3 and Lardy's printed slide 36 name the same four authors.
2. **The asset value.** `V_0 = S_0 + B` with zero drift. Lardy derives this on printed slides 10 to 12.
3. **The barrier idea.** `B = L̄ · D`, and `L̄` near 0.5.
4. **The white noise line.** Slide 26's bold sentence is nearly word for word the title of Lardy's printed slide 27. Lardy shows the evidence (average pairwise correlation 0.15 on 69 names, printed slide 26). This deck shows none.

**It differs on these.**
1. **Vol.** This deck uses a term structure `σ_cum(T)` from equity options. Lardy and CreditGrades use one flat vol.
2. **Barrier.** This deck reads it from the skew when it can. On GX that is 0.42 `D`. Lardy and CreditGrades fix `L̄ = 0.5`.
3. **Option pricing.** This deck prices options as knock-outs. Neither of the others prices an option.
4. **Short end.** This deck replaces the mass at `T = 0` with a flat intensity below 0.5 years. The others keep it.
5. **`λ`.** This deck shows 0 to 0.4 and picks none. The others fix 0.3. My fits give about 0 on GX and about 0.28 on the hedge example.
6. **Hedges.** This deck solves delta, vega and jump to default in stock, puts and calls. Lardy reports equity equivalents. CreditGrades reports delta, gamma and vega curves, and one hedge ratio.
7. **Evidence.** This deck has two names. Lardy has 142 names. CreditGrades has 122 firms.
8. **Bonds.** This deck builds its market curve from a bond on slide 14. Lardy's tests use CDS. CreditGrades uses CDS, with one bond spread in the Tyco case.

Yu's model is CreditGrades with `L̄` fitted on ten days of CDS, plus the only trading rule in this group. See `notes/paper_method/01_paper_extraction.md`.

Chen, Chen and Li (2026) extend CreditGrades with a payout drift and an exact barrier integral. Their gap is the bond-against-stock comparison that slides 12 to 15 make on one name, run on the cross-section with realised vol. They cite the CreditGrades document, which names Finkelstein and Lardy as authors. They do not cite this deck.

**Related documents I could not find in the files.** The CreditGrades bibliography (printed pp.51 onward) lists Finkelstein (2001), a Credit Risk Summit talk with this deck's title, Finkelstein and Lardy (2001), an ICBI talk, and Lardy, Finkelstein, Khuong-Huu and Yang (2000), an internal JPMorgan document with a patent application. They may hold what this deck leaves out. I have not seen them.
