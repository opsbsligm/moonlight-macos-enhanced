//
//  HIDSupport_Internal.h
//  Moonlight for macOS
//
//  Created by Michael Kenny on 26/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//
#import "HIDSupport.h"
#import "Controller.h"
#import "Ticks.h"
#import "HIDSupportRumbleTypes.h"
#import "MouseEmulation.h"

#import "Moonlight-Swift.h"
#include <limits.h>
#include <stdatomic.h>
#include <math.h>

#include "Limelight.h"
#include "Limelight-internal.h"

#import <Carbon/Carbon.h>
#import <IOKit/hid/IOHIDManager.h>
#import <IOKit/hid/IOHIDKeys.h>
#import <IOKit/hid/IOHIDElement.h>

@import GameController;

// Relative pointer motion is produced on the GameController mouse callback
// queue and consumed by the CVDisplayLink output callback on another thread.
// An atomic CGFloat pair could not express that handoff: the producer's
// compound update and the consumer's read-then-clear are each several
// accesses, so motion that landed between a read and the clear that followed
// was overwritten and lost. Each component is now a single atomic add on the
// producing side and a single atomic take on the consuming side, so every
// unit of motion moves exactly once and the accumulator reads as zero again
// without a second store.
@interface HIDMouseDeltaAccumulator : NSObject
- (void)accumulateMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY;
- (void)takeAccumulatedMotionX:(CGFloat *)deltaXOut deltaY:(CGFloat *)deltaYOut;
@end

@interface HIDSupport () <CoreHIDMouseDriverDelegate>
@property (nonatomic) dispatch_queue_t rumbleQueue;
@property (nonatomic, strong) NSDictionary *mappings;
@property (nonatomic) IOHIDManagerRef hidManager;
@property (nonatomic, strong) Controller *controller;
@property (nonatomic) CVDisplayLinkRef displayLink;
@property (nonatomic, strong) HIDMouseDeltaAccumulator *mouseDeltaAccumulator;
@property (nonatomic) UInt8 previousLowFreqMotor;
@property (nonatomic) UInt8 previousHighFreqMotor;
@property (atomic) UInt16 nextLowFreqMotor;
@property (atomic) UInt16 nextHighFreqMotor;
@property (atomic) dispatch_semaphore_t rumbleSemaphore;
@property (atomic) BOOL closeRumble;
@property (atomic) BOOL isRumbleTimer;
@property (nonatomic) PS4StatePacket_t lastPS4State;
@property (nonatomic) PS5StatePacket_t lastPS5State;
@property (nonatomic) NSInteger controllerDriver;
@property (nonatomic) BOOL isPS5Bluetooth;

@property (nonatomic) SwitchSimpleStatePacket_t lastSimpleSwitchState;
@property (nonatomic) SwitchStatePacket_t lastSwitchState;

@property (atomic) dispatch_semaphore_t hidReadSemaphore;
@property (atomic) BOOL vibrationEnableResponded;
@property (atomic) BOOL waitingForVibrationEnable;
@property (atomic) UInt32 startedWaitingForVibrationEnable;
@property (nonatomic) dispatch_queue_t enableVibrationQueue;

@property (nonatomic) BOOL switchUsingBluetooth;
@property (nonatomic) UInt8 switchCommandNumber;
@property (nonatomic) BOOL switchRumbleActive;
@property (nonatomic) UInt32 switchUnRumbleSent;
@property (nonatomic) BOOL switchRumblePending;
@property (nonatomic) BOOL switchRumbleZeroPending;
@property (nonatomic) UInt32 switchUnRumblePending;

@property (nonatomic, strong) Ticks *ticks;

@property (nonatomic) id mouseConnectObserver;
@property (nonatomic) id mouseDisconnectObserver;

@property (nonatomic) BOOL useGCMouse;
@property (nonatomic) BOOL useCoreHIDMouse;
@property (nonatomic, strong) CoreHIDMouseDriver *coreHIDMouseDriver;
@property (nonatomic) BOOL coreHIDMouseDidDeliverMovement;
@property (nonatomic) BOOL coreHIDMouseRuntimeFailed;
@property (nonatomic) NSUInteger keyboardPhysicalModifierSourceMask;
@property (nonatomic) NSUInteger keyboardRemoteModifierMask;
@property (atomic) BOOL keyboardModifierReleaseInProgress;
@property (atomic) BOOL keyboardTeardownAlreadyCalled;
/// Virtual key codes whose keyDown was consumed locally. The host never learned
/// the key went down, so the matching keyUp has to be consumed as well; the set
/// holds at most one entry per physical key and is cleared by a forwarded
/// keyDown of the same key, by session teardown, and by consuming the release.
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;

/// Key codes the host was told went down, in the encoding that was dispatched
/// (0x8000 | translated), so the release can replay the exact same code. Capture
/// can end while a key is still physically held: keyUp: is gated on
/// shouldSendInputEvents, so that release would be dropped and the host would
/// keep the key pressed for the rest of the session.
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardForwardedKeyDownKeyCodes;

