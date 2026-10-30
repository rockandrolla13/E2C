"""Worked example for 02_bond_vol_method.md. EVERY INPUT HERE IS MADE UP.

One hypothetical issuer and one hypothetical bond, walked through every step with e2c_bond.py.
Each line is tagged [function name], and the document turns the lines into its table.
Run: python3 worked_example.py
"""
from dataclasses import replace

import numpy as np

import e2c_bond as m


def show(function: str, text: str) -> None:
    print(f"[{function}] {text}")


def bp(x: float) -> str:
    return f"{x * 1e4:,.1f} bp"


DAY = 1 / 360
ALPHA = 0.5
BETA = 0.20
K = 0.5
COUPON = 0.055
YEARS_LEFT = 4.8
LIABILITIES = 14_000e6
LIABILITIES_NEW = 14_400e6
SHARES = 500e6
ROUND_TRIP = 0.0100
STOCK_HALF = 0.0005
TSY_HALF = 0.00005


def bond_on(calendar_days: int) -> m.Bond:
    return m.Bond(COUPON, YEARS_LEFT - calendar_days * DAY)


def shifted(curve: m.ZeroCurve, dy: float) -> m.ZeroCurve:
    return m.ZeroCurve(curve.tenors, tuple(z + dy for z in curve.zeros))


# ---------------------------------------------------------------- Part 1. Issuer and bond

show("issuer_is_eligible", f"Industrial issuer with listed stock: {m.issuer_is_eligible('industrial', True)}.")
show("bond_terms_are_eligible", "Senior unsecured, USD, fixed, make-whole call, no other option: "
     f"{m.bond_terms_are_eligible('senior_unsecured', 'USD', 'fixed', 'make_whole', False, False, False, False, False)}.")
show("callable_is_usable", f"Make-whole call, so the test does not apply: {m.callable_is_usable('make_whole', 0.99, float('nan'))}.")
show("maturity_is_eligible", f"{YEARS_LEFT} years left: {m.maturity_is_eligible(YEARS_LEFT, True)}.")
show("age_and_size_are_eligible", f"1.5 years old, {YEARS_LEFT} left, USD 750mm: {m.age_and_size_are_eligible(1.5, YEARS_LEFT, 750e6)}.")
chosen = m.pick_bond_and_sibling(["BOND_A", "BOND_B", "BOND_C"], [140, 90, 30])
show("pick_bond_and_sibling", f"60-day trades 140, 90, 30: bond {chosen[0]}, sibling {chosen[1]}.")
show("passes_liquidity_screen", f"14 institutional trades in five days: {m.passes_liquidity_screen(14)}.")

# ---------------------------------------------------------------- Part 2. Inputs

D0 = m.debt_per_share(LIABILITIES, SHARES)
show("debt_per_share", f"USD 14,000mm over 500mm shares: D = {D0:.2f}.")
usable = m.filing_usable_from("2024-05-07", "2024-03-31", "10-Q")
show("filing_usable_from", f"10-Q accepted Tue 2024-05-07: usable from {usable}.")
spin_firm = m.Firm(30.0, D0, 0.38, 0.8)
show("debt_after_corporate_action", f"Spinoff takes the stock from 30 to 27: D moves from {D0:.2f} to "
     f"{m.debt_after_corporate_action(spin_firm, 27.0, 5.0, 0.5, 0.0395):.2f}, and the model spread does not move.")

rng = np.random.default_rng(7)
raw = rng.standard_normal(1000)
returns = (raw - raw.mean()) / raw.std(ddof=1) * 0.38 / np.sqrt(252)
SIGMA_S = m.historical_equity_vol(returns)
show("historical_equity_vol", f"1,000 daily returns: {SIGMA_S:.4f}.")
show("equity_vol_input", f"Source 'historical', with implied vol 0.42 on hand: {m.equity_vol_input('historical', SIGMA_S, 0.42):.4f}.")

TENORS = (0.25, 1, 2, 3, 5, 7, 10, 30)
PAR_YIELDS = (0.0435, 0.0415, 0.0392, 0.0386, 0.0396, 0.0411, 0.0431, 0.0460)
CURVE = m.zero_curve_from_par_yields(TENORS, PAR_YIELDS)
R_5Y = 0.0396
show("zero_curve_from_par_yields", f"Par yields 4.35% to 4.60%: zero rates at 1, 5, 10 years "
     f"{np.interp(1, CURVE.tenors, CURVE.zeros):.4%}, {np.interp(5, CURVE.tenors, CURVE.zeros):.4%}, {np.interp(10, CURVE.tenors, CURVE.zeros):.4%}.")

# ---------------------------------------------------------------- Part 3. Market spread on the signal day (day 84)

