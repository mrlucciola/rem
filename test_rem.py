#!/usr/bin/env python3
"""rem test suite. Run: python3 test_rem.py

In-process checks through rem's COMMANDS table, plus subprocess checks where the real
entry point matters (exit codes, concurrency, PATH). Exit code 1 on any failure."""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
REM = os.path.join(HERE, "rem")
rem = SourceFileLoader("rem_cli", REM).load_module()

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL: {msg}")


class Result:
    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err


STORE = None


def run(*args, stdin="", store=None):
    d = store or STORE
    os.environ["REM_DIR"] = d
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdout, sys.stderr, sys.stdin
    sys.stdout, sys.stderr, sys.stdin = out, err, io.StringIO(stdin)
    code = 0
    try:
        code = rem.main(list(args)) or 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdout, sys.stderr, sys.stdin = old
    return Result(code, out.getvalue(), err.getvalue())


def sh(*args, store=None, env=None, stdin=None):
    e = dict(os.environ)
    e["REM_DIR"] = store or STORE
    if env:
        e.update(env)
    p = subprocess.run([sys.executable, REM, *args], capture_output=True, text=True, env=e, input=stdin)
    return Result(p.returncode, p.stdout, p.stderr)


def fresh():
    global STORE
    STORE = tempfile.mkdtemp(prefix="rem-test-")
    run("init")
    return STORE


def complete(T):
    out, s = [], 2
    while s <= T:
        out += [(k * s, (k + 1) * s) for k in range(T // s)]
        s *= 2
    return out


def pay_all(max_rounds=10_000):
    """Pay every nap batch the tool offers; return the number of rounds."""
    rounds = 0
    while True:
        r = run("nap")
        if "No memory debt" in r.out:
            return rounds
        rounds += 1
        lines = []
        for m in re.finditer(r"^Write: (.*)$", r.out, re.M):
            for b in m.group(1).split():
                lines.append(f"{b} summary of {b}")
        check(lines, "nap batch offers at least one block")
        r2 = run("nap", stdin="\n".join(lines))
        check(r2.code == 0, f"batch accepted: {r2.out}")
        if rounds > max_rounds:
            check(False, "nap loop did not terminate")
            return rounds


def tree_bytes(d):
    t = os.path.join(d, "TREE")
    return sum(os.path.getsize(os.path.join(t, f)) for f in os.listdir(t))


def fingerprint(d):
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            if f == ".lock":
                continue
            p = os.path.join(root, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, d)] = fh.read()
    return out


# ------------------------------------------------------------ 1. cover math
print("1 cover")
for T in list(range(0, 400)) + [1000, 4096, 4097, 65535, 1_000_000, 2**24 + 17]:
    for budget in (8, 32, 96):
        c = rem.cover(T, budget)
        pc = bin(T).count("1")
        check(len(c) <= max(budget, pc), f"cover({T},{budget}) size {len(c)} over budget")
        check(all(c[i][1] == c[i + 1][0] for i in range(len(c) - 1)), f"cover({T},{budget}) has a gap")
        check((not c and T == 0) or (c[0][0] == 0 and c[-1][1] == T), f"cover({T},{budget}) does not span [0,T)")
        for lo, hi in c:
            s = hi - lo
            check(s & (s - 1) == 0 and lo % s == 0, f"cover({T},{budget}) block {lo}-{hi} not aligned pow2")
        sizes = [hi - lo for lo, hi in c]
        check(all(sizes[i] >= sizes[i + 1] for i in range(len(sizes) - 1)), f"cover({T},{budget}) not finest toward T: {sizes[:8]}...")
        if T > budget >= pc:
            check(len(c) == budget, f"cover({T},{budget}) leaves budget unused: {len(c)}")
check(rem.cover(5, 10) == [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)], "small T is all singletons")

# buildability: every block any cover needs is a complete block
need = set()
for T in range(1, 3001):
    need |= set(rem.cover(T, 96))
check(all(b in set(complete(3000)) or b[1] - b[0] == 1 for b in need), "every cover block is buildable")

# work bound
check(all(len(complete(T)) - len(complete(T - 1)) <= 16 for T in range(1, 65537, 977)), "one note adds at most 16 summaries")

