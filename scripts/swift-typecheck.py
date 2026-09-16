#!/usr/bin/env python3
"""Type-check the Swift half of the app, the way compile-audit does the C half.

A fix to the settings page's keyboard hand-back reached three failing jobs before
anybody learned what was wrong with it: it asked an ``NSResponder`` which window it
belonged to, and only a view, or the window itself, can answer that. Nothing in the
tree could see it. The syntax parse accepted the line, because parsing never
resolves a member lookup, and the source audit accepted it, because the source audit
reads shape rather than types. Twelve minutes of CI was the only answer this tree
had.

The Command Line Tools ship a Swift compiler and SDK that run without Xcode's
licence, and the aggregate already compiles every Objective-C source against every
installable SDK, so the Swift half was the last half nobody checked until a runner
did. This is that check: one ``swiftc -typecheck`` per installable SDK, over the
project's own Swift files, with the project's own bridging header and the same
vendored include paths compile-audit uses.

Two things about this host shape the design, and both are reported rather than
hidden. A ``#Preview`` block needs a macro plugin that ships with Xcode and not with
the Command Line Tools, so the trailing preview block of one file is taken out of
the copy that gets checked -- and a preview block that is not the tail of its file
refuses to be taken out, because a check that silently drops a region of the tree is
worse than no check at all. The 27 SDK needs a plugin for ``@State`` with the same
problem, so an SDK whose only complaints are missing plugins is reported as skipped,
while any other error in the same output is reported as the failure it is.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

MACRO_GAP = re.compile(r"plugin for module '(\w+)' not found")
ERROR_LINE = re.compile(r"^\s*(\S+?):(\d+):(\d+): error: (.*)$")
PREVIEW = re.compile(r"^#Preview\b")


def parse_arguments(argv):
    """root, self-test, and whether the host was asked to say what it found."""
    arguments = list(argv)
    self_test = "--self-test" in arguments
    explain = "--list-sdk" in arguments
    arguments = [a for a in arguments if a not in ("--self-test", "--list-sdk")]
    return (arguments[0] if arguments else "."), self_test, explain


def include_module():
    """compile-audit.py, loaded as a module: it owns the vendored include paths.

    Two scripts that each walked xcframeworks would drift the way the keyboard
    consumers drifted, and a Swift check with a shorter include list would fail on a
    header that the C half can already find.
    """
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compile-audit.py")
    spec = importlib.util.spec_from_file_location("compile_audit_for_swift", path)
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = [path]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


def strip_preview(text):
    """The text without a trailing #Preview block, plus what was given up.

    Returns ``(text, stripped_plugins, uncheckable)``. Only a block that runs to the
    end of its file is removed; anything after it is product code that would be lost
    from the check along with the block, so that file is reported instead.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not PREVIEW.match(line):
            continue
        depth = 0
        seen = False
        for offset in range(index, len(lines)):
            depth += lines[offset].count("{") - lines[offset].count("}")
            seen = seen or "{" in lines[offset]
            if seen and depth <= 0:
                end = offset
                break
        else:
            return text, set(), "a #Preview block at line %d never closes" % (index + 1)
        if any(line.strip() for line in lines[end + 1:]):
            return (text, set(),
                    "a #Preview block at line %d is not the tail of its file, so "
                    "removing it would drop code from the check" % (index + 1))
        return ("\n".join(lines[:index]), {"SwiftUI"},
                None)
    return text, set(), None


def classify(output):
    """Split compiler output into real errors, macro gaps, and the knock-on.

    Three outcomes have to be told apart, not two. "no plugin for SwiftUIMacros" says
    this host cannot run the check. Every other error says the tree is broken. And a
    macro that could not be expanded breaks the code around it: a ``@State`` property
    that never became a property wrapper stops being assignable, and the compiler
    reports "left side of mutating operator isn't mutable" at the lines that use it,
    in the same file, in the same place the missing plugin was named. A rule that
    called those errors defects would be red on the machine that has no plugin at all
    -- which is every machine that has no Xcode -- and a rule that skipped a whole run
    the moment any plugin was missing would let a real defect travel inside the noise.
    So the gap is tracked per file, and an error is only forgiven where the compiler
    had already said it could not see the macro that file uses.
    """
    gaps, gap_files, errors, knockon = set(), set(), [], []
    for line in output.splitlines():
        match = ERROR_LINE.search(line)
        if not match:
            continue
        path, line_no, column, message = match.groups()
        gap = MACRO_GAP.search(message)
        if gap:
            gaps.add(gap.group(1))
            gap_files.add(path)
            continue
        entry = "%s:%s:%s: %s" % (path, line_no, column, message)
        (knockon if path in gap_files else errors).append(entry)
    return gaps, gap_files, errors, knockon