SIGNAL_DAYS = 84
bond_sig = bond_on(SIGNAL_DAYS)
reports = {
    "msg_seq":      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
    "orig_msg_seq": [0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0],
    "action":       ["new"] * 8 + ["cancel"] + ["new"] * 4,
    "duplicate":    [False] * 12 + [True],
    "price":        [93.5, 92.5, 97.0, 93.5, 925.0, 93.5, 50.0, 92.5, 97.0, 93.5, 92.5, 95.0, 93.5],
    "size":         [5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 5e5, 2e4, 5e5],
    "buy":          [True, False, True, True, False, True, False, False, True, True, False, True, True],
}
keep = m.clean_trade_reports(reports["msg_seq"], reports["orig_msg_seq"], reports["action"], reports["duplicate"])
show("clean_trade_reports", f"13 reports in. {int(keep.sum())} kept. Dropped: one cancel, the report it cancels, one duplicate side.")
fixed = m.fix_decimal_shifts(np.array(reports["price"])[keep])
show("fix_decimal_shifts", "Price 925.00 corrected to " f"{fixed[np.array(reports['price'])[keep] == 925.0][0]:.2f}. Others unchanged.")
spikes = m.flag_price_spikes(fixed)
show("flag_price_spikes", f"Flagged {int(spikes.sum())} print: {fixed[spikes][0]:.2f}, which reverted on the next print.")
good = ~spikes
sizes = np.array(reports["size"])[keep][good]
buys = np.array(reports["buy"])[keep][good]
CLEAN_SIG, one_sided = m.daily_clean_price(fixed[good], sizes, buys)
show("daily_clean_price", f"Buys 93.50, sells 92.50, one small trade ignored: clean price {CLEAN_SIG:.4f}, one-sided {one_sided}.")
FULL_SIG = m.full_price(CLEAN_SIG, bond_sig)
show("full_price", f"Accrued {m.accrued_interest(bond_sig):.5f}: full price {FULL_SIG:.5f}.")
z_mkt = m.z_spread(FULL_SIG, bond_sig, CURVE)
show("z_spread", f"Market Z-spread {bp(z_mkt)}.")

# ---------------------------------------------------------------- Part 5 comes first in time: the fit on the first 20 days

R_B, LAM = m.yu_fixed_parameters()
FIT_S = np.array([30.10, 29.90, 30.20, 30.00, 29.80, 30.10, 30.30, 30.00, 29.90, 30.20,
                  30.15, 29.95, 30.05, 30.25, 29.85, 30.00, 30.10, 29.90, 30.05, 30.20])
FIT_CLEAN = np.array([99.20, 99.05, 99.30, 99.15, 98.95, 99.25, 99.40, 99.10, 99.00, 99.30,
                      99.22, 99.08, 99.18, 99.35, 98.98, 99.12, 99.24, 99.02, 99.14, 99.28]) / 100
fit_bonds = [bond_on(i) for i in range(20)]
fit_curves = [CURVE] * 20
fit_z = np.array([m.z_spread(m.full_price(c, b), b, CURVE) for c, b in zip(FIT_CLEAN, fit_bonds)])
show("yu_fixed_parameters", f"R_b = {R_B}, lam = {LAM}.")
L_BAR, rmse = m.fit_barrier_on_bond(fit_bonds, FIT_S, np.full(20, D0), np.full(20, SIGMA_S), fit_z, fit_curves, R_B, LAM)
show("fit_barrier_on_bond", f"20 days, market Z averaging {bp(fit_z.mean())}: L_bar = {L_BAR:.4f}, fit error {bp(rmse)}.")
show("fit_status", f"L_bar {L_BAR:.4f}: {m.fit_status(L_BAR)}.")

# ---------------------------------------------------------------- Part 4. Model value

f0 = m.Firm(float(FIT_S[-1]), D0, SIGMA_S, L_BAR, LAM)
BOND0 = fit_bonds[-1]
show("asset_vol", f"Last fit day, S = {f0.S:.2f}: asset vol {m.asset_vol(f0):.4f}.")
show("barrier_distance", f"d = {m.barrier_distance(f0):.4f}.")
qs = m.survival(np.array([0.0, 1.0, 3.0, 5.0]), f0)
show("survival", f"q(0), q(1), q(3), q(5) = {qs[0]:.5f}, {qs[1]:.4f}, {qs[2]:.4f}, {qs[3]:.4f}.")
show("discounted_default", f"H(5) = {m.discounted_default(5.0, f0, R_5Y):.5f}.")
show("cds_annuity", f"5-year annuity {m.cds_annuity(5.0, f0, R_5Y):.4f}.")
c5 = m.cds_par_spread(5.0, f0, R_B, R_5Y)
show("cds_par_spread", f"5-year model CDS spread {bp(c5)}.")
show("default_leg", f"Default leg to {BOND0.maturity:.3f} years {m.default_leg(BOND0.maturity, f0, CURVE):.5f}.")
show("risky_bond_price", f"Model full price {m.risky_bond_price(BOND0, f0, CURVE, R_B):.5f}. Market {m.full_price(FIT_CLEAN[-1], BOND0):.5f}.")
show("model_z_spread", f"Model Z {bp(m.model_z_spread(BOND0, f0, CURVE, R_B))}. Market Z {bp(fit_z[-1])}.")

