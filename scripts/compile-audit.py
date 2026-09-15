#!/usr/bin/env python3
"""Type-check the macOS sources with the same compiler the build uses.

A build reaches a runner and reports a mistake that every local gate called clean.
`effectIsInteractive` was named in a container that the local machine's newer SDK
knows and the CI image's older one does not, and a header used a first-party class
it could not see: both parsed, both passed every grep, and both were only visible in
a translation unit. Grep cannot see a translation unit -- a compiler can, and
`-fsyntax-only` gets the answer without producing a binary.

The rule is deliberately narrow. It compiles the files that belong to the macOS
target against a real Apple toolchain and a real set of generated headers. Where
either is missing it says so and reports nothing, because a gate that invents a
failure for a host that cannot answer is a gate people learn to ignore -- and where
it can answer, both directions are proven by `--self-test`.

Exit 0: every file it could compile passed, or it had nothing to compile and said so.
Exit 1: a source file does not type-check, or a self-test control disagreed.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX_HEADER = os.path.join(ROOT, "Limelight", "macOS", "Supporting Files",
                             "Limelight-Prefix.pch")
TARGETS = (os.path.join("Limelight", "macOS"),)


def deployment_target():
    """The minimum macOS the shipped target claims to run on.

    An SDK below that is not a target of this build, and compiling against it is not
    a stricter test -- it is a different question. The macOS 11 SDK has no
    `NSGlassEffectView` and no `kCMVideoCodecType_AV1`, so reporting those as failures
    would only teach people that this gate cries.
    """
    import plistlib
    import re
    try:
        with open(os.path.join(ROOT, "Moonlight.xcodeproj", "project.pbxproj"),
                  encoding="utf-8", errors="replace") as handle:
            values = re.findall(r"MACOSX_DEPLOYMENT_TARGET = ([0-9.]+)", handle.read())
    except OSError:
        return None
    versions = [tuple(int(part) for part in value.split(".")) for value in values if value]
    return max(versions) if versions else None


def sdk_version(path):
    import plistlib
    for name in ("SDKSettings.plist", "SDKSettings.json"):
        try:
            with open(os.path.join(path, name), "rb") as handle:
                settings = plistlib.load(handle)
            version = settings.get("ProductVersion") or settings.get("Version")
            if isinstance(version, str):
                return tuple(int(part) for part in version.split(".")[:2] if part.isdigit())
        except (OSError, ValueError):
            continue
    return None


def installed_sdks(default):
    """Every macOS SDK this host offers, newest first, with the default one included.

    A CI image built with the 26.5 SDK while the developer machine had the 27 SDK: the
    newer one declared `effectIsInteractive`, the older one did not, and every local
    gate said clean while three jobs failed. Compiling once per installed SDK turns
    that class of mistake into a local failure, which is why the list is not just the
    default one.
    """
    found = {os.path.realpath(default): sdk_version(os.path.realpath(default))}
    root = os.path.dirname(default)
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not (name.startswith("MacOSX") and name.endswith(".sdk")):
                continue
            real = os.path.realpath(path)
            if os.path.isdir(real) and os.path.exists(os.path.join(real, "usr", "include")):
                found[real] = sdk_version(real)
    return found


def usable_sdks(default):
    """The installed SDKs this build is allowed to be compiled against."""
    minimum = deployment_target()
    usable, too_old = [], []
    for path, version in installed_sdks(default).items():
        if minimum is None or version is None or version >= minimum:
            usable.append(path)
        else:
            too_old.append(path)
    return sorted(usable, key=lambda path: sdk_version(path) or ()), too_old


# Where a build may have put its derived data. The CI analyze job uses a path outside
# the repository, so `--derived` names one as well; the scan below only ever finds the
# ones that happen to live beside the sources.
EXTRA_DERIVED = []


def derived_sources():
    """Directories that hold xcodebuild's generated headers, in any derived-data root.

    The layout has one directory per derived-data root, per configuration, per target,
    so it is walked rather than spelled out: `build`, `build-arm64-check`, and
    `$TMPDIR/analyze` are the same thing to this gate.
    """
    found = []
    for extra in EXTRA_DERIVED:
        if not os.path.isdir(extra):
            continue
        for current, directories, files in os.walk(extra):
            directories.sort()
            if os.path.basename(current) == "DerivedSources" and files:
                found.append(current)
    for name in sorted(os.listdir(ROOT)):
        candidate = os.path.join(ROOT, name)
        if name.startswith(".") or not os.path.isdir(candidate):
            continue
        intermediates = os.path.join(candidate, "Build", "Intermediates.noindex")
        if not os.path.isdir(intermediates):
            continue
        for current, directories, files in os.walk(intermediates):
            directories.sort()
            if os.path.basename(current) == "DerivedSources" and files:
                found.append(current)
    return sorted(found)


# Some vendored libraries are imported by package name (`#include "enet/unix.h"`), so
# the directory that has to be on the search path holds no headers of its own -- only
# a subdirectory named after the package. Walking for headers would miss them.
PACKAGE_ROOTS = (
    os.path.join("moonlight-common", "moonlight-common-c", "enet", "include"),
    os.path.join("moonlight-common", "moonlight-common-c", "nanors"),
)


def include_dirs(sdk):
    """Every repository directory that holds a header, plus the generated ones."""
    includes = {os.path.join(ROOT, relative) for relative in PACKAGE_ROOTS}
    for base in ("Limelight", "moonlight-common"):
        for current, _, files in os.walk(os.path.join(ROOT, base)):
            if any(name.endswith(".h") for name in files):
                includes.add(current)
    sources = derived_sources()
    if not sources:
        return None
    for generated in sources:
        for current, _, files in os.walk(generated):
            if any(name.endswith(".h") for name in files):
                includes.add(current)
    return sorted("-I" + path for path in includes)


def compile_flags(sdk, includes):
    return [
        "-fsyntax-only",
        "-Wall",
        # The project still names APIs the SDK marks deprecated, and the build does
        # not fail on them. A gate that reports what the build tolerates as its own
        # failure teaches people to pass --skip, so it reports what the build refuses.
        "-Wno-deprecated-declarations",
        "-fobjc-arc",
        "-fmodules",
        "-fmodules-cache-path=" + os.path.join(tempfile.gettempdir(), "moonlight-compile-audit-modules"),
        "-include", PREFIX_HEADER,
        "-isysroot", sdk,
    ] + includes


def sources():
    found = []
    for relative in TARGETS:
        for current, _, files in os.walk(os.path.join(ROOT, relative)):
            found += [os.path.join(current, name) for name in sorted(files) if name.endswith(".m")]
    return sorted(found)


def compile_one(clang, flags, path):
    proc = subprocess.run([clang] + flags + [path], capture_output=True, text=True, cwd=ROOT)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def controls(clang, flags):
    """Both directions, on the same flags the real files are compiled with.

    Without these, an empty include list or a silently rejected flag would look like
    a clean tree: the same shape as every other gate here -- prove the gate can be
    wrong in both directions before believing it says anything.
    """
    findings = []
    probe = """#import "StreamViewController_Internal.h"

