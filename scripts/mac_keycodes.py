#!/usr/bin/env python3
"""The macOS virtual key codes the keyboard mapping table has to answer for.

Generated from the SDK header Carbon HIToolbox/Events.h, whose values have been
frozen since the 1990s because applications hardcode them:

    grep -E "^ *kVK_[A-Za-z0-9_]+ += +0x" \\
      $(xcrun --sdk macosx --show-sdk-path)/System/Library/Frameworks/ \\
      Carbon.framework/Versions/A/Frameworks/HIToolbox.framework/Versions/A/ \\
      Headers/Events.h

The table lives here rather than being read from an SDK because the audit job
runs on a Linux runner that has no Apple headers, and the set of codes a game can
bind is a fact the audit has to be able to state on its own.

"""
KVK_CODES = {'kVK_ANSI_0': 29, 'kVK_ANSI_1': 18, 'kVK_ANSI_2': 19, 'kVK_ANSI_3': 20, 'kVK_ANSI_4': 21, 'kVK_ANSI_5': 23, 'kVK_ANSI_6': 22, 'kVK_ANSI_7': 26, 'kVK_ANSI_8': 28, 'kVK_ANSI_9': 25, 'kVK_ANSI_A': 0, 'kVK_ANSI_B': 11, 'kVK_ANSI_Backslash': 42, 'kVK_ANSI_C': 8, 'kVK_ANSI_Comma': 43, 'kVK_ANSI_D': 2, 'kVK_ANSI_E': 14, 'kVK_ANSI_Equal': 24, 'kVK_ANSI_F': 3, 'kVK_ANSI_G': 5, 'kVK_ANSI_Grave': 50, 'kVK_ANSI_H': 4, 'kVK_ANSI_I': 34, 'kVK_ANSI_J': 38, 'kVK_ANSI_K': 40, 'kVK_ANSI_Keypad0': 82, 'kVK_ANSI_Keypad1': 83, 'kVK_ANSI_Keypad2': 84, 'kVK_ANSI_Keypad3': 85, 'kVK_ANSI_Keypad4': 86, 'kVK_ANSI_Keypad5': 87, 'kVK_ANSI_Keypad6': 88, 'kVK_ANSI_Keypad7': 89, 'kVK_ANSI_Keypad8': 91, 'kVK_ANSI_Keypad9': 92, 'kVK_ANSI_KeypadClear': 71, 'kVK_ANSI_KeypadDecimal': 65, 'kVK_ANSI_KeypadDivide': 75, 'kVK_ANSI_KeypadEnter': 76, 'kVK_ANSI_KeypadEquals': 81, 'kVK_ANSI_KeypadMinus': 78, 'kVK_ANSI_KeypadMultiply': 67, 'kVK_ANSI_KeypadPlus': 69, 'kVK_ANSI_L': 37, 'kVK_ANSI_LeftBracket': 33, 'kVK_ANSI_M': 46, 'kVK_ANSI_Minus': 27, 'kVK_ANSI_N': 45, 'kVK_ANSI_O': 31, 'kVK_ANSI_P': 35, 'kVK_ANSI_Period': 47, 'kVK_ANSI_Q': 12, 'kVK_ANSI_Quote': 39, 'kVK_ANSI_R': 15, 'kVK_ANSI_RightBracket': 30, 'kVK_ANSI_S': 1, 'kVK_ANSI_Semicolon': 41, 'kVK_ANSI_Slash': 44, 'kVK_ANSI_T': 17, 'kVK_ANSI_U': 32, 'kVK_ANSI_V': 9, 'kVK_ANSI_W': 13, 'kVK_ANSI_X': 7, 'kVK_ANSI_Y': 16, 'kVK_ANSI_Z': 6, 'kVK_CapsLock': 57, 'kVK_Command': 55, 'kVK_ContextualMenu': 110, 'kVK_Control': 59, 'kVK_Delete': 51, 'kVK_DownArrow': 125, 'kVK_End': 119, 'kVK_Escape': 53, 'kVK_F1': 122, 'kVK_F10': 109, 'kVK_F11': 103, 'kVK_F12': 111, 'kVK_F13': 105, 'kVK_F14': 107, 'kVK_F15': 113, 'kVK_F16': 106, 'kVK_F17': 64, 'kVK_F18': 79, 'kVK_F19': 80, 'kVK_F2': 120, 'kVK_F20': 90, 'kVK_F3': 99, 'kVK_F4': 118, 'kVK_F5': 96, 'kVK_F6': 97, 'kVK_F7': 98, 'kVK_F8': 100, 'kVK_F9': 101, 'kVK_ForwardDelete': 117, 'kVK_Function': 63, 'kVK_Help': 114, 'kVK_Home': 115, 'kVK_ISO_Section': 10, 'kVK_JIS_Eisu': 102, 'kVK_JIS_Kana': 104, 'kVK_JIS_KeypadComma': 95, 'kVK_JIS_Underscore': 94, 'kVK_JIS_Yen': 93, 'kVK_LeftArrow': 123, 'kVK_Mute': 74, 'kVK_Option': 58, 'kVK_PageDown': 121, 'kVK_PageUp': 116, 'kVK_Return': 36, 'kVK_RightArrow': 124, 'kVK_RightCommand': 54, 'kVK_RightControl': 62, 'kVK_RightOption': 61, 'kVK_RightShift': 60, 'kVK_Shift': 56, 'kVK_Space': 49, 'kVK_Tab': 48, 'kVK_UpArrow': 126, 'kVK_VolumeDown': 73, 'kVK_VolumeUp': 72}

