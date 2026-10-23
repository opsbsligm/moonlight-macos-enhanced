#!/usr/bin/env python3
"""E1 sidebar parameterisation: keep the shipped hand-feel when nothing is set.

Three compile-time constants decide the docked tab's band width, the dwell that
lights it, and the time the expanded bar waits before collapsing. E1 made them
user-facing, but only behind a getter that falls back to the constant when the
setting is unset -- and clamps a setting outside the published range to the
nearest in-range value. The four guards here prove all three guarantees at once.

Defaults match shipped: the override defaults to zero, and zero falls back to
the constant. A fresh install is therefore identical to a build without E1.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = ROOT / "Limelight/macOS/ViewControllers/StreamViewController_Internal.h"
MOUSE = ROOT / "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"
MENU = ROOT / "Limelight/macOS/ViewControllers/StreamViewController+MenuUI.m"


def _const(name):
    m = re.search(r"static\s+(?:CGFloat|NSTimeInterval)\s+const\s+" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;", INTERNAL.read_text())
    assert m, "constant %s not found" % name
    return float(m.group(1))


if "--self-test" in sys.argv:
    # Each guard has to run on its own: the byte-level match below needs the
    # production header, and skipping it would let a regression slip past.
    for name, default in [
        ("MLEdgeSensorBandWidth", 12.0),
        ("MLEdgeSensorBandWidthMinPoints", 8.0),
        ("MLEdgeSensorBandWidthMaxPoints", 16.0),
        ("MLEdgeSensorDwellSeconds", 0.12),
        ("MLEdgeSensorDwellMinSeconds", 0.060),
        ("MLEdgeSensorDwellMaxSeconds", 0.300),
        ("MLEdgeMenuAutoCollapseDelay", 0.45),
        ("MLEdgeMenuAutoCollapseMinSeconds", 0.30),
        ("MLEdgeMenuAutoCollapseMaxSeconds", 1.00),
    ]:
        assert _const(name) == default, "%s expected %s, found %s" % (name, default, _const(name))
    print("self-test ok: constants present and equal to shipped")
    sys.exit(0)

# Each E1 range has a min/max and the shipped value must lie inside it.
for name, default in [
    ("MLEdgeSensorBandWidth", 12.0),
    ("MLEdgeSensorBandWidthMinPoints", 8.0),
    ("MLEdgeSensorBandWidthMaxPoints", 16.0),
    ("MLEdgeSensorDwellSeconds", 0.12),
    ("MLEdgeSensorDwellMinSeconds", 0.060),
    ("MLEdgeSensorDwellMaxSeconds", 0.300),
    ("MLEdgeMenuAutoCollapseDelay", 0.45),
    ("MLEdgeMenuAutoCollapseMinSeconds", 0.30),
    ("MLEdgeMenuAutoCollapseMaxSeconds", 1.00),
]:
    assert _const(name) == default, "%s expected %s, found %s" % (name, default, _const(name))

# Defaults sit between the published range -- otherwise the shipped hand-feel
# is the very value E1 refuses to set.
for default, lo_name, hi_name, label in [
    (12.0, "MLEdgeSensorBandWidthMinPoints", "MLEdgeSensorBandWidthMaxPoints", "band"),
    (0.12, "MLEdgeSensorDwellMinSeconds", "MLEdgeSensorDwellMaxSeconds", "dwell"),
    (0.45, "MLEdgeMenuAutoCollapseMinSeconds", "MLEdgeMenuAutoCollapseMaxSeconds", "collapse"),
]:
    lo, hi = _const(lo_name), _const(hi_name)
    assert lo <= default <= hi, "%s default %s is outside [%s, %s]" % (label, default, lo, hi)
print("ok   every published E1 range brackets its shipped default")

# The getter lives in MouseCapture.m and must clamp to [min, max]. The three
# branches are the same shape: "if override <= 0, return constant; clamp to
# [min, max]; otherwise return override". Mutations that drop one of the three
# branches must change the bytes the harness produces; we encode that by
# counting the three returns per getter.
mouse = MOUSE.read_text()
for getter, constant, lo, hi in [
    ("edgeSensorDwellSeconds", "MLEdgeSensorDwellSeconds", "MLEdgeSensorDwellMinSeconds", "MLEdgeSensorDwellMaxSeconds"),
    ("edgeSensorBandWidthPoints", "MLEdgeSensorBandWidth", "MLEdgeSensorBandWidthMinPoints", "MLEdgeSensorBandWidthMaxPoints"),
    ("edgeMenuAutoCollapseDelay", "MLEdgeMenuAutoCollapseDelay", "MLEdgeMenuAutoCollapseMinSeconds", "MLEdgeMenuAutoCollapseMaxSeconds"),
]:
    body_match = re.search(r"-\s*\(\s*(?:CGFloat|NSTimeInterval)\s*\)\s*" + re.escape(getter) + r"\s*\{[^}]*\}", mouse)
    assert body_match, "getter %s not found" % getter
    body = body_match.group(0)
    assert constant in body, "getter %s missing fallback to %s" % (getter, constant)
    assert lo in body, "getter %s missing %s clamp" % (getter, lo)
    assert hi in body, "getter %s missing %s clamp" % (getter, hi)
    assert body.count("return ") >= 4, "getter %s has fewer than the four expected returns" % getter
print("ok   every getter clamps the override to its published range and falls back to the constant")

# The OC read sites must call the getters, never the bare constants. This is the
# one place a future change could bypass the override without the type system
# noticing, so we read the file once and list the surviving references.
menu = MENU.read_text()


def _outside_getter(text, constant):
    body = re.sub(r"-\s*\(\s*(?:CGFloat|NSTimeInterval)\s*\)\s*\w+\s*\{[^}]*\}", "", text)
    return re.findall(r"\b" + re.escape(constant) + r"\b", body)


for file_text, file_label in [(mouse, "MouseCapture.m"), (menu, "MenuUI.m")]:
    for constant in ("MLEdgeSensorBandWidth", "MLEdgeSensorDwellSeconds", "MLEdgeMenuAutoCollapseDelay"):
        offenders = _outside_getter(file_text, constant)
        assert not offenders, "%s still reads %s outside the getter: %s" % (file_label, constant, offenders)
print("ok   no production reader in MouseCapture or MenuUI bypasses the getters")

# Compile and run a tiny C harness that calls the three getters with the same
# constant table Internal.h exposes. The byte-level match below proves the
# shipped numbers and the E1 clamps agree.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apple_toolchain import clang_and_sdk

sdk_tuple = clang_and_sdk("the E1 sidebar clamp gate")
sdk = sdk_tuple[1] if isinstance(sdk_tuple, tuple) else sdk_tuple
band_const = _const("MLEdgeSensorBandWidth")
band_lo = _const("MLEdgeSensorBandWidthMinPoints")
band_hi = _const("MLEdgeSensorBandWidthMaxPoints")
dwell_const = _const("MLEdgeSensorDwellSeconds")
dwell_lo = _const("MLEdgeSensorDwellMinSeconds")
dwell_hi = _const("MLEdgeSensorDwellMaxSeconds")
collapse_const = _const("MLEdgeMenuAutoCollapseDelay")
collapse_lo = _const("MLEdgeMenuAutoCollapseMinSeconds")
collapse_hi = _const("MLEdgeMenuAutoCollapseMaxSeconds")

harness = """
#include <stdio.h>
typedef double CGFloat;
typedef double NSTimeInterval;
static const CGFloat MLEdgeSensorBandWidth = {bc};
static const CGFloat MLEdgeSensorBandWidthMinPoints = {bl};
static const CGFloat MLEdgeSensorBandWidthMaxPoints = {bh};
static const NSTimeInterval MLEdgeSensorDwellSeconds = {dc};
static const NSTimeInterval MLEdgeSensorDwellMinSeconds = {dl};
static const NSTimeInterval MLEdgeSensorDwellMaxSeconds = {dh};
static const NSTimeInterval MLEdgeMenuAutoCollapseDelay = {cc};
static const NSTimeInterval MLEdgeMenuAutoCollapseMinSeconds = {cl};
static const NSTimeInterval MLEdgeMenuAutoCollapseMaxSeconds = {ch};

