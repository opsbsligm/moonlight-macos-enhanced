#!/usr/bin/env python3
"""Ask the bus what shape it has today, and refuse to stay quiet about an unpinned one.

Why this exists is a mistake, not a theory. The measurement in
docs/usb-redirection-design.md 2.5 first said no device published a serial number. That
was wrong, and it was wrong because the probe asked for `USB SerialNumber` while the
registry publishes `USB Serial Number`, with the space. A probe that asks for the wrong
key name reports a clean, tidy, false world -- and a false world in that table is worse
than none, because the security rules were written against it.

So the question this tool asks is not "is the bus still there" but "does every shape the
bus produces today have a fixture that pins it". The probe it compiles asks about exactly
the keys the parser reads: the five candidate key lists are extracted out of
USBDeviceEnumeration.m, so a probe can no longer under-ask, which is the precise failure
that produced the wrong serial answer. The node counts come from the probe too, because
the first version capped each class at eight nodes and the table reported that cap as if
it had been the size of the bus.

Three outcomes, and only one of them is a pass:

  covered   every observed shape is pinned by a named case in the Stage 1 harness
  drift     something arrived that no fixture asserts -- add the case, or widen the
            parser on purpose, and write down which
  not measured   no toolchain or no IOKit here (an Ubuntu runner, say): the run says so
            in as many words and does not print the word covered

`--self-test` is pure Python and drives the classifier with fabricated buses, so the
classifier itself is checked where no USB device exists -- including the rule that every
pinned case name still exists in the harness text, which is what turns a deleted fixture
into a red run rather than a quietly shortened table.

This tool is deliberately not named *-audit, *-tests or *-probe: it is a measurement, not
a gate, and it is run by the enumeration harness's own self-test rather than registered
as a gate that would pass on a runner with no USB devices.
"""
import argparse
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENUM_M = "Limelight/Stream/USBDeviceEnumeration.m"
HARNESS = "scripts/usb-device-enumeration-tests.py"
ENUMERATOR_CLASSES = ("IOUSBHostDevice", "IOUSBHostInterface", "IOUSBDevice", "IOUSBInterface")

# Which accessor in the shipping file owns which role, and which shape names that role's
# values can take. The role names are this tool's vocabulary; the keys come from the source.
ROLES = (
    ("vendor", "MLVendorKeys", ("number", "hex-text", "text-not-hex", "data", "array", "absent")),
    ("product", "MLProductKeys", ("number", "hex-text", "text-not-hex", "data", "array", "absent")),
    ("serial", "MLSerialKeys", ("string", "absent")),
    ("interface-class", "MLInterfaceClassKeys", ("number-per-node", "number-array", "absent")),
    ("interface-protocol", "MLInterfaceProtocolKeys", ("number-per-node", "number-array", "absent")),
)

# Every shape the classifier can produce, pinned to the case in the Stage 1 harness that
# asserts the parser's behaviour on it. A shape missing from this table is drift by
# definition; a case name missing from the harness text is a self-test failure, so the
# table cannot shrink by deleting the thing it pointed at.
PINNED_SHAPES = {
    "vendor=number": "numeric identifiers",
    "product=number": "numeric identifiers",
    "vendor=hex-text": "hex text identifiers",
    "product=hex-text": "hex text identifiers",
    "vendor=text-not-hex": "half a hex number is not an identifier",
    "product=text-not-hex": "half a hex number is not an identifier",
    "vendor=data": "a data-shaped identifier stays unread instead of becoming two bytes of a vendor id",
    "product=data": "a data-shaped identifier stays unread instead of becoming two bytes of a vendor id",
    "vendor=array": "an array-shaped identifier is not read out of its first element",
    "product=array": "an array-shaped identifier is not read out of its first element",
    "vendor=absent": "no identifiers at all",
    "product=absent": "no identifiers at all",
    "serial=string": "one serial is one token, two serials are two, and no serial says none",
    "serial=absent": "a device the registry gave no serial for says none",
    "interface-class=number-per-node": "a device split across four registry nodes comes back as one device with three interfaces",
    "interface-protocol=number-per-node": "an interface whose protocol byte arrived is believed",
    "interface-class=number-array": "a dock that is also a smart card is refused through the enumeration path too",
    "interface-protocol=number-array": "one protocol byte is not shared out to two interfaces",
    "interface-class=absent": "no nodes is an unreadable device, not an empty one",
    "interface-protocol=absent": "no nodes is an unreadable device, not an empty one",
}

# Keys the parser must keep answering to, whatever the classifier says. This list is what
# the wrong probe got wrong; it is spelled out here so the mistake has a name.
MEASURED_BASELINE = {"vendor": "idVendor", "product": "idProduct"}


