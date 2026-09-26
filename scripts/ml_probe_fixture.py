"""Shared fixture for the hand-written probes that drive the shipping keyboard edges.

    Why this file exists: keyDown: and -settleHeldKeyboardPresses reach for the stray-click state
    (the press a 2.4G receiver sent as a keyboard usage instead of the left button it was). Every
    probe that lifts those methods out of HIDSupport.m therefore has to carry that state, and a
    probe that invents its own copy of the guard windows can pass while the shipping rule changed.
    The windows here are only defaults for probes that never measure them; key-state-heal-tests.py
    lifts the shipped numbers and the shipped candidate rule verbatim and is the harness that pins
    the behaviour. docs/memory-ownership.md S36.
"""

STATE_TEMPLATE = """
// Injected by ml_probe_fixture.py: the state the shipping keyDown: and settle loop write.
@interface {cls} ()
@property (nonatomic) uint64_t lastTypedOtherKeyDownAtMs;
@property (nonatomic) uint64_t lastStrayClickAtMs;
@property (nonatomic, copy) BOOL (^strayKeyPressHandler)(unsigned short physicalKeyCode,
                                                        uint64_t ageMs);
@end
"""

KEY_CODE = """
// Injected by ml_probe_fixture.py: the key the leak arrives as.
enum {{ kVK_ANSI_C = 8 }};
"""

CANDIDATE = """
// Injected by ml_probe_fixture.py: which denied press may stand for a click. The harness that
// measures this behaviour lifts the shipped rule verbatim instead.
static BOOL HIDKeyCodeIsStrayClickCandidate(unsigned short physicalKeyCode) {{
    return physicalKeyCode == kVK_ANSI_C;
}}
"""

WINDOWS = """
// Injected by ml_probe_fixture.py: the shipped guard windows for probes that do not lift them.
// key-state-heal-tests.py lifts the real numbers and is the harness that pins them.
static uint64_t const HIDStrayClickTypingWindowMs = 1500;
static uint64_t const HIDStrayClickMinIntervalMs = 200;
"""

DETECTABLE = """
// Injected by ml_probe_fixture.py because this probe drives keyDown: without lifting the region
// rule itself; key-state-heal-tests.py is the harness that carries the shipped text verbatim.
static BOOL HIDWireCodeIsKeyStateDetectable(short wireCode) {{
    short vk = (short)(wireCode & 0xFF);
    if (vk >= 0x41 && vk <= 0x5A) {{ return YES; }}
    if (vk >= 0x30 && vk <= 0x39) {{ return YES; }}
    if (vk >= 0x60 && vk <= 0x69) {{ return YES; }}
    switch (vk) {{
        case 0x08: case 0x09: case 0x0D: case 0x1B: case 0x20:
        case 0xBA: case 0xBB: case 0xBC: case 0xBD:
        case 0xBE: case 0xBF: case 0xC0:
        case 0xDB: case 0xDC: case 0xDD: case 0xDE:
            return YES;
        default:
            return NO;
    }}
}}
"""


def apply(source):
    """Give a probe the stray-click state its lifted methods write, without touching the probe."""
    marker = "lastTypedOtherKeyDownAtMs"
    if marker not in source:
        return source

    at = source.find(marker)
    implementation = source.rfind("@implementation ", 0, at)
    if implementation < 0:
        raise SystemExit("ml_probe_fixture: no @implementation owns the keyboard edges")
    cls = source[implementation + len("@implementation "):].split()[0].rstrip("{").strip()

    # Some probes import Carbon and get the key codes for free; some lift the shipped keys[] table
    # and arrive at the name with no definition behind it. Only the second group needs the enum.
    defines_key_codes = ("kVK_ANSI_C = " in source) or ("<Carbon/" in source) or ("Carbon/Carbon.h" in source)
    prefix = ""
    if not defines_key_codes:
        prefix += KEY_CODE.format()
    if "static BOOL HIDKeyCodeIsStrayClickCandidate(" not in source:
        if not defines_key_codes and "kVK_ANSI_C = " not in prefix:
            prefix += KEY_CODE.format()
        prefix += CANDIDATE.format()
    if "HIDStrayClickTypingWindowMs" not in source:
        prefix += WINDOWS.format()
    if "static BOOL HIDWireCodeIsKeyStateDetectable(" not in source:
        prefix += DETECTABLE.format()

    # A class extension belongs after the class's own @interface (a second @interface for a class
    # the file already declared is an error, and before the imports nothing knows uint64_t), so it
    # lands on the @end that closes that interface.
    declaration = source.find("@interface " + cls)
    if declaration < 0:
        raise SystemExit("ml_probe_fixture: the probe declares no @interface for " + cls)
    close = source.find("\n@end", declaration)
    if close < 0 or implementation < close:
        raise SystemExit("ml_probe_fixture: cannot find where %s's interface ends" % cls)
    insert_at = close + len("\n@end")
    block = prefix + STATE_TEMPLATE.format(cls=cls)
    return source[:insert_at] + block + source[insert_at:]
