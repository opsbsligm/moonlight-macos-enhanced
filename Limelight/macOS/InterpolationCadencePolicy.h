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
//  The rule itself, measured from the admission it mirrors: doubling a stream's frame rate only
//  looks smooth when every frame -- source and interpolated alike -- lands on a whole number of
//  display refreshes. That is true exactly when the refresh rate is a whole multiple of twice
//  the stream rate: 90 FPS on a 180 Hz panel puts one interpolated frame in every refresh;
//  120 FPS on that same panel tries to show 240 frames on a screen that scans 180 times, so
//  some frames wait one refresh and some wait none, and the motion reads as viscous jitter no
//  matter how low the measured latency is. The 180 Hz player therefore gets 90, not 120 --
//  the arithmetic is the feature. Measured panels lie by a few hundredths of a hertz
//  (179.82 for a display mode named 180), so the multiple is judged within a few percent;
//  that tolerance is the difference between refusing a 60 FPS stream on a "180 Hz" screen for
//  the right reason and refusing a 90 FPS stream for a rounding error.
//

#ifndef InterpolationCadencePolicy_h
#define InterpolationCadencePolicy_h

#include <stdbool.h>
#include <math.h>

// How far a measured refresh rate may sit from a whole multiple of twice the stream rate and
// still be counted as that multiple. Display modes are advertised as round numbers and measured
// with a display link's timer resolution; 179.82 for 180 is 0.1%, while the nearest wrong
// pairing on a 144 Hz panel (60 FPS, a 1.2x cadence) sits 20% away. Three percent separates
// "this is that cadence, measured" from "this is a different cadence" with room on both sides.
#define ML_INTERPOLATION_CADENCE_TOLERANCE 0.03

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

/// The refresh rate a given stream frame rate needs at the closest possible cadence: the
/// doubled stream rate, one interpolated frame per display refresh. Anything the admission
/// accepts sits at a whole multiple of this; the value itself is what a forced-admission log
/// line names as the floor it overrode.
static inline double MLInterpolationMinimumRefreshForSourceFps(double sourceFps)
{
    return sourceFps * 2.0;
}

/// The question the renderer asks, in one place: does this display carry the doubled stream
/// cadence on whole refreshes? An unknown refresh rate answers "no" rather than "yes", because
/// an engine built on an assumption nobody measured is the failure that looks like success right
/// up until the drop. A ratio below one -- more doubled frames than the screen scans -- is the
/// same refusal the old headroom floor made, just named by what the player would see.
static inline bool MLInterpolationHasCadenceHeadroom(double refreshHz, int sourceFps)
{
    if (refreshHz <= 0.0 || sourceFps <= 0) {
        return false;
    }
    double ratio = refreshHz / ((double)sourceFps * 2.0);
    double nearest = round(ratio);
    if (nearest < 1.0) {
        return false;
    }
    double difference = ratio > nearest ? ratio - nearest : nearest - ratio;
    return difference <= ML_INTERPOLATION_CADENCE_TOLERANCE;
}

/// The fastest offered stream frame rate this refresh rate can carry at an even cadence, or 0
/// when the display cannot carry any offered rate at all (a 144 Hz panel, whose only even
/// doubled pairing -- 72 FPS -- is not one the page offers).
static inline int MLInterpolationMaxSourceFpsForRefresh(double refreshHz)
{
    int best = 0;
    for (int i = 0; i < MLStreamFpsPresetCount(); i++) {
        int preset = MLStreamFpsPresetAtIndex(i);
        if (MLInterpolationHasCadenceHeadroom(refreshHz, preset) && preset > best) {
            best = preset;
        }
    }
    return best;
}

/// The frame rate to recommend: the largest offered rate the display can carry at an even
/// cadence, or 0 when none can (interpolation is simply not on the table on that panel without
/// forcing it).
static inline int MLInterpolationSuggestedFpsForRefresh(double refreshHz)
{
    return MLInterpolationMaxSourceFpsForRefresh(refreshHz);
}

#endif /* InterpolationCadencePolicy_h */
