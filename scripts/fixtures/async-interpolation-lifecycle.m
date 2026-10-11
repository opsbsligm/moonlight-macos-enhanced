// Shipping FI methods + deterministic VT double; native CV and dispatch stay real.
// This is ownership/deadline evidence, not hardware interpolation quality evidence.
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#include <assert.h>
#include <math.h>
#include <stdatomic.h>
#include "EnhancementProcessingPolicy.h"
#include "EnhancedPresentationPolicy.h"
#define LOG_W 1
#define Log(level, ...) do {} while (0)
static _Atomic uint64_t testClock = 100;
static uint64_t LiGetMillis(void) { return atomic_load(&testClock); }
@@ENUMS@@
static NSString *MLVideoFrameInterpolationEngineName(MLActiveVideoFrameInterpolationEngine e) { return @"test"; }
@interface VTFrameProcessorFrame : NSObject
@property(nonatomic) CVImageBufferRef buffer;
@property(nonatomic) CMTime timestamp;
- (instancetype)initWithBuffer:(CVImageBufferRef)b presentationTimeStamp:(CMTime)t;
@end
@implementation VTFrameProcessorFrame
- (instancetype)initWithBuffer:(CVImageBufferRef)b presentationTimeStamp:(CMTime)t {
    if ((self=[super init])) { _buffer=b;_timestamp=t; } return self;
}
@end
@interface VTLowLatencyFrameInterpolationParameters : NSObject
@property VTFrameProcessorFrame *source, *previous, *destination;
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s previousFrame:(VTFrameProcessorFrame *)p
               interpolationPhase:(NSArray *)phase destinationFrames:(NSArray *)d;
