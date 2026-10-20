#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#include <assert.h>
#include "InterpolationCadencePolicy.h"
#define Log(...) ((void)0)
#define VIDEO_FORMAT_MASK_10BIT 1
#define CAMetalLayer MLQueueTestLayer

@@RENDERER_ENUM@@
@@CONSTANTS@@
@@CLAMP@@
static uint64_t LiGetMillis(void) { return 1000; }

@interface MLQueueTestLayer : NSObject
@property NSUInteger maximumDrawableCount;
@end
@implementation MLQueueTestLayer
@end
@interface MLQueueTestView : NSObject
@property(nonatomic, strong) MLQueueTestLayer *layer;
@end
@implementation MLQueueTestView
@end

@interface MLQueueProbe : NSObject {
@public
    NSInteger _frameQueueTargetOverride, _timingBufferLevel, _framePacingMode;
    NSInteger _smoothnessLatencyMode, _timingResponsivenessBias;
    BOOL _timingEnableVsync, _timingCompatibilityMode, _timingPrioritizeResponsiveness;
    BOOL _timingSdrCompatibilityWorkaround, _enableHdr, _didLogEnhancedStartupPacing;
    int videoFormat;
    MLActiveVideoRendererMode _activeRendererMode;
    uint64_t _enhancedStartupPacingUntilMs;
    NSUInteger _enhancedStartupPresentedFrameCount, _metalInflightLimit;
    double _lastDisplayRefreshRate;
    dispatch_semaphore_t _metalInflightSemaphore;
    MLQueueTestView *_metalView;
}
@property int frameRate;
@property BOOL shortQueueOnDoubledCadence;
@end
@implementation MLQueueProbe
@@METHODS@@
@end

static NSUInteger permits(dispatch_semaphore_t semaphore) {
    NSUInteger count = 0;
    while (dispatch_semaphore_wait(semaphore, DISPATCH_TIME_NOW) == 0) {
        assert(++count <= 4);
    }
    for (NSUInteger i = 0; i < count; ++i) dispatch_semaphore_signal(semaphore);
    return count;
}

