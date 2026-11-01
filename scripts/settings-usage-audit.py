#!/usr/bin/env python3
"""Report a setting the interface exposes but nothing acts on.

`SettingsStore.Settings` is the persisted shape, `SettingsObjCBridge` turns one into
the dictionary and the accessors the stream reads, and `SettingsModel` turns one into
what the window shows. A key can therefore be complete as *storage* and still be a
lie as a *control*: the pane has a switch, `loadSettings()` reads it back so the
switch remembers its position, and no code on the streaming path ever asks for it.
Wave V's audit (defaults-consistency.py) proves the value shown equals the value
used. It cannot see this defect at all -- with one stored value there is no fork to
find -- and its `unread by the stream` line is what made the defect look audited:
that sentence is true, and it was read as "this key was checked".

So this audit asks the other question of every persisted key: *does anything act on
it*. Judgement is by symbol resolution, not by grepping the key name, because the
three shapes that hide a consumer are all name changes:

  * an `@objc static func x(for key:)` accessor reaches Objective-C as the selector
    `xFor:` (or the name inside an explicit `@objc(...)` rename), so grepping
    `captureSystemShortcuts` never shows the call site that would have used it;
  * the exported dictionary renames keys on the way out -- `"yuv444":
    settings.enableYUV444`, `"microphone": settings.enableMicrophone` -- so the
    reader's string and the field's name share no characters;
  * the interface can act on a key inside itself: `unlockMaxBitrate` changes which
    slider steps exist (`bitrateSteps(unlocked:)`), which is a real effect that
    lives in no runtime file.

A read that only *reports* is not an act. `DiagnosticsReportBuilder` lists switches
so a report can tell "off" from "this build has no such switch"; a key whose only
reader is that list is still a switch that does nothing.

The plumbing that every key necessarily has is excluded on purpose, and each
exclusion is a rule with a shape rather than a file list: the export row that ships
the value, a setter that re-encodes the value it was handed, the accessor's own
read, `loadSettings()`'s assignment into the model, and the model property's own
declaration and `didSet`. The self-test breaks each one and requires the key to turn
green, because an exclusion that cannot fail is how this gate starts lying.

Usage:
  settings-usage-audit.py            # audit the current tree
  settings-usage-audit.py --json
  settings-usage-audit.py --write-baseline
  settings-usage-audit.py --self-test
Exit 0 only when every persisted key either has a consumer that acts on it, or sits
in the baseline with a reason that still matches the source.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "settings-usage-audit-baseline.json")
VC = os.path.join("Limelight", "macOS", "ViewControllers")
STORE = os.path.join(VC, "SettingsStore.swift")
BRIDGE = os.path.join(VC, "SettingsObjCBridge.swift")
MODEL = os.path.join(VC, "SettingsModel.swift")
PERSISTENCE = os.path.join(VC, "SettingsModel+Persistence.swift")
DIAG = os.path.join("Limelight", "macOS", "Helpers", "DiagnosticsReportBuilder.m")
# Files whose reads of a model property are the interface acting on the value.
# Panes are deliberately absent: a pane read is the control's own surface, which is
# the thing being questioned, not a consumer of it.
MODEL_LAYER = (MODEL, PERSISTENCE, os.path.join(VC, "SettingsModel+DerivedValues.swift"))
# Files whose per-key rows are generated for every stored key, so a mention there
# proves nothing. Everything outside these files is judged on the shape it acts on.
PLUMBING_FILES = (BRIDGE, PERSISTENCE, STORE,
                  os.path.join(VC, "SettingsModel+RiskAssessment.swift"))
SCV_MOUSE = os.path.join(VC, "StreamViewController+MouseCapture.m")
INPUT_PANE = os.path.join(VC, "SettingsInputPane.swift")
DERIVED = os.path.join(VC, "SettingsModel+DerivedValues.swift")
CONNECTION = os.path.join("Limelight", "Stream", "Connection.m")
HID_INTERNAL = os.path.join("Limelight", "Input", "HIDSupport_Internal.h")
MEMBER_PREFIX = ("load", "save", "apply", "set", "persist", "encode", "decode",
                 "update", "sync", "reset", "register", "migrate", "cache")


def path(*parts):
    return os.path.join(ROOT, *parts)


def read(relative):
    with open(path(relative), encoding="utf-8") as handle:
        return handle.read()


def brace_end(text, open_index):
    """Index of the `}` closing the brace at `open_index`, skipping comments/strings."""
    depth = 0
    index = open_index
    length = len(text)
    while index < length:
        char = text[index]
        if char == "/" and text[index + 1:index + 2] in ("/", "*"):
            index += 2
            continue
        if char in "\"'":
            quote = char
            index += 1
            while index < length and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unbalanced braces")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


class Tree:
    """The sources the audit reads, as text, with per-file overrides.

    Every conclusion comes from source text, so the self-test rewrites source text
    and the audit re-derives everything from it. Mutating an in-memory verdict list
    instead would only prove the test could edit a list.
    """

    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    def read(self, relative):
        if relative in self.overrides:
            return self.overrides[relative]
        return read(relative)

    def with_override(self, relative, text):
        return Tree({**self.overrides, relative: text})

    def sources(self):
        """Every .swift/.m/.mm/.h under Limelight/, build directories excluded."""
        found = []
        base = path("Limelight")
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith("build") and d not in ("Pods", "carthage")]
            for name in filenames:
                if name.endswith((".swift", ".m", ".mm", ".h")):
                    found.append(os.path.relpath(os.path.join(dirpath, name), ROOT))
        return sorted(found)


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------
def settings_fields(tree):
    """Field names of `struct Settings`.

    Only declarations at the struct's own indentation count. A first draft collected
    every `let x:` in the body and so counted `let decoded: Self?`, which is a local
    of `persistedSettings(for:)` three floors down; a "field" that is a local of a
    helper would be reported as an unreachable key forever, because no pane can bind
    a function's local.
    """
    text = tree.read(STORE)
    start = text.index("struct Settings")
    open_index = text.index("{", start)
    body = text[open_index + 1:brace_end(text, open_index)]
    fields = set(re.findall(r"^  (?:let|var)\s+(\w+)\s*:", body, re.M))
    fields -= {"cachedPersistedSettingsByProfileKey"}
    return fields


def _top_level_split(text):
    """Split a bracketed literal's inside on commas that sit at depth zero."""
    rows = []
    depth = 0
    current = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "/" and text[index + 1:index + 2] == "/":
            index = text.find("\n", index)
            if index < 0:
                break
            continue
        if char in "\"'":
            quote = char
            start = index
            index += 1
            while index < len(text) and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
            current.append(text[start:index + 1])
            index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            rows.append("".join(current))
            current = []
        else:
            # The bracket characters are tracked for depth and then dropped; keeping the
            # comma too put every row but the first one on a leading `,`, which the
            # `^\s*"key"\s*:` match rejected. That surfaced as *one* export row -- and a
            # gate that finds no renames silently excuses exactly the renames it was
            # written to catch, so a wrong count here is worse than a crash.
            current.append(char)
        index += 1
    rows.append("".join(current))
    return rows


