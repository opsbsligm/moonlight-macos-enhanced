#!/usr/bin/env python3
"""Grade a real-device acceptance run from the exported report, not from anybody's memory.

What this file is about
-----------------------
Seven acceptance items in `docs/goal-mode-prompt.md` section 4 have carried
`hardware_validated=false` for weeks. What was missing was not a feature: it was a way
to say "this row was actually evidenced" without a human reading a report and
remembering what they saw. The app now exports a `machine` block (one `key=value` per
line, Wave I), so a checker can index it directly.

Two kinds of evidence exist, and this tool keeps them apart on purpose:

  * the report proves the *configuration was live* during a real stream -- a switch was
    written on, a parameter was overridden rather than sitting on its shipped constant,
    a stream really delivered frames, a backoff really counted an attempt;
  * only a person proves the *host-side behaviour* -- the gamepad icon in Sunshine, the
    candidate window anchoring over the composed text, SAS actually lifting.

An item therefore passes only when both halves are present: the report says the setting
was in force, and a declaration bound to that exact report says the behaviour was seen.
A report alone never yields PASS, and a declaration alone is a claim about a build that
may not have had the switch on.

The rule the whole tool exists for: a key the app never wrote is `unknown`, never a
zero and never a pass. `--self-test` re-runs the same contract against two mutated
copies of this file -- one that reads a missing key as satisfied, one that accepts any
value -- and refuses to be green while either is alive, because those two mutations are
exactly how a grader turns an unevidenced row into a checked box.

Usage:
  hardware-acceptance-check.py REPORT.txt [--declare DECL.json] [--json]
  hardware-acceptance-check.py REPORT.txt --emit-declaration > DECL.json
  hardware-acceptance-check.py --self-test
Exit 0 only when every row is PASS. Exit 1 when any row is FAIL or UNKNOWN. Exit 2 for
a report that cannot be parsed at all (that is a broken export, not an unevidenced row).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

SELF = os.path.abspath(__file__)

# A mutation check runs this file again from a mutated copy. The child only ever runs in
# grade mode, so it cannot fork again; the sentinel is belt-and-braces for whoever edits
# this file next and puts a self-test call inside a code path the mutation touches.
NESTED = os.environ.get("HWC_GATE_NESTED") == "1"

SCHEMA = "1"
MACHINE_HEADER = "[machine]"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"

# The one answer to "what does a key the app never wrote mean?". It is a named constant
# instead of an inline `machine.get(k, default)` so the self-test can plant the opposite
# answer in a copy of this file and show that the contract below notices.
MISSING_READS_AS_SATISFIED = False

# The six hand-feel parameters, by the key name the report writes. These come from the
# labels in `StreamViewController+Diagnostics.m`, lowercased with non-alphanumerics
# folded to `_`; `scripts/diagnostics-report-tests.py` pins the block's shape, this gate
# pins which keys a verdict is allowed to depend on.
SIDEBAR_PARAMS = (
    "edge_sensor_band",
    "edge_sensor_dwell",
    "auto_collapse",
    "summon_grace",
    "flick_stroke",
    "idle_tab_thickness",
)

# Types that mean "the host was told which pad this is". `unknown` is a real answer the
# formatter can emit, and it is not a verified type announcement.
ANNOUNCED_TYPES = ("xbox", "ps", "nintendo")


class ReportError(Exception):
    """The machine block is missing or malformed, so nothing here is gradable."""


def parse_machine(text):
    """The `machine` block as a dict. Strict: this is data for a checker, not prose."""
    lines = text.splitlines()
    if MACHINE_HEADER not in lines:
        raise ReportError("no %s block in the report (exported from a build older than Wave I?)"
                          % MACHINE_HEADER)
    start = lines.index(MACHINE_HEADER)
    machine = {}
    for raw in lines[start + 1:]:
        if raw.startswith("["):
            break
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or " " in key:
            raise ReportError("malformed machine line: %r" % raw)
        if key in machine:
            raise ReportError("duplicate machine key: %s" % key)
        machine[key] = value
    if machine.get("ml.schema") != SCHEMA:
        raise ReportError("machine block schema %r is not understood (this checker reads schema %s)"
                          % (machine.get("ml.schema"), SCHEMA))
    return machine


def want(machine, key, expected):
    """Is this key exactly the value the verdict needs?"""
    value = machine.get(key)
    if value is None:
        return MISSING_READS_AS_SATISFIED
    return value == expected


def number_at(machine, key):
    """An integer key, or None when it is absent or not a number. Never a silent zero."""
    value = machine.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def keys_under(machine, prefix):
    return sorted(k for k in machine if k.startswith(prefix))


def stream_was_running(machine):
    """A stream delivered frames, so any host-side claim made in this session has a subject."""
    if machine.get("ml.video.present") != "yes":
        return False, "ml.video.present is %s -- no stream counters in this report" \
            % machine.get("ml.video.present", "absent")
    received = number_at(machine, "ml.video.frames.received")
    if not received:
        return False, "ml.video.frames.received is %s -- a stream that received nothing cannot " \
                      "evidence a host-side behaviour" % machine.get("ml.video.frames.received", "absent")
    return True, "stream delivered %s received frames (%s)" % (
        received, machine.get("ml.video.format", "codec unknown"))


def all_true(reasons):
    return all(ok for ok, _ in reasons)


def join_reasons(reasons):
    return "; ".join(text for _, text in reasons)


def check_two_pads(machine):
    present = number_at(machine, "ml.controllers.slot_count_placeholder")
    del present
    slots = keys_under(machine, "ml.controllers.slot.")
    reasons = [(machine.get("ml.controllers.present") == "yes",
                "ml.controllers.present is %s" % machine.get("ml.controllers.present", "absent")),
               (want(machine, "ml.controllers.arrivals", "yes"),
                "ml.controllers.arrivals is %s -- nothing was announced to the host"
                % machine.get("ml.controllers.arrivals", "absent"))]
    # The count a checker is allowed to use is the number of player slots the host was told
    # about. `group_count` counts VID/PID/family identities, and two pads of one model are
    # one row there, so a build that dropped the caveat key must not be graded from it.
    caveat = want(machine, "ml.controllers.group_count_is_physical_devices", "no")
    reasons.append((caveat,
                    "ml.controllers.group_count_is_physical_devices is %s -- without that caveat "
                    "the group count reads as a device count"
                    % machine.get("ml.controllers.group_count_is_physical_devices", "absent")))
    reasons.append((len(slots) >= 2,
                    "%d slot row(s) advertised: %s -- two pads have to reach two slots"
                    % (len(slots), ", ".join(slots) or "none")))
    if len(slots) < 2 and (number_at(machine, "ml.controllers.group_count") or 0) >= 2:
        reasons.append((False,
                        "two or more identity groups but a single advertised slot -- the second "
                        "pad was never announced, so this session cannot grade controller input"))
    return all_true(reasons), join_reasons(reasons)


def check_host_side_types(machine):
    slots = keys_under(machine, "ml.controllers.slot.")
    types = [machine[k] for k in slots]
    reasons = [(want(machine, "ml.controllers.arrivals", "yes"),
                "ml.controllers.arrivals is %s" % machine.get("ml.controllers.arrivals", "absent")),
               (bool(slots), "no ml.controllers.slot.N rows -- the host was told no player at all"),
               (bool(slots) and all(t in ANNOUNCED_TYPES for t in types),
                "advertised slot types: %s -- each has to be one of %s"
                % (", ".join(types) or "none", "/".join(ANNOUNCED_TYPES))),
               (want(machine, "ml.controllers.caps.rumble", "yes"),
                "ml.controllers.caps.rumble is %s -- a capability that is not advertised cannot be "
                "graded for force feedback" % machine.get("ml.controllers.caps.rumble", "absent"))]
    return all_true(reasons), join_reasons(reasons)


def check_stream_only(machine):
    """Rows where the report can only prove a session existed; the behaviour is the human's claim."""
    return stream_was_running(machine)


