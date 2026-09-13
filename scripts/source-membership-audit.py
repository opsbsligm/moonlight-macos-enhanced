#!/usr/bin/env python3
"""Fail when a source file exists but no target compiles it.

Limelight is a file system synchronized group, and its membership exception
list is the explicit member list in this project: a source file that appears
neither in that list nor as a file reference elsewhere in the project file is
silently excluded from the build. That is how NetworkPermissionManager.swift
shipped nothing for months, with no build error and no test signal.

Entries are compared as whole paths or whole file names. Directory prefixes
are never used, because macOS/ViewControllers/ also occurs inside other
entries and would hide a genuine orphan.
"""
import os, re, sys

root = sys.argv[1] if len(sys.argv) > 1 else "."
source_root = os.path.join(root, "Limelight")
pbx_path = os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj")
IMPL_SUFFIXES = (".m", ".mm", ".c", ".swift")

project = open(pbx_path, encoding="utf-8").read()

def normalize(value):
    value = value.strip()
    if value.endswith(","):
        value = value[:-1].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.lstrip("/")

entries = set()

for block in re.findall(r"membershipExceptions = \((.*?)\n\t*\);", project, re.S):
    for line in block.splitlines():
        if line.strip():
            entries.add(normalize(line))

for path in re.findall(r"^\s*path = (\"[^\"]*\"|[^;]+);", project, re.M):
    entries.add(normalize(path))

entries.discard("")
entry_basenames = {os.path.basename(entry) for entry in entries}

paths = []
for base, _, files in os.walk(source_root):
    for name in files:
        if name.endswith(IMPL_SUFFIXES):
            paths.append(os.path.join(base, name))

# Files that legitimately produce no object code inside an app target. Each
# entry needs a reason, and the audit fails if the reason goes stale.
EXCLUSIONS = {
    "Limelight/Input/OnScreenControls.m":
        "upstream iOS-only overlay; the macOS target draws its own stream view",
    "Limelight/Input/StreamView.m":
        "upstream iOS-only view, companion to OnScreenControls.m",
    "Limelight/macOS/Helpers/AwdlPrivilegedHelperMain.m":
        "built by scripts/build_awdl_privileged_helper.sh into the privileged "
        "helper binary instead of the app sources phase",
}

orphans, stale = [], []
for path in sorted(paths):
    rel_to_root = os.path.relpath(path, root)
    compiled = (os.path.relpath(path, source_root) in entries
                or os.path.basename(path) in entry_basenames)
    if compiled and rel_to_root in EXCLUSIONS:
        stale.append(rel_to_root)
    elif not compiled and rel_to_root not in EXCLUSIONS:
        orphans.append(rel_to_root)

print("source membership: %d implementation files checked against %d project "
      "entries, %d documented exclusions"
      % (len(paths), len(entries), len(EXCLUSIONS)))
for orphan in orphans:
    print("::error file=%s::source file is not a member of any target, is not "
          "excluded on purpose, and will never be compiled" % orphan)
for entry in stale:
    print("::error file=%s::file is now a target member; drop it from the "
          "exclusion list in this script" % entry)

if orphans or stale:
    sys.exit(1)
print("every implementation file is either compiled or excluded with a reason")