def export_rows(tree, relative=BRIDGE):
    """dictKey -> fields read by its expression, out of `getSettings(for:)`.

    One row legitimately reads two fields (`"displayMode": settings.displayMode ??
    (settings.autoFullscreen ? 1 : 0)`), so the value is a set and every field in it
    ships into the dictionary.
    """
    text = tree.read(relative)
    marker = text.index("static func getSettings(for key: String)")
    open_index = text.index("{", marker)
    body = strip_comments(text[open_index + 1:brace_end(text, open_index)])
    # The literal, not the first bracket: the declaration reads
    # `let objcSettings: [String: Any?] = [`, and splitting the *type annotation*
    # produced zero rows -- a silent zero, which for this gate reads as "no renamed
    # keys exist" and would have excused every rename it was written to catch.
    declaration = re.search(r"=\s*\[", body)
    if not declaration:
        raise ValueError("no dictionary literal in getSettings(for:)")
    literal = declaration.end() - 1
    rows = {}
    depth = 0
    close = None
    for index in range(literal, len(body)):
        if body[index] == "[":
            depth += 1
        elif body[index] == "]":
            depth -= 1
            if depth == 0:
                close = index
                break
    if close is None:
        raise ValueError("no dictionary literal in getSettings(for:)")
    for row in _top_level_split(body[literal + 1:close]):
        match = re.match(r'\s*"([A-Za-z0-9_]+)"\s*:\s*(.*)$', row, re.S)
        if not match:
            continue
        rows[match.group(1)] = set(re.findall(r"\bsettings\.(\w+)", match.group(2)))
    return rows