/// Reentry guard for -releaseAllHeldKeys, matching the modifier release guard.
@property (atomic) BOOL keyboardHeldKeyReleaseInProgress;
@property (atomic) BOOL coreHIDFreeMouseAbsoluteSyncScheduled;
@property (atomic) uint64_t coreHIDFreeMouseAbsoluteSyncToken;
@property (nonatomic) dispatch_queue_t inputQueue;
@property (atomic) uint64_t suppressRelativeMouseUntilMs;
@property (nonatomic, strong) NSObject *freeMouseVirtualCursorLock;
@property (atomic) BOOL freeMouseVirtualCursorRequestedActive;
@property (nonatomic) BOOL freeMouseVirtualCursorHasAnchor;
@property (nonatomic) NSPoint freeMouseVirtualCursorPoint;
@property (nonatomic) NSPoint freeMouseVirtualCursorLastAnchorPoint;
@property (nonatomic) NSSize freeMouseVirtualCursorReferenceSize;
@property (nonatomic) double freeMouseVirtualCursorGainX;
@property (nonatomic) double freeMouseVirtualCursorGainY;
@property (nonatomic) double freeMouseVirtualCursorRawSinceAnchorX;
@property (nonatomic) double freeMouseVirtualCursorRawSinceAnchorY;
@property (nonatomic, strong) NSObject *inputDiagnosticsLock;
@property (atomic) BOOL inputDiagnosticsEnabled;
@property (nonatomic) NSUInteger inputDiagnosticsDetailedLogSequence;
@property (nonatomic) NSUInteger inputDiagnosticsRemainingDetailedLogs;
@property (nonatomic) NSUInteger inputDiagnosticsRemainingScrollDetailedLogs;
@property (nonatomic) uint64_t scrollTraceSequence;
@property (nonatomic) uint64_t activeScrollTraceId;
@property (nonatomic) uint64_t activeScrollTraceStartedMs;
@property (nonatomic) uint64_t activeScrollTraceLastEventMs;
@property (nonatomic) BOOL activeScrollTraceLockedToPrecise;
@property (nonatomic, copy) NSString *activeScrollTraceSource;
@property (nonatomic) NSUInteger inputDiagnosticsMouseMoveEvents;
@property (nonatomic) NSUInteger inputDiagnosticsNonZeroRelativeEvents;
@property (nonatomic) NSUInteger inputDiagnosticsRelativeDispatches;
@property (nonatomic) NSUInteger inputDiagnosticsAbsoluteDispatches;
@property (nonatomic) NSUInteger inputDiagnosticsAbsoluteDuplicateSkips;
@property (nonatomic) NSUInteger inputDiagnosticsCoreHIDRawEvents;
@property (nonatomic) NSUInteger inputDiagnosticsCoreHIDDispatches;
@property (nonatomic) NSUInteger inputDiagnosticsSuppressedRelativeEvents;
@property (nonatomic) NSInteger inputDiagnosticsRawRelativeDeltaX;
@property (nonatomic) NSInteger inputDiagnosticsRawRelativeDeltaY;
@property (nonatomic) NSInteger inputDiagnosticsSentRelativeDeltaX;
@property (nonatomic) NSInteger inputDiagnosticsSentRelativeDeltaY;
@property (nonatomic) short lastAbsolutePointerHostX;
@property (nonatomic) short lastAbsolutePointerHostY;
@property (nonatomic) short lastAbsolutePointerReferenceWidth;
@property (nonatomic) short lastAbsolutePointerReferenceHeight;
@property (nonatomic) uint64_t lastAbsolutePointerAtMs;
@property (nonatomic, copy) NSString *lastAbsolutePointerSource;
@property (atomic) BOOL pendingCoalescedAbsolutePointerDispatch;
@property (atomic) BOOL pendingCoalescedAbsolutePointerValid;
@property (nonatomic) short pendingCoalescedAbsolutePointerHostX;
@property (nonatomic) short pendingCoalescedAbsolutePointerHostY;
@property (nonatomic) short pendingCoalescedAbsolutePointerReferenceWidth;
@property (nonatomic) short pendingCoalescedAbsolutePointerReferenceHeight;
@property (nonatomic, copy) NSString *pendingCoalescedAbsolutePointerSource;
@property (nonatomic) uint32_t pressedMouseButtonsMask;
@property (nonatomic) CGFloat accumulatedHighResScrollDeltaX;
@property (nonatomic) CGFloat accumulatedHighResScrollDeltaY;
@property (nonatomic) CGFloat accumulatedQuantizedWheelDeltaX;
@property (nonatomic) CGFloat accumulatedQuantizedWheelDeltaY;
// Motion that has been asked for but not yet worth a whole pixel, one pair per
// producing thread. HIDDrainRelativeDelta keeps the debt; these pairs are where it
// lives, and they are separate because the display-link consumer and the HID-queue
// consumer are not the same thread.
@property (nonatomic) CGFloat relativeMotionResidualX;
@property (nonatomic) CGFloat relativeMotionResidualY;
@property (nonatomic) CGFloat relativeDeltaResidualX;
@property (nonatomic) CGFloat relativeDeltaResidualY;
// The emulated pointer keeps its own debt, separate from the mouse's: a stick held a
// little off centre asks for one and eight tenths pixels a frame, and the residue is
// what makes the cursor travel at the rate the settings promise instead of the two
// pixels a frame that truncation reported.
@property (nonatomic) CGFloat mouseEmulationResidualX;
@property (nonatomic) CGFloat mouseEmulationResidualY;
@property (nonatomic) uint64_t accumulatedQuantizedWheelLastEventMsX;
@property (nonatomic) uint64_t accumulatedQuantizedWheelLastEventMsY;
@property (nonatomic) NSInteger gcMouseScrollLastClickY;
@property (nonatomic) uint64_t gcMouseScrollLastEventMsY;
@property (atomic) uint64_t suppressAppKitScrollUntilMsY;

- (void)sendControllerEvent;
- (KeyboardCompatibilityMode)keyboardCompatibilityMode;
- (BOOL)usesKeyboardCommandToControlCompatibility;
- (BOOL)usesKeyboardLeftControlWinSwapCompatibility;
- (BOOL)usesKeyboardShortcutTranslationCompatibility;
- (BOOL)usesKeyboardMoonlightClassicMapping;
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event;
- (BOOL)shouldApplyKeyboardShortcutTranslationForEvent:(NSEvent *)event;
- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (char)translatedModifierFlagsForEvent:(NSEvent *)event;
- (short)translateKeyCodeWithEvent:(NSEvent *)event;
- (char)translateKeyModifierWithEvent:(NSEvent *)event;
- (void)handleDpad:(NSInteger)intValue;
- (void)updateButtonFlags:(int)flag state:(BOOL)set;
- (void)setupHidManager;
- (void)tearDownHidManagerOnMainThread;
- (BOOL)reserveDetailedInputDiagnosticsLogSequence:(NSUInteger *)sequence;
- (void)syncScrollTraceDiagnosticsPreferenceToInputContext;
- (uint64_t)prepareScrollTraceFromSource:(NSString *)source
                               rawDeltaX:(CGFloat)rawDeltaX
                               rawDeltaY:(CGFloat)rawDeltaY
                                   phase:(NSEventPhase)phase
                           momentumPhase:(NSEventPhase)momentumPhase
                        hasPreciseDeltas:(BOOL)hasPreciseDeltas;
- (void)recordRelativeInputDiagnosticsFrom:(NSString *)source
                                 rawDeltaX:(CGFloat)rawDeltaX
                                 rawDeltaY:(CGFloat)rawDeltaY
                                sentDeltaX:(short)sentDeltaX
                                sentDeltaY:(short)sentDeltaY
                                suppressed:(BOOL)suppressed;
