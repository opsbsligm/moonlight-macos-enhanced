//
//  DataManager.h
//  Moonlight
//
//  Created by Diego Waxemberg on 10/28/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import <Foundation/Foundation.h>
#import "TemporaryHost.h"
#import "TemporaryApp.h"
#import "TemporarySettings.h"

// Legacy methods retain unspecified nullability; the new metadata API alone
// explicitly promise nullable lookup/fetch results.
@interface DataManager : NSObject

- (void) saveSettingsWithBitrate:(NSInteger)bitrate
                       framerate:(NSInteger)framerate
                          height:(NSInteger)height
                           width:(NSInteger)width
                onscreenControls:(NSInteger)onscreenControls
                          remote:(BOOL)streamingRemotely
                   optimizeGames:(BOOL)optimizeGames
                 multiController:(BOOL)multiController
                       audioOnPC:(BOOL)audioOnPC
                         useHevc:(BOOL)useHevc
                       enableHdr:(BOOL)enableHdr
                  btMouseSupport:(BOOL)btMouseSupport;

- (NSArray * _Null_unspecified) getHosts;
/// Connection descriptors only; nil on fetch failure, empty on a successful empty store.
- (nullable NSArray<TemporaryHost *> *)getHostMetadata;
/// Reads one connection descriptor without constructing any TemporaryApp graph.
- (nullable TemporaryHost *)hostMetadataForUUID:(NSString * _Nonnull)uuid NS_SWIFT_NAME(hostMetadata(forUUID:));
- (void) removeHostsWithEmptyUuid;
- (void) updateHost:(TemporaryHost * _Null_unspecified)host;
- (void) updateAppsForExistingHost:(TemporaryHost * _Null_unspecified)host;
- (void) removeHost:(TemporaryHost * _Null_unspecified)host;
- (void) removeApp:(TemporaryApp * _Null_unspecified)app;

- (TemporarySettings * _Null_unspecified) getSettings;

- (void) updateUniqueId:(NSString * _Null_unspecified)uniqueId;
- (NSString * _Null_unspecified) getUniqueId;

@end
