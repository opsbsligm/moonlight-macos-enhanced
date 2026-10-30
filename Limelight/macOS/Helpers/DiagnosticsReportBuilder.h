//
//  DiagnosticsReportBuilder.h
//  Moonlight for macOS
//
//  The text a player pastes into an issue. Building it is one job and taking the
//  machine's measurements is another, so this file holds the shape and the privacy
//  rules and nothing that needs a running app: `DiagnosticsReportBuilder+Live.m`
//  is where the version numbers, permissions and hosts are read.
//

#import <Foundation/Foundation.h>

@class InputDiagnosticsSummary;
@class MLControllerInventorySnapshot;

NS_ASSUME_NONNULL_BEGIN

/// One hand-feel parameter the player can move, stated the way the stream states it:
/// the shipped constant, the published range the stream clamps to, and the override the
/// player actually wrote (zero meaning "no preference written"). The live side fills the
/// shipped default and the range from the same compile-time constants the stream's getter
/// reads, so a report cannot name a number the stream would never use.
@interface DiagnosticsFeatureParam : NSObject
@property (nonatomic, copy, readonly) NSString *label;
@property (nonatomic, readonly) double shippedDefault;
@property (nonatomic, readonly) double minimum;
@property (nonatomic, readonly) double maximum;
@property (nonatomic, readonly) double overrideValue;
+ (instancetype)paramWithLabel:(NSString *)label
               shippedDefault:(double)shippedDefault
                       minimum:(double)minimum
                       maximum:(double)maximum
                overrideValue:(double)overrideValue;
@end

/// Everything the feature-state block reports, already read off the running app. It is a
/// plain value object on purpose: the block's whole job is to turn settings into "what is
/// in force right now", and that decision has to be compiled and replayed without a
/// stream, a host, or a pair of hands on a controller.
///
/// Two shapes carry the honesty of the block. An override of zero is not a value, it is
/// the absence of one, and it has to read as the shipped constant. A measurement the app
/// does not have -- no stream, so no video counters, no reconnector -- has to read as
/// absent, because a zero printed where a counter should be is the single most
/// misleading thing this block can hold.
@interface DiagnosticsFeatureState : NSObject
/// "global profile" or "per-host profile". The host's own identifier never appears here:
/// a report says which rules applied, not which machine they applied to.
@property (nonatomic, copy) NSString *profileScope;
@property (nonatomic, copy) NSArray<DiagnosticsFeatureParam *> *sidebarParams;
/// Feature switches by preference key. A key that is absent reads as unknown rather than
/// as off, which is the difference between "this build has no such switch" and "the
/// player turned it off".
@property (nonatomic, copy) NSDictionary<NSString *, NSNumber *> *switches;
/// The pointer path the running session settled on. Empty means nothing was recorded.
@property (nonatomic, copy) NSDictionary<NSString *, NSString *> *pointerState;
@property (nonatomic) BOOL hasVideoStats;
@property (nonatomic) uint32_t receivedFrames;
@property (nonatomic) uint32_t decodedFrames;
@property (nonatomic) uint32_t renderedFrames;
@property (nonatomic) uint64_t receivedBytes;
@property (nonatomic) float renderedFps;
@property (nonatomic) float jitterMs;
@property (nonatomic, copy, nullable) NSString *videoFormatName;
@property (nonatomic) BOOL hasReconnectState;
@property (nonatomic) NSUInteger reconnectAttemptCount;
@property (nonatomic) NSUInteger reconnectMaxAttempts;
@property (nonatomic) BOOL reconnectPending;
@property (nonatomic) BOOL reconnectHostConfirmedGone;
/// Which commit produced the running binary, read off the bundle by the live layer.
/// Empty or the word `unknown` means the build had no readable HEAD -- a source tarball,
/// or a build that predated this key -- and that has to print as `unknown` rather than
/// being inferred from the build number, because two branches share build numbers.
@property (nonatomic, copy, nullable) NSString *gitCommit;
/// The marketing version and bundle version the binary announced itself with, so a
/// report can be tied to a shipped DMG without asking the player to read the About pane.
@property (nonatomic, copy, nullable) NSString *appVersion;
@property (nonatomic, copy, nullable) NSString *buildNumber;
@end

