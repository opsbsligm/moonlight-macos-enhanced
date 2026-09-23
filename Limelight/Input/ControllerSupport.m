//
//  ControllerSupport.m
//  Moonlight
//
//  Created by Cameron Gutman on 10/20/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import "ControllerSupport.h"
#import "GamepadMenuGesture.h"
#import "Controller.h"

#import "OnScreenControls.h"

#import "DataManager.h"
#import "HIDSupport.h"
#import "MouseEmulation.h"
#include "Limelight.h"
#include "Limelight-internal.h"

@import GameController;
@import AudioToolbox;
@import CoreHaptics;

// The buttons a controller can drive a pointer with, in one table, because
// the uncapture has to hand back exactly what the host was told about and
// nothing that it was not.
#define DERIVED_MOUSE_LEFT   0x1
#define DERIVED_MOUSE_RIGHT  0x2
#define DERIVED_MOUSE_MIDDLE 0x4
#define DERIVED_MOUSE_X1     0x8
#define DERIVED_MOUSE_X2     0x10

static const int kDerivedMouseButtonBits[5] = {
    DERIVED_MOUSE_LEFT, DERIVED_MOUSE_RIGHT, DERIVED_MOUSE_MIDDLE,
    DERIVED_MOUSE_X1, DERIVED_MOUSE_X2
};
static const int kDerivedMouseButtonCodes[5] = {
    BUTTON_LEFT, BUTTON_RIGHT, BUTTON_MIDDLE, BUTTON_X1, BUTTON_X2
};

static inline PML_INPUT_STREAM_CONTEXT ControllerInputContext(ControllerSupport *support) {
    PML_INPUT_STREAM_CONTEXT ctx = (PML_INPUT_STREAM_CONTEXT)support.inputContext;
    if (ctx != NULL && ctx->connectionContext != NULL) {
        LiSetThreadConnectionContext(ctx->connectionContext);
    }
    return ctx;
}

enum ButtonDebouncerState {
    BDS_none,
    BDS_initialPress,
    BDS_down,
    BDS_replicatedPress,
    BDS_chord
};

@interface ButtonDebouncer : NSObject
@property (nonatomic) unsigned int button;
@property (nonatomic, strong) GCControllerButtonInput *input;
@property (nonatomic, strong) ControllerSupport *support;
@property (nonatomic) unsigned int chordButton;

@property (nonatomic, weak) ButtonDebouncer *other;

@property (nonatomic) enum ButtonDebouncerState state;
@property (nonatomic, strong) NSDate *buttonDownTime;
@property (nonatomic, strong) NSTimer *buttonDebounceTimer;
@property (nonatomic, strong) NSTimer *replicatedButtonTimeTimer;

@end

@implementation ButtonDebouncer

- (instancetype)initWithButton:(unsigned int)button input:(GCControllerButtonInput *)input controllerSupport:(ControllerSupport *)support chordButton:(unsigned int)chordButton {
    self = [super init];
    if (self) {
        self.button = button;
        self.input = input;
        self.support = support;
        self.chordButton = chordButton;
    }
    return self;
}

- (void)handlePress:(Controller *)controller pressedButtons:(int)pressedButtons {
    if (controller.lastButtonFlags & self.button) {
        if (self.state == BDS_none) {
            
            // If we are 2nd button and 1st button is in initialPress state, then:
            //   turn on chord button
            //   put 1st and 2nd buttons into special chord state
            if (self.other.state == BDS_initialPress) {
                
                [self transitionToChordState];
                [self.other transitionToChordState];

                [self updateLastButtonFlagsForChordState:controller];
            } else {

                self.state = BDS_initialPress;
                self.buttonDownTime = [[NSDate alloc] init];
                controller.lastButtonFlags &= ~self.button;
                
                [self.buttonDebounceTimer invalidate];
                self.buttonDebounceTimer = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:NO block:^(NSTimer * _Nonnull timer) {
                    [self initialPressTimeout:controller];
                }];
            }
        } else if (self.state == BDS_initialPress) {
            controller.lastButtonFlags &= ~self.button;
        } else if (self.state == BDS_chord) {
            [self updateLastButtonFlagsForChordState:controller];
        }
    }
}

- (void)handleRelease:(Controller *)controller releasedButtons:(int)releasedButtons {
    if (releasedButtons & self.button) {
        
        if (self.state == BDS_down && !self.input.pressed) {
            self.state = BDS_none;
            
        } else if (self.state == BDS_initialPress && !self.input.pressed) {
            
            controller.lastButtonFlags |= self.button;
            [self.support updateFinished:controller];
            
            self.state = BDS_replicatedPress;
            
            NSTimeInterval pressDuration = -[self.buttonDownTime timeIntervalSinceNow];
            
            [self.buttonDebounceTimer invalidate];
            [self.replicatedButtonTimeTimer invalidate];
            self.replicatedButtonTimeTimer = [NSTimer scheduledTimerWithTimeInterval:pressDuration repeats:NO block:^(NSTimer * _Nonnull timer) {
                
                controller.lastButtonFlags &= ~self.button;
                [self.support updateFinished:controller];

                self.state = BDS_none;
            }];

        } else if (self.state == BDS_chord && !self.input.pressed) {
            if (self.other.state == BDS_chord && !self.other.input.pressed) {

                controller.lastButtonFlags &= ~self.chordButton;

                [self transitionToNoneState];
                [self.other transitionToNoneState];
            } else if (self.other.state == BDS_chord && self.other.input.pressed) {
                
                [self updateLastButtonFlagsForChordState:controller];
            }
        }
    }
}

- (void)initialPressTimeout:(Controller *)controller {
    if (self.state == BDS_initialPress) {
        if (self.input.pressed) {
            self.state = BDS_down;
            controller.lastButtonFlags |= self.button;
            [self.support updateFinished:controller];
        }
    }
}

- (void)transitionToChordState {
    self.state = BDS_chord;
}

- (void)transitionToNoneState {
    self.state = BDS_none;
}

- (void)updateLastButtonFlagsForChordState:(Controller *)controller {
    controller.lastButtonFlags |= self.chordButton;
    
    controller.lastButtonFlags &= ~self.button;
    controller.lastButtonFlags &= ~self.other.button;
}

