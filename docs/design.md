# rem: design

Source under analysis: VictorTaelin/OptMem (`memo`, 31 KB, Python 3, zero deps; 2.3k stars).
Written 2026-10-29 against OptMem `main`.

## 1. OptMem, abstracted

Strip the code away and OptMem is five things.

| Component | Abstraction | Concrete choice in OptMem |
|---|---|---|
| Log | append-only sequence of atomic facts; position is identity | `LOG.txt`, 320-byte records `#<id> <date> <text>`, one seek per lookup |
| Tree | cache of `summarize(range)` over aligned power-of-two blocks | `TREE/<size>`, 288-byte records, dense prefix per level, rebuildable from the log |
| Policy | `(T, budget) -> partition of [0,T)` into blocks, resolution decaying with age | `cover()`: split a block while `size > alpha * age`; bisect alpha to fit 96 lines |
| Protocol | the agent is the summarizer; the tool only schedules, validates, stores | `note` prints one nap prompt; agent answers `nap lo-hi "line"`; repeat |
| View | render the partition, raw for singletons, summary otherwise, paginated | `wake [part] [T]`; refuses if a needed summary is missing |

Attributes worth keeping, in order of how much they matter:

1. **The tool never calls a model.** Model-agnostic, zero deps, no keys, no background process. The agent that already has context does the summarizing.
2. **Log is the only truth.** Tree is a cache; `forget` + `nap` rebuilds any part of it deterministically.
3. **Position is identity.** Fixed-width records make every read one seek, make crash repair a truncate, and make the tree implicit (no pointers, no index).
4. **Bounded reading cost.** `wake` prints `WAKE_LINES` lines whatever the log size. Storage and reading budgets are decoupled.
5. **Bounded write amplification.** A note triggers at most `log2(T)` summaries.
6. **Snapshot pinning.** `wake k T` pages are stable under concurrent writes.
7. **Small prompt footprint.** The agent protocol fits in ~430 tokens of CLAUDE.md.

Where it loses points:

| # | Weakness | Why it matters |
|---|---|---|
| W1 | **Naps are synchronous and one at a time.** Note number 1024 forces 10 sequential prompt/answer round trips before the agent may continue its task. Blocks of size 2..16 are all summarized from the same raw memories, yet each gets its own prompt listing them again. | Latency and tokens scale with `log2(T)` per boundary; interrupts the task at the worst moment. |
| W2 | **Wake fails closed.** One missing summary in the cover and `wake` exits 1. | Startup blocked by bookkeeping; the agent must nap before it has even read its memory. |
| W3 | **Resolution is recency-only.** Nothing but age decides what stays verbatim. A user preference noted on day one is 20 summary levels deep after a million notes and survives only if every summarizer along the chain kept it. | Compounding loss of the most valuable memory class (durable preferences, hard rules). |
| W4 | **No duplicate defence.** The prompt says "avoid duplicates"; the tool does nothing. | Agents re-note the same preference every session; the tree fills with repeats. |
| W5 | **Cover search is indirect.** 60-iteration bisection over a real-valued alpha, then a mop-up loop. | Not a performance issue; a clarity one. The same cover is a single greedy priority split. |
| W6 | Uniform 280-byte summaries at every level. | The summary of 2 memories and of 2^19 memories get the same budget. |
| W7 | One global store; subagents barred from writing; no scoping. | Project vs global knowledge mixes; subagent learnings are lost. |
| W8 | Byte budgets, not token budgets; regex-only recall. | Deliberate zero-dependency choices; cost is modest. |

## 2. The optimised abstraction

Same five components, three changes at the abstraction level:

- **Debt, not interruption.** A completed block is *debt*, not a *demand*. Commands report debt in one line. The agent pays debt when it chooses, in one batch, bottom-up, in a single response. The tool validates and stores the batch in canonical order. Wake renders missing summaries as their children (up to a slack) instead of failing, and only refuses when debt would blow the slack. (fixes W1, W2)
- **Batches are organised by input, not output.** All pending blocks that share the same raw window are listed under one copy of that window. Higher blocks reference either a stored child summary or "the line you write above". Round trips per boundary: `log2(T)` to 1. Prompt bytes per boundary: `2+4+8+16` raw lines to `16`. (fixes W1)
- **A second, tiny, agent-controlled axis: pins.** A pin is an id the agent marks as "in view every session". Pins render verbatim at the top of wake, counted against the same line budget. The timeline stays recency-decayed; pins are the importance axis, kept small by design and by a warning threshold. (fixes W3 for the class that matters most)

Plus two local improvements: the cover is a direct greedy priority split (fixes W5), and `note` refuses an exact normalised duplicate within the recent window and prints the existing id (fixes W4).

Everything else is kept on purpose: fixed-width records, identical `LOG.txt` and `TREE/` byte layout (a `rem` store is an OptMem store plus a `PINS` file, so `MEMORY_DIR=~/.optmem/memory rem wake` works on an existing store), one file, zero deps, no background process, no model calls.