def read(root, rel):
    return open(os.path.join(root, rel), encoding="utf-8").read()


def key_lists(root):
    """The parser's own candidate keys, read out of the file that reads the registry.

    Extracted rather than copied: the probe that measures the bus has to ask about every
    key the parser might consult, and a hand-copied list is how a serial number got
    measured as absent.
    """
    source = read(root, ENUM_M)
    lists = {}
    for role, accessor, _ in ROLES:
        block = re.search(r"\*%s\(void\) \{\s*return @\[(.*?)\];" % accessor, source, re.S)
        if block is None:
            raise SystemExit("%s: no candidate key list for %s -- the parser was refactored "
                             "and this tool has to follow it" % (ENUM_M, accessor))
        keys = re.findall(r'@\s*\(?\s*"((?:[^"\\]|\\.)*)"', block.group(1))
        if not keys:
            raise SystemExit("%s: %s lists no keys" % (ENUM_M, accessor))
        lists[role] = keys
    for role, key in MEASURED_BASELINE.items():
        if key not in lists[role]:
            raise SystemExit("%s no longer reads %s, which the 2.5 measurement says answers "
                             "on real hardware" % (role, key))
    return lists


def probe_source(lists):
    """A read-only IORegistry probe that asks about exactly those keys."""
    wanted = sorted({key for keys in lists.values() for key in keys})
    entries = "\n".join('    "%s",' % key for key in wanted)
    return """// Generated by scripts/usb-registry-shape.py from the candidate key lists in
// Limelight/Stream/USBDeviceEnumeration.m: the probe asks what the parser reads, never
// less. Read only -- an iterator and a property read, no device opened, no entitlement.
// No value is printed. Serial numbers are personal data, and this program's output is
// meant to be pasted into a bug report: only the shape is reported (type, length, and
// whether a string is hex-shaped), never the content.
//   CLASS <TAB> KEY <TAB> TYPE <TAB> DETAIL
//   COUNT <TAB> CLASS <TAB> NODES <TAB> n
#include <IOKit/IOKitLib.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

static const char *Wanted[] = {
%s
    NULL
};

static int is_hex(CFStringRef text) {
    const char *prefix = "0x";
    CFIndex length = CFStringGetLength(text);
    char stack[128];
    char *buffer = length < (CFIndex)sizeof stack ? stack : (char *)malloc((size_t)length + 1);
    if (!buffer) {
        return 0;
    }
    int hex = 0;
    if (CFStringGetCString(text, buffer, length + 1, kCFStringEncodingUTF8)) {
        const char *start = buffer;
        if (strlen(start) > 2 && strncmp(start, prefix, 2) == 0) {
            start += 2;
        }
        hex = *start != '\\0';
        for (; *start; start++) {
            if (!isxdigit((unsigned char)*start)) {
                hex = 0;
                break;
            }
        }
    }
    if (buffer != stack) {
        free(buffer);
    }
    return hex;
}

static void emit(const char *cls, const char *key, CFTypeRef value) {
    if (!value) {
        return;
    }
    const CFTypeID type = CFGetTypeID(value);
    if (type == CFDataGetTypeID()) {
        printf("%%s\\t%%s\\tdata\\t%%ld\\n", cls, key, (long)CFDataGetLength((CFDataRef)value));
    } else if (type == CFNumberGetTypeID()) {
        long long number = 0;
        CFNumberGetValue((CFNumberRef)value, kCFNumberLongLongType, &number);
        printf("%%s\\t%%s\\tnumber\\t%%lld\\n", cls, key, number);
    } else if (type == CFStringGetTypeID()) {
        printf("%%s\\t%%s\\tstring\\t%%ld,%%s\\n", cls, key,
               (long)CFStringGetLength((CFStringRef)value),
               is_hex((CFStringRef)value) ? "hex" : "nohex");
    } else if (type == CFArrayGetTypeID()) {
        printf("%%s\\t%%s\\tarray\\t%%ld\\n", cls, key, (long)CFArrayGetCount((CFArrayRef)value));
    } else {
        printf("%%s\\t%%s\\tother\\t%%lu\\n", cls, key, (unsigned long)type);
    }
}

static void walk(const char *cls) {
    io_iterator_t iterator = {0};
    const kern_return_t result = IOServiceGetMatchingServices(kIOMainPortDefault,
                                                             IOServiceMatching(cls),
                                                             &iterator);
    if (result != KERN_SUCCESS) {
        printf("COUNT\\t%%s\\tNODES\\t0\\n", cls);
        return;
    }
    long nodes = 0;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        nodes++;
        CFMutableDictionaryRef properties = NULL;
        if (IORegistryEntryCreateCFProperties(service, &properties, kCFAllocatorDefault, 0)
            == KERN_SUCCESS && properties) {
            for (int index = 0; Wanted[index]; index++) {
                CFStringRef key = CFStringCreateWithCString(NULL, Wanted[index],
                                                            kCFStringEncodingUTF8);
                emit(cls, Wanted[index], CFDictionaryGetValue(properties, key));
                CFRelease(key);
            }
            CFRelease(properties);
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    printf("COUNT\\t%%s\\tNODES\\t%%ld\\n", cls, nodes);
}

int main(void) {
%s
    return 0;
}
""" % (entries, "\n".join('    walk("%s");' % cls for cls in ENUMERATOR_CLASSES))