@end

#if TARGET_OS_IPHONE
static const double MOUSE_SPEED_DIVISOR = 2.5;
#endif

@implementation ControllerSupport {
    id _controllerConnectObserver;
    id _controllerDisconnectObserver;
#if TARGET_OS_IPHONE
    id _mouseConnectObserver;
    id _mouseDisconnectObserver;
    id _keyboardConnectObserver;
    id _keyboardDisconnectObserver;
#endif
    
    NSLock *_controllerStreamLock;
    NSMutableDictionary *_controllers;
    id<InputPresenceDelegate> _presenceDelegate;
    
#if TARGET_OS_IPHONE
    float accumulatedDeltaX;
    float accumulatedDeltaY;
    float accumulatedScrollY;
#endif

    OnScreenControls *_osc;
    
    // This controller object is shared between on-screen controls
    // and player 0
    Controller *_player0osc;
    
#define EMULATING_SELECT     0x1
#define EMULATING_SPECIAL    0x2
    
    bool _oscEnabled;
    char _controllerNumbers;
    bool _multiController;
    BOOL _gamepadMouseModeEnabled;
    bool _isMouseModeActive;
    NSDate *_startPressTime;
    float _accumulatedMouseX;
    float _accumulatedMouseY;
    // Which controller-derived mouse buttons the host was told about,
    // so an uncapture can return the ones it stops being able to release.
    int _derivedMouseButtonFlags;
    NSTimer *_mouseTimer;

    NSMutableDictionary<NSNumber * /* key flag */, NSMutableDictionary<NSNumber * /* player index */, ButtonDebouncer *> *> *_debouncers;
}

// UPDATE_BUTTON_FLAG(controller, flag, pressed)
#define UPDATE_BUTTON_FLAG(controller, x, y) \
((y) ? [self setButtonFlag:controller flags:x] : [self clearButtonFlag:controller flags:x])

-(void) rumble:(unsigned short)controllerNumber lowFreqMotor:(unsigned short)lowFreqMotor highFreqMotor:(unsigned short)highFreqMotor
{
    Controller* controller = [_controllers objectForKey:[NSNumber numberWithInteger:controllerNumber]];
    if (controller == nil && controllerNumber == 0 && _oscEnabled) {
        // No physical controller, but we have on-screen controls
        controller = _player0osc;
    }
    if (controller == nil) {
        // No connected controller for this player
        return;
    }
    
    [controller.lowFreqMotor setMotorAmplitude:lowFreqMotor];
    [controller.highFreqMotor setMotorAmplitude:highFreqMotor];
}

-(void) updateLeftStick:(Controller*)controller x:(short)x y:(short)y
{
    @synchronized(controller) {
        controller.lastLeftStickX = x;
        controller.lastLeftStickY = y;
    }
}

-(void) updateRightStick:(Controller*)controller x:(short)x y:(short)y
{
    @synchronized(controller) {
        controller.lastRightStickX = x;
        controller.lastRightStickY = y;
    }
}

-(void) updateLeftTrigger:(Controller*)controller left:(unsigned char)left
{
    @synchronized(controller) {
        controller.lastLeftTrigger = left;
    }
}

-(void) updateRightTrigger:(Controller*)controller right:(unsigned char)right
{
    @synchronized(controller) {
        controller.lastRightTrigger = right;
    }
}

-(void) updateTriggers:(Controller*) controller left:(unsigned char)left right:(unsigned char)right
{
    @synchronized(controller) {
        controller.lastLeftTrigger = left;
        controller.lastRightTrigger = right;
    }
}

-(void) handleSpecialCombosReleased:(Controller*)controller releasedButtons:(int)releasedButtons
{
    [self->_debouncers enumerateKeysAndObjectsUsingBlock:^(NSNumber * _Nonnull keyFlag, NSMutableDictionary<NSNumber *,ButtonDebouncer *> * _Nonnull debouncers, BOOL * _Nonnull stop) {
        ButtonDebouncer *debouncer = debouncers[@(controller.playerIndex)];
        [debouncer handleRelease:controller releasedButtons:releasedButtons];
    }];
}

-(void) handleSpecialCombosPressed:(Controller*)controller pressedButtons:(int)pressedButtons
{
    [self->_debouncers enumerateKeysAndObjectsUsingBlock:^(NSNumber * _Nonnull keyFlag, NSMutableDictionary<NSNumber *,ButtonDebouncer *> * _Nonnull debouncers, BOOL * _Nonnull stop) {
        ButtonDebouncer *debouncer = debouncers[@(controller.playerIndex)];
        [debouncer handlePress:controller pressedButtons:pressedButtons];
    }];
}

-(void) updateButtonFlags:(Controller*)controller flags:(int)flags
{
    @synchronized(controller) {
        controller.lastButtonFlags = flags;
        
        // This must be called before handleSpecialCombosPressed
        // because we clear the original button flags there
        int releasedButtons = (controller.lastButtonFlags ^ flags) & ~flags;
        int pressedButtons = (controller.lastButtonFlags ^ flags) & flags;
        
        [self handleSpecialCombosReleased:controller releasedButtons:releasedButtons];
        
        [self handleSpecialCombosPressed:controller pressedButtons:pressedButtons];
    }
}

-(void) setButtonFlag:(Controller*)controller flags:(int)flags
{
    @synchronized(controller) {
        controller.lastButtonFlags |= flags;
        [self handleSpecialCombosPressed:controller pressedButtons:flags];
    }
}

-(void) clearButtonFlag:(Controller*)controller flags:(int)flags
{
    @synchronized(controller) {
        controller.lastButtonFlags &= ~flags;
        [self handleSpecialCombosReleased:controller releasedButtons:flags];
    }
}

