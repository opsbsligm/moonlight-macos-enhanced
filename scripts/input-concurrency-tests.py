#!/usr/bin/env python3
"""Verify that relative pointer motion moves exactly once across threads.

A compound update on an atomic Objective-C property, and a read followed by a
separate clear, are each several accesses. Nothing in a build, a warning or a
link step reports that, which is how the pointer delta handoff between the
GameController callback queue and the CVDisplayLink output callback shipped
motion that was both dropped and duplicated.

The implementation under test is extracted from HIDSupport+Pointer.m instead of
being copied here, so the test cannot drift away from the shipping code. The
check runs in the real one producer and one consumer topology and in a wider
one, then proves the harness itself has teeth by rebuilding it with the previous
semantics, which must show the deviation.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain


SOURCE = "Limelight/Input/HIDSupport+Pointer.m"
CLASS = "HIDMouseDeltaAccumulator"

DECLS = """@interface HIDMouseDeltaAccumulator : NSObject
- (void)accumulateMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY;
- (void)takeAccumulatedMotionX:(CGFloat *)deltaXOut deltaY:(CGFloat *)deltaYOut;
@end
"""

# The semantics that were in place before the accumulator, kept deliberately so
# the harness is checked against a known-bad implementation.
LEGACY = DECLS.replace("@interface HIDMouseDeltaAccumulator : NSObject",
                       "@interface HIDMouseDeltaAccumulator : NSObject\n"
                       "@property (atomic) CGFloat pendingX;\n"
                       "@property (atomic) CGFloat pendingY;") + """
@implementation HIDMouseDeltaAccumulator
- (void)accumulateMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY {
    self.pendingX += deltaX;
    self.pendingY += deltaY;
}
- (void)takeAccumulatedMotionX:(CGFloat *)deltaXOut deltaY:(CGFloat *)deltaYOut {
    CGFloat x = self.pendingX;
    CGFloat y = self.pendingY;
    if (x != 0 || y != 0) {
        self.pendingX = 0;
        self.pendingY = 0;
    }
    if (deltaXOut != NULL) { *deltaXOut = x; }
    if (deltaYOut != NULL) { *deltaYOut = y; }
}
@end
"""

MAIN = r"""
#import <Foundation/Foundation.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
typedef double CGFloat;

__IMPL__

static HIDMouseDeltaAccumulator *g_accumulator;
static _Atomic int g_stop;
static _Atomic long long g_takenX;
static _Atomic long long g_takenY;

static void *producer(void *context) {
    (void)context;
    for (int i = 0; i < kIterations; i++) {
        [g_accumulator accumulateMotionX:1.0 deltaY:-1.0];
    }
    return NULL;
}

static void *consumer(void *context) {
    (void)context;
    CGFloat x = 0, y = 0;
    long long sumX = 0, sumY = 0;
    while (!atomic_load_explicit(&g_stop, memory_order_relaxed)) {
        [g_accumulator takeAccumulatedMotionX:&x deltaY:&y];
        sumX += (long long)llround(x);
        sumY += (long long)llround(y);
    }
    [g_accumulator takeAccumulatedMotionX:&x deltaY:&y];
    sumX += (long long)llround(x);
    sumY += (long long)llround(y);
    atomic_fetch_add(&g_takenX, sumX);
    atomic_fetch_add(&g_takenY, sumY);
    return NULL;
}

int main(void) {
    g_accumulator = [[HIDMouseDeltaAccumulator alloc] init];
    pthread_t producers[kProducers], consumers[kConsumers];
    for (long i = 0; i < kConsumers; i++) pthread_create(&consumers[i], NULL, consumer, (void *)i);
    for (long i = 0; i < kProducers; i++) pthread_create(&producers[i], NULL, producer, (void *)i);
    for (int i = 0; i < kProducers; i++) pthread_join(producers[i], NULL);
    atomic_store(&g_stop, 1);
    for (int i = 0; i < kConsumers; i++) pthread_join(consumers[i], NULL);

    long long expected = (long long)kProducers * kIterations;
    printf("expected=%lld takenX=%lld takenY=%lld\n", expected, g_takenX, g_takenY);
    if (g_takenX != expected || g_takenY != -expected) {
        printf("deviation dx=%lld dy=%lld\n", g_takenX - expected, g_takenY + expected);
        return 1;
    }
    printf("conserved\n");
    return 0;
}
"""

TOPOLOGIES = (("one producer and one consumer", 1, 1), ("four producers and three consumers", 4, 3))
LEGACY_ATTEMPTS = 5


def toolchain():
    """The compiler and SDK, as one matched pair. See scripts/apple_toolchain.py."""
    return apple_toolchain.clang_and_sdk("pointer concurrency probe")


def extract_implementation(path):
    source = open(path, encoding="utf-8").read()
    start = source.index("@implementation " + CLASS)
    end = source.index("@implementation HIDSupport (Pointer)")
    return source[start:end].rstrip() + "\n"


def build(clang, sdk, declarations, implementation, producers, consumers, workdir, name):
    enum = "enum { kProducers = %d, kConsumers = %d, kIterations = 300000 };" % (producers, consumers)
    program = MAIN.replace("__IMPL__", declarations + "\n" + implementation + "\n" + enum)
    source = os.path.join(workdir, name + ".m")
    binary = os.path.join(workdir, name)
    open(source, "w", encoding="utf-8").write(program)
    result = subprocess.run([clang, "-isysroot", sdk, "-fobjc-arc", "-O1",
                             "-framework", "Foundation", source, "-o", binary],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("error: the %s harness failed to compile:\n%s" % (name, result.stderr))
    return binary


def run(binary):
    return subprocess.run([binary], capture_output=True, text=True).returncode == 0


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    source = os.path.join(root, SOURCE)
    if not os.path.exists(source):
        sys.exit("error: %s not found" % source)
    clang, sdk = toolchain()
    implementation = extract_implementation(source)
    failures = []

    with tempfile.TemporaryDirectory() as workdir:
        for label, producers, consumers in TOPOLOGIES:
            binary = build(clang, sdk, DECLS, implementation, producers, consumers, workdir, "current")
            if not run(binary):
                failures.append("%s: motion was lost or duplicated" % label)
            else:
                print("ok   %s conserves every unit of motion" % label)

        deviations = 0
        for _ in range(LEGACY_ATTEMPTS):
            binary = build(clang, sdk, LEGACY, "", 1, 1, workdir, "legacy")
            if not run(binary):
                deviations += 1
        if deviations == 0:
            failures.append("the previous semantics conserved motion in this harness, so the "
                            "harness is not observing the race and cannot protect it")
        else:
            print("ok   the previous semantics deviated in %d of %d runs, so the harness has teeth"
                  % (deviations, LEGACY_ATTEMPTS))

    if failures:
        for failure in failures:
            print("FAIL %s" % failure)
        sys.exit(1)
    print("pointer delta handoff is exact on every topology")


main()
