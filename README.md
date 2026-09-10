# AgentCourt v1.0

**Autonomous AI arbitration for agent-to-agent contracts, on GenLayer.**

Two parties agree that Party A will deliver something against a fixed,
weighted set of named conditions for a fixed payment. If Party B
disputes the delivery, AgentCourt — not a human moderator — runs the
dispute through a bounded, appealable, multi-validator arbitration
pipeline and produces an auditable, **partial-verdict-capable**
settlement split, with a documented terminal state for every path.

This is the sibling project to **ScoreSettle** (sports-score
settlement), generalized from "who won the match" to "did the agent
actually deliver what it promised."

## What's here

```
contract.py          The GenLayer intelligent contract
index.html            Reference frontend (genlayer-js)
tests/                Offline unit tests (no live GenLayer node needed)
```

## Scope of this v1

Per the design discussion, this is the deliberately-bounded MVP, not
the full 15-feature vision:

- ✅ Two-party binding (real signed addresses, never free text)
- ✅ Immutable contract snapshot (task + weighted conditions frozen at creation)
- ✅ Locked evidence set (locked from data both parties already committed — no "first caller poisons it" risk)
- ✅ Structured claims (plain text, always treated as untrusted data)
- ✅ Independent multi-validator adjudication (`gl.eq_principle.prompt_comparative`)
- ✅ Partial verdicts as the default settlement math, not a special case
- ✅ One bounded, text-only appeal (no new evidence)
- ✅ Deterministic timeout on every non-terminal state — no stuck agreements
- ⏳ Not in v1: multi-round appeal ladders, a real bonded appeal economy,
  per-condition (rather than whole-verdict) appeals, actual on-chain
  fund custody. See the class docstring in `contract.py` for the full
  "v1 scope / known limitations" section — every simplification here
  is written down, not hidden.

## Try it offline (no GenLayer node needed)

```bash
cd agentcourt-dapp
python3 -m unittest discover -s tests -p "test_*.py" -t .
```

This exercises every deterministic code path (party binding, timing
windows, the settlement math, evidence locking, appeal eligibility)
against an offline stub of the `genlayer` SDK, with `gl.nondet.web.render`
and `gl.nondet.exec_prompt` mocked per test case — the same pattern
ScoreSettle's test suite uses.

## Try it live on GenLayer Studio

1. Open [GenLayer Studio](https://studio.genlayer.com) and deploy `contract.py`.
2. Copy the deployed contract address into `CONTRACT_ADDRESS` near the
   top of `index.html`'s `<script>` tag.
3. Open `index.html` in a browser (or serve it locally) and either
   connect MetaMask (pointed at Studio's network) or click
   **"Start test session"** for a throwaway generated account.
4. Walk through the numbered panels in order:
   1. **Create Agreement** — as Party A, using the burner/wallet address
      of a second account as Party B.
   2. **Accept** — switch to the Party B account and accept.
   3. **Submit Deliverable** — back to Party A, submit a claim (+ optional evidence URLs).
   4. **Raise Dispute** — as Party B, dispute with a counter-claim.
   5. **Permissionless Actions → `resolve_dispute`** — anyone can trigger
      the real fetch + LLM adjudication. This is the slow step (can take
      a couple of minutes under validator consensus).
   6. **Raise Appeal** (optional) — the losing/partially-losing party
      can appeal once, within the challenge window.
   7. **Permissionless Actions → `resolve_appeal`** (if appealed) or
      **`finalize_unappealed`** (if the challenge window passed) to reach
      a final settlement.
   8. **Read Agreement** at any point to see the full state, including
      the per-condition verdict once adjudicated.

## State machine

```
pending_acceptance --accept_agreement------------> open
pending_acceptance --cancel_agreement------------> cancelled            [terminal]
pending_acceptance --expire_unaccepted (timeout)--> cancelled           [terminal]

open --submit_deliverable------------------------> submitted
open --expire_unsubmitted (timeout)---------------> refunded            [terminal]

submitted --raise_dispute-------------------------> disputed
submitted --finalize_uncontested (timeout)--------> settled             [terminal]

disputed --resolve_dispute------------------------> adjudicated
disputed --force_timeout_dispute (timeout)--------> refunded            [terminal]

adjudicated --raise_appeal-------------------------> appealed
adjudicated --finalize_unappealed (timeout)--------> settled            [terminal]

appealed --resolve_appeal--------------------------> settled            [terminal]
appealed --force_timeout_appeal (timeout)-----------> settled           [terminal]
```

Every non-terminal state has both a "happy path" transition and a
permissionless timeout exit — no agreement can get stuck.

## Design notes worth reading before extending this

See the `AgentCourt` class docstring in `contract.py` — it documents,
in order: the trust model (party binding, evidence locking, why the
*contract* computes settlement rather than the model), the full state
machine, the GenLayer building blocks used, and the intentionally
disclosed v1 limitations. If you're planning a v1.1 (bonded appeals,
multi-round appeal ladders, an escrow/payout layer), start there.
