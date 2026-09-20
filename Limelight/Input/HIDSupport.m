//
//  HIDSupport.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 26/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//
#import "HIDSupport_Internal.h"
#import "GamepadMenuGesture.h"
#import "KeyboardMapResolver.h"

#import <IOKit/hid/IOHIDElement.h>
#import <IOKit/hidsystem/IOLLEvent.h>

// ---------------------------------------------------------------------------
// CI/CD Pipeline Refactor (2026-08-02): KeyboardMapResolver bridge
//
// The 4 DUPLICATED switch/case blocks that previously defined modifier-key
// mappings have been REMOVED and all callers now route through KMR_*()
// in KeyboardMapResolver.{h,m}.
// This guarantees that, for any keyboard state, "what L⌘ maps to"
// has exactly ONE answer across the entire application.
//
// SIMPLIFIED MODE: We now use the Industry Standard Streaming Mapping.
// There are no more "compatibility modes" - the mapping is fixed and final:
// macOS Command -> Windows Win
// macOS Control -> Windows Control
// macOS Option -> Windows Alt
// macOS Shift -> Windows Shift
// ---------------------------------------------------------------------------

// CVDisplayLink is deprecated in macOS 15.0 but remains the recommended API
// for low-latency game input polling. The new NSView.displayLink API is not
// yet validated for sub-frame input latency. Suppress deprecation at file
// scope; tracked for migration in a future release.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"


NSString *const HIDMouseModeToggledNotification = @"HIDMouseModeToggledNotification";
NSString *const HIDGamepadQuitNotification = @"HIDGamepadQuitNotification";


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
    // -----------------------------------------------------------------------
    // CRITICAL FIX (2026-08-02): DO NOT infer physical modifier state from
    // event.modifierFlags for mouse events.
    //
    // This was the ROOT CAUSE of the "double-click sends Win key" bug:
    // When the user pressed-and-held the Mac Command (⌘) key and then
    // clicked the mouse button, mouse event.modifierFlags naturally
    // included NSEventModifierFlagCommand. The previous code used those
    // bits to FORCE-INJECT the "LeftCommand pressed" state into
    // physicalMask, which then caused syncKeyboardModifierStateForEvent()
    // to emit a VK_LWIN (0x5B) down event to the remote PC. The same
    // applied for any modifier held during a mouse click (Ctrl→LCtrl,
    // Option→LAlt, Shift→LShift).
    //
    // Under the STREAMING STANDARD (Parsec/UU Remote):
    // * Physical modifier key down/up is tracked ONLY from kVK_* key
    //   events received by flagsChanged:/keyDown:/keyUp:.
    // * Mouse events are NOT permitted to mutate the modifier state.
    // * The physicalMask is therefore returned AS-IS, regardless of
    //   what event.modifierFlags says.
    // -----------------------------------------------------------------------
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
    // SIMPLIFIED: Always use the standard streaming mapping.
    // No more compatibility modes.
    KMR_PhysicalModifier phys = KMR_PhysicalFromKeyCode(keyCode);
    if (phys == KMR_Phys_Count) {
        return 0;
    }
    return (NSUInteger)KMR_RemoteMaskForPhysical(phys);
}

