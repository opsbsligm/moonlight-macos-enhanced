#import "MLBandwidthTracker.h"
#import <mach/mach_time.h>

@interface MLBandwidthTracker () {
    struct {
        uint64_t startNanos;
        NSUInteger bytes;
    } *_buckets;
    uint32_t _bucketCount;
    uint32_t _windowSeconds;
    uint32_t _bucketIntervalMs;
    os_unfair_lock _lock;
}
@end

@implementation MLBandwidthTracker

- (instancetype)initWithWindowSeconds:(uint32_t)windowSeconds bucketIntervalMs:(uint32_t)bucketIntervalMs {
    self = [super init];
    if (self) {
        _windowSeconds = windowSeconds > 0 ? windowSeconds : 10;
        _bucketIntervalMs = (bucketIntervalMs > 0) ? bucketIntervalMs : 250;
        _bucketCount = (_windowSeconds * 1000) / _bucketIntervalMs;
        _buckets = calloc(_bucketCount, sizeof(*_buckets));
        _lock = OS_UNFAIR_LOCK_INIT;
    }
    return self;
}

- (void)dealloc {
    free(_buckets);
}

/// Nanoseconds since first call, monotonic.
static inline uint64_t ml_nanos(void) {
    static dispatch_once_t s_onceToken;
    static mach_timebase_info_data_t s_timebase;
    static uint64_t s_machBase;
    dispatch_once(&s_onceToken, ^{
        mach_timebase_info(&s_timebase);
        s_machBase = mach_absolute_time();
    });
    uint64_t raw = mach_absolute_time() - s_machBase;
    return (raw * s_timebase.numer) / s_timebase.denom;
}

- (void)addBytes:(NSUInteger)bytes {
    os_unfair_lock_lock(&_lock);
    [self p_addBytes:bytes now:ml_nanos()];
    os_unfair_lock_unlock(&_lock);
}

- (double)averageMbps {
    os_unfair_lock_lock(&_lock);
    double r = [self p_averageAt:ml_nanos()];
    os_unfair_lock_unlock(&_lock);
    return r;
}

- (double)peakMbps {
    os_unfair_lock_lock(&_lock);
    double r = [self p_peakAt:ml_nanos()];
    os_unfair_lock_unlock(&_lock);
    return r;
}

- (unsigned int)windowSeconds {
    return _windowSeconds;
}

#pragma mark - Private

- (void)p_addBytes:(NSUInteger)bytes now:(uint64_t)now {
    uint64_t nowMs = now / 1000000ULL;
    uint32_t idx = (uint32_t)((nowMs / _bucketIntervalMs) % _bucketCount);
    uint64_t aligned = (nowMs - (nowMs % _bucketIntervalMs)) * 1000000ULL;

    struct { uint64_t startNanos; NSUInteger bytes; } *b = &_buckets[idx];
    uint64_t windowNs = (uint64_t)_windowSeconds * 1000000000ULL;

    if (b->startNanos == 0 || (now - b->startNanos) > windowNs) {
        b->startNanos = aligned;
        b->bytes = bytes;
    } else if (b->startNanos == aligned) {
        b->bytes += bytes;
    } else {
        b->startNanos = aligned;
        b->bytes = bytes;
    }
}

- (double)p_averageAt:(uint64_t)now {
    uint32_t take = MAX(_bucketCount / 4, 1);
    uint64_t nowMs = now / 1000000ULL;
    int32_t cur = (int32_t)((nowMs / _bucketIntervalMs) % _bucketCount);
    uint64_t totalBytes = 0;
    uint64_t oldest = now;

    for (int32_t i = 0; i < (int32_t)take; i++) {
        int32_t idx = (cur - i + (int32_t)_bucketCount) % (int32_t)_bucketCount;
        if (_buckets[idx].startNanos == 0) continue;
        uint64_t ageMs = (now - _buckets[idx].startNanos) / 1000000ULL;
        if (ageMs >= _bucketIntervalMs) {
            totalBytes += _buckets[idx].bytes;
            if (_buckets[idx].startNanos < oldest) oldest = _buckets[idx].startNanos;
        }
    }

    double elapsed = (now - oldest) / 1000000000.0;
    if (elapsed <= 0.0) return 0.0;
    return (double)totalBytes * 8.0 / 1000000.0 / elapsed;
}

- (double)p_peakAt:(uint64_t)now {
    (void)now;
    double peak = 0.0;
    double period = _bucketIntervalMs / 1000.0;
    for (uint32_t i = 0; i < _bucketCount; i++) {
        if (_buckets[i].startNanos == 0) continue;
        double mbps = (double)_buckets[i].bytes * 8.0 / 1000000.0 / period;
        if (mbps > peak) peak = mbps;
    }
    return peak;
}

@end