def bridge_functions(tree, relative=BRIDGE):
    """[(name, selector, start, end)] for every static func in the bridge."""
    text = tree.read(relative)
    found = []
    for match in re.finditer(
            r"(?P<attrs>(?:\s*@[\w:]+(?:\([^)]*\))?)*)"
            r"(?:\s*(?:private|fileprivate|internal|public|open))?\s*static func (?P<name>\w+)"
            r"[^{\n]*", text):
        try:
            start = text.index("{", match.end() - 1)
            end = brace_end(text, start)
        except (ValueError, IndexError):
            continue
        explicit = re.search(r"@objc\(([^)]*)\)", match.group("attrs") or "")
        signature = match.group(0)
        if explicit:
            selector = explicit.group(1).strip()
        elif "@objc" in (match.group("attrs") or ""):
            # Swift exposes `func x(for key:)` as `xFor:`; a first argument label
            # becomes part of the selector, so the ObjC call site is `[C xFor:uuid]`.
            # `func x(for key:)` exposes as `xFor:` -- the label is part of the
            # selector even when the internal name follows it, so the parameter word
            # has to be skipped rather than required to end at the colon.
            label = re.search(r"\(\s*(\w+)(?:\s+\w+)?\s*:", signature)
            selector = match.group("name") + ((label.group(1).capitalize() + ":")
                                              if label and label.group(1) != "_" else ":")
        else:
            selector = None
        found.append((match.group("name"), selector, match.start(), end))
    return found


def bridge_accessors(tree, relative=BRIDGE):
    """`func x(for key:)` accessors: name -> (selector, fields read in its body)."""
    text = tree.read(relative)
    accessors = {}
    for name, selector, start, end in bridge_functions(tree, relative):
        signature = text[start:text.index("{", start)]
        if not re.search(r"\(\s*for key\s*:", signature):
            continue
        body = text[start + 1:end]
        if re.search(r"->\s*\[\s*String\s*:", signature):
            # `getSettings(for:)` returns the whole dictionary. Charging its 119 rows
            # to 119 keys would make every call site look like a consumer, so its keys
            # are judged where they are actually read: the subscript on the dictionary.
            continue
        accessors[name] = (selector, set(re.findall(r"\bsettings\.(\w+)", body)))
    return accessors


def diagnostic_keys(tree):
    """Keys `featureSwitchKeys` lists, so a report-only reader is recognisable."""
    text = tree.read(DIAG)
    match = re.search(r"\+\s*\(NSArray<NSString \*> \*\)\s*featureSwitchKeys.*?return\s*@\[(.*?)\];",
                      text, re.S)
    if not match:
        raise ValueError("featureSwitchKeys not found")
    return {item.strip().strip('@"') for item in match.group(1).split(",") if item.strip()}


def model_property_map(tree):
    """Settings field -> the model properties it is loaded into.

    `loadSettings()` is where the persisted shape and the displayed shape meet, and
    the names differ: `keyboardCompatibilityMode` is stored as an Int and lands in
    `selectedKeyboardCompatibilityMode`, a display string. Without the rename that
    control's pane binding would be charged to no field, and a working control would
    be reported as an unbound dead field.
    """
    text = strip_comments(tree.read(PERSISTENCE))
    marker = re.search(r"func loadSettings[^\n]*\{", text)
    if not marker:
        raise ValueError("loadSettings() not found")
    body = text[marker.end() - 1:brace_end(text, marker.end() - 1)]
    mapping = {}
    lines = body.split("\n")
    index = 0
    while index < len(lines):
        match = re.match(r"^\s+(?:self\.)?(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rest>.*)$",
                         lines[index])
        if match:
            expression = match.group("rest")
            depth = expression.count("(") - expression.count(")")
            stop = index
            while depth > 0 and stop + 1 < len(lines):
                stop += 1
                expression += "\n" + lines[stop]
                depth += lines[stop].count("(") - lines[stop].count(")")
            for field in set(re.findall(r"\bsettings\.(?P<f>\w+)", expression)):
                mapping.setdefault(field, set()).add(match.group("lhs"))
            index = stop + 1
            continue
        index += 1
    for field in settings_fields(tree):
        mapping.setdefault(field, set()).add(field)
    return mapping


def pane_surfaces(tree):
    """Model properties a pane touches: the control's own surface.

    Both a two-way `$settingsModel.x` binding and a display-only read count. Either
    way a person can see or拨 that control, which is what turns a key nothing acts on
    into a broken promise rather than an unused column.
    """
    panes = [item for item in tree.sources()
             if re.search(r"Settings(App|Audio|Devices|Input|Stream|Video)Pane\.swift$"
                          r"|Settings(Shortcuts|SharedControls|View)\.swift$", item)]
    surfaces = set()
    for relative in panes:
        text = strip_comments(tree.read(relative))
        for match in re.finditer(r"settingsModel\.(?P<f>\w+)", text):
            surfaces.add(match.group("f"))
    return surfaces


