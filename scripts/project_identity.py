#!/usr/bin/env python3
"""Who this build is: the name it installs under, read from the one file that decides it.

The bundle name is the string a DMG layout, a codesign path, a tar member, a workflow step
and a README install line all have to agree on. Every one of them used to carry its own
copy of `Moonlight.app`, which is how upstream issue 41 happened: this client and the Qt
client installed under the same name, so installing one quietly replaced the other, and a
rename would have meant finding all of them by hand -- and one of them being missed would
have shipped an image whose bundle name no gate had ever looked at.

So the name is read from `project.pbxproj` and refused when it is the Qt name. `--print`
exists for the shell side (`scripts/product-name.sh`), because bash and Python should ask
the same question of the same file rather than keep two readers in step.

Usage: project_identity.py [--print] [--self-test]
Exit 0 with the name on stdout, or a refusal explaining which decision is missing.
"""
import os
import plistlib
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "Moonlight.xcodeproj", "project.pbxproj")

# The name the Qt client installs under. Two bundles with this name in /Applications is not
# a cosmetic clash: the second install replaces the first app's bundle under the same path.
QT_BUNDLE_NAME = "Moonlight"


def marketing_version(project=PROJECT):
    """The single MARKETING_VERSION the project builds, or a refusal naming the ambiguity.

    A shell script that wants the short version string has the same problem as one that
    wants the bundle name: copying it out of the project file by hand means the copy is
    authoritative the day the project moves. This is the reader for that case -- the
    packaging step asks for it and hands it to the image audit, so the audit compares the
    version the *source* declares against the version the *downloaded image* carries.
    Reading it back out of the built bundle instead would certify a bundle against itself.

    `release-gate.py` also reads this setting, to refuse a tag that disagrees with it; the
    two readers are pinned together in `self_test`, because two readers agreeing by
    accident are the same bug as two readers disagreeing on purpose.
    """
    versions = set(re.findall(r"MARKETING_VERSION\s*=\s*([^;]+);",
                              open(project, encoding="utf-8").read()))
    if len(versions) != 1:
        raise SystemExit("project identity: the project declares %d MARKETING_VERSION values "
                         "(%s); exactly one is expected"
                         % (len(versions), ", ".join(sorted(versions)) or "none"))
    declared = versions.pop().strip()
    if not declared:
        raise SystemExit("project identity: MARKETING_VERSION is empty")
    return declared


def bundle_executable(app_bundle):
    """The binary name the bundle itself declares.

    PRODUCT_NAME decides this today, so spelling it in a consumer looks harmless and then
    breaks the day somebody changes the product name and only the bundle moves. This is the
    second place the rename got half-applied for exactly that reason: the probe looked for
    `Contents/MacOS/Moonlight` inside a bundle whose binary had moved.
    """
    path = os.path.join(app_bundle, "Contents", "Info.plist")
    try:
        with open(path, "rb") as handle:
            declared = plistlib.load(handle).get("CFBundleExecutable")
    except OSError as error:
        raise SystemExit("project identity: cannot read %s (%s)" % (path, error))
    if not declared:
        raise SystemExit("project identity: %s declares no CFBundleExecutable" % path)
    return declared


def product_name(project=PROJECT):
    """The single PRODUCT_NAME the project builds, or a refusal naming the ambiguity."""
    names = set(re.findall(r"PRODUCT_NAME = ([^;]+);",
                           open(project, encoding="utf-8").read()))
    if len(names) != 1:
        raise SystemExit("project identity: the project names %d products (%s); one is expected"
                         % (len(names), ", ".join(sorted(names)) or "none"))
    name = names.pop()
    if not name:
        raise SystemExit("project identity: PRODUCT_NAME is empty")
    if name == QT_BUNDLE_NAME:
        raise SystemExit("project identity: PRODUCT_NAME is %s, the name the Qt client installs "
                         "under -- the two would replace each other in /Applications (issue 41)"
                         % name)
    return name