def check_sidebar_params(machine):
    missing = []
    for param in SIDEBAR_PARAMS:
        for suffix in ("effective", "shipped", "range", "written", "state"):
            if ("ml.param.%s.%s" % (param, suffix)) not in machine:
                missing.append("ml.param.%s.%s" % (param, suffix))
    reasons = [(not missing, "machine block lacks %d key(s) the six-parameter verdict needs: %s"
                % (len(missing), ", ".join(missing[:4]) + (" ..." if len(missing) > 4 else "")))]
    states = {param: machine.get("ml.param.%s.state" % param, "")
              for param in SIDEBAR_PARAMS}
    exercised = [p for p, state in states.items()
                 if state.startswith("override_of_") or state.startswith("clamped_")]
    # A parameter sitting on its shipped constant proves the default survived an upgrade.
    # It does not prove the slider does anything, which is the thing this row is about.
    reasons.append((bool(exercised),
                    "all six parameters read %s -- shipped defaults do not evidence a "
                    "parameterised hand-feel, move at least one off its default"
                    % sorted(set(states.values())) if not missing else ""))
    reason_text = join_reasons(reasons)
    if exercised:
        reason_text = "exercised off their defaults: %s" % ", ".join(exercised)
    return all_true(reasons), reason_text


def check_local_ime(machine):
    state = machine.get("ml.switch.imeLocalComposition")
    if state is None:
        return False, "ml.switch.imeLocalComposition is absent -- the report cannot say the " \
                      "composition path was ever live"
    if state != "on":
        return False, "ml.switch.imeLocalComposition is %s -- composition was not in force, so " \
                      "this session tested pass-through" % state
    return True, "ml.switch.imeLocalComposition=on"


