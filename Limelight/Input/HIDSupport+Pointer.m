//
//  HIDSupport+Pointer.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 26/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//
#import "HIDSupport_Internal.h"

// CVDisplayLink is deprecated in macOS 15.0 but remains the recommended API
// for low-latency pointer input. The new NSView.displayLink API is not yet
// validated for sub-frame input latency. Suppress deprecation at file scope;
// tracked for migration in a future release.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

static CGFloat const HIDGCMouseRelativeSpeedDivisor = 2.5;
static CGFloat const HIDCoreHIDFreeMouseBaselineScale = 0.75;

static inline BOOL HIDAbsoluteMousePayloadForEvent(NSEvent *event,
                                                   BOOL clampToBounds,
                                                   short *hostX,
                                                   short *hostY,
                                                   short *referenceWidth,
                                                   short *referenceHeight) {
    NSPoint viewPoint;
    NSSize referenceSize;
    if (!HIDAbsoluteMouseReferenceForEvent(event, &viewPoint, &referenceSize)) {
        return NO;
    }

    return HIDAbsoluteMousePositionForViewPoint(viewPoint,
                                                referenceSize,
                                                clampToBounds,
                                                hostX,
                                                hostY,
                                                referenceWidth,
                                                referenceHeight);
}

static inline CGFloat HIDClampFreeMouseCoordinate(CGFloat value, CGFloat upperBound) {
    if (!isfinite(value)) {
        return 0.0;
    }
    if (!isfinite(upperBound) || upperBound <= 0.0) {
        return 0.0;
    }
    if (value < 0.0) {
        return 0.0;
    }
    if (value > upperBound) {
        return upperBound;
    }
    return value;
}

static inline NSPoint HIDClampFreeMousePoint(NSPoint point, NSSize referenceSize) {
    CGFloat maxX = MAX(0.0, referenceSize.width);
    CGFloat maxY = MAX(0.0, referenceSize.height);
    return NSMakePoint(HIDClampFreeMouseCoordinate(point.x, maxX),
                       HIDClampFreeMouseCoordinate(point.y, maxY));
}

static inline double HIDClampFreeMouseGain(double value) {
    if (!isfinite(value)) {
        return 1.0;
    }
    if (value < 0.25) {
        return 0.25;
    }
    if (value > 4.0) {
        return 4.0;
    }
    return value;
}

static inline double HIDBlendFreeMouseGain(double currentGain, double rawDelta, double observedDelta) {
    if (!isfinite(rawDelta) || !isfinite(observedDelta)) {
        return currentGain;
    }
    if (fabs(rawDelta) < 0.5 || fabs(observedDelta) < 0.25) {
        return currentGain;
    }
    if ((rawDelta > 0.0 && observedDelta < 0.0) || (rawDelta < 0.0 && observedDelta > 0.0)) {
        return currentGain;
    }

    double sample = fabs(observedDelta / rawDelta);
    sample = HIDClampFreeMouseGain(sample);
    if (!isfinite(currentGain) || currentGain <= 0.0) {
        return sample;
    }

    return HIDClampFreeMouseGain((currentGain * 0.82) + (sample * 0.18));
}

@implementation HIDMouseDeltaAccumulator {
    _Atomic double _pendingX;
    _Atomic double _pendingY;
}
// Relaxed is the right ordering here. Each axis is an independent counter with
// no other data published alongside it that another thread has to observe in
// the same order, so the only requirement is that an add and a take never
// interleave into a lost update, which the atomic read-modify-write gives.
- (void)accumulateMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY {
    atomic_fetch_add_explicit(&_pendingX, (double)deltaX, memory_order_relaxed);
    atomic_fetch_add_explicit(&_pendingY, (double)deltaY, memory_order_relaxed);
}

- (void)takeAccumulatedMotionX:(CGFloat *)deltaXOut deltaY:(CGFloat *)deltaYOut {
    CGFloat takenX = (CGFloat)atomic_exchange_explicit(&_pendingX, 0.0, memory_order_relaxed);
    CGFloat takenY = (CGFloat)atomic_exchange_explicit(&_pendingY, 0.0, memory_order_relaxed);
    if (deltaXOut != NULL) {
        *deltaXOut = takenX;
    }
    if (deltaYOut != NULL) {
        *deltaYOut = takenY;
    }
}
@end

@implementation HIDSupport (Pointer)

// Capture changes, GC producers and the display-link consumer share self's
// lock. A quick uncapture/recapture must not carry buffered motion into the new
// capture, even when no display frame ran while forwarding was disabled.
- (void)resetPointerMotionForCaptureTransition {
    @synchronized (self) {
        [self.mouseDeltaAccumulator takeAccumulatedMotionX:NULL deltaY:NULL];
        self.relativeMotionResidualX = 0;
        self.relativeMotionResidualY = 0;
        self.relativeDeltaResidualX = 0;
        self.relativeDeltaResidualY = 0;
        self.mouseEmulationResidualX = 0;
        self.mouseEmulationResidualY = 0;
        @synchronized (self.inputDiagnosticsLock) {
            self.pendingCoalescedAbsolutePointerValid = NO;
            // Invalidate duplicate detection too: the host may have moved its
            // cursor while this capture did not own it.
            self.lastAbsolutePointerReferenceWidth = 0;
            self.lastAbsolutePointerReferenceHeight = 0;
            self.lastAbsolutePointerAtMs = 0;
        }
    }
}

- (void)accumulateCapturedMouseMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY {
    @synchronized (self) {
        if (!self.shouldSendInputEvents || !self.useGCMouse) return;
        [self.mouseDeltaAccumulator accumulateMotionX:deltaX deltaY:deltaY];
    }
}

