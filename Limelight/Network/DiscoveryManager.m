//
//  DiscoveryManager.m
//  Moonlight
//
//  Created by Diego Waxemberg on 1/1/15.
//  Copyright (c) 2015 Moonlight Stream. All rights reserved.
//

#import "DiscoveryManager.h"
#import "CryptoManager.h"
#import "HttpManager.h"
#import "Utils.h"
#import "DataManager.h"
#import "DiscoveryWorker.h"
#import "ServerInfoResponse.h"
#import "IdManager.h"

#include <Limelight.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netdb.h>

static NSString * const MoonlightAutoDiscoverNewHostsDefaultsKey = @"autoDiscoverNewHosts";

static BOOL MoonlightShouldAutoDiscoverNewHosts(void) {
    id value = [[NSUserDefaults standardUserDefaults] objectForKey:MoonlightAutoDiscoverNewHostsDefaultsKey];
    if (value == nil) {
        return YES;
    }

    return [[NSUserDefaults standardUserDefaults] boolForKey:MoonlightAutoDiscoverNewHostsDefaultsKey];
}

@implementation DiscoveryManager {
    NSMutableArray* _hostQueue;
    NSMutableSet* _pausedHosts;
    id<DiscoveryCallback> _callback;
    MDNSManager* _mdnsMan;
    NSOperationQueue* _opQueue;
    NSString* _uniqueId;
    NSData* _cert;
    BOOL shouldDiscover;
}

- (id)initWithHosts:(NSArray *)hosts andCallback:(id<DiscoveryCallback>)callback {
    self = [super init];
    
    // Using addHostToDiscovery ensures no duplicates
    // will make it into the list from the database
    _callback = callback;
    shouldDiscover = NO;
    _hostQueue = [NSMutableArray array];
    _pausedHosts = [NSMutableSet set];
    for (TemporaryHost* host in hosts)
    {
        [self addHostToDiscovery:host];
    }
    [_callback updateAllHosts:_hostQueue];
    
    _opQueue = [[NSOperationQueue alloc] init];
    _mdnsMan = [[MDNSManager alloc] initWithCallback:self];
    [CryptoManager generateKeyPairUsingSSL];
    _uniqueId = [IdManager getUniqueId];
    _cert = [CryptoManager readCertFromFile];
    return self;
}

+ (BOOL) isAddressLAN:(in_addr_t)addr {
    addr = htonl(addr);
    
    // 10.0.0.0/8
    if ((addr & 0xFF000000) == 0x0A000000) {
        return YES;
    }
    // 172.16.0.0/12
    else if ((addr & 0xFFF00000) == 0xAC100000) {
        return YES;
    }
    // 192.168.0.0/16
    else if ((addr & 0xFFFF0000) == 0xC0A80000) {
        return YES;
    }
    // 169.254.0.0/16
    else if ((addr & 0xFFFF0000) == 0xA9FE0000) {
        return YES;
    }
    // 100.64.0.0/10 - RFC6598 official CGN address (shouldn't see this in a LAN)
    else if ((addr & 0xFFC00000) == 0x64400000) {
        return YES;
    }
    
    return NO;
}

// This ensures that only RFC 1918 IPv4 addresses can be passed to
// the Add PC dialog. This is required to comply with Apple App Store
// Guideline 4.2.7a.
+ (BOOL) isProhibitedAddress:(NSString*)address {
#ifdef ENABLE_APP_STORE_RESTRICTIONS
    struct addrinfo hints;
    struct addrinfo* result;
    int err;
    
    NSString* hostAddress;
    [Utils parseAddress:address intoHost:&hostAddress andPort:nil];

    // We're explicitly using AF_INET here because we don't want to
    // ever receive a synthesized IPv6 address here, even on NAT64.
    // IPv6 addresses are not restricted here because we cannot easily
    // tell whether they are local or not.
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    err = getaddrinfo([hostAddress UTF8String], NULL, &hints, &result);
    if (err != 0 || result == NULL) {
        Log(LOG_W, @"getaddrinfo(%@) failed: %d", hostAddress, err);
        return NO;
    }
    
    if (result->ai_family != AF_INET) {
        // This should never happen due to our hints
        assert(result->ai_family == AF_INET);
        Log(LOG_W, @"Unexpected address family: %d", result->ai_family);
        freeaddrinfo(result);
        return NO;
    }
    
    BOOL ret = ![DiscoveryManager isAddressLAN:((struct sockaddr_in*)result->ai_addr)->sin_addr.s_addr];
    freeaddrinfo(result);

    return ret;
#else
    return NO;
#endif
}

