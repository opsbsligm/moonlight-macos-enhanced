#!/usr/bin/env python3
"""Wave AP criterion gate: how many times does the encrypted control sender allocate.

What this file is about
-----------------------
`docs/history/incidents/common-c-drift-2026-10-26.md` (evaluation 1) judged upstream
`342b106` (control stream encryption built in place) as the one drift commit worth
absorbing: our `sendMessageEnet()` still stages every encrypted control message in a
separate plaintext buffer -- `char tempBuffer[256]` on the stack, a heap `malloc` plus
a whole-block `memcpy` once the message grows past 256 bytes. That heap fallback is
live: the clipboard sync (commit `991396a`) sends `LI_CLIPBOARD_MAX_CHUNK_SIZE`
(16384)-byte chunks down this exact path, so every big chunk costs one heap
allocation and one full copy that an in-place build of the plaintext inside the
destination packet would not.

The goal-mode contract for this wave is deliberately narrow: *criterion first, hot
path later*. A real encrypted control stream is only provable on hardware, so this
gate does not merge a behaviour change -- it makes the allocation behaviour of the
shipping sender a re-runnable, mutation-tested fact. The harness compiles the
*shipping `sendMessageEnet()` text* (extracted from
`moonlight-common/moonlight-common-c/src/ControlStream.c`) against a stubbed ENet and
crypto layer and, for each message size, records:

  * heap allocations on top of the destination buffer itself (2 mallocs: the
    ENetPacket struct and its data region, present in every variant),
  * whether the crypto layer ever saw the plaintext inside the destination packet
    (`inplace=1`) or in a separate buffer (`inplace=0`).

Expected on the shipped tree:

  * encrypted, payload that fits the 256-byte stack buffer: 0 staging mallocs,
    inplace=0;
  * encrypted, clipboard-sized (16384) and one size past the boundary: 1 staging
    malloc and 1 staging copy each, inplace=0;
  * unencrypted, both sizes: 0 staging mallocs.

A refactor of `sendMessageEnet()` that changes any of these numbers fails the gate;
the planted defects in --self-test prove each direction is noticed. When `342b106`
finally lands, this gate is the one to re-anchor: staging mallocs and copies drop to
zero and `inplace` flips to 1 on the encrypted paths.
"""
import os
import subprocess
import sys
import tempfile
from apple_toolchain import clang_and_sdk

# The mutation child compiles the planted source with the plain assertions only;
# without the sentinel it would plant its own defects and the battery would grow by
# one level per level.
NESTED = os.environ.get("CS_ALLOC_GATE_NESTED") == "1"
STRICT_TEST = "--self-test" in sys.argv

ROOT = "."
for a in sys.argv[1:]:
    if a != "--self-test" and os.path.isdir(a):
        ROOT = a

CONTROL_STREAM = "moonlight-common/moonlight-common-c/src/ControlStream.c"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def extract_sender(text):
    """Cut the shipping sendMessageEnet() out of the file by brace matching."""
    start = text.index("static bool sendMessageEnet(")
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


# The destination layout encryptControlMessage() writes:
# [enc header 8B][GCM tag 16B][V2 header 4B][payload]. The in-place variant of
# upstream 342b106 stages the plaintext at tag+V2 inside that region.
HARNESS = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LC_ASSERT(x)
#define Limelog(...)
#define LE16(v) (v)
#define LE32(v) (v)
#define AES_GCM_TAG_LENGTH 16
#define ENET_PACKET_FLAG_RELIABLE 1
#define ENET_PEER_STATE_CONNECTED 1
#define ENET_PEER_PACKET_LOSS_SCALE 100

typedef struct { unsigned short type; unsigned short payloadLength; }
    NVCTL_ENET_PACKET_HEADER_V2, *PNVCTL_ENET_PACKET_HEADER_V2;
typedef struct { unsigned short type; } NVCTL_ENET_PACKET_HEADER_V1, *PNVCTL_ENET_PACKET_HEADER_V1;
typedef struct { unsigned short encryptedHeaderType; unsigned short length;
    unsigned int seq; } NVCTL_ENCRYPTED_PACKET_HEADER, *PNVCTL_ENCRYPTED_PACKET_HEADER;
typedef struct { int AppVersionQuad[4]; } ML_CONNECTION_CONTEXT, *PML_CONNECTION_CONTEXT;

typedef struct _ENetPacket { int magic; void* data; size_t dataLength;
    void* userData; void (*freeCallback)(struct _ENetPacket*); } ENetPacket;
typedef struct { int state; unsigned int channelCount; unsigned int roundTripTime;
    float packetLoss; } ENetPeer;