def check_desktop_suite(machine):
    reasons = []
    absolute = machine.get("ml.pointer.absolute")
    reasons.append((absolute == "yes",
                    "ml.pointer.absolute is %s -- P2-1 needs the absolute path actually taken "
                    "at least once" % absolute))
    reconnect_present = machine.get("ml.reconnect.present")
    attempts = number_at(machine, "ml.reconnect.attempt")
    reasons.append((reconnect_present == "yes" and attempts is not None and attempts >= 1,
                    "ml.reconnect.present=%s attempt=%s -- P2-2 needs a backoff that counted at "
                    "least one attempt" % (reconnect_present, attempts)))
    for switch, feature in (("muteOnFocusLoss", "P2-3a"), ("backgroundGamepad", "P2-3b")):
        value = machine.get("ml.switch.%s" % switch)
        reasons.append((value == "on",
                        "ml.switch.%s is %s -- %s was never in force" % (switch, value, feature)))
    return all_true(reasons), join_reasons(reasons)


# The matrix. The ids are stable: a declaration names one, and the checklist in
# `docs/hardware-acceptance-checklist.md` repeats them so a person and a checker mean the
# same thing by the same word.
ITEMS = (
    {"id": "controllers-two-pads", "row": "4.1", "title": "two controllers diagnosed and announced",
     "report": check_two_pads},
    {"id": "host-side-controller-behaviour", "row": "4.2", "title": "host-side type, icons, IMU, battery, touchpad",
     "report": check_host_side_types},
    {"id": "keyboard-unicode", "row": "4.3", "title": "K1.1 Chinese / emoji / full-width / key repeat",
     "report": check_stream_only},
    {"id": "edge-sidebar-params", "row": "4.4", "title": "E1 + Wave C six hand-feel parameters exercised",
     "report": check_sidebar_params},
    {"id": "local-ime-composition", "row": "4.5", "title": "K1.2 local composition (per-host switch on)",
     "report": check_local_ime},
    {"id": "secure-attention-sequence", "row": "4.6", "title": "K2/SAS lifted on the host",
     "report": check_stream_only},
    {"id": "desktop-suite", "row": "4.7", "title": "P2-1 absolute mouse, P2-2 backoff, P2-3a/b focus behaviours",
     "report": check_desktop_suite},
)


