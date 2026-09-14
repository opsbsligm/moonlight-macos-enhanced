//
//  PairManager.m
//  Moonlight
//
//  Created by Diego Waxemberg on 10/19/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "PairManager.h"
#import "CryptoManager.h"
#import "Utils.h"
#import "HttpResponse.h"
#import "HttpRequest.h"
#import "ServerInfoResponse.h"

#include <dispatch/dispatch.h>

@implementation PairManager {
    HttpManager* _httpManager;
    NSData* _clientCert;
    id<PairCallback> _callback;
}

- (id) initWithManager:(HttpManager*)httpManager clientCert:(NSData*)clientCert callback:(id<PairCallback>)callback {
    self = [super init];
    _httpManager = httpManager;
    _clientCert = clientCert;
    _callback = callback;
    return self;
}

- (void) main {
    // We have to call startPairing before calling any other _callback functions
    NSString* PIN = [self generatePIN];
    [_callback startPairing:PIN];
    
    ServerInfoResponse* serverInfoResp = [[ServerInfoResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:serverInfoResp withUrlRequest:[_httpManager newServerInfoRequest:false]
                                               fallbackError:401 fallbackRequest:[_httpManager newHttpServerInfoRequest]]];
    if ([serverInfoResp isStatusOk]) {
        if ([[serverInfoResp getStringTag:@"state"] hasSuffix:@"_SERVER_BUSY"]) {
            // The sentence belongs to the screen, not to the request that failed.
            [_callback pairFailedWithReason:PairFailureReasonHostBusy
                                     detail:@"the host is still running a previous session"];
        } else if (![[serverInfoResp getStringTag:@"PairStatus"] isEqual:@"1"]) {
            NSString* appversion = [serverInfoResp getStringTag:@"appversion"];
            if (appversion == nil || appversion.length == 0) {
                [_callback pairFailedWithReason:PairFailureReasonMalformedReply
                                         detail:@"Missing XML element"];
                return;
            }
            int serverMajorVersion = (appversion.length > 0) ? [[appversion substringToIndex:1] intValue] : 0;
            [self initiatePairWithPin:PIN forServerMajorVersion:serverMajorVersion];
        } else {
            [_callback alreadyPaired];
        }
    }
    else {
        // A negative status code is an NSURL error code: the request never got a
        // reply, which is a different decision from the host answering and refusing.
        [_callback pairFailedWithReason:(serverInfoResp.statusCode < 0 ?
                                         PairFailureReasonNetwork : PairFailureReasonRejected)
                                 detail:serverInfoResp.statusMessage];
    }
}

- (void) finishPairing:(OSBackgroundTaskIdentifier)bgId
           forResponse:(HttpResponse*)resp
     withFallbackError:(NSString*)errorMsg {
    // One fact, named once: a negative status code is an NSURL error code the HTTP
    // layer stored, which means the request never got an answer. That is the same
    // fact behind two decisions here -- do not undo a pairing the host may already
    // have accepted, and tell the screen this is worth trying another address for.
    BOOL networkLevelFailure = (resp != nil && resp.statusCode < 0);
    if (networkLevelFailure) {
        Log(LOG_W, @"Skipping unpair due to transient network error during pairing: %ld (%@)",
            (long)resp.statusCode,
            resp.statusMessage ?: @"Unknown error");
    }

    if (!networkLevelFailure) {
        [_httpManager executeRequestSynchronously:[HttpRequest requestWithUrlRequest:[_httpManager newUnpairRequest]]];
        // Clear any pinned server cert so a failed pairing doesn't leave stale cert pinning
        [_httpManager setServerCert:nil];
    }
    
    
#if TARGET_OS_IPHONE
    if (bgId != UIBackgroundTaskInvalid) {
        [[UIApplication sharedApplication] endBackgroundTask:bgId];
    }
#endif
    
    if (![resp isStatusOk]) {
        // Use the response error if the request failed
        errorMsg = resp.statusMessage;
    }

    // A sentence for the user belongs to the screen that shows it, so this reports
    // which kind of failure it was and leaves the wording there.
    PairFailureReason reason = (resp != nil && resp.statusCode == NSURLErrorTimedOut) ?
        PairFailureReasonTimeout : (networkLevelFailure ? PairFailureReasonNetwork
                                                        : PairFailureReasonRejected);

    [_callback pairFailedWithReason:reason detail:errorMsg];
}

