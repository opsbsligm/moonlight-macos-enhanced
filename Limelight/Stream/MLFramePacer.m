//
//  MLFramePacer.m
//  Moonlight
//
//  Ported from moonlight-qt Pacer (pacer.h/pacer.cpp).
//  Dual-queue frame pacing algorithm with adaptive frame dropping.
//  Licensed under GPL-3.0.
//

// Standalone microsecond clock for environments (e.g. CI static analyzer) where
// moonlight-common-c's LiGetMicroseconds() is not available during pure-SDK
// type-checking. Uses mach_absolute_time for high-resolution monotonic time.
#import <mach/mach_time.h>
static uint64_t ml_pacer_get_microseconds(void) {
    static mach_timebase_info_data_t timebase = {0};
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        mach_timebase_info(&timebase);
    });
    uint64_t raw = mach_absolute_time();
    uint64_t nanos = raw * timebase.numer / timebase.denom;
    return nanos / 1000;
}



#import "MLFramePacer.h"

// Queue depth history window: 500ms of entries.


@interface MLFramePacer ()
{
    // Queues
    NSMutableArray<MLPacedFrame *> *_pacingQueue;
    NSMutableArray<MLPacedFrame *> *_renderQueue;
    
    // Queue depth history for adaptive drop decisions
    NSMutableArray<NSNumber *> *_pacingQueueHistory;
    NSMutableArray<NSNumber *> *_renderQueueHistory;
    NSUInteger _historyWindowCount;
    
    // Sync
    NSLock *_lock;
    NSCondition *_renderQueueNotEmpty;
    NSCondition *_pacingQueueNotEmpty;
    
    // Config
    int _maxVideoFps;
    int _displayFps;
    BOOL _enablePacing;
    BOOL _stopping;
    
    // Stats
    uint32_t _pacerDroppedFrames;
    
    // Deferred free (GPU safety: keep one frame alive until next render)
    MLPacedFrame *_deferredFreeFrame;
    
    __weak id<MLFramePacerDelegate> _delegate;
    VideoStats *_videoStats; // weak reference to renderer's stats
}
@end

@implementation MLFramePacer

@synthesize pacingQueueDepth = _pacingQueueDepth;
@synthesize renderQueueDepth = _renderQueueDepth;
@synthesize pacerDroppedFrames = _pacerDroppedFrames;

- (instancetype)initWithDelegate:(id<MLFramePacerDelegate>)delegate
                      videoStats:(VideoStats *)videoStats
{
    self = [super init];
    if (self) {
        _delegate = delegate;
        _videoStats = videoStats;
        _pacingQueue = [[NSMutableArray alloc] initWithCapacity:MLPacerMaxQueuedFrames + 1];
        _renderQueue = [[NSMutableArray alloc] initWithCapacity:MLPacerMaxQueuedFrames + 1];
        _pacingQueueHistory = [[NSMutableArray alloc] init];
        _renderQueueHistory = [[NSMutableArray alloc] init];
        _lock = [[NSLock alloc] init];
        _renderQueueNotEmpty = [[NSCondition alloc] init];
        _pacingQueueNotEmpty = [[NSCondition alloc] init];
        _stopping = NO;
        _pacerDroppedFrames = 0;
        _maxVideoFps = 0;
        _displayFps = 0;
        _enablePacing = NO;
        _historyWindowCount = 0;
    }
    return self;
}

- (BOOL)initializeWithMaxVideoFps:(int)maxVideoFps
                       displayFps:(int)displayFps
                     enablePacing:(BOOL)enablePacing
{
    _maxVideoFps = maxVideoFps;
    _displayFps = displayFps;
    _enablePacing = enablePacing;
    
    // History window = 500ms
    _historyWindowCount = (NSUInteger)MAX(displayFps / 2, 1);
    
    if (enablePacing) {
        NSLog(@"[pacer] Frame pacing: target %d Hz with %d FPS stream", displayFps, maxVideoFps);
    } else {
        NSLog(@"[pacer] Frame pacing disabled: target %d Hz with %d FPS stream", displayFps, maxVideoFps);
    }
    
    return YES;
}

