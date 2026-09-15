#!/usr/bin/env python3
"""Fail when a first-party class never reaches the shipped binary.

source-membership-audit.py reads the project file, which is a claim about the
build, not the build. This script reads the linked Mach-O instead: the
__objc_classname table lists every Objective-C class the linker actually put in
the binary, so a source file that the project file mentions but no target
compiles cannot pass here.

The gap is real. GlassOverlayContainer.m was committed with the log browser
wired to it, passed a standalone harness compile, and appeared in no build:
the project file lists every compiled source in its membership exception list,
a new file that is absent from that list belongs to no target, so nothing
compiled it and nothing failed. The check below catches that class of bug from
the artifact, where a missing file cannot hide.

Swift types are not covered: their names are mangled and live in a different
section, and a half-read of that section would report success on a build that
dropped a file. The membership audit covers Swift by name in the project file.
"""
import argparse, os, re, subprocess, sys

TOOLCHAIN = "/Library/Developer/CommandLineTools/usr/bin"
OTOOL = os.environ.get("OTOOL", os.path.join(TOOLCHAIN, "otool"))
LIPO = os.environ.get("LIPO", os.path.join(TOOLCHAIN, "lipo"))
IMPL_SUFFIXES = (".m", ".mm")
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

# Declarations that do not add a class to the binary. A category or a class
# extension hangs off a class declared elsewhere, so demanding a new name for it
# would fail a build that is entirely correct.
CATEGORY = re.compile(r"@implementation\s+[A-Za-z_$][A-Za-z0-9_$]*\s*\(")
CLASS_NAME = re.compile(r"@implementation\s+([A-Za-z_$][A-Za-z0-9_$]*)")


def declared_classes(source_root, exclusions):
    """Map every declared class name to the file that declares it."""
    found, skipped = {}, []
    for base, _, files in os.walk(source_root):
        for name in sorted(files):
            if not name.endswith(IMPL_SUFFIXES):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, os.path.dirname(source_root.rstrip("/")))
            if rel in exclusions:
                skipped.append(rel)
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            for line in text.splitlines():
                if CATEGORY.search(line):
                    continue
                match = CLASS_NAME.search(line)
                if match:
                    found.setdefault(match.group(1), rel)
    return found, skipped


def arch_slices(binary):
    """The architectures a Mach-O carries, as `lipo` sees them."""
    info = subprocess.run([LIPO, "-archs", binary], capture_output=True, text=True)
    if info.returncode != 0:
        raise SystemExit("error: %s could not be read (%s), so this audit cannot tell "
                         "what was compiled" % (binary, info.stderr.strip() or "no reason"))
    return info.stdout.split()


def class_names_in(binary, arch, tmpdir=None):
    """Return the exact __objc_classname table of one architecture slice.

    The slice matters, and so does the shape of the file it arrives in. A
    per-architecture build hands over a thin binary and the release job a fat one:
    asking `lipo -info` whether the word fat appears in its answer is not a way to
    tell them apart, because a single-architecture file answers "Non-fat", and the
    first version of this audit then tried to thin a file that had one slice and
    died on both build jobs while passing at home on a universal artifact.
    """
    slices = arch_slices(binary)
    target = binary
    if arch:
        if arch not in slices:
            raise SystemExit("error: %s carries %s and not the %s slice this job was "
                             "asked to check, so nothing compiled here can be read "
                             "from it" % (binary, " ".join(slices) or "no slice at all",
                                          arch))
        if len(slices) > 1:
            import tempfile
            handle, thin = tempfile.mkstemp(prefix="compiled-source-audit-")
            os.close(handle)
            subprocess.run([LIPO, "-thin", arch, "-output", thin, binary], check=True,
                           capture_output=True)
            target = thin
    load = subprocess.run([OTOOL, "-l", target], capture_output=True, text=True,
                          check=True).stdout
    sections, current = {}, None
    for line in load.splitlines():
        name = re.match(r"\s*sectname (\S+)", line)
        if name:
            current = name.group(1)
            sections[current] = {}
            continue
        if current:
            size = re.match(r"\s*size 0x([0-9a-f]+)", line)
            offset = re.match(r"\s*offset (\d+)", line)
            if size:
                sections[current]["size"] = int(size.group(1), 16)
            if offset:
                sections[current]["offset"] = int(offset.group(1))
            if re.match(r"\s*reloff", line):
                current = None
    if "__objc_classname" not in sections:
        raise SystemExit("error: %s has no __objc_classname section, so this audit "
                         "cannot tell what was compiled" % target)
    info = sections["__objc_classname"]
    blob = open(target, "rb").read()[info["offset"]:info["offset"] + info["size"]]
    # The table is padding-terminated, so trailing bytes are not a class name.
    return {token.decode("utf-8", "replace") for token in blob.split(b"\x00")
            if token and IDENTIFIER.match(token.decode("latin-1"))}


