//
//  GamepadMenuGesture.m
//  Moonlight
//
//  See GamepadMenuGesture.h. No AppKit, no GameController, no clock read here: the caller
//  hands in the press state and the time, which is what lets one table of samples decide
//  whether the shipping answer is the one this file gives.
//

#import "GamepadMenuGesture.h"

const NSTimeInterval MLGamepadMenuLongPressRequiredSeconds = 1.0;

/// On, because this is the behaviour every build before the switch had. A player who
/// holds Menu for a game gets the switch; a player who never asked for one keeps the
/// gesture they have always had.
BOOL MLGamepadMenuLongPressDefault(void) { return YES; }

/// The one spelling of "no press is being watched": a NaN, asked of the compiler rather
/// than computed, because dividing by zero reaches -INFINITY, which is a number -- it
/// compares, it subtracts, and a gate that decides "am I holding a press" by asking a
/// value to equal itself would keep saying yes forever. That defect was planted here by
/// this file's first draft and is what the sample table caught.
#define MLGamepadMenuNoPress __builtin_nan("")

MLGamepadMenuGesture MLGamepadMenuGestureIdle(void) {
    MLGamepadMenuGesture gesture;
    gesture.pressedAt = MLGamepadMenuNoPress;
    return gesture;
}

bool MLGamepadMenuGestureIsHolding(MLGamepadMenuGesture gesture) {
    // A value equal only to itself is the test for "not a NaN", which is what makes the
    // idle state above un-inventable: no clock reading can be mistaken for it.
    return gesture.pressedAt == gesture.pressedAt;
}

bool MLGamepadMenuGestureToggles(MLGamepadMenuGesture *state,
                                 bool menuPressed,
                                 NSTimeInterval now,
                                 bool gestureEnabled,
                                 NSTimeInterval requiredSeconds) {
    // Switched off is not "hold longer" and not "remember the press for later": every
    // sample says no, and the Menu key keeps travelling to the host as the ordinary
    // button it is. The state is cleared rather than frozen so turning the switch back on
    // cannot complete a toggle with time that elapsed while it was off.
    if (!gestureEnabled) {
        if (state != NULL) {
            *state = MLGamepadMenuGestureIdle();
        }
        return false;
    }

    MLGamepadMenuGesture gesture = state != NULL ? *state : MLGamepadMenuGestureIdle();

    if (menuPressed) {
        // The first sample of a press starts the clock. Later samples leave it alone, so a
        // gesture measured across a dropped callback still ends at the original start.
        if (!MLGamepadMenuGestureIsHolding(gesture)) {
            gesture.pressedAt = now;
        }
        if (state != NULL) {
            *state = gesture;
        }
        // A hold is not yet a toggle. The player has not let go.
        return false;
    }

    bool holding = MLGamepadMenuGestureIsHolding(gesture);
    bool toggled = false;
    if (holding) {
        // Strictly longer than the requirement, matching what this gesture has always done:
        // a release at exactly the threshold is the game's own short-press timing, not the
        // player reaching for mouse mode.
        toggled = (now - gesture.pressedAt) > requiredSeconds;
    }
    if (state != NULL) {
        *state = MLGamepadMenuGestureIdle();
    }
    return toggled;
}