- (void) finishPairing:(OSBackgroundTaskIdentifier)bgId withSuccess:(NSData*)derCertBytes {
#if TARGET_OS_IPHONE
    if (bgId != UIBackgroundTaskInvalid) {
        [[UIApplication sharedApplication] endBackgroundTask:bgId];
    }
#endif
    
    [_callback pairSuccessful:derCertBytes];
}

// All codepaths must call finishPairing exactly once before returning!
- (void) initiatePairWithPin:(NSString*)PIN forServerMajorVersion:(int)serverMajorVersion {
    Log(LOG_I, @"Pairing with generation %d server", serverMajorVersion);
    
    OSBackgroundTaskIdentifier bgId = 0;
#if TARGET_OS_IPHONE
    // Start a background task to help prevent the app from being killed
    // while pairing is in progress.
    bgId = [[UIApplication sharedApplication] beginBackgroundTaskWithName:@"Pairing PC" expirationHandler:^{
        Log(LOG_W, @"Background pairing time has expired!");
    }];
#endif
    
    NSData* salt = [self saltPIN:PIN];
    Log(LOG_I, @"PIN: %@, saltedPIN: %@", PIN, salt);
    
    HttpResponse* pairResp = [[HttpResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:pairResp withUrlRequest:[_httpManager newPairRequest:salt clientCert:_clientCert]]];
    if (![self verifyResponseStatus:pairResp]) {
        [self finishPairing:bgId forResponse:pairResp withFallbackError:@"Pairing was declined by the target."];
        return;
    }
    
    NSString* plainCert = [pairResp getStringTag:@"plaincert"];
    if ([plainCert length] == 0) {
        [self finishPairing:bgId forResponse:pairResp withFallbackError:@"Another pairing attempt is already in progress."];
        return;
    }
    
    // Pin the cert for TLS usage on this host
    NSData* derCertBytes = [CryptoManager pemToDer:[Utils hexToBytes:plainCert]];
    [_httpManager setServerCert:derCertBytes];
    
    CryptoManager* cryptoMan = [[CryptoManager alloc] init];
    NSData* aesKey;
    
    // Gen 7 servers use SHA256 to get the key
    int hashLength;
    if (serverMajorVersion >= 7) {
        aesKey = [cryptoMan createAESKeyFromSaltSHA256:salt];
        hashLength = 32;
    }
    else {
        aesKey = [cryptoMan createAESKeyFromSaltSHA1:salt];
        hashLength = 20;
    }
    
    NSData* randomChallenge = [Utils randomBytes:16];
    NSData* encryptedChallenge = [cryptoMan aesEncrypt:randomChallenge withKey:aesKey];
    
    HttpResponse* challengeResp = [[HttpResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:challengeResp withUrlRequest:[_httpManager newChallengeRequest:encryptedChallenge]]];
    if (![self verifyResponseStatus:challengeResp]) {
        [self finishPairing:bgId forResponse:challengeResp withFallbackError:@"Pairing stage #2 failed"];
        return;
    }
    
    NSData* encServerChallengeResp = [Utils hexToBytes:[challengeResp getStringTag:@"challengeresponse"]];
    NSData* decServerChallengeResp = [cryptoMan aesDecrypt:encServerChallengeResp withKey:aesKey];
    
    NSData* serverResponse = [decServerChallengeResp subdataWithRange:NSMakeRange(0, hashLength)];
    NSData* serverChallenge = [decServerChallengeResp subdataWithRange:NSMakeRange(hashLength, 16)];
    
    NSData* clientSecret = [Utils randomBytes:16];
    NSData* challengeRespHashInput = [self concatData:[self concatData:serverChallenge with:[CryptoManager getSignatureFromCert:_clientCert]] with:clientSecret];
    NSData* challengeRespHash;
    if (serverMajorVersion >= 7) {
        challengeRespHash = [cryptoMan SHA256HashData: challengeRespHashInput];
    }
    else {
        challengeRespHash = [cryptoMan SHA1HashData: challengeRespHashInput];
    }
    NSData* challengeRespEncrypted = [cryptoMan aesEncrypt:challengeRespHash withKey:aesKey];
    
    HttpResponse* secretResp = [[HttpResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:secretResp withUrlRequest:[_httpManager newChallengeRespRequest:challengeRespEncrypted]]];
    if (![self verifyResponseStatus:secretResp]) {
        [self finishPairing:bgId forResponse:secretResp withFallbackError:@"Pairing stage #3 failed"];
        return;
    }
    
    NSData* serverSecretResp = [Utils hexToBytes:[secretResp getStringTag:@"pairingsecret"]];
    NSData* serverSecret = [serverSecretResp subdataWithRange:NSMakeRange(0, 16)];
    NSData* serverSignature = [serverSecretResp subdataWithRange:NSMakeRange(16, 256)];
    
    if (![cryptoMan verifySignature:serverSecret withSignature:serverSignature andCert:[Utils hexToBytes:plainCert]]) {
        [self finishPairing:bgId forResponse:secretResp withFallbackError:@"Server certificate invalid"];
        return;
    }
    
    NSData* serverChallengeRespHashInput = [self concatData:[self concatData:randomChallenge with:[CryptoManager getSignatureFromCert:[Utils hexToBytes:plainCert]]] with:serverSecret];
    NSData* serverChallengeRespHash;
    if (serverMajorVersion >= 7) {
        serverChallengeRespHash = [cryptoMan SHA256HashData: serverChallengeRespHashInput];
    }
    else {
        serverChallengeRespHash = [cryptoMan SHA1HashData: serverChallengeRespHashInput];
    }
    if (![serverChallengeRespHash isEqual:serverResponse]) {
        [self finishPairing:bgId forResponse:secretResp withFallbackError:@"Incorrect PIN"];
        return;
    }
    
    NSData* clientPairingSecret = [self concatData:clientSecret with:[cryptoMan signData:clientSecret withKey:[CryptoManager readKeyFromFile]]];
    HttpResponse* clientSecretResp = [[HttpResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:clientSecretResp withUrlRequest:[_httpManager newClientSecretRespRequest:[Utils bytesToHex:clientPairingSecret]]]];
    if (![self verifyResponseStatus:clientSecretResp]) {
        [self finishPairing:bgId forResponse:clientSecretResp withFallbackError:@"Pairing stage #4 failed"];
        return;
    }
    
    HttpResponse* clientPairChallengeResp = [[HttpResponse alloc] init];
    [_httpManager executeRequestSynchronously:[HttpRequest requestForResponse:clientPairChallengeResp withUrlRequest:[_httpManager newPairChallenge]]];
    if (![self verifyResponseStatus:clientPairChallengeResp]) {
        [self finishPairing:bgId forResponse:clientPairChallengeResp withFallbackError:@"Pairing stage #5 failed"];
        return;
    }
    
    [self finishPairing:bgId withSuccess:derCertBytes];
}

// Caller calls finishPairing for us on failure
- (BOOL) verifyResponseStatus:(HttpResponse*)resp {
    if (![resp isStatusOk]) {
        return false;
    } else {
        NSInteger pairedStatus;
        
        if (![resp getIntTag:@"paired" value:&pairedStatus]) {
            return false;
        }
        
        return pairedStatus == 1;
    }
}

- (NSData*) concatData:(NSData*)data with:(NSData*)moreData {
    NSMutableData* concatData = [[NSMutableData alloc] initWithData:data];
    [concatData appendData:moreData];
    return concatData;
}

- (NSString*) generatePIN {
    NSString* PIN = [NSString stringWithFormat:@"%d%d%d%d",
                     arc4random_uniform(10), arc4random_uniform(10),
                     arc4random_uniform(10), arc4random_uniform(10)];
    return PIN;
}

- (NSData*) saltPIN:(NSString*)PIN {
    NSMutableData* saltedPIN = [[NSMutableData alloc] initWithCapacity:20];
    [saltedPIN appendData:[Utils randomBytes:16]];
    [saltedPIN appendBytes:[PIN UTF8String] length:4];
    return saltedPIN;
}

@end
