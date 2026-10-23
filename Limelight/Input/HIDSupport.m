//
//  HIDSupport.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 26/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//
#import "HIDSupport_Internal.h"
#import "InputDiagnosticsLedger.h"
#import "ControllerEventBaseline.h"
#import "GamepadMenuGesture.h"
#import "KeyboardMapResolver.h"
#import "HIDKeyboardQuirkFilter.h"
#import "HIDSupport+Inventory.h"
#import "MLControllerInventory.h"
#import "KeyboardTextRouting.h"

#import <IOKit/hid/IOHIDElement.h>
#import <IOKit/hid/IOHIDKeys.h>  // kIOHIDPrimaryUsagePageKey: what kind of device a node claims to be
#import <ApplicationServices/ApplicationServices.h>  // CGEventSourceKeyState: what the keyboard is physically doing
#import <IOKit/hidsystem/IOLLEvent.h>

// Physical modifier mappings and the per-host Command preference are resolved
// by KeyboardMapResolver. Ordinary key ownership remains in this session.

// CVDisplayLink is deprecated in macOS 15.0 but remains the recommended API
// for low-latency game input polling. The new NSView.displayLink API is not
// yet validated for sub-frame input latency. Suppress deprecation at file
// scope; tracked for migration in a future release.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"


NSString *const HIDMouseModeToggledNotification = @"HIDMouseModeToggledNotification";
NSString *const HIDGamepadQuitNotification = @"HIDGamepadQuitNotification";
const void *HIDInputQueueSpecificKey = &HIDInputQueueSpecificKey;


// Check missing releases after a short state-race allowance. This recovery is
// limited to the allowlist below and can be disabled independently of attribution.
static uint64_t const HIDKeyStateHealGraceMs = 120;
static uint64_t const HIDKeyStateHealIntervalMs = 25;
// Allow AppKit and IOHID callbacks to arrive in either order before attribution.
static uint64_t const HIDKeyStateHoldConfirmMs = 60;
// General state-based quarantine is opt-in. The observed unpaired C defect also
// occurs without an external pointer or Input Monitoring access, so C has its
// own default confirmation path below. A real release confirms a rapid tap.
// No key is converted into a mouse click.
static NSString * const HIDKeyStateHealDisabledDefault = @"input.disableKeyStateHeal";
static NSString * const HIDKeyStateHoldEnabledDefault = @"input.enableKeyStateHold";


struct KeyMapping {
    unsigned short mac;
    short windows;
};

static struct KeyMapping keys[] = {
    {kVK_ANSI_A, 'A'},
    {kVK_ANSI_B, 'B'},
    {kVK_ANSI_C, 'C'},
    {kVK_ANSI_D, 'D'},
    {kVK_ANSI_E, 'E'},
    {kVK_ANSI_F, 'F'},
    {kVK_ANSI_G, 'G'},
    {kVK_ANSI_H, 'H'},
    {kVK_ANSI_I, 'I'},
    {kVK_ANSI_J, 'J'},
    {kVK_ANSI_K, 'K'},
    {kVK_ANSI_L, 'L'},
    {kVK_ANSI_M, 'M'},
    {kVK_ANSI_N, 'N'},
    {kVK_ANSI_O, 'O'},
    {kVK_ANSI_P, 'P'},
    {kVK_ANSI_Q, 'Q'},
    {kVK_ANSI_R, 'R'},
    {kVK_ANSI_S, 'S'},
    {kVK_ANSI_T, 'T'},
    {kVK_ANSI_U, 'U'},
    {kVK_ANSI_V, 'V'},
    {kVK_ANSI_W, 'W'},
    {kVK_ANSI_X, 'X'},
    {kVK_ANSI_Y, 'Y'},
    {kVK_ANSI_Z, 'Z'},

    {kVK_ANSI_0, '0'},
    {kVK_ANSI_1, '1'},
    {kVK_ANSI_2, '2'},
    {kVK_ANSI_3, '3'},
    {kVK_ANSI_4, '4'},
    {kVK_ANSI_5, '5'},
    {kVK_ANSI_6, '6'},
    {kVK_ANSI_7, '7'},
    {kVK_ANSI_8, '8'},
    {kVK_ANSI_9, '9'},
    
    {kVK_ANSI_Equal, 0xBB},
    {kVK_ANSI_Minus, 0xBD},
    {kVK_ANSI_RightBracket, 0xDD},
    {kVK_ANSI_LeftBracket, 0xDB},
    {kVK_ANSI_Quote, 0xDE},
    {kVK_ANSI_Semicolon, 0xBA},
    {kVK_ANSI_Backslash, 0xDC},
    {kVK_ANSI_Comma, 0xBC},
    {kVK_ANSI_Slash, 0xBF},
    {kVK_ANSI_Period, 0xBE},
    {kVK_ANSI_Grave, 0xC0},
    {kVK_ANSI_KeypadDecimal, 0x6E},
    {kVK_ANSI_KeypadMultiply, 0x6A},
    {kVK_ANSI_KeypadPlus, 0x6B},
    {kVK_ANSI_KeypadClear, 0xFE},
    {kVK_ANSI_KeypadDivide, 0x6F},
    {kVK_ANSI_KeypadEnter, 0x0D},
    {kVK_ISO_Section, 0xE2},
    {kVK_ContextualMenu, 0x5D},
    {kVK_ANSI_KeypadMinus, 0x6D},
    {kVK_ANSI_KeypadEquals, 0xBB},
    {kVK_ANSI_Keypad0, 0x60},
    {kVK_ANSI_Keypad1, 0x61},
    {kVK_ANSI_Keypad2, 0x62},
    {kVK_ANSI_Keypad3, 0x63},
    {kVK_ANSI_Keypad4, 0x64},
    {kVK_ANSI_Keypad5, 0x65},
    {kVK_ANSI_Keypad6, 0x66},
    {kVK_ANSI_Keypad7, 0x67},
    {kVK_ANSI_Keypad8, 0x68},
    {kVK_ANSI_Keypad9, 0x69},
    
    {kVK_Delete, 0x08},
    {kVK_Tab, 0x09},
    {kVK_Return, 0x0D},
    {kVK_Shift, 0xA0},
    {kVK_Control, 0xA2},
    {kVK_Option, 0xA4},
    {kVK_CapsLock, 0x14},
    {kVK_Escape, 0x1B},
    {kVK_Space, 0x20},
    {kVK_PageUp, 0x21},
    {kVK_PageDown, 0x22},
    {kVK_End, 0x23},
    {kVK_Home, 0x24},
    {kVK_LeftArrow, 0x25},
    {kVK_UpArrow, 0x26},
    {kVK_RightArrow, 0x27},
    {kVK_DownArrow, 0x28},
    {kVK_ForwardDelete, 0x2E},
    {kVK_Help, 0x2F},
    {kVK_Command, 0x5B},
    {kVK_RightCommand, 0x5C},
    {kVK_RightShift, 0xA1},
    {kVK_RightOption, 0xA5},
    {kVK_RightControl, 0xA3},
    {kVK_Mute, 0xAD},
    {kVK_VolumeDown, 0xAE},
    {kVK_VolumeUp, 0xAF},

    {kVK_F1, 0x70},
    {kVK_F2, 0x71},
    {kVK_F3, 0x72},
    {kVK_F4, 0x73},
    {kVK_F5, 0x74},
    {kVK_F6, 0x75},
    {kVK_F7, 0x76},
    {kVK_F8, 0x77},
    {kVK_F9, 0x78},
    {kVK_F10, 0x79},
    {kVK_F11, 0x7A},
    {kVK_F12, 0x7B},
    {kVK_F13, 0x7C},
    {kVK_F14, 0x7D},
    {kVK_F15, 0x7E},
    {kVK_F16, 0x7F},
    {kVK_F17, 0x80},
    {kVK_F18, 0x81},
    {kVK_F19, 0x82},
    {kVK_F20, 0x83},
};

typedef NS_OPTIONS(NSUInteger, HIDKeyboardPhysicalModifierMask) {
    HIDKeyboardPhysicalModifierMaskLeftShift = 1 << 0,
    HIDKeyboardPhysicalModifierMaskRightShift = 1 << 1,
    HIDKeyboardPhysicalModifierMaskLeftControl = 1 << 2,
    HIDKeyboardPhysicalModifierMaskRightControl = 1 << 3,
    HIDKeyboardPhysicalModifierMaskLeftOption = 1 << 4,
    HIDKeyboardPhysicalModifierMaskRightOption = 1 << 5,
    HIDKeyboardPhysicalModifierMaskLeftCommand = 1 << 6,
    HIDKeyboardPhysicalModifierMaskRightCommand = 1 << 7,
};

typedef NS_OPTIONS(NSUInteger, HIDKeyboardRemoteModifierMask) {
    HIDKeyboardRemoteModifierMaskLeftShift = 1 << 0,
    HIDKeyboardRemoteModifierMaskRightShift = 1 << 1,
    HIDKeyboardRemoteModifierMaskLeftControl = 1 << 2,
    HIDKeyboardRemoteModifierMaskRightControl = 1 << 3,
    HIDKeyboardRemoteModifierMaskLeftAlt = 1 << 4,
    HIDKeyboardRemoteModifierMaskRightAlt = 1 << 5,
    HIDKeyboardRemoteModifierMaskLeftMeta = 1 << 6,
    HIDKeyboardRemoteModifierMaskRightMeta = 1 << 7,
};

static HIDKeyboardPhysicalModifierMask HIDPhysicalModifierMaskForKeyCode(unsigned short keyCode) {
    switch (keyCode) {
        case kVK_Shift:
            return HIDKeyboardPhysicalModifierMaskLeftShift;
        case kVK_RightShift:
            return HIDKeyboardPhysicalModifierMaskRightShift;
        case kVK_Control:
            return HIDKeyboardPhysicalModifierMaskLeftControl;
        case kVK_RightControl:
            return HIDKeyboardPhysicalModifierMaskRightControl;
        case kVK_Option:
            return HIDKeyboardPhysicalModifierMaskLeftOption;
        case kVK_RightOption:
            return HIDKeyboardPhysicalModifierMaskRightOption;
        case kVK_Command:
            return HIDKeyboardPhysicalModifierMaskLeftCommand;
        case kVK_RightCommand:
            return HIDKeyboardPhysicalModifierMaskRightCommand;
        default:
            return 0;
    }
}

static NSEventModifierFlags HIDModifierFlagForKeyCode(unsigned short keyCode) {
    switch (keyCode) {
        case kVK_Shift:
        case kVK_RightShift:
            return NSEventModifierFlagShift;
        case kVK_Control:
        case kVK_RightControl:
            return NSEventModifierFlagControl;
        case kVK_Option:
        case kVK_RightOption:
            return NSEventModifierFlagOption;
        case kVK_Command:
        case kVK_RightCommand:
            return NSEventModifierFlagCommand;
        default:
            return 0;
    }
}

// AppKit's family bit answers "is some shift down". That is not the question
// this file asks: a flagsChanged names the key that just moved, and the record
// has to say whether that one key is held. The two answers disagree the moment
// a player holds one shift and lets go of the other -- the family bit stays set
// because its twin still holds it -- and reading the family bit there keeps
// the released key in the physical mask for good. The host goes on holding a
// modifier nobody is touching, and every key pressed after it carries that
// modifier: a walk that will not slow down, and a jump that arrives as whatever
// Shift+Space is bound to. This is the same complaint as "W and Space collide",
// one layer underneath the pair the player happened to notice.
//
// The per-key answer is in the same field, in its device-dependent half. It is
// used whenever the source supplies any of those bits, and the family
// bit stays the fallback for a source that supplies none, so an event that only
// ever carried a family bit keeps behaving exactly as it did before.
static NSEventModifierFlags HIDDeviceModifierMaskForKeyCode(
        unsigned short keyCode) {
    switch (keyCode) {
        case kVK_Shift:        return NX_DEVICELSHIFTKEYMASK;
        case kVK_RightShift:   return NX_DEVICERSHIFTKEYMASK;
        case kVK_Control:      return NX_DEVICELCTLKEYMASK;
        case kVK_RightControl: return NX_DEVICERCTLKEYMASK;
        case kVK_Option:       return NX_DEVICELALTKEYMASK;
        case kVK_RightOption:  return NX_DEVICERALTKEYMASK;
        case kVK_Command:      return NX_DEVICELCMDKEYMASK;
        case kVK_RightCommand: return NX_DEVICERCMDKEYMASK;
        default:               return 0;
    }
}

// True when the snapshot says which key moved at all. A set carrying none of
// these bits is only answering "some member of the family is down", and the
// family bit is the honest reading of that.
static BOOL HIDEventCarriesDeviceModifierState(NSEventModifierFlags flags) {
    static const NSEventModifierFlags every =
        NX_DEVICELCTLKEYMASK | NX_DEVICELSHIFTKEYMASK | NX_DEVICERSHIFTKEYMASK |
        NX_DEVICELCMDKEYMASK | NX_DEVICERCMDKEYMASK | NX_DEVICELALTKEYMASK |
        NX_DEVICERALTKEYMASK | NX_DEVICERCTLKEYMASK;
    return (flags & every) != 0;
}

static HIDKeyboardPhysicalModifierMask HIDEffectivePhysicalModifierMaskForEvent(HIDKeyboardPhysicalModifierMask physicalMask,
                                                                                NSEvent *event) {
    // flagsChanged and capture reconciliation own the physical side state.
    // Generic event flags cannot reliably distinguish left from right, and
    // mouse events must never be used as keyboard evidence.
    (void)event;
    return physicalMask;
}

static unsigned short HIDRemoteModifierKeyCode(HIDKeyboardRemoteModifierMask mask) {
    switch (mask) {
        case HIDKeyboardRemoteModifierMaskLeftShift:
            return 0xA0;
        case HIDKeyboardRemoteModifierMaskRightShift:
            return 0xA1;
        case HIDKeyboardRemoteModifierMaskLeftControl:
            return 0xA2;
        case HIDKeyboardRemoteModifierMaskRightControl:
            return 0xA3;
        case HIDKeyboardRemoteModifierMaskLeftAlt:
            return 0xA4;
        case HIDKeyboardRemoteModifierMaskRightAlt:
            return 0xA5;
        case HIDKeyboardRemoteModifierMaskLeftMeta:
            return 0x5B;
        case HIDKeyboardRemoteModifierMaskRightMeta:
            return 0x5C;
        default:
            return 0;
    }
}

static BOOL HIDIsModifierKeyCode(unsigned short keyCode) {
    return HIDPhysicalModifierMaskForKeyCode(keyCode) != 0;
}

static char HIDRemoteModifierFlagsToGenericFlags(NSUInteger remoteMask) {
    char modifiers = 0;

    if (remoteMask & (HIDKeyboardRemoteModifierMaskLeftShift | HIDKeyboardRemoteModifierMaskRightShift)) {
        modifiers |= MODIFIER_SHIFT;
    }
    if (remoteMask & (HIDKeyboardRemoteModifierMaskLeftControl | HIDKeyboardRemoteModifierMaskRightControl)) {
        modifiers |= MODIFIER_CTRL;
    }
    if (remoteMask & (HIDKeyboardRemoteModifierMaskLeftAlt | HIDKeyboardRemoteModifierMaskRightAlt)) {
        modifiers |= MODIFIER_ALT;
    }
    if (remoteMask & (HIDKeyboardRemoteModifierMaskLeftMeta | HIDKeyboardRemoteModifierMaskRightMeta)) {
        modifiers |= MODIFIER_META;
    }

    return modifiers;
}

// A synthetic sequence may only press and release modifiers it actually put down.
//
// The physical modifier state is tracked separately from these hand-written packets,
// and -syncKeyboardModifierStateForEvent: decides what to send by diffing the desired
// mask against that tracker. Releasing a modifier the player is holding with a real
// finger is therefore not a cosmetic surplus: the tracker still says the key is down,
// the diff comes out zero, and no corrective press is ever sent. The player keeps
// Shift held and the game has stopped sprinting, with nothing logged on either side.
// Pressing it a second time is the other half of the same mistake -- it is what makes
// the release below ambiguous about which press it answers.
//
// Reachable during gameplay: StreamViewController+MouseCapture.m fires these for
// mouse-driven translation rules, so "hold Shift to sprint, trigger a Shift+Tab rule"
// is a normal sequence and not an edge case.
static NSUInteger HIDSyntheticOwnedModifierMask(HIDSupport *support, NSUInteger requested) {
    return requested & ~support.keyboardRemoteModifierMask;
}

static NSUInteger HIDSyntheticRemoteModifierMaskForKeyCode(HIDSupport *support,
                                                           unsigned short keyCode,
                                                           BOOL preferShortcutTranslationCommandMapping) {
    // The mapping is the standard one; only what Command means is the player's to choose.
    // preferShortcutTranslationCommandMapping is a name the old compatibility modes left
    // behind, and it no longer picks a mapping -- the preference below does.
    KMR_PhysicalModifier phys = KMR_PhysicalFromKeyCode(keyCode);
    if (phys == KMR_Phys_Count) {
        return 0;
    }
    return (NSUInteger)KMR_RemoteMaskForPhysicalWithCommandPreference(
        phys, [support commandKeyPreferenceForCurrentHost]);
}

static void HIDDispatchSyntheticRemoteModifierTap(HIDSupport *support,
                                                  NSUInteger remoteModifierMask,
                                                  const char *op) {
    if (remoteModifierMask == 0) {
        return;
    }

    HIDInputLease inputLease = HIDAcquireInputContext(support);

    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, op)) {
        return;
    }

    // A modifier the player is already holding belongs to the player, not to this tap:
    // pressing it again and letting it go would take it away mid-gameplay.
    NSUInteger owned = HIDSyntheticOwnedModifierMask(support, remoteModifierMask);
    if (owned == 0) {
        return;
    }

    static const HIDKeyboardRemoteModifierMask remoteOrder[] = {
        HIDKeyboardRemoteModifierMaskLeftShift,
        HIDKeyboardRemoteModifierMaskRightShift,
        HIDKeyboardRemoteModifierMaskLeftControl,
        HIDKeyboardRemoteModifierMaskRightControl,
        HIDKeyboardRemoteModifierMaskLeftAlt,
        HIDKeyboardRemoteModifierMaskRightAlt,
        HIDKeyboardRemoteModifierMaskLeftMeta,
        HIDKeyboardRemoteModifierMaskRightMeta,
    };

    // The legacy flag byte still describes the whole combination the host is being
    // asked about; which keys this sequence is allowed to touch is the owned mask.
    char translatedModifiers = HIDRemoteModifierFlagsToGenericFlags(remoteModifierMask);
    HIDDispatchInput(support, inputLease, ^{
        for (NSUInteger i = 0; i < sizeof(remoteOrder) / sizeof(remoteOrder[0]); i++) {
            HIDKeyboardRemoteModifierMask mask = remoteOrder[i];
            if ((owned & mask) == 0) {
                continue;
            }

            unsigned short modifierKeyCode = HIDRemoteModifierKeyCode(mask);
            if (modifierKeyCode != 0) {
                LiSendKeyboardEventCtx(inputCtx, modifierKeyCode, KEY_ACTION_DOWN, translatedModifiers);
                LiSendKeyboardEventCtx(inputCtx, modifierKeyCode, KEY_ACTION_UP, 0);
            }
        }
    });
}

@implementation HIDInputDiagnosticsSnapshot
@end

@implementation HIDSupport
@synthesize inputContext = _inputContext;
@synthesize shouldSendInputEvents = _shouldSendInputEvents;
@synthesize suspendControllerEvents = _suspendControllerEvents;

// Button ownership and capture closure share this lock. Once NO is published,
// a concurrent hardware producer cannot insert another press behind cleanup.
- (BOOL)shouldSendInputEvents {
    @synchronized (self) { return _shouldSendInputEvents; }
}

- (void)setShouldSendInputEvents:(BOOL)enabled {
    @synchronized (self) {
        BOOL next = enabled && !self.keyboardTeardownAlreadyCalled;
        if (_shouldSendInputEvents != next) {
            self.inputCaptureGeneration += 1;
            [self resetPointerMotionForCaptureTransition];
        }
        _shouldSendInputEvents = next;
        // M1: a stream that starts announces the pads the player already has in
        // hand -- an idle controller sends no input, so waiting for its first
        // value would leave the host without it for the whole session.
        if (next) {
            [self announceIdleControllersForNewStream];
        }
    }
}

// M1: every pad in the table that the host has not been told about yet gets its
// arrival event now. Kept out of the setter so the setter stays the one-line
// transition the boundary harness extracts on its own.
- (void)announceIdleControllersForNewStream {
    // P2-3b: a stream that opens while the app is in the background (e.g. a
    // side-by-side window that lost focus before the launch even finished)
    // must not tell the host the pads are already live -- the player is not
    // in a position to send input, so the host would have to wait for an
    // arrival it can do nothing with.
    if (self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents) return;
    for (HIDDeviceControllerEntry *entry in [self deviceControllerTable].allValues) {
        [self sendControllerArrivalForEntry:entry];
    }
}

- (void *)inputContext {
    @synchronized (self.inputContextLock) {
        return _inputContext;
    }
}

