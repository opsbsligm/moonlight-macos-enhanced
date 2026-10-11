//
//  DatabaseSingleton.h
//  Moonlight
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import <Foundation/Foundation.h>
#import <CoreData/CoreData.h>

@interface DatabaseSingleton : NSObject

+ (DatabaseSingleton * _Null_unspecified)shared;

@property (readonly, strong, nonatomic) NSManagedObjectContext * _Null_unspecified managedObjectContext;
@property (readonly, strong, nonatomic) NSManagedObjectModel * _Null_unspecified managedObjectModel;
@property (readonly, strong, nonatomic) NSPersistentStoreCoordinator * _Null_unspecified persistentStoreCoordinator;

/// Opening failed: preserve the library and remain unavailable until next launch.
@property (readonly, strong, nonatomic) NSError * _Nullable persistentStoreLoadError;

- (void)saveContext;

+ (NSURL * _Null_unspecified)applicationSupportDirectory;

@end
