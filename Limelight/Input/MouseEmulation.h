//
//  MouseEmulation.h
//  Moonlight for macOS
//
//  The shared numbers behind moving the pointer with a controller stick,
//  kept in a header of their own, without project imports, because the two
//  files that move the cursor live on different sides of the codebase and
//  one of them must not have to pull in the HID internals to agree on a
//  threshold.
//
//  Copyright \u00a9 Moonlight Stream. All rights reserved.
//

#pragma once

#include <math.h>
#include <stdbool.h>

//  The right stick drives the emulated pointer at this rate, and one pair
//  of numbers has to serve both paths that do it: the HID consumer in
//  HIDSupport+Pointer and the display-link consumer in ControllerSupport.
//  They agreed on the speed by accident -- two separate literals reading
//  15.0 -- and disagreed on the deadzone, which was 4000 counts out of
//  32767 on one side and 0.1 of full scale on the other. The same stick
//  position therefore moved the cursor at two different rates and started
//  moving it at two different deflections, depending on which device
//  produced the frame. The rate is approximately 900 points per second at
//  full deflection at 60Hz.
#define HIDMouseEmulationSpeed 15.0
#define HIDMouseEmulationDeadzone 0.1

/**
 * What one stick axis contributes to an emulated pointer move, as a
 * fraction of a full deflection. Normalising here is the point: a deadzone
 * compared against raw short counts and one compared against a normalised
 * fraction are different thresholds, and the two paths used to carry both.
 * The answer stays a fraction so the caller can hand it to a draining
 * helper, which applies the rate and keeps whatever the frame cannot ship.
 * The emulated pointer used to truncate the fraction itself, which threw
 * away the part of the frame that did not fill a whole pixel: just past
 * the deadzone the cursor travelled at a little over half the speed the
 * settings promised.
 */
static inline double HIDControllerMouseDeltaForAxis(short axisValue) {
    double magnitude = (double)axisValue / 32767.0;
    if (!isfinite(magnitude) || fabs(magnitude) <= HIDMouseEmulationDeadzone) {
        return 0.0;
    }
    return magnitude;
}