REQUIRED_MAPPED_KEYS = ["kVK_ANSI_A", "kVK_ANSI_B", "kVK_ANSI_C", "kVK_ANSI_D", "kVK_ANSI_E", "kVK_ANSI_F", "kVK_ANSI_G", "kVK_ANSI_H", "kVK_ANSI_I", "kVK_ANSI_J", "kVK_ANSI_K", "kVK_ANSI_L", "kVK_ANSI_M", "kVK_ANSI_N", "kVK_ANSI_O", "kVK_ANSI_P", "kVK_ANSI_Q", "kVK_ANSI_R", "kVK_ANSI_S", "kVK_ANSI_T", "kVK_ANSI_U", "kVK_ANSI_V", "kVK_ANSI_W", "kVK_ANSI_X", "kVK_ANSI_Y", "kVK_ANSI_Z", "kVK_ANSI_0", "kVK_ANSI_1", "kVK_ANSI_2", "kVK_ANSI_3", "kVK_ANSI_4", "kVK_ANSI_5", "kVK_ANSI_6", "kVK_ANSI_7", "kVK_ANSI_8", "kVK_ANSI_9", "kVK_Space", "kVK_Return", "kVK_Delete", "kVK_Tab", "kVK_Escape", "kVK_LeftArrow", "kVK_RightArrow", "kVK_DownArrow", "kVK_UpArrow", "kVK_Home", "kVK_End", "kVK_PageUp", "kVK_PageDown", "kVK_ANSI_Keypad0", "kVK_ANSI_Keypad1", "kVK_ANSI_Keypad2", "kVK_ANSI_Keypad3", "kVK_ANSI_Keypad4", "kVK_ANSI_Keypad5", "kVK_ANSI_Keypad6", "kVK_ANSI_Keypad7", "kVK_ANSI_Keypad8", "kVK_ANSI_Keypad9", "kVK_ANSI_KeypadDecimal", "kVK_ANSI_KeypadMultiply", "kVK_ANSI_KeypadPlus", "kVK_ANSI_KeypadClear", "kVK_ANSI_KeypadDivide", "kVK_ANSI_KeypadEnter", "kVK_ANSI_KeypadMinus", "kVK_Shift", "kVK_RightShift", "kVK_Control", "kVK_RightControl", "kVK_Option", "kVK_RightOption", "kVK_Command", "kVK_RightCommand", "kVK_F1", "kVK_F2", "kVK_F3", "kVK_F4", "kVK_F5", "kVK_F6", "kVK_F7", "kVK_F8", "kVK_F9", "kVK_F10", "kVK_F11", "kVK_F12"]


# Every SDK virtual key code that has no row in the mapping table, with the reason.
#
# A missing row and an overlooked row look identical in the table, so the ignore
# path in keyDown: is only honest while this list accounts for every gap. The audit
# fails if a code disappears from the table without appearing here, and if a row is
# added here without being removed from here.
UNMAPPED_BY_CHOICE = {
    "kVK_Function": ("the Fn key is reported as a modifier flag rather than a key "
                     "event, and Windows has no virtual key for it"),
    "kVK_JIS_Yen": ("the PC equivalent is not settled: guessing types a different "
                    "character on the host, and the host has no key that is the Mac "
                    "yen key"),
    "kVK_JIS_Underscore": ("shares a physical key with another code on the PC side, "
                           "so forwarding it would double a key the table already "
                           "sends"),
    "kVK_JIS_KeypadComma": ("a JIS numpad punctuation key with no Windows virtual "
                            "key; the numpad decimal separator already reaches the "
                            "host"),
    "kVK_JIS_Eisu": ("the closest Windows keys are the input method mode keys, which "
                     "switch the host IME instead of typing; a wrong guess changes "
                     "the host's input method mid-game"),
    "kVK_JIS_Kana": ("same as kVK_JIS_Eisu: the candidates change the host input "
                     "method rather than type a character"),
}


