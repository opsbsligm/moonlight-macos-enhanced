#!/usr/bin/env python3
"""Prove the battery says what it cost even when the job is killed part way through.

The assertion battery writes the shipped source, judges the defect, and puts the file
back. The ceiling question for its `mutation-battery` job turns on one number -- how
long a whole run takes -- and a run that overran its timeout used to leave only the
per-case `TIME` rows, so nobody could say how far over it went. The fix is to report
the total from the same path that restores the tree, because that handler re-raises
with the default disposition: the process dies there and `atexit` never runs. A total
printed after the loop is a total a long run cannot reach.

So this gate does not grep for a call and hope. It takes the real `report_cost` and the
real `restore_pending` out of the battery, runs them in a child that has dirtied a file
the way a planted mutation does, sends the child a signal, and asks three questions:
did the child die of that signal, did the file come back, and did the child's own
stdout carry a total before it died. Delete the call from the restore path and the
child dies quietly, which is the regression this gate exists to refuse.

Usage: battery-cost-report-tests.py [--self-test]
Exit 0 only when the shipped restore path reports the cost and this gate's own negative
control still refuses the version that stays quiet.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATTERY = os.path.join(ROOT, "scripts", "assertion-battery.py")
RESTORE_DEF = "    def restore_pending(report=True):"
COST_DEF = "def report_cost():"
HANDLER_DEF = "    def restore_and_return(signum, frame):"
TOTAL_MARKER = "COST    "


def _indented_body(lines, start):
    """Every line after `start` indented deeper than the def, dedented by the def's own
    indent so the body lands at one level in the child.

    The amount comes from the `def` line rather than from a constant because this file
    reads one nested and one top-level function: the nested one needs four spaces
    removed and the top-level one needs none, and a single constant would silently
    flatten the docstring of one of them into an IndentationError.
    """
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line[indent:])
    return "\n".join(body)


def shipped_source():
    return open(BATTERY, encoding="utf-8").read().split("\n")


def shipped_function(name, first_line):
    """One top-level or nested function's body, verbatim from the battery.

    Extracted rather than restated: a gate carrying its own copy of a function proves
    the copy works, which is not a claim anybody made about the battery.
    """
    lines = shipped_source()
    try:
        start = lines.index(first_line)
    except ValueError:
        return None
    return _indented_body(lines, start)


def restore_without_report(source):
    """The defect: the restore puts the tree back and never says what the run cost."""
    # The whole guard goes with the call. Deleting only the call would leave an empty
    # `if` block, which is a syntax error rather than a silent restore, and the child
    # would die on import instead of on the behaviour -- the gate would then pass for
    # the wrong reason (no output at all) instead of the right one (a restore that says
    # nothing).
    mutated, count = re.subn(r"[ \t]*if report:\n[ \t]*report_cost\(\)\n",
                             "", source, count=1)
    return mutated if count == 1 else None


def child_script(handler_source, restore_source, cost_source, path):
    """A child that installs the shipped handler and restore path, then waits.

    The handler is injected as well as the restore, because the default disposition for
    SIGTERM kills the process where it stands and nothing would run -- the child would
    report itself dead with the tree still dirty, and this gate would read a working
    battery as a broken one. The stubs above the injected bodies are the module state
    `report_cost` reads; they stand in for the real tallies, because the thing under
    test is which path prints a total, not what the numbers are.
    """
    return '''
import os, signal, sys, time

scratch = %r
pending = {}
RUN_STARTED = time.monotonic()
AGGREGATE_SECONDS = [1.0, 2.0]
LIGHT_SECONDS = [0.5]
UNAPPLIED_NAMES = []
SELF_PROOFS_EXCUSED = 7
COST_REPORTED = False
MUTATIONS = [None] * 5

def report_cost():
%s

def restore_pending(report=True):
%s

def restore_and_return(signum, frame):
%s

for _name in ("SIGINT", "SIGTERM", "SIGHUP"):
    signal.signal(getattr(signal, _name), restore_and_return)

with open(scratch, "w", encoding="utf-8") as handle:
    handle.write("clean\\n")
pending[scratch] = "clean\\n"
with open(scratch, "w", encoding="utf-8") as handle:
    handle.write("MUTATED\\n")
print(os.getpid(), flush=True)
while True:
    time.sleep(0.05)
''' % (path, cost_source.rstrip("\n"), restore_source.rstrip("\n"),
       handler_source.rstrip("\n"))


def interrupt_once(handler_source, restore_source, cost_source, signum):
    """Send one signal to a child running the shipped restore path.

    Returns (died_of_signal, restored, printed_total, why). Dying of the signal is a
    negative return code, not any exit: a child that restored, printed, and then walked
    on alive is the failure the sibling interrupt gate already refuses, and here it would
    also fake a clean summary the job never earned.
    """
    with tempfile.TemporaryDirectory() as scratch:
        path = os.path.join(scratch, "planted.txt")
        script_path = os.path.join(scratch, "child.py")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(child_script(handler_source, restore_source, cost_source, path))
        child = subprocess.Popen([sys.executable, script_path],
                                 stdout=subprocess.PIPE, text=True)
        try:
            if not child.stdout.readline().strip().isdigit():
                return False, False, False, "the child never reported a pid"
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    if open(path, encoding="utf-8").read().startswith("MUTATED"):
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            else:
                return False, False, False, "the child never reached the dirty state"
            os.kill(child.pid, getattr(signal, signum))
            # The output has to be read while the child dies; a pipe nobody drains can
            # keep a blocked writer alive, and then a quiet run and a stuck one look
            # the same from here.
            output = []
            try:
                code = child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                return False, True, False, ("%s was never delivered: the child was "
                                            "still running 15s after its signal" % signum)
            for line in child.stdout:
                output.append(line)
            restored = open(path, encoding="utf-8").read() == "clean\n"
            printed = any(TOTAL_MARKER in line for line in output)
            if code >= 0:
                return False, restored, printed, ("%s was handled and swallowed: the "
                                                  "child exited %d" % (signum, code))
            return True, restored, printed, ""
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def main():
    restore = shipped_function("restore_pending", RESTORE_DEF)
    cost = shipped_function("report_cost", COST_DEF)
    handler = shipped_function("restore_and_return", HANDLER_DEF)
    if restore is None or cost is None or handler is None:
        print("FAIL the battery no longer defines %s at the shape this gate reads, so "
              "the cost report has no source to prove"
              % ("restore_pending" if restore is None else
                 "report_cost" if cost is None else "restore_and_return"))
        print("1 failures")
        return 1

    # Extraction is a precondition, not a result: if the shipped restore path already
    # lost its call then the battery is broken, and reporting a red gate about the gate
    # would bury the finding.
    if "report_cost()" not in restore:
        print("FAIL the shipped restore path no longer reports the cost: that is the "
              "defect this gate exists for, in the battery itself")
        print("1 failures")
        return 1

    if "--self-test" in sys.argv:
        mutant = restore_without_report(restore)
        check(mutant is not None,
              "the negative control finds the call it deletes" if mutant else
              "the restore-path call moved, so the control planted nothing and proves "
              "nothing")
        if mutant:
            died, _, printed, why = interrupt_once(handler, mutant, cost, "SIGTERM")
            check(died and not printed,
                  "a restore that puts the tree back quietly is caught"
                  if died and not printed else
                  "the gate let the defect through: the child still printed a total "
                  "(died=%s) so the total does not come from the restore path" % died)
        print("%d failures" % len(failures))
        return 1 if failures else 0

    died, restored, printed, why = interrupt_once(handler, restore, cost, "SIGTERM")
    check(died and restored and printed,
          "SIGTERM leaves the tree restored and prints the run's cost"
          if died and restored and printed else
          "SIGTERM gave died=%s restored=%s cost printed=%s: %s"
          % (died, restored, printed, why or "the report never appeared"))
    print("%d failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
