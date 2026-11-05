// Spike 1: does a versioned record with "unknown version handled adversely" actually hold up?
// Compiled and run with the same clang/SDK pair the repository's behavioural gates use.
// Nothing here is imported from the repository; it is a shape test for docs/Design/user-memory.md.
#import <Foundation/Foundation.h>
#import <unistd.h>
#import <sys/wait.h>
#import <mach-o/dyld.h>
#include <string.h>

static int failures = 0;
static int checks_run = 0;

/// Evaluate the expression exactly once, the way scripts/code-signature-profile-tests.py does.
#define CHECK(ok, what) do { const BOOL _passed = (ok); checks_run++; if (!_passed) failures++; \
    printf("%-4s %s\n", _passed ? "ok" : "FAIL", (what)); } while (0)

// ---- the shape under test ----------------------------------------------------
// One record per key, self-describing: {"s": schema, "v": value}. A bare value written
// by the pre-version app has no envelope, which is the case a real migration must face.
static NSString *const kSchemaKey = @"moonlight.schema";
static NSInteger const kSchemaCurrent = 3;
static NSInteger const kSchemaOldestMigratable = 2;   // v1 is refused, not guessed

typedef NS_ENUM(NSInteger, MLPrefReadSource) {
    MLPrefReadSourceDefault = 0,   // nothing stored
    MLPrefReadSourceStored,        // stored at current schema
    MLPrefReadSourceMigrated,      // stored older, migrated forward
    MLPrefReadSourceTooOld,        // older than anything we can migrate
    MLPrefReadSourceTooNew,        // newer than this build understands
    MLPrefReadSourceUnreadable,    // envelope present but not a shape we can trust
};

__attribute__((unused)) static NSString *SourceName(MLPrefReadSource s) {
    switch (s) {
        case MLPrefReadSourceDefault: return @"default";
        case MLPrefReadSourceStored: return @"stored";
        case MLPrefReadSourceMigrated: return @"migrated";
        case MLPrefReadSourceTooOld: return @"tooOld";
        case MLPrefReadSourceTooNew: return @"tooNew";
        case MLPrefReadSourceUnreadable: return @"unreadable";
    }
    return @"?";
}

typedef struct { NSInteger schemaVersion; NSInteger unreadable; NSInteger tooNew; } MLPrefStats;

// nil means "this step cannot produce a value", which the caller reads as a refusal.
// A step that returned its input for a shape it did not recognise was the first version of
// this file, and check 7 caught it: a v2 payload of @"not a pair" flowed through unchanged
// and was reported as a successful migration.
static id Migrate(id value, NSInteger from) {
    if (from != 2) return nil;                       // no other step exists yet
    if (![value isKindOfClass:[NSArray class]]) return nil;
    NSArray *pair = (NSArray *)value;
    if (pair.count != 2) return nil;
    if (![pair[0] isKindOfClass:[NSNumber class]] || ![pair[1] isKindOfClass:[NSNumber class]]) {
        return nil;
    }
    return [NSString stringWithFormat:@"%@x%@", pair[0], pair[1]];
}

// Read refuses rather than guesses. It never mutates what is on disk.
static id ReadRecord(NSUserDefaults *d, NSString *key, id fallback,
                     MLPrefReadSource *outSource, MLPrefStats *stats) {
    id raw = [d objectForKey:key];
    if (raw == nil) { if (outSource) *outSource = MLPrefReadSourceDefault; return fallback; }
    if (![raw isKindOfClass:[NSDictionary class]]) {
        if (outSource) *outSource = MLPrefReadSourceUnreadable;
        if (stats) stats->unreadable++;
        return fallback;
    }
    NSDictionary *rec = (NSDictionary *)raw;
    id version = rec[@"s"];
    if (![version isKindOfClass:[NSNumber class]]) {
        if (outSource) *outSource = MLPrefReadSourceUnreadable;
        if (stats) stats->unreadable++;
        return fallback;
    }
    NSInteger schema = [(NSNumber *)version integerValue];
    id value = rec[@"v"];
    if (schema > kSchemaCurrent) {
        // A future build wrote this. Refusing is the only answer that cannot destroy data.
        if (outSource) *outSource = MLPrefReadSourceTooNew;
        if (stats) { stats->tooNew++; }
        return fallback;
    }
    if (schema < kSchemaOldestMigratable) {
        if (outSource) *outSource = MLPrefReadSourceTooOld;
        return fallback;
    }
    while (schema < kSchemaCurrent) {
        id next = Migrate(value, schema);
        if (next == nil) {
            if (outSource) *outSource = MLPrefReadSourceUnreadable;
            if (stats) stats->unreadable++;
            return fallback;
        }
        value = next;
        schema++;   // in memory only; the write layer is what persists
    }
    if (value == nil || [value isKindOfClass:[NSNull class]]) {
        if (outSource) *outSource = MLPrefReadSourceUnreadable;
        if (stats) stats->unreadable++;
        return fallback;
    }
    if (outSource) *outSource = ([(NSNumber *)version integerValue] == kSchemaCurrent)
        ? MLPrefReadSourceStored : MLPrefReadSourceMigrated;
    return value;
}

