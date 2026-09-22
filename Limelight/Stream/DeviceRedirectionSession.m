//
//  DeviceRedirectionSession.m
//  Moonlight
//

#import "DeviceRedirectionSession.h"

// The one tag with a name in the contract (docs/usb-redirection-host-contract.md 3). It is
// spelled once, here, so a session and the Stage 0 policy cannot drift into asking about two
// different fields and reporting the same "host does not support it" for both.
static NSString *const MLServerInfoRedirectionTag = @"usbRedirection";

// These three have no name in any contract, because no host implements stage 2. They are the
// names the in-repo reference responder answers with, and nothing more: a real host that
// agrees on sequencing but not on spelling needs these four strings changed and nothing else.
// Saying which names are guesses is the difference between a proposal and a fabrication.
static NSString *const MLBindAnswerTag = @"usbRedirectionBound";
static NSString *const MLStateSlotsTag = @"usbRedirectionSlots";
static NSString *const MLItemAnswerTag = @"usbRedirectionAccepted";

// The USB spec addresses a device with seven bits, so 127 is the most a host could fill and
// still be describing a bus. An answer above that is a host that mis-encoded something, and
// believing it would mean uploading more devices than any host could hold.
static const long long MLHostSlotCeiling = 127;

const NSInteger MLDeviceRedirectionSlotsUnknown = NSIntegerMin;

static BOOL MLNameHasChar(const char *name, char candidate) {
    for (; *name; name++) {
        if (*name == candidate) {
            return YES;
        }
    }
    return NO;
}

/// Whether a number says a whole count. A host that answers 2.7 slots is describing something
/// other than slots, and taking the 2 out of it would be the same mistake as reading a
/// vendor id out of half a hex string: the value arrives usable and the device is wrong.
static BOOL MLNumberIsIntegral(NSNumber *number) {
    const char *type = number.objCType;
    return type != NULL && type[0] != '\0' && type[0] != 'f' && type[0] != 'd' &&
           type[0] != 'B' && MLNameHasChar("cCSsSlLiqQ", type[0]);
}

NSString *MLDeviceRedirectionStopName(MLDeviceRedirectionStop stop) {
    switch (stop) {
        case MLDeviceRedirectionStopNone: return @"none";
        case MLDeviceRedirectionStopHostNotAdvertised: return @"host-not-advertised";
        case MLDeviceRedirectionStopBindRefused: return @"bind-refused";
        case MLDeviceRedirectionStopBindUnanswered: return @"bind-unanswered";
        case MLDeviceRedirectionStopStateRefused: return @"state-refused";
        case MLDeviceRedirectionStopStateUnanswered: return @"state-unanswered";
        case MLDeviceRedirectionStopNoSlots: return @"no-slots";
        case MLDeviceRedirectionStopItemRefused: return @"item-refused";
        case MLDeviceRedirectionStopItemUnanswered: return @"item-unanswered";
        case MLDeviceRedirectionStopStepOutOfOrder: return @"step-out-of-order";
        case MLDeviceRedirectionStopUnknownChannel: return @"unknown-channel";
        case MLDeviceRedirectionStopAmbiguousResponse: return @"ambiguous-response";
        case MLDeviceRedirectionStopMalformedResponse: return @"malformed-response";
    }
    return @"unknown-stop";
}

NSString *MLDeviceRedirectionPhaseName(MLDeviceRedirectionPhase phase) {
    switch (phase) {
        case MLDeviceRedirectionPhaseIdle: return @"idle";
        case MLDeviceRedirectionPhaseAwaitingBind: return @"awaiting-bind";
        case MLDeviceRedirectionPhaseBound: return @"bound";
        case MLDeviceRedirectionPhaseAwaitingState: return @"awaiting-state";
        case MLDeviceRedirectionPhaseReady: return @"ready";
        case MLDeviceRedirectionPhaseUploading: return @"uploading";
        case MLDeviceRedirectionPhaseClosed: return @"closed";
    }
    return @"unknown-phase";
}

NSString *MLDeviceRedirectionChannelName(MLDeviceRedirectionChannel channel) {
    switch (channel) {
        case MLDeviceRedirectionChannelBind: return @"bind";
        case MLDeviceRedirectionChannelState: return @"state";
        case MLDeviceRedirectionChannelItem: return @"item";
    }
    return @"unknown-channel";
}

