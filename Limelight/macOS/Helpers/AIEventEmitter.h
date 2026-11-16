//
//  AIEventEmitter.h
//  Moonlight
//
//  Semantic runtime event stream for Agent consumption. Each event is one
//  JSON line appended to a JSONL file. The schema is stable: the `event`
//  field names the event type, `data` carries typed fields, `seq` is a
//  process-wide monotonic counter, and `ts` is ISO-8601 UTC.
//
//  The emitter is a fire-and-forget singleton: callers emit from any
//  thread; the file write is serialised on a private queue and fsync'd
//  so a crash mid-write never leaves a torn line.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface AIEventEmitter : NSObject

/// Emit a semantic event. `event` is a stable snake_case identifier
/// (e.g. "key_mapping", "edge_controls_opened"). `data` holds typed
/// values that an Agent can branch on without parsing prose. Passing
/// nil for data is valid (the key is omitted, not an empty object).
+ (void)emit:(NSString *)event data:(nullable NSDictionary<NSString *, id> *)data;

/// The absolute path of the JSONL event file. Overridable for tests via
/// the ML_AI_EVENTS_PATH environment variable.
+ (NSString *)eventsFilePath;

/// Flush any pending writes and close the file handle. Call before the
/// process exits in headless mode so the last event is on disk.
+ (void)flushAndClose;

@end

NS_ASSUME_NONNULL_END