def swift_sources(root):
    paths = []
    for directory, _, names in os.walk(os.path.join(root, "Limelight")):
        paths += [os.path.join(directory, name) for name in sorted(names)
                  if name.endswith(".swift")]
    return sorted(paths)


def check_tree(root, swiftc, sdk, includes, bridging_header):
    """Type-check the tree. Returns (status, detail) with status in
    clean, failed, skipped."""
    work = tempfile.mkdtemp(prefix="swift-typecheck-")
    try:
        prepared, gaps, refused = [], set(), []
        for source in swift_sources(root):
            text = open(source, encoding="utf-8", errors="replace").read()
            text, plugins, refusal = strip_preview(text)
            gaps |= plugins
            if refusal:
                refused.append("%s: %s" % (os.path.relpath(source, root), refusal))
            prepared.append(os.path.join(work, os.path.relpath(source, root)
                                         .replace(os.sep, "__")))
            open(prepared[-1], "w", encoding="utf-8").write(text)
        if refused:
            return ("failed", "the check would have to drop these to run:\n  "
                    + "\n  ".join(refused))
        out = subprocess.run(
            [swiftc, "-typecheck", "-sdk", sdk, "-import-objc-header", bridging_header,
             "-parse-as-library"] + includes + prepared,
            capture_output=True, text=True, cwd=root)
        macro_gaps, gap_files, errors, knockon = classify(
            (out.stdout or "") + (out.stderr or ""))
        if errors:
            return ("failed", "%d type error(s) outside any macro gap:\n  %s"
                    % (len(errors), "\n  ".join(errors[:12])))
        if macro_gaps:
            return ("skipped", "no macro plugin for %s on this SDK; %d file(s) and "
                    "%d dependent error(s) could not be read"
                    % (", ".join(sorted(macro_gaps)), len(gap_files), len(knockon)))
        return ("clean", "%d files" % len(prepared))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def probe(swiftc, sdk, name, body):
    """Type-check one small file of known shape. Returns (exit, output)."""
    path = os.path.join(tempfile.mkdtemp(prefix="swift-probe-"), name)
    try:
        open(path, "w").write(body)
        out = subprocess.run([swiftc, "-typecheck", "-sdk", sdk, path],
                             capture_output=True, text=True)
        return out.returncode, (out.stdout or "") + (out.stderr or "")
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


GOOD_PROBE = """import AppKit
final class Probe {
  let window: NSWindow
  var savedFirstResponder: NSResponder?
  init(window: NSWindow) { self.window = window }
  func restore() {
    if let savedFirstResponder,
       (savedFirstResponder as? NSView)?.window === window
         || savedFirstResponder === window {
      window.makeFirstResponder(savedFirstResponder)
    } else {
      window.makeFirstResponder(window.contentView)
    }
  }
}
"""

BAD_PROBE = """import AppKit
final class Probe {
  let window: NSWindow
  var savedFirstResponder: NSResponder?
  init(window: NSWindow) { self.window = window }
  func restore() {
    if let savedFirstResponder, savedFirstResponder.window == window {
      window.makeFirstResponder(savedFirstResponder)
    } else {
      window.makeFirstResponder(window.contentView)
    }
  }
}
"""

CI_REFUSAL = """value of type 'NSResponder' has no member 'window'
/Users/runner/work/x/Limelight/macOS/ViewControllers/LiquidGlass/\
SettingsOverlayPresenter.swift:185:53: error: value of type 'NSResponder' has no \
member 'window'
"""

PLUGIN_NOISE = ("work/Stream.swift:46:32: error: external macro implementation type "
                "'SwiftUIMacros.StateMacro' could not be found for macro 'State()'; "
                "plugin for module 'SwiftUIMacros' not found\n")

KNOCK_ON = PLUGIN_NOISE + (
    "work/Stream.swift:117:29: error: left side of mutating operator isn't mutable: "
    "'self' is immutable\n")

GAP_AND_DEFECT = PLUGIN_NOISE + (
    "work/Stream.swift:117:29: error: left side of mutating operator isn't mutable: "
    "'self' is immutable\n"
    "other/File.swift:9:1: error: value of type 'NSResponder' has no member 'window'\n")


