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

NS_ASSUME_NONNULL_BEGIN

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

/// Assemble the sections in the order given, redact the whole of it once at the end
/// -- one pass, so a value cannot survive by arriving in a line nobody thought to
/// scrub -- and bring it under the cap, shortening the log block first.
+ (NSString *)reportFromSections:(NSArray<DiagnosticsReportSection *> *)sections;
@end

NS_ASSUME_NONNULL_END