/// One titled block of the report. English on purpose, in both the title and the
/// lines: the reader is whoever maintains the client or triages the report, not the
/// player whose language the menus are translated into.
@interface DiagnosticsReportSection : NSObject
@property (nonatomic, copy, readonly) NSString *title;
@property (nonatomic, copy, readonly) NSArray<NSString *> *lines;
+ (instancetype)sectionWithTitle:(NSString *)title lines:(NSArray<NSString *> *)lines;
@end

@interface DiagnosticsReportBuilder : NSObject

/// The title of the block that carries log lines. The cap shortens this block
/// before it shortens the report, because the header -- version, macOS, permissions
/// -- is the part a report is useless without, while the fiftieth old log line is
/// the part a report survives without.
+ (NSString *)logSectionTitle;

/// The character cap for one report, so the text still pastes into an issue body.
+ (NSUInteger)reportCharacterCap;

/// The line cap for one log tail.
+ (NSUInteger)logLineCap;

/// The last `maxLines` non-empty lines of a log body, in the order they were written.
+ (NSArray<NSString *> *)recentLinesFromLog:(NSString *)logBody maxLines:(NSUInteger)maxLines;

/// The privacy pass. What must not leave the machine in a report: a PIN, a password
/// or token, a pinned certificate or any other long opaque blob, a MAC address, a
/// UUID that identifies the client or the host, and the player's home path, which is
/// where their user name is written. Each rule leaves a marker behind, so a reader
/// can tell redaction from absence, and a maintainer can tell that the value existed.
+ (NSString *)redactString:(NSString *)input;

/// The same pass with the home path supplied rather than looked up. A rule whose one
/// job is to remove the player's own path has to be testable against a path that is
/// not the tester's, so the lookup lives in the caller and this one takes the value.
+ (NSString *)redactString:(NSString *)input homeDirectory:(nullable NSString *)home;

/// The block that says what the pointer-input path did.
///
/// `summary` may be nil, which means the app never recorded any input at all; that has to
/// read as absence, not as a session in which nothing moved. `now` is passed in rather than
/// read from the clock so the same summary can be shown to say "ended 15s ago" in a test and
/// in the shipping app.
///
/// The counters only advance while the "Input Diagnostics" switch is on. A session that ran
/// without it says so instead of printing zeros, because zeros are the single most
/// misleading thing this block can hold: they read like a pointer that never moved when the
/// truth is that nobody was counting. `collectionEnabledNow` is the switch as it stands
/// while the report is written, which is a different question from whether it was on during
/// the session the counters describe -- a player who turned it on after the mouse stopped
/// has to be told that the numbers below it were never collected.
+ (DiagnosticsReportSection *)inputSectionWithSummary:(nullable InputDiagnosticsSummary *)summary
                                collectionEnabledNow:(BOOL)collectionEnabledNow
                                                 now:(NSDate *)now;

/// Format the recorded inventory without enumerating devices. nil means no observation.
/// Protocol type candidates and HID node counts do not imply host advertisements or a
/// physical device count.
+ (DiagnosticsReportSection *)controllersSectionWithSnapshot:(nullable MLControllerInventorySnapshot *)snapshot;

/// The block that answers "what is this build actually doing right now", which is the
/// question every real-device acceptance check asks and no screenshot answers. Settings
/// are reported as the value in force, not the number in the file: a player who wrote
/// 30pt for a band the stream caps at 16pt has to see 16pt, and a parameter nobody
/// touched has to say it is the shipped default, so an upgrade cannot silently move it.
///
/// `state` is never nil. A build that could read nothing still produces a block, because
/// an absent block reads as "there is no such feature" to whoever receives the report.
+ (DiagnosticsReportSection *)featureStateSectionWithState:(DiagnosticsFeatureState *)state;

