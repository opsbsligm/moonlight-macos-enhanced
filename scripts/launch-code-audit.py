#!/usr/bin/env python3
"""Fail when a shipped bundle carries code the loader cannot trust.

Nothing read the signature back. The build packaged, tarred, wrapped and
published a bundle whose main executable carried no signature at all, whose two
vendored frameworks carried the upstream signature over a layout this repository
had since changed -- `lipo -create` replaces a signed binary during the
universal merge, and the framework headers the old seal listed are not shipped
at all -- so every one of them failed `codesign --verify` with `file missing`,
and the main binary failed it with `code object is not signed at all`. On Apple
Silicon a framework the loader will not accept is a crash with no source line,
and a release page cannot say which shape a download has.

Two rules, both read from the bundle rather than from the build log: every Mach-O
inside must verify, and the bundle itself must verify, which is the seal that
makes tampering detectable.

The identity is reported and not demanded. This project has no Developer ID and
nothing is notarized, so `spctl` rejects it and always will; asserting otherwise
would keep a gate red for a fact about certificates nobody here owns, which is
indistinguishable from a gate that never passes.

The self-test compiles its own bundles: a signed one passes, an unsigned one is
refused, and a resource added after signing breaks the seal and is refused.
"""
import argparse, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CODESIGN = shutil.which("codesign") or "/usr/bin/codesign"
# The four Mach-O magics, host- and byte-order-swapped, plus fat.
MACHO_MAGICS = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                b"\xbf\xfa\xed\xfe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca",
                b"\xca\xfe\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce")


def macho_objects(bundle):
    """Every Mach-O in the bundle: the ones a loader can be asked to accept."""
    found = []
    for base, _, files in os.walk(bundle):
        for name in sorted(files):
            path = os.path.join(base, name)
            try:
                with open(path, "rb") as handle:
                    head = handle.read(4)
            except OSError:
                continue
            if head in MACHO_MAGICS:
                found.append(path)
    return found


def verify(target):
    result = subprocess.run([CODESIGN, "--verify", "--strict", target],
                            capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def audit(bundle):
    """Return the list of ways this bundle's code cannot be trusted."""
    problems = []
    if not os.path.isdir(bundle):
        raise SystemExit("error: %s is not a directory, so there is no bundle to read"
                         % bundle)
    if not os.path.exists(CODESIGN):
        raise SystemExit("error: %s is missing, so no signature could be read. That is an "
                         "environment problem, not a defect in the bundle." % CODESIGN)
    objects = macho_objects(bundle)
    if not objects:
        problems.append("%s holds no Mach-O at all, so nothing in it could run" % bundle)
    for path in objects:
        ok, detail = verify(path)
        if not ok:
            problems.append("%s does not verify: %s"
                            % (os.path.relpath(path, bundle), detail.splitlines()[-1]
                               if detail else "no reason given"))
    ok, detail = verify(bundle)
    if not ok:
        problems.append("the bundle itself does not verify -- nothing seals it, so a changed "
                        "byte inside would go unnoticed: %s"
                        % (detail.splitlines()[-1] if detail else "no reason given"))
    return objects, problems


def report_identity(bundle):
    """Say what the signature is, since `ad-hoc` and `Developer ID` are not the same promise."""
    result = subprocess.run([CODESIGN, "-dvv", bundle], capture_output=True, text=True)
    text = result.stderr + result.stdout
    wanted = ("Signature", "TeamIdentifier", "Sealed Resources", "flags")
    for line in text.splitlines():
        if line.startswith(wanted):
            print("  %s" % line.strip())
    spctl = shutil.which("spctl")
    if spctl:
        verdict = subprocess.run([spctl, "-a", "-t", "install", bundle],
                                 capture_output=True, text=True)
        assessment = (verdict.stdout + verdict.stderr).strip().splitlines()
        print("  Gatekeeper: %s (reported, not asserted: this project has no Developer ID "
              "and notarizes nothing)"
              % (assessment[-1] if assessment else "no verdict"))


def expect(what, should_pass):
    _, problems = audit(what)
    if should_pass and problems:
        raise AssertionError("refused a bundle it should accept (%s): %s"
                             % (what, problems[0]))
    if not should_pass and not problems:
        raise AssertionError("accepted %s; a signature gate that accepts it is not a gate"
                             % what)
    print("%s %s" % ("accepts" if should_pass else "rejects",
                     os.path.basename(what) + ("" if should_pass else " -- "
                                               + (problems[0][:78] if problems else ""))))


def build_bundle(directory, clang, sdk, name):
    """Compile a throwaway .app so the gate is tested against real Mach-O bytes."""
    app = os.path.join(directory, name + ".app")
    os.makedirs(os.path.join(app, "Contents", "MacOS"))
    source = os.path.join(directory, name + ".c")
    with open(source, "w") as handle:
        handle.write("int main(void) { return 0; }\n")
    binary = os.path.join(app, "Contents", "MacOS", name)
    subprocess.run([clang, "-isysroot", sdk, source, "-o", binary], check=True)
    with open(os.path.join(app, "Contents", "Info.plist"), "w") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                     '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                     '<plist version="1.0"><dict>'
                     '<key>CFBundleExecutable</key><string>%s</string>'
                     '<key>CFBundleIdentifier</key><string>audit.selftest.%s</string>'
                     '<key>CFBundlePackageType</key><string>APPL</string>'
                     '</dict></plist>\n' % (name, name))
    return app


def self_test():
    import apple_toolchain  # the same module the behavioural harnesses use
    clang, sdk = apple_toolchain.clang_and_sdk("the signature self-test")
    workspace = tempfile.mkdtemp(prefix="launch-code-audit-")
    try:
        signed = build_bundle(workspace, clang, sdk, "Signed")
        subprocess.run([CODESIGN, "--force", "--sign", "-", signed],
                       check=True, capture_output=True)
        expect(signed, True)

        unsigned = build_bundle(workspace, clang, sdk, "Unsigned")
        expect(unsigned, False)

        # A byte added after signing has to break the seal, which is the whole
        # reason a shipped bundle is sealed in the first place.
        tampered = build_bundle(workspace, clang, sdk, "Tampered")
        subprocess.run([CODESIGN, "--force", "--sign", "-", tampered],
                       check=True, capture_output=True)
        with open(os.path.join(tampered, "Contents", "extra.txt"), "wb") as handle:
            handle.write(b"added after the seal was taken\n")
        expect(tampered, False)
        print("self-test passed")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report-identity", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.bundle:
        parser.error("no bundle to read; pass a .app or --self-test")
    objects, problems = audit(args.bundle)
    if args.report_identity:
        report_identity(args.bundle)
    if problems:
        raise SystemExit("error: %s carries code a loader cannot accept:\n  "
                         % args.bundle + "\n  ".join(problems))
    print("ok %d Mach-O object(s) verified, and the bundle is sealed" % len(objects))


if __name__ == "__main__":
    main()