-(void) updateFinished:(Controller*)controller
{
    if (!_shouldSendInputEvents) {
        return;
    }
    
    @synchronized(controller) {
        // Quit Combo: Start+Select+L1+R1
        // Note: ButtonDebouncer converts Start+Select to SPECIAL_FLAG (Guide)
        // So we check for Guide + L1 + R1
        int quitFlags = SPECIAL_FLAG | LB_FLAG | RB_FLAG;
        if ((controller.lastButtonFlags & quitFlags) == quitFlags) {
             dispatch_async(dispatch_get_main_queue(), ^{
                 [[NSNotificationCenter defaultCenter] postNotificationName:HIDGamepadQuitNotification object:nil];
             });
            // Clear flags to avoid sending
            controller.lastButtonFlags = 0;
        }

        if (controller.isMouseMode) {
            // Don't send controller events while in mouse mode
            return;
        }

        // Standard Controller Mode
        [_controllerStreamLock lock];

        PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
        if (!inputCtx) {
            [_controllerStreamLock unlock];
            return;
        }
        
        if (_multiController) {
            LiSendMultiControllerEventCtx(inputCtx,
                                          controller.playerIndex,
                                          [ControllerSupport getConnectedGamepadMask:nil],
                                          controller.lastButtonFlags,
                                          controller.lastLeftTrigger,
                                          controller.lastRightTrigger,
                                          controller.lastLeftStickX,
                                          controller.lastLeftStickY,
                                          controller.lastRightStickX,
                                          controller.lastRightStickY);
        }
        else {
            LiSendControllerEventCtx(inputCtx,
                                     controller.lastButtonFlags,
                                     controller.lastLeftTrigger,
                                     controller.lastRightTrigger,
                                     controller.lastLeftStickX,
                                     controller.lastLeftStickY,
                                     controller.lastRightStickX,
                                     controller.lastRightStickY);
        }
        
        [_controllerStreamLock unlock];
    }
}

#if TARGET_OS_IPHONE
+(BOOL) hasKeyboardOrMouse {
    if (@available(iOS 14.0, tvOS 14.0, *)) {
        return GCMouse.mice.count > 0 || GCKeyboard.coalescedKeyboard != nil;
    }
    else {
        return NO;
    }
}
#endif

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

-(void) unregisterControllerCallbacks:(GCController*) controller
{
    if (controller != NULL) {
        controller.controllerPausedHandler = NULL;
        
        if (controller.extendedGamepad != NULL) {
            controller.extendedGamepad.valueChangedHandler = NULL;
        }
        else if (controller.gamepad != NULL) {
            controller.gamepad.valueChangedHandler = NULL;
        }
    }
}

-(void) initializeControllerHaptics:(Controller*) controller
{
    controller.lowFreqMotor = [HapticContext createContextForLowFreqMotor:controller.gamepad];
    controller.highFreqMotor = [HapticContext createContextForHighFreqMotor:controller.gamepad];
}

-(void) cleanupControllerHaptics:(Controller*) controller
{
    [controller.lowFreqMotor cleanup];
    [controller.highFreqMotor cleanup];
}

