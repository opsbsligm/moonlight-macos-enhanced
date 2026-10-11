// Bounded asynchronous VT super-resolution admission/publication decisions.
#pragma once
#include <stdbool.h>
#include <stdint.h>
static inline bool MLEnhancementMayPublish(uint64_t taskGeneration, uint64_t currentGeneration,
                                           uint64_t taskSequence, uint64_t currentSequence,
                                           bool inputIsCurrent, bool alreadySubmitted) {
    return taskGeneration == currentGeneration && taskSequence == currentSequence &&
           inputIsCurrent && !alreadySubmitted;
}
static inline bool MLEnhancementShouldWait(bool sameInput, uint64_t startedAtMs,
                                          uint64_t nowMs, uint64_t budgetMs) {
    return sameInput && nowMs >= startedAtMs && nowMs - startedAtMs < budgetMs;
}

// Current-session circuit breaker: isolated mild overruns can recover, but a
// failed call or a four-period task must not continually occupy the accelerator.
static inline uint32_t MLEnhancementOverloadStrikes(uint32_t previous, bool processed,
                                                   uint64_t elapsedMs, uint64_t budgetMs) {
    if (!processed || budgetMs == 0 || elapsedMs / budgetMs >= 4) return 3;
    if (elapsedMs >= budgetMs) return previous >= 2 ? 3 : previous + 1;
    return 0;
}
