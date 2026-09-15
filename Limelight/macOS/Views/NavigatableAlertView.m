//
//  NavigatableAlertView.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 13/1/2022.
//  Copyright © 2022 Moonlight Game Streaming Project. All rights reserved.
//

#import "NavigatableAlertView.h"
#import "NSResponder+Moonlight.h"

#include <Carbon/Carbon.h>

@implementation NavigatableAlertView

- (void)controllerEvent:(MoonlightControllerEvent)event {
    switch (event.button) {
        case kMCE_LeftDpad:
            [self pressKey:kVK_Tab withFlags:kCGEventFlagMaskShift];
            break;
        case kMCE_RightDpad:
            [self pressKey:kVK_Tab withFlags:0];
            break;
        case kMCE_AButton:
            [self pressKey:kVK_Return withFlags:0];
            break;
        case kMCE_BButton:
            [self pressKey:kVK_Escape withFlags:0];
            break;
        case kMCE_XButton:
            [self pressKey:kVK_Space withFlags:0];
            break;

        case kMCE_Unknown:
            break;
    }
}

/// One pad button is one keystroke, and a keystroke has two edges. A responder keeps
/// key state -- it is the release that ends a press -- so handing it only the press
/// leaves every control that acts on release inert and the key itself stuck down as far
/// as that responder is concerned. A pad cannot press half a key, so neither may we.
///
/// Measured on the alert this exists for, with its buttons wired the way HostsViewController
/// wires them: pressing the A button actuates the default button exactly once with both
/// edges present, not twice, and B releases the sheet the same way it always did. The
/// release is the missing half, not an extra action.
- (void)pressKey:(CGKeyCode)keyCode withFlags:(CGEventFlags)modifierFlags {
    [self sendKey:keyCode down:YES modifiers:modifierFlags];
    [self sendKey:keyCode down:NO modifiers:modifierFlags];
}

- (void)sendKey:(CGKeyCode)keyCode down:(BOOL)down modifiers:(CGEventFlags)modifierFlags {
    CGEventRef cgEvent = CGEventCreateKeyboardEvent(NULL, keyCode, down);
    CGEventSetFlags(cgEvent, modifierFlags);
    NSEvent *event = [NSEvent eventWithCGEvent:cgEvent];
    // The event was created here, so this reference has to go with it:
    // eventWithCGEvent: has already copied what the responder needs.
    CFRelease(cgEvent);
    // The event was built as one edge or the other, so it has to arrive as that edge.
    // Handing a release to keyDown: would give the responder an event whose type says
    // keyUp and whose selector says otherwise, and handing it nothing at all -- which is
    // what used to happen, whatever `down:` said -- keeps the key pressed forever.
    if (down) {
        [self.responder keyDown:event];
    } else {
        [self.responder keyUp:event];
    }
}

@end
