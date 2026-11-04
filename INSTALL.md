# Installing rem

rem gives your coding agent a permanent memory: facts it learns today are still there
next week, in the next session, even under a different model. It is one Python script
with no dependencies, and installing it takes about five minutes. The only network
access in the whole process is the `git clone` in step 1 -- nothing else is downloaded,
and nothing phones home afterwards.

You need `git` and `python3` (3.8 or newer). macOS has both after
`xcode-select --install`; most Linux distributions ship them. On Windows, use WSL;
native Windows is untested.

## 1. Get the code

```sh
git clone https://github.com/mrlucciola/rem.git ~/rem
```

## 2. Link it into place

```sh
mkdir -p ~/.rem
ln -sf ~/rem/rem ~/.rem/rem
```

Why a symlink instead of a copy? Because then updating rem is just `git -C ~/rem pull`:
the link keeps pointing at the fresh script, and your memories -- which live in a
separate folder -- are never touched by an update.

## 3. Create the memory store

```sh
~/.rem/rem init
```

This creates `~/.rem/memory` (three small plain files that will hold everything your
agent remembers) and prints a block of instructions headed `## Memory`. Keep that
output on screen -- you need it in the next step.

## 4. Teach your agent about it

The printed `## Memory` block is the entire integration. Copy everything from the
`## Memory` line down and paste it at the end of the instructions file your agent
reads at the start of every session:

| Agent | File |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` for all projects, or `<repo>/CLAUDE.md` for one |
| Codex CLI | `~/.codex/AGENTS.md` |
| anything else | whatever it loads first; the block is plain markdown |

Paste by hand rather than redirecting `init`'s output into the file: `init` prints two
header lines above the block, and running it twice would leave you with two copies.

That's it. The agent now wakes its memory first thing in every session, saves durable
facts as it learns them, and condenses old ones at natural pauses. There is no daemon,
no plugin, and no API key.

## 5. Check it works

```sh
~/.rem/rem status
# expect: store ~/.rem/memory, memories 0, pins 0, debt 0
~/.rem/rem note "rem installed on this machine"
~/.rem/rem wake
```

`wake` should print your one memory back. Day to day the agent runs these, not you --
but this is also how you peek at what it knows.

## 6. Claude Code only: skip the permission prompts

Claude Code asks before every shell command, so each memory read or write would
interrupt you with a prompt. Allow the tool once, in `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(~/.rem/rem:*)"]
  }
}
```

## 7. Optional: make waking a guarantee

The `## Memory` block *tells* the agent to run `wake` first; well-behaved agents do.
If you want it enforced rather than followed, Claude Code can run it for you at
session start via a hook -- the hook's output lands directly in the session's context.
In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "~/.rem/rem wake" } ] }
    ]
  }
}
```

Keep the wake line in the pasted block anyway: after a context compaction mid-session,
hooks do not rerun, and the written instruction is what brings the memory back.

A hook's output reaches the agent only when the command exits 0, so `wake` exits 0 even
when it refuses for too much debt: the agent then sees the `Run: ~/.rem/rem nap` line
instead of nothing. Only real errors (no store, corrupt record) exit 1.

## Updating

```sh
git -C ~/rem pull
```

That is the whole update. The store is separate from the code, so your memories
survive every update.

## Memory on more than one machine

The clone carries the tool, not your memories. To share memory between machines, keep
the store in a folder that syncs (iCloud, Dropbox, a private git repo you push after
sessions) and tell rem where it is -- in `~/.zshrc` or `~/.bashrc`, before the agent
starts:

```sh
export REM_DIR=~/Sync/rem-memory
```

Then run `~/.rem/rem init` once to create the store there, and repeat steps 1-4 on the
other machine with the same `REM_DIR`. The store is three append-only files, so sync
conflicts are rare and never destroy earlier memories -- but do not run agents against
one store from two machines at the same moment; the write lock is per machine.

## Uninstalling

Remove the `## Memory` block from your instructions file, then delete the clone and
the tool directory:

```sh
rm -rf ~/rem ~/.rem
```

`~/.rem` contains your memories. If you might want them later, copy
`~/.rem/memory` somewhere first -- it is plain text and readable on its own.
