//
//  InterpolationCadencePolicy.h
//  Moonlight
//
//  One answer to "can this display interpolate frames at this stream frame rate, and if not,
//  which frame rate would work". It is a C header rather than a method because two very
//  different places have to agree on it: the renderer, which refuses to build an interpolating
//  engine, and the settings page, which has to warn a player before the stream starts. Those two
//  drifted once in this repository's neighbourhood (see the "keep in step with" comments this
//  file replaces in spirit), and a player who was told to pick a value that the renderer then
//  also refused is worse off than one who was told nothing.
//
//  The rule itself, measured from the admission it mirrors: a display can hold one interpolated
//  frame between every pair of source frames only if its refresh rate is at least 1.5x the
//  stream rate and at least 12 Hz above it. 60 FPS therefore needs 102 Hz, and a 180 Hz panel
//  accepts at most 120 FPS -- which is exactly the pairing a player on a 180 Hz screen has to
//  pick, and the reason this is arithmetic rather than prose.
//

#ifndef InterpolationCadencePolicy_h
#define InterpolationCadencePolicy_h

#include <stdbool.h>

/// How many frame rates the settings page offers as selectable values, minus 0 (which means
/// "let the host decide" and is not a rate a warning can recommend).
/// scripts/interpolation-cadence-policy-tests.py fails the tree when this list and fpss in
/// SettingsModel+DerivedValues.swift stop agreeing, so a recommendation the page prints is
/// always a value the page can actually select. The table lives inside a function rather than
/// as a file-scope static because a header is read by every translation unit that imports it,
/// and an unused file-scope array is a warning in the ones that never touch it.
static inline int MLStreamFpsPresetCount(void)
{
    return 5;
}

/// The offered frame rate at an index, slowest first: 30, 60, 90, 120, 144. Out of range
/// answers 0, the same value this file uses for "there is no such recommendation".
static inline int MLStreamFpsPresetAtIndex(int index)
{
    switch (index) {
        case 0: return 30;
        case 1: return 60;
        case 2: return 90;
        case 3: return 120;
        case 4: return 144;
        default: return 0;
    }
}

/// The refresh rate a given stream frame rate needs before interpolation is worth building.
static inline double MLInterpolationMinimumRefreshForSourceFps(double sourceFps)
{
    double byRatio = sourceFps * 1.5;
    double byHeadroom = sourceFps + 12.0;
    return byRatio > byHeadroom ? byRatio : byHeadroom;
}

/// The question the renderer asks, in one place: does this display have the cadence headroom?
/// An unknown refresh rate answers "no" rather than "yes", because an engine built on a
/// assumption nobody measured is the failure that looks like success right up until the drop.
static inline bool MLInterpolationHasCadenceHeadroom(double refreshHz, int sourceFps)
{
    if (refreshHz <= 0.0 || sourceFps <= 0) {
        return false;
    }
    return refreshHz >= MLInterpolationMinimumRefreshForSourceFps((double)sourceFps);
}

/// The fastest stream frame rate this refresh rate can carry, truncated to a whole frame, or 0
/// when the display cannot carry any offered rate at all.
static inline int MLInterpolationMaxSourceFpsForRefresh(double refreshHz)
{
    if (refreshHz <= 0.0) {
        return 0;
    }
    double byRatio = refreshHz / 1.5;
    double byHeadroom = refreshHz - 12.0;
    double cap = byRatio < byHeadroom ? byRatio : byHeadroom;
    if (cap < (double)MLStreamFpsPresetAtIndex(0)) {
        return 0;
    }
    return (int)cap;
}

/// The frame rate to recommend: the largest offered rate the display can carry, or 0 when even
/// the slowest one is beyond it (a 60 Hz panel, where interpolation is simply not on the table).
static inline int MLInterpolationSuggestedFpsForRefresh(double refreshHz)
{
    int cap = MLInterpolationMaxSourceFpsForRefresh(refreshHz);
    int suggested = 0;
    for (int i = 0; i < MLStreamFpsPresetCount(); i++) {
        int preset = MLStreamFpsPresetAtIndex(i);
        if (preset <= cap && preset > suggested) {
            suggested = preset;
        }
    }
    return suggested;
}

#endif /* InterpolationCadencePolicy_h */
