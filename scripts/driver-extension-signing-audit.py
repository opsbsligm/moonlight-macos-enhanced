#!/usr/bin/env python3
"""Refuse a driver extension that no player could load.

Stage 3 of docs/usb-redirection-design.md needs two things this repository does not have: a
Developer ID identity, and a notarisation pipeline. docs/usb-redirection-design.md 2.3 records that
as measured rather than assumed -- an ad-hoc signed `.dext` is refused by
`OSSystemExtensionErrorAuthorizationFailed` (103) on macOS 27.2 -- so a build that shipped one
would ship a settings page whose button cannot work, and an issue thread full of people being told
their hardware is unsupported by software that quietly contains no driver.

The gate is one-directional, and that direction is the whole point: if the tree ever carries a
driver extension target, DriverKit sources, a system-extension request, or the DriverKit
entitlement, then the workflow that builds it has to sign it with a Developer ID identity, enable
the hardened runtime, notarise it, and staple the ticket back. Today the tree carries none of those,
so the gate passes by having nothing to say -- which is why `--self-test` exists. It drives the same
rule with fabricated trees, including one that is properly signed, so the gate is known to be able
to go green as well as red, on a machine that owns no certificates.

What it does not do is claim the prerequisites arrived. It refuses the combination of "we built it"
and "nobody can load it", and says which file to change.
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(".github", "workflows", "build.yml")
ENTITLEMENTS = "Moonlight.entitlements"

# What has to be true of the build before a loadable extension can come out of it. Each entry is
# a requirement plus the thing a maintainer would type: a gap that does not name the file to edit
# is a gap that gets ignored.
REQUIREMENTS = (
    ("a Developer ID signature on the built product",
     re.compile(r"codesign[^\n]*--sign[^\n]*Developer ID|Developer ID Application", re.I),
     "sign the release job's product with a `Developer ID Application` identity"),
    ("the hardened runtime, which notarisation refuses without",
     re.compile(r"--options[^\S\n]*runtime|hardened_runtime|hardened-runtime", re.I),
     "add `--options runtime` to the `codesign` invocation for the app and the extension"),
    ("a notarisation step",
     re.compile(r"notarytool", re.I),
     "submit the artifact with `notarytool submit` and wait for acceptance"),
    ("the notarisation ticket stapled back onto the artifact",
     re.compile(r"stapler\s+staple", re.I),
     "run `xcrun stapler staple` on the notarized artifact before it is packaged"),
)


def read(root, rel):
    try:
        return open(os.path.join(root, rel), encoding="utf-8").read()
    except OSError:
        return ""


def tracked_files(root):
    """`git ls-files`, because a target that is not committed is not shipped either."""
    listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    if listed.returncode != 0:
        raise SystemExit("git ls-files failed, so this audit cannot see what is in the tree")
    return [line for line in listed.stdout.splitlines() if line.strip()]


def extension_evidence(root, files):
    """Every trace of stage 3 in the tree, in one place, so the gate has one input to reason about.

    Read from committed paths and from source text rather than from build settings, because a
    target can be added in the project file and the sources are what a reviewer actually reads.
    """
    targets = [path for path in files
               if ".dext" in path or path.endswith(".systemextension")]
    sources, requests, entitlements = [], [], []
    for path in files:
        if path.endswith((".h", ".m", ".mm", ".c", ".swift")):
            text = read(root, path)
            if re.search(r"#import\s*<(DriverKit|IOKit/IOCFPlugin)\b|OSBundleLibrary|<os/libdeclaration\.h>",
                         text):
                sources.append(path)
            if "OSSystemExtensionRequest" in text:
                requests.append(path)
        elif path.endswith(".entitlements") and "com.apple.developer.driverkit" in read(root, path):
            entitlements.append(path)
    return {"targets": targets, "sources": sources, "requests": requests,
            "entitlements": entitlements}


def has_stage3(evidence):
    return any(evidence[key] for key in ("targets", "sources", "requests", "entitlements"))


def gaps(evidence, workflow_text, workflow_name=WORKFLOW):
    """What is missing, in the order somebody would fix it. An empty list means the tree and the
    workflow agree -- not that signing exists, and not that it does not."""
    if not has_stage3(evidence):
        return []
    missing = []
    for what, pattern, instruction in REQUIREMENTS:
        if pattern.search(workflow_text) is None:
            missing.append("%s: stage 3 code is in the tree (%s), so %s has to carry %s -- %s"
                           % (what, describe(evidence), workflow_name, what, instruction))
    return missing


def describe(evidence):
    parts = []
    for key, label in (("targets", "extension targets"), ("sources", "DriverKit sources"),
                       ("requests", "system-extension requests"),
                       ("entitlements", "DriverKit entitlements")):
        if evidence[key]:
            parts.append("%s %s" % (label, ", ".join(sorted(evidence[key])[:3])))
    return "; ".join(parts)


def self_test():
    """Drive the rule with trees that do not exist, including one that would pass.

    Both halves matter. A gate that only ever fires is as useless as one that never does: the
    first version of this audit could not have told the difference between "the tree has no
    extension" and "the signing step exists", and only the second of those is a pass.
    """
    failures = 0
    checks_run = 0

    def check(ok, message):
        nonlocal failures, checks_run
        checks_run += 1
        print("%-4s %s" % ("ok" if ok else "FAIL", message))
        if not ok:
            failures += 1

    empty = {"targets": [], "sources": [], "requests": [], "entitlements": []}
    signed = """
      - run: codesign --force --sign "Developer ID Application: Example (TEAMID)" \\
              --options runtime --entitlements app.entitlements Moonlight.app
      - run: xcrun notarytool submit Moonlight.zip --keychain-profile AC --wait
      - run: xcrun stapler staple Moonlight.app