typedef struct { ENetPeer peer; } ENetHost;
typedef int PLT_MUTEX;
typedef struct {
    PML_CONNECTION_CONTEXT connectionContext;
    void* client;
    ENetPeer* peer;
    PLT_MUTEX enetMutex;
    bool encryptedControlStream;
    uint32_t currentEnetSequenceNumber;
    void* encryptionCtx;
} ML_CONTROL_STREAM_CONTEXT, *PML_CONTROL_STREAM_CONTEXT;

#define IS_SUNSHINE_CTX(ctx) ((ctx)->AppVersionQuad[3] < 0)

static const int ControlStreamAppVersionQuad[4] = {5, 0, 0, 1};
static ML_CONNECTION_CONTEXT g_connection;
static ENetPeer g_peer;
static unsigned char g_streamKey[16];

/* Instrumentation. The wrappers are defined *before* the renames below so their own
   bodies still reach libc; every definition after the renames is counted. */
static int g_mallocCalls;
static long g_mallocBytes;
static int g_memcpyCalls;
static void* g_lastPlaintext;
static ENetPacket* g_lastPacket;
static int g_cryptoCalls;

static void* cs_malloc(size_t size) {
    g_mallocCalls++;
    g_mallocBytes += (long)size;
    return malloc(size);
}
static void cs_free(void* p) { free(p); }
static void* cs_memcpy(void* dst, const void* src, size_t n) {
    g_memcpyCalls++;
    unsigned char* d = (unsigned char*)dst;
    const unsigned char* c = (const unsigned char*)src;
    while (n--) *d++ = *c++;
    return dst;
}
#define malloc cs_malloc
#define free cs_free
#undef memcpy
#define memcpy cs_memcpy

static ENetPacket* enet_packet_create(void* data, size_t dataLength, unsigned int flags) {
    (void)data; (void)flags;
    ENetPacket* p = cs_malloc(sizeof(*p));
    if (!p) return 0;
    p->magic = 0x51;
    p->dataLength = dataLength;
    p->data = cs_malloc(dataLength ? dataLength : 1);
    g_lastPacket = p;
    return p;
}
static void enet_packet_destroy(ENetPacket* packet) {
    if (packet) { cs_free(packet->data); cs_free(packet); }
}
static int enet_peer_send(ENetPeer* peer, unsigned int channelId, ENetPacket* packet) {
    (void)peer; (void)channelId;
    return packet ? 0 : -1;
}
static int enet_host_service(ENetHost* host, void* event, unsigned int timeout) {
    (void)host; (void)event; (void)timeout;
    return -1;
}
static void PltLockMutex(PLT_MUTEX* m) { (void)m; }
static void PltUnlockMutex(PLT_MUTEX* m) { (void)m; }
static void PltSleepMs(int ms) { (void)ms; }
static void enetPacketFreeCb(ENetPacket* packet) { (void)packet; }
static bool isPacketSentWaitingForAck(PML_CONTROL_STREAM_CONTEXT ctx, ENetPacket* packet) {
    (void)ctx; (void)packet;
    return true;
}

/* Crypto stubbed to the exact call shape encryptControlMessage() makes: the caller
   hands over (key, iv, tag-out, plaintext-in, ciphertext-out, size). We remember the
   plaintext pointer so main() can ask whether it sits inside the destination packet. */
static bool stubEncrypt(const unsigned char* in, size_t inLen, unsigned char* out) {
    g_cryptoCalls++;
    g_lastPlaintext = (void*)in;
    for (size_t n = 0; n < inLen; n++) out[n] = in[n];
    return true;
}
__attribute__((weak))
bool encryptControlMessage(PML_CONTROL_STREAM_CONTEXT ctx,
                           PNVCTL_ENCRYPTED_PACKET_HEADER encPacket,
                           PNVCTL_ENET_PACKET_HEADER_V2 packet) {
    (void)ctx;
    size_t inLen = sizeof(*packet) + packet->payloadLength;
    unsigned char* dst = (unsigned char*)(encPacket + 1) + AES_GCM_TAG_LENGTH;
    return stubEncrypt((const unsigned char*)packet, inLen, dst);
}

__SEND__

static void reset_counters(void) {
    g_mallocCalls = 0; g_mallocBytes = 0; g_memcpyCalls = 0;
    g_lastPlaintext = 0; g_cryptoCalls = 0;
}

/* Drive one send through the shipping function and report staging-only numbers:
   the 2 destination mallocs (packet + data) are subtracted, the staging copies are
   the memcpy calls the crypto stub does not perform, and `inplace` asks whether the
   crypto input pointer lies inside the destination data region. */