def report_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def grade(report_text, declaration):
    """Verdicts per row. `declaration` may be None (nothing was declared by a person yet)."""
    machine = parse_machine(report_text)
    bound = None
    observed = {}
    if declaration is not None:
        bound = declaration.get("report_sha256")
        for entry in declaration.get("items", []):
            observed[entry.get("id")] = entry
    verdicts = []
    for item in ITEMS:
        satisfied, reason = item["report"](machine)
        entry = observed.get(item["id"])
        if not satisfied:
            verdict, why = UNKNOWN, "report does not show the setting live: " + reason
        elif bound != report_sha256(report_text):
            verdict, why = UNKNOWN, ("no declaration bound to this report (report_sha256 is %s)"
                                     % "missing" if bound is None else
                                     "declaration is bound to a different report")
        elif not entry or not entry.get("observed"):
            verdict, why = UNKNOWN, "no observer statement for this row"
        elif not str(entry.get("note", "")).strip():
            verdict, why = UNKNOWN, "the observer statement carries no note, so it cannot be re-checked"
        else:
            verdict, why = PASS, reason + " | observed: " + str(entry["note"]).strip()
        verdicts.append({"id": item["id"], "row": item["row"], "title": item["title"],
                         "verdict": verdict, "reason": why})
    return {"schema": int(SCHEMA), "report_sha256": report_sha256(report_text), "items": verdicts}


def emit_declaration(report_text):
    """A skeleton the observer fills in. Nothing arrives pre-observed: a template that
    already said `true` would be a checkbox with a button on it."""
    return {"report_sha256": report_sha256(report_text),
            "observer": "",
            "accepted_at": "",
            "items": [{"id": item["id"], "observed": False, "note": ""} for item in ITEMS]}


def render(matrix):
    lines = []
    for item in matrix["items"]:
        lines.append("%-7s %-5s %-34s %s" % (item["verdict"], item["row"], item["id"], item["reason"]))
    counts = {verdict: sum(1 for i in matrix["items"] if i["verdict"] == verdict)
              for verdict in (PASS, UNKNOWN, FAIL)}
    lines.append("")
    lines.append("pass %d, unknown %d, fail %d of %d rows -- hardware_validated=%s"
                 % (counts[PASS], counts[UNKNOWN], counts[FAIL], len(matrix["items"]),
                    "true" if counts[PASS] == len(matrix["items"]) else "false"))
    return "\n".join(lines)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def run_tool(argv, tool=SELF):
    env = dict(os.environ, HWC_GATE_NESTED="1")
    done = subprocess.run([sys.executable, tool] + argv, capture_output=True, text=True, env=env)
    return done.returncode, done.stdout, done.stderr


def matrix_from(tool, argv):
    code, out, err = run_tool(argv + ["--json"], tool=tool)
    if code == 2:
        return None, err
    try:
        return json.loads(out), out
    except ValueError:
        return None, out + err


# --------------------------------------------------------------------------- fixtures

# A report shaped exactly as `machineStateSectionWithState:snapshot:` writes it. It is
# long on purpose: the contract is about key names, and a shortened fixture lets a grader
# pass on keys the shipped formatter never emits.
GOLDEN_PARAMS = {
    "edge_sensor_band": ("12", "12", "8..16", "none", "shipped"),
    "edge_sensor_dwell": ("0.12", "0.12", "0.06..0.3", "none", "shipped"),
    "auto_collapse": ("0.45", "0.45", "0.3..1", "none", "shipped"),
    "summon_grace": ("4", "2.5", "1..6", "4", "override_of_4"),
    "flick_stroke": ("700", "700", "400..1200", "none", "shipped"),
    "idle_tab_thickness": ("14", "14", "10..20", "none", "shipped"),
}


