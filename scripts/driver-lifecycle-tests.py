#!/usr/bin/env python3
"""Prove that a driver extension nobody has shipped cannot be relied on by accident.

Stage 3 of docs/usb-redirection-design.md is blocked on a signing identity and a notarisation
pipeline, both recorded as missing in 2.3, which measures the shipping product's own identity
(`Signature=adhoc`, `TeamIdentifier=not set`) instead of guessing at it. An earlier version of
this header cited an `OSSystemExtensionErrorAuthorizationFailed` measurement that 2.3 does not
contain and that this SDK's `OSSystemExtensionErrorCode` does not name -- thirteen cases, none
of them that one -- so the citation is gone and the structural reason stands. What is not
blocked is the
logic around that wall, so this gate covers it: what happens between asking for an extension and
trusting it, and between a device being handed over and the thing holding it dying.

Three claims hold the file together, and each has a planted defect:

  a request that never finished ends in a phase that says so. An install that stays `installing`
    forever is a settings page that never tells the player anything; a removal that "finished" on
    a timeout is a claim about somebody else's system that nothing observed;
  an extension being loaded and a device being free are separate facts. A check that asked only
    one of them would hand a device to a host while another session still held it, or report a
    device as unusable because an uninstall happened;
  a crash keeps what it was holding. A lease that came free the moment its holder died would let
    the next session attach to a device the dying extension may still have configured, so orphaned
    leases expire rather than return -- and the second arrival of the same device starts a new
    lease, because otherwise a device would be usable because of something that happened the last
    time it was plugged in.

Nothing here reads a clock: a timeout is an event the caller reports, and the assertions below
check that the alternatives are absent rather than trusting that claim. Devices are named by the
Stage 1 audit token, which is a digest, so a lifecycle log cannot become a hardware inventory.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_DRIVER_CHECKS = 30
LIFECYCLE_H = "Limelight/Stream/DriverLifecycle.h"
LIFECYCLE_M = "Limelight/Stream/DriverLifecycle.m"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def strip_imports(text, quoted):
    for name in quoted:
        text = text.replace('#import "%s"\n' % name, "")
    return text.replace("#import <Foundation/Foundation.h>\n", "")


def shipping_rules():
    header, impl = read(LIFECYCLE_H), read(LIFECYCLE_M)
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", header + impl))) ==
          ["Foundation/Foundation.h"],
          "the lifecycle imports nothing beyond Foundation: no DriverKit, no IOKit, no clock")
    rules = strip_imports(header, ["DriverLifecycle.h"]) + "\n" + \
        strip_imports(impl, ["DriverLifecycle.h"])
    check("#import" not in rules, "the compiled bundle carries no import at all")
    return rules


DRIVER = r"""
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

#define DEVICE(token) [MLManagedDevice managedDeviceWithToken:(token)]

static void check_case(BOOL ok, const char *what) {
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

// expect_lifecycle is the whole assertion for one step: phase, reason, crash tally, and the two
// questions the rest of the app would ask. Checking the phase alone would pass for an
// implementation that landed in the right place for a reason it could not name.
static void expect_lifecycle(const char *what, MLDriverLifecycle *lifecycle,
                             MLDriverExtensionPhase phase, MLDriverLifecycleStop stop,
                             NSInteger crashes, BOOL install, BOOL handover) {
    const BOOL ok = lifecycle.phase == phase && lifecycle.stop == stop &&
                    lifecycle.crashesObserved == crashes &&
                    lifecycle.mayAttemptInstall == install &&
                    lifecycle.mayHandOverDevices == handover;
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %-50s -> phase=%s stop=%s crashes=%ld/%ld ask:%s%s\n",
           ok ? "ok" : "FAIL", what,
           MLDriverExtensionPhaseName(lifecycle.phase).UTF8String,
           MLDriverLifecycleStopName(lifecycle.stop).UTF8String,
           (long)lifecycle.crashesObserved, (long)lifecycle.crashBudget,
           install ? "I" : "-", handover ? "H" : "-");
}

// expect_lease is the other half of the same claim: whether the extension is loaded and whether
// this device is free are answered by different questions, and a device is usable only when both.
static void expect_lease(const char *what, MLDriverLifecycle *lifecycle, NSString *token,
                         MLDeviceLeaseState state, BOOL usable) {
    const MLDeviceLeaseState got = [lifecycle leaseStateForDeviceToken:token];
    const BOOL ok = got == state && [lifecycle mayUseDeviceToken:token] == usable;
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %-50s -> lease=%s usable:%s\n", ok ? "ok" : "FAIL", what,
           MLDeviceLeaseStateName(got).UTF8String, usable ? "Y" : "-");
}