static void measure_send(ML_CONTROL_STREAM_CONTEXT* ctx, size_t paylen,
                         unsigned char* payload, int* outMallocs, int* outCopies,
                         int* outInplace) {
    reset_counters();
    bool ok = sendMessageEnet(ctx, 0x42, (short)paylen, payload, 0, 0, true);
    if (!ok) { fprintf(stderr, "failed line %d: send returned false\n", __LINE__); exit(1); }
    if (ctx->encryptedControlStream && g_cryptoCalls != 1) {
        fprintf(stderr, "failed line %d: expected 1 crypto call, got %d\n",
                __LINE__, g_cryptoCalls); exit(1);
    }
    if (!ctx->encryptedControlStream && g_cryptoCalls != 0) {
        fprintf(stderr, "failed line %d: unencrypted send called crypto %d times\n",
                __LINE__, g_cryptoCalls); exit(1);
    }
    *outMallocs = g_mallocCalls - 2;
    *outCopies = g_memcpyCalls;
    unsigned char* base = (unsigned char*)g_lastPacket->data;
    unsigned char* pt = (unsigned char*)g_lastPlaintext;
    *outInplace = (ctx->encryptedControlStream && pt != 0 &&
                   pt >= base && pt < base + g_lastPacket->dataLength) ? 1 : 0;
}

