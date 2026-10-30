# Yu (2005): exact extraction of how the arbitrage is computed

**Source.** Fan Yu, "How Profitable Is Capital Structure Arbitrage?", version of 3 April 2005, 40 pages (`E2C/ssrn-687436.pdf`).

**Page references.** "PDF p." is the page in the file. PDF page = printed page + 2. "CGTD" is the CreditGrades Technical Document, May 2002. For CGTD, PDF page = printed page + 6.

**How I read it.** I read every equation and table from a rendered page image. Images are in `pages/`. The text layer was used for prose only.

**Tags in this file.** "Stated" means the paper says it. "Inferred" means I worked it out from the paper, and I say from what. "Unspecified" means the paper does not say.

---

## 1. The computation in eight lines

1. Each day, take the 5-year CDS market spread `c_t`, the share price `S_t`, debt per share `D`, and the 1,000-day equity vol `σ_S`.
2. Fix `λ = 0.3` and `R = 0.5`. Set `r` to the 5-year Treasury yield.
3. On the obligor's first ten days, fit one number, the barrier level `L̄`, by least squares on the spread. Never refit it.
4. Compute the model spread `c'_t` from Eq. (12), using asset vol from Eq. (13).
5. Enter whenever `c_t > (1+α)c'_t` (sell protection, short stock) or `c'_t > (1+α)c_t` (buy protection, buy stock). Each qualifying day opens a new trade.
6. Hold `−δ` shares per $1 of notional, with `δ` from Eq. (15), fixed at entry.
7. Exit at `c_t = c'_t`, at the end of the holding period, at the end of the sample, or when the trade's value goes negative.
8. Mark the CDS with Eq. (6), using a survival-weighted annuity from the model. Divide P&L by a capital base of $0.5 per $1 notional. Equal-weight live trades daily and compound monthly.

---

## 2. Model equations

All are transcribed from page images. Symbols follow each block.

### CDS pricing (Section 2.1)

```
(1)  PV premium = E( c ∫_0^T exp(−∫_0^s r_u du) 1{τ>s} ds )                       PDF p. 7
(2)             = c ∫_0^T P(0,s) q_0(s) ds                                         PDF p. 7
(3)  PV protection = E( (1−R) exp(−∫_0^τ r_u du) 1{τ<T} )                          PDF p. 8
(4)                = −(1−R) ∫_0^T P(0,s) q_0'(s) ds                                PDF p. 8
(5)  c = −(1−R) ∫_0^T P(0,s) q_0'(s) ds  /  ∫_0^T P(0,s) q_0(s) ds                 PDF p. 8
(6)  π(t,T) = ( c(t,T) − c(0,T) ) ∫_t^T P(t,s) q_t(s) ds                           PDF p. 8
(7)  δ(t,T) = ∂π(t,T) / ∂S_t                                                       PDF p. 9
```

- `c`: CDS spread. `T`: contract maturity. `r`: risk-free rate. `τ`: default time.
- `P(0,s)`: default-free zero-coupon bond price. `q_0(s)`: risk-neutral survival probability at time 0.
- `R`: "the recovery of bond market value as a percentage of par in the event of default" (PDF p. 8).
- `π(t,T)`: value of a long (protection-buying) position held from 0 to t.
- `c(t,T)`: spread on a contract initiated at t with maturity date T.
- Assumptions (stated): continuous premium, no accrued premium, no cheapest-to-deliver option (PDF p. 7). Default is independent of rates.

### CreditGrades (Appendix A)

```
(9)  dV_t / V_t = σ dW_t                                                           PDF p. 35
(10) L D = L̄ D exp(λZ − λ²/2)                                                      PDF p. 35
(11) q(t) = Φ(−A_t/2 + ln d / A_t) − d · Φ(−A_t/2 − ln d / A_t)                    PDF p. 35
     d    = (V_0 / (L̄ D)) · exp(λ²)
     A_t² = σ² t + λ²
(12) c(0,T) = r (1−R) · (1 − q(0) + H(T)) / (q(0) − q(T) exp(−rT) − H(T))          PDF p. 36
     H(T) = exp(rξ) ( G(T+ξ) − G(ξ) )
     G(T) = d^(z+1/2) Φ(−ln d/(σ√T) − zσ√T) + d^(−z+1/2) Φ(−ln d/(σ√T) + zσ√T)
     ξ    = λ²/σ²
     z    = sqrt(1/4 + 2r/σ²)
(13) σ = σ_S · S / (S + L̄ D),   from the linear approximation V = S + L̄ D          PDF p. 36
(14) π(0,T) = (c(0,T) − c) ∫_0^T exp(−rs) q(s) ds
            = ((c(0,T) − c)/r) · ( q(0) − q(T) exp(−rT) − exp(rξ)(G(T+ξ) − G(T)) ) PDF p. 36
(15) δ(0,T) = (1/r) (∂c(0,T)/∂S) · ( q(0) − q(T) exp(−rT) − exp(rξ)(G(T+ξ) − G(T)) ) PDF p. 37
```