"""
    check(gaps(empty, "") == [],
          "a tree with no driver extension needs nothing, so the gate says nothing today")
    naked = dict(empty, targets=["EmbeddedContent/MoonlightVirtualUsb.dext/Info.plist"])
    naked_gaps = gaps(naked, "jobs:\n  build:\n    steps: []\n")
    check(len(naked_gaps) == len(REQUIREMENTS),
          "an extension target with an ordinary release job is reported as %d separate gaps"
          % len(REQUIREMENTS))
    check(all(WORKFLOW in gap for gap in naked_gaps),
          "every gap names the workflow file that has to change")
    check(all("EmbeddedContent" in gap for gap in naked_gaps),
          "every gap names the target that made it fire, so it is not a mystery")
    check(gaps(naked, signed) == [],
          "the same target with a Developer ID, the hardened runtime, notarisation and a staple passes")
    half = signed.replace("notarytool", "echo skipped")
    half_gaps = gaps(naked, half)
    check(len(half_gaps) == 1 and "notarisation" in half_gaps[0],
          "a signing step that stopped short of notarising is caught by exactly one gap")
    sources = dict(empty, sources=["Limelight/Stream/USBPassthrough.m"])
    check(len(gaps(sources, "")) == len(REQUIREMENTS),
          "DriverKit sources count as stage 3 even with no target in the project")
    requests = dict(empty, requests=["Limelight/macOS/Helpers/ExtensionManager.m"])
    check(len(gaps(requests, "")) == len(REQUIREMENTS),
          "asking the system to load an extension is stage 3 wherever it is asked")
    entitlements = dict(empty, entitlements=[ENTITLEMENTS])
    check(len(gaps(entitlements, "")) == len(REQUIREMENTS),
          "the DriverKit entitlement is treated as a promise that a signed build follows")
    check(gaps(entitlements, signed) == [],
          "the entitlement is fine once the signing exists to back it")
    print("%s (%d checks)" % ("RUN FAILED" if failures else "RUN PASSED", checks_run))
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(prog="driver-extension-signing-audit.py")
    parser.add_argument("--self-test", action="store_true",
                        help="drive the rule with fabricated trees, so the gate proves both colours")
    parser.add_argument("--root", default=None)
    # The other scripts in this directory take the repository as a bare argument, so accept both
    # spellings: a gate that only answers to one of them is a gate somebody runs from the wrong
    # directory and reads as a pass.
    parser.add_argument("legacy_root", nargs="?", default=None)
    args = parser.parse_args()
    root = os.path.abspath(args.root or args.legacy_root or ROOT)
    if args.self_test:
        return self_test()

    workflow = read(root, WORKFLOW)
    # An audit that silently reads nothing is an audit that passes. The file being checked has to
    # look like the thing it claims to be before its contents can be trusted to clear anything.
    print("reading %s (%d bytes)" % (WORKFLOW, len(workflow)))
    if "jobs:" not in workflow or len(workflow) < 1000:
        print("::error file=%s::the workflow this audit reads is missing or truncated, so its "
              "signing steps cannot be confirmed" % WORKFLOW)
        return 1

    evidence = extension_evidence(root, tracked_files(root))
    print("stage 3 traces: %s" % (describe(evidence) or "none in the tree"))
    present = [what for what, pattern, _ in REQUIREMENTS if pattern.search(workflow)]
    print("signing steps in the workflow: %s" % (", ".join(present) if present else "none"))

    problems = 0
    gaps_found = gaps(evidence, workflow)
    for gap in gaps_found:
        print("::error::%s" % gap)
    problems += len(gaps_found)

    # The one rule that holds whatever else happens: an extension cannot be asked for by a build
    # that nobody notarised, whether it arrives as a target, a source file or an entitlement.
    print("driver-extension signing: %s"
          % ("no stage 3 artefact to sign, and no signing step claimed" if not has_stage3(evidence)
             and not gaps_found else
             ("a signed and notarised path exists for every stage 3 artefact" if not gaps_found
              else "%d gap(s) between what the tree builds and what the workflow signs"
                   % len(gaps_found))))
    print("%d driver-extension signing failures" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