- (ServerInfoResponse*) getServerInfoResponseForAddress:(NSString*)address {
    // Parse host and explicit port from address string. We need to handle
    // the port correctly for both HTTPS and HTTP fallback requests.
    NSString *hostPart = nil;
    NSString *portPart = nil;
    [Utils parseAddress:address intoHost:&hostPart andPort:&portPart];
    if (hostPart.length == 0) {
        hostPart = address;
    }

    NSString *httpsPort;
    NSString *httpPort;

    if (portPart.length > 0) {
        // Explicit port supplied. Determine whether it's an HTTPS or HTTP port.
        // Known HTTPS GameStream API ports: 47984, 49984, 57984 (and any ending in 4)
        // Known HTTP GameStream API ports: 47989, 49989, 57989 (and any ending in 9)
        // WebUI ports: 47990, 49990, 57990 — the GameStream API ports are at
        //   WebUI - 6 (HTTPS) and WebUI - 1 (HTTP). E.g. 47990 -> 47984 / 47989.
        NSInteger portVal = portPart.integerValue;
        switch (portVal) {
            case 47984: case 49984: case 57984:
                // This is an HTTPS API port
                httpsPort = portPart;
                httpPort = [NSString stringWithFormat:@"%ld", (long)(portVal + 5)];
                break;
            case 47989: case 49989: case 57989:
                // This is an HTTP API port
                httpsPort = [NSString stringWithFormat:@"%ld", (long)(portVal - 5)];
                httpPort = portPart;
                break;
            case 47990: case 49990: case 57990:
                // WebUI port — HTTPS API is port-6, HTTP API is port-1
                httpsPort = [NSString stringWithFormat:@"%ld", (long)(portVal - 6)];
                httpPort  = [NSString stringWithFormat:@"%ld", (long)(portVal - 1)];
                break;
            default:
                // Unknown port — use a heuristic based on the last digit to
                // decide whether it's a WebUI, HTTPS, or HTTP port. This keeps
                // custom Sunshine ports (e.g. 48990, 55990) from being
                // misclassified as plain HTTP ports.
                switch (portVal % 10) {
                    case 0:
                        // WebUI port — HTTPS API is port-6, HTTP API is port-1
                        httpsPort = [NSString stringWithFormat:@"%ld", (long)(portVal - 6)];
                        httpPort  = [NSString stringWithFormat:@"%ld", (long)(portVal - 1)];
                        break;
                    case 4:
                        // HTTPS API port
                        httpsPort = portPart;
                        httpPort = [NSString stringWithFormat:@"%ld", (long)(portVal + 5)];
                        break;
                    case 9:
                        // HTTP API port
                        httpsPort = [NSString stringWithFormat:@"%ld", (long)(portVal - 5)];
                        httpPort = portPart;
                        break;
                    default:
                        // Conservative fallback — treat as HTTP port
                        httpsPort = [NSString stringWithFormat:@"%ld", (long)(portVal - 5)];
                        httpPort = portPart;
                        break;
                }
                break;
        }
    } else {
        // No port — use standard defaults
        httpsPort = @"47984";
        httpPort = @"47989";
    }

    HttpManager* hMan = [[HttpManager alloc] initWithHost:hostPart
                                              httpsPort:httpsPort
                                                httpPort:httpPort
                                                uniqueId:_uniqueId
                                              serverCert:nil];
    ServerInfoResponse* serverInfoResponse = [[ServerInfoResponse alloc] init];

    NSURLRequest *httpsReq = [hMan newServerInfoRequest:true];
    NSURLRequest *httpReq = [hMan newHttpServerInfoRequest:true];
    Log(LOG_D, @"[Discovery] Probing %@ — HTTPS: %@ | HTTP: %@",
        address, httpsReq.URL.absoluteString, httpReq.URL.absoluteString);

    // Probe HTTP first so that activeAddress (recorded from the responding candidate)
    // carries the HTTP port or bare IP — never an HTTPS-only port. Downstream code
    // that re-derives ports from activeAddress treats the embedded port as HTTP.
    // HTTPS is retained as the 401 fallback (legacy GFE/Sunshine hosts that
    // reject unauthenticated HTTP serverinfo return 401 and need a retry over TLS).
    [hMan executeRequestSynchronously:[HttpRequest requestForResponse:serverInfoResponse
                                                        withUrlRequest:httpReq
                                                         fallbackError:401
                                                        fallbackRequest:httpsReq]];

    return serverInfoResponse;
}

