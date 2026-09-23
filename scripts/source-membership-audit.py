#!/usr/bin/env python3
"""Fail when a source file exists but no target compiles it.

Two authorities exist for this question and they are not the same file:

  * the build log is what happened. `CompileC` and `ScanDependencies` lines name
    each file xcodebuild fed to the compiler, so pass --build-log and this script
    reports a file nobody compiled;
  * the project file is a claim. It is also the one that lied here once:
    NetworkPermissionManager.swift shipped nothing for months with no build error.

The claim needs reading carefully, because the shape of this project file fools a
name-based reading. `Limelight` is a `PBXFileSystemSynchronizedRootGroup`, and the
one `PBXFileSystemSynchronizedBuildFileExceptionSet` hanging off it carries 137
`membershipExceptions` entries, 93 of them implementation files. Exceptions mean
"not a member", so that list looks like a list of things the target skips -- and
the previous version of this script read it as the opposite, an explicit member
list, which is the only reading under which the tree makes sense.

The build log settles it. Every one of those 93 files appears in an xcodebuild
compile line, and compiled-source-audit.py reports 0 of 90 first-party classes
missing from the linked binary. The reason is one grep away: the target carries no
`fileSystemSynchronizedGroups` at all (the string occurs zero times in the project
file), so neither the synchronized group nor its exception set is attached to the
target, and the target's own sources phase holds three empty `PBXBuildFile`
entries with no file reference behind them. The exception entries are Xcode
metadata that no target consumes: they exclude nothing and include nothing.

So neither list answers the question on its own, and this script stops pretending
otherwise. It reports an entry as an exclusion only when the association Xcode
needs is actually present, it says out loud when the project carries unattached
membership metadata instead of reading it as membership, and it asks for the build
log -- which CI has, next to the step that wrote it -- whenever a real answer is
wanted. A new file nobody compiles is still caught, and it is caught by the
authority that cannot bluff.

Path handling: the root argument is a checkout path a maintainer or CI types, not
a request from a stranger. The script still reads exactly one named file under it,
because a gate that reads some other file answers some other question.
"""
import argparse, os, re, sys

IMPL_SUFFIXES = (".m", ".mm", ".c", ".swift")
OBJC_SUFFIXES = (".m", ".mm", ".c")
# How many ::error annotations one run may print before the rest are counted instead.
REPORT_LIMIT = 20

# Files that legitimately produce no object code inside an app target. Each entry
# needs a reason, and the audit fails if the reason goes stale.
EXCLUSIONS = {
    "Limelight/Input/OnScreenControls.m":
        "upstream iOS-only overlay; the macOS target draws its own stream view",
    "Limelight/Input/StreamView.m":
        "upstream iOS-only view, companion to OnScreenControls.m",
    "Limelight/macOS/Helpers/AwdlPrivilegedHelperMain.m":
        "built by scripts/build_awdl_privileged_helper.sh into the privileged "
        "helper binary instead of the app sources phase",
}


def normalize(value):
    value = value.strip()
    if value.endswith(","):
        value = value[:-1].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.lstrip("/")


def project_text(root):
    """Read the one project file this gate is allowed to reason about."""
    pbx_path = os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj")
    if not os.path.isfile(pbx_path):
        raise SystemExit("::error::no project.pbxproj under %s -- this gate reads a "
                         "project file, so point it at a checkout" % root)
    return open(pbx_path, encoding="utf-8").read()


def synchronized_groups(project):
    """{object id: group path} for every file system synchronized root group."""
    groups = {}
    for match in re.finditer(
            r"^[\t ]*(?P<id>[0-9A-F]{24})[^\n]*?= *[\{\s]*isa = PBXFileSystemSynchronizedRootGroup;"
            r"(?P<attrs>[^\n]*)", project, re.M):
        path = re.search(r"\bpath = (?P<path>\"[^\"]*\"|[^;]+)", match.group("attrs"))
        if path:
            groups[match.group("id")] = normalize(path.group("path"))
    return groups


