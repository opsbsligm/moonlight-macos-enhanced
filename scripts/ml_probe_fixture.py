"""Minimal non-behavioral declarations shared by extracted keyboard probes.

State transitions are always extracted from shipping code. Probes that do not
exercise device attribution leave its dependency nil; key-state-heal-tests.py
supplies a controlled monitor and verifies attribution separately.
"""
import re
from pathlib import Path

QUIRK_DECL = """
@interface HIDKeyboardQuirkFilter : NSObject
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
@end
"""


def apply(source):
    # The local-IME hooks read a session the probe does not own: nil session means
    # the real key path, and flush is a no-op until capture starts one.
    if "self.imeSession" in source or "[self flushIMECommit]" in source:
        if "@interface MLLocalIMESession" not in source:
            # The extracted key methods send handleEvent: through the session,
            # so a forward declaration is not enough.
            at = source.find("@interface ")
            source = source[:at] + (
                "@interface MLLocalIMESession : NSObject\n"
                "@property (nonatomic, strong) NSTextInputContext *context;\n"
                "@end\n"
            ) + source[at:]

        def ime_interface(match):
            block = match.group(0)
            if ("keyDown:" in block or "keyboardForwardedKeyDownKeyCodes" in block) \
                    and "imeSession" not in block:
                block = block.replace("@end",
                                      "@property (nonatomic, strong) MLLocalIMESession *imeSession;\n@end")
            return block

        source = re.sub(r"@interface\s+([A-Za-z_]\w*)\s*:\s*NSObject\b"
                        r"(?:(?!@end).)*?@end",
                        ime_interface, source, flags=re.S)

        # The extracted key methods call flushIMECommit, so every probe class the
        # session landed on needs the selector declared: a private extension after
        # each such interface. The session being nil means no IME is active, so a
        # no-op definition is behaviorally identical to the shipping one.
        if "@class MLLocalIMESession;" not in source and "@interface MLLocalIMESession" not in source:
            at = source.find("@interface ")
            source = source[:at] + "@class MLLocalIMESession;\n" + source[at:]
        extended = set()
        for probe in re.finditer(
                r"@interface\s+([A-Za-z_]\w*)\s*:\s*NSObject\b"
                r"(?:(?!@end).)*?(?:keyDown:|keyboardForwardedKeyDownKeyCodes)"
                r"(?:(?!@end).)*?imeSession(?:(?!@end).)*?@end",
                source, flags=re.S):
            cls = probe.group(1)
            if re.search(r"flushIMECommit;", probe.group(0)):
                continue
            ins = ("\n@interface %s ()\n"
                   "- (void)flushIMECommit;\n"
                   "- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event;\n"
                   "@end\n" % cls)
            source = (source[:probe.end()] + ins + source[probe.end():])
            extended.add(cls)
        # The session being nil means no IME is active, so the no-op definition is
        # behaviorally identical to the shipping one.
        for m in re.finditer(r"@implementation\s+([A-Za-z_]\w*)\b(?!\s*\()", source):
            if m.group(1) not in extended:
                continue
            impl_end = source.index("@end", m.end())
            body = source[m.start():impl_end]
            if not re.search(r"^-\s*\(void\)\s*flushIMECommit\b", body, flags=re.M):
                source = (source[:m.end()]
                          + "\n- (void)flushIMECommit {}\n" + source[m.end():])

    if "HIDUnicodeTextForEvent(event)" in source:
        header = Path(__file__).resolve().parents[1] / "Limelight/Input/KeyboardTextRouting.h"
        source = '#import "' + str(header) + '"\n' + source
        at = source.index("@interface ")
        # Existing keyboard probes exercise the wire route. A text send in
        # those scenarios is a regression rather than a silently ignored call.
        source = source[:at] + """
static int LiSendUtf8TextEventCtx(void *ctx, const char *text, unsigned int length) {
    (void)ctx; (void)text; (void)length; abort();
}
""" + source[at:]
    if "HIDAcquireInputContext(" in source and "} HIDInputLease;" not in source:
        lease = """
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
static HIDInputLease HIDAcquireInputContext(id support) {
    return (HIDInputLease){ HIDInputContext(support), 1 };
}
"""
        at = source.index("static void HIDDispatchInput(")
        source = source[:at] + lease + source[at:]
        source = source.replace("static void HIDDispatchInput(id support, PML_INPUT_STREAM_CONTEXT ctx,",
                                "static void HIDDispatchInput(id support, HIDInputLease lease,")
    if "self.keyboardQuirkFilter" not in source and "self.keyboardHeldUnconfirmedKeyDowns" not in source:
        return source
    if "@interface HIDKeyboardQuirkFilter" not in source:
        # Foundation/AppKit has already been imported before the first declaration.
        at = source.find("@interface ")
        source = source[:at] + QUIRK_DECL + source[at:]

    def augment(match):
        block = match.group(0)
        if "keyboardForwardedKeyDownKeyCodes" in block:
            fields = {
                "keyboardHeldUnconfirmedKeyDowns": "NSMutableDictionary<NSNumber *, NSDictionary *> *",
                "keyboardQuirkFilter": "HIDKeyboardQuirkFilter *",
                "keyboardCapsLockState": "NSNumber *",
            }
            for field, typ in fields.items():
                if field not in block:
                    block = block.replace("@end", "@property (nonatomic, strong) " + typ + field + ";\n@end")
        if "keyCode" in block and "NSEventType type" in block:
            for field, typ in (("timestamp", "NSTimeInterval"), ("isARepeat", "BOOL")):
                if field not in block:
                    block = block.replace("@end", "@property (nonatomic) " + typ + " " + field + ";\n@end")
        return block

    return re.sub(r"@interface\s+\w+.*?@end", augment, source, flags=re.S)