# ---------------------------------------------------------------- Part 6. Signal day

D_NEW = m.debt_per_share(LIABILITIES_NEW, SHARES)
S_SIG, VOL_SIG = 27.00, 0.385
firm_sig = m.Firm(S_SIG, D_NEW, VOL_SIG, L_BAR, LAM)
show("passes_barrier_filter", f"New filing D = {D_NEW:.2f}, stock {S_SIG:.2f}: 1 - q(0) = {1 - m.survival(0.0, firm_sig):.4f}, passes = {m.passes_barrier_filter(firm_sig)}.")
z_mod = m.model_z_spread(bond_sig, firm_sig, CURVE, R_B)
raw_signal = m.entry_signal(z_mkt, z_mod, ALPHA)
show("entry_signal", f"Market Z {bp(z_mkt)}, model Z {bp(z_mod)}, ratio {z_mkt / z_mod:.3f} against {1 + ALPHA}: signal {raw_signal:+d}.")
gap = m.log_gap(z_mkt, z_mod)
show("log_gap", f"ln(market / model) = {gap:.3f}. Trigger ln(1.5) = {np.log(1.5):.3f}.")
peer_gap = m.peer_median_gap([0.02, 0.05, 0.08, float("nan"), 0.03, 0.07])
show("peer_median_gap", f"Six peers, one with no price: median {peer_gap:.3f}.")
signal = m.peer_adjusted_signal(gap, peer_gap, ALPHA)
show("peer_adjusted_signal", f"{gap:.3f} - {peer_gap:.3f} = {gap - peer_gap:.3f}: signal {signal:+d}.")
sibling_gap = 0.40
sibling_ok = m.sibling_confirms(gap, sibling_gap)
show("sibling_confirms", f"Sibling gap {sibling_gap:.2f}, same sign and at least half the size: {sibling_ok}.")
cds_mod = m.cds_par_spread(5.0, firm_sig, R_B, R_5Y)
cds_ok = m.cds_confirms(signal, float("nan"), cds_mod, ALPHA)
show("cds_confirms", f"No CDS in this example, so no veto: {cds_ok}. With a 3.5% CDS quote against the model's {bp(cds_mod)}: {m.cds_confirms(signal, 0.035, cds_mod, ALPHA)}.")
dur_sig = m.dollar_duration(bond_sig, z_mkt, CURVE)
cost_ok = m.passes_cost_gate(z_mkt, z_mod, dur_sig, ROUND_TRIP)
show("passes_cost_gate", f"Full convergence pays {(z_mkt - z_mod) * dur_sig * 100:.2f} points against 2 x {ROUND_TRIP * 100:.2f}: {cost_ok}.")
vol_ok = m.implied_vol_confirms(signal, z_mkt, bond_sig, firm_sig, 0.40, CURVE, R_B, ALPHA)
show("implied_vol_confirms", f"Implied vol 0.40: {vol_ok}. Implied vol 0.50 would veto it: {not m.implied_vol_confirms(signal, z_mkt, bond_sig, firm_sig, 0.50, CURVE, R_B, ALPHA)}.")
inv = m.implied_vol_bond(z_mkt, bond_sig, firm_sig, CURVE, R_B)
show("implied_vol_bond", f"Status {inv.status}. Credit-implied vol {inv.sigma_s:.4f} against observed {VOL_SIG:.4f}, ratio {inv.sigma_s / VOL_SIG:.3f}. "
     f"Price 1.60 gives {m.implied_vol_bond(m.z_spread(1.60, bond_sig, CURVE), bond_sig, firm_sig, CURVE, R_B).status}. "
     f"Price 0.58 gives {m.implied_vol_bond(m.z_spread(0.58, bond_sig, CURVE), bond_sig, firm_sig, CURVE, R_B).status}.")
show("implied_vol_cds", f"The CDS version, on the model's own {bp(cds_mod)}: {m.implied_vol_cds(cds_mod, 5.0, firm_sig, R_B, R_5Y).sigma_s:.4f}.")
show("vol_status_allows_trade", f"Status {inv.status}: {m.vol_status_allows_trade(inv)}.")
show("vol_entry_signal", f"{inv.sigma_s:.4f} against {VOL_SIG:.4f}, trigger 1 + beta = {1 + BETA}: signal {m.vol_entry_signal(inv.sigma_s, VOL_SIG, BETA):+d}.")
beta_here = m.beta_equivalent_to_alpha(ALPHA, bond_sig, firm_sig, CURVE, R_B)
beta_safe = m.beta_equivalent_to_alpha(ALPHA, bond_sig, replace(firm_sig, S=3 * D_NEW), CURVE, R_B)
beta_risky = m.beta_equivalent_to_alpha(ALPHA, bond_sig, replace(firm_sig, S=0.6 * D_NEW), CURVE, R_B)
show("beta_equivalent_to_alpha", f"alpha = 0.5 equals beta = {beta_safe:.3f} at S/D = 3, {beta_here:.3f} at S/D = {S_SIG / D_NEW:.2f}, {beta_risky:.3f} at S/D = 0.6.")
side = m.decide_entry(signal, True, m.passes_barrier_filter(firm_sig), sibling_ok, cds_ok, cost_ok, vol_ok)
show("decide_entry", f"Every check passes: side {side:+d}, which is long bond, short stock, short Treasury.")

