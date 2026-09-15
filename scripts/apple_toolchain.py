#!/usr/bin/env python3
"""One answer to "which clang, and which SDK goes with it".

Five behavioural harnesses each wrote this themselves, all of them asking xcrun, and
on a host whose Xcode license has not been accepted from a Terminal every one of them
refused: not failed, refused, which is worse, because the gate reads as an
environment problem and someone learns to expect it. The Command Line Tools ship their
own clang and their own SDK, and that pair works without Xcode's consent.

The pairing is the whole rule. `xcrun --show-sdk-path` without `--sdk macosx` answers
with the Command Line Tools SDK on a machine that also has Xcode, and the Xcode linker
cannot read that SDK's stub files -- "unknown architecture arm64e.x1" -- so a compiler
from one vendor and a SDK from the other produces a gate that is red for a reason
nothing in the tree caused. Each candidate below is a matched pair.
"""
import os
import subprocess

CLANG_TOOLS = "/Library/Developer/CommandLineTools"

# (clang, sdk), in preference order. A pair is used only when both halves exist.
def _xcrun_pair():
    # `xcrun` does not exist on a machine that has never seen Xcode -- the audits
    # job's ubuntu runner, or any Linux box a contributor tries -- and a missing
    # binary arrives as FileNotFoundError from inside subprocess, not as an empty
    # answer. That crash used to escape clang_and_sdk(), so on such a host every
    # behavioural harness died with a traceback instead of reporting that it has no
    # compiler, which is the difference between a gate that says "not here" and one
    # that looks like the code under test is broken.
    def ask(arguments):
        try:
            return subprocess.run(["xcrun"] + arguments,
                                  capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""
    return ask(["--find", "clang"]), ask(["--sdk", "macosx", "--show-sdk-path"])


def _command_line_tools_pair():
    return (os.path.join(CLANG_TOOLS, "usr", "bin", "clang"),
            os.path.join(CLANG_TOOLS, "SDKs", "MacOSX.sdk"))


def clang_and_sdk(what="probe"):
    """A usable (clang, sdk) pair, or a SystemExit that says what is missing."""
    tried = []
    for name, locate in (("xcrun", _xcrun_pair),
                         ("Command Line Tools", _command_line_tools_pair)):
        clang, sdk = locate()
        if clang and sdk and os.path.exists(clang) and os.path.isdir(sdk):
            return clang, sdk
        tried.append("%s (%s)" % (name, "no clang" if not clang or not os.path.exists(clang)
                                  else "no readable SDK"))
    raise SystemExit("no usable clang and macOS SDK pair was found for the %s, tried %s. "
                     "Neither is a defect in the code under test."
                     % (what, " and ".join(tried)))
