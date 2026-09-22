//
//  DeviceRedirectionSession.h
//  Moonlight
//
//  When a device may be handed to a host that said it could take one.
//
//  Stage 0 decides whether a device may be offered at all, and Stage 1 reads the device.
//  What is left is order: the host advertised a capability over one channel, then a bind,
//  then a state request, then an upload, and each step can be refused, answered badly, or
//  not answered at all. Stage 2 of docs/usb-redirection-design.md is that sequence, and
//  this file is the half of it the client owns.
//
//  What this file deliberately does not claim: the wire format. The three calls in
//  docs/usb-redirection-host-contract.md 4 -- bind, request state, upload -- do not exist
//  in moonlight-common-c or in any host, so no tag name here is a report about the wire.
//  `usbRedirection` comes from contract 3, which is a proposal with a named field; the rest
//  are the names the in-repo reference responder uses. That is why nothing here is wired
//  into the stream start path: sequencing is ours to get right today, encoding is not.
//
//  What is ours, and therefore asserted: a step never runs before the step before it was
//  accepted; an answer that is not an explicit yes is a no; a response that says two
//  different things about one field is not resolved by picking either; a message on a
//  channel nobody defined ends the session rather than being skipped; and the first reason
//  a session died is the reason it reports, whatever happens after it.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// The three exchanges of contract 4, in the only order any of them can happen. A response
/// arrives on one of these too, which is what lets a reply to a request that was never sent
/// be recognised as one instead of being read as an answer to something else.
typedef NS_ENUM(NSInteger, MLDeviceRedirectionChannel) {
    MLDeviceRedirectionChannelBind = 1,
    MLDeviceRedirectionChannelState = 2,
    MLDeviceRedirectionChannelItem = 3,
};

/// Where the exchange stands. Every transition is recorded by a message, never by a clock,
/// so a run of this file replays identically on a machine whose clock is wrong.
typedef NS_ENUM(NSInteger, MLDeviceRedirectionPhase) {
    /// Nothing asked. Only a host that advertised the capability leaves a session here.
    MLDeviceRedirectionPhaseIdle = 0,
    MLDeviceRedirectionPhaseAwaitingBind = 1,
    MLDeviceRedirectionPhaseBound = 2,
    MLDeviceRedirectionPhaseAwaitingState = 3,
    /// Slots are known and at least one is free: an upload may start.
    MLDeviceRedirectionPhaseReady = 4,
    MLDeviceRedirectionPhaseUploading = 5,
    /// No further exchange is possible, and the session must not be reused for a second
    /// device: a stale "there were slots" must not outlive the connection it was learned on.
    MLDeviceRedirectionPhaseClosed = 6,
};

/// Why a session is closed, or why a step is not allowed. One spelling each, shared with the
/// log line, because "the host did not take it" is not something a supporter can act on.
typedef NS_ENUM(NSInteger, MLDeviceRedirectionStop) {
    MLDeviceRedirectionStopNone = 0,
    MLDeviceRedirectionStopHostNotAdvertised = 1,
    MLDeviceRedirectionStopBindRefused = 2,
    MLDeviceRedirectionStopBindUnanswered = 3,
    MLDeviceRedirectionStopStateRefused = 4,
    MLDeviceRedirectionStopStateUnanswered = 5,
    /// The host answered with an explicit zero. Different from the next one, and the
    /// difference is the whole point: one is a full host, the other is a host that did not
    /// answer the question.
    MLDeviceRedirectionStopNoSlots = 6,
    MLDeviceRedirectionStopItemRefused = 7,
    MLDeviceRedirectionStopItemUnanswered = 8,
    /// Asked for state before binding, or uploaded before asking for state.
    MLDeviceRedirectionStopStepOutOfOrder = 9,
    /// A response on a channel this contract does not define. Skipping it would let the next
    /// message be read against the wrong step.
    MLDeviceRedirectionStopUnknownChannel = 10,
    /// One field answered twice with two different values. There is no safe way to choose.
    MLDeviceRedirectionStopAmbiguousResponse = 11,
    /// A field the contract requires is missing, or carries a value that cannot be read.
    /// Treated as a host that implements something other than this contract.
    MLDeviceRedirectionStopMalformedResponse = 12,
};

