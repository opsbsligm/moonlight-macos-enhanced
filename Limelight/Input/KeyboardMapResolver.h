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

// What a physical Command key means on the host. The shipping answer is the Windows key,
// which is the mapping this project chose on purpose (see the header above) and the answer
// Parsec, UU Remote and Steam Link give. One player's next keyboard is the ToDesk-style
// one, where Command is the Control key, and that player cannot get there with a
// translation rule: a rule names one chord, and Command-as-Control has to hold for every
// chord a player might press. So it is one switch, and it is off unless the player says so.
//
// This is NOT the old KeyboardCompatibilityMode list coming back. Nothing here chooses
// between rival tables: the table below is still the only one, and the preference below
// relabels one key inside it.
typedef NS_ENUM(uint8_t, KMR_CommandPreference) {
    KMR_CommandPreferenceWin     = 0,   // the shipping default
    KMR_CommandPreferenceControl = 1,   // "my Command key is my Control key"
};

// The one default, spelled here so a caller that never asks still gets the Windows key.
KMR_CommandPreference KMR_CommandPreferenceDefault(void);

// Convert a macOS kVK_* keycode to KMR_PhysicalModifier.
KMR_PhysicalModifier KMR_PhysicalFromKeyCode(unsigned short keyCode);

// Core mapping functions (now simple, stateless).
//
// Every one of them takes the preference. A player who asked for Control must not get it
// on the keys they type and the Windows key on the shortcuts they bind, so there is no
// single-argument way to ask: the argument-free names below are the ones that answer for a
// player who never opened the switch, and scripts/command-to-control-tests.py refuses a
// keyboard path that calls one of them.
KMR_RemoteModifierMask KMR_RemoteMaskForPhysicalWithCommandPreference(KMR_PhysicalModifier phys,
                                                                      KMR_CommandPreference pref);
unsigned short KMR_RemoteVKForPhysicalKeyCodeWithCommandPreference(unsigned short keyCode,
                                                                   KMR_CommandPreference pref);
KMR_RemoteModifierMask KMR_RemoteMaskForAppKitFlagsWithCommandPreference(NSEventModifierFlags appKitFlags,
                                                                         KMR_CommandPreference pref);

// The same three answers for the player who never touched the switch.
KMR_RemoteModifierMask KMR_RemoteMaskForPhysical(KMR_PhysicalModifier phys);
unsigned short KMR_RemoteVKForPhysicalKeyCode(unsigned short keyCode);
KMR_RemoteModifierMask KMR_RemoteMaskForAppKitFlags(NSEventModifierFlags appKitFlags);

// ---------------------------------------------------------------------------
// Diagnostic / self-report interface.
// ---------------------------------------------------------------------------
void KMR_LogActiveMapping(KMR_CommandPreference pref);
const char *KMR_LabelForPhysical(KMR_PhysicalModifier phys);
void KMR_FormatRemoteMask(KMR_RemoteModifierMask mask, char *buf, size_t bufLen);

#ifdef __cplusplus
}
#endif

#endif /* KeyboardMapResolver_h */
