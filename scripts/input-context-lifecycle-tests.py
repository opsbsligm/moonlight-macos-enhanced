#!/usr/bin/env python3
"""Exercise the shipping input lease and context setter on a real serial queue.

Checks queue drain before detachment, late producers, pointer reuse (ABA), host
replacement, and rejection before validation touches retired connection memory.
The negative control drops the lease generation check and must expose ABA.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / 'Limelight/Input/HIDSupport_Internal.h'
SOURCE = ROOT / 'Limelight/Input/HIDSupport.m'
POINTER_SOURCE = ROOT / 'Limelight/Input/HIDSupport+Pointer.m'

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#include <stdbool.h>
#include <stdint.h>
typedef struct { int host; } ML_CONNECTION_CONTEXT, *PML_CONNECTION_CONTEXT;
typedef struct { PML_CONNECTION_CONTEXT connectionContext; bool alive; } ML_INPUT_STREAM_CONTEXT, *PML_INPUT_STREAM_CONTEXT;
static const void *HIDInputQueueSpecificKey = &HIDInputQueueSpecificKey;
static _Thread_local PML_CONNECTION_CONTEXT selectedConnection;
static int invalidValidations = 0, offQueueValidations = 0, failures = 0;
static NSMutableArray<NSNumber *> *packets;
static NSMutableArray<NSArray<NSNumber *> *> *moves;
static void LiSendMouseMoveEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short x, short y) { [moves addObject:@[@(ctx->connectionContext->host), @(x), @(y)]]; }
static bool LiInputContextIsInitialized(PML_INPUT_STREAM_CONTEXT context) {
    if (!dispatch_get_specific(HIDInputQueueSpecificKey)) offQueueValidations++;
    if (!context->alive) invalidValidations++;
    return context->alive;
}
static void LiSetThreadConnectionContext(PML_CONNECTION_CONTEXT context) { selectedConnection = context; }
@interface HIDSupport : NSObject {
    void *_inputContext;
}
@property(atomic, assign) void *inputContext;
@property(atomic) uint64_t inputContextGeneration;
@property(strong) NSObject *inputContextLock;
@property dispatch_queue_t inputQueue;
@property BOOL shouldSendInputEvents;
@end
__HELPERS__
@implementation HIDSupport
@synthesize inputContext = _inputContext;
__GETTER__
__SETTER__
__POINTER_API__
@end
static void check(BOOL good, const char *message) {
    printf("%s %s\n", good ? "PASS" : "FAIL", message);
    if (!good) failures++;
}
static void drain(HIDSupport *support) { dispatch_sync(support.inputQueue, ^{}); }
static void send(HIDSupport *support, HIDInputLease lease, int value) {
    HIDDispatchInput(support, lease, ^{
        check(selectedConnection == lease.context->connectionContext, "queue selects leased connection TLS");
        [packets addObject:@(selectedConnection->host * 100 + value)];
    });
}
int main(void) {
    @autoreleasepool {
        packets = [NSMutableArray array];
        moves = [NSMutableArray array];
        HIDSupport *support = [HIDSupport new];
        support.inputContextLock = [NSObject new];
        support.shouldSendInputEvents = YES;
        support.inputQueue = dispatch_queue_create("test.input.context", DISPATCH_QUEUE_SERIAL);
        dispatch_queue_set_specific(support.inputQueue, HIDInputQueueSpecificKey, (__bridge void *)support, NULL);
        ML_CONNECTION_CONTEXT firstConnection = { 1 }, secondConnection = { 2 };
        ML_INPUT_STREAM_CONTEXT first = { &firstConnection, true }, second = { &secondConnection, true };
        support.inputContext = &first;
        HIDInputLease original = HIDAcquireInputContext(support);
        check(original.context == &first && original.generation == support.inputContextGeneration,
              "acquisition snapshots pointer and generation without validating connection memory");
        check(offQueueValidations == 0, "producer does not validate context outside the consumer queue");

        dispatch_semaphore_t entered = dispatch_semaphore_create(0);
        dispatch_semaphore_t proceed = dispatch_semaphore_create(0);
        dispatch_semaphore_t detachStarted = dispatch_semaphore_create(0);
        dispatch_semaphore_t detached = dispatch_semaphore_create(0);
        dispatch_async(support.inputQueue, ^{
            dispatch_semaphore_signal(entered);
            dispatch_semaphore_wait(proceed, DISPATCH_TIME_FOREVER);
        });
        dispatch_semaphore_wait(entered, DISPATCH_TIME_FOREVER);
        send(support, original, 1);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            dispatch_semaphore_signal(detachStarted);
            support.inputContext = NULL;
            dispatch_semaphore_signal(detached);
        });
        dispatch_semaphore_wait(detachStarted, DISPATCH_TIME_FOREVER);
        long earlyDetach = dispatch_semaphore_wait(detached, dispatch_time(DISPATCH_TIME_NOW, 50000000));
        check(earlyDetach != 0 && support.inputContext == &first, "detach waits for queued input before replacing pointer");
        dispatch_semaphore_signal(proceed);
        if (earlyDetach != 0) dispatch_semaphore_wait(detached, DISPATCH_TIME_FOREVER);
        check([packets isEqual:@[@101]] && support.inputContext == NULL,
              "queued press finishes before detach returns");

        first.alive = false;
        send(support, original, 2);
        drain(support);
        check([packets isEqual:@[@101]] && invalidValidations == 0,
              "late producer is rejected before touching retired context");

        support.inputContext = &second;
        send(support, original, 3);
        send(support, HIDAcquireInputContext(support), 4);
        drain(support);
        check([packets isEqual:@[@101, @204]], "reconnected host receives only its own lease");

        support.inputContext = NULL;
        first.connectionContext = &secondConnection;
        first.alive = true;
        support.inputContext = &first;
        send(support, original, 5);
        send(support, HIDAcquireInputContext(support), 6);
        drain(support);
        check([packets isEqual:@[@101, @204, @206]], "same-address context reuse rejects earlier generation (ABA)");
        check(invalidValidations == 0 && offQueueValidations == 0,
              "every initialization check runs on queue for a live context");

        [support sendRelativeMouseMoveDeltaX:7 deltaY:-3];
        [support sendRelativeMouseMoveDeltaX:0 deltaY:0];
        support.shouldSendInputEvents = NO;
        [support sendRelativeMouseMoveDeltaX:99 deltaY:99];
        support.inputContext = NULL;
        check([moves isEqual:@[@[@2, @7, @-3]]],
              "controller motion preserves quantized delta and drains before detach; capture gate rejects later motion");
        support.shouldSendInputEvents = YES;
        [support sendRelativeMouseMoveDeltaX:88 deltaY:88];
        drain(support);
        check(moves.count == 1, "controller motion has no raw context fallback after detachment");

        dispatch_sync(support.inputQueue, ^{ support.inputContext = NULL; });
        check(support.inputContext == NULL, "detaching from the input queue does not deadlock");
        check(HIDValidateInputContext(NULL, "test") == false, "producer presence gate rejects missing context");
        printf("%d failure(s)\n", failures);
        return failures ? 1 : 0;
    }
}
'''

def method(source, anchor):
    begin = source.index(anchor)
    opening = source.index('{', begin)
    depth, cursor = 1, opening + 1
    while depth:
        if source[cursor] == '{': depth += 1
        elif source[cursor] == '}': depth -= 1
        cursor += 1
    return source[begin:cursor]

def run(negative=False):
    header = HEADER.read_text()
    begin = header.index('typedef struct {\n    PML_INPUT_STREAM_CONTEXT context;')
    end = header.index('static inline CGFloat HIDPointerSensitivityForHost', begin)
    helpers = header[begin:end].replace('extern const void *HIDInputQueueSpecificKey;', '')
    if negative:
        target = 'support.inputContextGeneration != lease.generation || '
        assert target in helpers
        helpers = helpers.replace(target, '')
    source = SOURCE.read_text()
    setter = method(source, '- (void)setInputContext:(void *)inputContext {')
    # Only the downstream UI diagnostics/monitoring side effects are excluded;
    # the complete context replacement/drain operation is shipping source.
    setter = setter[:setter.index('    [self syncScrollTraceDiagnosticsPreferenceToInputContext];')] + '}\n'
    getter = method(source, '- (void *)inputContext {') if '- (void *)inputContext {' in source else ''
    pointer_api = method(POINTER_SOURCE.read_text(), '- (void)sendRelativeMouseMoveDeltaX:(short)deltaX deltaY:(short)deltaY {')
    code = HARNESS.replace('__HELPERS__', helpers).replace('__SETTER__', setter).replace('__GETTER__', getter).replace('__POINTER_API__', pointer_api)
    clang, sdk = clang_and_sdk('input context lifecycle regression')
    with tempfile.TemporaryDirectory(prefix='moonlight-context-lifecycle-') as directory:
        probe = Path(directory) / 'probe.m'
        executable = Path(directory) / 'probe'
        probe.write_text(code)
        subprocess.run([clang, '-isysroot', sdk, '-fobjc-arc', '-fblocks', '-framework', 'Foundation', str(probe), '-o', str(executable)], check=True)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if negative:
            if result.returncode == 0:
                raise SystemExit('FAIL removed generation check did not expose ABA')
            print('PASS negative control detects same-address stale input')
        elif result.returncode:
            raise SystemExit(result.returncode)

if __name__ == '__main__':
    run('--self-test' in sys.argv)
