#!/usr/bin/env python3
"""Turn the release gate's refusal into a command that clears it.

release-gate.py refuses a tag whose CHANGELOG section is missing, which is the
right rule: the section has to name the exact build the binaries carry. It was
still a manual scramble at release time, and a hand-edited heading is exactly the
kind of step that gets the tag and the built version out of step.

BUILD_NUMBER is git rev-list --count HEAD, so the tag for this commit is
derivable from the commit itself. This script computes that tag, asks the gate
what it objects to, and with --apply promotes the Unreleased section to the
version the gate will accept.

The promotion is what makes the next step a trap, so the script names it instead
of leaving it to be discovered in front of a release: the edit belongs in the
commit that is already HEAD. A normal commit is itself a commit, so it raises the
count by one, the gate then asks for a section naming a build one higher, --apply
writes that one too, and the tag stays one commit away forever. `git commit
--amend` replaces HEAD, so the count does not move and the section stays correct.
"the gate accepts it" is only ever a statement about the working tree in front of
you, which is why every report that clears a promotion says how to commit it.

  prepare-release.py                 report the tag this commit builds and what
                                     still stands between it and a release
  prepare-release.py --apply         promote the Unreleased section for that tag
  prepare-release.py --self-test     run the fixtures
"""
import argparse, contextlib, importlib.util, io, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNRELEASED = "## [Unreleased]"

# The shape the repository audit requires of a released section: the version heading
# with its date. It is spelled here as the one string scripts/constraints-audit.py
# matches released headings with, and the self-test refuses a change that makes the two
# texts differ. The reason to bind them is a promotion that wrote `## [version]` with no
# date at all: the release tool reported the gate accepting the tag, the changelog audit
# then answered "a released section lost its date", and the tree went red on the day it
# had to ship. Writing the heading the audit accepts is the only report that is worth
# making, so the constant is also the last thing promote() checks before it writes.
RELEASED_HEADING = r"^## \[[\w.\-]+\] - \d{4}-\d{2}-\d{2}$"


def load_gate():
    path = os.path.join(ROOT, "scripts", "release-gate.py")
    spec = importlib.util.spec_from_file_location("release_gate", path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True).stdout


def build_number(repo=ROOT):
    """Ask the one script that owns BUILD_NUMBER, never re-derive it here.

    Counting commits a second way is how a release tool and CI disagree about
    what a commit is called: build-number.sh refuses a shallow clone, a plain
    rev-list silently returns the size of the shallow window instead.
    """
    out = subprocess.run(["sh", os.path.join(repo, "Limelight", "build-number.sh"), "--print"],
                         cwd=repo, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("build-number.sh refused to name the build: %s"
                         % (out.stderr.strip() or out.stdout.strip() or "exit %d" % out.returncode))
    value = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    if not value.isdigit():
        raise SystemExit("build-number.sh --print did not print a number: %r" % out.stdout)
    return int(value)


def commit_date(repo=ROOT):
    """Name the date of the commit this release describes, not the day the tool ran.

    Every released section in this changelog carries the date of the commit its tag
    points at, which is a fact about the tree rather than about the moment somebody
    prepared the release: a promotion made the evening before a release, or the morning
    after an amend, would otherwise print the wrong day and the audit's date-order rule
    would not notice. A tree that cannot name HEAD's date gets an error, because a
    guessed date is the same class of mistake as no date at all.
    """
    out = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short", "HEAD"],
                         cwd=repo, capture_output=True, text=True)
    value = out.stdout.strip()
    if out.returncode != 0 or re.match(r"^\d{4}-\d{2}-\d{2}$", value) is None:
        raise SystemExit("cannot name the date of HEAD for the release section: %s"
                         % (out.stderr.strip() or "git log did not print a short date"))
    return value


def promote(text, version, date):
    """Give the Unreleased section the release's version and open a new one.

    The promoted heading carries the release date, because that is the shape every
    other released section has and the shape the changelog audit insists on. Returns
    None when the version already has its own section, because there is
    nothing to do and silently editing a second time would move a released entry.
    """
    gate = load_gate()
    if gate.changelog_has(text, version):
        return None
    if text.count(UNRELEASED) != 1:
        raise SystemExit("expected exactly one %s heading, found %d"
                         % (UNRELEASED, text.count(UNRELEASED)))
    heading = "## [%s] - %s" % (version, date)
    # Checked here rather than left to the audit, so the failure lands on the command
    # that writes the text instead of on a build minutes later: a promotion that has
    # to be undone by hand is the step that stalls a release.
    if re.match(RELEASED_HEADING, heading) is None:
        raise SystemExit("refusing to write %r, which is not the shape the changelog "
                         "audit requires of a released section" % heading)
    return text.replace(UNRELEASED, "%s\n\n%s\n" % (UNRELEASED, heading), 1)