def target_groups(project):
    """{target id: [root group ids]} -- the association that makes membership real."""
    attached = {}
    for match in re.finditer(r"isa = PBXNativeTarget;(?P<body>.{0,4000}?)\n[\t ]*?\};",
                             project, re.S):
        groups = re.search(r"fileSystemSynchronizedGroups = \((?P<ids>[^)]*)\)",
                           match.group("body"), re.S)
        if groups is None:
            continue
        ids = re.findall(r"[0-9A-F]{24}", groups.group("ids"))
        name = re.search(r"\bname = \"([^\"]*)\"", match.group("body"))
        attached[name.group(1) if name else "?"] = ids
    return attached


def exception_sets(project):
    """{object id: (target id, [entry paths], [root group ids it hangs off])}."""
    sets = {}
    for match in re.finditer(
            r"[\t ]*(?P<id>[0-9A-F]{24})[^\n=]*=[ \t]*\{(?P<body>.*?)(?:\n[\t ]*\}|[ \t]*\};)",
            project, re.S):
        if not re.match(r"\s*isa = PBXFileSystemSynchronizedBuildFileExceptionSet;",
                        match.group("body")):
            # A synchronized root group names this class in its own `exceptions` list, so
            # filtering on the isa of the object being read is the only way to keep the
            # group out of the set count.
            continue
        body = match.group("body")
        block = re.search(r"membershipExceptions = \((?P<entries>.*?)\);", body, re.S)
        entries = [normalize(line) for line in block.group("entries").splitlines()] if block else []
        target = re.search(r"\btarget = ([0-9A-F]{24})", body)
        sets[match.group("id")] = (target.group(1) if target else None,
                                   [entry for entry in entries if entry], [])
    for group_id, attrs in re.findall(
            r"[\t ]*([0-9A-F]{24})[^\n]*isa = PBXFileSystemSynchronizedRootGroup;([^\n]*)", project):
        listed = re.search(r"exceptions = \(([^)]*)\)", attrs)
        for set_id in re.findall(r"[0-9A-F]{24}", listed.group(1)) if listed else []:
            if set_id in sets and group_id not in sets[set_id][2]:
                sets[set_id][2].append(group_id)
    return sets


def reference_members(project):
    """Source files named by a real file reference, wherever they live."""
    refs = set(re.findall(r"isa = PBXFileReference;[^\n]*path = (\"[^\"]*\"|[^;]+);", project))
    return {normalize(ref) for ref in refs if normalize(ref)}


def effective_exclusions(project):
    """Entries that really exclude, plus the unattached metadata worth reporting."""
    groups = synchronized_groups(project)
    attached = target_groups(project)
    attached_ids = {gid for ids in attached.values() for gid in ids}
    sets = exception_sets(project)
    excluded, unattached = set(), []
    for set_id, (target_id, entries, set_groups) in sets.items():
        live_groups = [gid for gid in set_groups if gid in attached_ids]
        if live_groups and target_id:
            excluded.update(entries)
        else:
            unattached.append((set_id, len(entries),
                               [groups.get(gid, "?") for gid in set_groups]))
    return excluded, unattached, groups, attached


# A path with a space in it is written `Supporting\ Files`, so the transcript cannot be
# split on whitespace to find a source: `Files/main.m` would land in a different token
# than the `/Limelight/` prefix that identifies it. Match the path as text instead.
LOG_SOURCE = re.compile(
    r"/Limelight/(?P<rel>[^\s\"]*(?:\s[^\s\"]*)*?\.(?:m|mm|c))(?![A-Za-z0-9])")
# Swift is compiled file by file, but the transcript names those files by basename
# inside a `Compiling` argument list, so a Swift file is recognised by its name.
SWIFT_FILE = re.compile(r"([A-Za-z][A-Za-z0-9_+]*\.swift)")


def compiled_from_log(log_path):
    """What xcodebuild fed to the compiler, per its own transcript.

    C-family sources come back as Limelight-relative paths and Swift files as plain
    names, because that is the evidence the transcript offers for each.
    """
    compiled = set()
    for line in open(log_path, encoding="utf-8", errors="replace"):
        line = line.replace("\\ ", " ").replace("\\,", ",")
        if line.startswith("CompileC ") or line.startswith("ScanDependencies "):
            for match in LOG_SOURCE.finditer(line):
                if " -" not in match.group("rel"):
                    compiled.add(match.group("rel"))
        elif line.startswith("SwiftCompile ") or line.startswith("SwiftDriverJobDiscovery "):
            compiled.update(SWIFT_FILE.findall(line))
    return compiled


