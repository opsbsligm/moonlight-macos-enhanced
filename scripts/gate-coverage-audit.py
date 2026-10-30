#!/usr/bin/env python3
"""Reconcile the gate list across both CI definitions, because two lists drift.

The repository carries two pipeline definitions: `.gitlab-ci.yml` is the source of
truth and `.github/workflows/build.yml` is the read-only image GitHub sees. Gates get
written for the mirror first -- it is the file a new gate has ever been added to -- and
the source of truth then runs a subset. The measured state at the point this audit was
written: the mirror called 87 repository gates, the source of truth called 33, and the
54 that sat only on the mirror were still reported as passing by `local-gates.sh`,
because that script builds its list from the mirror. A local sweep could therefore be
green on gates the authority never ran, which is the pairing `local-gates.sh` says it
exists to prevent, pointed the other way.

The rule this audit enforces: every gate the mirror calls must be reachable on the
source of truth, either written out in `.gitlab-ci.yml` or emitted at run time by this
script from a job that asks for its class. A gate can leave the fast set only by being
listed in NON_FAST with a reason, and a stale entry there is itself a violation --
an excuse that no longer names a real gate is how a gate stops being looked at.

Only regular expressions are used, on purpose: PyYAML is not installed on a bare
checkout, and an audit that cannot run without a venv is an audit that does not run.

What this audit does not see: a job that asks for a class and throws the answer away.
It reads the definition as text, so it can tell a class some job asks for from a class
nothing asks for, but not whether the emitted commands reach a shell. The rule is
written down rather than left implied because the alternative -- a stricter reader --
is what made this audit go unrunnable on the checkout that needed it.

Usage:
  gate-coverage-audit.py [--verify] [--json] [--quiet]
  gate-coverage-audit.py --emit-commands --class=fast|selftest|deep
  gate-coverage-audit.py --self-test
Exit 0 only when every mirrored gate is reachable on the source of truth.
"""
import argparse
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_OF_TRUTH = ".gitlab-ci.yml"
MIRROR = os.path.join(".github", "workflows", "build.yml")
SELF = os.path.join("scripts", os.path.basename(__file__))

# `scripts/x.py` but not `.github/scripts/x.py`: the mirror also calls one helper that
# lives beside the workflow, and counting it as a repository gate made the sets disagree
# by one for no reason a reader could check.
GATE_REF = re.compile(r"(?<![\w./-])scripts/([A-Za-z0-9_.+-]+\.py)")

EMIT_CLASSES = ("fast", "selftest", "deep")

# Gates that cannot sit in the fast set, with why. Three shapes:
#   selftest -- its full form needs an artefact or a CI-computed value, but a real
#              self-test runs anywhere, so the emitted command is that self-test;
#   deep     -- it builds or compiles something, so it belongs on the tag/main deep pass
#              rather than in front of every merge request.
# `full_form` says where the complete check happens, and is required for `selftest`:
# without it the entry would hide a coverage gap instead of recording one.
NON_FAST = {
    "analyzer-audit.py": {
        "class": "selftest",
        "self_test": "--self-test",
        "reason": "its full form reads an analyze-configuration build transcript "
                  "($RUNNER_TEMP/analyze.log on the mirror); the source of truth builds "
                  "one Release configuration, so the transcript-shaped rule is not the "
                  "same claim",
        "full_form": "uncovered on the source of truth: no analyze-configuration build "
                     "exists there, and the release path's warnings are covered by "
                     "build-warning-audit.py, which is wired to build.log",
    },
    "launch-code-audit.py": {
        "class": "selftest",
        "self_test": "--self-test",
        "reason": "its full form reads a built .app bundle",
        "full_form": "uncovered on the source of truth: the bundle-level identity report "
                     "is a release-time claim about the shipped image",
    },
    "release-gate.py": {
        "class": "selftest",
        "self_test": "--self-test",
        "reason": "its full form wants a tag name, which a branch pipeline does not have",
        "full_form": "uncovered on the source of truth: releases are cut from the mirror, "
                     "and no GitLab release job exists",
    },
    "swift-typecheck.py": {
        "class": "selftest",
        "self_test": "--self-test",
        "reason": "its full form names the DerivedSources root of a build that has "
                  "happened, and that path differs per configuration",
        "full_form": "runnable locally -- local-gates.sh resolves the generated-header "
                     "root from whatever configuration this checkout last built, so the "
                     "full form runs there and not in CI",
    },
    "render-probe.py": {
        "class": "deep",
        "reason": "it builds its own Debug product and measures the page inside the app; "
                  "about twenty minutes from cold, sixty seconds once that build is warm",
    },
    "scaling-output-evidence-tests.py": {
        "class": "deep",
        "reason": "it compiles and runs C probes against the SDK, measured at 126 seconds "
                  "on the machine that wrote this",
    },
}