- (void)recordAbsoluteInputDiagnosticsFrom:(NSString *)source
                                         x:(short)x
                                         y:(short)y
                                     width:(short)width
                                    height:(short)height;
- (void)dispatchRelativeMouseDeltaX:(CGFloat)deltaX
                             deltaY:(CGFloat)deltaY
                          sourceTag:(NSString *)sourceTag;
- (void)setupCoreHIDMouseDriverIfNeeded;
- (void)tearDownCoreHIDMouseDriver;
- (void)refreshMouseInputConfiguration;
- (void)recordMouseButtonDiagnosticsAction:(NSString *)action
                                    button:(int)button
                                      mask:(uint32_t)mask
                                 synthetic:(BOOL)synthetic;
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
                              dispatchedY:(short)dispatchedY;
@end

@interface HIDSupport (PointerInternal)
- (void)registerMouseCallbacks:(GCMouse *)mouse API_AVAILABLE(macos(11.0));
- (void)unregisterMouseCallbacks:(GCMouse *)mouse API_AVAILABLE(macos(11.0));
- (BOOL)initializeDisplayLink;
- (BOOL)dispatchVirtualFreeMouseDeltaX:(double)deltaX
                                deltaY:(double)deltaY
                             sourceTag:(NSString *)sourceTag;
- (BOOL)getFreeMouseVirtualCursorPoint:(NSPoint *)viewPoint
                         referenceSize:(NSSize *)referenceSize;
@end

@interface HIDSupport (RumbleInternal)
- (int)hidGetFeatureReport:(IOHIDDeviceRef)device data:(unsigned char *)data length:(size_t)length;
- (void)rumbleSync;
- (void)runRumbleLoop;
- (IOHIDDeviceRef)getFirstDevice;
- (int)switch_RumbleJoystick:(IOHIDDeviceRef)device lowFreqMotor:(UInt16)lowFreqMotor highFreqMotor:(UInt16)highFreqMotor;
- (BOOL)setVibrationEnabled:(UInt8)enabled;
- (BOOL)writeSubcommand:(ESwitchSubcommandIDs)ucCommandID
                   pBuf:(UInt8 *)pBuf
                  ucLen:(UInt8)ucLen
                ppReply:(SwitchSubcommandInputPacket_t **)ppReply;
- (void)constructSubcommand:(ESwitchSubcommandIDs)ucCommandID
                       pBuf:(UInt8 *)pBuf
                      ucLen:(UInt8)ucLen
                  outPacket:(SwitchSubcommandOutputPacket_t *)outPacket;
- (int)switchSendPendingRumble:(IOHIDDeviceRef)device;
- (int)switchActuallyRumbleJoystick:(IOHIDDeviceRef)device low_frequency_rumble:(UInt16)low_frequency_rumble high_frequency_rumble:(UInt16)high_frequency_rumble;
- (void)setNeutralRumble:(SwitchRumbleData_t *)pRumble;
- (void)switchEncodeRumble:(SwitchRumbleData_t *)pRumble
                usHighFreq:(UInt16)usHighFreq
            ucHighFreqAmp:(UInt8)ucHighFreqAmp
                 ucLowFreq:(UInt8)ucLowFreq
              usLowFreqAmp:(UInt16)usLowFreqAmp;
- (BOOL)writeRumble:(IOHIDDeviceRef)device;
- (BOOL)writePacket:(IOHIDDeviceRef)device pBuf:(void *)pBuf ucLen:(UInt8)ucLen;
@end

@interface HIDSupport (ScrollInternal)
- (void)handleGCMouseScrollValueY:(float)value API_AVAILABLE(macos(11.0));
@end

typedef NS_OPTIONS(NSUInteger, HIDInputCapabilityMask) {
    HIDInputCapabilityRelativeMotion = 1UL << 0,
    HIDInputCapabilityDiscreteVerticalWheel = 1UL << 1,
    HIDInputCapabilityDiscreteHorizontalWheel = 1UL << 2,
    HIDInputCapabilityContinuousScrollGesture = 1UL << 3,
    HIDInputCapabilityExtraButtons = 1UL << 4,
    HIDInputCapabilityHighReportRate = 1UL << 5,
    HIDInputCapabilityVendorEnhancementAvailable = 1UL << 6,
};

typedef NS_ENUM(NSUInteger, HIDInputSourceKind) {
    HIDInputSourceKindAppKit = 0,
    HIDInputSourceKindGCMouse = 1,
    HIDInputSourceKindCoreHID = 2,
    HIDInputSourceKindFallbackNSEvent = 3,
};

typedef NS_ENUM(NSUInteger, HIDScrollSemanticKind) {
    HIDScrollSemanticKindDiscreteWheel = 0,
    HIDScrollSemanticKindContinuousGestureScroll = 1,
    HIDScrollSemanticKindHorizontalWheel = 2,
    HIDScrollSemanticKindSyntheticOrRewrittenScroll = 3,
};

typedef NS_ENUM(NSInteger, HIDPhysicalWheelModeOption) {
    HIDPhysicalWheelModeOptionNotched = 0,
    HIDPhysicalWheelModeOptionHighPrecision = 1,
    HIDPhysicalWheelModeOptionAutomatic = 2,
};

typedef NS_ENUM(NSInteger, HIDRewrittenScrollModeOption) {
    HIDRewrittenScrollModeOptionAdaptive = 0,
    HIDRewrittenScrollModeOptionNotched = 1,
    HIDRewrittenScrollModeOptionHighPrecision = 2,
};

typedef struct {
    HIDInputSourceKind sourceKind;
    HIDScrollSemanticKind semanticKind;
    HIDInputCapabilityMask capabilities;
    BOOL quantizedWheel;
    BOOL wheelLikeCandidate;
} HIDScrollClassification;

static inline UInt16 usbIdFromDevice(IOHIDDeviceRef device, NSString *key) {
    CFTypeRef value = IOHIDDeviceGetProperty(device, (__bridge CFStringRef)key);
    if (value == NULL) {
        return 0;
    }
    return [(__bridge NSNumber *)value unsignedShortValue];
}

static inline BOOL isNintendo(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    return vendorId == 0x057E && (productId == 0x2009);
}

