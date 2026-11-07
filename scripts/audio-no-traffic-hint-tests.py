#!/usr/bin/env python3
"""P1 audio triage gate: a silent host must be named, not masquerade as a buffer fault.

What this file is about
-----------------------
The underrun warning in Connection.m fires on the render side whenever the
circular buffer is dry -- which is also exactly what happens when the host
simply never sends a single audio sample (muted output device, no stream
traffic at all). build 2125 shipped a real session with 832 underrun lines
and only a closing "No audio traffic was ever received from the host!" at
teardown, so triage pointed at client buffering before the truth landed.

This gate proves that:

  * ArInit arms a silence clock (_audioTrafficArmedTime) and a
    _audioEverReceivedTraffic latch that both start fresh each session,
  * the decode callback flips the latch on the first real sample and, when
    30s of silence preceded it, logs a one-shot clarification that the
    earlier underrun warnings were host-side,
  * the underrun path names the host side too: only when copied==0, no
    traffic yet, 30s elapsed, and the throttle (every 800 underruns) lines
    up, the log says "check the host audio output device",
  * nothing new is added to the settings model or the Settings UI: the hint
    is log-level triage, not a user-facing control, so a regression that
    starts touching those files fails the file-scope check,
  * a planted defect in any of those anchors is caught by --self-test, with
    the nested MOAT_GATE_NESTED sentinel keeping the battery from forking.
"""
import os, subprocess, sys

NESTED = os.environ.get('MOAT_GATE_NESTED') == '1'

ROOT = "."
STRICT_TEST = "--self-test" in sys.argv
for a in sys.argv[1:]:
    if a != "--self-test" and os.path.isdir(a):
        ROOT = a

CONN_M = "Limelight/Stream/Connection.m"

ARM_ANCHOR = """    // P1 audio triage: a fresh session starts silent-unknown; the first sample
    // flips the flag, the 30s check below names a host that never sends any.
    conn->_audioEverReceivedTraffic = NO;
    conn->_audioTrafficArmedTime = (uint64_t)dispatch_time(DISPATCH_TIME_NOW, 0);"""

FLIP_ANCHOR = """    if (!conn->_audioEverReceivedTraffic) {
        conn->_audioEverReceivedTraffic = YES;
        uint64_t elapsedNs = (uint64_t)dispatch_time(DISPATCH_TIME_NOW, 0) - conn->_audioTrafficArmedTime;
        if (elapsedNs >= 30ull * NSEC_PER_SEC) {"""

HINT_ANCHOR = """        if (copiedFrames == 0 && !_audioEverReceivedTraffic) {
            uint64_t elapsedNs = (uint64_t)dispatch_time(DISPATCH_TIME_NOW, 0) - _audioTrafficArmedTime;
            if (elapsedNs >= 30ull * NSEC_PER_SEC && (_audioUnderrunCount % 800) == 1) {"""

failures = []

def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)

def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()

def run_self_test():
    """Plant a defect and confirm the gate fails."""
    cases = [
        (
            CONN_M,
            "    conn->_audioEverReceivedTraffic = NO;\n    conn->_audioTrafficArmedTime = (uint64_t)dispatch_time(DISPATCH_TIME_NOW, 0);",
            "    /* MUTATION PLANTED: ArInit no longer arms the silence clock */",
            "ArInit stopped arming the silence clock, so the 30s threshold never runs",
        ),
        (
            CONN_M,
            "    if (!conn->_audioEverReceivedTraffic) {\n        conn->_audioEverReceivedTraffic = YES;",
            "    if (NO) {\n        /* MUTATION PLANTED: first sample never flips the latch */",
            "first real sample no longer flips the latch: the one-shot clarification and the host hint would fire forever",
        ),
        (
            CONN_M,
            "            if (elapsedNs >= 30ull * NSEC_PER_SEC && (_audioUnderrunCount % 800) == 1) {",
            "            if (elapsedNs >= 30ull * NSEC_PER_SEC && (1) == 1) {  /* MUTATION PLANTED: throttle removed */",
            "the 10s-style throttle fell out, so a silent host spams a host-side hint on every dry render",
        ),
        (
            CONN_M,
            "        if (copiedFrames == 0 && !_audioEverReceivedTraffic) {",
            "        if (copiedFrames == 0) {  /* MUTATION PLANTED: silent-host condition dropped */",
            "the hint would fire even once real traffic arrived, misnaming a genuine client underrun",
        ),
    ]
    for rel, needle, replacement, message in cases:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        idx = original.find(needle)
        if idx < 0:
            check(False, "self-test defect for %s: needle not found" % rel.split("/")[-1])
            continue
        planted = original[:idx] + replacement + original[idx+len(needle):]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(planted)
        try:
            env = dict(os.environ, MOAT_GATE_NESTED="1")
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), ROOT],
                capture_output=True, text=True, env=env,
            )
            check(result.returncode != 0,
                  "self-test caught defect in %s (%s)" % (rel.split("/")[-1], message))
        finally:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(original)

def main():
    global failures

    conn_m = read(CONN_M)

    # The import that backs NSEC_PER_SEC is explicit, not inherited.
    check("#import <mach/mach_time.h>" in conn_m,
          "Connection.m imports mach/mach_time.h for NSEC_PER_SEC")

    # Both state members are declared in the audio state block.
    check("BOOL _audioEverReceivedTraffic;" in conn_m,
          "Connection.m declares the _audioEverReceivedTraffic latch")
    check("uint64_t _audioTrafficArmedTime;" in conn_m,
          "Connection.m declares the _audioTrafficArmedTime silence clock")

    # ArInit arms both before the buffer layout work.
    check(ARM_ANCHOR in conn_m,
          "ArInit arms the silence clock and resets the latch for the fresh session")

    # The decode callback flips the latch on the first real sample.
    check(FLIP_ANCHOR in conn_m,
          "decode callback flips the latch on the first sample and clarifies 30s+ silence")

    # The underrun path names the host side, gated on copied==0 + no traffic.
    check(HINT_ANCHOR in conn_m,
          "underrun path names the host audio device after 30s of silence, throttled")

    # The hint copy keeps the triage wording stable for log greps.
    check("check the host " in conn_m and "audio output device or mute" in conn_m,
          "host-side hint keeps its greppable wording")

    # File scope: log-level triage only -- no new settings state, no new UI.
    check("_audioEverReceivedTraffic" not in read("Limelight/macOS/ViewControllers/SettingsModel.swift"),
          "silence triage does not leak into the settings model")
    check("audioTraffic" not in read("Limelight/macOS/ViewControllers/SettingsAudioPane.swift"),
          "silence triage does not add a user-facing control")

    return 1 if failures else 0

if __name__ == "__main__":
    if STRICT_TEST and not NESTED:
        run_self_test()
    sys.exit(main())