# ---------------------------------------------------------------- Part 7. Build the trade on the next day

ENTRY_DAYS = SIGNAL_DAYS + 1
show("execution_day", f"Signal on trading day 60: trade on day {m.execution_day(60)}, at that day's price.")
S_IN, CLEAN_IN = 27.20, 0.9330
bond_in = bond_on(ENTRY_DAYS)
firm_in = m.Firm(S_IN, D_NEW, VOL_SIG, L_BAR, LAM)
z_in = m.z_spread(m.full_price(CLEAN_IN, bond_in), bond_in, CURVE)
dur_in = m.dollar_duration(bond_in, z_in, CURVE)
show("dollar_duration", f"Stock {S_IN:.2f}, clean {CLEAN_IN:.4f}, Z {bp(z_in)}: duration {dur_in:.3f}.")
a5_in = m.cds_annuity(5.0, firm_in, R_5Y)
face = m.cds_equivalent_face(bond_in, z_in, CURVE, a5_in)
show("cds_equivalent_face", f"Annuity {a5_in:.3f} over duration {dur_in:.3f}: face {face:.4f}.")
delta = m.bond_equity_delta(bond_in, firm_in, CURVE, R_B, "asset_vol")
delta_eq = m.bond_equity_delta(bond_in, firm_in, CURVE, R_B, "equity_vol")
show("bond_equity_delta", f"{delta:.5f} shares per 1 of face holding asset vol. {delta_eq:.5f} holding equity vol, {delta / delta_eq:.1f} times smaller.")
hedge_bond = m.par_hedge_bond(bond_in.maturity, CURVE)
show("par_hedge_bond", f"Treasury with {hedge_bond.maturity:.3f} years left, coupon {hedge_bond.coupon:.4%}, priced at par.")
ratio = m.rate_hedge_face(bond_in, z_in, hedge_bond, CURVE)
show("rate_hedge_face", f"{ratio:.4f} of Treasury face per 1 of bond face.")
pos = m.build_position(side, face, delta, ratio)
show("build_position", f"Long {pos.face:.4f} face. Short {pos.shares:.5f} shares, value {pos.shares * S_IN:.4f}, or {pos.shares * S_IN / pos.face:.1%} of face. Short {pos.hedge_face:.4f} Treasury face.")
show("rate_hedge_is_due", f"Today's hedge is on target: {m.rate_hedge_is_due(pos.hedge_face, pos.hedge_face, 0)}. After 30 days: {m.rate_hedge_is_due(pos.hedge_face, pos.hedge_face, 30)}.")
CARRY = m.Carry(repo=0.042, bond_fee=0.0040, stock_fee=0.0030, cash_rate=0.041, hedge_repo=0.041, dt=DAY)
show("bond_financing_rate", f"Long bond pays {m.bond_financing_rate(1, CARRY.repo, CARRY.bond_fee):.2%}. A short bond would earn {m.bond_financing_rate(-1, CARRY.repo, CARRY.bond_fee):.2%}.")
show("stock_financing_rate", f"Short stock earns {m.stock_financing_rate(1, CARRY.cash_rate, CARRY.stock_fee):.2%}. Long stock would pay {m.stock_financing_rate(-1, CARRY.cash_rate, CARRY.stock_fee):.2%}.")


def hedge_on(days_after_entry: int) -> m.Bond:
    return m.Bond(hedge_bond.coupon, hedge_bond.maturity - days_after_entry * DAY)


marks_in = m.Marks(CLEAN_IN, m.accrued_interest(bond_in), S_IN, m.price_from_z(0.0, hedge_bond, CURVE))

# ---------------------------------------------------------------- Part 9. Costs

show("yu_cds_round_trip", f"Yu's own cost at 100 bp and a 4.3 annuity: {m.yu_cds_round_trip(0.01, 4.3) * 100:.3f} points.")
measured = m.measured_round_trip([93.5], [1e6], [92.5], [1e6])
show("measured_round_trip", f"Buys 93.50, sells 92.50: {measured * 100:.2f} points.")
show("planning_round_trip", f"If it could not be measured, rating BBB at {bp(z_in)}: {m.planning_round_trip('BBB', z_in) * 100:.2f} points. BB: {m.planning_round_trip('BB', z_in) * 100:.2f} points.")
show("stressed_cost", f"Twice the cost: {m.stressed_cost(measured, 2.0) * 100:.2f} points.")
entry_cost = m.trade_cost(pos, marks_in, measured / 2, STOCK_HALF, TSY_HALF)
show("trade_cost", f"Entry cost {entry_cost:.5f}: bond {pos.face * measured / 2:.5f}, stock {pos.shares * S_IN * STOCK_HALF:.5f}, Treasury {pos.hedge_face * TSY_HALF:.5f}.")
value0 = m.opening_account_value(K, entry_cost)
show("opening_account_value", f"Capital {K} less entry cost: {value0:.5f}.")

