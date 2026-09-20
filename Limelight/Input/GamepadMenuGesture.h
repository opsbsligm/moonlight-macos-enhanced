//
//  GamepadMenuGesture.h
//  Moonlight
//
//  Whether one sample of a gamepad's Menu button completes a long press that hands the
//  pointer to the controller.
//
//  The behaviour is old here -- a held Menu key of more than a second, noticed when the
//  player lets go, with a rumble to say it happened -- but the answer used to be computed
//  inside a 16 ms timer callback against `[NSDate date]`, which is neither replayable nor
//  switchable. Issue #45 is not a request for the gesture: it is a request from a player
//  who holds Menu for real in-game actions and gets their mouse mode changed by it. A
//  gesture nobody can switch off is the same defect as a gesture nobody can test, so both
//  get fixed by the same function.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// How long Menu has to be held before letting go counts as a deliberate toggle. One
/// place spells it; the caller passes it, so a harness can drive the boundary without
/// waiting a second per sample and a change of feel cannot land in two files.
FOUNDATION_EXPORT const NSTimeInterval MLGamepadMenuLongPressRequiredSeconds;

/// Whether the gesture is on for a player who never opened the setting. Kept here, beside
/// the gesture, because the shipping answer has to be readable next to the behaviour it
/// guards, and the Swift default is compared against this by a gate rather than by eye.
FOUNDATION_EXPORT BOOL MLGamepadMenuLongPressDefault(void);

/// The memory the gesture needs: when the current press started, or NaN when no press is
/// being watched. NaN rather than a sentinel date, because 0 is a timestamp a clock could
/// actually report and a machine's clock could really be at the epoch.
typedef struct {
    NSTimeInterval pressedAt;
} MLGamepadMenuGesture;

FOUNDATION_EXPORT MLGamepadMenuGesture MLGamepadMenuGestureIdle(void);
FOUNDATION_EXPORT bool MLGamepadMenuGestureIsHolding(MLGamepadMenuGesture gesture);

/// One sample. Returns whether this sample completes a toggle, which happens on release
/// only: a player still holding Menu has not yet shown whether the hold was the gesture or
/// the game. `gestureEnabled` false answers no every sample and keeps the state idle, so a
/// player who turns the gesture off mid-hold and back on afterwards does not inherit a
/// stale timer -- the next press is measured from its own start.
FOUNDATION_EXPORT bool MLGamepadMenuGestureToggles(MLGamepadMenuGesture *_Nullable state,
                                                   bool menuPressed,
                                                   NSTimeInterval now,
                                                   bool gestureEnabled,
                                                   NSTimeInterval requiredSeconds);

NS_ASSUME_NONNULL_END