def implementation_files(root):
    paths = []
    for base, _, files in os.walk(os.path.join(root, "Limelight")):
        for name in files:
            if name.endswith(IMPL_SUFFIXES):
                paths.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(paths)


def audit(root, build_log=None, exclusions=None):
    """Return (problems, notes, checked, authority). Problems are repo-relative paths."""
    exclusions = EXCLUSIONS if exclusions is None else exclusions
    project = project_text(root)
    excluded, unattached, groups, attached = effective_exclusions(project)
    notes = []

    compiled = compiled_from_log(build_log) if build_log else None
    if compiled is None:
        authority = "project declarations"
        notes.append("declaration mode: the project file in this shape cannot say what "
                     "compiled; pass --build-log for the answer xcodebuild wrote down")
    else:
        authority = "the xcodebuild transcript"

    for set_id, count, set_paths in unattached:
        notes.append("membership-exception set %s carries %d entries under %s but no "
                     "target lists that group in fileSystemSynchronizedGroups, so the "
                     "entries neither include nor exclude anything"
                     % (set_id, count, ", ".join(set_paths) or "no group"))

    problems, checked = [], 0
    for rel in implementation_files(root):
        under_source = rel[len("Limelight/"):] if rel.startswith("Limelight/") else rel
        checked += 1
        excluded_by_project = (under_source in excluded or rel in excluded
                               or os.path.basename(rel) in excluded)
        documented = rel in exclusions
        if compiled is None:
            reached = False
        elif rel.endswith(".swift"):
            # The transcript names a Swift file by basename, so the name is the evidence.
            reached = os.path.basename(rel) in compiled
        else:
            reached = under_source in compiled or rel in compiled

        # What a project file proves is an exclusion: an entry attached to a target says
        # on purpose that this file is not built. Anything it says about inclusion is a
        # claim about a build, and this project's claims are unattached metadata.
        if excluded_by_project and not documented:
            problems.append((rel, "excluded by a membership exception that is attached to "
                                  "a target, and this script records no reason for it"))
            continue
        if compiled is None:
            continue
        if reached and documented:
            problems.append((rel, "the build log compiled it, so drop it from the exclusion "
                                  "list in this script"))
        elif not reached and not documented:
            problems.append((rel, "named by no compile line in the "
                                  "build log, so nothing compiled it, and it is not "
                                  "excluded on purpose"))
    return problems, notes, checked, authority


