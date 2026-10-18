#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Tracks network bandwidth over a sliding window using fixed-interval buckets.
/// Thread-safe. Ported from moonlight-qt's BandwidthTracker.
@interface MLBandwidthTracker : NSObject

- (instancetype)initWithWindowSeconds:(uint32_t)windowSeconds
                    bucketIntervalMs:(uint32_t)bucketIntervalMs NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;

/// Record bytes received at the current time.
- (void)addBytes:(NSUInteger)bytes;

/// Average bandwidth in Mbps for the most recent 25% of completed buckets.
- (double)averageMbps;

/// Peak bandwidth in Mbps over any single bucket interval within the window.
- (double)peakMbps;

/// The tracking window duration in seconds.
- (unsigned int)windowSeconds;

@end

NS_ASSUME_NONNULL_END
