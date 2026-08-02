//
//  KeyboardMapResolver.h
//  Moonlight for macOS
//
//  Keyboard Compatibility Layer - Single Source of Truth (Simplified for Streaming).
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
//  =================================================================
//  We have REMOVED all legacy mapping modes (CommandToControl, Swap,
//  MoonlightClassic, Hybrid, etc.) because they were the primary source
//  of repeated regressions (e.g. double-click sending Win key, Ctrl
//  mapped incorrectly).
//
//  This module now implements the INDUSTRY STANDARD for game streaming
//  software (Parsec, UU Remote, Steam Link, etc.):
//
//  CORE PRINCIPLE:
//  The physical macOS modifiers map DIRECTLY and unambiguously to their
//  logical Windows HID equivalents. There is NO "smart" or "deferred"
//  logic that can cause a double-click to accidentally send a Win key.
//
//  Final, Simplified Mapping:
//    macOS Command (⌘)   ->  Windows Left/Right Win Key (VK_LWIN/VK_RWIN)
//    macOS Control (⌃)  ->  Windows Left/Right Ctrl Key (VK_LCONTROL/VK_RCONTROL)
//    macOS Option  (⌥)  ->  Windows Left/Right Alt Key (VK_LALT/VK_RALT)
//    macOS Shift   (⇧)  ->  Windows Left/Right Shift Key (VK_LSHIFT/VK_RSHIFT)
//  =================================================================
//

#ifndef KeyboardMapResolver_h
#define KeyboardMapResolver_h

#import <Foundation/Foundation.h>
#import <Carbon/Carbon.h>   // kVK_* codes

#ifdef __cplusplus
extern "C" {
#endif

// ---------------------------------------------------------------------------
// Windows HID modifier remote masks (aligned with HIDSupport definitions).
// ---------------------------------------------------------------------------
enum {
    KMR_Remote_LeftShift   = 1 << 0,
    KMR_Remote_RightShift  = 1 << 1,
    KMR_Remote_LeftControl = 1 << 2,
    KMR_Remote_RightControl= 1 << 3,
    KMR_Remote_LeftAlt     = 1 << 4,
    KMR_Remote_RightAlt    = 1 << 5,
    KMR_Remote_LeftMeta    = 1 << 6,
    KMR_Remote_RightMeta   = 1 << 7,
};
typedef uint8_t KMR_RemoteModifierMask;

// ---------------------------------------------------------------------------
// Windows HID modifier USB keycodes (VK codes).
// ---------------------------------------------------------------------------
enum {
    KMR_VK_LSHIFT   = 0xA0,
    KMR_VK_RSHIFT   = 0xA1,
    KMR_VK_LCONTROL = 0xA2,
    KMR_VK_RCONTROL = 0xA3,
    KMR_VK_LALT     = 0xA4,
    KMR_VK_RALT     = 0xA5,
    KMR_VK_LWIN     = 0x5B,
    KMR_VK_RWIN     = 0x5C,
};

// ---------------------------------------------------------------------------
// Physical macOS modifier codes.
// ---------------------------------------------------------------------------
typedef NS_ENUM(uint8_t, KMR_PhysicalModifier) {
    KMR_Phys_LeftShift = 0,
    KMR_Phys_RightShift,
    KMR_Phys_LeftControl,
    KMR_Phys_RightControl,
    KMR_Phys_LeftOption,
    KMR_Phys_RightOption,
    KMR_Phys_LeftCommand,
    KMR_Phys_RightCommand,
    KMR_Phys_Count,
};

// Convert a macOS kVK_* keycode to KMR_PhysicalModifier.
KMR_PhysicalModifier KMR_PhysicalFromKeyCode(unsigned short keyCode);

// Core mapping functions (now simple, stateless).
KMR_RemoteModifierMask KMR_RemoteMaskForPhysical(KMR_PhysicalModifier phys);
unsigned short KMR_RemoteVKForPhysicalKeyCode(unsigned short keyCode);

// Convenience: Convert NSEventModifierFlags to remote mask.
KMR_RemoteModifierMask KMR_RemoteMaskForAppKitFlags(NSEventModifierFlags appKitFlags);

// ---------------------------------------------------------------------------
// Diagnostic / self-report interface.
// ---------------------------------------------------------------------------
void KMR_LogActiveMapping(void);
const char *KMR_LabelForPhysical(KMR_PhysicalModifier phys);
void KMR_FormatRemoteMask(KMR_RemoteModifierMask mask, char *buf, size_t bufLen);

#ifdef __cplusplus
}
#endif

#endif /* KeyboardMapResolver_h */