def self_test(root=".", exclusions=None):
    """Plant each failure this gate claims to catch, in a throwaway checkout."""
    import shutil, tempfile
    failures = 0
    tmp = tempfile.mkdtemp(prefix="source-membership-")
    try:
        def fixture(attached, exceptions_block):
            repo = os.path.join(tmp, "attached" if attached else "detached")
            proj = os.path.join(repo, "Moonlight.xcodeproj")
            src = os.path.join(repo, "Limelight", "Input")
            os.makedirs(proj, exist_ok=True)
            os.makedirs(src, exist_ok=True)
            for name in ("Compiled.m", "Unlisted.m"):
                open(os.path.join(src, name), "w").write("@implementation %s\n@end\n" % name)
            target = ("\t\t\t\tA10000000000000000000001 /* Limelight */,\n" if attached else "")
            sync = ("\t\t\tfileSystemSynchronizedGroups = (\n%s\t\t\t);\n" % target) if attached else ""
            open(os.path.join(proj, "project.pbxproj"), "w").write(
                "//{{{\n"
                "\t\tA10000000000000000000001 /* Limelight */ = {isa = PBXFileSystemSynchronizedRootGroup;"
                " exceptions = (A20000000000000000000001 /* PBXFileSystemSynchronizedBuildFileExceptionSet */, );"
                " path = Limelight; sourceTree = \"<group>\"; };\n"
                "\t\tA20000000000000000000001 /* PBXFileSystemSynchronizedBuildFileExceptionSet */ = {\n"
                "\t\t\tisa = PBXFileSystemSynchronizedBuildFileExceptionSet;\n"
                "\t\t\tmembershipExceptions = (\n%s\t\t\t);\n"
                "\t\t\ttarget = A30000000000000000000001 /* Fixture */;\n"
                "\t\t};\n"
                "\t\tA30000000000000000000001 /* Fixture */ = {\n"
                "\t\t\tisa = PBXNativeTarget;\n"
                "%s"
                "\t\t\tname = \"Fixture\";\n"
                "\t\t};\n"
                "}}}\n" % (exceptions_block, sync))
            return repo

        plant = "\t\t\t\tInput/Unlisted.m,\n"
        problems, notes, _, _ = audit(fixture(False, plant), exclusions={})
        caught = [rel for rel, _ in problems if rel.endswith("Unlisted.m")]
        print("%-4s unattached membership exceptions are not read as an exclusion"
              % ("ok" if not caught else "FAIL"))
        failures += 0 if not caught else 1
        print("%-4s unattached membership metadata is reported instead of believed"
              % ("ok" if notes else "FAIL"))
        failures += 0 if notes else 1

        problems, attached_notes, _, _ = audit(fixture(True, plant), exclusions={})
        caught = [rel for rel, _ in problems if rel.endswith("Unlisted.m")]
        print("%-4s an effective membership exception makes a file an orphan"
              % ("ok" if caught else "FAIL"))
        failures += 0 if caught else 1

        log = os.path.join(tmp, "build-fixture.log")
        open(log, "w", encoding="utf-8").write(
            "CompileC /tmp/Compiled.o /r/Limelight/Input/Compiled.m normal arm64 objective-c\n"
            "    builtin-ScanDependencies -o /tmp/Compiled.o.scan -- /bin/clang -x objective-c\te\n"
            "CompileC /tmp/Other.o /r/Limelight/Supporting\\ Files/main.m normal arm64\n")
        repo = fixture(True, plant)
        open(os.path.join(repo, "Limelight", "Supporting Files"), "w").close()
        os.remove(os.path.join(repo, "Limelight", "Supporting Files"))
        os.makedirs(os.path.join(repo, "Limelight", "Supporting Files"))
        open(os.path.join(repo, "Limelight", "Supporting Files", "main.m"), "w").write(
            "@implementation main\n@end\n")
        problems, _, checked, authority = audit(repo, build_log=log, exclusions={})
        names = {os.path.basename(rel) for rel, _ in problems}
        print("%-4s a file the transcript never compiled is reported (%s)"
              % ("ok" if "Unlisted.m" in names else "FAIL", authority))
        failures += 0 if "Unlisted.m" in names else 1
        print("%-4s an escaped space in a compile line still counts as compiled"
              % ("ok" if "main.m" not in names else "FAIL"))
        failures += 0 if "main.m" not in names else 1
        print("%-4s the transcript is read as the authority it is (%d files checked)"
              % ("ok" if authority == "the xcodebuild transcript" else "FAIL", checked))
        failures += 0 if authority == "the xcodebuild transcript" else 1
        print("%d source membership self-test failures" % failures)
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--build-log", default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test(args.root)

    problems, notes, checked, authority = audit(args.root, args.build_log)
    for note in notes:
        print("note  %s" % note)
    print("source membership: %d implementation files checked against %s" % (checked, authority))
    # Attaching a synchronized group to a target excludes every entry of its exception
    # set at once, which is over a hundred files. The count is the headline and the first
    # pages are enough to act on; a wall of annotations hides both.
    shown = problems if len(problems) <= REPORT_LIMIT else problems[:REPORT_LIMIT]
    for rel, why in shown:
        print("::error file=%s::%s" % (rel, why))
    if len(problems) > len(shown):
        print("... and %d more, all of them files no target builds"
              % (len(problems) - len(shown)))
    if problems:
        return 1
    print("every implementation file is compiled, excluded with a reason, or covered by "
          "a synchronized group this sweep could not measure without a build log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