// Try the user-provided address first, then probe common Sunshine/GFE ports
// on the same host. This handles cases where the user typed just an IP
// (Sunshine runs on non-default ports), or a WebUI port (47990/49990/57990)
// where we need to fall back to the adjacent GameStream API port (port-1).
- (void) discoverHost:(NSString *)hostAddress withCallback:(void (^)(TemporaryHost *, NSString*))callback {
    BOOL prohibitedAddress = [DiscoveryManager isProhibitedAddress:hostAddress];
    NSString* prohibitedAddressMessage = [NSString stringWithFormat: @"Moonlight only supports adding PCs on your local network on %s.",
    #if TARGET_OS_TV
                                   "tvOS"
    #else
                                   "iOS"
    #endif
                             ];

    // Parse the user's input into host + optional port
    NSString *baseHost = nil;
    NSString *userPort = nil;
    [Utils parseAddress:hostAddress intoHost:&baseHost andPort:&userPort];
    if (baseHost.length == 0) {
        baseHost = hostAddress;
    }

    // Build a list of candidate addresses to probe, in priority order.
    // The getServerInfoResponseForAddress method now correctly maps each
    // port to its HTTPS/HTTP counterparts, so we just need to provide the
    // right candidate addresses.
    NSMutableOrderedSet<NSString *> *candidates = [NSMutableOrderedSet orderedSetWithCapacity:6];
    [candidates addObject:hostAddress];

    if (userPort.length == 0) {
        // No explicit port: probe well-known Sunshine/GFE API ports.
        // HTTP ports first — when a candidate succeeds we record it as
        // activeAddress, and downstream code treats an embedded port as HTTP.
        // Putting HTTP first keeps activeAddress HTTP-shaped so later
        // single-arg initWithHost:uniqueId:serverCert: (used by ConnectionHelper
        // and elsewhere) can re-derive the correct HTTPS port.
        NSArray<NSNumber *> *apiPorts = @[@47989, @49989, @57989, @47984, @49984, @57984];
        for (NSNumber *p in apiPorts) {
            NSString *addr = [self joinHost:baseHost withPort:p.integerValue];
            if (addr) [candidates addObject:addr];
        }
    }

    Log(LOG_D, @"[Discovery] Candidates for %@: %@", hostAddress, candidates.array);

    ServerInfoResponse* serverInfoResponse = nil;
    NSString* bestAddress = nil;
    for (NSString *candidate in candidates) {
        serverInfoResponse = [self getServerInfoResponseForAddress:candidate];
        if ([serverInfoResponse isStatusOk]) {
            bestAddress = candidate;
            Log(LOG_D, @"Manual host discovery hit on %@", candidate);
            break;
        }
    }

    TemporaryHost* host = nil;
    if (serverInfoResponse != nil && [serverInfoResponse isStatusOk]) {
        host = [[TemporaryHost alloc] init];
        // Use the address that actually responded as activeAddress; persist
        // the original user input as address so subsequent discovery (which
        // reads address/localAddress/externalAddress) still works.
        NSString *normalizedAddress = bestAddress ?: hostAddress;
        // Normalize HTTPS-shaped activeAddress to HTTP port so downstream
        // single-arg initWithHost:uniqueId:serverCert: (which treats an
        // embedded port as HTTP) derives the correct HTTPS port.
        {
            NSString *nh = nil, *np = nil;
            [Utils parseAddress:normalizedAddress intoHost:&nh andPort:&np];
            if (np.length > 0) {
                NSInteger pv = np.integerValue;
                if (pv > 0 && pv % 10 == 4) {
                    // HTTPS API port — convert to HTTP counterpart (port + 5)
                    normalizedAddress = [self joinHost:nh withPort:pv + 5];
                }
            }
        }
        host.activeAddress = normalizedAddress;
        host.address = hostAddress;
        host.state = StateOnline;
        [serverInfoResponse populateHost:host];

        // If we succeeded on a derived (not user-entered) address, also
        // update localAddress with that derived endpoint so the saved
        // host record can reach the server on next launch even if the
        // original bare IP has no API listener.
        if (bestAddress != nil && ![bestAddress isEqualToString:hostAddress]) {
            if (host.localAddress.length == 0) {
                NSString *derivedHost = nil;
                [Utils parseAddress:bestAddress intoHost:&derivedHost andPort:nil];
                if ([derivedHost isEqualToString:baseHost]) {
                    host.localAddress = bestAddress;
                }
            }
        }
        
        // Check if this is a new PC
        if (![self getHostInDiscovery:host.uuid]) {
            // Enforce LAN restriction for App Store Guideline 4.2.7a
            if ([DiscoveryManager isProhibitedAddress:hostAddress]) {
                // We have a prohibited address. This might be because the user specified their WAN address
                // instead of their LAN address. If that's the case, we'll try their LAN address and if we
                // can reach it through that address, we'll allow it.
                ServerInfoResponse* lanInfo = [self getServerInfoResponseForAddress:host.localAddress];
                if ([lanInfo isStatusOk]) {
                    TemporaryHost* lanHost = [[TemporaryHost alloc] init];
                    [lanInfo populateHost:lanHost];
                    
                    if (![lanHost.uuid isEqualToString:host.uuid]) {
                        // This is a different host, so it's prohibited
                        prohibitedAddress = YES;
                    }
                    else {
                        // This is the same host that is reachable on the LAN
                        prohibitedAddress = NO;
                    }
                }
                else {
                    // LAN request failed, so it's a prohibited address
                    prohibitedAddress = YES;
                }
            }
            else {
                // It's an RFC 1918 IPv4 address or IPv6 address which counts as LAN
                prohibitedAddress = NO;
            }
            
            if (prohibitedAddress) {
                callback(nil, prohibitedAddressMessage);
                return;
            }
            
            NSString* cleanHostAddress;
            [Utils parseAddress:hostAddress intoHost:&cleanHostAddress andPort:nil];
            if ([DiscoveryManager isAddressLAN:inet_addr([cleanHostAddress UTF8String])]) {
                // Don't send a STUN request if we're connected to a VPN. We'll likely get the VPN
                // gateway's external address rather than the external address of the LAN.
                if (![Utils isActiveNetworkVPN]) {
                    // This host was discovered over a permissible LAN address, so we can update our
                    // external address for this host.
                    struct in_addr wanAddr;
                    int err = LiFindExternalAddressIP4("stun.moonlight-stream.org", 3478, &wanAddr.s_addr);
                    if (err == 0) {
                        char addrStr[INET_ADDRSTRLEN];
                        inet_ntop(AF_INET, &wanAddr, addrStr, sizeof(addrStr));
                        host.externalAddress = [NSString stringWithFormat: @"%s", addrStr];
                    }
                }
            }
        }
        
        if (![self addHostToDiscovery:host]) {
            callback(nil, @"Host information updated");
        } else {
            callback(host, nil);
        }
    } else if (!prohibitedAddress) {
        callback(nil, NSLocalizedString(@"Could not connect to host. Ensure GameStream is enabled in GeForce Experience on your PC.", @"Host connect failure"));
    } else {
        callback(nil, prohibitedAddressMessage);
    }
}

