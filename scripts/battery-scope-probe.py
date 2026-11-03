#!/usr/bin/env python3
"""Measure which files a self-proof gate actually reads, so a skip rule can be checked.

`battery-self-proof-scope.py` excuses a gate's red proof when the file the assertion
battery moved sits in nothing that proof opens. That is only safe while the recorded
read surface is at least as wide as the truth: a snapshot narrower than reality silences
a proof on precisely the mutations it exists to catch, and silences it quietly, because
the run stays green. A hand-written list went wrong exactly that way the first time.

So the list is measured. Each skipped form runs in a child with two audit hooks:
`open`, which catches every file the gate reads itself, and `subprocess.Popen`, which
catches the file arguments of the compilers and helpers it spawns. A harness compiled
against `Limelight/Stream/VideoDecoderRenderer.m` reads that header through clang, not
through Python, and a rule that only watched Python would call that header unread.
Include directories become directory subjects for the same reason: any header under a
directory handed to `-I` can be pulled in by a later `#include`.

Usage:
    battery-scope-probe.py                 # measure, compare with the snapshot, report
    battery-scope-probe.py --write         # measure and rewrite the snapshot's surfaces
    battery-scope-probe.py --gate <name>   # measure one gate only

Exit 0 only when every measured read is covered by the snapshot that ships. Missing
coverage is the dangerous direction and fails; extra recorded coverage only costs time
and is reported without failing.
"""
import argparse
import json
import importlib
import platform
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SNAPSHOT = os.path.join(SCRIPTS, "battery-self-proof-scope.json")

# The module that consumes the snapshot this file checks. Wiring it in is what makes a
# subject that names a file the repository no longer has a failure of this step instead
# of a silent narrowing: the consumer would then excuse a proof for a file no mutation
# can name, and the run stays green forever. `SCRIPTS` is on `sys.path` for the child
# below; the parent needs it for the import.
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
scope = importlib.import_module("battery-self-proof-scope")

# The child installs the hooks and then runs the gate, so the gate's own import of
# python modules is excluded below; what matters is what it reads under this checkout.
CHILD = r'''
import json, os, runpy, sys

root, out = sys.argv[1], sys.argv[2]
target, args = sys.argv[3], sys.argv[4:]
opened, spawned, walked = [], [], []

def rel(path):
    try:
        absolute = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
        resolved = os.path.realpath(absolute)
        relative = os.path.relpath(resolved, os.path.realpath(root))
    except (ValueError, OSError):
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    # Only something that exists can be a read surface. `enhanced-presentation-tests.py`
    # opens a path the standard library spells `<unknown>`, which resolves to a name
    # under this checkout and would otherwise be reported as an undeclared read no
    # snapshot could ever satisfy. A file the gate tried and failed to open says
    # nothing about what the gate reads, so it is not evidence about scope either.
    if not os.path.exists(resolved):
        return None
    return relative.replace(os.sep, "/")

def hook(event, payload):
    if event == "os.walk":
        # A directory walk is a claim about a whole subtree, and it is the one read
        # surface a file list cannot express: `os.walk(Limelight)` sees a file that does
        # not exist yet, so a snapshot that recorded only the files read today would
        # excuse the proof on tomorrow's file. Record the root; subjects() decides how
        # wide the claim is.
        path = rel(payload[0])
        if path:
            walked.append(path)
    if event == "open":
        # The first payload item is the file *argument*, and `open` takes a file
        # descriptor as readily as a name: io.open(c2pread, 'rb') in a parent waiting
        # on a child's pipe hands this hook the integer 12. Passing it to os.path.isabs
        # raised TypeError inside the hook, and an exception raised by an audit hook
        # propagates into the audited call -- so the gate under measurement died in its
        # own subprocess.wait and the probe reported nothing at all. A descriptor names
        # no path, so it is not a read surface; skip it.
        subject = payload[0]
        if isinstance(subject, (str, bytes, os.PathLike)):
            path = rel(subject)
            if path:
                opened.append(path)
    elif event == "subprocess.Popen":
        args_ = payload[0]
        if isinstance(args_, bytes):
            args_ = args_.decode("utf-8", "replace")
        for piece in (args_ if isinstance(args_, (list, tuple)) else [args_]):
            piece = os.path.splitdrive(str(piece))[1]
            for candidate in (piece, piece.lstrip("-I")):
                if isinstance(candidate, (str, bytes, os.PathLike)):
                    path = rel(candidate)
                    if path:
                        spawned.append(path)

sys.addaudithook(hook)
sys.argv = [target] + args
# A gate run as `python scripts/<gate>.py` gets `scripts/` as sys.path[0] and imports
# its helpers from there (apple_toolchain, battery-self-proof-scope). Run through -c,
# sys.path[0] is the working directory instead, so the import fails and the gate dies
# before reading anything -- which the hook would record as a *narrow* read surface,
# the one direction that silences a proof. Put the gate's own directory first, so the
# child sees the same import environment the gate sees when CI runs it.
sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
try:
    runpy.run_path(target, run_name="__main__")
except SystemExit as exit_:
    code = exit_.code or 0
except BaseException as error:  # noqa: BLE001 - the gate's crash is the measurement
    # A gate that raises is a result, not a lost measurement. Without this the child
    # dies before writing its file, and the parent reports "no such file" -- which
    # reads like a broken probe and hides the gate's own traceback.
    import traceback
    traceback.print_exc()
    code = 1
else:
    code = 0
with open(out, "w", encoding="utf-8") as handle:
    json.dump({"code": code, "opened": sorted(set(opened)),
               "spawned": sorted(set(spawned)), "walked": sorted(set(walked))},
              handle)
'''


