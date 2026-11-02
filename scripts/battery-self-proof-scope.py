"""Which self-proof a gate owes a mutation that was planted somewhere else.

The assertion battery judges a planted mutation by running a gate over the mutated
tree. Thirty of its cases ask the aggregate auditor (`constraints-audit.py`), and
the aggregate answers by running every gate it drives -- including four gates whose
red proofs re-derive their own verdict from a fixture or from a compiled harness:

    defaults-consistency.py --self-test        35.4s
    enhanced-presentation-tests.py             30.0s
    battery-interrupt-tests.py --self-test     15.1s
    hardware-acceptance-check.py --self-test    3.5s

Eighty-four seconds of the aggregate's measured 104 seconds. Multiplied by the
mutations that go through it, pipeline 1053 spent 10537 of its 10801 seconds there
and was killed by its own timeout -- and the answer each of those four returned was
the same answer it returns on a clean tree, because the line the battery moved does
not sit in anything they read.

So the question this file answers is narrow: does the proof still prove something
about the file that was just changed? A red proof that re-runs unchanged is not
evidence about the mutation; it is the same evidence, bought twice. The judgement
form -- the half that actually reads the tree -- always runs, because that half can
see the mutation. And outside the battery nothing is skipped at all: no marker is in
the environment, so a push, a merge request, and a developer's `local-gates.sh` each
still run every red proof, which is where these four gates are covered anyway (the
`audit:python` job runs all four on every push).

The subject lists below are the honest scope of each gate: the files it opens. A
subject that does not exist is a bug in this file, not an excuse -- see
`scripts/battery-self-proof-scope-tests.py`, which refuses a list naming a file that
is not in the repository, because a typo there would silence a proof permanently and
silently.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Set by the battery for the duration of one judged mutation, to the repository-
# relative path it just rewrote. Deliberately absent everywhere else.
MUTATED_ENVIRONMENT_VARIABLE = "ML_MUTATED_FILE"

STREAM = os.path.join("Limelight", "Stream")
VIEW_CONTROLLERS = os.path.join("Limelight", "macOS", "ViewControllers")

# gate script -> the files that gate reads. A mutation outside this set cannot
# change what the gate says about the tree, so its self-proof adds cost and no
# verdict. Paths are repository-relative and must exist.
SUBJECTS = {
    # Compiles the three shipping C policy headers and replays ordering against them.
    "enhanced-presentation-tests.py": [
        os.path.join(STREAM, "EnhancedPresentationPolicy.h"),
        os.path.join(STREAM, "EnhancementProcessingPolicy.h"),
        os.path.join(STREAM, "ActualPresentationMetrics.h"),
    ],
    # Evaluates each absent-key fallback in the settings layers against the stream side.
    "defaults-consistency.py": [
        os.path.join(VIEW_CONTROLLERS, "SettingsObjCBridge.swift"),
        os.path.join(VIEW_CONTROLLERS, "SettingsModel+Persistence.swift"),
        os.path.join(VIEW_CONTROLLERS, "SettingsModel+DerivedValues.swift"),
        os.path.join(VIEW_CONTROLLERS, "SettingsStore.swift"),
        os.path.join(VIEW_CONTROLLERS, "SettingsModel.swift"),
        os.path.join(VIEW_CONTROLLERS, "StreamViewController.m"),
    ],
    # Runs the battery's own signal handler, extracted from the battery's text.
    "battery-interrupt-tests.py": [
        os.path.join("scripts", "assertion-battery.py"),
    ],
    # Grades acceptance rows out of an exported report; its red proofs move fixtures,
    # and it opens no shipping source at all. It judges itself, so it reads itself.
    "hardware-acceptance-check.py": [
        os.path.join("scripts", "hardware-acceptance-check.py"),
    ],
}


def mutated_file(environ=None):
    """The repository-relative file the battery rewrote, or None outside the battery."""
    source = os.environ if environ is None else environ
    raw = source.get(MUTATED_ENVIRONMENT_VARIABLE, "").strip()
    if not raw:
        return None
    absolute = raw if os.path.isabs(raw) else os.path.join(ROOT, raw)
    try:
        return os.path.relpath(os.path.realpath(absolute), os.path.realpath(ROOT))
    except ValueError:
        # Off-volume on a platform that has volumes; not a file this repository owns.
        return None


def self_proof_is_about(script, mutated=None):
    """Whether this mutation reaches anything `script` reads.

    True is the answer that costs time and earns it. Outside the battery -- no
    marker, no mutation -- it is always True, so nothing is skipped on a push.
    """
    if mutated is None:
        mutated = mutated_file()
    if mutated is None:
        return True
    subjects = SUBJECTS.get(os.path.basename(script))
    if subjects is None:
        # A gate with no recorded scope keeps its proof. Unknown is not the same as
        # irrelevant, and guessing wrong here would silence a guard.
        return True
    normalised = mutated.replace(os.sep, os.path.sep)
    return any(normalised == s.replace(os.sep, os.path.sep) for s in subjects)


def missing_subjects():
    """Scope entries that name a file the repository does not have."""
    return ["%s -> %s" % (gate, subject) for gate, subjects in SUBJECTS.items()
            for subject in subjects
            if not os.path.isfile(os.path.join(ROOT, subject))]