- (void)setInputContext:(void *)inputContext {
    // Serialize detachment with sends. Queued blocks also carry this generation,
    // so address reuse cannot turn an old packet into input for a new session.
    __block BOOL changed = NO;
    void (^replaceContext)(void) = ^{
        @synchronized (self.inputContextLock) {
            if (self->_inputContext == inputContext) {
                return;
            }
            self->_inputContext = inputContext;
            self.inputContextGeneration += 1;
            changed = YES;
        }
    };
    if (self.inputQueue != NULL && dispatch_get_specific(HIDInputQueueSpecificKey) != (__bridge void *)self) {
        dispatch_sync(self.inputQueue, replaceContext);
    } else {
        replaceContext();
    }
    if (!changed) {
        return;
    }
    [self syncScrollTraceDiagnosticsPreferenceToInputContext];
    // The heal loop belongs to the input channel, not to a key press: arming it here means the first
    // press of a session is already covered, and a harness that drives -keyDown: directly (the
    // pairing and identity probes) never starts a timer it has no runloop for. The loop itself is
    // pinned by key-state-heal-tests.py.
    void (^updateKeyboardMonitoring)(void) = ^{
        if (self.inputContext != inputContext) {
            return;
        }
        if (inputContext != NULL) {
            [self.keyboardQuirkFilter start];
            [self startKeyboardStateHealTimerIfNeeded];
            [self announceIdleControllersForNewStream];
        } else {
            [self.keyboardQuirkFilter stop];
            [self stopKeyboardStateHealTimer];
            // Stream end is the sensor-stop request the host does not bother
            // to send: clear every pad's activation so a reconnected host
            // starts from "no sensors" instead of inheriting the previous
            // session's requests.
            for (HIDDeviceControllerEntry *candidate in self.deviceControllerTable.allValues) {
                [self stopMotionEventsForEntry:candidate];
                // A reconnected host has not seen this session's battery yet,
                // so clear the dedup and let the next packet re-announce it.
                candidate.previousBatteryState = 0xFF;
                candidate.previousBatteryPercentage = 0xFF;
                // Same for the touch session: a finger that was down when the
                // stream ended is not on the pad when it resumes.
                candidate.touchPressed = NO;
                candidate.touchPressed2 = NO;
                candidate.touchPointerId = 0;
                candidate.touchLastX = 0.0f;
                candidate.touchLastY = 0.0f;
                candidate.touchPointerId2 = 0;
                candidate.touchLastX2 = 0.0f;
                candidate.touchLastY2 = 0.0f;
            }
        }
    };
    if ([NSThread isMainThread]) {
        updateKeyboardMonitoring();
    } else {
        dispatch_async(dispatch_get_main_queue(), updateKeyboardMonitoring);
    }
}

- (void)refreshInputDiagnosticsPreference {
    self.inputDiagnosticsEnabled = [SettingsClass inputDiagnosticsEnabled];
    [self syncScrollTraceDiagnosticsPreferenceToInputContext];
}

- (void)resetInputDiagnostics {
    [self refreshInputDiagnosticsPreference];

    @synchronized (self.inputDiagnosticsLock) {
        self.inputDiagnosticsDetailedLogSequence = 0;
        self.inputDiagnosticsRemainingDetailedLogs = self.inputDiagnosticsEnabled ? 24 : 0;
        self.inputDiagnosticsRemainingScrollDetailedLogs = self.inputDiagnosticsEnabled ? 256 : 0;
        self.inputDiagnosticsRemainingButtonEdgeLogs = self.inputDiagnosticsEnabled ? 512 : 0;
        self.scrollTraceSequence = 0;
        self.activeScrollTraceId = 0;
        self.activeScrollTraceStartedMs = 0;
        self.activeScrollTraceLastEventMs = 0;
        self.activeScrollTraceLockedToPrecise = NO;
        self.activeScrollTraceSource = nil;
        self.inputDiagnosticsMouseMoveEvents = 0;
        self.inputDiagnosticsNonZeroRelativeEvents = 0;
        self.inputDiagnosticsRelativeDispatches = 0;
        self.inputDiagnosticsAbsoluteDispatches = 0;
        self.inputDiagnosticsAbsoluteDuplicateSkips = 0;
        self.inputDiagnosticsCoreHIDRawEvents = 0;
        self.inputDiagnosticsCoreHIDDispatches = 0;
        self.inputDiagnosticsSuppressedRelativeEvents = 0;
        self.inputDiagnosticsRawRelativeDeltaX = 0;
        self.inputDiagnosticsRawRelativeDeltaY = 0;
        self.inputDiagnosticsSentRelativeDeltaX = 0;
        self.inputDiagnosticsSentRelativeDeltaY = 0;
        self.inputDiagnosticsRelativeMotionBySource = [NSMutableDictionary dictionary];
        self.inputDiagnosticsAbsoluteMotionBySource = [NSMutableDictionary dictionary];
    }
}

- (HIDInputDiagnosticsSnapshot *)consumeInputDiagnosticsSnapshot {
    HIDInputDiagnosticsSnapshot *snapshot = [[HIDInputDiagnosticsSnapshot alloc] init];

    @synchronized (self.inputDiagnosticsLock) {
        snapshot.mouseMoveEvents = self.inputDiagnosticsMouseMoveEvents;
        snapshot.nonZeroRelativeEvents = self.inputDiagnosticsNonZeroRelativeEvents;
        snapshot.relativeDispatches = self.inputDiagnosticsRelativeDispatches;
        snapshot.absoluteDispatches = self.inputDiagnosticsAbsoluteDispatches;
        snapshot.absoluteDuplicateSkips = self.inputDiagnosticsAbsoluteDuplicateSkips;
        snapshot.coreHIDRawEvents = self.inputDiagnosticsCoreHIDRawEvents;
        snapshot.coreHIDDispatches = self.inputDiagnosticsCoreHIDDispatches;
        snapshot.suppressedRelativeEvents = self.inputDiagnosticsSuppressedRelativeEvents;
        snapshot.rawRelativeDeltaX = self.inputDiagnosticsRawRelativeDeltaX;
        snapshot.rawRelativeDeltaY = self.inputDiagnosticsRawRelativeDeltaY;
        snapshot.sentRelativeDeltaX = self.inputDiagnosticsSentRelativeDeltaX;
        snapshot.sentRelativeDeltaY = self.inputDiagnosticsSentRelativeDeltaY;
        // Taken and cleared rather than read, like every other field here: a report that
        // sampled the same sender twice would credit it twice, and one that sampled after a
        // clear would show a sender that had already been counted.
        snapshot.relativeMotionBySource = [self.inputDiagnosticsRelativeMotionBySource copy];
        snapshot.absoluteMotionBySource = [self.inputDiagnosticsAbsoluteMotionBySource copy];
        [self.inputDiagnosticsRelativeMotionBySource removeAllObjects];
        [self.inputDiagnosticsAbsoluteMotionBySource removeAllObjects];

        self.inputDiagnosticsMouseMoveEvents = 0;
        self.inputDiagnosticsNonZeroRelativeEvents = 0;
        self.inputDiagnosticsRelativeDispatches = 0;
        self.inputDiagnosticsAbsoluteDispatches = 0;
        self.inputDiagnosticsAbsoluteDuplicateSkips = 0;
        self.inputDiagnosticsCoreHIDRawEvents = 0;
        self.inputDiagnosticsCoreHIDDispatches = 0;
        self.inputDiagnosticsSuppressedRelativeEvents = 0;
        self.inputDiagnosticsRawRelativeDeltaX = 0;
        self.inputDiagnosticsRawRelativeDeltaY = 0;
        self.inputDiagnosticsSentRelativeDeltaX = 0;
        self.inputDiagnosticsSentRelativeDeltaY = 0;
    }

    return snapshot;
}

- (BOOL)reserveDetailedInputDiagnosticsLogSequence:(NSUInteger *)sequence {
    BOOL shouldLog = NO;

    @synchronized (self.inputDiagnosticsLock) {
        if (!self.inputDiagnosticsEnabled || self.inputDiagnosticsRemainingDetailedLogs == 0) {
            return NO;
        }

        self.inputDiagnosticsDetailedLogSequence += 1;
        self.inputDiagnosticsRemainingDetailedLogs -= 1;
        shouldLog = YES;
        if (sequence != NULL) {
            *sequence = self.inputDiagnosticsDetailedLogSequence;
        }
    }

    return shouldLog;
}

// The button edge gets its own credit and may not stand in the shared queue behind the motion
// lines. The 24-slot budget above is spent by relative/absolute motion the moment a stream starts,
// so a button probe that reserves from it goes silent before the first click and then reports
// "no button ever arrived" for a session that had hundreds of them. That is how the 2026-09-26
// capture read mouse-button as zero lines while [clickdiag] recorded 32 right clicks in the same
// window: the counter was empty, the mouse was not. The sequence number stays shared so a button
// line still lines up with the motion lines around it. docs/memory-ownership.md S36.
- (BOOL)reserveMouseButtonEdgeDiagnosticsLogSequence:(NSUInteger *)sequence {
    if (!self.inputDiagnosticsEnabled) {
        return NO;
    }

    @synchronized (self.inputDiagnosticsLock) {
        if (self.inputDiagnosticsRemainingButtonEdgeLogs == 0) {
            return NO;
        }

        self.inputDiagnosticsDetailedLogSequence += 1;
        self.inputDiagnosticsRemainingButtonEdgeLogs -= 1;
        if (sequence != NULL) {
            *sequence = self.inputDiagnosticsDetailedLogSequence;
        }
    }

    return YES;
}

- (void)syncScrollTraceDiagnosticsPreferenceToInputContext {
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    BOOL enabled = self.inputDiagnosticsEnabled;
    HIDDispatchInput(self, inputLease, ^{
        LiSetScrollTraceDiagnosticsEnabledCtx(inputCtx, enabled);
    });
}

- (uint64_t)prepareScrollTraceFromSource:(NSString *)source
                               rawDeltaX:(CGFloat)rawDeltaX
                               rawDeltaY:(CGFloat)rawDeltaY
                                   phase:(NSEventPhase)phase
                           momentumPhase:(NSEventPhase)momentumPhase
                        hasPreciseDeltas:(BOOL)hasPreciseDeltas {
    [self syncScrollTraceDiagnosticsPreferenceToInputContext];
    // Gesture classification must not change when diagnostic logging is off.
    // Trace state belongs to the input path; only wire instrumentation is optional.

    uint64_t nowMs = LiGetMillis();
    __block BOOL startsNewTrace = NO;
    __block uint64_t traceId = 0;

    @synchronized (self.inputDiagnosticsLock) {
        BOOL idleExpired = self.activeScrollTraceLastEventMs == 0 ||
                           nowMs < self.activeScrollTraceLastEventMs ||
                           nowMs - self.activeScrollTraceLastEventMs > 180;
        BOOL explicitBegin = phase == NSEventPhaseBegan || momentumPhase == NSEventPhaseBegan;
        BOOL sourceChanged = (self.activeScrollTraceSource == nil && source != nil) ||
                             (self.activeScrollTraceSource != nil && source == nil) ||
                             (self.activeScrollTraceSource != nil && source != nil &&
                              ![self.activeScrollTraceSource isEqualToString:source]);
        if (self.activeScrollTraceId == 0 || explicitBegin || idleExpired || sourceChanged) {
            self.scrollTraceSequence += 1;
            if (self.scrollTraceSequence == 0) {
                self.scrollTraceSequence = 1;
            }
            self.activeScrollTraceId = self.scrollTraceSequence;
            self.activeScrollTraceStartedMs = nowMs;
            self.activeScrollTraceLockedToPrecise = NO;
            self.activeScrollTraceSource = [source copy];
            startsNewTrace = YES;
        } else if (source != nil) {
            self.activeScrollTraceSource = [source copy];
        }

        self.activeScrollTraceLastEventMs = nowMs;
        traceId = self.activeScrollTraceId;
    }

    if (startsNewTrace && self.inputDiagnosticsEnabled) {
        HIDInputLease inputLease = HIDAcquireInputContext(self);
        PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
        HIDDispatchInput(self, inputLease, ^{
            LiStartScrollTraceCtx(inputCtx, traceId, nowMs);
        });
        Log(LOG_D, @"[inputdiag] scroll-trace start trace=%llu source=%@ raw=(%.3f,%.3f) phase=%lu momentum=%lu precise=%d",
            (unsigned long long)traceId,
            source ?: @"unknown",
            rawDeltaX,
            rawDeltaY,
            (unsigned long)phase,
            (unsigned long)momentumPhase,
            hasPreciseDeltas ? 1 : 0);
    }

    return traceId;
}

/// Count one packet under the sender that handed it over.
///
/// Under the diagnostics lock rather than atomic: the buckets are read whole by
/// `consumeInputDiagnosticsSnapshot:`, which takes and clears them, and an atomic value in a
/// dictionary still leaves that read halfway through a write.
static inline void HIDIncrementInputDiagnosticsBucket(NSMutableDictionary<NSString *, NSNumber *> *bucket,
                                                     NSString *source) {
    if (bucket == nil) {
        return;
    }
    NSString *key = source.length > 0 ? source : @"unknown";
    bucket[key] = @(bucket[key].unsignedIntegerValue + 1);
}

- (void)recordRelativeInputDiagnosticsFrom:(NSString *)source
                                 rawDeltaX:(CGFloat)rawDeltaX
                                 rawDeltaY:(CGFloat)rawDeltaY
                                sentDeltaX:(short)sentDeltaX
                                sentDeltaY:(short)sentDeltaY
                                suppressed:(BOOL)suppressed {
    if (!self.inputDiagnosticsEnabled) {
        return;
    }

    BOOL rawNonZero = (rawDeltaX != 0.0 || rawDeltaY != 0.0);
    NSUInteger sequence = 0;

    @synchronized (self.inputDiagnosticsLock) {
        self.inputDiagnosticsMouseMoveEvents += 1;
        if (rawNonZero) {
            self.inputDiagnosticsNonZeroRelativeEvents += 1;
            self.inputDiagnosticsRawRelativeDeltaX += (NSInteger)llround(rawDeltaX);
            self.inputDiagnosticsRawRelativeDeltaY += (NSInteger)llround(rawDeltaY);
        }
        if (suppressed) {
            self.inputDiagnosticsSuppressedRelativeEvents += 1;
        } else if (sentDeltaX != 0 || sentDeltaY != 0) {
            self.inputDiagnosticsRelativeDispatches += 1;
            self.inputDiagnosticsSentRelativeDeltaX += sentDeltaX;
            self.inputDiagnosticsSentRelativeDeltaY += sentDeltaY;
            HIDIncrementInputDiagnosticsBucket(self.inputDiagnosticsRelativeMotionBySource, source);
        }
    }

    if ([self reserveDetailedInputDiagnosticsLogSequence:&sequence]) {
        Log(LOG_D, @"[inputdiag] #%lu %@ relative raw=(%.3f,%.3f) sent=(%d,%d) suppressed=%d ctx=%p",
            (unsigned long)sequence,
            source ?: @"unknown",
            rawDeltaX,
            rawDeltaY,
            sentDeltaX,
            sentDeltaY,
            suppressed ? 1 : 0,
            self.inputContext);
    }
}

- (void)recordAbsoluteInputDiagnosticsFrom:(NSString *)source
                                         x:(short)x
                                         y:(short)y
                                     width:(short)width
                                    height:(short)height {
    NSUInteger sequence = 0;
    BOOL diagnosticsEnabled = self.inputDiagnosticsEnabled;
    @synchronized (self.inputDiagnosticsLock) {
        self.lastAbsolutePointerHostX = x;
        self.lastAbsolutePointerHostY = y;
        self.lastAbsolutePointerReferenceWidth = width;
        self.lastAbsolutePointerReferenceHeight = height;
        self.lastAbsolutePointerAtMs = LiGetMillis();
        self.lastAbsolutePointerSource = [source copy];
        if (diagnosticsEnabled) {
            self.inputDiagnosticsMouseMoveEvents += 1;
            self.inputDiagnosticsAbsoluteDispatches += 1;
            HIDIncrementInputDiagnosticsBucket(self.inputDiagnosticsAbsoluteMotionBySource, source);
        }
    }

    if (diagnosticsEnabled && [self reserveDetailedInputDiagnosticsLogSequence:&sequence]) {
        Log(LOG_D, @"[inputdiag] #%lu %@ absolute pos=(%d,%d) ref=%dx%d ctx=%p",
            (unsigned long)sequence,
            source ?: @"unknown",
            x,
            y,
            width,
            height,
            self.inputContext);
    }
}

- (BOOL)getLastAbsolutePointerHostX:(short *)hostX
                              hostY:(short *)hostY
                     referenceWidth:(short *)referenceWidth
                    referenceHeight:(short *)referenceHeight
                              ageMs:(uint64_t *)ageMs
                             source:(NSString * __autoreleasing *)source {
    @synchronized (self.inputDiagnosticsLock) {
        if (self.lastAbsolutePointerAtMs == 0) {
            return NO;
        }

        if (hostX != NULL) {
            *hostX = self.lastAbsolutePointerHostX;
        }
        if (hostY != NULL) {
            *hostY = self.lastAbsolutePointerHostY;
        }
        if (referenceWidth != NULL) {
            *referenceWidth = self.lastAbsolutePointerReferenceWidth;
        }
        if (referenceHeight != NULL) {
            *referenceHeight = self.lastAbsolutePointerReferenceHeight;
        }
        if (ageMs != NULL) {
            uint64_t nowMs = LiGetMillis();
            *ageMs = nowMs >= self.lastAbsolutePointerAtMs ? (nowMs - self.lastAbsolutePointerAtMs) : 0;
        }
        if (source != NULL) {
            *source = [self.lastAbsolutePointerSource copy];
        }
        return YES;
    }
}

- (void)recordMouseButtonDiagnosticsAction:(NSString *)action
                                    button:(int)button
                                      mask:(uint32_t)mask
                                 synthetic:(BOOL)synthetic {
    if (!self.inputDiagnosticsEnabled) {
        return;
    }

    NSUInteger sequence = 0;
    if ([self reserveMouseButtonEdgeDiagnosticsLogSequence:&sequence]) {
        Log(LOG_D, @"[inputdiag] #%lu mouse-button action=%@ button=%d mask=0x%02X synthetic=%d ctx=%p",
            (unsigned long)sequence,
            action ?: @"unknown",
            button,
            (unsigned int)mask,
            synthetic ? 1 : 0,
            self.inputContext);
    }
}

// Mouse diagnostics use fields defined for mouse events. Undefined keyboard fields
// are not evidence of a physical key, even when they are only printed in a log.
- (void)logMouseEventDiagnosticsForEvent:(NSEvent *)event where:(NSString *)where {
    if (event == nil ||
        (event.type != NSEventTypeLeftMouseDown && event.type != NSEventTypeLeftMouseUp &&
         event.type != NSEventTypeRightMouseDown && event.type != NSEventTypeRightMouseUp &&
         event.type != NSEventTypeOtherMouseDown && event.type != NSEventTypeOtherMouseUp)) {
        return;
    }
    if (!self.inputDiagnosticsEnabled) {
        return;
    }
    Log(LOG_D, @"[inputdiag] mouse-button event where=%@ button=%ld clicks=%lu type=%ld timestamp=%.6f",
        where ?: @"unknown", (long)event.buttonNumber, (unsigned long)event.clickCount,
        (long)event.type, event.timestamp);
}

// Global key state cannot identify a device. Keep the optional state heuristic
// separate from the narrowly scoped device-attribution policy.
static BOOL HIDKeyboardHoldEnabled(void) {
    return [[NSUserDefaults standardUserDefaults] boolForKey:HIDKeyStateHoldEnabledDefault];
}

static BOOL HIDKeyboardHealEnabled(void) {
    return ![[NSUserDefaults standardUserDefaults] boolForKey:HIDKeyStateHealDisabledDefault];
}


// Conservative state-query allowlist. Navigation/function/media keys produced
// false negatives in the device capture, so neither quarantine nor orphan healing
// may infer their release from this global query. Their event pairs remain primary.
static BOOL HIDWireCodeIsKeyStateDetectable(short wireCode) {
    short vk = (short)(wireCode & 0xFF);
    if (vk >= 0x41 && vk <= 0x5A) {  // A-Z
        return YES;
    }
    if (vk >= 0x30 && vk <= 0x39) {  // 0-9 on the number row
        return YES;
    }
    if (vk >= 0x60 && vk <= 0x69) {  // numpad 0-9
        return YES;
    }
    switch (vk) {
        case 0x08:  // Backspace
        case 0x09:  // Tab
        case 0x0D:  // Return
        case 0x1B:  // Escape
        case 0x20:  // Space
        case 0xBA: case 0xBB: case 0xBC: case 0xBD:  // ; = , -
        case 0xBE: case 0xBF: case 0xC0:             // . / `
        case 0xDB: case 0xDC: case 0xDD: case 0xDE:  // [ \ ] '
            return YES;
        default:
            return NO;
    }
}

