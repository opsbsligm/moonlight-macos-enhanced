#!/usr/bin/env python3
"""Prove a gamepad press reaches the responder as a complete key stroke.

The controller cannot press a keyboard, so `NavigatableAlertView` synthesises one: the
D-pad becomes Shift+Tab and Tab, A becomes Return, B becomes Escape, X becomes Space,
and the synthesised event is handed straight to `self.responder` -- the alert window,
the way HostsViewController wires it. The helper takes a `down:` argument, which says
plainly enough that both edges were once expected, and then calls `-[NSResponder
keyDown:]` whatever the caller asked for. Every caller passed YES, so the responder was
told a key went down and never told it came back up.

That is not a cosmetic asymmetry. A responder keeps key state, and the release is the
half that ends a press: a control that actuates on release never actuates, and anything
that pairs a press with its release stays in the pressed half of that pair. Worse, the
event object itself was built by `CGEventCreateKeyboardEvent(..., down)`, so had anyone
ever passed NO, AppKit would have handed a keyUp-typed event to `keyDown:`.

This gate compiles the real `NavigatableAlertView.m` -- not a model of it -- against a
spy responder that records which selector fired, the key code, the modifier flags, and
the type carried inside the event. Four facts come from the compiled shipping source and
none from this description: which key each button produces, that the D-pad's Back stroke
is the one carrying shift, that every press produces one press edge and one release edge
with the same key and the same flags, and that each edge arrives at the selector matching
the event it carries. Rebuilding the old one-edge shape and watching this test refuse it
is what says the test can see the difference.

Exit 0 only when the compiled real source passes and the rebuilt old shape fails.
"""
import os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
VIEW_M = os.path.join(ROOT, "Limelight", "macOS", "Views", "NavigatableAlertView.m")
HELPERS = os.path.join(ROOT, "Limelight", "macOS", "Helpers")
VIEWS = os.path.join(ROOT, "Limelight", "macOS", "Views")
VIEW_HEADER = os.path.join(HELPERS, "NSResponder+Moonlight.h")

SPY_MAIN = r"""
#import <Cocoa/Cocoa.h>
#import "NavigatableAlertView.h"
#import "NSResponder+Moonlight.h"

/* Records every edge the view hands the responder: which selector ran, the key code,
 * the modifier flags, and whether the event type agrees with that selector. A release
 * delivered to keyDown: would be invisible to a count of edges -- it would still look
 * like something arrived -- so the type is part of the record. */
@interface SpyResponder : NSResponder
@property(nonatomic, strong) NSMutableArray<NSString *> *edges;
@end

@implementation SpyResponder
- (instancetype)init {
    self = [super init];
    if (self) {
        _edges = [NSMutableArray array];
    }
    return self;
}
- (void)record:(NSString *)edge event:(NSEvent *)event expects:(NSEventType)expected {
    NSString *agrees = event.type == expected ? @"" : @" misrouted";
    [_edges addObject:[NSString stringWithFormat:@"%@ %u flags %llu%@", edge,
                       (unsigned)event.keyCode, (unsigned long long)event.modifierFlags, agrees]];
}
- (void)keyDown:(NSEvent *)event {
    [self record:@"down" event:event expects:NSEventTypeKeyDown];
}
- (void)keyUp:(NSEvent *)event {
    [self record:@"up" event:event expects:NSEventTypeKeyUp];
}
@end

static int gFailed = 0;

static void expect(int ok, const char *message) {
    if (!ok) {
        gFailed += 1;
        printf("FAIL %s\n", message);
    }
}

static unsigned long long flags_of(NSString *edge) {
    return [[[edge componentsSeparatedByString:@" "] lastObject] longLongValue];
}

static void run_button(NavigatableAlertView *view, SpyResponder *spy, unsigned short button,
                       unsigned expectedKey, int expectShift, const char *label) {
    [spy.edges removeAllObjects];
    MoonlightControllerEvent event = {0};
    event.button = button;
    [view controllerEvent:event];

    expect(spy.edges.count == 2, "a controller press did not reach the responder as a "
                                 "complete stroke (one press edge and one release edge)");
    if (spy.edges.count < 2) {
        printf("        %s recorded: %s\n", label,
               [[spy.edges componentsJoinedByString:@" | "] UTF8String]);
        return;
    }
    NSString *down = spy.edges[0];
    NSString *up = spy.edges[1];
    expect([down hasPrefix:[NSString stringWithFormat:@"down %u", expectedKey]],
           "the press edge of the stroke carried the wrong key code");
    expect([up hasPrefix:[NSString stringWithFormat:@"up %u", expectedKey]],
           "the release edge of the stroke carried the wrong key code");
    expect([down rangeOfString:@"misrouted"].location == NSNotFound,
           "a press arrived as an event that is not a key-down");
    expect([up rangeOfString:@"misrouted"].location == NSNotFound,
           "a release arrived as an event that is not a key-up");
    int downShift = (flags_of(down) & (1ULL << 17)) != 0;    /* NSEventModifierFlagShift */
    int upShift = (flags_of(up) & (1ULL << 17)) != 0;
    expect(downShift == (expectShift ? 1 : 0),
           "the press edge of the stroke carried the wrong modifier flags");
    expect(upShift == (expectShift ? 1 : 0),
           "the release edge of the stroke dropped the modifier flags of its press");
}

int main(void) {
    @autoreleasepool {
        NavigatableAlertView *view = [[NavigatableAlertView alloc] init];
        SpyResponder *spy = [[SpyResponder alloc] init];
        view.responder = spy;
        expect(view != nil && spy != nil, "the view or the spy could not be created");

        run_button(view, spy, kMCE_LeftDpad, 48 /* kVK_Tab */, 1, "dpad left");
        run_button(view, spy, kMCE_RightDpad, 48 /* kVK_Tab */, 0, "dpad right");
        run_button(view, spy, kMCE_AButton, 36 /* kVK_Return */, 0, "button A");
        run_button(view, spy, kMCE_BButton, 53 /* kVK_Escape */, 0, "button B");
        run_button(view, spy, kMCE_XButton, 49 /* kVK_Space */, 0, "button X");

        printf("%s\n", gFailed ? "scenarios failed" : "all scenarios passed");
    }
    return gFailed;
}
"""


