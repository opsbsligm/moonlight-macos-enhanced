//
//  DataManager.m
//  Moonlight
//
//  Created by Diego Waxemberg on 10/28/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "DataManager.h"
#import "TemporaryApp.h"
#import "TemporarySettings.h"
#import "DatabaseSingleton.h"

#if DEBUG
#include <stdatomic.h>

// How many times the library has been read through `getHosts`, counted for the Debug probes.
//
// The number exists because of a chain that has been asserted in prose for a long time and never
// counted: `SettingsModel.hosts` is a computed property (`SettingsModel.swift:122`), every
// evaluation of it calls `getHosts`, and every `getHosts` builds a *fresh* object graph out of
// Core Data (`DataManager.m:175`) -- one `TemporaryHost` per row plus the `TemporaryApp` set each
// one holds, in a cycle that `leaks` calls ROOT CYCLE and `docs/memory-ownership.md` records as
// pinned by whoever asked. So the leak the memory gate judges is not one graph per run of the app:
// it is one graph per read. That makes this counter the quantity that explains the leak gate's
// numbers, and the only honest answer to "how many times does opening one page ask for the whole
// library". The call-site count in the documentation (seventeen) is stale by measurement -- there
// are twenty-nine call sites today, and a call-site count was never the question anyway, because
// a site inside a loop is not a site.
//
// Relaxed ordering is deliberate: the counter is not standing in for anything else, and no other
// value is meant to be visible because a read was. Debug-only for the same reason the count costs
// nothing where players run: `#if DEBUG` means the release binary does not carry the increment.
static atomic_ullong MLHostReadCounter = 0;

unsigned long long MLHostReads(void) {
    return atomic_load_explicit(&MLHostReadCounter, memory_order_relaxed);
}

void MLResetHostReads(void) {
    atomic_store_explicit(&MLHostReadCounter, 0, memory_order_relaxed);
}

static void MLRecordHostRead(void) {
    atomic_fetch_add_explicit(&MLHostReadCounter, 1ULL, memory_order_relaxed);
}
#endif

@implementation DataManager {
    NSManagedObjectContext *_managedObjectContext;
}

- (id) init {
    self = [super init];
    
    _managedObjectContext = [[NSManagedObjectContext alloc] initWithConcurrencyType:NSPrivateQueueConcurrencyType];
    [_managedObjectContext setPersistentStoreCoordinator:[DatabaseSingleton shared].persistentStoreCoordinator];
    [_managedObjectContext setMergePolicy:NSMergeByPropertyObjectTrumpMergePolicy];
    
    return self;
}

- (void) updateUniqueId:(NSString*)uniqueId {
    [_managedObjectContext performBlockAndWait:^{
        [self retrieveSettings].uniqueId = uniqueId;
        [self saveData];
    }];
}

- (NSString*) getUniqueId {
    __block NSString *uid;
    
    [_managedObjectContext performBlockAndWait:^{
        uid = [self retrieveSettings].uniqueId;
    }];

    return uid;
}

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
                  btMouseSupport:(BOOL)btMouseSupport {
    
    [_managedObjectContext performBlockAndWait:^{
        Settings* settingsToSave = [self retrieveSettings];
        settingsToSave.framerate = [NSNumber numberWithInteger:framerate];
        settingsToSave.bitrate = [NSNumber numberWithInteger:bitrate];
        settingsToSave.height = [NSNumber numberWithInteger:height];
        settingsToSave.width = [NSNumber numberWithInteger:width];
        settingsToSave.onscreenControls = [NSNumber numberWithInteger:onscreenControls];
        settingsToSave.streamingRemotely = streamingRemotely;
        settingsToSave.optimizeGames = optimizeGames;
        settingsToSave.multiController = multiController;
        settingsToSave.playAudioOnPC = audioOnPC;
        settingsToSave.useHevc = useHevc;
        settingsToSave.enableHdr = enableHdr;
        settingsToSave.btMouseSupport = btMouseSupport;
        
        [self saveData];
    }];
}

- (void) updateHost:(TemporaryHost *)host {
    [_managedObjectContext performBlockAndWait:^{
        // Add a new persistent managed object if one doesn't exist
        Host* parent = [self getHostForTemporaryHost:host withHostRecords:[self fetchRecords:@"Host"]];
        if (parent == nil) {
            NSEntityDescription* entity = [NSEntityDescription entityForName:@"Host" inManagedObjectContext:self->_managedObjectContext];
            parent = [[Host alloc] initWithEntity:entity insertIntoManagedObjectContext:self->_managedObjectContext];
        }
        
        // Push changes from the temp host to the persistent one
        [host propagateChangesToParent:parent];
        
        [self saveData];
    }];
}

- (void) updateAppsForExistingHost:(TemporaryHost *)host {
    [_managedObjectContext performBlockAndWait:^{
        Host* parent = [self getHostForTemporaryHost:host withHostRecords:[self fetchRecords:@"Host"]];
        if (parent == nil) {
            // The host must exist to be updated
            return;
        }
        
        NSMutableSet *applist = [[NSMutableSet alloc] init];
        NSArray *appRecords = [self fetchRecords:@"App"];
        for (TemporaryApp* app in host.appList) {
            // Add a new persistent managed object if one doesn't exist
            App* parentApp = [self getAppForTemporaryApp:app withAppRecords:appRecords];
            if (parentApp == nil) {
                NSEntityDescription* entity = [NSEntityDescription entityForName:@"App" inManagedObjectContext:self->_managedObjectContext];
                parentApp = [[App alloc] initWithEntity:entity insertIntoManagedObjectContext:self->_managedObjectContext];
            }
            
            [app propagateChangesToParent:parentApp withHost:parent];
            
            [applist addObject:parentApp];
        }
        
        parent.appList = applist;
        
        [self saveData];
    }];
}