def _function_spans(text):
    """(start, end, name) for methods and computed properties declared at 2-4 spaces.

    Only needs to be right for the questions the exclusions ask -- is this read
    inside `saveSettings()`, inside `getSettings`, inside an accessor -- so it is a
    narrow pattern rather than a Swift parser. A read whose owner is not recognised
    is charged as an actor, which makes the audit report more uncommitted keys, not
    fewer; an exclusion that fails open would be the dangerous direction.
    """
    spans = []
    for match in re.finditer(
            r"^[ \t]{2,4}(?:@\w+(?:\([^)]*\))?\s*)*"
            r"(?:private\s+|fileprivate\s+|internal\s+|public\s+|static\s+|override\s+)*"
            r"(?:func|var)\s+(?P<name>\w+)", text, re.M):
        brace = text.find("{", match.end())
        if brace < 0 or "\n" in text[match.end():brace]:
            continue
        try:
            spans.append((match.start(), brace_end(text, brace), match.group("name")))
        except ValueError:
            continue
    return spans


def _span_of(spans, index):
    """Innermost declared member containing `index`."""
    best = None
    for start, end, name in spans:
        if start <= index <= end and (best is None or start > best[0]):
            best = (start, end, name)
    return best[2] if best else None


# ---------------------------------------------------------------------------
# consumers
# ---------------------------------------------------------------------------
# The functions that move a value without acting on it. Every persisted key appears
# in all of them, so charging these to a key would credit 119 of 119 and the audit
# would report a clean tree no matter what was deleted from the stream.
PLUMBING_FUNCTIONS = re.compile(
    r"^(?:loadSettings|loadDefaultSettings|saveSettings|resetToDefaults|"
    r"apply[A-Z]|set[A-Z]\w*|persist[A-Z]\w*|updateCached\w*|copy)\b")
# Objective-C files whose only job is to *describe* the build. A switch listed here
# proves the report knows the name; it does not prove the switch does anything.
REPORT_ONLY_FILES = (
    os.path.join("Limelight", "macOS", "Helpers", "DiagnosticsReportBuilder.m"),
    os.path.join("Limelight", "macOS", "Helpers", "DiagnosticsReportBuilder+Live.m"),
)


def _line_of(text, index):
    return text[:index].count("\n") + 1


def _accessor_fields(tree, relative=BRIDGE):
    """accessor name -> fields its body reaches, through the bridge's own helpers.

    `shouldUseHybridFreeMouseMotion(for:)` does not name a field; it calls
    `mouseInputStrategy(for:)`, which reads `settings.mouseDriver`. Crediting only
    the literal `settings.` tokens in the outer body would call `mouseDriver`
    unconsumed while four Objective-C call sites sit in the file, which is a false
    red on a working control -- the failure direction this gate must not have.
    """
    text = tree.read(relative)
    bodies = {}
    for name, selector, start, end in bridge_functions(tree, relative):
        bodies[name] = text[start:end]
    fields = {}

    def resolve(name, seen):
        if name in fields:
            return fields[name]
        if name in seen:
            return set()
        seen = seen | {name}
        body = bodies.get(name, "")
        found = set(re.findall(r"\bsettings\.(?P<f>\w+)", body))
        for helper in re.findall(r"(?<![.\w])(?P<h>\w+)\(for:", body):
            found |= resolve(helper, seen)
        return found

    for name in bodies:
        fields[name] = resolve(name, frozenset())
    return fields


def _selector_map(accessors):
    """ObjC selector -> Swift accessor name, for `func x(for key:)` shapes."""
    return {selector: name for name, (selector, _) in accessors.items() if selector}


def _is_relocation(text, index, name, qualifier, plumbing=False):
    """True when this mention only *moves* the value rather than acting on it.

    Three shapes look like a read and are not: the declaration of the storage itself,
    the row that ships a value out (`"x": settings.x`, `Settings(x: settings.x)`), and
    the assignment target that overwrites it. Each is generated for every stored key
    whether or not anything downstream ever looks at it, so they are excluded by shape
    -- and the self-test breaks each exclusion by rewriting the line into a form that
    does act, which has to turn the key green-to-red.

    The shipping shapes only count as relocation inside the per-key plumbing files.
    Elsewhere a labelled argument *is* the value being acted on: `unlockMaxBitrate`
    reaches no Objective-C accessor, but `Self.bitrateSteps(unlocked:
    unlockMaxBitrate)` decides which bitrate steps the interface offers, which is
    exactly the consumption this gate is asking about.
    """
    line_start = text.rfind("\n", 0, index) + 1
    prefix = text[line_start:index]
    token = ("%s.%s" % (qualifier, name)) if qualifier else name
    before = prefix.rstrip()
    if not before:
        return True
    if plumbing:
        if re.search(r":\s*$", before):
            # `label: settings.x` / `label: x` -- a labelled argument or dictionary row.
            return bool(re.search(r"(?:^|[,{(])\s*[A-Za-z_]\w*\s*:\s*$", before))
        if re.search(r"(?:^|[,{(])\s*(?:self\.)?[A-Za-z_]\w*\s*(?::\s*\S+\s*)?=\s*$",
                     before):
            # `x = settings.x` -- an assignment target, which is a write, not a read.
            return True
    if re.search(r"(?:^|[,{(])\s*(?:@Published\s+)?(?:private\s+|fileprivate\s+"
                 r"|static\s+|weak\s+)*(?:let|var)\s*(?:self\.)?$", before):
        # The declaration itself: `@Published var x: Bool` mentions the name without
        # reading it, and every persisted key has one, so counting it would credit 119
        # of 119 -- the same false green as the export row, from a different direction.
        return True
    del token
    return False