# ---------------------------------------------------------------- Part 8. One day of P&L

bond_d1 = bond_on(ENTRY_DAYS + 1)
curve_d1 = shifted(CURVE, 0.0003)
marks_d1 = m.Marks(0.9345, m.accrued_interest(bond_d1), 27.05, m.price_from_z(0.0, hedge_on(1), curve_d1))
show("coupons_paid", f"Bond, next day: {m.coupons_paid(bond_in, bond_d1):.4f}. Over the next 45 days: {m.coupons_paid(bond_in, bond_on(ENTRY_DAYS + 45)):.4f}.")
legs = m.daily_pnl(pos, marks_in, marks_d1, CARRY)
show("daily_pnl", "Stock 27.05, clean 93.45, rates up 3 bp. " + ", ".join(f"{k} {v:+.6f}" for k, v in legs.items()) + ".")
value1, ret1 = m.next_account_value(value0, legs["total"])
show("next_account_value", f"Account {value1:.5f}. Day's excess return {ret1:.4%}.")

# ---------------------------------------------------------------- Part 10. Exit, good path and bad path

HOLD = 45
bond_out = bond_on(ENTRY_DAYS + HOLD)
curve_out = shifted(CURVE, -0.0010)
S_OUT, CLEAN_OUT, VOL_OUT = 28.60, 0.9920, 0.386
firm_out = m.Firm(S_OUT, D_NEW, VOL_OUT, L_BAR, LAM)
z_out = m.z_spread(m.full_price(CLEAN_OUT, bond_out), bond_out, curve_out)
z_mod_out = m.model_z_spread(bond_out, firm_out, curve_out, R_B)
show("exit_reason", f"{HOLD} days on: stock {S_OUT:.2f}, clean {CLEAN_OUT * 100:.2f}, rates down 10 bp. Market Z {bp(z_out)}, model Z {bp(z_mod_out)}: {m.exit_reason(1, z_out, z_mod_out, HOLD, 180, K)}.")
show("bond_exit_reason", f"The same day with the bond rules: {m.bond_exit_reason(1, z_out, z_mod_out, HOLD, 180, K, bond_out.maturity, 1)}. Had a merger been announced: {m.bond_exit_reason(1, z_out, z_mod_out, HOLD, 180, K, bond_out.maturity, 1, 'merger')}.")
bond_cash = m.coupons_paid(bond_in, bond_out)
hedge_cash = m.coupons_paid(hedge_on(0), hedge_on(HOLD))
marks_out = m.Marks(CLEAN_OUT, m.accrued_interest(bond_out), S_OUT, m.price_from_z(0.0, hedge_on(HOLD), curve_out),
                    bond_coupon=bond_cash, hedge_coupon=hedge_cash)
hold_carry = replace(CARRY, dt=HOLD * DAY)
good = m.daily_pnl(pos, marks_in, marks_out, hold_carry)
exit_cost = m.trade_cost(pos, marks_out, measured / 2, STOCK_HALF, TSY_HALF)
net = good["total"] - entry_cost - exit_cost
show("daily_pnl", f"Good path, whole hold: bond leg {good['bond_price'] + good['bond_financing']:+.5f} (includes coupon {bond_cash:.4f}), stock leg {good['stock_price'] + good['stock_financing']:+.5f}, rate hedge {good['hedge_price'] + good['hedge_financing']:+.5f}, costs {-entry_cost - exit_cost:+.5f}. Net {net:+.5f}, or {net / K:+.2%} on capital.")

S_BAD, CLEAN_BAD = 30.00, 0.8600
marks_bad = m.Marks(CLEAN_BAD, m.accrued_interest(bond_out), S_BAD, m.price_from_z(0.0, hedge_on(HOLD), CURVE),
                    bond_coupon=bond_cash, hedge_coupon=hedge_cash)
bad = m.daily_pnl(pos, marks_in, marks_bad, hold_carry)
bad_net = bad["total"] - entry_cost - m.trade_cost(pos, marks_bad, measured / 2, STOCK_HALF, TSY_HALF)
show("daily_pnl", f"Bad path, same entry: stock up to {S_BAD:.2f}, clean down to {CLEAN_BAD * 100:.2f}. Bond leg {bad['bond_price'] + bad['bond_financing']:+.5f}, stock leg {bad['stock_price'] + bad['stock_financing']:+.5f}. Net {bad_net:+.5f}, or {bad_net / K:+.2%} on capital.")
show("drawdown_from_peak", f"Account path 0.494, 0.498, 0.520, 0.470, 0.544: largest fall {m.drawdown_from_peak([0.494, 0.498, 0.520, 0.470, 0.544]):.1%}.")