@implementation MLDeviceRedirectionField

+ (instancetype)fieldNamed:(NSString *)name value:(nullable id)value {
    MLDeviceRedirectionField *field = [[MLDeviceRedirectionField alloc] init];
    field->_name = [name copy];
    field->_value = value;
    return field;
}

@end

@implementation MLDeviceRedirectionHostResponse

+ (instancetype)responseOnChannel:(MLDeviceRedirectionChannel)channel
                           fields:(NSArray<MLDeviceRedirectionField *> *)fields {
    MLDeviceRedirectionHostResponse *response =
        [[MLDeviceRedirectionHostResponse alloc] init];
    response->_channel = channel;
    response->_fields = [fields copy];
    return response;
}

@end

/// How a host answered one field. Absent and Ambiguous are states rather than nil, because
/// both have to be reported differently in the log and both refuse an upload for a different
/// reason than a host that said no.
typedef NS_ENUM(NSInteger, MLFieldReading) {
    MLFieldReadingAbsent = 0,
    MLFieldReadingAnswered,
    MLFieldReadingAmbiguous,
};

/// The value of one named field, read case-sensitively. A tag in another case is a different
/// tag: a host that meant to answer would have answered, and reading `USBRedirection` as
/// `usbRedirection` is how an old host becomes a new one by accident.
static MLFieldReading MLReadField(NSArray<MLDeviceRedirectionField *> *fields,
                                 NSString *name, id *value) {
    id found = nil;
    BOOL seen = NO;
    BOOL differs = NO;
    for (MLDeviceRedirectionField *field in fields) {
        if (![field.name isEqualToString:name]) {
            continue;
        }
        if (!seen) {
            found = field.value;
            seen = YES;
            continue;
        }
        // Two copies of one tag agreeing is one answer; disagreeing is two. Picking either
        // would let the same bytes authorise a device on one parse and refuse it on another.
        const BOOL same = (found == nil && field.value == nil) ||
                          (found != nil && field.value != nil && [found isEqual:field.value]);
        if (!same) {
            differs = YES;
        }
    }
    if (!seen) {
        return MLFieldReadingAbsent;
    }
    if (differs) {
        return MLFieldReadingAmbiguous;
    }
    *value = found;
    return MLFieldReadingAnswered;
}

/// Only an explicit yes is a yes. Foundation erases the difference between `@1` and `@YES`,
/// so this accepts both and refuses everything else, including the text `yes`: a host that
/// writes the truth in prose is a host that will also write `no` in some prose nobody agreed
/// on, and the reading that survives a disagreement is the one that refused in the meantime.
static BOOL MLAnswerIsYes(id value) {
    if ([value isKindOfClass:[NSNumber class]]) {
        return [(NSNumber *)value integerValue] == 1;
    }
    if ([value isKindOfClass:[NSString class]]) {
        return [(NSString *)value isEqualToString:@"1"];
    }
    return NO;
}

@interface MLDeviceRedirectionSession ()
@property(nonatomic, readwrite) MLDeviceRedirectionPhase phase;
@property(nonatomic, readwrite) MLDeviceRedirectionStop stop;
@property(nonatomic, readwrite) NSInteger availableSlots;
@end

@implementation MLDeviceRedirectionSession

+ (instancetype)sessionFromServerInfoFields:(NSArray<MLDeviceRedirectionField *> *)serverInfoFields {
    MLDeviceRedirectionSession *session = [[MLDeviceRedirectionSession alloc] init];
    session.availableSlots = MLDeviceRedirectionSlotsUnknown;
    id answer = nil;
    const MLFieldReading reading = MLReadField(serverInfoFields ?: @[], MLServerInfoRedirectionTag,
                                               &answer);
    if (reading == MLFieldReadingAbsent) {
        // The common case: a host that has never heard of the field. This is the answer an
        // un-upgraded host and a host that forgot to send it share, and it is a refusal.
        session.phase = MLDeviceRedirectionPhaseClosed;
        session.stop = MLDeviceRedirectionStopHostNotAdvertised;
        return session;
    }
    if (reading == MLFieldReadingAmbiguous) {
        session.phase = MLDeviceRedirectionPhaseClosed;
        session.stop = MLDeviceRedirectionStopAmbiguousResponse;
        return session;
    }
    if (!MLAnswerIsYes(answer)) {
        session.phase = MLDeviceRedirectionPhaseClosed;
        session.stop = MLDeviceRedirectionStopHostNotAdvertised;
        return session;
    }
    session.phase = MLDeviceRedirectionPhaseIdle;
    session.stop = MLDeviceRedirectionStopNone;
    return session;
}

