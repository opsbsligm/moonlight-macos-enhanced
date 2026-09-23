#!/usr/bin/env python3
"""Measure when a repeating timer is allowed to fire, and who it keeps alive while doing so.

Three shipped decisions rest on run loop behaviour no test in this repository had looked at:
the gamepad-as-mouse poll, the stats overlay, the Control Center pill and the diagnostics
timers all assume they keep firing through a stream. What they actually ask for differs --
five of them name the common modes, one of them used to be scheduled, which asks for a single
mode -- and the difference is invisible until somebody opens something.

Nothing here is argued from documentation. The program below registers four repeating timers
that differ only in the mode they were added to, runs the main run loop in each of the three
modes this app uses during a session, and counts what fired:

  a repeating timer fires only while the loop runs in a mode it was added to. In the same
    300ms in which a timer added to NSDefaultRunLoopMode fires, one added to
    NSModalPanelRunLoopMode fires 0 times -- and the reverse holds the other way round. Both
    directions are measured, so a zero is never read as "the timer is broken";
  whether NSRunLoopCommonModes really reaches those modes on a given host is reported as a
    counted number, and where it counts 0 the gate prints `not measured` rather than passing
    the claim. It counts 0 for real on a host where AppKit has not populated the set, and a
    green that means "nobody looked" is the defect this repository keeps coming back for;
  a repeating timer scheduled with target:self outlives its owner: the object was alive and
    still being polled 300ms after the last reference outside the timer was dropped. That is
    why a stop that lives only in that object's -dealloc is not a stop at all;
  -invalidate stops a repeating timer dead and immediately -- 0 ticks after it on every
    timer -- which is what makes "a stop on a path that can run" worth gating.

Two claims are deliberately absent. Nothing here reads the shipped files:
constraints-audit.py does that, and refuses a repeating timer that names one mode or that is
stopped only by a dealloc that cannot run. And nothing here says how often a player opens a
modal during a stream -- the app reaches a modal alert by name from the microphone permission
prompt and from the settings page's file picker, which is a fact about call sites, not a
measurement of players.
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

# The compiled program counts its own assertions. A count below the floor means a case stopped
# running, which is not a case that passed -- it is a case that is gone.
MIN_TIMER_CHECKS = 12

SOURCE = r'''
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

static int checks = 0;
#define CHECK(cond, note) do { checks++; if (!(cond)) printf("FAIL %s\n", note); } while (0)

static void Drain(NSString *mode, int milliseconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:milliseconds / 1000.0];
    while ([[NSDate date] compare:until] == NSOrderedAscending) {
        [[NSRunLoop mainRunLoop] runMode:mode beforeDate:until];
    }
}

@interface Polled : NSObject {
@public
    int ticks;
}
@end

@implementation Polled
- (void)tick { ticks++; }
@end

static Polled * __weak weakPolled = nil;

int main(void) {
    @autoreleasepool {
        // The app initialises AppKit, and AppKit is what puts its own modes into the common
        // set, so a probe that skipped this would be measuring a different program.
        [NSApplication sharedApplication];

        __block int onDefault = 0, onCommon = 0, onModal = 0, onTracking = 0;
        NSTimer *timerOnDefault = [NSTimer timerWithTimeInterval:0.01 repeats:YES
                                                           block:^(NSTimer *t) { onDefault++; }];
        [[NSRunLoop mainRunLoop] addTimer:timerOnDefault forMode:NSDefaultRunLoopMode];
        NSTimer *timerOnCommon = [NSTimer timerWithTimeInterval:0.01 repeats:YES
                                                          block:^(NSTimer *t) { onCommon++; }];
        [[NSRunLoop mainRunLoop] addTimer:timerOnCommon forMode:NSRunLoopCommonModes];
        NSTimer *timerOnModal = [NSTimer timerWithTimeInterval:0.01 repeats:YES
                                                         block:^(NSTimer *t) { onModal++; }];
        [[NSRunLoop mainRunLoop] addTimer:timerOnModal forMode:NSModalPanelRunLoopMode];
        NSTimer *timerOnTracking = [NSTimer timerWithTimeInterval:0.01 repeats:YES
                                                           block:^(NSTimer *t) { onTracking++; }];
        [[NSRunLoop mainRunLoop] addTimer:timerOnTracking forMode:NSEventTrackingRunLoopMode];

        int before[4], after[4];

        before[0] = onDefault; before[1] = onCommon; before[2] = onModal; before[3] = onTracking;
        Drain(NSDefaultRunLoopMode, 300);
        after[0] = onDefault; after[1] = onCommon; after[2] = onModal; after[3] = onTracking;
        printf("case=default default=%d common=%d modal=%d tracking=%d\n",
               after[0] - before[0], after[1] - before[1],
               after[2] - before[2], after[3] - before[3]);
        CHECK(after[0] - before[0] > 0, "a poll added to the default mode fires in the default mode");
        CHECK(after[1] - before[1] > 0, "a poll added to the common modes fires in the default mode");
        CHECK(after[2] - before[2] == 0, "a poll added only for the modal mode is silent in the default one");
        CHECK(after[3] - before[3] == 0, "a poll added only for the tracking mode is silent in the default one");

        before[0] = onDefault; before[1] = onCommon; before[2] = onModal; before[3] = onTracking;
        Drain(NSModalPanelRunLoopMode, 300);
        after[0] = onDefault; after[1] = onCommon; after[2] = onModal; after[3] = onTracking;
        printf("case=modal default=%d common=%d modal=%d tracking=%d\n",
               after[0] - before[0], after[1] - before[1],
               after[2] - before[2], after[3] - before[3]);
        CHECK(after[0] - before[0] == 0, "a poll added only to the default mode is silent during a modal session");
        CHECK(after[2] - before[2] > 0, "a poll added to the modal mode keeps firing during a modal session");
        CHECK(after[3] - before[3] == 0, "a poll added only for the tracking mode is silent during a modal session");

        before[0] = onDefault; before[1] = onCommon; before[2] = onModal; before[3] = onTracking;
        Drain(NSEventTrackingRunLoopMode, 300);
        after[0] = onDefault; after[1] = onCommon; after[2] = onModal; after[3] = onTracking;
        printf("case=tracking default=%d common=%d modal=%d tracking=%d\n",
               after[0] - before[0], after[1] - before[1],
               after[2] - before[2], after[3] - before[3]);
        CHECK(after[0] - before[0] == 0, "a poll added only to the default mode is silent while AppKit tracks events");
        CHECK(after[3] - before[3] > 0, "a poll added to the tracking mode keeps firing while AppKit tracks events");
        printf("common-modes-covers-modal=%d\n", after[1] - before[1] > 0);

        [timerOnDefault invalidate];
        [timerOnCommon invalidate];
        [timerOnModal invalidate];
        [timerOnTracking invalidate];

        before[0] = onDefault; before[1] = onCommon; before[2] = onModal; before[3] = onTracking;
        Drain(NSDefaultRunLoopMode, 300);
        printf("case=after-invalidate default=%d common=%d modal=%d tracking=%d\n",
               onDefault - before[0], onCommon - before[1],
               onModal - before[2], onTracking - before[3]);
        CHECK(onDefault - before[0] == 0 && onCommon - before[1] == 0,
              "invalidate stops a repeating timer, so a stop on a path that runs is a real stop");

        // Who a repeating timer keeps alive. Both shapes below are shapes the app can be
        // written in; the object reports its own ticks, and nothing here stands in for a
        // decision the app makes.
        {
            Polled *owner = [[Polled alloc] init];
            weakPolled = owner;
            NSTimer *scheduled = [NSTimer scheduledTimerWithTimeInterval:0.01
                                                                  target:owner
                                                                selector:@selector(tick)
                                                                userInfo:nil
                                                                 repeats:YES];
            owner = nil;
            Drain(NSDefaultRunLoopMode, 300);
            Polled *stillThere = weakPolled;
            printf("shape=target-self survived=%d ticks=%d\n",
                   stillThere != nil, stillThere != nil ? stillThere->ticks : 0);
            CHECK(stillThere != nil && stillThere->ticks > 0,
                  "a repeating timer with target:self keeps the object it polls alive and polling");
            [scheduled invalidate];
            weakPolled = nil;
        }
        {
            Polled *owner = [[Polled alloc] init];
            weakPolled = owner;
            NSTimer *weakPoll = [NSTimer timerWithTimeInterval:0.01 repeats:YES
                                                         block:^(NSTimer *t) {
                Polled *strong = weakPolled;
                if (strong == nil) {
                    [t invalidate];
                    return;
                }
                [strong tick];
            }];
            [[NSRunLoop mainRunLoop] addTimer:weakPoll forMode:NSRunLoopCommonModes];
            owner = nil;
            Drain(NSDefaultRunLoopMode, 50);
            Polled *seen = weakPolled;
            int beforeDeath = seen != nil ? seen->ticks : 0;
            Drain(NSDefaultRunLoopMode, 300);
            seen = weakPolled;
            printf("shape=weak-block survived=%d ticks-after-death=%d\n",
                   seen != nil, seen != nil ? seen->ticks - beforeDeath : 0);
            CHECK(seen == nil, "a weak poll that invalidates itself does not keep its owner alive");
        }

        printf("checks=%d\n", checks);
        return 0;
    }
}
'''

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def counts(line):
    """`case=modal default=0 common=15 ...` -> {mode: ticks}."""
    return {field.split("=")[0]: int(field.split("=")[1]) for field in line.split()[1:]}


def main():
    cc, sdk = apple_toolchain.clang_and_sdk("timer registration probe")
    with tempfile.TemporaryDirectory(prefix="timer-registration-") as work:
        source = os.path.join(work, "probe.m")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(SOURCE)
        binary = os.path.join(work, "probe")
        built = subprocess.run(
            [cc, "-fobjc-arc", "-Wno-deprecated-declarations", "-isysroot", sdk,
             "-framework", "AppKit", "-framework", "Foundation", source, "-o", binary],
            capture_output=True, text=True)
        if built.returncode != 0:
            print("timer-registration: the probe did not compile:\n"
                  + (built.stdout + built.stderr).strip()[-2500:])
            return 1
        ran = subprocess.run([binary], capture_output=True, text=True)
        if ran.returncode != 0:
            print("timer-registration: the probe exited %d:\n%s" % (ran.returncode, ran.stdout))
            return 1

    out = ran.stdout
    print(out.rstrip())
    cases = {line.split()[0].split("=")[1]: counts(line)
             for line in out.splitlines() if line.startswith("case=")}
    # Keyed by the line's own first token, because `shape=target-self survived=1 ticks=30`
    # carries three fields and a split on "=" alone collapses both shape lines into one key.
    reported = {line.split()[0]: line for line in out.splitlines() if line.startswith("shape=")}
    checks_line = next((line for line in out.splitlines() if line.startswith("checks=")), "")

    check("FAIL" not in out, "the probe's own assertions held, in both directions of every mode")
    if checks_line.count("=") == 1:
        check(int(checks_line.split("=")[1]) >= MIN_TIMER_CHECKS,
              "the probe ran at least %d of its own assertions, not fewer" % MIN_TIMER_CHECKS)
    else:
        check(False, "the probe reported how many assertions it ran")

    if set(cases) != {"default", "modal", "tracking", "after-invalidate"}:
        check(False, "the probe measured all four cases, measured: %s" % ", ".join(sorted(cases)))
        return 1 if failures else 0

    control = cases["default"]
    check(control["default"] > 0 and control["common"] > 0,
          "in the default mode both a default-mode poll and a common-modes poll fire")
    check(control["modal"] == 0 and control["tracking"] == 0,
          "and a poll added only for a mode AppKit is not in stays silent, so every zero "
          "below is the mode rather than a dead timer")

    modal, tracking = cases["modal"], cases["tracking"]
    check(modal["default"] == 0 and modal["modal"] > 0,
          "during a modal session a default-mode poll fires 0 times while one added to the "
          "modal mode keeps firing")
    check(tracking["default"] == 0 and tracking["tracking"] > 0,
          "during event tracking the same holds the other way round")
    check(cases["after-invalidate"]["default"] == 0 and cases["after-invalidate"]["common"] == 0,
          "invalidate ends a repeating timer immediately, so the stop a gate asks for is a "
          "stop that actually stops")

    for mode in ("modal", "tracking"):
        if modal["common"] > 0 if mode == "modal" else tracking["common"] > 0:
            check(True, "NSRunLoopCommonModes covers the %s mode on this host" % mode)
        else:
            print("skip  NSRunLoopCommonModes does not cover the %s mode here, so the claim "
                  "that one registration reaches it is not measured, not passed" % mode)

    target_shape = reported.get("shape=target-self", "")
    survived = "survived=1" in target_shape
    polled_after = 0
    if "ticks=" in target_shape:
        polled_after = int(target_shape.split("ticks=")[1])
    check(survived and polled_after > 0,
          "a repeating timer with target:self was still polling an object its owner had "
          "already let go of")
    check("survived=0" in reported.get("shape=weak-block", ""),
          "a weak poll that invalidates itself left its owner free to go away")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