static inline BOOL isXbox(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    // Microsoft Xbox controllers (vendor 0x045E):
    //   0x02FD - Xbox One (original GIP)
    //   0x0B00 - Xbox Elite 2 (BTH)
    //   0x0B05 - Xbox Elite 2 (USB)
    //   0x0B13 - Xbox Series X|S
    //   0x0B22 - Xbox Elite Series 2 Core
    //
    // 0x02E0 is deliberately absent. It is a KingKong product id that borrows
    // the Microsoft vendor id, so listing it here would claim the device for
    // the Xbox report layout and hide it from isKingKong, whose axis map
    // differs: KingKong reports the right stick on Rx/Ry and the triggers on
    // Z/Rz, while Xbox reports the right stick on Z/Rz. Keep the two sets
    // disjoint and let isKingKong win whenever they would overlap.
    return vendorId == 0x045E &&
        (productId == 0x02FD ||
         productId == 0x0B00 ||
         productId == 0x0B05 ||
         productId == 0x0B13 ||
         productId == 0x0B22);
}

static inline BOOL isKingKong(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    // KingKong / Betop Zeus devices:
    //   0x045E:0x02E0 - borrows the Microsoft vendor id, so it is the one
    //     overlap between isXbox and isKingKong and must be settled here.
    //   0x2DC8:0x2000+ - known Betop vid range (e.g. BTP-A1T2/A1U2/A1S2)
    if (vendorId == 0x045E && productId == 0x02E0) {
        return YES;
    }
    if (vendorId == 0x2DC8 && (productId == 0x2000 || productId == 0x2020 || productId == 0x2100)) {
        return YES;
    }
    // Betop/8Bitdo also use 0x1235 / 0x1532 / 0x2DE8 in adapter mode. Only add
    // known Zeus product ids here to avoid mis-identifying HID keyboards/mice.
    return NO;
}

static inline BOOL isPlayStation(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    return vendorId == 0x054C && (productId == 0x09CC || productId == 0x05C4 || productId == 0x0CE6);
}

static inline BOOL isPS4(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    return vendorId == 0x054C && (productId == 0x09CC || productId == 0x05c4);
}

static inline BOOL isPS5(IOHIDDeviceRef device) {
    UInt16 vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    UInt16 productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    return vendorId == 0x054C && (productId == 0x0ce6);
}

static inline PML_INPUT_STREAM_CONTEXT HIDInputContext(HIDSupport *support) {
    PML_INPUT_STREAM_CONTEXT ctx = (PML_INPUT_STREAM_CONTEXT)support.inputContext;
    if (ctx != NULL && ctx->connectionContext != NULL) {
        LiSetThreadConnectionContext(ctx->connectionContext);
    }
    return ctx;
}

static inline bool HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) {
    static CFAbsoluteTime lastLogTime = 0;
    CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
    if (ctx == NULL) {
        if (now - lastLogTime > 1.0) {
            Log(LOG_W, @"Input dropped (%s): inputContext is NULL", op);
            lastLogTime = now;
        }
        return false;
    }
    if (!LiInputContextIsInitialized(ctx)) {
        if (now - lastLogTime > 1.0) {
            Log(LOG_W, @"Input dropped (%s): inputContext not initialized (ctx=%p conn=%p)", op, ctx, LiInputContextGetConnectionCtx(ctx));
            lastLogTime = now;
        }
        return false;
    }
    return true;
}

static inline void HIDDispatchInput(HIDSupport *support, PML_INPUT_STREAM_CONTEXT inputCtx, dispatch_block_t block) {
    if (inputCtx == NULL) {
        return;
    }
    PML_CONNECTION_CONTEXT connCtx = inputCtx->connectionContext;
    dispatch_async(support.inputQueue, ^{
        if (connCtx != NULL) {
            LiSetThreadConnectionContext(connCtx);
        }
        block();
    });
}

static inline CGFloat HIDPointerSensitivityForHost(TemporaryHost *host) {
    CGFloat sensitivity = [SettingsClass pointerSensitivityFor:host.uuid];
    if (!isfinite(sensitivity) || sensitivity <= 0.0) {
        return 1.0;
    }
    return MIN(MAX(sensitivity, 0.25), 3.0);
}

static inline CGFloat HIDNormalizedScrollSpeed(CGFloat speed, CGFloat fallback) {
    if (!isfinite(speed) || speed <= 0.0) {
        return fallback;
    }
    return MIN(MAX(speed, 0.1), 4.0);
}

static inline CGFloat HIDWheelScrollSpeedForHost(TemporaryHost *host) {
    return HIDNormalizedScrollSpeed([SettingsClass wheelScrollSpeedFor:host.uuid], 1.0);
}

static inline CGFloat HIDRewrittenScrollSpeedForHost(TemporaryHost *host) {
    return HIDNormalizedScrollSpeed([SettingsClass rewrittenScrollSpeedFor:host.uuid], 1.0);
}

static inline CGFloat HIDGestureScrollSpeedForHost(TemporaryHost *host) {
    return HIDNormalizedScrollSpeed([SettingsClass gestureScrollSpeedFor:host.uuid], 1.0);
}

static inline CGFloat HIDPhysicalWheelHighPrecisionScaleForHost(TemporaryHost *host) {
    CGFloat scale = [SettingsClass physicalWheelHighPrecisionScaleFor:host.uuid];
    if (!isfinite(scale) || scale <= 0.0) {
        return 7.0;
    }
    return MIN(MAX(scale, 1.0), 12.0);
}

static inline CGFloat HIDSmartWheelTailFilterForHost(TemporaryHost *host) {
    CGFloat threshold = [SettingsClass smartWheelTailFilterFor:host.uuid];
    if (!isfinite(threshold) || threshold < 0.0) {
        return 0.0;
    }
    return MIN(MAX(threshold, 0.0), 1.0);
}

static inline CGFloat HIDPhysicalWheelHighPrecisionScrollSpeed(TemporaryHost *host, CGFloat baseSpeed) {
    CGFloat normalizedBase = HIDNormalizedScrollSpeed(baseSpeed, 1.0);
    return normalizedBase * HIDPhysicalWheelHighPrecisionScaleForHost(host);
}

static inline HIDPhysicalWheelModeOption HIDPhysicalWheelModeForHost(TemporaryHost *host) {
    return (HIDPhysicalWheelModeOption)[SettingsClass physicalWheelModeFor:host.uuid];
}