def run_probe(root):
    """Compile and run the probe. Returns records, or None where there is no IOKit."""
    try:
        import apple_toolchain
        cc, sdk = apple_toolchain.clang_and_sdk("usb registry shape")
    except (Exception, SystemExit) as problem:  # no toolchain, no SDK, consent refused
        print("not measured: no toolchain here (%s)" % str(problem).strip().splitlines()[0])
        return None
    with tempfile.TemporaryDirectory() as work:
        source = os.path.join(work, "shape.c")
        binary = os.path.join(work, "shape")
        open(source, "w", encoding="utf-8").write(probe_source(key_lists(root)))
        built = subprocess.run([cc, "-x", "c", "-isysroot", sdk, "-Wall", "-Wextra",
                                "-framework", "IOKit", "-framework", "CoreFoundation",
                                source, "-o", binary], capture_output=True, text=True)
        if built.returncode != 0:
            print("not measured: the probe did not build (%s)"
                  % (built.stdout + built.stderr).strip().splitlines()[-1])
            return None
        ran = subprocess.run([binary], capture_output=True, text=True)
        if ran.returncode != 0:
            print("not measured: the probe exited %d" % ran.returncode)
            return None
        return parse_records(ran.stdout)


def parse_records(text):
    records = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        records.append(tuple(fields))
    return records


def shape_name(role, typ, detail):
    """Name one observed value shape, or None where the row carries no shape."""
    if role in ("vendor", "product"):
        if typ == "number":
            return "%s=number" % role
        if typ == "data":
            return "%s=data" % role
        if typ == "array":
            return "%s=array" % role
        if typ == "string":
            return "%s=%s" % (role, "hex-text" if "hex" in detail.split(",") and
                              "nohex" not in detail.split(",") else "text-not-hex")
        return "%s=unknown-type-%s" % (role, typ)
    if role == "serial":
        if typ == "string":
            return "serial=string"
        return "serial=unknown-type-%s" % typ
    if typ == "number":
        return "%s=number-per-node" % role
    if typ == "array":
        return "%s=number-array" % role
    return "%s=unknown-type-%s" % (role, typ)


def classify(records, lists):
    """Shapes observed on the bus, plus the node counts that give them meaning.

    Records are what the probe printed: ``CLASS KEY TYPE DETAIL`` rows, plus one
    ``COUNT CLASS NODES n`` row per class. Rows are grouped by (role, shape), and each
    group says which key answered on how many nodes of which class -- so a shape that
    only appears on interface nodes cannot be read as if the whole bus had it.
    """
    role_of_key = {}
    for role, keys in lists.items():
        for key in keys:
            role_of_key[key] = role
    counts = {}
    for row_class, field, kind, value in records:
        if row_class == "COUNT":
            counts[field] = int(value)
    groups = {}
    answered = set()
    for row_class, key, typ, detail in records:
        if row_class == "COUNT":
            continue
        role = role_of_key.get(key)
        if role is None:
            continue
        shape = shape_name(role, typ, detail)
        answered.add(role)
        tally = groups.setdefault(shape, {}).setdefault((key, row_class), [0, typ])
        tally[0] += 1
    shapes = set()
    evidence = {}
    for shape, keys in groups.items():
        shapes.add(shape)
        evidence[shape] = ["%d/%s nodes carry %s as %s" % (n, row_class, key, typ)
                           for (key, row_class), (n, typ) in sorted(keys.items())]
    for role, _, _ in ROLES:
        if role not in answered:
            shape = "%s=absent" % role
            shapes.add(shape)
            evidence[shape] = ["no node carried any of: " + ", ".join(lists[role])]
    return shapes, evidence, counts