def measure(gate, form):
    """Run one form of one gate and return every checkout path it touched."""
    script = os.path.join(SCRIPTS, gate)
    # The measurement file goes outside the checkout. Writing it under `scripts/` made
    # the probe measure its own output: every gate reported the probe's scratch file as
    # an undeclared read surface, and that self-pollution looked like a defect in the
    # snapshot rather than in the probe.
    scratch = tempfile.mkdtemp(prefix="battery-scope-probe.")
    out = os.path.join(scratch, "measurement.json")
    try:
        child = subprocess.run([sys.executable, "-c", CHILD, ROOT, out, script] + list(form),
                               capture_output=True, text=True, cwd=ROOT, timeout=900)
        if not os.path.exists(out):
            # The child died hard enough that even its handler could not write: an
            # audit-hook bug, a signal, or an interpreter failure. Say which command
            # and show its tail, because that is the only trace there will be.
            tail = (child.stdout + child.stderr).strip().splitlines()[-8:]
            raise SystemExit("probe: %s %s wrote no measurement; child said:\n  %s"
                             % (gate, " ".join(form), "\n  ".join(tail) or "(nothing)"))
        with open(out, encoding="utf-8") as handle:
            recorded = json.load(handle)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return recorded


def subjects(files, spawned, walked=()):
    """The narrowest honest surface: files read, plus walked and include directories.

    A file the gate opened itself belongs in `files`. A directory enters `dirs` two
    ways. A walked root belongs there because the gate listed that subtree -- and it
    is a *wider* claim than the files found inside it, because `os.walk(Limelight)`
    also sees a file that does not exist yet, so a snapshot recording only today's
    files would excuse the gate's proof on tomorrow's file. A directory handed to a
    child as an include path belongs there because any file beneath it can arrive on
    a later `#include`. A directory merely named as an argument is not a claim that
    its contents were read.
    """
    kept_files = sorted({normalise(f) for f in files if not f.endswith("/")})
    dirs = {s.rstrip("/") for s in walked if os.path.isdir(os.path.join(ROOT, s))}
    dirs |= {s.rstrip("/") for s in spawned
             if s.endswith(("-I",)) or os.path.isdir(os.path.join(ROOT, s))}
    # A file under a declared directory is a duplicate claim, and duplicates age
    # badly: renaming one Swift file would fail `missing_subjects()` for a scope that
    # the directory already covers, and the repair would be to edit a snapshot that
    # never needed naming the file. Keep only the files outside every declared tree.
    kept_files = [f for f in kept_files
                  if not any(f == d or f.startswith(d.rstrip("/") + "/") for d in dirs)]
    return kept_files, sorted(dirs)


def normalise(path):
    """Fold a compiled artefact back onto the source it was built from.

    Importing a module reads `scripts/__pycache__/x.cpython-315.pyc`, and recording
    *that* would be both useless and wrong: a mutation lands in `x.py`, and the byte
    code is regenerated from it, so the read that matters is the source. Recording the
    source is also the wider claim of the two, which is the direction a read surface
    has to err in -- too wide costs seconds, too narrow silences a proof.
    """
    directory, name = os.path.split(path)
    if os.path.basename(directory) == "__pycache__" and name.endswith(".pyc"):
        source = os.path.join(os.path.dirname(directory), name.split(".")[0] + ".py")
        if os.path.isfile(os.path.join(ROOT, source)):
            return source
    return path


