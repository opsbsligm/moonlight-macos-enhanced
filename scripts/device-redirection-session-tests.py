#!/usr/bin/env python3
"""Prove the order in which a device may be handed over, against a host that does not exist.

Stage 2 of docs/usb-redirection-design.md, and only the half of it this repository owns. No
host implements the three exchanges in docs/usb-redirection-host-contract.md 4, so there is
nothing here that talks to one: the answers come from a reference responder written in this
file, and what is under test is the sequencing, not the encoding. That distinction is the
reason the class is not wired into the stream start path -- with no peer, wiring would mean
deciding the protocol by guessing, and a guess that looks like support costs a user a device
they were told they had.

What is decided here is worth locking anyway, because every one of these rules is a claim
about behaviour rather than about bytes, and each has a defect planted against it:

  a step never runs before the step before it was accepted, so an upload cannot happen on a
    session that never learned whether the host had room;
  only an explicit yes is a yes, in serverinfo and in every answer after it;
  a field that answered two different things is not resolved by picking one;
  a message on a channel nobody defined ends the session instead of being skipped, because
    the next answer would otherwise be read against the wrong step;
  an unanswered step is not a no: it is a different stop, so a slow host and a full host do
    not come out of the log looking the same;
  the first reason a session died survives whatever happens next.

The value shapes are the ones the shape tool says a real registry answers with: numbers,
text that looks like a number, a number with a fraction, a count above what a bus can hold,
a tag in the wrong case, a tag twice, and a tag that carries nothing at all.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

# The floor for the compiled driver's own case count, not the count itself: the number the
# binary prints is the truth, and this only notices a case list that got shorter.
MIN_DRIVER_CHECKS = 25
SESSION_H = "Limelight/Stream/DeviceRedirectionSession.h"
SESSION_M = "Limelight/Stream/DeviceRedirectionSession.m"

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
    header, impl = read(SESSION_H), read(SESSION_M)
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", header + impl))) ==
          ["Foundation/Foundation.h"],
          "the session imports nothing beyond Foundation: no clock, no socket, no IOKit")
    rules = strip_imports(header, ["DeviceRedirectionSession.h"]) + "\n" + \
        strip_imports(impl, ["DeviceRedirectionSession.h"])
    check("#import" not in rules, "the compiled bundle carries no import at all")
    return rules


DRIVER = r"""
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

