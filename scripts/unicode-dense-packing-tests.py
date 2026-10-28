#!/usr/bin/env python3
"""Wave G-1 gate: UTF-8 text packs densely on Sunshine and one code point per
packet on GFE, and the size field keeps describing the bytes that were copied.

What this file is about
-----------------------
`moonlight-common-c` used to send every UTF-8 code point in its own
`NV_UNICODE_PACKET` and, before the first packet of a text block, flush the
control stream, wait for it to drain and then sleep a further 50 ms. Both
choices are about GeForce Experience: GFE reads one code point per packet, and
GFE does not order keyboard events and UTF-8 events against each other.
Sunshine does neither of those things, so on Sunshine the old path paid one
packet per Chinese character and 50 ms per text block for a race that does not
exist there. Upstream commit 0405384 fixed that; this repository's fork carries
the ctx-shaped send path, so the port had to be rewritten rather than cherry-
picked -- which is exactly the kind of rewrite that silently loses a branch.

The gate compiles the shipping source: it extracts the three helpers
(`getUtf8CodePointLength`, `unicodeNeedsControlStreamFlush`,
`unicodeChunkLength`) and the real body of the UTF-8 branch of the sender loop
out of `moonlight-common/moonlight-common-c/src/InputStream.c`, wraps them in a
harness whose `sendInputPacket` records instead of sending, and replays the
emitted packet manifest -- channel, size field, payload bytes, moreData flag --
against an independent Python model of the wire format, scenario by scenario.
A planted defect has to change the manifest, not merely the compiler's mood; the
`--self-test` pass says which kind of catch each defect produced.

Usage: unicode-dense-packing-tests.py [root] | --self-test [root]
Exit 0 when every scenario replays and every planted defect is caught.
"""
import os
import re
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
KEYBOARD_CHANNEL = 0x02
failures = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def max_count():
    """UTF8_TEXT_EVENT_MAX_COUNT, read from the header it ships in.

    The Python reference has to keep its own copy of the packing rule, so the one
    number that rule turns on comes out of Input.h rather than being retyped: a
    header change then moves the model with it, instead of leaving a gate that
    proves an out-of-date packet budget.
    """
    text = read(os.path.join(COMMON, "Input.h"))
    found = re.search(r"^#define\s+UTF8_TEXT_EVENT_MAX_COUNT\s+(\d+)", text, re.M)
    if not found:
        raise AssertionError("UTF8_TEXT_EVENT_MAX_COUNT is no longer in Input.h")
    return int(found.group(1))


def code_point_length(first_byte):
    if first_byte < 0x80:
        return 1
    if first_byte < 0xC0:
        return 0  # a continuation byte cannot start a code point
    if first_byte < 0xE0:
        return 2
    if first_byte < 0xF0:
        return 3
    if first_byte < 0xF8:
        return 4
    return 0


# (name, text) pairs. A str is UTF-8 encoded, a bytes entry is handed over
# verbatim, so the scenario table cannot drift from what the C side is sent and
# can still describe a block that ends in the middle of a code point.
SCENARIO_TEXTS = [
    ("ascii short", "hello"),
    ("chinese four characters", "你好世界"),
    ("ascii fills a packet", "a" * 32),
    ("ascii just past a packet", "b" * 33),
    ("two byte code points", "é" * 20),
    ("four byte code points", "😀" * 9),
    ("mixed scripts", "Moonlight月光串流😀abc"),
    ("long chinese block", "月光串流客户端" * 4),
    # A caller that cut its buffer at a byte limit hands over a trailing fragment.
    # The dense packer has to clamp that last chunk to the bytes that are really
    # left; claiming a whole code point would put bytes on the wire that the
    # client never had.
    ("truncated three byte tail", "你好".encode("utf-8") + b"\xe4"),
    ("truncated four byte tail", ("月光😀abc").encode("utf-8") + b"\xf0\x9f\x98"),
    # A stray continuation byte stops the block, it does not skip ahead.
    ("stray continuation byte tail", b"hi\x80"),
]