/** Drop the motion owed to the host, because nothing is going to send it.

Each caller of this is a decision that the motion taken from the accumulator will
not be dispatched: the input context vanished, the pointer went absolute, or the
relative path is muted. Keeping the debt across that decision would bank a sub-pixel
fraction and then hand it to a later frame, so the cursor would answer a movement the
player finished making -- the same family of ghost motion this file has been fixing,
only with the delay measured in gestures instead of frames.
*/
- (void)resetRelativeMotionResidualForDisplayLinkConsumer {
    self.relativeMotionResidualX = 0.0;
    self.relativeMotionResidualY = 0.0;
}

- (void)suppressRelativeMouseMotionForMilliseconds:(uint64_t)durationMs {
    if (durationMs == 0) {
        self.suppressRelativeMouseUntilMs = 0;
        return;
    }
    self.suppressRelativeMouseUntilMs = LiGetMillis() + durationMs;
}

- (void)setFreeMouseVirtualCursorActive:(BOOL)active {
    self.freeMouseVirtualCursorRequestedActive = active;
    if (active) {
        return;
    }

    HIDInvalidateCoreHIDFreeMouseAbsoluteSync(self);
    [self resetFreeMouseVirtualCursorState];
}

- (void)resetFreeMouseVirtualCursorState {
    @synchronized (self.freeMouseVirtualCursorLock) {
        self.freeMouseVirtualCursorHasAnchor = NO;
        self.freeMouseVirtualCursorPoint = NSZeroPoint;
        self.freeMouseVirtualCursorLastAnchorPoint = NSZeroPoint;
        self.freeMouseVirtualCursorReferenceSize = NSZeroSize;
        self.freeMouseVirtualCursorGainX = 1.0;
        self.freeMouseVirtualCursorGainY = 1.0;
        self.freeMouseVirtualCursorRawSinceAnchorX = 0.0;
        self.freeMouseVirtualCursorRawSinceAnchorY = 0.0;
    }
}

- (void)updateFreeMouseVirtualCursorAnchorWithViewPoint:(NSPoint)viewPoint
                                          referenceSize:(NSSize)referenceSize {
    if (!self.freeMouseVirtualCursorRequestedActive) {
        return;
    }

    if (!isfinite(viewPoint.x) || !isfinite(viewPoint.y) ||
        !isfinite(referenceSize.width) || !isfinite(referenceSize.height) ||
        referenceSize.width <= 0.0 || referenceSize.height <= 0.0) {
        return;
    }

    NSPoint clampedPoint = HIDClampFreeMousePoint(viewPoint, referenceSize);
    BOOL shouldBlendGain = ![self hasPressedMouseButtons];

    @synchronized (self.freeMouseVirtualCursorLock) {
        if (self.freeMouseVirtualCursorHasAnchor && shouldBlendGain) {
            double observedDeltaX = clampedPoint.x - self.freeMouseVirtualCursorLastAnchorPoint.x;
            double observedDeltaY = clampedPoint.y - self.freeMouseVirtualCursorLastAnchorPoint.y;
            self.freeMouseVirtualCursorGainX = HIDBlendFreeMouseGain(self.freeMouseVirtualCursorGainX,
                                                                     self.freeMouseVirtualCursorRawSinceAnchorX,
                                                                     observedDeltaX);
            self.freeMouseVirtualCursorGainY = HIDBlendFreeMouseGain(self.freeMouseVirtualCursorGainY,
                                                                     self.freeMouseVirtualCursorRawSinceAnchorY,
                                                                     observedDeltaY);
        }

        self.freeMouseVirtualCursorPoint = clampedPoint;
        self.freeMouseVirtualCursorLastAnchorPoint = clampedPoint;
        self.freeMouseVirtualCursorReferenceSize = referenceSize;
        self.freeMouseVirtualCursorRawSinceAnchorX = 0.0;
        self.freeMouseVirtualCursorRawSinceAnchorY = 0.0;
        self.freeMouseVirtualCursorHasAnchor = YES;
    }
}

- (BOOL)reconcileFreeMouseVirtualCursorToViewPoint:(NSPoint)viewPoint
                                     referenceSize:(NSSize)referenceSize
                               correctionThreshold:(CGFloat)correctionThreshold {
    if (!self.freeMouseVirtualCursorRequestedActive) {
        return NO;
    }

    if (!isfinite(viewPoint.x) || !isfinite(viewPoint.y) ||
        !isfinite(referenceSize.width) || !isfinite(referenceSize.height) ||
        referenceSize.width <= 0.0 || referenceSize.height <= 0.0) {
        return NO;
    }

    NSPoint clampedPoint = HIDClampFreeMousePoint(viewPoint, referenceSize);
    BOOL shouldBlendGain = ![self hasPressedMouseButtons];
    CGFloat threshold = MAX(0.0, correctionThreshold);
    BOOL shouldSendCorrection = NO;

    @synchronized (self.freeMouseVirtualCursorLock) {
        if (self.freeMouseVirtualCursorHasAnchor) {
            if (shouldBlendGain) {
                double observedDeltaX = clampedPoint.x - self.freeMouseVirtualCursorLastAnchorPoint.x;
                double observedDeltaY = clampedPoint.y - self.freeMouseVirtualCursorLastAnchorPoint.y;
                self.freeMouseVirtualCursorGainX = HIDBlendFreeMouseGain(self.freeMouseVirtualCursorGainX,
                                                                         self.freeMouseVirtualCursorRawSinceAnchorX,
                                                                         observedDeltaX);
                self.freeMouseVirtualCursorGainY = HIDBlendFreeMouseGain(self.freeMouseVirtualCursorGainY,
                                                                         self.freeMouseVirtualCursorRawSinceAnchorY,
                                                                         observedDeltaY);
            }

            CGFloat driftX = fabs(clampedPoint.x - self.freeMouseVirtualCursorPoint.x);
            CGFloat driftY = fabs(clampedPoint.y - self.freeMouseVirtualCursorPoint.y);
            shouldSendCorrection = driftX > threshold || driftY > threshold;
        } else {
            shouldSendCorrection = YES;
        }

        self.freeMouseVirtualCursorPoint = clampedPoint;
        self.freeMouseVirtualCursorLastAnchorPoint = clampedPoint;
        self.freeMouseVirtualCursorReferenceSize = referenceSize;
        self.freeMouseVirtualCursorRawSinceAnchorX = 0.0;
        self.freeMouseVirtualCursorRawSinceAnchorY = 0.0;
        self.freeMouseVirtualCursorHasAnchor = YES;
    }

    if (shouldSendCorrection) {
        [self sendAbsoluteMousePositionForViewPoint:clampedPoint
                                      referenceSize:referenceSize
                                      clampToBounds:YES];
    }

    return shouldSendCorrection;
}

