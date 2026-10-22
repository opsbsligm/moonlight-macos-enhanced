#!/usr/bin/env python3
"""Record and replay the single-controller wire bytes, byte for byte.

The tuple-level baseline (controller-event-baseline.py) proves what the Mac
client hands to the C layer. This gate proves what the C layer writes onto
the wire: it compiles the real sendControllerEventInternal and
LiSendControllerArrivalEventCtx from moonlight-common-c, feeds a fixed
scenario table through them, drains the real packet queue in order, and
compares every emitted byte -- payload, channel, order -- against an
independent Python reference of the wire format.

The scenarios are the recorded baseline for one connected controller:
Sunshine gen4/5, GFE gen3/4/5, extended button overflow (buttonFlags2),
sign-extended flag clients, controller-number wrapping, the legacy gen3
packet, and the arrival sequence (arrival packet plus the fallback neutral
state; on GFE the neutral state alone). A mutation of the shipping
source must change at least one byte or one channel, or the reference
catches the drift.

Usage: controller-wire-baseline.py [root] | --self-test [root]
Exit 0 when every scenario replays byte-for-byte and every planted
mutation is caught.
"""
import os
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.abspath(".")
args = [a for a in sys.argv[1:] if a != "--self-test"]
SELF_TEST = "--self-test" in sys.argv
if args:
    ROOT = os.path.abspath(args[0])

COMMON = os.path.join(ROOT, "moonlight-common", "moonlight-common-c", "src")
INPUT_STREAM = os.path.join(COMMON, "InputStream.c")

MC_CHANNEL_BASE = 0x10
# Recorded wire constants, copied from Input.h so the Python reference
# cannot drift from the C header in the same tree without a test failing.
MC_MAGIC_GEN5, MC_MAGIC = 0x0000000C, 0x0000000D
MC_HEADER_B, MC_MID_B, MC_TAIL_A, MC_TAIL_B = 0x001A, 0x0014, 0x009C, 0x0055
LEGACY_MAGIC, LEGACY_HEADER_B = 0x0000000A, 0x1400
LEGACY_TAIL_A, LEGACY_TAIL_B = 0x0000009C, 0x0055
ARRIVAL_MAGIC = 0x55000004
MISC_FLAG = 0x200000
SPECIAL_FLAG = 0x0400
MAX_GAMEPADS = 16

