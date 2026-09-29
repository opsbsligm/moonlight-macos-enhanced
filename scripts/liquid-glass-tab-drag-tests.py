#!/usr/bin/env python3
"""Drive the shipped settings tab bar the way AppKit does, and measure what it costs.

The accepted look is the native Activity-Monitor-style NSSegmentedControl and the accepted
feel is "clicking or dragging the segments never strands the window and never blocks the
drag". Until now both halves were only asserted statically: the audit reads for the glass
API and the overlay harness compiles the container. Neither answers the behavioural
questions the objective asks -- who owns the pointer over the bar and what is left to drag
the window by, whether committing a pane happens while native tracking still holds the
pointer (the shape that makes a drag feel stuck), how many writes one release produces, and
what the deferral costs.

This harness compiles the shipping LiquidGlassTabBar.swift -- the real file, not a copy --
into a throwaway AppKit program and answers those with real AppKit objects. What it does
not fake: headless synthetic mouse-downs reach the control by hit-test but never enter an
NSSegmentedControl cell's private tracking loop (verified here), so the interaction half
drives the boundary AppKit reaches when tracking ends -- `selectedSegment` plus
`sendAction` to the target -- instead of pretending a synthetic click moved the cell. The
geometry half is real hit-testing. Both are said out loud in the output.
"""
import os
import subprocess
import sys
import tempfile

from apple_toolchain import swiftc_and_sdk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB_BAR = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "LiquidGlass",
                       "LiquidGlassTabBar.swift")
DEFERRAL = "RunLoop.main.perform(inModes: [.default])"
FAILURES = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        FAILURES.append(message)


HARNESS = r'''
import AppKit
import SwiftUI

var failures = 0
func check(_ ok: Bool, _ message: String) {
    print("\(ok ? "ok  " : "FAIL") \(message)")
    fflush(stdout)
    if !ok { failures += 1 }
}

_ = NSApplication.shared
NSApp.setActivationPolicy(.prohibited)

// The harness must not become the frontmost app -- that would take the keyboard away from
// whoever is using this machine -- so its window never becomes key. A real settings window
// is key when the player clicks it; this container says that much to AppKit for the
// harness's own view, and production code stays untouched.
final class HarnessContent: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

let items = [
    LiquidGlassTabItem(id: 10, title: "Display", symbol: "display", tint: .cyan),
    LiquidGlassTabItem(id: 20, title: "Audio", symbol: "speaker.wave.2", tint: .green),
    LiquidGlassTabItem(id: 30, title: "Input", symbol: "keyboard", tint: .orange),
]

final class Box {
    var writes = 0
    var released = Date()
    var latencies: [Double] = []
    var value = 10 { didSet { writes += 1; latencies.append(Date().timeIntervalSince(released) * 1000) } }
}
let box = Box()
let binding = Binding(get: { box.value }, set: { box.value = $0 })

let window = NSWindow(contentRect: NSRect(x: 240, y: 240, width: 700, height: 500),
                      styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
let content = HarnessContent(frame: NSRect(x: 0, y: 0, width: 700, height: 500))
window.contentView = content
let host = NSHostingView(rootView: LiquidGlassTabBar(selection: binding, items: items))
host.frame = NSRect(x: 120, y: 420, width: 420, height: 32)
content.addSubview(host)
window.layoutIfNeeded()

func findSegmented(_ view: NSView) -> NSSegmentedControl? {
    if let control = view as? NSSegmentedControl { return control }
    for child in view.subviews { if let found = findSegmented(child) { return found } }
    return nil
}
guard let control = findSegmented(host), let action = control.action, control.target != nil else {
    print("FAIL no NSSegmentedControl with a target and action in the hosting view: the harness is driving nothing")
    exit(1)
}
let barRect = control.convert(control.bounds, to: nil)
let contentHeight = window.contentRect(forFrameRect: window.frame).height

// --- who owns the pointer, and what is left to drag the window by ---
check(control.segmentCount == items.count, "the mounted bar is the shipped native NSSegmentedControl (\(items.count) segments)")
check(control.trackingMode == .selectOne && !control.isContinuous,
      "native tracking is left alone (.selectOne, not continuous): no gesture over the glass")
check(window.contentView?.hitTest(NSPoint(x: barRect.midX, y: barRect.midY)) is NSSegmentedControl,
      "a pointer aimed at the bar hits the bar, not the hosting view behind it")
check(!control.mouseDownCanMoveWindow, "the bar keeps its own clicks (mouseDownCanMoveWindow == false)")
check(barRect.maxY <= contentHeight + 0.5,
      "the bar stays in the content region (bar top \(barRect.maxY) <= content height \(Int(contentHeight))), so it never covers the titlebar")
check(content.hitTest(NSPoint(x: barRect.midX, y: contentHeight + 6)) == nil,
      "the strip above the content region hit-tests to no content view: that is the frame view, what the window drags by, and the bar does not reach it")
check(window.isMovable, "the window is movable with the bar mounted")

// --- the shipped commit path ---
func drain(_ mode: RunLoop.Mode, for seconds: TimeInterval) {
    RunLoop.current.run(mode: mode, before: Date().addingTimeInterval(seconds))
}
// One 50ms drain would report its own window as the cost. Poll in small slices and stop at
// the write, so the number says when the commit landed, at a 2ms resolution.
@discardableResult
func drainUntilCommit(_ limit: TimeInterval = 0.4) -> Bool {
    let before = box.writes
    let started = Date()
    while Date().timeIntervalSince(started) < limit {
        drain(.default, for: 0.002)
        if box.writes > before { return true }
    }
    return box.writes > before
}

for target in [1, 2, 0, 2, 1] {
    box.writes = 0
    box.latencies.removeAll()
    box.released = Date()
    control.selectedSegment = target
    control.sendAction(action, to: control.target)
    check(box.writes == 0, "segment \(target): the release wrote no pane while native tracking still holds the pointer")
    drain(.eventTracking, for: 0.04)
    check(box.writes == 0, "segment \(target): 40ms of eventTracking mode -- the mode native tracking runs in -- still mounts no pane")
    box.released = Date() // native tracking has ended here; the cost below is the deferral alone
    let landed = drainUntilCommit()
    check(landed, "segment \(target): the commit lands once tracking is out of the way")
    check(box.writes == 1, "segment \(target): that release produced \(box.writes) write, not one per mode pass")
    check(box.value == items[target].id, "segment \(target): the selection landed on pane \(items[target].id)")
}

// A drag crosses segments and releases once: .selectOne with isContinuous == false fires the
// action at the release, so one drag must mount one pane.
box.writes = 0
box.latencies.removeAll()
control.selectedSegment = 1
control.selectedSegment = 2
control.sendAction(action, to: control.target)
drain(.eventTracking, for: 0.04)
box.released = Date()
_ = drainUntilCommit()
check(box.writes == 1, "a drag across every segment produced \(box.writes) selection write (one per segment crossed would remount the pane under the pointer)")
check(box.value == items[2].id && control.selectedSegment == 2, "the drag ends where the pointer was released (pane \(box.value), segment \(control.selectedSegment))")

let latencies = box.latencies
check(!latencies.isEmpty, "writes were observed, so the timing below is not vacuous")
let worst = latencies.max()!
print("     measured commit-after-tracking (ms, 2ms resolution; the 40ms eventTracking drain above is the harness standing in for native tracking and is not counted): median \(String(format: "%.2f", latencies.sorted()[latencies.count / 2])), worst \(String(format: "%.2f", worst))")
check(worst <= 12.0, "every commit landed within 12ms of tracking ending, so the deferral itself is not where a drag could feel stuck")

box.writes = 0
RunLoop.main.run(until: Date().addingTimeInterval(0.6))
check(box.writes == 0, "600ms of runloop afterwards produced \(box.writes) further writes: nothing repeats on its own behind the tabs")

print("\(failures) tab-bar interaction failure(s)")
exit(failures == 0 ? 0 : 1)
'''

