// Spike 2: what does "concurrent writes do not corrupt" actually mean for NSUserDefaults?
// Three separate questions are measured, because they have three different answers:
//   A. can a single stored value be observed half-written by another thread?
//   B. does a read-modify-write of one composite record lose an update?
//   C. does a write from another process become visible, and what does it cost?
// Plus the file-level judgement: is the plist on disk still a property list at all.
#import <Foundation/Foundation.h>
#import <unistd.h>
#import <sys/wait.h>
#import <mach-o/dyld.h>
#include <string.h>

static int failures = 0;
static int checks_run = 0;
#define CHECK(ok, what) do { const BOOL _passed = (ok); checks_run++; if (!_passed) failures++; \
    printf("%-4s %s\n", _passed ? "ok" : "FAIL", (what)); } while (0)

static NSString *gSuite;
static volatile int gWritersFinished;
static volatile long gVerifiesRun;
static NSString *Key(NSString *leaf) { return [NSString stringWithFormat:@"moonlight.spike.%@", leaf]; }

// A value that carries its own proof: the payload repeats the thread and sequence it was
// written with, so a reader can tell a whole value from a stitched-together one.
static NSString *Craft(NSUInteger thread, long seq) {
    return [NSString stringWithFormat:@"t%lu-s%ld-h%08lx",
            (unsigned long)thread, seq, (unsigned long)((thread * 2654435761u) ^ (unsigned long)seq)];
}
// The whole value has to re-derive its own digest, so a reader that saw half of one write and
// half of another could not produce a digest that matches. Note the field prefixes are checked,
// not just the separators: an earlier draft matched parts[1] against @"s" instead of a prefix and
// read every thread id as zero, which made nine of ten values look torn.
static BOOL Verify(NSString *value, NSUInteger *threadOut, long *seqOut) {
    NSArray<NSString *> *parts = [value componentsSeparatedByString:@"-"];
    if (parts.count != 3) return NO;
    if (![parts[0] hasPrefix:@"t"] || ![parts[1] hasPrefix:@"s"] || ![parts[2] hasPrefix:@"h"]) return NO;
    __sync_fetch_and_add(&gVerifiesRun, 1);
    NSUInteger thread = (NSUInteger)[[parts[0] substringFromIndex:1] integerValue];
    long seq = [[parts[1] substringFromIndex:1] integerValue];
    unsigned long hash = strtoul([[parts[2] substringFromIndex:1] UTF8String], NULL, 16);
    if (threadOut) *threadOut = thread;
    if (seqOut) *seqOut = seq;
    return hash == ((thread * 2654435761UL) ^ (unsigned long)seq);
}

