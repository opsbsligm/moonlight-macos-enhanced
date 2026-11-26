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
                                                           uint64_t interpolationCostMs)
{
    return sourceIntervalMs > (double)interpolationCostMs;
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