- `V_t`: firm value per share. `σ`: asset vol. `W`: Brownian motion. `D`: debt per share, constant.
- `L`: random global recovery. `L̄ = E(L)`. `λ² = var(ln L)`. `Z`: standard normal.
- `Φ`: normal CDF. `S`: equity price. `σ_S`: equity vol. `c` in (14): the spread at which the contract was first initiated.
- `L` is the recovery on all liabilities. `R` is the recovery on the specific issue under the CDS (PDF p. 35).

**Eqs. (14) and (15) contain a misprint.** See Section 13.

### Trading trigger (Section 4)

```
(8)  c_t > (1+α) c'_t   or   c'_t > (1+α) c_t                                      PDF p. 20
```

`c_t` is the market spread. `c'_t` is the model spread. `α` is the trading trigger.

### Pricing error (Section 2.2)

```
e_t = c_t − c'_t                 PDF p. 10
c'_t = f(S_t, σ; θ)              PDF p. 10   (σ is an estimate of asset vol, θ holds the other fixed parameters)
c_t  = f(S_t, σ^imp; θ)          PDF p. 10   (σ^imp is the implied asset vol from inverting the pricing equation)
```

---

## 3. Inputs

| Input | Definition | Source | Timing | PDF p. |
|---|---|---|---|---|
| `c_t` | Daily composite spread, 5-year CDS, senior unsecured, North American obligors, modified restructuring, USD | Markit | Daily, 2001 to 2004. A composite exists only with more than three contributors | 14 |
| `S_t` | Equity price | CRSP daily stock file | Daily | 14 |
| `D` | Total liabilities / common shares outstanding | Compustat quarterly | Lagged one month from quarter end | 14, 17 |
| `σ_S` | "1,000-day historical equity volatility" | Equity history | Daily. Figure 2 shows it moving, so I infer a rolling window | 17, 20 |
| `r` | Five-year constant maturity Treasury yield | Datastream | Daily, inferred from "time-series" use | 14, 17 |
| 3-month T-bill | Obtained, use not spelled out | Datastream | Unspecified | 14 |
| `R` | 0.5, consistent with Moody's historical recovery on senior unsecured | Fixed | Constant | 17, 18 |
| `λ` | 0.3, motivated by the CGTD | Fixed | Constant | 17, 18 |
| `L̄` | Fitted, see Section 4 | Fitted | First ten days only | 18 |

Corporate actions (footnote 14, PDF pp. 14-15): no adjustment to the model spread for cash dividends or stock splits. For stock dividends or spinoffs, the balance sheet variables are adjusted so the model spread stays unchanged through the event, until the next quarterly update.

---

## 4. Parameters and calibration

- `λ = 0.3`, `R = 0.5`. Fixed for all obligors and dates (PDF p. 17).
- `L̄` is fitted "by minimizing the sum of squared pricing errors over L̄" on "the 10 daily CDS spreads at the start of the sample period" (PDF p. 18).
- The first ten daily observations "are set aside for use in the model estimation procedure" (PDF p. 17).
- Altria's fit gives `L̄ = 0.62` (PDF p. 18).
- `L̄` is not refitted. The model tracks Altria "despite calibrating the model using only the first ten observations" (PDF p. 20). The conclusion states the same general procedure (PDF p. 34).
- Yu's stated reason: fix `R` and "let the data speak to the value of L̄", because traders who fit `R` often find values "negative or close to 1" (PDF p. 18).

**Inferred.** Section 5 applies "the preceding trading strategy" to all 261 obligors, so each obligor gets its own `L̄` from its own first ten days. The paper reports only Altria's value.

