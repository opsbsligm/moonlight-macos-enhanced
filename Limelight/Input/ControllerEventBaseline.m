//
//  ControllerEventBaseline.m
//  Moonlight for macOS
//

#import "ControllerEventBaseline.h"
#import "Limelight.h"

BOOL ControllerEventBaselineFromController(Controller *controller,
                                           BOOL shouldSendInputEvents,
                                           ControllerWireEvent *outEvent) {
    if (!shouldSendInputEvents) {
        return NO;
    }
    // Capture state, exactly in the order and shape the HID path sends it.
    int playerIndex = controller.playerIndex;
    int lastButtonFlags = controller.lastButtonFlags;

    // Guide Button Emulation (Start + Select).
    // If both Start and Select are pressed, convert to Guide.
    if ((lastButtonFlags & (PLAY_FLAG | BACK_FLAG)) == (PLAY_FLAG | BACK_FLAG)) {
        lastButtonFlags &= ~(PLAY_FLAG | BACK_FLAG);
        lastButtonFlags |= SPECIAL_FLAG;
    }

    unsigned char lastLeftTrigger = controller.lastLeftTrigger;
    unsigned char lastRightTrigger = controller.lastRightTrigger;
    short lastLeftStickX = controller.lastLeftStickX;
    short lastLeftStickY = controller.lastLeftStickY;
    short lastRightStickX = controller.lastRightStickX;
    short lastRightStickY = controller.lastRightStickY;

    if (controller.isMouseMode) {
        return NO;
    }

    if (outEvent != NULL) {
        outEvent->playerIndex = playerIndex;
        // Hard-coded until M1 replaces it with the real active-device mask.
        outEvent->mask = 1;
        outEvent->buttons = lastButtonFlags;
        outEvent->leftTrigger = lastLeftTrigger;
        outEvent->rightTrigger = lastRightTrigger;
        outEvent->leftStickX = lastLeftStickX;
        outEvent->leftStickY = lastLeftStickY;
        outEvent->rightStickX = lastRightStickX;
        outEvent->rightStickY = lastRightStickY;
    }
    return YES;
}