- (NSString *)joinHost:(NSString *)host withPort:(NSInteger)port {
    if (host.length == 0 || port <= 0 || port > 65535) {
        return nil;
    }
    if ([host containsString:@":"] && ![host hasPrefix:@"["]) {
        return [NSString stringWithFormat:@"[%@]:%ld", host, (long)port];
    }
    return [NSString stringWithFormat:@"%@:%ld", host, (long)port];
}

- (void) resetDiscoveryState {
    // Allow us to rediscover hosts that were already found before
    [_mdnsMan forgetHosts];
}

- (void) startDiscovery {
    if (shouldDiscover) {
        return;
    }

    NSUInteger queuedHosts;
    NSUInteger pausedHosts;
    @synchronized (_hostQueue) {
        queuedHosts = _hostQueue.count;
        pausedHosts = _pausedHosts.count;
    }
    Log(LOG_I, @"[Discovery] START — queued hosts=%lu, paused=%lu, auto-discover-new=%d",
        (unsigned long)queuedHosts,
        (unsigned long)pausedHosts,
        MoonlightShouldAutoDiscoverNewHosts() ? 1 : 0);
    shouldDiscover = YES;
    [_mdnsMan searchForHosts];

    @synchronized (_hostQueue) {
        for (TemporaryHost* host in _hostQueue) {
            if (![_pausedHosts containsObject:host]) {
                [_opQueue addOperation:[self createWorkerForHost:host]];
            }
        }
    }

    // After ~15s of discovery, if we have zero hosts in the queue (first run)
    // or ZERO saved hosts are currently online, emit a diagnostic summary that
    // points users toward the permission checklist and the manual-add flow.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(15.0 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        // Reads the isa ivar on purpose: the block must keep self alive for 15s.
        if (!self->shouldDiscover) return;

        NSUInteger total = 0;
        NSUInteger online = 0;
        @synchronized (self->_hostQueue) {
            total = self->_hostQueue.count;
            for (TemporaryHost *h in self->_hostQueue) {
                if (h.state == StateOnline) online++;
            }
        }
        if (total == 0 || online == 0) {
            Log(LOG_W, @"[Discovery] ⚠️ 15s SUMMARY: hosts-in-queue=%lu, online=%lu. "
                @"If this is unexpected: (1) Verify LocalNetwork is ON in System Settings "
                @"→ Privacy & Security → Local Network. (2) Click + and add the host by IP "
                @"directly. (3) Run Help → 诊断连接问题 to capture a full diagnostic report.",
                (unsigned long)total, (unsigned long)online);
        } else {
            Log(LOG_I, @"[Discovery] 15s SUMMARY: hosts-in-queue=%lu, online=%lu. OK.",
                (unsigned long)total, (unsigned long)online);
        }
    });
}

