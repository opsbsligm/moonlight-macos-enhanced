#!/usr/bin/env python3
"""Plant defects one at a time and ask whether the spikes' own assertions notice.

This follows scripts/code-signature-profile-tests.py: a check that never fails proves nothing,
so every rule the design depends on gets its implementation broken once, and the broken build
has to exit non-zero. A mutation that nothing can tell apart is reported as such instead of
being quietly dropped -- two of the concurrency mutations below are exactly that, and saying so
is the difference between a mutation test and a theatre.
"""
import os, subprocess, sys, tempfile, glob

HERE = os.path.dirname(os.path.abspath(__file__))
CLANG = os.popen("xcrun --find clang 2>/dev/null").read().strip() or \
        "/Library/Developer/CommandLineTools/usr/bin/clang"
SDK = os.popen("xcrun --sdk macosx --show-sdk-path 2>/dev/null").read().strip() or \
      "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"

MIGRATION = os.path.join(HERE, "spike_migration.m")
CONCURRENCY = os.path.join(HERE, "spike_concurrency.m")

MUTANTS = [
    ("spike_migration.m", "a schema from the future is read anyway",
     "    if (schema > kSchemaCurrent) {", "    if (schema > kSchemaCurrent + 64) {"),
    ("spike_migration.m", "this build writes over a newer build's record",
     "    if (sawSource == MLPrefReadSourceTooNew) {\n        return NO;",
     "    if (sawSource == MLPrefReadSourceTooNew) {\n        return YES;"),
    ("spike_migration.m", "every old schema is treated as migratable",
     "    if (schema < kSchemaOldestMigratable) {", "    if (schema < 0) {"),
    ("spike_migration.m", "a version written as text is coerced to a number",
     "    if (![version isKindOfClass:[NSNumber class]]) {", "    if (version == nil) {"),
    ("spike_migration.m", "a migration step returns what it did not understand",
     "    if (from != 2) return nil;", "    if (from != 2) return value;"),
    ("spike_migration.m", "an unversioned bare value is believed",
     "    if (![raw isKindOfClass:[NSDictionary class]]) {\n        if (outSource) *outSource = MLPrefReadSourceUnreadable;",
     "    if (![raw isKindOfClass:[NSDictionary class]]) {\n        if (outSource) *outSource = MLPrefReadSourceStored;\n        if (stats) { } return raw;"),
    ("spike_migration.m", "an unreadable record is not counted",
     "        if (stats) stats->unreadable++;\n        return fallback;\n    }\n    NSDictionary *rec",
     "        return fallback;\n    }\n    NSDictionary *rec"),
    ("spike_migration.m", "tooNew is folded into unreadable",
     "        if (stats) { stats->tooNew++; }", "        if (stats) { stats->unreadable++; }"),
    ("spike_migration.m", "the write layer stops vetting value types",
     "static BOOL IsStorableValue(id value) {\n    if (value == nil) return NO;",
     "static BOOL IsStorableValue(id value) {\n    if (value == nil) return NO;\n    if ([value isKindOfClass:[NSNull class]]) return NO;\n    if (value) return YES;"),
    ("spike_migration.m", "a refusal answers nil instead of the fallback",
     "        if (stats) { stats->tooNew++; }\n        return fallback;",
     "        if (stats) { stats->tooNew++; }\n        return nil;"),
    ("spike_migration.m", "every write claims schema 1",
     '    [d setObject:@{ @"s": @(kSchemaCurrent), @"v": value } forKey:key];',
     '    [d setObject:@{ @"s": @1, @"v": value } forKey:key];'),
    ("spike_migration.m", "clearing a preference stores a null instead",
     "        [d removeObjectForKey:key];   // clearing a preference is a removal, not a null payload",
     "        [d setObject:[NSNull null] forKey:key];"),
    ("spike_concurrency.m", "the reader stops checking its reads",
     "                    if (!Verify((NSString *)value, NULL, NULL)) torn++;", "                    (void)value;"),
    ("spike_concurrency.m", "the composite write drops its lock",
     "                        @synchronized (gSuite) {   // one process, one writer at a time, by design",
     "                        if (YES) {   // the lock is gone"),
    ("spike_concurrency.m", "a peer's value is renamed so readers disagree",
     '    return [NSString stringWithFormat:@"t%lu-s%ld-h%08lx",',
     '    return [NSString stringWithFormat:@"t%lu-s%ld-%08lx",'),
]


def build_and_run(source_path, work, name):
    src = os.path.join(work, name)
    open(src, "w").write(source_path)
    binary = os.path.join(work, name + ".bin")
    compile = subprocess.run([CLANG, "-fobjc-arc", "-isysroot", SDK, "-framework", "Foundation",
                              "-o", binary, src], capture_output=True, text=True)
    if compile.returncode != 0:
        return None, compile.stderr
    run = subprocess.run([binary], capture_output=True, text=True)
    return run, run.stdout + run.stderr


def cleanup():
    for path in glob.glob(os.path.join(os.path.expanduser("~/Library/Preferences"), "usermem.*.plist")):
        os.remove(path)


def main():
    print("== planted defects: does the spike notice? ==")
    print("clang: %s" % CLANG)
    print("sdk:   %s" % SDK)
    sources = {os.path.basename(p): open(p).read() for p in (MIGRATION, CONCURRENCY)}
    caught, missed, uncompiled = [], [], []
    with tempfile.TemporaryDirectory() as work:
        for path, label in (("spike_migration.m", "the migration spike"),
                            ("spike_concurrency.m", "the concurrency spike")):
            run, out = build_and_run(sources[path], work, path)
            if run is None:
                print("FAIL %s could not be compiled: %s" % (label, out.strip().splitlines()[-1:]))
                return 1
            ok = run.returncode == 0
            print("%-4s %s compiles and passes its own checks" % ("ok" if ok else "FAIL", label))
            if not ok:
                print(out)
                return 1

        for filename, label, old, new in MUTANTS:
            text = sources[filename]
            if old not in text:
                print("FAIL mutation %s could not be applied: the line it edits is not in the file" % label)
                missed.append(label + " (unappliable)")
                continue
            mutated = text.replace(old, new, 1)
            run, out = build_and_run(mutated, work, "mutant.m")
            if run is None:
                caught.append(label + " (refused to compile)")
                print("ok   caught by the compiler: %s" % label)
                continue
            if run.returncode != 0:
                first = [line for line in out.splitlines() if line.startswith("FAIL") or "error" in line]
                detail = first[0][:120] if first else "exited %d" % run.returncode
                caught.append(label)
                print("ok   caught: %-52s | %s" % (label, detail))
            else:
                missed.append(label)
                print("MISS not caught: %-50s | the spike still passed" % label)
    cleanup()
    print("\n%d caught, %d missed of %d planted defects" % (len(caught), len(missed), len(MUTANTS)))
    for label in missed:
        print("  missed: %s" % label)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
