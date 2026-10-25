#pragma once
#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN
// K1.2 local IME composition (default off). The document half of the pair the
// system text input context types into: it holds the in-progress marked text
// and the committed text that HIDSupport sends to the host. One client per
// session; the session owns the input context and the lifecycle.
@interface MLLocalIMETextClient : NSObject <NSTextInputClient>

// Current composition draft; empty when no composition is in progress.
@property (nonatomic, copy, readonly) NSString *markedText;
// Committed text accumulated since the last consume; nil when there is none.
@property (nonatomic, copy, readonly, nullable) NSString *pendingCommit;
// Distinct non-empty drafts and committed insertions, for diagnostics.
@property (nonatomic, readonly) NSUInteger compositions;
@property (nonatomic, readonly) NSUInteger commits;
// Screen-space anchor for the candidate window, set by the session before begin.
@property (nonatomic) NSRect anchorRect;

- (void)resetState;
- (void)consumePendingCommit;

@end

// One local IME composition session: the NSTextInputContext and the text
// client it drives. Created when capture starts (setting enabled and an IME
// is in effect), torn down when capture ends or the session ends.
@interface MLLocalIMESession : NSObject

@property (nonatomic, strong, readonly) MLLocalIMETextClient *client;
@property (nonatomic, strong, readonly) NSTextInputContext *context;
// Number of distinct non-empty drafts observed, for diagnostics.
@property (nonatomic, readonly) NSUInteger compositions;
// Number of committed insertions observed, for diagnostics.
@property (nonatomic, readonly) NSUInteger commits;

- (instancetype)initWithClient:(MLLocalIMETextClient *)client;
// Activate the text input context so the system IME can process events.
- (void)begin;
// Cancel any in-progress composition, deactivate the context, reset the client.
- (void)end;
// Return the pending commit (and clear it), or nil when there is none.
- (nullable NSString *)drainCommit;

@end
NS_ASSUME_NONNULL_END