- (BOOL)getFreeMouseVirtualCursorPoint:(NSPoint *)viewPoint
                         referenceSize:(NSSize *)referenceSize {
    BOOL hasAnchor = NO;
    NSPoint currentPoint = NSZeroPoint;
    NSSize currentReferenceSize = NSZeroSize;

    @synchronized (self.freeMouseVirtualCursorLock) {
        hasAnchor = self.freeMouseVirtualCursorHasAnchor &&
                    self.freeMouseVirtualCursorReferenceSize.width > 0.0 &&
                    self.freeMouseVirtualCursorReferenceSize.height > 0.0;
        if (hasAnchor) {
            currentPoint = self.freeMouseVirtualCursorPoint;
            currentReferenceSize = self.freeMouseVirtualCursorReferenceSize;
        }
    }

    if (!hasAnchor) {
        return NO;
    }

    if (viewPoint != NULL) {
        *viewPoint = currentPoint;
    }
    if (referenceSize != NULL) {
        *referenceSize = currentReferenceSize;
    }
    return YES;
}

- (void)dispatchPendingCoalescedAbsolutePointerPosition {
    __block short hostX = 0;
    __block short hostY = 0;
    __block short referenceWidth = 0;
    __block short referenceHeight = 0;
    __block NSString *source = nil;
    __block BOOL hasPending = NO;
    __block HIDInputLease pendingLease = { NULL, 0 };
    __block uint64_t captureGeneration = 0;

    @synchronized (self.inputDiagnosticsLock) {
        if (self.pendingCoalescedAbsolutePointerValid) {
            hostX = self.pendingCoalescedAbsolutePointerHostX;
            hostY = self.pendingCoalescedAbsolutePointerHostY;
            referenceWidth = self.pendingCoalescedAbsolutePointerReferenceWidth;
            referenceHeight = self.pendingCoalescedAbsolutePointerReferenceHeight;
            source = [self.pendingCoalescedAbsolutePointerSource copy];
            pendingLease.context = (PML_INPUT_STREAM_CONTEXT)self.pendingCoalescedAbsolutePointerContext;
            pendingLease.generation = self.pendingCoalescedAbsolutePointerGeneration;
            captureGeneration = self.pendingCoalescedAbsolutePointerCaptureGeneration;
            self.pendingCoalescedAbsolutePointerValid = NO;
            hasPending = YES;
        } else {
            self.pendingCoalescedAbsolutePointerDispatch = NO;
        }
    }

    if (!hasPending) {
        return;
    }

    HIDExecuteInputLeaseOnQueue(self, pendingLease, ^{
        @synchronized (self) {
            if (!self.shouldSendInputEvents || captureGeneration != self.inputCaptureGeneration) return;
            if (source.length > 0) {
                [self recordAbsoluteInputDiagnosticsFrom:source
                                                       x:hostX
                                                       y:hostY
                                                   width:referenceWidth
                                                  height:referenceHeight];
            }
            LiSendMousePositionEventCtx(pendingLease.context, hostX, hostY, referenceWidth, referenceHeight);
        }
    });

    BOOL shouldScheduleNext = NO;
    @synchronized (self.inputDiagnosticsLock) {
        self.pendingCoalescedAbsolutePointerDispatch = NO;
        if (self.pendingCoalescedAbsolutePointerValid) {
            self.pendingCoalescedAbsolutePointerDispatch = YES;
            shouldScheduleNext = YES;
        }
    }

    if (shouldScheduleNext) {
        dispatch_async(self.inputQueue, ^{
            [self dispatchPendingCoalescedAbsolutePointerPosition];
        });
    }
}