def referenced(relative):
    """Every `scripts/*.py` a pipeline definition calls."""
    path = os.path.join(ROOT, relative)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        raise SystemExit("gate-coverage-audit: cannot read %s" % relative)
    return referenced_text(text)


def referenced_text(text):
    """Every `scripts/*.py` a pipeline definition actually runs, comments excluded.

    `asked_classes` already refuses to read a class out of a remark, for the reason
    spelled out there: an explanation of a rule is not a consumer of it. The gate names
    themselves were read from raw text all the same, so a job that deleted its audit step
    and kept the paragraph naming that step stayed "covered on the source of truth" -- the
    silence rewritten as prose, which is the exact shape this audit exists to refuse. A
    package step that describes a check is now worth the same as one that runs it: nothing.
    """
    return set(GATE_REF.findall("\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#"))))


def asked_classes(source_text):
    """Which gate classes the source of truth asks for at run time.

    A mention in a comment is not a consumer. The first version of this function asked
    whether the string `--class=fast` appeared anywhere, so a header comment explaining
    the classes made every mirror-only gate look covered, and the audit that exists to
    end a silence reintroduced one. Only a line that also names an interpreter counts,
    because the definitions spell their gate calls that way -- and a line beginning with
    `#` is the shape of an explanation, not of a job step.
    """
    asked = set()
    for line in source_text.splitlines():
        if line.strip().startswith("#"):
            continue
        if not re.search(r"\bpython3?\b", line):
            continue
        asked.update(re.findall(r"--class=([A-Za-z]+)", line))
    return asked


def klass(name):
    entry = NON_FAST.get(name)
    return entry["class"] if entry else "fast"


def emitted_command(name):
    entry = NON_FAST.get(name)
    if entry and entry["class"] == "selftest":
        return "python3 scripts/%s %s" % (name, entry["self_test"])
    return "python3 scripts/%s" % name


def reconcile(source_text=None, mirror_text=None):
    """Compare the two definitions. Returns (violations, notes, covered)."""
    source_text = source_text if source_text is not None else read(SOURCE_OF_TRUTH)
    mirror_text = mirror_text if mirror_text is not None else read(MIRROR)
    truth = referenced_text(source_text)
    mirror = referenced_text(mirror_text)
    violations, notes, covered = [], [], set()

    for name in sorted(mirror):
        if name in truth:
            covered.add(name)
            continue
        gate_class = klass(name)
        if gate_class not in EMIT_CLASSES:
            violations.append(("HC002", name,
                               "listed as class %r, which is not an emittable class"
                               % gate_class))
            continue
        if gate_class in ("selftest", "deep"):
            entry = NON_FAST[name]
            if not entry.get("reason", "").strip():
                violations.append(("HC003", name,
                                   "listed as %s with no reason" % gate_class))
                continue
            if gate_class == "selftest" and not entry.get("full_form", "").strip():
                violations.append(("HC003", name,
                                   "self-test form substituted without recording where "
                                   "the full form runs"))
                continue
        if gate_class not in asked_classes(source_text):
            violations.append(("HC001", name,
                               "the mirror calls it, the source of truth neither calls it "
                               "nor emits class %r" % gate_class))
            continue
        covered.add(name)
        if gate_class == "selftest":
            notes.append("%s: runs as `%s` on the source of truth; %s"
                         % (name, NON_FAST[name]["self_test"], NON_FAST[name]["full_form"]))
        elif gate_class == "deep":
            notes.append("%s: deep pass only (tag and main), so a merge-request pipeline "
                         "does not cover it" % name)

    for name in sorted(truth - mirror):
        # A gate that only the source of truth calls is allowed -- the authority may add
        # a guard the image has not caught up with -- but it has to be said out loud,
        # because the mirror's pipeline is what a contributor sees going green.
        notes.append("%s: source-of-truth only; the mirror does not run it" % name)

    for name in sorted(set(NON_FAST) - mirror - truth):
        violations.append(("HC004", name,
                           "listed as NON_FAST but no pipeline definition calls it: the "
                           "excuse outlived the gate"))
    return violations, notes, covered