/// A closed session is closed for its first reason. Later mistakes are true as well, but a
/// log that reports the last one turns a host that never advertised into a host that
/// misbehaved, and the two have different owners.
- (instancetype)sessionByCarryingIntoPhase:(MLDeviceRedirectionPhase)phase stop:(MLDeviceRedirectionStop)stop {
    MLDeviceRedirectionSession *next = [[MLDeviceRedirectionSession alloc] init];
    next.phase = phase;
    next.stop = stop;
    next.availableSlots = self.availableSlots;
    return next;
}

- (instancetype)sessionByClosing:(MLDeviceRedirectionStop)stop {
    return [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseClosed stop:stop];
}

- (instancetype)sessionByRecordingRequest:(MLDeviceRedirectionChannel)channel {
    if (self.phase == MLDeviceRedirectionPhaseClosed) {
        return self;
    }
    const MLDeviceRedirectionPhase expected =
        channel == MLDeviceRedirectionChannelBind ? MLDeviceRedirectionPhaseIdle :
        channel == MLDeviceRedirectionChannelState ? MLDeviceRedirectionPhaseBound :
        channel == MLDeviceRedirectionChannelItem ? MLDeviceRedirectionPhaseReady :
                                                     MLDeviceRedirectionPhaseClosed;
    if (self.phase != expected) {
        return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];
    }
    const MLDeviceRedirectionPhase waiting =
        channel == MLDeviceRedirectionChannelBind ? MLDeviceRedirectionPhaseAwaitingBind :
        channel == MLDeviceRedirectionChannelState ? MLDeviceRedirectionPhaseAwaitingState :
                                                     MLDeviceRedirectionPhaseUploading;
    return [self sessionByCarryingIntoPhase:waiting stop:MLDeviceRedirectionStopNone];
}

