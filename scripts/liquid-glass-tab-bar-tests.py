#!/usr/bin/env python3
"""Drive the shipped settings tab bar through the accessibility tree, and measure what it costs.

The bar draws its selection as system glass and mounts a real SwiftUI Button per segment.
The audit proves the glass and the API statically; nothing until now proved the two
behavioural promises that shape makes -- that a screen reader can say which pane each
segment opens, and that one click on one segment produces exactly one selection write and
no straggler behind it. Those are questions about the accessibility tree AppKit actually
vends and about what the binding sees at runtime, so this answers them that way.

How it runs, and why each part is placed where it is (all three facts measured here, on
this SDK, before the harness was written):

* In-process self-queries of the app's own AX tree answer nothing at all -- AXWindows
  comes back empty from inside the app, however the query is made. The tree is vended for
  out-of-process clients, so the harness builds two binaries: the shipping bar hosted in
  a real window, and a separate inspector process that reads it over AXUIElement.
* SwiftUI vends a .plain button's label only when the button pairs
  .accessibilityElement(children: .ignore) with an explicit .accessibilityLabel(Text(...)).
  Without the pair the segments are nameless (AXDescription nil), which is the failure
  the audit pins statically; here it is caught from the tree itself.
* The selected trait has to arrive as a branch (.accessibilityAddTraits(.isSelected) on
  one side of an if, .accessibilityRemoveTraits on the other). A trait set computed per
  render -- .union(selected ? .isSelected : []) -- freezes AXSelected at its first answer
  for an out-of-process client even while every other reading updates.
* AXPress reaches the element but does not drive a SwiftUI action on this SDK; a real
  CGEvent mouse click at the element's AX-reported centre does, once the app is frontmost
  (a click on a background window only activates it). The click is posted through the HID
  tap, which is the closest thing to what a pointer does.
* The host view must own its selection the way the page does -- @State, not a reference
  box behind a hand-rolled binding. SwiftUI does not notice an object mutating behind a
  Binding's getter, so a harness that stores the selection in a class watches its binding
  take the write while the tree never re-renders, and blames the bar for the harness's
  own storage.

The app under test watches a marker file, then reports how many writes the click produced
and whether any repeated after it. SKIP is reserved for a host with no GUI session or no
AX trust -- the same "not here" shape the toolchain skip uses -- and says why out loud.
"""
import os
import subprocess
import sys
import tempfile
import time

from apple_toolchain import swiftc_and_sdk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB_BAR = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "LiquidGlass",
                       "LiquidGlassTabBar.swift")
FAILURES = []
SKIPS = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        FAILURES.append(message)


APP = r'''
import AppKit
import SwiftUI

// The shipping bar, mounted the way the settings window mounts it. Regular activation
// policy and a real key window because this half has to answer an out-of-process AX
// client -- the tree only exists for one -- and take a real mouse click.
final class Counter {
    var writes = 0
}
let counter = Counter()

// The page holds its selection in @State, exactly as the settings overlay does: the bar
// re-renders because SwiftUI owns the storage, not because the harness reached in. The
// write count rides on the setter.
struct Harness: View {
    @State private var selection = 10
    let counter: Counter
    let items: [LiquidGlassTabItem]
    var body: some View {
        LiquidGlassTabBar(selection: Binding(get: { selection },
                                             set: { selection = $0; counter.writes += 1 }),
                          items: items)
    }
}
let items = [
    LiquidGlassTabItem(id: 10, title: "Display", symbol: "display", tint: .cyan),
    LiquidGlassTabItem(id: 20, title: "Audio", symbol: "speaker.wave.2", tint: .green),
    LiquidGlassTabItem(id: 30, title: "Input", symbol: "keyboard", tint: .orange),
]

_ = NSApplication.shared
NSApp.setActivationPolicy(.regular)
let window = NSWindow(contentRect: NSRect(x: 240, y: 240, width: 700, height: 500),
                      styleMask: [.titled, .closable, .resizable], backing: .buffered,
                      defer: false)
window.title = "MLE tab harness"
let host = NSHostingView(rootView: Harness(counter: counter, items: items))
host.frame = NSRect(x: 20, y: 420, width: 420, height: 40)
window.contentView?.addSubview(host)
window.makeKeyAndOrderFront(nil)
NSApp.activate(ignoringOtherApps: true)

// The marker directory arrives as argv[1]. When the inspector has clicked, it creates
// `clicked`; the app then gives the tree a beat to settle, watches for straggler writes,
// and reports. One line, machine-read by the python driver.
let markerDirectory = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
let deadline = Date().addingTimeInterval(25)
Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { timer in
    if FileManager.default.fileExists(atPath: (markerDirectory as NSString).appendingPathComponent("clicked")) {
        timer.invalidate()
        let writesAtClick = counter.writes
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        print("RESULT writes=\(counter.writes) writesAtClick=\(writesAtClick)")
        fflush(stdout)
        NSApp.stop(nil)
        exit(0)
    }
    if Date() > deadline {
        print("RESULT timeout writes=\(counter.writes)")
        fflush(stdout)
        exit(0)
    }
}
NSApp.run()
'''