**Derived by me, not stated.** In Eqs. (11)-(13), `D` appears only through the product `L̄D`. So `L̄` fits the barrier level. The definition of `D` affects the level only through the fitted `L̄`. It still matters through later changes in `D`. A test in `test_e2c_bond.py` confirms this.

---

## 5. Signal

- The implemented signal is Eq. (8), a ratio test on spreads (PDF p. 20).
- Trigger values tested: `α = 0.5, 1, 2` (PDF p. 22).
- Section 2.2 mentions `e_t > E(e) + 2σ(e)` "for example". That is an illustration of the idea. The trading exercise does not use it (PDF p. 10).
- The check runs "for each of the 962 days" for Altria (PDF p. 20).

**Inferred: one new trade per qualifying day.** `N` in Table 2 is the same at both holding periods (550, 319, 154). A trade count that independent of holding period means entries do not wait for earlier trades to exit. Section 6 confirms overlap: "on a given day there are n ongoing trades" (PDF p. 28).

**How often it fires (my arithmetic from Table 3, PDF p. 26, and the 135,759 obligor-days).** Removing ten days per obligor leaves 133,149. Trades are then 50.3% of days at `α = 0.5`, 30.8% at `α = 1`, and 14.5% at `α = 2`.

---

## 6. Entry, exit, holding period, stop

| Item | Rule | PDF p. |
|---|---|---|
| Entry 1 | `c_t > (1+α)c'_t`: short $1 CDS notional and short `−δ_t` shares | 20 |
| Entry 2 | `c'_t > (1+α)c_t`: long $1 CDS notional and buy `−δ_t` shares | 20 |
| Exit, convergence | `c_t = c'_t` | 20 |
| Exit, time | End of the holding period (30 or 180 days) or end of the sample | 12, 20, 22 |
| Exit, liquidation | "a trade is liquidated whenever its total value becomes negative" | 20 |
| Liquidity | "the arbitrageur will be forced to close out his positions once the liquidity in the obligor vanishes" | 15 |
| Monitored only | Drawdowns over 20% are counted as `N2`. They do not trigger an exit | 20 |
| Default or acquisition | No explicit rule. Yu expects the CDS market to reflect these early enough to exit | 12 |

`δ` is negative for long protection, so `−δ` is a positive number of shares. Both directions therefore trade equity the same way as the CDS leg.

---

## 7. Hedge ratio

- Formula: Eq. (15), with `∂c/∂S` found numerically: "I then differentiate c(0,T) numerically with respect to S" (PDF p. 37).
- Eq. (15) follows from (14) by the product rule, because `c(0,T) − c = 0` at inception.
- Set at entry from the model spread: "I set the hedge ratio to correspond to the model CDS spread ... when entering the trade and fix this hedge ratio throughout the trade" (PDF p. 11).
- Base case: static, no rebalancing. Variant "Hedge": rebalanced daily, with no equity cost (PDF pp. 32-33).

---

## 8. Position P&L

**CDS leg.**
- Marked by Eq. (6). Yu approximates `c(t,T)` with `c(t,t+T)`, the quote on a fresh fixed-maturity contract, so no secondary quote is needed (PDF p. 13).
- The annuity uses model survival probabilities, "plugging the historical equity volatility into the CG model" (PDF p. 13).
- Approximation (14) treats `t` as small against `T`, and represents "a contract which was entered into one instant ago at spread c" now quoted at `c(0,T)` (PDF pp. 36-37).
- Premiums are cash flows into or out of the margin account (footnote 12, PDF p. 12).

**Equity leg.** Change in share price times shares. Yu calls this "trivial" (PDF p. 13). Dividends go to the margin account (footnote 12).

**Recovery or default payment.** No default payment is modelled in the trade. Yu argues that the market will reflect a default long before it happens, leaving time to exit (PDF p. 12). The WorldCom sample ends two months before its bankruptcy (PDF p. 25).

**Variant "Value" (PDF pp. 32-33).** The annuity is discounted at the risk-free rate plus the market CDS spread divided by `1 − R`, with `R = 0.5`. This follows Duffie and Singleton (1999), and it replaces the model survival curve.

---

## 9. Return definition and aggregation

