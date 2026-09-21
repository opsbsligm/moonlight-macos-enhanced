#!/usr/bin/env python3
"""Prove 10-bit samples can carry an SDR picture, and that nothing else moved.

Issue #22 asks for what the Qt client offers as two independent controls: a 10-bit
transport, and HDR. Here HDR was the only road to a 10-bit format bit, so the
combination could not be requested at all, and a person whose display would gain from
10-bit banding-free SDR had to take PQ or HLG to get it.

The change is small, which is the danger: a small change to codec negotiation moves
every stream in the tree. So the first thing compiled here is the answer that shipped
before it -- the old if-chain, kept as a model -- and the 32 combinations of the five
inputs have to agree with it wherever 10-bit SDR is not asked for. A refactor that
quietly improved one combination would show up as a disagreement, not as a green run.

Then the new request itself is played: 10-bit bits appear under SDR; the 4:4:4 10-bit
profiles appear with it; AV1 switches profile rather than advertising two; HDR and the
10-bit SDR switch together are the same answer as HDR alone; and a Mac whose only codec
is 8-bit is left exactly where it was, because a request that cannot be encoded must
degrade rather than lie.

The failure the reporter described is a rendering one -- oversaturated or washed out --
so the second half matters more than the bits: the dynamic range the picture is drawn
with comes out of Connection.m, and it has to stay a function of the HDR preference
alone. That function is compiled from the shipping source and swept across every
transfer preference with HDR off, and the answer may not move. That is the rule that
would catch the bug being reported, if this client ever moved it.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
NEGOTIATION = "Limelight/Stream/VideoFormatNegotiation.h"
CONNECTION = "Limelight/Stream/Connection.m"
CORE_HEADER_DIR = "moonlight-common/moonlight-common-c/src"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
STORE = "Limelight/macOS/ViewControllers/SettingsStore.swift"
PREFERENCE_KEY = "sdr10bit"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def block(text, pattern, what):
    found = re.search(pattern, text, re.S)
    if found is None:
        raise SystemExit("%s: the source that should hold it changed shape" % what)
    return found.group(0)


def shipping_rules():
    header = read(NEGOTIATION)
    connection = read(CONNECTION)
    return "\n".join([
        block(header, r"typedef struct \{.*?\} MLVideoFormatRequest;", "the request"),
        block(header, r"static inline BOOL MLVideoFormatRequestWantsTenBit\(.*?\n\}",
              "the 10-bit answer"),
        block(header, r"static inline int MLResolveSupportedVideoFormats\(.*?\n\}",
              "the format answer"),
        block(header, r"static inline BOOL MLVideoFormatRequestIsSatisfiable\(.*?\n\}",
              "the satisfiability answer"),
        # The picture's dynamic range, taken from the file that decides it.
        block(connection, r"static int MLResolvedDynamicRangeModeForPreference\(.*?\n\}",
              "the dynamic range answer"),
    ])


# The answer that shipped while HDR was the only road to 10-bit samples. It lives here,
# beside the core macros it names, so that the comparison below is a comparison of two
# answers to the same question rather than a restatement of one answer twice.
LEGACY = r'''
static int MLLegacySupportedVideoFormats(BOOL hevcAvailable, BOOL av1Available,
                                         BOOL hdrRequested, BOOL yuv444Requested) {
    int formats = VIDEO_FORMAT_H264;
    if (hevcAvailable) {
        formats |= VIDEO_FORMAT_H265;
        if (hdrRequested) {
            formats |= VIDEO_FORMAT_H265_MAIN10;
        }
    }
    if (yuv444Requested) {
        formats |= VIDEO_FORMAT_H264_HIGH8_444;
        if (hevcAvailable) {
            formats |= VIDEO_FORMAT_H265_REXT8_444;
            if (hdrRequested) {
                formats |= VIDEO_FORMAT_H265_REXT10_444;
            }
        }
    }
    if (av1Available) {
        formats |= hdrRequested ? VIDEO_FORMAT_AV1_MAIN10 : VIDEO_FORMAT_AV1_MAIN8;
        if (yuv444Requested) {
            formats |= VIDEO_FORMAT_AV1_HIGH8_444;
            if (hdrRequested) {
                formats |= VIDEO_FORMAT_AV1_HIGH10_444;
            }
        }
    }
    return formats;
}
'''

DRIVER = r'''
#import <Foundation/Foundation.h>
#import <Limelight.h>

@@RULES@@

@@LEGACY@@

static int failures = 0;

static void expect(const char *what, int got, int want) {
    BOOL ok = got == want;
    if (!ok) failures++;
    printf("%-4s %-58s -> 0x%04X (want 0x%04X)\n", ok ? "ok" : "FAIL", what, got, want);
}

static void expectTrue(const char *what, BOOL got, BOOL want) {
    BOOL ok = got == want;
    if (!ok) failures++;
    printf("%-4s %-58s -> %s (want %s)\n", ok ? "ok" : "FAIL", what,
           got ? "yes" : "no", want ? "yes" : "no");
}

int main(void) {
    // Every combination of the five inputs, so no branch is reached by one case only.
    for (unsigned bits = 0; bits < 32; bits++) {
        MLVideoFormatRequest request = {
            .hevcAvailable = (bits >> 0) & 1,
            .av1Available = (bits >> 1) & 1,
            .hdrRequested = (bits >> 2) & 1,
            .sdrTenBitRequested = (bits >> 3) & 1,
            .yuv444Requested = (bits >> 4) & 1,
        };
        int got = MLResolveSupportedVideoFormats(request);
        char label[160];
        snprintf(label, sizeof(label), "hevc=%d av1=%d hdr=%d sdr10=%d 444=%d",
                 request.hevcAvailable, request.av1Available, request.hdrRequested,
                 request.sdrTenBitRequested, request.yuv444Requested);

        // Where 10-bit SDR is not asked for, nothing may have moved.
        if (!request.sdrTenBitRequested) {
            expect(label, got, MLLegacySupportedVideoFormats(request.hevcAvailable,
                                                            request.av1Available,
                                                            request.hdrRequested,
                                                            request.yuv444Requested));
        }

        // Asking for 10-bit samples without HDR must add 10-bit bits and nothing else:
        // no 4:4:4 bit appears because of it, and the 8-bit bits already offered stay.
        if (request.sdrTenBitRequested && !request.hdrRequested) {
            int alone = MLResolveSupportedVideoFormats((MLVideoFormatRequest){
                .hevcAvailable = request.hevcAvailable, .av1Available = request.av1Available,
                .hdrRequested = NO, .sdrTenBitRequested = NO,
                .yuv444Requested = request.yuv444Requested});
            expectTrue("10-bit SDR reaches a 10-bit profile",
                       (got & VIDEO_FORMAT_MASK_10BIT) != 0,
                       request.hevcAvailable || request.av1Available);
            // A request about sample depth may not decide whether 4:4:4 is on offer.
            // It may deepen the 4:4:4 profiles it finds there, which is the point.
            expectTrue("10-bit SDR introduces no 4:4:4 by itself",
                       (got & VIDEO_FORMAT_MASK_YUV444) != 0,
                       (alone & VIDEO_FORMAT_MASK_YUV444) != 0);
            // AV1 picks one profile by depth, so its 8-bit bit has to go. HEVC has a
            // separate 8-bit Main bit, and dropping it would narrow the host's choice
            // for a reason nobody asked for.
            expectTrue("the 8-bit HEVC bit survives the 10-bit request",
                       request.hevcAvailable ? (got & VIDEO_FORMAT_H265) != 0 : YES, YES);
            expectTrue("10-bit SDR does not also offer the 8-bit AV1 profile",
                       request.av1Available ? (got & VIDEO_FORMAT_AV1_MAIN8) == 0 : YES, YES);
            // HDR and the 10-bit switch together cannot offer more than HDR alone: the
            // two requests ask for the same bits, so one is a no-op beside the other.
            int hdrOnly = MLResolveSupportedVideoFormats((MLVideoFormatRequest){
                .hevcAvailable = request.hevcAvailable, .av1Available = request.av1Available,
                .hdrRequested = YES, .sdrTenBitRequested = NO,
                .yuv444Requested = request.yuv444Requested});
            int both = MLResolveSupportedVideoFormats((MLVideoFormatRequest){
                .hevcAvailable = request.hevcAvailable, .av1Available = request.av1Available,
                .hdrRequested = YES, .sdrTenBitRequested = YES,
                .yuv444Requested = request.yuv444Requested});
            expect("hdr with the 10-bit switch is hdr alone", both, hdrOnly);
        }

        // A Mac with no 10-bit codec in hardware is not asked to advertise one. What it
        // may still offer is the 8-bit 4:4:4 profile, which this request says nothing about.
        if (request.sdrTenBitRequested && !request.hevcAvailable && !request.av1Available) {
            expectTrue("no 10-bit codec, no 10-bit bit", (got & VIDEO_FORMAT_MASK_10BIT) == 0,
                       YES);
            if (!request.yuv444Requested) {
                expect("no 10-bit codec and no 4:4:4 is the plain stream", got, VIDEO_FORMAT_H264);
            }
        }

        expectTrue("satisfiability answers for HDR alone",
                   MLVideoFormatRequestIsSatisfiable(request),
                   !request.hdrRequested || request.hevcAvailable || request.av1Available);

        // The picture. Whatever the transfer preference says, a stream not asked for as
        // HDR is drawn as SDR: this is the oversaturation the report describes, and it
        // has to be unreachable from the 10-bit side of the negotiation.
        if (!request.hdrRequested) {
            for (int tf = 0; tf <= 2; tf++) {
                char rangeLabel[96];
                snprintf(rangeLabel, sizeof(rangeLabel),
                         "dynamic range with hdr off, preference %d", tf);
                expect(rangeLabel,
                       MLResolvedDynamicRangeModeForPreference(NO, tf),
                       DYNAMIC_RANGE_MODE_SDR);
            }
        }
    }

    // The named cases, spelled out so a regression names itself.
    MLVideoFormatRequest sdrTen = {.hevcAvailable = YES, .av1Available = YES,
                                   .sdrTenBitRequested = YES};
    expect("10-bit SDR over both codecs",
           MLResolveSupportedVideoFormats(sdrTen),
           VIDEO_FORMAT_H264 | VIDEO_FORMAT_H265 | VIDEO_FORMAT_H265_MAIN10 |
           VIDEO_FORMAT_AV1_MAIN10);
    MLVideoFormatRequest sdrTen444 = {.hevcAvailable = YES, .av1Available = YES,
                                      .sdrTenBitRequested = YES, .yuv444Requested = YES};
    expectTrue("10-bit SDR with 4:4:4 reaches the 10-bit 4:4:4 profiles",
               (MLResolveSupportedVideoFormats(sdrTen444) &
                (VIDEO_FORMAT_H265_REXT10_444 | VIDEO_FORMAT_AV1_HIGH10_444))
               == (VIDEO_FORMAT_H265_REXT10_444 | VIDEO_FORMAT_AV1_HIGH10_444), YES);
    expect("the switch off is the tree that shipped",
           MLResolveSupportedVideoFormats((MLVideoFormatRequest){
               .hevcAvailable = YES, .av1Available = YES, .yuv444Requested = YES}),
           MLLegacySupportedVideoFormats(YES, YES, NO, YES));

    printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
    return failures ? 1 : 0;
}
'''


def compiled(source, work, cc, sdk):
    path = os.path.join(work, "sdr10.m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-I", os.path.join(ROOT, CORE_HEADER_DIR),
               "-framework", "Foundation", path, "-o", os.path.join(work, "sdr10")]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2500:]
    ran = subprocess.run([os.path.join(work, "sdr10")], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2500:]


def run_rules(label, rules, cc, sdk, driver=None, expect_pass=False):
    source = (driver or DRIVER).replace("@@RULES@@", rules).replace("@@LEGACY@@", LEGACY)
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(source, work, cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return False
        if expect_pass:
            ok = code == 0 and "RUN PASSED" in (out or "")
            check(ok, "the shipped negotiation answers every case"
                  if ok else "the shipping negotiation failed a case:" + (out or log))
            return ok
        check(code != 0, "the run fails when %s" % label)
        return code != 0


def settings_constructions_missing(argument, beside):
    """Lines where a Settings(...) call passes `beside` but not `argument`.

    Every stored member of Settings is optional, and Swift lets an optional member be
    left out of the memberwise initialiser, so a construction that forgets one compiles
    and silently answers with the default instead of the value it was copying. For a
    preference that reaches the encoder through one dictionary, forgetting it is not a
    cosmetic miss: the setting would stop surviving that one code path.
    """
    missing = {}
    folder = os.path.join(ROOT, "Limelight/macOS/ViewControllers")
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".swift"):
            continue
        text = open(os.path.join(folder, name), encoding="utf-8").read()
        for found in re.finditer(r"Settings\(", text):
            i, depth = found.end() - 1, 0
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            arguments = text[found.end():i]
            if beside in arguments and argument not in arguments:
                missing.setdefault(name, []).append(
                    text.count("\n", 0, found.start()) + 1)
    return missing


def main():
    cc, sdk = apple_toolchain.clang_and_sdk("10-bit codec negotiation")
    if cc is None:
        print("SKIP no clang/SDK pair on this host")
        return 1

    rules = shipping_rules()
    run_rules("shipped", rules, cc, sdk, expect_pass=True)

    # Each mutation is the mistake this feature could actually make, not a random edit.
    mutations = [
        ("10-bit SDR is ignored",
         lambda r: r.replace("return request.hdrRequested || request.sdrTenBitRequested;",
                             "return request.hdrRequested;")),
        ("10-bit SDR is treated as HDR",
         lambda r: r.replace("return request.hdrRequested || request.sdrTenBitRequested;",
                             "return request.hdrRequested && request.sdrTenBitRequested;")),
        ("AV1 stays 8-bit under the request",
         lambda r: r.replace("formats |= wantsTenBit ? VIDEO_FORMAT_AV1_MAIN10 : VIDEO_FORMAT_AV1_MAIN8;",
                             "formats |= VIDEO_FORMAT_AV1_MAIN8;")),
        ("the dynamic range starts following sample depth",
         lambda r: r.replace("static int MLResolvedDynamicRangeModeForPreference(BOOL hdrEnabled, int hdrTransferFunction) {\n    if (!hdrEnabled) {",
                             "static int MLResolvedDynamicRangeModeForPreference(BOOL hdrEnabled, int hdrTransferFunction) {\n    if (hdrEnabled || hdrTransferFunction == 7) {")),
        ("a machine with no 10-bit codec is told it has one",
         lambda r: r.replace("if (request.hevcAvailable) {\n        formats |= VIDEO_FORMAT_H265;",
                             "if (YES) {\n        formats |= VIDEO_FORMAT_H265;")),
        ("satisfiability starts refusing 10-bit SDR",
         lambda r: r.replace("    if (!request.hdrRequested) {\n        return YES;\n    }",
                             "    if (!request.hdrRequested) {\n        return !request.sdrTenBitRequested;\n    }")),
    ]
    for name, mutate in mutations:
        mutated = mutate(rules)
        check(mutated != rules, "the %s mutation is a real edit" % name)
        run_rules(name, mutated, cc, sdk)

    connection = read(CONNECTION)
    bridge = read(BRIDGE)
    store = read(STORE)

    check("MLResolveSupportedVideoFormats(formatRequest)" in connection,
          "the connection asks the shared answer for its bits instead of assembling them")
    bits_at_callsite = connection[
        connection.index("MLVideoFormatRequest formatRequest"):
        connection.index("_streamConfig.supportedVideoFormats")]
    check("supportedVideoFormats |=" not in bits_at_callsite
          and "VIDEO_FORMAT_" not in bits_at_callsite,
          "no format bit is assembled outside the shared answer any more")
    check('settings[@"%s"]' % PREFERENCE_KEY in connection,
          "the connection reads the %s preference it negotiates with" % PREFERENCE_KEY)
    check('"%s"' % PREFERENCE_KEY in bridge,
          "the Swift side hands the connection the %s key under the same name" % PREFERENCE_KEY)
    check(PREFERENCE_KEY in store or "sdr10Bit" in store or "enable10BitSdr" in store,
          "the preference is carried by the settings store, not invented at the call site")
    # Both switches reach the connection through the same dictionary, so a construction
    # that copies one and drops the other would lose the setting along that path only --
    # and compile clean, because every stored member here is optional.
    forgotten = settings_constructions_missing("enable10BitSdr:", "enableYUV444:")
    check(not forgotten,
          "every Settings construction that carries 4:4:4 also carries the 10-bit switch"
          if not forgotten else
          "constructions that drop the new preference: "
          + "; ".join("%s line %s" % (f, lines) for f, lines in sorted(forgotten.items())))

    check("dynamicRangeMode =\n        MLResolvedDynamicRangeModeForPreference(config.enableHdr"
          in connection or
          "MLResolvedDynamicRangeModeForPreference(config.enableHdr" in connection,
          "the dynamic range is still answered by the HDR preference alone")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
