// Deterministic backend double; real shipping renderer methods are inserted below.
// This exercises native CV buffer lifetime and real dispatch ordering, not VT quality.
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#include <assert.h>
#include <math.h>
#include "EnhancementProcessingPolicy.h"
// Never register doubles under the system VideoToolbox runtime class names.
#define VTFrameProcessorFrame MLTestSRFrameProcessorFrame
#define VTLowLatencySuperResolutionScalerParameters MLTestSRLowLatencySuperResolutionScalerParameters
#define VTSuperResolutionScalerParameters MLTestSRSuperResolutionScalerParameters
#define VTFrameProcessor MLTestSRFrameProcessor
#define LOG_W 1
#define Log(level, ...) do {} while (0)
static uint64_t testTimeMs = 100;
static uint64_t LiGetMillis(void) { return testTimeMs; }
@@ENUM@@
static NSString *MLVideoEnhancementEngineName(MLActiveVideoEnhancementEngine e) { return @"test"; }
@interface VTFrameProcessorFrame : NSObject
@property(nonatomic) CVImageBufferRef buffer;
@property(nonatomic) CMTime timestamp;
- (instancetype)initWithBuffer:(CVImageBufferRef)b presentationTimeStamp:(CMTime)t;
@end
@implementation VTFrameProcessorFrame
- (instancetype)initWithBuffer:(CVImageBufferRef)b presentationTimeStamp:(CMTime)t { self=[super init]; if(self){_buffer=b;_timestamp=t;}return self; }
@end
@interface VTLowLatencySuperResolutionScalerParameters : NSObject
@property(nonatomic,strong) VTFrameProcessorFrame *source;
@property(nonatomic,strong) VTFrameProcessorFrame *destination;
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s destinationFrame:(VTFrameProcessorFrame *)d;
@end
@implementation VTLowLatencySuperResolutionScalerParameters
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s destinationFrame:(VTFrameProcessorFrame *)d { self=[super init];if(self){_source=s;_destination=d;}return self; }
@end
#define VTSuperResolutionScalerParametersSubmissionModeSequential 1
#define VTSuperResolutionScalerParametersSubmissionModeRandom 0
@interface VTSuperResolutionScalerParameters : VTLowLatencySuperResolutionScalerParameters
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s previousFrame:(VTFrameProcessorFrame *)p previousOutputFrame:(VTFrameProcessorFrame *)o opticalFlow:(id)f submissionMode:(NSInteger)m destinationFrame:(VTFrameProcessorFrame *)d;
@end
@implementation VTSuperResolutionScalerParameters
- (instancetype)initWithSourceFrame:(VTFrameProcessorFrame *)s previousFrame:(VTFrameProcessorFrame *)p previousOutputFrame:(VTFrameProcessorFrame *)o opticalFlow:(id)f submissionMode:(NSInteger)m destinationFrame:(VTFrameProcessorFrame *)d {return [super initWithSourceFrame:s destinationFrame:d];}
@end
@interface VTFrameProcessor : NSObject
@property(nonatomic,strong) dispatch_semaphore_t entered;
@property(nonatomic,strong) dispatch_semaphore_t allowed;
@property(atomic) BOOL running;
@property(atomic) NSUInteger calls;
@property(atomic) NSUInteger ends;
@property(nonatomic) CMTime seenTimestamp;
@property(nonatomic) uint64_t elapsedMs;
@property(nonatomic) BOOL fail;
- (BOOL)processWithParameters:(VTLowLatencySuperResolutionScalerParameters *)p error:(NSError **)e;
- (void)endSession;
@end
@implementation VTFrameProcessor
- (instancetype)init { self=[super init];if(self){_entered=dispatch_semaphore_create(0);_allowed=dispatch_semaphore_create(0);}return self; }
- (BOOL)processWithParameters:(VTLowLatencySuperResolutionScalerParameters *)p error:(NSError **)e {
    self.running=YES;self.calls+=1;dispatch_semaphore_signal(self.entered);
    assert(dispatch_semaphore_wait(self.allowed,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC))==0);
    // Touch real buffers only after the test has retired the renderer's references.
    assert(CVPixelBufferGetWidth(p.source.buffer)==4);
    assert(CVPixelBufferGetWidth(p.destination.buffer)==8);
    self.seenTimestamp=p.source.timestamp; testTimeMs += self.elapsedMs; self.running=NO;return !self.fail;
}
- (void)endSession { assert(!self.running);self.ends+=1; }
@end
@interface Probe : NSObject {
@public
    id _frameProcessor, _frameProcessorConfiguration;
    CVPixelBufferPoolRef _frameProcessorOutputPool;
    MLActiveVideoEnhancementEngine _frameProcessorEngine, _enhancementWarmupEngine;
    MLActiveVideoEnhancementEngine _activeEnhancementEngine, _lastLoggedEnhancementEngine;
    NSInteger _frameProcessorInputWidth, _frameProcessorInputHeight, _enhancementWarmupWidth, _enhancementWarmupHeight;
    float _frameProcessorScaleFactor, _enhancementWarmupScaleFactor;
    BOOL _enhancementWarmupInFlight, _enhancementProcessInFlight;
    NSUInteger _enhancementWarmupGeneration, _enhancementProcessGeneration;
    dispatch_queue_t _vtEnhancementQueue;
    CVImageBufferRef _enhancementTaskSourceFrame, _enhancementResultFrame, _enhancementResultSourceFrame;
    CVImageBufferRef _previousEnhancedSourceFrame, _previousEnhancedOutputFrame;
    CVImageBufferRef _currentFrame, _pendingInterpolatedFrame;
    uint64_t _enhancementTaskSequence, _enhancementTaskStartedAtMs, _enhancementFailedSequence;
    uint64_t _enhancementResultSequence, _currentFrameSequence, _pendingInterpolatedForSourceSequence, _lastPresentedFrameSequence;
    BOOL _pendingInterpolatedPresented;
    uint64_t _enhancementFailedInterpolatedSequence;
    uint32_t _enhancementOverloadStrikes;
    BOOL _enhancementSuspended;
    uint64_t _enhancementSuspendedWhenMs, _enhancementProbeBackoffMs;
    CMTime _previousEnhancedPresentationTimeStamp;
    double _lastDisplayRefreshRate;
}
@property(nonatomic) int frameRate;
@property(atomic) NSUInteger draws;
- (BOOL)prepareFrameProcessorForEngine:(MLActiveVideoEnhancementEngine)e sourceWidth:(NSUInteger)w sourceHeight:(NSUInteger)h scaleFactor:(float)s warmupPending:(BOOL *)p;
- (void)requestEnhancedDraw;
- (void)publishVideoEnhancementRuntimeStatusSummary:(NSString *)s detail:(NSString *)d;
- (void)releasePreviousEnhancedFrames;
- (void)teardownEnhancementProcessor;
- (CVImageBufferRef)copyFrameUsingFrameProcessorIfNeeded:(CVImageBufferRef)s activeEnhancement:(MLActiveVideoEnhancementEngine)e scaleFactor:(float)f frameSequence:(uint64_t)n presentationTimeStamp:(CMTime)t interpolatedFrame:(BOOL)i warmupPending:(BOOL *)w processingPending:(BOOL *)p waitForOutput:(BOOL *)wait;
@end
@implementation Probe
- (BOOL)prepareFrameProcessorForEngine:(MLActiveVideoEnhancementEngine)e sourceWidth:(NSUInteger)w sourceHeight:(NSUInteger)h scaleFactor:(float)s warmupPending:(BOOL *)p {return _frameProcessor!=nil;}
- (void)requestEnhancedDraw {self.draws+=1;}
- (void)publishVideoEnhancementRuntimeStatusSummary:(NSString *)s detail:(NSString *)d {}
@@METHODS@@
@end
static Probe *freshProbe(void) {
    Probe *r=[Probe new];r.frameRate=90;r->_lastDisplayRefreshRate=180;
    r->_vtEnhancementQueue=dispatch_queue_create("test.enhancement",DISPATCH_QUEUE_SERIAL);
    r->_frameProcessor=[VTFrameProcessor new];r->_currentFrameSequence=7;
    NSDictionary *attrs=@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
        (id)kCVPixelBufferWidthKey:@8,(id)kCVPixelBufferHeightKey:@8};
    assert(CVPixelBufferPoolCreate(NULL,NULL,(__bridge CFDictionaryRef)attrs,&r->_frameProcessorOutputPool)==kCVReturnSuccess);
    assert(CVPixelBufferCreate(NULL,4,4,kCVPixelFormatType_32BGRA,NULL,&r->_currentFrame)==kCVReturnSuccess);
    return r;
}
int main(void) { @autoreleasepool {
    assert([NSStringFromClass([VTFrameProcessorFrame class]) isEqualToString:@"MLTestSRFrameProcessorFrame"]);
    assert([NSStringFromClass([VTLowLatencySuperResolutionScalerParameters class]) isEqualToString:@"MLTestSRLowLatencySuperResolutionScalerParameters"]);
    assert([NSStringFromClass([VTSuperResolutionScalerParameters class]) isEqualToString:@"MLTestSRSuperResolutionScalerParameters"]);
    assert([NSStringFromClass([VTFrameProcessor class]) isEqualToString:@"MLTestSRFrameProcessor"]);

    if (@available(macOS 26.0,*)) {} else { puts("SKIP async VT lifecycle: runtime below macOS 26");return 0; }
    for(int engineIndex=0;engineIndex<2;engineIndex++) for(int scenario=0;scenario<4;scenario++) {
        Probe *r=freshProbe();VTFrameProcessor *p=r->_frameProcessor;
        MLActiveVideoEnhancementEngine engine=engineIndex?MLActiveVideoEnhancementEngineVTQualitySuperResolution:MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
        BOOL warm=NO,pending=NO,wait=NO;CMTime pts=CMTimeMake(7,90);
        CVImageBufferRef answer=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:pts interpolatedFrame:NO warmupPending:&warm processingPending:&pending waitForOutput:&wait];
        assert(answer==NULL && pending && wait);
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        // A second refresh must not enqueue another CPU job.
        answer=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:pts interpolatedFrame:NO warmupPending:&warm processingPending:&pending waitForOutput:&wait];
        assert(answer==NULL && pending && p.calls==1);
        if(scenario==1) {CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;[r teardownEnhancementProcessor];assert(p.ends==0);}
        if(scenario==2) {@synchronized(r){r->_currentFrameSequence=8;}}
        if(scenario==3) {@synchronized(r){r->_lastPresentedFrameSequence=7;}}
        dispatch_semaphore_signal(p.allowed);
        dispatch_sync(r->_vtEnhancementQueue,^{}); // test barrier, not production UI
        assert(!r->_enhancementProcessInFlight && p.calls==1);
        if(scenario==0) {
            assert(r.draws==1 && r->_enhancementResultFrame!=NULL);
            answer=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:pts interpolatedFrame:NO warmupPending:&warm processingPending:&pending waitForOutput:&wait];
            assert(answer && CVPixelBufferGetWidth(answer)==8 && !pending && !wait);
            CVBufferRelease(answer);assert(CMTimeCompare(p.seenTimestamp,pts)==0);
        } else {assert(r.draws==0 && r->_enhancementResultFrame==NULL);}
        if(r->_currentFrame) {CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;}
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(p.ends==1);
    }
    // Total budget includes queue residence: at/after deadline and clock rollback
    // skip VT, release the slot, fall back, and never repeatedly enqueue that source.
    for(int engineIndex=0;engineIndex<2;engineIndex++) for(int inputKind=0;inputKind<2;inputKind++) for(int timing=0;timing<3;timing++) {
        testTimeMs=100;
        Probe *r=freshProbe(); VTFrameProcessor *p=r->_frameProcessor;
        MLActiveVideoEnhancementEngine engine=engineIndex?MLActiveVideoEnhancementEngineVTQualitySuperResolution:MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
        dispatch_semaphore_t entered=dispatch_semaphore_create(0), release=dispatch_semaphore_create(0);
        dispatch_async(r->_vtEnhancementQueue,^{ dispatch_semaphore_signal(entered); dispatch_semaphore_wait(release,DISPATCH_TIME_FOREVER); });
        assert(dispatch_semaphore_wait(entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        if(inputKind) {r->_pendingInterpolatedFrame=CVBufferRetain(r->_currentFrame);r->_pendingInterpolatedForSourceSequence=7;}
        BOOL w=NO,pending=NO,wait=NO;
        [r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:inputKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        testTimeMs=timing==0?105:(timing==1?106:99);
        dispatch_semaphore_signal(release); dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(p.calls==0 && !r->_enhancementProcessInFlight && !r->_enhancementResultFrame);
        assert((inputKind?r->_enhancementFailedInterpolatedSequence:r->_enhancementFailedSequence)==7 && !r->_enhancementSuspended && r->_enhancementOverloadStrikes==0);
        for(int refresh=0;refresh<20;refresh++) {
            CVImageBufferRef result=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:inputKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
            assert(!result && pending && !wait && p.calls==0 && !r->_enhancementProcessInFlight);
        }
        // The refusal belongs to this source, not all later source frames.
        testTimeMs=200; r->_currentFrameSequence=8; if(inputKind) r->_pendingInterpolatedForSourceSequence=8;
        [r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:8 presentationTimeStamp:CMTimeMake(8,90) interpolatedFrame:inputKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(p.calls==1 && r->_enhancementResultSequence==8 && r->_enhancementResultFrame);
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        if(r->_pendingInterpolatedFrame) CVBufferRelease(r->_pendingInterpolatedFrame);r->_pendingInterpolatedFrame=NULL;
        CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;
    }
    // Finishing on/after deadline must not publish or seed quality-SR history.
    for(int engineIndex=0;engineIndex<2;engineIndex++) for(int inputKind=0;inputKind<2;inputKind++) for(int elapsed=5;elapsed<=6;elapsed++) {
        testTimeMs=100;
        Probe *r=freshProbe();VTFrameProcessor *p=r->_frameProcessor;p.elapsedMs=elapsed;
        MLActiveVideoEnhancementEngine engine=engineIndex?MLActiveVideoEnhancementEngineVTQualitySuperResolution:MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
        if(inputKind) {r->_pendingInterpolatedFrame=CVBufferRetain(r->_currentFrame);r->_pendingInterpolatedForSourceSequence=7;}
        BOOL w=NO,pending=NO,wait=NO;
        [r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:inputKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(p.calls==1 && !r->_enhancementResultFrame && !r->_previousEnhancedOutputFrame && !r->_previousEnhancedSourceFrame);
        assert((inputKind?r->_enhancementFailedInterpolatedSequence:r->_enhancementFailedSequence)==7 && r->_enhancementOverloadStrikes==1 && !r->_enhancementSuspended);
        CVImageBufferRef result=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:inputKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(!result && pending && !wait && p.calls==1 && !r->_enhancementProcessInFlight);
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        if(r->_pendingInterpolatedFrame) CVBufferRelease(r->_pendingInterpolatedFrame);r->_pendingInterpolatedFrame=NULL;
        CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;
    }
    puts("ok: 20 total-deadline scenarios (source and interpolated inputs), queue expiry skips VT, late output discarded, no retry loop or history contamination");
    // A failed midpoint cannot suppress its source (or the reverse). They
    // deliberately share sequence 7, but have different real CV buffers.
    for(int engineIndex=0;engineIndex<2;engineIndex++) for(int firstKind=0;firstKind<2;firstKind++) for(int lateSecond=0;lateSecond<2;lateSecond++) {
        testTimeMs=100;
        Probe *r=freshProbe(); VTFrameProcessor *p=r->_frameProcessor;
        assert(CVPixelBufferCreate(NULL,4,4,kCVPixelFormatType_32BGRA,NULL,&r->_pendingInterpolatedFrame)==kCVReturnSuccess);
        r->_pendingInterpolatedForSourceSequence=7;
        MLActiveVideoEnhancementEngine engine=engineIndex?MLActiveVideoEnhancementEngineVTQualitySuperResolution:MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
        BOOL w=NO,pending=NO,wait=NO;
        p.elapsedMs=5; // One deadline overrun, not a processor-wide hard failure.
        CVImageBufferRef first=firstKind?r->_pendingInterpolatedFrame:r->_currentFrame;
        [r copyFrameUsingFrameProcessorIfNeeded:first activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:firstKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        assert((firstKind?r->_enhancementFailedInterpolatedSequence:r->_enhancementFailedSequence)==7);
        // Same input is not retried, preserving the bounded fallback.
        [r copyFrameUsingFrameProcessorIfNeeded:first activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:firstKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(!r->_enhancementProcessInFlight && p.calls==1 && pending && !wait);
        p.elapsedMs=lateSecond?5:0;
        CVImageBufferRef second=firstKind?r->_currentFrame:r->_pendingInterpolatedFrame;
        [r copyFrameUsingFrameProcessorIfNeeded:second activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:!firstKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(r->_enhancementProcessInFlight && pending && wait);
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        CVImageBufferRef result=[r copyFrameUsingFrameProcessorIfNeeded:second activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:!firstKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
        if (!lateSecond) {assert(result && p.calls==2);CVBufferRelease(result);}
        else {
            assert(!result && p.calls==2 && !r->_enhancementSuspended);
            assert(r->_enhancementFailedSequence==7 && r->_enhancementFailedInterpolatedSequence==7);
            [r copyFrameUsingFrameProcessorIfNeeded:first activeEnhancement:engine scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:firstKind warmupPending:&w processingPending:&pending waitForOutput:&wait];
            assert(!r->_enhancementProcessInFlight && p.calls==2 && pending && !wait);
        }
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(!r->_enhancementFailedSequence && !r->_enhancementFailedInterpolatedSequence);
        CVBufferRelease(r->_pendingInterpolatedFrame);r->_pendingInterpolatedFrame=NULL;
        CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;
    }
    puts("ok: eight SR source/midpoint failure-isolation scenarios, same input never requeues");
    // Three mild consecutive overruns pause; an in-budget call resets strikes.
    for(int recover=0;recover<2;recover++) {
        Probe *r=freshProbe();VTFrameProcessor *p=r->_frameProcessor;
        BOOL w=NO,pending=NO,wait=NO;
        for(int task=0;task<3;task++) {
            @synchronized(r) {r->_currentFrameSequence=7+task;}
            p.elapsedMs=(recover && task==1)?4:6;
            [r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:MLActiveVideoEnhancementEngineVTLowLatencySuperResolution scaleFactor:2 frameSequence:7+task presentationTimeStamp:CMTimeMake(7+task,90) interpolatedFrame:NO warmupPending:&w processingPending:&pending waitForOutput:&wait];
            assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
            dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        }
        assert(r->_enhancementSuspended==!recover);
        assert(r->_enhancementOverloadStrikes==(recover?1:3));
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;
    }
    // Stale input still consumed compute; failure/overload pauses that session.
    for (int reason=0; reason<3; reason++) {
        Probe *r=freshProbe(); VTFrameProcessor *p=r->_frameProcessor;
        p.elapsedMs=reason==0?900:0; p.fail=reason==1;
        BOOL w=NO,pending=NO,wait=NO;
        [r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:MLActiveVideoEnhancementEngineVTQualitySuperResolution scaleFactor:2 frameSequence:7 presentationTimeStamp:CMTimeMake(7,90) interpolatedFrame:NO warmupPending:&w processingPending:&pending waitForOutput:&wait];
        assert(dispatch_semaphore_wait(p.entered,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
        @synchronized(r) {r->_currentFrameSequence=8;}
        if(reason==2) {p.elapsedMs=900; [r teardownEnhancementProcessor];}
        dispatch_semaphore_signal(p.allowed);dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(r->_enhancementSuspended==(reason!=2));
        assert(!r->_enhancementResultFrame);
        if(reason!=2) {
            for(int i=0;i<20;i++) {
                CVImageBufferRef result=[r copyFrameUsingFrameProcessorIfNeeded:r->_currentFrame activeEnhancement:MLActiveVideoEnhancementEngineVTQualitySuperResolution scaleFactor:2 frameSequence:8 presentationTimeStamp:CMTimeMake(8,90) interpolatedFrame:NO warmupPending:&w processingPending:&pending waitForOutput:&wait];
                assert(!result && pending && !wait && p.calls==1);
            }
        }
        [r teardownEnhancementProcessor];dispatch_sync(r->_vtEnhancementQueue,^{});
        assert(!r->_enhancementSuspended && r->_enhancementOverloadStrikes==0);
        CVBufferRelease(r->_currentFrame);r->_currentFrame=NULL;
    }
    puts("ok: overload/failure suppress repeated VT, stale source charged, retired session cannot suspend replacement");
    puts("ok: 8 shipping asynchronous lifecycle scenarios, native CV lifetime + dispatch ordering; VT backend simulated");
    return 0;
}}