AMEND_HOWTO = ("Fix it with `git commit --amend`: BUILD_NUMBER is "
               "`git rev-list --count HEAD`, and an amend replaces HEAD instead of "
               "adding to that count, so the section keeps naming the build the "
               "binaries carry.")


def catchup_hint(version, text):
    """Say when the goal is already being chased, or stay silent.

    The loop is this tool following its own instructions one commit at a time: a
    commit made for the previous refusal counts itself, the gate asks for a section
    one build higher, and each further commit moves the target again. The
    fingerprint is exact rather than a hunch -- the gate wants build N and the
    changelog already carries a section for N-1. A tree that never prepared
    anything cannot match, which matters as much as matching: a hint that fires in
    the ordinary case is a hint that gets ignored in the case it exists for.
    """
    match = re.match(r"^(.*)-build(\d+)$", version)
    if match is None:
        return None
    previous = "%s-build%d" % (match.group(1), int(match.group(2)) - 1)
    if not load_gate().changelog_has(text, previous):
        return None
    return ("the changelog already carries [%s], one build back, so a commit made "
            "for the previous refusal is what moved the target to %s. Stop committing "
            "it forward. %s" % (previous, version, AMEND_HOWTO))


def evaluate(args):
    gate = load_gate()
    changelog_path = args.changelog or os.path.join(ROOT, "CHANGELOG.md")
    project_path = args.project or os.path.join(ROOT, "Moonlight.xcodeproj", "project.pbxproj")
    text = open(changelog_path, encoding="utf-8").read()
    project = open(project_path, encoding="utf-8").read()
    versions = gate.marketing_versions(project)
    declared = sorted(versions)[0] if len(versions) == 1 else None
    build = args.build_number if args.build_number is not None else str(build_number())
    tag = args.tag or ("v%s-build%s" % (declared, build) if declared and build else None)
    if tag is None:
        raise SystemExit("MARKETING_VERSION must declare exactly one value")
    existing = args.tags.split(",") if args.tags is not None else [
        line for line in git("tag", "-l", "v*").splitlines() if line.strip()]
    reasons = gate.evaluate(tag, versions, int(build), text, existing)
    return tag, declared, int(build), text, reasons


def run(args):
    tag, declared, build, text, reasons = evaluate(args)
    print("this commit builds %s (MARKETING_VERSION %s, BUILD_NUMBER %d)" % (tag, declared, build))
    if not reasons:
        print("the gate accepts it: nothing to prepare")
        return 0
    for reason in reasons:
        print("gate refuses: %s" % reason)
    if [reason for reason in reasons if "CHANGELOG.md has no" in reason]:
        hint = catchup_hint(tag[1:], text)
        if hint:
            print("warning: %s" % hint)
    if [reason for reason in reasons if "CHANGELOG.md has no" not in reason]:
        print("only the changelog can be prepared automatically; fix the rest first")
        return 1
    # Promoting here is still the right edit even mid-loop: the section for the
    # current count is the one a tag needs, and the loop is the commit that carries
    # it, not the text. Refusing to write would leave no way out but a hand edit.
    updated = promote(text, tag[1:], args.release_date or commit_date())
    if not args.apply:
        print("run with --apply to promote the %s heading to [%s]" % (UNRELEASED, tag[1:]))
        return 1
    write_to = args.changelog or os.path.join(ROOT, "CHANGELOG.md")
    open(write_to, "w", encoding="utf-8").write(updated)
    _, _, _, _, after = evaluate(args)
    if after:
        print("the gate still refuses after promotion: %s" % "; ".join(after))
        return 1
    print("CHANGELOG.md carries [%s] in this working tree, and the gate accepts it "
          "there." % tag[1:])
    print("Do not commit that as a new commit. %s" % AMEND_HOWTO)
    print("Re-run prepare-release.py after the amend to confirm it still accepts %s." % tag)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tag")
    ap.add_argument("--changelog")
    ap.add_argument("--project")
    ap.add_argument("--build-number", type=int)
    ap.add_argument("--tags")
    ap.add_argument("--release-date")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run(args)


