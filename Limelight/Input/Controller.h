//
//  Controller.h
//  Moonlight
//
//  Created by Cameron Gutman on 2/11/19.
//  Copyright © 2019 Moonlight Game Streaming Project. All rights reserved.
//

#import "GamepadMenuGesture.h"
#import "HapticContext.h"

@import GameController;
@import CoreHaptics;

@interface Controller : NSObject

@property(nullable, nonatomic, retain) GCController *gamepad;
@property(nonatomic) int playerIndex;
@property(nonatomic) int lastButtonFlags;
@property(nonatomic) int emulatingButtonFlags;
@property(nonatomic) int supportedEmulationFlags;
@property(nonatomic) unsigned char lastLeftTrigger;
@property(nonatomic) unsigned char lastRightTrigger;
@property(nonatomic) short lastLeftStickX;
@property(nonatomic) short lastLeftStickY;
@property(nonatomic) short lastRightStickX;
@property(nonatomic) short lastRightStickY;

@property(nonatomic) HapticContext *_Nullable lowFreqMotor;
@property(nonatomic) HapticContext *_Nullable highFreqMotor;

// Gamepad Mouse Emulation State
@property(nonatomic) BOOL isMouseMode;
@property(nonatomic) int lastMouseModeButtonFlags;
// How long the current Menu press has been held, in the shape MLGamepadMenuGestureToggles
// reads. It replaces a stored NSDate: the gesture now needs "no press" to be a value the
// function owns, so that a switch turned off mid-hold cannot leave a timer running.
@property(nonatomic) MLGamepadMenuGesture menuGesture;

@end