# Each mutation is a shape the shipping code must not be allowed to take. The three fail for
# three different reasons, which is what shows the assertions read behaviour rather than the
# source text.
MUTATIONS = {
    "commit-during-tracking": (DEFERRAL, "RunLoop.main.perform(inModes: [.eventTracking])",
                               "a pane mounted while native tracking holds the pointer"),
    "commit-inline": ("      pendingSelection = parent.items[index].id\n",
                      "      pendingSelection = parent.items[index].id\n        parent.selection = parent.items[index].id\n",
                      "a commit that happens before tracking ends"),
    "double-write": ("if self.parent.selection != selection { self.parent.selection = selection }",
                     "self.parent.selection = selection\n        self.parent.selection = selection",
                     "two writes for one release"),
}


def build_and_run(directory, label, source):
    # Top-level code is legal only in a file named main.swift, so each build gets its own
    # directory rather than a renamed copy of one.
    build = os.path.join(directory, label)
    os.makedirs(build, exist_ok=True)
    tab_path = os.path.join(build, "tab_bar.swift")
    main_path = os.path.join(build, "main.swift")
    with open(tab_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    with open(main_path, "w", encoding="utf-8") as handle:
        handle.write(HARNESS)
    swiftc, sdk = swiftc_and_sdk("liquid glass tab bar harness")
    binary = os.path.join(directory, "tabdrag_%s" % label)
    built = subprocess.run([swiftc, "-sdk", sdk, "-o", binary, main_path, tab_path],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL %s did not compile:\n%s" % (label, (built.stdout + built.stderr)[-1200:]))
        return None
    return subprocess.run([binary], capture_output=True, text=True, timeout=180)


def main():
    with open(TAB_BAR, encoding="utf-8") as handle:
        shipping = handle.read()
    if DEFERRAL not in shipping:
        raise SystemExit("the shipping tab bar no longer defers its commit to the default mode; this "
                         "harness has to be rewritten against whatever replaced it, not left "
                         "proving nothing")
    swiftc, sdk = swiftc_and_sdk("liquid glass tab bar harness")
    if swiftc is None:
        print("SKIP no swiftc/SDK pair on this host")
        return 1

    with tempfile.TemporaryDirectory() as work:
        shipped = build_and_run(work, "shipped", shipping)
        if shipped is None:
            return 1
        print(shipped.stdout.rstrip())
        check(shipped.returncode == 0, "the shipped tab bar answers every interaction assertion on this host")

        if "--self-test" in sys.argv:
            for name, (before, after, what) in MUTATIONS.items():
                if before not in shipping:
                    print("FAIL mutation %s: the code it edits is gone (%r)" % (name, before[:56]))
                    check(False, "%s is refused" % what)
                    continue
                mutated = build_and_run(work, name, shipping.replace(before, after, 1))
                if mutated is None:
                    check(False, "%s is refused (and the mutant must compile to prove anything)" % what)
                    continue
                caught = mutated.returncode != 0
                first = next((line for line in mutated.stdout.splitlines() if line.startswith("FAIL")), "")
                print("     %-22s %s" % (name, first[:100]))
                check(caught, "%s is refused" % what)

    print("%d harness failure(s)" % len(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
