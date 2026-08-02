//
//  KeyboardMapResolver.m
//  Moonlight for macOS
//
//  Copyright © 2026 SkyHua and contributors.
//  This file is part of Moonlight for macOS — Enhanced Edition.
//
//  This program is free software: you can redistribute it and/or modify
//  it under the terms of the GNU General Public License as published by
//  the Free Software Foundation, either version 3 of the License, or
//  (at your option) any later version.
//
//  REFACTORED on 2026-08-02:
//  Implements industry-standard game streaming key mapping.
//  Pure, stateless, and deterministic.
//  No more "smart" logic that causes double-click to send Win keys.
//  No more mode flags. The mapping is fixed and final.
//

#import "KeyboardMapResolver.h"
#import "HIDSupport_Internal.h"
#import "../Utility/Logger.h"

// ---------------------------------------------------------------------------
// 1. The One True Lookup Table (Simplified & Final).
// ---------------------------------------------------------------------------

// This is the ONLY place that defines modifier mapping.
// It maps macOS physical modifier -> Windows HID modifier mask.
static const uint8_t s_mapTable[KMR_Phys_Count] = {
    KMR_Remote_LeftShift,   // KMR_Phys_LeftShift
    KMR_Remote_RightShift,  // KMR_Phys_RightShift
    KMR_Remote_LeftControl, // KMR_Phys_LeftControl
    KMR_Remote_RightControl,// KMR_Phys_RightControl
    KMR_Remote_LeftAlt,     // KMR_Phys_LeftOption
    KMR_Remote_RightAlt,    // KMR_Phys_RightOption
    KMR_Remote_LeftMeta,    // KMR_Phys_LeftCommand  -> Win
    KMR_Remote_RightMeta,   // KMR_Phys_RightCommand -> Win
};

// ---------------------------------------------------------------------------
// 2. Public entry points.
// ---------------------------------------------------------------------------

KMR_PhysicalModifier KMR_PhysicalFromKeyCode(unsigned short keyCode) {
    switch (keyCode) {
        case kVK_Shift:       return KMR_Phys_LeftShift;
        case kVK_RightShift:  return KMR_Phys_RightShift;
        case kVK_Control:     return KMR_Phys_LeftControl;
        case kVK_RightControl:return KMR_Phys_RightControl;
        case kVK_Option:      return KMR_Phys_LeftOption;
        case kVK_RightOption: return KMR_Phys_RightOption;
        case kVK_Command:     return KMR_Phys_LeftCommand;
        case kVK_RightCommand:return KMR_Phys_RightCommand;
        default:              return KMR_Phys_Count;
    }
}

KMR_RemoteModifierMask KMR_RemoteMaskForPhysical(KMR_PhysicalModifier phys) {
    if ((unsigned)phys >= KMR_Phys_Count) {
        return 0;
    }
    return s_mapTable[phys];
}

unsigned short KMR_RemoteVKForPhysicalKeyCode(unsigned short keyCode) {
    KMR_PhysicalModifier phys = KMR_PhysicalFromKeyCode(keyCode);
    if (phys == KMR_Phys_Count) {
        return 0;
    }
    KMR_RemoteModifierMask mask = s_mapTable[phys];
    // Invert mask to VK code.
    switch (mask) {
        case KMR_Remote_LeftShift:   return KMR_VK_LSHIFT;
        case KMR_Remote_RightShift:  return KMR_VK_RSHIFT;
        case KMR_Remote_LeftControl: return KMR_VK_LCONTROL;
        case KMR_Remote_RightControl:return KMR_VK_RCONTROL;
        case KMR_Remote_LeftAlt:     return KMR_VK_LALT;
        case KMR_Remote_RightAlt:    return KMR_VK_RALT;
        case KMR_Remote_LeftMeta:    return KMR_VK_LWIN;
        case KMR_Remote_RightMeta:   return KMR_VK_RWIN;
        default:                     return 0;
    }
}

KMR_RemoteModifierMask KMR_RemoteMaskForAppKitFlags(NSEventModifierFlags appKitFlags) {
    KMR_RemoteModifierMask out = 0;
    if (appKitFlags & NSEventModifierFlagShift) {
        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftShift);
    }
    if (appKitFlags & NSEventModifierFlagControl) {
        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftControl);
    }
    if (appKitFlags & NSEventModifierFlagOption) {
        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftOption);
    }
    if (appKitFlags & NSEventModifierFlagCommand) {
        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftCommand);
    }
    return out;
}