- (instancetype)sessionByRecordingResponse:(MLDeviceRedirectionHostResponse *)response {
    if (self.phase == MLDeviceRedirectionPhaseClosed) {
        return self;
    }
    const MLDeviceRedirectionChannel channel = response.channel;
    if (channel != MLDeviceRedirectionChannelBind && channel != MLDeviceRedirectionChannelState &&
        channel != MLDeviceRedirectionChannelItem) {
        // Ignoring it would leave the session waiting for the message that was actually
        // coming, and the reply that follows would be read against the wrong step.
        return [self sessionByClosing:MLDeviceRedirectionStopUnknownChannel];
    }
    id answer = nil;
    MLFieldReading reading = MLFieldReadingAbsent;
    switch (channel) {
        case MLDeviceRedirectionChannelBind: {
            if (self.phase != MLDeviceRedirectionPhaseAwaitingBind) {
                return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];
            }
            reading = MLReadField(response.fields, MLBindAnswerTag, &answer);
            if (reading == MLFieldReadingAbsent) {
                // A reply that did not answer the question. Silent here would look like a
                // host that was merely slow, and slow hosts get retried.
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            if (reading == MLFieldReadingAmbiguous) {
                return [self sessionByClosing:MLDeviceRedirectionStopAmbiguousResponse];
            }
            if (answer == nil) {
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            if (MLAnswerIsYes(answer)) {
                return [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseBound
                                                   stop:MLDeviceRedirectionStopNone];
            }
            if ([answer isKindOfClass:[NSNumber class]] ||
                [answer isKindOfClass:[NSString class]]) {
                return [self sessionByClosing:MLDeviceRedirectionStopBindRefused];
            }
            return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
        }
        case MLDeviceRedirectionChannelState: {
            if (self.phase != MLDeviceRedirectionPhaseAwaitingState) {
                return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];
            }
            reading = MLReadField(response.fields, MLStateSlotsTag, &answer);
            if (reading == MLFieldReadingAbsent) {
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            if (reading == MLFieldReadingAmbiguous) {
                return [self sessionByClosing:MLDeviceRedirectionStopAmbiguousResponse];
            }
            NSInteger slots = 0;
            if (![answer isKindOfClass:[NSNumber class]] ||
                !MLNumberIsIntegral((NSNumber *)answer) ||
                (slots = (NSInteger)[(NSNumber *)answer longLongValue]) < 0 ||
                slots > (NSInteger)MLHostSlotCeiling) {
                // Includes the text `2`: a count written as prose is not a count, and a
                // client that parsed it would upload to a host that reported no slots at all.
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            if (slots == 0) {
                // The host is full, which is an answer and not a fault. Retrying it is the
                // caller's business; saying "unknown" here would hide that it answered.
                return [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseClosed
                                                   stop:MLDeviceRedirectionStopNoSlots];
            }
            MLDeviceRedirectionSession *ready =
                [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseReady
                                            stop:MLDeviceRedirectionStopNone];
            ready.availableSlots = slots;
            return ready;
        }
        default: {
            if (self.phase != MLDeviceRedirectionPhaseUploading) {
                return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];
            }
            reading = MLReadField(response.fields, MLItemAnswerTag, &answer);
            if (reading == MLFieldReadingAbsent || answer == nil) {
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            if (reading == MLFieldReadingAmbiguous) {
                return [self sessionByClosing:MLDeviceRedirectionStopAmbiguousResponse];
            }
            if (!MLAnswerIsYes(answer)) {
                if ([answer isKindOfClass:[NSNumber class]] ||
                    [answer isKindOfClass:[NSString class]]) {
                    return [self sessionByClosing:MLDeviceRedirectionStopItemRefused];
                }
                return [self sessionByClosing:MLDeviceRedirectionStopMalformedResponse];
            }
            MLDeviceRedirectionSession *delivered =
                [self sessionByCarryingIntoPhase:MLDeviceRedirectionPhaseReady
                                            stop:MLDeviceRedirectionStopNone];
            if (delivered.availableSlots != MLDeviceRedirectionSlotsUnknown) {
                delivered.availableSlots = delivered.availableSlots - 1;
            }
            return delivered;
        }
    }
}

- (instancetype)sessionByRecordingTimeoutOnChannel:(MLDeviceRedirectionChannel)channel {
    if (self.phase == MLDeviceRedirectionPhaseClosed) {
        return self;
    }
    if ((channel == MLDeviceRedirectionChannelBind &&
         self.phase != MLDeviceRedirectionPhaseAwaitingBind) ||
        (channel == MLDeviceRedirectionChannelState &&
         self.phase != MLDeviceRedirectionPhaseAwaitingState) ||
        (channel == MLDeviceRedirectionChannelItem &&
         self.phase != MLDeviceRedirectionPhaseUploading)) {
        return [self sessionByClosing:MLDeviceRedirectionStopStepOutOfOrder];
    }
    return [self sessionByClosing:channel == MLDeviceRedirectionChannelBind
                                    ? MLDeviceRedirectionStopBindUnanswered
                                : channel == MLDeviceRedirectionChannelState
                                    ? MLDeviceRedirectionStopStateUnanswered
                                    : MLDeviceRedirectionStopItemUnanswered];
}

- (BOOL)mayRequestBind {
    return self.phase == MLDeviceRedirectionPhaseIdle;
}

- (BOOL)mayRequestState {
    // Bound and not yet asking: a second state request while one is outstanding would be a
    // second answer waiting to disagree with the first.
    return self.phase == MLDeviceRedirectionPhaseBound;
}

- (BOOL)mayUploadDeviceDescriptor {
    // Unknown slots never authorises an upload: "the host has not said how full it is" and
    // "the host has room" are different claims about the world.
    return self.phase == MLDeviceRedirectionPhaseReady &&
           self.availableSlots != MLDeviceRedirectionSlotsUnknown &&
           self.availableSlots > 0;
}

- (NSString *)auditLine {
    NSString *slots = self.availableSlots == MLDeviceRedirectionSlotsUnknown
        ? @"unknown"
        : [NSString stringWithFormat:@"%ld", (long)self.availableSlots];
    return [NSString stringWithFormat:@"device redirection session: step=%@ stop=%@ slots=%@",
                                      MLDeviceRedirectionPhaseName(self.phase),
                                      MLDeviceRedirectionStopName(self.stop), slots];
}

@end