def collect_consumers(tree):
    """field -> [(site, kind, why)], where kind says what kind of reader was found.

    Kinds: `stream` (Objective-C acts on the exported dictionary), `accessor` (a
    per-key accessor is messaged or called), `interface` (the settings layer itself
    changes its behaviour on the value). Report-only reads are collected under
    `report` so a key whose only reader is the report can be named, not hidden.
    """
    exports = export_rows(tree)
    accessors = bridge_accessors(tree)
    accessor_fields = _accessor_fields(tree)
    selectors = _selector_map(accessors)
    properties = model_property_map(tree)
    consumers = {field: [] for field in settings_fields(tree)}

    def add(field, site, kind, why):
        if field in consumers:
            consumers[field].append((site, kind, why))

    property_index = {name for names in properties.values() for name in names}
    bound = re.compile(r"\b(?P<var>[A-Za-z_]\w*)\s*=\s*(?:id\s*)?"
                       r"\[SettingsClass getSettingsFor")
    subscript = re.compile(r"\b(?P<var>[A-Za-z_]\w*)\s*\[\s*@\"(?P<key>[A-Za-z0-9_]+)\"\s*\]")
    objc_call = re.compile(r"\[SettingsClass\s+(?P<selector>\w+For)\s*:")
    swift_call = re.compile(r"SettingsObjCBridge\.(?P<name>\w+)\s*\(\s*for\s*:")
    for relative in tree.sources():
        text = strip_comments(tree.read(relative))
        spans = _function_spans(text)
        report_only = relative in REPORT_ONLY_FILES
        # Headers count as Objective-C here: the inline helpers in
        # HIDSupport_Internal.h are the real readers for a dozen scroll and pointer
        # keys, and skipping them would report a working slider as unwired.
        if relative.endswith((".m", ".mm", ".h")):
            variables = {m.group("var") for m in bound.finditer(text)}
            for match in subscript.finditer(text):
                if match.group("var") not in variables:
                    continue
                for field in exports.get(match.group("key"), ()):
                    add(field, "%s:%d" % (relative, _line_of(text, match.start())),
                        "report" if report_only else "stream",
                        "reads exported key %s" % match.group("key"))
            for match in objc_call.finditer(text):
                selector = match.group("selector") + ":"
                name = selectors.get(selector)
                if name is None:
                    continue
                for field in accessor_fields.get(name, ()):
                    add(field, "%s:%d" % (relative, _line_of(text, match.start())),
                        "report" if report_only else "accessor",
                        "messages %s" % selector)
            continue
        for match in swift_call.finditer(text):
            name = match.group("name")
            if name not in accessors:
                continue
            for field in accessor_fields.get(name, ()):
                add(field, "%s:%d" % (relative, _line_of(text, match.start())),
                    "accessor", "calls %s(for:)" % name)
        if relative == STORE:
            continue
        # A read *inside* the interface counts when the value changes what the
        # interface does. Two shapes look like a consumer and are not: the row that
        # ships a value out (`"x": settings.x`) and the assignment or construction
        # argument that moves it (`x = settings.x`, `Settings(x: settings.x)`). Both
        # exist for every key that is merely stored, so charging them credited 119 of
        # 119 keys and the audit reported a clean tree with every control unwired.
        for match in re.finditer(r"\bsettings\.(?P<f>\w+)", text):
            field = match.group("f")
            owner = _span_of(spans, match.start())
            if os.path.basename(relative) == "SettingsObjCBridge.swift":
                if _span_of(spans, match.start()) == "getSettings" or owner in accessors:
                    continue
            if PLUMBING_FUNCTIONS.match(owner or ""):
                continue
            if _is_relocation(text, match.start(), match.group("f"), "settings",
                              plumbing=relative in PLUMBING_FILES):
                continue
            add(field, "%s:%d" % (relative, _line_of(text, match.start())),
                "interface", "read by %s()" % (owner or "top level"))
        if relative not in MODEL_LAYER:
            continue
        for match in re.finditer(r"(?<![\w.])(?P<f>[A-Za-z_]\w*)\b", text):
            field = match.group("f")
            if field not in property_index:
                continue
            owner = _span_of(spans, match.start())
            if PLUMBING_FUNCTIONS.match(owner or ""):
                continue
            if _is_relocation(text, match.start(), field, None,
                              plumbing=relative == PERSISTENCE):
                continue
            add(field, "%s:%d" % (relative, _line_of(text, match.start())),
                "interface", "read by %s()" % (owner or "top level"))
    return consumers, exports, properties