- (TemporarySettings*) getSettings {
    __block TemporarySettings *tempSettings;
    
    [_managedObjectContext performBlockAndWait:^{
        tempSettings = [[TemporarySettings alloc] initFromSettings:[self retrieveSettings]];
    }];
    
    return tempSettings;
}

- (Settings*) retrieveSettings {
    NSArray* fetchedRecords = [self fetchRecords:@"Settings"];
    if (fetchedRecords.count == 0) {
        // create a new settings object with the default values
        NSEntityDescription* entity = [NSEntityDescription entityForName:@"Settings" inManagedObjectContext:_managedObjectContext];
        Settings* settings = [[Settings alloc] initWithEntity:entity insertIntoManagedObjectContext:_managedObjectContext];
        
        return settings;
    } else {
        // we should only ever have 1 settings object stored
        return [fetchedRecords objectAtIndex:0];
    }
}

- (void) removeApp:(TemporaryApp*)app {
    [_managedObjectContext performBlockAndWait:^{
        App* managedApp = [self getAppForTemporaryApp:app withAppRecords:[self fetchRecords:@"App"]];
        if (managedApp != nil) {
            [self->_managedObjectContext deleteObject:managedApp];
            [self saveData];
        }
    }];
}

- (void) removeHost:(TemporaryHost*)host {
    [_managedObjectContext performBlockAndWait:^{
        Host* managedHost = [self getHostForTemporaryHost:host withHostRecords:[self fetchRecords:@"Host"]];
        if (managedHost != nil) {
            [self->_managedObjectContext deleteObject:managedHost];
            [self saveData];
        }
    }];
}

- (void) saveData {
    NSError* error;
    if ([_managedObjectContext hasChanges] && ![_managedObjectContext save:&error]) {
        Log(LOG_E, @"Unable to save hosts to database: %@", error);
    }

    [[DatabaseSingleton shared] saveContext];
}

- (NSArray*) getHosts {
#if DEBUG
    MLRecordHostRead();
#endif
    __block NSMutableArray *tempHosts = [[NSMutableArray alloc] init];
    
    [_managedObjectContext performBlockAndWait:^{
        NSArray *hosts = [self fetchRecords:@"Host"];
        
        for (Host* host in hosts) {
            [tempHosts addObject:[[TemporaryHost alloc] initFromHost:host]];
        }
    }];
    
    return tempHosts;
}

- (void) removeHostsWithEmptyUuid {
    [_managedObjectContext performBlockAndWait:^{
        NSArray *hosts = [self fetchRecords:@"Host"];
        BOOL didDelete = NO;
        for (id host in hosts) {
            NSString *uuid = [host valueForKey:@"uuid"];
            if (uuid == nil || uuid.length == 0) {
                [self->_managedObjectContext deleteObject:host];
                didDelete = YES;
            }
        }
        if (didDelete) {
            [self saveData];
        }
    }];
}

// Only call from within performBlockAndWait!!!
- (Host*) getHostForTemporaryHost:(TemporaryHost*)tempHost withHostRecords:(NSArray*)hosts {
    for (Host* host in hosts) {
        if (tempHost.uuid != nil && [tempHost.uuid isEqualToString:host.uuid]) {
            return host;
        }
    }

    // Fallback matching when UUID is missing
    if (tempHost.uuid == nil || tempHost.uuid.length == 0) {
        for (Host* host in hosts) {
            if (tempHost.mac != nil && host.mac != nil && [tempHost.mac isEqualToString:host.mac]) {
                return host;
            }
            if (tempHost.address != nil && host.address != nil && [tempHost.address isEqualToString:host.address]) {
                return host;
            }
            if (tempHost.name != nil && host.name != nil && [tempHost.name isEqualToString:host.name]) {
                return host;
            }
        }
    }
    
    return nil;
}

// Only call from within performBlockAndWait!!!
- (App*) getAppForTemporaryApp:(TemporaryApp*)tempApp withAppRecords:(NSArray*)apps {
    for (App* app in apps) {
        if ([app.id isEqualToString:tempApp.id] &&
            [app.host.uuid isEqualToString:tempApp.host.uuid]) {
            return app;
        }
    }
    
    return nil;
}

- (NSArray*) fetchRecords:(NSString*)entityName {
    NSArray* fetchedRecords;
    
    NSFetchRequest* fetchRequest = [[NSFetchRequest alloc] init];
    NSEntityDescription* entity = [NSEntityDescription entityForName:entityName inManagedObjectContext:_managedObjectContext];
    [fetchRequest setEntity:entity];
    
    NSError* error;
    fetchedRecords = [_managedObjectContext executeFetchRequest:fetchRequest error:&error];
    //TODO: handle errors
    
    return fetchedRecords;
}

@end

