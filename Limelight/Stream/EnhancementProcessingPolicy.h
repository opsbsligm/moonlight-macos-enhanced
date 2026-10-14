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

// The staging deadline one interpolation task may hold presentation. A display
// period alone is the wrong shape of answer: VT low-latency interpolation is
// lawful work whose cost is set by the image, not by the panel, so a 180Hz
// display period (~5ms) sits below any honest VTLLFI call and opens the breaker
// on the first three frames -- a budget that cannot be met is a refusal wearing
// the breaker's clothes. The deadline is one source frame period: the instant
// the next source supersedes this task's input, so work finished later cannot
// reach a present that still wants it, and MLEnhancementMayPublish already
// refuses that publication. It is still a deadline the task is charged against:
// a call over the budget scores a strike and a call at four times the budget
// trips the breaker at once, so an engine that cannot keep up still stops.
static inline uint64_t MLEnhancementStagingBudgetMs(double refreshHz, int sourceFps) {
    if (refreshHz <= 0.0 || sourceFps <= 0) {
        return 16;
    }
    const double sourceFrameMs = 1000.0 / (double)sourceFps;
    const double displayFrameMs = 1000.0 / refreshHz;
    double budget = sourceFrameMs;
    if (budget < displayFrameMs) {
        budget = displayFrameMs;
    }
    // A service window below this cannot hold a real call at any resolution, so
    // a high refresh rate must not squeeze it away.
    if (budget < 8.0) {
        budget = 8.0;
    }
    uint64_t floored = (uint64_t)budget;
    return floored < 1 ? 1 : floored;
}

// Cooldown probe: a paused engine re-tests one frame after a growing backoff.
// Without this the breaker is permanent for the whole session, so a temporary
// thermal/scaled-frame stall (for example 4x super-resolution while hot) can
// never recover even after the GPU has cooled down.
static inline bool MLEnhancementProbeDue(uint64_t suspendedSinceMs, uint64_t nowMs, uint64_t backoffMs) {
    return nowMs >= suspendedSinceMs && nowMs - suspendedSinceMs >= backoffMs;
}

// A costly probe must also leave room for normal presentation. Cap its compute
// duty cycle by waiting at least eight times the measured call duration, while
// retaining exponential retry and a bounded opportunity to recover.
static inline uint64_t MLEnhancementNextBackoff(uint64_t previousMs, uint64_t elapsedMs) {
    uint64_t exponential = previousMs == 0 ? 2000 : (previousMs >= 30000 ? 60000 : previousMs * 2);
    uint64_t measured = elapsedMs >= 7500 ? 60000 : elapsedMs * 8;
    uint64_t next = exponential > measured ? exponential : measured;
    return next > 60000 ? 60000 : next;
}
