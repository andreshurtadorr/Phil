# Phil (self-improving trader)

A self-improving trading agent for short-term Polymarket markets. The
agent (Claude Code, headless) runs `CYCLE.md` repeatedly: settle → score →
retrospective → edit its own strategy → research → place simulated bets.

## Roles and models (operator, 2026-09-26)

Three sessions, three models, set in `config/protected.json` → `models` and
pinned by `loop.sh`:

- **Executive** (`EXECUTE.md`, Fable 5.1): the CEO. Final say on every
  placement, paper and real. The only session with `PHIL_ROLE=executor`,
  which `core/ledger.py place` and `core/real.py place` require. Steers the
  operations agent through `journal/ceo-directives.md`. Graded by
  `core/score.py` (exec gate).
- **Operations** (`CYCLE.md` FULL/TRIGGERED ticks, Opus 5.5): research,
  forecasts, strategy edits, and bet *proposals* (`core/ledger.py propose`
  → `journal/bet-queue.jsonl`). Cannot place.
- **Grunt** (Sonnet 4.6): LIGHT ticks and every Task subagent (screening
  batches), pinned with `CLAUDE_CODE_SUBAGENT_MODEL` + `_FORCE`.

The mandate is profitability month to month: `core/score.py` reports P&L
by month, and `monthly_loss_stop_usd` (protected) stops new positions for
the rest of any month whose realized P&L reaches the floor.

## Layout

- `core/` + `config/protected.json` — PROTECTED simulation engine (honest
  CLOB-ask fills, bankroll caps, official resolutions). The agent must never
  edit these; `loop.sh` reverts any such change. Also operator-owned: the
  top-level docs, `LICENSE`, and `.github/` (CI).
- CI (`.github/workflows/ci.yml`) runs on every push: `core/validate.py`
  integrity tripwires (real caps inside their ceilings, the models block and
  monthly loss stop present, JSONs parse, ledger and bet-queue rows respect
  the protected caps, Python compiles), a bug-class-only ruff
  pass, and a boundary guard — commits not prefixed `operator:` are agent
  commits and must not touch operator-owned paths. Human commits to protected
  files MUST use the `operator:` message prefix or CI fails the push.
- `strategy/` — the agent's own playbook, risk policy, and tools. This is what
  self-improves. Its git history IS the experiment's product.
- `journal/` — ledger (JSONL, written only by core), retros, cycle log.
- `CYCLE.md` — the per-cycle procedure the operations agent follows.
- `EXECUTE.md` — the executive pass that decides the cycle's proposals.
- `journal/bet-queue.jsonl` — proposals and verdicts (append-only, last row
  per id wins; written only by `core/ledger.py`).
- `journal/ceo-directives.md` — the executive's standing orders, binding on
  the operations agent.

## Purpose

Paper is the 24/7 learning engine (cloud loop, hourly): find WHERE fast
research beats the market (calibration per category and edge class,
`brier_delta` in `core/score.py`). Real execution runs only on the
operator's machine via `./loop.sh --real`: qualifying paper bets (edge
classes in `config/protected.json` → `real.allowed_edge_classes`) get a $1
real twin on Polymarket through Pearl Connect.

Whenever the local Pearl Connect signer is up (paper or real cycles on the
operator's machine), the agent may also buy second-opinion predictions from
the Olas mech marketplace (~$0.01 USDC each, paid by the service safe) —
see CYCLE.md step 5a. Cloud cycles have no signer and skip this.

## Real execution (operator machine only)

- Env: `PEARL_CONNECT_STORE` = Pearl Connect workspace dir (contains
  `.mcp.json`); optional `CONNECT_POLYMARKET_VENV` (default
  `~/.cache/connect-polymarket/venv`).
- `core/real.py` (protected) is the only code that touches funds for
  trading (mech second opinions per CYCLE.md 5a are the one non-trading
  spend) — it wraps
  the connect-polymarket skill scripts Pearl Connect provisions, enforces
  the `real` caps block, and is the sole writer of
  `journal/real-ledger.jsonl` (paper `ledger.jsonl` discipline mirrored).
- `real_trading_enabled: true` + the `real` caps block are validated by CI
  (`core/validate.py` hard ceilings). Editing either is an operator act.
- REAL.md is appended to the cycle prompt only in real mode; loop.sh
  downgrades to paper with a warning if the signer isn't ready.