-(void) registerControllerCallbacks:(GCController*) controller
{
    if (controller != NULL) {
        // iOS 13 allows the Start button to behave like a normal button, however
        // older MFi controllers can send an instant down+up event for the start button
        // which means the button will not be down long enough to register on the PC.
        // To work around this issue, use the old controllerPausedHandler if the controller
        // doesn't have a Select button (which indicates it probably doesn't have a proper
        // Start button either).
        BOOL useLegacyPausedHandler = YES;
        if (@available(iOS 13.0, tvOS 13.0, macOS 10.15, *)) {
            if (controller.extendedGamepad != nil &&
                controller.extendedGamepad.buttonOptions != nil) {
                useLegacyPausedHandler = NO;
            }
        }
        
        if (useLegacyPausedHandler) {
            controller.controllerPausedHandler = ^(GCController *controller) {
                Controller* limeController = [self->_controllers objectForKey:[NSNumber numberWithInteger:controller.playerIndex]];
                
                // Get off the main thread
                dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0), ^{
                    [self setButtonFlag:limeController flags:PLAY_FLAG];
                    [self updateFinished:limeController];
                    
                    // Pause for 100 ms
                    usleep(100 * 1000);
                    
                    [self clearButtonFlag:limeController flags:PLAY_FLAG];
                    [self updateFinished:limeController];
                });
            };
        }
        
        __weak typeof(controller) weakController = controller;
        if (controller.extendedGamepad != NULL) {
            controller.extendedGamepad.valueChangedHandler = ^(GCExtendedGamepad *gamepad, GCControllerElement *element) {
                Controller* limeController = [self->_controllers objectForKey:[NSNumber numberWithInteger:weakController.playerIndex]];
                short leftStickX, leftStickY;
                short rightStickX, rightStickY;
                unsigned char leftTrigger, rightTrigger;

                if (limeController.isMouseMode) {
                    // Mouse Toggle and Movement are handled by timer
                    
                    // Mouse Clicks (A = Left, B = Right)
                    // Handing the pointer back to the Mac leaves this handler
                    // registered for the rest of the session, and in mouse mode
                    // A and B are host mouse buttons, so a press made while the
                    // player is using their own cursor clicked on the host.
                    // The gate covers the recorded edge as well as the packet,
                    // because the uncapture has already brought the host back to
                    // no buttons down and cleared this tracker along with it. A
                    // press kept here would be a debt the host never took on,
                    // and it would come back as a release for a button the host
                    // was never told about.
                    BOOL pointerForwarded = self->_shouldSendInputEvents;
                    BOOL currentA = gamepad.buttonA.pressed;
                    BOOL currentB = gamepad.buttonB.pressed;
                    BOOL lastA = (limeController.lastMouseModeButtonFlags & A_FLAG) != 0;
                    BOOL lastB = (limeController.lastMouseModeButtonFlags & B_FLAG) != 0;
                    PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
                    
                    if (currentA != lastA && pointerForwarded) {
                        if (inputCtx) {
                            LiSendMouseButtonEventCtx(inputCtx, currentA ? BUTTON_ACTION_PRESS : BUTTON_ACTION_RELEASE, BUTTON_LEFT);
                        }
                        if (currentA) limeController.lastMouseModeButtonFlags |= A_FLAG;
                        else limeController.lastMouseModeButtonFlags &= ~A_FLAG;
                    }
                    if (currentB != lastB && pointerForwarded) {
                        if (inputCtx) {
                            LiSendMouseButtonEventCtx(inputCtx, currentB ? BUTTON_ACTION_PRESS : BUTTON_ACTION_RELEASE, BUTTON_RIGHT);
                        }
                        if (currentB) limeController.lastMouseModeButtonFlags |= B_FLAG;
                        else limeController.lastMouseModeButtonFlags &= ~B_FLAG;
                    }
                }
                
                BOOL suppress = limeController.isMouseMode;
                
                UPDATE_BUTTON_FLAG(limeController, A_FLAG, suppress ? NO : gamepad.buttonA.pressed);
                UPDATE_BUTTON_FLAG(limeController, B_FLAG, suppress ? NO : gamepad.buttonB.pressed);
                UPDATE_BUTTON_FLAG(limeController, X_FLAG, gamepad.buttonX.pressed);
                UPDATE_BUTTON_FLAG(limeController, Y_FLAG, gamepad.buttonY.pressed);
                
                UPDATE_BUTTON_FLAG(limeController, UP_FLAG, gamepad.dpad.up.pressed);
                UPDATE_BUTTON_FLAG(limeController, DOWN_FLAG, gamepad.dpad.down.pressed);
                UPDATE_BUTTON_FLAG(limeController, LEFT_FLAG, gamepad.dpad.left.pressed);
                UPDATE_BUTTON_FLAG(limeController, RIGHT_FLAG, gamepad.dpad.right.pressed);
                
                UPDATE_BUTTON_FLAG(limeController, LB_FLAG, gamepad.leftShoulder.pressed);
                UPDATE_BUTTON_FLAG(limeController, RB_FLAG, gamepad.rightShoulder.pressed);
                
                // Yay, iOS 12.1 now supports analog stick buttons
                if (@available(iOS 12.1, tvOS 12.1, macOS 10.14.1, *)) {
                    if (gamepad.leftThumbstickButton != nil) {
                        UPDATE_BUTTON_FLAG(limeController, LS_CLK_FLAG, gamepad.leftThumbstickButton.pressed);
                    }
                    if (gamepad.rightThumbstickButton != nil) {
                        UPDATE_BUTTON_FLAG(limeController, RS_CLK_FLAG, gamepad.rightThumbstickButton.pressed);
                    }
                }
                
                if (@available(iOS 13.0, tvOS 13.0, macOS 10.15, *)) {
                    // For older MFi gamepads, the menu button will already be handled by
                    // the controllerPausedHandler.
                    UPDATE_BUTTON_FLAG(limeController, PLAY_FLAG, gamepad.buttonMenu.pressed);
                    
                    // Options button is optional (only present on Xbox One S and PS4 gamepads)
                    if (gamepad.buttonOptions != nil) {
                        UPDATE_BUTTON_FLAG(limeController, BACK_FLAG, gamepad.buttonOptions.pressed);
                    }
                }
                
                if (@available(iOS 14.0, tvOS 14.0, macOS 11.0, *)) {
                    if (gamepad.buttonHome != nil) {
                        UPDATE_BUTTON_FLAG(limeController, SPECIAL_FLAG, gamepad.buttonHome.pressed);
                    }
                }

                leftStickX = gamepad.leftThumbstick.xAxis.value * 0x7FFE;
                leftStickY = gamepad.leftThumbstick.yAxis.value * 0x7FFE;
                
                rightStickX = suppress ? 0 : (gamepad.rightThumbstick.xAxis.value * 0x7FFE);
                rightStickY = suppress ? 0 : (gamepad.rightThumbstick.yAxis.value * 0x7FFE);
                
                leftTrigger = gamepad.leftTrigger.value * 0xFF;
                rightTrigger = gamepad.rightTrigger.value * 0xFF;
                
                [self updateLeftStick:limeController x:leftStickX y:leftStickY];
                [self updateRightStick:limeController x:rightStickX y:rightStickY];
                [self updateTriggers:limeController left:leftTrigger right:rightTrigger];
                [self updateFinished:limeController];
            };
        }
        else if (controller.gamepad != NULL) {
            controller.gamepad.valueChangedHandler = ^(GCGamepad *gamepad, GCControllerElement *element) {
                Controller* limeController = [self->_controllers objectForKey:[NSNumber numberWithInteger:weakController.playerIndex]];
                UPDATE_BUTTON_FLAG(limeController, A_FLAG, gamepad.buttonA.pressed);
                UPDATE_BUTTON_FLAG(limeController, B_FLAG, gamepad.buttonB.pressed);
                UPDATE_BUTTON_FLAG(limeController, X_FLAG, gamepad.buttonX.pressed);
                UPDATE_BUTTON_FLAG(limeController, Y_FLAG, gamepad.buttonY.pressed);
                
                UPDATE_BUTTON_FLAG(limeController, UP_FLAG, gamepad.dpad.up.pressed);
                UPDATE_BUTTON_FLAG(limeController, DOWN_FLAG, gamepad.dpad.down.pressed);
                UPDATE_BUTTON_FLAG(limeController, LEFT_FLAG, gamepad.dpad.left.pressed);
                UPDATE_BUTTON_FLAG(limeController, RIGHT_FLAG, gamepad.dpad.right.pressed);
                
                UPDATE_BUTTON_FLAG(limeController, LB_FLAG, gamepad.leftShoulder.pressed);
                UPDATE_BUTTON_FLAG(limeController, RB_FLAG, gamepad.rightShoulder.pressed);
                
                [self updateFinished:limeController];
            };
        }
    } else {
        Log(LOG_W, @"Tried to register controller callbacks on NULL controller");
    }
}

#if TARGET_OS_IPHONE
-(void) unregisterMouseCallbacks:(GCMouse*)mouse API_AVAILABLE(ios(14.0)) {
    mouse.mouseInput.mouseMovedHandler = nil;
    
    mouse.mouseInput.leftButton.pressedChangedHandler = nil;
    mouse.mouseInput.middleButton.pressedChangedHandler = nil;
    mouse.mouseInput.rightButton.pressedChangedHandler = nil;
    
    for (GCControllerButtonInput* auxButton in mouse.mouseInput.auxiliaryButtons) {
        auxButton.pressedChangedHandler = nil;
    }
}