- **Capital.** "a certain amount of initial capital deposited into a margin account", which also finances the initial equity hedge (footnote 12, PDF p. 12).
- **Capital levels.** $0.1 and $0.5 per $1 of notional for Altria (PDF p. 22). $0.5 for all later results (PDF pp. 23, 29).
- **Why $0.5.** It leaves very few trades over the 20% drawdown, so Sharpe ratios depend little on the capital choice (PDF p. 23).
- **Trade return.** Holding period return in percent. The formula is not printed.
- **Daily return.** "To ensure that daily returns from the trades are properly defined, I impose a limited liability assumption" (PDF p. 20). **Inferred:** daily return is P&L over the prior day's trade value, which needs that value to be positive.
- **Portfolio.** Each day, equal-weight the daily excess returns of all `n` live trades. Compound to monthly (PDF pp. 28-29). A month with no trades has zero excess return (PDF p. 29).
- **Monthly statistics.** `N` counts months with non-zero returns (PDF p. 29). **Inferred:** median and `Neg` use all 48 months. The Spec row at `α = 2` has N = 25, Neg = 0.29 and median 0, which fits only 14/48.
- **Sharpe.** "annualized Sharpe ratio" (PDF p. 29). **Checked:** `sqrt(12) × Mean / Std` lands within rounding of all 18 published values in Tables 4 and 7.
- **Statistical arbitrage test (PDF p. 30).** `Φ_i = r_i − r_i^f + Φ_{i−1}(1 + r_i^f)`. `Δφ_i` is the discounted increment, normal with mean `μ` and variance `σ²(Δt_i)^{2λ}`. Test `μ > 0` and `λ < 0`. This `λ` is not the barrier `λ`.
- **Factor test (PDF p. 31).** Regress monthly returns on excess returns of S&P Industrials, Lehman Baa and Ba Intermediate, and CSFB/Tremont Fixed Income Arbitrage.

---

## 10. Transaction costs

- CDS: a proportional 5% bid/ask on the spread, for all obligors and dates (PDF pp. 13-14).
- Worked in the paper: at 100 bp, the buyer pays 102.5 bp and the seller receives 97.5 bp. At 1,000 bp, the bid/ask is 50 bp.
- Equity: ignored. The CDS spread "is probably the single largest source", and static hedging trades little (PDF p. 14).
- Variant "Trans": 10% bid/ask (PDF p. 33).

---

## 11. Filters

| Filter | Rule | PDF p. |
|---|---|---|
| Contract | 5-year, senior unsecured, North American, modified restructuring, USD | 14 |
| Merge | Needs equity price and balance sheet data | 14 |
| Continuity | For each obligor, the longest string of more than 252 daily spreads no more than 14 calendar days apart | 15 |
| Sector | Excludes financials and utilities | 16 |
| Result | 135,759 daily spreads on 261 obligors | 15 |
| Rating groups | S&P rating at the end of the sample. 210 investment grade, 51 speculative. The speculative group includes two unrated names (WorldCom, Qwest) | 16, 24 |

**Look-ahead in the filters (my reading).** The continuity filter uses future data. The rating split uses end-of-sample ratings, and Yu flags that this differs from usual practice (PDF p. 16). Neither is a tradable rule.

---

## 12. Results a replicator should hit

### Table 1: obligors (PDF p. 16)

| Category | N | SPD (bp) | VOL | LEV | SIZE ($mm) | CORR |
|---|---:|---:|---:|---:|---:|---:|
| AAA | 4 | 13 | 0.30 | 0.29 | 257,415 | 0.01 |
| AA | 12 | 16 | 0.32 | 0.20 | 81,306 | -0.06 |
| A | 68 | 37 | 0.37 | 0.32 | 30,123 | -0.04 |
| BBB | 126 | 84 | 0.39 | 0.46 | 9,381 | -0.05 |
| BB | 35 | 247 | 0.51 | 0.56 | 7,162 | -0.07 |
| B | 11 | 444 | 0.65 | 0.66 | 3,627 | -0.12 |
| CCC | 3 | 627 | 0.56 | 0.82 | 3,949 | -0.23 |
| NR | 2 | 388 | 0.73 | 0.68 | 22,858 | -0.16 |
| Comm. and Tech. | 35 | 153 | 0.51 | 0.42 | 32,373 | -0.07 |
| Consumer Cyclical | 56 | 134 | 0.43 | 0.45 | 15,850 | -0.07 |
| Consumer Stable | 49 | 75 | 0.36 | 0.34 | 34,926 | -0.07 |
| Diversified | 1 | 81 | 0.29 | 0.40 | 8,057 | -0.02 |
| Energy | 30 | 96 | 0.39 | 0.46 | 20,142 | -0.03 |
| Industrial | 52 | 102 | 0.42 | 0.46 | 18,542 | -0.05 |
| Materials | 38 | 126 | 0.39 | 0.50 | 7,224 | -0.04 |