// [NSNull null] is not a property-list type. Measured on macOS 27.2: writing one into
// NSUserDefaults does not raise an Objective-C exception that @try could catch, it aborts
// the process inside CoreFoundation (_CFPrefsValidateValueForKey -> abort, SIGABRT). So the
// value is checked here, before the setter, rather than trusting the framework to complain.
static BOOL IsStorableValue(id value) {
    if (value == nil) return NO;
    if ([value isKindOfClass:[NSString class]]) return YES;
    if ([value isKindOfClass:[NSNumber class]]) return YES;
    if ([value isKindOfClass:[NSDate class]]) return YES;
    if ([value isKindOfClass:[NSData class]]) return YES;
    if ([value isKindOfClass:[NSArray class]]) {
        for (id one in (NSArray *)value) if (!IsStorableValue(one)) return NO;
        return YES;
    }
    if ([value isKindOfClass:[NSDictionary class]]) {
        for (id one in (NSDictionary *)value) {
            if (![one isKindOfClass:[NSString class]] || !IsStorableValue(((NSDictionary *)value)[one])) return NO;
        }
        return YES;
    }
    return NO;   // NSNull, a URL, a custom object, anything CFPrefs would abort on
}

// Write refuses to downgrade a record this build could not read.
static BOOL WriteRecord(NSUserDefaults *d, NSString *key, id value,
                        MLPrefReadSource sawSource) {
    if (sawSource == MLPrefReadSourceTooNew) {
        return NO;   // somebody newer owns this key; leaving it alone is the whole point
    }
    if (value == nil) {
        [d removeObjectForKey:key];   // clearing a preference is a removal, not a null payload
        return YES;
    }
    if (!IsStorableValue(value)) return NO;
    [d setObject:@{ @"s": @(kSchemaCurrent), @"v": value } forKey:key];
    return YES;
}

// ---- the driver -------------------------------------------------------------
static NSString *gSuite;

static NSUserDefaults *FreshSuite(void) {
    static int n = 0;
    NSString *name = [NSString stringWithFormat:@"%@.%d", gSuite, ++n];
    NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:name];
    [d removePersistentDomainForName:name];
    return d;
}

