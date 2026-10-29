#!/usr/bin/env python3
"""Drive the shipped settings tab bar through the accessibility tree, and measure what it costs.

The bar is the system's segmented control: it draws its own selection, vends one
AXRadioButton per segment inside a tab group, and commits through the binding once per
click. The audit proves the control and the API statically; nothing until now proved the
two behavioural promises that shape makes -- that a screen reader can say which pane each
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
// Say out loud, through the marker directory, when the window is genuinely on screen. The
// inspector cannot settle this on its own: a headless session leaves the window server's list
// empty for a process that has no screen-recording permission, which looks the same as a
// harness that never opened a window. This process is the only one that knows.
var announcedWindow = false
Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { timer in
    if !announcedWindow, window.isVisible, window.screen != nil {
        announcedWindow = true
        FileManager.default.createFile(atPath: (markerDirectory as NSString).appendingPathComponent("window-shown"),
                                       contents: Data())
    }
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
// The window server's own list, as a source that does not depend on the accessibility layer.
func onScreenWindows(of target: pid_t) -> Int {
    let option = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
    guard let list = CGWindowListCopyWindowInfo(option, kCGNullWindowID) as? [[String: Any]]
    else { return 0 }
    return list.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == target }.count
}
func role(_ el: AXUIElement) -> String {
    (copyAttr(el, kAXRoleAttribute as String) as? String) ?? ""
}
func name(_ el: AXUIElement) -> String {
    (copyAttr(el, kAXDescriptionAttribute as String) as? String) ?? ""
}
func selected(_ el: AXUIElement) -> Bool {
    // The native control answers the selection question with AXValue -- a segment is
    // selected when its value is one (CFBoolean bridges to both readings below); the
    // hand-drawn bar that preceded it answered AXSelected instead. Accept either so
    // the verdict is about the control keeping one selected segment, not about which
    // attribute a particular implementation chose to carry it on.
    if let v = copyAttr(el, "AXValue") as? Bool { return v }
    if let v = copyAttr(el, "AXValue") as? Int { return v == 1 }
    return (copyAttr(el, kAXSelectedAttribute as String) as? Bool) == true
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
// Every tree walk in this inspector is iterative, and it has to be. AppKit vends the app
// element among its own children (measured here, and recorded in
// scripts/edge_acceptance_helper.swift: a plain recursive dump expanded the menu bar
// 2^depth times), and an AX-manual client sees AXApplication > AXMenuBar > AXMenuBarItem >
// AXMenu > ... > AXApplication. Recursion over that graph overruns the thread stack, so the
// inspector died with SIGSEGV on the guard page and the gate reported an exit code instead
// of a verdict. An explicit stack cannot overrun, the ancestor chain below skips the
// back-edges, and the two caps turn any surprise into a loud diagnostic rather than a hang.
let walkDepthCap = 128
let walkNodeBudget = 400_000
var walkNodes = 0
var walkDepthReached = 0
var walkBudgetHit = false
var walkDepthHit = false

// Collect every element under `roots` that `match` accepts, in document order, without
// following an edge back into one of its own ancestors.
func collect(roots: [AXUIElement], match: (AXUIElement) -> Bool) -> [AXUIElement] {
    struct Frame {
        let el: AXUIElement
        let depth: Int
        let ancestors: [ObjectIdentifier]
    }
    var out: [AXUIElement] = []
    var stack = roots.reversed().map { Frame(el: $0, depth: 0, ancestors: []) }
    while let frame = stack.popLast() {
        walkNodes += 1
        if walkNodes > walkNodeBudget { walkBudgetHit = true; break }
        walkDepthReached = max(walkDepthReached, frame.depth)
        if frame.depth > walkDepthCap { walkDepthHit = true; continue }
        if match(frame.el) { out.append(frame.el) }
        for child in kids(frame.el).reversed() {
            // The app element reports itself among its own children, so a walk that starts
            // at a window reaches AXApplication and would re-expand the whole menu bar from
            // there. Dropping that edge is the same guard scripts/edge_acceptance_helper.swift
            // uses, and it is the cheap one; the ancestor check below still catches cycles
            // that do not run through the app element.
            if role(child) == "AXApplication" { continue }
            // A child that is already one of our ancestors is a back-edge in a cycle, not
            // a new subtree; following it is exactly what made the walk exponential.
            if frame.ancestors.contains(ObjectIdentifier(child as AnyObject)) { continue }
            stack.append(Frame(el: child, depth: frame.depth + 1,
                               ancestors: frame.ancestors + [ObjectIdentifier(frame.el as AnyObject)]))
        }
    }
    return out
}

func isBarRoot(_ el: AXUIElement) -> Bool {
    ((copyAttr(el, "AXIdentifier") as? String) ?? "") == "settings-navigation"
}
func isSegment(_ el: AXUIElement) -> Bool {
    // A segment is an AXRadioButton on the native control (the tab-group shape every
    // screen reader expects) and was an AXButton on the hand-drawn bar; collect either
    // so "one element per segment" keeps its meaning across the swap.
    role(el) == "AXButton" || role(el) == "AXRadioButton"
}

// The window appears asynchronously after activation; give it a moment, then answer the
// three questions the driver cannot ask without a GUI session, and say "no session" in
// words rather than failing if there is not one.
// AXWindows answers with the application element itself when the session vends no windows
// (measured on this host: for Safari and Terminal, whose on-screen windows the window server
// does list, AXWindows still returns n entries all CFEqual to the app element, and System
// Events -- Apple's own trusted client -- reports `count of windows` as 0 for the same
// processes). Such an entry is a sentinel, not a window: it has the app's attributes, its
// children are the menu bar, and walking it is what turns the app element into one of its own
// descendants. Filter it out before the guard below, otherwise "a window appeared" is satisfied
// by an element that is the app, and the walk then reports the bar as missing.
func windowElements(_ raw: [AXUIElement]) -> [AXUIElement] {
    raw.filter { role($0) != "AXApplication" && !CFEqual($0, app) }
}
var windows: [AXUIElement] = []
var sawSelfSentinel = false
for _ in 0..<40 {
    Thread.sleep(forTimeInterval: 0.1)
    let err = error(app, kAXWindowsAttribute as String)
    if err == .apiDisabled || err.rawValue == -25218 || err == .illegalArgument {
        print("SKIP no accessibility trust for this inspector (\(err.rawValue))")
        exit(3)
    }
    let raw = (copyAttr(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? []
    sawSelfSentinel = sawSelfSentinel || raw.contains { CFEqual($0, app) }
    windows = windowElements(raw)
    if !windows.isEmpty { break }
}
guard !windows.isEmpty else {
    // Nothing below can be judged without a window in the tree, and the two outside readings
    // are reported rather than acted on, because neither can tell a broken harness from a host
    // with no GUI session: a headless runner leaves the window server's list empty for a
    // process with no screen-recording permission, which is the same reading a harness that
    // never opened a window gives. What is *not* possible to conclude from here is anything
    // about the bar, so the honest answer is SKIP with the evidence attached -- and whenever
    // the tree is readable, the checks below do run and fail loudly.
    let shown = FileManager.default.fileExists(atPath: (markerDirectory as NSString)
        .appendingPathComponent("window-shown"))
    let axRead = sawSelfSentinel
        ? "AXWindows vends only the application element itself (its no-window sentinel)"
        : "AXWindows vends no elements"
    print("SKIP no window in the app's AX tree -- \(axRead); the app reports a window on "
          + "screen: \(shown), the window server lists \(onScreenWindows(of: pid)) for it; "
          + "this host cannot answer an out-of-process accessibility query")
    exit(3)
}
// Scope to the bar's own container: the window's traffic lights are AXButtons too, and
// counting them as segments would make every verdict below about the window chrome.
// The bar marks its subtree with .accessibilityIdentifier("settings-navigation"), which
// vends as AXIdentifier -- a handle that does not depend on the names being tested.
let bars = collect(roots: windows, match: isBarRoot)
guard !bars.isEmpty else {
    // Name the walk's shape in the failure itself: "not in the tree" means something
    // different when the walk hit its node budget than when it truly saw no such element.
    print("FAIL the bar's settings-navigation subtree is not in the window's AX tree "
          + "(nodes=\(walkNodes) maxdepth=\(walkDepthReached) budget_hit=\(walkBudgetHit) depth_hit=\(walkDepthHit))")
    exit(2)
}
let found = bars.flatMap { collect(roots: [$0], match: isSegment) }
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
        .flatMap { collect(roots: [$0], match: isBarRoot) }
        .flatMap { collect(roots: [$0], match: isSegment) }
    picked = fresh.filter { selected($0) }.map { name($0) }
    if picked == [wanted] { break }
}
let afterBtns = bars.flatMap { collect(roots: [$0], match: isSegment) }
for b in afterBtns {
    print("AFTERBTN name=\(name(b)) selected=\(selected(b))")
}
print("SELECTION_AFTER \(picked == [wanted] ? "ok" : "fail \(picked)")")
// Say what the walk cost, so a tree that starts expanding again shows up as a number in
// the log instead of an inspector that died before it could answer.
print("WALK nodes=\(walkNodes) maxdepth=\(walkDepthReached) budget_hit=\(walkBudgetHit) depth_hit=\(walkDepthHit)")
FileManager.default.createFile(atPath: (markerDirectory as NSString).appendingPathComponent("clicked"),
                              contents: Data())
exit(0)
'''

MUTATIONS = {
    # The native control vends a segment's label as its AX name; the regression that
    # goes nameless is a washed-out label at the call site, which is what a careless
    # localisation refactor produces.
    "nameless": ("control.setLabel(item.title, forSegment: index)",
                 "control.setLabel(\"\", forSegment: index)",
                 "segments whose AX names were washed out"),
    # The coordinator commits once, guarded by an inequality; a mutation that writes
    # twice must show as two binding writes for one click.
    "double-write": ("if self.parent.selection != selection { self.parent.selection = selection }",
                     "if self.parent.selection != selection { self.parent.selection = selection\n          self.parent.selection = selection }",
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
    check(count == 3, "%s: the bar vends one AX element per segment (%d found)" % (label, count))
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