S_R, CLEAN_R, DAYS_R = 25.50, 1.0150, 200
bond_r = bond_on(DAYS_R)
firm_r = m.Firm(S_R, D_NEW, VOL_SIG, L_BAR, LAM)
z_r = m.z_spread(m.full_price(CLEAN_R, bond_r), bond_r, CURVE)
z_mod_r = m.model_z_spread(bond_r, firm_r, CURVE, R_B)
side_r = m.entry_signal(z_r, z_mod_r, ALPHA)
show("entry_signal", f"The other direction, a later day: stock {S_R:.2f}, clean {CLEAN_R * 100:.2f}. Market Z {bp(z_r)}, model Z {bp(z_mod_r)}, ratio {z_mod_r / z_r:.3f}: signal {side_r:+d}, which is short bond, long stock, long Treasury.")
hedge_r = m.par_hedge_bond(bond_r.maturity, CURVE)
pos_r = m.build_position(side_r, m.cds_equivalent_face(bond_r, z_r, CURVE, m.cds_annuity(5.0, firm_r, R_5Y)),
                         m.bond_equity_delta(bond_r, firm_r, CURVE, R_B), m.rate_hedge_face(bond_r, z_r, hedge_r, CURVE))
bond_r1 = bond_on(DAYS_R + 1)
marks_r0 = m.Marks(CLEAN_R, m.accrued_interest(bond_r), S_R, m.price_from_z(0.0, hedge_r, CURVE))
marks_r1 = m.Marks(1.0130, m.accrued_interest(bond_r1), 25.35,
                   m.price_from_z(0.0, m.Bond(hedge_r.coupon, hedge_r.maturity - DAY), CURVE), dividend=0.05)
legs_r = m.daily_pnl(pos_r, marks_r0, marks_r1, CARRY)
show("daily_pnl", "The other direction, one day, stock 25.35 with a 0.05 dividend, clean 101.30: " + ", ".join(f"{k} {v:+.6f}" for k, v in legs_r.items()) + ".")

# ---------------------------------------------------------------- Part 11. The whole loop, on a made-up panel

panel = m.synthetic_bond_panel(n_days=90, S=30.0, D=28.0, sigma_s=0.38, coupon=COUPON, years_left=YEARS_LEFT, L_bar=0.8)
gapped = m.inject_gap(panel, 0.8, 30, 0.02, 30, R_B, LAM)
config = m.BacktestConfig(calibration_days=10)
result = m.run_bond_backtest(gapped, config)
t = result.trades[0]
show("run_bond_backtest", f"90 days, flat stock and rates, a 200 bp gap on day 30 that closes in 30 days. Fitted L_bar {result.L_bar:.4f}. "
     f"One trade: side {t.side:+d}, signal day {t.signal_day}, entry day {t.entry_day}, exit day {t.exit_day}, {t.reason}, return {t.hpr:+.2%} on capital.")
slope_rng = np.random.default_rng(3)
stock_moves = slope_rng.standard_normal(250) * 0.6
bond_moves = 0.0055 * stock_moves + slope_rng.standard_normal(250) * 0.002
slope, slope_se = m.empirical_hedge_slope(bond_moves, stock_moves)
show("empirical_hedge_slope", f"250 made-up days built with a true slope 0.0055: slope {slope:.5f}, standard error {slope_se:.5f}, against the model delta {delta:.5f}.")
month_ids = np.arange(90) // 30
monthly = m.monthly_index(result.daily_returns, month_ids)
show("monthly_index", f"Three months from that one trade: {np.round(monthly, 4)}.")
series = np.array([0.012, -0.004, 0.003, 0.0, 0.008, -0.011, 0.006, 0.002, -0.003, 0.009, 0.0, 0.004])
show("annual_sharpe", f"12 made-up months: {m.annual_sharpe(series):.2f}.")
summary = m.trade_summary(result.trades)
show("trade_summary", f"N {summary['N']}, N1 {summary['N1']}, N2 {summary['N2']}, N3 {summary['N3']}, mean {summary['mean']:+.2%}, min {summary['min']:+.2%}, max {summary['max']:+.2%}.")
monthly_out = m.monthly_summary(series)
show("monthly_summary", "The 12 months: " + ", ".join(f"{k} {v:.4f}" if k != "N" else f"N {v}" for k, v in monthly_out.items()) + ".")
many = m.run_bond_backtest(gapped, replace(config, overlapping=True))
groups = m.summaries_by_group(many.trades, [t.side for t in many.trades])
show("summaries_by_group", f"Overlapping book on the same gap, by side: {[(k, v['N'], round(v['mean'], 4)) for k, v in groups.items()]}.")
factors = np.column_stack([np.array([0.02, -0.01, 0.015, 0.0, 0.01, -0.02, 0.012, 0.004, -0.006, 0.018, 0.002, 0.007]),
                           np.array([0.004, 0.002, -0.001, 0.003, -0.002, 0.001, 0.0, 0.002, -0.003, 0.004, 0.001, -0.001])])