## 3. 8 / 9 / 10

**OptMem today: 7/10.** Excellent engineering of a clear idea; loses points on W1..W4.

**8/10 design.** OptMem's storage and tree, unchanged, plus:
- batch naps, input-organised prompts, canonical-order acceptance with partial success;
- wake degrades to children under a slack and reports debt instead of failing;
- direct priority-split cover;
- the same ~400-token protocol, with "pay debt at a pause and before session end" replacing "nap before your next action".

**9/10 design (the target, implemented here).** The 8/10 plus:
- pins (`note --pin`, `pin`, `unpin`), rendered first in wake, warned past `PIN_LINES`;
- exact-duplicate refusal with the existing id, `--force` to override;
- `status` (count, pins, debt) so agents and hooks can poll cheaply;
- OptMem store compatibility, so adoption is a rename.

**10/10 design (what is missing, and why it is not here).**
- **Scopes.** A project store layered over a global store, woken together (CLAUDE.md-style layering). Additive: two stores, one merged view. Left out because it doubles the protocol surface for a benefit that `REM_DIR` per project already approximates.
- **Importance-weighted cover.** Generalise pins to weights so the split priority is `size * weight / age`. Needs a weight source (access counts from `recall`/`zoom`, agent-set weights). Left out: no evidence yet that agents set weights well; pins are the proven 80%.
- **Graded summary widths.** Record width per level grows with span. Cheap to store (`TREE/<s>` already has its own file), but changes the on-disk compat and the wake byte budget. Left out for compat.
- **Token-accurate budgets and semantic recall.** Both need a dependency (tokenizer, embeddings). Out by the zero-dep rule; a 10/10 would make them optional plug-ins.
- **Subagent inbox.** Subagents write to `INBOX`, the parent reviews and promotes at session end. Left out: protocol cost in the prompt block.
- **Summary provenance.** Model and date per summary, so a model upgrade can re-summarise selectively. Needs a wider record. Left out for compat.
- **Session-aligned blocks.** Summaries over natural session boundaries read better than over power-of-two boundaries. Incompatible with the implicit tree; would need an explicit one.

## 4. Design gate (design-pattern-language)

```text
Relevant patterns:
  Existing Pattern First -- OptMem's log/tree layout is proven; keep it byte-compatible.
  Explicit State Model   -- debt (pending blocks) and pins are the only new state; both derived
                            or append-only; transitions: note->debt, nap->settled, forget->debt,
                            pin/unpin->PINS append.
  Smallest Reversible Change -- every addition is additive to the store (PINS file) or to the
                            protocol (batch nap accepts the single-line OptMem form too).
  Error Path First       -- wake must never fail closed on bookkeeping; corrupt data names the
                            repair command; partial nap batches store the valid prefix.

Boundary map:
  log     owns ids, dates, text; append-only; LOG.txt
  tree    owns summaries keyed by (lo,hi); dense-prefix invariant per level; TREE/<s>
  pins    owns the in-view set; append-only +id/-id events; PINS
  cover   pure function (T, budget) -> blocks; no IO
  prompts pure function (store snapshot, T) -> batch text; no writes
  cli     parses, locks, writes, prints; the only layer that exits

Design choice:
  Debt model with batch naps; wake degrades under slack; pins as a separate, bounded axis;
  one file, zero deps, OptMem-compatible layout.

Rejected alternatives:
  Variable-length log + offset index: saves disk, loses byte compat and grep-ability, no
    reading-cost benefit. Disk is not the bottleneck (608 MB per million).
  Lazy summarisation (build only what the cover needs): every block is eventually an input
    to its parent, so laziness only moves the cost; debt deferral captures the benefit.
  Refuse near-duplicates by word overlap: false positives on updates ("prefers tabs" vs
    "prefers spaces"). Exact normalised match only.
  Nap prompt inline in wake: keeps wake unbounded; a one-line pointer costs one extra call.

Implementation plan:
  1. rem (single file): knobs, store, log, tree, pins, cover, prompts, commands, cli.
  2. test_rem.py: OptMem's invariant set ported, plus batch/debt/pin/dedup/compat checks.
  3. README.md with the prompt block; install.sh.

Validation:
  python3 test_rem.py -> all checks pass, including 16-process concurrency and crash repair.
  Prompt block measured under 450 tokens (bytes/4 bound).

Measured (2026-10-29, Python 3.13, Apple silicon):
  2000-memory import: 1999 summaries paid in 33 nap rounds (NAP_MAX=64), 0.1 MB of prompts;
    OptMem: 1999 rounds.
  1M-memory store (320 MB log, full tree): wake 2 ms, 98 lines; pending_count 0.2 ms;
    duplicate check 3.8 ms.
  test_rem.py: 56131 checks, 0 failures.

Stop conditions:
  A compat break with OptMem's LOG/TREE layout; a new dependency; wake output unbounded.
```
