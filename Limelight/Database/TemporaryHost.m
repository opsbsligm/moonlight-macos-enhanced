//
//  TemporaryHost.m
//  Moonlight
//
//  Created by Cameron Gutman on 12/1/15.
//  Copyright © 2015 Moonlight Stream. All rights reserved.
//

#import "DataManager.h"
#import "TemporaryHost.h"
#import "TemporaryApp.h"

@implementation TemporaryHost

- (id) init {
    self = [super init];
    self.appList = [[NSMutableSet alloc] init];
    self.currentGame = @"0";
    self.state = StateUnknown;
    self.addressLatencies = [[NSMutableDictionary alloc] init];
    self.addressStates = [[NSMutableDictionary alloc] init];
    
    return self;
}

- (id) initFromHost:(Host*)host {
    self = [self init];
    
    self.address = host.address;
    self.externalAddress = host.externalAddress;
    self.localAddress = host.localAddress;
    self.ipv6Address = host.ipv6Address;
    self.mac = host.mac;
    self.name = host.name;
    self.customName = [host valueForKey:@"customName"];
    self.uuid = host.uuid;
    self.serverCodecModeSupport = host.serverCodecModeSupport;
    self.serverCert = host.serverCert;
    
    // Ensure we don't use a stale cached pair state if we haven't pinned the cert yet
    self.pairState = host.serverCert ? [host.pairState intValue] : PairStateUnpaired;
    
    NSMutableSet *appList = [[NSMutableSet alloc] init];

    for (App* app in host.appList) {
        TemporaryApp *tempApp = [[TemporaryApp alloc] initFromApp:app withTempHost:self];
        [appList addObject:tempApp];
    }
    
    self.appList = appList;
    
    return self;
}

- (void) propagateChangesToParent:(Host*)parentHost {
    // Avoid overwriting existing data with nil if
    // we don't have everything populated in the temporary
    // host.
    if (self.address != nil) {
        parentHost.address = self.address;
    }
    if (self.externalAddress != nil) {
        parentHost.externalAddress = self.externalAddress;
    }
    if (self.localAddress != nil) {
        parentHost.localAddress = self.localAddress;
    }
    if (self.ipv6Address != nil) {
        parentHost.ipv6Address = self.ipv6Address;
    }
    if (self.mac != nil) {
        parentHost.mac = self.mac;
    }
    if (self.serverCert != nil) {
        parentHost.serverCert = self.serverCert;
    }
    parentHost.name = self.name;
    [parentHost setValue:self.customName forKey:@"customName"];
    // The guard every field above this one carries, extended to the field where its absence cost
    // the most. `-[DataManager getHostForTemporaryHost:withHostRecords:]` has a branch commented
    // "Fallback matching when UUID is missing" and looks the stored host up by mac, address or name
    // instead, so a discovery response that arrived without a `uniqueid` is expected often enough
    // to be coded for -- and it reaches the paired host. Assigning the missing value here used to
    // take that host's identifier off. Nothing repairs it later: `SettingsModel.hosts` and the
    // device sidebar both call `removeHostsWithEmptyUuid` before they read a row, so the next look
    // at the device list deletes the host, and `Host.appList` is `Cascade` -- measured against a
    // live store, with the apps going 6 to 3 and the host going 2 to 1 for one response that simply
    // did not carry the tag -- so the applications somebody added to that machine went with it.
    // An empty id is refused for the same reason as a nil one: `<uniqueid></uniqueid>` parses to an
    // empty string, and an empty string deletes the row just as completely. No legitimate flow sets
    // a host's uuid to empty, because the code that reads the list treats empty as trash to remove.
    if (self.uuid != nil && self.uuid.length > 0) {
        parentHost.uuid = self.uuid;
    }
    parentHost.serverCodecModeSupport = self.serverCodecModeSupport;
    parentHost.pairState = [NSNumber numberWithInt:self.pairState];
}

- (NSString *)displayName {
    NSString *trimmedCustomName = [self.customName stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    if (trimmedCustomName.length > 0) {
        return trimmedCustomName;
    }
    return self.name ?: @"";
}

- (NSComparisonResult)compareName:(TemporaryHost *)other {
    return [self.displayName caseInsensitiveCompare:other.displayName];
}

- (NSUInteger)hash {
    return [self.uuid hash];
}

- (BOOL)isEqual:(id)object {
    if (self == object) {
        return YES;
    }
    
    if (![object isKindOfClass:[Host class]]) {
        return NO;
    }
    
    return [self.uuid isEqualToString:((Host*)object).uuid];
}

@end