def expected_manifest(text_bytes, sunshine, limit):
    """The packets the host should see for one text block: (payload, moreData).

    moreData follows the shipping rule, `cursor + chunk < total`, not "a further
    packet follows". The two differ only when a block stops on an invalid byte:
    the sender still claims more data, so the last packet of that block waits in
    the ENet queue for the next event to flush it. That is upstream's long-standing
    behaviour and this client cannot produce it -- both UTF-8 producers hand over
    complete, valid text -- so the gate records it rather than quietly rewriting it.
    """
    packets = []
    more_flags = []
    i = 0
    total = len(text_bytes)
    while i < total:
        remaining = total - i
        length = code_point_length(text_bytes[i])
        if length == 0:
            break
        if sunshine:
            chunk = 0
            while chunk < remaining:
                nxt = code_point_length(text_bytes[i + chunk])
                if nxt == 0:
                    break
                if chunk + nxt > limit:
                    break
                chunk += nxt
            if chunk == 0:
                break
        else:
            chunk = length
        # The sender clamps to what is left, so a truncated final code point
        # still goes out rather than being dropped.
        chunk = min(chunk, remaining)
        packets.append(text_bytes[i:i + chunk])
        more_flags.append("1" if i + chunk < total else "0")
        i += chunk
    return packets, more_flags


PREAMBLE = r'''
#include "Limelight-internal.h"
#include <stdlib.h>
#include <string.h>
#undef ListenerCallbacks
#undef StreamConfig
#undef Limelog
#define AppVersionQuad (ctx->connectionContext->AppVersionQuad)
#define Limelog(s, ...) do {} while (0)
#define PAYLOAD_SIZE(x) BE32((x)->packet.header.size)
/* The Pluto calls the loop leans on are declarations in Plt.h; the harness is not
 * linked against Pluto, so they answer the loop directly instead of needing stubs
 * whose signatures could drift from the header. */
#define PltIsThreadInterrupted(t) (false)
#define PltSleepMs(ms) record_sleep(ms)
static int flushes;
static int sleeps;
static int frees;
static int transit_checks;
static void record_sleep(int ms) { (void)ms; sleeps++; }
void flushInputOnControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx) { (void)ctx; flushes++; }
bool isControlDataInTransitCtx(PML_CONTROL_STREAM_CONTEXT ctx) {
    (void)ctx;
    return transit_checks++ == 0;
}
'''

SENDER_STUBS = r'''
/* The two functions the extracted body calls on its way out. Recording the packet
 * is the point of the harness: everything the model checks comes from here, so a
 * change to the shipping block shows up as a changed manifest line. */
static bool sendInputPacket(PML_INPUT_STREAM_CONTEXT ctx, PPACKET_HOLDER holder,
                            bool moreData) {
    (void)ctx;
    uint32_t size = BE32(holder->packet.header.size);
    uint32_t textLength = size - sizeof(uint32_t);
    if (textLength > UTF8_TEXT_EVENT_MAX_COUNT) {
        /* A size field that describes more than the payload can hold is itself the
         * defect; report it as such instead of reading past the union. */
        textLength = UTF8_TEXT_EVENT_MAX_COUNT;
    }
    printf("PKT ch=0x%02X size=%u more=%d text=", holder->channelId, size,
           moreData ? 1 : 0);
    for (uint32_t i = 0; i < textLength; i++) {
        printf("%02X", (unsigned char)holder->packet.unicode.text[i]);
    }
    printf("\n");
    return true;
}

static void freePacketHolder(PML_INPUT_STREAM_CONTEXT ctx, PPACKET_HOLDER holder) {
    (void)ctx;
    (void)holder;
    frees++;
}
'''

WRAPPER = r'''
/* The extracted block is the body of the sender loop's UTF-8 branch, verbatim.
 * Its trailing `continue` belongs to that loop, so inside this wrapper the word
 * means `break`; nothing in the block itself is edited to get here. */
#define continue break
static void run_utf8_block(PML_INPUT_STREAM_CONTEXT ctx, PPACKET_HOLDER holder) {
    for (int guard = 1; guard; guard = 0) {
__BLOCK__
    }
}
#undef continue
'''