// Confirm unpaired C independently of a particular device or listen permission.
// Other keys retain the opted-in state check / device attribution policy.
// A known pointer-generated key is discarded, never translated into a second click.
- (BOOL)holdKeyboardPressIfUnconfirmedForKeyCode:(unsigned short)physicalKeyCode
                                        wireCode:(short)wireCode
                                       modifiers:(char)modifiers
                                       timestamp:(NSTimeInterval)timestamp {
    NSNumber *physical = @(physicalKeyCode);
    BOOL knownPointer = [self.keyboardQuirkFilter isKnownPointerKeyCode:physicalKeyCode timestamp:timestamp];
    BOOL quirk = [self.keyboardQuirkFilter shouldDeferKeyCode:physicalKeyCode timestamp:timestamp];
    BOOL unpairedC = physicalKeyCode == kVK_ANSI_C && !quirk;
    if ((!HIDKeyboardHoldEnabled() && !quirk && !unpairedC) || !HIDWireCodeIsKeyStateDetectable(wireCode)) {
        return NO;
    }
    if (!knownPointer && CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, (CGKeyCode)physicalKeyCode)) {
        return NO;
    }
    if (self.keyboardHeldUnconfirmedKeyDowns == nil) {
        self.keyboardHeldUnconfirmedKeyDowns = [NSMutableDictionary dictionary];
    }
    self.keyboardHeldUnconfirmedKeyDowns[physical] =
        @{@"wire": @(wireCode), @"mods": @(modifiers), @"at": @((unsigned long long)LiGetMillis()),
          @"timestamp": @(timestamp), @"quirk": @(quirk)};
    Log(LOG_D, @"[inputdiag] keyboard-wire held-unconfirmed kVK=%hu source-check=%d unpaired-c=%d", physicalKeyCode, quirk, unpairedC);
    return YES;
}

// A matched device report can reject a pending press. Missing source evidence is
// fail-open; the optional state heuristic is the only path allowed to expire closed.
- (void)settleHeldKeyboardPresses {
    if (!self.shouldSendInputEvents) {
        [self.keyboardHeldUnconfirmedKeyDowns removeAllObjects];
        return;
    }
    if (self.keyboardHeldUnconfirmedKeyDowns.count == 0) {
        return;
    }
    uint64_t nowMs = LiGetMillis();
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "settleHeldKeyboardPresses")) {
        return;
    }
    for (NSNumber *physicalKeyCode in self.keyboardHeldUnconfirmedKeyDowns.allKeys) {
        NSDictionary *held = self.keyboardHeldUnconfirmedKeyDowns[physicalKeyCode];
        unsigned short physical = physicalKeyCode.unsignedShortValue;
        uint64_t since = [held[@"at"] unsignedLongLongValue];
        uint64_t ageMs = nowMs >= since ? nowMs - since : 0;
        BOOL quirk = [held[@"quirk"] boolValue];
        BOOL pointerKey = quirk && [self.keyboardQuirkFilter isKnownPointerKeyCode:physical
                                                       timestamp:[held[@"timestamp"] doubleValue]];
        BOOL confirmed = CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, (CGKeyCode)physical);
        if (ageMs < HIDKeyStateHoldConfirmMs && (pointerKey || !confirmed)) {
            continue;
        }
        [self.keyboardHeldUnconfirmedKeyDowns removeObjectForKey:physicalKeyCode];
        // Device attribution fails open. The separately opted-in state heuristic keeps
        // its previous expiry policy, but never converts a keyboard edge into a click.
        if (pointerKey || (!quirk && !confirmed)) {
            if (self.keyboardSuppressedKeyDownKeyCodes == nil) {
                self.keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
            }
            [self.keyboardSuppressedKeyDownKeyCodes addObject:physicalKeyCode];
            Log(LOG_D, @"[inputdiag] keyboard-wire dropped-unconfirmed kVK=%hu pointer=%d", physical, pointerKey);
            continue;
        }
        short code = [held[@"wire"] shortValue];
        char modifiers = [held[@"mods"] charValue];
        BOOL alreadyOwned = [self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:@(code)];
        self.keyboardForwardedKeyDownKeyCodes[physicalKeyCode] = @(code);
        self.keyboardForwardedKeyDownAtMs[physicalKeyCode] = @(nowMs);
        if (!alreadyOwned) {
            HIDDispatchInput(self, inputLease, ^{
                Log(LOG_D, @"[inputdiag] keyboard-wire sent-down code=0x%hx mods=0x%hhx", (unsigned short)code, modifiers);
                LiSendKeyboardEventCtx(inputCtx, code, KEY_ACTION_DOWN, modifiers);
            });
        }
    }
}

- (void)healUnpairedForwardedKeyDowns {
    if (!self.shouldSendInputEvents) {
        [self.keyboardHeldUnconfirmedKeyDowns removeAllObjects];
        return;
    }
    [self settleHeldKeyboardPresses];
    if (!HIDKeyboardHealEnabled() || self.keyboardForwardedKeyDownKeyCodes.count == 0) {
        return;  // teardown owns that path, and it already releases every held key
    }
    uint64_t nowMs = LiGetMillis();
    NSMutableArray<NSNumber *> *orphaned = [NSMutableArray array];
    for (NSNumber *physicalKeyCode in self.keyboardForwardedKeyDownKeyCodes.allKeys) {
        NSNumber *sinceMs = self.keyboardForwardedKeyDownAtMs[physicalKeyCode];
        if (sinceMs == nil) {
            continue;
        }
        uint64_t ageMs = nowMs >= sinceMs.unsignedLongLongValue ? nowMs - sinceMs.unsignedLongLongValue : 0;
        if (ageMs < HIDKeyStateHealGraceMs) {
            continue;
        }
        unsigned short physical = (unsigned short)physicalKeyCode.unsignedShortValue;
        if (HIDIsModifierKeyCode(physical)) {
            continue;
        }
        if (!HIDWireCodeIsKeyStateDetectable([self.keyboardForwardedKeyDownKeyCodes[physicalKeyCode] shortValue])) {
            continue;
        }
        if (CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, (CGKeyCode)physical)) {
            continue;  // physically down: this press is held, not orphaned
        }
        [orphaned addObject:physicalKeyCode];
    }
    if (orphaned.count == 0) {
        return;
    }
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "healUnpairedForwardedKeyDowns")) {
        return;
    }
    for (NSNumber *physicalKeyCode in orphaned) {
        NSNumber *wireCode = self.keyboardForwardedKeyDownKeyCodes[physicalKeyCode];
        NSNumber *sinceMs = self.keyboardForwardedKeyDownAtMs[physicalKeyCode];
        if (wireCode == nil || sinceMs == nil) {
            continue;
        }
        uint64_t ageMs = nowMs >= sinceMs.unsignedLongLongValue ? nowMs - sinceMs.unsignedLongLongValue : 0;
        [self.keyboardForwardedKeyDownKeyCodes removeObjectForKey:physicalKeyCode];
        [self.keyboardForwardedKeyDownAtMs removeObjectForKey:physicalKeyCode];
        short code = wireCode.shortValue;
        if ([self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:wireCode]) {
            continue;
        }
        Log(LOG_D, @"[inputdiag] keyboard-wire healed kVK=%hu code=0x%hx age=%llums",
            (unsigned short)physicalKeyCode.unsignedShortValue, (unsigned short)code,
            (unsigned long long)ageMs);
        HIDDispatchInput(self, inputLease, ^{
            LiSendKeyboardEventCtx(inputCtx, code, KEY_ACTION_UP, 0);
        });
    }
}

- (void)startKeyboardStateHealTimerIfNeeded {
    @synchronized (self) {
        if (self.keyboardStateHealTimer != nil) {
            return;
        }
        dispatch_source_t timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0,
                                                         dispatch_get_main_queue());
        if (timer == NULL) {
            return;
        }
        dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * HIDKeyStateHealIntervalMs),
                                  NSEC_PER_MSEC * HIDKeyStateHealIntervalMs, NSEC_PER_MSEC * 5);
        __weak typeof(self) weakSelf = self;
        dispatch_source_set_event_handler(timer, ^{
            [weakSelf healUnpairedForwardedKeyDowns];
        });
        self.keyboardStateHealTimer = timer;  // strong: an ARC local source dies at scope exit
        dispatch_resume(timer);
    }
}

- (void)stopKeyboardStateHealTimer {
    @synchronized (self) {
        dispatch_source_t timer = self.keyboardStateHealTimer;
        if (timer == NULL) {
            return;
        }
        dispatch_source_cancel(timer);
        self.keyboardStateHealTimer = nil;
    }
}

- (void)recordScrollInputDiagnosticsMode:(NSString *)mode
                                 traceId:(uint64_t)traceId
                               rawDeltaX:(CGFloat)rawDeltaX
                               rawDeltaY:(CGFloat)rawDeltaY
                            rawWheelDeltaX:(NSInteger)rawWheelDeltaX
                            rawWheelDeltaY:(NSInteger)rawWheelDeltaY
                        normalizedDeltaX:(CGFloat)normalizedDeltaX
                        normalizedDeltaY:(CGFloat)normalizedDeltaY
                              continuous:(BOOL)continuous
                        hasPreciseDeltas:(BOOL)hasPreciseDeltas
                             lineDeltaX:(NSInteger)lineDeltaX
                             lineDeltaY:(NSInteger)lineDeltaY
                            pointDeltaX:(NSInteger)pointDeltaX
                            pointDeltaY:(NSInteger)pointDeltaY
                          fixedDeltaXRaw:(NSInteger)fixedDeltaXRaw
                          fixedDeltaYRaw:(NSInteger)fixedDeltaYRaw
                                   phase:(NSEventPhase)phase
                           momentumPhase:(NSEventPhase)momentumPhase
                              dispatchedX:(short)dispatchedX
                              dispatchedY:(short)dispatchedY {
    if (!self.inputDiagnosticsEnabled) {
        return;
    }

    uint64_t nowMs = LiGetMillis();
    uint64_t traceStartMs = 0;

    NSUInteger sequence = 0;
    BOOL shouldLog = NO;
    @synchronized (self.inputDiagnosticsLock) {
        if (self.inputDiagnosticsRemainingScrollDetailedLogs > 0) {
            self.inputDiagnosticsDetailedLogSequence += 1;
            self.inputDiagnosticsRemainingScrollDetailedLogs -= 1;
            sequence = self.inputDiagnosticsDetailedLogSequence;
            shouldLog = YES;
        }
        traceStartMs = self.activeScrollTraceStartedMs;
    }

    if (shouldLog) {
        uint64_t traceAgeMs = traceStartMs != 0 && nowMs >= traceStartMs ? nowMs - traceStartMs : 0;
        Log(LOG_D, @"[inputdiag] #%lu scroll trace=%llu ageMs=%llu mode=%@ raw=(%.3f,%.3f) rawWheel=(%ld,%ld) normalized=(%.3f,%.3f) dispatched=(%d,%d) continuous=%d precise=%d line=(%ld,%ld) point=(%ld,%ld) fixedRaw=(%ld,%ld) phase=%lu momentum=%lu ctx=%p",
            (unsigned long)sequence,
            (unsigned long long)traceId,
            (unsigned long long)traceAgeMs,
            mode ?: @"unknown",
            rawDeltaX,
            rawDeltaY,
            (long)rawWheelDeltaX,
            (long)rawWheelDeltaY,
            normalizedDeltaX,
            normalizedDeltaY,
            dispatchedX,
            dispatchedY,
            continuous ? 1 : 0,
            hasPreciseDeltas ? 1 : 0,
            (long)lineDeltaX,
            (long)lineDeltaY,
            (long)pointDeltaX,
            (long)pointDeltaY,
            (long)fixedDeltaXRaw,
            (long)fixedDeltaYRaw,
            (unsigned long)phase,
            (unsigned long)momentumPhase,
            self.inputContext);
    }
}

- (instancetype)init:(TemporaryHost *)host {
    self = [super init];
    if (self) {
        self.host = host;
        self.inputContextLock = [[NSObject alloc] init];
        self.inputQueue = dispatch_queue_create("com.moonlight.input", DISPATCH_QUEUE_SERIAL);
        dispatch_queue_set_specific(self.inputQueue, HIDInputQueueSpecificKey, (__bridge void *)self, NULL);
        self.freeMouseVirtualCursorLock = [[NSObject alloc] init];
        self.mouseDeltaAccumulator = [[HIDMouseDeltaAccumulator alloc] init];
        self.freeMouseVirtualCursorGainX = 1.0;
        self.freeMouseVirtualCursorGainY = 1.0;
        self.inputDiagnosticsLock = [[NSObject alloc] init];
        self.pressedMouseButtonsMask = 0;
        // The held-key record has to exist before the first keyDown: sending a
        // message to nil drops the record silently, which is the same stuck-key
        // bug this table exists to prevent, just quieter.
        self.keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        self.keyboardForwardedKeyDownAtMs = [NSMutableDictionary dictionary];
        self.keyboardHeldUnconfirmedKeyDowns = [NSMutableDictionary dictionary];
        self.keyboardQuirkFilter = [[HIDKeyboardQuirkFilter alloc] init];
        self.keyboardCapsLockState = @(([NSEvent modifierFlags] & NSEventModifierFlagCapsLock) != 0);
        [self resetInputDiagnostics];

        // Report the actual per-host mapping used by physical and synthetic keys.
        KMR_LogActiveMapping([self commandKeyPreferenceForCurrentHost]);
        Log(LOG_I, @"[kbmap] HIDSupport init: Mode = Streaming Standard (Cmd->%@, Ctrl->Ctrl, Option->Alt)",
            [self commandKeyPreferenceForCurrentHost] == KMR_CommandPreferenceControl ? @"Ctrl" : @"Win");

        [self setupHidManager];
        
        self.ticks = [[Ticks alloc] init];
        self.switchUsingBluetooth = YES;

        // Inactive pointer source until a physical pad requests mouse mode.
        self.controller = [[Controller alloc] init];

        [self rumbleSync];

        for (GCMouse *mouse in GCMouse.mice) {
            [self registerMouseCallbacks:mouse];
        }
        
        __weak typeof(self) weakSelf = self;
        self.mouseConnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidConnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification * _Nonnull note) {
            [weakSelf registerMouseCallbacks:note.object];
        }];
        self.mouseDisconnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidDisconnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification * _Nonnull note) {
            [weakSelf unregisterMouseCallbacks:note.object];
        }];
        
        NSMutableDictionary *d = [NSMutableDictionary dictionary];
        for (size_t i = 0; i < sizeof(keys) / sizeof(struct KeyMapping); i++) {
            struct KeyMapping m = keys[i];
            [d setObject:@(m.windows) forKey:@(m.mac)];
        }
        _mappings = [NSDictionary dictionaryWithDictionary:d];
        
        [self initializeDisplayLink];
        [self setupCoreHIDMouseDriverIfNeeded];
    }
    return self;
}

- (void)dealloc {
    [self stopKeyboardStateHealTimer];
    if (_mouseConnectObserver != nil) [[NSNotificationCenter defaultCenter] removeObserver:_mouseConnectObserver];
    if (_mouseDisconnectObserver != nil) [[NSNotificationCenter defaultCenter] removeObserver:_mouseDisconnectObserver];
    [self tearDownCoreHIDMouseDriver];
    // The display link is the same shape of object as the manager below: a CoreFoundation
    // reference that an assign property does not own, and a C callback whose context is
    // this object. It is worse in one respect -- that callback runs on the display link's
    // own thread and turns its context straight back into a strong reference without
    // asking whether anybody still holds the object. The stream paths stop it through
    // tearDownHidManager before dropping their reference, which leaves this NULL; this is
    // the net for every other path. It is not a thread-safety proof: what keeps the
    // callback honest is that the teardown happens before the last release, and today
    // every path that drops an HIDSupport goes through that teardown first.
    if (_displayLink != NULL) {
        CVDisplayLinkStop(_displayLink);
        CVDisplayLinkRelease(_displayLink);
        _displayLink = NULL;
    }

    // The manager is a CoreFoundation reference that this object owns by hand:
    // clang does not manage a CF typed property, so nothing releases it when we
    // go away. Leaving it alive is worse than the leak, because it is scheduled
    // on the main run loop with four callbacks whose context is this object, and
    // the next gamepad event would message freed memory. The streaming paths call
    // tearDownHidManager before dropping their reference, which leaves this NULL
    // and therefore does nothing; this is the net for every other path.
    if (_hidManager != NULL) {
        IOHIDManagerUnscheduleFromRunLoop(_hidManager, CFRunLoopGetMain(), kCFRunLoopDefaultMode);
        IOHIDManagerClose(_hidManager, kIOHIDOptionsTypeNone);
        CFRelease(_hidManager);
        _hidManager = NULL;
    }
    NSLog(@"HIDSupport dealloc");
}


// M1: what the arrival event tells the host this pad is. The mapping is the
// same table the report prints (one owner, no second id list), and it is only a
// local candidate until the host answers: the report says so.
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)device {
    if (isPlayStation(device)) {
        return LI_CTYPE_PS;
    }
    if (isNintendo(device)) {
        return LI_CTYPE_NINTENDO;
    }
    return LI_CTYPE_XBOX;
}

// M1: the capabilities an arriving pad claims. Only what the HID path can back
// with a real write: analog triggers (the trigger axes above) and rumble (the
// +Rumble.m write path). ACCEL/GYRO/TOUCHPAD/BATTERY/RGB stay unclaimed until
// M3/M4 implement them, because a claimed capability is a promise the host
// will keep trying to use.
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;

// The buttons every layout this path reads can actually produce: the face and
// shoulder buttons, the menu pair, the stick clicks and the D-pad. The arrival
// event carries them so the host knows what the emulated gamepad has; a flag
// the HID path never sets (paddles, touchpad) is not one the host should draw.
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)device {
    (void)device;
    return A_FLAG | B_FLAG | X_FLAG | Y_FLAG | LB_FLAG | RB_FLAG |
           PLAY_FLAG | BACK_FLAG | SPECIAL_FLAG | LS_CLK_FLAG | RS_CLK_FLAG |
           UP_FLAG | DOWN_FLAG | LEFT_FLAG | RIGHT_FLAG;
}

// M1: tell the host a pad exists, with the type and capabilities it actually
// has. The event goes out on the input queue next to the pad's own events, so
// it lands in order with them, and it doubles as the fallback multi-controller
// event the C library sends on hosts without arrival support.
- (void)sendControllerArrivalForEntry:(HIDDeviceControllerEntry *)entry {
    // P2-3b: arrival must honour suspendControllerEvents the same way the
    // axis / button / motion / touch / battery paths do -- the host should
    // not learn about a pad while the player has stepped away from the app.
    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents) return;
    int playerIndex = entry.playerIndex;
    int mask = [self activeDeviceMask];
    uint8_t protocolType = entry.protocolType;
    uint32_t buttons = entry.supportedButtonFlags;
    uint16_t capabilities = entry.capabilities;
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (inputCtx == NULL) {
        return;
    }
    HIDDispatchInput(self, inputLease, ^{
        // The lease consumer has validated initialization and context lifetime.
        // A successful C return means accepted by its queue, not host receipt.
        if (entry.advertisedInputGeneration == inputLease.generation) return;
        int result = LiSendControllerArrivalEventCtx(inputCtx, (uint8_t)playerIndex,
                                                     (uint16_t)mask, protocolType,
                                                     buttons, capabilities);
        if (result != 0) return;
        entry.advertisedInputGeneration = inputLease.generation;
        dispatch_async(dispatch_get_main_queue(), ^{
            HIDInputLease current = HIDAcquireInputContext(self);
            if (current.context != inputLease.context ||
                current.generation != inputLease.generation ||
                ![self.deviceControllerTable.allValues containsObject:entry]) return;
            entry.advertisedToHost = YES;
            [MLControllerInventory.sharedInventory noteControllerArrival:playerIndex
                                                           protocolType:protocolType];
        });
    });
}

// The mask bitfield the protocol wants on every controller event: one bit per
// pad still connected. Computed from the table at send time, so a removal
// between two events changes the mask without a second bookkeeping store.
- (int)activeDeviceMask {
    int mask = 0;
    for (HIDDeviceControllerEntry *entry in [self deviceControllerTable].allValues) {
        mask |= 1 << entry.playerIndex;
    }
    return mask;
}

// Sends one entry's controller to the host as its own active controller:
// playerIndex and the mask bit both come from the entry's player slot. With a
// single pad that is exactly the tuple the old shared path sent (slot 0, mask 1),
// which is what keeps the 0.2 wire baseline byte-for-byte intact.
- (void)sendControllerEventForEntry:(HIDDeviceControllerEntry *)entry {
    // The wire tuple has one owner, ControllerEventBaselineFromController: 0.2 is
    // allowed to change how this is called per device, not what is sent. The
    // baseline gate (scripts/controller-event-baseline.py) replays the exact
    // tuple the old inline code sent and refuses any drift on this path.
    entry.controller.playerIndex = entry.playerIndex;
    ControllerWireEvent wireEvent;
    if (!ControllerEventBaselineFromController(entry.controller, self.shouldSendInputEvents, &wireEvent)) {
        return;
    }

    HIDInputLease inputLease = HIDAcquireInputContext(self);

    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!inputCtx) {
        return;
    }
    // The owner computed the single-pad tuple (mask 1); the per-device layer
    // widens it to the full active set, so every pad's event names every pad
    // still connected. With one pad that is the original mask 1, which is the
    // case the baseline gate pins.
    wireEvent.mask = [self activeDeviceMask];
    HIDDispatchInput(self, inputLease, ^{
        LiSendMultiControllerEventCtx(inputCtx, wireEvent.playerIndex, wireEvent.mask, wireEvent.buttons,
                                      wireEvent.leftTrigger, wireEvent.rightTrigger,
                                      wireEvent.leftStickX, wireEvent.leftStickY,
                                      wireEvent.rightStickX, wireEvent.rightStickY);
    });
}

- (void)sendControllerNeutralEventForEntry:(HIDDeviceControllerEntry *)entry {
    // P2-3b: the neutral frame is part of the same wire path as axis/button
    // updates, so it follows the same focus-loss suspension.
    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents) return;
    int playerIndex = entry.playerIndex;
    int mask = [self activeDeviceMask];
    HIDInputLease lease = HIDAcquireInputContext(self);
    if (lease.context == NULL) return;
    HIDDispatchInput(self, lease, ^{
        LiSendMultiControllerEventCtx(lease.context, playerIndex, mask, 0, 0, 0, 0, 0, 0, 0);
    });
}