- (void)submitPixelBuffer:(CVPixelBufferRef)pixelBuffer
             enqueueTimeUs:(uint64_t)enqueueTimeUs
             receiveTimeMs:(uint64_t)receiveTimeMs
        presentationTimeMs:(unsigned int)presentationTimeMs
              frameNumber:(uint32_t)frameNumber
            isInterpolated:(BOOL)isInterpolated
{
    if (_stopping) return;
    
    MLPacedFrame *frame = [[MLPacedFrame alloc] init];
    frame.pixelBuffer = CVPixelBufferRetain(pixelBuffer);
    frame.enqueueTimeUs = enqueueTimeUs;
    frame.receiveTimeMs = receiveTimeMs;
    frame.presentationTimeMs = presentationTimeMs;
    frame.frameNumber = frameNumber;
    frame.isInterpolated = isInterpolated;
    
    [_lock lock];
    
    if (_enablePacing) {
        // Drop oldest frame if pacing queue is full
        [self dropFrameForEnqueue:_pacingQueue];
        [_pacingQueue addObject:frame];
        [_lock unlock];
        [_pacingQueueNotEmpty signal];
    } else {
        // Bypass pacing: place directly on render queue
        [self dropFrameForEnqueue:_renderQueue];
        [_renderQueue addObject:frame];
        [_lock unlock];
        [_renderQueueNotEmpty signal];
    }
}

- (void)signalVsync
{
    if (_stopping || !_enablePacing) return;
    
    [_lock lock];
    
    if (_maxVideoFps == 0) {
        [_lock unlock];
        return;
    }
    
    // Adaptive frame dropping based on pacing queue history
    int frameDropTarget = 1;
    
    if (_maxVideoFps >= _displayFps && _displayFps > 0) {
        // Keep pacing queue at 1 frame when stream fps >= display refresh.
        // The old frameDropTarget=3 accumulated ~33ms delay (3 frames at 90fps)
        // and was the root cause of the 29ms queue bottleneck.
        frameDropTarget = 1;
    }
    
    // Drop excess frames from pacing queue
    while (_pacingQueue.count > frameDropTarget) {
        MLPacedFrame *dropped = _pacingQueue.firstObject;
        [_pacingQueue removeObjectAtIndex:0];
        [_lock unlock];
        _pacerDroppedFrames++;
        if (_videoStats) _videoStats->pacerDroppedFrames++;
        if (dropped.pixelBuffer) CVPixelBufferRelease(dropped.pixelBuffer);
        [_lock lock];
    }
    
    if (_pacingQueue.count == 0) {
        // Wait briefly for a frame, or bail
        [_lock unlock];
        return;
    }
    
    // Promote the first pacing frame to render queue
    MLPacedFrame *frame = _pacingQueue.firstObject;
    [_pacingQueue removeObjectAtIndex:0];
    [self enqueueFrameForRendering:frame];
    // lock is unlocked by enqueueFrameForRendering
}

- (void)enqueueFrameForRendering:(MLPacedFrame *)frame
{
    [self dropFrameForEnqueue:_renderQueue];
    [_renderQueue addObject:frame];
    [_lock unlock];
    [_renderQueueNotEmpty signal];
}

- (void)renderOnMainThread
{
    if (_stopping) return;
    
    MLPacedFrame *frame = nil;
    
    [_lock lock];
    if (_renderQueue.count > 0) {
        frame = _renderQueue.firstObject;
        [_renderQueue removeObjectAtIndex:0];
    }
    [_lock unlock];
    
    if (frame) {
        [self renderPacedFrame:frame];
    }
}

