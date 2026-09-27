#!/usr/bin/env python3
"""Exercise the shipped MFi button handoff without a physical gamepad."""
from pathlib import Path
import subprocess
import tempfile

from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Limelight/Input/ControllerSupport.m"


def method(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for end in range(brace, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if depth == 0:
            return text[start:end + 1]
    raise AssertionError(signature)


PREAMBLE = r'''
#import <Foundation/Foundation.h>
#define TARGET_OS_IPHONE 0
enum { A_FLAG = 1, B_FLAG = 2, BUTTON_LEFT = 1, BUTTON_RIGHT = 3 };
static int failures;
static void check(BOOL ok, const char *label) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", label); failures += !ok;
}
@interface Controller : NSObject
@property int lastMouseModeButtonFlags;
@end
@implementation Controller
@end
// The shared pointer ledger has separate behavioral coverage. This spy records
// the sources the MFi producer actually hands to it, including releases.
@interface MouseSupportSpy : NSObject
@property NSMutableDictionary<NSString *, NSNumber *> *owners;
@property NSMutableArray<NSString *> *releases;
- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source;
- (void)releaseMouseButtonsForSource:(NSString *)source;
@end
@implementation MouseSupportSpy
- (id)init { if ((self = [super init])) { _owners = [NSMutableDictionary new]; _releases = [NSMutableArray new]; } return self; }
- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source {
    if (pressed) _owners[source] = @(button); else [_owners removeObjectForKey:source];
}
- (void)releaseMouseButtonsForSource:(NSString *)source {
    [_releases addObject:source]; [_owners removeObjectForKey:source];
}
@end
@interface ControllerSupport : NSObject {
@public
    BOOL _shouldSendInputEvents;
    NSMutableDictionary *_controllers;
    int _derivedMouseButtonFlags;
    float _accumulatedMouseX;
    float _accumulatedMouseY;
}
@property MouseSupportSpy *mouseButtonSupport;
@end
@implementation ControllerSupport
'''

DRIVER = r'''
@end
int main(void) { @autoreleasepool {
    ControllerSupport *support = [ControllerSupport new];
    support->_shouldSendInputEvents = YES;
    support.mouseButtonSupport = [MouseSupportSpy new];
    Controller *first = [Controller new], *second = [Controller new];
    support->_controllers = [@{@1:first, @2:second} mutableCopy];
    [support.mouseButtonSupport sendMouseButton:BUTTON_LEFT pressed:YES source:@"appkit"];
    [support sendMouseButton:BUTTON_LEFT pressed:YES forController:first];
    [support sendMouseButton:BUTTON_LEFT pressed:YES forController:second];
    check(support.mouseButtonSupport.owners.count == 3, "physical mouse and two gamepads retain separate owners");
    first.lastMouseModeButtonFlags = A_FLAG;
    [support releaseMouseButtonsForController:first];
    check(support.mouseButtonSupport.owners.count == 2 && first.lastMouseModeButtonFlags == 0 &&
          support.mouseButtonSupport.owners[@"appkit"] != nil &&
          support.mouseButtonSupport.owners[[support mouseButtonSourceForController:second]] != nil,
          "disconnecting one gamepad releases only its own mouse buttons");
    support->_shouldSendInputEvents = NO;
    [support sendMouseButton:BUTTON_RIGHT pressed:YES forController:first];
    check(support.mouseButtonSupport.owners.count == 2, "uncaptured gamepad cannot create an owner");
    second.lastMouseModeButtonFlags = A_FLAG | B_FLAG;
    support->_accumulatedMouseX = 0.75;
    support->_accumulatedMouseY = -0.75;
    [support releaseRemoteMouseButtonsForUncapture];
    check(support->_accumulatedMouseX == 0 && support->_accumulatedMouseY == 0,
          "uncapture clears controller motion even when no timer tick runs");
    check(support.mouseButtonSupport.owners.count == 1 && support.mouseButtonSupport.owners[@"appkit"] != nil &&
          second.lastMouseModeButtonFlags == 0,
          "bulk controller release preserves a physical button still held");
    [support releaseMouseButtonsForController:nil];
    [support releaseRemoteMouseButtonsForUncapture];
    check(support.mouseButtonSupport.owners.count == 1, "repeated teardown does not release unrelated sources");
    return failures ? 1 : 0;
} }
'''


def main():
    text = SOURCE.read_text()
    signatures = ["-(NSString *) mouseButtonSourceForController:",
                  "-(void) sendMouseButton:(int)button pressed:(BOOL)pressed forController:",
                  "-(void) releaseMouseButtonsForController:",
                  "-(void) releaseRemoteMouseButtonsForUncapture"]
    source = PREAMBLE + "\n".join(method(text, signature) for signature in signatures) + DRIVER
    # Lifecycle entry points must release before losing the controller identity.
    disconnect = text[text.index("addObserverForName:GCControllerDidDisconnectNotification"):]
    assert disconnect.index("releaseMouseButtonsForController:limeController") < disconnect.index("[self->_controllers removeObjectForKey:")
    cleanup = method(text, "-(void) cleanup\n")
    assert cleanup.index("releaseRemoteMouseButtonsForUncapture") < cleanup.index("[_controllers removeAllObjects]")
    timer = method(text, "-(void) mouseTimerCallback:")
    assert timer.index("releaseMouseButtonsForController:controller") < timer.index("controller.isMouseMode = !controller.isMouseMode")
    print("ok   disconnect, mode exit, and cleanup release before discarding ownership")
    clang, sdk = clang_and_sdk("controller mouse ownership probe")
    with tempfile.TemporaryDirectory(prefix="controller-mouse-ownership-") as directory:
        path = Path(directory) / "probe.m"
        binary = Path(directory) / "probe"
        path.write_text(source)
        subprocess.run([clang, "-isysroot", sdk, "-fobjc-arc", "-framework", "Foundation",
                        str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