static inline HIDRewrittenScrollModeOption HIDRewrittenScrollModeForHost(TemporaryHost *host) {
    return (HIDRewrittenScrollModeOption)[SettingsClass rewrittenScrollModeFor:host.uuid];
}

static inline short HIDScaledRelativeDelta(CGFloat delta, CGFloat sensitivity) {
    if (delta == 0.0) {
        return 0;
    }

    CGFloat scaled = delta * sensitivity;
    if (scaled > SHRT_MAX) {
        scaled = SHRT_MAX;
    } else if (scaled < SHRT_MIN) {
        scaled = SHRT_MIN;
    } else if (fabs(scaled) < 1.0) {
        scaled = scaled > 0.0 ? 1.0 : -1.0;
    }

    return (short)lrint(scaled);
}

/** Send the whole pixels a relative move has earned, and remember the rest.
 *
 * HIDScaledRelativeDelta answers every frame on its own and promises at least one
 * pixel whenever a frame's scaled move is non-zero but under one. At the low end of
 * the Pointer Sensitivity slider (0.25, which the settings UI offers and the
 * function above clamps to) that promise is a lie in the loud direction: a frame
 * asking for a tenth of a pixel ships a whole one, so moving the cursor carefully
 * moves it ten times too far, and the difference between the ends of the slider is
 * made of how often the promise fires rather than of the number the player set.
 * Noise drifts the same way, because every jitter of any size ships a pixel it was
 * never asked for and nothing ever subtracts it.
 *
 * This drains a running debt instead: the sub-pixel remainder stays with the caller
 * and the next frame adds to it, so over any number of frames what ships differs
 * from what was asked by less than one pixel. A slow move arrives a frame late,
 * which is what scaling means; it does not arrive amplified, and a reversal pays
 * back the residue rather than being charged for it.
 *
 * Residual state belongs to whoever drains it, and each caller here runs on one
 * thread, so an ordinary CGFloat is enough -- the pointer deltas themselves are
 * already handed over atomically by HIDMouseDeltaAccumulator.
 */
static inline short HIDDrainRelativeDelta(CGFloat *residual, CGFloat delta, CGFloat sensitivity) {
    if (residual == NULL) {
        return 0;
    }
    if (!isfinite(*residual)) {
        *residual = 0.0;
    }
    if (delta == 0.0 || !isfinite(delta) || !isfinite(sensitivity)) {
        return 0;
    }

    CGFloat owed = *residual + (delta * sensitivity);
    if (!isfinite(owed)) {
        *residual = 0.0;
        return 0;
    }

    CGFloat clamped = owed;
    if (clamped > SHRT_MAX) {
        clamped = SHRT_MAX;
    } else if (clamped < SHRT_MIN) {
        clamped = SHRT_MIN;
    }

    short move = (short)clamped;
    *residual = owed - (CGFloat)move;
    return move;
}

static inline CGFloat HIDAbsoluteMouseReferencePrecisionScale(NSSize referenceSize) {
    CGFloat width = MAX(referenceSize.width, 1.0);
    CGFloat height = MAX(referenceSize.height, 1.0);
    CGFloat maxDimension = ceil(MAX(width, height));
    if (!isfinite(maxDimension) || maxDimension <= 0.0) {
        return 1.0;
    }

    CGFloat maxSafeScale = floor((((CGFloat)SHRT_MAX) - 1.0) / maxDimension);
    if (!isfinite(maxSafeScale) || maxSafeScale < 1.0) {
        return 1.0;
    }

    return MIN(8.0, maxSafeScale);
}

static inline BOOL HIDAbsoluteMousePositionForViewPoint(NSPoint viewPoint,
                                                        NSSize referenceSize,
                                                        BOOL clampToBounds,
                                                        short *hostX,
                                                        short *hostY,
                                                        short *referenceWidth,
                                                        short *referenceHeight) {
    CGFloat width = MAX(referenceSize.width, 1.0);
    CGFloat height = MAX(referenceSize.height, 1.0);
    CGFloat precisionScale = HIDAbsoluteMouseReferencePrecisionScale(referenceSize);
    CGFloat scaledWidth = MAX(1.0, floor(width * precisionScale));
    CGFloat scaledHeight = MAX(1.0, floor(height * precisionScale));
    CGFloat x = isfinite(viewPoint.x) ? viewPoint.x : 0.0;
    CGFloat y = isfinite(viewPoint.y) ? viewPoint.y : 0.0;

    if (clampToBounds) {
        x = MIN(MAX(x, 0.0), width - 1.0);
        y = MIN(MAX(y, 0.0), height - 1.0);
    }

    if (hostX != NULL) {
        *hostX = (short)lrint(MIN(MAX(x * precisionScale, 0.0), scaledWidth - 1.0));
    }
    if (hostY != NULL) {
        *hostY = (short)lrint(MIN(MAX((height - y) * precisionScale, 0.0), scaledHeight));
    }
    if (referenceWidth != NULL) {
        *referenceWidth = (short)lrint(scaledWidth);
    }
    if (referenceHeight != NULL) {
        *referenceHeight = (short)lrint(scaledHeight);
    }

    return YES;
}

static inline BOOL HIDAbsoluteMouseReferenceForEvent(NSEvent *event,
                                                     NSPoint *viewPoint,
                                                     NSSize *referenceSize) {
    if (event == nil || event.window == nil || event.window.contentView == nil) {
        return NO;
    }

    NSView *contentView = event.window.contentView;
    NSPoint convertedPoint = [contentView convertPoint:event.locationInWindow fromView:nil];
    NSSize boundsSize = contentView.bounds.size;
    if (!isfinite(convertedPoint.x) || !isfinite(convertedPoint.y) ||
        !isfinite(boundsSize.width) || !isfinite(boundsSize.height)) {
        return NO;
    }

    if (viewPoint != NULL) {
        *viewPoint = convertedPoint;
    }
    if (referenceSize != NULL) {
        *referenceSize = boundsSize;
    }

    return YES;
}

static inline BOOL HIDAbsoluteMouseReferenceForCurrentPointer(NSWindow *window,
                                                              NSPoint *viewPoint,
                                                              NSSize *referenceSize) {
    if (window == nil || window.contentView == nil) {
        return NO;
    }

    NSView *contentView = window.contentView;
    NSPoint screenPoint = [NSEvent mouseLocation];
    NSPoint windowPoint = [window convertPointFromScreen:screenPoint];
    NSPoint convertedPoint = [contentView convertPoint:windowPoint fromView:nil];
    NSSize boundsSize = contentView.bounds.size;
    if (!isfinite(convertedPoint.x) || !isfinite(convertedPoint.y) ||
        !isfinite(boundsSize.width) || !isfinite(boundsSize.height)) {
        return NO;
    }

    if (viewPoint != NULL) {
        *viewPoint = convertedPoint;
    }
    if (referenceSize != NULL) {
        *referenceSize = boundsSize;
    }

    return YES;
}