# ------------------------------------------------------------ 2. smoke, init, empty wake
print("2 init")
fresh()
r = sh()
check(r.code == 0 and "rem:" in r.out, "no-arg usage exits 0")
r = sh("bogus")
check(r.code == 1 and "No such command" in r.err, "unknown command exits 1")
r = run("init")
check("## Memory" in r.out and "wake" in r.out, "init prints the prompt block")
block = re.search(r"## Memory.*", r.out, re.S).group(0)
check(len(block.encode()) / 4 < 450, f"prompt block under 450 tokens by bytes/4: {len(block.encode()) / 4:.0f}")
r = run("wake")
check(r.code == 0 and "No memories yet" in r.out and "You are awake" in r.out, "empty wake")
r = sh("wake", store=os.path.join(STORE, "nope"))
check(r.code == 1 and "init" in r.err and "Traceback" not in r.err, "missing store names init, no traceback")

# ------------------------------------------------------------ 3. note, dedup, pins
print("3 note")
r = run("note", "User prefers terse replies.")
check(r.code == 0 and "Saved as #0" in r.out and "debt" not in r.out, "first note, no debt")
r = run("note", "user prefers terse replies")
check(r.code == 0 and "Already known as #0" in r.out and rem.log_len(STORE) == 1, "exact normalised duplicate refused")
r = run("note", "--force", "user prefers terse replies")
check("Saved as #1" in r.out and "Memory debt: 1 summary" in r.out, "--force saves; debt reported in one line")
r = run("note", "User prefers tabs over spaces")
r = run("note", "User prefers spaces over tabs")
check("Saved as #3" in r.out, "near-duplicates are not refused (updates must get through)")
r = run("note", "")
check(r.code == 1 and "empty" in r.err, "empty refused")
r = run("note", "a\nb")
check(r.code == 1 and "one line" in r.err, "multiline refused")
r = run("note", "x" * 281)
check(r.code == 1 and "too long" in r.err, "281 bytes refused")
r = run("note", "é" * 140)
check(r.code == 0, "280 bytes of UTF-8 accepted")
r = run("note", "é" * 141)
check(r.code == 1, "282 bytes of UTF-8 refused: the limit is bytes")
r = run("note", "--pin", "Always answer in English.")
check("Saved and pinned as #5" in r.out and rem.pins(STORE) == [5], "note --pin")
r = run("pin", "2")
check("Pinned #2" in r.out and rem.pins(STORE) == [2, 5], "pin by id")
r = run("pin", "2")
check("already pinned" in r.out, "double pin is a no-op")
r = run("pin", "99")
check(r.code == 1, "pin of a missing id fails")
r = run("wake")
check("Pinned (2):" in r.out and r.out.index("#2 ") < r.out.index("Memory (") , "pins render first")
check("#5 " in r.out.split("Memory (")[0], "pinned #5 is in the pinned section")
r = run("unpin", "2")
check(rem.pins(STORE) == [5], "unpin")
r = run("note", "--pin", "always answer in english")
check("Already known as #5" in r.out and rem.pins(STORE) == [5], "dup with --pin keeps pin, saves nothing")
r = run("status")
check("memories  6" in r.out and "pins      1" in r.out and re.search(r"debt      \d", r.out), "status")

# ------------------------------------------------------------ 4. debt, degraded wake, batch nap
print("4 debt")
fresh()
for i in range(8):
    run("note", f"memory number {i}")
check(rem.pending(STORE, 8) == complete(8), "pending equals the oracle, smallest level first")
r = run("wake")
check(r.code == 0 and "You are awake" in r.out and "Memory debt: 7 summaries" in r.out, "wake succeeds with debt and reports it")
r = run("nap")
check(r.out.count("Memories #0-7:") == 1, "raw window listed once for all levels")
check(re.search(r"^Write: 0-1 2-3 4-5 6-7 0-3 4-7 0-7$", r.out, re.M), f"one Write line covers every pending block: {r.out}")
check("7 in this batch" in r.out, "batch header counts")
# out-of-order: parent-only submission at a level with a gap
r = run("nap", "2-3 pair two")
check(r.code == 1 and "0-1 comes first" in r.out and "Stored 0 summaries" in r.out, "gap at a level is reported")
r = run("nap", "0-3 quad", "2-3 pair two", "0-1 pair one", "6-7 pair four")
check(r.code == 1 and "Stored 3 summaries" in r.out and "4-5 comes first" in r.out,
      f"batch applied in canonical order; a gap at a level is reported: {r.out}")
