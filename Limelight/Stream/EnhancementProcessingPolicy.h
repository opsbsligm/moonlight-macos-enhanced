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