static inline BOOL HIDShouldUseHybridFreeMouseMotion(HIDSupport *support) {
    return [SettingsClass shouldUseHybridFreeMouseMotionFor:support.host.uuid];
}

static inline BOOL HIDShouldUseCoreHIDFreeMouseAbsoluteSync(HIDSupport *support) {
    NSString *mouseMode = [SettingsClass mouseModeFor:support.host.uuid];
    BOOL remoteDesktopMode = [mouseMode isEqualToString:@"remote"];
    return remoteDesktopMode &&
           support.useCoreHIDMouse &&
           !support.useGCMouse &&
           !support.coreHIDMouseRuntimeFailed &&
           HIDShouldUseHybridFreeMouseMotion(support);
}

static inline BOOL HIDShouldUseAbsolutePointerPath(HIDSupport *support, NSInteger touchscreenMode) {
    NSString *mouseMode = [SettingsClass mouseModeFor:support.host.uuid];
    BOOL remoteDesktopMode = [mouseMode isEqualToString:@"remote"];
    return (remoteDesktopMode &&
            (!HIDShouldUseHybridFreeMouseMotion(support) || support.coreHIDMouseRuntimeFailed))
           || touchscreenMode == 1;
}

static inline BOOL HIDShouldSuppressRelativeMouse(HIDSupport *support) {
    uint64_t untilMs = support.suppressRelativeMouseUntilMs;
    return untilMs > 0 && LiGetMillis() < untilMs;
}

static inline void HIDInvalidateCoreHIDFreeMouseAbsoluteSync(HIDSupport *support) {
    support.coreHIDFreeMouseAbsoluteSyncScheduled = NO;
    support.coreHIDFreeMouseAbsoluteSyncToken += 1;
}

static inline uint32_t HIDMouseButtonBitForButton(int button) {
    switch (button) {
        case BUTTON_LEFT:
            return 1u << 0;
        case BUTTON_MIDDLE:
            return 1u << 1;
        case BUTTON_RIGHT:
            return 1u << 2;
        case BUTTON_X1:
            return 1u << 3;
        case BUTTON_X2:
            return 1u << 4;
        default:
            return 0;
    }
}

static short const HIDScrollWheelDelta = 120;
// Tight window to catch only true macOS-generated duplicate events
// (which arrive within a few milliseconds of each other).
// The old 240/360ms values created a dead zone that dropped ~25% of
// legitimate scroll events, causing stutter, latency, and missed scrolls.
static uint64_t const HIDQuantizedWheelDuplicateSuppressMinMs = 25;
static uint64_t const HIDQuantizedWheelDuplicateSuppressMaxMs = 50;
// Duration to suppress AppKit scroll events after a GCMouse scroll dispatch.
// AppKit echoes arrive within ~10ms; 80ms provides a safe margin.
static uint64_t const HIDGCMouseAppKitSuppressMs = 80;
static inline NSInteger HIDScrollEventIntegerField(NSEvent *event, CGEventField field) {
    if (event == nil || event.CGEvent == NULL) {
        return 0;
    }

    return (NSInteger)CGEventGetIntegerValueField(event.CGEvent, field);
}

static inline BOOL HIDScrollEventHasMomentumOrPhase(NSEvent *event) {
    if (event == nil) {
        return NO;
    }

    return event.phase != NSEventPhaseNone || event.momentumPhase != NSEventPhaseNone;
}

static inline BOOL HIDScrollEventIsContinuous(NSEvent *event, BOOL horizontalDominant) {
    if (event == nil) {
        return NO;
    }

    CGEventField rawField = horizontalDominant ? kCGScrollWheelEventRawDeltaAxis2 : kCGScrollWheelEventRawDeltaAxis1;
    CGEventField lineField = horizontalDominant ? kCGScrollWheelEventDeltaAxis2 : kCGScrollWheelEventDeltaAxis1;
    CGEventField pointField = horizontalDominant ? kCGScrollWheelEventPointDeltaAxis2 : kCGScrollWheelEventPointDeltaAxis1;
    NSInteger continuousField = HIDScrollEventIntegerField(event, kCGScrollWheelEventIsContinuous);
    NSInteger rawDelta = HIDScrollEventIntegerField(event, rawField);
    NSInteger lineDelta = HIDScrollEventIntegerField(event, lineField);
    NSInteger pointDelta = HIDScrollEventIntegerField(event, pointField);
    BOOL hasMomentumOrPhase = HIDScrollEventHasMomentumOrPhase(event);

    if (hasMomentumOrPhase) {
        return YES;
    }

    if (!event.hasPreciseScrollingDeltas) {
        if (lineDelta != 0 || rawDelta != 0) {
            return NO;
        }
        return continuousField != 0;
    }

    if (rawDelta != 0) {
        return NO;
    }

    if (lineDelta != 0) {
        return labs(pointDelta) > MAX(labs(lineDelta), 1);
    }

    if (pointDelta != 0) {
        return YES;
    }

    return continuousField != 0;
}

static inline NSInteger HIDScrollEventDiscreteDeltaForAxis(NSEvent *event,
                                                           CGEventField rawField,
                                                           CGEventField lineField,
                                                           CGFloat fallbackDelta) {
    NSInteger rawDelta = HIDScrollEventIntegerField(event, rawField);
    if (rawDelta != 0) {
        return rawDelta;
    }

    NSInteger lineDelta = HIDScrollEventIntegerField(event, lineField);
    if (lineDelta != 0) {
        return lineDelta;
    }

    if (!isfinite(fallbackDelta) || fabs(fallbackDelta) < 1.0) {
        return 0;
    }

    return fallbackDelta > 0.0 ? 1 : -1;
}