r = run("nap", "0-1 pair one again")
check("1 already settled" in r.out and rem.tree_get(STORE, 0, 2) == "pair one", "settled block is immutable")
r = run("nap", "4-5 pair three", "6-7 pair four", "4-7 quad two", "0-7 oct", "8-9 future")
check(r.code == 1 and "Stored 4 summaries" in r.out and "ends after" in r.out and "Clear" in r.out, f"partial batch, future block rejected: {r.out}")
check(rem.pending_count(STORE, 8) == 0, "debt clear")
r = run("nap")
check("No memory debt" in r.out, "no debt")
r = run("nap", "0-1")
check(r.code == 1 and "skipped" in r.out, "line without text reported")
r = run("nap", "x" * 300)
check(r.code == 1, "garbage line fails")

# ------------------------------------------------------------ 5. scale: import, refuse over slack, pay in batches, exact budget
print("5 scale")
fresh()
N = 2000
p = os.path.join(STORE, "import.txt")
import datetime
with open(p, "w") as f:
    for i in range(N):
        day = datetime.date(2024, 1, 1) + datetime.timedelta(days=i // 10)
        f.write(f"{day.isoformat()} imported memory {i} with some words\n")
r = run("import", p)
check(r.code == 0 and f"Imported #0-#{N - 1}" in r.out, f"import: {r.err}")
r = run("wake")
check(r.code == 1 and "Cannot wake within budget" in r.out and "nap" in r.out, "debt beyond slack refuses with a pointer")
rounds = pay_all()
total = len(complete(N))
check(rounds < total / 4, f"batching: {rounds} rounds for {total} summaries")
check(rem.pending_count(STORE, N) == 0, "all debt paid")
r = run("wake")
check(r.code == 0 and "debt" not in r.out, "wake after paying")
body = r.out.split("oldest first):\n", 1)[1].split("\nYou are awake")[0].splitlines()
check(len(body) == rem.WAKE_LINES, f"wake is exactly WAKE_LINES lines of memory: {len(body)}")
check(body[-1].startswith(f"#{N - 1} "), "newest memory is last and verbatim")
check(body[0].startswith("#0-"), "oldest block is a summary")
# small debt: degrade instead of refusing
for i in range(20):
    run("note", f"late memory {i}")
r = run("wake")
check(r.code == 0 and "Memory debt" in r.out, "small debt degrades and reports")
# tree record widths
for f in os.listdir(os.path.join(STORE, "TREE")):
    check(os.path.getsize(os.path.join(STORE, "TREE", f)) % rem.TREE_REC == 0, f"TREE/{f} whole records")
check(os.path.getsize(os.path.join(STORE, "LOG.txt")) % rem.LOG_REC == 0, "LOG.txt whole records")
with open(os.path.join(STORE, "LOG.txt"), "rb") as f:
    rec = f.read(rem.LOG_REC)
check(rec.startswith(b"#0 2024-01-01 imported memory 0") and rec[-1:] == b"\n" and rec[-2:-1] == b" ", "OptMem-compatible log record")

# ------------------------------------------------------------ 6. as-of-T, pagination
print("6 snapshot")
run("config", "PART_LINES=40", "WAKE_LINES=96")
r1 = run("wake", "1", str(N))
check("part 1 of" in r1.out and f"wake 2 {N}" in r1.out, "paginated wake pins T in the Run line")
for i in range(5):
    run("note", f"concurrent note {i}")
r2 = run("wake", "1", str(N))
check(r1.out == r2.out, "a part rendered at T is unchanged by later notes")
r = run("wake", "1", str(10**9))
check(r.code == 1 and "future" in r.err, "future T rejected")
r = run("wake", "99")
check(r.code == 1 and "no part 99" in r.err, "bad part number")
run("config", "PART_LINES=", "WAKE_LINES=")

# ------------------------------------------------------------ 7. recall, zoom, forget
print("7 navigate")
r = run("recall", "imported memory 1999")
check(r.code == 0 and "#1999 " in r.out and "1 match." in r.out, "recall hits id and text")
r = run("recall", "imported")
check("Showing the newest" in r.out, "recall is capped and says so")
r = run("recall", "zzzqqq")
check("No match." in r.out, "recall miss")
r = run("recall", "(")
check(r.code == 1 and "regex" in r.err, "bad regex")
r = run("zoom", "0-1023")
check("#0-511 " in r.out and "#512-1023 " in r.out, "zoom halves")
r = run("zoom", "1998-1999")
check("#1998 " in r.out and "#1999 " in r.out, "zoom to leaves")
r = run("zoom", "0-2")
check(r.code == 1 and "not a block" in r.err, "non-block rejected")
r = run("zoom", f"{2**20}-{2**21 - 1}")
check(r.code == 1, "block after newest rejected")
pay_all()
before = tree_bytes(STORE)
fp = fingerprint(STORE)
r = run("forget", "0-511")
check(r.code == 0 and "0-511" in r.out and "0-1023" in r.out, "forget drops the block and its ancestors")
check(tree_bytes(STORE) < before, "tree shrank")
after = fingerprint(STORE)
check(after["LOG.txt"] == fp["LOG.txt"] and after["PINS"] == fp["PINS"], "forget never touches the log or pins")
pay_all()
check(tree_bytes(STORE) == before, "rebuild restores the tree size")
r = run("forget", "0-511")
r = run("forget", "0-511")
check(r.code == 1 and "no summary" in r.err, "forgetting twice fails")
pay_all()

# ------------------------------------------------------------ 8. corrupt store
print("8 corrupt")
fresh()
for i in range(40):
    run("note", f"m{i}")
pay_all()
run("config", "WAKE_LINES=8")
check(rem.cover(40, 8)[0] == (0, 16), "test premise: #0-15 is in the cover")
p2 = os.path.join(STORE, "TREE", "16")
with open(p2, "r+b") as f:
    f.seek(0)
    f.write(b" " * (rem.TREE_REC - 1) + b"\n")
r = run("wake")
# the blank is a cover block with children present: wake must name forget, not pending work
check(r.code == 1 and "forget 0-15" in r.err and "Traceback" not in r.err, f"blank summary names forget: {r.err}")
run("forget", "0-15")
pay_all()
with open(p2, "r+b") as f:
    f.seek(0)
    f.write(b"\xff\xfe" + b" " * (rem.TREE_REC - 3) + b"\n")
r = run("wake")
check(r.code == 1 and "forget" in r.err, "non-UTF-8 summary names forget")
run("config", "WAKE_LINES=")

# ------------------------------------------------------------ 9. crash recovery
print("9 crash")
fresh()
run("note", "one")
with open(os.path.join(STORE, "LOG.txt"), "ab") as f:
    f.write(b"#1 2024-01-01 torn")
run("note", "two")
lines = rem.log_slice(STORE, 0, 2)
check(len(lines) == 2 and lines[1].endswith("two") and rem.log_len(STORE) == 2, "torn record dropped, alignment kept")

# ------------------------------------------------------------ 10. config
print("10 config")
r = run("config")
check("WAKE_LINES" in r.out and "RAW_MAX" in r.out, "config table")
r = run("config", "WAKE_LINES=10")
check(rem.WAKE_LINES == 10 and "WAKE_LINES = 10" in open(os.path.join(STORE, "config")).read(), "set takes effect and persists")
r = run("config", "WAKE_LINES=")
check(rem.WAKE_LINES == 96, "empty value restores default")
r = run("config", "ENTRY_CHARS=5000")
check(r.code == 1 and "may not exceed" in r.err, "ENTRY_CHARS capped by the record")
r = run("config", "NOPE=3")
check(r.code == 1 and "unknown" in r.err, "unknown key")
with open(os.path.join(STORE, "config"), "a") as f:
    f.write("WAKE_LINES = abc\n")
r = sh("wake")
check(r.code == 1 and "config:" in r.err and "Traceback" not in r.err, f"config typo names file and line: {r.err}")

# ------------------------------------------------------------ 11. concurrency
print("11 concurrency")
fresh()
procs = [subprocess.Popen([sys.executable, REM, "note", f"parallel {i}"], env={**os.environ, "REM_DIR": STORE},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(16)]
outs = [p.communicate()[0].decode() for p in procs]
check(all(p.returncode == 0 for p in procs), "16 parallel notes exit 0")
ids = sorted(int(re.search(r"#(\d+)", o).group(1)) for o in outs)
check(ids == list(range(16)), f"ids 0..15 without collision: {ids}")
check(rem.log_len(STORE) == 16 and os.path.getsize(os.path.join(STORE, "LOG.txt")) == 16 * rem.LOG_REC, "log intact")

# ------------------------------------------------------------ 12. runnable Run: lines, locale, import validation
print("12 misc")
fresh()
run("note", "a")
run("note", "b")
r = sh("nap")
cmd = re.search(r"^  (\S+) nap <<'EOF'", r.out, re.M).group(1)
check(cmd == rem.ME and os.path.exists(os.path.expanduser(cmd)), "printed command is this script")
r = subprocess.run(["/bin/sh", "-c", f"{cmd} status"], capture_output=True, text=True,
                   env={"REM_DIR": STORE, "PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~")})
check(r.returncode == 0 and "memories  2" in r.stdout, f"Run line executes with a bare PATH: {r.stderr}")
r = sh("wake", env={"PYTHONIOENCODING": "latin-1"})
check(r.code == 0, "wake under latin-1 locale")
run("note", "ünïcödé across the boundary")
r = sh("recall", "ünïcödé", env={"PYTHONIOENCODING": "latin-1"})
check("ünïcödé" in r.out, "UTF-8 output under latin-1 locale")
bad = os.path.join(STORE, "bad.txt")
with open(bad, "w") as f:
    f.write("2024-02-30 impossible\n")
r = run("import", bad)
check(r.code == 1 and "not a date" in r.err, "impossible date rejected")
with open(bad, "w") as f:
    f.write("2023-01-01 earlier than existing\n")
r = run("import", bad)
check(r.code == 1 and "earlier" in r.err, "non-monotone date rejected")
with open(bad, "wb") as f:
    f.write(b"2024-01-01 \xff\xfe\n")
r = run("import", bad)
check(r.code == 1 and "UTF-8" in r.err, "non-UTF-8 import rejected")
fp = fingerprint(STORE)
run("init")
check(fingerprint(STORE) == fp, "re-init is byte-identical")

# ------------------------------------------------------------ 13. OptMem store compatibility
print("13 compat")
d = tempfile.mkdtemp(prefix="optmem-")
os.makedirs(os.path.join(d, "TREE"))
with open(os.path.join(d, "LOG.txt"), "wb") as f:
    for i in range(4):
        f.write(rem.pad(f"#{i} 2025-01-0{i + 1} optmem memory {i}", 320))
with open(os.path.join(d, "TREE", "2"), "wb") as f:
    f.write(rem.pad("first pair", 288))
    f.write(rem.pad("second pair", 288))
with open(os.path.join(d, "config"), "w") as f:
    f.write("WAKE_LINES = 2  # from optmem\n# ENTRY_CHARS = 280\n")
os.environ.pop("REM_DIR", None)
os.environ["MEMORY_DIR"] = d
out, err = io.StringIO(), io.StringIO()
old = sys.stdout, sys.stderr
sys.stdout, sys.stderr = out, err
try:
    code = rem.main(["wake"])
except SystemExit as e:
    code = e.code
finally:
    sys.stdout, sys.stderr = old
os.environ.pop("MEMORY_DIR")
check(code == 0 and "#0-1 first pair" in out.getvalue() and "#2-3 second pair" in out.getvalue(), f"reads an OptMem store via MEMORY_DIR: {out.getvalue()}{err.getvalue()}")
check(rem.pending(d, 4) == [(0, 4)], "OptMem tree levels are understood")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
