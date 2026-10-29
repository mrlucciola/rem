# rem

Permanent memory for AI agents. One Python 3 script, no dependencies, nothing in the
background, and a prompt block of about 330 tokens. A reimplementation of
[OptMem](https://github.com/VictorTaelin/OptMem) with the same storage and a leaner protocol;
the reasoning is in [docs/design.md](docs/design.md).

```
curl -fsSL https://raw.githubusercontent.com/mrlucciola/rem/main/install.sh | sh
```

That puts the tool at `~/.rem/rem`, creates `~/.rem/memory`, and prints the block to paste
into your agent's `AGENTS.md` or `CLAUDE.md`. Rerun the line to update.

## What the agent does

| Command | When |
|---|---|
| `rem wake` | first thing in every session: the whole memory in about 96 lines, oldest first, finest toward now |
| `rem note "<one line>"` | whenever something durable is learned; `--pin` for the few facts that must be in view every session |
| `rem nap` | when a command reports memory debt: prints every pending summary in one batch, the agent answers with one command |
| `rem recall <regex>` | search every memory verbatim |
| `rem zoom <a-b>` | open a summary line into its two halves, down to the memories |
| `rem pin <id>` / `unpin <id>` | keep a memory in view, or stop |
| `rem forget <a-b>` | drop a bad summary; the next nap rebuilds it |
| `rem status` | memories, pins, debt, tree levels |
| `rem config [NAME=VALUE]` | sizes |
| `rem import <file>` | lines of `YYYY-MM-DD <text>` |

## How it works

Memories are an append-only log. Over the log sits an implicit binary tree: every aligned
power-of-two block of memories (`#0-1`, `#2-3`, `#0-3`, `#4-7`, `#0-7`, ...) has one line of
summary, written by the agent, cached on disk, rebuildable from the log.

`wake` picks a tiling of the log into at most `WAKE_LINES` blocks, splitting a block while
its size is large relative to its age, so the newest memories print verbatim and the oldest
print as one line per thousand. That is a reading budget, not a storage limit: a million
memories wake in 2 ms and 98 lines.

**Debt, not interruption.** A block whose summary is missing is debt. `note` reports it in one
line and moves on. `wake` renders a missing summary as its children instead of failing, up to
twice the budget; past that it asks for the debt first. The agent pays debt at a pause with
`rem nap`, which prints every pending block organised by input: each window of raw memories
once, with the list of summaries to write from it; higher blocks from their two halves, or
from "the line you write above". The agent writes them all in one response:

```
rem nap <<'EOF'
0-1 user runs macOS, zsh, prefers tabs
2-3 project X uses bun; tests under tests/
0-3 user: macOS/zsh/tabs. project X: bun, tests under tests/
EOF
```

Lines are applied in canonical order whatever order they arrive; a settled block is never
overwritten; a gap is reported with the block that comes first. 2000 imported memories pay
their 1999 summaries in 33 rounds of at most `NAP_MAX`, not 1999; a normal session's debt
is one round.

**Pins.** Recency decides resolution; pins are the one exception. A pinned memory prints
verbatim at the top of every wake, inside the same line budget. Keep them few; `wake` warns
past `PIN_LINES`.

**Duplicates.** `note` refuses a memory whose normalised text already exists in the recent
window or among pins, and prints the existing id. `--force` overrides. Near-duplicates are
saved: "prefers tabs" and "prefers spaces" are an update, not a repeat.

## Files

```
~/.rem/
  rem              the tool
  memory/          or $REM_DIR (also honours OptMem's $MEMORY_DIR)
    LOG.txt        320-byte records "#<id> <date> <text>"; memory i is at byte i*320
    TREE/<s>       288-byte records; the summary of block k of size s is at byte k*288
    PINS           append-only +id / -id events
    config         sizes, via rem config
```

Position is identity: every read is one seek, there is no index, and a torn write is repaired
by truncating to the record boundary. Writes take one `flock`; reads take none, and `wake k T`
pins its snapshot so pages stay consistent under concurrent notes.

`LOG.txt` and `TREE/` are byte-compatible with OptMem. `MEMORY_DIR=~/.optmem/memory rem wake`
reads an existing OptMem store as is.

## Sizes

```
WAKE_LINES    96   lines wake may print
PIN_LINES     16   pins above this count make wake warn
ENTRY_CHARS  280   max bytes in one memory or summary
RAW_MAX       32   blocks up to this size are summarised from raw memories
NAP_MAX       64   max summaries asked for in one nap batch
PART_CHARS 20000   max bytes per output part
PART_LINES   500   max lines per output part
```

## Tests

```
python3 test_rem.py
```

Cover maths over 400+ sizes, buildability, work bound, init idempotence, validation,
debt/degraded wake/batch acceptance, 2000-memory import and exact-budget wake, snapshot
stability, recall/zoom/forget/rebuild, corrupt-store repair hints, torn-record recovery,
config, 16-process concurrency, bare-PATH `Run:` lines, locale, and OptMem compatibility.