- (void)setControllerMouseMode:(BOOL)enabled forEntry:(HIDDeviceControllerEntry *)entry {
    if (entry == nil) return;
    @synchronized (self) {
        if (enabled == entry.controller.isMouseMode) return;
        [self releaseMouseButtonsForSource:@"hid-controller"];
        if (enabled) {
            HIDDeviceControllerEntry *previous = self.mouseModeEntry;
            previous.controller.isMouseMode = NO;
            if (previous != nil && previous != entry) {
                [self sendControllerEventForEntry:previous];
            }
            // Keep the slot connected, but release its remote held state before
            // mouse mode starts suppressing ordinary gamepad packets.
            [self sendControllerNeutralEventForEntry:entry];
            entry.controller.isMouseMode = YES;
            self.mouseModeEntry = entry;
            self.controller = entry.controller;
        } else {
            entry.controller.isMouseMode = NO;
            if (self.mouseModeEntry == entry) self.mouseModeEntry = nil;
        }
        self.mouseEmulationResidualX = 0;
        self.mouseEmulationResidualY = 0;
        BOOL active = self.mouseModeEntry != nil;
        dispatch_async(dispatch_get_main_queue(), ^{
            [[NSNotificationCenter defaultCenter]
                postNotificationName:HIDMouseModeToggledNotification object:nil
                userInfo:@{@"enabled": @(active)}];
        });
    }
}

// M1: removal sends an empty event for the gone pad with the refreshed mask,
// which is the protocol's "this slot is free now".
- (void)sendControllerRemovalForEntry:(HIDDeviceControllerEntry *)entry {
    if (entry == nil || self.controllerDriver != 0) return;
    int playerIndex = entry.playerIndex;
    int mask = [self activeDeviceMask];
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (inputCtx == NULL) {
        return;
    }
    HIDDispatchInput(self, inputLease, ^{
        // A state packet may have succeeded even when arrival failed.
        // Clearing the removed slot is idempotent and must not depend on arrival.
        LiSendMultiControllerEventCtx(inputCtx, playerIndex, mask, 0, 0, 0, 0, 0, 0, 0);
    });
}

- (void)sendControllerEvent {
    // 0.2: fan out one event per connected pad, in slot order. With zero or one
    // pad this is the old path exactly; with several, each pad keeps its own
    // state instead of overwriting the shared one.
    NSMutableArray<HIDDeviceControllerEntry *> *entries =
        [[self deviceControllerTable] allValues].mutableCopy;
    [entries sortUsingComparator:^NSComparisonResult(HIDDeviceControllerEntry *a, HIDDeviceControllerEntry *b) {
        return [@(a.playerIndex) compare:@(b.playerIndex)];
    }];
    for (HIDDeviceControllerEntry *entry in entries) {
        [self sendControllerEventForEntry:entry];
    }
}

- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event {
    // Gate at the door, not at the caller: -keyCode is undefined on the mouse, tablet and
    // gesture events a stream view also receives, and some drivers leave a value there that
    // collides with a real kVK_ANSI_* code. The one caller today hands this a flagsChanged,
    // and the audit (scripts/key-code-read-site-audit.py) refuses a reader that asks a
    // helper to have remembered to check.
    if (event == nil || (event.type != NSEventTypeKeyDown && event.type != NSEventTypeKeyUp &&
                         event.type != NSEventTypeFlagsChanged)) {
        return;
    }

    HIDKeyboardPhysicalModifierMask mask = HIDPhysicalModifierMaskForKeyCode(event.keyCode);
    NSEventModifierFlags modifierFlag = HIDModifierFlagForKeyCode(event.keyCode);
    if (mask == 0 || modifierFlag == 0) {
        return;
    }

    BOOL pressed;
    NSEventModifierFlags deviceMask =
        HIDDeviceModifierMaskForKeyCode(event.keyCode);
    if (deviceMask != 0 &&
        HIDEventCarriesDeviceModifierState(event.modifierFlags)) {
        // Ask about the key the event names, not about its family.
        pressed = (event.modifierFlags & deviceMask) != 0;
    } else {
        pressed = (event.modifierFlags & modifierFlag) != 0;
    }
    if (pressed) {
        self.keyboardPhysicalModifierSourceMask |= mask;
    } else {
        self.keyboardPhysicalModifierSourceMask &= ~mask;
    }
}

- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event {
    // SIMPLIFIED: Iterate over physical modifiers and map directly.
    NSUInteger physical = HIDEffectivePhysicalModifierMaskForEvent(self.keyboardPhysicalModifierSourceMask, event);
    if (physical == 0) {
        return 0;
    }

    static const struct {
        NSUInteger  physMask;
        KMR_PhysicalModifier physEnum;
    } kMap[] = {
        { HIDKeyboardPhysicalModifierMaskLeftShift,    KMR_Phys_LeftShift },
        { HIDKeyboardPhysicalModifierMaskRightShift,   KMR_Phys_RightShift },
        { HIDKeyboardPhysicalModifierMaskLeftControl,  KMR_Phys_LeftControl },
        { HIDKeyboardPhysicalModifierMaskRightControl, KMR_Phys_RightControl },
        { HIDKeyboardPhysicalModifierMaskLeftOption,   KMR_Phys_LeftOption },
        { HIDKeyboardPhysicalModifierMaskRightOption,  KMR_Phys_RightOption },
        { HIDKeyboardPhysicalModifierMaskLeftCommand,  KMR_Phys_LeftCommand },
        { HIDKeyboardPhysicalModifierMaskRightCommand, KMR_Phys_RightCommand },
    };

    NSUInteger desired = 0;
    KMR_CommandPreference commandPref = [self commandKeyPreferenceForCurrentHost];
    for (size_t i = 0; i < sizeof(kMap) / sizeof(kMap[0]); i++) {
        if ((physical & kMap[i].physMask) == 0) {
            continue;
        }
        desired |= (NSUInteger)KMR_RemoteMaskForPhysicalWithCommandPreference(kMap[i].physEnum,
                                                                             commandPref);
    }
    // Under the Control preference a player holding both Control and Command lands on one
    // bit here rather than two. That is the behaviour to keep: the bit already went down
    // when the first of the two arrived, so releasing either one leaves the other held,
    // while a second bit would let the first release take the key away mid-chord.
    return desired;
}

- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {
    NSUInteger previous = self.keyboardRemoteModifierMask;
    NSUInteger desired = [self desiredRemoteKeyboardModifierMaskForEvent:event];
    NSUInteger changed = previous ^ desired;
    if (changed == 0) {
        return;
    }

    char modifiers = HIDRemoteModifierFlagsToGenericFlags(desired);
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!inputCtx) {
        self.keyboardRemoteModifierMask = desired;
        return;
    }

    static const HIDKeyboardRemoteModifierMask remoteOrder[] = {
        HIDKeyboardRemoteModifierMaskLeftShift,
        HIDKeyboardRemoteModifierMaskRightShift,
        HIDKeyboardRemoteModifierMaskLeftControl,
        HIDKeyboardRemoteModifierMaskRightControl,
        HIDKeyboardRemoteModifierMaskLeftAlt,
        HIDKeyboardRemoteModifierMaskRightAlt,
        HIDKeyboardRemoteModifierMaskLeftMeta,
        HIDKeyboardRemoteModifierMaskRightMeta,
    };

    self.keyboardRemoteModifierMask = desired;
    HIDDispatchInput(self, inputLease, ^{
        for (NSUInteger i = 0; i < sizeof(remoteOrder) / sizeof(remoteOrder[0]); i++) {
            HIDKeyboardRemoteModifierMask mask = remoteOrder[i];
            if ((changed & mask) == 0) {
                continue;
            }

            unsigned short keyCode = HIDRemoteModifierKeyCode(mask);
            if (keyCode == 0) {
                continue;
            }

            char action = (desired & mask) != 0 ? KEY_ACTION_DOWN : KEY_ACTION_UP;
            LiSendKeyboardEventCtx(inputCtx, keyCode, action, modifiers);
        }
    });
}

- (void)refreshKeyboardModifiersForCapture {
    if (!self.shouldSendInputEvents) return;
    // Caps Lock can toggle while another application owns focus, with no event
    // delivered here. Refresh the baseline without replaying that local toggle.
    self.keyboardCapsLockState = @(([NSEvent modifierFlags] & NSEventModifierFlagCapsLock) != 0);
    // The responder does not see releases while another application owns focus.
    // Reconcile once at capture, preserving left/right identity without reading
    // keyboard-only fields from the mouse event that activated the window.
    static const unsigned short keys[] = {
        kVK_Shift, kVK_RightShift, kVK_Control, kVK_RightControl,
        kVK_Option, kVK_RightOption, kVK_Command, kVK_RightCommand
    };
    NSUInteger physical = 0;
    for (NSUInteger i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
        if (CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, keys[i])) {
            physical |= HIDPhysicalModifierMaskForKeyCode(keys[i]);
        }
    }
    self.keyboardPhysicalModifierSourceMask = physical;
    [self syncKeyboardModifierStateForEvent:nil];
}

- (void)flagsChanged:(NSEvent *)event {
    // Hard gate: reject any non-keyboard event before touching keyCode.
    // Mouse/tablet/gesture events have UNDEFINED -keyCode on macOS.
    if (event == nil || event.type != NSEventTypeFlagsChanged) {
        return;
    }

    // What the player is physically holding is recorded whether or not this
    // particular event can be forwarded. A modifier that came down while the
    // embedded settings page had the keyboard is still down when the player
    // comes back, and the record made here is the only thing that will ever
    // tell the host about it: skip the record along with the send and sprinting
    // becomes walking for as long as the finger stays down. The release that
    // follows is gated the same way, so the whole press is silent -- which is
    // why no log ever mentioned it.
    //
    // Recording early cannot press anything the host never saw. -sync: only
    // fires on the difference between what was sent and what is wanted, and
    // while forwarding is off nothing is sent, so a modifier that arrived and
    // left behind the door nets to zero. -releaseAllModifierKeys zeroes the
    // physical and remote records together, so no path inherits a modifier
    // that was only ever recorded locally.
    // Caps Lock is delivered as flagsChanged, never as an ordinary key pair.
    // Remember the local toggle even while uncaptured; duplicate state reports
    // must not toggle the host twice.
    if (event.keyCode == kVK_CapsLock) {
        NSNumber *state = @((event.modifierFlags & NSEventModifierFlagCapsLock) != 0);
        BOOL changed = ![self.keyboardCapsLockState isEqual:state];
        self.keyboardCapsLockState = state;
        if (changed && self.shouldSendInputEvents) {
            [self syncKeyboardModifierStateForEvent:event];
            HIDInputLease lease = HIDAcquireInputContext(self);
            char lockModifiers = [self translateKeyModifierWithEvent:event];
            HIDDispatchInput(self, lease, ^{
                LiSendKeyboardEventCtx(lease.context, (short)0x8014, KEY_ACTION_DOWN, lockModifiers);
                LiSendKeyboardEventCtx(lease.context, (short)0x8014, KEY_ACTION_UP, lockModifiers);
            });
        }
        return;
    }

    [self updateKeyboardPhysicalModifierStateFromEvent:event];

    if (!self.shouldSendInputEvents) {
        return;
    }

    [self syncKeyboardModifierStateForEvent:event];
}

- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyDown) {
        return;
    }
    NSNumber *physical = @(event.keyCode);
    // A local consumer may take an auto-repeat, but it cannot take ownership of
    // the original press or suppress the release owed for that press.
    if (self.keyboardForwardedKeyDownKeyCodes[physical] != nil ||
        self.keyboardHeldUnconfirmedKeyDowns[physical] != nil) {
        return;
    }
    if (self.keyboardSuppressedKeyDownKeyCodes == nil) {
        self.keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
    }
    [self.keyboardSuppressedKeyDownKeyCodes addObject:physical];
}

- (void)keyDown:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyDown || !self.shouldSendInputEvents) {
        return;
    }
    NSNumber *physical = @(event.keyCode);
    NSNumber *savedCode = self.keyboardForwardedKeyDownKeyCodes[physical];
    Log(LOG_D, @"[inputdiag] keyboard-wire down kVK=%hu repeat=%d", event.keyCode, event.isARepeat);
    if (savedCode != nil && !event.isARepeat) {
        return; // A second delivery of the same physical edge is not a new press.
    }
    if (self.keyboardHeldUnconfirmedKeyDowns[physical] != nil) {
        return; // Repeats cannot restart the confirmation deadline.
    }
    if (event.isARepeat && savedCode == nil) {
        return; // Capture ended or a local consumer owns this press.
    }
    [self.keyboardSuppressedKeyDownKeyCodes removeObject:physical];
    [self syncKeyboardModifierStateForEvent:event];
    short translated = savedCode != nil ? savedCode.shortValue : [self translateKeyCodeWithEvent:event];
    NSData *committed = savedCode == nil ? HIDUnicodeTextForEvent(event) : nil;
    if (committed != nil && committed.length > 0) {
        // Text owns this edge; no key-code DOWN or orphan UP accompanies it.
        // An existing wire-key owner always keeps its original route.
        HIDInputLease textLease = HIDAcquireInputContext(self);
        PML_INPUT_STREAM_CONTEXT textCtx = textLease.context;
        if (HIDValidateInputContext(textCtx, "keyDown")) {
            HIDDispatchInput(self, textLease, ^{
                // Capture the data, not a pointer into an object released
                // before this queued block runs.
                LiSendUtf8TextEventCtx(textCtx, committed.bytes, (unsigned int)committed.length);
            });
        }
        return;
    }
    if (translated == 0) {
        return;
    }
    short keyCode = (short)(0x8000 | translated);
    char modifiers = [self translateKeyModifierWithEvent:event];
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "keyDown")) {
        return;
    }
    if (savedCode == nil && [self holdKeyboardPressIfUnconfirmedForKeyCode:event.keyCode
                                                                wireCode:keyCode
                                                               modifiers:modifiers
                                                               timestamp:event.timestamp]) {
        return;
    }
    BOOL alreadyOwned = [self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:@(keyCode)];
    self.keyboardForwardedKeyDownKeyCodes[physical] = @(keyCode);
    if (savedCode == nil) {
        self.keyboardForwardedKeyDownAtMs[physical] = @((unsigned long long)LiGetMillis());
    }
    if (alreadyOwned && !event.isARepeat) {
        return; // Another physical key owns this VK (for example keypad Enter).
    }
    HIDDispatchInput(self, inputLease, ^{
        Log(LOG_D, @"[inputdiag] keyboard-wire sent-down code=0x%hx mods=0x%hhx", (unsigned short)keyCode, modifiers);
        LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
    });
}

- (void)keyUp:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyUp) {
        return;
    }
    Log(LOG_D, @"[inputdiag] keyboard-wire up kVK=%hu send=%d", event.keyCode, self.shouldSendInputEvents);
    NSNumber *physical = @(event.keyCode);
    NSDictionary *pending = self.keyboardHeldUnconfirmedKeyDowns[physical];
    NSNumber *savedCode = self.keyboardForwardedKeyDownKeyCodes[physical];
    [self.keyboardHeldUnconfirmedKeyDowns removeObjectForKey:physical];
    [self.keyboardSuppressedKeyDownKeyCodes removeObject:physical];
    [self.keyboardForwardedKeyDownKeyCodes removeObjectForKey:physical];
    [self.keyboardForwardedKeyDownAtMs removeObjectForKey:physical];
    if (!self.shouldSendInputEvents || (savedCode == nil && pending == nil)) {
        Log(LOG_D, @"[inputdiag] keyboard-wire up-swallowed kVK=%hu", event.keyCode);
        // No matching forwarded press: no orphan UP reaches the host.
        return;
    }
    [self syncKeyboardModifierStateForEvent:event];
    short keyCode = savedCode != nil ? savedCode.shortValue : [pending[@"wire"] shortValue];
    if ([self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:@(keyCode)]) {
        return; // The remaining owner still holds this remote key.
    }
    char modifiers = [self translateKeyModifierWithEvent:event];
    char pressModifiers = pending != nil ? [pending[@"mods"] charValue] : modifiers;
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "keyUp")) {
        return;
    }
    HIDDispatchInput(self, inputLease, ^{
        // A real release confirms a quick tap before the state poll could see it.
        // Keep both edges in one queue item so teardown cannot split the pair.
        if (pending != nil && savedCode == nil) {
            Log(LOG_D, @"[inputdiag] keyboard-wire sent-down code=0x%hx mods=0x%hhx", (unsigned short)keyCode, pressModifiers);
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, pressModifiers);
        }
        Log(LOG_D, @"[inputdiag] keyboard-wire sent-up code=0x%hx mods=0x%hhx", (unsigned short)keyCode, modifiers);
        LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_UP, modifiers);
    });
}

- (void)releaseAllModifierKeys {
    // Reentry guard: if already inside a modifier release (which can
    // happen when tearDownKeyboardStateForSessionEnd -> releaseAllButtons
    // -> releaseAllModifierKeys, or during stream teardown when multiple
    // teardown paths all call releaseAllModifierKeys), bail immediately
    // to avoid a self-reentrant HIDDispatchInput deadlock.
    if (self.keyboardModifierReleaseInProgress) {
        return;
    }
    self.keyboardModifierReleaseInProgress = YES;

    // Local masks are zeroed FIRST, so any concurrent flagsChanged: /
    // keyDown: racing past the shouldSendInputEvents gate can't add
    // back modifier bits before we send the UP events.
    self.keyboardPhysicalModifierSourceMask = 0;
    self.keyboardRemoteModifierMask = 0;

    HIDInputLease inputLease = HIDAcquireInputContext(self);

    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!inputCtx) {
        self.keyboardModifierReleaseInProgress = NO;
        return;
    }
    HIDDispatchInput(self, inputLease, ^{
        LiSendKeyboardEventCtx(inputCtx, 0x5B, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0x5C, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA0, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA1, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA2, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA3, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA4, KEY_ACTION_UP, 0);
        LiSendKeyboardEventCtx(inputCtx, 0xA5, KEY_ACTION_UP, 0);
    });

    self.keyboardModifierReleaseInProgress = NO;
}

- (void)releaseRemoteModifierKeysForUncapture {
    // Input forwarding is about to switch off, and flagsChanged: stops
    // reaching the sync once it has. A modifier the host was told about and
    // the player later lets go of therefore never comes up on the host: it
    // waits there until the next keyboard event, and every pointer click in
    // between carries a modifier nobody is holding. The pointer was handed
    // back, so the modifiers go back with it, for the same reason
    // -releaseAllHeldKeys is called there.
    if (self.keyboardRemoteModifierMask == 0 ||
        self.keyboardModifierReleaseInProgress) {
        return;
    }

    // What must not go back is the physical tracker, because it records the
    // player's fingers and not the host's state. A player who triggers this
    // while sprinting on Shift has to be sprinting again after recapture:
    // the remote record is empty and the desired mask is not, so the first
    // keyboard event re-presses the modifier before it sends that key. A
    // modifier let go of behind the door stays released, because
    // flagsChanged: updates the physical tracker whether or not the event
    // can be forwarded.
    // The eight packets, the reentry guard and the send-before-record order
    // belong to -releaseAllModifierKeys. Only what it also does to the
    // physical tracker is unwanted here, so that one value is put back
    // afterwards.
    HIDKeyboardPhysicalModifierMask heldPhysical =
        self.keyboardPhysicalModifierSourceMask;
    [self releaseAllModifierKeys];
    self.keyboardPhysicalModifierSourceMask = heldPhysical;
}

- (void)releaseAllHeldKeys {
    if (self.keyboardHeldKeyReleaseInProgress) {
        return;
    }
    self.keyboardHeldKeyReleaseInProgress = YES;
    [self.keyboardHeldUnconfirmedKeyDowns removeAllObjects];
    NSArray<NSNumber *> *held = [NSSet setWithArray:self.keyboardForwardedKeyDownKeyCodes.allValues ?: @[]].allObjects;
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    [self.keyboardForwardedKeyDownAtMs removeAllObjects];
    if (held.count > 0) {
        HIDInputLease inputLease = HIDAcquireInputContext(self);
        PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
        if (HIDValidateInputContext(inputCtx, "releaseAllHeldKeys")) {
            HIDDispatchInput(self, inputLease, ^{
                for (NSNumber *keyCode in held) {
                    LiSendKeyboardEventCtx(inputCtx, keyCode.shortValue, KEY_ACTION_UP, 0);
                }
            });
        }
    }
    self.keyboardHeldKeyReleaseInProgress = NO;
}