static int RunAbortProbe(void);

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--abort-probe") == 0) return RunAbortProbe();
    @autoreleasepool {
        gSuite = [NSProcessInfo processInfo].processIdentifier
               ? [NSString stringWithFormat:@"usermem.migration.%lu",
                  (unsigned long)[[NSProcessInfo processInfo] processIdentifier]] : @"usermem.migration";
        printf("== spike 1: schema versioning on macOS %s ==\n",
               [[[NSProcessInfo processInfo] operatingSystemVersionString] UTF8String]);

        // 1. nothing stored
        {
            NSUserDefaults *d = FreshSuite();
            MLPrefReadSource src; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK([v isEqual:@"1080p"] && src == MLPrefReadSourceDefault,
                  "an absent key answers the fallback and says it was absent");
        }

        // 2. round trip at current schema
        {
            NSUserDefaults *d = FreshSuite();
            MLPrefReadSource src = MLPrefReadSourceDefault;
            WriteRecord(d, @"moonlight.stream.resolution", @"1440p", src);
            [d synchronize];
            MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK([v isEqual:@"1440p"] && src == MLPrefReadSourceStored,
                  "a value written by this build reads back as stored, not migrated");
            NSDictionary *rec = [d objectForKey:@"moonlight.stream.resolution"];
            CHECK([rec isKindOfClass:[NSDictionary class]] && [rec[@"s"] integerValue] == kSchemaCurrent,
                  "the record on disk carries its own schema version");
        }

        // 3. legacy bare value (the pre-version world) is refused, not silently trusted
        {
            NSUserDefaults *d = FreshSuite();
            [d setObject:@"720p" forKey:@"moonlight.stream.resolution"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK(src == MLPrefReadSourceUnreadable && [v isEqual:@"1080p"],
                  "a bare unversioned value is called unreadable and the fallback answers");
            CHECK(st.unreadable == 1, "and the refusal is counted, the way the panel counts unreadable rules");
            CHECK([d objectForKey:@"moonlight.stream.resolution"] != nil,
                  "the refusal left the foreign value on disk instead of erasing evidence");
        }

        // 4. migration v2 -> v3
        {
            NSUserDefaults *d = FreshSuite();
            [d setObject:@{ @"s": @2, @"v": @[ @1920, @1080 ] }
                    forKey:@"moonlight.stream.resolution"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK([v isEqual:@"1920x1080"] && src == MLPrefReadSourceMigrated,
                  "a v2 pair migrates to the v3 string and reports that it was migrated");
            NSDictionary *before = [d objectForKey:@"moonlight.stream.resolution"];
            CHECK([before[@"s"] integerValue] == 2,
                  "reading does not rewrite the record: migration is a write-layer decision");
            CHECK(WriteRecord(d, @"moonlight.stream.resolution", v, src),
                  "the migrated value may be written forward");
            CHECK([[d objectForKey:@"moonlight.stream.resolution"][@"s"] integerValue] == kSchemaCurrent,
                  "and the write advances the stored schema");
        }

        // 5. too old is refused
        {
            NSUserDefaults *d = FreshSuite();
            [d setObject:@{ @"s": @1, @"v": @[ @640, @480 ] }
                    forKey:@"moonlight.stream.resolution"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK(src == MLPrefReadSourceTooOld && [v isEqual:@"1080p"],
                  "a schema older than the migration floor is refused rather than guessed");
            CHECK([d objectForKey:@"moonlight.stream.resolution"] != nil,
                  "the old record survives the refusal so a newer build can still read it");
        }

        // 6. the load-bearing one: a newer schema must not be downgraded away
        {
            NSUserDefaults *d = FreshSuite();
            NSDictionary *future = @{ @"s": @(kSchemaCurrent + 4),
                                      @"v": @{ @"res": @"4k", @"hdr": @YES } };
            [d setObject:future forKey:@"moonlight.stream.quality"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.quality", @"balanced", &src, &st);
            CHECK(src == MLPrefReadSourceTooNew && [v isEqual:@"balanced"],
                  "a record from a newer build answers the fallback and says tooNew");
            CHECK(st.tooNew == 1, "the tooNew case is counted on its own, not folded into unreadable");
            CHECK(WriteRecord(d, @"moonlight.stream.quality", @"fast", src) == NO,
                  "this build refuses to write over a key a newer build owns");
            CHECK([[d objectForKey:@"moonlight.stream.quality"] isEqual:future],
                  "and the future record is byte-for-byte the one that was there");
        }

        // 7. a migration step that cannot produce a value is a refusal, not a nil
        {
            NSUserDefaults *d = FreshSuite();
            [d setObject:@{ @"s": @2, @"v": @"not a pair" } forKey:@"moonlight.stream.resolution"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.resolution", @"1080p", &src, &st);
            CHECK(src == MLPrefReadSourceUnreadable && [v isEqual:@"1080p"],
                  "a v2 record whose payload is not a pair is refused instead of formatted as \"(null)x\"");
        }

        // 8. envelope with a non-numeric version
        {
            NSUserDefaults *d = FreshSuite();
            [d setObject:@{ @"s": @"3", @"v": @"4k" } forKey:@"moonlight.stream.quality"];
            MLPrefReadSource src = MLPrefReadSourceDefault; MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.stream.quality", @"balanced", &src, &st);
            CHECK(src == MLPrefReadSourceUnreadable && [v isEqual:@"balanced"],
                  "a schema version written as a string is not coerced into a number");
        }

        // 9. What does the platform actually do with a null payload? It cannot be stored and
        // read back -- the write kills the process -- so the case is measured rather than staged.
        // The probe is a re-exec of this binary, not a fork()ed child: forked children inherit a
        // cfprefs connection they should not keep, and one did not abort on the same call that
        // killed two standalone processes (both crashes are in ~/Library/Logs/DiagnosticReports).
        {
            char exePath[4096];
            uint32_t size = (uint32_t)sizeof(exePath);
            _NSGetExecutablePath(exePath, &size);
            char *args[3] = { exePath, (char *)"--abort-probe", NULL };
            pid_t kid = fork();
            if (kid == 0) { execv(exePath, args); _exit(127); }
            int status = 0;
            waitpid(kid, &status, 0);
            BOOL aborted = WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT;
            printf("     a separate process writing [NSNull null] exited with signal %d\n",
                   WIFSIGNALED(status) ? WTERMSIG(status) : 0);
            CHECK(aborted, "measured: NSUserDefaults aborts a process on a null payload, it does not raise");
        }

        // 9b. the migration step is asked about the versions it cannot handle, directly: the
        // guard below is unreachable through ReadRecord while the floor is 2, and a mutation of
        // an unreachable line is a mutation nothing can catch.
        {
            CHECK(Migrate(@"anything", 1) == nil, "step 1 refuses to migrate what it has no rule for");
            CHECK(Migrate(@[ @1, @2 ], 3) == nil, "a step beyond the current schema is refused too");
            CHECK([Migrate(@[ @8, @6 ], 2) isEqual:@"8x6"], "the one real step still works");
        }

        // 10. zero is a real answer and must not read as absent
        {
            NSUserDefaults *d = FreshSuite();
            MLPrefReadSource src = MLPrefReadSourceDefault;
            WriteRecord(d, @"moonlight.input.mouseSpeed", @0, src);
            MLPrefStats st = {0,0,0};
            id v = ReadRecord(d, @"moonlight.input.mouseSpeed", @5, &src, &st);
            CHECK([v isEqual:@0] && src == MLPrefReadSourceStored,
                  "a stored zero is a stored value, not a missing one");
        }

        // 10b. every source has its own word, because two sources sharing one name is how a
        // support thread ends up unable to tell "nothing stored" from "refused to read it".
        {
            NSMutableSet *names = [NSMutableSet set];
            for (NSInteger raw = 0; raw <= MLPrefReadSourceUnreadable; raw++) {
                [names addObject:SourceName((MLPrefReadSource)raw)];
            }
            CHECK(names.count == 6, "the six read sources have six distinct names");
        }

        // 11. the value that would abort the process is refused before the setter runs
        {
            NSUserDefaults *d = FreshSuite();
            MLPrefReadSource src = MLPrefReadSourceDefault;
            CHECK(WriteRecord(d, @"moonlight.ui.lastPane", [NSNull null], src) == NO,
                  "a null value is refused by the write layer instead of reaching CFPrefs");
            CHECK([d objectForKey:@"moonlight.ui.lastPane"] == nil,
                  "and nothing was stored on the way to the refusal");
            CHECK(IsStorableValue([NSURL fileURLWithPath:@"/tmp"]) == NO,
                  "a non-property-list object is refused for the same reason");
            CHECK(IsStorableValue(@[ @1, @{ @"k": @[ @"deep" ] } ]) == YES,
                  "a nested property-list value still passes");
        }

        // 12. clearing a preference is a removal
        {
            NSUserDefaults *d = FreshSuite();
            MLPrefReadSource src = MLPrefReadSourceDefault;
            WriteRecord(d, @"moonlight.stream.bitrate", @60000000, src);
            id stored = [d objectForKey:@"moonlight.stream.bitrate"];
            WriteRecord(d, @"moonlight.stream.bitrate", nil, MLPrefReadSourceStored);
            CHECK(stored != nil && [d objectForKey:@"moonlight.stream.bitrate"] == nil,
                  "writing nil removes the record rather than storing a null");
        }

        printf("\nRUN %s (%d checks, %d failures)\n", failures ? "FAILED" : "PASSED",
               checks_run, failures);
        return failures ? 1 : 0;
    }
}

// RunAbortProbe writes one illegal value and prints if it survives. It does not survive.
static int RunAbortProbe(void) {
    @autoreleasepool {
        NSUserDefaults *raw = [[NSUserDefaults alloc]
            initWithSuiteName:@"usermem.migration.abortprobe"];
        [raw setObject:@{ @"s": @3, @"v": [NSNull null] } forKey:@"moonlight.ui.lastPane"];
        printf("the illegal write came back\n");
    }
    return 0;
}
