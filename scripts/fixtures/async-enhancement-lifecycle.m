// Deterministic backend double; real shipping renderer methods are inserted below.
// This exercises native CV buffer lifetime and real dispatch ordering, not VT quality.
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#include <assert.h>
#include <math.h>
#include "EnhancementProcessingPolicy.h"
#define LOG_W 1
#define Log(level, ...) do {} while (0)
static uint64_t LiGetMillis(void) { return NSProcessInfo.processInfo.systemUptime * 1000; }
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
    self.seenTimestamp=p.source.timestamp;self.running=NO;return YES;
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
    puts("ok: 8 shipping asynchronous lifecycle scenarios, native CV lifetime + dispatch ordering; VT backend simulated");
    return 0;
}}