LEV is total liabilities / (total liabilities + market cap). CORR is between daily changes in CDS spread and equity price.

### Table 2: Altria holding period returns, percent (PDF p. 22)

`N` trades, `N1` converged, `N2` drawdown over 20%, `N3` negative return.

| Capital | HP | α | N | N1 | N2 | N3 | Mean | Min | Max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.1 | 30 | 0.5 | 550 | 0 | 104 | 260 | 0.10 | -104.56 | 94.24 |
| 0.1 | 30 | 1 | 319 | 0 | 53 | 142 | 2.46 | -44.66 | 94.24 |
| 0.1 | 30 | 2 | 154 | 0 | 14 | 56 | 2.22 | -20.08 | 18.04 |
| 0.1 | 180 | 0.5 | 550 | 76 | 235 | 140 | 20.20 | -104.56 | 113.37 |
| 0.1 | 180 | 1 | 319 | 8 | 96 | 61 | 24.68 | -25.10 | 113.37 |
| 0.1 | 180 | 2 | 154 | 0 | 25 | 19 | 18.03 | -2.68 | 43.46 |
| 0.5 | 30 | 0.5 | 550 | 0 | 1 | 252 | 0.14 | -10.68 | 18.92 |
| 0.5 | 30 | 1 | 319 | 0 | 0 | 138 | 0.58 | -8.87 | 18.92 |
| 0.5 | 30 | 2 | 154 | 0 | 0 | 54 | 0.55 | -3.91 | 3.75 |
| 0.5 | 180 | 0.5 | 550 | 76 | 1 | 134 | 4.50 | -4.63 | 23.06 |
| 0.5 | 180 | 1 | 319 | 8 | 0 | 60 | 5.37 | -4.52 | 23.06 |
| 0.5 | 180 | 2 | 154 | 0 | 0 | 18 | 4.04 | -5.32 | 9.30 |

### Table 3: all obligors, capital $0.5, percent (PDF p. 26)

| Rating | HP | α | N | N1 | N2 | N3 | Mean | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| INV | 30 | 0.5 | 57,621 | 372 | 70 | 28,512 | -0.03 | -75.16 | 50.97 |
| INV | 30 | 1 | 37,125 | 25 | 50 | 17,387 | 0.03 | -75.16 | 50.97 |
| INV | 30 | 2 | 18,173 | 0 | 13 | 7,453 | 0.13 | -8.50 | 50.97 |
| INV | 180 | 0.5 | 57,621 | 5,615 | 215 | 17,872 | 0.84 | -88.71 | 104.41 |
| INV | 180 | 1 | 37,125 | 1,235 | 83 | 10,140 | 0.96 | -45.69 | 104.41 |
| INV | 180 | 2 | 18,173 | 142 | 25 | 4,140 | 1.02 | -13.37 | 104.41 |
| SPEC | 30 | 0.5 | 9,315 | 111 | 204 | 5,503 | -0.52 | -49.75 | 45.60 |
| SPEC | 30 | 1 | 3,912 | 0 | 49 | 2,302 | -0.12 | -49.75 | 31.91 |
| SPEC | 30 | 2 | 1,191 | 0 | 0 | 746 | -0.31 | -7.41 | 29.31 |
| SPEC | 180 | 0.5 | 9,315 | 1,883 | 480 | 4,610 | 2.78 | -54.60 | 70.29 |
| SPEC | 180 | 1 | 3,912 | 367 | 94 | 2,238 | 1.95 | -31.63 | 70.29 |
| SPEC | 180 | 2 | 1,191 | 85 | 0 | 795 | 0.05 | -11.32 | 68.72 |

**What this means (my arithmetic).** Convergence is rare even over 180 days: 9.7% of INV trades and 20.2% of SPEC trades at `α = 0.5`, and 0.8% and 7.1% at `α = 2`. Most trades end on the holding period.

### Table 4: monthly excess returns, capital $0.5, 180 days, percent (PDF p. 29)

