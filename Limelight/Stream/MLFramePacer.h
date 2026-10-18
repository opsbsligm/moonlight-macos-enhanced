//
//  MLFramePacer.h
//  Moonlight
//
//  Ported from moonlight-qt Pacer (pacer.h/pacer.cpp).
//  Dual-queue frame pacing: pacing queue (pre-vsync) + render queue (post-vsync),
//  with adaptive frame dropping based on queue history.
//  Licensed under GPL-3.0.
//

#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import "VideoDecoderRenderer.h"

NS_ASSUME_NONNULL_BEGIN

/// The maximum number of frames the pacer will ever hold in flight.
/// - 3 frames in the pacing queue
/// - 1 frame removed from the render queue in the process of rendering
/// - 1 frame for deferred free (GPU safety)
#define MLPacerMaxOutstandingFrames 5
#define MLPacerMaxQueuedFrames 3
#define MLPacerTimerSlackMs 3

/// A display link / vsync source that drives the pacer.
/// On macOS this wraps CVDisplayLink.
@protocol MLVsyncSource <NSObject>
- (BOOL)initializeVsyncWithDisplayFps:(int)displayFps;
- (BOOL)isAsync;
- (void)waitForVsync;
@end

/// Opaque frame wrapper for the pacer queue.
/// The pacer takes ownership of the CVPixelBuffer and releases it when done.
@interface MLPacedFrame : NSObject
@property (nonatomic, assign) CVPixelBufferRef pixelBuffer;
@property (nonatomic, assign) uint64_t enqueueTimeUs;   // LiGetMicroseconds() when submitted
@property (nonatomic, assign) uint64_t receiveTimeMs;
@property (nonatomic, assign) unsigned int presentationTimeMs;
@property (nonatomic, assign) uint32_t frameNumber;
@property (nonatomic, assign) BOOL isInterpolated;
@end

/// Delegate for rendering a frame that the pacer has decided to show.
@protocol MLFramePacerDelegate <NSObject>
- (void)pacerRenderFrame:(CVPixelBufferRef)pixelBuffer
             enqueueTimeUs:(uint64_t)enqueueTimeUs
               interpolated:(BOOL)interpolated;
- (void)pacerCleanupRenderContext;
@end

/// Frame pacing engine.
///
/// Separates decode from display: decoded frames enter the pacing queue, and
/// one frame per vsync is promoted to the render queue. If the decoder
/// produces frames faster than the display rate, excess frames are dropped
/// intelligently (keeping the most recent). Queue depth history provides
/// leniency for brief bursts vs. sustained overload.
///
/// Usage:
///   pacer = [[MLFramePacer alloc] initWithDelegate:renderer];
///   [pacer initializeWithMaxVideoFps:60 displayFps:120 enablePacing:YES];
///   // On each decoded frame:
///   [pacer submitPixelBuffer:... enqueueTimeUs:...];
///   // On each vsync callback:
///   [pacer signalVsync];
///   // To render on main thread:
///   [pacer renderOnMainThread];
@interface MLFramePacer : NSObject

- (instancetype)initWithDelegate:(id<MLFramePacerDelegate>)delegate
                      videoStats:(VideoStats *)videoStats NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;

/// Configure the pacer. Must be called before submitPixelBuffer.
/// @param maxVideoFps The maximum frame rate of the video stream.
/// @param displayFps The display refresh rate.
/// @param enablePacing YES to enable frame pacing; NO to bypass (render immediately).
- (BOOL)initializeWithMaxVideoFps:(int)maxVideoFps
                       displayFps:(int)displayFps
                     enablePacing:(BOOL)enablePacing;

/// Submit a decoded pixel buffer to the pacing queue.
/// The pacer takes ownership of the buffer (retains it).
- (void)submitPixelBuffer:(CVPixelBufferRef)pixelBuffer
             enqueueTimeUs:(uint64_t)enqueueTimeUs
             receiveTimeMs:(uint64_t)receiveTimeMs
        presentationTimeMs:(unsigned int)presentationTimeMs
              frameNumber:(uint32_t)frameNumber
            isInterpolated:(BOOL)isInterpolated;

/// Called on vsync (from CVDisplayLink callback or timer).
/// Promotes one frame from pacing queue to render queue.
- (void)signalVsync;

/// Render the next available frame on the calling thread.
/// Call this from the main run loop or render thread.
- (void)renderOnMainThread;

/// Stop the pacer and release all queued frames.
- (void)stop;

/// Current queue depths (for diagnostics).
@property (nonatomic, readonly) NSInteger pacingQueueDepth;
@property (nonatomic, readonly) NSInteger renderQueueDepth;
@property (nonatomic, readonly) uint32_t pacerDroppedFrames;

@end

NS_ASSUME_NONNULL_END
