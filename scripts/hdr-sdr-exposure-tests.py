#!/usr/bin/env python3
"""Prove that every tone-mapping policy knows the exposure it applies, and says so.

Upstream PR #47 asks for the HDR-to-SDR compensation to be removed. That is a disagreement
about a number, and this fork answers numbers with a family of policies, so the answer here
is one more policy -- No Exposure Shift -- and not a changed default. Which makes two things
worth locking down: that the five policies already shipped apply exactly the numbers they
applied before this change, and that the number is now an answer a test can ask for instead
of a literal sitting inside Metal source that no runner can compile.

So the exposure moved out of the shader into a C function, and the shader is handed the
result through a uniform component it never read before. The function is compiled with a real
clang and driven across every policy and every transfer mode: eighteen pairs. The rest is
structure -- the constants appear once, in one place; the kernel receives the value; the
Swift picker and the C enum still describe the same set of policies -- and each of those
rules is shown to bite by planting the defect it exists to catch.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
SWIFT = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"

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
    renderer = read(RENDERER)
    return "\n".join([
        block(renderer, r"typedef NS_ENUM\(NSUInteger, MLHDRTransferMode\) \{.*?\};", "transfer modes"),
        block(renderer, r"typedef NS_ENUM\(NSInteger, MLHDRToneMappingPolicy\) \{.*?\};", "policies"),
        block(renderer, r"static float MLHDRSdrExposureForPolicy\(.*?\n\}", "the exposure answer"),
    ])


DRIVER = r'''
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;

static void expect(const char *what, float got, double want) {
    BOOL ok = fabsf(got - (float)want) < 0.0001f;
    if (!ok) failures++;
    printf("%-4s %-52s -> %.3f (want %.2f)\n", ok ? "ok" : "FAIL", what, got, want);
}

int main(void) {
    const MLHDRTransferMode modes[] = {MLHDRTransferModeSDR, MLHDRTransferModePQ,
                                       MLHDRTransferModeHLG};
    const char *modeNames[] = {"sdr", "pq", "hlg"};
    struct {
        const char *name;
        MLHDRToneMappingPolicy policy;
        double pq;
        double other;
    } table[] = {
        // The five policies this fork has always shipped keep the numbers they applied in
        // the shader: this change adds a choice, it does not quietly re-tune a default.
        {"auto", MLHDRToneMappingPolicyAuto, 0.82, 1.08},
        {"preserve highlights", MLHDRToneMappingPolicyPreserveHighlights, 0.82, 1.08},
        {"preserve midtones", MLHDRToneMappingPolicyPreserveMidtones, 0.82, 1.08},
        {"preserve shadows", MLHDRToneMappingPolicyPreserveShadows, 0.82, 1.08},
        {"reference", MLHDRToneMappingPolicyReference, 0.82, 1.08},
        // The one upstream asked for, and it is a policy: nothing shifts at all, whatever
        // the transfer function turned out to be.
        {"no exposure shift", MLHDRToneMappingPolicyNoExposureShift, 1.0, 1.0},
    };
    for (unsigned policy = 0; policy < 6; policy++) {
        for (unsigned mode = 0; mode < 3; mode++) {
            char label[128];
            snprintf(label, sizeof(label), "%s under %s", table[policy].name, modeNames[mode]);
            double want = modes[mode] == MLHDRTransferModePQ ? table[policy].pq
                                                             : table[policy].other;
            expect(label, MLHDRSdrExposureForPolicy(table[policy].policy, modes[mode]), want);
        }
    }
    printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
    return failures ? 1 : 0;
}
'''


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2500:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2500:]


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "hdrexp", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "every policy states the exposure it applies"
                  if code == 0 else "the shipping exposure answer failed a case:" + out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def structural(renderer, swift):
    """The rules that hold without compiling Metal: one constant, one home, one table."""
    problems = []
    if renderer.count('float exposure = sdrExposure;') != 1:
        problems.append("the shader no longer takes its exposure from the value it is given")
    # 1.08 is also the office-lighting HLG multiplier elsewhere in this file, so the rule
    # is not "this number appears once in the world"; it is "the tone map decides nothing
    # on its own", which is exactly what putting the constant back into Metal source breaks.
    try:
        body = renderer[renderer.index('float3 toneMapHdrToSdr('):
                       renderer.index('float3 processHdr(')]
    except ValueError:
        problems.append("the tone map is no longer the span this rule can read")
        body = ""
    for constant in ("0.82", "1.08"):
        if constant in body:
            problems.append("%s went back inside the shader" % constant)
    if renderer.count("params.hdrControls.y") != 1:
        problems.append("the kernel is not handed the exposure any more")
    if renderer.count("MLHDRSdrExposureForPolicy(toneMappingPolicy, hdrTransferMode)") != 1:
        problems.append("the parameters no longer ask the one function that answers")
    if renderer.count("uint tonePolicy, float sdrExposure, float4 hdrLuminance") != 2:
        problems.append("one of the two shader entry points stopped carrying the exposure")

    enum_values = [int(v) for v in re.findall(
        r"MLHDRToneMappingPolicy\w+\s*=\s*(\d+)",
        block(renderer, r"typedef NS_ENUM\(NSInteger, MLHDRToneMappingPolicy\) \{.*?\};",
              "policies"))]
    picker = block(swift, r"hdrToneMappingPolicyOptions: \[\(title: String, value: Int\)\] = \[.*?\]",
                   "the picker")
    swift_pairs = re.findall(r"\(\s*\"([^\"]+)\"\s*,\s*(\d+)\s*\)", picker)
    if sorted(int(v) for _, v in swift_pairs) != sorted(enum_values):
        problems.append("the picker and the C enum no longer offer the same policies")
    faithful = [v for title, v in swift_pairs if title == "No Exposure Shift"]
    c_faithful = re.findall(r"MLHDRToneMappingPolicyNoExposureShift\s*=\s*(\d+)", renderer)
    if len(faithful) != 1 or len(c_faithful) != 1 or faithful[0] != c_faithful[0]:
        problems.append("the new policy means a different number in C and in the picker")
    return problems


def expect_structure(renderer, swift, label, ok_when_clean):
    problems = structural(renderer, swift)
    if ok_when_clean:
        check(not problems, label if not problems else "; ".join(problems))
    else:
        check(bool(problems), label)


def main():
    renderer = read(RENDERER)
    swift = read(SWIFT)
    rules = shipping_rules()
    print("-- what each tone-mapping policy actually applies, and where that number lives --")

    cc, sdk = apple_toolchain.clang_and_sdk("hdr sdr exposure")
    run_rules("the shipping exposure answer", rules, cc, sdk, expect_pass=True)

    expect_structure(renderer, swift,
                     "one constant, one home, one picker, and a kernel that is told", True)

    run_rules("the new policy shifts the picture after all",
              mutated(rules, "the faithful answer",
                      "        return 1.0f;", "        return 0.82f;"),
              cc, sdk)
    run_rules("the PQ default drifted",
              mutated(rules, "the pq number",
                      "    return transferMode == MLHDRTransferModePQ ? 0.82f : 1.08f;",
                      "    return transferMode == MLHDRTransferModePQ ? 1.08f : 1.08f;"),
              cc, sdk)
    run_rules("the non-PQ default drifted",
              mutated(rules, "the other number",
                      "    return transferMode == MLHDRTransferModePQ ? 0.82f : 1.08f;",
                      "    return transferMode == MLHDRTransferModePQ ? 0.82f : 1.0f;"),
              cc, sdk)

    expect_structure(renderer.replace("float exposure = sdrExposure;",
                                      "float exposure = hdrMode == 1 ? 0.82 : 1.08;"), swift,
                     "the constant planted back inside the shader is refused", False)
    expect_structure(renderer.replace('"                     params.hdrControls.y,' + chr(92) + 'n"', ""),
                     swift,
                     "a kernel that is not handed the exposure is refused", False)
    expect_structure(renderer, swift.replace('    ("Reference", 4),\n', ""),
                     "a picker that lost a policy is refused", False)
    expect_structure(renderer.replace("MLHDRToneMappingPolicyNoExposureShift = 5",
                                      "MLHDRToneMappingPolicyNoExposureShift = 6"), swift,
                     "a policy that means two different numbers is refused", False)

    print("%d hdr-sdr-exposure failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
