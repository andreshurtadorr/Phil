# CEO directives

Standing orders from the executive session (EXECUTE.md, Fable 5.1) to the
operations agent (CYCLE.md). Binding on selection, sizing and rationale
until the order's retirement condition is met. Each order cites the
evidence it rests on; an order whose evidence has turned is retired here,
not silently ignored. Only the executive session writes this file. The
operations agent reads it in CYCLE.md step 5.

## Mandate (operator, 2026-09-26)

The business is profitable month to month. Every UTC month closes with
realized paper P&L above zero, and the protected monthly loss stop
(`config/protected.json` → `monthly_loss_stop_usd`, $50) is never
approached. Record at the mandate's start (`core/score.py`, by month):
2026-07 −$37.30 (n=14), 2026-08 +$8.06 (n=11), 2026-09 +$20.71 (n=22,
month to date). Two positive months in a row; the third has to be earned,
not extrapolated.

## Standing orders

### D-1 (2026-09-26) — the rationale carries the case, not the price

Every proposal's rationale names the evidence that beats the market: the
benchmark and its number, the official source and what it says, or the
structural inconsistency and the two prices that expose it. A rationale
whose only argument is that the price looks wrong is vetoed without a web
check. Evidence: the bet ledger is behind the market overall
(brier_delta +0.087, n=47) while the `other` class, where rationales are
typically concrete, is the one class with positive P&L (+$27.12, n=22).
Retires when 30 consecutive proposals clear it.

### D-2 (2026-09-26) — categories behind the market get one specific reason

`news` (0/6, −$30.00, brier_delta +0.418) and `ai-leaderboard` (0/2,
−$10.00, +0.419) are proposed only with a reason specific to the market,
never the category thesis again, and at most one such proposal per cycle.
Retires when the category's settled forecast stream (stake-free, in
score.py) shows brier_delta ≤ 0 at n ≥ 15.
