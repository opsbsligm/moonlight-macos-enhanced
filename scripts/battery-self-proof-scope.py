"""Which files a self-proof gate actually opens, and what that lets the battery skip.

The assertion battery judges one planted mutation at a time by running a gate over
the mutated tree. Of its 153 cases, 107 ask the aggregate auditor
(`constraints-audit.py`) -- 77 by the default gate, 30 by naming it -- and the
aggregate answers by running every gate it drives, including four whose red proofs
re-derive their verdict from a fixture or a compiled harness. Measured here, in the
exact call shape the battery makes, one aggregate run costs 103.1s, and 85.1s of it
is those four red proofs (the snapshot's per-form seconds sum to more, 94s, because
they are timed in isolation and this delta shares a process tree). The answer each
returns is the answer it returns on a clean tree, because the line the battery moved
sits in nothing they open. That accounts for the record: 107 cases x 103.1s projects
to 11032s. The source of truth agrees from the other side: the untrimmed baseline
job 7141 (pipeline 1075) timed the first 34 aggregate cases at a mean of 154.2s, so
all 107 of them are 16500s against a 180-minute ceiling -- the job cannot finish
however long it is allowed. With the marker set and the mutation out of scope the
same local run measured 18.0s.

The narrow question this module answers: would this gate's proof say anything about
the file that was just moved? A proof that re-runs unchanged is not evidence about
the mutation -- it is the same evidence, bought twice. The judgement half of each
gate, the half that reads the tree, always runs; only the self-proof is skipped, and
only when the battery says which file it moved. Outside the battery nothing is
skipped at all: no marker is in the environment, so a push, a merge request, and a
developer's `local-gates.sh` each still run every red proof.

The read surfaces come from `scripts/battery-scope-probe.py`, which runs each gate
with an audit hook on `open` and records what it touched. A hand-written list went
wrong exactly that way: the first draft declared that `enhanced-presentation-tests.py`
reads three policy headers, when it also opens `VideoDecoderRenderer.m`,
`StreamViewController+Diagnostics.m` and three fixtures, and it declared that the
defaults audit reads five Swift files, when it walks the whole `Limelight` tree. A
list narrower than the truth silences a proof on precisely the mutations it exists
to catch, and does it quietly.

Two failures this module has to refuse, because it has had both:

  * answering about a gate it does not know. Unknown is not the same as irrelevant;
    an unlisted gate keeps its proof.
  * treating a caller's argument as a filename. The first draft passed the gate's
    whole command line -- a list -- where a path was expected.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "battery-self-proof-scope.json")

# Set by the battery for the duration of one judged mutation, to the repository-
# relative path it just rewrote. Deliberately absent everywhere else.
MUTATED_ENVIRONMENT_VARIABLE = "ML_MUTATED_FILE"

# The one sentence the aggregate prints when it excuses a proof, and the handle the
# battery counts to report how much it excused. Single-sourced so the counter cannot
# drift away from the print and quietly report zero excuses forever.
EXCUSED_LINE = "skip self-proof"


def _relative(path):
    """A repository-relative path with forward slashes, or None if it is outside."""
    if not path:
        return None
    absolute = path if os.path.isabs(path) else os.path.join(ROOT, path)
    try:
        resolved = os.path.realpath(absolute)
        relative = os.path.relpath(resolved, os.path.realpath(ROOT))
    except (ValueError, OSError):
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return relative.replace(os.sep, "/")


def mutated_file(environ=None):
    """The repository-relative file the battery rewrote, or None outside the battery."""
    source = os.environ if environ is None else environ
    raw = source.get(MUTATED_ENVIRONMENT_VARIABLE, "").strip()
    if not raw:
        return None
    return _relative(raw)


def load(path=SNAPSHOT_PATH):
    """The measured read surfaces. Raises if the snapshot is absent or unreadable.

    Loud on purpose: a missing snapshot means every gate is unknown, and unknown
    gates keep their proofs, so a silent fallback would look like the mechanism
    working while nothing was ever skipped.
    """
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    gates = document.get("gates")
    if not isinstance(gates, dict) or not gates:
        raise ValueError("%s declares no gates" % path)
    return gates


def gate_of(script):
    """The snapshot entry for a gate, found by its file name."""
    if script is None:
        return None
    name = os.path.basename(str(script))
    try:
        return load().get(name)
    except (OSError, ValueError):
        return None


def is_about(script, mutated=None):
    """Whether this mutation reaches anything `script` opens.

    `script` is the gate file, not a command line: the caller knows which gate it is
    about to excuse, and a list here is a caller bug worth hearing about. True is the
    answer that costs time and earns it; outside the battery it is always the answer.
    """
    if script is not None and not isinstance(script, (str, bytes, os.PathLike)):
        raise TypeError("is_about wants a gate path, got %s (%r)"
                        % (type(script).__name__, script))
    if mutated is None:
        mutated = mutated_file()
    if mutated is None:
        return True
    entry = gate_of(script)
    if entry is None:
        return True
    if mutated in entry.get("files", ()):
        return True
    return any(mutated == directory or mutated.startswith(directory.rstrip("/") + "/")
               for directory in entry.get("dirs", ()))


def skip_is_safe(script):
    """Whether this aggregate run may excuse `script`'s self-proof.

    The marker is the only authority, and that took two wrong attempts to see. The
    first question asked whether this was a battery run by asking whether
    `--no-battery` was absent, and the battery's own judging call passes that flag:
    `AUDIT_GATE` in assertion-battery.py carries it precisely so the aggregate does
    not recurse into the battery. So the flag says "do not run the battery", not
    "the battery is running me", and a rule keyed on its absence skipped nothing at
    all -- measured, a judging-shaped run with the marker set cost 103.6s against
    107.5s without it, and printed no skip line. A mechanism that cannot fire is
    worse than none, because it reads as a fix.

    The battery writes ML_MUTATED_FILE around each judged mutation and clears it
    otherwise, so a marker in the environment *is* the battery judging one
    mutation, from whichever call shape it came. With no marker this is a plain run
    -- a push, a merge request, or a developer's `local-gates.sh` -- and a plain run
    excuses nothing.
    """
    return mutated_file() is not None and not is_about(script)


def missing_subjects(path=SNAPSHOT_PATH):
    """Snapshot entries naming a file or directory the repository does not have."""
    findings = []
    for gate, entry in sorted(load(path).items()):
        for subject in entry.get("files", ()):
            if not os.path.isfile(os.path.join(ROOT, subject)):
                findings.append("%s -> %s" % (gate, subject))
        for subject in entry.get("dirs", ()):
            if not os.path.isdir(os.path.join(ROOT, subject)):
                findings.append("%s -> %s/" % (gate, subject))
    return findings


def skipped_in_a_battery_run(gates=None):
    """How many of a run's self-proofs the current marker would excuse, and their cost."""
    if gates is None:
        gates = load()
    seconds = 0.0
    names = []
    for gate, entry in sorted(gates.items()):
        if not is_about(gate):
            seconds += entry.get("seconds", 0)
            names.append(gate)
    return names, seconds
