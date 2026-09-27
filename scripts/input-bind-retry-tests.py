#!/usr/bin/env python3
"""Replay startup callbacks and input retries across stop/reconnect boundaries.

The binding methods and callback entry guards are extracted from the app. A
deterministic scheduler separates callback receipt from execution without a
network, UI session, real input, or sleeps. Connection spies flag context access
after retirement and expose weak references to verify the retry's ownership.
"""
from pathlib import Path
import subprocess
import tempfile

from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Limelight/macOS/ViewControllers/StreamViewController.m"


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
#import <dispatch/dispatch.h>
#define Log(...) ((void)0)
typedef struct { BOOL initialized, retired; } ML_INPUT_STREAM_CONTEXT, *PML_INPUT_STREAM_CONTEXT;
static NSMutableArray *pending;
static int failures, reads, retiredReads, startedEffects;
static void enqueue(dispatch_block_t block) { [pending addObject:[block copy]]; }
static void runOne(void) { dispatch_block_t block = pending.firstObject; [pending removeObjectAtIndex:0]; block(); }
static void runAll(void) { while (pending.count) runOne(); }
#define dispatch_async(queue, block) enqueue(block)
#define dispatch_after(time, queue, block) enqueue(block)
static BOOL LiInputContextIsInitialized(PML_INPUT_STREAM_CONTEXT ctx) {
    if (ctx->retired) retiredReads++; return ctx->initialized;
}
@interface Connection : NSObject {
@public ML_INPUT_STREAM_CONTEXT state;
}
@property(getter=isCancelled) BOOL cancelled;
@property int microphoneNotifications;
+ (Connection *)currentConnection;
- (void *)inputStreamContext;
- (void)notifyInputStreamReadyForMicrophoneControlIfNeeded;
@end
static Connection *currentConnection;
@implementation Connection
+ (Connection *)currentConnection { return currentConnection; }
- (void *)inputStreamContext { reads++; if (state.retired) retiredReads++; return &state; }
- (void)notifyInputStreamReadyForMicrophoneControlIfNeeded { _microphoneNotifications++; }
@end
@interface StreamManager : NSObject
@property Connection *connection;
@end
@implementation StreamManager
@end
@interface InputSupport : NSObject
@property void *inputContext;
@property BOOL shouldSendInputEvents;
@end
@implementation InputSupport
@end
@interface StreamViewController : NSObject
@property BOOL stopStreamInProgress;
@property BOOL reconnectInProgress;
@property NSUInteger activeStreamGeneration;
@property StreamManager *streamMan;
@property InputSupport *hidSupport;
@property InputSupport *controllerSupport;
@property int rearms;
- (void)rearmMouseCaptureIfPossibleWithReason:(NSString *)reason;
@end
@implementation StreamViewController
- (void)rearmMouseCaptureIfPossibleWithReason:(NSString *)reason { _rearms++; }
'''

DRIVER = r'''
@end
static void check(BOOL good, const char *label) {
    printf("%s %s\n", good ? "ok  " : "FAIL", label); failures += !good;
}
static StreamViewController *controller(Connection *connection) {
    StreamViewController *owner = [StreamViewController new];
    owner.activeStreamGeneration = 1;
    owner.streamMan = [StreamManager new];
    owner.streamMan.connection = connection;
    owner.hidSupport = [InputSupport new];
    owner.controllerSupport = [InputSupport new];
    return owner;
}
int main(void) { @autoreleasepool {
    pending = [NSMutableArray new];
    Connection *first = [Connection new];
    first->state.initialized = YES;
    StreamViewController *owner = controller(first);
    [owner bindInputForConnection:first generation:1 remainingAttempts:2];
    check(owner.hidSupport.inputContext == &first->state &&
          owner.controllerSupport.inputContext == &first->state &&
          !owner.hidSupport.shouldSendInputEvents && !owner.controllerSupport.shouldSendInputEvents && owner.rearms == 1,
          "ready connection binds consumers without capturing background input");

    first->state.initialized = NO;
    [owner bindInputForConnection:first generation:1 remainingAttempts:2];
    int before = reads;
    owner.stopStreamInProgress = YES;
    first->state.retired = YES;
    runAll();
    check(reads == before && retiredReads == 0, "stop cancels a retry before any old context access");
    owner.stopStreamInProgress = NO;
    first->state.retired = NO;
    [owner bindInputForConnection:first generation:1 remainingAttempts:2];
    before = reads;
    owner.activeStreamGeneration = 2;
    first->state.retired = YES;
    runAll();
    check(reads == before && retiredReads == 0, "generation change rejects a retry even if the object is unchanged");

    Connection *second = [Connection new];
    second->state.initialized = YES;
    owner.streamMan.connection = second;
    before = reads;
    [owner bindInputForConnection:first generation:2 remainingAttempts:2];
    check(reads == before && retiredReads == 0, "replacement identity rejects an old connection even with matching generation");
    owner.reconnectInProgress = YES;
    [owner bindInputForConnection:second generation:2 remainingAttempts:2];
    check(owner.hidSupport.inputContext == &second->state,
          "the active replacement may bind while reconnect UI is still visible");
    second.cancelled = YES;
    before = reads;
    [owner bindInputForConnection:second generation:2 remainingAttempts:2];
    check(reads == before, "cancelled operation cannot rebind input");
    second.cancelled = NO;

    __weak Connection *weakConnection;
    @autoreleasepool {
        Connection *temporary = [Connection new];
        weakConnection = temporary;
        owner.streamMan.connection = temporary;
        [owner bindInputForConnection:temporary generation:2 remainingAttempts:1];
        owner.streamMan.connection = second;
    }
    check(weakConnection != nil, "pending retry strongly retains the context's Connection owner");
    runAll();
    check(weakConnection == nil, "obsolete retry releases its Connection after rejecting identity");

    currentConnection = second;
    [owner stageComplete:"input stream establishment"];
    before = reads;
    owner.activeStreamGeneration++;
    runAll();
    check(reads == before, "delayed stageComplete cannot bind after generation changes");
    [owner connectionStarted];
    before = reads;
    owner.stopStreamInProgress = YES;
    runAll();
    check(reads == before && startedEffects == 0, "delayed connectionStarted is rejected before startup effects");
    owner.stopStreamInProgress = NO;
    [owner connectionStarted];
    runAll();
    check(startedEffects == 1, "current connectionStarted still binds normally");

    second->state.initialized = NO;
    before = reads;
    [owner bindInputForConnection:second generation:owner.activeStreamGeneration remainingAttempts:2];
    runAll();
    check(reads == before + 3 && pending.count == 0, "uninitialized context retries have a finite budget");
    check(retiredReads == 0, "all retired connection contexts remained untouched");
    currentConnection = nil;
    return failures ? 1 : 0;
} }
'''


def main():
    text = SOURCE.read_text()
    text = text[text.index("#pragma mark - ConnectionCallbacks"):]
    names = ["- (BOOL)isCurrentInputBindingConnection:", "- (void)bindInputForConnection:",
             "- (void)stageComplete:"]
    implementation = "\n".join(method(text, name) for name in names)
    started = method(text, "- (void)connectionStarted {")
    # Keep the actual queue hop and validation guard. Downstream UI setup is
    # replaced with a counter and the exact shipping bind call it contains.
    call = "[self bindInputForConnection:callbackConn generation:callbackGeneration remainingAttempts:20];"
    assert call in started
    assert "callbackInputContext" not in started and "retryBind" not in started
    prefix = started[:started.index("        @try {")]
    implementation += "\n" + prefix + "startedEffects++; " + call + "\n    });\n}\n"
    variants = [("current", implementation, True)]
    for label, guard in (
        ("stop guard", "!self.stopStreamInProgress &&"),
        ("generation guard", "generation == self.activeStreamGeneration &&"),
        ("connection identity", "self.streamMan.connection == connection &&"),
    ):
        assert implementation.count(guard) == 1
        variants.append((label, implementation.replace(guard, "", 1), False))
    clang, sdk = clang_and_sdk("input binding retry regression")
    with tempfile.TemporaryDirectory(prefix="input-bind-retry-") as directory:
        for index, (label, methods, expected) in enumerate(variants):
            path, binary = Path(directory) / f"probe{index}.m", Path(directory) / f"probe{index}"
            path.write_text(PREAMBLE + methods + DRIVER)
            subprocess.run([clang, "-isysroot", sdk, "-fobjc-arc", "-framework", "Foundation",
                            str(path), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
            if expected or (result.returncode == 0) != expected:
                print(result.stdout, end="")
                print(result.stderr, end="")
            if (result.returncode == 0) != expected:
                raise SystemExit(f"{label} unexpectedly returned {result.returncode}")
            if not expected:
                print(f"ok   missing {label} is rejected")


if __name__ == "__main__":
    main()
