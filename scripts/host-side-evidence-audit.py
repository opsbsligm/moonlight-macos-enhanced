#!/usr/bin/env python3
"""Judge what the streaming host is actually able to show, from the host itself.

What this file is about
-----------------------
`hardware-acceptance-check.py` grades the client half: the exported report proves a setting
was live, a person declares what they saw. The "what they saw" half has always been the part
 nobody can re-check, because it describes a second machine. This tool removes the memory
from that half by reading the host over WinRM: the ViGEmBus driver state, the Sunshine
version, and Sunshine's own words about which gamepad emulations it switched on and off.

Why the host has a say at all
-----------------------------
The client can honestly advertise a DualSense and never lie, and the row still cannot be
accepted, because Sunshine on this host prints `Gamepad ds5 is disabled due to
gamepads.ds5-sidecar-not-available` before any client connects. A PS slot verified against
that host is not verified -- the host refused to create the device. So each row that needs a
virtual pad now has a precondition owned by the host, and this tool is the only thing that
reads it.

The trap this tool exists to not fall into
------------------------------------------
`ds5-sidecar-package.json` is present on this host and says exactly one thing: the payload
was *described*. The payload is a 44 MB archive that is not there. A check that looks for a
file named `ds5` and reports "present" would grade the DS5 path as available on a host that
says the opposite in its own log. The manifest and the component are separate fields in the
snapshot for that reason, and the self-test plants that exact confusion as a mutation.

Usage:
  host-side-evidence-audit.py --collect [--host IP] [--out SNAPSHOT.json]  # needs WinRM
  host-side-evidence-audit.py --snapshot SNAPSHOT.json [--report REPORT.txt]
  host-side-evidence-audit.py --self-test
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

SELF = os.path.abspath(__file__)
# A mutated copy of this file runs from /tmp, so the fixture location is the one thing a
# child cannot derive from its own path. Without the override every mutation would "fail"
# because it could not find its evidence, which is how a harness reports strength it has.
FIXTURE_DIR = os.environ.get("HSE_FIXTURE_DIR") or os.path.join(os.path.dirname(SELF), "fixtures")
FIXTURE = os.path.join(FIXTURE_DIR, "home-pc-host-snapshot.json")
RAW_CAPTURE = os.path.join(FIXTURE_DIR, "home-pc-winrm-stdout.txt")
CLAIM_REPORT = os.path.join(FIXTURE_DIR, "home-pc-claim-report.txt")

OK, BLOCKED, UNKNOWN = "OK", "BLOCKED", "UNKNOWN"

# Set when this file runs itself as a child, so a self-test can never recurse.
NESTED = os.environ.get("HSE_GATE_NESTED") == "1"


class SnapshotError(Exception):
    """The snapshot does not describe a host we can name, so it can say nothing."""


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_snapshot(path):
    try:
        data = json.loads(read(path))
    except (OSError, ValueError) as error:
        raise SnapshotError("cannot read the snapshot: %s" % error)
    if not isinstance(data, dict):
        raise SnapshotError("the snapshot is not an object")
    return data


# --------------------------------------------------------------------------- host facts

def host_identity(snapshot):
    """Which host, which build. A precondition on every verdict below, not a row.

    The same reasoning `hardware-acceptance-check.py` applies to the client build applies
    here: "Sunshine on some machine" cannot carry a conclusion about a virtual pad, because
    the emulations a host offers are version-specific. The version string is what the host
    itself printed; a snapshot without it describes a machine, not a build.
    """
    version = str(snapshot.get("version", ""))
    if snapshot.get("winrm_rc") != 0:
        return False, "WinRM did not complete (rc=%r) -- nothing below was read from the host" % snapshot.get("winrm_rc")
    if not str(snapshot.get("host", "")).strip():
        return False, "the snapshot names no host"
    match = re.search(r"v\d{4}\.\d+\.\d+", version)
    if not match:
        return False, "the host did not report a Sunshine version (got %r)" % version
    if not [c for c in snapshot.get("config", []) if isinstance(c, str) and "=" in c]:
        # The config file is the one artefact that exists only in a Sunshine installation.
        # A snapshot with a version line but no config was read from a machine where the
        # install directory could not be opened, so its driver and log claims are unverified.
        return False, "the host reported a version but no Sunshine configuration lines -- " \
                      "the install directory was never read, so this snapshot may not " \
                      "describe a Sunshine installation at all"
    return True, "host %s running Sunshine %s" % (snapshot["host"], match.group(0))


def vigem_state(snapshot):
    """The ViGEmBus *driver*. It is not a service, so the service list is the wrong place."""
    drivers = [d for d in snapshot.get("vigem", []) if isinstance(d, dict)]
    running = [d for d in drivers if str(d.get("state", "")).lower() == "running"]
    if running:
        return True, "ViGEmBus is Running (%s)" % running[0].get("path", "path unknown")
    if drivers:
        return False, "ViGEmBus present but %s -- the host cannot create a virtual pad while " \
                      "the driver is not running" % sorted({str(d.get("state")) for d in drivers})
    return False, "no ViGEmBus driver on the host -- no virtual pad of any kind can appear"


def log_records(snapshot):
    """Every log line, newest first, whatever order the snapshot's list arrived in.

    The ordering is the point. Sunshine rotates its log files and a collector lists them in
    whatever order it happened to walk them, so a reader that trusts the list order can be
    handed a refusal from October and an enablement from November in either order -- and the
    one that reads decides whether an old refusal can veto a path the host later started.
    The stamp is what settles that, so the stamp is what is used: `mtime` is an ISO-ish
    string, so sorting the text sorts the time, and the lines inside one file are reversed
    because a log file reads oldest first.
    """
    entries = [entry for entry in snapshot.get("logs", []) if isinstance(entry, dict)]
    ordered = sorted(entries, key=lambda entry: str(entry.get("mtime", "")), reverse=True)
    records = []
    for entry in ordered:
        records.extend(reversed([str(line) for line in entry.get("lines", [])]))
    return records


def emulation_state(snapshot, keyword):
    """What Sunshine said about one emulation last, in its own words.

    Only the newest mention counts, in either direction: a refusal written before the
    sidecar was installed does not veto the path for ever, and an enablement that the host
    switched off again afterwards does not certify it.
    """
    for line in log_records(snapshot):
        if keyword not in line.lower():
            continue
        if "disabled" in line.lower():
            return False, line.strip()
        return True, line.strip()
    return None, "the host logs never mention the %s emulation -- the snapshot cannot say " \
                 "whether it was offered" % keyword


def ds5_installed(snapshot):
    """The payload, not the manifest that describes it."""
    return bool(snapshot.get("ds5_sidecar_installed"))


def motion_installed(snapshot):
    return bool(snapshot.get("motion_server_installed"))


# ------------------------------------------------------------------- client-side claims

def report_slots(report_text):
    """Player types the client advertised, read from the `machine` block of a report."""
    slots = {}
    for line in report_text.splitlines():
        match = re.match(r"^ml\.controllers\.slot\.(\d+)=(\S+)$", line)
        if match:
            slots[match.group(1)] = match.group(2)
    return slots


def report_arrivals(report_text):
    for line in report_text.splitlines():
        if line.startswith("ml.controllers.arrivals="):
            return line.split("=", 1)[1].strip()
    return None


# ----------------------------------------------------------------------------- verdicts

def verdicts(snapshot, report_text=None):
    """Per-capability statements. Each says what it checked and what would change it."""
    out = []

    def add(capability, verdict, reason):
        out.append({"capability": capability, "verdict": verdict, "reason": reason})

    identified, why = host_identity(snapshot)
    if not identified:
        # Every capability verdict below is a statement about a host build. Without the
        # version the snapshot is a description of a machine, and a machine does not offer
        # or refuse an emulation -- its build does.
        return [{
            "capability": "host-identity",
            "verdict": UNKNOWN,
            "reason": "host identity unresolved: %s -- no capability below can be judged" % why,
        }]

    add("host-identity", OK, why)

    can_virtualise, vigem_reason = vigem_state(snapshot)
    add("xbox-360-emulation", OK if can_virtualise else BLOCKED, vigem_reason)

    for capability, keyword, installed, component in (
        ("ds5-emulation", "ds5", ds5_installed(snapshot), "the DS5 sidecar payload"),
        ("switch-emulation", "switch", motion_installed(snapshot), "the motion server"),
    ):
        offered, evidence = emulation_state(snapshot, keyword)
        if offered is False and not installed:
            add(capability, BLOCKED, "%s -- and %s is not installed, so this host cannot show "
                                     "this pad type whatever the client advertises" % (evidence, component))
        elif offered is False:
            add(capability, BLOCKED, evidence)
        elif offered is None and not installed:
            add(capability, UNKNOWN, "%s The host snapshot also has no %s, so the path is "
                                     "neither confirmed working nor confirmed refused"
                % (evidence, component))
        else:
            add(capability, OK, evidence)

    if report_text is not None:
        add("advertised-versus-host", *contradiction(snapshot, report_text))

    return out


def contradiction(snapshot, report_text):
    """The client's own claim tested against what the host was willing to build.

    This is the only check in the file that can turn a green-looking acceptance run red
    after the fact: a PS slot the client advertised, on a host that printed its refusal to
    emulate a DualSense before the session started, means nobody ever saw a PS pad on the
    host, however confident the observation note reads.
    """
    slots = report_slots(report_text)
    if not slots:
        return UNKNOWN, "the report advertises no player slot -- there is no client claim to " \
                        "compare the host's answer against"
    arrivals = report_arrivals(report_text)
    if arrivals != "yes":
        # A report can carry slot rows and still describe a session where no pad was ever
        # announced: the rows say what the client would offer, the arrivals key says whether
        # it told the host. Without that second half a stale block from an earlier session
        # would count as a claim, and the tool would grade a pad nobody could have seen.
        return BLOCKED, "the report lists slots %s but says controller arrivals were never " \
                        "advertised (%r) -- a slot the host was never told about cannot have " \
                        "been observed on it" % (", ".join(sorted(slots)), arrivals)
    can_virtualise, vigem_reason = vigem_state(snapshot)
    if not can_virtualise:
        return BLOCKED, "the client advertised slots %s but %s" % (
            ", ".join(sorted(slots)), vigem_reason)
    problems = []
    for slot, declared in sorted(slots.items()):
        if declared == "ps":
            offered, evidence = emulation_state(snapshot, "ds5")
            if offered is False or (offered is None and not ds5_installed(snapshot)):
                problems.append("slot %s claims ps: %s" % (slot, evidence))
        elif declared == "nintendo":
            offered, evidence = emulation_state(snapshot, "switch")
            if offered is False or (offered is None and not motion_installed(snapshot)):
                problems.append("slot %s claims nintendo: %s" % (slot, evidence))
        elif declared != "xbox":
            # The three names are what the client can advertise. A fourth is a report this
            # tool has no host-side mapping for, and grading it as satisfied would let a
            # renamed or invented type collect a PASS nobody argued for.
            problems.append("slot %s declares %r, which this tool cannot map to a host-side "
                            "path" % (slot, declared))
    if problems:
        return BLOCKED, "; ".join(problems)
    return OK, "every advertised slot (%s) has a host-side path that the host did not refuse" % \
               ", ".join("%s=%s" % (slot, slots[slot]) for slot in sorted(slots))


def render(rows):
    width = max(len(row["capability"]) for row in rows)
    return "\n".join("%-*s  %-8s  %s" % (width, row["capability"], row["verdict"], row["reason"])
                     for row in rows)


def verify_expectations(rows, expect):
    """Replay the reviewed verdicts of the real host, so CI can run this without a host.

    The judgement form without `--expect` asks "is the host healthy", which on this host is
    a legitimate red: the DS5 sidecar payload genuinely is not installed. What CI can and
    has to assert is that the audit still reaches the reviewed answers -- if the identity
    stops resolving or a refusal stops being read, the rows change and this goes red. An
    expectation nobody reviewed is a name typo, so an unknown capability is its own failure
    rather than a silent skip.
    """
    reached = {row["capability"]: row for row in rows}
    problems = []
    for pair in expect.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            problems.append("malformed expectation %r" % pair)
            continue
        capability, wanted = pair.split("=", 1)
        capability, wanted = capability.strip(), wanted.strip().upper()
        if capability not in reached:
            problems.append("%s was never judged (judged: %s)"
                            % (capability, ", ".join(sorted(reached))))
        elif reached[capability]["verdict"] != wanted:
            problems.append("%s reads %s, expected %s -- %s"
                            % (capability, reached[capability]["verdict"], wanted,
                               reached[capability]["reason"]))
    for problem in problems:
        print("MISMATCH %s" % problem)
    if problems:
        return 1
    print("matches the reviewed host state: %s" % expect)
    return 0


# ------------------------------------------------------------------------------ collect

# The host is read in one round trip, and every value that is not ours travels as base64
# UTF-8. That is not decoration: this host prints `Sunshine version:
# v2026.925.152547.<two Chinese characters>` because its locale is `zh`, and an earlier
# version of this script replaced every byte above 0x7E with `?` to keep the channel
# single-byte. It turned the one sentence that names the host build into a string no other
# tool could reproduce, and a snapshot that cannot be byte-compared to the host it came
# from is a transcription, not evidence.
POWERSHELL = r'''
$ProgressPreference="SilentlyContinue"
function Emit-B64([string]$tag, [string]$text) {
  $b = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
  $t = $tag.Replace("`r", "").Replace("`n", "")
  $b -replace '^(.{0,' + $t.Length + '})', ('$1|') -replace ('^' + [regex]::Escape($t) + '\|'), ($t + '|' + $b.Substring(0, 0) + '|') | Out-Null
  $t + "|" + $b
}
"###VIGEM"
@(Get-WmiObject Win32_SystemDriver | Where-Object { $_.Name -match "vigem" }) | ForEach-Object { "DRV|" + $_.Name + "|" + $_.State + "|" + $_.PathName }
"###XDEVICE"
$x = @(Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match "VID_045E.PID_028E" })
"XCOUNT|" + $x.Count
$x | ForEach-Object { "XDEV|" + $_.InstanceId + "|" + $_.Status }
"###DS5"
"DS5COUNT|" + @(Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match "VID_054C" }).Count
"###COMPONENTS"
@(Get-ChildItem "C:\Program Files\Sunshine" -Recurse -Include "*ds5*","*sidecar*","*motion*" -ErrorAction SilentlyContinue) | ForEach-Object { Emit-B64 "COMP" $_.Name }
"###CONFIG"
$c = @(Get-Content "C:\Program Files\Sunshine\config\sunshine.conf" -Encoding UTF8 -ErrorAction SilentlyContinue)
"CONFCOUNT|" + $c.Count
foreach ($l in $c) { if ($l -match "=") { Emit-B64 "CONF" $l } }
"###LOGS"
@(Get-ChildItem "C:\Program Files\Sunshine\config\logs_archive" -Filter "sunshine.log*" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3) | ForEach-Object {
  $hits = @(Select-String -Path $_.FullName -Pattern "Gamepad|gamepad|ViGEm|sidecar|motion" -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -First 8 | ForEach-Object { $_.Line })
  "LOGF|" + $_.Name + "|" + $_.LastWriteTime.ToString("s") + "|" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($hits -join "`n")))
}
"###VERSION"
Emit-B64 "VER" (((& "C:\Program Files\Sunshine\Sunshine.exe" --version 2>&1) -join " "))
"###END"
'''


def parse_capture(text, host, winrm_rc=0):
    """The host's transcript as a snapshot. Everything the judge reads goes through here.

    Split out from `collect` so the half that turns a transcript into fields is reachable
    without a Windows machine: `--parse-capture` runs it on a transcript captured once from
    the real host, so a parser that silently drops a log file or reads a manifest as a
    component fails where a laptop can see it.
    """
    snapshot = {"host": host, "winrm_rc": winrm_rc, "vigem": [], "xbox_360_devices": [],
                "xbox_360_count": 0, "ds5_devices": 0, "sidecar": [], "config": [],
                "logs": [], "version": ""}
    for line in text.replace("\r\n", "\n").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        tag, rest = line.split("|", 1)
        parts = rest.split("|")

        def decoded(index):
            if len(parts) <= index:
                return ""
            try:
                return base64.b64decode(parts[index]).decode("utf-8", "replace")
            except Exception:
                return ""

        if tag == "DRV":
            snapshot["vigem"].append({"name": parts[0], "state": parts[1],
                                      "path": parts[2] if len(parts) > 2 else ""})
        elif tag == "XDEV":
            snapshot["xbox_360_devices"].append({"instance_id": parts[0], "status": parts[1]})
        elif tag == "XCOUNT":
            snapshot["xbox_360_count"] = int(rest or 0)
        elif tag == "DS5COUNT":
            snapshot["ds5_devices"] = int(rest or 0)
        elif tag == "COMP":
            snapshot["sidecar"].append(decoded(0))
        elif tag == "CONF":
            value = decoded(0)
            if value.strip():
                snapshot["config"].append(re.sub(r"\s+", " ", value).strip())
        elif tag == "LOGF":
            payload = decoded(2)
            snapshot["logs"].append({"file": parts[0], "mtime": parts[1],
                                     "lines": [l for l in payload.splitlines() if l.strip()]})
        elif tag == "VER":
            snapshot["version"] = re.sub(r"\s+", " ", decoded(0)).strip()

    names = [n.lower() for n in snapshot["sidecar"]]
    # A manifest whose payload was never unpacked has the same name stem as the component,
    # so the extension is what separates "described" from "installed".
    snapshot["ds5_manifest"] = any("ds5-sidecar-package.json" in n for n in names)
    snapshot["ds5_sidecar_installed"] = any("ds5" in n and n.endswith(".exe") for n in names)
    snapshot["motion_server_installed"] = any("motion" in n and n.endswith(".exe") for n in names)
    return snapshot


MUTATIONS = (
    # Each entry is one way this judge could keep printing verdicts while meaning less, plus
    # the one check that has to go red when it does. Naming the check is not decoration: an
    # earlier version of this table accepted "anything went red", and once the mutant
    # children lost their fixtures *everything* went red, which read as a perfect mutation
    # score built on nothing. An anchor has to appear exactly once above the table, so a
    # refactor that moves a rule out of the mutable half fails loudly rather than quietly
    # stopping the mutation.
    ("the newest log line stops outranking the older one",
     "ordered = sorted(entries, key=lambda entry: str(entry.get(\"mtime\", \"\")), "
     "reverse=True)",
     "ordered = list(entries)",
     "an enablement older than the refusal does not certify the path"),
    ("the manifest that describes a payload reads as the payload",
     '    return bool(snapshot.get("ds5_sidecar_installed"))',
     '    return bool(snapshot.get("ds5_manifest"))',
     "the refusal says the payload is missing, not that the host is suspicious"),
    ("the host identity stops gating the capability rows",
     "    if not identified:",
     "    if False:",
     "a snapshot without a host version says nothing about any capability"),
    ("a ps slot stops being tested against the host's refusal",
     '        if declared == "ps":',
     '        if declared == "never-a-slot":',
     "a ps slot on a host that refused DS5 is held back by that refusal"),
    ("a report whose slots were never advertised still counts as a claim",
     '    if arrivals != "yes":',
     "    if False:",
     "slot rows the client never advertised as arriving are not taken as evidence"),
    ("a slot type this tool cannot map stops being refused",
     '        elif declared != "xbox":',
     '        elif declared == "never-xbox":',
     "a slot type with no host-side mapping is refused rather than collected as a pass"),
    # The parsing half: the two ways a transcript stops being evidence about components.
    ("the collector reads a manifest as an installed component",
     '    snapshot["ds5_sidecar_installed"] = any("ds5" in n and n.endswith(".exe") '
     'for n in names)',
     '    snapshot["ds5_sidecar_installed"] = any("ds5" in n for n in names)',
     "the transcript captured from the host parses into the shipped snapshot"),
    ("the collector transcodes the host's version instead of keeping it",
     '            snapshot["version"] = re.sub(r"\\s+", " ", decoded(0)).strip()',
     '            snapshot["version"] = re.sub(r"\\s+", " ", decoded(0)).strip().encode(\n'
     '                "ascii", "replace").decode("ascii")',
     "the transcript captured from the host parses into the shipped snapshot"),
    # The collector's own branch is judged, not just parsed: removing the import makes the
    # collection die on an undefined name, which is the exact defect this check was written
    # over. It stays green on every other mutant, so it pins the branch and not the file.
    ("the collect branch loses the module it writes its snapshot through",
     "import tempfile\n",
     "",
     "the collected snapshot is judged in the same run that wrote it"),
)

# A copy that changes no behaviour at all. The contract has to be green on it, or "mutation
# caught" only proves the harness stopped working: the green baseline is what gives the red
# mutants their meaning. This is the check that was missing while the fixtures were missing.
BENIGN = ("a comment that changes nothing",
          "def host_identity(snapshot):",
          "def host_identity(snapshot):  # unchanged on purpose\n",
          "the shipped snapshot names the host build")


# --------------------------------------------------------------------------- self-test

def ok(message):
    print("ok   %s" % message)


def fail(message, failures):
    print("FAIL %s" % message)
    failures.append(message)


def check_mutation(local_failures, expected, label, failures, caught):
    """Say whether a copy went red on the check that owns the rule it bent.

    `expected` names the check, because "something went red" is not the claim: a copy that
    could not read its own fixtures goes red everywhere, and that used to be scored as a
    caught mutation. The benign copy runs through here with `caught=False` so a harness that
    stopped working has to report it on the way.
    """
    matched = [message for message in local_failures if expected in message]
    if caught and matched:
        ok("mutation caught (%s): %s" % (label, expected))
    elif caught:
        fail("mutation survived %s -- %s stayed green%s"
             % (label, expected,
                (" (other checks went red: %s)" % local_failures[0]) if local_failures else ""),
             failures)
    elif not local_failures:
        ok("baseline held (%s): %s" % (label, expected))
    else:
        fail("a copy that changes nothing went red: %s" % local_failures[0], failures)


def write(workdir, name, text):
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run_tool(tool, argv, env_extra=None):
    # The fixture location is handed down, not derived. A mutated copy lives in /tmp, where
    # `__file__` points at a directory with no fixtures beside it; without this the child
    # dies on a missing snapshot, the parent sees an empty verdict list, and every mutation
    # reads as "caught" for a reason that has nothing to do with the rule it bent. Measured:
    # with the variable stripped, a copy that differs from the original by one comment still
    # reported all 7 mutations caught.
    env = dict(os.environ, HSE_GATE_NESTED="1", HSE_FIXTURE_DIR=FIXTURE_DIR)
    if env_extra:
        env.update(env_extra)
    done = subprocess.run([sys.executable, tool] + argv, capture_output=True, text=True, env=env)
    if done.returncode == 2 and "nested self-test refused" in done.stderr:
        return done.returncode, done.stdout, done.stderr
    if done.returncode not in (0, 1):
        # Anything past the two verdict codes is the tool failing to answer, which must not
        # be mistaken for a verdict of its own.
        raise AssertionError("%s answered %s: %s" % (os.path.basename(tool), done.returncode,
                                                     (done.stderr or done.stdout)[-300:]))
    return done.returncode, done.stdout, done.stderr


def rows_from(tool, workdir, name, snapshot, report=None):
    """Ask a copy of this tool about a snapshot, and get its verdicts back as data."""
    path = write(workdir, name, json.dumps(snapshot, ensure_ascii=True))
    argv = ["--snapshot", path, "--json"]
    if report is not None:
        argv += ["--report", write(workdir, name + ".report.txt", report)]
    code, out, err = run_tool(tool, argv)
    try:
        return json.loads(out)
    except ValueError:
        return [{"capability": "output", "verdict": UNKNOWN, "reason": "rc=%s %s%s" % (code, out, err)}]


def graded(rows, capability):
    for row in rows:
        if row["capability"] == capability:
            return row["verdict"]
    return None


def reason_for(rows, capability):
    for row in rows:
        if row["capability"] == capability:
            return row["reason"]
    return ""


def with_field(snapshot, key, value):
    copy = json.loads(json.dumps(snapshot))
    copy[key] = value
    return copy


def without_vigem(snapshot):
    copy = json.loads(json.dumps(snapshot))
    copy["vigem"] = []
    return copy


def blind_version(snapshot):
    copy = json.loads(json.dumps(snapshot))
    copy["version"] = ""
    return copy


def logs_snapshot(refusal_mtime, refusal_lines, enablement_mtime, enablement_lines):
    """A host that changed its mind, with the two files always listed in the same order.

    The listing order is the same in every shape the self-test builds -- the enablement file
    first -- and it is deliberately the wrong clue: in one shape the refusal really is the
    newer file, so a reader that trusts the listing says the path is available when the host
    closed it. Only the two `mtime` fields tell the shapes apart, and the stamps are passed
    in apart from the text they date, because which mention came last is the whole question:
    a collector that walked its directory in name order, or a host whose rotation numbers and
    timestamps disagree, hands exactly this shape to the reader.
    """
    return {"host": "192.0.2.1", "winrm_rc": 0, "version": "Sunshine version: v2026.925.1",
            "vigem": [{"name": "ViGEmBus", "state": "Running", "path": "x"}],
            "sidecar": ["ds5-sidecar.exe"],
            # One config line, or the identity precondition below refuses the snapshot and
            # the two timestamp checks are answered by "nothing was read" instead of by the
            # logs. A synthetic snapshot has to earn the verdict it asks about.
            "config": ["sunshine_name = HOME-PC"], "xbox_360_count": 0,
            "ds5_devices": 0, "xbox_360_devices": [], "ds5_manifest": True,
            "ds5_sidecar_installed": True, "motion_server_installed": False,
            "logs": [{"file": "sunshine.log00001", "mtime": enablement_mtime,
                      "lines": enablement_lines},
                     {"file": "sunshine.log00002", "mtime": refusal_mtime,
                      "lines": refusal_lines}]}


PS_REPORT = ("[machine]\nml.controllers.present=yes\nml.controllers.arrivals=yes\n"
             "ml.controllers.slot.0=ps\n")
XBOX_REPORT = ("[machine]\nml.controllers.present=yes\nml.controllers.arrivals=yes\n"
               "ml.controllers.slot.0=xbox\n")
TWO_SLOT_REPORT = ("[machine]\nml.controllers.present=yes\nml.controllers.arrivals=yes\n"
                   "ml.controllers.slot.0=xbox\nml.controllers.slot.1=ps\n")
SILENT_REPORT = ("[machine]\nml.controllers.present=yes\nml.controllers.arrivals=no\n"
                 "ml.controllers.slot.0=xbox\n")
REFUSAL = ["[2026-10-30 22:59:05.186]: Warning: Gamepad ds5 is disabled due to "
           "gamepads.ds5-sidecar-not-available"]
ENABLEMENT = ["[2026-11-01 07:00:00.000]: Info: Gamepad ds5 enabled"]
# The two file stamps, held apart from the lines they date. Sunshine writes its own
# timestamp into every line and rotates whole files, so the collector's `mtime` is a second,
# independent statement of order, and it is the one the judge has to use. The two shapes the
# self-test builds below give the refusal and the enablement these stamps the other way
# round; the log text stays where it was, so only the order-in-time flips.
STAMPS = ("2026-10-30T22:59:05", "2026-11-01T07:00:00")


def contract(tool, workdir, failures, label):
    """What any copy of this tool has to say. A weakened copy trips at least one check."""
    base = load_snapshot(FIXTURE)

    def check(condition, message, detail=""):
        if condition:
            ok("%s: %s" % (label, message))
        else:
            fail("%s: %s%s" % (label, message, (" -- " + detail) if detail else ""), failures)

    rows = rows_from(tool, workdir, "fixture.json", base)
    check(graded(rows, "host-identity") == OK,
          "the shipped snapshot names the host build", reason_for(rows, "host-identity"))
    check(graded(rows, "xbox-360-emulation") == OK,
          "a running ViGEmBus reads as able to host a virtual pad",
          reason_for(rows, "xbox-360-emulation"))
    check(graded(rows, "ds5-emulation") == BLOCKED,
          "a DS5 manifest without its payload does not read as an available path",
          reason_for(rows, "ds5-emulation"))
    check("not installed" in reason_for(rows, "ds5-emulation"),
          "the refusal says the payload is missing, not that the host is suspicious",
          reason_for(rows, "ds5-emulation"))

    rows = rows_from(tool, workdir, "ps.json", base, PS_REPORT)
    # The verdict alone is not the claim: a reader that refused the slot for any reason at
    # all would print a red row here. The refusal has to be the host's own words about the
    # emulation, which is the only thing that makes the row a statement about the host.
    check(graded(rows, "advertised-versus-host") == BLOCKED
          and "ds5-sidecar-not-available" in reason_for(rows, "advertised-versus-host"),
          "a ps slot on a host that refused DS5 is held back by that refusal",
          reason_for(rows, "advertised-versus-host"))
    rows = rows_from(tool, workdir, "unknown.json", base,
                     "[machine]\nml.controllers.present=yes\nml.controllers.arrivals=yes\n"
                     "ml.controllers.slot.0=dreamcast\n")
    check(graded(rows, "advertised-versus-host") == BLOCKED
          and "cannot map" in reason_for(rows, "advertised-versus-host"),
          "a slot type with no host-side mapping is refused rather than collected as a pass",
          reason_for(rows, "advertised-versus-host"))
    rows = rows_from(tool, workdir, "xbox.json", base, XBOX_REPORT)
    check(graded(rows, "advertised-versus-host") == OK,
          "an xbox slot on a host that can emulate one is not held back",
          reason_for(rows, "advertised-versus-host"))
    rows = rows_from(tool, workdir, "two.json", base, TWO_SLOT_REPORT)
    check(graded(rows, "advertised-versus-host") == BLOCKED,
          "one refused slot holds the whole report back even beside an accepted one",
          reason_for(rows, "advertised-versus-host"))
    rows = rows_from(tool, workdir, "silent.json", base, SILENT_REPORT)
    check(graded(rows, "advertised-versus-host") == BLOCKED,
          "slot rows the client never advertised as arriving are not taken as evidence",
          reason_for(rows, "advertised-versus-host"))

    rows = rows_from(tool, workdir, "blind.json", blind_version(base), PS_REPORT)
    check(len(rows) == 1 and rows[0]["capability"] == "host-identity"
          and rows[0]["verdict"] == UNKNOWN,
          "a snapshot without a host version says nothing about any capability", str(rows))
    rows = rows_from(tool, workdir, "novigem.json", without_vigem(base), XBOX_REPORT)
    check(graded(rows, "xbox-360-emulation") == BLOCKED
          and graded(rows, "advertised-versus-host") == BLOCKED,
          "without ViGEmBus no advertised slot survives, including the xbox one", str(rows))
    rows = rows_from(tool, workdir, "rc.json", with_field(base, "winrm_rc", 1), PS_REPORT)
    check(len(rows) == 1 and rows[0]["verdict"] == UNKNOWN,
          "a failed WinRM run yields no capability verdict rather than a silent pass", str(rows))
    rows = rows_from(tool, workdir, "installed.json",
                     with_field(base, "ds5_sidecar_installed", True), PS_REPORT)
    check(graded(rows, "ds5-emulation") == BLOCKED,
          "an installed payload is still judged on the host's own words",
          reason_for(rows, "ds5-emulation"))

    # Which log mention wins has to come from the timestamp, never from list order.
    # Both shapes list the refusal file first, so the listing order is identical between
    # them and only the two `mtime` fields differ. A judge that trusted the list would
    # answer both the same way, which is the failure this pair exists to catch.
    older, newer = STAMPS
    refusal_written_last = logs_snapshot(newer, REFUSAL, older, ENABLEMENT)
    enablement_written_last = logs_snapshot(older, REFUSAL, newer, ENABLEMENT)
    rows = rows_from(tool, workdir, "stale-enable.json", refusal_written_last, PS_REPORT)
    check(graded(rows, "ds5-emulation") == BLOCKED,
          "an enablement older than the refusal does not certify the path",
          reason_for(rows, "ds5-emulation"))
    rows = rows_from(tool, workdir, "stale-refusal.json", enablement_written_last, PS_REPORT)
    check(graded(rows, "ds5-emulation") == OK,
          "a refusal older than the enablement does not veto the path for ever",
          reason_for(rows, "ds5-emulation"))
    # The pair above only says something if the two snapshots really are opposites. Built
    # from one call, or with the log text moved along with the stamps, they would be the same
    # shape twice and an honest reader could not be asked for both answers.
    def stamps_and_text(snapshot):
        return [e["mtime"] for e in snapshot["logs"]], [e["lines"] for e in snapshot["logs"]]

    refusal_stamps, refusal_text = stamps_and_text(refusal_written_last)
    enablement_stamps, enablement_text = stamps_and_text(enablement_written_last)
    check(refusal_text == enablement_text and refusal_stamps != enablement_stamps
          and sorted(refusal_stamps) == sorted(enablement_stamps),
          "the two 'changed its mind' snapshots differ only in which file the stamp dates",
          "%r vs %r" % (refusal_stamps, enablement_stamps))

    # The collector's own half: the transcript captured from the real host has to parse into
    # the snapshot this file ships, or the shipped snapshot is a transcription.
    code, out, err = run_tool(tool, ["--parse-capture", RAW_CAPTURE, "--json"])
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = None
    check(parsed is not None, "the captured transcript parses without an error", (out + err)[:200])
    if parsed is not None:
        comparable = dict(parsed)
        comparable.pop("winrm_rc", None)
        expected = dict(base)
        expected.pop("winrm_rc", None)
        check(comparable == expected,
              "the transcript captured from the host parses into the shipped snapshot",
              "differing fields: " + ", ".join(sorted(k for k in set(comparable) | set(expected)
                                                      if comparable.get(k) != expected.get(k))))

    rows = rows_from(tool, workdir, "claim.json", base, read(CLAIM_REPORT))
    check(graded(rows, "advertised-versus-host") == BLOCKED
          and "ds5-sidecar-not-available" in reason_for(rows, "advertised-versus-host"),
          "the committed claim report is held back by the host's own refusal",
          reason_for(rows, "advertised-versus-host"))

    # The collector's own branch, end to end. Nothing in any gate ever ran `--collect`: it
    # needs a Windows host, and it carried an undefined name -- `tempfile` was used and never
    # imported -- so the first real collection would have died with a traceback after writing
    # its own file. A stub `winrm` answers with the captured transcript, which puts the whole
    # branch (password file, parse, write, judge) inside a check a laptop can run.
    stub = write(workdir, "winrm.py",
                 "import os\n"
                 "class _Result:\n"
                 "    def __init__(self, payload, status):\n"
                 "        self.std_out, self.status_code = payload, status\n"
                 "class Session:\n"
                 "    def __init__(self, *args, **kwargs):\n"
                 "        pass\n"
                 "    def run_ps(self, script):\n"
                 "        with open(os.environ['HSE_STUB_CAPTURE'], 'rb') as handle:\n"
                 "            return _Result(handle.read(), 0)\n")
    collected = os.path.join(workdir, "collected.json")
    code, out, err = run_tool(
        tool, ["--collect", "--host", "stub-host", "--user", "u",
               "--password-file", write(workdir, "pw.txt", "stub\n"), "--out", collected],
        {"PYTHONPATH": os.path.dirname(stub), "HSE_STUB_CAPTURE": RAW_CAPTURE})
    written = None
    try:
        with open(collected, encoding="utf-8") as handle:
            written = json.load(handle)
    except (OSError, ValueError):
        written = None
    check(written is not None and written.get("host") == "stub-host"
          and "v2026." in str(written.get("version", "")),
          "the collect branch writes the snapshot it read from the host",
          "collect answered rc=%s out=%s err=%s" % (code, out[-200:], err[-300:]))
    check("host-identity" in out and "stub-host" in out
          and "ds5-sidecar-not-available" in out,
          "the collected snapshot is judged in the same run that wrote it",
          "collect answered rc=%s out=%s err=%s" % (code, out[-200:], err[-300:]))

    for label_shape, text in (("a duplicated slot row", "ml.controllers.slot.0=xbox\n"
                                                        "slot.0=xbox\n"),
                              ("a malformed slot row", "ml.controllers.slot.0 xbox")):
        if report_slots(text) == {"0": "xbox"} and label_shape.startswith("a duplicated"):
            ok("%s: %s still yields the slot it names" % (label, label_shape))
        elif label_shape.startswith("a malformed") and report_slots(text) == {}:
            ok("%s: %s is not read as a slot" % (label, label_shape))
        else:
            fail("%s: report_slots misread %s: %r" % (label, label_shape, report_slots(text)),
                 failures)


def mutated_copy(old, new):
    """This file with one answer flipped, on disk, for a contract run against it."""
    source = read(SELF)
    # Only the half above the table is mutable. The table quotes each anchor verbatim, so
    # searching the whole file would find the quotation as well as the code and report every
    # anchor as ambiguous; the child still runs, because `main()` stays below the marker.
    marker = "\nMUTATIONS = ("
    if source.count(marker) != 1:
        raise AssertionError("could not locate the mutable half of this file")
    head, tail = source.split(marker, 1)
    if head.count(old) != 1:
        raise AssertionError("mutation anchor is not unique in the mutable half: %r" % old)
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=tempfile.gettempdir())
    handle.write(head.replace(old, new) + marker + tail)
    handle.close()
    return handle.name


def self_test():
    failures = []
    workdir = tempfile.mkdtemp(prefix="host-evidence-")

    print("== contract on the shipped tool ==")
    contract(SELF, workdir, failures, "shipped")

    # The baseline that makes every red mutant below mean something: a copy that changes no
    # behaviour has to be as green as the shipped file. Without this, a harness that stopped
    # reading its own fixtures reports every mutation as caught.
    benign_label, benign_old, benign_new, benign_expect = BENIGN
    benign = mutated_copy(benign_old, benign_new)
    local = []
    contract(benign, workdir, local, "benign")
    check_mutation(local, benign_expect, benign_label, failures, caught=False)
    os.unlink(benign)

    print("== contract on mutated copies ==")
    for label, old, new, expected in MUTATIONS:
        copy = mutated_copy(old, new)
        local = []
        contract(copy, workdir, local, "mutant")
        check_mutation(local, expected, label, failures, caught=True)
        os.unlink(copy)

    if failures:
        print("\n%d failure(s)" % len(failures))
        return 1
    print("\nself-test ok: the host's refusal outranks any client claim, the newest log line "
          "wins over the older one whatever order the collector listed, a manifest without "
          "its payload is not an installed component, and %d mutations each went red on the "
          "check that owns them" % len(MUTATIONS))
    return 0


def collect(host, user, password_file):
    """Read the host. `winrm` is imported here so the judge stays importable without it."""
    import winrm

    password = read(password_file).strip()
    session = winrm.Session("http://%s:5985/wsman" % host, auth=(user, password),
                            transport="ntlm", server_cert_validation="ignore")
    result = session.run_ps(POWERSHELL)
    return parse_capture(result.std_out.decode("utf-8", "replace"), host, result.status_code)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", help="a collected host snapshot to judge")
    parser.add_argument("--collect", action="store_true", help="read the host over WinRM")
    parser.add_argument("--host", default="192.0.2.1")
    parser.add_argument("--user", default="administrator@homelab.local")
    parser.add_argument("--password-file",
                        default=os.path.expanduser("~/.config/weknora/legacy-host-ssh-password"))
    parser.add_argument("--parse-capture", help="a saved WinRM transcript to parse into a snapshot")
    parser.add_argument("--out", help="where to write a collected snapshot")
    parser.add_argument("--report", help="a client report to test the host's answer against")
    parser.add_argument("--expect",
                        help="capability=VERDICT pairs this run has to reproduce, e.g. "
                             "host-identity=OK,ds5-emulation=BLOCKED. The reviewed state of "
                             "the real host, so CI asserts the audit still reaches it instead "
                             "of asserting the host is healthy.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        if NESTED:
            print("nested self-test refused", file=sys.stderr)
            return 2
        return self_test()

    if args.parse_capture:
        parsed = parse_capture(read(args.parse_capture), args.host)
        print(json.dumps(parsed, ensure_ascii=True, indent=1, sort_keys=True))
        return 0

    if args.collect:
        snapshot = collect(args.host, args.user, args.password_file)
        text = json.dumps(snapshot, ensure_ascii=True, indent=1, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
            print("wrote %s" % args.out)
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        snapshot_path = handle.name
        with handle:
            handle.write(text)
        # This run made the file, so this run removes it. The cleanup used to hide behind
        # `HSE_OWN_TEMP`, an environment variable no caller in the repository ever set, so
        # every collection left a snapshot in the system temp directory.
        own_temp = True
    elif args.snapshot:
        snapshot_path = args.snapshot
        own_temp = False
    else:
        parser.error("nothing to judge -- pass --snapshot, --collect, --parse-capture, or "
                     "--self-test")

    report_text = read(args.report) if args.report else None
    try:
        rows = verdicts(load_snapshot(snapshot_path), report_text)
    except SnapshotError as error:
        print("UNKNOWN  every capability -- %s" % error)
        return 1
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    if args.expect:
        return verify_expectations(rows, args.expect)
    if own_temp:
        os.unlink(snapshot_path)
    return 0 if all(row["verdict"] == OK for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
