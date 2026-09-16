//
//  ControllerSupport.h
//  Moonlight
//
//  Created by Cameron Gutman on 10/20/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "Controller.h"
#import "StreamConfiguration.h"

@class OnScreenControls;

@protocol InputPresenceDelegate <NSObject>

- (void)gamepadPresenceChanged;
- (void)mousePresenceChanged;
- (void)mouseModeToggled:(BOOL)enabled;

@end

@interface ControllerSupport : NSObject
@property(nonatomic) BOOL shouldSendInputEvents;
@property(nonatomic) BOOL gamepadMouseModeEnabled;
@property(nonatomic, assign) void *inputContext;

- (id)initWithConfig:(StreamConfiguration *)streamConfig
    presenceDelegate:(id<InputPresenceDelegate>)delegate;

#if TARGET_OS_IPHONE
- (void)initAutoOnScreenControlMode:(OnScreenControls *)osc;
- (Controller *)getOscController;
#endif
/// Hands the mouse buttons this class pressed on the host back to it: for the
/// moment input forwarding stops (mouse capture released) and the session
/// continues afterwards. It covers the mouse-mode A and B and the buttons of a
/// GCMouse device, which no other tracker knows about. It clears this class's
/// button trackers as it sends, so the host and the trackers agree that nothing
/// is down: a player still holding a button has to press it again after
/// recapture, and nothing from the hand-back is left owed to either side.
- (void)releaseRemoteMouseButtonsForUncapture;

- (void)cleanup;

- (void)updateLeftStick:(Controller *)controller x:(short)x y:(short)y;
- (void)updateRightStick:(Controller *)controller x:(short)x y:(short)y;

- (void)updateLeftTrigger:(Controller *)controller left:(unsigned char)left;
- (void)updateRightTrigger:(Controller *)controller right:(unsigned char)right;
- (void)updateTriggers:(Controller *)controller
                  left:(unsigned char)left
                 right:(unsigned char)right;

- (void)updateButtonFlags:(Controller *)controller flags:(int)flags;
- (void)setButtonFlag:(Controller *)controller flags:(int)flags;
- (void)clearButtonFlag:(Controller *)controller flags:(int)flags;

- (void)updateFinished:(Controller *)controller;

- (void)rumble:(unsigned short)controllerNumber
     lowFreqMotor:(unsigned short)lowFreqMotor
    highFreqMotor:(unsigned short)highFreqMotor;

+ (int)getConnectedGamepadMask:(StreamConfiguration *)streamConfig;

- (NSUInteger)getConnectedGamepadCount;

@end