- (void)sendCoalescedAbsoluteMousePositionForViewPoint:(NSPoint)viewPoint
                                         referenceSize:(NSSize)referenceSize
                                         clampToBounds:(BOOL)clampToBounds
                                             sourceTag:(NSString *)sourceTag {
    if (!self.shouldSendInputEvents) return;
    uint64_t captureGeneration = self.inputCaptureGeneration;
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "sendCoalescedAbsoluteMousePosition")) {
        return;
    }

    short hostX = 0;
    short hostY = 0;
    short referenceWidth = 0;
    short referenceHeight = 0;
    if (!HIDAbsoluteMousePositionForViewPoint(viewPoint,
                                              referenceSize,
                                              clampToBounds,
                                              &hostX,
                                              &hostY,
                                              &referenceWidth,
                                              &referenceHeight)) {
        return;
    }

    BOOL shouldSchedule = NO;
    BOOL isDuplicate = NO;
    @synchronized (self.inputDiagnosticsLock) {
        BOOL matchesLastKnown = hostX == self.lastAbsolutePointerHostX &&
                                hostY == self.lastAbsolutePointerHostY &&
                                referenceWidth == self.lastAbsolutePointerReferenceWidth &&
                                referenceHeight == self.lastAbsolutePointerReferenceHeight;
        BOOL matchesPending = self.pendingCoalescedAbsolutePointerValid &&
                              hostX == self.pendingCoalescedAbsolutePointerHostX &&
                              hostY == self.pendingCoalescedAbsolutePointerHostY &&
                              referenceWidth == self.pendingCoalescedAbsolutePointerReferenceWidth &&
                              referenceHeight == self.pendingCoalescedAbsolutePointerReferenceHeight;
        if (matchesLastKnown || matchesPending) {
            isDuplicate = YES;
            if (self.inputDiagnosticsEnabled) {
                self.inputDiagnosticsAbsoluteDuplicateSkips += 1;
            }
        } else {
            self.lastAbsolutePointerHostX = hostX;
            self.lastAbsolutePointerHostY = hostY;
            self.lastAbsolutePointerReferenceWidth = referenceWidth;
            self.lastAbsolutePointerReferenceHeight = referenceHeight;
            self.lastAbsolutePointerAtMs = LiGetMillis();
            self.lastAbsolutePointerSource = [sourceTag copy];
            self.pendingCoalescedAbsolutePointerHostX = hostX;
            self.pendingCoalescedAbsolutePointerHostY = hostY;
            self.pendingCoalescedAbsolutePointerReferenceWidth = referenceWidth;
            self.pendingCoalescedAbsolutePointerReferenceHeight = referenceHeight;
            self.pendingCoalescedAbsolutePointerSource = [sourceTag copy];
            self.pendingCoalescedAbsolutePointerContext = inputLease.context;
            self.pendingCoalescedAbsolutePointerGeneration = inputLease.generation;
            self.pendingCoalescedAbsolutePointerCaptureGeneration = captureGeneration;
            self.pendingCoalescedAbsolutePointerValid = YES;
            if (!self.pendingCoalescedAbsolutePointerDispatch) {
                self.pendingCoalescedAbsolutePointerDispatch = YES;
                shouldSchedule = YES;
            }
        }
    }

    if (isDuplicate || !shouldSchedule) {
        return;
    }

    dispatch_async(self.inputQueue, ^{
        [self dispatchPendingCoalescedAbsolutePointerPosition];
    });
}

- (BOOL)dispatchVirtualFreeMouseDeltaX:(double)deltaX
                                deltaY:(double)deltaY
                             sourceTag:(NSString *)sourceTag {
    (void)sourceTag;
    if (!self.freeMouseVirtualCursorRequestedActive ||
        !HIDShouldUseCoreHIDFreeMouseAbsoluteSync(self) ||
        !self.shouldSendInputEvents ||
        !isfinite(deltaX) ||
        !isfinite(deltaY) ||
        (deltaX == 0.0 && deltaY == 0.0)) {
        return NO;
    }

    CGFloat sensitivity = HIDPointerSensitivityForHost(self.host);
    double calibratedSensitivity = sensitivity * HIDCoreHIDFreeMouseBaselineScale;
    double viewDeltaX = deltaX * calibratedSensitivity;
    double viewDeltaY = -deltaY * calibratedSensitivity;

    NSPoint predictedPoint = NSZeroPoint;
    NSSize referenceSize = NSZeroSize;

    @synchronized (self.freeMouseVirtualCursorLock) {
        if (!self.freeMouseVirtualCursorHasAnchor ||
            self.freeMouseVirtualCursorReferenceSize.width <= 0.0 ||
            self.freeMouseVirtualCursorReferenceSize.height <= 0.0) {
            return NO;
        }

        double gainX = HIDClampFreeMouseGain(self.freeMouseVirtualCursorGainX);
        double gainY = HIDClampFreeMouseGain(self.freeMouseVirtualCursorGainY);
        predictedPoint = self.freeMouseVirtualCursorPoint;
        predictedPoint.x += viewDeltaX * gainX;
        predictedPoint.y += viewDeltaY * gainY;
        predictedPoint = HIDClampFreeMousePoint(predictedPoint, self.freeMouseVirtualCursorReferenceSize);

        self.freeMouseVirtualCursorRawSinceAnchorX += viewDeltaX;
        self.freeMouseVirtualCursorRawSinceAnchorY += viewDeltaY;
        self.freeMouseVirtualCursorPoint = predictedPoint;
        referenceSize = self.freeMouseVirtualCursorReferenceSize;
    }

    [self sendCoalescedAbsoluteMousePositionForViewPoint:predictedPoint
                                           referenceSize:referenceSize
                                           clampToBounds:YES
                                               sourceTag:@"sendAbsoluteMousePosition"];
    return YES;
}

- (NSString *)mouseButtonSourceForGCMouse:(GCMouse *)mouse API_AVAILABLE(macos(11.0)) {
    return [NSString stringWithFormat:@"gcmouse:%p", mouse];
}

- (GCControllerButtonValueChangedHandler)mouseButtonHandlerForButton:(int)button
                                                            source:(NSString *)source {
    __weak typeof(self) weakSelf = self;
    return ^(GCControllerButtonInput *input, float value, BOOL pressed) {
        (void)input;
        (void)value;
        __strong typeof(weakSelf) support = weakSelf;
        if (pressed && !support.useGCMouse) return;
        [support sendMouseButton:button pressed:pressed source:source];
    };
}