DRIVER = r'''
#undef AppVersionQuad
typedef struct {
    const char *name;
    const char *text;
    int sunshine;
} Scenario;

int main(void) {
    Scenario scenarios[] = {__SCENARIOS__};
    int n = (int)(sizeof(scenarios) / sizeof(scenarios[0]));
    for (int i = 0; i < n; i++) {
        ML_CONNECTION_CONTEXT *connection = calloc(1, sizeof(*connection));
        connection->AppVersionQuad[0] = 4;
        connection->AppVersionQuad[3] = scenarios[i].sunshine ? -1 : 0;
        PML_INPUT_STREAM_CONTEXT ctx = &connection->inputContext;
        ctx->connectionContext = connection;
        PPACKET_HOLDER holder = calloc(1, sizeof(*holder) + 64);
        int length = (int)strlen(scenarios[i].text);
        holder->channelId = CTRL_CHANNEL_KEYBOARD;
        holder->packet.unicode.header.size = BE32(sizeof(uint32_t) + length);
        holder->packet.unicode.header.magic = LE32(UTF8_TEXT_EVENT_MAGIC);
        memcpy(holder->packet.unicode.text, scenarios[i].text, length);
        flushes = sleeps = frees = transit_checks = 0;
        printf("SCN %d %s sunshine=%d bytes=%d\n", i, scenarios[i].name,
               scenarios[i].sunshine, length);
        run_utf8_block(ctx, holder);
        printf("SUM flushes=%d sleeps=%d frees=%d\n", flushes, sleeps, frees);
        free(holder);
        free(connection);
    }
    printf("RUN PASSED (%d scenarios)\n", n);
    return 0;
}
'''


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


