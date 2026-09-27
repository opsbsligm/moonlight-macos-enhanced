#!/usr/bin/env python3
"""Execute the shipping mouse ownership methods against a real serial queue.

Covers delayed press/uncapture ordering, fixed press-time mappings, independent
sources, duplicate HID reports, unpaired releases and disabled capture. The
negative control replaces only release dispatch with the old immediate send.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Limelight/Input/HIDSupport+Pointer.m'

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#include <stdint.h>
#define BUTTON_ACTION_PRESS 1
#define BUTTON_ACTION_RELEASE 2
#define BUTTON_LEFT 1
#define BUTTON_MIDDLE 2
#define BUTTON_RIGHT 3
#define BUTTON_X1 4
#define BUTTON_X2 5
typedef void *PML_INPUT_STREAM_CONTEXT;
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
static BOOL swapButtons = NO;
static uint64_t sessionGeneration = 1;
static NSMutableArray<NSNumber *> *packets;
static void LiSendMouseMoveEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short x, short y) {}
static int failures;
@interface SettingsClass : NSObject
+ (BOOL)swapMouseButtonsFor:(NSString *)uuid;
@end
@implementation SettingsClass
+ (BOOL)swapMouseButtonsFor:(NSString *)uuid { return swapButtons; }
@end
@interface TestHost : NSObject
@property NSString *uuid;
@end
@implementation TestHost
@end
@interface HIDSupport : NSObject
@property TestHost *host;
@property dispatch_queue_t inputQueue;
@property BOOL shouldSendInputEvents;
@property uint32_t pressedMouseButtonsMask;
@property uint64_t mouseButtonOwnersGeneration;
@property NSMutableDictionary<NSString *, NSMutableDictionary<NSNumber *, NSNumber *> *> *mouseButtonOwners;
- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source;
- (void)releaseMouseButtonsForSource:(NSString *)source;
- (void)releaseAllPressedMouseButtons;
- (BOOL)hasPressedMouseButtons;
- (void)recordMouseButtonDiagnosticsAction:(NSString *)action button:(int)button mask:(uint32_t)mask synthetic:(BOOL)synthetic;
@end
static HIDInputLease HIDAcquireInputContext(HIDSupport *support) { return (HIDInputLease){ (void *)1, sessionGeneration }; }
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) { return ctx != NULL; }
static uint32_t HIDMouseButtonBitForButton(int button) { return button >= 1 && button <= 5 ? 1u << (button - 1) : 0; }
static void HIDDispatchInput(HIDSupport *support, HIDInputLease lease, dispatch_block_t block) { dispatch_async(support.inputQueue, block); }
static void HIDDispatchInputImmediately(HIDSupport *support, HIDInputLease lease, dispatch_block_t block) { block(); }
static void LiSendMouseButtonEventCtx(PML_INPUT_STREAM_CONTEXT ctx, int action, int button) {
    @synchronized (packets) { [packets addObject:@(action == BUTTON_ACTION_PRESS ? button : -button)]; }
}
@implementation HIDSupport
- (void)recordMouseButtonDiagnosticsAction:(NSString *)action button:(int)button mask:(uint32_t)mask synthetic:(BOOL)synthetic {}
__METHODS__
@end
static void drain(HIDSupport *support) { dispatch_sync(support.inputQueue, ^{}); }
static void check(BOOL good, const char *message) {
    printf("%s %s\n", good ? "PASS" : "FAIL", message);
    if (!good) failures++;
}
static void expect(HIDSupport *support, NSArray<NSNumber *> *expected, const char *message) {
    drain(support);
    check([packets isEqual:expected], message);
    [packets removeAllObjects];
}
int main(void) {
    @autoreleasepool {
        packets = [NSMutableArray array];
        HIDSupport *support = [HIDSupport new];
        support.host = [TestHost new];
        support.host.uuid = @"test";
        support.shouldSendInputEvents = YES;
        support.inputQueue = dispatch_queue_create("test.mouse.packets", DISPATCH_QUEUE_SERIAL);

        dispatch_suspend(support.inputQueue);
        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"appkit"];
        [support releaseAllPressedMouseButtons];
        dispatch_resume(support.inputQueue);
        expect(support, @[@1, @-1], "queued press precedes uncapture release");
        check(![support hasPressedMouseButtons], "uncapture empties ownership");

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"appkit"];
        swapButtons = YES;
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"appkit"];
        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"appkit"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"appkit"];
        expect(support, @[@1, @-1, @3, @-3], "release uses press-time mapping; next press uses new setting");
        swapButtons = NO;

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"mouse-1"];
        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"mouse-1"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"unknown"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"mouse-1"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"mouse-1"];
        expect(support, @[@1, @-1], "duplicate presses and orphan releases produce no extra edges");

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"mouse-1"];
        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"controller"];
        [support releaseMouseButtonsForSource:@"controller"];
        check([support hasPressedMouseButtons], "disconnect preserves another owner's hold");
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"mouse-1"];
        expect(support, @[@1, @-1], "multiple sources share one remote edge pair");

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"held"];
        support.shouldSendInputEvents = NO;
        [support sendMouseButton:BUTTON_RIGHT pressed:YES source:@"local"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"held"];
        expect(support, @[@1, @-1], "disabled capture rejects new press but retires an existing hold");
        support.shouldSendInputEvents = YES;

        for (int button = 1; button <= 5; button++)
            [support sendMouseButton:button pressed:YES source:@"five-buttons"];
        [support releaseAllPressedMouseButtons];
        [support releaseAllPressedMouseButtons];
        expect(support, @[@1, @2, @3, @4, @5, @-1, @-2, @-3, @-4, @-5], "all five buttons release once and cleanup is idempotent");

        [support sendMouseButton:0 pressed:YES source:@"invalid"];
        [support sendMouseButton:42 pressed:YES source:@"invalid"];
        [support sendMouseButton:1 pressed:YES source:@""];
        expect(support, @[], "unknown button and source are rejected");

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"reused-owner"];
        expect(support, @[@1], "first session receives its press");
        sessionGeneration++;
        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"reused-owner"];
        [support sendMouseButton:BUTTON_LEFT pressed:NO source:@"reused-owner"];
        expect(support, @[@1, @-1], "new session discards previous ownership before accepting the same source");

        [support sendMouseButton:BUTTON_LEFT pressed:YES source:@"old-cleanup-all"];
        expect(support, @[@1], "old session owns a button before global cleanup");
        sessionGeneration++;
        [support releaseAllPressedMouseButtons];
        expect(support, @[], "global cleanup of an old generation never sends release to the new host");
        check(![support hasPressedMouseButtons], "global cleanup discards obsolete local ownership");

        [support sendMouseButton:BUTTON_RIGHT pressed:YES source:@"old-cleanup-source"];
        expect(support, @[@3], "old session owns a source before per-device cleanup");
        sessionGeneration++;
        [support releaseMouseButtonsForSource:@"old-cleanup-source"];
        expect(support, @[], "per-source cleanup of an old generation never sends release to the new host");
        check(![support hasPressedMouseButtons], "per-source cleanup discards obsolete local ownership");

        dispatch_apply(32, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t source) {
            NSString *name = [NSString stringWithFormat:@"concurrent-%zu", source];
            for (int i = 0; i < 100; i++) {
                [support sendMouseButton:BUTTON_LEFT pressed:YES source:name];
                [support sendMouseButton:BUTTON_LEFT pressed:NO source:name];
            }
        });
        drain(support);
        BOOL alternating = packets.count > 0 && packets.count % 2 == 0;
        for (NSUInteger i = 0; i < packets.count; i++) {
            if (packets[i].intValue != (i % 2 == 0 ? 1 : -1)) alternating = NO;
        }
        check(alternating && ![support hasPressedMouseButtons], "concurrent producers preserve balanced remote state");
        printf("%d failure(s)\n", failures);
        return failures ? 1 : 0;
    }
}
'''

def implementation():
    source = SOURCE.read_text()
    begin = source.index('- (HIDInputLease)currentMouseButtonLease {')
    end = source.index('- (void)mouseDown:', begin)
    return source[begin:end]

def run(negative=False):
    methods = implementation()
    if negative:
        start = methods.index('- (void)enqueueMouseButtonReleasesForMask:')
        end = methods.index('- (void)releaseAllPressedMouseButtons', start)
        methods = methods[:start] + methods[start:end].replace('HIDDispatchInput(', 'HIDDispatchInputImmediately(') + methods[end:]
    clang, sdk = clang_and_sdk('mouse ownership regression')
    with tempfile.TemporaryDirectory(prefix='moonlight-mouse-buttons-') as temp:
        source = Path(temp) / 'probe.m'
        binary = Path(temp) / 'probe'
        source.write_text(HARNESS.replace('__METHODS__', methods))
        subprocess.run([clang, '-isysroot', sdk, '-fobjc-arc', '-fblocks', '-framework', 'Foundation', str(source), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if negative:
            if result.returncode == 0:
                raise SystemExit('FAIL negative control did not expose release-before-press')
            print('PASS negative control detects legacy release ordering')
        elif result.returncode != 0:
            raise SystemExit(result.returncode)

if __name__ == '__main__':
    run('--self-test' in sys.argv)