// One handler for every button of a GCMouse device. Handing the pointer back to
// the Mac leaves these registered, so a click made while the player is using
// their own cursor used to reach the host as a click there too. The gate refuses
// before the button table is touched: an uncapture has already brought the host
// back to no buttons down and emptied this table with it, so a press kept here
// would be something the host never took on and would surface later as a release
// for a button the host was never told about.
-(GCControllerButtonValueChangedHandler)
    derivedMouseButtonHandlerForBit:(int)buttonBit
{
    return ^(GCControllerButtonInput *button, float value, BOOL pressed) {
        if (!self->_shouldSendInputEvents) {
            return;
        }
        if (pressed) self->_derivedMouseButtonFlags |= buttonBit;
        else self->_derivedMouseButtonFlags &= ~buttonBit;
        PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
        if (inputCtx) {
            for (int i = 0; i < 5; i++) {
                if (kDerivedMouseButtonBits[i] != buttonBit) continue;
                LiSendMouseButtonEventCtx(inputCtx,
                                          pressed ? BUTTON_ACTION_PRESS
                                                  : BUTTON_ACTION_RELEASE,
                                          kDerivedMouseButtonCodes[i]);
                break;
            }
        }
    };
}

-(void) registerMouseCallbacks:(GCMouse*) mouse API_AVAILABLE(ios(14.0)) {
    mouse.mouseInput.mouseMovedHandler = ^(GCMouseInput * _Nonnull mouse, float deltaX, float deltaY) {
        // Asked before the accumulation rather than before the send, so motion
        // refused while the Mac owns the cursor is dropped and not kept as a
        // debt that recapture would spend on the host in one packet.
        if (!self->_shouldSendInputEvents) {
            return;
        }
        self->accumulatedDeltaX += deltaX / MOUSE_SPEED_DIVISOR;
        self->accumulatedDeltaY += -deltaY / MOUSE_SPEED_DIVISOR;
        
        short truncatedDeltaX = (short)self->accumulatedDeltaX;
        short truncatedDeltaY = (short)self->accumulatedDeltaY;
        
        if (truncatedDeltaX != 0 || truncatedDeltaY != 0) {
            PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
            if (inputCtx) {
                LiSendMouseMoveEventCtx(inputCtx, truncatedDeltaX, truncatedDeltaY);
            }
            
            self->accumulatedDeltaX -= truncatedDeltaX;
            self->accumulatedDeltaY -= truncatedDeltaY;
        }
    };
    
    mouse.mouseInput.leftButton.pressedChangedHandler =
        [self derivedMouseButtonHandlerForBit:DERIVED_MOUSE_LEFT];
    mouse.mouseInput.middleButton.pressedChangedHandler =
        [self derivedMouseButtonHandlerForBit:DERIVED_MOUSE_MIDDLE];
    mouse.mouseInput.rightButton.pressedChangedHandler =
        [self derivedMouseButtonHandlerForBit:DERIVED_MOUSE_RIGHT];
    
    if (mouse.mouseInput.auxiliaryButtons != nil) {
        if (mouse.mouseInput.auxiliaryButtons.count >= 1) {
            mouse.mouseInput.auxiliaryButtons[0].pressedChangedHandler =
                [self derivedMouseButtonHandlerForBit:DERIVED_MOUSE_X1];
        }
        if (mouse.mouseInput.auxiliaryButtons.count >= 2) {
            mouse.mouseInput.auxiliaryButtons[1].pressedChangedHandler =
                [self derivedMouseButtonHandlerForBit:DERIVED_MOUSE_X2];
        }
    }
    
    // TODO: Confirm scroll direction
    mouse.mouseInput.scroll.yAxis.valueChangedHandler = ^(GCControllerAxisInput * _Nonnull axis, float value) {
        // The wheel belongs to the pointer the player handed back, and the same
        // rule applies: refuse before accumulating, so nothing is owed later.
        if (!self->_shouldSendInputEvents) {
            return;
        }
        self->accumulatedScrollY += -value;
        
        short truncatedScrollY = (short)self->accumulatedScrollY;
        
        if (truncatedScrollY != 0) {
            PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
            if (inputCtx) {
                LiSendHighResScrollEventCtx(inputCtx, truncatedScrollY);
            }
            
            self->accumulatedScrollY -= truncatedScrollY;
        }
    };
}
#endif