static MLDriverLifecycle *untouched(NSInteger budget) {
    return [MLDriverLifecycle untouchedLifecycleWithCrashBudget:budget];
}

static MLDriverLifecycle *installing(void) {
    return [untouched(3) lifecycleByRequestingInstall];
}

static MLDriverLifecycle *active(void) {
    return [[installing() lifecycleByRecordingActivation]
                lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")];
}

int main(void) {
    @autoreleasepool {
        // Out of the box. Nothing is installed, nothing is held, and nothing may be relied on.
        expect_lifecycle("nothing asked for yet", untouched(3),
                         MLDriverExtensionPhaseNotInstalled,
                         MLDriverLifecycleStopNeverRequested, 0, YES, NO);
        // A budget of zero means the first death is the last attempt. It is spelled as a chain
        // of named steps rather than one nested expression, because a message chain this long is
        // where a mismatched bracket hides behind a name.
        MLDriverLifecycle *no_retries = [untouched(0) lifecycleByRequestingInstall];
        no_retries = [no_retries lifecycleByRecordingActivation];
        no_retries = [no_retries lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")];
        no_retries = [no_retries lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")];
        expect_lifecycle("a device was taken under a budget of none", no_retries,
                         MLDriverExtensionPhaseActive, MLDriverLifecycleStopNone, 0, NO, YES);
        expect_lifecycle("one death is already the last attempt",
                         [no_retries lifecycleByRecordingCrash],
                         MLDriverExtensionPhaseHeldBack,
                         MLDriverLifecycleStopCrashBudgetSpent, 1, NO, NO);
        // A negative budget is not "infinite retries" and not "always held back": both would
        // turn a nonsense argument into a behaviour nobody chose. It becomes the default, and
        // the default is what the crash cases below are counted against.
        check_case(untouched(-1).crashBudget == 3 && untouched(0).crashBudget == 0,
                   "a nonsense crash budget becomes the default rather than a new behaviour");

        // Asking for the extension, and the two ways an answer does not arrive.
        expect_lifecycle("a request was made", installing(),
                         MLDriverExtensionPhaseInstalling, MLDriverLifecycleStopNone, 0, NO, NO);
        expect_lifecycle("the player approved, which is not a loaded extension",
                         [installing() lifecycleByRecordingUserApproval],
                         MLDriverExtensionPhaseInstalling, MLDriverLifecycleStopNone, 0, NO, NO);
        expect_lifecycle("the extension is up", [installing() lifecycleByRecordingActivation],
                         MLDriverExtensionPhaseActive, MLDriverLifecycleStopNone, 0, NO, YES);
        expect_lifecycle("activation nobody asked for is refused",
                         [untouched(3) lifecycleByRecordingActivation],
                         MLDriverExtensionPhaseNotInstalled,
                         MLDriverLifecycleStopNeverRequested, 0, YES, NO);
        expect_lifecycle("activation reported twice is the same fact",
                         [[installing() lifecycleByRecordingActivation]
                             lifecycleByRecordingActivation],
                         MLDriverExtensionPhaseActive, MLDriverLifecycleStopNone, 0, NO, YES);
        expect_lifecycle("the install was asked for and nothing came back",
                         [installing() lifecycleByRecordingInstallTimeout],
                         MLDriverExtensionPhaseNotInstalled,
                         MLDriverLifecycleStopInstallUnanswered, 0, YES, NO);
        expect_lifecycle("the player declined: nothing is installed, and we do not ask again",
                         [installing() lifecycleByRecordingUserDecline],
                         MLDriverExtensionPhaseNotInstalled, MLDriverLifecycleStopUserDeclined,
                         0, NO, NO);
        expect_lifecycle("an install may not be removed out from under itself",
                         [installing() lifecycleByRequestingRemoval],
                         MLDriverExtensionPhaseInstalling, MLDriverLifecycleStopNone, 0, NO, NO);

        // Crashes, and the budget that stops the retrying.
        MLDriverLifecycle *held = [active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")];
        expect_lease("a device the extension took", held, @"a1b2c3d4",
                     MLDeviceLeaseStateHeld, YES);
        MLDriverLifecycle *crashed = [held lifecycleByRecordingCrash];
        expect_lifecycle("the extension died once", crashed,
                         MLDriverExtensionPhaseCrashed, MLDriverLifecycleStopNone, 1, NO, NO);
        expect_lease("a crash does not hand the device back", crashed, @"a1b2c3d4",
                     MLDeviceLeaseStateOrphaned, NO);
        expect_lease("an orphaned lease cannot be returned by the process that died",
                     [crashed lifecycleByReturningDevice:DEVICE(@"a1b2c3d4")], @"a1b2c3d4",
                     MLDeviceLeaseStateOrphaned, NO);
        expect_lease("an orphaned lease does expire",
                     [crashed lifecycleByExpiringLeaseForDevice:DEVICE(@"a1b2c3d4")],
                     @"a1b2c3d4", MLDeviceLeaseStateNone, NO);
        expect_lifecycle("a device that came back is a new arrival",
                         [[crashed lifecycleByExpiringLeaseForDevice:DEVICE(@"a1b2c3d4")]
                             lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")],
                         MLDriverExtensionPhaseCrashed, MLDriverLifecycleStopNone, 1, NO, NO);
        expect_lease("the second arrival inherits nothing",
                     [[crashed lifecycleByExpiringLeaseForDevice:DEVICE(@"a1b2c3d4")]
                         lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")], @"a1b2c3d4",
                     MLDeviceLeaseStateNone, NO);
        expect_lifecycle("a crashed extension is not reinstalled by asking again",
                         [crashed lifecycleByRequestingInstall],
                         MLDriverExtensionPhaseCrashed, MLDriverLifecycleStopNone, 1, NO, NO);
        MLDriverLifecycle *twice = [[crashed lifecycleByRecordingCrash]
                                        lifecycleByRecordingCrash];
        expect_lifecycle("the third death spends the budget", twice,
                         MLDriverExtensionPhaseHeldBack,
                         MLDriverLifecycleStopCrashBudgetSpent, 3, NO, NO);
        expect_lifecycle("held back cannot be argued out of holding back",
                         [[twice lifecycleByRequestingInstall]
                             lifecycleByRecordingActivation],
                         MLDriverExtensionPhaseHeldBack,
                         MLDriverLifecycleStopCrashBudgetSpent, 3, NO, NO);

        // Taking the extension away, including when that request goes unanswered.
        expect_lifecycle("a removal was asked for",
                         [active() lifecycleByRequestingRemoval],
                         MLDriverExtensionPhaseRemoving, MLDriverLifecycleStopNone, 0, NO, NO);
        expect_lifecycle("the removal finished",
                         [[active() lifecycleByRequestingRemoval]
                             lifecycleByRecordingRemovalCompleted],
                         MLDriverExtensionPhaseNotInstalled,
                         MLDriverLifecycleStopNeverRequested, 0, YES, NO);
        expect_lease("what the removed extension held is gone with it",
                     [[active() lifecycleByRequestingRemoval]
                         lifecycleByRecordingRemovalCompleted], @"a1b2c3d4",
                     MLDeviceLeaseStateNone, NO);
        expect_lifecycle("a removal that never answered leaves the extension where it was",
                         [[active() lifecycleByRequestingRemoval]
                             lifecycleByRecordingRemovalTimeout],
                         MLDriverExtensionPhaseRemoving,
                         MLDriverLifecycleStopRemovalUnanswered, 0, NO, NO);
        expect_lifecycle("a removal may not be asked for twice",
                         [[active() lifecycleByRequestingRemoval]
                             lifecycleByRequestingRemoval],
                         MLDriverExtensionPhaseRemoving, MLDriverLifecycleStopNone, 0, NO, NO);

        // Devices, leases, and the two hot-plug shapes that used to be the same thing.
        expect_lease("a device that appeared is not usable by itself",
                     [active() lifecycleByNoticingDevice:DEVICE(@"ffffffff")], @"ffffffff",
                     MLDeviceLeaseStateNone, NO);
        expect_lease("a device nobody mentioned", active(), @"deadbeef",
                     MLDeviceLeaseStateNone, NO);
        expect_lease("a device cannot be taken before it was mentioned",
                     [active() lifecycleByLeasingDevice:DEVICE(@"ffffffff")], @"ffffffff",
                     MLDeviceLeaseStateNone, NO);
        expect_lease("a device cannot be taken while no extension is loaded",
                     [[untouched(3) lifecycleByNoticingDevice:DEVICE(@"ffffffff")]
                         lifecycleByLeasingDevice:DEVICE(@"ffffffff")], @"ffffffff",
                     MLDeviceLeaseStateNone, NO);
        // A replug whose removal event never arrived -- the race a hub with a fast reconnect
        // actually produces. The extension may still be holding a device that is no longer there,
        // and a second arrival must not be usable on the strength of that older hand-over.
        expect_lease("a device replugged while the extension still holds it",
                     [[active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")]
                         lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")], @"a1b2c3d4",
                     MLDeviceLeaseStateNone, NO);
        // The other half of the two-question rule: a lease that outlived the phase that granted
        // it. The removal was asked for, so the extension is on its way out while holding a
        // device, and neither fact on its own is enough to let another host use it.
        expect_lease("a device still held while the extension is being removed",
                     [[active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")]
                         lifecycleByRequestingRemoval], @"a1b2c3d4",
                     MLDeviceLeaseStateHeld, NO);
        expect_lease("a device the removed extension was holding is gone with it",
                     [[[active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")]
                           lifecycleByRequestingRemoval]
                       lifecycleByRecordingRemovalCompleted], @"a1b2c3d4",
                     MLDeviceLeaseStateNone, NO);
        expect_lease("a device that went away stops being a device",
                     [[[active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")]
                           lifecycleByNoticingDeviceRemoved:DEVICE(@"a1b2c3d4")]
                       lifecycleByNoticingDevice:DEVICE(@"a1b2c3d4")], @"a1b2c3d4",
                     MLDeviceLeaseStateNone, NO);

        // What a line about the lifecycle may say. A token is a digest already, and the line is
        // still checked for it: the day somebody keys a device by product name, this is the
        // assertion that notices.
        MLDriverLifecycle *talking = [[active() lifecycleByLeasingDevice:DEVICE(@"a1b2c3d4")]
                                          lifecycleByRecordingCrash];
        expect_lifecycle("a crashed session with a lease held", talking,
                         MLDriverExtensionPhaseCrashed, MLDriverLifecycleStopNone, 1, NO, NO);
        check_case([talking.auditLine rangeOfString:@"a1b2c3d4"].location == NSNotFound,
                   "the line counts leases without repeating what they are attached to");
        check_case([talking.auditLine rangeOfString:@"1 orphaned"].location != NSNotFound,
                   "the line distinguishes a lease held from one its owner died holding");
        check_case([untouched(3).auditLine rangeOfString:@"phase=not-installed"].location
                   != NSNotFound,
                   "the line names the phase rather than a boolean");

        printf("%s (%d checks)\n", failures ? "RUN FAILED" : "RUN PASSED", checks_run);
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    binary = os.path.join(work, name)
    open(path, "w", encoding="utf-8").write(source)
    built = subprocess.run([cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                            "-framework", "Foundation", path, "-o", binary],
                           capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-1500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran, (ran.stdout + ran.stderr)


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        source = DRIVER.replace("@@RULES@@", rules)
        ran, out = compiled(source, work, "lifecycle_driver", cc, sdk)
        if ran is None:
            check(False, "%s: the harness compiled (%s)"
                  % (label, (out or "").strip().splitlines()[-1:]))
            return
        if expect_pass:
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "%s behaves as documented" % label)
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_DRIVER_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_DRIVER_CHECKS))
        else:
            check(ran.returncode != 0, "the check still fails when %s" % label)
            if ran.returncode == 0:
                print((out or "").strip().splitlines()[-3:])


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    impl = read(LIFECYCLE_M)
    header = read(LIFECYCLE_H)
    print("-- what a driver extension that does not exist yet may be trusted to have done --")

    cc, sdk = apple_toolchain.clang_and_sdk("driver lifecycle")
    run_rules("the shipping lifecycle", rules, cc, sdk, expect_pass=True)

    check("NSLog(" not in impl and "printf(" not in impl,
          "the lifecycle has no path to the log of its own")
    for forbidden in ("NSDate", "CACurrentMediaTime", "clock_gettime", "gettimeofday",
                      "sysctl", "task_info", "NSUserDefaults", "NSHomeDirectory"):
        check(forbidden not in impl + header,
              "the lifecycle never reads %s: a timeout arrives as an event or it is not tested"
              % forbidden)
    check(re.findall(r"#import\s*<(IOKit|DriverKit)", impl + header) == [],
          "nothing imports a driver bus yet: stage 3 is still the logic around the wall, not the wall")
    check("OSSystemExtension" not in impl + header,
          "no system-extension API is called from here, so no signing identity is implied")
    check("product" not in impl.lower() and "serialNumber" not in impl,
          "a device is named by digest here, the way stage 1 named it")

    run_rules("an install that timed out is still called installing",
              mutated(rules, "the install fallback",
                      "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseNotInstalled\n"
                      "                                     stop:MLDriverLifecycleStopInstallUnanswered",
                      "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseInstalling\n"
                      "                                     stop:MLDriverLifecycleStopInstallUnanswered"),
              cc, sdk)
    run_rules("a crash is not counted",
              mutated(rules, "the crash tally",
                      "    const NSInteger seen = self.crashesObserved + 1;",
                      "    const NSInteger seen = self.crashesObserved;"),
              cc, sdk)
    run_rules("a crash hands its device straight back",
              mutated(rules, "the orphaned lease",
                      "            leases[token] = @(MLDeviceLeaseStateOrphaned);",
                      "            leases[token] = @(MLDeviceLeaseStateNone);"),
              cc, sdk)
    run_rules("a replugged device inherits the lease it had last time",
              mutated(rules, "the replug reset",
                      "    leases[device.deviceToken] = @(MLDeviceLeaseStateNone);\n"
                      "    noticed->_leases = [leases copy];",
                      "    if (leases[device.deviceToken] == nil) {\n"
                      "        leases[device.deviceToken] = @(MLDeviceLeaseStateNone);\n"
                      "    }\n"
                      "    noticed->_leases = [leases copy];"),
              cc, sdk)
    run_rules("a device can be taken while no extension is loaded",
              mutated(rules, "the lease gate",
                      "- (instancetype)lifecycleByLeasingDevice:(MLManagedDevice *)device {\n"
                      "    if (self.phase != MLDriverExtensionPhaseActive) {\n"
                      "        return [self lifecycleByRefusing];\n"
                      "    }",
                      "- (instancetype)lifecycleByLeasingDevice:(MLManagedDevice *)device {\n"
                      "    if (self.phase == MLDriverExtensionPhaseHeldBack) {\n"
                      "        return [self lifecycleByRefusing];\n"
                      "    }"),
              cc, sdk)
    run_rules("an unanswered removal is reported as a completed one",
              mutated(rules, "the removal timeout",
                      "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseRemoving\n"
                      "                                     stop:MLDriverLifecycleStopRemovalUnanswered",
                      "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseNotInstalled\n"
                      "                                     stop:MLDriverLifecycleStopRemovalUnanswered"),
              cc, sdk)
    run_rules("a lease alone makes a device usable",
              mutated(rules, "the two-question check",
                      "    return [self mayHandOverDevices] &&\n"
                      "           self.leases[deviceToken] != nil &&",
                      "    return self.leases[deviceToken] != nil &&"),
              cc, sdk)
    run_rules("held back can be reopened by asking for an install",
              mutated(rules, "the held-back gate",
                      "- (instancetype)lifecycleByRequestingInstall {\n"
                      "    if (self.phase != MLDriverExtensionPhaseNotInstalled) {",
                      "- (instancetype)lifecycleByRequestingInstall {\n"
                      "    if (self.phase != MLDriverExtensionPhaseNotInstalled &&\n"
                      "        self.phase != MLDriverExtensionPhaseHeldBack) {"),
              cc, sdk)
    run_rules("a declined player is asked again anyway",
              mutated(rules, "the decline sticks",
                      "    return self.phase == MLDriverExtensionPhaseNotInstalled &&\n"
                      "           self.stop != MLDriverLifecycleStopUserDeclined;",
                      "    return self.phase == MLDriverExtensionPhaseNotInstalled;"),
              cc, sdk)
    run_rules("an uninstall leaves the leases behind",
              mutated(rules, "the clean removal",
                      "    removed->_leases = @{};",
                      "    removed->_leases = [self.leases copy];"),
              cc, sdk)

    print("%d driver-lifecycle failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
