//
//  TemporaryApp.h
//  Moonlight
//
//  Created by Cameron Gutman on 9/30/15.
//  Copyright © 2015 Moonlight Stream. All rights reserved.
//

#import "TemporaryHost.h"
#import "App+CoreDataClass.h"

@interface TemporaryApp : NSObject

@property (nullable, nonatomic, retain) NSString *id;
@property (nullable, nonatomic, retain) NSString *name;
@property (nullable, nonatomic, retain) NSString *installPath;
@property (nonatomic)                   BOOL hdrSupported;
@property (nonatomic)                   BOOL hidden;
@property (nonatomic)                   BOOL pinned;
// Weak back-pointer: the owning TemporaryHost.appList is the single strong
// holder. A weak back-edge breaks the host<->app retain cycle so a removed
// host graph can actually be deallocated (see docs/memory-ownership.md §9).
@property (nullable, nonatomic, weak) TemporaryHost *host;

NS_ASSUME_NONNULL_BEGIN

- (id) initFromApp:(App*)app withTempHost:(TemporaryHost*)tempHost;

- (NSComparisonResult)compareName:(TemporaryApp *)other;
- (NSComparisonResult)compare:(TemporaryApp *)other;

- (void) propagateChangesToParent:(App*)parent withHost:(Host*)host;

NS_ASSUME_NONNULL_END

@end