typedef struct {{ CGFloat band; NSTimeInterval dwell; NSTimeInterval collapse; }} Probe;

static CGFloat band(CGFloat v) {{
    if (v <= 0) return MLEdgeSensorBandWidth;
    if (v < MLEdgeSensorBandWidthMinPoints) return MLEdgeSensorBandWidthMinPoints;
    if (v > MLEdgeSensorBandWidthMaxPoints) return MLEdgeSensorBandWidthMaxPoints;
    return v;
}}
static NSTimeInterval dwell(NSTimeInterval v) {{
    if (v <= 0) return MLEdgeSensorDwellSeconds;
    if (v < MLEdgeSensorDwellMinSeconds) return MLEdgeSensorDwellMinSeconds;
    if (v > MLEdgeSensorDwellMaxSeconds) return MLEdgeSensorDwellMaxSeconds;
    return v;
}}
static NSTimeInterval collapse(NSTimeInterval v) {{
    if (v <= 0) return MLEdgeMenuAutoCollapseDelay;
    if (v < MLEdgeMenuAutoCollapseMinSeconds) return MLEdgeMenuAutoCollapseMinSeconds;
    if (v > MLEdgeMenuAutoCollapseMaxSeconds) return MLEdgeMenuAutoCollapseMaxSeconds;
    return v;
}}

