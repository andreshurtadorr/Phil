#!/usr/bin/env python3
"""Paper broker: propose, approve and place simulated positions; track the bankroll.

PROTECTED CORE — the trading agent must not edit files under core/.
The agent CALLS this to bet; it cannot bypass the caps in config/protected.json
because this is the only writer of journal/ledger.jsonl.

Two roles since 2026-09-26 (operator):
  * the OPERATIONS agent (CYCLE.md, models.operations) may only PROPOSE a bet:
    `propose` appends a row to journal/bet-queue.jsonl and places nothing;
  * the EXECUTIVE session (EXECUTE.md, models.executive) has the final say:
    `place --proposal <id>` fills a proposal, `reject --proposal <id>` vetoes
    it. Both require PHIL_ROLE=executor in the environment, which loop.sh sets
    only for the executive session. A `place` without that role is refused.

journal/bet-queue.jsonl is append-only; the last row per proposal id wins
(statuses: proposed -> placed | rejected | expired | failed). It is the
executive's scorecard: core/score.py grades approved rows on realized P&L
and vetoed rows on the counterfactual at the proposal-time ask.

Fills are honest: a paper BUY fills at the live CLOB best ask for the chosen
outcome token (crossing the spread, like a real taker order). If the book is
empty or the fill violates protected caps, the bet is rejected.

Month-to-month profitability guard: when realized P&L for the current UTC
month is at or below -monthly_loss_stop_usd (config/protected.json), `place`
refuses every new position until the month rolls over.

Usage:
  propose: python3 core/ledger.py propose --market-id 123 --outcome Yes \
             --est-prob 0.62 --stake 5 --category earnings --edge-class other \
             --rationale "consensus beat rate 78%, whisper above street" \
             [--forecast-id <id>] [--strategy-rev <rev>]
  queue:   python3 core/ledger.py queue [--json]      (expires stale proposals)
  place:   PHIL_ROLE=executor python3 core/ledger.py place --proposal <id> \
             [--note "<why approved>"]
  reject:  PHIL_ROLE=executor python3 core/ledger.py reject --proposal <id> \
             --reason "<why vetoed>"
  status:  python3 core/ledger.py status
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pmapi  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal" / "ledger.jsonl"
QUEUE = ROOT / "journal" / "bet-queue.jsonl"
PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text())

EDGE_CLASSES = ["info-race", "cross-market", "book-devig", "other"]
QUEUE_STATUSES = ("proposed", "placed", "rejected", "expired", "failed")
# A proposal is priced at proposal time; the executive runs right after the
# cycle. Older than this the ask is stale and the proposal expires unfilled.
PROPOSAL_TTL_MIN = 120


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def executor_role():
    return os.environ.get("PHIL_ROLE") == "executor"


def require_executor(verb):
    if not executor_role():
        sys.exit(f"REFUSED: `{verb}` is the executive session's act "
                 f"(PHIL_ROLE=executor, set by loop.sh for EXECUTE.md only). "
                 f"The operations agent proposes: python3 core/ledger.py propose ...")


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_ledger():
    return read_jsonl(LEDGER)


def read_queue():
    return read_jsonl(QUEUE)


def queue_latest(rows=None):
    """Last row per proposal id, in first-seen order."""
    latest = {}
    for r in rows if rows is not None else read_queue():
        latest[r["id"]] = r
    return latest


def append_queue(row):
    with QUEUE.open("a") as f:
        f.write(json.dumps(row) + "\n")


def bankroll(entries):
    cash = PROTECTED["sim_bankroll_usd"]
    for e in entries:
        if e["status"] in ("open", "won", "lost", "void"):
            cash -= e["stake_usd"]
        if e["status"] == "won":
            cash += e["shares"]  # $1 per share
        elif e["status"] == "void":
            cash += e["stake_usd"]
    return cash


def month_realized_pnl(entries, now=None):
    """Realized paper P&L of positions settled in the current UTC month."""
    month = iso(now or now_utc())[:7]
    return sum(e.get("pnl_usd", 0.0) for e in entries
               if e["status"] in ("won", "lost")
               and (e.get("settled_ts") or "")[:7] == month)


def monthly_stop_state(entries, now=None):
    stop = PROTECTED.get("monthly_loss_stop_usd")
    mtd = round(month_realized_pnl(entries, now), 2)
    tripped = isinstance(stop, (int, float)) and stop > 0 and mtd <= -stop
    return {"month": iso(now or now_utc())[:7], "mtd_realized_pnl_usd": mtd,
            "monthly_loss_stop_usd": stop, "tripped": tripped}


def expire_stale(latest, now):
    """Mark proposals older than PROPOSAL_TTL_MIN as expired. Returns count."""
    n = 0
    for r in list(latest.values()):
        if r["status"] != "proposed":
            continue
        try:
            age_min = (now - parse_iso(r["ts"])).total_seconds() / 60
        except (KeyError, ValueError):
            continue
        if age_min > PROPOSAL_TTL_MIN:
            row = {**r, "status": "expired", "verdict_ts": iso(now),
                   "verdict_reason": f"unfilled after {PROPOSAL_TTL_MIN} min; "
                                     f"the proposal-time ask is stale"}
            append_queue(row)
            latest[r["id"]] = row
            n += 1
    return n


def cmd_status(entries):
    open_pos = [e for e in entries if e["status"] == "open"]
    settled = [e for e in entries if e["status"] in ("won", "lost")]
    pnl = sum((e["shares"] - e["stake_usd"]) if e["status"] == "won" else -e["stake_usd"]
              for e in settled)
    latest = queue_latest()
    print(json.dumps({
        "cash": round(bankroll(entries), 2),
        "open_positions": len(open_pos),
        "settled": len(settled),
        "wins": sum(1 for e in settled if e["status"] == "won"),
        "realized_pnl": round(pnl, 2),
        "month": monthly_stop_state(entries),
        "queue": {s: sum(1 for r in latest.values() if r["status"] == s)
                  for s in QUEUE_STATUSES},
        "open": [{"id": e["id"], "q": e["question"][:70], "outcome": e["outcome"],
                  "entry": e["entry_price"], "est": e["est_prob"], "ends": e["end_date"]}
                 for e in open_pos],
    }, indent=2))


def precheck(args, entries, latest):
    """Cap checks that need no network. Shared by propose and place."""
    open_pos = [e for e in entries if e["status"] == "open"]
    if len(open_pos) >= PROTECTED["max_open_positions"]:
        sys.exit(f"REJECTED: max_open_positions ({PROTECTED['max_open_positions']}) reached")
    if args.stake > PROTECTED["max_stake_usd"]:
        sys.exit(f"REJECTED: stake {args.stake} > max_stake_usd {PROTECTED['max_stake_usd']}")
    if args.stake > bankroll(entries):
        sys.exit("REJECTED: insufficient sim cash")
    if not 0.0 < args.est_prob < 1.0:
        sys.exit("REJECTED: est-prob must be in (0,1)")
    if any(e["market_id"] == args.market_id and e["outcome"] == args.outcome
           for e in open_pos):
        sys.exit("REJECTED: already have an open position on this market+outcome")
    return open_pos


def fetch_book(args):
    m = pmapi.gamma_market(args.market_id)
    if m.get("closed"):
        sys.exit("REJECTED: market is closed")
    tokens = pmapi.market_tokens(m)
    if args.outcome not in tokens:
        sys.exit(f"REJECTED: outcome {args.outcome!r} not in {list(tokens)}")
    bid, ask = pmapi.best_prices(tokens[args.outcome])
    if ask is None:
        sys.exit("REJECTED: no asks in the book (cannot fill)")
    if not PROTECTED["min_entry_price"] <= ask <= PROTECTED["max_entry_price"]:
        sys.exit(f"REJECTED: fill price {ask} outside protected bounds")
    return m, tokens, bid, ask


def cmd_propose(args, entries):
    latest = queue_latest()
    precheck(args, entries, latest)
    if any(r["status"] == "proposed" and r["market_id"] == args.market_id
           and r["outcome"] == args.outcome for r in latest.values()):
        sys.exit("REJECTED: this market+outcome already has a pending proposal")
    m, tokens, bid, ask = fetch_book(args)
    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": iso(now_utc()),
        "status": "proposed",
        "proposed_by": os.environ.get("PHIL_MODEL") or "operations",
        "market_id": args.market_id,
        "question": m.get("question"),
        "slug": m.get("slug"),
        "end_date": m.get("endDate"),
        "outcome": args.outcome,
        "token_id": tokens[args.outcome],
        "ask_at_proposal": ask,
        "bid_at_proposal": bid,
        "est_prob": args.est_prob,
        "edge_at_proposal": round(args.est_prob - ask, 4),
        "stake_usd": args.stake,
        "category": args.category,
        "edge_class": args.edge_class,
        "rationale": args.rationale,
        "forecast_id": args.forecast_id,
        "strategy_rev": args.strategy_rev,
    }
    append_queue(row)
    print(json.dumps({"proposed": row["id"], "ask": ask, "bid": bid,
                      "edge_at_proposal": row["edge_at_proposal"],
                      "question": row["question"],
                      "next": "the executive session decides (EXECUTE.md)"}, indent=2))


def cmd_queue(args, entries):
    now = now_utc()
    latest = queue_latest()
    expired = expire_stale(latest, now)
    pending = [r for r in latest.values() if r["status"] == "proposed"]
    out = {"pending": pending, "expired_now": expired,
           "month": monthly_stop_state(entries, now),
           "counts": {s: sum(1 for r in latest.values() if r["status"] == s)
                      for s in QUEUE_STATUSES}}
    if args.json:
        print(json.dumps(out, indent=2))
        return
    mo = out["month"]
    print(f"pending={len(pending)} expired_now={expired} "
          f"month={mo['month']} mtd_pnl=${mo['mtd_realized_pnl_usd']:+.2f} "
          f"stop=-${mo['monthly_loss_stop_usd']} "
          f"{'TRIPPED' if mo['tripped'] else 'ok'}")
    for r in pending:
        print(f"\n{r['id']}  {r['ts']}  [{r['category']} / {r['edge_class']}]  "
              f"stake ${r['stake_usd']:.2f}")
        print(f"  {r['question']}")
        print(f"  outcome={r['outcome']} est={r['est_prob']} ask={r['ask_at_proposal']} "
              f"bid={r['bid_at_proposal']} edge={r['edge_at_proposal']:+.4f} "
              f"ends={r.get('end_date')}")
        print(f"  rationale: {r['rationale']}")
        if r.get("forecast_id"):
            print(f"  forecast_id: {r['forecast_id']}")


def cmd_reject(args, entries):
    require_executor("reject")
    latest = queue_latest()
    r = latest.get(args.proposal)
    if not r:
        sys.exit(f"REJECTED: no proposal {args.proposal}")
    if r["status"] != "proposed":
        sys.exit(f"REJECTED: proposal {args.proposal} is already {r['status']}")
    row = {**r, "status": "rejected", "verdict_ts": iso(now_utc()),
           "verdict_by": os.environ.get("PHIL_MODEL") or "executive",
           "verdict_reason": args.reason}
    append_queue(row)
    print(json.dumps({"rejected": r["id"], "question": r["question"],
                      "reason": args.reason}, indent=2))


def cmd_place(args, entries):
    require_executor("place")
    now = now_utc()
    latest = queue_latest()
    expire_stale(latest, now)
    proposal = None
    if args.proposal:
        proposal = latest.get(args.proposal)
        if not proposal:
            sys.exit(f"REJECTED: no proposal {args.proposal}")
        if proposal["status"] != "proposed":
            sys.exit(f"REJECTED: proposal {args.proposal} is {proposal['status']}, "
                     f"not pending")
        for field in ("market_id", "outcome", "est_prob", "category", "edge_class",
                      "rationale", "strategy_rev"):
            setattr(args, field, proposal[field])
        args.stake = proposal["stake_usd"]
    else:
        missing = [f for f in ("market_id", "outcome", "est_prob", "stake",
                               "category", "edge_class", "rationale")
                   if getattr(args, f) is None]
        if missing:
            sys.exit(f"REJECTED: without --proposal, place needs "
                     f"--{' --'.join(m.replace('_', '-') for m in missing)}")

    def refuse(msg):
        if proposal:
            append_queue({**proposal, "status": "failed", "verdict_ts": iso(now),
                          "verdict_by": os.environ.get("PHIL_MODEL") or "executive",
                          "verdict_reason": f"approved but not filled: {msg}"})
        sys.exit(msg)

    mo = monthly_stop_state(entries, now)
    if mo["tripped"]:
        refuse(f"REJECTED: month-to-date realized P&L ${mo['mtd_realized_pnl_usd']:+.2f} "
               f"is at or below the monthly loss stop -${mo['monthly_loss_stop_usd']} "
               f"(config/protected.json) - no new positions until {mo['month']} ends")

    try:
        precheck(args, entries, latest)
        m, tokens, bid, ask = fetch_book(args)
    except SystemExit as e:
        refuse(str(e))

    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": iso(now),
        "market_id": args.market_id,
        "question": m.get("question"),
        "slug": m.get("slug"),
        "end_date": m.get("endDate"),
        "outcome": args.outcome,
        "token_id": tokens[args.outcome],
        "entry_price": ask,
        "best_bid_at_entry": bid,
        "market_prob_at_entry": ask,
        "est_prob": args.est_prob,
        "edge": round(args.est_prob - ask, 4),
        "stake_usd": args.stake,
        "shares": round(args.stake / ask, 4),
        "category": args.category,
        "edge_class": args.edge_class,
        "rationale": args.rationale,
        "strategy_rev": args.strategy_rev,
        "status": "open",
    }
    if proposal:
        entry["proposal_id"] = proposal["id"]
        entry["approved_note"] = args.note or ""
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    if proposal:
        append_queue({**proposal, "status": "placed", "verdict_ts": iso(now),
                      "verdict_by": os.environ.get("PHIL_MODEL") or "executive",
                      "verdict_reason": args.note or "", "ledger_id": entry["id"],
                      "entry_price": ask})
    print(json.dumps({"placed": entry["id"], "filled_at": ask, "edge": entry["edge"],
                      "shares": entry["shares"], "question": entry["question"],
                      "proposal": proposal["id"] if proposal else None}, indent=2))


def add_bet_args(p, required):
    p.add_argument("--market-id", required=required)
    p.add_argument("--outcome", required=required, help="exact outcome name, e.g. Yes")
    p.add_argument("--est-prob", type=float, required=required,
                   help="agent's probability that this outcome wins")
    p.add_argument("--stake", type=float, required=required)
    p.add_argument("--category", required=required,
                   help="agent-assigned category, e.g. earnings/soccer/esports/news")
    p.add_argument("--edge-class", required=required, choices=EDGE_CLASSES,
                   help="playbook edge class this bet claims (scored separately)")
    p.add_argument("--rationale", required=required, help="one-line reason (for the retro)")
    p.add_argument("--strategy-rev", default="", help="git rev of strategy/ used")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("propose", help="operations agent: queue a bet for the executive")
    add_bet_args(pr, required=True)
    pr.add_argument("--forecast-id", default=None,
                    help="id of the step-5b forecast recorded for this candidate")

    q = sub.add_parser("queue", help="list pending proposals (expires stale ones)")
    q.add_argument("--json", action="store_true")

    p = sub.add_parser("place", help="executive: fill a proposal (PHIL_ROLE=executor)")
    p.add_argument("--proposal", default=None, help="bet-queue proposal id to fill")
    p.add_argument("--note", default="", help="one line: why approved")
    add_bet_args(p, required=False)

    rj = sub.add_parser("reject", help="executive: veto a proposal (PHIL_ROLE=executor)")
    rj.add_argument("--proposal", required=True)
    rj.add_argument("--reason", required=True, help="one line: why vetoed")

    sub.add_parser("status")
    args = ap.parse_args()

    entries = read_ledger()
    if args.cmd == "status":
        cmd_status(entries)
    elif args.cmd == "propose":
        cmd_propose(args, entries)
    elif args.cmd == "queue":
        cmd_queue(args, entries)
    elif args.cmd == "reject":
        cmd_reject(args, entries)
    else:
        cmd_place(args, entries)


if __name__ == "__main__":
    main()
