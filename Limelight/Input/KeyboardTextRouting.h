#pragma once
#import <AppKit/AppKit.h>
#include <limits.h>

// Raw key events are not an IME commit callback. This route only preserves
// printable Unicode already present on an event; composition belongs to the view.
static inline NSData *HIDUnicodeTextForEvent(NSEvent *event) {
    if (![event respondsToSelector:@selector(characters)] ||
        ![event respondsToSelector:@selector(modifierFlags)]) return nil;
    if (event.modifierFlags & (NSEventModifierFlagCommand |
                              NSEventModifierFlagControl |
                              NSEventModifierFlagOption)) return nil;
    NSString *characters = event.characters;
    if (characters.length == 0) return nil;
    BOOL nonASCII = NO;
    for (NSUInteger i = 0; i < characters.length; i++) {
        unichar c = [characters characterAtIndex:i];
        // AppKit function keys occupy the private-use range. Controls and NUL
        // must keep their ordinary key-code semantics.
        if (c < 0x20 || (c >= 0x7F && c <= 0x9F) ||
            (c >= 0xE000 && c <= 0xF8FF)) return nil;
        if (c > 0x7F) nonASCII = YES;
    }
    if (!nonASCII) return nil;
    NSData *text = [characters dataUsingEncoding:NSUTF8StringEncoding
                            allowLossyConversion:NO];
    return text.length > 0 && text.length <= UINT_MAX ? text : nil;
}