- (void)renderPacedFrame:(MLPacedFrame *)frame
{
    uint64_t beforeRender = ml_pacer_get_microseconds();
    
    // Track pacer queue time
    if (frame.enqueueTimeUs != 0 && beforeRender >= frame.enqueueTimeUs) {
        if (_videoStats) _videoStats->totalPacerTime += beforeRender - frame.enqueueTimeUs;
    }
    
    // Render via delegate
    [_delegate pacerRenderFrame:frame.pixelBuffer
                   enqueueTimeUs:frame.enqueueTimeUs
                     interpolated:frame.isInterpolated];
    
    uint64_t afterRender = ml_pacer_get_microseconds();
    if (_videoStats) {
        _videoStats->totalRenderTime += afterRender - beforeRender;
        _videoStats->renderedFrames++;
    }
    
    // Deferred free: keep one frame alive for GPU to finish reading
    if (_deferredFreeFrame) {
        if (_deferredFreeFrame.pixelBuffer) CVPixelBufferRelease(_deferredFreeFrame.pixelBuffer);
    }
    _deferredFreeFrame = frame; // transfer ownership, old one is released
    
    // Adaptive render queue drop
    [_lock lock];
    int frameDropTarget;
    // Keep render queue minimal: 0 frames normally, 1 for high-fps streams
    // to avoid pipeline stalls without adding noticeable latency.
    frameDropTarget = 0;
    if (_maxVideoFps > 60 && _displayFps > 0) {
        frameDropTarget = 1;
    }
    if (_renderQueueHistory.count == _historyWindowCount) {
        [_renderQueueHistory removeObjectAtIndex:0];
    }
    [_renderQueueHistory addObject:@(_renderQueue.count)];
    
    while (_renderQueue.count > frameDropTarget) {
        MLPacedFrame *dropped = _renderQueue.firstObject;
        [_renderQueue removeObjectAtIndex:0];
        [_lock unlock];
        _pacerDroppedFrames++;
        if (_videoStats) _videoStats->pacerDroppedFrames++;
        if (dropped.pixelBuffer) CVPixelBufferRelease(dropped.pixelBuffer);
        [_lock lock];
    }
    [_lock unlock];
}

- (void)dropFrameForEnqueue:(NSMutableArray<MLPacedFrame *> *)queue
{
    if (queue.count >= MLPacerMaxQueuedFrames) {
        MLPacedFrame *dropped = queue.firstObject;
        [queue removeObjectAtIndex:0];
        _pacerDroppedFrames++;
        if (_videoStats) _videoStats->pacerDroppedFrames++;
        if (dropped.pixelBuffer) CVPixelBufferRelease(dropped.pixelBuffer);
    }
}

- (void)stop
{
    _stopping = YES;
    [_lock lock];
    
    // Clear pacing queue
    for (MLPacedFrame *frame in _pacingQueue) {
        if (frame.pixelBuffer) CVPixelBufferRelease(frame.pixelBuffer);
    }
    [_pacingQueue removeAllObjects];
    
    // Clear render queue
    for (MLPacedFrame *frame in _renderQueue) {
        if (frame.pixelBuffer) CVPixelBufferRelease(frame.pixelBuffer);
    }
    [_renderQueue removeAllObjects];
    
    // Release deferred free
    if (_deferredFreeFrame) {
        if (_deferredFreeFrame.pixelBuffer) CVPixelBufferRelease(_deferredFreeFrame.pixelBuffer);
        _deferredFreeFrame = nil;
    }
    
    [_lock unlock];
    
    [_renderQueueNotEmpty broadcast];
    [_pacingQueueNotEmpty broadcast];
}

- (NSInteger)pacingQueueDepth
{
    [_lock lock];
    NSInteger depth = _pacingQueue.count;
    [_lock unlock];
    return depth;
}

- (NSInteger)renderQueueDepth
{
    [_lock lock];
    NSInteger depth = _renderQueue.count;
    [_lock unlock];
    return depth;
}

- (uint32_t)pacerDroppedFrames
{
    return _pacerDroppedFrames;
}

- (void)dealloc
{
    [self stop];
}

@end

@implementation MLPacedFrame

- (void)dealloc
{
    if (_pixelBuffer) {
        CVPixelBufferRelease(_pixelBuffer);
        _pixelBuffer = NULL;
    }
}

@end
