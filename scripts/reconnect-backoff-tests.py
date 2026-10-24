#!/usr/bin/env python3
"""P2-2 reconnect backoff: gate for the state machine and its wiring.

What this gate refuses to accept:

  * a second reconnect executor. The reconnector decides *whether* and *when*;
    the teardown/relaunch still goes through attemptReconnectWithReason:, which
    already releases HID state, preserves the window mode, bumps the stream
    generation and suppresses transient warnings. A parallel path drifts.
  * a backoff budget that is refunded by the retry itself. Every retry calls
    prepareForStreaming, so a reset there pins every attempt at the first delay
    and the attempt ceiling is never reached.
  * a timer in the default runloop mode: the stream window lives in a fullscreen
    space, where a default-mode timer stops during menu tracking.
  * an unlocalised countdown, and a countdown that the connect watchdog can
    override with its own reconnect behind the budget's back.

Defects are planted by rewriting the file and re-running this gate in a child
process, so the mutation battery tests the real assertions. The child sees
MLR_GATE_NESTED and only runs the plain assertions.
"""
import os
import re
import subprocess
import sys

NESTED = os.environ.get('MLR_GATE_NESTED') == '1'

ROOT = "."
STRICT_TEST = "--self-test" in sys.argv
for arg in sys.argv[1:]:
    if arg != "--self-test" and os.path.isdir(arg):
        ROOT = arg

REC_H = "Limelight/macOS/Helpers/MLStreamReconnector.h"
REC_M = "Limelight/macOS/Helpers/MLStreamReconnector.m"
SVC = "Limelight/macOS/ViewControllers/StreamViewController.m"
INT = "Limelight/macOS/ViewControllers/StreamViewController_Internal.h"
MENU = "Limelight/macOS/ViewControllers/StreamViewController+MenuUI.m"
PBX = "Moonlight.xcodeproj/project.pbxproj"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

COUNTDOWN_KEY = '"Reconnecting… (%ld of %ld)"'

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def method_body(source, signature):
    """Body of the LAST method with this signature.

    StreamViewController.m opens with a scoped callback forwarder that declares
    the same selectors and delegates them, so the first hit is a two-line shim;
    the behaviour under audit is always the implementation further down.
    """
    start = source.rfind(signature)
    if start < 0:
        return ""
    depth = None
    for index in range(start, len(source)):
        char = source[index]
        if char == '{':
            if depth is None:
                depth = 0
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return ""


def plant(rel, needle, replacement, label):
    """Rewrite one file, re-run this gate in a child, restore, report."""
    full = os.path.join(ROOT, rel)
    with open(full, encoding="utf-8") as handle:
        original = handle.read()
    if needle not in original:
        check(False, "planted defect %s: needle not found in %s"
                    % (label, rel.split("/")[-1]))
        return
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(original.replace(needle, replacement, 1))
    try:
        env = dict(os.environ, MLR_GATE_NESTED="1")
        result = subprocess.run([sys.executable, os.path.abspath(__file__), ROOT],
                                capture_output=True, text=True, env=env)
        caught = result.returncode != 0
        print("%-4s defect: %s" % ("ok" if caught else "FAIL", label))
        if not caught:
            failures.append("planted defect escaped: %s" % label)
    finally:
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(original)


