#!/usr/bin/env python3
"""Prove that Apple's activation callbacks cannot be read as more than they say.

Stage 3 of docs/usb-redirection-design.md is blocked on a Developer ID identity and a
notarisation pipeline (2.3), and staging/driver-extension/MLDriverExtensionActivation.h says why
the code sits outside `Limelight/`: that directory is a synchronised folder group, so a file
dropped into it is compiled into the product whether or not anybody wired it. What can be finished
today is the reading of the callbacks, and that is what this gate drives.

Four claims hold the table together, and each has a planted defect:

  a scheduled load is not a load. `didFinishWithResult:` arrives with two results, and
    `WillCompleteAfterReboot` means registered-and-not-running. Recording an activation there hands
    a device to a driver that starts on a boot this machine has not taken;
  a dialog is not a driver. `requestNeedsUserApproval:` says somebody is being asked. It is neither
    an approval, a decline, nor an activation, and the lifecycle keeps its `installing` phase
    because the request is genuinely still outstanding;
  a signing refusal is not a player who pressed a button. Half of the error codes are about this
    build -- no entitlement, a signature it will not accept, a bundle it cannot find -- and reading
    them as `user-declined` blames a person who never saw a dialog for a certificate, then lets the
    retry path ask again for a result that cannot change;
  a message nobody recognised teaches nothing. A code outside the named list, an error from another
    domain, a failure that carried no error, and a callback value this switch does not carry all
    leave the lifecycle where it was. A check that reached for the nearest case would report a
    driver state that nothing observed.

The three lines of Apple's API that no gate can execute sit behind `MLSystemExtensionRequesting`,
so the sequence is driven by a fake that counts submissions. That seam is asserted too: a request
the lifecycle already refused must never reach the framework at all.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_ACTIVATION_CHECKS = 24
STAGED_H = "staging/driver-extension/MLDriverExtensionActivation.h"
STAGED_M = "staging/driver-extension/MLDriverExtensionActivation.m"
LIFECYCLE_H = "Limelight/Stream/DriverLifecycle.h"
LIFECYCLE_M = "Limelight/Stream/DriverLifecycle.m"
PROJECT = "Moonlight.xcodeproj/project.pbxproj"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def sdk_path():
    ran = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True)
    return ran.stdout.strip() if ran.returncode == 0 else ""


def sdk_extension_header():
    candidate = os.path.join(sdk_path(), "System/Library/Frameworks",
                             "SystemExtensions.framework/Versions/A/Headers/SystemExtensions.h")
    return candidate if os.path.exists(candidate) else None


#
#  The driver. Every assertion below is compiled with the staged sources, so a change to the
#  table is a compile error or a red run rather than a stale comment.
#

DRIVER = r'''
#import <Foundation/Foundation.h>
#import "MLDriverExtensionActivation.h"

static int checks_run = 0;
static int failures = 0;

static void check_case(BOOL ok, const char *message) {
    checks_run++;
    if (!ok) {
        failures++;
        printf("FAIL %s\n", message);
    }
}

@interface FakePort : NSObject <MLSystemExtensionRequesting>
@property(nonatomic, readonly) NSUInteger submissions;
@property(nonatomic, readonly, copy) NSString *lastIdentifier;
@property(nonatomic, readonly) BOOL delegateWasSet;
@property(nonatomic, readonly) BOOL queueWasGiven;
@end

@implementation FakePort
- (void)submitActivationForExtension:(NSString *)identifier
                             delegate:(id)delegate
                                queue:(dispatch_queue_t)queue {
    _submissions++;
    _lastIdentifier = [identifier copy];
    _delegateWasSet = delegate != nil;
    _queueWasGiven = queue != nil;
}
@end

static MLDriverLifecycle *untouched(void) {
    return [MLDriverLifecycle untouchedLifecycleWithCrashBudget:3];
}

static MLDriverLifecycle *requested(void) {
    return [untouched() lifecycleByRequestingInstall];
}

static MLDriverLifecycle *active(void) {
    return [[requested() lifecycleByRecordingActivation] lifecycleByRecordingActivation];
}

static OSSystemExtensionRequest *standInRequest(void) {
    // Neither callback under test messages the request, and nothing here pretends otherwise: an
    // object that answers none of an activation request's methods is handed in, so a porter that
    // started messaging it would die on an unrecognized selector. That death is the assertion.
    return (OSSystemExtensionRequest *)[[NSObject alloc] init];
}

static OSSystemExtensionProperties *standInProperties(void) {
    return (OSSystemExtensionProperties *)[[NSObject alloc] init];
}

static NSError *ourError(NSInteger code) {
    return [NSError errorWithDomain:OSSystemExtensionErrorDomain code:code userInfo:nil];
}

static MLDriverExtensionOutcome *fail(MLDriverLifecycle *lifecycle, NSInteger code) {
    return MLDriverExtensionApplyCallback(lifecycle, MLDriverExtensionCallbackFailed, ourError(code));
}

@interface Driver : NSObject
@end

@implementation Driver
+ (void)run {
    @autoreleasepool {
        // 1. The one callback that means a running extension.
        MLDriverExtensionOutcome *completed =
            MLDriverExtensionApplyCallback(requested(), MLDriverExtensionCallbackCompleted, nil);
        check_case(completed.lifecycle.phase == MLDriverExtensionPhaseActive,
                   "Completed is the callback that activates");
        check_case([completed.reasonName isEqualToString:@"activated"],
                   "the activation reason is the one spelling");
        check_case(!completed.playerActionRequired,
                   "nothing is asked of the player once the extension is running");

        // 2. Registered, scheduled, and not running.
        MLDriverExtensionOutcome *reboot =
            MLDriverExtensionApplyCallback(requested(),
                                           MLDriverExtensionCallbackCompletedAfterReboot, nil);
        check_case(reboot.lifecycle.phase != MLDriverExtensionPhaseActive,
                   "a load that waits for a reboot does not become active");
        check_case(reboot.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "the request stays outstanding until the reboot answers it");
        check_case([reboot.reasonName isEqualToString:@"active-after-reboot"],
                   "the reboot answer says which reboot state it is in");
        check_case(reboot.playerActionRequired, "rebooting is the player's to do");

        // 3. A dialog opened. Nothing was learned about the extension.
        MLDriverExtensionOutcome *approval =
            MLDriverExtensionApplyCallback(requested(),
                                           MLDriverExtensionCallbackNeedsUserApproval, nil);
        check_case(approval.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "being asked for approval is not an approval");
        check_case([approval.reasonName isEqualToString:@"awaiting-user-approval"],
                   "the approval state has its own name");
        check_case(approval.playerActionRequired, "approving is the player's to do");

        // 4. A replacement question is a decision, not a load.
        MLDriverExtensionOutcome *replacement =
            MLDriverExtensionApplyCallback(requested(),
                                           MLDriverExtensionCallbackReplacementRequested, nil);
        check_case(replacement.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "answering the replacement question loads nothing");
        check_case([replacement.reasonName isEqualToString:@"replacement-decision"],
                   "the replacement answer is recorded as a decision");
        check_case(!replacement.playerActionRequired, "nobody is blamed for a version question");

        // 5. A failure with nothing to read, and an error from somebody else's domain.
        MLDriverExtensionOutcome *empty =
            MLDriverExtensionApplyCallback(requested(), MLDriverExtensionCallbackFailed, nil);
        check_case([empty.reasonName isEqualToString:@"failed-without-error"],
                   "a failure with no error invents no reason");
        check_case(empty.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "a failure with no error changes nothing");
        NSError *foreign = [NSError errorWithDomain:NSCocoaErrorDomain
                                               code:8 userInfo:nil];
        MLDriverExtensionOutcome *not_ours =
            MLDriverExtensionApplyCallback(requested(), MLDriverExtensionCallbackFailed, foreign);
        check_case([not_ours.reasonName isEqualToString:@"failed-foreign-error"],
                   "an error from another domain is not read against our table of codes");
        check_case(not_ours.lifecycle.phase != MLDriverExtensionPhaseHeldBack,
                   "another domain's code cannot hold this build back");

        // 6. The build class: eight codes, eight names, one phase, and no player to blame.
        NSArray<NSNumber *> *build_codes = @[ @2, @3, @4, @5, @6, @7, @8, @9 ];
        NSMutableSet *build_reasons = [NSMutableSet set];
        BOOL all_held_back = YES;
        BOOL any_blamed_player = NO;
        for (NSNumber *code in build_codes) {
            MLDriverExtensionOutcome *outcome = fail(requested(), code.integerValue);
            all_held_back = all_held_back &&
                outcome.lifecycle.phase == MLDriverExtensionPhaseHeldBack &&
                outcome.lifecycle.stop == MLDriverLifecycleStopBuildCannotLoadExtension;
            any_blamed_player = any_blamed_player || outcome.playerActionRequired;
            [build_reasons addObject:outcome.reasonName];
        }
        check_case(all_held_back,
                   "every build-class refusal holds this session back rather than retrying");
        check_case(build_reasons.count == build_codes.count,
                   "each build-class code keeps its own name instead of merging into one");
        check_case(!any_blamed_player,
                   "a signing gap says nothing about what the player should do");
        check_case([[MLDriverLifecycle untouchedLifecycleWithCrashBudget:3]
                        lifecycleByRequestingInstall].phase == MLDriverExtensionPhaseInstalling,
                   "the refusal is recorded against a session that did ask");

        // 7. The refusal must not overwrite a driver that is already running.
        MLDriverExtensionOutcome *on_active = fail(active(), 2);
        check_case(on_active.lifecycle.phase == MLDriverExtensionPhaseActive,
                   "a refusal cannot unload an extension that is running");

        // 8. The consent class: nothing installed, and the player can finish it.
        MLDriverExtensionOutcome *policy = fail(requested(), 10);
        check_case(policy.lifecycle.phase == MLDriverExtensionPhaseNotInstalled,
                   "a policy refusal leaves nothing installed");
        check_case(policy.lifecycle.stop == MLDriverLifecycleStopUserDeclined,
                   "a policy refusal is the player's to finish");
        check_case(policy.playerActionRequired, "the consent class names a next step");
        MLDriverExtensionOutcome *authorization = fail(requested(), 13);
        check_case([authorization.reasonName isEqualToString:@"authorization-required"],
                   "an authorization request is not read as a signing gap");

        // 9. The request class: the system said this request stopped mattering.
        MLDriverExtensionOutcome *canceled = fail(requested(), 11);
        check_case([canceled.reasonName isEqualToString:@"request-canceled"],
                   "a canceled request keeps its own name");
        check_case(canceled.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "a canceled request is not evidence that nothing is installed");
        MLDriverExtensionOutcome *superseded = fail(requested(), 12);
        check_case([superseded.reasonName isEqualToString:@"request-superseded"],
                   "a superseded request is not somebody else's failure");

        // 10. Nothing recognised, nothing learned.
        MLDriverExtensionOutcome *unknown_code = fail(requested(), 4242);
        check_case([unknown_code.reasonName isEqualToString:@"unmapped-error"],
                   "a code this table does not name is reported as unmapped");
        check_case(unknown_code.lifecycle.phase != MLDriverExtensionPhaseActive,
                   "an unmapped code never activates an extension");
        MLDriverExtensionOutcome *unknown_callback = MLDriverExtensionApplyCallback(
            requested(), (MLDriverExtensionCallback)4242, nil);
        check_case([unknown_callback.reasonName isEqualToString:@"unmapped-callback"],
                   "a callback value this switch does not carry is reported as unmapped");
        check_case(unknown_callback.lifecycle.phase != MLDriverExtensionPhaseActive,
                   "a callback nobody read never activates an extension");
        check_case(![MLDriverExtensionCallbackName((MLDriverExtensionCallback)4242)
                        isEqualToString:@"completed"],
                   "the callback name table answers with the same honesty as the mapping");

        // 11. `mayAskAgain` is the lifecycle's question, not the table's opinion.
        MLDriverExtensionOutcome *idle =
            MLDriverExtensionApplyCallback(untouched(),
                                           MLDriverExtensionCallbackNeedsUserApproval, nil);
        check_case(idle.mayAskAgain == untouched().mayAttemptInstall,
                   "asking again is read out of the lifecycle that came back");
        check_case(!MLDriverExtensionApplyCallback(active(), MLDriverExtensionCallbackCompleted,
                                                   nil).mayAskAgain,
                   "a session whose extension is running has nothing to ask again for");
        check_case(MLDriverExtensionApplyCallback(untouched(), MLDriverExtensionCallbackCompleted,
                                                  nil).lifecycle.phase
                       != MLDriverExtensionPhaseActive,
                   "an activation nobody asked for teaches the lifecycle nothing it did not ask");

        // 12. The controller: one submission per allowed request, and none when refused.
        FakePort *port = [[FakePort alloc] init];
        MLDriverExtensionActivationController *controller =
            [[MLDriverExtensionActivationController alloc] initWithExtensionIdentifier:
                                          @"std.skyhua.MoonlightMac2.StagingExtension"
                                                                           crashBudget:3
                                                                                    port:port];
        MLDriverExtensionOutcome *asked = [controller askForActivation];
        check_case(port.submissions == 1, "the first allowed request reaches the port once");
        check_case([port.lastIdentifier
                        isEqualToString:@"std.skyhua.MoonlightMac2.StagingExtension"],
                   "the identifier reaches the port unchanged");
        check_case(port.delegateWasSet && port.queueWasGiven,
                   "a request submitted without a delegate or a queue would answer to nobody");
        check_case(controller.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "asking puts the lifecycle into the phase that says it asked");
        check_case([asked.reasonName isEqualToString:@"awaiting-user-approval"],
                   "the first answer a caller gets is that somebody is being asked");

        MLDriverExtensionOutcome *second = [controller askForActivation];
        check_case(port.submissions == 1, "a second request while one is outstanding never leaves");
        check_case([second.reasonName isEqualToString:@"attempt-refused-by-lifecycle"],
                   "the refusal says who refused it");

        FakePort *held_port = [[FakePort alloc] init];
        MLDriverExtensionActivationController *held =
            [[MLDriverExtensionActivationController alloc]
                initWithExtensionIdentifier:@"std.skyhua.MoonlightMac2.StagingExtension"
                           startingLifecycle:fail(requested(), 2).lifecycle
                                        port:held_port];
        [held askForActivation];
        check_case(held_port.submissions == 0,
                   "a session held back by a signing gap does not ask Apple again");

        // 13. The delegate callbacks themselves, driven with the request object AppKit owns.
        FakePort *third_port = [[FakePort alloc] init];
        MLDriverExtensionActivationController *listener =
            [[MLDriverExtensionActivationController alloc] initWithExtensionIdentifier:
                                          @"std.skyhua.MoonlightMac2.StagingExtension"
                                                                           crashBudget:3
                                                                                    port:third_port];
        [listener askForActivation];
        [listener requestNeedsUserApproval:standInRequest()];
        check_case(listener.lifecycle.phase == MLDriverExtensionPhaseInstalling,
                   "the approval callback keeps the phase it had");
        check_case([listener.lastReasonName isEqualToString:@"awaiting-user-approval"],
                   "the callback reaches the same table the free function holds");
        [listener request:standInRequest()
            didFinishWithResult:OSSystemExtensionRequestWillCompleteAfterReboot];
        check_case(listener.lifecycle.phase != MLDriverExtensionPhaseActive,
                   "the reboot result arrives as the reboot case through the delegate too");
        [listener request:standInRequest()
            didFinishWithResult:OSSystemExtensionRequestCompleted];
        check_case(listener.lifecycle.phase == MLDriverExtensionPhaseActive,
                   "the completed result activates through the delegate");
        check_case([listener request:standInRequest()
              actionForReplacingExtension:standInProperties()
                            withExtension:standInProperties()] ==
                       OSSystemExtensionReplacementActionReplace,
                   "replacing our own older extension is what the question asks for");
        check_case([listener.lastReasonName isEqualToString:@"replacement-decision"],
                   "the replacement answer is recorded and not read as a load");
        [listener request:standInRequest() didFailWithError:ourError(8)];
        check_case(listener.lifecycle.phase == MLDriverExtensionPhaseActive,
                   "a late failure cannot unload an extension the same session activated");

        // 14. The log line says the new stop in the same words the panel uses.
        NSString *line = fail(requested(), 2).lifecycle.auditLine;
        check_case([line rangeOfString:@"build-cannot-load-extension"].location != NSNotFound,
                   "the audit line names the signing refusal");
        check_case([line rangeOfString:@"StagingExtension"].location == NSNotFound,
                   "the audit line does not repeat the identifier it was handed");

        printf("%s (%d checks)\n", failures ? "RUN FAILED" : "RUN PASSED", checks_run);
        return;
    }
}
@end

int main(void) {
    [Driver run];
    return failures ? 1 : 0;
}
'''


def staged_sources(staged_m=None, lifecycle_m=None):
    """The staged pair plus the lifecycle it maps into, as one compile unit."""
    return {STAGED_H: read(STAGED_H),
            STAGED_M: staged_m if staged_m is not None else read(STAGED_M),
            LIFECYCLE_H: read(LIFECYCLE_H),
            LIFECYCLE_M: lifecycle_m if lifecycle_m is not None else read(LIFECYCLE_M)}


def compiled(sources, driver, cc, sdk):
    """Mirror the two directories so the staged header's relative import still resolves."""
    with tempfile.TemporaryDirectory() as work:
        for rel, text in sources.items():
            path = os.path.join(work, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(text)
        driver_path = os.path.join(work, "driver.m")
        open(driver_path, "w", encoding="utf-8").write(driver)
        binary = os.path.join(work, "driver")
        command = [cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-Wall", "-Werror",
                   "-F", os.path.join(sdk, "System/Library/Frameworks"),
                   "-I", os.path.join(work, "staging/driver-extension"),
                   driver_path,
                   os.path.join(work, STAGED_M),
                   os.path.join(work, LIFECYCLE_M),
                   "-framework", "Foundation",
                   "-framework", "SystemExtensions",
                   "-o", binary]
        built = subprocess.run(command, capture_output=True, text=True)
        if built.returncode != 0:
            return None, (built.stdout + built.stderr)[-1500:]
        ran = subprocess.run([binary], capture_output=True, text=True)
        return ran, (ran.stdout + ran.stderr)


def run_sources(label, sources, cc, sdk, expect_pass=False):
    ran, out = compiled(sources, DRIVER, cc, sdk)
    if ran is None:
        first_errors = [line for line in (out or "").splitlines() if " error:" in line][:3]
        check(False, "%s: the harness compiled (%s)"
              % (label, " | ".join(first_errors) or (out or "").strip()[-200:]))
        return
    if expect_pass:
        reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
        check(ran.returncode == 0, "%s behaves as documented" % label)
        count = int(reported.group(1)) if reported else -1
        check(count >= MIN_ACTIVATION_CHECKS,
              "the compiled run reports its own case list (%d checks, floor %d)"
              % (count, MIN_ACTIVATION_CHECKS))
    else:
        check(ran.returncode != 0, "the check still fails when %s" % label)
        if ran.returncode == 0:
            print((out or "").strip().splitlines()[-3:])


def mutate(text, label, before, after):
    check(before in text, "%s: the source it mutates is still there" % label)
    return text.replace(before, after, 1)


def shipping_shape(cc, sdk):
    staged = read(STAGED_H) + read(STAGED_M)
    check(os.path.isdir(os.path.join(ROOT, "staging")),
          "the staged half of stage 3 exists outside the app's source tree")
    for forbidden in ("NSDate", "CACurrentMediaTime", "clock_gettime", "gettimeofday",
                      "NSUserDefaults", "NSHomeDirectory"):
        check(forbidden not in staged,
              "the activation table reads no %s: a state machine with a clock cannot be replayed"
              % forbidden)
    check("NSLog(" not in staged and "printf(" not in staged,
          "the activation table has no path to the log of its own")
    imported = sorted(set(re.findall(r"#import\s*<([^>]+)>", staged)))
    check(set(imported) <= {"Foundation/Foundation.h", "SystemExtensions/SystemExtensions.h"},
          "the staged pair imports nothing but Foundation and SystemExtensions (%s)"
          % ", ".join(imported))
    check('#import "MLDriverExtensionActivation.h"' in read(STAGED_M),
          "the implementation imports the header it is checked against, so a declaration drift is "
          "a compile error rather than a difference nobody sees")
    check(re.findall(r"#import\s*<(IOKit|DriverKit)", staged) == [] and
          "OSBundleLibrary" not in staged,
          "nothing here names a driver bus: this is the reading of a refusal, not a driver")

    check(read(PROJECT).count("staging") == 0,
          "the project file does not reference staging/, so nothing in it reaches the product")
    check("membershipExceptions" in read(PROJECT) and
          "staging" not in read(PROJECT).split("membershipExceptions")[1][:4000],
          "the synchronised Limelight group has no staging entry to grow into the app")

    header = read(STAGED_H)
    check("UNLOCK(stage3)" in header,
          "the staged half announces itself as unfinished, the way the panel's placeholder does")
    unlock = header.rsplit("UNLOCK(stage3)", 1)[1]
    unlock_items = re.findall(r"^\s*//\s*(\d)\.", unlock.split("When all four land")[0], re.M)
    check(unlock_items == ["1", "2", "3", "4"],
          "the unlock block lists the four prerequisites a build has to clear, in order (%s)"
          % ",".join(unlock_items))

    # Naming a method Apple does not have is a build failure at worst and a runtime surprise at
    # best, so every system-extension identifier the staged source names is checked against the
    # header the build actually compiles against.
    header_path = sdk_extension_header()
    if header_path is None:
        print("skip  the SDK's SystemExtensions header was not found, so the name check below "
              "is not measured this run")
    else:
        declaration = open(header_path, encoding="utf-8").read()
        named = set(re.findall(r"\bOSSystem(?:Extension|Extensions)[A-Za-z]*", staged))
        missing = sorted(name for name in named if name not in declaration)
        check(not missing,
              "every system-extension name the staged source uses exists in the SDK header"
              if not missing else "the staged source names an API this SDK does not declare: "
              + ", ".join(missing))
        check("OSSystemExtensionErrorDomain" in named,
              "the check above has the domain constant in it, which is what makes a foreign "
              "error recognisable as one")

    check(len(re.findall(r"OSSystemExtensionManager", read(STAGED_M))) == 1,
          "exactly one line of the product's future talks to the extension manager")


def main():
    print("-- what Apple's activation callbacks may be read as saying --")
    cc, sdk = apple_toolchain.clang_and_sdk("driver extension activation")
    if not sdk:
        print("FAIL no SDK, so nothing here was compiled")
        print("%d driver-extension-activation failures" % (len(failures) + 1))
        return 1

    shipping_shape(cc, sdk)
    staged, lifecycle = read(STAGED_M), read(LIFECYCLE_M)
    run_sources("the shipped table", staged_sources(), cc, sdk, expect_pass=True)

    def with_staged(label, before, after):
        run_sources(label, staged_sources(mutate(staged, label, before, after)), cc, sdk)

    def with_lifecycle(label, before, after):
        run_sources(label, staged_sources(None, mutate(lifecycle, label, before, after)), cc, sdk)

    with_staged("a reboot becomes a running driver",
                "            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle\n"
                "                                                       reasonName:@\"active-after-reboot\"\n"
                "                                             playerActionRequired:YES];",
                "            return [MLDriverExtensionOutcome\n"
                "                        outcomeWithLifecycle:[lifecycle lifecycleByRecordingActivation]\n"
                "                                  reasonName:@\"active-after-reboot\"\n"
                "                        playerActionRequired:YES];")
    with_staged("an open dialog becomes an approval",
                "            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle\n"
                "                                                       reasonName:@\"awaiting-user-approval\"\n"
                "                                             playerActionRequired:YES];",
                "            return [MLDriverExtensionOutcome\n"
                "                        outcomeWithLifecycle:[lifecycle lifecycleByRecordingActivation]\n"
                "                                  reasonName:@\"activated\"\n"
                "                        playerActionRequired:NO];")
    with_staged("a signing gap becomes a player who declined",
                "[lifecycle lifecycleByRecordingBuildRefusal]",
                "[lifecycle lifecycleByRecordingUserDecline]")
    with_staged("a code nobody named becomes an activation",
                "            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle\n"
                "                                                       reasonName:reason\n"
                "                                             playerActionRequired:YES];\n"
                "        }\n",
                "            return [MLDriverExtensionOutcome\n"
                "                        outcomeWithLifecycle:[lifecycle lifecycleByRecordingActivation]\n"
                "                                  reasonName:reason\n"
                "                        playerActionRequired:YES];\n"
                "        }\n")
    with_staged("another domain's code is read as ours",
                "    *isOurDomain = [error.domain isEqualToString:OSSystemExtensionErrorDomain];",
                "    *isOurDomain = YES;")
    with_staged("a failure with no error is given a reason",
                '                                                           reasonName:@"failed-without-error"',
                '                                                           reasonName:@"authorization-required"')
    with_staged("asking again becomes the table's opinion",
                "    outcome->_mayAskAgain = lifecycle.mayAttemptInstall;",
                "    outcome->_mayAskAgain = YES;")
    with_staged("a refused request still reaches Apple",
                "    if (!before.mayAttemptInstall) {",
                "    if (NO) {")
    with_staged("a callback's transition is dropped on the floor",
                "    MLDriverExtensionOutcome *outcome =\n"
                "        MLDriverExtensionApplyCallback(self.lifecycle, callback, error);\n"
                "    self.lifecycle = outcome.lifecycle;",
                "    MLDriverExtensionOutcome *outcome =\n"
                "        MLDriverExtensionApplyCallback(self.lifecycle, callback, error);\n"
                "    (void)outcome;")
    with_staged("a callback nobody knows becomes the nearest one",
                "    return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle\n"
                "                                               reasonName:@\"unmapped-callback\"\n"
                "                                     playerActionRequired:YES];",
                "    return [MLDriverExtensionOutcome\n"
                "                outcomeWithLifecycle:[lifecycle lifecycleByRecordingActivation]\n"
                "                          reasonName:@\"activated\"\n"
                "                playerActionRequired:NO];")
    with_staged("a version question refuses its own new build",
                "    return OSSystemExtensionReplacementActionReplace;",
                "    return OSSystemExtensionReplacementActionCancel;")
    with_lifecycle("a refusal can unload a running extension",
                   "    if (self.phase != MLDriverExtensionPhaseNotInstalled &&\n"
                   "        self.phase != MLDriverExtensionPhaseInstalling) {\n"
                   "        return [self lifecycleByRefusing];\n"
                   "    }\n"
                   "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseHeldBack\n"
                   "                                     stop:MLDriverLifecycleStopBuildCannotLoadExtension",
                   "    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseHeldBack\n"
                   "                                     stop:MLDriverLifecycleStopBuildCannotLoadExtension")

    print("%d driver-extension-activation failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
