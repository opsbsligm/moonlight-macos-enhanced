#!/usr/bin/env python3
"""Compile the real keyboard/button senders and bounded queue, without a host.

Exercise congestion recovery, FIFO order, shutdown during backpressure, and
allocation/timeout failures. Transport callbacks must run only on the consumer,
not synchronously under the producer's application locks. A legacy drop-on-full
mutation must fail the same scenarios.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "moonlight-common/moonlight-common-c/src"


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


PREAMBLE = r'''
#include "Limelight-internal.h"
#include <time.h>
#undef ListenerCallbacks
#undef StreamConfig

static int failures, callbackCount, callbackError;
static bool denyAllocation;
// Set by the thread that is about to enqueue, so the helper that hands a slot back stops guessing
// when that moment happens. See waitForProducer for why a fixed sleep cannot work here.
static atomic_int producerStarted;
static pthread_t callbackThread;
static void check(bool value, const char *name) {
    printf("%s %s\n", value ? "ok  " : "FAIL", name);
    failures += !value;
}
static void terminated(int error) {
    callbackCount++;
    callbackError = error;
    callbackThread = pthread_self();
}
static void *probeMalloc(size_t size) { return denyAllocation ? NULL : malloc(size); }
int PltCreateMutex(PLT_MUTEX *m) { return pthread_mutex_init(m, NULL); }
void PltDeleteMutex(PLT_MUTEX *m) { pthread_mutex_destroy(m); }
void PltLockMutex(PLT_MUTEX *m) { pthread_mutex_lock(m); }
void PltUnlockMutex(PLT_MUTEX *m) { pthread_mutex_unlock(m); }
int PltCreateConditionVariable(PLT_COND *c, PLT_MUTEX *m) {
    (void)m; return pthread_cond_init(c, NULL);
}
void PltDeleteConditionVariable(PLT_COND *c) { pthread_cond_destroy(c); }
void PltSignalConditionVariable(PLT_COND *c) { pthread_cond_signal(c); }
void PltWaitForConditionVariable(PLT_COND *c, PLT_MUTEX *m) { pthread_cond_wait(c, m); }
uint64_t PltGetMillis(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
void PltSleepMs(int ms) { usleep(ms * 1000); }
#define AppVersionQuad (ctx->connectionContext->AppVersionQuad)
#define ListenerCallbacks (ctx->connectionContext->ListenerCallbacks)
#define PAYLOAD_SIZE(x) BE32((x)->packet.header.size)
#define PACKET_SIZE(x) (PAYLOAD_SIZE(x) + sizeof(uint32_t))
#define malloc probeMalloc
'''

DRIVER = r'''
#undef malloc
#undef AppVersionQuad
#undef ListenerCallbacks

static void init(ML_CONNECTION_CONTEXT *connection) {
    memset(connection, 0, sizeof(*connection));
    connection->AppVersionQuad[0] = 7;
    connection->AppVersionQuad[3] = -1;
    connection->ListenerCallbacks.connectionTerminated = terminated;
    ML_INPUT_STREAM_CONTEXT *ctx = &connection->inputContext;
    ctx->connectionContext = connection;
    atomic_init(&ctx->initialized, true);
    atomic_init(&ctx->inputEdgeFailure, 0);
    LbqInitializeLinkedBlockingQueue(&ctx->packetQueue, MAX_QUEUED_INPUT_PACKETS);
    LbqInitializeLinkedBlockingQueue(&ctx->packetHolderFreeList, MAX_QUEUED_INPUT_PACKETS);
    callbackCount = callbackError = 0;
}
static void destroy(ML_CONNECTION_CONTEXT *connection) {
    LINKED_BLOCKING_QUEUE *queues[] = {&connection->inputContext.packetQueue,
                                      &connection->inputContext.packetHolderFreeList};
    for (int i = 0; i < 2; i++) {
        LbqSignalQueueShutdown(queues[i]);
        PLINKED_BLOCKING_QUEUE_ENTRY item = LbqDestroyLinkedBlockingQueue(queues[i]);
        while (item) {
            PLINKED_BLOCKING_QUEUE_ENTRY next = item->flink;
            free(item->data);
            item = next;
        }
    }
}
// A fixed sleep used to space "the producer is blocked" against "a slot came back", and on a
// slow runner the producer's own 100ms edge wait expired before the helper thread was even
// scheduled. The product then failed closed exactly as designed and the test reported it as a
// product failure: two x86_64 CI runs, both with the same cascade (release not queued, bound
// broken, session not alive), while arm64 and 136 local runs stayed green. Waiting for the
// producer instead of sleeping removes that race without touching one assertion, and the bound
// keeps a broken handshake from turning into a hang.
static void waitForProducer(int extraMs) {
    for (int spin = 0; spin < 500 && !atomic_load(&producerStarted); spin++) PltSleepMs(1);
    for (int spin = 0; spin < extraMs; spin++) PltSleepMs(1);
}
static void fill(ML_INPUT_STREAM_CONTEXT *ctx) {
    for (int i = 0; i < MAX_QUEUED_INPUT_PACKETS; i++) {
        if (LiSendKeyboardEvent2Ctx(ctx, (short)(0x8000 | i), KEY_ACTION_DOWN, 0, 0)) abort();
    }
}
static void *freeOneSlot(void *argument) {
    ML_INPUT_STREAM_CONTEXT *ctx = argument;
    waitForProducer(0);
    PPACKET_HOLDER holder;
    if (LbqPollQueueElement(&ctx->packetQueue, (void **)&holder)) abort();
    freePacketHolder(ctx, holder);
    return NULL;
}
static void *stopProducer(void *argument) {
    ML_INPUT_STREAM_CONTEXT *ctx = argument;
    // Interrupt inside the wait window: too early and the send never blocks (so nothing is
    // interrupted), too late and it has already failed closed.
    waitForProducer(2);
    atomic_store(&ctx->initialized, false);
    LbqSignalQueueDrain(&ctx->packetQueue);
    return NULL;
}
static void *reportFailure(void *argument) {
    ML_INPUT_STREAM_CONTEXT *ctx = argument;
    void *holder = NULL;
    int result = LbqWaitForQueueElement(&ctx->packetQueue, &holder);
    check(result == LBQ_USER_WAKE, "lost edge wakes the input consumer");
    if (holder != NULL) freePacketHolder(ctx, holder);
    check(reportInputEdgeFailureIfPending(ctx), "consumer reports the failure");
    check(!reportInputEdgeFailureIfPending(ctx), "failure callback occurs exactly once");
    return NULL;
}
static void congestionRecovery(bool mouse) {
    ML_CONNECTION_CONTEXT connection;
    init(&connection);
    ML_INPUT_STREAM_CONTEXT *ctx = &connection.inputContext;
    fill(ctx);
    pthread_t consumer;
    atomic_store(&producerStarted, 0);
    pthread_create(&consumer, NULL, freeOneSlot, ctx);
    atomic_store(&producerStarted, 1);
    int result = mouse ? LiSendMouseButtonEventCtx(ctx, BUTTON_ACTION_RELEASE, BUTTON_LEFT)
                       : LiSendKeyboardEvent2Ctx(ctx, 0x8043, KEY_ACTION_UP, 0, 0);
    pthread_join(consumer, NULL);
    check(result == LBQ_SUCCESS, mouse ? "left release survives temporary congestion"
                                      : "C release survives temporary congestion");
    check(LbqGetItemCount(&ctx->packetQueue) == MAX_QUEUED_INPUT_PACKETS,
          "backpressure preserves the finite queue bound");
    bool fifo = true;
    PPACKET_HOLDER holder;
    for (int i = 1; i < MAX_QUEUED_INPUT_PACKETS; i++) {
        if (LbqPollQueueElement(&ctx->packetQueue, (void **)&holder) != LBQ_SUCCESS) { fifo = false; break; }
        fifo &= LE16(holder->packet.keyboard.keyCode) == (short)(0x8000 | i);
        freePacketHolder(ctx, holder);
    }
    if (LbqPollQueueElement(&ctx->packetQueue, (void **)&holder) == LBQ_SUCCESS) {
        fifo &= holder->channelId == (mouse ? CTRL_CHANNEL_MOUSE : CTRL_CHANNEL_KEYBOARD);
        fifo &= LE32(holder->packet.header.magic) == (mouse ? MOUSE_BUTTON_UP_EVENT_MAGIC_GEN5
                                                          : KEY_UP_EVENT_MAGIC);
        freePacketHolder(ctx, holder);
    } else fifo = false;
    check(fifo, "release follows all earlier presses in FIFO order");
    check(callbackCount == 0 && atomic_load(&ctx->initialized), "recovery keeps the session alive");
    destroy(&connection);
}
int main(void) {
    congestionRecovery(false);
    congestionRecovery(true);

    ML_CONNECTION_CONTEXT connection;
    init(&connection);
    ML_INPUT_STREAM_CONTEXT *ctx = &connection.inputContext;
    fill(ctx);
    uint64_t before = PltGetMillis();
    int result = LiSendKeyboardEvent2Ctx(ctx, 0x8043, KEY_ACTION_UP, 0, 0);
    check(result == LBQ_BOUND_EXCEEDED && !atomic_load(&ctx->initialized),
          "persistent congestion fails closed instead of leaving C stuck");
    check(PltGetMillis() - before < INPUT_EDGE_QUEUE_WAIT_MS + 1000,
          "producer wait is bounded");
    check(callbackCount == 0, "producer never calls connection callbacks synchronously");
    if (atomic_load(&ctx->inputEdgeFailure)) {
        pthread_t consumer;
        pthread_create(&consumer, NULL, reportFailure, ctx);
        pthread_join(consumer, NULL);
        check(callbackCount == 1 && callbackError == ML_ERROR_INPUT_STREAM &&
              !pthread_equal(callbackThread, pthread_self()), "callback runs on the consumer thread");
    } else check(false, "lost edge must schedule a failure callback");
    check(LiSendMouseButtonEventCtx(ctx, BUTTON_ACTION_PRESS, BUTTON_LEFT) == -2,
          "failed session refuses later edges");
    destroy(&connection);

    init(&connection);
    fill(ctx);
    pthread_t stopper;
    atomic_store(&producerStarted, 0);
    pthread_create(&stopper, NULL, stopProducer, ctx);
    atomic_store(&producerStarted, 1);
    result = LiSendMouseButtonEventCtx(ctx, BUTTON_ACTION_RELEASE, BUTTON_LEFT);
    pthread_join(stopper, NULL);
    check(result == LBQ_INTERRUPTED && callbackCount == 0 && !atomic_load(&ctx->inputEdgeFailure),
          "normal shutdown interrupts backpressure without assertion or failure callback");
    destroy(&connection);

    init(&connection);
    denyAllocation = true;
    result = LiSendKeyboardEvent2Ctx(ctx, 0x8043, KEY_ACTION_UP, 0, 0);
    denyAllocation = false;
    check(result == -1 && !atomic_load(&ctx->initialized) &&
          atomic_load(&ctx->inputEdgeFailure) == ML_ERROR_INPUT_STREAM && callbackCount == 0,
          "allocation failure schedules consumer-side termination");
    destroy(&connection);
    return failures ? 1 : 0;
}
'''


def build_source():
    source = (COMMON / "InputStream.c").read_text()
    constants = "\n".join(re.findall(r"^#define (?:MAX_QUEUED_INPUT_PACKETS|INPUT_EDGE_QUEUE_WAIT_MS) .*$", source, re.M))
    packet = source[source.index("typedef struct _PACKET_HOLDER {"):source.index("} PACKET_HOLDER, *PPACKET_HOLDER;") + len("} PACKET_HOLDER, *PPACKET_HOLDER;")]
    names = ["static void freePacketHolder(", "static PPACKET_HOLDER allocatePacketHolder(",
             "static void failInputStreamForLostEdge(", "static bool reportInputEdgeFailureIfPending(",
             "static int queueInputEdge(", "int LiSendMouseButtonEventCtx(", "int LiSendKeyboardEvent2Ctx("]
    consumer = function(source, "static void inputSendThreadProc(")
    if "reportInputEdgeFailureIfPending(ctx)" not in consumer:
        raise SystemExit("input consumer no longer reports edge failures")
    return PREAMBLE + constants + "\n" + packet + "\n" + "\n".join(function(source, name) for name in names) + DRIVER


def main():
    clang, sdk = clang_and_sdk("input edge queue probe")
    source = build_source()
    with tempfile.TemporaryDirectory(prefix="input-edge-queue-") as directory:
        for name, text, expect_success in (
            ("current", source, True),
            ("legacy", source.replace("return queueInputEdge(ctx, holder);",
                "int err = LbqOfferQueueItem(&ctx->packetQueue, holder, &holder->entry); "
                "if (err != LBQ_SUCCESS) freePacketHolder(ctx, holder); return err;"), False),
        ):
            path = Path(directory) / (name + ".c")
            binary = Path(directory) / name
            path.write_text(text)
            subprocess.run([clang, "-isysroot", sdk, "-std=c11", "-DLC_DEBUG", "-I", str(COMMON),
                            "-I", str(COMMON.parent / "enet/include"), str(path),
                            str(COMMON / "LinkedBlockingQueue.c"), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
            if expect_success or result.returncode == 0:
                print(result.stdout, end="")
                print(result.stderr, end="")
            if (result.returncode == 0) != expect_success:
                raise SystemExit(f"{name} returned {result.returncode}, expected success={expect_success}")
        print("ok   legacy drop-on-full behavior is rejected")


if __name__ == "__main__":
    main()
