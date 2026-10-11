// Independent observations of MTLDrawable.presentedTime; never submission counters.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <math.h>
#define ML_ACTUAL_PRESENTATION_CAPACITY 128

typedef struct { double time, submittedAt; } MLActualPresentationSample;
typedef struct {
    uint64_t generation, presented, interpolated, scaled, unpresented, invalid;
    size_t count, next;
    MLActualPresentationSample samples[ML_ACTUAL_PRESENTATION_CAPACITY];
} MLActualPresentationState;
typedef struct {
    bool available, waitAvailable;
    size_t count;
    double fps, frameP95Ms, waitP95Ms, latestTime;
} MLActualPresentationReading;

static inline void MLActualPresentationReset(MLActualPresentationState *state) {
    uint64_t generation = state->generation + 1;
    *state = (MLActualPresentationState){0};
    state->generation = generation;
}
static inline bool MLActualPresentationRecord(MLActualPresentationState *state, uint64_t generation,
                                              double time, double submittedAt, bool interpolated, bool scaled) {
    if (generation != state->generation) return false;
    if (time == 0.0) { state->unpresented++; return false; }
    if (!isfinite(time) || time < 0.0) { state->invalid++; return false; }
    // Handler arrival order need not equal presentation order. Sort at query time.
    state->samples[state->next] = (MLActualPresentationSample){time, submittedAt};
    state->next = (state->next + 1) % ML_ACTUAL_PRESENTATION_CAPACITY;
    if (state->count < ML_ACTUAL_PRESENTATION_CAPACITY) state->count++;
    state->presented++;
    if (interpolated) state->interpolated++;
    if (scaled) state->scaled++;
    return true;
}
static inline int MLActualPresentationCompare(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static inline double MLActualPresentationP95(double *values, size_t count) {
    if (!count) return 0.0;
    qsort(values, count, sizeof(double), MLActualPresentationCompare);
    return values[(count * 95 + 99) / 100 - 1];
}
static inline MLActualPresentationReading MLActualPresentationRead(const MLActualPresentationState *state, double now) {
    MLActualPresentationReading result = {0};
    result.count = state->count;
    if (state->count < 2 || !isfinite(now)) return result;
    double times[ML_ACTUAL_PRESENTATION_CAPACITY], waits[ML_ACTUAL_PRESENTATION_CAPACITY];
    double intervals[ML_ACTUAL_PRESENTATION_CAPACITY];
    size_t waitCount = 0, intervalCount = 0;
    for (size_t i = 0; i < state->count; ++i) {
        MLActualPresentationSample sample = state->samples[i];
        times[i] = sample.time;
        if (isfinite(sample.submittedAt) && sample.submittedAt > 0.0 && sample.submittedAt <= sample.time)
            waits[waitCount++] = (sample.time - sample.submittedAt) * 1000.0;
    }
    qsort(times, state->count, sizeof(double), MLActualPresentationCompare);
    result.latestTime = times[state->count - 1];
    if (now < result.latestTime || now - result.latestTime > 2.0) return result;
    for (size_t i = 1; i < state->count; ++i) {
        if (times[i] <= times[i - 1]) return result; // ambiguous duplicate time: no FPS claim
        intervals[intervalCount++] = (times[i] - times[i - 1]) * 1000.0;
    }
    result.fps = (state->count - 1) / (result.latestTime - times[0]);
    result.frameP95Ms = MLActualPresentationP95(intervals, intervalCount);
    result.waitAvailable = waitCount > 0;
    result.waitP95Ms = MLActualPresentationP95(waits, waitCount);
    result.available = true;
    return result;
}
