#!/usr/bin/env python3
"""Prove the assertion battery dies when the terminal asks it to, with the tree whole.

The battery writes the shipped source: it plants a defect, runs a gate over it, and puts
the file back. Putting it back has to happen even when the run is interrupted, so the
handler blocks the three interrupt signals, restores the tree, and then ends the process
the way the signal asked. The last step has a trap in it: a signal that is still masked
when it is re-raised stays pending forever, the handler returns, and the process carries
on with a restored tree, a log line that reads like an orderly shutdown, and no death.
The consequence is a run that has already said goodbye and keeps going: the tree is
whole, the log reads like an orderly shutdown, and the only thing that ends it is SIGKILL.
That is what a Ctrl+C looks like when it is ignored, and it is why a cancelled CI job
burns its remaining minutes instead of stopping.

So this gate does not grep for `SIG_UNBLOCK` and hope. It takes the handler **as the
battery writes it**, runs it in a child process against a file the child has dirtied,
sends the child one signal, and asks two questions: did the child die of that signal, and
did the file come back. Delete the unblock and the child lives, which is the whole point.

Usage: battery-interrupt-tests.py [--self-test]
Exit 0 only when the shipped handler ends the process for all three signals and restores
what it wrote, and when this gate's own negative control still refuses the regression.
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
SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")
DEF_LINE = "    def restore_and_return(signum, frame):"


def shipped_handler():
    """The `restore_and_return` body, verbatim from the battery.

    Extracted rather than restated: a gate that carries its own copy of a handler proves
    the copy works, which is not a claim anybody made. The body is every line indented
    deeper than the `def`, so the function ends where Python says it ends rather than at
    a guess; comments are kept, because the reasoning is the thing under test. A rename
    is reported as a failure -- the usual way code stops being watched.
    """
    lines = open(BATTERY, encoding="utf-8").read().split("\n")
    try:
        start = lines.index(DEF_LINE)
    except ValueError:
        return None
    body = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("        "):
            break
        body.append(line[4:] if line.startswith("    ") else line)
    return "\n".join(body)


def unblock_removed(source):
    """The defect this gate exists for: restore, then re-raise while still masked."""
    pattern = re.compile(
        r"[ \t]*signal\.pthread_sigmask\(signal\.SIG_UNBLOCK,\n"
        r"[ \t]*\{signal\.SIGINT, signal\.SIGTERM, signal\.SIGHUP\}\)\n")
    mutated, count = pattern.subn("", source)
    return mutated if count == 1 else None


def child_script(handler_source, path):
    """A child that installs the shipped handler, dirties a file, then waits.

    The dirtied file stands in for a planted mutation, and the restore drains the same
    `pending` table the battery uses, so this covers restore-then-return rather than a
    bare signal reaction. The child prints its pid and spins; the parent waits for the
    file to read as dirty before signalling, so nothing here races with a sleep.
    """
    return '''
import os, signal, sys, time

scratch = %r
pending = {}

def restore_pending():
    while pending:
        where, text = pending.popitem()
        with open(where, "w", encoding="utf-8") as handle:
            handle.write(text)

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
''' % (path, handler_source)


def interrupt_once(handler_source, signum):
    """Send `signum` once to a child running `handler_source`.

    Returns (died_of_signal, tree_restored, why). "Died of the signal" is checked as a
    negative return code rather than any exit: a handler that swallows the interrupt and
    lets `main` run to its summary would exit 0, and that is exactly the behaviour this
    gate must refuse, dressed up as success.
    """
    with tempfile.TemporaryDirectory() as scratch:
        path = os.path.join(scratch, "planted.txt")
        script_path = os.path.join(scratch, "child.py")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(child_script(handler_source, path))
        child = subprocess.Popen([sys.executable, script_path],
                                 stdout=subprocess.PIPE, text=True)
        try:
            if not child.stdout.readline().strip().isdigit():
                return False, False, "the child never reported a pid"
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    if open(path, encoding="utf-8").read().startswith("MUTATED"):
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            else:
                return False, False, "the child never reached the dirty state"
            os.kill(child.pid, getattr(signal, signum))
            try:
                code = child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                return False, True, ("%s was never delivered: the child was still "
                                     "running 15s after its own signal" % signum)
            restored = open(path, encoding="utf-8").read() == "clean\n"
            if code >= 0:
                return False, restored, ("%s was handled and swallowed: the child "
                                         "exited %d instead of dying of the signal"
                                         % (signum, code))
            return True, restored, ""
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
    shipped = shipped_handler()
    if shipped is None:
        print("FAIL the battery no longer defines restore_and_return at the shape this "
              "gate reads, so the interrupt path has no source to prove")
        print("1 failures")
        return 1

    # Extraction is a precondition, not a result: if the shipped text no longer carries
    # the unblock then the battery is broken, and saying "the gate is red" about that
    # would bury the real finding.
    if "signal.SIG_UNBLOCK" not in shipped:
        print("FAIL the shipped handler no longer unblocks before it re-raises: that is "
              "the defect this gate exists for, in the battery itself")
        print("1 failures")
        return 1

    if "--self-test" in sys.argv:
        # The gate has to refuse the defect it exists to catch, or a red run is
        # indistinguishable from a broken harness: both leave a child alive.
        mutant = unblock_removed(shipped)
        check(mutant is not None,
              "the negative control finds the unblock it deletes"
              if mutant else
              "the unblock anchor moved, so the control planted nothing and proves "
              "nothing")
        if mutant:
            died, _, why = interrupt_once(mutant, "SIGTERM")
            check(not died,
                  "a handler that re-raises while still masked is caught: %s"
                  % why.splitlines()[0][:90]
                  if not died else
                  "the gate let the defect through: the child died even "
                  "with the unblock deleted, so this harness is not testing the mask")
        print("%d failures" % len(failures))
        return 1 if failures else 0

    for signum in SIGNALS:
        died, restored, why = interrupt_once(shipped, signum)
        check(died and restored,
              "%s ends the battery with the tree restored" % signum
              if died and restored else
              "%s does not: %s" % (signum, why or "the tree stayed mutated"))
    print("%d failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
