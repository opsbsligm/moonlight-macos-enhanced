#!/usr/bin/env python3
"""Hold the Liquid Glass surface to the rules that were decided for it.

A glass look is easy to fake and easy to erode. The failures these rules catch are
all ones that compile, run and look plausible in a code review:

  * a hand-made blur, gradient or .regularMaterial standing in for the system
    material, which is exactly what produced the see-through-the-desktop panel
    first reported by a user;
  * a warm accent, which the design brief rules out;
  * a glass transition given its own literal duration, so the panel and the tab
    pill stop moving together;
  * a springy curve, which the brief rejects.

The rules are a pure function over file contents. --self-test breaks each rule on
a fixture to prove it fires, because a rule that never fires is worse than none.
"""
import argparse, os, re, sys

GLASS_DIR = "Limelight/macOS/ViewControllers/LiquidGlass"
COLOUR = re.compile(r"red:\s*([0-9.]+)\s*,\s*green:\s*([0-9.]+)\s*,\s*blue:\s*([0-9.]+)")
FAKE_GLASS = ("NSVisualEffectView", "UIBlurEffect", ".blur(radius:", ".regularMaterial",
              ".thinMaterial", ".thickMaterial")
# Everything that overshoots and settles back. The brief rejects it for glass.
SPRINGY = re.compile(r"\.bouncy\b|\.spring\s*\(|interpolatingSpring|\bSpring\s*\(|bounce\s*:")
DURATION = re.compile(r"duration:\s*[0-9.]+")


def strip_comments(text):
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith("//"):
            continue
        out.append(re.sub(r"//.*$", "", line))
    return "\n".join(out)


def check(files):
    """files maps basename to raw source. Returns human readable violations."""
    problems = []
    combined = "\n".join(strip_comments(t) for t in files.values())

    if ".glassEffect(" not in combined:
        problems.append("no native .glassEffect anywhere in the glass surface")
    if "GlassEffectContainer(" not in combined:
        problems.append("glass elements are not grouped in a GlassEffectContainer, "
                        "so they cannot merge, cull or morph together")

    for needle in FAKE_GLASS:
        if needle in combined:
            problems.append("%s stands in for the system material" % needle)

    for name, text in files.items():
        hit = SPRINGY.search(strip_comments(text))
        if hit:
            problems.append("%s uses an overshooting curve (%s)" % (name, hit.group(0).strip()))

    bar = files.get("LiquidGlassTabBar.swift", "")
    match = COLOUR.search(strip_comments(bar))
    if match is None:
        problems.append("the glass accent colour could not be read from TabBarConfig")
    else:
        r, g, b = (float(match.group(i)) for i in (1, 2, 3))
        if not (b > r and g > r):
            problems.append("accent is warm: red %.2f is not below green %.2f and blue %.2f"
                            % (r, g, b))

    duration = re.search(r"animationDuration\s*:\s*Double\s*=\s*([0-9.]+)", strip_comments(bar))
    if duration is None:
        problems.append("TabBarConfig no longer declares animationDuration")
    elif abs(float(duration.group(1)) - 0.22) > 1e-9:
        problems.append("the shared glass transition is %ss, not the agreed 0.22s"
                        % duration.group(1))

    for name, text in files.items():
        body = strip_comments(text)
        for found in DURATION.finditer(body):
            if "TabBarConfig.animationDuration" not in body:
                problems.append("%s sets its own animation duration" % name)
            break

    presenter = files.get("SettingsOverlayPresenter.swift", "")
    if presenter and "TabBarConfig.animationDuration" not in strip_comments(presenter):
        problems.append("the overlay animates with something other than the shared duration")

    return problems


FIXTURE = {
    "LiquidGlassTabBar.swift": """
        static let accentCoolBlue = Color(
          .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
        )
        static let animationDuration: Double = 0.22
        GlassEffectContainer(spacing: 6) {
          view.glassEffect(.regular.tint(accentCoolBlue), in: shape)
        }
        """,
    "SettingsOverlayPresenter.swift": """
        context.duration = TabBarConfig.animationDuration
        """,
}


def mutate(text, old, new):
    assert old in text, "fixture drift: " + old
    return text.replace(old, new, 1)


def self_test():
    cases = []
    cases.append(("the compliant fixture", FIXTURE, False))

    warm = dict(FIXTURE)
    warm["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "red: 0.34, green: 0.62, blue: 0.95",
                                             "red: 0.95, green: 0.45, blue: 0.20")
    cases.append(("a warm accent", warm, True))

    slow = dict(FIXTURE)
    slow["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "animationDuration: Double = 0.22",
                                             "animationDuration: Double = 0.4")
    cases.append(("a retimed shared transition", slow, True))

    fake = dict(FIXTURE)
    fake["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "GlassEffectContainer(spacing: 6) {",
                                             "NSVisualEffectView()\n        GlassEffectContainer(spacing: 6) {")
    cases.append(("a hand-made blur replacing the material", fake, True))

    ungrouped = dict(FIXTURE)
    ungrouped["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                                 "GlassEffectContainer(spacing: 6) {", "VStack {")
    cases.append(("glass elements outside a container", ungrouped, True))

    noglass = dict(FIXTURE)
    noglass["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                               ".glassEffect(", ".tint(")
    cases.append(("no native glass at all", noglass, True))

    springy = dict(FIXTURE)
    springy["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                                "static let animationDuration",
                                                "withAnimation(.bouncy) { label.isHidden = true }\n        static let animationDuration")
    cases.append(("a springy curve", springy, True))

    solo = dict(FIXTURE)
    solo["SettingsOverlayPresenter.swift"] = "withAnimation(.easeInOut(duration: 0.5)) { panel.alpha = 1 }\n"
    cases.append(("an overlay with its own duration", solo, True))

    failures = 0
    for what, files, expect_problem in cases:
        problems = check(files)
        if bool(problems) != expect_problem:
            failures += 1
            print("FAIL %-38s expected %s, got %s"
                  % (what, "a violation" if expect_problem else "clean", problems))
        else:
            print("ok   %-38s %s" % (what, "refused" if problems else "accepted"))
    print("%d liquid glass audit self-test failures" % failures)
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    root = os.path.join(args.repo, GLASS_DIR)
    if not os.path.isdir(root):
        print("error: %s is missing" % GLASS_DIR)
        return 1
    files = {}
    for name in sorted(os.listdir(root)):
        if name.endswith(".swift"):
            files[name] = open(os.path.join(root, name), encoding="utf-8").read()
    problems = check(files)
    for problem in problems:
        print("violation: %s" % problem)
    print("%d liquid glass violations across %d files" % (len(problems), len(files)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
