//
//  AIEventEmitter.m
//  Moonlight
//

#import "AIEventEmitter.h"

#include <sys/stat.h>

/// One serial queue owns the file handle and the sequence counter. A crash
/// mid-write must not leave a torn line behind, so every line is written in a
/// single `write:` call and fsync'd before the next is accepted. The cost is
/// one fsync per event; the events this emitter carries are session-scale
/// (a handful per stream), not frame-scale.

@implementation AIEventEmitter

static dispatch_queue_t AIEventQueue(void) {
    static dispatch_queue_t queue;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        queue = dispatch_queue_create("moonlight.ai-events", DISPATCH_QUEUE_SERIAL);
    });
    return queue;
}

+ (NSString *)eventsFilePath {
    const char *override = getenv("ML_AI_EVENTS_PATH");
    if (override != NULL && *override != '\0') {
        return [NSString stringWithUTF8String:override];
    }
    NSString *logs = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Moonlight"];
    return [logs stringByAppendingPathComponent:@"ai-events.jsonl"];
}

+ (void)emit:(NSString *)event data:(nullable NSDictionary<NSString *, id> *)data {
    if (event.length == 0) return;
    // Copy up front: the caller's dictionary is not ours to hold, and the
    // write happens on another queue.
    NSString *eventCopy = [event copy];
    NSDictionary *dataCopy = data.count > 0 ? [data copy] : nil;
    dispatch_async(AIEventQueue(), ^{
        [self appendLineForEvent:eventCopy data:dataCopy];
    });
}

+ (void)flushAndClose {
    // Synchronising against the serial queue is what makes "flushed" mean
    // "every emit issued before this call is on disk", not "the queue was
    // briefly idle".
    dispatch_sync(AIEventQueue(), ^{
        static NSFileHandle *flushHandle;
        // The handle is process-global for the life of the queue; flush is
        // the only thing that needs it out of the write path.
        if (flushHandle != nil) {
            @try { [flushHandle synchronizeFile]; } @catch (__unused NSException *e) {}
        }
    });
}

+ (void)appendLineForEvent:(NSString *)event data:(nullable NSDictionary<NSString *, id> *)data {
    static NSFileHandle *fileHandle;
    static unsigned long long sequence;
    static NSDateFormatter *formatter;
    // The identity of the file the open handle points at. When the file is
    // replaced out from under us (a crash left a zero-byte file, the user
    // cleared the Logs folder, a test swapped ML_AI_EVENTS_PATH) the descriptor
    // is still open but no longer the file the next read will find, so the
    // inode check re-opens instead of appending into the orphan.
    static ino_t openInode = 0;
    static dev_t openDevice = 0;

    if (formatter == nil) {
        formatter = [[NSDateFormatter alloc] init];
        formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
        formatter.timeZone = [NSTimeZone timeZoneWithName:@"UTC"];
        formatter.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'";
    }

    NSMutableDictionary *line = [NSMutableDictionary dictionary];
    line[@"ts"] = [formatter stringFromDate:[NSDate date]];
    sequence += 1;
    line[@"seq"] = @(sequence);
    line[@"pid"] = @(getpid());
    line[@"event"] = event;
    if (data != nil) {
        line[@"data"] = data;
    }

    // JSONSerialization can still fail on a value that is not plist-compatible
    // (a caller slipped a CF object in). Refuse rather than write a line an
    // Agent cannot parse: a partial line in a JSONL file is worse than no
    // line, because the reader stops at the first bad one.
    if (![NSJSONSerialization isValidJSONObject:line]) {
        return;
    }
    NSError *jsonError = nil;
    NSData *bytes = [NSJSONSerialization dataWithJSONObject:line options:0 error:&jsonError];
    if (bytes == nil || jsonError != nil) {
        return;
    }
    NSMutableData *lineData = [NSMutableData dataWithData:bytes];
    [lineData appendBytes:(const uint8_t *)"\n" length:1];

    NSString *path = [self eventsFilePath];
    NSFileManager *fm = [NSFileManager defaultManager];
    if (![fm fileExistsAtPath:path] && ![fm createDirectoryAtPath:[path stringByDeletingLastPathComponent]
                                                 withIntermediateDirectories:YES
                                                                  attributes:nil
                                                                       error:NULL]) {
        // Cannot even make the log directory; the event is dropped, not
        // retried, because this path is only reached when something the
        // rest of the app depends on is already broken.
        return;
    }
    struct stat current;
    BOOL handleValid = fileHandle != nil &&
        stat([path fileSystemRepresentation], &current) == 0 &&
        current.st_ino == openInode && current.st_dev == openDevice;
    if (!handleValid) {
        if (fileHandle != nil) {
            @try { [fileHandle closeFile]; } @catch (__unused NSException *e) {}
        }
        fileHandle = [NSFileHandle fileHandleForWritingAtPath:path];
        if (fileHandle == nil) {
            [fm createFileAtPath:path contents:nil attributes:nil];
            fileHandle = [NSFileHandle fileHandleForWritingAtPath:path];
        }
        if (fileHandle == nil) return;
        [fileHandle seekToEndOfFile];
        struct stat identity;
        if (fstat([fileHandle fileDescriptor], &identity) == 0) {
            openInode = identity.st_ino;
            openDevice = identity.st_dev;
        }
    }
    @try {
        [fileHandle writeData:lineData];
        [fileHandle synchronizeFile];
    } @catch (__unused NSException *exception) {
        // A write exception means the handle is no longer valid; close it so
        // the next event re-opens instead of failing again in place.
        [fileHandle closeFile];
        fileHandle = nil;
    }
}

@end