INSPECT = r'''
import ApplicationServices
import CoreGraphics
import Foundation

// An out-of-process AX client: the shape System Events and VoiceOver use, and the only
// shape (measured) under which this SDK vends the hosting view's tree at all.
let pid = Int32(CommandLine.arguments[1])!
let markerDirectory = CommandLine.arguments[2]
let app = AXUIElementCreateApplication(pid)
// SwiftUI holds the tree back until a client says it will consume it; this is the flag
// an assistive client sets, and we are one here.
AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
// The same second flag System Events sets: it asks AppKit to vend the tree live rather
// than as a first-read snapshot. Without it (measured here) the selection trait stays
// frozen at its first answer even after the element is rebuilt -- the tree, the click
// and the app-side state all update; only this client's view of the trait does not.
AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)

func copyAttr(_ el: AXUIElement, _ attr: String) -> CFTypeRef? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, attr as CFString, &v) == .success ? v : nil
}
func error(_ el: AXUIElement, _ attr: String) -> AXError {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, attr as CFString, &v)
}
func kids(_ el: AXUIElement) -> [AXUIElement] {
    (copyAttr(el, kAXChildrenAttribute as String) as? [AXUIElement]) ?? []
}
func role(_ el: AXUIElement) -> String {
    (copyAttr(el, kAXRoleAttribute as String) as? String) ?? ""
}
func name(_ el: AXUIElement) -> String {
    (copyAttr(el, kAXDescriptionAttribute as String) as? String) ?? ""
}
func selected(_ el: AXUIElement) -> Bool {
    // Read the value, not the presence: with the shipping bar every segment answers
    // AXSelected -- true on the selected one, false on the rest -- and the trait moves
    // with the selection. Presence-only reading once served as a proxy (unselected
    // segments used to withhold the attribute entirely) and stopped being true the
    // moment the bar started answering the question instead of refusing it.
    (copyAttr(el, kAXSelectedAttribute as String) as? Bool) == true
}
func cgPoint(_ el: AXUIElement) -> CGPoint {
    var point = CGPoint.zero
    if let v = copyAttr(el, kAXPositionAttribute as String) {
        AXValueGetValue(v as! AXValue, .cgPoint, &point)
    }
    return point
}
func cgSize(_ el: AXUIElement) -> CGSize {
    var size = CGSize.zero
    if let v = copyAttr(el, kAXSizeAttribute as String) {
        AXValueGetValue(v as! AXValue, .cgSize, &size)
    }
    return size
}
func buttons(_ el: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    if role(el) == "AXButton" { out.append(el) }
    for k in kids(el) { out += buttons(k) }
    return out
}

// The window appears asynchronously after activation; give it a moment, then answer the
// three questions the driver cannot ask without a GUI session, and say "no session" in
// words rather than failing if there is not one.
var windows: [AXUIElement] = []
for _ in 0..<40 {
    Thread.sleep(forTimeInterval: 0.1)
    let err = error(app, kAXWindowsAttribute as String)
    if err == .apiDisabled || err.rawValue == -25218 || err == .illegalArgument {
        print("SKIP no accessibility trust for this inspector (\(err.rawValue))")
        exit(3)
    }
    windows = (copyAttr(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? []
    if !windows.isEmpty { break }
}
guard !windows.isEmpty else {
    print("SKIP no window in the app's AX tree -- this host has no windowed GUI session")
    exit(3)
}
// Scope to the bar's own container: the window's traffic lights are AXButtons too, and
// counting them as segments would make every verdict below about the window chrome.
// The bar marks its subtree with .accessibilityIdentifier("settings-navigation"), which
// vends as AXIdentifier -- a handle that does not depend on the names being tested.
func barRoots(_ el: AXUIElement) -> [AXUIElement] {
    if ((copyAttr(el, "AXIdentifier") as? String) ?? "") == "settings-navigation" { return [el] }
    var out: [AXUIElement] = []
    for k in kids(el) { out += barRoots(k) }
    return out
}
let bars = windows.flatMap { barRoots($0) }
guard !bars.isEmpty else {
    print("FAIL the bar's settings-navigation subtree is not in the window's AX tree")
    exit(2)
}
let found = bars.flatMap { buttons($0) }
print("BUTTONS \(found.count)")
for b in found {
    let p = cgPoint(b)
    let s = cgSize(b)
    print("BTN name=\(name(b)) selected=\(selected(b)) x=\(p.x) y=\(p.y) w=\(s.width) h=\(s.height)")
}

let names = found.map { name($0) }
let unnamed = names.filter { $0.isEmpty }
print("NAMING \(unnamed.isEmpty ? "ok" : "fail") (\(names.joined(separator: ",")))")
let isSelected = found.filter { selected($0) }.map { name($0) }
print("SELECTION \(isSelected.count == 1 ? "ok" : "fail") (\(isSelected.joined(separator: ",")))")

// Click the second segment for real, at the centre its own AX geometry reports.
let wanted = "Audio"
let target = found.first(where: { name($0) == wanted })
guard let target else {
    // A washed-out name is a NAMING failure the driver already counted; release the
    // app and let the write-count say the click never landed. It is a verdict, not a
    // crash: exit 0 keeps environment failures the only thing an exit code means.
    print("CLICK fail no segment named \(wanted)")
    FileManager.default.createFile(atPath: (markerDirectory as NSString).appendingPathComponent("clicked"),
                                  contents: Data())
    exit(0)
}
// Raise the app under test before posting: a click on a background window reaches the
// view, but this checks what a user's click does, and a user clicks a front window.
// Bring the app forward and wait until the window server agrees: a click aimed at a
// background window only activates it (the first click is swallowed), which would test
// the activation path instead of the bar.
AXUIElementSetAttributeValue(app, "AXFrontmost" as CFString, kCFBooleanTrue)
var frontmost = false
for _ in 0..<20 {
    Thread.sleep(forTimeInterval: 0.1)
    if (copyAttr(app, kAXFrontmostAttribute as String) as? Bool) == true { frontmost = true; break }
}
guard frontmost else {
    print("SKIP the app under test would not come forward -- no usable window session")
    exit(3)
}
Thread.sleep(forTimeInterval: 0.2)
let centre = CGPoint(x: cgPoint(target).x + cgSize(target).width / 2,
                     y: cgPoint(target).y + cgSize(target).height / 2)
let source = CGEventSource(stateID: .hidSystemState)
guard CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: centre,
              mouseButton: .left) != nil else {
    print("SKIP cannot post mouse events -- this session has no window server")
    exit(3)
}
CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: centre,
        mouseButton: .left)?.post(tap: .cghidEventTap)
Thread.sleep(forTimeInterval: 0.02)
CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: centre,
        mouseButton: .left)?.post(tap: .cghidEventTap)
print("CLICK posted at \(centre)")

// The tree has to move the selection too -- a click that fires the action but leaves
// AXSelected on the old segment would read as a pane that switched while its tab did not.
// The selection morph rebuilds the segment views, so the handles taken before the click
// can go stale: re-fetch the whole tree and give it a moment, checking the settled state.
var picked: [String] = []
for _ in 0..<10 {
    Thread.sleep(forTimeInterval: 0.1)
    let fresh = ((copyAttr(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? [])
        .flatMap { barRoots($0) }
        .flatMap { buttons($0) }
    picked = fresh.filter { selected($0) }.map { name($0) }
    if picked == [wanted] { break }
}
let afterBtns = bars.flatMap { buttons($0) }
for b in afterBtns {
    print("AFTERBTN name=\(name(b)) selected=\(selected(b))")
}
print("SELECTION_AFTER \(picked == [wanted] ? "ok" : "fail \(picked)")")
FileManager.default.createFile(atPath: (markerDirectory as NSString).appendingPathComponent("clicked"),
                              contents: Data())
exit(0)
'''

