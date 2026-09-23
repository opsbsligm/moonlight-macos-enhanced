#!/usr/bin/env python3
"""Measure who a block notification observer keeps alive, and how many times it fires.

Six shipped files register a block observer inside a method AppKit may run more than
once, and three of them registered one on every pass. Whether that is a bug depends on
behaviour no test in this repository had looked at: does the notification centre let go
of a block whose token was overwritten, can a removal by object reach a block at all, and
does -viewDidAppear really arrive twice for one view controller.

Nothing here is argued from documentation. The program below registers blocks that differ
only in the shape the shipped code uses, posts once, and counts what fired:

  one post reaches every block registered for a name -- three registrations answer a
    single notification three times, so a callback is not one per event;
  writing a fresh token over an old one does not unregister the old block: two
    registrations reached one post, and the object only ever held one token to remove
    with, so the extra registration is unreachable rather than merely wasted;
  removing the token this object already holds before registering again leaves exactly
    one block answering, and removing by token then posting reaches none -- which is what
    makes "remove first, then register" a stop rather than a formality;
  -removeObserver:name:object: removes a selector observer and removes nothing of a block
    observer whose token was thrown away, so a -dealloc that asks for the object does not
    withdraw a block;
  a block that names its owner strongly keeps that owner alive and callable after every
    reference outside the centre is gone, so a stop in that owner's -dealloc is not a stop
    at all; a block that names it weakly lets it go, which is what makes a -dealloc stop
    reachable;
  and AppKit delivers -viewDidAppear to the same view controller again after its window is
    hidden and shown again, and once per show across three parent changes. That is the
    path on which the registrations below happen a second time; it is measured here rather
    than assumed, because the whole finding rests on it.

Two claims are deliberately absent. Nothing here reads the shipped files:
constraints-audit.py does that, and refuses a block observer registered on a repeatable
lifecycle path without a removal of the token it already holds. And nothing here says how
often a player hides and re-shows a stream window -- that is a fact about players, and a
gate that pretends to know it would be guessing.
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

# The compiled program counts its own assertions. A count below the floor means a case
# stopped running, which is not a case that passed -- it is a case that is gone.
MIN_OBSERVER_CHECKS = 12

SOURCE = r'''
#import <AppKit/AppKit.h>
#include <stdio.h>

static int checks = 0;
#define CHECK(cond, note) do { checks++; if (!(cond)) printf("FAIL %s\n", note); } while (0)

static int blockHits = 0;
static int appears = 0;
static int disappears = 0;

// A token property, a block that names its owner weakly, and a removal by token: this
// is the shape three shipped view controllers use. Counting how often AppKit delivers
// -viewDidAppear is what decides whether registering one inside it is safe at all.
@interface Page : NSViewController
@end
@implementation Page
- (void)loadView { self.view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 400, 300)]; }
- (void)viewDidAppear { [super viewDidAppear]; appears++; }
- (void)viewDidDisappear { [super viewDidDisappear]; disappears++; }
@end

@interface Owner : NSObject {
@public
    id token;
    int selectorHits;
}
- (void)selectorHit:(NSNotification *)note;
@end
@implementation Owner
- (void)selectorHit:(NSNotification *)note { selectorHits++; }
@end

static Owner * __weak ghost = nil;

int main(void) {
    @autoreleasepool {
        // AppKit is initialised because the shipped app initialises it, and because a
        // view controller only hears about appearing when AppKit is showing its window.
        [NSApplication sharedApplication];
        NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
        Owner *owner = [[Owner alloc] init];

        NSString *repeatName = @"Gate.Repeats";
        [nc addObserverForName:repeatName object:nil queue:nil
                     usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc addObserverForName:repeatName object:nil queue:nil
                     usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc addObserverForName:repeatName object:nil queue:nil
                     usingBlock:^(NSNotification *n) { blockHits++; }];
        blockHits = 0;
        [nc postNotificationName:repeatName object:nil];
        printf("case=repeats hits=%d\n", blockHits);
        CHECK(blockHits == 3, "one post reaches every block registered for its name");

        NSString *overwriteName = @"Gate.Overwrite";
        blockHits = 0;
        owner->token = [nc addObserverForName:overwriteName object:nil queue:nil
                                    usingBlock:^(NSNotification *n) { blockHits++; }];
        owner->token = [nc addObserverForName:overwriteName object:nil queue:nil
                                    usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc postNotificationName:overwriteName object:nil];
        printf("case=overwrite hits=%d\n", blockHits);
        CHECK(blockHits == 2, "writing a fresh token over an old one leaves the old block registered");

        NSString *removeFirstName = @"Gate.RemoveFirst";
        blockHits = 0;
        owner->token = [nc addObserverForName:removeFirstName object:nil queue:nil
                                    usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc removeObserver:owner->token];
        owner->token = [nc addObserverForName:removeFirstName object:nil queue:nil
                                    usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc postNotificationName:removeFirstName object:nil];
        printf("case=remove-first hits=%d\n", blockHits);
        CHECK(blockHits == 1, "removing the token this object already holds keeps the count at one");

        [nc removeObserver:owner->token];
        owner->token = nil;
        blockHits = 0;
        [nc postNotificationName:removeFirstName object:nil];
        printf("case=after-token-remove hits=%d\n", blockHits);
        CHECK(blockHits == 0, "a removal by token stops that block dead, so the step above is a stop");

        NSString *tokenlessName = @"Gate.Tokenless";
        blockHits = 0;
        owner->selectorHits = 0;
        [nc addObserver:owner selector:@selector(selectorHit:) name:tokenlessName object:nil];
        [nc addObserverForName:tokenlessName object:nil queue:nil
                     usingBlock:^(NSNotification *n) { blockHits++; }];
        [nc removeObserver:owner name:tokenlessName object:nil];
        [nc postNotificationName:tokenlessName object:nil];
        printf("case=tokenless selector=%d block=%d\n", owner->selectorHits, blockHits);
        CHECK(owner->selectorHits == 0, "removing by object removes the selector observer");
        CHECK(blockHits == 1, "and removes nothing of a block observer whose token was thrown away");

        NSString *strongName = @"Gate.StrongCapture";
        @autoreleasepool {
            Owner *strong = [[Owner alloc] init];
            ghost = strong;
            [nc addObserverForName:strongName object:nil queue:nil
                         usingBlock:^(NSNotification *n) { strong->selectorHits++; }];
            strong = nil;
            Owner *alive = ghost;
            [nc postNotificationName:strongName object:nil];
            printf("shape=strong-block survived=%d hits=%d\n",
                   alive != nil, alive != nil ? alive->selectorHits : -1);
            CHECK(alive != nil, "a block that names its owner strongly keeps the owner alive");
            CHECK(alive != nil && alive->selectorHits == 1,
                  "and the centre still calls it, so a stop in that owner's -dealloc cannot run");
        }

        NSString *weakName = @"Gate.WeakCapture";
        @autoreleasepool {
            Owner *weakOwner = [[Owner alloc] init];
            ghost = weakOwner;
            __weak Owner *weakRef = weakOwner;
            [nc addObserverForName:weakName object:nil queue:nil
                         usingBlock:^(NSNotification *n) { if (weakRef) { blockHits++; } }];
            weakOwner = nil;
            Owner *alive = ghost;
            printf("shape=weak-block survived=%d\n", alive != nil);
            CHECK(alive == nil, "a block that names its owner weakly lets the owner go, which is "
                                "what makes a stop in that owner's -dealloc a stop that can run");
        }

        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 400, 300)
                                                       styleMask:NSWindowStyleMaskTitled
                                                         backing:NSBackingStoreBuffered
                                                           defer:NO];
        NSViewController *container = [[NSViewController alloc] init];
        container.view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 400, 300)];
        window.contentViewController = container;
        [window makeKeyAndOrderFront:nil];

        for (int cycle = 0; cycle < 3; cycle++) {
            Page *page = [[Page alloc] init];
            [container addChildViewController:page];
            [container.view addSubview:page.view];
            [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
            [page.view removeFromSuperview];
            [page removeFromParentViewController];
            [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        printf("case=parent-swaps appears=%d disappears=%d\n", appears, disappears);
        CHECK(appears == 3 && disappears == 3,
              "one view controller hears -viewDidAppear once per show, so three shows are three");

        appears = 0;
        disappears = 0;
        Page *resident = [[Page alloc] init];
        [container addChildViewController:resident];
        [container.view addSubview:resident.view];
        [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        int firstShow = appears;
        [window orderOut:nil];
        [window makeKeyAndOrderFront:nil];
        [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        printf("case=window-reshow appears-after-first-show=%d appears-after-reshow=%d\n",
               firstShow, appears);
        CHECK(firstShow == 1, "a page shown once hears -viewDidAppear once");
        CHECK(appears == firstShow + 1,
              "and the same instance hears it again when its window is hidden and shown again, "
              "which is the path that registers an observer a second time");

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
    """`case=repeats hits=3` -> {"hits": 3}."""
    return {field.split("=")[0]: int(field.split("=")[1]) for field in line.split()[1:]}


def reported_number(line, prefix):
    """`shape=weak-block survived=0` -> 0, for the one field a shape line answers."""
    for field in line.split()[1:]:
        if field.startswith(prefix + "="):
            return int(field.split("=")[1])
    return None


def main():
    cc, sdk = apple_toolchain.clang_and_sdk("notification observer probe")
    with tempfile.TemporaryDirectory(prefix="notification-observer-") as work:
        source = os.path.join(work, "probe.m")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(SOURCE)
        binary = os.path.join(work, "probe")
        built = subprocess.run(
            [cc, "-fobjc-arc", "-Wno-deprecated-declarations", "-isysroot", sdk,
             "-framework", "AppKit", "-framework", "Foundation", source, "-o", binary],
            capture_output=True, text=True)
        if built.returncode != 0:
            print("notification-observers: the probe did not compile:\n"
                  + (built.stdout + built.stderr).strip()[-2500:])
            return 1
        ran = subprocess.run([binary], capture_output=True, text=True)
        if ran.returncode != 0:
            print("notification-observers: the probe exited %d:\n%s"
                  % (ran.returncode, ran.stdout))
            return 1

    out = ran.stdout
    print(out.rstrip())
    cases = {line.split()[0].split("=")[1]: counts(line)
             for line in out.splitlines() if line.startswith("case=")}
    # Keyed by the line's own first token: `shape=strong-block survived=1 hits=1` carries
    # two answers, and a split on "=" alone would collapse the two shape lines together.
    reported = {line.split()[0]: line for line in out.splitlines() if line.startswith("shape=")}
    checks_line = next((line for line in out.splitlines() if line.startswith("checks=")), "")

    check("FAIL" not in out, "the probe's own assertions held, in both directions of every shape")
    if checks_line.count("=") == 1:
        check(int(checks_line.split("=")[1]) >= MIN_OBSERVER_CHECKS,
              "the probe ran at least %d of its own assertions, not fewer" % MIN_OBSERVER_CHECKS)
    else:
        check(False, "the probe reported how many assertions it ran")

    expected = {"repeats", "overwrite", "remove-first", "after-token-remove", "tokenless",
                "parent-swaps", "window-reshow"}
    if set(cases) != expected:
        check(False, "the probe measured all seven cases, measured: %s"
              % ", ".join(sorted(cases)))
        return 1 if failures else 0

    check(cases["repeats"]["hits"] == 3,
          "one post reaches all three blocks registered for its name, so a shipped callback "
          "answering twice is two registrations and not two events")
    check(cases["overwrite"]["hits"] == 2,
          "overwriting the token keeps the previous block registered, and the owner can no "
          "longer name it to the centre")
    check(cases["remove-first"]["hits"] == 1,
          "removing the token before registering again is what a repeated lifecycle pass "
          "needs to end at exactly one observer")
    check(cases["after-token-remove"]["hits"] == 0,
          "and that removal stops the block, so the step above is a stop and not a gesture")
    check(cases["tokenless"]["selector"] == 0 and cases["tokenless"]["block"] == 1,
          "removing by object reaches a selector observer and not a block observer, so a "
          "token that was never stored cannot be withdrawn later")

    check(cases["parent-swaps"]["appears"] == 3 and cases["parent-swaps"]["disappears"] == 3,
          "one view controller hears -viewDidAppear once per show across three parent changes")
    check(cases["window-reshow"]["appears-after-first-show"] == 1
          and cases["window-reshow"]["appears-after-reshow"] == 2,
          "and the same instance hears it again after its window is hidden and shown again, "
          "which is the path that runs a registration twice")

    strong = reported.get("shape=strong-block", "")
    weak = reported.get("shape=weak-block", "")
    check(reported_number(strong, "survived") == 1
          and reported_number(strong, "hits") == 1,
          "a strongly capturing block keeps its owner alive and callable, so a stop parked "
          "in that owner's -dealloc never runs")
    check(reported_number(weak, "survived") == 0,
          "a weakly capturing block releases its owner, which is the difference between a "
          "-dealloc stop that runs and one that cannot")

    print("%d notification-observer failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
