"""Minimal non-behavioral declarations shared by extracted keyboard probes.

State transitions are always extracted from shipping code. Probes that do not
exercise device attribution leave its dependency nil; key-state-heal-tests.py
supplies a controlled monitor and verifies attribution separately.
"""
import re

QUIRK_DECL = """
@interface HIDKeyboardQuirkFilter : NSObject
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
@end
"""


def apply(source):
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