def main():
    header = read(REC_H)
    impl = read(REC_M)
    svc = read(SVC)
    internal = read(INT)
    menu = read(MENU)
    pbx = read(PBX)
    flat = re.sub(r"\s+", " ", header)

    # --- 1. the state machine is a decision-maker, nothing else --------------
    check("@interface MLStreamReconnector : NSObject" in header,
          "the backoff lives in its own class")
    for selector in ("requestReconnectFromTrigger:", "cancelWithReason:",
                     "resetForNextAttemptWithReason:",
                     "markHostConfirmedGoneWithReason:", "recordSuccess",
                     "requestImmediateReconnectFromMenuWithReason:"):
        check(selector in flat, "public surface exposes %s" % selector)
    check("@property (nonatomic) NSUInteger maxAttempts" in header,
          "the attempt ceiling is configurable (default 3)")
    check("@property (nonatomic, copy) NSArray<NSNumber *> *backoffSeconds" in header,
          "the backoff sequence is configurable (default 1s/3s/9s)")
    check("_maxAttempts = 3" in impl, "the default ceiling is three attempts")
    check("_backoffSeconds = @[@1, @3, @9]" in impl,
          "the default backoff is 1s then 3s then 9s")
    check("_startupGraceMs = 30000" in impl,
          "the start-up grace window is 30 seconds")
    # Purity is about imports: the comments name the classes it refuses to
    # reach for, and that is exactly the point worth reading.
    imports = [line for line in (header + impl).splitlines()
               if line.startswith("#import") or line.startswith("#include")]
    for forbidden in ("AppKit", "HIDSupport", "StreamManager", "StreamViewController",
                      "Connection"):
        check(not any(forbidden in line for line in imports),
              "the state machine imports nothing but Foundation, so a timer bug "
                "cannot be reasoned about only inside the stream controller (%s)"
                % forbidden)

    # --- 2. the timer must survive a fullscreen space ------------------------
    check("[NSTimer timerWithTimeInterval:delay" in impl,
          "the countdown uses a manually scheduled timer, not the convenience "
          "API that pins it to the default runloop mode")
    check("forMode:NSRunLoopCommonModes" in impl,
          "the countdown runs in the common modes, so a fullscreen space and "
          "menu tracking do not freeze it")

    # --- 2b. a countdown that is already running absorbs the next trigger ----
    request = method_body(impl, "- (BOOL)requestReconnectFromTrigger:")
    check("if (self.hostConfirmedGone) {\n        return NO;" in request,
          "a host confirmed unreachable ends reconnecting instead of burning the "
            "budget on a machine that is not there")
    coalesce = re.search(r"if \(self\.scheduledTimer\) \{\n(.*?)return YES;", request, re.S)
    check(bool(coalesce),
          "a trigger arriving while a countdown is pending takes the coalesce "
            "branch, so flapping links cannot stack parallel timers")
    coalesce_body = coalesce.group(1) if coalesce else ""
    check("attemptCount" not in coalesce_body,
          "the coalesce branch spends no second attempt")
    check("self.pendingTrigger = trigger" in coalesce_body and "self.pendingReason = reason" in coalesce_body,
          "the coalesce keeps the latest trigger and reason, so the log names the "
            "condition that is still true")

    # --- 3. the budget is spent, not refunded by the retry ------------------
    fired = method_body(impl, "- (void)timerFired:")
    check("if (begin) {\n        begin(firedTrigger, firedAttempt, firedReason" in fired,
          "when the countdown expires somebody is actually told to reconnect")
    check("self.attemptCount = 0" not in fired,
          "firing an attempt keeps the budget spent, so the next wait grows "
            "instead of returning to one second")
    check("self.attemptCount = 0" in method_body(impl, "- (void)recordSuccess"),
          "a connection that actually started returns the budget")
    check("self.attemptCount = 0" in method_body(impl, "- (void)cancelWithReason:"),
          "a user-initiated stop returns the budget")
    reset = method_body(impl, "- (void)resetForNextAttemptWithReason:")
    check("self.attemptCount = 0" not in reset and "[self invalidateTimer]" in reset,
          "a new stream generation clears the countdown but not the budget, "
            "because every retry passes through prepareForStreaming")
    check("[self.reconnector resetForNextAttemptWithReason:@\"new-stream-generation\"]" in svc,
          "prepareForStreaming releases the countdown without refunding the budget")
    check("if (self.attemptCount >= self.maxAttempts)" in impl,
          "the ceiling is checked before another attempt is scheduled")
    grace = re.search(r"isStall && startupElapsedMs < self\.startupGraceMs", impl)
    check(bool(grace),
          "a stall inside the start-up grace window spends no budget -- a cold "
            "start is not a lost connection")

    # --- 4. one executor: the retry runs through the existing manual path ----
    schedule = method_body(svc, "- (BOOL)scheduleBackoffReconnectWithTrigger:")
    check("beginReconnectNow" in schedule,
          "the scheduled attempt is handed back to the stream controller")
    check("attemptReconnectWithReason:" in schedule,
          "the scheduled retry runs on the one executor that already releases "
            "HID state and preserves the window mode")
    check("[strongSelf attemptReconnectWithReason:fireReason ?: @\"backoff\"]" in schedule,
          "the retry keeps the trigger's own reason so the log names the condition")
    check("[self.reconnector requestReconnectFromTrigger:trigger" in schedule,
          "the gate asks the state machine rather than reconnecting inline")
    check("strongSelf.shouldAttemptReconnect && !strongSelf.disconnectWasUserInitiated" in schedule,
          "the backoff respects the same two gates as the manual path, so a user "
            "stop cannot be resurrected by a timer")
    check("self.connectWatchdogToken += 1" in schedule,
          "the connect watchdog is retired for the length of the countdown, so "
            "it cannot start a reconnect that bypasses the budget")
    check("scheduleBackoffReconnectWithTrigger:(MLReconnectTrigger)trigger" in internal,
          "the shared entry point is declared for the categories to reach")

    # --- 5. triggers: both real ones route through the gate, and only the ----
    #         ones that mean "host is up, link is broken"
    terminated = method_body(svc, "- (void)connectionTerminated:")
    check("[self scheduleBackoffReconnectWithTrigger:MLReconnectTriggerConnectionTerminated" in terminated,
          "a lost connection asks the state machine before closing the window")
    check("if ([self scheduleBackoffReconnectWithTrigger:MLReconnectTriggerConnectionTerminated"
          in terminated,
          "a scheduled attempt keeps the window open instead of closing and reopening it")
    stage = method_body(svc, "- (void)stageFailed:")
    check("[self scheduleBackoffReconnectWithTrigger:MLReconnectTriggerStageFailed" in stage,
          "a stage failure before any connection asks the state machine")
    check("BOOL hadEstablishedConnection = (self.streamHealthConnectionStartedMs != 0)" in stage,
          "the gate reads whether a connection ever existed BEFORE the handler "
            "zeroes the marker -- reading the zeroed value would retry nothing")
    check("if (!hadEstablishedConnection &&" in stage,
          "a stage failure after a real connection still closes: that is protocol "
            "drift, not a flaky link")
    launch = method_body(svc, "- (void)launchFailed:")
    check("scheduleBackoffReconnectWithTrigger" not in launch,
          "launchFailed still closes -- a host application that will not start is "
            "not a network problem a retry can fix")
    started = method_body(svc, "- (void)connectionStarted")
    check("[self.reconnector recordSuccess]" in started,
          "a connection that reached the video stage returns the budget")
    check("prepareForStreaming" in svc and "resetForNextAttemptWithReason" in svc,
          "the generation boundary is wired")

    # --- 6. a user retry burns no budget ------------------------------------
    menu_body = method_body(menu, "- (void)reconnectFromMenu:")
    check("requestImmediateReconnectFromMenuWithReason:@\"menu\"" in menu_body,
          "the menu retry goes through the state machine and spends no attempt")
    check("attemptReconnectWithReason:" in menu_body,
          "the menu retry lands on the same executor as an automatic one")
    check("self.hostConfirmedGone = NO" in
          method_body(impl, "- (BOOL)requestImmediateReconnectFromMenuWithReason:"),
          "an explicit user retry clears a host-gone verdict: the user is allowed "
            "to disagree with the diagnostic")

    # --- 7. the countdown is a localised sentence, not a literal -------------
    en = read(EN)
    zh = read(ZH)
    check(COUNTDOWN_KEY in en and "of %2$ld" in en,
          "the countdown sentence is in the English table with positional arguments")
    check(COUNTDOWN_KEY in zh and "%1$ld" in zh,
          "the countdown sentence is in the Chinese table with positional arguments")
    check("Reconnecting… (%ld of %ld)" in svc,
          "the stream controller asks for that sentence instead of embedding text")
    check(not re.search(r"@\"正在重连", svc),
          "no hardcoded Chinese sentence in the stream controller")

    # --- 8. the new pair is really in the build ------------------------------
    check("macOS/Helpers/MLStreamReconnector.m" in pbx,
          "the state machine is listed in the file-system-synchronised group, "
            "so a clean checkout builds it")


