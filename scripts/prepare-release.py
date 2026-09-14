#!/usr/bin/env python3
"""Turn the release gate's refusal into a command that clears it.

release-gate.py refuses a tag whose CHANGELOG section is missing, which is the
right rule: the section has to name the exact build the binaries carry. It was
still a manual scramble at release time, and a hand-edited heading is exactly the
kind of step that gets the tag and the built version out of step.

BUILD_NUMBER is git rev-list --count HEAD, so the tag for this commit is
derivable from the commit itself. This script computes that tag, asks the gate
what it objects to, and with --apply promotes the Unreleased section to the
version the gate will accept, then re-asks.

  prepare-release.py                 report the tag this commit builds and what
                                     still stands between it and a release
  prepare-release.py --apply         promote the Unreleased section for that tag
  prepare-release.py --self-test     run the fixtures
"""
import argparse, contextlib, importlib.util, io, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNRELEASED = "## [Unreleased]"


def load_gate():
    path = os.path.join(ROOT, "scripts", "release-gate.py")
    spec = importlib.util.spec_from_file_location("release_gate", path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True).stdout


def promote(text, version):
    """Give the Unreleased section the release's version and open a new one.

    Returns None when the version already has its own section, because there is
    nothing to do and silently editing a second time would move a released entry.
    """
    gate = load_gate()
    if gate.changelog_has(text, version):
        return None
    if text.count(UNRELEASED) != 1:
        raise SystemExit("expected exactly one %s heading, found %d"
                         % (UNRELEASED, text.count(UNRELEASED)))
    return text.replace(UNRELEASED, "%s\n\n%s [%s]" % (UNRELEASED, "##", version), 1)


def evaluate(args):
    gate = load_gate()
    changelog_path = args.changelog or os.path.join(ROOT, "CHANGELOG.md")
    project_path = args.project or os.path.join(ROOT, "Moonlight.xcodeproj", "project.pbxproj")
    text = open(changelog_path, encoding="utf-8").read()
    project = open(project_path, encoding="utf-8").read()
    versions = gate.marketing_versions(project)
    declared = sorted(versions)[0] if len(versions) == 1 else None
    build = args.build_number if args.build_number is not None else git("rev-list", "--count", "HEAD").strip()
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
    if [reason for reason in reasons if "CHANGELOG.md has no" not in reason]:
        print("only the changelog can be prepared automatically; fix the rest first")
        return 1
    updated = promote(text, tag[1:])
    if not args.apply:
        print("run with --apply to promote the %s heading to [%s]" % (UNRELEASED, tag[1:]))
        return 1
    write_to = args.changelog or os.path.join(ROOT, "CHANGELOG.md")
    open(write_to, "w", encoding="utf-8").write(updated)
    _, _, _, _, after = evaluate(args)
    if after:
        print("the gate still refuses after promotion: %s" % "; ".join(after))
        return 1
    print("CHANGELOG.md now carries [%s]: the gate accepts the tag" % tag[1:])
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tag")
    ap.add_argument("--changelog")
    ap.add_argument("--project")
    ap.add_argument("--build-number", type=int)
    ap.add_argument("--tags")
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
            # The report the script prints is what a release engineer reads; in
            # the fixtures it would bury the verdicts.
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                rc = run(argparse.Namespace(tag=tag, changelog=changelog_path,
                                            project=project_path, build_number=build,
                                            tags="", apply=apply))
            return rc, open(changelog_path, encoding="utf-8").read()

        rc, text = attempt("v1.3.9-build42", unreleased_only)
        check(rc == 1 and text == unreleased_only,
              "a report run names the missing section without editing the file")
        rc, text = attempt("v1.3.9-build42", unreleased_only, apply=True)
        check(rc == 0 and "## [1.3.9-build42]" in text and text.count(UNRELEASED) == 1,
              "--apply promotes Unreleased and leaves a fresh Unreleased behind")
        rc, text = attempt("v1.3.9-build42", text, apply=True)
        check(rc == 0 and text.count("## [1.3.9-build42]") == 1,
              "running again has nothing to do and does not duplicate the entry")
        for tag, build, message in [
            ("v1.3.9-build7", 42, "a tag naming another build is refused and never promoted"),
            ("v1.4.0-build42", 42, "a tag that disagrees with MARKETING_VERSION is refused"),
        ]:
            rc, text = attempt(tag, unreleased_only, build=build, apply=True)
            check(rc == 1 and text == unreleased_only, message)

    print("%d prepare-release self-test failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
