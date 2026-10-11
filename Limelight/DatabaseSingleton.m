//
//  DatabaseSingleton.m
//  Moonlight
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import "DatabaseSingleton.h"

// Only the explicit Debug QA identity uses a private library. Release and normal
// Debug keep the user's established path; changing HOME does not isolate Foundation.
static NSString *MLDatabaseSupportDirectoryName(NSString *bundleIdentifier) {
#if DEBUG
    if ([bundleIdentifier isEqualToString:@"std.skyhua.MoonlightMac2.QA"]) return @"Moonlight-QA";
#endif
    return @"Moonlight";
}

@interface DatabaseSingleton ()
@property (strong, nonatomic) NSManagedObjectContext *managedObjectContext;
@property (strong, nonatomic) NSManagedObjectModel *managedObjectModel;
@property (strong, nonatomic) NSPersistentStoreCoordinator *persistentStoreCoordinator;
@property (strong, nonatomic) NSError *persistentStoreLoadError;
@end

@implementation DatabaseSingleton {
    BOOL _persistentStoreLoadAttempted;
}

+ (DatabaseSingleton *)shared {
    static DatabaseSingleton *instance;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        instance = [[DatabaseSingleton alloc] init];
    });
    
    return instance;
}

- (void)saveContext
{
    NSError *error = nil;
    NSManagedObjectContext *managedObjectContext = self.managedObjectContext;
    if (managedObjectContext != nil) {
        if ([managedObjectContext hasChanges] && ![managedObjectContext save:&error]) {
            Log(LOG_E, @"Critical database error: %@, %@", error, [error userInfo]);
        }
    }
}

// Returns the managed object context for the application.
// If the context doesn't already exist, it is created and bound to the persistent store coordinator for the application.
- (NSManagedObjectContext *)managedObjectContext
{
    if (_managedObjectContext != nil) {
        return _managedObjectContext;
    }
    
    NSPersistentStoreCoordinator *coordinator = [self persistentStoreCoordinator];
    if (coordinator != nil) {
        _managedObjectContext = [[NSManagedObjectContext alloc] initWithConcurrencyType:NSPrivateQueueConcurrencyType];
        [_managedObjectContext setPersistentStoreCoordinator:coordinator];
        [_managedObjectContext setMergePolicy:NSMergeByPropertyObjectTrumpMergePolicy];
    }
    return _managedObjectContext;
}

// Returns the managed object model for the application.
// If the model doesn't already exist, it is created from the application's model.
- (NSManagedObjectModel *)managedObjectModel
{
    if (_managedObjectModel != nil) {
        return _managedObjectModel;
    }
    _managedObjectModel = [NSManagedObjectModel mergedModelFromBundles:nil];
    return _managedObjectModel;
}

// Returns the persistent store coordinator for the application.
// If the coordinator doesn't already exist, it is created and the application's store added to it.
- (NSPersistentStoreCoordinator *)persistentStoreCoordinator
{
    @synchronized(self) {
        if (_persistentStoreCoordinator != nil || _persistentStoreLoadAttempted) {
            return _persistentStoreCoordinator;
        }
        // Publish only after opening succeeds. A failed store must never look like
        // an empty working library, or be deleted/retried by each DataManager.
        _persistentStoreLoadAttempted = YES;
        NSPersistentStoreCoordinator *coordinator =
            [[NSPersistentStoreCoordinator alloc] initWithManagedObjectModel:self.managedObjectModel];
        NSDictionary *options = @{ NSMigratePersistentStoresAutomaticallyOption: @YES,
                                    NSInferMappingModelAutomaticallyOption: @YES };
        NSError *error = nil;
        if (![coordinator addPersistentStoreWithType:NSSQLiteStoreType configuration:nil
                                                URL:[self getStoreURL] options:options error:&error]) {
            _persistentStoreLoadError = error ?: [NSError errorWithDomain:@"MoonlightDatabase"
                                                                    code:1 userInfo:nil];
            Log(LOG_E, @"Database open failed; data preserved (%@, %ld)",
                _persistentStoreLoadError.domain, (long)_persistentStoreLoadError.code);
            return nil;
        }
        _persistentStoreCoordinator = coordinator;
        return _persistentStoreCoordinator;
    }
}

- (NSError *)persistentStoreLoadError {
    @synchronized(self) {
        (void)self.persistentStoreCoordinator;
        return _persistentStoreLoadError;
    }
}


#pragma mark - Database Path

+ (NSURL *)applicationSupportDirectory {
    
    NSURL *directoryUrl = [[[[NSFileManager defaultManager] URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask] firstObject]
            URLByAppendingPathComponent:MLDatabaseSupportDirectoryName(NSBundle.mainBundle.bundleIdentifier)];
    NSError *error;
    if (![[NSFileManager defaultManager] fileExistsAtPath:directoryUrl.path]) {
        [[NSFileManager defaultManager] createDirectoryAtPath:directoryUrl.path withIntermediateDirectories:YES attributes:nil error:&error];
    }
    
    return directoryUrl;
}

- (NSURL *)getStoreURL {
    return [[DatabaseSingleton applicationSupportDirectory] URLByAppendingPathComponent:@"Moonlight_macOS.sqlite"];
}

@end
