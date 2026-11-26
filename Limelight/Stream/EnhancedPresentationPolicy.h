// Submission policy shared by the renderer and the behavioural replay.
// Keep one latest source: retry pressure without building latency in a FIFO.
#ifndef ML_ENHANCED_PRESENTATION_POLICY_H
#define ML_ENHANCED_PRESENTATION_POLICY_H
#include <stdbool.h>
#include <stdint.h>

static inline bool MLInterpolationCanStageAfterSource(uint64_t previousSource,
                                                      uint64_t submittedSource,
                                                      bool cacheMatchesSource)
{
    return previousSource != 0 && previousSource == submittedSource && cacheMatchesSource;
}

static inline bool MLInterpolationCanFinishBeforeNextSource(double sourceIntervalMs,
                                                           uint64_t interpolationCostMs,
                                                           bool wasActive)
{
    // The field session measured a 36 FPS source whose per-frame interval jitters inside
    // 19-28 ms while the measured cost sits on the 18/19 ms boundary: a bare > lets the
    // gate flip every frame, and the engine follows it Off/On at frame rate. The margin is
    // the hysteresis band: entering (or staying in) On needs headroom above it, and a
    // frame that only falls short of it keeps the current answer instead of forcing one.
    const double emaMs = (double)interpolationCostMs;
    const double margin = 1.5 > 0.10 * emaMs ? 1.5 : 0.10 * emaMs;
    if (sourceIntervalMs > emaMs + margin) return true;
    if (wasActive) return sourceIntervalMs >= emaMs - margin;
    return false;
}

static inline bool MLInterpolationResultIsCurrent(uint64_t current, uint64_t result,
                                                  uint64_t submittedSource)
{
    return result != 0 && result == current && result != submittedSource;
}

static inline bool MLPresentationNeedsDraw(uint64_t current, uint64_t staging,
                                          uint64_t submittedSource, uint64_t midpointSource,
                                          bool midpointSubmitted)
{
    if (current == 0 || staging == current) return false;
    if (midpointSource == current && !midpointSubmitted) return true;
    return current != submittedSource;
}
#endif