def golden_report():
    lines = [MACHINE_HEADER, "ml.schema=1",
             "# one key=value per line; unknown means the app could not read it, never zero",
             "ml.profile=per-host"]
    for param, values in GOLDEN_PARAMS.items():
        for suffix, value in zip(("effective", "shipped", "range", "written", "state"), values):
            lines.append("ml.param.%s.%s=%s" % (param, suffix, value))
    lines += ["ml.switch.edgeSensorSummon=on", "ml.switch.absoluteMouseMode=on",
              "ml.switch.relativeMouseAsAbsolute=off", "ml.switch.imeLocalComposition=on",
              "ml.switch.muteOnFocusLoss=on", "ml.switch.backgroundGamepad=on",
              "ml.pointer.mouse_mode=remote", "ml.pointer.path=corehid (absolute)",
              "ml.pointer.absolute=yes", "ml.video.present=yes",
              "ml.video.frames.received=12000", "ml.video.frames.decoded=11980",
              "ml.video.frames.rendered=11900", "ml.video.fps=119.4", "ml.video.jitter_ms=2.1",
              "ml.video.bytes=1073741824", "ml.video.format=hevc",
              "ml.reconnect.present=yes", "ml.reconnect.attempt=2", "ml.reconnect.max=10",
              "ml.reconnect.pending=no", "ml.reconnect.host_confirmed_gone=no",
              "ml.controllers.present=yes", "ml.controllers.sessions=1",
              "ml.controllers.recording=yes", "ml.controllers.driver=AppleUserHIDDrivers",
              "ml.controllers.arrivals=yes", "ml.controllers.slot.0=xbox",
              "ml.controllers.slot.1=ps", "ml.controllers.caps.analog_triggers=yes",
              "ml.controllers.caps.rumble=yes", "ml.controllers.group_count=2",
              "ml.controllers.group_count_is_physical_devices=no",
              "ml.controllers.group.0.vid=045e", "ml.controllers.group.0.pid=0b12",
              "ml.controllers.group.0.family=xbox", "ml.controllers.group.0.type_map=0",
              "ml.controllers.group.0.transport=usb",
              "ml.controllers.group.0.battery_percent=unknown",
              "ml.controllers.group.0.nodes=1", "ml.controllers.group.1.vid=054c",
              "ml.controllers.group.1.pid=0ce6", "ml.controllers.group.1.family=ps",
              "ml.controllers.group.1.type_map=1", "ml.controllers.group.1.transport=bluetooth",
              "ml.controllers.group.1.battery_percent=87", "ml.controllers.group.1.nodes=2",
              ""]
    return "[report]\napp: MoonlightEnhanced\n\n" + "\n".join(lines)


def golden_declaration(report_text):
    declaration = emit_declaration(report_text)
    declaration["observer"] = "fixture"
    for entry in declaration["items"]:
        entry["observed"] = True
        entry["note"] = "fixture observation"
    return declaration


def mutated_copy(old, new):
    """This file with one answer flipped, on disk, for a contract run against it."""
    source = read(SELF)
    # Only the grading half is mutable. Everything from the MUTATIONS table down is the
    # harness, and it quotes the anchors verbatim -- searching the whole file would find
    # the quotation as well as the code and report every anchor as ambiguous. The child
    # copy still parses and runs, because `main()` and the entry point stay in the tail.
    marker = "\nMUTATIONS = ("
    if source.count(marker) != 1:
        raise AssertionError("could not locate the grading half of this file")
    head, tail = source.split(marker, 1)
    if head.count(old) != 1:
        raise AssertionError("mutation anchor is not unique in the grading half: %r" % old)
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=tempfile.gettempdir())
    handle.write(head.replace(old, new) + marker + tail)
    handle.close()
    return handle.name


def fail(message, failures):
    print("FAIL %s" % message)
    failures.append(message)


def ok(message):
    print("ok   %s" % message)