static void HIDDispatchSyntheticRemoteModifierTap(HIDSupport *support,
                                                  NSUInteger remoteModifierMask,
                                                  const char *op) {
    if (remoteModifierMask == 0) {
        return;
    }

    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(support);
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
    HIDDispatchInput(support, inputCtx, ^{
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

- (void)setInputContext:(void *)inputContext {
    _inputContext = inputContext;
    [self syncScrollTraceDiagnosticsPreferenceToInputContext];
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

- (void)syncScrollTraceDiagnosticsPreferenceToInputContext {
    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
    LiSetScrollTraceDiagnosticsEnabledCtx(inputCtx, self.inputDiagnosticsEnabled ? true : false);
}

- (uint64_t)prepareScrollTraceFromSource:(NSString *)source
                               rawDeltaX:(CGFloat)rawDeltaX
                               rawDeltaY:(CGFloat)rawDeltaY
                                   phase:(NSEventPhase)phase
                           momentumPhase:(NSEventPhase)momentumPhase
                        hasPreciseDeltas:(BOOL)hasPreciseDeltas {
    [self syncScrollTraceDiagnosticsPreferenceToInputContext];
    if (!self.inputDiagnosticsEnabled) {
        return 0;
    }

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

    if (startsNewTrace) {
        PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
        LiStartScrollTraceCtx(inputCtx, traceId, nowMs);
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
    if ([self reserveDetailedInputDiagnosticsLogSequence:&sequence]) {
        Log(LOG_D, @"[inputdiag] #%lu mouse-button action=%@ button=%d mask=0x%02X synthetic=%d ctx=%p",
            (unsigned long)sequence,
            action ?: @"unknown",
            button,
            (unsigned int)mask,
            synthetic ? 1 : 0,
            self.inputContext);
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
    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);

    NSUInteger sequence = 0;
    BOOL shouldLog = NO;
    @synchronized (self.inputDiagnosticsLock) {
        if (self.inputDiagnosticsRemainingScrollDetailedLogs > 0) {
            self.inputDiagnosticsDetailedLogSequence += 1;
            self.inputDiagnosticsRemainingScrollDetailedLogs -= 1;
            sequence = self.inputDiagnosticsDetailedLogSequence;
            shouldLog = YES;
        }
    }

    if (shouldLog) {
        uint64_t traceStartMs = LiGetScrollTraceStartMsCtx(inputCtx);
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
        self.inputQueue = dispatch_queue_create("com.moonlight.input", DISPATCH_QUEUE_SERIAL);
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
        [self resetInputDiagnostics];

        // SIMPLIFIED: Print the active keyboard mapping matrix once at init.
        // In the new "Streaming Standard" mode, the mapping is fixed (Cmd->Win, etc.)
        // and does not depend on any compatibility flags.
        KMR_LogActiveMapping();
        Log(LOG_I, @"[kbmap] HIDSupport init: Mode = Streaming Standard (Cmd->Win, Ctrl->Ctrl, Option->Alt)");

        [self setupHidManager];
        
        self.ticks = [[Ticks alloc] init];
        self.switchUsingBluetooth = YES;
        
        self.previousLowFreqMotor = 0xFF;
        self.previousHighFreqMotor = 0xFF;

        [self rumbleSync];

        self.controller = [[Controller alloc] init];
        
        for (GCMouse *mouse in GCMouse.mice) {
            [self registerMouseCallbacks:mouse];
        }
        
        self.mouseConnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidConnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification * _Nonnull note) {
            [self registerMouseCallbacks:note.object];
        }];
        self.mouseDisconnectObserver = [[NSNotificationCenter defaultCenter] addObserverForName:GCMouseDidDisconnectNotification object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification * _Nonnull note) {
            [self unregisterMouseCallbacks:note.object];
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
    [self tearDownCoreHIDMouseDriver];
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


- (void)sendControllerEvent {
    if (self.shouldSendInputEvents) {
        // Capture state
        int playerIndex = self.controller.playerIndex;
        int lastButtonFlags = self.controller.lastButtonFlags;
        
        // Guide Button Emulation (Start + Select)
        // If both Start and Select are pressed, convert to Guide
        if ((lastButtonFlags & (PLAY_FLAG | BACK_FLAG)) == (PLAY_FLAG | BACK_FLAG)) {
            lastButtonFlags &= ~(PLAY_FLAG | BACK_FLAG);
            lastButtonFlags |= SPECIAL_FLAG;
        }
        
        unsigned char lastLeftTrigger = self.controller.lastLeftTrigger;
        unsigned char lastRightTrigger = self.controller.lastRightTrigger;
        short lastLeftStickX = self.controller.lastLeftStickX;
        short lastLeftStickY = self.controller.lastLeftStickY;
        short lastRightStickX = self.controller.lastRightStickX;
        short lastRightStickY = self.controller.lastRightStickY;
        
        if (self.controller.isMouseMode) {
            return;
        }

        PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
        if (!inputCtx) {
            return;
        }
        HIDDispatchInput(self, inputCtx, ^{
            LiSendMultiControllerEventCtx(inputCtx, playerIndex, 1, lastButtonFlags, lastLeftTrigger, lastRightTrigger, lastLeftStickX, lastLeftStickY, lastRightStickX, lastRightStickY);
        });
    }
}

- (KeyboardCompatibilityMode)keyboardCompatibilityMode {
    return (KeyboardCompatibilityMode)[SettingsClass keyboardCompatibilityModeFor:self.host.uuid];
}

- (BOOL)usesKeyboardCommandToControlCompatibility {
    // SIMPLIFIED: Always return NO. Legacy compatibility mode disabled.
    return NO;
}

- (BOOL)usesKeyboardLeftControlWinSwapCompatibility {
    // SIMPLIFIED: Always return NO. Legacy compatibility mode disabled.
    return NO;
}

- (BOOL)usesKeyboardShortcutTranslationCompatibility {
    // SIMPLIFIED: Always return NO. Legacy compatibility mode disabled.
    return NO;
}

- (BOOL)usesKeyboardMoonlightClassicMapping {
    // SIMPLIFIED: Always return NO. Legacy compatibility mode disabled.
    return NO;
}

- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event {
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

- (BOOL)shouldApplyKeyboardShortcutTranslationForEvent:(NSEvent *)event {
    if (![self usesKeyboardShortcutTranslationCompatibility] || event == nil) {
        return NO;
    }

    if ((event.modifierFlags & NSEventModifierFlagCommand) == 0) {
        return NO;
    }

    if (event.type != NSEventTypeKeyDown && event.type != NSEventTypeKeyUp) {
        return NO;
    }

    if (HIDIsModifierKeyCode(event.keyCode)) {
        return NO;
    }

    return YES;
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
    for (size_t i = 0; i < sizeof(kMap) / sizeof(kMap[0]); i++) {
        if ((physical & kMap[i].physMask) == 0) {
            continue;
        }
        desired |= (NSUInteger)KMR_RemoteMaskForPhysical(kMap[i].physEnum);
    }
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
    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
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
    HIDDispatchInput(self, inputCtx, ^{
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
    if (self.keyboardSuppressedKeyDownKeyCodes == nil) {
        self.keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
    }
    [self.keyboardSuppressedKeyDownKeyCodes addObject:@(event.keyCode)];
}

- (void)keyDown:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyDown) {
        return;
    }

    // Real keyboard events only. keyCode is undefined on mouse, tablet and
    // gesture events, and some drivers leave garbage there that collides with
    // kVK_ANSI_C - reading it is what caused "double-click sends C". The type
    // gate below is the complete fix; no timing or glyph heuristics are needed
    // (and every previous attempt at those dropped genuine gameplay input).
    if (self.shouldSendInputEvents) {
        // This press is going through, so any record of an earlier suppressed
        // press of the same key is stale: keeping it would swallow this release
        // and leave the key held down on the host forever.
        [self.keyboardSuppressedKeyDownKeyCodes removeObject:@(event.keyCode)];
        [self syncKeyboardModifierStateForEvent:event];
        short translated = [self translateKeyCodeWithEvent:event];
        if (translated == 0) {
            // Zero is not a virtual key, it is the table saying it has no entry for
            // this hardware: the ISO section key, the JIS keys, and any code a new
            // keyboard adds. Sending zero hands the host a key that does not exist;
            // ignoring the key is the honest answer, and ignoring it on both edges
            // is what keeps the press and the release paired.
            Log(LOG_D, @"[input] Ignoring unmapped key: keyCode=%hu", event.keyCode);
            return;
        }
        short keyCode = 0x8000 | translated;
        char modifiers = [self translateKeyModifierWithEvent:event];
        PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
        if (!HIDValidateInputContext(inputCtx, "keyDown")) {
            return;
        }
        // Record the press under the physical key that produced it, holding the
        // exact encoding that is about to be dispatched, so capture can end
        // safely with this key still held down. Keying by the dispatched code
        // would make Return and Keypad Enter share one slot and let the release
        // of one spend the record of the other.
        self.keyboardForwardedKeyDownKeyCodes[@(event.keyCode)] = @(keyCode);
        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
        });
    }
}

- (void)keyUp:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyUp) {
        return;
    }
    if (self.shouldSendInputEvents) {
        NSNumber *physicalKeyCode = @(event.keyCode);
        if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {
            // The host never saw this key go down, so it must not see it come up
            // either: an unmatched release reads as the key being let go by
            // itself, which is what made local shortcuts look like gameplay keys
            // releasing mid-action.
            [self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];
            return;
        }

        [self syncKeyboardModifierStateForEvent:event];
        short translated = [self translateKeyCodeWithEvent:event];
        if (translated == 0) {
            // The press was ignored for the same reason, so the release must be
            // ignored too rather than reaching the host on its own.
            return;
        }
        short keyCode = 0x8000 | translated;
        char modifiers = [self translateKeyModifierWithEvent:event];
        // This release is going through, so the held-key record for this
        // physical key is spent - and only this one. Two Mac keys can share a
        // dispatched code, so spending by that code would forget a key the
        // player is still holding.
        [self.keyboardForwardedKeyDownKeyCodes removeObjectForKey:@(event.keyCode)];
        PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
        if (!HIDValidateInputContext(inputCtx, "keyUp")) {
            return;
        }
        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_UP, modifiers);
        });
    }
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

    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
    if (!inputCtx) {
        self.keyboardModifierReleaseInProgress = NO;
        return;
    }
    HIDDispatchInput(self, inputCtx, ^{
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

    // Take the records out first: a stray keyUp: racing on the main queue must
    // not find a record it can pair with a release we are already sending.
    // Every physical press gets its own release, even when two of them were
    // dispatched as the same code; a repeated release is inert on the host, a
    // missing one is a key that stays down for the rest of the session.
    NSArray<NSNumber *> *held = self.keyboardForwardedKeyDownKeyCodes.allValues;
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    if (held.count == 0) {
        self.keyboardHeldKeyReleaseInProgress = NO;
        return;
    }

    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
    if (!HIDValidateInputContext(inputCtx, "releaseAllHeldKeys")) {
        self.keyboardHeldKeyReleaseInProgress = NO;
        return;
    }
    HIDDispatchInput(self, inputCtx, ^{
        for (NSNumber *keyCode in held) {
            LiSendKeyboardEventCtx(inputCtx, keyCode.shortValue, KEY_ACTION_UP, 0);
        }
    });
    Log(LOG_I, @"[input] Released %lu held key(s) as input forwarding turned off", (unsigned long)held.count);

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
    [self.keyboardSuppressedKeyDownKeyCodes removeAllObjects];
    Log(LOG_I, @"[teardown] tearDownKeyboardStateForSessionEnd[%s]: start (physicalMask=0x%lx remoteMask=0x%lx send=%d)",
        reason ?: "",
        (unsigned long)self.keyboardPhysicalModifierSourceMask,
        (unsigned long)self.keyboardRemoteModifierMask,
        self.shouldSendInputEvents ? 1 : 0);

    // 0) Release keys the host still believes are pressed, before input is
    //    switched off, so an action key held at disconnect cannot stay stuck.
    [self releaseAllHeldKeys];

    // 1) Release remote modifier state FIRST, while inputContext may still
    //    be valid. This sends 8 KEY_ACTION_UP packets so the remote PC
    //    never ends a session with a stuck Win/Ctrl/Alt/Shift key.
    [self releaseAllModifierKeys];

    // 2) Release pressed mouse buttons before we drop input events.
    //    Pointer:releaseAllPressedMouseButtons is reentry-safe.
    [self releaseAllPressedMouseButtons];

    // 3) Disable further input event processing so any events still
    //    in flight on the main queue become a no-op instead of trying
    //    to talk to a dead Limelight context.
    self.shouldSendInputEvents = NO;

    Log(LOG_I, @"[teardown] tearDownKeyboardStateForSessionEnd[%s]: done", reason ?: "");
}

- (void)beginDeferredShortcutTranslationCommandHoldForKeyCode:(unsigned short)keyCode {
    // Legacy deferred-Command logic removed entirely. No-op.
    (void)keyCode;
}

- (void)endDeferredShortcutTranslationCommandHoldForKeyCode:(unsigned short)keyCode {
    // Legacy deferred-Command logic removed entirely. No-op.
    (void)keyCode;
}

- (void)sendSyntheticRemoteModifierTapForFlags:(NSEventModifierFlags)modifierFlags {
    // SIMPLIFIED: Use the standard streaming mapping.
    NSEventModifierFlags relevantFlags = [StreamShortcutProfile relevantModifierFlags:modifierFlags];
    NSUInteger remoteModifierMask = (NSUInteger)KMR_RemoteMaskForAppKitFlags(relevantFlags);
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

    NSNumber *mappedKey = [self.mappings objectForKey:@(shortcut.keyCode)];
    if (mappedKey == nil) {
        return;
    }

    // SIMPLIFIED: Use the standard streaming mapping.
    NSEventModifierFlags modifierFlags = [StreamShortcutProfile relevantModifierFlags:shortcut.modifierFlags];
    NSUInteger remoteModifierMask = (NSUInteger)KMR_RemoteMaskForAppKitFlags(modifierFlags);

    char translatedModifiers = HIDRemoteModifierFlagsToGenericFlags(remoteModifierMask);
    short translatedKeyCode = (short)(0x8000 | [mappedKey shortValue]);

    // Only the modifiers this rule is adding belong to it. A modifier the player holds
    // is already down on the host, and letting it go here would strand the tracker.
    NSUInteger owned = HIDSyntheticOwnedModifierMask(self, remoteModifierMask);

    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
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

    HIDDispatchInput(self, inputCtx, ^{
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
    // SIMPLIFIED: Always use the standard streaming mapping.
    return KMR_RemoteVKForPhysicalKeyCode(keyCode);
}

- (short)translateKeyCodeWithEvent:(NSEvent *)event {
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

    [self tearDownCoreHIDMouseDriver];
    [self setupCoreHIDMouseDriverIfNeeded];
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
    [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
                                        summaryKey:@"Mouse Runtime Path CoreHID Pending"
                                         detailKey:@"Mouse Runtime Detail CoreHID Pending"];
    Log(LOG_I, @"CoreHID mouse setup: strategy=%ld maxRate=%d requestAccess=%d",
        (long)[SettingsClass mouseDriverFor:self.host.uuid],
        self.coreHIDMouseDriver.maximumReportRate,
        self.coreHIDMouseDriver.requestsListenAccessIfNeeded ? 1 : 0);
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

    PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
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

    HIDDispatchInput(self, inputCtx, ^{
        LiSendMouseMoveEventCtx(inputCtx, moveX, moveY);
    });
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
    (void)driver;
    if (!self.useCoreHIDMouse) {
        return;
    }

    if (!self.coreHIDMouseDidDeliverMovement) {
        self.coreHIDMouseDidDeliverMovement = YES;
        Log(LOG_I, @"CoreHID mouse active: first movement received");
        [[InputMonitoringPermissionManager sharedManager] noteCoreHIDDidBecomeActive];
        [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
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
    (void)driver;
    NSString *safeReason = reason.length > 0 ? reason : @"unknown";
    NSString *safeMessage = messageKey.length > 0 ? messageKey : @"CoreHID Mouse input failed.";
    NSInteger configuredStrategy = [SettingsClass mouseDriverFor:self.host.uuid];
    self.coreHIDMouseRuntimeFailed = YES;
    if ([safeReason isEqualToString:@"permission-denied"]) {
        [[InputMonitoringPermissionManager sharedManager] noteCoreHIDPermissionFailureWithMessage:safeMessage];
    }
    LogLevel level = (configuredStrategy == 3 && [safeReason isEqualToString:@"permission-denied"]) ? LOG_I : LOG_W;
    Log(level, @"CoreHID mouse fallback: reason=%@ message=%@", safeReason, safeMessage);
    NSString *detailKey = @"Mouse Runtime Detail AppKit Fallback Runtime";
    if ([safeReason isEqualToString:@"permission-denied"]) {
        detailKey = @"Mouse Runtime Detail AppKit Fallback Permission";
    } else if ([safeReason isEqualToString:@"unsupported-os"]) {
        detailKey = @"Mouse Runtime Detail AppKit Fallback UnsupportedOS";
    }
    [SettingsClass updateMouseInputRuntimeStatusFor:self.host.uuid
                                        summaryKey:@"Mouse Runtime Path AppKit Fallback"
                                         detailKey:detailKey];
}

- (void)handleDpad:(NSInteger)intValue {
    switch (intValue) {
        case 0:
            [self updateButtonFlags:UP_FLAG state:YES];
            break;
        case 1:
            [self updateButtonFlags:UP_FLAG | RIGHT_FLAG state:YES];
            break;
        case 2:
            [self updateButtonFlags:RIGHT_FLAG state:YES];
            break;
        case 3:
            [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG state:YES];
            break;
        case 4:
            [self updateButtonFlags:DOWN_FLAG state:YES];
            break;
        case 5:
            [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG state:YES];
            break;
        case 6:
            [self updateButtonFlags:LEFT_FLAG state:YES];
            break;
        case 7:
            [self updateButtonFlags:UP_FLAG | LEFT_FLAG state:YES];
            break;

        case 8:
            [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG state:NO];
            break;

        default:
            break;
    }
}

void myHIDCallback(void* context, IOReturn result, void* sender, IOHIDValueRef value) {
    IOHIDElementRef elem = IOHIDValueGetElement(value);
    uint32_t usagePage = IOHIDElementGetUsagePage(elem);
    uint32_t usage = IOHIDElementGetUsage(elem);
    CFIndex intValue = IOHIDValueGetIntegerValue(value);
    
    HIDSupport *self = (__bridge HIDSupport *)context;
    
    IOHIDDeviceRef device = (IOHIDDeviceRef)sender;

    // KingKong claims the Microsoft vendor id, so the vendor-specific check
    // has to win over the generic Xbox layout check regardless of how either
    // id list evolves. The two sets are disjoint today; the negation keeps a
    // future overlap from silently stealing the KingKong axis map.
    if (isXbox(device) && !isKingKong(device)) {
        switch (usagePage) {
            case kHIDPage_GenericDesktop:
                switch (usage) {
                    case kHIDUsage_GD_X:
                        self.controller.lastLeftStickX = MIN((intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Y:
                        self.controller.lastLeftStickY = MIN(-(intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Z:
                        self.controller.lastRightStickX = MIN((intValue - 32768), 32767);
                        break;
                    case kHIDUsage_GD_Rz:
                        self.controller.lastRightStickY = MIN(-(intValue - 32768), 32767);
                        break;
                        
                    case kHIDUsage_GD_Hatswitch:
                        switch (intValue) {
                            case 1:
                                [self updateButtonFlags:UP_FLAG state:YES];
                                break;
                            case 2:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG state:YES];
                                break;
                            case 3:
                                [self updateButtonFlags:RIGHT_FLAG state:YES];
                                break;
                            case 4:
                                [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG state:YES];
                                break;
                            case 5:
                                [self updateButtonFlags:DOWN_FLAG state:YES];
                                break;
                            case 6:
                                [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG state:YES];
                                break;
                            case 7:
                                [self updateButtonFlags:LEFT_FLAG state:YES];
                                break;
                            case 8:
                                [self updateButtonFlags:UP_FLAG | LEFT_FLAG state:YES];
                                break;

                            case 0:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG state:NO];
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
                        self.controller.lastLeftTrigger = intValue;
                        break;
                    case kHIDUsage_Sim_Accelerator:
                        self.controller.lastRightTrigger = intValue;
                        break;

                    default:
                        break;
                }
                break;

            case kHIDPage_Button:
                switch (usage) {
                    case 1:
                        [self updateButtonFlags:A_FLAG state:intValue];
                        break;
                    case 2:
                        [self updateButtonFlags:B_FLAG state:intValue];
                        break;
                    case 4:
                        [self updateButtonFlags:X_FLAG state:intValue];
                        break;
                    case 5:
                        [self updateButtonFlags:Y_FLAG state:intValue];
                        break;
                    case 7:
                        [self updateButtonFlags:LB_FLAG state:intValue];
                        break;
                    case 8:
                        [self updateButtonFlags:RB_FLAG state:intValue];
                        break;
                    case 11:
                        [self updateButtonFlags:BACK_FLAG state:intValue];
                        break;
                    case 12:
                        [self updateButtonFlags:PLAY_FLAG state:intValue];
                        break;
                    case 13:
                        [self updateButtonFlags:SPECIAL_FLAG state:intValue];
                        break;

                        
                    default:
                        break;
                }
                
                break;
            case kHIDPage_Consumer:
                switch (usage) {
                    case kHIDUsage_Csmr_ACBack:
                        [self updateButtonFlags:BACK_FLAG state:intValue];
                        break;
                    case kHIDUsage_Csmr_ACHome:
                        [self updateButtonFlags:SPECIAL_FLAG state:intValue];
                        break;
                    case 14:
                        [self updateButtonFlags:LS_CLK_FLAG state:intValue];
                        break;
                    case 15:
                        [self updateButtonFlags:RS_CLK_FLAG state:intValue];
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
                        self.controller.lastLeftStickX = MAX(MIN((intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Y:
                        self.controller.lastLeftStickY = MAX(MIN(-(intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Rx:
                        self.controller.lastRightStickX = MAX(MIN((intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Ry:
                        self.controller.lastRightStickY = MAX(MIN(-(intValue - 32768), 32767), -32768);
                        break;
                    case kHIDUsage_GD_Z:
                        self.controller.lastLeftTrigger = (unsigned char)((int)intValue / 4);
                        break;
                    case kHIDUsage_GD_Rz:
                        self.controller.lastRightTrigger = (unsigned char)((int)intValue / 4);
                        break;
                        
                    case kHIDUsage_GD_Hatswitch:
                        switch (intValue) {
                            case 1:
                                [self updateButtonFlags:UP_FLAG state:YES];
                                break;
                            case 2:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG state:YES];
                                break;
                            case 3:
                                [self updateButtonFlags:RIGHT_FLAG state:YES];
                                break;
                            case 4:
                                [self updateButtonFlags:DOWN_FLAG | RIGHT_FLAG state:YES];
                                break;
                            case 5:
                                [self updateButtonFlags:DOWN_FLAG state:YES];
                                break;
                            case 6:
                                [self updateButtonFlags:DOWN_FLAG | LEFT_FLAG state:YES];
                                break;
                            case 7:
                                [self updateButtonFlags:LEFT_FLAG state:YES];
                                break;
                            case 8:
                                [self updateButtonFlags:UP_FLAG | LEFT_FLAG state:YES];
                                break;

                            case 0:
                                [self updateButtonFlags:UP_FLAG | RIGHT_FLAG | DOWN_FLAG | LEFT_FLAG state:NO];
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
                        [self updateButtonFlags:A_FLAG state:intValue];
                        break;
                    case 2:
                        [self updateButtonFlags:B_FLAG state:intValue];
                        break;
                    case 3:
                        [self updateButtonFlags:X_FLAG state:intValue];
                        break;
                    case 4:
                        [self updateButtonFlags:Y_FLAG state:intValue];
                        break;
                    case 5:
                        [self updateButtonFlags:LB_FLAG state:intValue];
                        break;
                    case 6:
                        [self updateButtonFlags:RB_FLAG state:intValue];
                        break;
                    case 7:
                        [self updateButtonFlags:BACK_FLAG state:intValue];
                        break;
                    case 8:
                        [self updateButtonFlags:PLAY_FLAG state:intValue];
                        break;
                    case 9:
                        [self updateButtonFlags:LS_CLK_FLAG state:intValue];
                        break;
                    case 10:
                        [self updateButtonFlags:RS_CLK_FLAG state:intValue];
                        break;
                    case 133:
                        [self updateButtonFlags:SPECIAL_FLAG state:intValue];
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
    HIDSupport *self = (__bridge HIDSupport *)context;
    
    IOHIDDeviceRef device = (IOHIDDeviceRef)sender;
    if (!isPlayStation(device) && !isNintendo(device)) {
        return;
    };
    
    if (isPS4(device)) {
        PS4StatePacket_t *state = (PS4StatePacket_t *)report;
        switch (report[0]) {
            case k_EPS4ReportIdUsbState:
                state = (PS4StatePacket_t *)(report + 1);
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
                if (report[1] & 0x80) {
                    state = (PS4StatePacket_t *)(report + 3);
                }
                break;
            default:
                NSLog(@"Unknown PS4 packet: 0x%hhu", report[0]);
                break;
        }
                
        
        UInt8 abxy = state->rgucButtonsHatAndCounter[0] >> 4;
        [self updateButtonFlags:X_FLAG state:(abxy & 0x01) != 0];
        [self updateButtonFlags:A_FLAG state:(abxy & 0x02) != 0];
        [self updateButtonFlags:B_FLAG state:(abxy & 0x04) != 0];
        [self updateButtonFlags:Y_FLAG state:(abxy & 0x08) != 0];
        
        [self handleDpad:state->rgucButtonsHatAndCounter[0] & 0x0F];

        UInt8 otherButtons = state->rgucButtonsHatAndCounter[1];
        [self updateButtonFlags:LB_FLAG state:(otherButtons & 0x01) != 0];
        [self updateButtonFlags:RB_FLAG state:(otherButtons & 0x02) != 0];
        [self updateButtonFlags:BACK_FLAG state:(otherButtons & 0x10) != 0];
        [self updateButtonFlags:PLAY_FLAG state:(otherButtons & 0x20) != 0];
        [self updateButtonFlags:LS_CLK_FLAG state:(otherButtons & 0x40) != 0];
        [self updateButtonFlags:RS_CLK_FLAG state:(otherButtons & 0x80) != 0];

        [self updateButtonFlags:SPECIAL_FLAG state:(state->rgucButtonsHatAndCounter[2] & 0x01) != 0];
        
        self.controller.lastLeftTrigger = state->ucTriggerLeft;
        self.controller.lastRightTrigger = state->ucTriggerRight;

        self.controller.lastLeftStickX = (state->ucLeftJoystickX - 128) * 255 + 1;
        self.controller.lastLeftStickY = (state->ucLeftJoystickY - 128) * -255;
        self.controller.lastRightStickX = (state->ucRightJoystickX - 128) * 255 + 1;
        self.controller.lastRightStickY = (state->ucRightJoystickY - 128) * -255;
        
        if (self.controllerDriver == 0) {

            if (self.lastPS4State.rgucButtonsHatAndCounter[0] != state->rgucButtonsHatAndCounter[0] ||
                self.lastPS4State.rgucButtonsHatAndCounter[1] != state->rgucButtonsHatAndCounter[1] ||
                self.lastPS4State.rgucButtonsHatAndCounter[2] != state->rgucButtonsHatAndCounter[2] ||
                self.lastPS4State.ucTriggerLeft != state->ucTriggerLeft ||
                self.lastPS4State.ucTriggerRight != state->ucTriggerRight ||
                self.lastPS4State.ucLeftJoystickX != state->ucLeftJoystickX ||
                self.lastPS4State.ucLeftJoystickY != state->ucLeftJoystickY ||
                self.lastPS4State.ucRightJoystickX != state->ucRightJoystickX ||
                self.lastPS4State.ucRightJoystickY != state->ucRightJoystickY ||
                0)
            {
                [self sendControllerEvent];
                self.lastPS4State = *state;
            }
        }
    } else if (isPS5(device)) {
        PS5StatePacket_t *state = (PS5StatePacket_t *)report;
        switch (report[0]) {
            case k_EPS5ReportIdState:
                state = (PS5StatePacket_t *)(report + 1);
                self.isPS5Bluetooth = reportLength == 10;
                break;
            case k_EPS5ReportIdBluetoothState:
                state = (PS5StatePacket_t *)(report + 2);
                self.isPS5Bluetooth = YES;
                break;
            default:
                NSLog(@"Unknown PS5 packet: 0x%hhu", report[0]);
                break;
        }
        
        UInt8 abxy = state->rgucButtonsAndHat[0] >> 4;
        [self updateButtonFlags:X_FLAG state:(abxy & 0x01) != 0];
        [self updateButtonFlags:A_FLAG state:(abxy & 0x02) != 0];
        [self updateButtonFlags:B_FLAG state:(abxy & 0x04) != 0];
        [self updateButtonFlags:Y_FLAG state:(abxy & 0x08) != 0];
        
        [self handleDpad:state->rgucButtonsAndHat[0] & 0x0F];

        UInt8 otherButtons = state->rgucButtonsAndHat[1];
        [self updateButtonFlags:LB_FLAG state:(otherButtons & 0x01) != 0];
        [self updateButtonFlags:RB_FLAG state:(otherButtons & 0x02) != 0];
        [self updateButtonFlags:BACK_FLAG state:(otherButtons & 0x10) != 0];
        [self updateButtonFlags:PLAY_FLAG state:(otherButtons & 0x20) != 0];
        [self updateButtonFlags:LS_CLK_FLAG state:(otherButtons & 0x40) != 0];
        [self updateButtonFlags:RS_CLK_FLAG state:(otherButtons & 0x80) != 0];

        [self updateButtonFlags:SPECIAL_FLAG state:(state->rgucButtonsAndHat[2] & 0x01) != 0];
        
        self.controller.lastLeftTrigger = state->ucTriggerLeft;
        self.controller.lastRightTrigger = state->ucTriggerRight;

        self.controller.lastLeftStickX = (state->ucLeftJoystickX - 128) * 255 + 1;
        self.controller.lastLeftStickY = (state->ucLeftJoystickY - 128) * -255;
        self.controller.lastRightStickX = (state->ucRightJoystickX - 128) * 255 + 1;
        self.controller.lastRightStickY = (state->ucRightJoystickY - 128) * -255;
        
        if (self.controllerDriver == 0) {

            if (self.lastPS5State.rgucButtonsAndHat[0] != state->rgucButtonsAndHat[0] ||
                self.lastPS5State.rgucButtonsAndHat[1] != state->rgucButtonsAndHat[1] ||
                self.lastPS5State.rgucButtonsAndHat[2] != state->rgucButtonsAndHat[2] ||
                self.lastPS5State.ucTriggerLeft != state->ucTriggerLeft ||
                self.lastPS5State.ucTriggerRight != state->ucTriggerRight ||
                self.lastPS5State.ucLeftJoystickX != state->ucLeftJoystickX ||
                self.lastPS5State.ucLeftJoystickY != state->ucLeftJoystickY ||
                self.lastPS5State.ucRightJoystickX != state->ucRightJoystickX ||
                self.lastPS5State.ucRightJoystickY != state->ucRightJoystickY ||
                0)
            {
                [self sendControllerEvent];
                self.lastPS5State = *state;
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
                SwitchSubcommandInputPacket_t *reply = (SwitchSubcommandInputPacket_t *)&report[1];
                if (reply->ucSubcommandID == k_eSwitchSubcommandIDs_EnableVibration && (reply->ucSubcommandAck & 0x80)) {
                    self.vibrationEnableResponded = YES;
                    self.waitingForVibrationEnable = NO;
                    dispatch_semaphore_signal(self.hidReadSemaphore);
                }
            }
        } else {
            if (report[0] == k_eSwitchInputReportIDs_SimpleControllerState) {
                SwitchSimpleStatePacket_t *packet = (SwitchSimpleStatePacket_t *)&report[1];
                
                SInt16 axis;
                
                UInt8 buttons = packet->rgucButtons[0];
                [self updateButtonFlags:Y_FLAG state:(buttons & 0x08) != 0];
                [self updateButtonFlags:B_FLAG state:(buttons & 0x02) != 0];
                [self updateButtonFlags:A_FLAG state:(buttons & 0x01) != 0];
                [self updateButtonFlags:X_FLAG state:(buttons & 0x04) != 0];
                [self updateButtonFlags:LB_FLAG state:(buttons & 0x10) != 0];
                [self updateButtonFlags:RB_FLAG state:(buttons & 0x20) != 0];
                axis = (buttons & 0x40) ? 32767 : -32768;
                self.controller.lastLeftTrigger = axis;
                axis = (buttons & 0x80) ? 32767 : -32768;
                self.controller.lastRightTrigger = axis;
                
                UInt8 otherButtons = packet->rgucButtons[1];
                [self updateButtonFlags:BACK_FLAG state:(otherButtons & 0x01) != 0];
                [self updateButtonFlags:PLAY_FLAG state:(otherButtons & 0x02) != 0];
                [self updateButtonFlags:LS_CLK_FLAG state:(otherButtons & 0x04) != 0];
                [self updateButtonFlags:RS_CLK_FLAG state:(otherButtons & 0x08) != 0];
                
                [self updateButtonFlags:SPECIAL_FLAG state:(otherButtons & 0x10) != 0];
                
                [self handleDpad:packet->ucStickHat];

                axis = (short)(packet->sJoystickLeft[0] - INT_MAX);
                self.controller.lastLeftStickX = axis;
                axis = (short)(packet->sJoystickLeft[1] - INT_MAX);
                self.controller.lastLeftStickY = axis;
                axis = (short)(packet->sJoystickRight[0] - INT_MAX);
                self.controller.lastRightStickX = axis;
                axis = (short)(packet->sJoystickRight[1] - INT_MAX);
                self.controller.lastRightStickY = axis;
                
                if (self.controllerDriver == 0) {
                    
                    if (self.lastSimpleSwitchState.rgucButtons[0] != packet->rgucButtons[0] ||
                        self.lastSimpleSwitchState.rgucButtons[1] != packet->rgucButtons[1] ||
                        self.lastSimpleSwitchState.ucStickHat != packet->ucStickHat ||
                        self.lastSimpleSwitchState.sJoystickLeft[0] != packet->sJoystickLeft[0] ||
                        self.lastSimpleSwitchState.sJoystickLeft[1] != packet->sJoystickLeft[1] ||
                        self.lastSimpleSwitchState.sJoystickRight[0] != packet->sJoystickRight[0] ||
                        self.lastSimpleSwitchState.sJoystickRight[1] != packet->sJoystickRight[1] ||
                        0)
                    {
                        [self sendControllerEvent];
                        self.lastSimpleSwitchState = *packet;
                    }
                }
            } else if (report[0] == k_eSwitchInputReportIDs_FullControllerState) {
                SwitchStatePacket_t *packet = (SwitchStatePacket_t *)&report[1];
                
                SInt16 axis;
                
                UInt8 buttons = packet->controllerState.rgucButtons[0];
                [self updateButtonFlags:Y_FLAG state:(buttons & 0x02) != 0];
                [self updateButtonFlags:B_FLAG state:(buttons & 0x08) != 0];
                [self updateButtonFlags:A_FLAG state:(buttons & 0x04) != 0];
                [self updateButtonFlags:X_FLAG state:(buttons & 0x01) != 0];
                [self updateButtonFlags:RB_FLAG state:(buttons & 0x40) != 0];
                axis = (buttons & 0x80) ? 32767 : -32768;
                self.controller.lastRightTrigger = axis;
                
                UInt8 otherButtons = packet->controllerState.rgucButtons[1];
                [self updateButtonFlags:BACK_FLAG state:(otherButtons & 0x01) != 0];
                [self updateButtonFlags:PLAY_FLAG state:(otherButtons & 0x02) != 0];
                [self updateButtonFlags:LS_CLK_FLAG state:(otherButtons & 0x08) != 0];
                [self updateButtonFlags:RS_CLK_FLAG state:(otherButtons & 0x04) != 0];
                
                [self updateButtonFlags:SPECIAL_FLAG state:(otherButtons & 0x10) != 0];
                
                UInt8 otherOtherButtons = packet->controllerState.rgucButtons[2];
                [self updateButtonFlags:DOWN_FLAG state:(otherOtherButtons & 0x01) != 0];
                [self updateButtonFlags:UP_FLAG state:(otherOtherButtons & 0x02) != 0];
                [self updateButtonFlags:RIGHT_FLAG state:(otherOtherButtons & 0x04) != 0];
                [self updateButtonFlags:LEFT_FLAG state:(otherOtherButtons & 0x08) != 0];
                [self updateButtonFlags:LB_FLAG state:(otherOtherButtons & 0x40) != 0];
                axis = (otherOtherButtons & 0x80) ? 32767 : -32768;
                self.controller.lastLeftTrigger = axis;
                
                axis = packet->controllerState.rgucJoystickLeft[0] | ((packet->controllerState.rgucJoystickLeft[1] & 0xF) << 8);
                self.controller.lastLeftStickX = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = ((packet->controllerState.rgucJoystickLeft[1] & 0xF0) >> 4) | (packet->controllerState.rgucJoystickLeft[2] << 4);
                self.controller.lastLeftStickY = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = packet->controllerState.rgucJoystickRight[0] | ((packet->controllerState.rgucJoystickRight[1] & 0xF) << 8);
                self.controller.lastRightStickX = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                axis = ((packet->controllerState.rgucJoystickRight[1] & 0xF0) >> 4) | (packet->controllerState.rgucJoystickRight[2] << 4);
                self.controller.lastRightStickY = MAX(MIN((axis - 2048) * 24, INT16_MAX), INT16_MIN);
                
                if (self.controllerDriver == 0) {
                    
                    if (self.lastSwitchState.controllerState.rgucButtons[0] != packet->controllerState.rgucButtons[0] ||
                        self.lastSwitchState.controllerState.rgucButtons[1] != packet->controllerState.rgucButtons[1] ||
                        self.lastSwitchState.controllerState.rgucButtons[2] != packet->controllerState.rgucButtons[2] ||
                        self.lastSwitchState.controllerState.rgucJoystickLeft[0] != packet->controllerState.rgucJoystickLeft[0] ||
                        self.lastSwitchState.controllerState.rgucJoystickLeft[1] != packet->controllerState.rgucJoystickLeft[1] ||
                        self.lastSwitchState.controllerState.rgucJoystickRight[0] != packet->controllerState.rgucJoystickRight[0] ||
                        self.lastSwitchState.controllerState.rgucJoystickRight[1] != packet->controllerState.rgucJoystickRight[1] ||
                        0)
                    {
                        [self sendControllerEvent];
                        self.lastSwitchState = *packet;
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

    [self rumbleSync];
}

void myHIDDeviceRemovalCallback(void * _Nullable        context,
                                IOReturn                result,
                                void * _Nullable        sender,
                                IOHIDDeviceRef          device) {
    HIDSupport *self = (__bridge HIDSupport *)context;

    if (self.controllerDriver == 0) {
        self.controller.lastButtonFlags = 0;
        self.controller.lastLeftTrigger = 0;
        self.controller.lastRightTrigger = 0;
        self.controller.lastLeftStickX = 0;
        self.controller.lastLeftStickY = 0;
        self.controller.lastRightStickX = 0;
        self.controller.lastRightStickY = 0;
        
        [self sendControllerEvent];
    }
}


- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled {
    // Read per press rather than once at connect, so a player who turns the gesture off
    // because a game needs the Menu key gets it on the very next hold. The read carries its
    // own default, so a host with no stored preference behaves like a fresh install.
    return [SettingsClass gamepadMenuLongPressTogglesMouseModeFor:self.host.uuid];
}

- (void)updateButtonFlags:(int)flag state:(BOOL)set {
    // Mouse Mode Toggle Logic: the same gesture the MFi path runs, asked of the same
    // function, so one switch and one timing boundary cover both controller drivers and
    // neither can drift away from the other (issue #45).
    if (flag == PLAY_FLAG) {
        MLGamepadMenuGesture gesture = self.controller.menuGesture;
        const BOOL toggled = MLGamepadMenuGestureToggles(&gesture,
                                                         set ? YES : NO,
                                                         [NSDate date].timeIntervalSinceReferenceDate,
                                                         [self gamepadMenuLongPressTogglesMouseModeEnabled] ? YES : NO,
                                                         MLGamepadMenuLongPressRequiredSeconds);
        self.controller.menuGesture = gesture;
        if (toggled) {
            self.controller.isMouseMode = !self.controller.isMouseMode;

            // Notify UI
            dispatch_async(dispatch_get_main_queue(), ^{
                [[NSNotificationCenter defaultCenter] postNotificationName:HIDMouseModeToggledNotification object:nil userInfo:@{@"enabled": @(self.controller.isMouseMode)}];
            });

            // Rumble
            [self rumbleLowFreqMotor:0xFFFF highFreqMotor:0xFFFF];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                [self rumbleLowFreqMotor:0 highFreqMotor:0];
            });
        }
    }

    // Mouse Click Logic
    if (self.controller.isMouseMode) {
        if (flag == A_FLAG) {
            // Left Click
            if (set) {
                 PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
                 if (!inputCtx) {
                     return;
                 }
                HIDDispatchInput(self, inputCtx, ^{ LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_PRESS, BUTTON_LEFT); });
            } else {
                 PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
                 if (!inputCtx) {
                     return;
                 }
                 HIDDispatchInput(self, inputCtx, ^{ LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_RELEASE, BUTTON_LEFT); });
            }
            return; // Don't set flag
        }
        if (flag == B_FLAG) {
            // Right Click
            if (set) {
                 PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
                 if (!inputCtx) {
                     return;
                 }
                 HIDDispatchInput(self, inputCtx, ^{ LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_PRESS, BUTTON_RIGHT); });
            } else {
                 PML_INPUT_STREAM_CONTEXT inputCtx = HIDInputContext(self);
                 if (!inputCtx) {
                     return;
                 }
                 HIDDispatchInput(self, inputCtx, ^{ LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_RELEASE, BUTTON_RIGHT); });
            }
            return; // Don't set flag
        }
    }

    if (set) {
        self.controller.lastButtonFlags |= flag;
    } else {
        self.controller.lastButtonFlags &= ~flag;
    }
    
    // Gamepad Quit Combo (Start + Select + LB + RB)
    int quitCombo = PLAY_FLAG | BACK_FLAG | LB_FLAG | RB_FLAG;
    if ((self.controller.lastButtonFlags & quitCombo) == quitCombo) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [[NSNotificationCenter defaultCenter] postNotificationName:HIDGamepadQuitNotification object:nil];
        });
        self.controller.lastButtonFlags = 0;
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
}


@end