-(void)registerMouseCallbacks:(GCMouse *)mouse API_AVAILABLE(macos(11.0)) {
    NSString *source = [self mouseButtonSourceForGCMouse:mouse];
    __weak typeof(self) weakSelf = self;
    if (self.useGCMouse) {
        mouse.mouseInput.mouseMovedHandler = ^(GCMouseInput *mouseInput, float deltaX, float deltaY) {
            (void)mouseInput;
            __strong typeof(weakSelf) support = weakSelf;
            [support accumulateCapturedMouseMotionX:(CGFloat)deltaX deltaY:(CGFloat)-deltaY];
        };
        mouse.mouseInput.leftButton.pressedChangedHandler =
            [self mouseButtonHandlerForButton:BUTTON_LEFT source:source];
        mouse.mouseInput.middleButton.pressedChangedHandler =
            [self mouseButtonHandlerForButton:BUTTON_MIDDLE source:source];
        mouse.mouseInput.rightButton.pressedChangedHandler =
            [self mouseButtonHandlerForButton:BUTTON_RIGHT source:source];
        static const int auxiliaryCodes[] = { BUTTON_X1, BUTTON_X2 };
        [mouse.mouseInput.auxiliaryButtons enumerateObjectsUsingBlock:
            ^(GCControllerButtonInput *input, NSUInteger index, BOOL *stop) {
                (void)stop;
                input.pressedChangedHandler = index < sizeof(auxiliaryCodes) / sizeof(auxiliaryCodes[0])
                    ? [self mouseButtonHandlerForButton:auxiliaryCodes[index] source:source]
                    : nil;
            }];
    } else {
        [self releaseMouseButtonsForSource:source];
        mouse.mouseInput.mouseMovedHandler = nil;
        mouse.mouseInput.leftButton.pressedChangedHandler = nil;
        mouse.mouseInput.middleButton.pressedChangedHandler = nil;
        mouse.mouseInput.rightButton.pressedChangedHandler = nil;
        for (GCControllerButtonInput *auxButton in mouse.mouseInput.auxiliaryButtons) {
            auxButton.pressedChangedHandler = nil;
        }
    }

    if (mouse.mouseInput.scroll != nil) {
        mouse.mouseInput.scroll.valueChangedHandler = nil;
        if (self.useGCMouse) {
            mouse.mouseInput.scroll.yAxis.valueChangedHandler = ^(GCControllerAxisInput *axis, float value) {
                (void)axis;
                [weakSelf handleGCMouseScrollValueY:value];
            };
        } else {
            mouse.mouseInput.scroll.yAxis.valueChangedHandler = nil;
        }
    }
}

-(void)unregisterMouseCallbacks:(GCMouse*)mouse API_AVAILABLE(macos(11.0)) {
    [self releaseMouseButtonsForSource:[self mouseButtonSourceForGCMouse:mouse]];
    mouse.mouseInput.mouseMovedHandler = nil;
    
    mouse.mouseInput.leftButton.pressedChangedHandler = nil;
    mouse.mouseInput.middleButton.pressedChangedHandler = nil;
    mouse.mouseInput.rightButton.pressedChangedHandler = nil;
    
    for (GCControllerButtonInput* auxButton in mouse.mouseInput.auxiliaryButtons) {
        auxButton.pressedChangedHandler = nil;
    }

    if (mouse.mouseInput.scroll != nil) {
        mouse.mouseInput.scroll.valueChangedHandler = nil;
        mouse.mouseInput.scroll.yAxis.valueChangedHandler = nil;
    }
}

