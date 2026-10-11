// Read-only enumeration scheduling, shared by the stream UI and replay tests.
#pragma once
#include <stdbool.h>
#include <stdint.h>

static inline bool MLUSBScanShouldStart(bool pending, bool stopping, bool force,
                                       bool hasSnapshot, uint64_t snapshotGeneration,
                                       uint64_t currentGeneration, double scannedAt, double now) {
    if (pending || stopping) return false;
    return force || !hasSnapshot || snapshotGeneration != currentGeneration ||
           now < scannedAt || now - scannedAt >= 2.0;
}

static inline bool MLUSBScanMayPublish(bool stopping, uint64_t requestedGeneration,
                                      uint64_t currentGeneration, bool sameHost) {
    return !stopping && requestedGeneration == currentGeneration && sameHost;
}