def verdict(shapes, harness_text):
    """Why a shape is not pinned, in the words an operator can act on."""
    problems = []
    for shape in sorted(shapes):
        case = PINNED_SHAPES.get(shape)
        if case is None:
            problems.append("no fixture pins %s -- add a case for it, or widen the parser "
                            "on purpose and record that in 2.5" % shape)
        elif case not in harness_text:
            problems.append("%s is pinned by a case that is no longer in %s: %r"
                            % (shape, HARNESS, case))
    return problems


def node_count_report(counts):
    """Say what was counted, including the alias classes that name the same objects."""
    return ", ".join("%s=%d" % (cls, counts[cls]) for cls in ENUMERATOR_CLASSES
                     if cls in counts) or "no USB node class reported a count"


# Buses that are not attached. Each case is a record list plus what the classifier has to
# make of it, so the classifier is itself checked on machines that own no USB devices.
def stale_pins(harness_text):
    """Pins that point at nothing.

    ``verdict`` only reports drift for the shapes a bus produced today, which is right for
    drift but wrong for this: a fixture nobody observed yesterday is still load-bearing, and
    if deleting it stayed quiet until such a device appeared, the table could be shrunk by
    deleting the thing it pointed at. So every pin is checked, observed or not.
    """
    return ["nothing in %s is called %r any more, so the pin for %s points at nothing"
            % (HARNESS, case, shape)
            for shape, case in sorted(PINNED_SHAPES.items()) if case not in harness_text]