static CVReturn displayLinkOutputCallback(CVDisplayLinkRef displayLink,
                                          const CVTimeStamp *now,
                                          const CVTimeStamp *vsyncTime,
                                          CVOptionFlags flagsIn,
                                          CVOptionFlags *flagsOut,
                                          void *displayLinkContext)
{
    HIDSupport *me = (__bridge HIDSupport *)displayLinkContext;
    if (me == nil) {
        return kCVReturnError;
    }

    // Finish consuming/enqueueing before a capture transition clears the debt.
    @synchronized (me) {
        CGFloat deltaX = 0, deltaY = 0;
        [me.mouseDeltaAccumulator takeAccumulatedMotionX:&deltaX deltaY:&deltaY];
        if (deltaX != 0 || deltaY != 0) {
            if (me.shouldSendInputEvents) {
                HIDInputLease inputLease = HIDAcquireInputContext(me);
                PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
                if (!inputCtx) {
                    [me resetRelativeMotionResidualForDisplayLinkConsumer];
                    return kCVReturnSuccess;
                }
                NSInteger touchscreenMode = [SettingsClass touchscreenModeFor:me.host.uuid];
                BOOL useAbsolutePointerPath = HIDShouldUseAbsolutePointerPath(me, touchscreenMode);
                if (useAbsolutePointerPath) {
                    // The absolute path reports where the cursor is rather than how far it
                    // went, so a pixel owed here would be a pixel charged twice the next
                    // time the pointer path is relative.
                    [me resetRelativeMotionResidualForDisplayLinkConsumer];
                }
                if (!useAbsolutePointerPath) {
                    BOOL suppressed = HIDShouldSuppressRelativeMouse(me);
                    if (suppressed) {
                        [me resetRelativeMotionResidualForDisplayLinkConsumer];
                        [me recordRelativeInputDiagnosticsFrom:@"gcMouse"
                                                     rawDeltaX:deltaX
                                                     rawDeltaY:deltaY
                                                    sentDeltaX:0
                                                    sentDeltaY:0
                                                    suppressed:YES];
                        return kCVReturnSuccess;
                    }
                    CGFloat normalizedDeltaX = deltaX / HIDGCMouseRelativeSpeedDivisor;
                    CGFloat normalizedDeltaY = deltaY / HIDGCMouseRelativeSpeedDivisor;
                    CGFloat sensitivity = HIDPointerSensitivityForHost(me.host);
                    CGFloat residualX = me.relativeMotionResidualX;
                    CGFloat residualY = me.relativeMotionResidualY;
                    short moveX = HIDDrainRelativeDelta(&residualX, normalizedDeltaX, sensitivity);
                    short moveY = HIDDrainRelativeDelta(&residualY, normalizedDeltaY, sensitivity);
                    me.relativeMotionResidualX = residualX;
                    me.relativeMotionResidualY = residualY;
                    [me recordRelativeInputDiagnosticsFrom:@"gcMouse"
                                                 rawDeltaX:deltaX
                                                 rawDeltaY:deltaY
                                                sentDeltaX:moveX
                                                sentDeltaY:moveY
                                                suppressed:NO];
                    HIDDispatchInput(me, inputLease, ^{
                        LiSendMouseMoveEventCtx(inputCtx, moveX, moveY);
                    });
                    [me noteMotionSource:@"gameController"
                              summaryKey:@"Mouse Runtime Path GameController Active"
                               detailKey:@"Mouse Runtime Detail GameController Active"];
                }
            }
        }

        // Mouse Emulation Movement
        if (me.controller.isMouseMode && me.shouldSendInputEvents) {
            HIDInputLease inputLease = HIDAcquireInputContext(me);
            PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
            if (!inputCtx) {
                return kCVReturnSuccess;
            }
            short rx = me.controller.lastRightStickX;
            short ry = me.controller.lastRightStickY;
            CGFloat emulationDeltaX = HIDControllerMouseDeltaForAxis(rx);
            CGFloat emulationDeltaY = HIDControllerMouseDeltaForAxis(ry);

            // updateButtonFlags already converts the stick's raw Z and Rz into "up is
            // positive", and a relative pointer move counts +Y as down, so the sign is
            // flipped here and nowhere else: neither the deadzone nor the scaling above
            // knows which way the host counts.
            CGFloat emulationResidualX = me.mouseEmulationResidualX;
            CGFloat emulationResidualY = me.mouseEmulationResidualY;
            short moveX = HIDDrainRelativeDelta(&emulationResidualX,
                                                emulationDeltaX,
                                                HIDMouseEmulationSpeed);
            short moveY = HIDDrainRelativeDelta(&emulationResidualY,
                                                -emulationDeltaY,
                                                HIDMouseEmulationSpeed);
            me.mouseEmulationResidualX = emulationResidualX;
            me.mouseEmulationResidualY = emulationResidualY;

            if (emulationDeltaX != 0.0 || emulationDeltaY != 0.0) {
                [me recordRelativeInputDiagnosticsFrom:@"controllerMouse"
                                             rawDeltaX:emulationDeltaX
                                             rawDeltaY:-emulationDeltaY
                                            sentDeltaX:moveX
                                            sentDeltaY:moveY
                                            suppressed:NO];
                if (moveX != 0 || moveY != 0) {
                    HIDDispatchInput(me, inputLease, ^{
                        LiSendMouseMoveEventCtx(inputCtx, moveX, moveY);
                    });
                }
            }
        }

        return kCVReturnSuccess;
    }
}

- (BOOL)initializeDisplayLink
{
    NSNumber *screenNumber = [[NSScreen mainScreen] deviceDescription][@"NSScreenNumber"];

    CGDirectDisplayID displayId = [screenNumber unsignedIntValue];
    CVDisplayLinkRef displayLink;
    CVReturn status = CVDisplayLinkCreateWithCGDisplay(displayId, &displayLink);
    if (status != kCVReturnSuccess) {
        Log(LOG_E, @"Failed to create CVDisplayLink: %d", status);
        return NO;
    }
    self.displayLink = displayLink;
    
    __weak typeof(self) weakSelf = self;
    status = CVDisplayLinkSetOutputCallback(self.displayLink, displayLinkOutputCallback, (__bridge void * _Nullable)(weakSelf));
    if (status != kCVReturnSuccess) {
        Log(LOG_E, @"CVDisplayLinkSetOutputCallback() failed: %d", status);
        return NO;
    }
    
    status = CVDisplayLinkStart(self.displayLink);
    if (status != kCVReturnSuccess) {
        Log(LOG_E, @"CVDisplayLinkStart() failed: %d", status);
        return NO;
    }
    
    return YES;
}


// A source owns its physical button until the matching release. The value is
// the host button selected at press time, so a settings change cannot release
// another button. All state and enqueue operations share this lock; packets
// share inputQueue with keyboard and motion events.
- (HIDInputLease)currentMouseButtonLease {
    HIDInputLease lease = HIDAcquireInputContext(self);
    if (self.mouseButtonOwnersGeneration != lease.generation) {
        [self.mouseButtonOwners removeAllObjects];
        self.pressedMouseButtonsMask = 0;
        self.mouseButtonOwnersGeneration = lease.generation;
    }
    return lease;
}

- (uint32_t)mouseButtonMaskForCurrentSources {
    uint32_t mask = 0;
    for (NSDictionary<NSNumber *, NSNumber *> *buttons in self.mouseButtonOwners.allValues) {
        for (NSNumber *hostButton in buttons.allValues) {
            mask |= HIDMouseButtonBitForButton(hostButton.intValue);
        }
    }
    return mask;
}

- (BOOL)hasPressedMouseButtons {
    @synchronized (self) {
        [self currentMouseButtonLease];
        return self.pressedMouseButtonsMask != 0;
    }
}