-(void) updateAutoOnScreenControlMode
{
    // Auto on-screen control support may not be enabled
    if (_osc == NULL) {
        return;
    }
    
    OnScreenControlsLevel level = OnScreenControlsLevelFull;
    
    // We currently stop after the first controller we find.
    // Maybe we'll want to change that logic later.
    for (int i = 0; i < [[GCController controllers] count]; i++) {
        GCController *controller = [GCController controllers][i];
        
        if (controller != NULL) {
            if (controller.extendedGamepad != NULL) {
                level = OnScreenControlsLevelAutoGCExtendedGamepad;
                if (@available(iOS 12.1, tvOS 12.1, macOS 10.14.1, *)) {
                    if (controller.extendedGamepad.leftThumbstickButton != nil &&
                        controller.extendedGamepad.rightThumbstickButton != nil) {
                        level = OnScreenControlsLevelAutoGCExtendedGamepadWithStickButtons;
                        if (@available(iOS 13.0, tvOS 13.0, macOS 10.15, *)) {
                            if (controller.extendedGamepad.buttonOptions != nil) {
                                // Has L3/R3 and Select, so we can show nothing :)
                                level = OnScreenControlsLevelOff;
                            }
                        }
                    }
                }
                break;
            }
            else if (controller.gamepad != NULL) {
                level = OnScreenControlsLevelAutoGCGamepad;
                break;
            }
        }
    }
    
#if TARGET_OS_IPHONE
    // If we didn't find a gamepad present and we have a keyboard or mouse, turn
    // the on-screen controls off to get the overlays out of the way.
    if (level == OnScreenControlsLevelFull && [ControllerSupport hasKeyboardOrMouse]) {
        level = OnScreenControlsLevelOff;
        
        // Ensure the virtual gamepad disappears to avoid confusing some games.
        // If the mouse and keyboard disconnect later, it will reappear when the
        // first OSC input is received.
        PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
        if (inputCtx) {
            LiSendMultiControllerEventCtx(inputCtx, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        }
    }
    
    [_osc setLevel:level];
#endif
}

-(void) initAutoOnScreenControlMode:(OnScreenControls*)osc
{
    _osc = osc;
    
    [self updateAutoOnScreenControlMode];
}

-(void) assignController:(GCController*)controller {
    for (int i = 0; i < 4; i++) {
        if (!(_controllerNumbers & (1 << i))) {
            _controllerNumbers |= (1 << i);
            controller.playerIndex = i;
            
            Controller* limeController;

            if (i == 0) {
                // Player 0 shares a controller object with the on-screen controls
                limeController = _player0osc;
            } else {
                limeController = [[Controller alloc] init];
                limeController.playerIndex = i;
            }
            
            limeController.gamepad = controller;

            // Prepare controller haptics for use
            [self initializeControllerHaptics:limeController];

            [_controllers setObject:limeController forKey:[NSNumber numberWithInteger:controller.playerIndex]];
            
            Log(LOG_I, @"Assigning controller index: %d", i);
            break;
        }
    }
}

#if TARGET_OS_IPHONE
-(Controller*) getOscController {
    return _player0osc;
}
#endif

+(bool) isSupportedGamepad:(GCController*) controller {
    return controller.extendedGamepad != nil || controller.gamepad != nil;
}

#pragma clang diagnostic pop

+(int) getGamepadCount {
    int count = 0;
    
    for (GCController* controller in [GCController controllers]) {
        if ([ControllerSupport isSupportedGamepad:controller]) {
            count++;
        }
    }
    
    return count;
}

+(int) getConnectedGamepadMask:(StreamConfiguration*)streamConfig {
    int mask = 0;
    
    if (streamConfig.multiController) {
        int i = 0;
        for (GCController* controller in [GCController controllers]) {
            if ([ControllerSupport isSupportedGamepad:controller]) {
                mask |= 1 << i++;
            }
        }
    }
    else {
        // Some games don't deal with having controller reconnected
        // properly so always report controller 1 if not in MC mode
        mask = 0x1;
    }
    
#if TARGET_OS_IPHONE
    DataManager* dataMan = [[DataManager alloc] init];
    TemporarySettings* settings = [dataMan getSettings];
    OnScreenControlsLevel level = (OnScreenControlsLevel)[settings.onscreenControls integerValue];
    
    // Even if no gamepads are present, we will always count one if OSC is enabled,
    // or it's set to auto and no keyboard or mouse is present. Absolute touch mode
    // disables the OSC.
    if (level != OnScreenControlsLevelOff && (![ControllerSupport hasKeyboardOrMouse] || level != OnScreenControlsLevelAuto) && !settings.absoluteTouchMode) {
        mask |= 0x1;
    }
#endif
    
    return mask;
}

-(NSUInteger) getConnectedGamepadCount
{
    return _controllers.count;
}

-(id) initWithConfig:(StreamConfiguration*)streamConfig presenceDelegate:(id<InputPresenceDelegate>)delegate
{
    self = [super init];
    
    _controllerStreamLock = [[NSLock alloc] init];
    _controllers = [[NSMutableDictionary alloc] init];
    _controllerNumbers = 0;
    _multiController = streamConfig.multiController;
    _gamepadMouseModeEnabled = streamConfig.gamepadMouseMode;
    _presenceDelegate = delegate;

    _debouncers = [[NSMutableDictionary alloc] init];
    _debouncers[@(PLAY_FLAG)] = [[NSMutableDictionary alloc] init];
    _debouncers[@(BACK_FLAG)] = [[NSMutableDictionary alloc] init];

    if (_gamepadMouseModeEnabled) {
        // Two things this timer needed and did not have.
        //
        // It has to keep firing in every mode the app runs its main run loop
        // in. A modal session and a menu drag are not NSDefaultRunLoopMode, and
        // a poll that stops there stops the only thing that turns a stick into
        // a pointer: the stream page can reach a modal alert mid-session twice
        // by name, once from MicrophoneManager (the alert whose own text is
        // about mouse polling) and once from the settings page's file picker.
        // The four other repeating timers in this app each ask for the common
        // modes by hand; this one was scheduled, which asks for the default.
        //
        // And it must not be the reason its own owner cannot be freed. A timer
        // scheduled with target:self is retained by the run loop, which retains
        // its target, so the object lived as long as the timer did -- and the
        // only thing that ever stopped the timer is -cleanup, reached from one
        // caller that returns without doing anything when it is not on the main
        // thread. An owner polled by its own timer cannot reach dealloc to stop
        // it, so the stop path cannot live there.
        //
        // Measured rather than assumed, with NSApplication initialized: a
        // repeating timer registered only in the default mode fires 0 times
        // while the main run loop runs in NSModalPanelRunLoopMode or in
        // NSEventTrackingRunLoopMode, and 15 times in 300ms registered in the
        // common modes; a target:self timer was still alive and still ticking
        // after the owner's last external reference went away, and a weak block
        // that invalidates itself was neither. scripts/timer-registration-tests.py
        // reruns that measurement, and refuses the shapes if they come back.
        //
        // This is the shape the clipboard monitor in this app already uses, and
        // the interval, the repeats, and -cleanup staying the deliberate stop
        // are all unchanged: an uncaptured session still keeps polling, because
        // the Menu-hold toggle below is the thing that turns mouse mode back on.
        __weak typeof(self) weakSelf = self;
        NSTimer *pointerPoll = [NSTimer timerWithTimeInterval:0.016
                                                      repeats:YES
                                                        block:^(NSTimer *timer) {
            ControllerSupport *owner = weakSelf;
            if (owner == nil) {
                [timer invalidate];
                return;
            }
            [owner mouseTimerCallback:timer];
        }];
        [[NSRunLoop mainRunLoop] addTimer:pointerPoll forMode:NSRunLoopCommonModes];
        _mouseTimer = pointerPoll;
    }

    _player0osc = [[Controller alloc] init];
    _player0osc.playerIndex = 0;

#if TARGET_OS_IPHONE
    DataManager* dataMan = [[DataManager alloc] init];
    _oscEnabled = (OnScreenControlsLevel)[[dataMan getSettings].onscreenControls integerValue] != OnScreenControlsLevelOff;
#endif
    
    Log(LOG_I, @"Number of supported controllers connected: %d", [ControllerSupport getGamepadCount]);
    Log(LOG_I, @"Multi-controller: %d", _multiController);
    
    for (GCController* controller in [GCController controllers]) {
        if ([ControllerSupport isSupportedGamepad:controller]) {
            [self assignController:controller];
            [self registerControllerCallbacks:controller];
            [self setupDebouncersForController:[_controllers objectForKey:@(controller.playerIndex)]];
        }
    }
    
#if TARGET_OS_IPHONE
    if (@available(iOS 14.0, tvOS 14.0, *)) {
        for (GCMouse* mouse in [GCMouse mice]) {
            [self registerMouseCallbacks:mouse];
        }
    }
#endif
    
    _controllerConnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCControllerDidConnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
        Log(LOG_I, @"Controller connected!");
        
        GCController* controller = note.object;
        
        if (![ControllerSupport isSupportedGamepad:controller]) {
            // Ignore micro gamepads and motion controllers
            return;
        }
        
        [self assignController:controller];
        
        // Register callbacks on the new controller
        [self registerControllerCallbacks:controller];
        
        [self setupDebouncersForController:[self->_controllers objectForKey:@(controller.playerIndex)]];
        
        // Re-evaluate the on-screen control mode
        [self updateAutoOnScreenControlMode];
        
        // Notify the delegate
        [self->_presenceDelegate gamepadPresenceChanged];
    }];
    _controllerDisconnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCControllerDidDisconnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
        Log(LOG_I, @"Controller disconnected!");
        
        GCController* controller = note.object;
        
        if (![ControllerSupport isSupportedGamepad:controller]) {
            // Ignore micro gamepads and motion controllers
            return;
        }
        
        [self unregisterControllerCallbacks:controller];
        self->_controllerNumbers &= ~(1 << controller.playerIndex);
        Log(LOG_I, @"Unassigning controller index: %ld", (long)controller.playerIndex);
        
        // Unset the GCController on this object (in case it is the OSC, which will persist)
        Controller* limeController = [self->_controllers objectForKey:[NSNumber numberWithInteger:controller.playerIndex]];
        
        // Stop haptics on this controller
        [self cleanupControllerHaptics:limeController];
        
        limeController.gamepad = nil;
        
        // Inform the server of the updated active gamepads before removing this controller
        [self updateFinished:limeController];
        [self->_controllers removeObjectForKey:[NSNumber numberWithInteger:controller.playerIndex]];

        // Re-evaluate the on-screen control mode
        [self updateAutoOnScreenControlMode];
        
        // Notify the delegate
        [self->_presenceDelegate gamepadPresenceChanged];
    }];
    