/// The feature switches this block reports, in reading order, as their settings keys.
/// The live side reads its values through this list rather than carrying a copy: the one
/// place that knows which switches exist is the block that prints them, so a switch added
/// to the block is reported by every build that compiles it, and a switch the settings
/// never wrote still arrives as a key with no value -- which prints as unknown.
+ (NSArray<NSString *> *)featureSwitchKeys;

/// The switch values one settings profile carries, narrowed to `featureSwitchKeys`. A key the
/// profile does not hold is left out rather than defaulted, because "the player turned it off"
/// and "this build never wrote a value" are fixed differently and the block has to keep them
/// apart. Both live paths go through here so neither can invent a third answer.
+ (NSDictionary<NSString *, NSNumber *> *)featureSwitchesFromPreferences:(nullable NSDictionary *)preferences;

/// The machine-readable mirror of the feature and controller blocks: one `ml.x.y=value`
/// line per fact, so a real-device acceptance run can be graded from the report instead of
/// from a screenshot.
///
/// It is a mirror and not a second opinion. Every value comes from the same two objects the
/// human blocks above already render, so the prose and the keys cannot disagree, and the
/// same three absences -- a switch the profile never wrote, a session with no video
/// counters, a stream window with no reconnector -- are written as `unknown` or
/// `present=no` rather than as zero. A checker that reads `rendered=0` would report a host
/// that sent nothing; the truth may be that nothing was ever measured.
///
/// The controller group count is the one number here that must not be read as a physical
/// device count: two controllers of the same model are one VID/PID/family group. It is
/// emitted as `ml.controllers.group_count`, and the key next to it --
/// `ml.controllers.group_count_is_physical_devices=no` -- states the limit, so misreading it
/// takes a parser choosing to ignore a key rather than failing to notice a sentence.
+ (DiagnosticsReportSection *)machineStateSectionWithState:(DiagnosticsFeatureState *)state
                                                  snapshot:(nullable MLControllerInventorySnapshot *)snapshot;

/// Assemble the sections in the order given, redact the whole of it once at the end
/// -- one pass, so a value cannot survive by arriving in a line nobody thought to
/// scrub -- and bring it under the cap, shortening the log block first.
+ (NSString *)reportFromSections:(NSArray<DiagnosticsReportSection *> *)sections;

/// The exact bytes an exported report file must hold.
///
/// A checker grades an exported report by hashing the file it was given, and a hash covers
/// every byte: one trailing newline from an editor, one CR that an editor normalised, and
/// the declaration the player wrote stops matching the report it described. That failure is
/// invisible until a whole acceptance run grades as unknown, so the app writes the file
/// itself, from these bytes, and nobody pastes a report into a file again.
///
/// The shape is one UTF-8 line per line, LF separated, no trailing blanks, and the file
/// ending in exactly one LF. Lines are found with `enumerateLinesUsingBlock:`, which
/// treats CR, CRLF, U+2028 and U+2029 as terminators too, because the point is that a
/// report reaching a checker from this app always reads the same way -- a separator the
/// checker's own line reader treats as a line break has to be folded here rather than
/// survive to make two files out of one report.
///
/// Idempotent on purpose: an export of a report that was itself exported hashes the same.
+ (NSData *)canonicalReportBytesFromString:(NSString *)report;

/// Write a report to a file as exactly those bytes, or say why it did not happen.
///
/// The write is atomic, so a cancelled save cannot leave a half report that a checker then
/// grades: a file that exists is a file that holds a whole report. The error is handed back
/// rather than swallowed, because an export button that returns to normal and wrote nothing
/// is the failure a player cannot see.
+ (BOOL)writeReport:(NSString *)report toURL:(NSURL *)url error:(NSError *_Nullable *_Nullable)error;
@end

NS_ASSUME_NONNULL_END