def self_test():
    """Every way the name can be wrong has to be refused, not read as a success."""
    import tempfile

    def write(text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".pbxproj", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        return handle.name

    failures = []

    # The shell side has to answer with the same string, because the workflow's paths and
    # every shell script here go through `product-name.sh`. Two readers that agree by
    # accident are the same bug as two readers that disagree on purpose.
    wrapper = os.path.join(ROOT, "scripts", "product-name.sh")
    try:
        shell_name = subprocess.run([wrapper], capture_output=True, text=True).stdout.strip()
    except OSError as error:
        shell_name = "<%s>" % error.__class__.__name__
    if shell_name == product_name():
        print("ok   scripts/product-name.sh and the Python reader agree: %s" % shell_name)
    else:
        failures.append("scripts/product-name.sh printed %r, the Python reader printed %r"
                        % (shell_name, product_name()))

    cases = (
        ("one product, a distinct name",
         "\t\t\tPRODUCT_NAME = MoonlightEnhanced;\n", "MoonlightEnhanced", None),
        ("one product, the Qt name",
         "\t\t\tPRODUCT_NAME = Moonlight;\n", None, SystemExit),
        ("two products disagreeing",
         "\t\t\tPRODUCT_NAME = MoonlightEnhanced;\n\t\t\tPRODUCT_NAME = Other;\n", None, SystemExit),
        ("no product name at all",
         "\t\t\tPRODUCT_BUNDLE_IDENTIFIER = std.skyhua.MoonlightMac2;\n", None, SystemExit),
    )
    for label, text, expected, raises in cases:
        path = write(text)
        try:
            if raises:
                try:
                    product_name(path)
                    failures.append("NOT REFUSED (%s)" % label)
                except SystemExit:
                    print("ok   refused: %s" % label)
            else:
                got = product_name(path)
                if got != expected:
                    failures.append("%s: read %r, expected %r" % (label, got, expected))
                else:
                    print("ok   %s -> %s" % (label, got))
        finally:
            os.unlink(path)

    # The version reader, and the second reader of the same setting. The two are asked the
    # same question of the shipped project file: an ambiguity check that only one of them
    # applies is how a project declaring two versions ships a DMG named after one of them.
    for label, text, expected, raises in (
            ("one declared version", "MARKETING_VERSION = 1.3.9;\n", "1.3.9", None),
            ("two versions disagreeing",
             "MARKETING_VERSION = 1.3.9;\nMARKETING_VERSION = 1.4.0;\n", None, SystemExit),
            ("no declared version", "PRODUCT_NAME = MoonlightEnhanced;\n", None, SystemExit),
    ):
        path = write(text)
        try:
            if raises:
                try:
                    marketing_version(path)
                    failures.append("NOT REFUSED (version: %s)" % label)
                except SystemExit:
                    print("ok   refused: version %s" % label)
            else:
                got = marketing_version(path)
                if got != expected:
                    failures.append("version %s: read %r, expected %r" % (label, got, expected))
                else:
                    print("ok   version %s -> %s" % (label, got))
        finally:
            os.unlink(path)

    release_gate = os.path.join(ROOT, "scripts", "release-gate.py")
    both = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys,os;"
         "spec=importlib.util.spec_from_file_location('rg',%r);"
         "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
         "print(' '.join(sorted(m.marketing_versions(open(%r,encoding='utf-8').read()))))"
         % (release_gate, PROJECT)],
        capture_output=True, text=True)
    readers = both.stdout.strip().split()
    if len(readers) == 1 and readers[0] == marketing_version():
        print("ok   scripts/release-gate.py and the identity reader agree on version %s"
              % marketing_version())
    else:
        failures.append("scripts/release-gate.py read %r, the identity reader read %r"
                        % (both.stdout.strip() or both.stderr.strip()[:80], marketing_version()))

    if failures:
        print("\n%d project-identity failure(s)" % len(failures))
        return 1
    print("\n0 project-identity failures")
    return 0


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    if "--print-version" in args:
        print(marketing_version())
        return 0
    print(product_name())
    return 0


if __name__ == "__main__":
    sys.exit(main())
