#import "HIDLocalIME.h"

// ---------------------------------------------------------------------------
// MLLocalIMETextClient
// ---------------------------------------------------------------------------

@implementation MLLocalIMETextClient {
    NSString *_markedText;
    NSRange _selectedRange;
    NSMutableString *_pendingCommit;
    NSRect _anchorRect;
    NSUInteger _compositions;
    NSUInteger _commits;
}

- (instancetype)init {
    if ((self = [super init])) {
        _markedText = @"";
        _selectedRange = NSMakeRange(0, 0);
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
    _selectedRange = NSMakeRange(0, 0);
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

// Edit the local draft for a backspace (backwards) or delete (forwards) press.
// With a non-empty selection that range goes; otherwise exactly one grapheme
// cluster goes, so emoji and combined sequences are never cut in half. The host
// sees nothing until a commit lands.
- (void)deleteCharactersForSelectionBackwards:(BOOL)backwards {
    if (_markedText.length == 0) return;

    NSRange target;
    if (_selectedRange.length > 0) {
        target = NSIntersectionRange(_selectedRange, NSMakeRange(0, _markedText.length));
    } else if (backwards) {
        if (_selectedRange.location == 0) return;
        // Foundation has no "reversed" variant: the cluster that owns the unit
        // before the caret is the one a backspace removes. Composed sequences
        // are contiguous and non-overlapping, so this only straddles the caret
        // when the caret sits inside one cluster, and the whole cluster goes
        // rather than half of a surrogate pair.
        target = [_markedText rangeOfComposedCharacterSequenceAtIndex:_selectedRange.location - 1];
    } else {
        if (_selectedRange.location >= _markedText.length) return;
        target = [_markedText rangeOfComposedCharacterSequenceAtIndex:_selectedRange.location];
    }
    if (target.length == 0 || NSMaxRange(target) > _markedText.length) return;

    NSMutableString *draft = [_markedText mutableCopy];
    [draft deleteCharactersInRange:target];
    _markedText = [draft copy];
    _selectedRange = NSMakeRange(target.location, 0);
}

// Backspace / Delete arrive here while composition is active; they edit the
// local draft only. The remaining commands stay unhandled on purpose: caret
// movement is owned by the IME engine, and cancel/enter are handled on the key
// path so the host keeps its own semantics for those keys.
- (void)doCommandBySelector:(SEL)selector {
    if (selector == @selector(deleteBackward:)) {
        [self deleteCharactersForSelectionBackwards:YES];
    } else if (selector == @selector(deleteForward:)) {
        [self deleteCharactersForSelectionBackwards:NO];
    }
}

- (void)setMarkedText:(id)string selectedRange:(NSRange)selectedRange replacementRange:(NSRange)replacementRange {
    (void)replacementRange;
    if ([string isKindOfClass:[NSAttributedString class]]) {
        string = [(NSAttributedString *)string string];
    }
    NSString *text = [string isKindOfClass:[NSString class]] ? [string copy] : @"";
    BOOL changed = ![_markedText isEqualToString:text];
    _markedText = text;
    // Keep the caret the IME reports, clamped into the new draft: engines hand
    // back a location past the end while they re-render the candidate window.
    NSUInteger caret = MIN(selectedRange.location, text.length);
    _selectedRange = NSMakeRange(caret, MIN(selectedRange.length, text.length - caret));
    // Count each distinct non-empty draft, not every IME refresh.
    if (text.length > 0 && changed) {
        _compositions += 1;
    }
}

- (void)unmarkText {
    _markedText = @"";
    _selectedRange = NSMakeRange(0, 0);
}

- (NSRange)selectedRange {
    return _selectedRange;
}

- (NSRange)markedRange {
    if (_markedText.length == 0) return NSMakeRange(NSNotFound, 0);
    return NSMakeRange(0, _markedText.length);
}

- (BOOL)hasMarkedText {
    return _markedText.length > 0;
}

- (NSAttributedString *)attributedSubstringForProposedRange:(NSRange)range actualRange:(NSRangePointer)actualRange {
    NSUInteger length = _markedText.length;
    if (length == 0 || range.location > length) {
        if (actualRange) *actualRange = NSMakeRange(NSNotFound, 0);
        return nil;
    }
    NSRange actual = NSMakeRange(range.location, MIN(range.length, length - range.location));
    if (actualRange) *actualRange = actual;
    return [[NSAttributedString alloc] initWithString:[_markedText substringWithRange:actual]];
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