#if TARGET_OS_IPHONE
    if (@available(iOS 14.0, tvOS 14.0, *)) {
        _mouseConnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidConnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
            Log(LOG_I, @"Mouse connected!");
            
            GCMouse* mouse = note.object;
            
            // Register for mouse events
            [self registerMouseCallbacks: mouse];

            // Re-evaluate the on-screen control mode
            [self updateAutoOnScreenControlMode];
            
            // Notify the delegate
            [self->_presenceDelegate mousePresenceChanged];
        }];
        _mouseDisconnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidDisconnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
            Log(LOG_I, @"Mouse disconnected!");
            
            GCMouse* mouse = note.object;
            
            // Unregister for mouse events
            [self unregisterMouseCallbacks: mouse];

            // Re-evaluate the on-screen control mode
            [self updateAutoOnScreenControlMode];
            
            // Notify the delegate
            [self->_presenceDelegate mousePresenceChanged];
        }];
        _keyboardConnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCKeyboardDidConnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
            Log(LOG_I, @"Keyboard connected!");
            
            // Re-evaluate the on-screen control mode
            [self updateAutoOnScreenControlMode];
        }];
        _keyboardDisconnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCKeyboardDidDisconnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
            Log(LOG_I, @"Keyboard disconnected!");

            // Re-evaluate the on-screen control mode
            [self updateAutoOnScreenControlMode];
        }];
    }
#endif
    
    return self;
}

-(void) setupDebouncersForController:(Controller*)controller {
    if (@available(iOS 13.0, macOS 10.15, *)) {
        if (controller.gamepad.extendedGamepad == nil) return;
        
        ButtonDebouncer *play = [[ButtonDebouncer alloc] initWithButton:PLAY_FLAG input:controller.gamepad.extendedGamepad.buttonMenu controllerSupport:self chordButton:SPECIAL_FLAG];
        ButtonDebouncer *back = [[ButtonDebouncer alloc] initWithButton:BACK_FLAG input:controller.gamepad.extendedGamepad.buttonOptions controllerSupport:self chordButton:SPECIAL_FLAG];
        play.other = back;
        back.other = play;
        
        _debouncers[@(PLAY_FLAG)][@(controller.playerIndex)] = play;
        _debouncers[@(BACK_FLAG)][@(controller.playerIndex)] = back;
    }
}

// Handing the pointer back stops forwarding, which stops every path above
// from releasing a button it had already pressed on the host. The uncapture
// commit point returns the keys, the modifiers and the buttons the HID
// support tracks; the pointer this class derives from a controller is in no
// table but this one, so the return has to happen here. Both the host and the
// trackers land on no buttons down, which is what makes the gate above safe to
// refuse with: a button the player goes on holding has to be pressed again
// after recapture, and no packet from the hand-back can be owed either way.
-(void) releaseRemoteMouseButtonsForUncapture {
    int pressed = _derivedMouseButtonFlags;
    _derivedMouseButtonFlags = 0;
    for (Controller *controller in [_controllers allValues]) {
        int flags = controller.lastMouseModeButtonFlags;
        if (flags & A_FLAG) pressed |= DERIVED_MOUSE_LEFT;
        if (flags & B_FLAG) pressed |= DERIVED_MOUSE_RIGHT;
        controller.lastMouseModeButtonFlags = flags & ~(A_FLAG | B_FLAG);
    }
    if (!pressed) {
        return;
    }
    PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
    if (!inputCtx) {
        return;
    }
    for (int i = 0; i < 5; i++) {
        if (pressed & kDerivedMouseButtonBits[i]) {
            LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_RELEASE,
                                      kDerivedMouseButtonCodes[i]);
        }
    }
}