- (void)enqueueMouseButtonReleasesForMask:(uint32_t)mask lease:(HIDInputLease)inputLease {
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (mask == 0 || !HIDValidateInputContext(inputCtx, "releaseMouseButtons")) {
        return;
    }
    uint32_t remainingMask = self.pressedMouseButtonsMask;
    HIDDispatchInput(self, inputLease, ^{
        static const int buttons[] = { BUTTON_LEFT, BUTTON_MIDDLE, BUTTON_RIGHT, BUTTON_X1, BUTTON_X2 };
        for (NSUInteger index = 0; index < sizeof(buttons) / sizeof(buttons[0]); index++) {
            int button = buttons[index];
            if ((mask & HIDMouseButtonBitForButton(button)) != 0) {
                LiSendMouseButtonEventCtx(inputCtx, BUTTON_ACTION_RELEASE, button);
                [self recordMouseButtonDiagnosticsAction:@"release"
                                                  button:button
                                                    mask:remainingMask
                                               synthetic:YES];
            }
        }
    });
}

- (void)releaseAllPressedMouseButtons {
    @synchronized (self) {
        HIDInputLease inputLease = [self currentMouseButtonLease];
        uint32_t mask = self.pressedMouseButtonsMask;
        [self.mouseButtonOwners removeAllObjects];
        self.pressedMouseButtonsMask = 0;
        [self enqueueMouseButtonReleasesForMask:mask lease:inputLease];
    }
}

- (void)releaseMouseButtonsForSource:(NSString *)source {
    if (source.length == 0) {
        return;
    }
    @synchronized (self) {
        HIDInputLease inputLease = [self currentMouseButtonLease];
        uint32_t previousMask = self.pressedMouseButtonsMask;
        [self.mouseButtonOwners removeObjectForKey:source];
        self.pressedMouseButtonsMask = [self mouseButtonMaskForCurrentSources];
        [self enqueueMouseButtonReleasesForMask:previousMask & ~self.pressedMouseButtonsMask lease:inputLease];
    }
}

- (void)sendMouseButton:(int)button
                pressed:(BOOL)pressed
                 source:(NSString *)source
       beforeTransition:(void (^)(PML_INPUT_STREAM_CONTEXT))beforeTransition {
    if (source.length == 0 || HIDMouseButtonBitForButton(button) == 0) {
        return;
    }
    @synchronized (self) {
        HIDInputLease inputLease = [self currentMouseButtonLease];
        NSMutableDictionary<NSNumber *, NSNumber *> *owned = self.mouseButtonOwners[source];
        NSNumber *savedButton = owned[@(button)];
        // A held hardware report is not another press. An unpaired release
        // must never lift a button another device still owns.
        if ((pressed && savedButton != nil) || (!pressed && savedButton == nil)) {
            return;
        }
        if (pressed && !self.shouldSendInputEvents) {
            return;
        }
        PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
        if (!HIDValidateInputContext(inputCtx, "sendMouseButton")) {
            if (!pressed) {
                [owned removeObjectForKey:@(button)];
                if (owned.count == 0) [self.mouseButtonOwners removeObjectForKey:source];
                self.pressedMouseButtonsMask = [self mouseButtonMaskForCurrentSources];
            }
            return;
        }
        uint32_t previousMask = self.pressedMouseButtonsMask;
        int hostButton = savedButton != nil ? savedButton.intValue : button;
        if (pressed) {
            if ([SettingsClass swapMouseButtonsFor:self.host.uuid]) {
                if (hostButton == BUTTON_LEFT) hostButton = BUTTON_RIGHT;
                else if (hostButton == BUTTON_RIGHT) hostButton = BUTTON_LEFT;
            }
            if (self.mouseButtonOwners == nil) {
                self.mouseButtonOwners = [NSMutableDictionary dictionary];
            }
            if (owned == nil) {
                owned = [NSMutableDictionary dictionary];
                self.mouseButtonOwners[source] = owned;
            }
            owned[@(button)] = @(hostButton);
        } else {
            [owned removeObjectForKey:@(button)];
            if (owned.count == 0) [self.mouseButtonOwners removeObjectForKey:source];
        }
        uint32_t mask = [self mouseButtonMaskForCurrentSources];
        self.pressedMouseButtonsMask = mask;
        if ((previousMask & HIDMouseButtonBitForButton(hostButton)) ==
            (mask & HIDMouseButtonBitForButton(hostButton))) {
            return;
        }
        [self recordMouseButtonDiagnosticsAction:pressed ? @"press" : @"release"
                                          button:hostButton
                                            mask:mask
                                       synthetic:NO];
        HIDDispatchInput(self, inputLease, ^{
            if (beforeTransition != nil) beforeTransition(inputCtx);
            LiSendMouseButtonEventCtx(inputCtx,
                                      pressed ? BUTTON_ACTION_PRESS : BUTTON_ACTION_RELEASE,
                                      hostButton);
        });
    }
}

- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source {
    [self sendMouseButton:button pressed:pressed source:source beforeTransition:nil];
}

- (void)sendRelativeMouseMoveDeltaX:(short)deltaX deltaY:(short)deltaY {
    if (!self.shouldSendInputEvents || (deltaX == 0 && deltaY == 0)) {
        return;
    }
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    HIDDispatchInput(self, inputLease, ^{
        LiSendMouseMoveEventCtx(inputLease.context, deltaX, deltaY);
    });
}

- (void)mouseDown:(NSEvent *)event withButton:(int)button {
    if (button == BUTTON_LEFT) {
        [self logMouseEventDiagnosticsForEvent:event where:@"wire-down"];
    }
    if (!self.useGCMouse) {
        [self sendMouseButton:button pressed:YES source:@"appkit"];
    }
}