failures = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# (name, sunshine, gen, op, pi, mask, buttons, lt, rt, lx, ly, rx, ry,
#       type, caps, supported_buttons)
# op 0 = multi controller event, 1 = arrival (fallback neutral included).
SCENARIOS = [
    ("sunshine neutral state", True, 4, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("sunshine guide button", True, 4, 0, 0, 1, SPECIAL_FLAG, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("sunshine full word", True, 4, 0, 1, 0b11, 0xFFFF, 255, 255, 32767, -32768, 32767, -32768, 0, 0, 0),
    ("sunshine extended buttons overflow", True, 4, 0, 0, 1, 0x03FFFF, 255, 255, 0, 0, 0, 0, 0, 0, 0),
    ("sign extended client flags", True, 4, 0, 0, 1, int(0x8000 | 0x80000000), 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("sunshine keeps sixteen slots", True, 4, 0, 15, 1, 0x0002, 10, 20, 100, -100, 0, 0, 0, 0, 0),
    ("sunshine wraps past sixteen", True, 4, 0, 16, 0b101, 0x0002, 10, 20, 100, -100, 0, 0, 0, 0, 0),
    ("sunshine gen5 magic", True, 5, 0, 0, 1, 0x0010, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("gfe gen4 four slots", False, 4, 0, 5, 0xF5, 0x0002, 10, 20, 100, -100, 0, 0, 0, 0, 0),
    ("gfe gen4 drops extended bits", False, 4, 0, 0, 1, 0x100000, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("gfe maps misc to guide", False, 4, 0, 0, 1, MISC_FLAG | 0x1000, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("gfe gen5 magic", False, 5, 0, 0, 1, 0x0010, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ("gfe gen3 legacy packet", False, 3, 0, 0, 1, 0xFFFF, 255, 255, 32767, -32768, 0, 0, 0, 0, 0),
    ("sunshine arrival ps", True, 4, 1, 1, 0b10, 0, 0, 0, 0, 0, 0, 0, 2, 3, 0xFFFF),
    ("gfe arrival falls back to neutral", False, 4, 1, 2, 0b100, 0, 0, 0, 0, 0, 0, 0, 1, 3, 0xFFFF),
]


def mc_packet(pi, mask, buttons, lt, rt, lx, ly, rx, ry, sunshine, gen5):
    # NV_MULTI_CONTROLLER_PACKET, packed(1); the size field is big-endian.
    return (struct.pack(">I", 30) + struct.pack(
        "<IHHHHHBBhhhhHHH",
        MC_MAGIC_GEN5 if gen5 else MC_MAGIC, MC_HEADER_B, pi, mask,
        MC_MID_B, buttons & 0xFFFF, lt, rt, lx, ly, rx, ry, MC_TAIL_A,
        (buttons >> 16) & 0xFFFF if sunshine else 0, MC_TAIL_B))


def legacy_packet(buttons, lt, rt, lx, ly, rx, ry):
    # NV_CONTROLLER_PACKET, packed(1); size big-endian, tailA 32-bit LE.
    return (struct.pack(">I", 24) + struct.pack(
        "<IHHBBhhhhIH",
        LEGACY_MAGIC, LEGACY_HEADER_B, buttons & 0xFFFF, lt, rt,
        lx, ly, rx, ry, LEGACY_TAIL_A, LEGACY_TAIL_B))


def arrival_packet(pi, type_, caps, supported):
    return (struct.pack(">I", 12) + struct.pack(
        "<IBBHI", ARRIVAL_MAGIC, pi, type_, caps, supported))


def expected_packets(scenario):
    """The recorded byte sequence one connected controller must produce."""
    (_name, sunshine, gen, op, pi, mask, buttons, lt, rt, lx, ly, rx, ry,
     type_, caps, supported) = scenario
    out = []
    # The C sender takes a signed 32-bit int; a 32-bit literal must read as
    # the same value here, or the sign-extension guard fires on the wrong side.
    if buttons > 0x7FFFFFFF:
        buttons -= 0x100000000
    if buttons < 0:
        buttons &= 0xFFFF
    if not sunshine:
        pi = pi % 4
        mask = mask & 0xF
        if buttons & MISC_FLAG:
            buttons |= SPECIAL_FLAG
    if op == 1:
        # The arrival event is a Sunshine-only packet; GFE still receives the
        # fallback neutral state, which always goes through the MC sender.
        if sunshine:
            out.append((MC_CHANNEL_BASE + pi,
                        arrival_packet(pi % MAX_GAMEPADS, type_, caps, supported)))
        pi = pi % MAX_GAMEPADS if sunshine else pi
        out.append((MC_CHANNEL_BASE + pi,
                    mc_packet(pi, mask, 0, 0, 0, 0, 0, 0, 0, sunshine, gen >= 5)))
        return out
    pi = pi % MAX_GAMEPADS if sunshine else pi
    if not sunshine and gen == 3:
        out.append((MC_CHANNEL_BASE + pi, legacy_packet(buttons, lt, rt, lx, ly, rx, ry)))
    else:
        out.append((MC_CHANNEL_BASE + pi,
                    mc_packet(pi, mask, buttons, lt, rt, lx, ly, rx, ry,
                              sunshine, gen >= 5)))
    return out


PREAMBLE = r'''
#include "Limelight-internal.h"
#include <assert.h>
#include <pthread.h>
#undef ListenerCallbacks
#undef StreamConfig
#undef Limelog
#define AppVersionQuad (ctx->connectionContext->AppVersionQuad)
#define Limelog(s, ...) do {} while (0)
#define PAYLOAD_SIZE(x) BE32((x)->packet.header.size)
#define PACKET_SIZE(x) (PAYLOAD_SIZE(x) + sizeof(uint32_t))
static void check(bool value, const char *name) {
    printf("%s %s\n", value ? "ok  " : "FAIL", name);
    if (!value) exit(1);
}
static void terminated(int error) { (void)error; }
int PltCreateMutex(PLT_MUTEX *m) { return pthread_mutex_init(m, NULL); }
void PltDeleteMutex(PLT_MUTEX *m) { pthread_mutex_destroy(m); }
void PltLockMutex(PLT_MUTEX *m) { pthread_mutex_lock(m); }
void PltUnlockMutex(PLT_MUTEX *m) { pthread_mutex_unlock(m); }
int PltCreateConditionVariable(PLT_COND *c, PLT_MUTEX *m) { (void)c; (void)m; return 0; }
void PltDeleteConditionVariable(PLT_COND *c) { (void)c; }
void PltSignalConditionVariable(PLT_COND *c) { (void)c; }
void PltWaitForConditionVariable(PLT_COND *c, PLT_MUTEX *m) { pthread_cond_wait(c, m); }
uint64_t PltGetMillis(void) { return 0; }
void PltSleepMs(int ms) { (void)ms; }
'''

DRIVER = r'''
#undef AppVersionQuad
#undef ListenerCallbacks
typedef struct {
    const char *name;
    int sunshine;
    int gen;
    int op;
    int pi;
    int mask;
    int buttons;
    int lt, rt;
    int lx, ly, rx, ry;
    int type, caps, supported;
} Scenario;

static void init(ML_CONNECTION_CONTEXT *connection, int sunshine, int gen) {
    memset(connection, 0, sizeof(*connection));
    connection->AppVersionQuad[0] = gen;
    connection->AppVersionQuad[3] = sunshine ? -1 : 0;
    connection->ListenerCallbacks.connectionTerminated = terminated;
    ML_INPUT_STREAM_CONTEXT *ctx = &connection->inputContext;
    ctx->connectionContext = connection;
    atomic_init(&ctx->initialized, true);
    LbqInitializeLinkedBlockingQueue(&ctx->packetQueue, MAX_QUEUED_INPUT_PACKETS);
    LbqInitializeLinkedBlockingQueue(&ctx->packetHolderFreeList, MAX_QUEUED_INPUT_PACKETS);
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

static int drained = 0;
static void drain(ML_INPUT_STREAM_CONTEXT *ctx) {
    PPACKET_HOLDER holder;
    while (LbqPollQueueElement(&ctx->packetQueue, (void **)&holder) == LBQ_SUCCESS) {
        int len = PACKET_SIZE(holder);
        const unsigned char *bytes = (const unsigned char *)&holder->packet;
        printf("PKT ch=0x%02X len=%d", holder->channelId, len);
        for (int i = 0; i < len; i++) printf(" %02X", bytes[i]);
        printf("\n");
        drained++;
        freePacketHolder(ctx, holder);
    }
}

int main(void) {
    Scenario scenarios[] = { __SCENARIOS__ };
    int n = (int)(sizeof(scenarios) / sizeof(scenarios[0]));
    int failed = 0;
    for (int i = 0; i < n; i++) {
        ML_CONNECTION_CONTEXT connection;
        init(&connection, scenarios[i].sunshine, scenarios[i].gen);
        ML_INPUT_STREAM_CONTEXT *ctx = &connection.inputContext;
        drained = 0;
        printf("SCN %d %s\n", i, scenarios[i].name);
        int rc;
        if (scenarios[i].op == 0) {
            rc = LiSendMultiControllerEventCtx(ctx, scenarios[i].pi, scenarios[i].mask,
                scenarios[i].buttons, (unsigned char)scenarios[i].lt,
                (unsigned char)scenarios[i].rt, (short)scenarios[i].lx,
                (short)scenarios[i].ly, (short)scenarios[i].rx, (short)scenarios[i].ry);
        } else {
            rc = LiSendControllerArrivalEventCtx(ctx, (uint8_t)scenarios[i].pi,
                (uint16_t)scenarios[i].mask, (uint8_t)scenarios[i].type,
                (uint32_t)scenarios[i].supported, (uint16_t)scenarios[i].caps);
        }
        printf("RC %d\n", rc);
        drain(ctx);
        destroy(&connection);
        failed += (rc != LBQ_SUCCESS);
    }
    printf("RUN %s (%d scenarios, %d packets)\n", failed ? "FAILED" : "PASSED", n, drained);
    return failed ? 1 : 0;
}
'''


def scenario_literals():
    return ",\n".join(
        '{ "%s", %d, %d, %d, %d, %d, (int)%d, %d, %d, %d, %d, %d, %d, %d, %d, %d }' % s
        for s in SCENARIOS)


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


def build_source(source):
    """The real sender functions plus the packet holder, nothing else.

    Compiling the whole InputStream.c would drag in the control-stream and
    thread machinery a byte baseline cannot reach; the extraction keeps the
    bytes under test exactly what ships, and a renamed function fails the
    build instead of passing in silence.
    """
    constants = "\n".join(re.findall(
        r"^#define (?:MAX_QUEUED_INPUT_PACKETS|MAX_GAMEPADS) .*$", source, re.M))
    holder = source[source.index("typedef struct _PACKET_HOLDER {"):
                    source.index("} PACKET_HOLDER, *PPACKET_HOLDER;") + len("} PACKET_HOLDER, *PPACKET_HOLDER;")]
    names = ["static void freePacketHolder(", "static PPACKET_HOLDER allocatePacketHolder(",
             "static int sendControllerEventInternal(", "int LiSendMultiControllerEventCtx(",
             "int LiSendControllerArrivalEventCtx("]
    return (PREAMBLE + constants + "\n" + holder + "\n" +
            "\n".join(function(source, name) for name in names) +
            DRIVER.replace("__SCENARIOS__", scenario_literals()))


def compile_and_run(source, work, cc, sdk):
    with open(os.path.join(work, "probe.c"), "w", encoding="utf-8") as handle:
        handle.write(build_source(source))
    binary = os.path.join(work, "wire-baseline")
    built = subprocess.run(
        [cc, "-isysroot", sdk, "-std=c11", "-DLC_DEBUG",
         "-I", COMMON, "-I", os.path.join(COMMON, "..", "enet", "include"),
         os.path.join(work, "probe.c"),
         os.path.join(COMMON, "LinkedBlockingQueue.c"),
         "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-2000:]
    ran = subprocess.run([binary], capture_output=True, text=True, timeout=30)
    return ran.returncode, ran.stdout + ran.stderr


def replay(actual):
    """Compare the driver manifest against the recorded reference, in order."""
    problems = []
    lines = actual.strip().splitlines()
    idx = 0
    for scenario in SCENARIOS:
        if idx >= len(lines) or not lines[idx].startswith("SCN "):
            problems.append("%s: manifest lost the scenario header" % scenario[0])
            break
        idx += 1
        rc_line = lines[idx] if idx < len(lines) else ""
        idx += 1
        got_rc = int(rc_line.split()[1]) if rc_line.startswith("RC ") else -99
        if got_rc != 0:
            problems.append("%s: enqueue returned %d" % (scenario[0], got_rc))
        expect = expected_packets(scenario)
        for slot, (channel, payload) in enumerate(expect):
            if idx >= len(lines) or not lines[idx].startswith("PKT "):
                problems.append("%s: packet %d missing" % (scenario[0], slot))
                break
            line = lines[idx]
            idx += 1
            parts = line.split()
            ch = int(parts[1].split("=")[1], 16)
            length = int(parts[2].split("=")[1])
            got = bytes(int(tok, 16) for tok in parts[3:])
            want = payload
            if ch != channel:
                problems.append("%s: packet %d channel 0x%02X, recorded 0x%02X"
                                % (scenario[0], slot, ch, channel))
            if length != len(want) or got != want:
                problems.append("%s: packet %d bytes %s, recorded %s"
                                % (scenario[0], slot, got.hex(), want.hex()))
    trailing = lines[idx:]
    # The run summary line is the only non-packet line allowed at the end.
    if any(not line.startswith(("RUN ", "FAIL ")) for line in trailing) or \
            len(trailing) > 1:
        problems.append("manifest carried unexpected trailing line(s): %r"
                        % trailing)
    return problems


def mutations_in_source():
    """Label, old, new triples planted into the shipping InputStream.c."""
    return [
        ("gen5 magic drifts from the recorded constant",
         "if (AppVersionQuad[0] >= 5) {\n      holder->packet.multiController.header.magic =\n          LE32(MULTI_CONTROLLER_MAGIC_GEN5);",
         "if (AppVersionQuad[0] >= 5) {\n      holder->packet.multiController.header.magic =\n          LE32(MULTI_CONTROLLER_MAGIC);"),
        ("Sunshine extended bits stop reaching buttonFlags2",
         "IS_SUNSHINE() ? LE16((short)(buttonFlags >> 16)) : 0;",
         "IS_SUNSHINE() ? 0 : LE16((short)(buttonFlags >> 16));"),
        ("Sunshine slot wrap is deleted",
         "controllerNumber %= MAX_GAMEPADS;\n  }\n\n  holder = allocatePacketHolder(ctx, 0);\n  if (holder == NULL) {\n    return -1;\n  }\n\n  // Send each controller on a separate channel\n  holder->channelId = CTRL_CHANNEL_GAMEPAD_BASE + controllerNumber;",
         "controllerNumber = controllerNumber;\n  }\n\n  holder = allocatePacketHolder(ctx, 0);\n  if (holder == NULL) {\n    return -1;\n  }\n\n  // Send each controller on a separate channel\n  holder->channelId = CTRL_CHANNEL_GAMEPAD_BASE + controllerNumber;"),
        ("GFE loses the misc-to-guide mapping",
         "if (buttonFlags & MISC_FLAG) {\n      buttonFlags |= SPECIAL_FLAG;\n    }",
         "if (buttonFlags & 0x01) {\n      buttonFlags |= SPECIAL_FLAG;\n    }"),
        ("gen3 legacy header byte drifts",
         "holder->packet.controller.headerB = LE16(C_HEADER_B);",
         "holder->packet.controller.headerB = LE16(C_HEADER_B ^ 0xFFFF);"),
        ("arrival capabilities drift",
         "holder->packet.controllerArrival.capabilities = LE16(capabilities);",
         "holder->packet.controllerArrival.capabilities = LE16(capabilities ^ 0xFFFF);"),
        ("GFE mask mask drifts",
         "activeGamepadMask &= 0xF;",
         "activeGamepadMask &= 0x1;"),
        ("multi controller tail A drifts",
         "holder->packet.multiController.tailA = LE16(MC_TAIL_A);",
         "holder->packet.multiController.tailA = LE16(MC_TAIL_B);"),
    ]


def run(root):
    global COMMON, INPUT_STREAM
    COMMON = os.path.join(root, "moonlight-common", "moonlight-common-c", "src")
    INPUT_STREAM = os.path.join(COMMON, "InputStream.c")
    cc, sdk = apple_toolchain.clang_and_sdk("the controller wire baseline harness")
    with open(INPUT_STREAM, encoding="utf-8") as handle:
        shipping = handle.read()
    with tempfile.TemporaryDirectory() as work:
        code, log = compile_and_run(shipping, work, cc, sdk)
        if code is None:
            check(False, "the wire baseline compiles: " + log)
            return
        check(code == 0 and "RUN PASSED" in log,
              "the shipping wire path replays the recorded byte baseline")
        problems = [] if code == 0 and "RUN PASSED" in log else ["run did not pass"]
        if code == 0 and "RUN PASSED" in log:
            problems = replay(log)
        for problem in problems:
            check(False, problem)
        if not problems:
            print("ok   every scenario packet matches the recorded bytes in order")
        check("RUN PASSED (%d scenarios" % len(SCENARIOS) in log or
              ("RUN PASSED" in log and str(len(SCENARIOS)) in log),
              "the harness ran its whole scenario table (%d scenarios)" % len(SCENARIOS))
    if SELF_TEST:
        for label, old, new in mutations_in_source():
            if shipping.count(old) != 1:
                check(False, "the self-test mutation '%s' must match exactly once" % label)
                continue
            with tempfile.TemporaryDirectory() as work:
                code, log = compile_and_run(shipping.replace(old, new, 1), work, cc, sdk)
                caught = code == 1 and "RUN FAILED" in log or (
                    code == 0 and "RUN PASSED" in log and bool(replay(log)))
                check(caught, "the bytes fail when %s" % label
                      if caught else "NOT CAUGHT (%s)" % label)


def main():
    run(ROOT)
    if failures:
        print("controller-wire-baseline: %d failures" % len(failures))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("controller-wire-baseline: all checks passed"
          + (" (self-test included)" if SELF_TEST else ""))


if __name__ == "__main__":
    main()