def load_exclusions(root):
    """Reuse the exclusions that justify themselves in the membership audit."""
    script = os.path.join(root, "scripts", "source-membership-audit.py")
    text = open(script, encoding="utf-8").read()
    block = re.search(r"EXCLUSIONS = \{(.*?)\n\}", text, re.S)
    return set(re.findall(r'"([^"]+)"', block.group(1))) if block else set()


def missing_from(declared, present):
    return sorted(name for name in declared if name not in present)


def self_test(binary, arch, root):
    """Prove the comparison can answer no, on the real artifact."""
    declared, skipped = declared_classes(os.path.join(root, "Limelight"),
                                         load_exclusions(root))
    present = class_names_in(binary, arch)
    failures = []
    if not declared or not present:
        failures.append("the audit found %d declared classes and %d classes in the "
                        "binary; an empty side proves nothing"
                        % (len(declared), len(present)))
    # A name nobody declares has to be reported as missing, or the comparison is
    # decoration: a check that cannot fail is the shape that let an uncompiled
    # file ship in the first place.
    fabricated = "CompiledSourceAuditAbsentClass"
    if missing_from({fabricated: "fixture"}, present) != [fabricated]:
        failures.append("a class that is not in the binary was not reported missing")
    # Most first-party classes are in the binary, so a table read that returns
    # unrelated names would be visible here as an implausibly low overlap.
    overlap = len(present & set(declared))
    if overlap < len(declared) * 0.5:
        failures.append("only %d of %d declared classes appear in the binary; the "
                        "section was probably read wrongly" % (overlap, len(declared)))
    # An artifact that does not carry the slice under test is a different question,
    # and answering it with the other slice's class list would report a defect that
    # is not in this build -- or hide one that is.
    try:
        class_names_in(binary, "ppc64-never-built")
        failures.append("an architecture the binary does not carry was accepted")
    except SystemExit as refused:
        if "slice" not in str(refused):
            failures.append("the missing slice was refused for the wrong reason: %s"
                            % refused)
    # Padding bytes at the end of the table must not count as classes.
    if any(not IDENTIFIER.match(name) for name in present):
        failures.append("a non-identifier was counted as a class name")
    for name in failures:
        print("::error::self-test failed: %s" % name)
    if failures:
        return 1
    print("compiled source self-test: %d classes declared, %d in the binary, "
          "%d declared files excluded with a reason, and a class that is absent "
          "is reported as absent" % (len(declared), len(present), len(skipped)))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", nargs="?")
    parser.add_argument("--arch", default=None)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = args.root
    if args.self_test:
        if not args.binary or not os.path.exists(args.binary):
            print("::error::--self-test needs a built binary to read")
            return 1
        return self_test(args.binary, args.arch, root)

    if not args.binary or not os.path.exists(args.binary):
        print("::error::usage: compiled-source-audit.py <binary> [--arch arm64]")
        return 1

    declared, _ = declared_classes(os.path.join(root, "Limelight"),
                                   load_exclusions(root))
    present = class_names_in(args.binary, args.arch)
    missing = missing_from(declared, present)
    print("compiled source audit: %d first-party classes declared, %d class names "
          "in the binary, %d missing" % (len(declared), len(present), len(missing)))
    for name in missing:
        print("::error file=%s::class %s is declared in the sources but is not in "
              "the linked binary, so nothing compiled that file"
              % (declared[name], name))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
