//
//  MDNSManager.h
//  Moonlight
//
//  Created by Diego Waxemberg on 10/14/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "TemporaryHost.h"

@protocol MDNSCallback <NSObject>

- (void) updateHost:(TemporaryHost*)host;

@end

@interface MDNSManager : NSObject <NSNetServiceBrowserDelegate, NSNetServiceDelegate>

/// Who to tell about a host. This is weak because the object on the other end is the one
/// that owns this manager: held strongly it is a cycle, and a cycle here was a DiscoveryManager,
/// its browser, its resolved services and the hosts page behind it, all kept alive forever,
/// one per refresh of that page. Weak also means a page that has gone away is not told.
@property (nonatomic, weak) id<MDNSCallback> callback;

- (id) initWithCallback:(id<MDNSCallback>) callback;
- (void) searchForHosts;
- (void) stopSearching;
- (void) forgetHosts;

@end