- (void) stopDiscovery {
    if (!shouldDiscover) {
        return;
    }
    
    Log(LOG_I, @"Stopping discovery");
    shouldDiscover = NO;
    [_mdnsMan stopSearching];
    [_opQueue cancelAllOperations];
}

- (void) stopDiscoveryBlocking {
    Log(LOG_I, @"Stopping discovery and waiting for workers to stop");
    
    if (shouldDiscover) {
        shouldDiscover = NO;
        [_mdnsMan stopSearching];
        [_opQueue cancelAllOperations];
    }
    
    // Ensure we always wait, just in case discovery
    // was stopped already but in an async manner that
    // left operations in progress.
    [_opQueue waitUntilAllOperationsAreFinished];
    
    Log(LOG_I, @"All discovery workers stopped");
}

- (BOOL) addHostToDiscovery:(TemporaryHost *)host {
    if (host.uuid.length == 0) {
        return NO;
    }
    
    TemporaryHost *existingHost = [self getHostInDiscovery:host.uuid];
    if (existingHost != nil) {
        // NB: Our logic here depends on the fact that we never propagate
        // the entire TemporaryHost to existingHost. In particular, when mDNS
        // discovers a PC and we poll it, we will do so over HTTP which will
        // not have accurate pair state. The fields explicitly copied below
        // are accurate though.
        
        // Update address of existing host
        if (host.address != nil) {
            // If this is a new address, try to add it to an empty slot
            // instead of overwriting the existing address immediately.
            if (![existingHost.address isEqualToString:host.address] &&
                ![existingHost.localAddress isEqualToString:host.address] &&
                ![existingHost.externalAddress isEqualToString:host.address] &&
                ![existingHost.ipv6Address isEqualToString:host.address]) {

                if (existingHost.address == nil) {
                    existingHost.address = host.address;
                }
                else if (existingHost.localAddress == nil) {
                    existingHost.localAddress = host.address;
                }
                else if (existingHost.externalAddress == nil) {
                    existingHost.externalAddress = host.address;
                }
                else if (existingHost.ipv6Address == nil) {
                    existingHost.ipv6Address = host.address;
                }
                else {
                    // No empty slots, overwrite the main address
                    existingHost.address = host.address;
                }
            }
        }
        if (host.localAddress != nil && ![host.localAddress isEqualToString:host.address]) {
             if (existingHost.localAddress == nil) {
                 existingHost.localAddress = host.localAddress;
             }
        }
        if (host.ipv6Address != nil && ![host.ipv6Address isEqualToString:host.address]) {
             if (existingHost.ipv6Address == nil) {
                 existingHost.ipv6Address = host.ipv6Address;
             }
        }
        if (host.externalAddress != nil && ![host.externalAddress isEqualToString:host.address]) {
             if (existingHost.externalAddress == nil) {
                 existingHost.externalAddress = host.externalAddress;
             }
        }

        // Always update active address and state
        existingHost.activeAddress = host.activeAddress;
        existingHost.state = host.state;
        return NO;
    }
    else {
        @synchronized (_hostQueue) {
            [_hostQueue addObject:host];
            if (shouldDiscover) {
                [_opQueue addOperation:[self createWorkerForHost:host]];
            }
        }
        return YES;
    }
}