static inline BOOL HIDScrollEventShouldQuantizePreciseWheel(BOOL hasPreciseDeltas,
                                                            NSInteger rawWheelDelta,
                                                            NSInteger lineDelta,
                                                            NSInteger fixedDeltaRaw,
                                                            NSEventPhase phase,
                                                            NSEventPhase momentumPhase) {
    if (!hasPreciseDeltas) {
        return NO;
    }

    if (rawWheelDelta != 0 ||
        phase != NSEventPhaseNone ||
        momentumPhase != NSEventPhaseNone) {
        return NO;
    }

    return lineDelta != 0 || fixedDeltaRaw != 0;
}

static inline BOOL HIDScrollEventShouldForceDiscreteWheel(HIDSupport *support,
                                                          NSEvent *event,
                                                          NSInteger rawWheelDelta,
                                                          NSInteger lineDelta,
                                                          NSInteger fixedDeltaRaw) {
    if (support.useGCMouse) {
        return NO;
    }
    if (event == nil) {
        return NO;
    }
    if (HIDScrollEventHasMomentumOrPhase(event)) {
        return NO;
    }
    if (event.scrollingDeltaX == 0.0 && event.scrollingDeltaY == 0.0 &&
        rawWheelDelta == 0 && lineDelta == 0 && fixedDeltaRaw == 0) {
        return NO;
    }

    return YES;
}

static inline HIDScrollClassification HIDClassifyAppKitScrollEvent(HIDSupport *support,
                                                                   NSEvent *event,
                                                                   BOOL horizontalDominant,
                                                                   NSInteger rawWheelDelta,
                                                                   NSInteger lineDelta,
                                                                   NSInteger fixedDeltaRaw) {
    HIDScrollClassification classification;
    classification.sourceKind = HIDInputSourceKindAppKit;
    classification.semanticKind = HIDScrollSemanticKindDiscreteWheel;
    classification.capabilities = 0;
    classification.quantizedWheel = NO;
    classification.wheelLikeCandidate = NO;

    if (event == nil) {
        return classification;
    }

    BOOL hasMomentumOrPhase = HIDScrollEventHasMomentumOrPhase(event);
    BOOL continuous = HIDScrollEventIsContinuous(event, horizontalDominant);
    BOOL quantizedPreciseWheel = HIDScrollEventShouldQuantizePreciseWheel(event.hasPreciseScrollingDeltas,
                                                                          rawWheelDelta,
                                                                          lineDelta,
                                                                          fixedDeltaRaw,
                                                                          event.phase,
                                                                          event.momentumPhase);
    BOOL forceDiscreteWheel = HIDScrollEventShouldForceDiscreteWheel(support,
                                                                     event,
                                                                     rawWheelDelta,
                                                                     lineDelta,
                                                                     fixedDeltaRaw);
    BOOL hasNativeWheelFields = rawWheelDelta != 0 || lineDelta != 0 || fixedDeltaRaw != 0;
    BOOL hasDelta = event.scrollingDeltaX != 0.0 || event.scrollingDeltaY != 0.0;
    CGFloat dominantAbsDelta = horizontalDominant ? fabs(event.scrollingDeltaX) : fabs(event.scrollingDeltaY);
    BOOL syntheticTailCandidate = !hasMomentumOrPhase &&
                                  !continuous &&
                                  !hasNativeWheelFields &&
                                  dominantAbsDelta > 0.0 &&
                                  dominantAbsDelta < 1.0;

    classification.wheelLikeCandidate = forceDiscreteWheel || quantizedPreciseWheel;
    if (!classification.wheelLikeCandidate &&
        !continuous &&
        !hasMomentumOrPhase &&
        hasDelta &&
        !hasNativeWheelFields &&
        dominantAbsDelta >= 1.0) {
        classification.wheelLikeCandidate = YES;
    }

    if (continuous && !quantizedPreciseWheel) {
        classification.semanticKind = HIDScrollSemanticKindContinuousGestureScroll;
        classification.capabilities |= HIDInputCapabilityContinuousScrollGesture;
        if (event.hasPreciseScrollingDeltas) {
            classification.capabilities |= HIDInputCapabilityHighReportRate;
        }
        return classification;
    }

    if (horizontalDominant) {
        classification.capabilities |= HIDInputCapabilityDiscreteHorizontalWheel;
        classification.semanticKind = HIDScrollSemanticKindHorizontalWheel;
    } else {
        classification.capabilities |= HIDInputCapabilityDiscreteVerticalWheel;
        classification.semanticKind = HIDScrollSemanticKindDiscreteWheel;
    }

    if (event.hasPreciseScrollingDeltas) {
        classification.capabilities |= HIDInputCapabilityHighReportRate;
    }

    if (classification.wheelLikeCandidate) {
        classification.quantizedWheel = YES;
    }

    if (syntheticTailCandidate) {
        classification.semanticKind = HIDScrollSemanticKindSyntheticOrRewrittenScroll;
        classification.quantizedWheel = NO;
        if (event.hasPreciseScrollingDeltas) {
            classification.capabilities |= HIDInputCapabilityHighReportRate;
        }
        classification.capabilities |= HIDInputCapabilityVendorEnhancementAvailable;
    }

    return classification;
}

static inline NSString *HIDScrollDiagnosticModeForClassification(HIDScrollClassification classification) {
    switch (classification.semanticKind) {
        case HIDScrollSemanticKindContinuousGestureScroll:
            return @"appkit-continuous-gesture";
        case HIDScrollSemanticKindHorizontalWheel:
            return classification.quantizedWheel ? @"appkit-horizontal-wheel" : @"appkit-horizontal-scroll";
        case HIDScrollSemanticKindSyntheticOrRewrittenScroll:
            return @"appkit-synthetic-rewritten";
        case HIDScrollSemanticKindDiscreteWheel:
        default:
            return classification.quantizedWheel ? @"appkit-discrete-wheel" : @"appkit-discrete-scroll";
    }
}