def shipping_source():
    with open(VIEW_M, encoding="utf-8") as handle:
        return handle.read()


def one_edge_shape(source):
    """Rebuild the shipped shape: hand the responder a press and never a release."""
    marker = "[self sendKey:keyCode down:NO"
    if marker not in source:
        raise SystemExit("the shipping source has no explicit release to remove, so the "
                         "shape this test rebuilds is not the one it describes")
    index = source.index(marker)
    end = source.index("\n", index)
    return source[:index] + "// release removed by the test" + source[end:]


def build(source, directory):
    view_path = os.path.join(directory, "NavigatableAlertView.m")
    main_path = os.path.join(directory, "spy_main.m")
    binary = os.path.join(directory, "controller_keys")
    with open(view_path, "w") as handle:
        handle.write(source)
    with open(main_path, "w") as handle:
        handle.write(SPY_MAIN)
    for header in (os.path.join(VIEWS, "NavigatableAlertView.h"), VIEW_HEADER):
        if not os.path.exists(header):
            raise SystemExit("%s is gone, so the view cannot be compiled as shipped" % header)
    import apple_toolchain
    clang, sdk = apple_toolchain.clang_and_sdk("the controller key navigator")
    compiled = subprocess.run(
        [clang, "-fobjc-arc", "-isysroot", sdk, "-I", VIEWS, "-I", HELPERS,
         "-F", os.path.join(sdk, "System", "Library", "Frameworks"),
         "-framework", "Cocoa", "-framework", "Carbon",
         view_path, main_path, "-o", binary],
        capture_output=True, text=True)
    if compiled.returncode != 0:
        raise SystemExit("the real NavigatableAlertView.m does not compile against the "
                         "spy:\n" + compiled.stderr)
    return binary


def main():
    source = shipping_source()
    with tempfile.TemporaryDirectory() as workspace:
        shipped = build(source, workspace)
        ran = subprocess.run([shipped], capture_output=True, text=True)
        output = (ran.stdout + ran.stderr).strip()
        if ran.returncode != 0:
            print("FAIL the shipped controller navigation is incomplete:\n%s" % output)
            return 1
        print("ok every controller press reaches the responder as a full stroke")

        rebuilt = build(one_edge_shape(source), workspace)
        again = subprocess.run([rebuilt], capture_output=True, text=True)
        if again.returncode == 0:
            print("FAIL the rebuilt one-edge shape passes, so this test cannot notice "
                  "a press without its release")
            return 1
        print("ok a press without its release is refused (%s)"
              % (again.stdout + again.stderr).strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
