//
//  DiagnosticsReportBuilder+Live.h
//  Moonlight for macOS
//

#import "DiagnosticsReportBuilder.h"

NS_ASSUME_NONNULL_BEGIN

@interface DiagnosticsReportBuilder (Live)

/// The report for the app that is running: its version, this machine, what the system
/// currently lets it do, what it can see on the network, and the tail of its own log.
/// Every value is read on the calling thread, so call it from the main queue, where the
/// database and the pasteboard both belong.
+ (NSString *)currentReport;

/// Build it and put it on the pasteboard. NO means nothing was copied, which the caller
/// has to say out loud rather than leave the player wondering whether the button worked.
+ (BOOL)writeCurrentReportToPasteboard;
@end

NS_ASSUME_NONNULL_END