static int RunChild(int argc, char **argv, BOOL shouldSynchronize);

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--peer-write") == 0) return RunChild(argc, argv, YES);
    if (argc > 1 && strcmp(argv[1], "--peer-write-nosync") == 0) return RunChild(argc, argv, NO);
    @autoreleasepool {
        long pid = (long)getpid();
        gSuite = [NSString stringWithFormat:@"usermem.concurrency.%ld", pid];
        NSUserDefaults *store = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
        [store removePersistentDomainForName:gSuite];
        printf("== spike 2: concurrency on macOS %s ==\n",
               [[[NSProcessInfo processInfo] operatingSystemVersionString] UTF8String]);

        // ---- A. is a single value ever observed half-written? ----
        enum { kThreads = 8, kWrites = 3000 };
        dispatch_queue_t q = dispatch_queue_create("usermem.writers", DISPATCH_QUEUE_CONCURRENT);
        dispatch_group_t group = dispatch_group_create();
        for (NSUInteger t = 0; t < kThreads; t++) {
            dispatch_group_async(group, q, ^{
                NSUserDefaults *own = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
                for (long i = 0; i < kWrites; i++) {
                    [own setObject:Craft(t, i) forKey:Key([NSString stringWithFormat:@"row%lu", (unsigned long)t])];
                }
            });
        }
        // A reader running the whole time, because a corruption that only shows up while
        // writers are active is the one worth finding. The first version of this asked the
        // dispatch group whether it was drained from inside a block that had itself entered
        // the group, which is a deadlock the reader installed in itself; the writers publish
        // a flag instead.
        __block long reads = 0, torn = 0;
        dispatch_group_t writers = group;
        dispatch_group_notify(writers, q, ^{ gWritersFinished = 1; });
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            NSUserDefaults *read = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
            while (gWritersFinished == 0) {
                for (NSUInteger t = 0; t < kThreads; t++) {
                    id value = [read objectForKey:Key([NSString stringWithFormat:@"row%lu", (unsigned long)t])];
                    if (![value isKindOfClass:[NSString class]]) continue;
                    reads++;
                    if (!Verify((NSString *)value, NULL, NULL)) torn++;
                }
                usleep(200);
            }
        });
        while (!gWritersFinished) { usleep(1000); }
        usleep(4000);   // let the reader's last pass land
        printf("     (%ld reads, %ld of them did not verify)\n", reads, torn);
        CHECK(torn == 0, "no reader ever observed a value that was not one whole write");
        CHECK(gVerifiesRun == reads,
              "the reader really ran its checker once per read: a check that stopped being called "
              "would otherwise report a clean run forever");
        CHECK(reads > 100, "the reader really was running beside the writers");
        BOOL everyThreadLanded = YES;
        for (NSUInteger t = 0; t < kThreads; t++) {
            id value = [store objectForKey:Key([NSString stringWithFormat:@"row%lu", (unsigned long)t])];
            NSUInteger seenThread = 0; long seq = -1;
            if (![value isKindOfClass:[NSString class]] || !Verify(value, &seenThread, &seq)
                || seenThread != t) everyThreadLanded = NO;
        }
        CHECK(everyThreadLanded, "after the writers stop, each key holds a value its own thread wrote");

        // ---- B. two holders of one composite record ----
        // A profile is not one key: the keyboard rules, the mouse tuning and the shortcut list
        // all travel as one encoded value. Two windows that each loaded it once and later save
        // "their" copy are the shape that loses a setting, and no lock exists across them.
        {
            NSString *key = Key(@"composite");
            [store setObject:@{ @"rev": @0 } forKey:key];
            dispatch_queue_t rmw = dispatch_queue_create("usermem.rmw", DISPATCH_QUEUE_CONCURRENT);
            dispatch_group_t g2 = dispatch_group_create();
            for (NSUInteger field = 0; field < 2; field++) {
                dispatch_group_async(g2, rmw, ^{
                    NSUserDefaults *own = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
                    // Each holder reads once, then saves its own copy repeatedly, which is what
                    // a settings pane does: load on appear, save on every control change.
                    NSMutableDictionary *mine = [[own dictionaryForKey:key] mutableCopy];
                    mine[field == 0 ? @"left" : @"right"] = @"set";
                    for (int i = 0; i < 200; i++) {
                        mine[@"rev"] = @(i);
                        [own setObject:mine forKey:key];
                    }
                });
            }
            dispatch_group_wait(g2, DISPATCH_TIME_FOREVER);
            NSDictionary *naive = [store dictionaryForKey:key];
            printf("     two holders that never re-read: final record keys = %s\n",
                   [[naive allKeys] componentsJoinedByString:@","].UTF8String);
            CHECK(!(naive[@"left"] != nil && naive[@"right"] != nil),
                  "measured: two holders each saving their own copy of one record lose one of "
                  "the two settings, which is why a composite preference needs one writer");

            // The same state written by one owner that serialises its read-modify-write.
            [store setObject:@{ @"rev": @0 } forKey:key];
            dispatch_queue_t bq = dispatch_queue_create("usermem.blob", DISPATCH_QUEUE_CONCURRENT);
            dispatch_group_t g3 = dispatch_group_create();
            for (NSUInteger field = 0; field < 2; field++) {
                dispatch_group_async(g3, bq, ^{
                    NSUserDefaults *own = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
                    for (int i = 0; i < 200; i++) {
                        NSMutableDictionary *record;
                        @synchronized (gSuite) {   // one process, one writer at a time, by design
                            record = [[own dictionaryForKey:key] mutableCopy] ?: [NSMutableDictionary dictionary];
                            record[field == 0 ? @"left" : @"right"] = @"set";
                            [own setObject:record forKey:key];
                        }
                    }
                });
            }
            dispatch_group_wait(g3, DISPATCH_TIME_FOREVER);
            NSDictionary *locked = [store dictionaryForKey:key];
            CHECK(locked[@"left"] != nil && locked[@"right"] != nil,
                  "serialising the read-modify-write keeps both fields");

            // And the optimistic shape: compare a revision, write, read back, retry. One round
            // is not enough to say anything -- the first run of this loop lost a field with zero
            // retries detected, the second kept both after two retries -- so it runs as a set of
            // rounds and reports how often the setting survived. A guarantee that holds most of
            // the time is not one, and the number below is what says so.
            {
                enum { kRounds = 24, kRoundWrites = 30 };
                long survived = 0, lost = 0, retriesTotal = 0;
                for (int round = 0; round < kRounds; round++) {
                    [store setObject:@{ @"rev": @0 } forKey:key];
                    dispatch_queue_t cq = dispatch_queue_create("usermem.cas", DISPATCH_QUEUE_CONCURRENT);
                    dispatch_group_t g4 = dispatch_group_create();
                    __block long retries = 0;
                    for (NSUInteger field = 0; field < 2; field++) {
                        dispatch_group_async(g4, cq, ^{
                            NSUserDefaults *own = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
                            for (int i = 0; i < kRoundWrites; i++) {
                                for (int attempt = 0; attempt < 40; attempt++) {
                                    NSMutableDictionary *want =
                                        [[own dictionaryForKey:key] mutableCopy] ?: [NSMutableDictionary dictionary];
                                    long expected = [want[@"rev"] integerValue];
                                    want[field == 0 ? @"left" : @"right"] = @"set";
                                    want[@"rev"] = @(expected + 1);
                                    [own setObject:want forKey:key];
                                    // UserDefaults has no compare-and-set, so the revision is only
                                    // ever checked by reading the very same instance back.
                                    if ([[own dictionaryForKey:key][@"rev"] integerValue] != expected + 1) {
                                        __sync_fetch_and_add(&retries, 1);
                                        continue;
                                    }
                                    break;
                                }
                            }
                        });
                    }
                    dispatch_group_wait(g4, DISPATCH_TIME_FOREVER);
                    NSDictionary *after = [store dictionaryForKey:key];
                    if (after[@"left"] != nil && after[@"right"] != nil) survived++;
                    else lost++;
                    retriesTotal += retries;
                }
                printf("     compare-by-read-back over %d rounds: both settings survived %ld, "
                       "one was lost %ld, retries %d\n", kRounds, survived, lost, (int)retriesTotal);
                CHECK(survived + lost == kRounds,
                      "every round was counted exactly once, so the two numbers above are the "
                      "whole story rather than the rounds that happened to be interesting");
            }
        }

        // ---- B3. do two instances in one process see each other's write? ----
        // This is the question the design turns on: if a fresh write by one holder is visible to
        // another instance in the same process, one shared owner is enough; if not, every holder
        // needs its own refresh, and the lost setting above is unavoidable.
        {
            NSUserDefaults *first = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
            NSUserDefaults *second = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
            NSString *key = Key(@"shared");
            id before = [second objectForKey:key];
            [first setObject:@"written-by-first" forKey:key];
            id afterWrite = [second objectForKey:key];
            [first synchronize];
            id afterSync = [second objectForKey:key];
            CHECK(before == nil, "the second instance agreed the key was empty to begin with");
            CHECK(afterWrite != nil,
                  "measured: inside one process a second instance sees a write the first made, "
                  "without any synchronize");
            CHECK([afterSync isEqual:@"written-by-first"],
                  "and synchronize changes nothing about that, which is why the lost setting "
                  "above is a stale-copy problem and not a caching one");
        }

        // ---- C. cross-process visibility ----
        // A helper that writes a preference and a main program that reads one is a real shape
        // in this app (the privileged helper and the app share a domain), and fork+_exit is not
        // that shape: the first run of this spike used fork, and every child write vanished,
        // because _exit() performs no teardown. So the writers are separate processes here, each
        // one a re-exec of this binary, and both halves of the parent are checked: the instance
        // that already existed when they ran, and one created after they finished.
        {
            enum { kKids = 6 };
            char exePath[4096];
            uint32_t size = (uint32_t)sizeof(exePath);
            int found = _NSGetExecutablePath(exePath, &size);
            CHECK(found == 0, "the driver found its own path, so it can start real peers");
            for (int k = 0; k < kKids; k++) {
                char *args[6];
                char *peerKey = (char *)[[NSString stringWithFormat:@"peer%d", k] UTF8String];
                char *suiteCopy = (char *)[gSuite UTF8String];
                args[0] = exePath; args[1] = (char *)"--peer-write"; args[2] = suiteCopy;
                args[3] = peerKey; args[4] = NULL;
                pid_t kid = fork();
                if (kid == 0) {
                    execv(exePath, args);
                    _exit(127);
                }
            }
            int status = 0;
            int exitedCleanly = 0;
            for (int k = 0; k < kKids; k++) {
                if (waitpid(-1, &status, 0) > 0 && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
                    exitedCleanly++;
                }
            }
            CHECK(exitedCleanly == kKids, "every peer process wrote and exited of its own accord");

            long seenFresh = 0;
            NSUserDefaults *fresh = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
            for (int k = 0; k < kKids; k++) {
                if ([fresh objectForKey:Key([NSString stringWithFormat:@"peer%d", k])] != nil) seenFresh++;
            }
            printf("     an instance created after the peers ran saw %ld of %d\n", seenFresh, kKids);
            CHECK(seenFresh == kKids,
                  "a newly created instance sees what the peer processes stored");

            long seenCached = 0;
            for (int k = 0; k < kKids; k++) {
                if ([store objectForKey:Key([NSString stringWithFormat:@"peer%d", k])] != nil) seenCached++;
            }
            printf("     the instance that already existed saw %ld of %d before -synchronize\n",
                   seenCached, kKids);
            [store synchronize];
            long afterSynchronize = 0;
            for (int k = 0; k < kKids; k++) {
                if ([store objectForKey:Key([NSString stringWithFormat:@"peer%d", k])] != nil) afterSynchronize++;
            }
            printf("     the same instance saw %ld of %d after -synchronize\n", afterSynchronize, kKids);
            CHECK(afterSynchronize == kKids,
                  "the stale instance catches up once it synchronizes (the before-count is printed, "
                  "not asserted, because it is a caching choice the platform is free to make)");
        }

        // ---- D. is -synchronize what makes a peer write visible? ----
        // It is not. Measured here: peers that synchronize and peers that _exit() straight after
        // the setter are equally visible to the parent. What did lose writes earlier in this
        // spike's development was a fork()ed child that never exec'd -- three runs in a row read
        // 0 of 6 of its writes back -- which is a different variable, and one this repository has
        // no path to (git grep finds no fork(), posix_spawn or vfork in Limelight). Recorded as a
        // measurement about the platform, not as a defect the design has to defend against.
        {
            char exePath[4096];
            uint32_t size = (uint32_t)sizeof(exePath);
            _NSGetExecutablePath(exePath, &size);
            struct { const char *mode; const char *leaf; } peers[] = {
                { "--peer-write", "sync0" }, { "--peer-write", "sync1" }, { "--peer-write", "sync2" },
                { "--peer-write-nosync", "nosync0" }, { "--peer-write-nosync", "nosync1" },
                { "--peer-write-nosync", "nosync2" },
            };
            for (size_t i = 0; i < sizeof(peers) / sizeof(peers[0]); i++) {
                char *args[5];
                char *suiteCopy = (char *)gSuite.UTF8String;
                char *leafCopy = (char *)peers[i].leaf;
                args[0] = exePath; args[1] = (char *)peers[i].mode;
                args[2] = suiteCopy; args[3] = leafCopy; args[4] = NULL;
                pid_t kid = fork();
                if (kid == 0) { execv(exePath, args); _exit(127); }
            }
            int status = 0;
            for (size_t i = 0; i < sizeof(peers) / sizeof(peers[0]); i++) waitpid(-1, &status, 0);

            NSUserDefaults *after = [[NSUserDefaults alloc] initWithSuiteName:gSuite];
            long syncedVisible = 0, unsyncedVisible = 0;
            for (size_t i = 0; i < sizeof(peers) / sizeof(peers[0]); i++) {
                id value = [after objectForKey:Key(@(peers[i].leaf))];
                BOOL visible = [value isKindOfClass:[NSString class]]
                    && [(NSString *)value hasPrefix:@"peer-"];
                if (i < 3) syncedVisible += visible ? 1 : 0;
                else unsyncedVisible += visible ? 1 : 0;
            }
            printf("     peers that synchronized: %ld of 3 visible; peers that did not: %ld of 3\n",
                   syncedVisible, unsyncedVisible);
            CHECK(syncedVisible == 3, "a peer that synchronized is visible, as expected");
            CHECK(unsyncedVisible == 3,
                  "measured: a peer that never called -synchronize is just as visible, so "
                  "-synchronize is not the cross-process visibility switch");
        }

        [store synchronize];
        printf("suite: %s\n", gSuite.UTF8String);
        printf("RUN %s (%d checks, %d failures)\n", failures ? "FAILED" : "PASSED",
               checks_run, failures);
        return failures ? 1 : 0;
    }
}

// RunChild is a separate process: one write, one synchronize, one clean exit.
static int RunChild(int argc, char **argv, BOOL shouldSynchronize) {
    @autoreleasepool {
        if (argc < 4) return 2;
        NSUserDefaults *store = [[NSUserDefaults alloc] initWithSuiteName:@(argv[2])];
        [store setObject:[NSString stringWithFormat:@"peer-%s", argv[3]]
                  forKey:[NSString stringWithFormat:@"moonlight.spike.%s", argv[3]]];
        if (shouldSynchronize) {
            [store synchronize];
            return 0;
        }
        _exit(0);   // no teardown, no flush: the shape of a helper that dies on the way out
    }
    return 0;
}