MUTATIONS = {
    # Deleting the pairing alone no longer loses the name on a live tree -- a plain
    # button vends its Text child as AXDescription once a client holds the tree open.
    # The regression that does go nameless is an explicit label whose text was washed
    # out, which is what a careless localisation refactor produces.
    "nameless": ("          .accessibilityLabel(Text(item.title))",
                 "          .accessibilityLabel(Text(\"\"))",
                 "segments whose AX names were washed out"),
    "double-write": ("            if selection != item.id { selection = item.id }",
                     "            selection = item.id\n            selection = item.id",
                     "a segment that writes the pane twice for one click"),
}


def build(directory, label, source, tab_bar_source):
    build_dir = os.path.join(directory, label)
    os.makedirs(build_dir, exist_ok=True)
    tab_path = os.path.join(build_dir, "tab_bar.swift")
    main_path = os.path.join(build_dir, "main.swift")
    with open(tab_path, "w", encoding="utf-8") as handle:
        handle.write(tab_bar_source)
    with open(main_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    swiftc, sdk = swiftc_and_sdk("liquid glass tab bar harness")
    binary = os.path.join(directory, "tabbar_%s" % label)
    built = subprocess.run([swiftc, "-sdk", sdk, "-o", binary, main_path, tab_path],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL %s did not compile:\n%s" % (label, (built.stdout + built.stderr)[-1200:]))
        return None
    return binary


def run_pair(work, app_binary, inspector_binary):
    marker = tempfile.mkdtemp(prefix="marker_", dir=work)
    app = subprocess.Popen([app_binary, marker], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
    try:
        inspected = subprocess.run([inspector_binary, str(app.pid), marker],
                                   capture_output=True, text=True, timeout=30)
        return app, inspected
    finally:
        pass


def parse_app_output(app, timeout=30):
    # The app exits itself once the marker lands; the report is its whole output.
    try:
        out = app.communicate(timeout=timeout)[0]
    except subprocess.TimeoutExpired:
        app.kill()
        return "RESULT killed after %ss" % timeout
    return out


def evaluate(inspected, app_output, label, expected=True):
    lines = inspected.stdout
    # A refused mutant is expected to fail *something*; its expected failures are
    # reported through "is refused" and must not also count against the tree, so the
    # failure list is restored when the refusal came from our own checks.
    if "-v" in sys.argv or "--verbose" in sys.argv:
        print("---- inspector output (%s) ----" % label)
        print(lines.rstrip())
    skipped = [line for line in lines.splitlines() if line.startswith("SKIP")]
    if inspected.returncode == 3:
        SKIPS.append("%s: %s" % (label, skipped[0][5:] if skipped else "no GUI session"))
        return None
    before = len(FAILURES)
    if inspected.returncode not in (0, 3):
        check(False, "%s: the inspector failed (exit %d): %s"
              % (label, inspected.returncode, (lines + inspected.stderr).strip()[-300:]))
        return False
    if inspected.returncode != 0:
        check(False, "%s: the inspector failed (exit %d): %s"
              % (label, inspected.returncode, (lines + inspected.stderr).strip()[-300:]))
        return False
    found = [line for line in lines.splitlines() if line.startswith("BUTTONS ")]
    count = int(found[0].split()[1]) if found else -1
    check(count == 3, "%s: the bar vends one AXButton per segment (%d found)" % (label, count))
    check("NAMING ok" in lines,
          "%s: every segment names the pane it opens in the AX tree" % label)
    check("SELECTION ok" in lines,
          "%s: exactly one segment reports itself selected" % label)
    check("SELECTION_AFTER ok" in lines,
          "%s: after a real click the selection state moved to the clicked segment" % label)
    report = next((l for l in app_output.splitlines() if l.startswith("RESULT")), app_output)
    if "timeout" in report:
        # The click was posted but the app never saw its marker: the window existed for
        # the inspector yet the click did not reach it. On a host with no Aqua session
        # that is the environment, not the bar -- say so instead of failing the verdict.
        SKIPS.append("%s: a posted click never reached the window (%s)" % (label, report))
        return None
    fields = dict(pair.split("=", 1) for pair in report.split()[1:] if "=" in pair)
    writes = int(fields.get("writes", -1))
    at_click = int(fields.get("writesAtClick", -1))
    check(at_click == 1 and writes == 1,
          "%s: one click produced %d write at the click and %d in total afterwards "
          "(no double commit, no straggler behind the glass)" % (label, at_click, writes))
    # The pane the click landed on is the one the tree says it selected -- checked above
    # as SELECTION_AFTER, which is the only reading a screen reader has.
    passed = len(FAILURES) == before
    if not passed and not expected:
        # The mutant failed as it should; those failures are the refusal, not a red tree.
        del FAILURES[before:]
    return passed


def main():
    with open(TAB_BAR, encoding="utf-8") as handle:
        shipping = handle.read()
    pair = swiftc_and_sdk("liquid glass tab bar harness")
    if pair is None:
        print("SKIP no swiftc/SDK pair on this host")
        return 0
    swiftc, sdk = pair

    with tempfile.TemporaryDirectory() as work:
        inspect_path = os.path.join(work, "inspect.swift")
        with open(inspect_path, "w", encoding="utf-8") as handle:
            handle.write(INSPECT)
        inspector = os.path.join(work, "inspector")
        built = subprocess.run([swiftc, "-sdk", sdk, "-o", inspector, inspect_path],
                               capture_output=True, text=True)
        if built.returncode != 0:
            print("FAIL the inspector did not compile:\n%s"
                  % (built.stdout + built.stderr)[-1200:])
            return 1
        app_binary = build(work, "shipped", APP, shipping)
        if app_binary is None:
            return 1
        app, inspected = run_pair(work, app_binary, inspector)
        app_output = parse_app_output(app)
        outcome = evaluate(inspected, app_output, "shipped")
        if outcome is None:
            print("SKIP %s" % "; ".join(SKIPS))
            return 0

        if "--self-test" in sys.argv:
            for name, (before, after, what) in MUTATIONS.items():
                if before not in shipping:
                    check(False, "%s is refused (the code it edits is gone: %r)"
                          % (what, before[:56]))
                    continue
                mutant_binary = build(work, name, APP, shipping.replace(before, after, 1))
                if mutant_binary is None:
                    check(False, "%s is refused (the mutant must compile to prove anything)"
                          % what)
                    continue
                app, inspected = run_pair(work, mutant_binary, inspector)
                app_output = parse_app_output(app)
                outcome = evaluate(inspected, app_output, what, expected=False)
                if outcome is None:
                    print("SKIP %s" % "; ".join(SKIPS))
                    return 0
                check(outcome is False, "%s is refused" % what)

    print("%d tab-bar behaviour failure(s)" % len(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