def covered(path, files, dirs):
    if path in files:
        return True
    return any(path == directory or path.startswith(directory.rstrip("/") + "/")
               for directory in dirs)


def excused_seconds(forms, form_seconds):
    """What the battery stops paying for one gate, from the measured form times.

    The aggregate excuses a gate's *red-proof* form: `--self-test` where a gate has a
    judgement form beside it, and the gate's only form when it has just one (that is
    `enhanced-presentation-tests.py`, whose whole run is the compiled-harness proof).
    Counting anything else would overstate the saving this file claims.
    """
    if len(forms) == 1:
        return form_seconds.get(forms[0], 0.0)
    return sum(seconds for form, seconds in form_seconds.items() if "--self-test" in form)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--gate")
    options = parser.parse_args()

    with open(SNAPSHOT, encoding="utf-8") as handle:
        document = json.load(handle)
    gates = document["gates"]

    problems = []
    total_excused = 0.0
    # A subject the repository does not have is the silent direction: the consumer
    # matches a mutation against this list, so a name that no longer exists can never
    # match, and the gate's proof is excused on mutations the snapshot was written to
    # cover. Checked before measuring, because a stale name is stale on every host and
    # costs nothing to find.
    for stale in scope.missing_subjects():
        problems.append("the snapshot names %s, which the repository does not have; "
                        "a subject that cannot exist excuses its gate's proof forever"
                        % stale)
    for gate in sorted(gates):
        if options.gate and gate != options.gate:
            continue
        entry = gates[gate]
        uncovered = []
        measured_files = set()
        measured_dirs = set()
        form_seconds = {}
        for form in entry.get("forms", [gate]):
            argv = form.split()[1:]
            started = time.time()
            recorded = measure(gate, argv)
            form_seconds[form] = round(time.time() - started, 1)
            if recorded["code"] != 0:
                # A gate that failed early read less than it would have, and a *narrow*
                # snapshot is the dangerous direction: it excuses a proof on exactly the
                # mutation it exists to catch, quietly, because the run stays green. So
                # a failed measurement is a problem in its own right, not a short list.
                problems.append("%s exited %d while being measured for the %r form; its "
                                "read surface cannot be trusted, because a gate that dies "
                                "early reports fewer reads"
                                % (gate, recorded["code"], form))
            touched = set(recorded["opened"]) | set(recorded["spawned"]) | set(recorded["walked"])
            touched.discard(os.path.relpath(SNAPSHOT, ROOT).replace(os.sep, "/"))
            touched = {normalise(path) for path in touched}
            files, directories = subjects(recorded["opened"],
                                          recorded["spawned"],
                                          recorded["walked"])
            measured_files.update(files)
            measured_dirs.update(directories)
            shipped_files = set(entry.get("files", ()))
            shipped_dirs = set(entry.get("dirs", ()))
            for path in sorted(touched):
                if not covered(path, shipped_files, shipped_dirs):
                    uncovered.append("%s [%s]" % (path, form))
        if uncovered:
            problems.append("%s reads %d path(s) its snapshot does not declare: %s"
                            % (gate, len(uncovered), ", ".join(uncovered[:6])))
        excused = excused_seconds(entry.get("forms", [gate]), form_seconds)
        total_excused += excused
        print("%-36s %d form(s), %d uncovered read(s), %ds excused per aggregate run"
              % (gate, len(entry.get("forms", [])), len(uncovered), round(excused)))
        if options.write:
            entry["files"] = sorted(measured_files)
            entry["dirs"] = sorted(measured_dirs)
            entry["seconds"] = round(excused, 1)

    if options.write:
        document["_measured_at"] = __import__("datetime").date.today().isoformat()
        document["_measured_on"] = ("%s %s, python %s, seconds per form as measured"
                                    % (platform.system(), platform.machine(),
                                       platform.python_version()))
        with open(SNAPSHOT, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print("--write rewrote %s from this measurement run" % os.path.relpath(SNAPSHOT, ROOT))
    else:
        print("a full battery run excuses about %d seconds of self-proof per aggregate "
              "call when the mutation is out of scope" % round(total_excused))
    for problem in problems:
        print("FAIL %s" % problem)
    print("battery scope probe: %d problem(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