- (void)tearDownKeyboardStateForSessionEnd:(const char *)reason {
    // Idempotency gate. Five teardown paths all want to call this function:
    //   1. performCloseStreamWindow (user hit the disconnect shortcut)
    //   2. performCloseAndQuitApp   (user hit quit-app shortcut)
    //   3. connectionTerminated     (common-c says connection is gone)
    //   4. windowWillClose          (OS closes the stream window)
    //   5. stageFailed/launchFailed (stream never got off the ground)
    // Without the gate they can race on the main queue and stampede
    // releaseAllModifierKeys, HID teardown, and window close logic.
    if (self.keyboardTeardownAlreadyCalled) {
        Log(LOG_I, @"[teardown] tearDownKeyboardStateForSessionEnd[%s]: skipped (already called, hadReleased=%d)",
            reason ?: "",
            self.keyboardModifierReleaseInProgress ? 1 : 0);
        return;
    }
    self.keyboardTeardownAlreadyCalled = YES;
    self.shouldSendInputEvents = NO;
    [self stopKeyboardStateHealTimer];
    [self.keyboardQuirkFilter stop];
    [self.keyboardHeldUnconfirmedKeyDowns removeAllObjects];
    [self.keyboardSuppressedKeyDownKeyCodes removeAllObjects];
    Log(LOG_I, @"[teardown] tearDownKeyboardStateForSessionEnd[%s]: start (physicalMask=0x%lx remoteMask=0x%lx send=%d)",
        reason ?: "",
        (unsigned long)self.keyboardPhysicalModifierSourceMask,
        (unsigned long)self.keyboardRemoteModifierMask,
        self.shouldSendInputEvents ? 1 : 0);

    // Return owned keys while the context is attached, even though admission
    // is already closed. Cleanup does not depend on ordinary event forwarding.
    [self releaseAllHeldKeys];

    // 1) Release remote modifier state FIRST, while inputContext may still
    //    be valid. This sends 8 KEY_ACTION_UP packets so the remote PC
    //    never ends a session with a stuck Win/Ctrl/Alt/Shift key.
    [self releaseAllModifierKeys];

    // Return shared button ownership after keyboard state.
    [self releaseAllPressedMouseButtons];

    Log(LOG_I, @"[teardown] tearDownKeyboardStateForSessionEnd[%s]: done", reason ?: "");
}

- (void)sendSyntheticRemoteModifierTapForFlags:(NSEventModifierFlags)modifierFlags {
    // SIMPLIFIED: Use the standard streaming mapping.
    NSEventModifierFlags relevantFlags = [StreamShortcutProfile relevantModifierFlags:modifierFlags];
    NSUInteger remoteModifierMask = (NSUInteger)KMR_RemoteMaskForAppKitFlagsWithCommandPreference(
        relevantFlags, [self commandKeyPreferenceForCurrentHost]);
    HIDDispatchSyntheticRemoteModifierTap(self, remoteModifierMask, "sendSyntheticRemoteModifierTapForFlags");
}

- (void)sendSyntheticRemoteModifierTapForKeyCode:(unsigned short)keyCode
            preferShortcutTranslationCommandMapping:(BOOL)preferShortcutTranslationCommandMapping {
    NSUInteger remoteModifierMask =
        HIDSyntheticRemoteModifierMaskForKeyCode(self, keyCode, preferShortcutTranslationCommandMapping);
    HIDDispatchSyntheticRemoteModifierTap(self,
                                          remoteModifierMask,
                                          "sendSyntheticRemoteModifierTapForKeyCode");
}

- (void)sendSyntheticRemoteShortcut:(StreamShortcut *)shortcut {
    if (shortcut == nil || shortcut.modifierOnly || shortcut.keyCode == StreamShortcut.noKeyCode) {
        return;
    }

    // The one path that puts a key on the wire without a key event behind it, so it
    // belongs on the same record as the edges that came from hardware.
    Log(LOG_D, @"[inputdiag] keyboard-wire synthetic kVK=%hu", shortcut.keyCode);

    NSNumber *mappedKey = [self.mappings objectForKey:@(shortcut.keyCode)];
    if (mappedKey == nil) {
        return;
    }

    // SIMPLIFIED: Use the standard streaming mapping.
    NSEventModifierFlags modifierFlags = [StreamShortcutProfile relevantModifierFlags:shortcut.modifierFlags];
    // A rule the player bound with Command travels under the same preference as the keys
    // they type. Flipping one path and not the other is the half-mapped keyboard.
    NSUInteger remoteModifierMask = (NSUInteger)KMR_RemoteMaskForAppKitFlagsWithCommandPreference(
        modifierFlags, [self commandKeyPreferenceForCurrentHost]);

    char translatedModifiers = HIDRemoteModifierFlagsToGenericFlags(remoteModifierMask);
    short translatedKeyCode = (short)(0x8000 | [mappedKey shortValue]);
    // A synthetic tap cannot release a key that a physical press still owns.
    if ([self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:@(translatedKeyCode)]) {
        return;
    }

    // Only the modifiers this rule is adding belong to it. A modifier the player holds
    // is already down on the host, and letting it go here would strand the tracker.
    NSUInteger owned = HIDSyntheticOwnedModifierMask(self, remoteModifierMask);

    HIDInputLease inputLease = HIDAcquireInputContext(self);

    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "sendSyntheticRemoteShortcut")) {
        return;
    }

    static const HIDKeyboardRemoteModifierMask remoteOrder[] = {
        HIDKeyboardRemoteModifierMaskLeftShift,
        HIDKeyboardRemoteModifierMaskRightShift,
        HIDKeyboardRemoteModifierMaskLeftControl,
        HIDKeyboardRemoteModifierMaskRightControl,
        HIDKeyboardRemoteModifierMaskLeftAlt,
        HIDKeyboardRemoteModifierMaskRightAlt,
        HIDKeyboardRemoteModifierMaskLeftMeta,
        HIDKeyboardRemoteModifierMaskRightMeta,
    };

    HIDDispatchInput(self, inputLease, ^{
        for (NSUInteger i = 0; i < sizeof(remoteOrder) / sizeof(remoteOrder[0]); i++) {
            HIDKeyboardRemoteModifierMask mask = remoteOrder[i];
            if ((owned & mask) == 0) {
                continue;
            }

            unsigned short modifierKeyCode = HIDRemoteModifierKeyCode(mask);
            if (modifierKeyCode != 0) {
                LiSendKeyboardEventCtx(inputCtx, modifierKeyCode, KEY_ACTION_DOWN, translatedModifiers);
            }
        }

        LiSendKeyboardEventCtx(inputCtx, translatedKeyCode, KEY_ACTION_DOWN, translatedModifiers);
        LiSendKeyboardEventCtx(inputCtx, translatedKeyCode, KEY_ACTION_UP, translatedModifiers);

        // Release in reverse, and only what was pressed above: the player's own hold has
        // to stay down until the real keyUp or flagsChanged says otherwise.
        for (NSInteger i = (NSInteger)(sizeof(remoteOrder) / sizeof(remoteOrder[0])) - 1; i >= 0; i--) {
            HIDKeyboardRemoteModifierMask mask = remoteOrder[(NSUInteger)i];
            if ((owned & mask) == 0) {
                continue;
            }

            unsigned short modifierKeyCode = HIDRemoteModifierKeyCode(mask);
            if (modifierKeyCode != 0) {
                LiSendKeyboardEventCtx(inputCtx, modifierKeyCode, KEY_ACTION_UP, 0);
            }
        }
    });
}

static unsigned short HIDRemappedKeyCodeForModifierKey(HIDSupport *support,
                                                          unsigned short keyCode) {
    if (!HIDIsModifierKeyCode(keyCode)) {
        return 0;
    }
    return KMR_RemoteVKForPhysicalKeyCodeWithCommandPreference(keyCode,
                                                               [support commandKeyPreferenceForCurrentHost]);
}

- (short)translateKeyCodeWithEvent:(NSEvent *)event {
    // Zero is what this table already answers when it has no entry, and both callers treat
    // it as "ignore this edge on both halves", so a non-keyboard event is refused with the
    // same value rather than translated from a field that means nothing. See
    // scripts/key-code-read-site-audit.py for why every reader carries this itself.
    if (event == nil || (event.type != NSEventTypeKeyDown && event.type != NSEventTypeKeyUp)) {
        return 0;
    }

    unsigned short keyCode = event.keyCode;

    if (HIDIsModifierKeyCode(keyCode)) {
        unsigned short remapped = HIDRemappedKeyCodeForModifierKey(self, keyCode);
        if (remapped != 0) {
            return (short)remapped;
        }
    }

    if (![self.mappings objectForKey:@(keyCode)]) {
        return 0;
    }
    return [self.mappings[@(keyCode)] shortValue];
}

- (char)translatedModifierFlagsForEvent:(NSEvent *)event {
    return HIDRemoteModifierFlagsToGenericFlags([self desiredRemoteKeyboardModifierMaskForEvent:event]);
}

- (char)translateKeyModifierWithEvent:(NSEvent *)event {
    return [self translatedModifierFlagsForEvent:event];
}

- (KMR_CommandPreference)commandKeyPreferenceForCurrentHost {
    // Read per event rather than once at connect, so a player who turns the switch over
    // mid-session gets the new keyboard on the next key rather than the next session. The
    // stored value is optional, so a host nobody opened the setting for answers the default.
    NSString *hostUuid = self.host.uuid ?: @"";
    return [SettingsClass commandSendsControlFor:hostUuid] ? KMR_CommandPreferenceControl
                                                           : KMR_CommandPreferenceWin;
}

- (BOOL)useGCMouse {
    return [SettingsClass shouldUseGameControllerMouseFor:self.host.uuid];
}

- (BOOL)useCoreHIDMouse {
    return [SettingsClass shouldAllowCoreHIDMouseFor:self.host.uuid];
}

- (BOOL)shouldUseAbsolutePointerPathForCurrentConfiguration {
    NSInteger touchscreenMode = [SettingsClass touchscreenModeFor:self.host.uuid];
    return HIDShouldUseAbsolutePointerPath(self, touchscreenMode);
}

- (BOOL)shouldUseCoreHIDFreeMouseAbsoluteSyncForCurrentConfiguration {
    return HIDShouldUseCoreHIDFreeMouseAbsoluteSync(self);
}

- (BOOL)hasRecentCoreHIDMouseMovement {
    return self.coreHIDMouseDriver != nil &&
           self.coreHIDMouseDriver.secondsSinceLastMovementEvent < 0.25;
}

- (NSInteger)controllerDriver {
    return [SettingsClass controllerDriverFor:self.host.uuid];
}

- (void)refreshMouseInputConfiguration {
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self refreshMouseInputConfiguration];
        });
        return;
    }

    for (GCMouse *mouse in GCMouse.mice) {
        [self unregisterMouseCallbacks:mouse];
        [self registerMouseCallbacks:mouse];
    }

    [self recordMouseInputPathStateIntoLedger];
    [self tearDownCoreHIDMouseDriver];
    [self setupCoreHIDMouseDriverIfNeeded];
}

/// Write what the input path decided into the ledger the diagnostics report reads.
///
/// The ledger is written by the code that decides, not by the page that displays. Issue 24
/// is what those two disagreeing costs: a strategy whose label promised HID and whose effect
/// was to stop CoreHID, and a settings page that went on showing the default while a host
/// nobody configured ran in the retired mode. A report assembled from display names would
/// repeat the mistake, so this reads the same accessors the branches read.
- (void)recordMouseInputPathStateIntoLedger {
    NSString *hostUuid = self.host.uuid ?: @"";
    NSNumber *storedValue = [SettingsClass persistedMouseDriverRawValueFor:hostUuid];
    BOOL allowedByStrategy = self.useCoreHIDMouse;
    NSString *pointerMode = [SettingsClass mouseModeFor:hostUuid];
    BOOL absolutePath = [self shouldUseAbsolutePointerPathForCurrentConfiguration];
    [[InputDiagnosticsLedger sharedLedger] updateSummary:^(InputDiagnosticsSummary *summary) {
        summary.mouseStrategyName = [SettingsClass mouseDriverStrategyNameFor:hostUuid];
        summary.mouseStrategyStoredValue = storedValue != nil ? storedValue.integerValue : -1;
        summary.coreHIDAllowedByStrategy = allowedByStrategy;
        // Read from the same accessors the branches read, for the same reason the strategy is:
        // the absolute path is what makes a zero in the relative counters mean nothing, and a
        // report that inferred it from the settings label would be guessing again.
        summary.pointerMode = pointerMode;
        summary.absolutePointerPathActive = absolutePath;
    }];
}

- (void)setupCoreHIDMouseDriverIfNeeded {
    if (!self.useCoreHIDMouse) {
        return;
    }

    NSInteger touchscreenMode = [SettingsClass touchscreenModeFor:self.host.uuid];
    BOOL useAbsolutePointerPath = HIDShouldUseAbsolutePointerPath(self, touchscreenMode);
    if (useAbsolutePointerPath) {
        Log(LOG_I, @"CoreHID mouse skipped: absolute pointer path active (mouseMode=%@ touchscreenMode=%ld strategy=%ld)",
            [SettingsClass mouseModeFor:self.host.uuid],
            (long)touchscreenMode,
            (long)[SettingsClass mouseDriverFor:self.host.uuid]);
        return;
    }

    if (self.coreHIDMouseDriver != nil) {
        return;
    }

    self.coreHIDMouseRuntimeFailed = NO;
    self.coreHIDMouseDidDeliverMovement = NO;
    self.coreHIDMouseDriver = [[CoreHIDMouseDriver alloc] init];
    self.coreHIDMouseDriver.delegate = self;
    self.coreHIDMouseDriver.maximumReportRate = [SettingsClass coreHIDMaxMouseReportRateFor:self.host.uuid];
    self.coreHIDMouseDriver.requestsListenAccessIfNeeded = NO;
    // Pending is a state of the driver, not a sender, so it may not leave a sender's
    // credit behind: the line has to be free to name whoever delivers the next motion.
    self.lastReportedRelativeMotionSource = nil;
    [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
                                        summaryKey:@"Mouse Runtime Path CoreHID Pending"
                                         detailKey:@"Mouse Runtime Detail CoreHID Pending"];
    Log(LOG_I, @"CoreHID mouse setup: strategy=%ld maxRate=%d requestAccess=%d",
        (long)[SettingsClass mouseDriverFor:self.host.uuid],
        self.coreHIDMouseDriver.maximumReportRate,
        self.coreHIDMouseDriver.requestsListenAccessIfNeeded ? 1 : 0);
    [[InputDiagnosticsLedger sharedLedger] updateSummary:^(InputDiagnosticsSummary *summary) {
        // Named for the attempt, not the permission: the strategy can allow CoreHID and the
        // session still never try, when the absolute pointer path takes the mouse instead.
        summary.coreHIDWantedToStart = YES;
        summary.coreHIDFailedAtRuntime = NO;
        summary.coreHIDFailureReason = nil;
    }];
    [self.coreHIDMouseDriver start];
}

- (void)tearDownCoreHIDMouseDriver {
    if (self.coreHIDMouseDriver == nil) {
        return;
    }

    [self.coreHIDMouseDriver stop];
    self.coreHIDMouseDriver.delegate = nil;
    self.coreHIDMouseDriver = nil;
    self.coreHIDMouseDidDeliverMovement = NO;
    // Reconfiguring retires the credit along with the driver, so the replacement gets to
    // say who it is instead of inheriting the name of a sender that no longer exists.
    self.lastReportedRelativeMotionSource = nil;
    HIDInvalidateCoreHIDFreeMouseAbsoluteSync(self);
}

/** Drop what this queue owes the host, for the same reason the display-link
 * consumer drops its own pair: every path that calls this has already decided the
 * motion it holds is not going to be dispatched, and a debt kept past that decision
 * is paid into a later, unrelated movement of the hand.
 *
 * This touches only the pair this queue drains. The display-link consumer owns the
 * other pair, and the two consumers are different threads.
 */
- (void)resetRelativeMotionResidualForHIDQueueConsumer {
    self.relativeDeltaResidualX = 0.0;
    self.relativeDeltaResidualY = 0.0;
}

/** Credit the status line to whoever really handed motion to the host.

 * Two things this fixes by construction. The AppKit line used to be written where the
 * pointer event arrived, which is upstream of every reason that event can still be
 * dropped -- suppressed inside the warp window, quantised down to a zero-pixel move, or
 * routed to the absolute path instead -- so the line could claim a sender that sent
 * nothing; and the GameController and absolute lines were written on every frame, which
 * rewrote the same sentence into settings sixty times a second. A sender credits itself
 * once, and the previous sender's credit is what makes the next change visible. */
- (void)noteMotionSource:(NSString *)sourceName
              summaryKey:(NSString *)summaryKey
               detailKey:(NSString *)detailKey {
    if ([self.lastReportedRelativeMotionSource isEqualToString:sourceName]) {
        return;
    }
    self.lastReportedRelativeMotionSource = [sourceName copy];
    // The same fact the status line shows, kept where the report can reach it after the
    // window is gone. This is the line that answers "which path had my mouse" once there is
    // no overlay left to look at.
    [[InputDiagnosticsLedger sharedLedger] updateSummary:^(InputDiagnosticsSummary *summary) {
        summary.lastMotionSource = [sourceName copy];
        summary.lastMotionSourceAt = [NSDate date];
    }];
    [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
                                        summaryKey:summaryKey
                                         detailKey:detailKey];
}

- (void)dispatchRelativeMouseDeltaX:(CGFloat)deltaX
                             deltaY:(CGFloat)deltaY
                          sourceTag:(NSString *)sourceTag {
    if (deltaX == 0.0 && deltaY == 0.0) {
        return;
    }

    if (!self.shouldSendInputEvents) {
        [self resetRelativeMotionResidualForHIDQueueConsumer];
        return;
    }

    HIDInputLease inputLease = HIDAcquireInputContext(self);

    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "dispatchRelativeMouseDelta")) {
        [self resetRelativeMotionResidualForHIDQueueConsumer];
        return;
    }

    NSInteger touchscreenMode = [SettingsClass touchscreenModeFor:self.host.uuid];
    if (HIDShouldUseAbsolutePointerPath(self, touchscreenMode)) {
        [self resetRelativeMotionResidualForHIDQueueConsumer];
        return;
    }

    BOOL suppressed = HIDShouldSuppressRelativeMouse(self);
    if (suppressed) {
        [self resetRelativeMotionResidualForHIDQueueConsumer];
        [self recordRelativeInputDiagnosticsFrom:sourceTag rawDeltaX:deltaX rawDeltaY:deltaY
                                      sentDeltaX:0 sentDeltaY:0 suppressed:YES];
        return;
    }
    CGFloat sensitivity = HIDPointerSensitivityForHost(self.host);
    CGFloat residualX = self.relativeDeltaResidualX;
    CGFloat residualY = self.relativeDeltaResidualY;
    short moveX = HIDDrainRelativeDelta(&residualX, deltaX, sensitivity);
    short moveY = HIDDrainRelativeDelta(&residualY, deltaY, sensitivity);
    self.relativeDeltaResidualX = residualX;
    self.relativeDeltaResidualY = residualY;
    [self recordRelativeInputDiagnosticsFrom:sourceTag
                                   rawDeltaX:deltaX
                                   rawDeltaY:deltaY
                                  sentDeltaX:(suppressed ? 0 : moveX)
                                  sentDeltaY:(suppressed ? 0 : moveY)
                                  suppressed:suppressed];
    if (suppressed || (moveX == 0 && moveY == 0)) {
        return;
    }

    HIDDispatchInput(self, inputLease, ^{
        // P2-1: when the host wants the cursor expressed in absolute coordinates,
        // forward the relative delta through LiSendMouseMoveAsMousePositionEvent
        // instead of the pure relative wire packet. The host maintains
        // absCurrentPosX/Y across calls, so as long as the session has produced
        // a fresh absolute pointer reference inside the staleness window, the
        // delta accumulates from the correct cursor origin. Sessions that have
        // never sent an absolute event keep the legacy relative packet so the
        // cursor does not snap to (0,0) on the host.
        BOOL useAbsoluteWire = NO;
        short p2ReferenceWidth = 0;
        short p2ReferenceHeight = 0;
        if (HIDShouldRouteRelativeAsAbsolute(self, &p2ReferenceWidth, &p2ReferenceHeight)) {
            useAbsoluteWire = YES;
        }
        if (useAbsoluteWire) {
            LiSendMouseMoveAsMousePositionEventCtx(inputCtx, moveX, moveY,
                                                   p2ReferenceWidth, p2ReferenceHeight);
        } else {
            LiSendMouseMoveEventCtx(inputCtx, moveX, moveY);
        }
    });
    if ([sourceTag isEqualToString:@"mouseMoved"]) {
        [self noteMotionSource:sourceTag
                    summaryKey:@"Mouse Runtime Path AppKit Active"
                     detailKey:@"Mouse Runtime Detail AppKit Active"];
    }
}

- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver
            didObserveRawDeltaX:(double)deltaX
                      deltaY:(double)deltaY {
    (void)driver;
    if (!self.inputDiagnosticsEnabled || (!isfinite(deltaX) && !isfinite(deltaY))) {
        return;
    }

    @synchronized (self.inputDiagnosticsLock) {
        self.inputDiagnosticsCoreHIDRawEvents += 1;
    }
}

- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver
             didReceiveDeltaX:(double)deltaX
                       deltaY:(double)deltaY {
    // CoreHID clients and timers run concurrently. AppKit owns the session's
    // pointer state; re-check driver identity after the queue handoff.
    if (![NSThread isMainThread]) {
        uint64_t captureGeneration = self.inputCaptureGeneration;
        dispatch_async(dispatch_get_main_queue(), ^{
            if (captureGeneration != self.inputCaptureGeneration) return;
            [self coreHIDMouseDriver:driver didReceiveDeltaX:deltaX deltaY:deltaY];
        });
        return;
    }
    if (driver != self.coreHIDMouseDriver) return;
    if (!self.useCoreHIDMouse) {
        return;
    }

    if (!self.coreHIDMouseDidDeliverMovement) {
        self.coreHIDMouseDidDeliverMovement = YES;
        [[InputDiagnosticsLedger sharedLedger] updateSummary:^(InputDiagnosticsSummary *summary) {
            summary.coreHIDDeliveredMovement = YES;
            summary.coreHIDFailedAtRuntime = NO;
        }];
        Log(LOG_I, @"CoreHID mouse active: first movement received");
        [[InputMonitoringPermissionManager sharedManager] noteCoreHIDDidBecomeActive];
        [self noteMotionSource:@"coreHIDMouse"
                    summaryKey:@"Mouse Runtime Path CoreHID Active"
                     detailKey:@"Mouse Runtime Detail CoreHID Active"];
    }
    if (self.inputDiagnosticsEnabled) {
        @synchronized (self.inputDiagnosticsLock) {
            self.inputDiagnosticsCoreHIDDispatches += 1;
        }
    }
    self.coreHIDMouseRuntimeFailed = NO;
    BOOL dispatchedVirtualFreeMouse = [self dispatchVirtualFreeMouseDeltaX:deltaX
                                                                    deltaY:deltaY
                                                                 sourceTag:@"coreHIDVirtualFreeMouse"];
    if (dispatchedVirtualFreeMouse) {
        HIDInvalidateCoreHIDFreeMouseAbsoluteSync(self);
        return;
    }
    if (HIDShouldUseCoreHIDFreeMouseAbsoluteSync(self) && self.freeMouseAbsoluteSyncHandler != nil) {
        if (!self.coreHIDFreeMouseAbsoluteSyncScheduled) {
            self.coreHIDFreeMouseAbsoluteSyncScheduled = YES;
            uint64_t scheduleToken = ++self.coreHIDFreeMouseAbsoluteSyncToken;
            HIDFreeMouseAbsoluteSyncHandler handler = self.freeMouseAbsoluteSyncHandler;
            __weak typeof(self) weakSelf = self;
            dispatch_async(dispatch_get_main_queue(), ^{
                __strong typeof(weakSelf) strongSelf = weakSelf;
                if (strongSelf == nil ||
                    !strongSelf.coreHIDFreeMouseAbsoluteSyncScheduled ||
                    strongSelf.coreHIDFreeMouseAbsoluteSyncToken != scheduleToken) {
                    return;
                }
                strongSelf.coreHIDFreeMouseAbsoluteSyncScheduled = NO;
                handler();
            });
        }
        return;
    }
    HIDInvalidateCoreHIDFreeMouseAbsoluteSync(self);
    [self dispatchRelativeMouseDeltaX:(CGFloat)deltaX
                               deltaY:(CGFloat)deltaY
                            sourceTag:@"coreHIDMouse"];
}

- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver
         didFailWithReason:(NSString *)reason
                messageKey:(NSString *)messageKey {
    // CoreHID clients and timers run concurrently. AppKit owns the session's
    // pointer state; re-check driver identity after the queue handoff.
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self coreHIDMouseDriver:driver didFailWithReason:reason messageKey:messageKey]; });
        return;
    }
    if (driver != self.coreHIDMouseDriver) return;
    NSString *safeReason = reason.length > 0 ? reason : @"unknown";
    NSString *safeMessage = messageKey.length > 0 ? messageKey : @"CoreHID Mouse input failed.";
    NSInteger configuredStrategy = [SettingsClass mouseDriverFor:self.host.uuid];
    self.coreHIDMouseRuntimeFailed = YES;
    [[InputDiagnosticsLedger sharedLedger] updateSummary:^(InputDiagnosticsSummary *summary) {
        summary.coreHIDFailedAtRuntime = YES;
        summary.coreHIDFailureReason = safeReason;
    }];
    if ([safeReason isEqualToString:@"permission-denied"]) {
        [[InputMonitoringPermissionManager sharedManager] noteCoreHIDPermissionFailureWithMessage:safeMessage];
    }
    LogLevel level = (configuredStrategy == 3 && [safeReason isEqualToString:@"permission-denied"]) ? LOG_I : LOG_W;
    Log(level, @"CoreHID mouse fallback: reason=%@ message=%@", safeReason, safeMessage);
    // Naming a replacement here was never supported by anything observed: this callback
    // knows CoreHID stopped, and nothing here knows another sender is delivering motion.
    NSString *detailKey = @"Mouse Runtime Detail CoreHID Stopped Runtime";
    if ([safeReason isEqualToString:@"permission-denied"]) {
        detailKey = @"Mouse Runtime Detail CoreHID Stopped Permission";
    } else if ([safeReason isEqualToString:@"unsupported-os"]) {
        detailKey = @"Mouse Runtime Detail CoreHID Stopped UnsupportedOS";
    }
    self.lastReportedRelativeMotionSource = nil;
    [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
                                        summaryKey:@"Mouse Runtime Path CoreHID Stopped"
                                         detailKey:detailKey];
}

- (void)handleDpad:(NSInteger)intValue entry:(HIDDeviceControllerEntry *)entry {
    switch (intValue) {
        case 0:
            [self updateButtonFlags:UP_FLAG entry:entry state:YES];
            break;
        case 1:
            [self updateButtonFlags:UP_FLAG | RIGHT_FLAG entry:entry state:YES];
            break;
        case 2:
            [self updateButtonFlags:RIGHT_FLAG entry:entry state:YES];
            break;
        case 3:
            [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG entry:entry state:YES];
            break;
        case 4:
            [self updateButtonFlags:DOWN_FLAG entry:entry state:YES];
            break;
        case 5:
            [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG entry:entry state:YES];
            break;
        case 6:
            [self updateButtonFlags:LEFT_FLAG entry:entry state:YES];
            break;
        case 7:
            [self updateButtonFlags:UP_FLAG | LEFT_FLAG entry:entry state:YES];
            break;

        case 8:
            [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG entry:entry state:NO];
            break;

        default:
            break;
    }
}