static inline short HIDDeduplicatedScrollClick(HIDSupport *support,
                                               short clicks,
                                                     BOOL horizontalAxis,
                                                     BOOL deduplicateBurst) {
    if (clicks == 0) {
        return 0;
    }

    if (!deduplicateBurst) {
        return clicks;
    }

    uint64_t nowMs = LiGetMillis();
    uint64_t lastEventMs = horizontalAxis ? support.accumulatedQuantizedWheelLastEventMsX
                                          : support.accumulatedQuantizedWheelLastEventMsY;
    CGFloat previousClicks = horizontalAxis ? support.accumulatedQuantizedWheelDeltaX
                                            : support.accumulatedQuantizedWheelDeltaY;
    BOOL sameDirection = (previousClicks > 0.0 && clicks > 0) ||
                         (previousClicks < 0.0 && clicks < 0);
    uint64_t elapsedMs = lastEventMs != 0 && nowMs >= lastEventMs ? (nowMs - lastEventMs) : UINT64_MAX;

    // Suppress only true macOS-generated duplicates that arrive within
    // a very tight window (< 25ms) in the same direction.  Anything
    // further apart is a legitimate separate scroll action.
    if (sameDirection && lastEventMs != 0 && elapsedMs < HIDQuantizedWheelDuplicateSuppressMinMs) {
        return 0;
    }

    // Always update timestamp on dispatch so elapsed time is measured
    // from the most recent dispatched event, not the first one.
    if (horizontalAxis) {
        support.accumulatedQuantizedWheelLastEventMsX = nowMs;
        support.accumulatedQuantizedWheelDeltaX = (CGFloat)clicks;
    } else {
        support.accumulatedQuantizedWheelLastEventMsY = nowMs;
        support.accumulatedQuantizedWheelDeltaY = (CGFloat)clicks;
    }
    return clicks;
}

static inline short HIDDispatchAccumulatedHighResScrollDelta(CGFloat *accumulatedDelta) {
    if (accumulatedDelta == NULL || !isfinite(*accumulatedDelta)) {
        if (accumulatedDelta != NULL) {
            *accumulatedDelta = 0.0;
        }
        return 0;
    }

    CGFloat clamped = *accumulatedDelta;
    if (clamped > SHRT_MAX) {
        clamped = SHRT_MAX;
    } else if (clamped < SHRT_MIN) {
        clamped = SHRT_MIN;
    }

    short dispatchedDelta = (short)clamped;
    *accumulatedDelta -= dispatchedDelta;
    if (fabs(*accumulatedDelta) < 0.0001) {
        *accumulatedDelta = 0.0;
    }
    return dispatchedDelta;
}

/** How many notches a wheel event actually went through.
 *
 * The count comes from the event's own wheel fields, which carry more than one notch
 * whenever AppKit coalesces a fast scroll into a single event, whenever a
 * free-spinning wheel reports several detents at once, and whenever the driver
 * reports a jump. Clamping that to one here was the same loss the accumulated
 * consumer had, only with less to show for it: the quantized and fallback branches
 * each answer once per event and keep nothing back, so a three-notch event shipped
 * one notch and the other two never existed anywhere.
 *
 * The floor stays, because it is a different thing: a real detent that rounds below
 * one has to send something, or the wheel looks broken at exactly the moment the
 * player is gentlest with it. The bound that replaces the clamp is the packet -- the
 * caller multiplies by HIDScrollWheelDelta into a short, and saturating an absurd
 * frame is honest where wrapping through SHRT_MIN would scroll the host backwards.
 */
static inline short HIDNormalizedDiscreteScrollClick(CGFloat delta) {
    if (!isfinite(delta) || delta == 0.0) {
        return 0;
    }

    NSInteger clicks = (NSInteger)llround(delta);
    if (clicks == 0) {
        clicks = delta > 0.0 ? 1 : -1;
    }
    NSInteger limit = SHRT_MAX / HIDScrollWheelDelta;
    if (clicks > limit) {
        clicks = limit;
    } else if (clicks < -limit) {
        clicks = -limit;
    }
    return (short)clicks;
}

/** Turn a notch count into the units one scroll packet can carry at this speed.
 *
 * Kept separate from the count because the two bounds are different: the count is
 * bounded by what a packet can hold at the default speed, and the units are bounded
 * again after the speed multiplier, which reaches 4.0 in the settings UI. Multiplying
 * first and clamping here is what keeps three notches at 4x speed -- 1440 units --
 * inside the short, where clamping the count alone would still have allowed a wrap.
 */
static inline short HIDDiscreteScrollPacketUnits(short clicks, CGFloat speed) {
    if (clicks == 0) {
        return 0;
    }
    if (!isfinite(speed) || speed <= 0.0) {
        speed = 1.0;
    }

    CGFloat units = llround((CGFloat)clicks * (CGFloat)HIDScrollWheelDelta * speed);
    if (!isfinite(units)) {
        return clicks > 0 ? SHRT_MAX : SHRT_MIN;
    }
    if (units > SHRT_MAX) {
        units = SHRT_MAX;
    } else if (units < SHRT_MIN) {
        units = SHRT_MIN;
    }
    if (units == 0.0) {
        units = clicks > 0 ? 1.0 : -1.0;
    }
    return (short)units;
}

static inline short HIDConsumeAccumulatedDiscreteScrollClick(CGFloat *accumulatedDelta) {
    if (accumulatedDelta == NULL || !isfinite(*accumulatedDelta)) {
        if (accumulatedDelta != NULL) {
            *accumulatedDelta = 0.0;
        }
        return 0;
    }

    if (fabs(*accumulatedDelta) < 1.0) {
        return 0;
    }

    CGFloat whole = *accumulatedDelta > 0.0 ? floor(*accumulatedDelta) : ceil(*accumulatedDelta);

    // Emit every whole notch the arrival contains, and subtract exactly that. The
    // fraction stays, which is what lets a slow drag add up to a notch, but a whole
    // notch must not: a scroll gesture ends by simply stopping, and nothing else in
    // this file ever empties the accumulator, so a notch held here after lift-off is
    // a notch the host never learns about. Clamping the answer to one notch while
    // the arrival can be several is how a fast flick lost most of its distance --
    // four frames asking for fifteen and a half notches shipped four.
    //
    // One packet is a short measured in HIDScrollWheelDelta units, so the most this
    // may return is SHRT_MAX / HIDScrollWheelDelta. Sending more would wrap the short
    // at the call site and hand the host the opposite direction; leaving the rest is
    // the same bargain HIDDispatchAccumulatedHighResScrollDelta strikes, and it is a
    // queue rather than a loss, because the next frame of the same gesture drains it.
    CGFloat limit = (CGFloat)(SHRT_MAX / HIDScrollWheelDelta);
    if (whole > limit) {
        whole = limit;
    } else if (whole < -limit) {
        whole = -limit;
    }

    *accumulatedDelta -= whole;
    if (fabs(*accumulatedDelta) < 0.0001) {
        *accumulatedDelta = 0.0;
    }

    return (short)whole;
}