def _selector_to_name(selector):
    """`hasHostSpecificProfile` from the selector `hasHostSpecificProfileFor:`."""
    core = selector.rstrip(":")
    return core[:-3] if core.endswith("For") else core


def _line_at(text, index):
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:end if end > 0 else len(text)].strip()


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------
def classify(tree):
    """Every persisted key -> whether a control promises it and whether code acts on it."""
    consumers, exports, properties = collect_consumers(tree)
    surfaces = pane_surfaces(tree)
    reported = diagnostic_keys(tree)
    rows = []
    for field in sorted(settings_fields(tree)):
        found = consumers[field]
        actors = [item for item in found if item[1] != "report"]
        only_report = [item for item in found if item[1] == "report"]
        promised = bool(surfaces & properties.get(field, set()))
        if actors:
            state = "consumed"
        elif promised and only_report:
            state = "report-only"
        elif promised:
            state = "unwired-control"
        elif only_report:
            state = "report-only-field"
        else:
            state = "unreachable-field"
        rows.append({"key": field,
                     "state": state,
                     "properties": sorted(surfaces & properties.get(field, set())),
                     "actors": ["%s (%s)" % (site, why) for site, kind, why in actors],
                     "reports": ["%s (%s)" % (site, why) for site, kind, why in only_report],
                     "diagnostic": field in reported or any(
                         field in fields for key, fields in exports.items()
                         if key in reported)})
    return rows


def reason_for(row):
    """The falsifiable statement that has to keep matching for the debt to stay valid.

    Bound to the source rather than written by hand, in both halves: the control it
    promises and the mechanism that would have to appear. Wiring the key adds an
    actor and the row stops reporting, so the entry goes stale and the baseline
    rejects it; renaming the model property changes the promised half, which is a
    different debt and has to be re-reviewed.
    """
    if row["state"] == "unreachable-field":
        return ("%s is in no pane, is not exported to the stream, and no accessor or "
                "settings-layer code reads it" % row["key"])
    if row["state"] == "report-only-field":
        return ("%s is read only by the diagnostics report and by no control" % row["key"])
    if row["state"] == "report-only":
        return ("%s is shown by %s and read only by the diagnostics report"
                % (row["key"], ", ".join(row["properties"])))
    return ("%s is a switch shown by %s that no accessor is messaged for and no "
            "stream or settings-layer code reads"
            % (row["key"], ", ".join(row["properties"])))


# ---------------------------------------------------------------------------
# debt ledger
# ---------------------------------------------------------------------------
def load_baseline():
    """{key: reason} from the committed ledger, or {} when there is none yet."""
    if not os.path.exists(BASELINE):
        return {}
    with open(BASELINE, encoding="utf-8") as handle:
        document = json.load(handle)
    return {entry["key"]: entry["reason"] for entry in document.get("debts", [])}


