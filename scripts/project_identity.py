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
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "Moonlight.xcodeproj", "project.pbxproj")

# The name the Qt client installs under. Two bundles with this name in /Applications is not
# a cosmetic clash: the second install replaces the first app's bundle under the same path.
QT_BUNDLE_NAME = "Moonlight"


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
    if failures:
        print("\n%d project-identity failure(s)" % len(failures))
        return 1
    print("\n0 project-identity failures")
    return 0


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    print(product_name())
    return 0


if __name__ == "__main__":
    sys.exit(main())
