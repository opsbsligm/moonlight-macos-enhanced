#!/usr/bin/env python3
"""Refuse a release tag that does not describe the tree it points at.

Three of these have been reachable before and each one produces a release that
looks fine on GitHub and is wrong on the machine that installs it:

  * a tag whose version is not the MARKETING_VERSION the binaries were built with,
    so the release title and About box disagree;
  * a tag with a build suffix that does not match the generated build number, so
    two different products can carry the same version;
  * a tag that repeats or lowers an existing release, which silently downgrades
    anyone who upgrades.

The version, the build number and the changelog are read from this repository, so
nothing has to be kept in step by hand. Pass --self-test to exercise the rule set
against fixtures without touching the real tree.
"""
import argparse, importlib.util, os, re, subprocess, sys

TAG_RE = re.compile(
    r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<kind>build(?P<build>\d+)|alpha\.(?P<alpha>\d+)|beta\.(?P<beta>\d+)))?$")


def marketing_versions(project_text):
    return set(re.findall(r"MARKETING_VERSION\s*=\s*([^;]+);", project_text))


def parse_tag(tag):
    match = TAG_RE.match(tag)
    if match is None:
        return None
    build = match.group("build") or match.group("alpha") or match.group("beta")
    return {
        "base": (int(match.group("major")), int(match.group("minor")), int(match.group("patch"))),
        "version": match.group(0)[1:],
        "build": int(build) if build else 0,
        "prerelease": match.group("kind") is not None and not match.group("build"),
    }


def changelog_has(changelog_text, version):
    return re.search(r"^## \[%s\]" % re.escape(version), changelog_text, re.M) is not None


def highest(parsed_tags):
    best = None
    for tag in parsed_tags:
        entry = parse_tag(tag.strip())
        if entry is None:
            continue
        if best is None or (entry["base"], entry["build"]) > (best["base"], best["build"]):
            best = entry
    return best


def evaluate(tag, versions, build_number, changelog_text, existing_tags):
    """Return the list of reasons this tag must not be released."""
    reasons = []
    parsed = parse_tag(tag)
    if parsed is None:
        return ["%s is not vMAJOR.MINOR.PATCH, optionally -buildN or -alpha.N/-beta.N" % tag]

    if len(versions) != 1:
        return ["MARKETING_VERSION is %s; the project must declare exactly one"
                % (sorted(versions) or "unset")]
    declared = next(iter(versions))
    if ".".join(str(p) for p in parsed["base"]) != declared:
        reasons.append("tag base is %d.%d.%d but the project builds %s"
                       % (parsed["base"][0], parsed["base"][1], parsed["base"][2], declared))

    if parsed["build"] and parsed["build"] != build_number:
        reasons.append("tag carries build %d but this commit builds %d"
                       % (parsed["build"], build_number))

    if not changelog_has(changelog_text, parsed["version"]):
        reasons.append("CHANGELOG.md has no [%s] section" % parsed["version"])

    top = highest(existing_tags)
    if top is not None:
        if parsed["base"] < top["base"]:
            reasons.append("%s is older than the released %d.%d.%d"
                           % (parsed["version"], top["base"][0], top["base"][1], top["base"][2]))
        elif (parsed["base"], parsed["build"]) <= (top["base"], top["build"]):
            reasons.append("release %s is not newer than build %d of the same version"
                           % (parsed["version"], top["build"]))
    return reasons


def self_test():
    fixture_project = "MARKETING_VERSION = 1.3.9;"
    fixture_log = ("## [Unreleased]\n\n## [1.3.9]\n\n## [1.3.9-build19]\n"
                   "\n## [1.3.9-build20]\n")
    cases = [
        ("v1.3.9-build20", ["v1.3.9-build19"], True, None, "newer build of the shipped version"),
        ("v1.3.9-build19", ["v1.3.9-build19"], False, "not newer than build 19", "the same build again"),
        ("v1.3.9", ["v1.3.9-build19"], False, "not newer than build 19", "the bare version after a build of it"),
        ("v1.4.0-build20", ["v1.3.9-build19"], False, "the project builds 1.3.9", "a version the project does not build"),
        ("v1.3.8-build20", ["v1.3.9-build19"], False, "older than the released", "an older version"),
        ("v1.3.9-build99", ["v1.3.9-build19"], False, "build 99 but this commit builds 20", "a build number that is not this commit"),
        ("v1.3.9-chore19", ["v1.3.9-build19"], False, "is not vMAJOR.MINOR.PATCH", "an unknown suffix"),
        ("v1.4.0", ["v1.3.9"], False, "no [1.4.0] section", "a version with no changelog section"),
    ]
    failures = 0
    for tag, existing, expected_ok, reason_fragment, what in cases:
        reasons = evaluate(tag, {"1.3.9"}, 20, fixture_log, existing)
        ok = not reasons
        # A refusal has to name the right reason. Checking only the verdict lets
        # one broken rule hide behind another rule that happens to reject the same
        # tag, which is how the build-number check passed with its check disabled.
        matched = reason_fragment is None or any(reason_fragment in r for r in reasons)
        if ok != expected_ok or not matched:
            failures += 1
            print("FAIL %s (%s): %s%s" % (tag, what, reasons,
                  "" if matched else " [right verdict, wrong reason]"))
        else:
            print("ok   %-8s %s" % ("accept" if ok else "refuse", tag + " (" + what + ")"))
    missing_log = evaluate("v1.4.0", {"1.4.0"}, 20, fixture_log, ["v1.3.9"])
    print("%-4s a version absent from the changelog is refused"
          % ("ok" if missing_log else "FAIL"))
    if not missing_log:
        failures += 1
    ambiguous = evaluate("v1.4.0", {"1.4.0", "1.4.1"}, 20, "## [1.4.0]\n", [])
    print("%-4s two different MARKETING_VERSION values are refused"
          % ("ok" if ambiguous else "FAIL"))
    if not ambiguous:
        failures += 1
    print("%d release-gate self-test failures" % failures)
    return 1 if failures else 0