def self_test():
    import tempfile

    failures = []

    def check(ok, message):
        print("%-4s %s" % ("ok" if ok else "FAIL", message))
        if not ok:
            failures.append(message)

    unreleased_only = "%s\n\n### Fixed\n\n- something\n" % UNRELEASED
    already_released = "## [1.3.9-build42]\n\n- shipped\n"

    with tempfile.TemporaryDirectory() as tmp:
        project_path = os.path.join(tmp, "project.pbxproj")
        open(project_path, "w", encoding="utf-8").write("MARKETING_VERSION = 1.3.9;")
        changelog_path = os.path.join(tmp, "CHANGELOG.md")

        def attempt(tag, changelog, build=42, apply=False):
            open(changelog_path, "w", encoding="utf-8").write(changelog)
            # The report the script prints is what a release engineer reads, so the
            # fixtures read it too: a fix that only lives in prose still has to be
            # the prose that is actually printed.
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                rc = run(argparse.Namespace(tag=tag, changelog=changelog_path,
                                            project=project_path, build_number=build,
                                            tags="", apply=apply,
                                            release_date="2020-01-02"))
            return (rc, open(changelog_path, encoding="utf-8").read(),
                    captured.getvalue())

        rc, text, report = attempt("v1.3.9-build42", unreleased_only)
        check(rc == 1 and text == unreleased_only,
              "a report run names the missing section without editing the file")
        rc, text, report = attempt("v1.3.9-build42", unreleased_only, apply=True)
        check(rc == 0 and "## [1.3.9-build42] - 2020-01-02" in text
              and text.count(UNRELEASED) == 1,
              "--apply promotes Unreleased and leaves a fresh Unreleased behind")
        # A cleared promotion used to end in "the gate accepts the tag", which is
        # true of the working tree and misleading about the commit. The next
        # command most people run is `git commit -m ...`, and that one commit makes
        # the number the section just named one too old, so the release closes with
        # a tool that reports success and a gate that refuses forever. Naming the
        # amend, and the count that forces it, is the part under test.
        check("--amend" in report and "rev-list --count" in report,
              "a cleared promotion says to amend and why a new commit would undo it")
        check("accepts the tag\n" not in report,
              "the promotion report does not claim the tag is accepted as a verdict")
        # The heading a promotion writes is only useful if it is the shape the
        # repository audit reads. The rule is read out of constraints-audit.py rather
        # than copied, because a copy drifts quietly: the promotion reported the gate
        # accepting the tag while the changelog audit called the section it had just
        # written "a released section [that] lost its date". The third check keeps the
        # rule from passing by accepting anything, which is the shape of every green
        # guard this repository has had to bury.
        written = [line for line in text.splitlines() if line.startswith("## [1.3.9-build42]")]
        check(len(written) == 1 and re.match(RELEASED_HEADING, written[0]) is not None,
              "the promoted heading carries the date a released section must have")
        audit_src = open(os.path.join(ROOT, "scripts", "constraints-audit.py"),
                         encoding="utf-8").read()
        check(RELEASED_HEADING in audit_src,
              "the shape this writes is the shape constraints-audit.py matches, not a copy of it")
        check(re.match(RELEASED_HEADING, "## [1.3.9-build42]") is None,
              "the shape rule really refuses an undated heading, so the check above can fail")
        try:
            promote(unreleased_only, "1.3.9-build42", "yesterday")
            check(False, "an unusable date is refused before any text is written")
        except SystemExit:
            check(True, "an unusable date is refused before any text is written")

        rc, text, report = attempt("v1.3.9-build42", text, apply=True)
        check(rc == 0 and text.count("## [1.3.9-build42] - 2020-01-02") == 1,
              "running again has nothing to do and does not duplicate the entry")
        # The loop itself: one ordinary commit after a promotion leaves the tree
        # asking for build 43 while 42 sits in the changelog. That shape has to be
        # named, because the alternative reading is "prepare again", which is what
        # keeps the loop running.
        chased = "## [Unreleased]\n\n### Fixed\n\n- x\n\n## [1.3.9-build42]\n\n- y\n"
        rc, text, report = attempt("v1.3.9-build43", chased, build=43, apply=True)
        check("one build back" in report and "--amend" in report,
              "a goal that already moved once is reported as moved, with the fix")
        # And the same report must stay quiet in the cases that look similar but are
        # ordinary, or the warning trains people to ignore it.
        check("one build back" not in attempt("v1.3.9-build42", unreleased_only)[2],
              "a first preparation is not described as a chase")
        older = "## [Unreleased]\n\n### Fixed\n\n- x\n\n## [1.3.9-build19]\n\n- y\n"
        check("one build back" not in attempt("v1.3.9-build42", older)[2],
              "an older released section is not mistaken for a moved goal")
        for tag, build, message in [
            ("v1.3.9-build7", 42, "a tag naming another build is refused and never promoted"),
            ("v1.4.0-build42", 42, "a tag that disagrees with MARKETING_VERSION is refused"),
        ]:
            rc, text, report = attempt(tag, unreleased_only, build=build, apply=True)
            check(rc == 1 and text == unreleased_only, message)

    print("%d prepare-release self-test failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