fit = m.factor_regression(series, factors)
show("factor_regression", f"The 12 months on two made-up factors: intercept {fit['intercept']:.4f} ({fit['intercept_se']:.4f}), betas {np.round(fit['betas'], 3)}, R2 {fit['r2']:.2f}.")

# ---------------------------------------------------------------- Part 12. Checks

c1 = m.check_table_c1()
show("check_table_c1", f"{c1['cells_matching']} of 156 cells match after rounding. Largest gap {c1['largest_gap_bp']:.3f} bp. Without the Act/360 scaling {c1['largest_gap_unscaled_bp']:.2f} bp.")
wc = m.check_worldcom(0.05)
firm_wc = m.Firm(13.0, 9.0, 0.40 * 17.5 / 13, 0.5, 0.3)
show("cds_equity_delta", f"CreditGrades WorldCom inputs: {m.cds_equity_delta(5.0, firm_wc, 0.5, 0.05):.5f} shares per 1 of notional.")
show("check_worldcom", f"Published 249 and 224 bp, ours {wc['score_13_bp']:.1f} and {wc['score_14_bp']:.1f}. Published hedge 7.7:1, ours {wc['hedge_ratio']:.1f}:1. Holding equity vol {wc['equity_vol_hedge_ratio']:.1f}:1.")
ids = m.check_identities(f0, R_B, R_5Y, 5.0)
show("check_identities", f"Annuity gap {ids['annuity_gap']:.1e}. Price identity gap {ids['price_identity_gap']:.1e}. Par delta gap {ids['par_delta_gap']:.1e}. Par Z minus CDS {ids['par_z_minus_cds_bp']:+.3f} bp.")

n_cds = 30
firm_cds = m.Firm(30.0, 28.0, 0.38, 0.62)
c_flat = m.cds_par_spread(5.0, firm_cds, R_B, R_5Y)
cds_path = np.array([c_flat] * 15 + [c_flat * 2.0] * 8 + [c_flat * 0.99] * 7)
one = np.ones(n_cds)
cds_panel = m.CdsPanel(c=cds_path, S=one * 30.0, D=one * 28.0, sigma_s=one * 0.38, r=one * R_5Y, dividend=one * 0.0,
                       day_fraction=one * DAY, calendar_day=np.arange(n_cds, dtype=float))
yu_config = m.BacktestConfig(calibration_days=10, overlapping=False, lag=0, peer_adjust=False)
fit_c, fit_c_err = m.fit_barrier_on_cds(cds_path[:10], one[:10] * 30.0, one[:10] * 28.0, one[:10] * 0.38, one[:10] * R_5Y, 5.0, R_B, LAM)
show("fit_barrier_on_cds", f"Ten days of made-up CDS at {bp(c_flat)}: L_bar {fit_c:.4f}, error {bp(fit_c_err)}.")
show("cds_contract_value", f"Long protection entered at 100 bp, now 150 bp: {m.cds_contract_value(0.015, 0.01, 5.0, firm_cds, R_5Y):+.5f}.")
cds_result = m.run_cds_backtest(cds_panel, yu_config)
ct = cds_result.trades[0]
show("run_cds_backtest", f"Made-up CDS doubles on day 15, then falls under the model on day 23: side {ct.side:+d}, exit day {ct.exit_day}, {ct.reason}, return {ct.hpr:+.2%} on capital.")
replication = m.check_cds_replication(m.trade_summary(cds_result.trades), 0.5, 180, 0.5)
show("check_cds_replication", f"Yours minus Yu's Altria row. Meaningless on made-up data, and shown only for the form: N {replication['N']:+d}, mean {replication['mean']:+.2f}.")
show("synthetic_bond_panel", f"{len(panel.S)} made-up days, flat stock and rates, clean {panel.clean[0]:.4f} on day 0.")
no_gap = m.panel_with_no_gap(panel, 0.8, R_B, LAM)
show("panel_with_no_gap", f"Every clean price set to its model price: largest change {np.abs(no_gap.clean - panel.clean).max():.1e}.")
show("check_no_signal_without_gap", f"Trades with no gap: {m.check_no_signal_without_gap(no_gap, config)}.")
show("inject_gap", f"200 bp added on day 30: clean falls from {gapped.clean[29]:.4f} to {gapped.clean[30]:.4f}.")
show("check_legs_add_up", f"Largest gap between the legs and the change in value: {m.check_legs_add_up(result, config.capital):.1e}.")
show("check_known_gap_profit", f"Largest gap against the end-price sum: {m.check_known_gap_profit(gapped, result):.1e}.")
cut = m.truncate_panel(gapped, 45)
show("truncate_panel", f"Panel cut to {len(cut.S)} days.")
show("check_no_lookahead", f"Largest change in a past return when later data is removed: {m.check_no_lookahead(gapped, config, 45):.1e}.")
lags = m.lag_sensitivity(gapped, config, (0, 1, 2, 5))
show("lag_sensitivity", "Mean return by execution lag: " + ", ".join(f"lag {k}: {v:+.2%}" for k, v in lags.items()) + ". This gap is real by design, so the profit does not vanish at lag 1.")
other = replace(panel, S=panel.S * 1.5)
placebo = m.run_bond_backtest(m.placebo_panel(gapped, other), config)
show("placebo_panel", f"Same bond against another stock: fitted L_bar {placebo.L_bar:.4f}, trades {len(placebo.trades)}. Here the fit moves the barrier, and the injected gap still shows.")
totals = m.attribute_pnl(result.trades)
show("attribute_pnl", ", ".join(f"{k} {v:+.5f}" for k, v in totals.items()) + ".")
shape = m.shape_against_yu({"N": 100, "N1": 2, "N3": 50, "min": -0.5, "max": 0.5}, {"N": 100, "N1": 15, "N3": 30, "min": -0.6, "max": 0.9},
                           {"N": 100, "N1": 15, "N3": 30, "min": -0.6, "max": 0.9}, {"N": 40, "N1": 2, "N3": 8, "min": -0.2, "max": 0.7})
