#!/usr/bin/env python3
"""Prove that a settings callback which keeps its own pane keeps the model too.

The settings page hands its model two closures to call when a value the page shows
changes. The model holds them for as long as it lives, and the presenter builds a new
model for every settings window, so a closure that reaches back into the pane makes a
cycle a closed window cannot break: the model keeps the closure, the closure keeps the
pane, the pane keeps the model. Nothing about the settings page behaves differently
while it leaks, which is how this shape hides -- and a reasoning about capture lists is
weak evidence here, because a mutating context refuses this capture outright while the
real one is a `body`, where it is allowed.

So the two closures are cut out of SettingsStreamPane.swift and compiled exactly as
they stand, beside a model that counts the times it was released. Three shapes are
measured: the shipped one, the same code with the weak capture taken away, and the
closure reaching for the pane the way it used to. The shipped one has to release the
model; the other two have to leak it, and all three have to write the right answer,
because behaviour is exactly what a leak does not disturb.

The model is a stand-in and says so: it exists to report its own release. The closures
being tested are the ones that ship.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

PANE = "Limelight/macOS/ViewControllers/SettingsStreamPane.swift"
ASSIGNMENTS = ("settingsModel.resolutionChangedCallback = {",
               "settingsModel.fpsChangedCallback = {")

failures = []


def check(ok, message):
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def statement(src, start_text):
    """One `x = { ... }` statement out of the shipping file, braces counted."""
    start = src.index(start_text)
    opening = src.index("{", start)
    depth, index = 0, opening
    while index < len(src):
        if src[index] == "{":
            depth += 1
        elif src[index] == "}":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
        index += 1
    raise AssertionError("unbalanced closure at " + start_text)


# The two statements arrive as text: the pane's own bindings and the model it reads are
# named the same here as in the file, so the closures compile without being edited.
HARNESS = """
import SwiftUI

final class Model {
    static var born = 0
    static var released = 0
    var selectedResolution = false
    var selectedFps = false
    var resolutionChangedCallback: (() -> Void)?
    var fpsChangedCallback: (() -> Void)?
    init() { Model.born += 1 }
    deinit { Model.released += 1 }
}

// What the callbacks write is a SwiftUI Binding. The box behind it is this class: the
// real one is a State, whose binding only behaves once SwiftUI has given it a location,
// and a command line harness never gets one. A binding over a box asks the same
// question -- does the closure hold the pane, or only the answer -- without that debt.
final class Flag { var value = false }

struct Pane {
    let settingsModel: Model
    let resolutionFlag: Flag
    let fpsFlag: Flag

    func attach() {
@@SHIP@@
    }

    // Somebody tidies the weak capture away, guard and all. The page goes on working
    // exactly as well as it ever did, and its model is never released again.
    func attachStrongCapture() {
@@STRONG@@
    }

    // The way it was written before: a local function reads the model through the pane,
    // so the closure keeps the pane and the pane keeps the model.
    func attachReachingForThePane() {
        func updateCustomResolutionGroup() {
            resolutionFlag.value = settingsModel.selectedResolution
        }
        settingsModel.resolutionChangedCallback = {
            withAnimation { updateCustomResolutionGroup() }
        }
    }
}

func bindings(_ pane: Pane) -> (Binding<Bool>, Binding<Bool>) {
    let resolution = pane.resolutionFlag
    let fps = pane.fpsFlag
    return (Binding(get: { resolution.value }, set: { resolution.value = $0 }),
            Binding(get: { fps.value }, set: { fps.value = $0 }))
}

func answers(_ mode: String) -> String {
    let resolution = Flag()
    let fps = Flag()
    let pane = Pane(settingsModel: Model(), resolutionFlag: resolution, fpsFlag: fps)
    if mode == "strong" { pane.attachStrongCapture() }
    else if mode == "pane" { pane.attachReachingForThePane() }
    else { pane.attach() }
    var line = ""
    for value in [true, false] {
        pane.settingsModel.selectedResolution = value
        pane.settingsModel.resolutionChangedCallback?()
        line += "\\(value)?" + (resolution.value ? "yes" : "no") + " "
    }
    return line
}

