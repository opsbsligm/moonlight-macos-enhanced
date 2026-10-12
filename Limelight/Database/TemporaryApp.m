//
//  TemporaryApp.m
//  Moonlight
//
//  Created by Cameron Gutman on 9/30/15.
//  Copyright © 2015 Moonlight Stream. All rights reserved.
//

#import "TemporaryApp.h"

@implementation TemporaryApp

- (id) initFromApp:(App*)app withTempHost:(TemporaryHost*)tempHost {
    self = [self init];
    
    self.id = app.id;
    self.name = app.name;
    self.hdrSupported = app.hdrSupported;
    self.hidden = app.hidden;
    self.pinned = app.pinned;
    self.host = tempHost;
    
    return self;
}

- (void) propagateChangesToParent:(App*)parent withHost:(Host*)host {
    parent.id = self.id;
    parent.name = self.name;
    parent.hdrSupported = self.hdrSupported;
    parent.hidden = self.hidden;
    parent.pinned = self.pinned;
    parent.host = host;
}

- (NSComparisonResult)compareName:(TemporaryApp *)other {
    return [self.name caseInsensitiveCompare:other.name];
}

- (NSComparisonResult)compare:(TemporaryApp *)other {
    NSComparisonResult retVal = [self comparePinned:other];
    if (retVal == NSOrderedSame) {
        retVal = [self.name caseInsensitiveCompare:other.name];
        if (retVal == NSOrderedSame) {
            return [self.id compare:other.id];
        }
    }
    
    return retVal;
}

- (NSComparisonResult)comparePinned:(TemporaryApp *)other {
    if (self.pinned == other.pinned) {
        return NSOrderedSame;
    } else if (self.pinned && !other.pinned) {
        return NSOrderedAscending;
    } else {
        return NSOrderedDescending;
    }
}

- (NSUInteger)hash {
    // Deliberately host-independent: the host back-pointer is weak, so hashing on
    // host.uuid would let the hash change (to 0) once the host is released and
    // silently corrupt any NSSet the app is still an element of. Equal apps still
    // agree because isEqual only ever narrows the id-based bucket.
    return [self.id hash] * 31;
}

- (BOOL)isEqual:(id)object {
    if (self == object) {
        return YES;
    }
    
    if (![object isKindOfClass:[App class]]) {
        return NO;
    }
    
    // A released weak host makes this app an orphan: it is intentionally unequal
    // to anything, rather than silently matching a same-id app on another host.
    NSString *ownHostUuid = self.host.uuid;
    return ownHostUuid != nil &&
    [ownHostUuid isEqualToString:((App*)object).host.uuid] &&
    [self.id isEqualToString:((App*)object).id];
}

@end
