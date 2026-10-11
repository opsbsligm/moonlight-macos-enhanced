// Controlled real VT backend probe. No streaming, model downloads or preferences.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#include <math.h>
#include <string.h>
static double nowMs(void) { return NSProcessInfo.processInfo.systemUptime * 1000.0; }
static NSDictionary *errorInfo(NSError *e) { return @{ @"domain": e.domain ?: @"unknown", @"code": @(e.code) }; }
static NSDictionary *resolved(NSDictionary *attributes, size_t w, size_t h) {
    NSMutableDictionary *a=[attributes mutableCopy];
    id formats=a[(id)kCVPixelBufferPixelFormatTypeKey];
    NSArray *values=[formats isKindOfClass:NSArray.class] ? formats : (formats ? @[formats] : @[@(kCVPixelFormatType_32BGRA)]);
    NSNumber *chosen=nil;
    for (NSNumber *candidate in @[@(kCVPixelFormatType_32BGRA),@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),@(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange),@(kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange),@(kCVPixelFormatType_420YpCbCr10BiPlanarFullRange),@(kCVPixelFormatType_64RGBAHalf)])
        if ([values containsObject:candidate]) { chosen=candidate;break; }
    if (!chosen) return nil;
    a[(id)kCVPixelBufferPixelFormatTypeKey]=chosen;a[(id)kCVPixelBufferWidthKey]=@(w);a[(id)kCVPixelBufferHeightKey]=@(h);
    a[(id)kCVPixelBufferIOSurfacePropertiesKey]=@{};a[(id)kCVPixelBufferMetalCompatibilityKey]=@YES;
    return a;
}
static BOOL pattern(CVPixelBufferRef b, int frame) {
    if (CVPixelBufferLockBaseAddress(b,0)!=kCVReturnSuccess) return NO;
    OSType f=CVPixelBufferGetPixelFormatType(b);size_t w=CVPixelBufferGetWidth(b),h=CVPixelBufferGetHeight(b);
    if (f==kCVPixelFormatType_32BGRA) {
        uint8_t *base=CVPixelBufferGetBaseAddress(b);size_t stride=CVPixelBufferGetBytesPerRow(b);
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++) {
            uint8_t *p=base+y*stride+x*4;p[0]=(x+frame*19)%256;p[1]=(y+frame*7)%256;p[2]=((x/16+y/16+frame)%2)*220+16;p[3]=255;
        }
    } else if(f==kCVPixelFormatType_64RGBAHalf) {
        uint8_t *base=CVPixelBufferGetBaseAddress(b);size_t stride=CVPixelBufferGetBytesPerRow(b);
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++) {
            __fp16 *v=(__fp16 *)(base+y*stride+x*8);v[0]=(x+frame*19)%256/255.0f;v[1]=y%256/255.0f;v[2]=0.5f;v[3]=1.0f;
        }
    } else if(f==kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange||f==kCVPixelFormatType_420YpCbCr10BiPlanarFullRange) {
        uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(b,0);size_t stride=CVPixelBufferGetBytesPerRowOfPlane(b,0);
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++)((uint16_t *)(base+y*stride))[x]=(64+(x+y+frame*19)%876)<<6;
        uint8_t *chroma=CVPixelBufferGetBaseAddressOfPlane(b,1);size_t cs=CVPixelBufferGetBytesPerRowOfPlane(b,1);
        for(size_t y=0;y<CVPixelBufferGetHeightOfPlane(b,1);y++)for(size_t x=0;x<cs/2;x++)((uint16_t *)(chroma+y*cs))[x]=512<<6;
    } else {
        uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(b,0);size_t stride=CVPixelBufferGetBytesPerRowOfPlane(b,0);
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++)base[y*stride+x]=16+((x+y+frame*19)%220);
        memset(CVPixelBufferGetBaseAddressOfPlane(b,1),128,CVPixelBufferGetBytesPerRowOfPlane(b,1)*CVPixelBufferGetHeightOfPlane(b,1));
    }
    CVPixelBufferUnlockBaseAddress(b,0);return YES;
}
static uint64_t signature(CVPixelBufferRef b) {
    if(CVPixelBufferLockBaseAddress(b,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess)return 0;
    BOOL planar=CVPixelBufferIsPlanar(b);size_t stride=planar?CVPixelBufferGetBytesPerRowOfPlane(b,0):CVPixelBufferGetBytesPerRow(b);
    uint8_t *base=planar?CVPixelBufferGetBaseAddressOfPlane(b,0):CVPixelBufferGetBaseAddress(b);
    size_t h=planar?CVPixelBufferGetHeightOfPlane(b,0):CVPixelBufferGetHeight(b);
    OSType f=CVPixelBufferGetPixelFormatType(b);
    size_t bytes=planar?CVPixelBufferGetWidthOfPlane(b,0)*(f==kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange||f==kCVPixelFormatType_420YpCbCr10BiPlanarFullRange?2:1):CVPixelBufferGetWidth(b)*(f==kCVPixelFormatType_64RGBAHalf?8:4);uint64_t sum=0;
    for(size_t y=0;y<h;y+=17)for(size_t x=0;x<bytes;x+=31)sum=sum*33+base[y*stride+x];
    CVPixelBufferUnlockBaseAddress(b,kCVPixelBufferLock_ReadOnly);return sum;
}
static double percentile(NSArray<NSNumber *> *times,double p) {
    NSArray *sorted=[times sortedArrayUsingSelector:@selector(compare:)];return [sorted[(NSUInteger)ceil(sorted.count*p)-1] doubleValue];
}
static NSDictionary *measure(id<VTFrameProcessorConfiguration> configuration, NSDictionary *inputAttributes,
                             NSDictionary *outputAttributes, NSString *engine, size_t w,size_t h,double scale) API_AVAILABLE(macos(26.0));
static NSDictionary *measure(id<VTFrameProcessorConfiguration> configuration, NSDictionary *inputAttributes,
                             NSDictionary *outputAttributes, NSString *engine, size_t w,size_t h,double scale) {
    NSMutableDictionary *r=[@{@"engine":engine,@"sourceWidth":@(w),@"sourceHeight":@(h),@"scale":@(scale),@"status":@"failed"} mutableCopy];
    size_t ow=lround(w*scale),oh=lround(h*scale);
    NSDictionary *ia=resolved(inputAttributes,w,h),*oa=resolved(outputAttributes,ow,oh);
    if(!ia||!oa){r[@"status"]=@"probe_format_unhandled";r[@"inputFormats"]=inputAttributes[(id)kCVPixelBufferPixelFormatTypeKey]?:@[];r[@"outputFormats"]=outputAttributes[(id)kCVPixelBufferPixelFormatTypeKey]?:@[];return r;}
    VTFrameProcessor *processor=[VTFrameProcessor new];NSError *error=nil;double start=nowMs();
    BOOL started=[processor startSessionWithConfiguration:configuration error:&error];r[@"startSessionMs"]=@(nowMs()-start);
    if(!started){r[@"error"]=errorInfo(error);return r;}
    CVPixelBufferPoolRef ip=NULL,op=NULL;CVPixelBufferRef previousInput=NULL,previousOutput=NULL;
    NSMutableArray *times=[NSMutableArray array];NSMutableSet *signatures=[NSMutableSet set];int completed=0;
    BOOL pools=CVPixelBufferPoolCreate(NULL,NULL,(__bridge CFDictionaryRef)ia,&ip)==kCVReturnSuccess &&
        CVPixelBufferPoolCreate(NULL,NULL,(__bridge CFDictionaryRef)oa,&op)==kCVReturnSuccess;
    BOOL interpolation=[engine isEqual:@"vt_low_latency_fi"];
    if(pools&&interpolation) {
        pools=CVPixelBufferPoolCreatePixelBuffer(NULL,ip,&previousInput)==kCVReturnSuccess && pattern(previousInput,0);
    }
    if(pools)for(int i=0;i<16;i++) {@autoreleasepool {
        CVPixelBufferRef input=NULL,output=NULL;
        if(CVPixelBufferPoolCreatePixelBuffer(NULL,ip,&input)!=kCVReturnSuccess ||
           CVPixelBufferPoolCreatePixelBuffer(NULL,op,&output)!=kCVReturnSuccess || !pattern(input,i+(interpolation?1:0))) {
            if(input)CVBufferRelease(input);if(output)CVBufferRelease(output);break;
        }
        CMTime t=CMTimeMake(i+(interpolation?2:1),90);
        CMTime outputTime=interpolation?CMTimeMake(2*i+3,180):t;
        VTFrameProcessorFrame *src=[[VTFrameProcessorFrame alloc]initWithBuffer:input presentationTimeStamp:t];
        VTFrameProcessorFrame *dst=[[VTFrameProcessorFrame alloc]initWithBuffer:output presentationTimeStamp:outputTime];
        id<VTFrameProcessorParameters> parameters;
        if(interpolation) {
            VTFrameProcessorFrame *previous=[[VTFrameProcessorFrame alloc]initWithBuffer:previousInput presentationTimeStamp:CMTimeMake(i+1,90)];
            parameters=[[VTLowLatencyFrameInterpolationParameters alloc]initWithSourceFrame:src previousFrame:previous interpolationPhase:@[@0.5f] destinationFrames:@[dst]];
        } else if([engine isEqual:@"vt_low_latency_sr"])
            parameters=[[VTLowLatencySuperResolutionScalerParameters alloc]initWithSourceFrame:src destinationFrame:dst];
        else {
            VTFrameProcessorFrame *ps=previousInput?[[VTFrameProcessorFrame alloc]initWithBuffer:previousInput presentationTimeStamp:CMTimeMake(i,90)]:nil;
            VTFrameProcessorFrame *po=previousOutput?[[VTFrameProcessorFrame alloc]initWithBuffer:previousOutput presentationTimeStamp:CMTimeMake(i,90)]:nil;
            parameters=[[VTSuperResolutionScalerParameters alloc]initWithSourceFrame:src previousFrame:ps previousOutputFrame:po opticalFlow:nil
                submissionMode:(ps&&po?VTSuperResolutionScalerParametersSubmissionModeSequential:VTSuperResolutionScalerParametersSubmissionModeRandom) destinationFrame:dst];
        }
        start=nowMs();BOOL processed=parameters&&[processor processWithParameters:parameters error:&error];double elapsed=nowMs()-start;
        if(processed&&CVPixelBufferGetWidth(output)==ow&&CVPixelBufferGetHeight(output)==oh) {
            completed++;if(i>=4)[times addObject:@(elapsed)];[signatures addObject:@(signature(output))];
        } else {r[@"error"]=errorInfo(error);CVBufferRelease(input);CVBufferRelease(output);break;}
        if(previousInput)CVBufferRelease(previousInput);if(previousOutput)CVBufferRelease(previousOutput);
        previousInput=input;previousOutput=output;
    }}
    [processor endSession];if(previousInput)CVBufferRelease(previousInput);if(previousOutput)CVBufferRelease(previousOutput);
    if(ip)CFRelease(ip);if(op)CFRelease(op);
    r[@"completedFrames"]=@(completed);r[@"measuredFrames"]=@(times.count);r[@"distinctOutputSignatures"]=@(signatures.count);
    r[@"outputWidth"]=@(ow);r[@"outputHeight"]=@(oh);
    if(completed==16&&signatures.count>1&&times.count==12) {
        r[@"status"]=@"backend_validated";r[@"p50ProcessMs"]=@(percentile(times,0.5));r[@"p95ProcessMs"]=@(percentile(times,0.95));
        r[@"maxProcessMs"]=[times valueForKeyPath:@"@max.self"];
    }
    return r;
}
int main(void){@autoreleasepool {
    NSMutableArray *cases=[NSMutableArray array];
    if(@available(macOS 26.0,*)) {
        for(NSArray *size in @[@[@1280,@720],@[@1920,@1080],@[@2560,@1440]]) {
            NSInteger w=[size[0] integerValue],h=[size[1] integerValue];
            NSArray *factors=[VTLowLatencySuperResolutionScalerConfiguration supportedScaleFactorsForFrameWidth:w frameHeight:h];
            if(!VTLowLatencySuperResolutionScalerConfiguration.isSupported||!factors.count)
                [cases addObject:@{@"engine":@"vt_low_latency_sr",@"sourceWidth":@(w),@"sourceHeight":@(h),@"factors":factors?:@[],@"status":@"unsupported"}];
            else {
                float factor=[factors.firstObject floatValue];VTLowLatencySuperResolutionScalerConfiguration *c=[[VTLowLatencySuperResolutionScalerConfiguration alloc]initWithFrameWidth:w frameHeight:h scaleFactor:factor];
                [cases addObject:measure(c,c.sourcePixelBufferAttributes,c.destinationPixelBufferAttributes,@"vt_low_latency_sr",w,h,factor)];
            }
            VTLowLatencyFrameInterpolationConfiguration *fi=[[VTLowLatencyFrameInterpolationConfiguration alloc]initWithFrameWidth:w frameHeight:h numberOfInterpolatedFrames:1];
            if(fi.numberOfInterpolatedFrames>0)
                [cases addObject:measure(fi,fi.sourcePixelBufferAttributes,fi.destinationPixelBufferAttributes,@"vt_low_latency_fi",w,h,1.0)];
            else [cases addObject:@{@"engine":@"vt_low_latency_fi",@"sourceWidth":@(w),@"sourceHeight":@(h),@"slots":@(fi.numberOfInterpolatedFrames),@"status":@"unsupported"}];
        }
        NSArray *factors=VTSuperResolutionScalerConfiguration.supportedScaleFactors;
        if(!VTSuperResolutionScalerConfiguration.isSupported||!factors.count)[cases addObject:@{@"engine":@"vt_quality_sr",@"status":@"unsupported"}];
        else {
            NSInteger factor=[[factors valueForKeyPath:@"@min.self"] integerValue];VTSuperResolutionScalerConfiguration *q=[[VTSuperResolutionScalerConfiguration alloc]initWithFrameWidth:1280 frameHeight:720 scaleFactor:factor inputType:VTSuperResolutionScalerConfigurationInputTypeVideo usePrecomputedFlow:NO qualityPrioritization:VTSuperResolutionScalerConfigurationQualityPrioritizationNormal revision:VTSuperResolutionScalerConfiguration.defaultRevision];
            if(q.configurationModelStatus!=VTSuperResolutionScalerConfigurationModelStatusReady)
                [cases addObject:@{@"engine":@"vt_quality_sr",@"status":@"model_not_ready",@"modelStatus":@(q.configurationModelStatus)}];
            else [cases addObject:measure(q,q.sourcePixelBufferAttributes,q.destinationPixelBufferAttributes,@"vt_quality_sr",1280,720,factor)];
        }
    } else [cases addObject:@{@"engine":@"vt_frame_processor",@"status":@"api_unavailable"}];
    NSDictionary *report=@{@"schema":@1,@"os":NSProcessInfo.processInfo.operatingSystemVersionString,@"syntheticInput":@YES,@"realVTBackend":@YES,@"streamingValidated":@NO,@"cases":cases};
    NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];fwrite(json.bytes,1,json.length,stdout);putchar('\n');
}return 0;}