/// The name used in the log line and by anything Stage 2 shows a player. Two spellings of
/// one refusal is a support thread nobody can follow.
FOUNDATION_EXPORT NSString *MLDeviceRedirectionStopName(MLDeviceRedirectionStop stop);
FOUNDATION_EXPORT NSString *MLDeviceRedirectionPhaseName(MLDeviceRedirectionPhase phase);
/// The name of a channel this session cannot speak, for a line about an unexpected message.
FOUNDATION_EXPORT NSString *MLDeviceRedirectionChannelName(MLDeviceRedirectionChannel channel);

/// One field of a host answer, kept in the order it arrived. Fields are a list rather than
/// a dictionary because the answers this contract is modelled on are `root.a=1&root.b=2`
/// text: a dictionary cannot represent the same name arriving twice, and "the host said two
/// different things about one field" is a real answer that has to reach the code as one.
@interface MLDeviceRedirectionField : NSObject
@property(nonatomic, readonly, copy) NSString *name;
/// nil models "the field was there and carried nothing", which is not the same event as the
/// field being absent: a tag with an empty value is a host that tried to answer.
@property(nonatomic, readonly, nullable, strong) id value;
+ (instancetype)fieldNamed:(NSString *)name value:(nullable id)value;
@end

/// One host answer, on one channel, in field order.
@interface MLDeviceRedirectionHostResponse : NSObject
@property(nonatomic, readonly) MLDeviceRedirectionChannel channel;
@property(nonatomic, readonly, copy) NSArray<MLDeviceRedirectionField *> *fields;
+ (instancetype)responseOnChannel:(MLDeviceRedirectionChannel)channel
                           fields:(NSArray<MLDeviceRedirectionField *> *)fields;
@end

/// The sequence itself. Immutable and returned fresh from every step, because a session that
/// can be mutated in place is a session whose stale answer can be read twice.
@interface MLDeviceRedirectionSession : NSObject
@property(nonatomic, readonly) MLDeviceRedirectionPhase phase;
@property(nonatomic, readonly) MLDeviceRedirectionStop stop;
/// Slots the host said are free, or MLDeviceRedirectionSlotsUnknown when it has not said. Zero is a
/// real answer and is never used to mean "unknown".
@property(nonatomic, readonly) NSInteger availableSlots;
/// The only three questions the stream path would ever ask. Each is true in exactly one
/// place in the sequence, and a session that is closed never returns true for any of them.
@property(nonatomic, readonly) BOOL mayRequestBind;
@property(nonatomic, readonly) BOOL mayRequestState;
@property(nonatomic, readonly) BOOL mayUploadDeviceDescriptor;
/// One line, safe to log: no device, no serial, no host address. It says which step the
/// session reached and why it stopped there.
@property(nonatomic, readonly, copy) NSString *auditLine;

/// A session for a host's `/serverinfo` fields. Only `usbRedirection` answered yes leaves a
/// session in Idle; everything else -- missing, `0`, `""`, `yes`, `2`, the name in another
/// case, the name twice with two values -- closes it, and closes it with the same reason a
/// host that never heard of the field gets.
+ (instancetype)sessionFromServerInfoFields:(NSArray<MLDeviceRedirectionField *> *)serverInfoFields;

/// Records that this side asked. Asking out of order closes the session.
- (instancetype)sessionByRecordingRequest:(MLDeviceRedirectionChannel)channel;
/// Records a host answer. Unknown channels and unreadable answers close the session.
- (instancetype)sessionByRecordingResponse:(MLDeviceRedirectionHostResponse *)response;
/// Records that an answer never came. The caller owns the clock and reports the fact; a
/// session that read the time itself could not be replayed, and a run of these cases on a
/// machine with a broken clock would otherwise disagree with one that is not.
- (instancetype)sessionByRecordingTimeoutOnChannel:(MLDeviceRedirectionChannel)channel;
@end

/// Slots when the host has not answered the question. Not zero: zero means the host is full,
/// and a caller that cannot tell the two apart retries a full host forever or refuses a host
/// that merely has not replied yet.
FOUNDATION_EXPORT const NSInteger MLDeviceRedirectionSlotsUnknown;

NS_ASSUME_NONNULL_END