def block_body(source, anchor):
    """The inside of the sender loop's UTF-8 branch, without its `else if` test."""
    start = source.index(anchor)
    brace = source.index("{", start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[brace + 1:end]
    raise AssertionError(anchor)


ANCHOR = "else if (holder->packet.header.magic == LE32(UTF8_TEXT_EVENT_MAGIC)) {"


def raw_text(text):
    """The exact bytes the C driver receives for one scenario.

    The driver measures the text with strlen(), so a NUL byte would quietly shorten
    it and the C side and the Python model would then describe different inputs --
    the one thing the scenario table may not do.
    """
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    if b"\x00" in raw:
        raise AssertionError("a scenario text may not contain a NUL byte")
    return raw


def scenario_literals():
    out = []
    for name, text in SCENARIO_TEXTS:
        for sunshine in (1, 0):
            out.append('{ "%s", "%s", %d }' % (name, c_escape(raw_text(text)),
                                               sunshine))
    return ",\n".join(out)


def c_escape(raw):
    """A C string literal body that holds exactly these bytes."""
    out = ""
    for byte in raw:
        if 0x20 <= byte < 0x7F and byte != ord('"') and byte != ord("\\"):
            out += chr(byte)
        else:
            out += "\\%03o" % byte
    return out


def scenario_table():
    """(name, sunshine, text bytes) in the same order the driver walks."""
    rows = []
    for name, text in SCENARIO_TEXTS:
        raw = raw_text(text)
        for sunshine in (True, False):
            rows.append(("%s %s" % (name, "sunshine" if sunshine else "gfe"),
                         sunshine, raw))
    return rows


def build_source(source):
    constants = "\n".join(re.findall(r"^#define (?:MAX_QUEUED_INPUT_PACKETS|MAX_GAMEPADS) .*$",
                                     source, re.M))
    start = source.index("typedef struct _PACKET_HOLDER {")
    end_marker = "} PACKET_HOLDER, *PPACKET_HOLDER;"
    holder = source[start:source.index(end_marker) + len(end_marker)]
    helpers = "\n".join([
        function(source, "static uint32_t getUtf8CodePointLength("),
        function(source, "static bool unicodeNeedsControlStreamFlush("),
        function(source, "static uint32_t unicodeChunkLength("),
    ])
    wrapper = WRAPPER.replace("__BLOCK__", block_body(source, ANCHOR))
    return (PREAMBLE + constants + "\n" + holder + "\n" + helpers + "\n" +
            SENDER_STUBS + wrapper +
            DRIVER.replace("__SCENARIOS__", scenario_literals()))


def compile_and_run(source, work, cc, sdk):
    with open(os.path.join(work, "probe.c"), "w", encoding="utf-8") as handle:
        handle.write(build_source(source))
    binary = os.path.join(work, "unicode-packing")
    built = subprocess.run(
        [cc, "-isysroot", sdk, "-std=c11", "-DLC_DEBUG",
         "-I", COMMON, "-I", os.path.join(COMMON, "..", "enet", "include"),
         os.path.join(work, "probe.c"), "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-2500:]
    ran = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    return ran.returncode, ran.stdout + ran.stderr


def replay(actual, limit):
    """Match the emitted manifest against the Python model, scenario by scenario."""
    problems = []
    lines = actual.strip().splitlines()
    rows = scenario_table()
    idx = 0
    for name, sunshine, raw in rows:
        if idx >= len(lines) or not lines[idx].startswith("SCN "):
            problems.append("%s: the manifest lost the scenario header" % name)
            break
        idx += 1
        want_packets, want_more = expected_manifest(raw, sunshine, limit)
        got_packets = []
        got_more = []
        while idx < len(lines) and lines[idx].startswith("PKT "):
            fields = dict(p.split("=", 1) for p in lines[idx].split()[1:])
            idx += 1
            if fields["ch"] != "0x%02X" % KEYBOARD_CHANNEL:
                problems.append("%s: a text packet left on channel %s, the keyboard "
                                "channel is the only one it may use"
                                % (name, fields["ch"]))
            payload = bytes.fromhex(fields["text"]) if fields["text"] else b""
            got_packets.append(payload)
            got_more.append(fields["more"])
            if int(fields["size"]) != sizeof_text(payload):
                problems.append("%s: the size field says %s bytes but %d text bytes were "
                                "copied, so the host reads a packet that does not "
                                "describe itself" % (name, fields["size"], len(payload)))
        summary = lines[idx] if idx < len(lines) else ""
        idx += 1
        got = dict(p.split("=", 1) for p in summary.split()[1:]) if summary.startswith("SUM ") else {}
        if not got:
            problems.append("%s: the manifest lost the run summary" % name)
            continue
        if got_packets != want_packets:
            problems.append("%s: packet payloads %s, model %s"
                            % (name, [p.hex() for p in got_packets],
                               [p.hex() for p in want_packets]))
        # Code points never straddle a packet boundary: only the last packet of a
        # block may end in the middle of one, and only because the text did.
        for number, payload in enumerate(got_packets[:-1]):
            if not is_whole_code_points(payload):
                problems.append("%s: packet %d splits a code point across a packet "
                                "boundary, which the host cannot parse"
                                % (name, number))
        if got_more != want_more:
            problems.append("%s: moreData flags %s, expected %s"
                            % (name, got_more, want_more))
        # The control-stream flush and its waits belong to GFE alone. Sunshine
        # processes keyboard and text events in order, so making it wait buys
        # nothing and costs 50 ms per text block.
        want_flushes = 0 if sunshine else 1
        want_sleeps = 0 if sunshine else 2
        if int(got["flushes"]) != want_flushes:
            problems.append("%s: %s control-stream flush, %d expected for this host"
                            % (name, got["flushes"], want_flushes))
        if int(got["sleeps"]) != want_sleeps:
            problems.append("%s: %d waits on the control stream, %d expected for this "
                            "host (the drain poll and the 50 ms settle)"
                            % (name, int(got["sleeps"]), want_sleeps))
        if int(got["frees"]) != 1:
            problems.append("%s: the template packet holder was freed %s times, exactly "
                            "once is what the loop owes it" % (name, got["frees"]))
    if not actual.strip().endswith("RUN PASSED (%d scenarios)" % len(rows)):
        problems.append("the harness did not run its whole scenario table")
    return problems


def sizeof_text(payload):
    return 4 + len(payload)


def is_whole_code_points(payload):
    i = 0
    while i < len(payload):
        length = code_point_length(payload[i])
        if length == 0 or i + length > len(payload):
            return False
        i += length
    return True


def mutations():
    """Label, old, new triples planted into the shipping InputStream.c."""
    dense_call = ("uint32_t chunkLength = unicodeChunkLength(holder->packet.unicode.text, i,\n"
                  "                                                  remaining, sunshineHost);")
    return [
        ("Sunshine stops packing densely and a text block floods the link again",
         dense_call, dense_call.replace("remaining, sunshineHost);", "remaining, false);")),
        ("GFE starts packing densely and keeps only the first code point of a packet",
         dense_call, dense_call.replace("remaining, sunshineHost);", "remaining, true);")),
        # The GFE branch is where a boundary split stays inside the packet buffer:
        # cutting the dense guard instead would write past the 32-byte text field,
        # which the harness could only report as a crash, and a crash is not a wire
        # observation. One byte per packet splits every multi-byte code point.
        ("a code point is allowed to straddle a packet boundary",
         "    return codePointLength < remaining ? codePointLength : remaining;",
         "    return 1 < remaining ? 1 : remaining;"),
        ("the size field stops describing the bytes that were copied",
         "BE32(sizeof(uint32_t) + chunkLength)", "BE32(chunkLength)"),
        ("the GFE-only flush and 50 ms wait disappear entirely",
         "if (unicodeNeedsControlStreamFlush(sunshineHost)) {",
         "if (false && unicodeNeedsControlStreamFlush(sunshineHost)) {"),
        ("Sunshine starts paying the GFE flush and wait",
         "if (unicodeNeedsControlStreamFlush(sunshineHost)) {",
         "if (true || unicodeNeedsControlStreamFlush(sunshineHost)) {"),
        ("a dense chunk stops clamping to the text that is actually left",
         "  // Clamp the chunk if the final code point is truncated\n"
         "  return chunkLength < remaining ? chunkLength : remaining;",
         "  // Clamp the chunk if the final code point is truncated\n"
         "  return chunkLength;"),
    ]


def run(root):
    global COMMON, INPUT_STREAM
    COMMON = os.path.join(root, "moonlight-common", "moonlight-common-c", "src")
    INPUT_STREAM = os.path.join(COMMON, "InputStream.c")
    if not os.path.exists(INPUT_STREAM):
        print("SKIP unicode-dense-packing-tests: the moonlight-common submodule is "
              "not checked out at %s" % INPUT_STREAM)
        return
    limit = max_count()
    shipping = read(INPUT_STREAM)
    cc, sdk = apple_toolchain.clang_and_sdk("the UTF-8 packing harness")
    rows = scenario_table()
    with tempfile.TemporaryDirectory() as work:
        code, log = compile_and_run(shipping, work, cc, sdk)
        if code is None:
            check(False, "%s: %s" % (apple_toolchain.PROBE_BUILD_FAILED_MESSAGE, log))
            return
        check(code == 0 and "RUN PASSED" in log,
              "the shipping UTF-8 sender ran its scenario table (exit %d)" % code)
        if code != 0:
            print(log[-2000:])
            return
        problems = replay(log, limit)
        for problem in problems:
            check(False, problem)
        if not problems:
            print("ok   all %d scenarios match the recorded packet manifest, the size "
                  "field, the boundary rule and the flush budget" % len(rows))
    if not SELF_TEST:
        return
    behavioural = 0
    for label, old, new in mutations():
        if shipping.count(old) != 1:
            check(False, "the self-test mutation '%s' must match exactly once (found %d)"
                  % (label, shipping.count(old)))
            continue
        with tempfile.TemporaryDirectory() as work:
            code, log = compile_and_run(shipping.replace(old, new, 1), work, cc, sdk)
            if code is None:
                check(False, "NOT CAUGHT by behaviour (%s): the mutant only failed to "
                             "compile, which proves the harness reads the right lines, "
                             "not the wire" % label)
                continue
            problems = replay(log, limit)
            if code == 0 and problems:
                behavioural += 1
            caught = bool(problems) or code != 0
            check(caught, "the manifest fails when %s" % label
                  if caught else "NOT CAUGHT (%s)" % label)
    # A gate that only notices broken syntax would be worthless, so the strength of
    # this one is graded as well as the count.
    check(behavioural == len(mutations()),
          "all %d planted defects are caught on the wire, not on the compiler"
          % len(mutations()) if behavioural == len(mutations()) else
          "only %d of %d planted defects were caught on the wire"
          % (behavioural, len(mutations())))


def main():
    run(ROOT)
    if failures:
        print("unicode-dense-packing-tests: %d failures" % len(failures))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("unicode-dense-packing-tests: all checks passed"
          + (" (self-test included)" if SELF_TEST else ""))


if __name__ == "__main__":
    main()
