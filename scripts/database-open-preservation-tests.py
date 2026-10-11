#!/usr/bin/env python3
"""Compile shipping store open + DataManager init; only private fixture stores are touched."""
import subprocess, tempfile
from pathlib import Path
import apple_toolchain
ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''
#import <Foundation/Foundation.h>
#import <CoreData/CoreData.h>
#import <objc/runtime.h>
#import <stdatomic.h>
#define Log(level, fmt, ...) ((void)0)
@@SINGLETON@@
@interface DataManager : NSObject { NSManagedObjectContext *_managedObjectContext; }
@property(readonly) NSManagedObjectContext *context;
@end
@implementation DataManager
@@INIT@@
- (NSManagedObjectContext *)context { return _managedObjectContext; }
@end
static NSURL *fixtureURL;
static DatabaseSingleton *fixture;
static int failureMode;
static _Atomic int opens;
static _Atomic int missingReaders;
static id (*realAdd)(id, SEL, NSString *, NSString *, NSURL *, NSDictionary *, NSError **);
static id injectedAdd(id self, SEL cmd, NSString *type, NSString *config, NSURL *url,
                      NSDictionary *options, NSError **error) {
    int count = atomic_fetch_add(&opens, 1) + 1;
    if (count > 1) @throw [NSException exceptionWithName:@"RepeatedOpen" reason:@"retry or concurrent open" userInfo:nil];
    if (failureMode == 1 || failureMode == 2) {
        if (failureMode == 1 && error) *error = [NSError errorWithDomain:@"FixtureOpen" code:42 userInfo:nil];
        return nil;
    }
    [NSThread sleepForTimeInterval:0.02];
    return realAdd(self, cmd, type, config, url, options, error);
}
static id injectedShared(id self, SEL cmd) { return fixture; }
@interface FixtureDatabase : DatabaseSingleton
@property NSManagedObjectModel *fixtureModel;
@end
@implementation FixtureDatabase
- (NSURL *)getStoreURL { return fixtureURL; }
- (NSManagedObjectModel *)managedObjectModel {
    if (!self.fixtureModel) {
        NSEntityDescription *entity = [NSEntityDescription new];
        entity.name = @"Fixture"; entity.managedObjectClassName = @"NSManagedObject";
        NSAttributeDescription *field = [NSAttributeDescription new];
        field.name = @"name"; field.attributeType = NSStringAttributeType;
        entity.properties = @[field];
        self.fixtureModel = [NSManagedObjectModel new]; self.fixtureModel.entities = @[entity];
    }
    return self.fixtureModel;
}
@end
#define CHECK(c, msg) do { if (!(c)) { puts("FAIL: " msg); return 1; } } while(0)
int main(int argc, char **argv) { @autoreleasepool { @try {
    CHECK(argc == 2, "private fixture path required");
    CHECK([MLDatabaseSupportDirectoryName(nil) isEqualToString:@"Moonlight"], "missing identity keeps normal library");
    CHECK([MLDatabaseSupportDirectoryName(@"std.skyhua.MoonlightMac2") isEqualToString:@"Moonlight"], "normal identity unchanged");
    CHECK([MLDatabaseSupportDirectoryName(@"other.QA") isEqualToString:@"Moonlight"], "unknown identity does not redirect library");
#if DEBUG
    CHECK([MLDatabaseSupportDirectoryName(@"std.skyhua.MoonlightMac2.QA") isEqualToString:@"Moonlight-QA"], "Debug QA library isolated");
#else
    CHECK([MLDatabaseSupportDirectoryName(@"std.skyhua.MoonlightMac2.QA") isEqualToString:@"Moonlight"], "Release never redirects library");
#endif
    Method add = class_getInstanceMethod(NSPersistentStoreCoordinator.class,
        @selector(addPersistentStoreWithType:configuration:URL:options:error:));
    realAdd = (void *)method_setImplementation(add, (IMP)injectedAdd);
    Method shared = class_getClassMethod(DatabaseSingleton.class, @selector(shared));
    IMP realShared = method_setImplementation(shared, (IMP)injectedShared);
    NSString *directory = [NSString stringWithUTF8String:argv[1]];
    for (failureMode = 1; failureMode <= 3; failureMode++) {
        fixtureURL = [NSURL fileURLWithPath:[directory stringByAppendingPathComponent:
            [NSString stringWithFormat:@"failed-%d.sqlite", failureMode]]];
        NSData *marker = [@"fixture-data-preserve" dataUsingEncoding:NSUTF8StringEncoding];
        NSArray *paths = @[fixtureURL.path, [fixtureURL.path stringByAppendingString:@"-wal"],
                            [fixtureURL.path stringByAppendingString:@"-shm"]];
        for (NSString *path in paths) CHECK([marker writeToFile:path atomically:YES], "seed failed");
        fixture = [FixtureDatabase new]; atomic_store(&opens, 0);
        CHECK(fixture.persistentStoreCoordinator == nil, "failed coordinator must not publish");
        CHECK(fixture.persistentStoreLoadError != nil, "failure must stay visible");
        if (failureMode == 1) CHECK([fixture.persistentStoreLoadError.domain isEqualToString:@"FixtureOpen"] &&
            fixture.persistentStoreLoadError.code == 42, "original error preserved");
        dispatch_apply(32, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^(size_t i) {
            @autoreleasepool { (void)fixture.persistentStoreCoordinator; }
        });
        CHECK([[DataManager alloc] init] == nil, "DataManager refuses unavailable store");
        CHECK(fixture.managedObjectContext == nil, "singleton context refuses unavailable store");
        [fixture saveContext];
        CHECK(atomic_load(&opens) == 1, "one failed open per launch instance");
        for (NSString *path in paths) CHECK([[NSData dataWithContentsOfFile:path] isEqual:marker], "sqlite or sidecar changed/deleted");
    }
    failureMode = 0; atomic_store(&opens, 0);
    fixtureURL = [NSURL fileURLWithPath:[directory stringByAppendingPathComponent:@"valid.sqlite"]];
    fixture = [FixtureDatabase new];
    atomic_store(&missingReaders, 0);
    dispatch_apply(32, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^(size_t i) {
        @autoreleasepool {
            if (fixture.persistentStoreCoordinator == nil) atomic_fetch_add(&missingReaders, 1);
        }
    });
    CHECK(atomic_load(&missingReaders) == 0, "concurrent first readers wait for real opened store");
    NSPersistentStoreCoordinator *opened = fixture.persistentStoreCoordinator;
    CHECK(opened != nil && opened.persistentStores.count == 1, "real SQLite opens");
    CHECK(fixture.persistentStoreCoordinator == opened && fixture.persistentStoreLoadError == nil, "successful store cached without false error");
    DataManager *manager = [[DataManager alloc] init];
    CHECK(manager.context.persistentStoreCoordinator == opened, "DataManager uses real opened store");
    CHECK(atomic_load(&opens) == 1, "successful store opened once");
    method_setImplementation(add, (IMP)realAdd); method_setImplementation(shared, realShared);
    puts("PASS: failed opens preserve sqlite/wal/shm; no-error + real corrupt store failure visible; 32 first readers; real SQLite + DataManager");
    return 0;
} @catch (NSException *e) { printf("FAIL: exception %s\n", e.name.UTF8String); return 1; } } }
'''
def main():
    source = (ROOT/'Limelight/DatabaseSingleton.m').read_text()
    data = (ROOT/'Limelight/Database/DataManager.m').read_text()
    init = data[data.index('- (id) init {'):data.index('\n- (void) updateUniqueId:')]
    cc, sdk = apple_toolchain.clang_and_sdk('database open preservation')
    failures = 0
    cases = [
        ('shipping', source, init, True),
        ('shipping-release', source, init, True),
        ('QA-shares-library', source.replace('@"Moonlight-QA"', '@"Moonlight"'), init, False),
        ('release-redirects-library', source.replace('#if DEBUG', '#if 1'), init, False),
        ('delete-store', source.replace('return nil;\n        }', '[[NSFileManager defaultManager] removeItemAtURL:[self getStoreURL] error:nil];\n            return nil;\n        }', 1), init, False),
        ('unserialized-open', source.replace('@synchronized(self)', 'if (YES)'), init, False),
        ('retry-failed', source.replace('|| _persistentStoreLoadAttempted', '|| NO'), init, False),
        ('publish-failed', source.replace('_persistentStoreLoadAttempted = YES;', '_persistentStoreLoadAttempted = YES;\n        _persistentStoreCoordinator = [[NSPersistentStoreCoordinator alloc] initWithManagedObjectModel:self.managedObjectModel];'), init, False),
        ('context-without-store', source, init.replace('if (coordinator == nil) return nil;', 'if (coordinator == nil) { /* ignore failure */ }'), False),
    ]
    with tempfile.TemporaryDirectory(prefix='ml-database-gate-') as temp:
        for name, singleton, initialiser, positive in cases:
            folder = Path(temp)/name; folder.mkdir()
            path = folder/'gate.m'; binary = folder/'gate'
            path.write_text(DRIVER.replace('@@SINGLETON@@', singleton).replace('@@INIT@@', initialiser))
            built = subprocess.run([cc, '-isysroot', sdk, '-fobjc-arc', '-Wall', '-Werror',
                '-DDEBUG='+('0' if name in ('shipping-release', 'release-redirects-library') else '1'),
                '-I'+str(ROOT/'Limelight'), str(path), '-framework', 'Foundation', '-framework', 'CoreData', '-o', str(binary)], capture_output=True, text=True)
            if built.returncode:
                print('FAIL:', name, 'must compile', built.stderr[-1800:]); failures += 1; continue
            ran = subprocess.run([str(binary), str(folder)], capture_output=True, text=True, timeout=30)
            valid = ran.returncode == 0 and 'PASS:' in ran.stdout if positive else ran.returncode == 1 and 'FAIL:' in ran.stdout
            print('ok:' if valid else 'FAIL:', name, 'compiled; runtime:', ran.stdout.strip())
            failures += not valid
    wired = 'URLByAppendingPathComponent:MLDatabaseSupportDirectoryName(NSBundle.mainBundle.bundleIdentifier)' in source
    print('ok:' if wired else 'FAIL:', 'shipping directory uses identity helper')
    failures += not wired
    app = (ROOT/'Limelight/macOS/AppDelegateForAppKit.m').read_text()
    startup = app.split('- (void)applicationDidFinishLaunching:', 1)[1].split('- (void)addDiagnoseMenu', 1)[0]
    valid = all(s in startup for s in ('persistentStoreLoadError', 'Local library unavailable',
        'Local library preserved after open failure', '[NSApp terminate:nil];')) and startup.index('persistentStoreLoadError') < startup.index('[self createMainWindow]')
    print('ok:' if valid else 'FAIL:', 'startup refuses silent empty library and explains data preservation')
    failures += not valid
    print(f'{failures} database-open-preservation failures')
    return int(failures != 0)
if __name__ == '__main__': raise SystemExit(main())
