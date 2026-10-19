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

        // The first measured refresh updates both resources before drawing.
        p->_lastDisplayRefreshRate = 179.99;
        assert([p desiredPendingFramesForDisplayRefreshRate:179.99] == 1);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalView.layer.maximumDrawableCount == 2);
        assert(p->_metalInflightLimit == 2 && permits(p->_metalInflightSemaphore) == 2);
        assert(p->_metalInflightSemaphore != initial && permits(initial) == 3);

        // An outstanding GPU command prevents replacement; partial reservations
        // are returned without changing the permit count.
        dispatch_semaphore_t doubled = p->_metalInflightSemaphore;
        assert(dispatch_semaphore_wait(doubled, DISPATCH_TIME_NOW) == 0);
        p->_lastDisplayRefreshRate = 60;
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightSemaphore == doubled && permits(doubled) == 1);
        assert(p->_metalView.layer.maximumDrawableCount == 2);
        dispatch_semaphore_signal(doubled);
        [p updateEnhancedQueueDepthIfNeeded];
        assert(p->_metalInflightLimit == 3 && permits(p->_metalInflightSemaphore) == 3);
        assert(permits(doubled) == 2);
        assert([p desiredPendingFramesForDisplayRefreshRate:60] == 2);
        p.frameRate = 60;
        assert([p desiredPendingFramesForDisplayRefreshRate:60] == 2);

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
