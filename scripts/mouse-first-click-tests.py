#!/usr/bin/env python3
"""Execute the actual stream responder's first-click ordering without a live host."""
from pathlib import Path
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1]
    raise AssertionError(signature)


HARNESS = r'''
#import <AppKit/AppKit.h>
#define BUTTON_LEFT 1
@interface ClickProbe : NSObject
@property BOOL isRemoteDesktopMode;
@property BOOL captured;
@property BOOL captureAllowed;
@property NSMutableArray *wire;
@property BOOL edgeMenuClickConsumedLocally;
// Collapsed-tab ownership is exercised by edge_sensor_runtime_probe; this gate
// only certifies the stream-click ordering.
- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer;
- (void)ensureStreamWindowKeyIfPossible;
- (void)resumeInputForExplicitStreamClick:(NSEvent *)event;
- (void)updateCoreHIDFreeMouseTruthPointFromEvent:(NSEvent *)event;
- (void)reassertHiddenLocalCursorIfNeededWithReason:(NSString *)reason;
- (void)logMouseClickDiagnosticsForPhase:(NSString *)phase event:(NSEvent *)event;
- (void)captureFreeMouseIfNeededForEvent:(NSEvent *)event;
- (void)dispatchMouseButton:(int)button pressed:(BOOL)pressed event:(NSEvent *)event;
- (void)captureMouse;
- (void)completeDeferredMouseUncaptureIfNeeded;
@end
@implementation ClickProbe
- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer { return NO; }
- (void)ensureStreamWindowKeyIfPossible {}
// Explicit-release ownership is exercised by edge_sensor_runtime_probe.
- (void)resumeInputForExplicitStreamClick:(NSEvent *)event {}
- (void)updateCoreHIDFreeMouseTruthPointFromEvent:(NSEvent *)event {}
- (void)reassertHiddenLocalCursorIfNeededWithReason:(NSString *)reason {}
- (void)logMouseClickDiagnosticsForPhase:(NSString *)phase event:(NSEvent *)event {}
- (void)captureFreeMouseIfNeededForEvent:(NSEvent *)event {
    if (self.isRemoteDesktopMode && self.captureAllowed) self.captured = YES;
}
- (void)dispatchMouseButton:(int)button pressed:(BOOL)pressed event:(NSEvent *)event {
    if (self.captured) [self.wire addObject:pressed ? @"D" : @"U"];
}
- (void)captureMouse { if (self.captureAllowed) self.captured = YES; }
- (void)completeDeferredMouseUncaptureIfNeeded {}
__METHODS__
@end
int main(void) {
    @autoreleasepool {
        int failures = 0;
        for (int remote = 0; remote <= 1; remote++) {
            ClickProbe *p = [ClickProbe new];
            p.isRemoteDesktopMode = remote;
            p.captureAllowed = YES;
            p.wire = [NSMutableArray array];
            [p mouseDown:nil];
            BOOL held = [p.wire isEqual:@[@"D"]];
            [p mouseUp:nil];
            BOOL pair = [p.wire isEqual:@[@"D", @"U"]];
            printf("%s %s first click and drag begin with DOWN\n", held && pair ? "PASS" : "FAIL", remote ? "remote" : "game");
            failures += !(held && pair);
            [p mouseDown:nil]; [p mouseUp:nil];
            BOOL doubleClick = [p.wire isEqual:@[@"D", @"U", @"D", @"U"]];
            printf("%s double click sends exactly two pairs\n", doubleClick ? "PASS" : "FAIL");
            failures += !doubleClick;
        }
        ClickProbe *blocked = [ClickProbe new];
        blocked.wire = [NSMutableArray array];
        [blocked mouseDown:nil]; [blocked mouseUp:nil];
        BOOL closed = blocked.wire.count == 0;
        printf("%s unavailable capture forwards no input\n", closed ? "PASS" : "FAIL");
        return failures + !closed;
    }
}
'''


def main():
    source = (ROOT / 'Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m').read_text()
    methods = '\n'.join(method(source, signature) for signature in (
        '- (void)mouseDown:(NSEvent *)event', '- (void)mouseUp:(NSEvent *)event'))
    # Prevent a harness from certifying a responder AppKit never delivers the click to.
    view = (ROOT / 'Limelight/macOS/Views/StreamViewMac.m').read_text()
    assert 'return YES;' in method(view, '- (BOOL)acceptsFirstMouse:(NSEvent *)event')
    cc, sdk = clang_and_sdk('first click')
    with tempfile.TemporaryDirectory() as directory:
        def run(body, name):
            path = Path(directory) / (name + '.m')
            binary = Path(directory) / name
            path.write_text(HARNESS.replace('__METHODS__', body))
            subprocess.run([cc, '-fobjc-arc', '-Wall', '-Werror', '-isysroot', sdk,
                            '-framework', 'AppKit', str(path), '-o', str(binary)], check=True)
            return subprocess.run([str(binary)], capture_output=True, text=True)
        result = run(methods, 'shipping')
        print(result.stdout, end='')
        if result.returncode:
            raise SystemExit(result.returncode)
        press = '    [self dispatchMouseButton:BUTTON_LEFT pressed:YES event:event];\n'
        old_order = methods.replace(press, '').replace('    if (!self.isRemoteDesktopMode)', press + '    if (!self.isRemoteDesktopMode)', 1)
        assert old_order != methods
        assert run(old_order, 'legacy').returncode != 0, 'legacy first-click loss was not detected'
        print('PASS old capture-after-dispatch ordering fails the same test')


if __name__ == '__main__':
    main()