int main(void) {
    g_connection.AppVersionQuad[0] = 5;
    g_connection.AppVersionQuad[3] = -1; /* Sunshine */
    ML_CONTROL_STREAM_CONTEXT ctx = {0};
    ctx.connectionContext = &g_connection;
    ctx.client = (void*)2;
    ctx.peer = &g_peer;
    ctx.peer->channelCount = 1;
    ctx.encryptedControlStream = true;
    ctx.currentEnetSequenceNumber = 7;
    ctx.encryptionCtx = (void*)3;

    const size_t small = 100;    /* fits the 256-byte stack buffer      */
    const size_t clip = 16384;   /* LI_CLIPBOARD_MAX_CHUNK_SIZE         */
    const size_t over = 256 + 4; /* first size past the buffer (V2+256) */

    unsigned char* payload = cs_malloc(clip);
    for (size_t i = 0; i < clip; i++) payload[i] = (unsigned char)(i * 31 + 7);

    int smallMallocs, smallCopies, smallInplace;
    int clipMallocs, clipCopies, clipInplace;
    int overMallocs, overCopies, overInplace;
    int plainSmall, plainSmallCopies, plainSmallInplace;
    int plainClip, plainClipCopies, plainClipInplace;

    measure_send(&ctx, small, payload, &smallMallocs, &smallCopies, &smallInplace);
    measure_send(&ctx, clip, payload, &clipMallocs, &clipCopies, &clipInplace);
    measure_send(&ctx, over, payload, &overMallocs, &overCopies, &overInplace);

    ctx.encryptedControlStream = false;
    measure_send(&ctx, small, payload, &plainSmall, &plainSmallCopies, &plainSmallInplace);
    measure_send(&ctx, clip, payload, &plainClip, &plainClipCopies, &plainClipInplace);
    (void)plainSmallCopies; (void)plainClipCopies; (void)plainSmallInplace; (void)plainClipInplace;

    cs_free(payload);

    printf("small_mallocs=%d\n", smallMallocs);
    printf("small_inplace=%d\n", smallInplace);
    printf("clip_mallocs=%d\n", clipMallocs);
    printf("clip_copies=%d\n", clipCopies);
    printf("clip_inplace=%d\n", clipInplace);
    printf("over_mallocs=%d\n", overMallocs);
    printf("over_inplace=%d\n", overInplace);
    printf("plain_small_mallocs=%d\n", plainSmall);
    printf("plain_clip_mallocs=%d\n", plainClip);
    return 0;
}
'''


def build(source, tmp):
    cc, sdk = clang_and_sdk("control stream allocation replay")
    harness = HARNESS.replace("__SEND__", source)
    probe = os.path.join(tmp, "probe.c")
    binary = os.path.join(tmp, "probe")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(harness)
    subprocess.run([cc, "-std=c11", "-Wall", "-Werror", "-Wno-unused-parameter",
                    "-Wno-unused-variable", "-Wno-unused-const-variable",
                    "-isysroot", sdk, probe, "-o", binary], check=True)
    return binary


def run_probe(source):
    with tempfile.TemporaryDirectory() as tmp:
        binary = build(source, tmp)
        return subprocess.run([binary], capture_output=True, text=True)


def counts(r):
    out = {}
    for line in r.stdout.splitlines():
        if "=" in line and line.split("=", 1)[0].isidentifier():
            out[line.split("=", 1)[0]] = int(line.split("=", 1)[1])
    return out


def main():
    text = read(CONTROL_STREAM)
    source = extract_sender(text)

    # Structural anchors: if these drift, the numbers below no longer name the fact
    # we think they name, so fail loudly instead of re-grading quietly.
    check(text.count("static bool sendMessageEnet(") == 1,
          "exactly one sendMessageEnet() in ControlStream.c")
    check("char tempBuffer[256];" in source,
          "shipped stack buffer still present (criterion anchor)")
    check("plaintextBufferAllocated = true;" in source,
          "shipped heap fallback still present (criterion anchor)")
    check("memcpy(&packet[1], payload, paylen);" in source,
          "plaintext staging copy present in the encrypted path")

    r = run_probe(source)
    check(r.returncode == 0,
          "probe compiles and runs" if r.returncode == 0
          else "probe compiles and runs (%s)" % r.stderr[-300:])
    if r.returncode:
        return
    c = counts(r)

    # The shipped fact: the 256-byte stack buffer buys zero staging allocation under
    # its limit; at/over it the sender adds exactly one staging malloc per message
    # (16384-byte clipboard chunks take this path today) and the plaintext never
    # starts life inside the destination packet.
    check(c.get("small_mallocs") == 0,
          "encrypted under-buffer message: no staging malloc (got %s)" % c.get("small_mallocs"))
    check(c.get("small_inplace") == 0,
          "encrypted under-buffer message: plaintext staged separately (got %s)" % c.get("small_inplace"))
    check(c.get("clip_mallocs") == 1,
          "encrypted clipboard chunk: one staging malloc per message (got %s)" % c.get("clip_mallocs"))
    check(c.get("clip_copies") == 1,
          "encrypted clipboard chunk: one staging copy (got %s)" % c.get("clip_copies"))
    check(c.get("clip_inplace") == 0,
          "encrypted clipboard chunk: plaintext staged separately (got %s)" % c.get("clip_inplace"))
    check(c.get("over_mallocs") == 1,
          "encrypted message past the buffer: one staging malloc (got %s)" % c.get("over_mallocs"))
    check(c.get("over_inplace") == 0,
          "encrypted message past the buffer: plaintext staged separately (got %s)" % c.get("over_inplace"))
    check(c.get("plain_small_mallocs") == 0,
          "unencrypted small: no staging malloc (got %s)" % c.get("plain_small_mallocs"))
    check(c.get("plain_clip_mallocs") == 0,
          "unencrypted clipboard chunk: no staging malloc (got %s)" % c.get("plain_clip_mallocs"))

    print("criterion recorded: shipped encrypted sender = 0 staging mallocs under the "
          "256B buffer, 1 malloc + 1 copy per message at/over it (clipboard chunks 16384B)")


def run_self_test():
    """Each planted defect must flip the probe's verdict."""
    original = read(CONTROL_STREAM)
    # The verdict is (returncode, counts): a planted defect that still compiles
    # and runs cleanly but moves the staging numbers must be caught the same way,
    # so compare the full verdict against the shipped baseline, not exit status.
    baseline_source = extract_sender(original)
    base = run_probe(baseline_source)
    check(base.returncode == 0, "self-test baseline probe runs")
    if base.returncode:
        return
    baseline = counts(base)
    cases = [
        # 1. grow the stack buffer past the clipboard chunk: clip drops to 0 mallocs.
        ("char tempBuffer[256];", "char tempBuffer[65536];",
         "stack buffer grown past the clipboard chunk size"),
        # 2. shrink it below the small probe size: small now mallocs.
        ("char tempBuffer[256];", "char tempBuffer[1];",
         "stack buffer shrunk below the small probe size"),
        # 3. kill the fast path: every size takes the heap branch.
        ("if (plaintextLength <= sizeof(tempBuffer)) {", "if (false) {",
         "stack buffer fast path removed"),
        # 4. the unencrypted path starts staging: plain numbers rise.
        ("packet = (PNVCTL_ENET_PACKET_HEADER_V1)enetPacket->data;",
         "packet = (PNVCTL_ENET_PACKET_HEADER_V1)malloc(sizeof(*packet));",
         "unencrypted path now heap-allocates the header"),
        # 5. a planted in-place rewrite must flip `inplace` and drop the staging copy:
        #    this is the shape 342b106 will take, and the gate must notice it.
        ("plaintextBuffer = tempBuffer;", "plaintextBuffer = (char*)enetPacket->data + 24;",
         "planted in-place rewrite (upstream 342b106 shape)"),
    ]
    for needle, replacement, label in cases:
        if original.count(needle) != 1:
            check(False, "self-test needle unique: %s" % label)
            continue
        mutated = original[:original.index(needle)] + replacement + \
            original[original.index(needle) + len(needle):]
        source = extract_sender(mutated)
        # Guard the extraction itself: if the mutation never reached the code the
        # probe compiles, the verdict comparison below would be vacuous.
        if source == baseline_source:
            check(False, "self-test mutation applied: %s" % label)
            continue
        r = run_probe(source)
        caught = (r.returncode != 0) or (counts(r) != baseline)
        check(caught, "self-test caught: %s" % label)


if STRICT_TEST and not NESTED:
    print("== self-test ==")
    run_self_test()
    print("")

main()
sys.exit(1 if failures else 0)