@interface MLCompileAuditProbe : NSObject
- (void)probe;
@end

@implementation MLCompileAuditProbe
- (void)probe {
    [self mlThisSelectorExistsNowhere];
}
@end
"""
    with tempfile.TemporaryDirectory() as temporary:
        broken = os.path.join(temporary, "ml-compile-audit-probe.m")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write(probe)
        code, output = compile_one(clang, flags, broken)
        if code == 0:
            findings.append("the broken probe compiled, so these flags report nothing: %s"
                            % (output.splitlines()[:1] or ["no output"],))
        elif "mlThisSelectorExistsNowhere" not in output:
            findings.append("the broken probe failed for a reason unrelated to the probe: %s"
                            % (output.splitlines()[:2],))
        fixed = probe.replace("mlThisSelectorExistsNowhere", "probe")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write(fixed)
        code, output = compile_one(clang, flags, broken)
        if code != 0:
            findings.append("the corrected probe still fails, so the flags cannot compile "
                            "the product's own header: %s" % (output.splitlines()[:3],))
    return findings


def main(argv):
    for index, argument in enumerate(argv):
        if argument == "--derived" and index + 1 < len(argv):
            EXTRA_DERIVED.append(os.path.realpath(argv[index + 1]))

    self_test = "--self-test" in argv
    try:
        clang, sdk = apple_toolchain.clang_and_sdk("compile audit")
    except SystemExit as missing:
        print("compile-audit: skipped, %s" % str(missing).strip())
        return 1 if self_test else 0

    includes = include_dirs(sdk)
    if includes is None:
        print("compile-audit: skipped, no xcodebuild DerivedSources in this checkout. The "
              "macOS sources import generated headers (the CoreData classes and the Swift "
              "interface), so this gate needs one build to have happened; it does not "
              "substitute its own guesses for them.")
        return 1 if self_test else 0

    files = sources()
    if self_test:
        findings = controls(clang, compile_flags(sdk, includes))
        for line in findings:
            print("SELF TEST FAIL: %s" % line)
        if findings:
            return 1
        print("compile-audit self test: the flags refuse a selector that does not exist and "
              "accept one that does, against the product's own headers")
        return 0

    only = None
    if "--sdk" in argv:
        only = os.path.realpath(argv[argv.index("--sdk") + 1])
    sdks = [only] if only else usable_sdks(sdk)[0]
    problems = 0
    for target in sdks:
        flags = compile_flags(target, includes)
        failed = []
        for path in files:
            code, output = compile_one(clang, flags, path)
            if code != 0:
                failed.append((os.path.relpath(path, ROOT), output))
        for path, output in failed:
            print("FAIL %s does not type-check against %s" % (path, os.path.basename(target)))
            for line in output.splitlines()[:12]:
                print("    %s" % line)
        problems += len(failed)
        print("compile-audit: %d of %d macOS source file(s) type-check against %s"
              % (len(files) - len(failed), len(files), os.path.basename(target)))
    if problems:
        print("compile-audit: %d file/SDK failure(s)" % problems)
        return 1
    if len(sdks) > 1:
        print("compile-audit: every file type-checks against all %d SDKs at or above the "
              "deployment target, so an API that only the newest of them declares has "
              "nowhere to hide" % len(sdks))
    skipped = usable_sdks(sdk)[1] if not only else []
    if skipped:
        print("compile-audit: %d older SDK(s) not tried, the target runs on %s at minimum"
              % (len(skipped), ".".join(str(part) for part in deployment_target())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
