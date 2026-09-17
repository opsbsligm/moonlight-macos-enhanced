//
//  VideoDecoderRenderer.h
//  Moonlight
//
//  Created by Cameron Gutman on 10/18/14.
//  Copyright (c) 2014 Moonlight Stream. All rights reserved.
//

#import <Foundation/Foundation.h>

#import "StreamConfiguration.h"

@import AVFoundation;

typedef struct {
  uint32_t receivedFrames;
  uint32_t decodedFrames;
  uint32_t renderedFrames;
  uint32_t totalFrames;
  uint32_t networkDroppedFrames;
  uint32_t pacerDroppedFrames;
  uint64_t totalReassemblyTime;
  uint64_t totalDecodeTime;
  uint64_t totalPacerTime;
  uint64_t totalRenderTime;
  uint64_t totalHostProcessingLatency;
  uint32_t framesWithHostProcessingLatency;

  float totalFps;
  float receivedFps;
  float decodedFps;
  float renderedFps;

  uint64_t measurementStartTimestamp;
  uint64_t lastUpdatedTimestamp;

  // Bytes of video payload received during this measurement window.
  // Can be used to estimate current bitrate.
  uint64_t receivedBytes;

  // RFC3550-style inter-arrival jitter estimate (ms) derived from frame
  // receiveTimeMs and presentationTimeMs deltas.
  float jitterMs;

  // Rolling 1% low FPS derived from recent rendered frame intervals.
  float renderedFpsOnePercentLow;

  // Frames the frame interpolator produced and drew during this measurement
  // window. It counts pixels that reached the display, not attempts: a window
  // that reads zero is a window where interpolation made nothing, which is a
  // different answer from interpolation being switched off, and the difference
  // is the only way to tell whether the feature does anything at all.
  uint32_t interpolatedFrames;

  // interpolatedFrames as a rate over the window that just closed.
  float interpolatedFps;

  // Frames a hardware scaler resampled and drew during this measurement window.
  // It counts pixels that reached the display, not a scaler being selected: the
  // renderer can name the engine it chose and still have that engine make nothing,
  // and a player who picked a hardware scaler can only tell the two apart if the
  // frames it produced are tallied where they are drawn. Interpolation is counted
  // separately, so a doubled stream that is also scaled reads on both lines.
  uint32_t scaledFrames;

  // scaledFrames as a rate over the window that just closed.
  float scaledFps;

  // The size the scaler wrote those frames at, from the window that published
  // scaledFps. What the player asked for was a bigger picture, so the size is the
  // part of the answer that a count cannot give: 0 means no scaler ran.
  uint32_t scaledOutputWidth;
  uint32_t scaledOutputHeight;
} VideoStats;

@interface VideoDecoderRenderer : NSObject

@property(nonatomic, assign) void *depacketizerContext;

@property(nonatomic, readonly) VideoStats videoStats;
@property(nonatomic, readonly) int videoFormat;

- (id)initWithView:(OSView *)view;

- (void)prewarmPresentationForStreamConfig:(StreamConfiguration *)streamConfig;
- (void)setupWithVideoFormat:(int)videoFormat
                   frameRate:(int)frameRate
               upscalingMode:(int)upscalingMode
                streamConfig:(StreamConfiguration *)streamConfig;
- (void)start;
- (void)stop;

- (int)submitDecodeBuffer:(unsigned char *)data
                   length:(int)length
               bufferType:(int)bufferType
                frameType:(int)frameType
                      pts:(unsigned int)pts;

- (int)submitDecodeUnit:(void *)du;

@end