-(void) cleanup
{
    [[NSNotificationCenter defaultCenter] removeObserver:_controllerConnectObserver];
    [[NSNotificationCenter defaultCenter] removeObserver:_controllerDisconnectObserver];
#if TARGET_OS_IPHONE
    [[NSNotificationCenter defaultCenter] removeObserver:_mouseConnectObserver];
    [[NSNotificationCenter defaultCenter] removeObserver:_mouseDisconnectObserver];
    [[NSNotificationCenter defaultCenter] removeObserver:_keyboardConnectObserver];
    [[NSNotificationCenter defaultCenter] removeObserver:_keyboardDisconnectObserver];
#endif
    
    _controllerConnectObserver = nil;
    _controllerDisconnectObserver = nil;
#if TARGET_OS_IPHONE
    _mouseConnectObserver = nil;
    _mouseDisconnectObserver = nil;
    _keyboardConnectObserver = nil;
    _keyboardDisconnectObserver = nil;
#endif
    
    _controllerNumbers = 0;
    
    for (Controller* controller in [_controllers allValues]) {
        [self cleanupControllerHaptics:controller];
    }
    [_controllers removeAllObjects];
    
    for (GCController* controller in [GCController controllers]) {
        if ([ControllerSupport isSupportedGamepad:controller]) {
            [self unregisterControllerCallbacks:controller];
        }
    }
    
#if TARGET_OS_IPHONE
    if (@available(iOS 14.0, tvOS 14.0, *)) {
        for (GCMouse* mouse in [GCMouse mice]) {
            [self unregisterMouseCallbacks:mouse];
        }
    }
#endif
    
    if (_mouseTimer) {
        [_mouseTimer invalidate];
        _mouseTimer = nil;
    }
}

-(void) mouseTimerCallback:(NSTimer*)timer {
    for (Controller* controller in [_controllers allValues]) {
        if (controller.gamepad == nil) continue;
        
        GCController *gcController = controller.gamepad;
        GCExtendedGamepad *gamepad = gcController.extendedGamepad;
        
        // 1. Mouse Mode Toggle Logic: a Menu hold past the requirement, decided on release.
        // The answer comes from MLGamepadMenuGestureToggles rather than a date compare in
        // this callback, because issue #45 asked for a switch on a gesture that had none --
        // and a gesture nobody could switch off was also a gesture nobody could replay.
        // The MFi path here and the CoreHID path in HIDSupport.m now ask one function, so a
        // single switch governs both and the boundary cannot drift between them.
        BOOL menuPressed = NO;

        if (gamepad) {
            if (@available(iOS 13.0, tvOS 13.0, macOS 10.15, *)) {
                menuPressed = gamepad.buttonMenu.pressed;
            }
        }

        BOOL gestureEnabled = NO;
        if ([self->_presenceDelegate respondsToSelector:@selector(gamepadMenuLongPressTogglesMouseModeEnabled)]) {
            gestureEnabled = [self->_presenceDelegate gamepadMenuLongPressTogglesMouseModeEnabled];
        }

        MLGamepadMenuGesture gesture = controller.menuGesture;
        const BOOL toggled = MLGamepadMenuGestureToggles(&gesture,
                                                         menuPressed ? YES : NO,
                                                         [NSDate date].timeIntervalSinceReferenceDate,
                                                         gestureEnabled ? YES : NO,
                                                         MLGamepadMenuLongPressRequiredSeconds);
        controller.menuGesture = gesture;
        if (toggled) {
            controller.isMouseMode = !controller.isMouseMode;

            // Notify delegate
            if ([self->_presenceDelegate respondsToSelector:@selector(mouseModeToggled:)]) {
                [self->_presenceDelegate mouseModeToggled:controller.isMouseMode];
            }

            // Rumble to indicate toggle
            [self rumble:controller.playerIndex lowFreqMotor:0xFFFF highFreqMotor:0xFFFF];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                [self rumble:controller.playerIndex lowFreqMotor:0 highFreqMotor:0];
            });
        }

        // 2. Mouse Movement Logic
        if (controller.isMouseMode) {
            // Handing the pointer back to the Mac turns input forwarding off,
            // and this timer keeps running until the session ends: uncapture
            // clears shouldSendInputEvents and nothing invalidates the timer.
            // The button path in this file asks that flag before it sends, and
            // so does the display-link consumer in HIDSupport+Pointer.m. This
            // path asked nothing, so a right stick parked past its deadzone
            // kept dragging the remote cursor with it while the player was
            // moving their own mouse across the Mac.
            // It asks before the deadzone rather than before the send, which
            // is what keeps refused motion from adding up. A gate sitting
            // between the accumulation and the send would owe the host the
            // whole uncapture as one throw when capture came back.
            if (!_shouldSendInputEvents) {
                continue;
            }

            float deltaX = 0;
            float deltaY = 0;
            
            if (gamepad) {
                deltaX = gamepad.rightThumbstick.xAxis.value;
                deltaY = gamepad.rightThumbstick.yAxis.value;
            }
            
            // The same deadzone and the same rate the HID consumer applies, from
            // one shared header: these were two literals here and a count threshold
            // there, so the same stick position meant two different cursor speeds.
            if (fabs(deltaX) > HIDMouseEmulationDeadzone ||
                fabs(deltaY) > HIDMouseEmulationDeadzone) {
                self->_accumulatedMouseX += deltaX * HIDMouseEmulationSpeed;
                self->_accumulatedMouseY += -deltaY * HIDMouseEmulationSpeed;
                
                short truncX = (short)self->_accumulatedMouseX;
                short truncY = (short)self->_accumulatedMouseY;
                
                if (truncX != 0 || truncY != 0) {
                    PML_INPUT_STREAM_CONTEXT inputCtx = ControllerInputContext(self);
                    if (inputCtx) {
                        LiSendMouseMoveEventCtx(inputCtx, truncX, truncY);
                    }
                    self->_accumulatedMouseX -= truncX;
                    self->_accumulatedMouseY -= truncY;
                }
            }
        }
    }
}

@end
