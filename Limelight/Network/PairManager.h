//
//  PairManager.h
//  Moonlight
//
//  Created by Diego Waxemberg on 10/19/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "HttpManager.h"

// What actually went wrong, decided where the failure is known. It used to be a
// single sentence, and the screen that received it had to guess the difference
// between a host that refused and a network that never answered by looking for
// words in it -- "timeout", "network", and their Chinese equivalents -- so the
// retry fired or did not fire depending on which language the failure happened to
// be described in, and a rewording of either side changed the behaviour silently.
typedef NS_ENUM(NSInteger, PairFailureReason) {
    PairFailureReasonHostBusy,       // a session is still running on the host
    PairFailureReasonMalformedReply, // the host answered without a required element
    PairFailureReasonNetwork,        // the request never completed: worth retrying
    PairFailureReasonTimeout,        // it waited for an answer that never came
    PairFailureReasonRejected,       // the host answered and refused
};

@protocol PairCallback <NSObject>

- (void) startPairing:(NSString*)PIN;
- (void) pairSuccessful:(NSData*)serverCert;

// The detail is whatever the host or the network layer said, for a log and a
// fallback line of text. It is not what decides anything: reason is.
- (void) pairFailedWithReason:(PairFailureReason)reason detail:(NSString*)detail;
- (void) alreadyPaired;

@end

@interface PairManager : NSOperation
- (id) initWithManager:(HttpManager*)httpManager clientCert:(NSData*)clientCert callback:(id<PairCallback>)callback;
@end