@end
@implementation VTLowLatencyFrameInterpolationParameters
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s previousFrame:(VTFrameProcessorFrame *)p
               interpolationPhase:(NSArray *)phase destinationFrames:(NSArray *)d {
    if ((self=[super init])) { _source=s;_previous=p;_destination=d.firstObject; } return self;
}
@end
@interface VTFrameProcessor : NSObject
@property BOOL blockProcessing, fail, ended, endedDuringProcess, ranOnCaller, processing;
@property NSUInteger calls;
@property double midpoint, previousTime, inputTime;
@property dispatch_semaphore_t entered, releaseWork;
- (BOOL)processWithParameters:(VTLowLatencyFrameInterpolationParameters *)p error:(NSError **)error;
- (void)endSession;
@end
@implementation VTFrameProcessor
- (instancetype)init { if ((self=[super init])) { _entered=dispatch_semaphore_create(0);_releaseWork=dispatch_semaphore_create(0); } return self; }
- (BOOL)processWithParameters:(VTLowLatencyFrameInterpolationParameters *)p error:(NSError **)error {
    self.processing=YES;self.calls+=1;self.ranOnCaller=NSThread.isMainThread;
    self.midpoint=CMTimeGetSeconds(p.destination.timestamp);
    self.previousTime=CMTimeGetSeconds(p.previous.timestamp);self.inputTime=CMTimeGetSeconds(p.source.timestamp);
    assert(CVPixelBufferGetWidth(p.source.buffer)==8 && CVPixelBufferGetWidth(p.previous.buffer)==8);
    dispatch_semaphore_signal(self.entered);
    if (self.blockProcessing) assert(dispatch_semaphore_wait(self.releaseWork,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
    self.processing=NO;return !self.fail;
}
- (void)endSession { self.endedDuringProcess=self.processing;self.ended=YES; }
@end
@interface Probe : NSObject {
@public
    dispatch_queue_t _vtInterpolationQueue;
    NSUInteger _interpolationProcessGeneration, _frameInterpolationWarmupGeneration;
    BOOL _interpolationProcessInFlight, _frameInterpolationWarmupInFlight, _frameInterpolationCadenceForced;
    NSInteger _frameInterpolationWarmupWidth, _frameInterpolationWarmupHeight;
    NSInteger _frameInterpolationInputWidth, _frameInterpolationInputHeight;
    OSType _frameInterpolationSourcePixelFormat, _frameInterpolationRefusedSourcePixelFormat;
    id _frameInterpolationProcessor, _frameInterpolationConfiguration;
    CVPixelBufferPoolRef _frameInterpolationOutputPool;
    CVImageBufferRef _currentFrame, _previousInterpolationSourceFrame, _pendingInterpolatedFrame;
    CMTime _currentFramePresentationTimeStamp, _previousInterpolationSourcePresentationTimeStamp;
    CMTime _pendingInterpolatedPresentationTimeStamp;
    uint64_t _currentFrameSequence, _lastPresentedFrameSequence, _interpolationStagingSequence;
    uint64_t _interpolationStagingStartedAtMs, _interpolationStagingBudgetMs;
    uint64_t _pendingInterpolatedEnqueueTimeMs, _pendingInterpolatedForSourceSequence, _deferredCurrentSourceSequence;
    uint32_t _pendingInterpolatedFrameNumber;
    BOOL _pendingInterpolatedPresented;
    MLActiveVideoFrameInterpolationEngine _activeFrameInterpolationEngine, _lastLoggedFrameInterpolationEngine;
}
@property int frameRate;
@property dispatch_semaphore_t finished;
@property MLVideoFrameInterpolationReport report;
- (BOOL)shouldUseFrameInterpolationForDisplayRefreshRate:(double)r report:(MLVideoFrameInterpolationReport *)report reason:(NSString **)reason;
- (BOOL)prepareFrameInterpolationProcessorForSourceFrame:(CVImageBufferRef)f report:(MLVideoFrameInterpolationReport *)report;
- (void)logActiveFrameInterpolationEngine:(MLActiveVideoFrameInterpolationEngine)e report:(MLVideoFrameInterpolationReport)r reason:(NSString *)reason;
- (void)requestEnhancedDraw;
- (void)teardownFrameInterpolationProcessor;
@end
@implementation Probe
- (BOOL)shouldUseFrameInterpolationForDisplayRefreshRate:(double)r report:(MLVideoFrameInterpolationReport *)report reason:(NSString **)reason { return YES; }
- (BOOL)prepareFrameInterpolationProcessorForSourceFrame:(CVImageBufferRef)f report:(MLVideoFrameInterpolationReport *)report { return _frameInterpolationProcessor != nil && _frameInterpolationOutputPool != NULL; }
- (void)logActiveFrameInterpolationEngine:(MLActiveVideoFrameInterpolationEngine)e report:(MLVideoFrameInterpolationReport)r reason:(NSString *)reason { self.report=r; }
- (void)publishVideoFrameInterpolationRuntimeStatusSummary:(NSString *)s detail:(NSString *)d {}
- (NSString *)runtimeDetailKeyForFrameInterpolationReport:(MLVideoFrameInterpolationReport)r { return @"test"; }
- (void)publishVideoCadenceRuntimeReadoutStopped {}
- (void)requestEnhancedDraw { dispatch_semaphore_signal(self.finished); }
@@METHODS@@
@end
static void waitFor(dispatch_semaphore_t s) { assert(dispatch_semaphore_wait(s,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0); }
static Probe *freshProbe(BOOL blocked) {
    atomic_store(&testClock,100);
    Probe *r=[Probe new];r.frameRate=90;r.finished=dispatch_semaphore_create(0);
    r->_vtInterpolationQueue=dispatch_queue_create("test.fi",DISPATCH_QUEUE_SERIAL);
    VTFrameProcessor *processor=[VTFrameProcessor new];processor.blockProcessing=blocked;r->_frameInterpolationProcessor=processor;
    NSDictionary *attrs=@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),(id)kCVPixelBufferWidthKey:@8,(id)kCVPixelBufferHeightKey:@8};
    assert(CVPixelBufferPoolCreate(NULL,NULL,(__bridge CFDictionaryRef)attrs,&r->_frameInterpolationOutputPool)==kCVReturnSuccess);
    assert(CVPixelBufferPoolCreatePixelBuffer(NULL,r->_frameInterpolationOutputPool,&r->_currentFrame)==kCVReturnSuccess);
    assert(CVPixelBufferPoolCreatePixelBuffer(NULL,r->_frameInterpolationOutputPool,&r->_previousInterpolationSourceFrame)==kCVReturnSuccess);
    r->_currentFramePresentationTimeStamp=CMTimeMake(100,100);r->_previousInterpolationSourcePresentationTimeStamp=CMTimeMake(99,100);
    r->_currentFrameSequence=7;r->_lastPresentedFrameSequence=6;r->_interpolationStagingSequence=7;
    r->_interpolationStagingStartedAtMs=100;r->_interpolationStagingBudgetMs=5;return r;
}
static BOOL stage(Probe *r) { return [r stageInterpolatedFrameFromPreviousSource:r->_previousInterpolationSourceFrame toSource:r->_currentFrame frameSequence:7 enqueueTimeMs:90 frameNumber:42 displayRefreshRate:180]; }
static void dispose(Probe *r) { [r teardownFrameInterpolationProcessor];dispatch_sync(r->_vtInterpolationQueue,^{});if(r->_currentFrame){CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;} }
int main(void) { @autoreleasepool {
    // Successful path carries the exact immutable midpoint; repeats cannot queue more work.
    Probe *r=freshProbe(NO);VTFrameProcessor *p=r->_frameInterpolationProcessor;
    assert(stage(r));waitFor(r.finished);assert(r->_pendingInterpolatedFrame && r->_pendingInterpolatedForSourceSequence==7);
    assert(!p.ranOnCaller && fabs(p.midpoint-0.995)<0.000001 && fabs(p.previousTime-0.99)<0.000001);
    assert(r->_interpolationStagingSequence==0 && r->_pendingInterpolatedFrameNumber==42);dispose(r);
    // Timeout releases source without releasing the task's ownership slot.
    r=freshProbe(YES);p=r->_frameInterpolationProcessor;assert(stage(r));waitFor(p.entered);
    assert(!stage(r));atomic_store(&testClock,106);[r expireInterpolationStagingIfNeeded];
    assert(r->_interpolationStagingSequence==0 && r->_interpolationProcessInFlight);
    assert(MLPresentationNeedsDraw(7,0,6,0,false));dispatch_semaphore_signal(p.releaseWork);waitFor(r.finished);
    assert(!r->_pendingInterpolatedFrame && !r->_interpolationProcessInFlight && p.calls==1);dispose(r);
    // Stop retires behind processing; same sequence on a new generation cannot publish.
    r=freshProbe(YES);p=r->_frameInterpolationProcessor;assert(stage(r));waitFor(p.entered);
    [r teardownFrameInterpolationProcessor];assert(r->_interpolationProcessInFlight && !p.ended);
    r->_currentFrameSequence=7;dispatch_semaphore_signal(p.releaseWork);waitFor(r.finished);
    dispatch_sync(r->_vtInterpolationQueue,^{});assert(p.ended && !p.endedDuringProcess && !r->_pendingInterpolatedFrame);dispose(r);
    // New decode replaces source while old task runs; stale result never attaches to it.
    r=freshProbe(YES);p=r->_frameInterpolationProcessor;assert(stage(r));waitFor(p.entered);
    @synchronized(r){r->_currentFrameSequence=8;r->_interpolationStagingSequence=8;}
    dispatch_semaphore_signal(p.releaseWork);waitFor(r.finished);assert(!r->_pendingInterpolatedFrame && r->_interpolationStagingSequence==8);dispose(r);
    // A queued task invalidated before execution never asks VT.
    r=freshProbe(NO);p=r->_frameInterpolationProcessor;dispatch_semaphore_t gate=dispatch_semaphore_create(0);
    dispatch_async(r->_vtInterpolationQueue,^{waitFor(gate);});assert(stage(r));
    @synchronized(r){r->_currentFrameSequence=8;}
    dispatch_semaphore_signal(gate);waitFor(r.finished);assert(p.calls==0 && !r->_pendingInterpolatedFrame);dispose(r);
    // A source already submitted cannot be overtaken by its midpoint.
    r=freshProbe(YES);p=r->_frameInterpolationProcessor;assert(stage(r));waitFor(p.entered);
    @synchronized(r){r->_lastPresentedFrameSequence=7;}
    dispatch_semaphore_signal(p.releaseWork);waitFor(r.finished);assert(!r->_pendingInterpolatedFrame);dispose(r);
    // Backend failure unblocks presentation and reports runtime failure, not active.
    r=freshProbe(NO);p=r->_frameInterpolationProcessor;p.fail=YES;assert(stage(r));waitFor(r.finished);
    assert(!r->_pendingInterpolatedFrame && r->_interpolationStagingSequence==0 && r.report==MLVideoFrameInterpolationReportRuntimeUnavailable);dispose(r);
    // Preparatory staging also expires, without requiring a task to have been admitted.
    r=freshProbe(NO);atomic_store(&testClock,105);[r expireInterpolationStagingIfNeeded];
    assert(r->_interpolationStagingSequence==0);dispose(r);
    puts("ok: native FI lifecycle 8 scenarios; real CV/dispatch, simulated VT");
} return 0; }