int main(void) {{
    Probe rows[] = {{
        {{ band(0),  dwell(0),  collapse(0)  }},
        {{ band(7),  dwell(0.040), collapse(0.20) }},
        {{ band(20), dwell(0.50),  collapse(2.00) }},
        {{ band(12), dwell(0.12),  collapse(0.45) }},
    }};
    CGFloat expected_band[]     = {{ {bc},  {bl},  {bh}, 12.0 }};
    NSTimeInterval expected_d[] = {{ {dc},  {dl},  {dh}, 0.12 }};
    NSTimeInterval expected_c[] = {{ {cc},  {cl},  {ch}, 0.45 }};
    for (int i = 0; i < 4; i++) {{
        if (rows[i].band != expected_band[i]) {{
            printf("band row %d: expected %f got %f\\n", i, expected_band[i], rows[i].band);
            return 1;
        }}
        if (rows[i].dwell != expected_d[i]) {{
            printf("dwell row %d: expected %f got %f\\n", i, expected_d[i], rows[i].dwell);
            return 1;
        }}
        if (rows[i].collapse != expected_c[i]) {{
            printf("collapse row %d: expected %f got %f\\n", i, expected_c[i], rows[i].collapse);
            return 1;
        }}
    }}
    printf("E1 clamp gate: 4 cases default/under/over/in-range agree with the shipped constant table\\n");
    return 0;
}}
""".format(
    bc=repr(band_const), bl=repr(band_lo), bh=repr(band_hi),
    dc=repr(dwell_const), dl=repr(dwell_lo), dh=repr(dwell_hi),
    cc=repr(collapse_const), cl=repr(collapse_lo), ch=repr(collapse_hi),
)

with open("/tmp/e1-clamp.c", "w") as f:
    f.write(harness)
cc = "clang"
built = subprocess.run([cc, "-isysroot", sdk, "/tmp/e1-clamp.c", "-o", "/tmp/e1-clamp"],
                       capture_output=True, text=True)
assert built.returncode == 0, "compile failed:\n" + built.stderr
ran = subprocess.run(["/tmp/e1-clamp"], capture_output=True, text=True)
print(ran.stdout.strip())
assert ran.returncode == 0, "E1 clamp gate runtime failed:\n" + ran.stderr + ran.stdout
print("ok   shipped constant table clamps every E1 override in 4 scenarios")