// ---------------------------------------------------------------------------
// 3. Diagnostic / self-report helpers.
// ---------------------------------------------------------------------------

const char *KMR_LabelForPhysical(KMR_PhysicalModifier phys) {
    switch (phys) {
        case KMR_Phys_LeftShift:    return "L⇧";
        case KMR_Phys_RightShift:   return "R⇧";
        case KMR_Phys_LeftControl:  return "L⌃";
        case KMR_Phys_RightControl: return "R⌃";
        case KMR_Phys_LeftOption:   return "L⌥";
        case KMR_Phys_RightOption:  return "R⌥";
        case KMR_Phys_LeftCommand:  return "L⌘";
        case KMR_Phys_RightCommand: return "R⌘";
        default:                    return "??";
    }
}

static const char *LabelForRemoteBit(uint8_t bitMask_single) {
    switch (bitMask_single) {
        case KMR_Remote_LeftShift:    return "LShift";
        case KMR_Remote_RightShift:   return "RShift";
        case KMR_Remote_LeftControl:  return "LCtrl";
        case KMR_Remote_RightControl: return "RCtrl";
        case KMR_Remote_LeftAlt:      return "LAlt";
        case KMR_Remote_RightAlt:     return "RAlt";
        case KMR_Remote_LeftMeta:     return "LWin";
        case KMR_Remote_RightMeta:    return "RWin";
        default:                      return "?";
    }
}

void KMR_FormatRemoteMask(KMR_RemoteModifierMask mask, char *buf, size_t bufLen) {
    if (buf == NULL || bufLen == 0) return;
    buf[0] = '\0';
    if (mask == 0) {
        strlcpy(buf, "(none)", bufLen);
        return;
    }
    static const uint8_t order[] = {
        KMR_Remote_LeftShift, KMR_Remote_RightShift,
        KMR_Remote_LeftControl, KMR_Remote_RightControl,
        KMR_Remote_LeftAlt, KMR_Remote_RightAlt,
        KMR_Remote_LeftMeta, KMR_Remote_RightMeta
    };
    int first = 1;
    for (size_t i = 0; i < sizeof(order); i++) {
        if ((mask & order[i]) == 0) continue;
        if (!first) {
            strlcat(buf, "+", bufLen);
        }
        strlcat(buf, LabelForRemoteBit(order[i]), bufLen);
        first = 0;
    }
}

void KMR_LogActiveMapping(void) {
    char maskBuf[32];
    Log(LOG_I, @"[kbmap] ===== KeyboardMapResolver active mapping (Streaming Mode) =====");
    Log(LOG_I, @"[kbmap] %-8s  %-10s  %s", "Phys", "Keycode", "→ Remote Mask");
    Log(LOG_I, @"[kbmap] --------  ----------  ----------------------------");
    for (uint8_t p = 0; p < KMR_Phys_Count; p++) {
        KMR_PhysicalModifier phys = (KMR_PhysicalModifier)p;
        KMR_RemoteModifierMask mask = s_mapTable[phys];
        KMR_FormatRemoteMask(mask, maskBuf, sizeof(maskBuf));

        unsigned short kvk = 0;
        switch (phys) {
            case KMR_Phys_LeftShift:    kvk = kVK_Shift; break;
            case KMR_Phys_RightShift:   kvk = kVK_RightShift; break;
            case KMR_Phys_LeftControl:  kvk = kVK_Control; break;
            case KMR_Phys_RightControl: kvk = kVK_RightControl; break;
            case KMR_Phys_LeftOption:   kvk = kVK_Option; break;
            case KMR_Phys_RightOption:  kvk = kVK_RightOption; break;
            case KMR_Phys_LeftCommand:  kvk = kVK_Command; break;
            case KMR_Phys_RightCommand: kvk = kVK_RightCommand; break;
            default: break;
        }
        unsigned short vk = KMR_RemoteVKForPhysicalKeyCode(kvk);

        Log(LOG_I, @"[kbmap] %-8s  kVK=%03u(0x%02X)  → %s  (VK=0x%02X)",
            KMR_LabelForPhysical(phys),
            (unsigned)kvk, (unsigned)kvk,
            maskBuf,
            (unsigned)vk);
    }
    Log(LOG_I, @"[kbmap] ===== end matrix =====");
}