static void check_case(BOOL ok, const char *what) {
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

// The macro parameters are not called `name` or `value`: the preprocessor rewrites an
// argument wherever the identifier appears, including inside a selector, and a macro
// that turns `value:` into `@1:` is a syntax error that reads like a bad literal.
#define FIELD(tag, payload) [MLDeviceRedirectionField fieldNamed:(tag) value:(payload)]

static MLDeviceRedirectionSession *advertised(NSArray *serverInfoFields) {
    return [MLDeviceRedirectionSession sessionFromServerInfoFields:serverInfoFields];
}

static MLDeviceRedirectionSession *ask(MLDeviceRedirectionSession *session,
                                       MLDeviceRedirectionChannel channel) {
    return [session sessionByRecordingRequest:channel];
}

static MLDeviceRedirectionSession *answered(MLDeviceRedirectionSession *session,
                                            MLDeviceRedirectionChannel channel,
                                            NSArray *fields) {
    return [session sessionByRecordingResponse:
                [MLDeviceRedirectionHostResponse responseOnChannel:channel fields:fields]];
}

// expect_state is the whole assertion: phase, reason, slot count and which of the three
// questions the stream path may ask. Checking the phase alone would pass for an
// implementation that closed the session for the wrong reason and printed a good name.
static void expect_state(const char *what, MLDeviceRedirectionSession *session,
                         MLDeviceRedirectionPhase phase, MLDeviceRedirectionStop stop,
                         NSInteger slots, BOOL bind, BOOL state, BOOL upload) {
    const BOOL ok = session.phase == phase && session.stop == stop &&
                    session.availableSlots == slots && session.mayRequestBind == bind &&
                    session.mayRequestState == state &&
                    session.mayUploadDeviceDescriptor == upload;
    checks_run++;
    if (!ok) failures++;
    NSString *slots_text = session.availableSlots == MLDeviceRedirectionSlotsUnknown
        ? @"unknown" : [@(session.availableSlots) stringValue];
    printf("%-4s %-52s -> step=%s stop=%s slots=%s ask:%s%s%s\n",
           ok ? "ok" : "FAIL", what,
           MLDeviceRedirectionPhaseName(session.phase).UTF8String,
           MLDeviceRedirectionStopName(session.stop).UTF8String,
           slots_text.UTF8String,
           bind ? "B" : "-", state ? "S" : "-", upload ? "U" : "-");
}

// The path every working session walks, so one case can change exactly one step.
static MLDeviceRedirectionSession *bound(MLDeviceRedirectionSession *session) {
    return answered(ask(session, MLDeviceRedirectionChannelBind),
                    MLDeviceRedirectionChannelBind,
                    @[ FIELD(@"usbRedirectionBound", @1) ]);
}

static MLDeviceRedirectionSession *ready(MLDeviceRedirectionSession *session, NSInteger slots) {
    return answered(ask(bound(session), MLDeviceRedirectionChannelState),
                    MLDeviceRedirectionChannelState,
                    @[ FIELD(@"usbRedirectionSlots", @(slots)) ]);
}

static MLDeviceRedirectionSession *the_advertised_host(void) {
    return advertised(@[ FIELD(@"usbRedirection", @1) ]);
}

int main(void) {
    @autoreleasepool {
        // What a host's /serverinfo may answer. Everything that is not an explicit yes gets
        // the same refusal an un-upgraded host gets.
        expect_state("serverinfo says 1", the_advertised_host(),
                     MLDeviceRedirectionPhaseIdle, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, YES, NO, NO);
        expect_state("serverinfo says the text 1",
                     advertised(@[ FIELD(@"usbRedirection", @"1") ]),
                     MLDeviceRedirectionPhaseIdle, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, YES, NO, NO);
        // Foundation cannot tell @YES from @1, so accepting one means accepting the other.
        // Recorded rather than wished away: a rule that claimed to refuse a boolean would be
        // a rule the next reader could not reproduce.
        expect_state("serverinfo says YES, which Foundation cannot tell from 1",
                     advertised(@[ FIELD(@"usbRedirection", @YES) ]),
                     MLDeviceRedirectionPhaseIdle, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, YES, NO, NO);
        expect_state("serverinfo says nothing about it", advertised(@[]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("serverinfo says 0", advertised(@[ FIELD(@"usbRedirection", @0) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("serverinfo says the text 0",
                     advertised(@[ FIELD(@"usbRedirection", @"0") ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("serverinfo says yes in prose",
                     advertised(@[ FIELD(@"usbRedirection", @"yes") ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("serverinfo carries the tag with no value",
                     advertised(@[ FIELD(@"usbRedirection", nil) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("serverinfo says 2, which is not a yes",
                     advertised(@[ FIELD(@"usbRedirection", @2) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("the tag in another case is a different tag",
                     advertised(@[ FIELD(@"USBRedirection", @1) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopHostNotAdvertised,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("the tag twice, agreeing, is one answer",
                     advertised(@[ FIELD(@"usbRedirection", @1),
                                   FIELD(@"usbRedirection", @1) ]),
                     MLDeviceRedirectionPhaseIdle, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, YES, NO, NO);
        expect_state("the tag twice, disagreeing, is not resolved by picking one",
                     advertised(@[ FIELD(@"usbRedirection", @1),
                                   FIELD(@"usbRedirection", @0) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopAmbiguousResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        // A field from a newer host is ignored rather than feared: refusing every unknown key
        // would make the first host that adds a field unable to be used by this client.
        expect_state("a field this client has never seen does not stop the session",
                     advertised(@[ FIELD(@"usbRedirection", @1),
                                   FIELD(@"usbRedirectionFutureThing", @"whatever") ]),
                     MLDeviceRedirectionPhaseIdle, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, YES, NO, NO);

        // Order. Each of these is a step the stream path could take in the wrong sequence.
        expect_state("asking for room before binding", ask(the_advertised_host(),
                                                           MLDeviceRedirectionChannelState),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStepOutOfOrder,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("uploading before binding", ask(the_advertised_host(),
                                                     MLDeviceRedirectionChannelItem),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStepOutOfOrder,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("asking twice while one answer is owed",
                     ask(ask(the_advertised_host(), MLDeviceRedirectionChannelBind),
                         MLDeviceRedirectionChannelBind),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStepOutOfOrder,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a bind the host took", bound(the_advertised_host()),
                     MLDeviceRedirectionPhaseBound, MLDeviceRedirectionStopNone,
                     MLDeviceRedirectionSlotsUnknown, NO, YES, NO);
        expect_state("a bind the host refused",
                     answered(ask(the_advertised_host(), MLDeviceRedirectionChannelBind),
                              MLDeviceRedirectionChannelBind,
                              @[ FIELD(@"usbRedirectionBound", @0) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopBindRefused,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a bind the host never answered",
                     [ask(the_advertised_host(), MLDeviceRedirectionChannelBind)
                         sessionByRecordingTimeoutOnChannel:MLDeviceRedirectionChannelBind],
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopBindUnanswered,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a bind answer that did not answer the question",
                     answered(ask(the_advertised_host(), MLDeviceRedirectionChannelBind),
                              MLDeviceRedirectionChannelBind, @[]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);

        // The state answer, which is the only thing that can make an upload legal.
        expect_state("two slots free", ready(the_advertised_host(), 2),
                     MLDeviceRedirectionPhaseReady, MLDeviceRedirectionStopNone,
                     2, NO, NO, YES);
        expect_state("one slot free", ready(the_advertised_host(), 1),
                     MLDeviceRedirectionPhaseReady, MLDeviceRedirectionStopNone,
                     1, NO, NO, YES);
        expect_state("the host is full, which is an answer", ready(the_advertised_host(), 0),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopNoSlots,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a state answer with no slot count in it",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState, @[]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a slot count written as text is not a count",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @"2") ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a slot count with a fraction on it",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @2.7) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a negative slot count",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @(-1)) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("more slots than a bus can address",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @128) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopMalformedResponse,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("the most slots a bus could hold",
                     answered(ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState),
                              MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @127) ]),
                     MLDeviceRedirectionPhaseReady, MLDeviceRedirectionStopNone,
                     127, NO, NO, YES);
        expect_state("a state answer the host never sent",
                     [ask(bound(the_advertised_host()), MLDeviceRedirectionChannelState)
                         sessionByRecordingTimeoutOnChannel:MLDeviceRedirectionChannelState],
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStateUnanswered,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        expect_state("a reply to a state request that was never made",
                     answered(bound(the_advertised_host()), MLDeviceRedirectionChannelState,
                              @[ FIELD(@"usbRedirectionSlots", @1) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStepOutOfOrder,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);

        // Uploading, and what a slot actually means once one is spent.
        MLDeviceRedirectionSession *carrying =
            ask(ready(the_advertised_host(), 2), MLDeviceRedirectionChannelItem);
        expect_state("a device on its way", carrying,
                     MLDeviceRedirectionPhaseUploading, MLDeviceRedirectionStopNone,
                     2, NO, NO, NO);
        MLDeviceRedirectionSession *delivered =
            answered(carrying, MLDeviceRedirectionChannelItem,
                     @[ FIELD(@"usbRedirectionAccepted", @1) ]);
        expect_state("the host took it, and one slot is gone", delivered,
                     MLDeviceRedirectionPhaseReady, MLDeviceRedirectionStopNone,
                     1, NO, NO, YES);
        MLDeviceRedirectionSession *last_one =
            answered(ask(delivered, MLDeviceRedirectionChannelItem),
                     MLDeviceRedirectionChannelItem,
                     @[ FIELD(@"usbRedirectionAccepted", @1) ]);
        expect_state("the last slot is spent, and no third device may start", last_one,
                     MLDeviceRedirectionPhaseReady, MLDeviceRedirectionStopNone,
                     0, NO, NO, NO);
        expect_state("the host refused the device",
                     answered(ask(ready(the_advertised_host(), 1), MLDeviceRedirectionChannelItem),
                              MLDeviceRedirectionChannelItem,
                              @[ FIELD(@"usbRedirectionAccepted", @0) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopItemRefused,
                     1, NO, NO, NO);
        expect_state("the host took the upload and said nothing",
                     [ask(ready(the_advertised_host(), 1), MLDeviceRedirectionChannelItem)
                         sessionByRecordingTimeoutOnChannel:MLDeviceRedirectionChannelItem],
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopItemUnanswered,
                     1, NO, NO, NO);
        expect_state("an upload answer before any upload",
                     answered(ready(the_advertised_host(), 1), MLDeviceRedirectionChannelItem,
                              @[ FIELD(@"usbRedirectionAccepted", @1) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopStepOutOfOrder,
                     1, NO, NO, NO);
        expect_state("a message on a channel this contract does not define",
                     answered(ready(the_advertised_host(), 1),
                              (MLDeviceRedirectionChannel)42,
                              @[ FIELD(@"usbRedirectionSlots", @9) ]),
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopUnknownChannel,
                     1, NO, NO, NO);

        // The first reason survives. A session that died of a full host must not be
        // re-askable, and must not be relabelled by whatever the caller tries next.
        expect_state("a session closed for a full host stays closed for that reason",
                     [ask(ask(ready(the_advertised_host(), 0), MLDeviceRedirectionChannelBind),
                          MLDeviceRedirectionChannelItem)
                         sessionByRecordingTimeoutOnChannel:MLDeviceRedirectionChannelBind],
                     MLDeviceRedirectionPhaseClosed, MLDeviceRedirectionStopNoSlots,
                     MLDeviceRedirectionSlotsUnknown, NO, NO, NO);
        // The same device plugged in twice is a new session: a stale "there were two slots"
        // must not carry across the connection that learned it.
        check_case(ready(the_advertised_host(), 2).availableSlots == 2 &&
                   ready(the_advertised_host(), 1).availableSlots == 1,
                   "a second attempt is a new session and re-reads the slots");
        check_case(ready(the_advertised_host(), 0).mayUploadDeviceDescriptor == NO &&
                   the_advertised_host().mayUploadDeviceDescriptor == NO,
                   "no step of a session that never heard about room authorises an upload");

        // What a line about the session is allowed to say.
        check_case([the_advertised_host().auditLine rangeOfString:@"slots=unknown"].location
                   != NSNotFound,
                   "a session that never learned the slots says unknown, never zero");
        check_case([ready(the_advertised_host(), 2).auditLine rangeOfString:@"step=ready"].location
                   != NSNotFound,
                   "the line names the step the session reached");
        check_case([ready(the_advertised_host(), 0).auditLine
                    rangeOfString:@"stop=no-slots"].location != NSNotFound,
                   "a full host reads differently from a host that never answered");

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
        ran, out = compiled(source, work, "session_driver", cc, sdk)
        if ran is None:
            check(False, "%s: the harness compiled (%s)" % (label, (out or "").splitlines()[-1:]))
            return
        if expect_pass:
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "%s reads and speaks correctly" % label)
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_DRIVER_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_DRIVER_CHECKS))
        else:
            check(ran.returncode != 0 or "RUN FAILED" not in (out or ""),
                  "the check still fails when %s" % label)
            if ran.returncode == 0:
                print((out or "").strip().splitlines()[-1:])


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    impl = read(SESSION_M)
    print("-- the order a device may be handed over in, against a host that does not exist --")

    cc, sdk = apple_toolchain.clang_and_sdk("device redirection session")
    run_rules("the shipping session", rules, cc, sdk, expect_pass=True)

    check("NSLog(" not in impl and "printf(" not in impl,
          "the session has no path to the log of its own")
    for forbidden in ("NSDate", "CACurrentMediaTime", "NSUserDefaults", "clock_gettime",
                      "gettimeofday"):
        check(forbidden not in impl,
              "the session never reads %s: a timeout arrives as an event or it is not tested"
              % forbidden)
    check(len(re.findall(r"^static NSString \*const ", impl, re.M)) == 4,
          "the four tag names live in one place, so a rename cannot half-happen")
    check("usbRedirection" in impl,
          "the one tag with a name in the contract is the tag the contract names")

    run_rules("a host that answers 2 is taken as support",
              mutated(rules, "only one is yes",
                      "return [(NSNumber *)value integerValue] == 1;",
                      "return [(NSNumber *)value integerValue] != 0;"),
              cc, sdk)
    run_rules("an unknown channel is skipped instead of ending the session",
              mutated(rules, "the unknown channel",
                      "return [self sessionByClosing:MLDeviceRedirectionStopUnknownChannel];",
                      "return self;"),
              cc, sdk)
    run_rules("two answers to one tag are resolved by taking the first",
              mutated(rules, "the ambiguous tag",
                      "        if (!same) {\n            differs = YES;\n        }",
                      "        if (!same) {\n            differs = NO;\n        }\n"
                      "        break;"),
              cc, sdk)
    run_rules("a slot count written as text is parsed anyway",
              mutated(rules, "the text slot count",
                      "            if (![answer isKindOfClass:[NSNumber class]] ||\n"
                      "                !MLNumberIsIntegral((NSNumber *)answer) ||",
                      "            if ([answer isKindOfClass:[NSString class]]) {\n"
                      "                answer = @((long long)[(NSString *)answer longLongValue]);\n"
                      "            }\n"
                      "            if (![answer isKindOfClass:[NSNumber class]] ||\n"
                      "                !MLNumberIsIntegral((NSNumber *)answer) ||"),
              cc, sdk)
    run_rules("an upload is allowed while the slots are still unknown",
              mutated(rules, "the unknown slots",
                      "    return self.phase == MLDeviceRedirectionPhaseReady &&\n"
                      "           self.availableSlots != MLDeviceRedirectionSlotsUnknown &&\n"
                      "           self.availableSlots > 0;",
                      "    return self.phase == MLDeviceRedirectionPhaseReady;"),
              cc, sdk)
    run_rules("a closed session is reopened by the next request",
              mutated(rules, "the first reason",
                      "- (instancetype)sessionByRecordingRequest:(MLDeviceRedirectionChannel)channel {\n"
                      "    if (self.phase == MLDeviceRedirectionPhaseClosed) {\n        return self;",
                      "- (instancetype)sessionByRecordingRequest:(MLDeviceRedirectionChannel)channel {\n"
                      "    if (self.phase == MLDeviceRedirectionPhaseClosed) {\n"
                      "        return [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseAwaitingBind\n"
                      "                                         stop:MLDeviceRedirectionStopNone];"),
              cc, sdk)
    run_rules("any step may be asked in any order",
              mutated(rules, "the order",
                      "    if (self.phase != expected) {\n"
                      "        return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];",
                      "    if (self.phase != expected && self.phase != MLDeviceRedirectionPhaseIdle) {\n"
                      "        return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];"),
              cc, sdk)
    run_rules("a state answer with no slot count is read as a full host",
              mutated(rules, "the missing slot count",
                      "            reading = MLReadField(response.fields, MLStateSlotsTag, &answer);\n"
                      "            if (reading == MLFieldReadingAbsent) {\n"
                      "                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];",
                      "            reading = MLReadField(response.fields, MLStateSlotsTag, &answer);\n"
                      "            if (reading == MLFieldReadingAbsent) {\n"
                      "                return [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseClosed\n"
                      "                                                   stop:MLDeviceRedirectionStopNoSlots];"),
              cc, sdk)
    run_rules("a reply on one channel is read against another",
              mutated(rules, "the channel pairing",
                      "            if (self.phase != MLDeviceRedirectionPhaseAwaitingState) {\n"
                      "                return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];",
                      "            if (self.phase == MLDeviceRedirectionPhaseClosed) {\n"
                      "                return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];"),
              cc, sdk)
    run_rules("a session that spent a slot still offers the second device",
              mutated(rules, "the spent slot",
                      "                delivered.availableSlots = delivered.availableSlots - 1;",
                      "                delivered.availableSlots = delivered.availableSlots;"),
              cc, sdk)

    print("%d device-redirection-session failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