def write_baseline(rows):
    """Commit today's unresolved keys with the source-bound reason each one carries."""
    debts = [{"key": row["key"], "reason": reason_for(row)}
             for row in rows if row["state"] != "consumed"]
    document = {"_about": (
        "Keys the settings interface exposes and nothing acts on. Regenerate with "
        "`python3 scripts/settings-usage-audit.py --write-baseline` and read the diff: "
        "an entry that leaves means the key got wired or the reason stopped matching, "
        "which is the only good reason for one to go. The reason text is part of the "
        "identity, so a key that stops being unwired for the reviewed reason is a new "
        "debt and has to be re-reviewed."),
        "debts": sorted(debts, key=lambda entry: entry["key"])}
    with open(BASELINE, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(debts)


def audit(tree=None):
    """The ledger plus the two ways it can be wrong: a new hole, or a stale entry."""
    rows = classify(tree or Tree())
    baseline = load_baseline()
    reported = {row["key"]: row for row in rows if row["state"] != "consumed"}
    new = [key for key in sorted(reported) if key not in baseline]
    stale = []
    for key in sorted(set(baseline) - set(reported)):
        stale.append((key, "no longer reported"))
    for key in sorted(set(baseline) & set(reported)):
        reason = reason_for(reported[key])
        if reason != baseline[key]:
            stale.append((key, "reason no longer matches: was %r, source now says %r"
                          % (baseline[key], reason)))
    return rows, new, stale


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
def _overridden(tree, relative, pairs):
    """A tree where `relative` has each fragment replaced, all of them or none."""
    text = tree.read(relative)
    for old, new, expected in pairs:
        found = text.count(old)
        if found != expected:
            raise AssertionError("anchor %r found %d times, expected %d in %s"
                                 % (old, found, expected, relative))
        text = text.replace(old, new)
    return tree.with_override(relative, text)


def _state(rows, key):
    for row in rows:
        if row["key"] == key:
            return row["state"]
    return None


# (name, tree->tree, key, state that must appear) -- each one breaks a belief the
# verdict rests on, so a green audit that ignores it is caught here rather than in
# production. `adds` is the opposite direction: an equivalent spelling must not move.
MUTATIONS = (
    # The call site goes away: a control whose only accessor is never messaged has to
    # turn red, which is the whole point of the gate.
    ("accessor-call-site-deleted",
     lambda tree: _overridden(tree, SCV_MOUSE,
                              [("[SettingsClass imeLocalCompositionFor:",
                                 "[SettingsClass quitAppAfterStreamFor:", 1)]),
     "imeLocalComposition", "unwired-control"),
    # The dictionary key is renamed on one side only. `enable10BitSdr` ships under a
    # different name, so this is the mutation that proves the rename map is followed
    # rather than the Swift name being grepped.
    ("exported-key-read-removed",
     lambda tree: _overridden(tree, CONNECTION,
                              [('settings[@"sdr10bit"]',
                                'settings[@"nope"]', 1)]),
     "enable10BitSdr", "unwired-control"),
    # The inline header helper is the only reader for the scroll keys, so a scan that
    # reads only `.m` files would report five working sliders as unwired.
    ("header-reader-missed",
     lambda tree: _overridden(tree, HID_INTERNAL,
                              [("[SettingsClass wheelScrollSpeedFor:",
                                 "[SettingsClass swapMouseButtonsFor:", 1)]),
     "wheelScrollSpeed", "unwired-control"),
    # The control disappears but the key is still persisted: the row must stay on the
    # ledger as unreachable, because dropping it would hide the debt.
    ("pane-binding-deleted",
     lambda tree: _overridden(tree, INPUT_PANE,
                              [("boolBinding: $settingsModel.emulateGuide",
                                "boolBinding: $settingsModel.showConnectionWarnings", 1)]),
     "emulateGuide", "unreachable-field"),
    # An explicit `@objc(...)` selector is the spelling a rename actually takes. The
    # verdict must not move, which proves the explicit name is what is matched.
    ("accessor-selector-stated-explicitly",
     lambda tree: _overridden(tree, BRIDGE,
                              [("  @objc static func imeLocalComposition(for key: String)",
                                "  @objc(imeLocalCompositionFor:)\n"
                                "  @objc static func imeLocalComposition(for key: String)",
                                1)]),
     "imeLocalComposition", "consumed"),
    # An equivalent spelling of one export row must not move the verdict either, so
    # the gate cannot be satisfied by a particular source formatting.
    ("export-row-restated",
     lambda tree: _overridden(tree, BRIDGE,
                              [('"yuv444": settings.enableYUV444',
                                '"yuv444": settings.enableYUV444 ? settings.enableYUV444 : false',
                                1)]),
     "enableYUV444", "consumed"),
    # Every read of the bitrate unlock happens inside the interface, where it decides
    # which steps the slider offers. Turning all of them into a constant is the only
    # way to make it unwired, so this pins the interface-read arm.
    ("interface-read-turned-into-a-write",
     lambda tree: _overridden(
         _overridden(tree, DERIVED,
                     [("Self.bitrateSteps(unlocked: unlockMaxBitrate)",
                       "Self.bitrateSteps(unlocked: true)", 1)]),
         MODEL, [("Self.bitrateSteps(unlocked: unlockMaxBitrate)",
                  "Self.bitrateSteps(unlocked: true)", 3)]),
     "unlockMaxBitrate", "unwired-control"),
)

# Verdicts that have each been wrong at least once while this gate was written, so a
# regression in any of the five parsers has to trip one of them. Every entry names the
# defect it was added for: a bridge-wide dictionary counted as 119 consumers, a
# `@Published var` declaration read as a use, a missing argument label in a derived
# selector, a visibility modifier treated as required, a header kept out of the scan.
REQUIRED_STATES = (
    ("captureSystemShortcuts", "unwired-control"),
    ("emulateGuide", "unwired-control"),
    ("enhancedAudioEQLayout", "unwired-control"),
    ("keyboardCompatibilityMode", "unwired-control"),
    ("shortQueueOnDoubledCadence", "unwired-control"),
    ("swapABXYButtons", "unwired-control"),
    ("absoluteMouseMode", "unreachable-field"),
    ("clipboardSyncMode", "unreachable-field"),
    ("coreHIDAutoEnabled", "unreachable-field"),
    ("enable10BitSdr", "consumed"),
    ("enableYUV444", "consumed"),
    ("muteOnFocusLoss", "consumed"),
    ("mouseDriver", "consumed"),
    ("relativeMouseAsAbsolute", "consumed"),
    ("wheelScrollSpeed", "consumed"),
    ("unlockMaxBitrate", "consumed"),
)


def self_test():
    """Each mutation has to change exactly the verdict it invalidates."""
    tree = Tree()
    before = {row["key"]: row for row in classify(tree)}
    failures = []
    for name, mutate, key, expected in MUTATIONS:
        try:
            mutated = mutate(tree)
        except AssertionError as error:
            failures.append("%s: %s" % (name, error))
            continue
        after = {row["key"]: row for row in classify(mutated)}
        states = list(after.values())
        if _state(states, key) != expected:
            failures.append("%s: %s became %r, expected %r"
                            % (name, key, _state(states, key), expected))
        moved = sorted(other for other in before
                       if other != key
                       and _state(states, other) != before[other]["state"])
        if moved:
            failures.append("%s: also moved %s" % (name, ", ".join(moved)))
    # The control goes away and the key stays on the ledger, just unreachable.
    orphan = classify(_overridden(
        tree, os.path.join(VC, "SettingsStreamPane.swift"),
        [("Toggle(isOn: $settingsModel.unlockMaxBitrate)",
          "Toggle(isOn: $settingsModel.showConnectionWarnings)", 1)]))
    if _state(orphan, "unlockMaxBitrate") != "consumed":
        failures.append("pane-binding-deleted: unlockMaxBitrate left the ledger")
    for key, expected in REQUIRED_STATES:
        if _state(list(before.values()), key) != expected:
            failures.append("pinned: %s is %r, expected %r"
                            % (key, _state(list(before.values()), key), expected))
    return failures


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable ledger")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record the current unresolved keys as reviewed debt")
    parser.add_argument("--self-test", action="store_true",
                        help="prove the verdict follows the source")
    args = parser.parse_args(argv)

    if args.self_test:
        failures = self_test()
        for failure in failures:
            print("FAIL %s" % failure)
        print("settings-usage-audit self-test: %d mutations, %d pinned verdicts,"
              " %d failures" % (len(MUTATIONS), len(REQUIRED_STATES), len(failures)))
        return 1 if failures else 0

    rows, new, stale = audit()
    if args.write_baseline:
        print("wrote %d debts to %s" % (write_baseline(rows),
                                        os.path.relpath(BASELINE, ROOT)))
        return 0

    reported = {row["key"]: row for row in rows if row["state"] != "consumed"}
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        # A reported key either sits in the ledger or it does not, and the two cases
        # are printed apart so the red half of the output is the only thing a reader
        # has to act on. Listing an unregistered key twice -- once as a state, once as
        # a RED -- reads like two findings and hides how many there are.
        order = ("unwired-control", "report-only", "report-only-field", "unreachable-field")
        for state in order:
            group = [row for row in rows
                     if row["state"] == state and row["key"] not in new]
            if group:
                print("debt %s (%d)" % (state, len(group)))
                for row in group:
                    print("  %-34s %s" % (row["key"], reason_for(row)))
        for key in new:
            print("RED %s: %s" % (key, reason_for(reported[key])))
        for key, why in stale:
            print("STALE %s: %s" % (key, why))
        print("%d of %d persisted keys act on their value; %d are registered debt"
              % (sum(1 for row in rows if row["state"] == "consumed"), len(rows),
                 len(reported) - len(new)))

    for key in new:
        print("RED %s: %s" % (key, reason_for(reported[key])), file=sys.stderr)
    for key, why in stale:
        print("STALE %s: %s" % (key, why), file=sys.stderr)
    return 1 if (new or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