let mode = CommandLine.arguments[1]
let line = answers(mode)
// Nothing outside this call still holds the pane or the model, so a model alive here is
// alive because its own callback is the one holding it.
print("mode=\\(mode) wrote[\\(line)] released=\\(Model.released) of \\(Model.born)")
"""


def finish():
    print("%d ownership failures" % len(failures))
    return 1 if failures else 0


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, PANE), encoding="utf-8").read()

    shipped = [statement(src, start) for start in ASSIGNMENTS]
    check(len(shipped) == 2, "the page hands the model two callbacks")
    check(all("[weak model = settingsModel]" in body for body in shipped),
          "both of them capture the model weakly, which is what the run below is testing")
    check(all("wrappedValue" in body for body in shipped),
          "both of them write the pane's state through a binding, not through the pane")

    # Taking the weak away is not only the capture list: the guard that follows it stops
    # compiling once the capture is strong, so the mutation is the whole tidy-up someone
    # would actually make, not one token of it.
    strong = [body.replace("[weak model = settingsModel]", "[model = settingsModel]")
                  .replace("guard let model else { return }\n", "")
              for body in shipped]
    def with_bindings(bodies):
        # The closures name two bindings; here is where a real pane gets them from.
        preamble = (
            "        let (resolutionGroupShown, fpsGroupShown) = bindings(self)\n"
            "        func customResolutionShown(for model: Model) -> Bool {\n"
            "            model.selectedResolution\n        }\n"
            "        func customFpsShown(for model: Model) -> Bool {\n"
            "            model.selectedFps\n        }\n")
        return preamble + "\n".join("        " + b for b in bodies)

    harness = (HARNESS.replace("@@SHIP@@", with_bindings(shipped))
               .replace("@@STRONG@@", with_bindings(strong)))

    pair = apple_toolchain.swiftc_and_sdk("settings callback ownership")
    if pair is None:
        print("SKIP no swiftc/SDK pair on this host")
        return 1
    swiftc, sdk = pair

    with tempfile.TemporaryDirectory() as work:
        source = os.path.join(work, "ownership.swift")
        binary = os.path.join(work, "ownership")
        open(source, "w", encoding="utf-8").write(harness)
        built = subprocess.run([swiftc, "-sdk", sdk, "-o", binary, source],
                               capture_output=True, text=True)
        check(built.returncode == 0,
              "the shipping closures compile as they stand"
              if built.returncode == 0 else
              "the shipping closures do not compile:\n%s" % (built.stdout + built.stderr)[-2000:])
        if built.returncode:
            return finish()
        seen = {}
        for mode in ("shipped", "strong", "pane"):
            ran = subprocess.run([binary, mode], capture_output=True, text=True)
            check(ran.returncode == 0, "%s mode ran" % mode)
            seen[mode] = ran.stdout.strip()

    for mode in ("shipped", "strong", "pane"):
        line = seen.get(mode, "")
        wrote = re.search(r"wrote\[(.*?)\] released=(\d+) of (\d+)", line)
        check(bool(wrote), "%s mode reported an answer: %s" % (mode, line or "(nothing)"))
        if not wrote:
            continue
        written, released, born = wrote.group(1), int(wrote.group(2)), int(wrote.group(3))
        check(written.strip() == "true?yes false?no",
              "%s mode still shows the custom field when the model asks for it" % mode)
        if mode == "shipped":
            check(released == born and born == 1,
                  "a shipped page lets its model go once the page is gone"
                  if released == born else
                  "the shipped page keeps its model: released %d of %d, which is the leak"
                  % (released, born))
        else:
            check(released == 0,
                  "%s mode leaks the model, so the rule that refuses it is refusing a "
                  "real cycle" % mode
                  if released == 0 else
                  "%s mode released the model, so this mutation no longer proves the "
                  "shape leaks and the run above is testing something else" % mode)

    print("::note::the Model here is a stand-in that counts releases; the closures "
          "under test are cut out of " + PANE)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
