# Real-execution addendum

This section is appended to a session prompt ONLY when the operator runs
`./loop.sh --real` on a machine with a healthy Pearl Connect signer. Real
money is involved. It is appended to BOTH the operations cycle (CYCLE.md)
and the executive pass (EXECUTE.md); each takes only its own steps below.
Everything in the base procedure still applies; these steps are additive.

## Extra steps — operations cycle (CYCLE.md)

- During **Settle** (step 1), also run: `python3 core/real.py settle`.
  It sweeps filled positions to the Safe, redeems resolved ones, and
  reconciles any ambiguous submissions. Read its output; report anomalies
  (reverted redemptions, unresolved pending orders) in the cycle log.
- You do NOT place real twins. `core/real.py place` refuses the operations
  session (it needs `PHIL_ROLE=executor`). Proposals whose `--edge-class` is
  in `config/protected.json` → `real.allowed_edge_classes` are the ones the
  executive may mirror, so say in the rationale what makes the class claim
  hold.
- In the **Log** line (step 7), append: ` | real: settled S`.

## Extra steps — executive pass (EXECUTE.md)

- After **each proposal you approve** (`ledger.py place`): if its
  `edge_class` is in `real.allowed_edge_classes`, mirror it:
  `python3 core/real.py place --paper-id <paper ledger id>`
  The stake comes from `real.max_stake_usd` in config; never pass `--usd`
  yourself. Real caps are enforced by core/real.py — a refusal (cap hit,
  market already held, unreconciled order) is policy working, not an error
  to fix. A real twin is a second, smaller yes on the same evidence: if you
  would not stake the real dollar, you should not have approved the paper
  five either.
- In the **Log** line, append: ` | real: placed R`.

## Hard rules for real mode

- core/real.py is the ONLY way you touch real funds for trading. Never
  call Pearl Connect signing tools or the skill scripts directly — with
  one exception: the `mcp__pearl-connect__mech_*` tools, which buy
  predictions per CYCLE.md step 5a and can never place orders or move
  funds anywhere but the mech payment.
- Never blind-retry a failed or timed-out real order — buys are not
  idempotent. core/real.py blocks new bets while any order is
  unreconciled; respect that.
- A guardrail refusal from the signer names the rule it violated — relay
  it verbatim in the cycle log and move on; never work around it.
- A 403/geoblock on order placement is venue policy: report it and stop
  real execution for the cycle. Do not attempt to circumvent.
- Never write tokens, config contents, or signer URLs to the journal —
  the journal is public. Wallet addresses are fine.