# The Windows virtual key codes the host is allowed to be told about.
#
# The mapping table sends Win32 VK codes, and the host turns a code it does not know into nothing at
# all: an entry that points at a reserved value is a key that silently does nothing on the far side,
# indistinguishable from a missing row while the app reports the press as sent. So every value the
# table carries is checked against this set.
#
# Generated from Microsoft's "Virtual Key Codes" reference, whose table names each code and marks the
# gaps Reserved or Unassigned:
#
#     curl -sL "https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes"
#
# then, per table row, the name, the hex column, and the description, keeping only the rows with a
# name and a description that does not say reserved or unassigned. The page numbers both the OEM keys
# the Mac keyboard reaches (0xE2 VK_OEM_102, 0xFE VK_OEM_CLEAR) and the whole F13-F24 row, so a value
# that looks exotic is not automatically wrong - 0xFE looked like a typo for NumLock during the 2026-09
# review and turned out to be VK_OEM_CLEAR, the Clear key the Mac keypad actually has.
WINDOWS_VK_DEFINED = {
    0x01: "VK_LBUTTON", 0x02: "VK_RBUTTON", 0x03: "VK_CANCEL", 0x04: "VK_MBUTTON",
    0x05: "VK_XBUTTON1", 0x06: "VK_XBUTTON2", 0x08: "VK_BACK", 0x09: "VK_TAB", 0x0C: "VK_CLEAR",
    0x0D: "VK_RETURN", 0x10: "VK_SHIFT", 0x11: "VK_CONTROL", 0x12: "VK_MENU", 0x13: "VK_PAUSE",
    0x14: "VK_CAPITAL", 0x15: "VK_HANGUL", 0x16: "VK_IME_ON", 0x17: "VK_JUNJA", 0x18: "VK_FINAL",
    0x19: "VK_KANJI", 0x1A: "VK_IME_OFF", 0x1B: "VK_ESCAPE", 0x1C: "VK_CONVERT",
    0x1D: "VK_NONCONVERT", 0x1E: "VK_ACCEPT", 0x1F: "VK_MODECHANGE", 0x20: "VK_SPACE",
    0x21: "VK_PRIOR", 0x22: "VK_NEXT", 0x23: "VK_END", 0x24: "VK_HOME", 0x25: "VK_LEFT",
    0x26: "VK_UP", 0x27: "VK_RIGHT", 0x28: "VK_DOWN", 0x29: "VK_SELECT", 0x2A: "VK_PRINT",
    0x2B: "VK_EXECUTE", 0x2C: "VK_SNAPSHOT", 0x2D: "VK_INSERT", 0x2E: "VK_DELETE", 0x2F: "VK_HELP",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4", 0x35: "5", 0x36: "6", 0x37: "7",
    0x38: "8", 0x39: "9", 0x41: "A", 0x42: "B", 0x43: "C", 0x44: "D", 0x45: "E", 0x46: "F",
    0x47: "G", 0x48: "H", 0x49: "I", 0x4A: "J", 0x4B: "K", 0x4C: "L", 0x4D: "M", 0x4E: "N",
    0x4F: "O", 0x50: "P", 0x51: "Q", 0x52: "R", 0x53: "S", 0x54: "T", 0x55: "U", 0x56: "V",
    0x57: "W", 0x58: "X", 0x59: "Y", 0x5A: "Z", 0x5B: "VK_LWIN", 0x5C: "VK_RWIN", 0x5D: "VK_APPS",
    0x5F: "VK_SLEEP", 0x60: "VK_NUMPAD0", 0x61: "VK_NUMPAD1", 0x62: "VK_NUMPAD2",
    0x63: "VK_NUMPAD3", 0x64: "VK_NUMPAD4", 0x65: "VK_NUMPAD5", 0x66: "VK_NUMPAD6",
    0x67: "VK_NUMPAD7", 0x68: "VK_NUMPAD8", 0x69: "VK_NUMPAD9", 0x6A: "VK_MULTIPLY",
    0x6B: "VK_ADD", 0x6C: "VK_SEPARATOR", 0x6D: "VK_SUBTRACT", 0x6E: "VK_DECIMAL",
    0x6F: "VK_DIVIDE", 0x70: "VK_F1", 0x71: "VK_F2", 0x72: "VK_F3", 0x73: "VK_F4", 0x74: "VK_F5",
    0x75: "VK_F6", 0x76: "VK_F7", 0x77: "VK_F8", 0x78: "VK_F9", 0x79: "VK_F10", 0x7A: "VK_F11",
    0x7B: "VK_F12", 0x7C: "VK_F13", 0x7D: "VK_F14", 0x7E: "VK_F15", 0x7F: "VK_F16", 0x80: "VK_F17",
    0x81: "VK_F18", 0x82: "VK_F19", 0x83: "VK_F20", 0x84: "VK_F21", 0x85: "VK_F22", 0x86: "VK_F23",
    0x87: "VK_F24", 0x90: "VK_NUMLOCK", 0x91: "VK_SCROLL", 0xA0: "VK_LSHIFT", 0xA1: "VK_RSHIFT",
    0xA2: "VK_LCONTROL", 0xA3: "VK_RCONTROL", 0xA4: "VK_LMENU", 0xA5: "VK_RMENU",
    0xA6: "VK_BROWSER_BACK", 0xA7: "VK_BROWSER_FORWARD", 0xA8: "VK_BROWSER_REFRESH",
    0xA9: "VK_BROWSER_STOP", 0xAA: "VK_BROWSER_SEARCH", 0xAB: "VK_BROWSER_FAVORITES",
    0xAC: "VK_BROWSER_HOME", 0xAD: "VK_VOLUME_MUTE", 0xAE: "VK_VOLUME_DOWN", 0xAF: "VK_VOLUME_UP",
    0xB0: "VK_MEDIA_NEXT_TRACK", 0xB1: "VK_MEDIA_PREV_TRACK", 0xB2: "VK_MEDIA_STOP",
    0xB3: "VK_MEDIA_PLAY_PAUSE", 0xB4: "VK_LAUNCH_MAIL", 0xB5: "VK_LAUNCH_MEDIA_SELECT",
    0xB6: "VK_LAUNCH_APP1", 0xB7: "VK_LAUNCH_APP2", 0xBA: "VK_OEM_1", 0xBB: "VK_OEM_PLUS",
    0xBC: "VK_OEM_COMMA", 0xBD: "VK_OEM_MINUS", 0xBE: "VK_OEM_PERIOD", 0xBF: "VK_OEM_2",
    0xC0: "VK_OEM_3", 0xC3: "VK_GAMEPAD_A", 0xC4: "VK_GAMEPAD_B", 0xC5: "VK_GAMEPAD_X",
    0xC6: "VK_GAMEPAD_Y", 0xC7: "VK_GAMEPAD_RIGHT_SHOULDER", 0xC8: "VK_GAMEPAD_LEFT_SHOULDER",
    0xC9: "VK_GAMEPAD_LEFT_TRIGGER", 0xCA: "VK_GAMEPAD_RIGHT_TRIGGER", 0xCB: "VK_GAMEPAD_DPAD_UP",
    0xCC: "VK_GAMEPAD_DPAD_DOWN", 0xCD: "VK_GAMEPAD_DPAD_LEFT", 0xCE: "VK_GAMEPAD_DPAD_RIGHT",
    0xCF: "VK_GAMEPAD_MENU", 0xD0: "VK_GAMEPAD_VIEW", 0xD1: "VK_GAMEPAD_LEFT_THUMBSTICK_BUTTON",
    0xD2: "VK_GAMEPAD_RIGHT_THUMBSTICK_BUTTON", 0xD3: "VK_GAMEPAD_LEFT_THUMBSTICK_UP",
    0xD4: "VK_GAMEPAD_LEFT_THUMBSTICK_DOWN", 0xD5: "VK_GAMEPAD_LEFT_THUMBSTICK_RIGHT",
    0xD6: "VK_GAMEPAD_LEFT_THUMBSTICK_LEFT", 0xD7: "VK_GAMEPAD_RIGHT_THUMBSTICK_UP",
    0xD8: "VK_GAMEPAD_RIGHT_THUMBSTICK_DOWN", 0xD9: "VK_GAMEPAD_RIGHT_THUMBSTICK_RIGHT",
    0xDA: "VK_GAMEPAD_RIGHT_THUMBSTICK_LEFT", 0xDB: "VK_OEM_4", 0xDC: "VK_OEM_5", 0xDD: "VK_OEM_6",
    0xDE: "VK_OEM_7", 0xDF: "VK_OEM_8", 0xE2: "VK_OEM_102", 0xE5: "VK_PROCESSKEY",
    0xE7: "VK_PACKET", 0xF6: "VK_ATTN", 0xF7: "VK_CRSEL", 0xF8: "VK_EXSEL", 0xF9: "VK_EREOF",
    0xFA: "VK_PLAY", 0xFB: "VK_ZOOM", 0xFD: "VK_PA1", 0xFE: "VK_OEM_CLEAR",
}

# Physical keys that legitimately share one host code, because the PC has fewer codes than the Mac
# has keys. Without this note the duplicate looks like a copy-paste error and someone "fixes" it by
# inventing a code the page above does not define.
INTENDED_DUPLICATE_HOST_CODES = {
    0xBB: ("kVK_ANSI_Equal", "kVK_ANSI_KeypadEquals"),
    0x0D: ("kVK_Return", "kVK_ANSI_KeypadEnter"),
}