def build_number_self_test(repo="."):
    """A shallow clone has to stop the release, not slow it down quietly.

    BUILD_NUMBER is `git rev-list --count HEAD`, and in a shallow clone that
    counts the shallow window instead of the history: this tree reported 71
    locally while CI stamped the same commit 1407. Nothing objected until the
    DMG was already built. The fixture builds a real three-commit repository,
    clones it at depth one, and requires the script to refuse the clone and to
    still print the true number for the complete one.
    """
    import shutil, tempfile
    script = os.path.abspath(os.path.join(repo, "Limelight", "build-number.sh"))
    tmp = tempfile.mkdtemp(prefix="release-gate-shallow-")
    failures = 0
    try:
        full = os.path.join(tmp, "full")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        for step in (["init", "-q", full],
                     ["-C", full, "commit", "-q", "--allow-empty", "-m", "one"],
                     ["-C", full, "commit", "-q", "--allow-empty", "-m", "two"],
                     ["-C", full, "commit", "-q", "--allow-empty", "-m", "three"]):
            subprocess.run(["git"] + step, check=True, capture_output=True, text=True, env=env)
        shallow = os.path.join(tmp, "shallow")
        clone = subprocess.run(["git", "clone", "--quiet", "--depth", "1",
                                "file://" + full, shallow],
                               capture_output=True, text=True, env=env)
        if clone.returncode != 0:
            print("FAIL the fixture could not make a shallow clone: %s" % clone.stderr.strip())
            return 1

        def probe(cwd):
            out = subprocess.run(["sh", script, "--print"], cwd=cwd, env=dict(env, SRCROOT=cwd),
                                 capture_output=True, text=True)
            return out

        deep = probe(full)
        ok = deep.returncode == 0 and deep.stdout.strip().splitlines()[-1:] == ["3"]
        print("%-4s a complete history prints the real commit count" % ("ok" if ok else "FAIL"))
        failures += 0 if ok else 1

        shallow_run = probe(shallow)
        named_shallow = "shallow" in shallow_run.stderr.lower()
        ok = shallow_run.returncode != 0 and named_shallow
        print("%-4s a shallow clone is refused, not believed (%s)"
              % ("ok" if ok else "FAIL",
                 "exit %d" % shallow_run.returncode if shallow_run.returncode else "it printed a number"))
        failures += 0 if ok else 1
        if not ok and not named_shallow:
            print("     stderr: %s" % shallow_run.stderr.strip()[:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return failures


def preparation_self_test(repo="."):
    """Run the release preparation fixtures from this same CI entry point.

    The workflow runs `release-gate.py --self-test`, and the preparation step
    exists only to satisfy the rules checked here, so its fixtures belong to the
    same verdict: a gate whose release procedure is broken still reports green.
    """
    path = os.path.join(repo, "scripts", "prepare-release.py")
    spec = importlib.util.spec_from_file_location("prepare_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.self_test()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tag")
    ap.add_argument("--existing-tags", default="")
    ap.add_argument("--build-number", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return max(self_test(), preparation_self_test(args.repo),
                   build_number_self_test(args.repo))
    if not args.tag:
        print("error: --tag is required")
        return 2

    project = open(os.path.join(args.repo, "Moonlight.xcodeproj", "project.pbxproj"),
                   encoding="utf-8").read()
    changelog = open(os.path.join(args.repo, "CHANGELOG.md"), encoding="utf-8").read()
    build_number = args.build_number
    if build_number is None:
        out = subprocess.run(["sh", os.path.join(args.repo, "Limelight/build-number.sh"), "--print"],
                             capture_output=True, text=True, cwd=args.repo)
        if out.returncode != 0:
            print("error: build-number.sh failed: %s" % out.stderr.strip())
            return 2
        build_number = int(out.stdout.strip())

    existing = [t for t in args.existing_tags.split(",") if t.strip().startswith("v")]
    reasons = evaluate(args.tag, marketing_versions(project), build_number, changelog, existing)
    for reason in reasons:
        print("refuse %s: %s" % (args.tag, reason))
    print("%s: %s" % (args.tag, "blocked" if reasons else "cleared for release"))
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