def mutations():
    """Each case rewrites a real line and expects the assertions above to fail."""
    return [
        # The needle has to name the comment too: the same one-line guard also
        # opens the timer teardown helper, and replacing that one changes nothing.
        (REC_M, "if (self.scheduledTimer) {\n        // Already counting down",
         "if (NO && self.scheduledTimer) {\n        // Already counting down",
         "the coalesce branch is gone: a second trigger starts a parallel timer"),
        (REC_M, "if (self.hostConfirmedGone) {\n        return NO;",
         "if (0 && self.hostConfirmedGone) {\n        return NO;",
         "a host that is confirmed gone would keep being retried"),
        (REC_M, "if (self.attemptCount >= self.maxAttempts) {",
         "if (NO && self.attemptCount >= self.maxAttempts) {",
         "the attempt ceiling stopped applying"),
        (REC_M, "[NSTimer timerWithTimeInterval:delay",
         "[NSTimer scheduledTimerWithTimeInterval:delay",
         "the countdown moved back to the default runloop mode"),
        (REC_M, "    self.attemptCount = 0;\n    self.hostConfirmedGone = NO;\n}\n\n- (void)resetForNextAttemptWithReason:",
         "}\n\n- (void)resetForNextAttemptWithReason:",
         "recordSuccess stopped returning the budget"),
        (REC_M, "- (void)resetForNextAttemptWithReason:(NSString *)reason {\n    (void)reason;\n    NSAssert([NSThread isMainThread], @\"MLStreamReconnector must run on main thread\");\n    [self invalidateTimer];",
         "- (void)resetForNextAttemptWithReason:(NSString *)reason {\n    (void)reason;\n    NSAssert([NSThread isMainThread], @\"MLStreamReconnector must run on main thread\");\n    [self invalidateTimer];\n    self.attemptCount = 0;",
         "a new stream generation refunded the budget, so every attempt waits one second"),
        (REC_M, "    if (begin) {\n        begin(firedTrigger, firedAttempt, firedReason ?: @\"\");",
         "    if (NO) {\n        begin(firedTrigger, firedAttempt, firedReason ?: @\"\");",
         "the countdown expires but nobody is told to reconnect"),
        (SVC, "[strongSelf attemptReconnectWithReason:fireReason ?: @\"backoff\"];",
         "/* PLANTED: a second executor appeared instead */",
         "the retry stopped using the one executor"),
        (SVC, "return strongSelf.shouldAttemptReconnect && !strongSelf.disconnectWasUserInitiated;",
         "return YES;",
         "the backoff ignored the manual path's gates"),
        (SVC, "self.connectWatchdogToken += 1;\n        NSString *msg = [NSString stringWithFormat:MLString(@\"Reconnecting… (%ld of %ld)\", nil),",
         "NSString *msg = [NSString stringWithFormat:MLString(@\"Reconnecting… (%ld of %ld)\", nil),",
         "the connect watchdog stayed armed behind the countdown"),
        (SVC, "if (!hadEstablishedConnection &&", "if (!self.streamHealthConnectionStartedMs &&",
         "the stage-failed gate reads the marker after the handler zeroed it"),
        (SVC, "if ([self scheduleBackoffReconnectWithTrigger:MLReconnectTriggerConnectionTerminated",
         "if (NO && [self scheduleBackoffReconnectWithTrigger:MLReconnectTriggerConnectionTerminated",
         "a lost connection stopped asking the state machine"),
        (MENU, "[self.reconnector requestImmediateReconnectFromMenuWithReason:@\"menu\"",
         "[self attemptReconnectWithReason:@\"menu\"]; (void)^(MLReconnectTrigger t, NSUInteger a, NSString *r){}; (void)^{ return (void)0; };"
         " // PLANTED: menu bypasses the state machine\n    [self legacyReconnectNoop",
         "the menu retry stopped going through the state machine"),
        (SVC, "MLString(@\"Reconnecting… (%ld of %ld)\", nil)", "@\"正在重连（%ld / %ld）…\"",
         "the countdown became a hardcoded Chinese literal"),
    ]


if __name__ == "__main__":
    main()
    if STRICT_TEST and not NESTED:
        print("")
        print("== planted-defect battery ==")
        if failures:
            # A positive assertion already went red, so a planted defect "being
            # caught" would prove nothing.
            print("skipped: the positive assertions must pass first")
            sys.exit(1)
        for rel, needle, replacement, label in mutations():
            plant(rel, needle, replacement, label)
    print("")
    print("P2-2 reconnect-backoff gate: %d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)