int main(void) {
    @autoreleasepool {
        MLQueueProbe *p = [MLQueueProbe new];
        p.frameRate = 90;
        p->_frameQueueTargetOverride = -1;
        p->_framePacingMode = 1;
        p->_timingEnableVsync = YES;
        p->_timingBufferLevel = 2;
        p->_smoothnessLatencyMode = 3;
        p->_activeRendererMode = MLActiveVideoRendererModeEnhanced;
        p->_metalView = [MLQueueTestView new];
        p->_metalView.layer = [MLQueueTestLayer new];
        p->_metalView.layer.maximumDrawableCount = 3;
        p->_metalInflightLimit = 3;
        p->_metalInflightSemaphore = dispatch_semaphore_create(3);
        dispatch_semaphore_t initial = p->_metalInflightSemaphore;
        assert([p desiredPendingFramesForDisplayRefreshRate:0] == 2);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightSemaphore == initial);

        // The first measured refresh must NOT change the queue depth by itself:
        // a refresh-rate value alone is not a player-visible setting, and any
        // queue-depth change triggered here was the "doubled cadence step-down"
        // that the previous build slipped in without user consent. The buffered
        // default (drawable=3, inflight=3 with timingBufferLevel=2) must hold.
        p->_lastDisplayRefreshRate = 179.99;
        assert([p desiredPendingFramesForDisplayRefreshRate:179.99] == 2);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalView.layer.maximumDrawableCount == 3);
        assert(p->_metalInflightLimit == 3 && permits(p->_metalInflightSemaphore) == 3);
        assert(p->_metalInflightSemaphore == initial);

        // An outstanding GPU command prevents replacement; partial reservations
        // are returned without changing the permit count.
        dispatch_semaphore_t held = p->_metalInflightSemaphore;
        assert(dispatch_semaphore_wait(held, DISPATCH_TIME_NOW) == 0);
        p->_lastDisplayRefreshRate = 60;
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightSemaphore == held && permits(held) == 2);
        assert(p->_metalView.layer.maximumDrawableCount == 3);
        dispatch_semaphore_signal(held);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightLimit == 3 && permits(p->_metalInflightSemaphore) == 3);
        assert(permits(held) == 3);
        assert([p desiredPendingFramesForDisplayRefreshRate:60] == 2);
        p.frameRate = 60;
        assert([p desiredPendingFramesForDisplayRefreshRate:60] == 2);

        // Disabling VSync IS a player-visible setting, and the resource-replacement
        // path must still observe it: the buffered branch falls back to the
        // minimal-inflight path (return 1), so the semaphore has to be swapped.
        p.frameRate = 90;
        p->_lastDisplayRefreshRate = 180;
        p->_timingBufferLevel = 0;  // drops out of the buffered branch too
        p->_smoothnessLatencyMode = 0;
        dispatch_semaphore_t before = p->_metalInflightSemaphore;
        assert(dispatch_semaphore_wait(before, DISPATCH_TIME_NOW) == 0);
        p->_timingEnableVsync = NO;
        [p updateEnhancedQueueDepthIfNeeded];
        // inflight limit drops from 3 to 1 (minimal path), but the drawable number
        // stays at 3, so the semaphore cannot be replaced while a permit is held.
        // The held permit means updateEnhancedQueueDepthIfNeeded sees only 2 free
        // permits (3 - 1 held) and refuses to drain.
        assert(p->_metalInflightSemaphore == before && permits(before) == 2);
        dispatch_semaphore_signal(before);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightSemaphore != before);
        assert(p->_metalInflightLimit == 1 && permits(p->_metalInflightSemaphore) == 1);
        assert(permits(before) == 3);
        // Restore the buffered-branch state so the assertions below match the
        // baseline (timingBufferLevel=2, vsync=YES, smoothnessLatencyMode=3).
        p->_timingEnableVsync = YES;
        p->_timingBufferLevel = 2;
        p->_smoothnessLatencyMode = 3;
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightLimit == 3 && permits(p->_metalInflightSemaphore) == 3);

        // VSync never loses its floor, compatibility keeps the full queue,
        // and an explicit queue override wins even during startup.
        p.frameRate = 90;
        p->_lastDisplayRefreshRate = 180;
        p->_timingBufferLevel = 1;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 1);
        p->_timingCompatibilityMode = YES;
        assert([p desiredEnhancedDrawableDepth] == 3);
        assert([p desiredEnhancedInflightLimit] == 3);
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 1);
        p->_timingBufferLevel = 2;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 2);
        p->_timingEnableVsync = p->_timingCompatibilityMode = NO;
        p->_enhancedStartupPacingUntilMs = 1100;
        for (int override = 0; override <= 5; ++override) {
            p->_frameQueueTargetOverride = override;
            assert([p desiredPendingFramesForDisplayRefreshRate:180] == MIN(override, 3));
        }
        p->_frameQueueTargetOverride = -1;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 0);
        p->_activeRendererMode = MLActiveVideoRendererModeNative;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 2);

        // Compatibility-mode drawable depth must be 3 even when vsync is off
        // and the buffered branch falls back to 2. The mutation
        // compatibility-loses-depth removes the early-return and lets the
        // function fall through to drawable=2, which the assertion below
        // catches.
        p->_activeRendererMode = MLActiveVideoRendererModeEnhanced;
        p.frameRate = 90;
        p->_lastDisplayRefreshRate = 180;
        p->_timingBufferLevel = 0;
        p->_smoothnessLatencyMode = 0;
        p->_timingEnableVsync = NO;
        p->_timingCompatibilityMode = YES;
        assert([p desiredEnhancedDrawableDepth] == 3);
        p->_timingCompatibilityMode = NO;

        // The "short queue on doubled cadence" preference is a player opt-in
        // (SettingsModel default OFF). When the owner turns it on, the
        // halved-cadence target step is applied with the vsync floor: target
        // starts at 1 (buffer=1, vsync=YES, no startup), drops by 1, then the
        // floor returns it to 1. The mutation vsync-floor-lost removes the
        // floor and produces 0, which the assertion below catches.
        p->_activeRendererMode = MLActiveVideoRendererModeEnhanced;
        p.frameRate = 90;
        p->_lastDisplayRefreshRate = 180;
        p->_timingBufferLevel = 0;
        p->_smoothnessLatencyMode = 0;
        p->_timingEnableVsync = YES;
        p->_timingCompatibilityMode = NO;
        p->_enhancedStartupPacingUntilMs = 0;
        p.shortQueueOnDoubledCadence = YES;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 1);
        p->_timingEnableVsync = NO;
        assert([p desiredPendingFramesForDisplayRefreshRate:180] == 0);
        p.shortQueueOnDoubledCadence = NO;



        // Stop retires resources. A late old completion returns only its old
        // permit and cannot create or enlarge a subsequent session.
        dispatch_semaphore_t retired = p->_metalInflightSemaphore;
        assert(dispatch_semaphore_wait(retired, DISPATCH_TIME_NOW) == 0);
        p->_metalInflightSemaphore = nil;
        p->_metalInflightLimit = 0;
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightSemaphore == nil && p->_metalInflightLimit == 0);
        p->_metalInflightSemaphore = dispatch_semaphore_create(2);
        p->_metalInflightLimit = 2;
        dispatch_semaphore_signal(retired);
        assert(permits(p->_metalInflightSemaphore) == 2 && permits(retired) == 3);
        puts("ok: queue startup, refresh changes, GPU drain, floors, override and retired permits");
    }
}