def self_test():
    """Both directions, including the one this gate was written because of."""
    problems = []

    def check(ok, message):
        if not ok:
            problems.append(message)
        print("%s %s" % ("ok  " if ok else "FAIL", message))

    gaps, gap_files, errors, knockon = classify(CI_REFUSAL)
    check(len(errors) == 1 and not gaps and not knockon,
          "the mistake that reached CI is counted as a type error, not noise")
    gaps, gap_files, errors, knockon = classify(PLUGIN_NOISE)
    check(bool(gaps) and not errors and not knockon,
          "a missing macro plugin is counted as a host gap, not a defect")
    gaps, gap_files, errors, knockon = classify(KNOCK_ON)
    check(bool(gaps) and not errors and len(knockon) == 1
          and gap_files == {"work/Stream.swift"},
          "an error beside a macro the host could not expand is the gap, not a defect")
    gaps, gap_files, errors, knockon = classify(GAP_AND_DEFECT)
    check(bool(gaps) and len(errors) == 1 and "other/File.swift" in errors[0],
          "a real defect is not forgiven because another file lost a plugin")

    checked, plugins, refusal = strip_preview(
        "struct A { var x = 1 }\n#Preview {\n  Text(\"a\")\n}\n")
    check("A" in checked and "Preview" not in checked and plugins == {"SwiftUI"}
          and refusal is None, "a trailing preview block comes out of the copy")
    checked, plugins, refusal = strip_preview(
        "#Preview {\n  Text(\"a\")\n}\nstruct B { var y = 2 }\n")
    check(refusal is not None and "B" in checked,
          "a preview block with code after it is refused, not dropped")
    checked, plugins, refusal = strip_preview("struct C { }\n")
    check(refusal is None and not plugins, "a file with no preview is left alone")
    checked, plugins, refusal = strip_preview("#Preview {\n  Text(\"a\")\n")
    check(refusal is not None, "a preview block that never closes is reported")

    pair = apple_toolchain.swiftc_and_sdk("the Swift type check")
    if pair is None:
        print("skip the probe half of the self-test: no Swift compiler on this host")
    else:
        swiftc, sdk = pair
        code, out = probe(swiftc, sdk, "good.swift", GOOD_PROBE)
        check(code == 0 and not classify(out)[2],
              "the shape that fixed the bug type-checks clean")
        code, out = probe(swiftc, sdk, "bad.swift", BAD_PROBE)
        errors = classify(out)[2]
        check(code != 0 and any("has no member 'window'" in e for e in errors),
              "the shape that reached CI is refused by this gate")
    return problems


def main(argv):
    root, run_self_test, explain = parse_arguments(argv)
    if run_self_test:
        problems = self_test()
        print("%d swift type-check self-test failures" % len(problems))
        return 1 if problems else 0

    pair = apple_toolchain.swiftc_and_sdk("the Swift type check")
    if pair is None:
        print("swift type-check skipped: this host has no Swift compiler and SDK pair")
        return 0
    swiftc, default_sdk = pair
    audit = include_module()
    usable, too_old = audit.usable_sdks(default_sdk)
    if explain:
        for path in usable:
            print("sdk %s" % os.path.basename(path))
        for path in too_old:
            print("sdk %s is older than the deployment target" % os.path.basename(path))
        return 0

    bridging = os.path.join(root, "Limelight", "Moonlight-Bridging-Header.h")
    if not os.path.exists(bridging):
        print("swift type-check failed: no bridging header at %s" % bridging)
        return 1

    failures, skipped, reports = [], [], []
    for sdk in usable:
        name = os.path.basename(sdk)
        status, detail = check_tree(root, swiftc, sdk,
                                    audit.include_dirs(sdk), bridging)
        reports.append("%-18s %s (%s)" % (name, status, detail.splitlines()[0]))
        if status == "failed":
            failures.append("%s: %s" % (name, detail))
        elif status == "skipped":
            skipped.append("%s: %s" % (name, detail))
    for line in reports:
        print(line)
    if failures:
        print("\n".join(failures))
        return 1
    if skipped and len(skipped) == len(usable):
        print("swift type-check skipped: every usable SDK needs a macro plugin "
              + "this host does not have")
    for line in skipped:
        print("skip %s" % line)
    print("swift type check: %d of %d SDKs checked"
          % (len(usable) - len(skipped), len(usable)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