- (void)mouseUp:(NSEvent *)event withButton:(int)button {
    if (button == BUTTON_LEFT) {
        [self logMouseEventDiagnosticsForEvent:event where:@"wire-up"];
    }
    // Retire an AppKit press even if the selected driver changed while held.
    [self sendMouseButton:button pressed:NO source:@"appkit"];
}

- (void)mouseMoved:(NSEvent *)event {
    if (!self.shouldSendInputEvents) {
        return;
    }

    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "mouseMoved")) {
        return;
    }

    NSInteger touchscreenMode = [SettingsClass touchscreenModeFor:self.host.uuid];
    BOOL useAbsolutePointerPath = HIDShouldUseAbsolutePointerPath(self, touchscreenMode);

    if (self.useGCMouse && !useAbsolutePointerPath) {
        return;
    }

    if (useAbsolutePointerPath) {
        short hostX = 0;
        short hostY = 0;
        short referenceWidth = 0;
        short referenceHeight = 0;
        if (!HIDAbsoluteMousePayloadForEvent(event,
                                             YES,
                                             &hostX,
                                             &hostY,
                                             &referenceWidth,
                                             &referenceHeight)) {
            return;
        }
        [self recordAbsoluteInputDiagnosticsFrom:@"mouseMoved"
                                               x:hostX
                                               y:hostY
                                           width:referenceWidth
                                          height:referenceHeight];
        [self noteMotionSource:@"absolute"
                    summaryKey:@"Mouse Runtime Path Absolute Active"
                     detailKey:@"Mouse Runtime Detail Absolute Active"];
        HIDDispatchInput(self, inputLease, ^{
            LiSendMousePositionEventCtx(inputCtx, hostX, hostY, referenceWidth, referenceHeight);
        });
    } else {
        if (self.useCoreHIDMouse &&
            self.coreHIDMouseDriver != nil &&
            self.coreHIDMouseDriver.secondsSinceLastMovementEvent < 0.25) {
            return;
        }
        // No status line here: whether this delta reaches the host is decided inside the
        // dispatcher, which credits itself once it does.
        [self dispatchRelativeMouseDeltaX:event.deltaX
                                   deltaY:event.deltaY
                                sourceTag:@"mouseMoved"];
    }
}

- (void)sendAbsoluteMousePositionForViewPoint:(NSPoint)viewPoint
                                referenceSize:(NSSize)referenceSize
                                clampToBounds:(BOOL)clampToBounds {
    HIDInputLease inputLease = HIDAcquireInputContext(self);
    PML_INPUT_STREAM_CONTEXT inputCtx = inputLease.context;
    if (!HIDValidateInputContext(inputCtx, "sendAbsoluteMousePosition")) {
        return;
    }

    short hostX = 0;
    short hostY = 0;
    short referenceWidth = 0;
    short referenceHeight = 0;
    if (!HIDAbsoluteMousePositionForViewPoint(viewPoint,
                                              referenceSize,
                                              clampToBounds,
                                              &hostX,
                                              &hostY,
                                              &referenceWidth,
                                              &referenceHeight)) {
        return;
    }

    if (hostX == self.lastAbsolutePointerHostX &&
        hostY == self.lastAbsolutePointerHostY &&
        referenceWidth == self.lastAbsolutePointerReferenceWidth &&
        referenceHeight == self.lastAbsolutePointerReferenceHeight) {
        if (self.inputDiagnosticsEnabled) {
            @synchronized (self.inputDiagnosticsLock) {
                self.inputDiagnosticsAbsoluteDuplicateSkips += 1;
            }
        }
        return;
    }

    [self recordAbsoluteInputDiagnosticsFrom:@"sendAbsoluteMousePosition"
                                           x:hostX
                                           y:hostY
                                       width:referenceWidth
                                      height:referenceHeight];
    HIDDispatchInput(self, inputLease, ^{
        LiSendMousePositionEventCtx(inputCtx, hostX, hostY, referenceWidth, referenceHeight);
    });
}

- (void)sendMouseButton:(int)button
                pressed:(BOOL)pressed
      syncedToViewPoint:(NSPoint)viewPoint
          referenceSize:(NSSize)referenceSize
          clampToBounds:(BOOL)clampToBounds {
    if (pressed && self.useGCMouse) {
        return;
    }
    short hostX = 0, hostY = 0, referenceWidth = 0, referenceHeight = 0;
    BOOL hasPosition = HIDAbsoluteMousePositionForViewPoint(viewPoint, referenceSize, clampToBounds,
                                                           &hostX, &hostY, &referenceWidth, &referenceHeight);
    [self sendMouseButton:button pressed:pressed source:@"appkit"
        beforeTransition:^(PML_INPUT_STREAM_CONTEXT inputCtx) {
            // Keep the click's position and edge in one queue item. A newer
            // coalesced movement must not make this click use a later position.
            if (hasPosition) {
                [self recordAbsoluteInputDiagnosticsFrom:@"sendAbsoluteMouseButtonSync"
                                                       x:hostX y:hostY
                                                   width:referenceWidth height:referenceHeight];
                LiSendMousePositionEventCtx(inputCtx, hostX, hostY, referenceWidth, referenceHeight);
            }
        }];
}

- (BOOL)absoluteMousePayloadForViewPoint:(NSPoint)viewPoint
                           referenceSize:(NSSize)referenceSize
                           clampToBounds:(BOOL)clampToBounds
                                   hostX:(short *)hostX
                                   hostY:(short *)hostY
                          referenceWidth:(short *)referenceWidth
                         referenceHeight:(short *)referenceHeight {
    return HIDAbsoluteMousePositionForViewPoint(viewPoint,
                                                referenceSize,
                                                clampToBounds,
                                                hostX,
                                                hostY,
                                                referenceWidth,
                                                referenceHeight);
}


@end