def self_test(root):
    failures = []
    checks_run = []

    def check(ok, message):
        checks_run.append(message)
        print("%-4s %s" % ("ok" if ok else "FAIL", message))
        if not ok:
            failures.append(message)

    lists = key_lists(root)
    check(len(lists) == len(ROLES) and lists["vendor"] and lists["serial"],
          "all five candidate key lists were read out of the parser")
    check("idVendor" in lists["vendor"] and "idProduct" in lists["product"],
          "the keys that answered on real hardware are in the lists the probe asks about")
    check("USB Serial Number" in lists["serial"],
          "the serial key the wrong probe misspelled is spelled here")

    def row(cls, key, typ, detail):
        return (cls, key, typ, detail)

    def count(cls, n):
        return ("COUNT", cls, "NODES", str(n))

    real_bus = [
        count("IOUSBHostDevice", 10), count("IOUSBHostInterface", 11),
        row("IOUSBHostDevice", "idVendor", "number", "10462"),
        row("IOUSBHostDevice", "idProduct", "number", "8706"),
        row("IOUSBHostDevice", "USB Serial Number", "string", "17,nohex"),
        row("IOUSBHostInterface", "bInterfaceClass", "number", "3"),
        row("IOUSBHostInterface", "bInterfaceProtocol", "number", "0"),
    ]
    shapes, evidence, counts = classify(real_bus, lists)
    check(shapes == {"vendor=number", "product=number", "serial=string",
                     "interface-class=number-per-node",
                     "interface-protocol=number-per-node"},
          "a bus shaped like the one that was measured classifies as exactly its five shapes")
    check(evidence["vendor=number"] == ["1/IOUSBHostDevice nodes carry idVendor as number"],
          "the evidence names the key, the node class and how many of them answered")
    check("no node carried any of" not in "".join(evidence["vendor=number"]),
          "a role that answered is never described as absent")
    check(counts["IOUSBHostInterface"] == 11,
          "the node count is the probe's own, not a cap this tool imposed")
    harness = read(root, HARNESS)
    check(verdict(shapes, harness) == [],
          "every shape measured on that bus is pinned by a named harness case")
    check(stale_pins(harness) == [],
          "every pin in the table points at a case that still exists, observed or not")

    # The array fixture pins both halves of the identifier, so losing it has to cost two
    # pins rather than look like one half of the table is still supported.
    # The pass that means "we could not look" has to be unable to speak the word covered.
    # Faking the toolchain is the only way to test it on a machine that owns one.
    real_toolchain = sys.modules.get("apple_toolchain")

    class NoToolchain(object):
        @staticmethod
        def clang_and_sdk(_purpose):
            raise SystemExit("xcrun: error: no developer directory")

    sys.modules["apple_toolchain"] = NoToolchain
    spoken = io.StringIO()
    try:
        with contextlib.redirect_stdout(spoken):
            outcome = run_probe(root)
    finally:
        if real_toolchain is None:
            del sys.modules["apple_toolchain"]
        else:
            sys.modules["apple_toolchain"] = real_toolchain
    check(outcome is None and "not measured" in spoken.getvalue()
          and "covered" not in spoken.getvalue(),
          "a machine with no toolchain is told it was not measured, and never hears covered")

    stale = stale_pins(harness.replace(PINNED_SHAPES["product=array"], "removed on purpose"))
    check(len(stale) == 2 and all("array" in problem for problem in stale),
          "deleting a fixture for a shape no bus showed today is still a red run")

    # A type nobody specified. It has to reach the verdict as a shape with no fixture,
    # because the failure mode being defended against is a measurement saying nothing.
    unpinned, unpinned_evidence, _ = classify([
        count("IOUSBHostDevice", 1),
        row("IOUSBHostDevice", "idVendor", "boolean", "1"),
    ], lists)
    problems = [problem for problem in verdict(unpinned, read(root, HARNESS))
                if "no fixture pins" in problem]
    check(len(problems) == 1 and "vendor=unknown-type-boolean" in problems[0],
          "a vendor id of a type nobody has seen is reported as unpinned, not read as a number")
    check(unpinned_evidence.get("vendor=unknown-type-boolean"),
          "the unpinned shape still says which key produced it, so the fix is not a guess")

    data_bus, _, _ = classify([count("IOUSBHostDevice", 1),
                               row("IOUSBHostDevice", "idVendor", "data", "2")], lists)
    check("vendor=data" in data_bus,
          "a data-shaped identifier is named as one, so the rule against guessing stays pinned")

    check(shape_name("vendor", "string", "4,hex") == "vendor=hex-text" and
          shape_name("vendor", "string", "5,nohex") == "vendor=text-not-hex",
          "hex-shaped text and other text are told apart, which is what the parser does")

    # Deleting the fixture a shape points at has to be loud: the table is only worth
    # having if it cannot shrink by losing the thing it referenced.
    sample_case = PINNED_SHAPES["serial=string"]
    narrowed = harness.replace(sample_case, "the serial cases were removed")
    problems = verdict({"serial=string"}, narrowed)
    check(len(problems) == 1 and sample_case in problems[0],
          "a pinned shape whose case was deleted fails the run instead of passing quietly")

    # A bus with no serial anywhere must say absent, which is the path the wrong probe
    # pretended was the only one.
    silent, silent_evidence, _ = classify([
        count("IOUSBHostDevice", 1),
        row("IOUSBHostDevice", "idVendor", "number", "4146"),
        row("IOUSBHostDevice", "idProduct", "number", "4991"),
        row("IOUSBHostInterface", "bInterfaceClass", "number", "3"),
        row("IOUSBHostInterface", "bInterfaceProtocol", "number", "0"),
    ], lists)
    check("serial=absent" in silent and
          verdict(silent, harness) == [],
          "a bus that publishes no serial is called absent, and that shape is pinned too")
    check(lists["serial"][0] in silent_evidence["serial=absent"][0],
          "the absent line names the keys it looked for, so a misspelling is visible")

    # A value of a type nobody has seen has to surface as a shape with no fixture, not be
    # dropped: the first probe's silence about an unasked key is the failure mode here.
    odd, _, _ = classify([count("IOUSBHostDevice", 1),
                          row("IOUSBHostDevice", "idVendor", "boolean", "1")], lists)
    check(any(shape.startswith("vendor=") and shape != "vendor=absent" for shape in odd),
          "a value of a type nobody has observed still becomes a shape, so it cannot go uncounted")

    print("%s (%d checks)" % ("RUN FAILED" if failures else "RUN PASSED", len(checks_run)))
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(prog="usb-registry-shape.py")
    parser.add_argument("--self-test", action="store_true",
                        help="check the classifier with fabricated records (no IOKit needed)")
    parser.add_argument("--print-probe", action="store_true",
                        help="write the generated probe source to stdout instead of running it")
    parser.add_argument("--root", default=ROOT)
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    lists = key_lists(root)
    if args.print_probe:
        sys.stdout.write(probe_source(lists))
        return 0
    print("probe asks the parser's own keys: %s"
          % "; ".join("%s=[%s]" % (role, ", ".join(keys)) for role, keys in lists.items()))
    if args.self_test:
        return self_test(root)
    records = run_probe(root)
    if records is None:
        return 0
    shapes, evidence, counts = classify(records, lists)
    print("measured %s" % node_count_report(counts))
    for shape in sorted(shapes):
        print("  %-34s %s" % (shape, "; ".join(evidence.get(shape, []))))
    problems = verdict(shapes, read(root, HARNESS)) + stale_pins(read(root, HARNESS))
    for problem in problems:
        print("DRIFT %s" % problem)
    print("covered: every shape on this bus is pinned by a Stage 1 case"
          if not problems else "not covered: %d shape(s) no fixture pins" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