def read(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def names_for(truth_names, mirror_names, class_name):
    """The mirrored-only gates of one class, without touching the working tree."""
    return [n for n in sorted(mirror_names - truth_names) if klass(n) == class_name]


def emit(class_name):
    for name in names_for(referenced(SOURCE_OF_TRUTH), referenced(MIRROR), class_name):
        print(emitted_command(name))
    return 0


# A pair of definitions written for the self-test. The mutation checks below need a state
# that is known to be clean, and reusing the shipped files meant the self-test could only
# run once the repository was already compliant: the tool that measures the gap could not
# be tested while the gap existed. Worse, with a real violation already present, an
# assertion of the shape "did HC001 appear?" passes whether or not the mutation did
# anything, which is how a self-test keeps saying ok while testing nothing.
SAMPLE_TRUTH = """
gate_fast:
  - python3 scripts/gate-coverage-audit.py --emit-commands --class=fast
gate_selftest:
  - python3 scripts/gate-coverage-audit.py --emit-commands --class=selftest
gate_deep:
  - python3 scripts/gate-coverage-audit.py --emit-commands --class=deep
gate_shared:
  - python3 scripts/shared-tests.py
"""
# Every NON_FAST gate appears here, because HC004 exists to catch an excuse that names
# no gate -- a sample that omitted one would report the real rule as a baseline defect.
SAMPLE_MIRROR = """
steps:
  - run: python3 scripts/shared-tests.py
  - run: python3 scripts/fast-only-tests.py
  - run: python3 scripts/analyzer-audit.py --log "$RUNNER_TEMP/analyze.log"
  - run: python3 scripts/dmg-audit.py --self-test-checksums
  - run: python3 scripts/launch-code-audit.py --app "$app"
  - run: python3 scripts/release-gate.py --tag "$CI_COMMIT_TAG"
  - run: python3 scripts/swift-typecheck.py --derived "$DERIVED_DATA_PATH"
  - run: python3 scripts/render-probe.py
  - run: python3 scripts/scaling-output-evidence-tests.py
"""


def self_test():
    """Each rule has to refuse something, or it is not a rule.

    The four shapes below are the ways this reconciliation goes wrong on its own: a gate
    that appears on one side only, a job that stopped asking for a class it used to
    emit, an excuse that outlived its gate, and an artefact-shaped gate quietly filed
    as fast because that is the class with no paperwork. Whether the shipped definitions
    are compliant is `--verify`'s question, not this one.
    """
    truth, mirror = SAMPLE_TRUTH, SAMPLE_MIRROR
    baseline, _, _ = reconcile(truth, mirror)
    if baseline:
        print("self-test failed: the sample definitions are not a clean baseline: %s"
              % "; ".join("%s %s" % (code, name) for code, name, _ in baseline),
              file=sys.stderr)
        return 1
    probe = "probe-tests.py"

    # 1. A gate called only by the mirror, with nothing on the source of truth asking
    #    for its class, has to be reported. This is the defect the audit exists for.
    mutated = truth.replace("--class=fast", "--class=unused", 1)
    if not any(c == "HC001" for c, _, _ in reconcile(mutated, mirror)[0]):
        print("self-test failed: a class nobody emits still passed", file=sys.stderr)
        return 1

    # 2. A gate the source of truth writes out by name is covered even when the mirror
    #    calls it too; a source of truth that calls nothing must not be.
    if probe in truth:
        print("self-test failed: the probe gate is already on the source of truth",
              file=sys.stderr)
        return 1
    widened = truth + "  - python3 scripts/%s\n" % probe
    widened_mirror = mirror + "  - run: python3 scripts/%s\n" % probe
    if any(c == "HC001" for c, _, _ in reconcile(widened, widened_mirror)[0]):
        print("self-test failed: writing a gate out on the source of truth was refused",
              file=sys.stderr)
        return 1
    if not any(c == "HC001" for c, _, _ in reconcile("", mirror)[0]):
        print("self-test failed: an empty source of truth still passed", file=sys.stderr)
        return 1

    # 3. An excuse that names no gate.
    stale = dict(NON_FAST)
    stale["gone-tests.py"] = {"class": "selftest", "self_test": "--self-test",
                              "reason": "gone", "full_form": "gone"}
    saved = dict(NON_FAST)
    NON_FAST.clear()
    NON_FAST.update(stale)
    try:
        codes = {c for c, _, _ in reconcile(truth, mirror)[0]}
    finally:
        NON_FAST.clear()
        NON_FAST.update(saved)
    if "HC004" not in codes:
        print("self-test failed: a stale NON_FAST entry still passed", file=sys.stderr)
        return 1

    # 4. An artefact-shaped gate filed as fast: it would be emitted bare, and a gate
    #    handed no artefact reports a failure the tree does not have.
    target = "analyzer-audit.py"
    saved_entry = NON_FAST[target]
    NON_FAST[target] = {"class": "fast", "reason": saved_entry["reason"]}
    try:
        fast_also = target in names_for(set(GATE_REF.findall(truth)),
                                        set(GATE_REF.findall(mirror)), "fast")
    finally:
        NON_FAST[target] = saved_entry
    if not fast_also:
        print("self-test failed: an artefact gate filed as fast was not emitted, so the "
              "class rule has nothing to catch", file=sys.stderr)
        return 1
    if not any(c in ("HC001", "HC003") for c, _, _ in reconcile(
            truth.replace("--class=selftest", "--class=unused"), mirror)[0]):
        print("self-test failed: dropping the self-test class hid the gates that need it",
              file=sys.stderr)
        return 1

    # 5. A call that survives only as a remark. `release-gate.py` sits in NON_FAST, so a
    #    definition that no longer runs it has to be told it keeps an excuse for a gate it
    #    dropped (HC004) -- but only if a comment is not read as a call. Delete the
    #    filtering and the dropped gate stays "referenced", the excuse stays unchallenged,
    #    and the coverage gap reads as prose.
    dropped_mirror = "\n".join(line for line in mirror.splitlines()
                               if "release-gate.py" not in line)
    commented_truth = truth + "\n#  - python3 scripts/release-gate.py --tag \"$CI_COMMIT_TAG\"\n"
    if any(c == "HC004" for c, _, _ in reconcile(truth, mirror)[0]):
        print("self-test failed: the shipped sample already reports a stale excuse, so "
              "the mutation below proves nothing", file=sys.stderr)
        return 1
    if not any(c == "HC004" and n == "release-gate.py"
               for c, n, _ in reconcile(commented_truth, dropped_mirror)[0]):
        print("self-test failed: a definition whose only mention of a gate is a comment "
              "still counted as running it", file=sys.stderr)
        return 1

    print("self-test ok: one-sided gates, unemitted classes, stale excuses and "
          "misfiled artefact gates are all refused, and a remark is not a call")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="the default action")
    parser.add_argument("--emit-commands", action="store_true",
                        help="print the commands a job should run for one class")
    parser.add_argument("--class", dest="klass_name", default="fast",
                        choices=EMIT_CLASSES)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.emit_commands:
        return emit(args.klass_name)

    violations, notes, covered = reconcile()
    if args.json:
        print(json.dumps({
            "source_of_truth": SOURCE_OF_TRUTH,
            "mirror": MIRROR,
            "source_truth_gates": len(referenced(SOURCE_OF_TRUTH)),
            "mirror_gates": len(referenced(MIRROR)),
            "reachable_on_source_of_truth": len(covered),
            "violations": [{"code": c, "gate": n, "detail": d}
                           for c, n, d in violations],
            "notes": notes,
        }, indent=2))
    else:
        if not args.quiet:
            print("source of truth calls %d gates, the mirror calls %d, %d are reachable"
                  % (len(referenced(SOURCE_OF_TRUTH)), len(referenced(MIRROR)),
                     len(covered)))
            for note in notes:
                print("note  %s" % note)
    for code, name, detail in violations:
        print("%s %s: %s" % (code, name, detail), file=sys.stderr)
    if violations and not args.quiet:
        print("fix: call the gate in %s, or give the job that emits its class "
              "(--class=%s); a gate may leave the fast set only through NON_FAST, with a "
              "reason" % (SOURCE_OF_TRUTH, "|".join(EMIT_CLASSES)), file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