| | α | N | Mean | Med | Min | Max | Std | Corr | Neg | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Inv | 0.5 | 48 | 0.13 | 0.05 | -3.20 | 3.05 | 1.13 | 0.04 | 0.48 | 0.39 |
| Inv | 1 | 46 | 0.13 | 0.01 | -4.37 | 3.86 | 1.33 | -0.10 | 0.44 | 0.35 |
| Inv | 2 | 45 | 0.30 | 0.11 | -2.60 | 4.92 | 1.27 | 0.09 | 0.38 | 0.80 |
| Spec | 0.5 | 45 | 0.67 | 0.30 | -9.37 | 13.04 | 3.16 | 0.20 | 0.40 | 0.74 |
| Spec | 1 | 42 | 1.01 | 0.00 | -9.87 | 14.18 | 4.63 | -0.20 | 0.40 | 0.76 |
| Spec | 2 | 25 | 0.93 | 0.00 | -2.62 | 21.87 | 4.32 | 0.49 | 0.29 | 0.74 |

### Table 5: statistical arbitrage test (PDF p. 30)

Standard errors are in parentheses. `μ` and `σ` are in percent. "None of the strategies give rise to statistical arbitrage at conventional significance levels."

| | α | μ | σ | λ |
|---|---:|---:|---:|---:|
| Inv | 0.5 | 0.17 (0.15) | 1.2 (0.2) | -0.56 (0.19) |
| Inv | 1 | 0.16 (0.17) | 1.4 (0.2) | -0.56 (0.16) |
| Inv | 2 | 0.23 (0.24) | 1.4 (0.2) | -0.42 (0.17) |
| Spec | 0.5 | 0.60 (0.46) | 2.7 (0.3) | 0.22 (0.17) |
| Spec | 1 | 0.45 (0.65) | 5.5 (0.6) | -0.63 (0.16) |

### Table 6: factor regressions (PDF p. 31)