void myHIDCallback(void* context, IOReturn result, void* sender, IOHIDValueRef value) {
    if (context == NULL || result != kIOReturnSuccess || value == NULL) return;
    IOHIDElementRef elem = IOHIDValueGetElement(value);
    uint32_t usagePage = IOHIDElementGetUsagePage(elem);
    uint32_t usage = IOHIDElementGetUsage(elem);
    CFIndex intValue = IOHIDValueGetIntegerValue(value);
    
    HIDSupport *self = (__bridge HIDSupport *)context;
    
    IOHIDDeviceRef device = IOHIDElementGetDevice(elem);
    if (device == NULL) return;
    // 0.2: every pad owns its own state now; this pad's controller is what the
    // layout below writes into. The table is read-only from the HID callbacks'
    // point of view, so no allocation races.
    HIDDeviceControllerEntry *entry = [self entryForDevice:device];
    if (entry == nil) return;
    Controller *devController = entry.controller;
    [self sendControllerArrivalForEntry:entry];

    // KingKong claims the Microsoft vendor id, so the vendor-specific check
    // has to win over the generic Xbox layout check regardless of how either
    // id list evolves. The two sets are disjoint today; the negation keeps a
    // future overlap from silently stealing the KingKong axis map.
    if (isXbox(device) && !isKingKong(device)) {
        switch (usagePage) {
            case kHIDPage_GenericDesktop:
                switch (usage) {
                    case kHIDUsage_GD_X:
                        devController.lastLeftStickX = MIN((intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Y:
                        devController.lastLeftStickY = MIN(-(intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Z:
                        devController.lastRightStickX = MIN((intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Rz:
                        devController.lastRightStickY = MIN(-(intValue - 32768), 32767);
                        break;
                        
                    case kHIDUsage_GD_Hatswitch:
                        switch (intValue) {
                            case 1:
                                [self updateButtonFlags:UP_FLAG entry:entry state:YES];
                                break;
                            case 2:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 3:
                                [self updateButtonFlags:RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 4:
                                [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 5:
                                [self updateButtonFlags:DOWN_FLAG entry:entry state:YES];
                                break;
                            case 6:
                                [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG entry:entry state:YES];
                                break;
                            case 7:
                                [self updateButtonFlags:LEFT_FLAG entry:entry state:YES];
                                break;
                            case 8:
                                [self updateButtonFlags:UP_FLAG | LEFT_FLAG entry:entry state:YES];
                                break;

                            case 0:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG entry:entry state:NO];
                                break;

                            default:
                                break;
                        }

                    default:
                        break;
                }
                break;
            case kHIDPage_Simulation:
                switch (usage) {
                    case kHIDUsage_Sim_Brake:
                        devController.lastLeftTrigger = intValue;
                        break;
                    case kHIDUsage_Sim_Accelerator:
                        devController.lastRightTrigger = intValue;
                        break;

                    default:
                        break;
                }
                break;

            case kHIDPage_Button:
                switch (usage) {
                    case 1:
                        [self updateButtonFlags:A_FLAG entry:entry state:intValue];
                        break;
                    case 2:
                        [self updateButtonFlags:B_FLAG entry:entry state:intValue];
                        break;
                    case 4:
                        [self updateButtonFlags:X_FLAG entry:entry state:intValue];
                        break;
                    case 5:
                        [self updateButtonFlags:Y_FLAG entry:entry state:intValue];
                        break;
                    case 7:
                        [self updateButtonFlags:LB_FLAG entry:entry state:intValue];
                        break;
                    case 8:
                        [self updateButtonFlags:RB_FLAG entry:entry state:intValue];
                        break;
                    case 11:
                        [self updateButtonFlags:BACK_FLAG entry:entry state:intValue];
                        break;
                    case 12:
                        [self updateButtonFlags:PLAY_FLAG entry:entry state:intValue];
                        break;
                    case 13:
                        [self updateButtonFlags:SPECIAL_FLAG entry:entry state:intValue];
                        break;

                        
                    default:
                        break;
                }
                
                break;
            case kHIDPage_Consumer:
                switch (usage) {
                    case kHIDUsage_Csmr_ACBack:
                        [self updateButtonFlags:BACK_FLAG entry:entry state:intValue];
                        break;
                    case kHIDUsage_Csmr_ACHome:
                        [self updateButtonFlags:SPECIAL_FLAG entry:entry state:intValue];
                        break;
                    case 14:
                        [self updateButtonFlags:LS_CLK_FLAG entry:entry state:intValue];
                        break;
                    case 15:
                        [self updateButtonFlags:RS_CLK_FLAG entry:entry state:intValue];
                        break;

                    default:
                        break;
                }
                
                break;
            default:
                break;
        }
    } else if (isKingKong(device)) {
        switch (usagePage) {
            case kHIDPage_GenericDesktop:
                switch (usage) {
                    case kHIDUsage_GD_X:
                        devController.lastLeftStickX = MAX(MIN((intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Y:
                        devController.lastLeftStickY = MAX(MIN(-(intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Rx:
                        devController.lastRightStickX = MAX(MIN((intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Ry:
                        devController.lastRightStickY = MAX(MIN(-(intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Z:
                        devController.lastLeftTrigger = (unsigned char)((int)intValue / 4);
                        break;
                    case kHIDUsage_GD_Rz:
                        devController.lastRightTrigger = (unsigned char)((int)intValue / 4);
                        break;
                        
                    case kHIDUsage_GD_Hatswitch:
                        switch (intValue) {
                            case 1:
                                [self updateButtonFlags:UP_FLAG entry:entry state:YES];
                                break;
                            case 2:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 3:
                                [self updateButtonFlags:RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 4:
                                [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG entry:entry state:YES];
                                break;
                            case 5:
                                [self updateButtonFlags:DOWN_FLAG entry:entry state:YES];
                                break;
                            case 6:
                                [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG entry:entry state:YES];
                                break;
                            case 7:
                                [self updateButtonFlags:LEFT_FLAG entry:entry state:YES];
                                break;
                            case 8:
                                [self updateButtonFlags:UP_FLAG | LEFT_FLAG entry:entry state:YES];
                                break;

                            case 0:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG entry:entry state:NO];
                                break;

                            default:
                                break;
                        }

                    default:
                        break;
                }
                break;

            case kHIDPage_Button:
                switch (usage) {
                    case 1:
                        [self updateButtonFlags:A_FLAG entry:entry state:intValue];
                        break;
                    case 2:
                        [self updateButtonFlags:B_FLAG entry:entry state:intValue];
                        break;
                    case 3:
                        [self updateButtonFlags:X_FLAG entry:entry state:intValue];
                        break;
                    case 4:
                        [self updateButtonFlags:Y_FLAG entry:entry state:intValue];
                        break;
                    case 5:
                        [self updateButtonFlags:LB_FLAG entry:entry state:intValue];
                        break;
                    case 6:
                        [self updateButtonFlags:RB_FLAG entry:entry state:intValue];
                        break;
                    case 7:
                        [self updateButtonFlags:BACK_FLAG entry:entry state:intValue];
                        break;
                    case 8:
                        [self updateButtonFlags:PLAY_FLAG entry:entry state:intValue];
                        break;
                    case 9:
                        [self updateButtonFlags:LS_CLK_FLAG entry:entry state:intValue];
                        break;
                    case 10:
                        [self updateButtonFlags:RS_CLK_FLAG entry:entry state:intValue];
                        break;
                    case 133:
                        [self updateButtonFlags:SPECIAL_FLAG entry:entry state:intValue];
                        break;

                        
                    default:
                        break;
                }
                
                break;
            default:
                break;
        }
    }

    if (self.controllerDriver == 0) {
        [self sendControllerEvent];
    }
}

void myHIDReportCallback (
                          void * _Nullable        context,
                          IOReturn                result,
                          void * _Nullable        sender,
                          IOHIDReportType         type,
                          uint32_t                reportID,
                          uint8_t *               report,
                          CFIndex                 reportLength) {
    if (context == NULL || sender == NULL || result != kIOReturnSuccess ||
        type != kIOHIDReportTypeInput || report == NULL || reportLength < 1) return;
    HIDSupport *self = (__bridge HIDSupport *)context;
    
    IOHIDDeviceRef device = (IOHIDDeviceRef)sender;
    if (!isPlayStation(device) && !isNintendo(device)) {
        return;
    };
    // 0.2: the state packets below and the change detector belong to this pad,
    // not to one shared object.
    HIDDeviceControllerEntry *entry = [self entryForDevice:device];
    if (entry == nil) return;
    Controller *devController = entry.controller;
    [self sendControllerArrivalForEntry:entry];
    
    if (isPS4(device)) {
        PS4StatePacket_t snapshot;
        PS4StatePacket_t *state = &snapshot;
        size_t offset;
        switch (report[0]) {
            case k_EPS4ReportIdUsbState:
                offset = 1;
                break;
            case k_EPS4ReportIdBluetoothState1:
            case k_EPS4ReportIdBluetoothState2:
            case k_EPS4ReportIdBluetoothState3:
            case k_EPS4ReportIdBluetoothState4:
            case k_EPS4ReportIdBluetoothState5:
            case k_EPS4ReportIdBluetoothState6:
            case k_EPS4ReportIdBluetoothState7:
            case k_EPS4ReportIdBluetoothState8:
            case k_EPS4ReportIdBluetoothState9:
                // Bluetooth state packets have two additional bytes at the beginning, the first notes if HID is present.
                if (reportLength < 2 || !(report[1] & 0x80)) return;
                offset = 3;
                break;
            default:
                return;
        }
                
        
        if (!HIDCopyReportPayload(state, sizeof(*state),
                                  // The copy spans the whole packet, so the
                                  // six-axis bytes land in the snapshot too.
                                  // The gate must still guarantee those bytes
                                  // are present: a truncated packet (or the
                                  // 10-byte PS5 BT variant) leaves them zero.
                                  offsetof(PS4StatePacket_t, _rgucPad1),
                                  report, reportLength, offset)) return;
        UInt8 abxy = state->rgucButtonsHatAndCounter[0] >> 4;
        [self updateButtonFlags:X_FLAG entry:entry state:(abxy & 0x01) != 0];
        [self updateButtonFlags:A_FLAG entry:entry state:(abxy & 0x02) != 0];
        [self updateButtonFlags:B_FLAG entry:entry state:(abxy & 0x04) != 0];
        [self updateButtonFlags:Y_FLAG entry:entry state:(abxy & 0x08) != 0];
        
        [self handleDpad:state->rgucButtonsHatAndCounter[0] & 0x0F entry:entry];

        UInt8 otherButtons = state->rgucButtonsHatAndCounter[1];
        [self updateButtonFlags:LB_FLAG entry:entry state:(otherButtons & 0x01) != 0];
        [self updateButtonFlags:RB_FLAG entry:entry state:(otherButtons & 0x02) != 0];
        [self updateButtonFlags:BACK_FLAG entry:entry state:(otherButtons & 0x10) != 0];
        [self updateButtonFlags:PLAY_FLAG entry:entry state:(otherButtons & 0x20) != 0];
        [self updateButtonFlags:LS_CLK_FLAG entry:entry state:(otherButtons & 0x40) != 0];
        [self updateButtonFlags:RS_CLK_FLAG entry:entry state:(otherButtons & 0x80) != 0];

        [self updateButtonFlags:SPECIAL_FLAG entry:entry state:(state->rgucButtonsHatAndCounter[2] & 0x01) != 0];
        
        devController.lastLeftTrigger = state->ucTriggerLeft;
        devController.lastRightTrigger = state->ucTriggerRight;

        devController.lastLeftStickX = (state->ucLeftJoystickX - 128) * 255 + 1;
        devController.lastLeftStickY = (state->ucLeftJoystickY - 128) * -255;
        devController.lastRightStickX = (state->ucRightJoystickX - 128) * 255 + 1;
        devController.lastRightStickY = (state->ucRightJoystickY - 128) * -255;
        
        if (self.controllerDriver == 0) {

            // Compare against the previous packet before refreshing it, so a
            // button and a sensor change in the same packet are judged
            // against the same baseline and each dispatches exactly once.
            BOOL inputChanged = entry.lastPS4State.rgucButtonsHatAndCounter[0] != state->rgucButtonsHatAndCounter[0] ||
                entry.lastPS4State.rgucButtonsHatAndCounter[1] != state->rgucButtonsHatAndCounter[1] ||
                entry.lastPS4State.rgucButtonsHatAndCounter[2] != state->rgucButtonsHatAndCounter[2] ||
                entry.lastPS4State.ucTriggerLeft != state->ucTriggerLeft ||
                entry.lastPS4State.ucTriggerRight != state->ucTriggerRight ||
                entry.lastPS4State.ucLeftJoystickX != state->ucLeftJoystickX ||
                entry.lastPS4State.ucLeftJoystickY != state->ucLeftJoystickY ||
                entry.lastPS4State.ucRightJoystickX != state->ucRightJoystickX ||
                entry.lastPS4State.ucRightJoystickY != state->ucRightJoystickY ||
                0;
            // The IMU moves on its own: a pad held still with the game idle
            // still has six new sensor bytes, and the host's request is for
            // those, not for the button state.
            // Compare through a local copy: the property returns the struct
            // by value, and a packet's twelve sensor bytes are one memcmp.
            PS4StatePacket_t prev4 = entry.lastPS4State;
            BOOL motionChanged = memcmp(&prev4.rgucGyroX, &state->rgucGyroX, 12) != 0;
            BOOL batteryChanged = prev4.ucBatteryLevel != state->ucBatteryLevel;
            // Eight bytes: two counter bytes plus three data bytes each.
            BOOL touchChanged = memcmp(&prev4.ucTouchpadCounter1,
                                       &state->ucTouchpadCounter1, 8) != 0;
            entry.lastPS4State = *state;
            if (inputChanged) {
                [self sendControllerEventForEntry:entry];
            }
            if (motionChanged) {
                [self pushMotionEventsForEntry:entry];
            }
            if (batteryChanged) {
                [self pushBatteryEventForEntry:entry];
            }
            if (touchChanged) {
                [self pushControllerTouchForEntry:entry];
            }
        }
    } else if (isPS5(device)) {
        PS5StatePacket_t snapshot;
        PS5StatePacket_t *state = &snapshot;
        size_t offset;
        switch (report[0]) {
            case k_EPS5ReportIdState:
                offset = 1;
                self.isPS5Bluetooth = reportLength == 10;
                break;
            case k_EPS5ReportIdBluetoothState:
                offset = 2;
                self.isPS5Bluetooth = YES;
                break;
            default:
                return;
        }
        
        if (!HIDCopyReportPayload(state, sizeof(*state),
                                  // Extend the copy to cover the 12 IMU bytes
                                  // (GyroX..AccelZ) so the six-axis snapshot
                                  // is populated; before this the required
                                  // length stopped at the button bytes.
                                  offsetof(PS5StatePacket_t, rgucTimer1),
                                  report, reportLength, offset)) return;
        UInt8 abxy = state->rgucButtonsAndHat[0] >> 4;
        [self updateButtonFlags:X_FLAG entry:entry state:(abxy & 0x01) != 0];
        [self updateButtonFlags:A_FLAG entry:entry state:(abxy & 0x02) != 0];
        [self updateButtonFlags:B_FLAG entry:entry state:(abxy & 0x04) != 0];
        [self updateButtonFlags:Y_FLAG entry:entry state:(abxy & 0x08) != 0];
        
        [self handleDpad:state->rgucButtonsAndHat[0] & 0x0F entry:entry];

        UInt8 otherButtons = state->rgucButtonsAndHat[1];
        [self updateButtonFlags:LB_FLAG entry:entry state:(otherButtons & 0x01) != 0];
        [self updateButtonFlags:RB_FLAG entry:entry state:(otherButtons & 0x02) != 0];
        [self updateButtonFlags:BACK_FLAG entry:entry state:(otherButtons & 0x10) != 0];
        [self updateButtonFlags:PLAY_FLAG entry:entry state:(otherButtons & 0x20) != 0];
        [self updateButtonFlags:LS_CLK_FLAG entry:entry state:(otherButtons & 0x40) != 0];
        [self updateButtonFlags:RS_CLK_FLAG entry:entry state:(otherButtons & 0x80) != 0];

        [self updateButtonFlags:SPECIAL_FLAG entry:entry state:(state->rgucButtonsAndHat[2] & 0x01) != 0];
        
        devController.lastLeftTrigger = state->ucTriggerLeft;
        devController.lastRightTrigger = state->ucTriggerRight;

        devController.lastLeftStickX = (state->ucLeftJoystickX - 128) * 255 + 1;
        devController.lastLeftStickY = (state->ucLeftJoystickY - 128) * -255;
        devController.lastRightStickX = (state->ucRightJoystickX - 128) * 255 + 1;
        devController.lastRightStickY = (state->ucRightJoystickY - 128) * -255;
        
        if (self.controllerDriver == 0) {

            // Same compare-before-refresh rule as the PS4 branch: both change
            // flags are judged against the previous packet, then the snapshot
            // refreshes once, then each side dispatches exactly once.
            BOOL inputChanged = entry.lastPS5State.rgucButtonsAndHat[0] != state->rgucButtonsAndHat[0] ||
                entry.lastPS5State.rgucButtonsAndHat[1] != state->rgucButtonsAndHat[1] ||
                entry.lastPS5State.rgucButtonsAndHat[2] != state->rgucButtonsAndHat[2] ||
                entry.lastPS5State.ucTriggerLeft != state->ucTriggerLeft ||
                entry.lastPS5State.ucTriggerRight != state->ucTriggerRight ||
                entry.lastPS5State.ucLeftJoystickX != state->ucLeftJoystickX ||
                entry.lastPS5State.ucLeftJoystickY != state->ucLeftJoystickY ||
                entry.lastPS5State.ucRightJoystickX != state->ucRightJoystickX ||
                entry.lastPS5State.ucRightJoystickY != state->ucRightJoystickY ||
                0;
            // The 12 sensor bytes of the PS5 packet sit at the same offsets
            // as the PS4 ones, so the motion test shares the PS4 comparison.
            // Same compare, through the PS5 snapshot's own fields.
            PS5StatePacket_t prev5 = entry.lastPS5State;
            BOOL motionChanged = memcmp(&prev5.rgucGyroX, &state->rgucGyroX, 12) != 0;
            BOOL batteryChanged = prev5.ucBatteryLevel != state->ucBatteryLevel;
            BOOL touchChanged = memcmp(&prev5.ucTouchpadCounter1,
                                       &state->ucTouchpadCounter1, 8) != 0;
            entry.lastPS5State = *state;
            if (inputChanged) {
                [self sendControllerEventForEntry:entry];
            }
            if (motionChanged) {
                [self pushMotionEventsForEntry:entry];
            }
            if (batteryChanged) {
                [self pushBatteryEventForEntry:entry];
            }
            if (touchChanged) {
                [self pushControllerTouchForEntry:entry];
            }
        }
    } else if (isNintendo(device)) {
        if (self.waitingForVibrationEnable) {
            if (TICKS_PASSED([self.ticks getTicks], self.startedWaitingForVibrationEnable + 100)) {
                self.vibrationEnableResponded = NO;
                self.waitingForVibrationEnable = NO;
                dispatch_semaphore_signal(self.hidReadSemaphore);
            }
            if (report[0] == k_eSwitchInputReportIDs_SubcommandReply) {
                SwitchSubcommandInputPacket_t snapshot;
                SwitchSubcommandInputPacket_t *reply = &snapshot;
                if (!HIDCopyReportPayload(reply, sizeof(*reply),
                                          offsetof(SwitchSubcommandInputPacket_t, ucSubcommandID) + 1,
                                          report, reportLength, 1)) return;
                if (reply->ucSubcommandID == k_eSwitchSubcommandIDs_EnableVibration && (reply->ucSubcommandAck & 0x80)) {
                    self.vibrationEnableResponded = YES;
                    self.waitingForVibrationEnable = NO;
                    dispatch_semaphore_signal(self.hidReadSemaphore);
                }
            }
        } else {
            if (report[0] == k_eSwitchInputReportIDs_SimpleControllerState) {
                SwitchSimpleStatePacket_t snapshot;
                SwitchSimpleStatePacket_t *packet = &snapshot;
                if (!HIDCopyReportPayload(packet, sizeof(*packet), sizeof(*packet),
                                          report, reportLength, 1)) return;
                
                SInt16 axis;
                
                UInt8 buttons = packet->rgucButtons[0];
                [self updateButtonFlags:Y_FLAG entry:entry state:(buttons & 0x08) != 0];
                [self updateButtonFlags:B_FLAG entry:entry state:(buttons & 0x02) != 0];
                [self updateButtonFlags:A_FLAG entry:entry state:(buttons & 0x01) != 0];
                [self updateButtonFlags:X_FLAG entry:entry state:(buttons & 0x04) != 0];
                [self updateButtonFlags:LB_FLAG entry:entry state:(buttons & 0x10) != 0];
                [self updateButtonFlags:RB_FLAG entry:entry state:(buttons & 0x20) != 0];
                axis = (buttons & 0x40) ? 32767 : -32768;
                devController.lastLeftTrigger = axis;
                axis = (buttons & 0x80) ? 32767 : -32768;
                devController.lastRightTrigger = axis;
                
                UInt8 otherButtons = packet->rgucButtons[1];
                [self updateButtonFlags:BACK_FLAG entry:entry state:(otherButtons & 0x01) != 0];
                [self updateButtonFlags:PLAY_FLAG entry:entry state:(otherButtons & 0x02) != 0];
                [self updateButtonFlags:LS_CLK_FLAG entry:entry state:(otherButtons & 0x04) != 0];
                [self updateButtonFlags:RS_CLK_FLAG entry:entry state:(otherButtons & 0x08) != 0];
                
                [self updateButtonFlags:SPECIAL_FLAG entry:entry state:(otherButtons & 0x10) != 0];
                
                [self handleDpad:packet->ucStickHat entry:entry];

                axis = (short)(packet->sJoystickLeft[0] - INT_MAX);
                devController.lastLeftStickX = axis;
                axis = (short)(packet->sJoystickLeft[1] - INT_MAX);
                devController.lastLeftStickY = axis;
                axis = (short)(packet->sJoystickRight[0] - INT_MAX);
                devController.lastRightStickX = axis;
                axis = (short)(packet->sJoystickRight[1] - INT_MAX);
                devController.lastRightStickY = axis;
                
                if (self.controllerDriver == 0) {
                    
                    if (entry.lastSimpleSwitchState.rgucButtons[0] != packet->rgucButtons[0] ||
                        entry.lastSimpleSwitchState.rgucButtons[1] != packet->rgucButtons[1] ||
                        entry.lastSimpleSwitchState.ucStickHat != packet->ucStickHat ||
                        entry.lastSimpleSwitchState.sJoystickLeft[0] != packet->sJoystickLeft[0] ||
                        entry.lastSimpleSwitchState.sJoystickLeft[1] != packet->sJoystickLeft[1] ||
                        entry.lastSimpleSwitchState.sJoystickRight[0] != packet->sJoystickRight[0] ||
                        entry.lastSimpleSwitchState.sJoystickRight[1] != packet->sJoystickRight[1] ||
                        0)
                    {
                        [self sendControllerEventForEntry:entry];
                        entry.lastSimpleSwitchState = *packet;
                    }
                }
            } else if (report[0] == k_eSwitchInputReportIDs_FullControllerState) {
                SwitchStatePacket_t snapshot;
                SwitchStatePacket_t *packet = &snapshot;
                if (!HIDCopyReportPayload(packet, sizeof(*packet), sizeof(packet->controllerState),
                                          report, reportLength, 1)) return;
                
                SInt16 axis;
                
                UInt8 buttons = packet->controllerState.rgucButtons[0];
                [self updateButtonFlags:Y_FLAG entry:entry state:(buttons & 0x02) != 0];
                [self updateButtonFlags:B_FLAG entry:entry state:(buttons & 0x08) != 0];
                [self updateButtonFlags:A_FLAG entry:entry state:(buttons & 0x04) != 0];
                [self updateButtonFlags:X_FLAG entry:entry state:(buttons & 0x01) != 0];
                [self updateButtonFlags:RB_FLAG entry:entry state:(buttons & 0x40) != 0];
                axis = (buttons & 0x80) ? 32767 : -32768;
                devController.lastRightTrigger = axis;
                
                UInt8 otherButtons = packet->controllerState.rgucButtons[1];
                [self updateButtonFlags:BACK_FLAG entry:entry state:(otherButtons & 0x01) != 0];
                [self updateButtonFlags:PLAY_FLAG entry:entry state:(otherButtons & 0x02) != 0];
                [self updateButtonFlags:LS_CLK_FLAG entry:entry state:(otherButtons & 0x08) != 0];
                [self updateButtonFlags:RS_CLK_FLAG entry:entry state:(otherButtons & 0x04) != 0];
                
                [self updateButtonFlags:SPECIAL_FLAG entry:entry state:(otherButtons & 0x10) != 0];
                
                UInt8 otherOtherButtons = packet->controllerState.rgucButtons[2];
                [self updateButtonFlags:DOWN_FLAG entry:entry state:(otherOtherButtons & 0x01) != 0];
                [self updateButtonFlags:UP_FLAG entry:entry state:(otherOtherButtons & 0x02) != 0];
                [self updateButtonFlags:RIGHT_FLAG entry:entry state:(otherOtherButtons & 0x04) != 0];
                [self updateButtonFlags:LEFT_FLAG entry:entry state:(otherOtherButtons & 0x08) != 0];
                [self updateButtonFlags:LB_FLAG entry:entry state:(otherOtherButtons & 0x40) != 0];
                axis = (otherOtherButtons & 0x80) ? 32767 : -32768;
                devController.lastLeftTrigger = axis;
                
                axis = packet->controllerState.rgucJoystickLeft[0] | ((packet->controllerState.rgucJoystickLeft[1] & 0xF) << 8);
                devController.lastLeftStickX = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = ((packet->controllerState.rgucJoystickLeft[1] & 0xF0) >> 4) | (packet->controllerState.rgucJoystickLeft[2] << 4);
                devController.lastLeftStickY = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = packet->controllerState.rgucJoystickRight[0] | ((packet->controllerState.rgucJoystickRight[1] & 0xF) << 8);
                devController.lastRightStickX = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = ((packet->controllerState.rgucJoystickRight[1] & 0xF0) >> 4) | (packet->controllerState.rgucJoystickRight[2] << 4);
                devController.lastRightStickY = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                
                if (self.controllerDriver == 0) {
                    
                    if (entry.lastSwitchState.controllerState.rgucButtons[0] != packet->controllerState.rgucButtons[0] ||
                        entry.lastSwitchState.controllerState.rgucButtons[1] != packet->controllerState.rgucButtons[1] ||
                        entry.lastSwitchState.controllerState.rgucButtons[2] != packet->controllerState.rgucButtons[2] ||
                        entry.lastSwitchState.controllerState.rgucJoystickLeft[0] != packet->controllerState.rgucJoystickLeft[0] ||
                        entry.lastSwitchState.controllerState.rgucJoystickLeft[1] != packet->controllerState.rgucJoystickLeft[1] ||
                        entry.lastSwitchState.controllerState.rgucJoystickRight[0] != packet->controllerState.rgucJoystickRight[0] ||
                        entry.lastSwitchState.controllerState.rgucJoystickRight[1] != packet->controllerState.rgucJoystickRight[1] ||
                        0)
                    {
                        [self sendControllerEventForEntry:entry];
                        entry.lastSwitchState = *packet;
                    }
                }
            }
        }
    }
}

void myHIDDeviceMatchingCallback(void * _Nullable        context,
                                IOReturn                result,
                                void * _Nullable        sender,
                                IOHIDDeviceRef          device) {
    HIDSupport *self = (__bridge HIDSupport *)context;

    [self entryForDevice:device];
    [self announceIdleControllersForNewStream];
    [self rumbleSync];
    [self publishControllerInventoryChange];
}

void myHIDDeviceRemovalCallback(void * _Nullable        context,
                                IOReturn                result,
                                void * _Nullable        sender,
                                IOHIDDeviceRef          device) {
    HIDSupport *self = (__bridge HIDSupport *)context;

    [self publishControllerInventoryChange];
    // Clean up the table for both drivers; only the HID driver sends a removal.
    NSString *key = [self deviceKeyForDevice:device];
    if (key != nil) {
        HIDDeviceControllerEntry *entry = self.deviceControllerTable[key];
        if (self.mouseModeEntry == entry) {
            [self setControllerMouseMode:NO forEntry:entry];
        }
        [self resetControllerStateForEntry:entry];
        [self.deviceControllerTable removeObjectForKey:key];
        // Clear even when arrival or its diagnostic completion did not succeed.
        [self sendControllerRemovalForEntry:entry];
    }
}


- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled {
    // Read per press rather than once at connect, so a player who turns the gesture off
    // because a game needs the Menu key gets it on the very next hold. The read carries its
    // own default, so a host with no stored preference behaves like a fresh install.
    return [SettingsClass gamepadMenuLongPressTogglesMouseModeFor:self.host.uuid];
}

- (void)updateButtonFlags:(int)flag entry:(HIDDeviceControllerEntry *)entry state:(BOOL)set {
    if (self.controllerDriver != 0 || entry == nil) return;
    @synchronized (self) {
        // Mouse Mode Toggle Logic: the same gesture the MFi path runs, asked of the same
        // function, so one switch and one timing boundary cover both controller drivers and
        // neither can drift away from the other (issue #45).
        if (flag == PLAY_FLAG) {
            MLGamepadMenuGesture gesture = entry.controller.menuGesture;
            const BOOL toggled = MLGamepadMenuGestureToggles(&gesture,
                                                             set ? YES : NO,
                                                             [NSDate date].timeIntervalSinceReferenceDate,
                                                             [self gamepadMenuLongPressTogglesMouseModeEnabled] ? YES : NO,
                                                             MLGamepadMenuLongPressRequiredSeconds);
            entry.controller.menuGesture = gesture;
            if (toggled) {
                [self setControllerMouseMode:!entry.controller.isMouseMode forEntry:entry];

                // Legacy rumble cannot target a pad yet. Keep single-pad feedback
                // without vibrating an unrelated pad in a multi-device session.
                if (self.deviceControllerTable.count == 1) {
                    [self rumbleLowFreqMotor:0xFFFF highFreqMotor:0xFFFF];
                    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                        [self rumbleLowFreqMotor:0 highFreqMotor:0];
                    });
                }
            }
        }

        // Physical mice and controller emulation share the remote ownership ledger.
        if (entry.controller.isMouseMode) {
            if (flag == A_FLAG || flag == B_FLAG) {
                [self sendMouseButton:flag == A_FLAG ? BUTTON_LEFT : BUTTON_RIGHT
                             pressed:set source:@"hid-controller"];
            }
        }

        if (set) {
            entry.controller.lastButtonFlags |= flag;
        } else {
            entry.controller.lastButtonFlags &= ~flag;
        }
    
        // Gamepad Quit Combo (Start + Select + LB + RB)
        int quitCombo = PLAY_FLAG | BACK_FLAG | LB_FLAG | RB_FLAG;
        if ((entry.controller.lastButtonFlags & quitCombo) == quitCombo) {
            dispatch_async(dispatch_get_main_queue(), ^{
                [[NSNotificationCenter defaultCenter] postNotificationName:HIDGamepadQuitNotification object:nil];
            });
            entry.controller.lastButtonFlags = 0;
        }
    }
}

- (void)setupHidManager {
    self.hidManager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    IOHIDManagerOpen(self.hidManager, kIOHIDOptionsTypeNone);
    
    NSArray *matches = @[
                         @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop), @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Joystick)},
                         @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop), @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_GamePad)},
                         @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop), @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_MultiAxisController)},
                         ];
    IOHIDManagerSetDeviceMatchingMultiple(self.hidManager, (__bridge CFArrayRef)matches);
    
    IOHIDManagerRegisterInputValueCallback(self.hidManager, myHIDCallback, (__bridge void * _Nullable)(self));
    IOHIDManagerRegisterInputReportCallback(self.hidManager, myHIDReportCallback, (__bridge void * _Nullable)(self));
    IOHIDManagerRegisterDeviceMatchingCallback(self.hidManager, myHIDDeviceMatchingCallback, (__bridge void * _Nullable)(self));
    IOHIDManagerRegisterDeviceRemovalCallback(self.hidManager, myHIDDeviceRemovalCallback, (__bridge void * _Nullable)(self));
    
    IOHIDManagerScheduleWithRunLoop(self.hidManager, CFRunLoopGetMain(), kCFRunLoopDefaultMode);
    
    self.rumbleSemaphore = dispatch_semaphore_create(0);
    self.rumbleQueue = dispatch_queue_create("rumbleQueue", nil);
    
    self.enableVibrationQueue = dispatch_queue_create("enableVibrationQueue", nil);

    self.hidReadSemaphore = dispatch_semaphore_create(0);

    __weak typeof(self) weakSelf = self;
    dispatch_async(self.rumbleQueue, ^{
        [weakSelf runRumbleLoop];
    });

    IOHIDDeviceRef device = [self getFirstDevice];
    if (device != nil) {
        if (isNintendo(device)) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1 * NSEC_PER_SEC)), self.enableVibrationQueue, ^{
                if (![self setVibrationEnabled:1]) {
                    NSLog(@"Couldn't enable vibration");
                }
            });
        }
    }
    [self publishControllerInventoryForSessionStart];
}

- (void)tearDownHidManager {
    // Ensure we're on the main thread for RunLoop operations
    if (![NSThread isMainThread]) {
        dispatch_sync(dispatch_get_main_queue(), ^{
            [self tearDownHidManagerOnMainThread];
        });
    } else {
        [self tearDownHidManagerOnMainThread];
    }
}

- (void)tearDownHidManagerOnMainThread {
    [self setControllerMouseMode:NO forEntry:self.mouseModeEntry];
    [self releaseMouseButtonsForSource:@"hid-controller"];
    [self tearDownCoreHIDMouseDriver];

    [[NSNotificationCenter defaultCenter] removeObserver:self.mouseConnectObserver];
    [[NSNotificationCenter defaultCenter] removeObserver:self.mouseDisconnectObserver];
    self.mouseConnectObserver = nil;
    self.mouseDisconnectObserver = nil;

    for (GCMouse *mouse in GCMouse.mice) {
        [self unregisterMouseCallbacks:mouse];
    }

    if (self.displayLink != NULL) {
        CVDisplayLinkStop(self.displayLink);
        CVDisplayLinkRelease(self.displayLink);
        self.displayLink = NULL;
    }

    self.closeRumble = YES;
    self.isRumbleTimer = NO;
    dispatch_semaphore_signal(self.rumbleSemaphore);

    self.rumbleQueue = nil;

    if (self.hidManager != NULL) {
        IOHIDManagerUnscheduleFromRunLoop(self.hidManager, CFRunLoopGetMain(), kCFRunLoopDefaultMode);
        IOHIDManagerClose(self.hidManager, kIOHIDOptionsTypeNone);
        CFRelease(self.hidManager);
        self.hidManager = NULL;
    }
    // The manager that recorded the bench is going away, so the record stops claiming a
    // stream is running. The entries stay: the report a player copies is usually copied
    // after the session that would have answered is over.
    [MLControllerInventory.sharedInventory noteSessionStopped];
}

#pragma mark - 0.2 per-device state table

// Entries belong to live IOHIDDevice objects, not model/serial groups. The HID
// manager owns these objects until removal; the removal callback deletes the key.
- (NSString *)deviceKeyForDevice:(IOHIDDeviceRef)device {
    return device == NULL ? nil : [NSString stringWithFormat:@"hid:%p", (void *)device];
}

- (HIDDeviceControllerEntry *)entryForDevice:(IOHIDDeviceRef)device {
    NSString *key = [self deviceKeyForDevice:device];
    if (key == nil) {
        return nil;
    }
    if (self.deviceControllerTable == nil) {
        self.deviceControllerTable = [NSMutableDictionary dictionary];
    }
    NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *table = self.deviceControllerTable;
    HIDDeviceControllerEntry *entry = table[key];
    if (entry == nil) {
        int slot = [self allocatePlayerSlot];
        if (slot < 0) return nil;
        entry = [[HIDDeviceControllerEntry alloc] init];
        // The bus owns the reference the callback hands over; this entry keeps its own,
        // released when the entry leaves the table (see the class's dealloc below).
        entry.hidDevice = (IOHIDDeviceRef)CFRetain((CFTypeRef)device);
        entry.controller = [[Controller alloc] init];
        entry.controller.menuGesture = MLGamepadMenuGestureIdle();
        entry.playerIndex = slot;
        entry.previousLowFreqMotor = 0xFF;
        entry.previousHighFreqMotor = 0xFF;
        entry.previousLEDRed = 0xFF;
        entry.previousLEDGreen = 0xFF;
        entry.previousLEDBlue = 0xFF;
        entry.previousLeftTriggerMotor = 0xFF;
        entry.previousRightTriggerMotor = 0xFF;
        // The layout decision is made once, from the device, at the moment the
        // entry exists: every later announce reads it instead of re-asking the bus.
        entry.protocolType = [self protocolTypeForDevice:device];
        entry.supportedButtonFlags = [self supportedButtonFlagsForDevice:device];
        // Same once-at-creation rule for capabilities: RGB is advertised only
        // for a pad that has a lightbar write, so the host stops asking an
        // Xbox or Switch for a color it can never be given.
        // Each capability is a promise the host will keep using, so it is
        // added only where this tree has a write that can honor it.
        uint16_t capabilities = kHIDArrivalCapabilities;
        if (isPS4(device) || isPS5(device)) {
            capabilities |= LI_CCAP_RGB_LED;
            // The PS4/PS5 state packets carry six-axis IMU samples that the
            // state-packet path already copies onto the entry, so a motion
            // request can be honored without a second report channel.
            capabilities |= LI_CCAP_ACCEL | LI_CCAP_GYRO;
            // The same packets carry a charge level, so the battery event is
            // honorable for these two families only.
            capabilities |= LI_CCAP_BATTERY_STATE;
            // The same packets carry two touch points, so the touchpad event
            // is honorable for these two families only.
            capabilities |= LI_CCAP_TOUCHPAD;
        }
        // Xbox/KingKong's trigger motors are the two fields of the standard
        // output report, so a trigger rumble is a real write. The PS families'
        // trigger motors are the adaptive-effect arrays (setAdaptiveTriggers
        // territory), which this path does not drive, so the bit stays off for
        // them until that lands.
        if (isXbox(device) || isKingKong(device)) {
            capabilities |= LI_CCAP_TRIGGER_RUMBLE;
        }
        entry.capabilities = capabilities;
        table[key] = entry;
    }
    return entry;
}

// Connection-order slot with reuse: lowest free index in the protocol's 16-slot
// space. A removal frees the slot for the next pad that plugs in.
- (int)allocatePlayerSlot {
    BOOL taken[16] = {0};
    for (HIDDeviceControllerEntry *e in [self deviceControllerTable].allValues) {
        if (e.playerIndex >= 0 && e.playerIndex < 16) {
            taken[e.playerIndex] = YES;
        }
    }
    for (int i = 0; i < 16; i++) {
        if (!taken[i]) {
            return i;
        }
    }
    return -1;
}

- (void)resetControllerStateForEntry:(HIDDeviceControllerEntry *)entry {
    entry.controller.lastButtonFlags = 0;
    entry.controller.lastLeftTrigger = 0;
    entry.controller.lastRightTrigger = 0;
    entry.controller.lastLeftStickX = 0;
    entry.controller.lastLeftStickY = 0;
    entry.controller.lastRightStickX = 0;
    entry.controller.lastRightStickY = 0;
    // Removal ends the pad's sensor session: the entry leaves the table, so
    // its activation must go with it. Stream end keeps the table, and clears
    // the same fields from setInputContext.
    [self stopMotionEventsForEntry:entry];
    // A re-plug may be on a different charge state than the removed pad, so
    // the new session's first reading must not be suppressed as a repeat.
    entry.previousBatteryState = 0xFF;
    entry.previousBatteryPercentage = 0xFF;
    // A re-plug starts from "no finger on the pad", so the touch session
    // state must go with the entry.
    entry.touchPressed = NO;
    entry.touchPressed2 = NO;
    entry.touchPointerId = 0;
    entry.touchLastX = 0.0f;
    entry.touchLastY = 0.0f;
    entry.touchPointerId2 = 0;
    entry.touchLastX2 = 0.0f;
    entry.touchLastY2 = 0.0f;
}

// setMotionEventState: the host names the pad by player index and asks for
// (or stops) one sensor type. Bit layout matches the LI_MOTION_TYPE_* values
// themselves, so the requested type doubles as its own activation bit. The
// pad resolves through the same per-number path as rumble and the lightbar,
// so a request for a slot no device owns is a no-op with the same fallback
// behavior those writes already have.
- (void)setMotionEventStateForControllerNumber:(int)number motionType:(uint8_t)motionType reportRateHz:(uint16_t)reportRateHz {
    if (self.controllerDriver != 0 || number < 0 || number >= 16 ||
        (motionType != LI_MOTION_TYPE_ACCEL && motionType != LI_MOTION_TYPE_GYRO)) {
        return;
    }
    HIDDeviceControllerEntry *entry = nil;
    for (HIDDeviceControllerEntry *candidate in self.deviceControllerTable.allValues) {
        if (candidate.playerIndex == number) {
            entry = candidate;
            break;
        }
    }
    if (entry == nil) {
        IOHIDDeviceRef device = [self getFirstDevice];
        if (device != NULL) {
            entry = [self entryForDevice:device];
        }
    }
    if (entry == nil) {
        return;
    }
    if (reportRateHz == 0) {
        entry.motionActiveTypes &= (uint8_t)~motionType;
        if (motionType == LI_MOTION_TYPE_GYRO) {
            entry.motionGyroIntervalMs = 0;
        } else {
            entry.motionAccelIntervalMs = 0;
        }
        return;
    }
    // Only PS4/PS5 state packets carry six-axis samples, so an activation
    // request for anything else never produces a frame; leaving the bit set
    // would only make the push path take a device check per state packet.
    if (!isPS4(entry.hidDevice) && !isPS5(entry.hidDevice)) {
        return;
    }
    entry.motionActiveTypes |= motionType;
    // The host asked for reportRateHz; the pad's state packets run at their
    // own cadence, so the request becomes a minimum send interval. A 0 Hz
    // value would mean "as slow as possible" on the wire, but the host uses
    // 0 for stop, so any nonzero rate here clamps to at most 1 ms apart.
    const uint16_t intervalMs = (reportRateHz >= 1000) ? 1 : (uint16_t)(1000 / reportRateHz);
    if (motionType == LI_MOTION_TYPE_GYRO) {
        entry.motionGyroIntervalMs = intervalMs;
    } else {
        entry.motionAccelIntervalMs = intervalMs;
    }
}

// The one call site for "this pad's sensors are done": removal, stream end
// and the host's explicit stop all converge here so the clear cannot drift
// between paths.
- (void)stopMotionEventsForEntry:(HIDDeviceControllerEntry *)entry {
    if (entry == nil) {
        return;
    }
    entry.motionActiveTypes = 0;
    entry.motionAccelIntervalMs = 0;
    entry.motionGyroIntervalMs = 0;
}

// Push half of the motion path, called from the state-packet branch when the
// 12 sensor bytes moved. The sample comes from the family's own snapshot
// (the PS5 packet stores the same six axes in the same fields, typed as
// PS5StatePacket_t). A type the host has not activated sends nothing; the
// rate limit is the minimum send interval recorded at activation. Sampling
// is bounded by the pad's state-packet rate either way, and the C layer
// coalesces whatever slips through into one queued packet per type.
- (void)pushMotionEventsForEntry:(HIDDeviceControllerEntry *)entry {
    // P2-3b: motion events stay gated on suspendControllerEvents so a player
    // who stepped away does not keep the host IMU stream alive in the
    // background (which would burn battery on the pad and confuse the host
    // about which pad is still in play).
    if (self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents ||
        entry.motionActiveTypes == 0) {
        return;
    }
    // Both families store the six axes as six little-endian int16 pairs in
    // the same fields, so the sample read is one code path per family: a
    // copy of the family's own snapshot, decoded axis by axis.
    const BOOL ps5 = isPS5(entry.hidDevice);
    const int16_t gx = ps5 ? (int16_t)(entry.lastPS5State.rgucGyroX[0] | (entry.lastPS5State.rgucGyroX[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucGyroX[0] | (entry.lastPS4State.rgucGyroX[1] << 8));
    const int16_t gy = ps5 ? (int16_t)(entry.lastPS5State.rgucGyroY[0] | (entry.lastPS5State.rgucGyroY[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucGyroY[0] | (entry.lastPS4State.rgucGyroY[1] << 8));
    const int16_t gz = ps5 ? (int16_t)(entry.lastPS5State.rgucGyroZ[0] | (entry.lastPS5State.rgucGyroZ[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucGyroZ[0] | (entry.lastPS4State.rgucGyroZ[1] << 8));
    const int16_t ax = ps5 ? (int16_t)(entry.lastPS5State.rgucAccelX[0] | (entry.lastPS5State.rgucAccelX[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucAccelX[0] | (entry.lastPS4State.rgucAccelX[1] << 8));
    const int16_t ay = ps5 ? (int16_t)(entry.lastPS5State.rgucAccelY[0] | (entry.lastPS5State.rgucAccelY[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucAccelY[0] | (entry.lastPS4State.rgucAccelY[1] << 8));
    const int16_t az = ps5 ? (int16_t)(entry.lastPS5State.rgucAccelZ[0] | (entry.lastPS5State.rgucAccelZ[1] << 8))
                           : (int16_t)(entry.lastPS4State.rgucAccelZ[0] | (entry.lastPS4State.rgucAccelZ[1] << 8));
    // PS4 raw units follow the SDL HIDAPI PS4 driver (the upstream sensor
    // source): 16 counts per deg/s, 8192 counts per g. PS5 is 1024 per deg/s
    // with the same accelerometer range, per SDL_hidapi_ps5.
    const float gyroDiv = isPS5(entry.hidDevice) ? 1024.0f : 16.0f;
    const float accelDiv = 8192.0f;
    const float g = 9.80665f;
    const uint8_t types = entry.motionActiveTypes;
    const uint64_t nowMs = (uint64_t)([[NSDate date] timeIntervalSince1970] * 1000.0);
    for (uint8_t type = LI_MOTION_TYPE_ACCEL; type <= LI_MOTION_TYPE_GYRO; type <<= 1) {
        if ((types & type) == 0) {
            continue;
        }
        const float x = (type == LI_MOTION_TYPE_ACCEL) ? (ax / accelDiv) * g : gx / gyroDiv;
        const float y = (type == LI_MOTION_TYPE_ACCEL) ? (ay / accelDiv) * g : gy / gyroDiv;
        const float z = (type == LI_MOTION_TYPE_ACCEL) ? (az / accelDiv) * g : gz / gyroDiv;
        [self sendMotionSampleToHostForEntry:entry motionType:type x:x y:y z:z nowMs:nowMs];
    }
}

- (void)sendMotionSampleToHostForEntry:(HIDDeviceControllerEntry *)entry
                            motionType:(uint8_t)motionType
                                   x:(float)x y:(float)y z:(float)z
                               nowMs:(uint64_t)nowMs {
    int slot = entry.playerIndex;
    if (slot < 0 || slot >= 16 || entry.hidDevice == NULL) {
        return;
    }
    // Both sensor types ride the same state packet, so each type keeps its
    // own pacing guard: the host's Hz request became a minimum interval at
    // activation, and the first frame of a type is always sent because its
    // stamp starts at 0.
    const BOOL isGyro = (motionType == LI_MOTION_TYPE_GYRO);
    uint64_t stamp = isGyro ? entry.lastMotionGyroAtMs : entry.lastMotionAccelAtMs;
    uint16_t interval = isGyro ? entry.motionGyroIntervalMs : entry.motionAccelIntervalMs;
    if (interval == 0) {
        // Defensive: an active type without an interval is a request we did
        // not record; do not turn it into a per-packet flood.
        interval = 1;
    }
    if (stamp != 0 && nowMs - stamp < interval) {
        return;
    }
    if (isGyro) {
        entry.lastMotionGyroAtMs = nowMs;
    } else {
        entry.lastMotionAccelAtMs = nowMs;
    }
    HIDInputLease lease = HIDAcquireInputContext(self);
    if (lease.context == NULL) {
        return;
    }
    HIDDispatchInput(self, lease, ^{
        LiSendControllerMotionEventCtx(lease.context, (uint8_t)slot, motionType, x, y, z);
    });
}

// Push the battery path, called from the state-packet branch when the
// ucBatteryLevel byte moved. Both PS families store it in the same field and
// with the same layout (per SDL HIDAPI): the low nibble is a 0-10 charge
// level and bit 0x10 means the pad is on the wire (wired/charging dock).
// Wired pads carry a meaningless level, so they report NOT_CHARGING with an
// unknown percentage rather than a fake 0%. A level change is rare, so there
// is no pacing guard - only the same per-device dedup the LED and motor
// writes use, so the host's first reading is always honored (0xFF = never
// sent this session).
- (void)pushBatteryEventForEntry:(HIDDeviceControllerEntry *)entry {
    // P2-3b: battery changes are rare and reportable on their own; they
    // stay gated on suspendControllerEvents so a level read while the app
    // is in the background does not surface to the host until the player
    // is back to read it.
    if (self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents) {
        return;
    }
    const uint8_t raw = isPS5(entry.hidDevice) ? entry.lastPS5State.ucBatteryLevel
                                               : entry.lastPS4State.ucBatteryLevel;
    uint8_t state;
    uint8_t percentage;
    if (raw & 0x10) {
        state = LI_BATTERY_STATE_NOT_CHARGING;
        percentage = LI_BATTERY_PERCENTAGE_UNKNOWN;
    } else {
        state = LI_BATTERY_STATE_DISCHARGING;
        percentage = (uint8_t)((raw & 0x0F) * 10);
    }
    if (state == entry.previousBatteryState &&
        percentage == entry.previousBatteryPercentage) {
        return;
    }
    entry.previousBatteryState = state;
    entry.previousBatteryPercentage = percentage;
    int slot = entry.playerIndex;
    if (slot < 0 || slot >= 16 || entry.hidDevice == NULL) {
        return;
    }
    HIDInputLease lease = HIDAcquireInputContext(self);
    if (lease.context == NULL) {
        return;
    }
    HIDDispatchInput(self, lease, ^{
        LiSendControllerBatteryEventCtx(lease.context, (uint8_t)slot, state, percentage);
    });
}

// PS touchpad encoding follows the SDL HIDAPI PS4/PS5 driver: the top bit of
// the counter is clear while the finger is down, the low seven bits count
// presses (a stable identifier for the duration of one press), and the three
// data bytes carry the 12-bit X/Y. Two physical touch points ride the same
// packet, so each one is tracked independently below.

- (void)sendControllerTouchForEntry:(HIDDeviceControllerEntry *)entry
                            pointer:(uint32_t)pointerId
                            eventType:(uint8_t)eventType
                                  x:(float)x y:(float)y pressure:(float)pressure {
    int slot = entry.playerIndex;
    if (slot < 0 || slot >= 16 || entry.hidDevice == NULL) {
        return;
    }
    HIDInputLease lease = HIDAcquireInputContext(self);
    if (lease.context == NULL) {
        return;
    }
    HIDDispatchInput(self, lease, ^{
        // M4 退化路径: the family advertises the touchpad, but whether the host
        // can draw it is the host's answer, not the pad's. A host that did not set
        // LI_FF_CONTROLLER_TOUCH_EVENTS ignores the reports, so sending them is
        // churn the pad pays for on every frame the finger moves. The flag is read
        // on the same context the event rides, inside the same dispatch, so a
        // generation mismatch still suppresses the whole packet.
        if ((LiGetHostFeatureFlagsCtx(lease.context->connectionContext) & LI_FF_CONTROLLER_TOUCH_EVENTS) == 0) {
            return;
        }
        LiSendControllerTouchEventCtx(lease.context, (uint8_t)slot, eventType, pointerId, x, y, pressure);
    });
}

// Push one touch point of the PS touchpad, called from the state-packet branch
// when the eight touch bytes moved. The raw byte layout differs only in field
// order between the two families, so each family hands over its own decoded
// (active, pointerId, x12, y12) and the transition logic is shared.
- (void)pushControllerTouchForEntry:(HIDDeviceControllerEntry *)entry {
    // P2-3b: the touchpad path is a controller wire surface, so it honours
    // the focus-loss suspension like arrival / axis / motion / battery.
    if (self.controllerDriver != 0 || !self.shouldSendInputEvents ||
        self.suspendControllerEvents) {
        return;
    }
    // A value copy, not &entry.lastPS4State: the property returns the struct
    // by value, and taking the address of a property expression is a warning.
    // Both families carry the two touch points in the same eight bytes, so the
    // decode is one code path per family handed to the shared transition logic.
    if (isPS5(entry.hidDevice)) {
        PS5StatePacket_t s = entry.lastPS5State;
        BOOL active1 = !(s.ucTouchpadCounter1 & 0x80);
        uint8_t id1 = s.ucTouchpadCounter1 & 0x7F;
        float x1 = (float)(s.rgucTouchpadData1[0] | ((s.rgucTouchpadData1[1] & 0x0F) << 8)) / 4095.0f;
        float y1 = (float)((s.rgucTouchpadData1[1] >> 4) | (s.rgucTouchpadData1[2] << 4)) / 4095.0f;
        BOOL active2 = !(s.ucTouchpadCounter2 & 0x80);
        uint8_t id2 = s.ucTouchpadCounter2 & 0x7F;
        float x2 = (float)(s.rgucTouchpadData2[0] | ((s.rgucTouchpadData2[1] & 0x0F) << 8)) / 4095.0f;
        float y2 = (float)((s.rgucTouchpadData2[1] >> 4) | (s.rgucTouchpadData2[2] << 4)) / 4095.0f;
        [self dispatchTouchForEntry:entry active:active1 id:id1 x:x1 y:y1
                                active2:active2 id2:id2 x2:x2 y2:y2];
    } else {
        PS4StatePacket_t s = entry.lastPS4State;
        BOOL active1 = !(s.ucTouchpadCounter1 & 0x80);
        uint8_t id1 = s.ucTouchpadCounter1 & 0x7F;
        float x1 = (float)(s.rgucTouchpadData1[0] | ((s.rgucTouchpadData1[1] & 0x0F) << 8)) / 4095.0f;
        float y1 = (float)((s.rgucTouchpadData1[1] >> 4) | (s.rgucTouchpadData1[2] << 4)) / 4095.0f;
        BOOL active2 = !(s.ucTouchpadCounter2 & 0x80);
        uint8_t id2 = s.ucTouchpadCounter2 & 0x7F;
        float x2 = (float)(s.rgucTouchpadData2[0] | ((s.rgucTouchpadData2[1] & 0x0F) << 8)) / 4095.0f;
        float y2 = (float)((s.rgucTouchpadData2[1] >> 4) | (s.rgucTouchpadData2[2] << 4)) / 4095.0f;
        [self dispatchTouchForEntry:entry active:active1 id:id1 x:x1 y:y1
                                active2:active2 id2:id2 x2:x2 y2:y2];
    }
}

// The shared transition machine for both touch points. A finger going from
// absent to present is a DOWN (its pointer id is captured once and reused for
// the whole press); a present finger moving is a MOVE (re-sent only when the
// position changed); present to absent is an UP. Pressure is 1.0 while down
// and 0.0 on the up edge.
- (void)dispatchTouchForEntry:(HIDDeviceControllerEntry *)entry
                       active:(BOOL)active id:(uint8_t)id
                        x:(float)x y:(float)y
                     active2:(BOOL)active2 id2:(uint8_t)id2
                        x2:(float)x2 y2:(float)y2 {
    BOOL pressed = entry.touchPressed;
    uint32_t pid = pressed ? entry.touchPointerId : (uint32_t)id;
    if (active && !pressed) {
        entry.touchPressed = YES;
        entry.touchPointerId = pid;
        entry.touchLastX = x;
        entry.touchLastY = y;
        [self sendControllerTouchForEntry:entry pointer:pid eventType:LI_TOUCH_EVENT_DOWN x:x y:y pressure:1.0f];
    } else if (active && pressed) {
        if (x != entry.touchLastX || y != entry.touchLastY) {
            entry.touchLastX = x;
            entry.touchLastY = y;
            [self sendControllerTouchForEntry:entry pointer:pid eventType:LI_TOUCH_EVENT_MOVE x:x y:y pressure:1.0f];
        }
    } else if (!active && pressed) {
        entry.touchPressed = NO;
        entry.touchLastX = 0.0f;
        entry.touchLastY = 0.0f;
        [self sendControllerTouchForEntry:entry pointer:pid eventType:LI_TOUCH_EVENT_UP x:x y:y pressure:0.0f];
    }

    BOOL pressed2 = entry.touchPressed2;
    uint32_t pid2 = pressed2 ? entry.touchPointerId2 : (uint32_t)id2;
    if (active2 && !pressed2) {
        entry.touchPressed2 = YES;
        entry.touchPointerId2 = pid2;
        entry.touchLastX2 = x2;
        entry.touchLastY2 = y2;
        [self sendControllerTouchForEntry:entry pointer:pid2 eventType:LI_TOUCH_EVENT_DOWN x:x2 y:y2 pressure:1.0f];
    } else if (active2 && pressed2) {
        if (x2 != entry.touchLastX2 || y2 != entry.touchLastY2) {
            entry.touchLastX2 = x2;
            entry.touchLastY2 = y2;
            [self sendControllerTouchForEntry:entry pointer:pid2 eventType:LI_TOUCH_EVENT_MOVE x:x2 y:y2 pressure:1.0f];
        }
    } else if (!active2 && pressed2) {
        entry.touchPressed2 = NO;
        entry.touchLastX2 = 0.0f;
        entry.touchLastY2 = 0.0f;
        [self sendControllerTouchForEntry:entry pointer:pid2 eventType:LI_TOUCH_EVENT_UP x:x2 y:y2 pressure:0.0f];
    }
}

@end

@implementation HIDDeviceControllerEntry
// The entry owns one reference to its device: retained when it joins the table and
// released here, so a removal callback that drops the entry cannot outlive a
// write path that still resolves the pad through entryForDevice.
- (void)dealloc
{
    if (_hidDevice != NULL) {
        CFRelease(_hidDevice);
    }
}
@end

