#!/usr/bin/env python3
"""Read-only recorder: which local HID device can claim it typed a key.

A phantom key that arrives without a release is not always this app's doing, and
the way to see that is to ask the machine which keyboards exist at all. This
needs no Input Monitoring grant, because IORegistry carries each device's HID
Report Descriptor: the descriptor says whether a device that presents itself as a
mouse also declares a keyboard collection, and whether a key state is sent as a
six-entry key array or as one bit per key. Both facts change what a "key press
with no key release" means, and neither is visible from NSEvent.

Usage:  python3 scripts/hid-topology.py [--keys kVK[,kVK...]]
"""
import argparse
import re
import subprocess
import sys

GLOBAL = {0: "UsagePage", 1: "LogicalMin", 2: "LogicalMax", 3: "PhysMin", 4: "PhysMax",
          5: "UnitExp", 6: "Unit", 7: "ReportSize", 8: "ReportID", 9: "ReportCount",
          10: "Push", 11: "Pop"}
LOCAL = {0: "Usage", 1: "UsageMin", 2: "UsageMax"}
MAIN = {8: "Input", 9: "Output", 10: "Collection", 11: "Feature", 12: "EndCollection"}
USAGE_PAGE = {0x01: "GenericDesktop", 0x07: "Keyboard/Keypad", 0x08: "LED",
              0x0C: "Consumer", 0x80: "Sleep", 0x8C: "BarCode"}
# kVK -> Keyboard/Keypad usage. Only the letters this bug has been about.
VK_TO_USAGE = {0x0B: 0x04, 0x08: 0x06, 0x15: 0x0D}


def items(blob):
    """Yield (kind, tag, value) for every short item of a HID Report Descriptor."""
    i = 0
    while i < len(blob):
        head = blob[i]
        size = head & 0x03
        size = 0 if size == 0 else (4 if size == 3 else size)
        value = int.from_bytes(blob[i + 1:i + 1 + size], "little") if size else 0
        yield head & 0x0C, (head >> 4) & 0x0F, value
        i += 1 + size


def analyse(blob):
    """Return the collections and the per-Report-ID input fields of one descriptor."""
    page = 0
    usage = None
    report_id = None
    size = count = 0
    collections, fields = [], []
    depth = 0
    for head in items(blob):
        kind, tag, value = head
        if kind == 0x00:
            name = MAIN.get(tag)
            if name == "EndCollection":
                depth = max(0, depth - 1)
            elif name == "Collection":
                collections.append((depth, value, page, usage))
                depth += 1
            elif name in ("Input", "Output", "Feature"):
                fields.append((name, report_id, page, usage, size, count))
        elif kind == 0x04:
            field = GLOBAL.get(tag)
            if field == "UsagePage":
                page = value
            elif field == "ReportID":
                report_id = value
            elif field == "ReportSize":
                size = value
            elif field == "ReportCount":
                count = value
        elif kind == 0x08 and LOCAL.get(tag) == "Usage":
            usage = value if tag == 0 else None
    return collections, fields


def keyboard_reports(collections, fields):
    """Report IDs that carry Keyboard/Keypad input, and how wide their key state is."""
    out = {}
    for direction, report_id, page, _usage, size, count in fields:
        if direction != "Input" or page != 0x07:
            continue
        # A key array is 8 bits wide with a small count; one bit per key is the
        # bitmap form, where the count is the number of keys, not the number of slots.
        shape = "key array" if size == 8 and count <= 16 else "bitmap of %d keys" % count
        out.setdefault(report_id, []).append(shape)
    return out


def devices():
    listing = subprocess.run(["ioreg", "-c", "IOHIDDevice", "-r", "-l", "-w0"],
                             capture_output=True, text=True, check=True).stdout
    for block in re.split(r"\n\s*[+|\\]*-o ", listing):
        product = re.findall(r'"Product" = "([^"]+)"', block)
        descriptor = re.search(r'"ReportDescriptor" = <([0-9a-fA-F]+)>', block)
        if not product or not descriptor:
            continue
        usage_page = re.search(r'"PrimaryUsagePage" = (\d+)', block)
        usage = re.search(r'"PrimaryUsage" = (\d+)', block)
        transport = re.search(r'"Transport" = "([^"]+)"', block)
        yield {"product": product[-1],
               "primary": (int(usage_page.group(1)) if usage_page else -1,
                           int(usage.group(1)) if usage else -1),
               "transport": transport.group(1) if transport else "?",
               "descriptor": bytes.fromhex(descriptor.group(1))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="8",
                    help="comma separated kVK numbers to trace (default 8 = kVK_ANSI_C)")
    args = ap.parse_args()
    wanted = []
    for token in args.keys.split(","):
        vk = int(token, 0)
        wanted.append((vk, VK_TO_USAGE.get(vk)))

    seen = set()
    hit = 0
    for device in devices():
        key = (device["product"], device["descriptor"])
        if key in seen:
            continue
        seen.add(key)
        collections, fields = analyse(device["descriptor"])
        keyboard = keyboard_reports(collections, fields)
        declares_keyboard = any(page == 0x07 for _d, _c, page, _u in collections) or bool(keyboard)
        primary_is_keyboard = device["primary"][0] == 1 and device["primary"][1] == 6
        if not (declares_keyboard or primary_is_keyboard):
            continue
        hit += 1
        page, usage = device["primary"]
        print("%s  [%s]  presents as UsagePage=%d Usage=%d%s" % (
            device["product"], device["transport"], page, usage,
            "  (keyboard)" if primary_is_keyboard else ""))
        for depth, coll, cpage, cusage in collections:
            if coll == 1 and (cpage == 0x01 and cusage in (2, 6) or cpage == 0x07 or cpage == 0x0C):
                print("    collection: %s page=%s usage=0x%02X%s" % (
                    "Application", USAGE_PAGE.get(cpage, hex(cpage)), cusage or 0,
                    "  <-- keyboard" if (cpage == 0x07 or (cpage == 1 and cusage == 6)) else ""))
        for report_id, shapes in sorted(keyboard.items(), key=lambda x: (x[0] is None, x[0] or 0)):
            print("    keyboard input lives in ReportID=%s as %s" % (report_id, " + ".join(sorted(set(shapes)))))
        for vk, usage_id in wanted:
            if usage_id is None:
                print("    kVK=%d has no known Keyboard/Keypad usage, cannot map" % vk)
                continue
            for report_id, shapes in sorted(keyboard.items()):
                print("    kVK=%d would arrive as usage 0x%02X in ReportID=%s (%s)" % (
                    vk, usage_id, report_id, " + ".join(sorted(set(shapes)))))
    if not hit:
        print("no local HID device declares a keyboard collection at all")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