def contract(tool, workdir, failures, label):
    """The assertions any copy of this tool has to satisfy. A weakened copy must trip one."""
    def write(name, text):
        path = os.path.join(workdir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def verdicts(matrix):
        return {item["id"]: item["verdict"] for item in matrix["items"]}

    golden = golden_report()
    # The one declaration used raw, so C6 has a statement that belongs to a *different*
    # report than the one it is graded against.
    full_path = write("full.json", json.dumps(golden_declaration(golden)))

    def grade_with(report_path, declare=None):
        argv = [report_path]
        if declare:
            argv += ["--declare", declare]
        matrix, raw = matrix_from(tool, argv)
        if matrix is None:
            failures.append("%s: could not grade %s: %s" % (label, os.path.basename(report_path), raw))
            return {}
        return verdicts(matrix)

    def grade_text(name, text, observe=True):
        """Grade `text` with a declaration bound to that very text.

        Each variant needs its own statement. Reusing the golden declaration would make
        the hash check fail every row into UNKNOWN, and the assertions below ("this row
        must not read PASS") would then hold for the wrong reason -- a weakened grader
        would survive. Binding per report keeps the only thing under test the keys.
        """
        report_path = write("%s.txt" % name, text)
        declare = None
        if observe:
            declare = write("%s.json" % name, json.dumps(golden_declaration(text)))
        return grade_with(report_path, declare)

    # C1 -- the shape a completed acceptance run has: live settings plus bound statements.
    graded = grade_text("golden", golden)
    if graded and all(v == PASS for v in graded.values()):
        ok("%s: a fully evidenced run grades every row PASS" % label)
    else:
        fail("%s: fully evidenced run did not grade PASS: %s" % (label, graded), failures)

    # C2 -- the report alone is not an acceptance run.
    graded = grade_text("golden-unobserved", golden, observe=False)
    if graded and not any(v == PASS for v in graded.values()):
        ok("%s: a report with no observer statement yields no PASS" % label)
    else:
        fail("%s: report without a declaration produced PASS: %s" % (label, graded), failures)

    # C3 -- mutation class one: a key that is not there is not a pass.
    graded = grade_text("no-machine",
                        "[report]\napp: MoonlightEnhanced\n[features]\n"
                        "edge sensor band: 12 (shipped default)\n")
    if not graded or not any(v == PASS for v in graded.values()):
        ok("%s: a report with no machine block yields no PASS" % label)
    else:
        fail("%s: missing machine block graded PASS: %s" % (label, graded), failures)

    # C4 -- mutation class two, value shape: arrivals never sent is not a pass.
    graded = grade_text("no-arrival", golden.replace("ml.controllers.arrivals=yes",
                                                     "ml.controllers.arrivals=no"))
    if graded.get("controllers-two-pads") != PASS and \
       graded.get("host-side-controller-behaviour") != PASS:
        ok("%s: an unannounced controller is not graded as announced" % label)
    else:
        fail("%s: arrivals=no graded PASS: %s" % (label, graded), failures)

    # C5 -- mutation class two, meaning shape: shipped defaults are not an exercised slider.
    defaults = golden
    for param, values in GOLDEN_PARAMS.items():
        defaults = defaults.replace("ml.param.%s.state=override_of_4" % param,
                                    "ml.param.%s.state=shipped" % param)
    defaults = defaults.replace("ml.param.summon_grace.effective=4",
                                "ml.param.summon_grace.effective=2.5")
    graded = grade_text("defaults-only", defaults)
    if graded.get("edge-sidebar-params") != PASS:
        ok("%s: six shipped defaults do not evidence the parameterised sidebar" % label)
    else:
        fail("%s: all-shipped parameters graded PASS: %s" % (label, graded), failures)

    # C6 -- a statement has to belong to the report it is grading.
    other = golden.replace("ml.video.frames.received=12000", "ml.video.frames.received=12001")
    other_path = write("other.txt", other)
    graded = grade_with(other_path, full_path)
    if graded and not any(v == PASS for v in graded.values()):
        ok("%s: a declaration bound to another report grants no PASS" % label)
    else:
        fail("%s: mismatched report_sha256 granted PASS: %s" % (label, graded), failures)

    # C7 -- a verdict key that the block does not contain at all. This is the lever a
    # future edit is most likely to pull ("absent can read as fine, it saves an issue"),
    # so the contract deletes one key each row depends on and demands the row stop
    # grading PASS. Grading a key that was never written would invent an observation.
    for drop, row in (("ml.param.summon_grace.written", "edge-sidebar-params"),
                      ("ml.controllers.caps.rumble", "host-side-controller-behaviour")):
        tightened = "\n".join(line for line in golden.splitlines()
                              if not line.startswith("%s=" % drop))
        graded = grade_text("no-%s" % drop.replace(".", "-"), tightened)
        if graded.get(row) != PASS:
            ok("%s: dropping %s holds %s back from PASS" % (label, drop, row))
        else:
            fail("%s: %s graded PASS with %s absent: %s" % (label, row, drop, graded), failures)


MUTATIONS = (
    ("a missing machine key reads as satisfied",
     "MISSING_READS_AS_SATISFIED = False", "MISSING_READS_AS_SATISFIED = True"),
    ("any value matches the key the verdict needs",
     "    return value == expected", "    return True"),
)


def self_test():
    failures = []
    workdir = tempfile.mkdtemp(prefix="hw-acceptance-")

    print("== contract on the shipped tool ==")
    contract(SELF, workdir, failures, "shipped")

    print("== contract on mutated copies ==")
    for label, old, new in MUTATIONS:
        copy = mutated_copy(old, new)
        local = []
        contract(copy, workdir, local, "mutant")
        if local:
            ok("mutation caught (%s): %s" % (label, local[0].split(":", 2)[-1].strip()))
        else:
            fail("mutation survived: %s" % label, failures)
        os.unlink(copy)

    # Parsing is strict for a reason: a duplicated or space-bearing key means the block is
    # not the block this checker was written against, and grading it would invent verdicts.
    for label, text in (("a duplicated key", golden_report().replace(
                             "ml.profile=per-host", "ml.profile=per-host\nml.profile=global")),
                        ("a key with a space", golden_report().replace(
                             "ml.profile=per-host", "ml profile=per-host"))):
        try:
            parse_machine(text)
            fail("parser accepted %s" % label, failures)
        except ReportError:
            ok("parser rejects %s" % label)

    if failures:
        print("\n%d failure(s)" % len(failures))
        return 1
    print("\nself-test ok: verdicts need both halves, missing keys never pass, and two "
          "weakened graders were refused")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", nargs="?", help="an exported diagnostics report")
    parser.add_argument("--declare", help="an observation statement bound to this report")
    parser.add_argument("--emit-declaration", action="store_true",
                        help="print a declaration skeleton for this report and exit")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        if NESTED:
            print("nested self-test refused", file=sys.stderr)
            return 2
        return self_test()

    if not args.report:
        parser.error("no report given -- this grader never guesses, and it never passes in "
                     "silence. Pass a report, or --self-test for the fixture contract.")
    report_text = read(args.report)

    if args.emit_declaration:
        print(json.dumps(emit_declaration(report_text), indent=2))
        return 0

    declaration = None
    if args.declare:
        declaration = json.loads(read(args.declare))

    try:
        matrix = grade(report_text, declaration)
    except ReportError as error:
        # An unreadable block is every row unknown, and the exit code says so. It is not a
        # pass, and it is not a crash the operator has to interpret either.
        verdicts = {"schema": int(SCHEMA), "report_sha256": report_sha256(report_text),
                    "items": [{"id": item["id"], "row": item["row"], "title": item["title"],
                               "verdict": UNKNOWN, "reason": str(error)} for item in ITEMS]}
        print(json.dumps(verdicts, indent=2) if args.json else render(verdicts))
        return 1

    print(json.dumps(matrix, indent=2) if args.json else render(matrix))
    return 0 if all(item["verdict"] == PASS for item in matrix["items"]) else 1


if __name__ == "__main__":
    sys.exit(main())
