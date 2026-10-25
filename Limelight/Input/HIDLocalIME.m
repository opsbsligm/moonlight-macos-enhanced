#import "HIDLocalIME.h"

// ---------------------------------------------------------------------------
// MLLocalIMETextClient
// ---------------------------------------------------------------------------

@implementation MLLocalIMETextClient {
    NSString *_markedText;
    NSMutableString *_pendingCommit;
    NSRect _anchorRect;
    NSUInteger _compositions;
    NSUInteger _commits;
}

- (instancetype)init {
    if ((self = [super init])) {
        _markedText = @"";
        _pendingCommit = [NSMutableString new];
        _anchorRect = NSZeroRect;
    }
    return self;
}

- (NSString *)pendingCommit {
    return _pendingCommit.length > 0 ? [_pendingCommit copy] : nil;
}

- (void)consumePendingCommit {
    [_pendingCommit setString:@""];
}

- (void)resetState {
    _markedText = @"";
    [_pendingCommit setString:@""];
}

// Committed text: the full string goes to the host as one UTF-8 event.
// The replacement range refers to the local composition buffer, not the host
// document, so it carries no wire semantics.
- (void)insertText:(id)string replacementRange:(NSRange)replacementRange {
    (void)replacementRange;
    if ([string isKindOfClass:[NSAttributedString class]]) {
        string = [(NSAttributedString *)string string];
    }
    if (![string isKindOfClass:[NSString class]]) return;
    if ([(NSString *)string length] == 0) return;
    [_pendingCommit appendString:(NSString *)string];
    _commits += 1;
}

// Backspace / Delete arrive here while composition is active. They edit the
// local marked buffer only; the host sees nothing until a commit lands.
- (void)doCommandBySelector:(SEL)selector {
    (void)selector;
}

- (void)setMarkedText:(id)string selectedRange:(NSRange)selectedRange replacementRange:(NSRange)replacementRange {
    (void)selectedRange;
    (void)replacementRange;
    if ([string isKindOfClass:[NSAttributedString class]]) {
        string = [(NSAttributedString *)string string];
    }
    NSString *text = [string isKindOfClass:[NSString class]] ? [string copy] : @"";
    BOOL changed = ![_markedText isEqualToString:text];
    _markedText = text;
    // Count each distinct non-empty draft, not every IME refresh.
    if (text.length > 0 && changed) {
        _compositions += 1;
    }
}

- (void)unmarkText {
    _markedText = @"";
}

- (NSRange)selectedRange {
    return NSMakeRange(0, 0);
}

- (NSRange)markedRange {
    if (_markedText.length == 0) return NSMakeRange(NSNotFound, 0);
    return NSMakeRange(0, _markedText.length);
}

- (BOOL)hasMarkedText {
    return _markedText.length > 0;
}

- (NSAttributedString *)attributedSubstringForProposedRange:(NSRange)range actualRange:(NSRangePointer)actualRange {
    if (actualRange) *actualRange = range;
    return nil;
}

- (NSArray<NSAttributedStringKey> *)validAttributesForMarkedText {
    return @[];
}

- (NSRect)firstRectForCharacterRange:(NSRange)range actualRange:(NSRangePointer)actualRange {
    (void)range;
    if (actualRange) *actualRange = NSMakeRange(0, 0);
    return _anchorRect;
}

- (NSUInteger)characterIndexForPoint:(NSPoint)point {
    (void)point;
    return 0;
}

@end

// ---------------------------------------------------------------------------
// MLLocalIMESession
// ---------------------------------------------------------------------------

@implementation MLLocalIMESession {
    MLLocalIMETextClient *_client;
    NSTextInputContext *_context;
}

- (instancetype)initWithClient:(MLLocalIMETextClient *)client {
    if ((self = [super init])) {
        _client = client;
    }
    return self;
}

- (void)begin {
    _context = [[NSTextInputContext alloc] initWithClient:_client];
    [_context activate];
}

- (void)end {
    if (_context) {
        [_context discardMarkedText];
        [_context deactivate];
        _context = nil;
    }
    [_client resetState];
}

- (NSString *)drainCommit {
    NSString *text = [_client pendingCommit];
    if (text != nil) {
        [_client consumePendingCommit];
    }
    return text;
}

- (NSUInteger)compositions {
    return _client.compositions;
}

- (NSUInteger)commits {
    return _client.commits;
}

@end