show("shape_against_yu", f"Four made-up summaries: {shape}.")
small = m.inject_gap(panel, 0.8, 30, 0.012, 30, R_B, LAM)
be = m.break_even_cost(small, replace(config, peer_adjust=False, alpha=0.05), (0.0, 1.0, 10.0, 40.0))
show("break_even_cost", f"A 120 bp gap: mean return {[round(x, 4) for x in be['mean_returns']]} at cost multiples {be['multiples']}. Break-even at {be['break_even_multiple']:.1f} times the cost.")

# ---------------------------------------------------------------- Sensitivities quoted in the steps

print("SENSITIVITIES")
base_delta = m.bond_equity_delta(BOND0, f0, CURVE, R_B)
base_z = m.model_z_spread(BOND0, f0, CURVE, R_B)
print(f"Base: L_bar {L_BAR:.4f}, model Z {bp(base_z)}, delta {base_delta:.5f}.")


def refit(z, rec=R_B, lam=LAM):
    fit_l, _ = m.fit_barrier_on_bond(fit_bonds, FIT_S, np.full(20, D0), np.full(20, SIGMA_S), z, fit_curves, rec, lam)
    d = m.bond_equity_delta(BOND0, replace(f0, L_bar=fit_l, lam=lam), CURVE, rec)
    return fit_l, d


for bump in (0.0040, -0.0040):
    fit_l, d = refit(fit_z + bump)
    print(f"Fit to Z {bump * 1e4:+.0f} bp: L_bar {fit_l:.4f}, delta {d:.5f} ({d / base_delta - 1:+.0%}).")
for rec in (0.4, 0.3):
    fit_l, d = refit(fit_z, rec=rec)
    print(f"R_b = {rec}: L_bar {fit_l:.4f}, delta {d:.5f} ({d / base_delta - 1:+.0%}).")
for lam in (0.2, 0.4):
    fit_l, d = refit(fit_z, lam=lam)
    print(f"lam = {lam}: L_bar {fit_l:.4f}, delta {d:.5f} ({d / base_delta - 1:+.0%}).")
up = shifted(CURVE, 0.003)
print(f"Curve up 30 bp, prices and L_bar unchanged: market Z {bp(fit_z[-1])} -> {bp(m.z_spread(m.full_price(FIT_CLEAN[-1], BOND0), BOND0, up))}. Model Z {bp(base_z)} -> {bp(m.model_z_spread(BOND0, f0, up, R_B))}.")
fall = 0.9 * f0.S
print(f"Stock down 10%, equity vol fixed: model Z {m.model_z_spread(BOND0, replace(f0, S=fall), CURVE, R_B) * 1e4 - base_z * 1e4:+.1f} bp. Asset vol fixed: {m.model_z_spread(BOND0, replace(f0, S=fall, S_ref=f0.S), CURVE, R_B) * 1e4 - base_z * 1e4:+.1f} bp.")
print(f"Equity vol 38% -> 60%, same stock: model Z {bp(m.model_z_spread(BOND0, replace(f0, sigma_s=0.60), CURVE, R_B))}.")
for cpn in (0.02, 0.055, 0.09):
    b = m.Bond(cpn, BOND0.maturity)
    print(f"Coupon {cpn:.1%}: model full price {m.risky_bond_price(b, f0, CURVE, R_B) * 100:.2f}, model Z {bp(m.model_z_spread(b, f0, CURVE, R_B))}.")
print(f"5-year CDS on the same firm: {bp(c5)}.")