Second figure is the standard error (the June version's caption says so).

| | α | Int. | S&PINDS | LHIBAAI | LHHYBBI | CSTINFA | R² |
|---|---:|---:|---:|---:|---:|---:|---:|
| Inv | 0.5 | 0.22 (0.17) | 0.026 (0.037) | -0.19 (0.13) | -0.04 (0.10) | -0.18 (0.17) | 0.11 |
| Inv | 1 | 0.15 (0.21) | -0.014 (0.045) | -0.19 (0.16) | -0.02 (0.12) | -0.04 (0.21) | 0.05 |
| Inv | 2 | 0.27 (0.20) | -0.01 (0.04) | -0.14 (0.16) | -0.01 (0.11) | 0.13 (0.20) | 0.03 |
| Spec | 0.5 | 0.44 (0.48) | 0.06 (0.10) | 0.22 (0.37) | -0.06 (0.27) | 0.94 (0.47) | 0.12 |
| Spec | 1 | 0.81 (0.72) | 0.08 (0.15) | 0.37 (0.55) | -0.41 (0.40) | 1.02 (0.71) | 0.07 |
| Spec | 2 | 1.03 (0.69) | 0.04 (0.15) | 0.38 (0.53) | -0.14 (0.39) | -0.23 (0.68) | 0.02 |

### Table 7: variations, capital $0.5, 180 days, percent (PDF p. 33)

| | α | N | Mean | Med | Min | Max | Std | Corr | Neg | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All | 0.5 | 48 | 0.27 | 0.13 | -3.20 | 5.05 | 1.27 | 0.21 | 0.40 | 0.72 |
| All | 1 | 46 | 0.25 | 0.05 | -4.37 | 4.87 | 1.50 | 0.06 | 0.40 | 0.57 |
| All | 2 | 45 | 0.32 | 0.08 | -2.60 | 5.16 | 1.29 | 0.14 | 0.38 | 0.87 |
| Value | 0.5 | 48 | 0.16 | 0.06 | -3.43 | 4.52 | 1.26 | 0.21 | 0.42 | 0.45 |
| Value | 1 | 46 | 0.19 | 0.03 | -4.50 | 4.58 | 1.39 | 0.09 | 0.40 | 0.48 |
| Value | 2 | 45 | 0.33 | 0.08 | -2.45 | 5.13 | 1.26 | 0.12 | 0.35 | 0.89 |
| Hedge | 0.5 | 48 | 0.22 | 0.09 | -3.27 | 5.27 | 1.31 | 0.23 | 0.40 | 0.58 |
| Hedge | 1 | 46 | 0.23 | 0.06 | -4.54 | 5.03 | 1.53 | 0.06 | 0.35 | 0.52 |
| Hedge | 2 | 45 | 0.32 | 0.08 | -2.45 | 5.31 | 1.31 | 0.15 | 0.35 | 0.84 |
| Trans | 0.5 | 48 | 0.17 | -0.01 | -5.31 | 5.82 | 1.69 | 0.20 | 0.52 | 0.36 |
| Trans | 1 | 46 | 0.07 | 0.00 | -5.66 | 4.98 | 1.58 | 0.19 | 0.47 | 0.15 |
| Trans | 2 | 45 | 0.19 | 0.04 | -4.46 | 5.39 | 1.40 | 0.16 | 0.42 | 0.47 |

### Single numbers in the text

| Item | Value | PDF p. |
|---|---|---|
| Altria sample | 28 Feb 2001 to 31 Dec 2004, 962 daily spreads | 17 |
| Altria fitted `L̄` | 0.62 | 18 |
| Altria CORR | -0.25 | 18, 20 |
| Altria, 31 Mar 2003 | Market 210 to 299 bp, model up 11 bp | 20 |
| Altria, four days later | Market up 171 bp in one day, model up 8 bp | 20 |
| Altria, `α = 0.5` entry on 31 Mar 2003 | Market 299, model 168. Market 529 four days later. Stock down $1.66. Margin depleted, -100% | 22-23 |
| WorldCom, 10% capital, `α = 0.5` | Entry 7 Sep 2001, market 128, model 193. Exit 31 Oct, market 220, model 191. Return 37% | 25 |
| Hanson account (Euromoney) | €10m CDS, 95 to 140 bp, CDS gain €195,000, equity gain €16,000 | 3 |

---

## 13. What looks wrong

1. **Eqs. (14) and (15) print `G(T)` where they need `G(ξ)`.** The integral `∫_0^T e^{-rs} q(s) ds` equals `(q(0) − q(T)e^{-rT} − H(T))/r`, and `H(T)` uses `G(ξ)`. Eq. (12) and CGTD A.13-A.14 both use `G(ξ)`. A numeric test settles it: at S=30, D=30, L̄=0.5, λ=0.3, σ=0.25, r=5%, T=5, the integral is 4.2676. The `G(ξ)` form gives 4.2676. The printed form gives 5.3116, above the riskless annuity of 4.4240, which is impossible. The June version repeats the misprint. The printed formula would overstate both P&L and hedge ratio by 24% at this point, if coded literally.

2. **Eq. (5) does not lead to Eq. (12) as written.** Eqs. (3) to (5) have no mass at time zero. Eq. (12) has the term `1 − q(0)` in its numerator. That term is the default mass at `t = 0` that footnote 22 describes. CGTD A.6 includes it explicitly. Use Eq. (12).

3. **Yu's CDS spread has no Act/360 scaling, and the CGTD's does.** CGTD p. 9 (PDF 15) adjusts "for the market's Act/360 pricing convention". My code reproduces all 156 cells of CGTD Table C.1 only with the ×360/365 scaling. Without it, the largest gap is 11.6 bp. Yu does not mention this. If he did not scale, his model spreads are about 1.4% higher than a CreditGrades screen would show. The fit of `L̄` absorbs most of that.

4. **Yu calls the WorldCom numbers "very close" to the CGTD case. They differ by about 30 to 60 bp.** Yu has market 128 and model 193 on 7 Sep 2001 (PDF p. 25). The CGTD has 165 to 175 and 225 to 250 for September 2001 (CGTD p. 34, PDF 40). Different `D` and dates may explain this. I cannot check it.

5. **The currency in the Hanson quote.** April says "$2.91 (€4.40)". June says "£2.91". The June reading fits the euro conversion.

6. **Table 2 shows returns below -100%, while the text says the maximum loss is -100%.** The -104.56% minimum is consistent with daily monitoring, where value can go past zero before liquidation. This is my inference.

---

## 14. What the paper leaves unspecified

These all change the numbers. My choice for the bond version is in `02_bond_vol_method.md`.

1. **Which vol stays fixed in the delta.** Eq. (15) says `c(0,T)` is "a function of the equity price S". Eq. (13) ties asset vol to `S`. Yu does not say whether the numeric derivative holds `σ` or `σ_S` fixed. This is large. On the CGTD WorldCom inputs, the notional-to-stock hedge is 7.0:1 holding asset vol and 15.4:1 holding equity vol, a factor of 2.2. The CGTD holds asset vol fixed (p. 36, Figures 2.3 to 2.5).
2. **Daily vs reference price in Eq. (13).** I read it as the current price. The CGTD allows a reference price `S*` (2.27) and also uses the current price (3.1).
3. **Formula for the 1,000-day vol.** No statement on log or simple returns, window end date, annualisation factor, or what happens with fewer than 1,000 days.
4. **Days in the holding period.** "30 days and 180 days" does not say calendar or trading. **Inferred calendar:** the text treats the holding horizon as "six months" (PDF p. 13).
5. **What counts as `c_t = c'_t` on daily data.** I read it as the gap reaching zero or changing sign.
6. **The first ten days.** They "are set aside", yet the check runs "for each of the 962 days". So `N` may count from day 1 or day 11.
7. **How the bid/ask enters the marks.** The paper states the entry and exit prices at 100 bp. It does not say if daily marks use mid or the exit side.
8. **Trade return formula.** Holding period return is not written out. **Inferred:** total P&L over initial capital.
9. **Drawdown definition.** Table 2 has `N2 = 1` with a minimum final return of -4.63% at capital 0.5, 180 days. So **inferred:** drawdown is measured within the trade from a peak, and is not the final return.
10. **Interest on the margin account, and what "excess" subtracts.** The paper never says. The T-bill is the likely benchmark, and Table 5 uses a monthly risk-free rate, but neither is tied to the daily calculation.
11. **Financing when the hedge exceeds capital.** At capital $0.1, the equity hedge can exceed the margin account. No rule is given.
12. **Short-sale costs and rebates on the stock.** Not mentioned. Only trading costs are discussed, and those are ignored.
13. **Calendar handling of `T` in the annuity.** Eq. (14) keeps full `T`. The paper does not say whether a held contract rolls down.
14. **Timing within a day.** The paper implies same-day signal and execution at the daily mark. It does not address the gap between the CDS quote and the equity close.
15. **Fitting range for `L̄`.** No bounds are given, and no treatment is stated for names that cannot fit.
16. **Which obligor gets which first ten days after the continuity filter.** I read it as the first ten days of the selected string.

---

## 15. Yu against the CreditGrades Technical Document

| Item | Yu | CGTD | Effect |
|---|---|---|---|
| Survival, spread formula | Eqs. (11), (12) | 2.28, 2.15 | Same |
| `L̄` | Fitted per obligor | 0.5, fixed | Yu's `L̄` absorbs level error |
| `R` | 0.5, fixed | Bond-specific, from a JP Morgan database. Table C.1 uses 0.5 | Yu notes this "crucial" change (PDF p. 18) |
| `D` | Total liabilities / common shares | Financial debt + 0.5 × other liabilities − minority adjustment, over common plus preferred-equivalent shares (B.1 to B.7) | Yu's `D` is larger, so a fitted `L̄` is not comparable to 0.5 |
| `r` | 5-year CMT Treasury | 5-year LIBOR (p. 17) | Level effect, absorbed by fit |
| Day count | Continuous, no scaling stated | ×360/365 | See Section 13 |
| Vol | 1,000-day, same | 1,000-day chosen as best fit of implied asset vol (pp. 18-19) | Same |
| Delta | Annuity × `∂c/∂S` | Figures use the contingent leg only (footnote 5, p. 14). The WorldCom case uses `Δc × spread duration` (p. 36) | Small for low spreads |

---

## 16. The other PDF (`yu-2006-how-profitable-capital-structure-arbitrage.pdf`)

**It is not the published article.** It is the working paper dated 3 June 2005, 38 pages. Your `manifest.tsv` says so too. I have not seen the Financial Analysts Journal typeset version.

A word-level comparison found no change to the method. All 84 numeric table rows match, apart from the rounding in item 3.

1. Hanson's share price changes from $ to £.
2. Liu and Longstaff (2004) becomes Duarte, Longstaff and Yu (2005). "five times more initial capital" becomes "ten times", with $0.05 capital in the comparison study.
3. Table 6 rounds its first two Inv rows to two decimals (0.026 to 0.03, 0.037 to 0.04, -0.014 to -0.01, 0.045 to 0.05). The caption adds that standard errors are below the estimates.
4. "without a rating" becomes "without an average rating" for the two unrated names.
5. Eqs. (14) and (15) keep the `G(T)` misprint.
