//
//  ControllerEventBaseline.h
//  Moonlight for macOS
//
//  The single-controller wire tuple, factored out of the HID input path so that
//  "what one connected controller sends" has one owner. The per-device
//  refactor (campaign 0.2) is allowed to change how this function is called;
//  it is not allowed to change what it says, or the recorded byte-for-byte
//  baseline (scripts/controller-event-baseline.py) stops passing.

#import <Foundation/Foundation.h>
#import "Controller.h"

typedef struct ControllerWireEvent {
    int playerIndex;
    int mask;
    int buttons;
    unsigned char leftTrigger;
    unsigned char rightTrigger;
    short leftStickX;
    short leftStickY;
    short rightStickX;
    short rightStickY;
} ControllerWireEvent;

// Computes the exact argument tuple the current path sends for one controller:
// the Guide-button emulation applied to the button flags, the mask fixed at 1
// until M1 owns advertisement, and playerIndex passed through unchanged.
// Returns NO (sends nothing) when input is gated off or the controller is in
// mouse mode, which is today's shipping behaviour and part of the baseline.
FOUNDATION_EXPORT BOOL ControllerEventBaselineFromController(Controller *controller,
                                                             BOOL shouldSendInputEvents,
                                                             ControllerWireEvent *outEvent);