- (void) removeHostFromDiscovery:(TemporaryHost *)host {
    @synchronized (_hostQueue) {
        for (DiscoveryWorker* worker in [_opQueue operations]) {
            if ([worker getHost] == host) {
                [worker cancel];
            }
        }
        
        [_hostQueue removeObject:host];
        [_pausedHosts removeObject:host];
    }
}

- (void) pauseDiscoveryForHost:(TemporaryHost *)host {
    @synchronized (_hostQueue) {
        // Stop any worker for the host
        for (DiscoveryWorker* worker in [_opQueue operations]) {
            if ([worker getHost] == host) {
                [worker cancel];
            }
        }
        
        // Add it to the paused hosts list
        [_pausedHosts addObject:host];
    }
}

- (void) resumeDiscoveryForHost:(TemporaryHost *)host {
    @synchronized (_hostQueue) {
        // Remove it from the paused hosts list
        [_pausedHosts removeObject:host];
        
        // Start discovery again
        if (shouldDiscover) {
            [_opQueue addOperation:[self createWorkerForHost:host]];
        }
    }
}

// Override from MDNSCallback - called in a worker thread
- (void)updateHost:(TemporaryHost*)host {
    // Discover the hosts before adding to eliminate duplicates
    Log(LOG_D, @"Found host through MDNS: %@:", host.name);
    // Since this is on a background thread, we do not need to use the opQueue
    DiscoveryWorker* worker = (DiscoveryWorker*)[self createWorkerForHost:host];
    [worker discoverHost];
    TemporaryHost *knownHost = [self getHostInDiscovery:host.uuid];
    if (knownHost == nil && !MoonlightShouldAutoDiscoverNewHosts()) {
        Log(LOG_I, @"Ignoring newly discovered host because automatic discovery is disabled: %@", host.name ?: @"");
        return;
    }
    if ([self addHostToDiscovery:host]) {
        Log(LOG_I, @"Found new host through MDNS: %@:", host.name);
        @synchronized (_hostQueue) {
            [_callback updateAllHosts:_hostQueue];
        }
    } else {
        Log(LOG_D, @"Found existing host through MDNS: %@", host.name);
    }
}

- (TemporaryHost*) getHostInDiscovery:(NSString*)uuidString {
    @synchronized (_hostQueue) {
        for (TemporaryHost* discoveredHost in _hostQueue) {
            if (discoveredHost.uuid.length > 0 && [discoveredHost.uuid isEqualToString:uuidString]) {
                return discoveredHost;
            }
        }
    }
    return nil;
}

- (NSOperation*) createWorkerForHost:(TemporaryHost*)host {
    DiscoveryWorker* worker = [[DiscoveryWorker alloc] initWithHost:host uniqueId:_uniqueId];
    return worker;
}

@end
