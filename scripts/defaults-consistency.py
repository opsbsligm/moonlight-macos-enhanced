#!/usr/bin/env python3
"""Prove that an unset setting reads the same value in both layers.

`SettingsObjCBridge.getSettings(for:)` builds the dictionary the stream reads,
and `SettingsModel+Persistence.loadSettings()` builds the values the interface
shows. Both start from `Settings.getSettings(for:)`, and both write `?? <expr>`
for the case where nothing was ever stored. When those two expressions disagree,
the window shows one number and the stream runs with another -- and nothing in
the type system, the build, or the runtime notices. Wave V found the first
instance (`ignoreAspectRatio`); this gate is what stops the second one from
needing to be found by hand.

Why the check evaluates instead of comparing text: most of the fallbacks that
look different *are* the same value (`0.0` against `0`, `Self.defaultX` against
the `false` that `defaultX` holds). A text comparison calls those divergences,
and calls a shared name a match even after the name stops resolving to the
literal the other side spells. Both errors point the wrong way, and both report
green. So each fallback is parsed and evaluated down to a literal through a
symbol table read out of the same sources.

An expression that will not evaluate is not treated as a match. It goes to the
ledger, and a ledger entry is only valid while a condition that is re-checked on
every run still holds -- "harmless today" has to say what would make it not.

Usage:
  defaults-consistency.py            # audit the current tree
  defaults-consistency.py --self-test
  defaults-consistency.py --json
Exit 0 only when every shared key either evaluates equal on both sides, or sits
in the ledger with a condition that still holds.

Keys the audit cannot yet reduce to a literal are debt, and debt is tracked rather
than argued away: `--write-baseline` records the current set and a later run fails
if the set grows (new unproven key) *or* shrinks (a key got proven and the entry is
now an excuse). Same ratchet shape as `analyzer-baseline.json`.

The entry binds the reason text too, not just the key. The reason is derived from the
source -- it names the helper the interface reads through, or the neighbour key that
is unbound -- so a refactor that changes the shape changes the reason, and the entry
stops matching. An entry that only named the key would keep excusing a key whose
unprovability had nothing to do with the one that was reviewed.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "defaults-consistency-baseline.json")
VC = os.path.join("Limelight", "macOS", "ViewControllers")
BRIDGE = os.path.join(VC, "SettingsObjCBridge.swift")
PERSISTENCE = os.path.join(VC, "SettingsModel+Persistence.swift")
DERIVED = os.path.join(VC, "SettingsModel+DerivedValues.swift")
STORE = os.path.join(VC, "SettingsStore.swift")
STREAM_VIEW = os.path.join(VC, "StreamViewController.m")
MODEL = os.path.join(VC, "SettingsModel.swift")
# Every Objective-C file that can ask the stream dictionary for a setting. The
# substitutions all live in one file, but the reads do not, and a reader that
# only looked at StreamViewController.m concluded that the sidebar timers and
# the mouse-capture flags were never read at all.
#
# This used to be a hand-written list of nine paths, and it was wrong in both of
# the ways a list can be wrong: it omitted `DiscoveryWorker.m` and
# `DiagnosticsReportBuilder+Live.m`, both of which bind the dictionary, and it
# was therefore the ground on which every "nobody reads this key" ledger entry
# stood. The set is derived now -- a reader is any Objective-C file that binds
# the dictionary from `[SettingsClass getSettingsFor:]` -- because the question
# the ledger asks is about the code, and a list of files is an answer that goes
# stale in silence: nothing fails when a tenth reader appears, the ledger just
# keeps excusing a key the stream already uses.
OBJC_SOURCE_ROOT = os.path.join(ROOT, "Limelight")

FALLBACK = re.compile(r"settings\.([A-Za-z_]\w*)\s*\?\?")
# The dictionary the stream actually reads, and the only place a fallback can change
# what the stream runs with. `getSettings(for:)` builds one dictionary literal and ends
# with `compactMapValues { $0 }`, so a key whose expression is nil does not arrive as
# NSNull -- the key is absent, and Objective-C reading it gets the zero of its type.
# The same file also holds 76 standalone `@objc static func x(for key:)` accessors, and
# their `?? defaultX` belongs to *that* call path: `fallbacks` used to search the whole
# file, so 21 keys were credited with a fallback the stream dictionary never had. Three
# of them (`muteOnFocusLoss`, `backgroundGamepad`, `matchDisplayResolution`) are read
# out of the dictionary, so flipping `SettingsModel.defaultMuteOnFocusLoss` to `true`
# -- interface shows YES, stream reads nil as NO -- left this gate reporting
# "0 divergent" and exit 0. That is the green-wrong verdict this gate exists to refuse,
# so a dictionary read is now judged only against a fallback written inside this body.
BRIDGE_EXPORTED_FUNCTION = "@objc static func getSettings(for key: String)"
# A newline continues an expression only when the next token cannot open a
# statement. Without this the fallback swallows the following settings and every
# shape statistic built from it is noise -- which is how the first draft of this
# gate concluded that 74 keys had 74 distinct fallback shapes.
CONTINUATION = re.compile(r"[.,:?)\]}&|<>=!*/%+-]")
MEMBER = re.compile(r"^(Self|SettingsModel)\.([A-Za-z_]\w*)$")
# A fallback can be written against an alias for the profile field rather than the
# field itself: `let stored = settings.x` and then `stored ?? defaultX`, which is how
# the mouse-settings migration reads the value twice (once to compare against the
# legacy default, once to fall back). Matching only `settings.x ??` reported that key
# as having no interface default at all, and the audit said so in as many words -- a
# false excuse in the file whose whole purpose is to refuse false excuses. An alias
# counts only when the binding and the read are both in the file being scanned, and
# the alias name is required to be the sole thing on the right of its `let`, so a
# same-named local built from something else cannot lend its fallback to the key.
# `loadDefaultSettings()` is the interface's own answer to "what does the window
# show when nothing was stored", written as a plain assignment rather than a `??`
# fallback: `customFps = Self.defaultCustomFps`. Reading only `settings.x ??` called
# five keys "read by the interface with no fallback anywhere" while the file said
# otherwise on its first screen, and two of those keys are read by the stream, so the
# excuse was doing real work. The function body is brace-matched and its assignments
# read as fallbacks; the left side has to be a bare `self` property, so a `let` that
# happens to share a name cannot lend a default to a setting.
DEFAULTS_ASSIGN = re.compile(r"^\s*(?P<key>[a-zA-Z]\w*)\s*=\s*(?P<value>.+?)\s*$", re.M)


def defaults_assignments(tree):
    """{setting: [(line, expression)]} from `loadDefaultSettings()`."""
    text = tree.read(PERSISTENCE)
    marker = re.search(r"func loadDefaultSettings\(\)\s*\{", text)
    if not marker:
        return {}
    try:
        end = brace_matched(text, marker.end() - 1)
    except Unresolved:
        return {}
    body = text[marker.end():end]
    found = {}
    for match in DEFAULTS_ASSIGN.finditer(body):
        value = re.sub(r"\s+", " ", match.group("value")).strip()
        if not value or value.startswith("//"):
            continue
        found.setdefault(match.group("key"), []).append(
            (text[:match.start()].count("\n") + 1, value))
    return found


ALIAS = re.compile(r"^\s*(?:let|var)\s+(?P<alias>\w+)\s*=\s*settings\."
                   r"(?P<key>[A-Za-z_]\w*)\s*$", re.M)
ALIASED_FALLBACK = re.compile(r"\b(?P<alias>[A-Za-z_]\w*)\s*\?\?")
# An array written on one line (`static var pacingOptions: [String] = ["a", "b"]`)
# has no line-initial `]` for STRING_TABLE to stop at, so the multi-line pattern
# ran past the end of the literal and the array came back missing.
INLINE_ARRAY = re.compile(
    r"static\s+(?:let|var)\s+(\w+)\s*:\s*\[\s*String\s*\]\s*=\s*\[(?P<body>[^\[\]]*)\]")
# A numeric array is the other multi-entry default: `defaultEnhancedAudioEQGains`
# is twelve Doubles, and an audit that only reads `[String]` tables reports the key
# as an unknown symbol -- which reads like a gap in the sources when it is a gap in
# the reader.
NUMBER_ARRAY = re.compile(
    r"static\s+(?:let|var)\s+(\w+)\s*:\s*\[\s*(?:Double|CGFloat|Float|Int)\s*\]\s*=\s*\["
    r"(?P<body>[^\[\]]*)\]")


def path(*parts):
    return os.path.join(ROOT, *parts)


def read(relative):
    with open(path(relative), encoding="utf-8") as handle:
        return handle.read()


class Tree:
    """The sources the audit reads, as text.

    Every conclusion in this file is derived from source text, so the self-test
    mutates source text too: it hands the audit the same files with one line
    rewritten, and the audit re-derives everything from that text. A self-test
    that patched an in-memory dictionary instead would only prove the test could
    edit a dictionary -- which is the flaw that made the previous draft's claim
    that three mutations were caught unprovable, so it is refused here by shape.
    """

    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    def read(self, relative):
        if relative in self.overrides:
            return self.overrides[relative]
        return read(relative)

    def with_override(self, relative, text):
        """A copy of this tree with one file's text replaced.

        Returned rather than mutated in place so a self-test can apply several
        edits in sequence and each `audit` call still reads every other file from
        disk. Without it `mutate` raised AttributeError, which is the shape the
        self-test had before it reported anything about a mutation at all.
        """
        return Tree({**self.overrides, relative: text})


# ---------------------------------------------------------------------------
# expression extraction
# ---------------------------------------------------------------------------
def extract_expression(text, start):
    """Return (expression_source, stop_index) for the expression at `start`."""
    depth = 0
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == "{" and depth == 0:
            # A brace at the top level is the statement that follows, not part of
            # the fallback: `if settings.x ?? false { selected = sentinel }` would
            # otherwise swallow the whole body and refuse to parse. A brace inside
            # parentheses is still a dictionary or closure, so only depth zero cuts.
            return text[start:index].strip(), index
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return text[start:index].strip(), index
            depth -= 1
        elif char == "," and depth == 0:
            return text[start:index].strip(), index
        elif text[index:index + 2] == "//" and depth == 0:
            return text[start:index].strip(), index
        elif char == "\n":
            probe = index + 1
            while probe < length and text[probe] in " \t":
                probe += 1
            if depth == 0 and (probe >= length or not CONTINUATION.match(text[probe])):
                return text[start:index].strip(), index
        index += 1
    return text[start:].strip(), length


# A fallback written inside a sentinel branch is not that key's answer to "nothing was
# stored". `let dataFps = settings.fps == .zero ? Int(settings.customFps ?? 60.0)
# : settings.fps` (`SettingsObjCBridge.swift`) answers "what framerate runs when no
# preset was picked", and the 60 belongs to that derived framerate. Charging it to
# `customFps` reported a fork that does not exist: the interface branches the same way
# (`effectiveFpsForBitrate()` in `SettingsModel+DerivedValues.swift` falls to
# `defaultFps`, and `loadSettings()` applies the same value under the same
# `selectedFps == 0` test), so both layers land on 60 for an unset profile. Only the
# `== .zero` sentinel shape is excused, because that is the shape this codebase uses to
# mean "custom", and the excuse is tied to the guard text rather than to the key name:
# delete the guard and the fallback is unconditional again, which is what the self-test
# does to show the excuse can fail.
GUARDED_FALLBACK = re.compile(
    r"settings\.(?P<guard>[A-Za-z_]\w*)\s*==\s*\.zero\s*\?"
    r"(?P<guard_arm>[^:;{}]*?)"
    r"settings\.(?P<key>[A-Za-z_]\w*)\s*(?P<coalesce>\?\?)")


def _guarded_fallbacks(text):
    """[(coalesce offset, defaulted key, guard field, line source)] in a `.zero` branch.

    The guard key has to differ from the defaulted key: `settings.x == .zero ? (x ?? y)`
    is one key's own default written the long way round, and excusing that would excuse
    the exact shape the audit exists to catch.
    """
    found = []
    for match in GUARDED_FALLBACK.finditer(text):
        if match.group("guard") == match.group("key"):
            continue
        start = text.rfind("\n", 0, match.start()) + 1
        stop = text.find("\n", match.start())
        line_source = re.sub(
            r"\s+", " ", text[start:stop if stop > 0 else len(text)]).strip()
        found.append((match.start("coalesce"), match.group("key"),
                      match.group("guard"), line_source))
    return found


def guarded_fallbacks(tree, relative):
    """{guard field: [(line, defaulted key, value source)]} for branch-local defaults.

    Indexed by the *guard* field, because that is the key the branch is about:
    `settings.fps == .zero ? Int(settings.customFps ?? 60.0) : settings.fps` states what
    framerate runs when no preset was picked, so the 60 answers a question about `fps`
    and not about `customFps`. Keeping these out of `fallbacks` is what stops that 60
    from being charged to `customFps`, where it would report a fork that cannot happen.
    """
    text = tree.read(relative)
    found = {}
    for position, key, guard, _line in _guarded_fallbacks(text):
        source, _ = extract_expression(text, position + 2)
        source = re.sub(r"\s+", " ", source).strip()
        line = text[:position].count("\n") + 1
        found.setdefault(guard, []).append((line, key, source))
    return found


def fallbacks(tree, relative, within=None):
    """{setting: [(line, expression_source)]} for every `settings.x ?? expr`.

    A fallback inside a sentinel branch is skipped here and reported by
    `guarded_fallbacks`: its value belongs to the branch's derived quantity rather than
    to the absent key, and charging it to the key reports a fork that cannot happen.

    `within` restricts the search to a byte range. The bridge needs it: the same file
    holds standalone accessors whose `?? default` never reaches the stream dictionary,
    and crediting one to a dictionary key is what made this gate green while the
    interface and the stream disagreed.
    """
    text = tree.read(relative)
    guarded = {position for position, _, _, _ in _guarded_fallbacks(text)}
    found = {}
    for match in FALLBACK.finditer(text):
        if within and not (within[0] <= match.start() < within[1]):
            continue
        # Both patterns end at the `??`, so the offsets line up on that token:
        # `FALLBACK` starts at `settings`, which would never match a saved `??` offset.
        if match.end() - 2 in guarded:
            continue
        source, _ = extract_expression(text, match.end())
        source = re.sub(r"\s+", " ", source).strip()
        line = text[:match.start()].count("\n") + 1
        found.setdefault(match.group(1), []).append((line, source))
    return found


def bridge_export_body(tree, relative=BRIDGE):
    """Byte range of the `getSettings(for:)` body: what the stream dictionary holds.

    Brace-matched rather than regex-terminated because the body holds nested
    dictionaries and closures, and a pattern that stops at the first `}` returns a
    range that quietly excludes most of the exports -- which would be reported as
    "this key has no stream fallback", a claim about the code that the code denies.
    """
    text = tree.read(relative)
    anchor = text.index(BRIDGE_EXPORTED_FUNCTION)
    brace = text.index("{", anchor + len(BRIDGE_EXPORTED_FUNCTION))
    return brace + 1, brace_matched(text, brace)


def bridge_stream_accessors(tree, text):
    """Accessors that stand in for one key on the stream side, by name and by caller.

    Two conditions, both needed:

    * The function is named after the setting. `@objc static func muteOnFocusLoss(for
      key:)` answers one question and its `??` is that key's stream default, while
      `loadMoonlightSettings(for:)` returns nothing, reads a dozen settings to derive
      a resolution, and its `settings.matchDisplayResolution ?? false` is a local
      step in that arithmetic -- charging it to `matchDisplayResolution` credits the
      stream with a default that only ever decides a width and a height.
    * Objective-C really calls it, found in code rather than comments. An accessor
      nobody calls cannot supply the stream's default: `muteOnFocusLoss(for:)` is
      that shape, where the only mention of `muteOnFocusLossFor:` in the tree is a
      comment explaining why the reader uses the dictionary instead ("so the Swift
      getter does not need an @objc rename"). Reading comments kept crediting
      `defaultMuteOnFocusLoss` to a dictionary key that ships without it.

    Comments are stripped line by line; a stray block comment only costs an
    attribution, which reports as unproven rather than as agreement.
    """
    fields = settings_fields(tree)
    named = {match.group(1) for match in re.finditer(
        r"@objc static func (\w+)\(for key: String\)", text) if match.group(1) in fields}
    called = set()
    for dirpath, _, filenames in os.walk(OBJC_SOURCE_ROOT):
        for filename in filenames:
            if not filename.endswith((".m", ".mm")):
                continue
            with open(os.path.join(dirpath, filename), encoding="utf-8",
                      errors="replace") as handle:
                for line in handle:
                    code = line.split("//")[0]
                    for name in named:
                        if "%sFor:" % name in code:
                            called.add(name)
    return named & called


def bridge_read_ranges(tree, relative=BRIDGE):
    """Byte ranges where a `??` really is the stream's default for a key.

    The stream reaches a setting two ways, and each has its own default:

    * the `getSettings(for:)` dictionary, read as `prefs[@"key"]` -- 54 keys;
    * a standalone `@objc static func key(for key:)`, called as `[SettingsClass
      keyFor:]` -- 46 keys.

    Measured across the whole Objective-C tree, **no key is read both ways**, so each
    key has exactly one stream default and the two ranges can share one table. What
    may not happen is what searching the whole file did: it charged an accessor's
    `?? defaultX` to the dictionary's copy of the same key, which made
    `muteOnFocusLoss` read as agreed while the dictionary -- `compactMapValues` drops
    the nil -- gave Objective-C nothing, and setting `defaultMuteOnFocusLoss` to `true`
    left the gate printing "0 divergent" and exiting 0.

    Only accessors that pass `bridge_stream_accessors` contribute, and a `??` outside
    every range -- a free helper, a reader that computes several settings at once, or an
    accessor no caller uses -- is left unattributed. That is the strict direction: an
    unattributed default makes the key report as unproven and go on the debt books,
    where a reviewer sees it, instead of silently settling a two-layer comparison.
    """
    text = tree.read(relative)
    allowed = bridge_stream_accessors(tree, text)
    ranges = [bridge_export_body(tree, relative)]
    for match in re.finditer(r"@objc static func (\w+)\(for key: String\)", text):
        if match.group(1) not in allowed:
            continue
        brace = text.index("{", match.end())
        try:
            ranges.append((brace + 1, brace_matched(text, brace)))
        except Unresolved:
            continue  # unbalanced: no range claimed, so nothing is attributed to it
    return ranges


def dangling_accessor_calls(tree):
    """{setting: call site} where ObjC calls a `...For:` accessor that does not exist.

    A rename on one side of the bridge seam is the way a key leaves the audit books by
    accident: the accessor's trailing return stops being credited (its name no longer
    matches the setting), the dictionary never carried the key, and the key vanishes
    from *every* account -- not compared, not unproven, gone. The call site is the
    surviving half of the seam, and it is as much a stream-side consumer as a
    `prefs[@"key"]` read: charge the key to it and the audit reports the loss instead
    of swallowing it. (A build would not ship like this; the gate's job is to make the
    same-shaped accident in *defaults* visible even in the tree that does compile.)
    """
    text = tree.read(BRIDGE)
    named = {m.group(1) for m in re.finditer(
        r"@objc static func (\w+)\(for key: String\)", text)}
    fields = settings_fields(tree)
    dangling = {}
    for dirpath, _, filenames in os.walk(OBJC_SOURCE_ROOT):
        for filename in filenames:
            if not filename.endswith((".m", ".mm")):
                continue
            with open(os.path.join(dirpath, filename), encoding="utf-8",
                      errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    code = line.split("//")[0]
                    for match in re.finditer(r"\[\s*\w+\s+(\w+?)For:", code):
                        key = match.group(1)
                        key = key[0].lower() + key[1:]
                        if key in named or key not in fields:
                            continue
                        dangling.setdefault(key, "%s:%d %sFor:"
                                            % (filename, number, match.group(1)))
    return dangling


def bridge_fallbacks(tree, relative=BRIDGE):
    """The stream's own defaults for the dictionary and the accessors, one table.

    Kept as its own function so `audit` and `condition_holds` cannot drift apart --
    the ledger condition asks the same question the comparison asks, and the two
    answering it differently would let a key be excused by one and reported by the
    other, which reads as a flake rather than as a fork.
    """
    found = {}
    for start, stop in bridge_read_ranges(tree, relative):
        for key, entries in fallbacks(tree, relative,
                                      within=(start, stop)).items():
            found.setdefault(key, []).extend(entries)
    return found


def chained_fallbacks(tree, relative):
    """{setting: [(line, expression_source)]} for `(for: key)?.x ?? expr`.

    Kept apart from `fallbacks` for the same reason aliased fallbacks are: the two
    carry different evidence, and a self-test has to be able to break the chained
    shape without breaking the direct one. The expression is extracted from after the
    `??`, so what the evaluator and the one-expression comparison see is the same text
    a direct fallback yields.
    """
    text = tree.read(relative)
    found = {}
    for match in CHAINED_FALLBACK.finditer(text):
        tail = AFTER_CHAIN.match(text, match.end())
        if not tail:
            continue
        source, _ = extract_expression(text, tail.end())
        source = re.sub(r"\s+", " ", source).strip()
        if not source:
            continue
        line = text[:match.start()].count("\n") + 1
        found.setdefault(match.group("key"), []).append((line, source))
    return found


def depth_zero_trailing_return(body):
    """(offset, expression_source) for the last depth-zero `return` in a body.

    A `return` nested in an `if`/`switch`/closure answers that branch, not "the
    profile was absent", so only depth-zero returns count, and the *last* one is the
    one the fall-through reaches. A returned expression that reads `settings.` is the
    stored value rather than a default, so it is not claimed. Shared by the accessor
    reader and the helper reader below: the two must disagree about nothing, or the
    same source text answers "what is the default" two different ways one file apart.
    """
    depth = 0
    last = None
    index = 0
    while index < len(body):
        char = body[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif (body.startswith("return", index) and depth == 0
              and not (index and (body[index - 1].isalnum()
                                  or body[index - 1] == "_"))):
            source, stop = extract_expression(body, index + len("return"))
            source = re.sub(r"\s+", " ", source).strip()
            if source and "settings." not in source:
                last = (index, source)
            index = stop
            continue
        index += 1
    return last


def implicit_trailing_expression(body):
    """The body-as-one-expression default, for a body with no statement keyword.

    A Swift function body may be a bare expression, and two accessors are written that
    way (`mouseDriver(for:)` is one). Taking only an explicit `return` means the key
    reaches no account at all -- neither compared nor unproven -- which is the silence
    this reader exists to remove. Accepted only when the whole body *is* one
    expression: a body that opens with a statement keyword has no trailing expression
    to credit, and guessing one would invent a default the source does not state.
    """
    candidate = re.sub(r"\s+", " ", strip_leading_comments(body)).strip()
    if (candidate and IMPLICIT_TAIL_OK.match(candidate)
            and ";" not in candidate and "settings." not in candidate):
        return (0, candidate)
    return None


def accessor_tails(tree, relative=BRIDGE):
    """{setting: [(line, expression_source)]} for an accessor's trailing `return`.

    `fallbacks` can only see a default written with `??`, so a key whose accessor
    reads

        if let settings = Settings.getSettings(for: key) { return settings.x }
        return SettingsModel.defaultX

    is invisible to the audit: it lands in no account at all, not even "unproven".
    Eight such keys exist, and the shape is not exotic -- it is what an accessor whose
    profile field is *non-optional* has to look like, because there is no `??` to
    write. Measured before this existed: `return SettingsModel.defaultRumble` changed
    to `return false` (window shows rumble ON, stream runs it OFF) printed
    "0 divergent" and exited 0, and `rumble` appeared nowhere in the result.

    Only accessors that pass `bridge_stream_accessors` contribute, so a trailing
    return in a helper nobody calls is still not credited to a key. The return is
    found at brace/paren/bracket depth zero and must be the *last* one in the body:
    a `return` nested in an `if`/`switch`/closure answers that branch, not "the
    profile was absent", and taking the first depth-zero return instead of the last
    would credit an early-exit arm as the default. A trailing expression that reads
    `settings.` is the stored value rather than a default, so it is not claimed.

    A trailing expression the evaluator cannot reduce -- a delegation
    (`mouseInputStrategy(for: key).rawValue`) or a call into another type
    (`CGSizeMake(300, 400)`) -- is still returned here. That is the strict direction:
    the key then reports as unproven and goes on the debt books, where a reviewer
    sees it, instead of leaving the audit the way it was, which was silence.
    """
    text = tree.read(relative)
    allowed = bridge_stream_accessors(tree, text)
    found = {}
    for match in re.finditer(r"@objc static func (\w+)\(for key: String\)", text):
        if match.group(1) not in allowed:
            continue
        brace = text.index("{", match.end())
        try:
            body = text[brace + 1:brace_matched(text, brace)]
        except Unresolved:
            continue  # unbalanced: no body claimed, so nothing is attributed to it
        last = depth_zero_trailing_return(body)
        if last is None:
            last = implicit_trailing_expression(body)
        if not last:
            continue
        line = text[:brace].count("\n") + body[:last[0]].count("\n") + 2
        found.setdefault(match.group(1), []).append((line, last[1]))
    return found


# A body that starts with one of these is a statement sequence, so the "the body is
# one expression" reading does not apply and nothing is credited.
IMPLICIT_TAIL_OK = re.compile(r"^(?!//)(?!(?:let|var|if|guard|for|while|repeat|do|"
                              r"switch|return|throw|assert|self|deinit)\b)")


# A helper the accessor delegates to has to be declared in the same file and take the
# accessor's own `key`; a helper that lives elsewhere, or that is handed a different
# host id, answers a different question and its tail return is not this key's default.
LOCAL_HELPER = re.compile(
    r"\bprivate static func (?P<name>\w+)\s*\(\s*for key: String\s*\)\s*(?:->[^{]+)?\{")


def accessor_tail_readthrough(tree, relative=BRIDGE):
    """{setting: {"expression"|"stopped", "helper", "line"}} for delegated tails.

    `mouseDriver(for:)` states no default of its own: its whole body is
    `mouseInputStrategy(for: key).rawValue`, and the default lives one function away,
    as that helper's trailing `return MouseInputDriverStrategy.defaultStrategy`. An
    auditor that stops at the accessor either reports "unsupported call" (which is what
    Wave Y shipped: the key on the debt books with a reason about an initializer) or,
    worse, learns to ignore delegation-shaped tails and lets the key leave the books.

    So the reader crosses **exactly one** function, under the same rule that reads an
    accessor's own tail: the depth-zero last `return` is the default, and a return
    nested in an `if`/`switch`/closure answers that branch rather than "the profile was
    absent". The helper's default is then substituted for the call -- `(default).rawValue`
    -- so the evaluator sees one expression and the member access still resolves against
    the enum's own table.

    Crossing twice is where a reader starts inventing defaults, so a helper whose own
    default is *another* call stops here and says so: `clipboardSyncMode(for:)` delegates
    to `inferredDefaultClipboardSyncMode(for:)`, whose tail is
    `SettingsModel.clipboardSyncModeRawValue(for: "Auto Sync")` -- one layer in, stopped
    at a second. The key keeps its entry and the reason names both places, which is the
    strict direction: a proof the reader does not hold is never credited as agreement.
    """
    text = tree.read(relative)
    helpers = {}
    for match in LOCAL_HELPER.finditer(text):
        try:
            body = text[match.end():brace_matched(text, match.end() - 1)]
        except Unresolved:
            continue  # unbalanced: no body claimed, so the helper answers nothing
        tail = depth_zero_trailing_return(body) or implicit_trailing_expression(body)
        if tail:
            helpers[match.group("name")] = tail[1]
    found = {}
    for setting, entries in accessor_tails(tree, relative).items():
        line, source = entries[-1]
        name = re.match(r"([A-Za-z_]\w*)\s*\(", source)
        if not name or name.group(1) not in helpers:
            continue
        # Only the accessor's own `key` may be handed over: `helper(for: globalHostId)`
        # reads another host's profile, so its absent arm is not this key's default.
        depth, index, stop = 0, name.end() - 1, None
        while index < len(source):
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
                if depth == 0:
                    stop = index
                    break
            index += 1
        if stop is None:
            continue
        call = source[name.start():stop + 1]
        if re.fullmatch(r"\w+\(\s*for:\s*key\s*\)", re.sub(r"\s+", " ", call)) is None:
            continue
        default = helpers[name.group(1)]
        entry = {"helper": name.group(1), "line": line}
        if LOCAL_HELPER.search(default) or re.search(r"[\w)\]]\s*\(", default):
            entry["stopped"] = ("read through %s(), stopped at its own default %r, "
                                "which is another call: the audit crosses one function "
                                "and no further" % (name.group(1), default))
        else:
            entry["expression"] = "(%s)%s" % (default, source[stop + 1:])
        found[setting] = entry
    return found


def strip_leading_comments(text):
    """Drop whole-line comments so a leading doc/`//` note is not read as the body."""
    lines = text.splitlines()
    while lines and (not lines[0].strip() or lines[0].strip().startswith("//")):
        lines.pop(0)
    return "\n".join(lines)


def interface_field_map(tree):
    """{profile key: interface field} for a loader that renames the key.

    `interface_value`'s last resort is `loadDefaultSettings()`, which assigns the
    model's *own* fields, and those are not always named after the profile key:
    `framePacing` is shown as `selectedPacingOptions`, `audioConfiguration` as
    `selectedAudioConfiguration`, `controllerDriver` as `selectedControllerDriver`
    (`SettingsModel+Persistence.swift` reads `settings.framePacing` into
    `selectedPacingOptions` through `getString`). Hard-coding those four would be a
    table that rots in silence the day a key is renamed, so the pairing is read out
    of the loader: an assignment to a model field whose right-hand side names exactly
    one `settings.<key>` binds that key to that field.

    Exactly one, because an expression that reads two settings (`settings.mouseMode
    ?? (Self.defaultMouseMode == "game" ? 0 : 1)`, or a resolution derived from
    several) does not state the default of either. `let`/`var` bindings are excluded:
    those are locals inside the loader, not the field the window binds to.
    """
    text = tree.read(PERSISTENCE)
    marker = re.search(r"func loadSettings\(\)\s*\{", text)
    if not marker:
        return {}
    try:
        body = text[marker.end():brace_matched(text, marker.end() - 1)]
    except Unresolved:
        return {}
    found = {}
    for statement in split_statements(body):
        assignment = re.match(r"(?![lL]et\s|\var\s)([a-z]\w*)\s*=(?!=)(.+)",
                              statement, re.S)
        if not assignment:
            continue
        keys = re.findall(r"settings\.([A-Za-z_]\w*)", assignment.group(2))
        if len(keys) != 1:
            continue
        found.setdefault(keys[0], assignment.group(1))
    return found


def split_statements(body):
    """The statements of a function body, joined across their line breaks.

    Every line is a candidate, including the ones inside `if let settings = ...`: the
    loader binds the profile inside such a block, so a top-level-only scan sees one
    giant statement and finds no assignment at all -- which is how the first draft of
    this reader returned an empty map and left four renamed keys reporting "no fallback
    anywhere". An assignment nested in a branch still names the field the window binds
    to, so it counts.

    A line is joined to the next while its parentheses are unbalanced, because the
    common shape wraps: `selectedAudioConfiguration = Self.getString(` /
    `from: settings.audioConfiguration, in: ...)`. Braces are not a join reason --
    a block opener must terminate the statement before it.
    """
    joined = []
    pending = ""
    for line in body.splitlines():
        candidate = (pending + " " + line.strip()) if pending else line.strip()
        if candidate.count("(") != candidate.count(")"):
            pending = candidate
            continue
        pending = ""
        if candidate:
            joined.append(candidate)
    if pending:
        joined.append(pending)
    return joined


def aliased_fallbacks(tree, relative):
    """{setting: [(line, expression_source)]} for fallbacks written against an alias.

    Separated from `fallbacks` rather than merged into it because the two shapes
    carry different evidence: an alias read says the default lives next to the
    migration that compares against the legacy value, and the self-test needs to be
    able to break one shape without breaking the other.
    """
    text = tree.read(relative)
    found = {}
    for binding in ALIAS.finditer(text):
        alias, key = binding.group("alias"), binding.group("key")
        for read in ALIASED_FALLBACK.finditer(text):
            if read.group("alias") != alias:
                continue
            source, _ = extract_expression(text, read.end())
            source = re.sub(r"\s+", " ", source).strip()
            line = text[:read.start()].count("\n") + 1
            # The expression alone is stored so the evaluator and the
            # same-expression comparison see the same text they see for a direct
            # `settings.x ?? expr`; the line lands on the alias read, which is where
            # the default actually lives.
            found.setdefault(key, []).append((line, source))
    return found


# ---------------------------------------------------------------------------
# tokenizer
# ---------------------------------------------------------------------------
class Unresolved(Exception):
    """The expression cannot be reduced to a value; never counts as agreement."""

# Whitespace is stripped outside the alternation: `\s*` on the first branch only
# would leave every expression with a space before an operator untokenisable.
TOKEN = re.compile(r"""\s*(?:(?P<string>"(?:[^"\\]|\\.)*")
    |(?P<number>\d+\.\d+|\d+)
    |(?P<ident>[A-Za-z_]\w*)
    |(?P<op>\?\?|\?\.|==|!=|<=|>=|&&|\|\||[.,(){}\[\]?:!<>+*/-]))""", re.X)


def tokenize(source):
    tokens = []
    position = 0
    while position < len(source):
        if not source[position:].strip():
            break
        match = TOKEN.match(source, position)
        if not match or match.start() != position:
            raise Unresolved("cannot tokenise %r" % source[position:position + 40])
        position = match.end()
        kind = match.lastgroup
        if kind == "op" and match.group("op") in ("|", "&", "%"):
            raise Unresolved("operator outside the parsed subset: %r" % source[:40])
        tokens.append((kind, match.group(kind)))
    if not tokens:
        raise Unresolved("empty expression")
    return tokens


# ---------------------------------------------------------------------------
# parser -> AST
# ---------------------------------------------------------------------------
# `??` binds loosest, which is what lets a fallback expression that is itself a
# coalesce (`(settings.x ?? false) ? 1 : 0`) be read without a special case.
LEVELS = [["??"], ["||"], ["&&"], ["==", "!="], ["<", ">", "<=", ">="],
          ["+", "-", "*", "/"]]


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.at = 0

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else (None, None)

    def eat(self, value):
        if self.peek()[1] == value:
            self.at += 1
            return True
        return False

    def expect(self, value):
        if not self.eat(value):
            raise Unresolved("expected %r, found %r" % (value, self.peek()))

    def parse(self):
        node = self.ternary()
        if self.at != len(self.tokens):
            raise Unresolved("trailing tokens %r" % (self.tokens[self.at:self.at + 3],))
        return node

    def ternary(self):
        cond = self.binary(0)
        # `?.` is optional chaining, not the condition of a ternary.
        if self.peek()[1] == "?" and self.peek() != ("op", "?."):
            self.at += 1
            when_true = self.ternary()
            self.expect(":")
            return ("ternary", cond, when_true, self.ternary())
        return cond

    def binary(self, level):
        if level >= len(LEVELS):
            return self.postfix()
        left = self.binary(level + 1)
        while self.peek()[1] in LEVELS[level]:
            operator = self.peek()[1]
            self.at += 1
            left = ("binop", operator, left, self.binary(level + 1))
        return left

    def postfix(self):
        node = self.primary()
        while True:
            kind, text = self.peek()
            if text in (".", "?."):
                self.at += 1
                name = self.peek()[1]
                if self.peek()[0] != "ident":
                    raise Unresolved("expected a member name")
                self.at += 1
                node = ("member", name, node)
            elif text == "(":
                self.at += 1
                node = self.call(node)
            else:
                return node

    def call(self, callee):
        arguments = []
        if not self.eat(")"):
            while True:
                label = None
                if self.peek()[0] == "ident" and self.tokens[self.at + 1:self.at + 2] \
                        and self.tokens[self.at + 1][1] == ":":
                    label = self.peek()[1]
                    self.at += 2
                arguments.append((label, self.ternary()))
                if not self.eat(","):
                    break
            self.expect(")")
        return ("call", callee, arguments)

    def primary(self):
        kind, text = self.peek()
        if self.eat("("):
            node = self.ternary()
            self.expect(")")
            return node
        if self.eat("["):
            items = []
            if not self.eat("]"):
                while True:
                    items.append(self.ternary())
                    if not self.eat(","):
                        break
                self.expect("]")
            return ("array", items)
        if self.eat("!"):
            return ("not", self.postfix())
        if kind == "string":
            self.at += 1
            return ("literal", text[1:-1].replace('\\"', '"'))
        if kind == "number":
            self.at += 1
            return ("literal", float(text) if "." in text else int(text))
        if kind == "ident":
            self.at += 1
            if text in ("true", "false"):
                return ("literal", text == "true")
            # `Self.foo` / `SettingsModel.foo` collapse into one node shape so the
            # evaluator does not care which spelling a file happens to use.
            if text in ("Self", "SettingsModel") and self.peek()[1] == ".":
                self.at += 1
                name = self.peek()[1]
                if self.peek()[0] != "ident":
                    raise Unresolved("expected a member after %s." % text)
                self.at += 1
                return ("symbol", name)
            return ("name", text)
        raise Unresolved("unexpected token %r" % (text,))


# An option table read through a closure -- `Options.first(where: { $0.value == raw
# })?.title` -- is the one spelling a fallback takes that the expression parser covers
# in the source but not in its grammar, because the parser reads expressions and a
# closure is a program. Refusing it outright reported five settings as "the interface
# has no default anywhere", which is a claim about the code that the code contradicts:
# the default is on the line, written as a lookup. NORMALISE rewrites that one shape
# into a call with the table it names as an argument, so the evaluator reads the number
# out of the same table the picker renders. It substitutes a call, not an answer: the
# self-test breaks one table's number and expects a report, which is what proves the
# lookup is real rather than the label being carried across by hand.
OPTION_READ = re.compile(
    r"\b(?P<table>\w*[Oo]ptions)\s*\.\s*first\s*\(\s*where:\s*\{\s*\$0\s*\.\s*value"
    r"\s*==\s*(?P<raw>[\w.]+)\s*\}\s*\)\s*\?\.title")


def normalise(source):
    """Rewrite the one expression shape the grammar cannot hold into one it can."""
    def rewrite(match):
        return "titleForValue(%s, in: %s)" % (match.group("raw"), match.group("table"))
    return OPTION_READ.sub(rewrite, source)


def parse(source):
    return Parser(tokenize(normalise(source))).parse()


# ---------------------------------------------------------------------------
# symbol table read out of the sources
# ---------------------------------------------------------------------------
DECL = re.compile(r"^\s*static\s+(?:let|var)\s+(\w+)\s*(?::[^=]+?)?=\s*(.+?)\s*$")
TUPLE_TABLE = re.compile(
    r"static\s+(?:let|var)\s+(\w+)\s*:\s*\[\s*\(\s*title:\s*String,\s*value:\s*Int\s*\)\s*\]\s*=\s*\["
    r"(?P<body>.*?)\n\s*\]", re.S)
STRING_TABLE = re.compile(
    r"static\s+(?:let|var)\s+(\w+)\s*:\s*\[\s*String\s*\]\s*=\s*\[(?P<body>.*?)(?:\n\s*\]|\Z)", re.S)
FUNC_DECL = re.compile(r"static\s+func\s+(\w+)\s*\(")

# An `@objc enum … : Int` is the other place a default lives. Four settings
# (`freeMouseMotionMode` and friends) get their absent-profile value from
# `Type(persistedRawValue: settings.x).displayKey`, so the fallback is the enum's
# `defaultMode` case rendered through `displayKey` -- a name the raw-value side of
# the bridge spells as a number. Reading the enum is what makes that checkable;
# filing it as "no fallback anywhere" would be the string-comparison shortcut this
# gate refuses to take.
ENUM_DECL = re.compile(r"@objc enum (\w+)\s*:\s*Int[^{]*\{")
ENUM_CASE = re.compile(r"^\s*case\s+(\w+)(?:\s*=\s*(-?\d+))?\s*$", re.M)
ENUM_DEFAULT = re.compile(r"static\s+let\s+defaultMode\s*:\s*Self\s*=\s*\.(\w+)")
# The same shape under another name. `MouseInputDriverStrategy` names its default
# `defaultStrategy`, and a reader that only knows `defaultMode` reads that enum as
# having no default at all -- which surfaced as a debt entry claiming
# "profile key mouseDriver is not bound in this profile", pointing a reviewer at the
# profile struct when the default is stated one file away.
ENUM_STATIC = re.compile(r"static\s+let\s+(\w+)\s*:\s*Self\s*=\s*\.(\w+)")
DISPLAY_KEY_BODY = re.compile(r"var\s+displayKey\s*:\s*String\s*\{(.*?)\n\s*\}", re.S)
DISPLAY_KEY_CASE = re.compile(
    r"case\s+\.(\w+)\s*:\s*return\s+\"((?:[^\"\\]|\\.)*)\"", re.S)
# Which case an absent (nil) persisted value lands on. This is read from the
# `default:` arm of `init(persistedRawValue:)` rather than assumed to be
# `defaultMode`: the two happen to coincide for every enum today, and an
# assumption that quietly stops being true is the exact class of defect this
# gate exists to catch, so the arm is transcribed instead.
INIT_PERSISTED = re.compile(r"init\s*\(\s*persistedRawValue\s*:\s*Int\?\s*\)\s*\{")
DEFAULT_ARM = re.compile(r"default\s*:\s*self\s*=\s*\.(\w+)")
ANY_ASSIGNMENT = re.compile(r"self\s*=\s*\.(\w+)")


def brace_matched(text, open_index):
    """Index just past the `}` that matches the `{` at `open_index`."""
    depth = 0
    index = open_index
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise Unresolved("unbalanced braces")


class Symbols:
    def __init__(self):
        self.values = {}       # name -> literal
        self.pending = {}      # name -> expression source (resolved transitively)
        self.exprs = {}        # name -> one-line expression it is defined by
        self.arrays = {}       # name -> [literal]
        self.tables = {}       # name -> {title: value}
        self.enums = {}        # name -> {"default": case, "keys": {case: title},
                               #           "raw": {case: int}}
        self.functions = set()

    def load(self, texts):
        # Declarations first: a list built from those constants
        # (`timingBufferLevels = [timingBufferLow, ...]`) cannot be read before
        # the names inside it have values.
        for text in texts:
            self._declarations(text)
        for text in texts:
            self._tables(text)
            self._arrays(text)
            self._enums(text)
            self.functions.update(FUNC_DECL.findall(text))
        self._resolve_pending()
        for text in texts:
            self._arrays(text)

    def _tables(self, text):
        for match in TUPLE_TABLE.finditer(text):
            pairs = re.findall(r'\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(-?\d+)\s*\)', match.group("body"))
            self.tables[match.group(1)] = {title: int(value) for title, value in pairs}

    def _enums(self, text):
        """Read `@objc enum … : Int` case lists, defaults and display names."""
        for match in ENUM_DECL.finditer(text):
            start = match.end() - 1  # the opening brace
            try:
                end = brace_matched(text, start)
            except Unresolved:
                continue
            body = text[start:end]
            name = match.group(1)
            explicit = {case: int(value) for case, value in ENUM_CASE.findall(body)
                        if value is not None}
            cases = [case for case, _ in ENUM_CASE.findall(body)]
            raw, counter = {}, 0
            for case in cases:
                if case in explicit:
                    counter = explicit[case]
                raw[case] = counter
                counter += 1
            keys = dict(DISPLAY_KEY_CASE.findall(
                DISPLAY_KEY_BODY.search(body).group(1))) \
                if DISPLAY_KEY_BODY.search(body) else {}
            default = ENUM_DEFAULT.search(body)
            entry = {"keys": keys, "raw": raw}
            if default:
                entry["default"] = default.group(1)
            entry["statics"] = dict(ENUM_STATIC.findall(body))
            absent = self._absent_case(body)
            if absent:
                entry["absent"] = absent
            # Merge rather than replace: an extension elsewhere may add `displayKey`.
            previous = self.enums.get(name, {})
            merged = {"keys": dict(previous.get("keys", {})), "raw": dict(previous.get("raw", {})),
                      "statics": dict(previous.get("statics", {}))}
            merged["keys"].update(keys)
            merged["statics"].update(entry.get("statics", {}))
            merged["raw"].update(raw or merged["raw"])
            if "default" in entry:
                merged["default"] = entry["default"]
            elif "default" in previous:
                merged["default"] = previous["default"]
            if "absent" in entry:
                merged["absent"] = entry["absent"]
            elif "absent" in previous:
                merged["absent"] = previous["absent"]
            self.enums[name] = merged

    @staticmethod
    def _absent_case(body):
        """The case a nil persisted value produces, read from `init(persistedRawValue:)`."""
        match = INIT_PERSISTED.search(body)
        if not match:
            return None
        try:
            init_body = body[match.end() - 1:brace_matched(body, match.end() - 1)]
        except Unresolved:
            return None
        arm = DEFAULT_ARM.search(init_body)
        if arm:
            return arm.group(1)
        if "switch" not in init_body:
            assignments = ANY_ASSIGNMENT.findall(init_body)
            if len(set(assignments)) == 1:
                return assignments[0]
        return None

    def _arrays(self, text):
        for match in INLINE_ARRAY.finditer(text):
            body = match.group("body")
            if "{" in body or "\\(" in body:
                continue
            entries = [item.strip() for item in split_top_level(body) if item.strip()]
            if all(item.startswith('"') and item.endswith('"') and len(item) > 1
                   for item in entries):
                self.arrays[match.group(1)] = [item[1:-1] for item in entries]
        for match in NUMBER_ARRAY.finditer(text):
            body = match.group("body")
            if "{" in body or "\\(" in body:
                continue
            entries = [item.strip() for item in split_top_level(body) if item.strip()]
            numbers = [as_literal(item) for item in entries]
            if any(number is NOT_LITERAL for number in numbers):
                continue  # a computed entry is refused, as an interpolated string is
            self.arrays[match.group(1)] = numbers
        for match in STRING_TABLE.finditer(text):
            body = match.group("body")
            if "{" in body or "\\(" in body:
                continue  # interpolated entries are refused at evaluation time
            entries = [item.strip() for item in split_top_level(body) if item.strip()]
            resolved = []
            for entry in entries:
                if entry.startswith('"') and entry.endswith('"') and len(entry) > 1:
                    resolved.append(entry[1:-1])
                elif re.fullmatch(r"[A-Za-z_]\w*", entry):
                    if entry not in self.values:
                        return  # forward reference: retry once declarations land
                    resolved.append(self.values[entry])
                else:
                    return
            self.arrays[match.group(1)] = resolved

    def _declarations(self, text):
        for line in text.splitlines():
            match = DECL.match(line)
            if not match:
                continue
            name, source = match.group(1), match.group(2)
            source = re.sub(r"\s*//.*$", "", source).strip()
            if source.endswith(",") and not source.endswith("),"):
                source = source[:-1].strip()
            literal = as_literal(source)
            if literal is not NOT_LITERAL:
                self.values.setdefault(name, literal)
            elif re.fullmatch(r"[A-Za-z_]\w*", source):
                self.pending.setdefault(name, source)
            elif source and "{" not in source and "\n" not in source:
                # A one-line expression constant (`defaultMouseDriver =
                # MouseInputDriverStrategy.defaultStrategy.displayKey`). Held aside
                # rather than dropped so a binding can say *which* expression it
                # choked on; a multi-line literal is a table or array, and those are
                # read by their own readers.
                self.exprs.setdefault(name, source)

    def _resolve_pending(self):
        for _ in range(12):
            outstanding = dict(self.pending)
            for name, source in outstanding.items():
                target = self.values.get(source)
                if source in self.values:
                    self.values.setdefault(name, target)
                    self.pending.pop(name, None)
            if not outstanding:
                break


# `None` is a value Swift holds, so it cannot double as "this text is not a literal".
NOT_LITERAL = object()


def as_literal(source):
    if re.fullmatch(r"-?\d+\.\d+|-?\d+", source):
        return float(source) if "." in source else int(source)
    if source in ("true", "false"):
        return source == "true"
    if source == "nil":
        # `static let defaultCustomFps: CGFloat? = nil` states the shipped default
        # as the absence of a value. Refusing to read it left the key unproven, and
        # an unproven key is what this file is for -- not an excuse to stop looking.
        return None
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', source):
        return source[1:-1]
    return NOT_LITERAL


def split_top_level(body):
    parts, depth, current, quote, index = [], 0, "", False, 0
    while index < len(body):
        char = body[index]
        if quote:
            current += char
            if char == "\\":
                current += body[index + 1]
                index += 2
                continue
            if char == '"':
                quote = False
        elif char == '"':
            quote = True
            current += char
        elif char in "([{":
            depth += 1
            current += char
        elif char in ")]}":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
        index += 1
    parts.append(current)
    return parts


# ---------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------
class Evaluator:
    """Reduce a fallback expression to a literal.

    `env` binds the neighbour settings a fallback reads (`settings.framePacing`
    and friends). A name that is in neither the symbol table nor the environment
    raises Unresolved -- assuming a value is the exact failure this gate exists
    to catch.
    """

    def __init__(self, symbols, env=None):
        self.symbols = symbols
        self.env = dict(env or {})

    _MISSING = object()

    def symbol_value(self, name):
        """Look a bare or qualified static member up in the symbol table."""
        for store in (self.symbols.values, self.symbols.arrays, self.symbols.tables):
            if name in store:
                return store[name]
        # A `static let` written as a one-line expression is a stated default, not a
        # gap: `defaultMouseDriver = MouseInputDriverStrategy.defaultStrategy.displayKey`
        # says exactly which row the picker shows, and refusing to follow the binding
        # reported the loader's own default as "unknown symbol". Following it is the
        # same reading the `?? defaultX` shape already gets -- the name is a window onto
        # its right-hand side, so moving the enum moves the default with it.
        source = self.symbols.exprs.get(name)
        if source:
            # `a = b; b = a` is two bindings with no value under them, so the walk is
            # bounded rather than left to the call stack.
            walking = getattr(self, "_walking", None)
            if walking is None:
                walking = self._walking = set()
            if name in walking:
                raise Unresolved("symbol %s is defined in a cycle" % name)
            walking.add(name)
            try:
                return self.value(parse(source))
            finally:
                walking.discard(name)
        return self._MISSING

    def value(self, node):
        kind = node[0]
        if kind == "literal":
            return node[1]
        if kind == "name":
            if node[1] in self.env:
                value = self.env[node[1]]
                if isinstance(value, Deferred):
                    return self.value(parse(value.source))
                return value
            # A bare identifier in these files is also a static member of the type
            # that owns the expression (`guard let rawValue else { return
            # defaultFrameQueueTarget }`), so the symbol table answers it too. Only
            # a name that is in neither place is a gap.
            resolved = self.symbol_value(node[1])
            if resolved is not self._MISSING:
                return resolved
            raise Unresolved("unbound name %r" % node[1])
        if kind == "symbol":
            resolved = self.symbol_value(node[1])
            if resolved is not self._MISSING:
                return resolved
            raise Unresolved("unknown symbol %r" % node[1])
        if kind == "array":
            return [self.value(item) for item in node[1]]
        if kind == "binop" and node[1] == "??":
            # Swift only evaluates the right side when the left is nil, and a
            # missing setting is exactly `nil` here, so the branch that is taken
            # is a fact about the profile rather than something to guess.
            left = self.value(node[2])
            return left if left is not None else self.value(node[3])
        if kind == "not":
            return not self.truthy(self.value(node[1]))
        if kind == "ternary":
            test = self.value(node[1])
            return self.value(node[2]) if self.truthy(test) else self.value(node[3])
        if kind == "binop":
            return self.binop(node[1], self.value(node[2]), self.value(node[3]))
        if kind == "member":
            return self.member(node[1], node[2])
        if kind == "call":
            return self.call(node[1], node[2])
        raise Unresolved("node %r" % kind)

    @staticmethod
    def truthy(value):
        if isinstance(value, bool):
            return value
        if value is None:
            raise Unresolved("truthiness of nil")
        raise Unresolved("truthiness of a non-Bool %r" % (value,))

    @staticmethod
    def binop(operator, left, right):
        if operator == "&&":
            return Evaluator.truthy(left) and Evaluator.truthy(right)
        if operator == "||":
            return Evaluator.truthy(left) or Evaluator.truthy(right)
        if operator in ("==", "!="):
            equal = left == right
            return equal if operator == "==" else not equal
        if operator in ("<", ">", "<=", ">="):
            return {"<": left < right, ">": left > right,
                    "<=": left <= right, ">=": left >= right}[operator]
        if isinstance(left, str) or isinstance(right, str):
            raise Unresolved("string arithmetic is out of scope")
        return {"+": left + right, "-": left - right,
                "*": left * right, "/": left / right}[operator]

    def member(self, name, base):
        # `settings.x` is a read of the stored profile: its value is whatever the
        # profile holds, which is what `env` binds. An absent binding is a gap in
        # the analysis, not a zero.
        if base[0] == "name" and base[1] == "settings":
            if name in self.env:
                value = self.env[name]
                if isinstance(value, Deferred):
                    return self.value(parse(value.source))
                return value
            raise Unresolved("profile key %s is not bound in this profile" % name)
        # `Type.defaultMode` is a static member of an enum, and the enum is described
        # by its cases rather than by a literal in the symbol table. It yields the same
        # marker an initializer yields so `.rawValue` and `.displayKey` both resolve.
        # The member's *name* is not part of the shape: four enums spell it
        # `defaultMode`, the mouse driver's spells it `defaultStrategy`, and matching on
        # the name is what made the latter read as "enum has no default".
        if base[0] == "name" and base[1] in self.symbols.enums:
            entry = self.symbols.enums[base[1]]
            statics = entry.get("statics", {})
            if name in statics:
                return ("enum-value", base[1], statics[name])
            if name == "default" and "default" in entry:
                return ("enum-value", base[1], entry["default"])
            # `Type.gameController` is the case, not a lookup: an enum spelled out by
            # its cases states which case a name picks, so reading a case as a static
            # member needs no defaulting rule at all. This matters once the audit
            # reads through a helper -- a helper is free to end on any case, and only
            # the `default*` spelling being answerable would make the reader blind to
            # exactly the mutations this wave exists to catch.
            if name in entry.get("raw", {}):
                return ("enum-value", base[1], name)
            if name.startswith("default"):
                raise Unresolved("%s declares no static member %s" % (base[1], name))
        target = self.value(base) if base[0] != "symbol" or base[1] not in ("enhancedAudioEQGains",) else None
        # An enum initializer evaluates to a marker rather than a literal, so
        # `.displayKey` and `.rawValue` resolve against the table the enum itself
        # declares. Without this the picker's label and the stored number look like two
        # different defaults, which is precisely the false fork this gate must not file.
        if isinstance(target, tuple) and target[:1] == ("enum-value",):
            _, enum_name, case = target
            entry = self.symbols.enums.get(enum_name, {})
            if name == "displayKey" and case in entry.get("keys", {}):
                return entry["keys"][case]
            if name == "rawValue" and case in entry.get("raw", {}):
                return entry["raw"][case]
            raise Unresolved("%s.%s is not readable" % (enum_name, name))
        if name == "count":
            if isinstance(target, (list, tuple, dict)):
                return len(target)
            raise Unresolved(".count of %r" % (target,))
        if name == "first":
            if isinstance(target, list) and target:
                return target[0]
            raise Unresolved(".first of an empty or non-sequence value")
        raise Unresolved("unsupported member %r" % name)

    def callee_name(self, node):
        if node[0] == "symbol":
            return node[1]
        if node[0] == "member":
            return node[1]
        # An enum initializer is spelled as a bare type name, unlike the
        # `Self.helper(...)` form the fallbacks elsewhere use.
        if node[0] == "name":
            return node[1]
        raise Unresolved("cannot resolve the callee")

    def call(self, callee, arguments):
        name = self.callee_name(callee)
        positional = [self.value(node) for _, node in arguments]
        named = {label: self.value(node) for label, node in arguments if label}
        if name == "getInt":
            selected = named.get("from", positional[0] if positional else None)
            names = named.get("in", positional[1] if len(positional) > 1 else None)
            if not isinstance(names, list):
                raise Unresolved("getInt without a list")
            # Swift answers 0 when the selection is absent. Keeping that matters:
            # a renamed option silently becomes index 0 instead of failing.
            return names.index(selected) if selected in names else 0
        if name == "getString":
            index = named.get("from", positional[0] if positional else None)
            names = named.get("in", positional[1] if len(positional) > 1 else None)
            if not isinstance(names, list):
                raise Unresolved("getString without a list")
            if isinstance(index, int) and 0 <= index < len(names):
                return names[index]
            return names[0]
        if name == "titleForValue":
            # The label the option table carries for a stored number. Refusing an
            # unknown number is deliberate: `xRawValue(for:)` above answers 0 because
            # that is what Swift does with a failed `firstIndex(of:)`, but this call
            # replaces a `?.title` that yields nil and falls through to whatever the
            # expression spells next, so inventing a label here could hide a fork.
            raw = named.get("value", positional[0] if positional else None)
            table = named.get("in", positional[1] if len(positional) > 1 else None)
            if not isinstance(table, dict):
                raise Unresolved("titleForValue without a readable options table")
            labels = [title for title, value in table.items() if value == raw]
            if len(labels) != 1:
                raise Unresolved("value %r is carried by %d options" % (raw, len(labels)))
            return labels[0]
        match = re.fullmatch(r"(\w+)RawValue", name)
        if match:
            table = self.symbols.tables.get(match.group(1) + "Options")
            selection = named.get("for", positional[0] if positional else None)
            if not isinstance(table, dict):
                raise Unresolved("%s has no readable options table" % name)
            return table.get(selection, 0)
        if name in self.symbols.enums:
            return self.enum_init(name, positional, named)
        raise Unresolved("unsupported call %s(...)" % name)

    def enum_init(self, name, positional, named):
        """`Type(persistedRawValue: settings.x)` for the profile under audit.

        The audited profile never stored the key, so the argument is nil and the
        initializer lands on whichever case its own `default:` arm names. A non-nil
        argument is refused: the value then depends on what the user stored, which is
        not the state being compared.
        """
        entry = self.symbols.enums[name]
        if "persistedRawValue" in named:
            argument = named["persistedRawValue"]
        elif positional:
            argument = positional[0]
        else:
            raise Unresolved("%s(...) has no persisted value to read" % name)
        if argument is not None:
            raise Unresolved("%s(persistedRawValue:) is only evaluable when absent"
                             % name)
        case = entry.get("absent") or entry.get("default")
        if not case:
            raise Unresolved("%s does not say which case an absent value gives" % name)
        return ("enum-value", name, case)

    @staticmethod
    def getInt(selected, names):
        return names.index(selected) if selected in names else 0

    @staticmethod
    def getString(index, names):
        return names[index] if isinstance(index, int) and 0 <= index < len(names) else names[0]


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------
# Keys that cannot be reduced to a literal, and the condition under which the
# difference stays harmless. The condition is re-checked on every run; an entry
# whose condition no longer holds is a violation, and so is an entry for a key
# that no longer needs one.
LEDGER = {
    "enhancedAudioEQLayout": {
        "condition": "no ObjC reader asks the stream dictionary for this key",
        "check": "objc_does_not_read_key:enhancedAudioEQLayout",
        "why": "Persistence infers a layout from the stored gain count where the "
               "bridge spells the shipped default, so the picker can show 24-Band "
               "while the dictionary says 12-Band; nothing on the stream side reads "
               "the key, so no behaviour differs today",
    },
}



# ---------------------------------------------------------------------------
# the third layer: what Objective-C does when the dictionary has no key
# ---------------------------------------------------------------------------
# `getSettings(for:)` ends with `compactMapValues { $0 }`, so a setting the bridge
# exports without a fallback does not arrive as NSNull -- the key is simply absent.
# The stream side then either ignores it or substitutes its own number, and that
# substitution is a default too. An audit of two layers would report "the interface
# says Balanced, the bridge says nothing" and call it a divergence when the stream
# actually runs Balanced, or would miss a real fork because the two places that do
# agree are both one file away from where it looked. All three are read here.
OBJC_FALLBACK = re.compile(
    r'prefs\[@"(?P<key>[A-Za-z_]\w*)"\]\s*!=\s*nil\s*\?'
    r'(?P<used>.*?)\s*:\s*(?P<fallback>[^;{}]*?)(?=\s*[;,)])', re.S)
# The dictionary is bound to eight different local names across the files that read
# it -- `prefs`, `settings`, `windowPrefs`, `windowGamepadPrefs`, `resignPrefs`,
# `resignGamepadPrefs`, `currentPrefs`, `hostSettings`. The pattern used to list two
# of them, which made the wider read list decorative: `StreamViewController.m` was
# scanned, and the reads through `windowPrefs[@"muteOnFocusLoss"]` and
# `windowGamepadPrefs[@"backgroundGamepad"]` still came back absent, so two keys the
# stream demonstrably uses were reported as unread. Matching any identifier would
# over-count, so the names come from the file itself: a name counts when that file
# binds it from `[SettingsClass getSettingsFor:]`. Over-counting stays the safe
# direction -- a spurious read retires a ledger excuse and the key gets reported --
# while an under-count is the silence that lets a fork ship.
OBJC_BIND = re.compile(
    r"\b([A-Za-z_]\w*)\s*=\s*(?:id\s*)?\[SettingsClass getSettingsFor")
OBJC_READ = re.compile(r'\b([A-Za-z_]\w*)\[@"([A-Za-z_]\w*)"\]')
# The guard clause is read with a brace-matching scan rather than a regex over the
# function text. A pattern cannot express "the braces balance" -- the body of a
# `guard let ... else { ... }` routinely holds a closure (`options.first(where: { ...
# })?.title ?? "Off"`), so a `[^{}]*` body stops at the first inner brace and the
# default goes unread. What that costs is not a missing note: an unread default is
# reported as "no fallback anywhere", which is a claim about the code that the code
# contradicts. GUARD_LET finds the clause, brace_matched finds its end, and FUNC_DECL --
# the same pattern the symbol table uses -- attributes it to the function that owns it.
GUARD_LET = re.compile(r"guard let \w+ else \{")
# The absent-value arm of every `...Selection(for:)` helper in this codebase is one
# spelling: `Options.first(where: { $0.value == defaultX })?.title ?? "Off"`. Reading it
# means reading a closure, and the parser here covers expressions, not closures -- so
# the idiom is normalised to a call the evaluator resolves against the option table it
# names, rather than the answer being written down. What the normalisation must not do
# is invent a value: `title(forRaw:)` looks the number up in the same table the picker
# renders, and self-test item 9 breaks the table to show the read is real.
OPTION_TITLE = re.compile(
    r"\b(?P<table>\w*[Oo]ptions)\s*\.\s*first\s*\(\s*where:\s*\{\s*\$0\s*\.\s*value"
    r"\s*==\s*(?P<raw>[\w.]+)\s*\}\s*\)\s*\?\.title")
# Any argument label is allowed: the helpers take `for:`, `persistedRawValue:`,
# `rawValue:` and `selection:`, and a label-specific pattern silently matched
# none of them, which read as "the interface has no default anywhere".
HELPER_ARGUMENT = re.compile(
    r"(?:Self|SettingsModel|SettingsClass)\.(?P<name>\w+)\(\s*(?:\w+\s*:\s*)?"
    r"settings\.(?P<key>[A-Za-z_]\w*)\s*(?:,[^()]*\))?"
    r"\)")
# The same read written against an optional chain (`?.key ?? default`) is a fallback
# for that key: `Settings.getSettings(for: key)?.enhancedAudioEQGains
# ?? SettingsModel.defaultEnhancedAudioEQGains` is the accessor Objective-C calls, so
# the stream layer does state a default there. Matching only `settings.x ??` reported
# three keys as having no default on either side, and the audit said so in a file whose
# purpose is to refuse false excuses. The chain's left side must be a `Settings` lookup,
# not any optional, so `runtimeCadenceReadout(for: key)?.refreshHz ?? 0` -- a runtime
# readout, not a profile field -- cannot lend a default to a setting.
CHAINED_FALLBACK = re.compile(
    r"(?:Settings\.getSettings\(for:|Settings\.persistedSettings\(for:)\s*[^)]*\)"
    r"\s*\?\.\s*(?P<key>[A-Za-z_]\w*)\s*(?P<tail>\?\?|\Z|\n)", re.M)
AFTER_CHAIN = re.compile(r"\s*(?:\?\.\s*\w+\s*)?\?\?")
# A `let` inside the same function can be the fallback (`?? legacyBias`), so a
# single-line binding is a symbol like any other. Multi-line bindings are left
# out: reading them would need brace tracking, and the audit says so rather than
# guessing.
# `re.M` is what makes the `^`/`$` anchors mean lines rather than the file;
# without it the pattern matched nothing at all, and the fallback that reads
# like `?? legacyResponsivenessBias` came back unbound.
LOCAL_LET = re.compile(r"^\s*let\s+(\w+)\s*=\s*(.+?)\s*$", re.M)


def objc_fallbacks(tree):
    """{setting: expression_source} for every `prefs[@"k"] != nil ? .. : <fallback>`."""
    text = tree.read(STREAM_VIEW)
    found = {}
    for match in OBJC_FALLBACK.finditer(text):
        source = re.sub(r"\s+", " ", match.group("fallback")).strip()
        found.setdefault(match.group("key"), []).append((
            text[:match.start()].count("\n") + 1, source))
    return found


def objc_reads(tree):
    """Every setting Objective-C asks the dictionary for, fallback or not."""
    return {key for key, _ in read_keys(tree)}


def objc_reader_files(tree):
    """Objective-C sources that bind the stream dictionary at all."""
    for dirpath, _, names in os.walk(OBJC_SOURCE_ROOT):
        for name in sorted(names):
            if not name.endswith((".m", ".mm")):
                continue
            relative = os.path.relpath(os.path.join(dirpath, name), ROOT)
            if "getSettingsFor" in tree.read(relative):
                yield relative


def read_keys(tree):
    """[(key, file)] for every dictionary read in a file that binds the dictionary.

    Returned as pairs rather than a set because the self-test has to name where a
    newly visible read came from: "the audit sees this key now" and "the audit sees
    this key in the file the mutation edited" are different claims, and only the
    second one shows that widening the scan actually bought something.
    """
    found = []
    for relative in objc_reader_files(tree):
        text = tree.read(relative)
        bound = set(OBJC_BIND.findall(text))
        for name, key in OBJC_READ.findall(text):
            if name in bound:
                found.append((key, relative))
    return found


def local_bindings(text):
    """{name: expression_source} for single-line `let name = expr` bindings."""
    found = {}
    for match in LOCAL_LET.finditer(text):
        found.setdefault(match.group(1), re.sub(r"\s+", " ", match.group(2)))
    return found


def helper_defaults(tree):
    """{helper: default-expression} for `guard let x else { return defaultX }`.

    A bare `settings.x` inside `Self.someSelection(for: settings.x)` is not a missing
    fallback; the fallback lives in the helper. Reading only the call site would call
    every one of those a divergence, which is how a two-layer draft of this gate
    invented twenty fake forks while missing the two real ones.
    """
    found = {}
    for relative in (BRIDGE, PERSISTENCE, DERIVED, MODEL):
        text = tree.read(relative)
        # At most one function-scope clause is taken per function: a guard inside a
        # closure inside the function returns from the closure, and a function with two
        # such clauses states two defaults, which is a conflict for `self_conflict` to
        # judge rather than something to settle by taking the first one found.
        claimed = {}
        for clause in GUARD_LET.finditer(text):
            try:
                end = brace_matched(text, clause.end() - 1)
            except Unresolved:
                continue
            body = text[clause.end():end].strip()
            returned = re.match(r"return\b\s*", body)
            if not returned:
                continue
            owner = list(FUNC_DECL.finditer(text[:clause.start()]))
            if not owner or owner[-1].group(1) in claimed:
                continue
            claimed[owner[-1].group(1)] = True
            # The offset is found, not assumed: the clause opens with `{`, so the
            # keyword is somewhere inside the body rather than at a fixed distance from
            # the brace, and reading from `brace + len("return")` starts mid-word.
            start = text.index(body, clause.end()) + returned.end()
            default, _ = extract_expression(text, start)
            default = re.sub(r"\s+", " ", default).strip()
            if not default:
                continue
            found.setdefault(owner[-1].group(1), []).append((
                text[:clause.start()].count("\n") + 1, default))
    return found


def helper_wrapped(tree):
    """{setting: [helper]} for `Self.<helper>(for: settings.<setting>)`."""
    found = {}
    for relative in (BRIDGE, PERSISTENCE):
        text = tree.read(relative)
        for match in HELPER_ARGUMENT.finditer(text):
            found.setdefault(match.group("key"), set()).add(match.group("name"))
    return found

# `Type(persistedRawValue: settings.x).displayKey` is a read with no `??`, so the
# fallback lives inside the initializer. Without this the audit says "no fallback
# anywhere" for four input settings whose two layers do agree, and a ledger entry
# would hide a fork that could be detected. The expression is kept whole -- the
# evaluator resolves the case, the display name, and the raw value from the enum.
ENUM_INIT_READ = re.compile(
    r"\b([A-Z]\w+)\(\s*persistedRawValue:\s*settings\.(?P<key>[A-Za-z_]\w*)\s*\)"
    r"\s*\.(?P<member>displayKey|rawValue)")


def enum_init_reads(tree):
    """{setting: expression source} for enum-initializer reads of a profile key."""
    found = {}
    for relative in (BRIDGE, PERSISTENCE):
        text = tree.read(relative)
        for match in ENUM_INIT_READ.finditer(text):
            source = re.sub(r"\s+", " ", match.group(0))
            found.setdefault(match.group("key"), set()).add(source)
    return found


def settings_fields(tree):
    """{field: optional?} for the profile struct.

    A fallback on a non-optional field is dead code, and a `settings.x` read on one
    is a value the profile always has. Without the nullability the audit has to guess
    whether an absent key is possible at all.
    """
    text = tree.read(STORE)
    body = text[text.index("struct Settings:"):]
    optional = set(re.findall(r"(?:let|var)\s+(\w+)\s*:\s*[^=\n]+\?", body))
    # The type fragment may itself contain `?`, and a property may carry an
    # initialiser (`var hdrToneMappingPolicy: Int? = nil`), so the line -- not the
    # type -- is the unit being matched.
    declared = set(re.findall(r"(?:let|var)\s+(\w+)\s*:\s*[^\n]*\n", body))
    return {name: (name in optional) for name in declared - PRIVATE_FIELDS}


def published_defaults_gap(model, fields, persistence, bridge, stream_view, loader):
    """{profile field: [(layer, line)]} for the published fields a default never
    reaches.

    The key books above are built from what the layers *read*. A field that the
    profile struct declares optional but no layer ever defaults is invisible to
    them: `settings.x` is nil, the interface decodes the struct's zero, and the
    stream runs with the C zero of its type, and both sides look quiet because
    nothing states a value to disagree with. The gate here asks the other
    question -- for every `@Published` optional the model carries, does at least
    one audited layer state what "never stored" runs with -- and it is ratcheted:
    the current tree has zero gaps, so a new field is a violation until a default
    is written for it in the persistence layer, the bridge, an Objective-C
    substitution, or the loader.
    """
    optional = re.findall(r"@Published\s+(?:var|let)\s+(\w+)\s*:\s*[^\n]*\?", model)
    gap = {}
    for name in optional:
        if fields.get(name) is not True:
            continue  # not a profile field: a UI state the profile never persists
        stated = []
        if name in persistence:
            stated.append(("persistence", persistence[name][0][0]))
        if name in bridge:
            stated.append(("bridge", bridge[name][0][0]))
        if name in stream_view:
            stated.append(("stream", stream_view[name][0][0]))
        if name in loader:
            stated.append(("loader", loader[name][0][0]))
        if not stated:
            gap[name] = stated
    return gap

PRIVATE_FIELDS = frozenset(("cachedPersistedSettingsByProfileKey",))


def profile_bindings(symbols, fields, overrides=None):
    """Bind every profile field for the all-defaults profile.

    Non-optional fields are bound to the value the struct is decoded with, which is
    the shipped default that `loadDefaultSettings()` writes; optional fields are bound
    to `None`, because the case under audit is the one where nothing was ever stored.
    A field that is bound to neither is a gap, and the evaluator refuses to guess.
    """
    env = {}
    for name, optional in fields.items():
        if optional:
            env[name] = None
        else:
            symbol = "default" + name[0].upper() + name[1:]
            if symbol in symbols.values:
                env[name] = symbols.values[symbol]
            elif symbol in symbols.pending or symbol in symbols.exprs:
                source = symbols.pending.get(symbol) or symbols.exprs[symbol]
                # The constant exists but is written as an expression -- 
                # `defaultMouseDriver = MouseInputDriverStrategy.defaultStrategy
                # .displayKey` -- so the binding is the expression and the evaluator
                # either reduces it or says which shape stopped it. Binding nothing
                # instead reported "profile key mouseDriver is not bound in this
                # profile", which points the reviewer at the wrong file: the default
                # is stated, the reader is what cannot read it.
                env[name] = Deferred(source)
            elif name in NON_OPTIONAL_FROM_DEFAULTS:
                env[name] = NON_OPTIONAL_FROM_DEFAULTS[name]
    env.update(overrides or {})
    return env


# A non-optional field whose value comes from a computed default rather than a
# `defaultX` constant. Listed rather than inferred: an inferred value that drifted
# would silently change what the audit concludes about the keys that read it.
NON_OPTIONAL_FROM_DEFAULTS = {}


def evaluate_sources(evaluator, sources):
    return [evaluator.value(parse(source)) for _, source in sources]


def self_conflict(values):
    """Spellings one layer writes for the same absent key that do not agree.

    A layer can state a default twice: the bridge spells one fallback in the
    dictionary it hands the stream and another in the accessor Objective-C calls
    directly, and the interface can spell one in the loader and another in the helper
    the picker reads. Which of the two the runtime reaches depends on which path the
    reader took, so a layer that disagrees with itself has two answers to "what runs
    when nothing was stored" -- and the two-layer comparison cannot see it, because
    each side picks one expression and they may both pick the same one. Today one key
    has two spellings on each side and they hold the same value, which is why the
    check passes; it is a check, not a note.
    """
    distinct = []
    for value in values:
        if not any(equivalent(value, seen) for seen in distinct):
            distinct.append(value)
    return distinct if len(distinct) > 1 else None


def same_expression(interface, stream):
    """True when both layers spell one and the same expression.

    Compared as syntax trees, so `Self.f(...)` and `SettingsModel.f(...)` -- the two
    spellings the same codebase uses in the two files -- count as one expression.
    An expression that is literally one expression cannot have forked, which is what
    lets a key reading a stored non-optional field (`displayMode` reads
    `autoFullscreen` both ways) be settled without inventing a value for it.

    An expression that will not evaluate still counts here, and that is deliberate:
    the two sides share one expression *and* one environment, so any gap in the
    analysis is a gap on both sides at once. Refusing to conclude in that case would
    report a fork that cannot exist, and the report would be noise that hides the
    forks that can.
    """
    left = [interface["expression"]] if interface.get("expression") \
        else list(interface.get("source", []))
    right = [stream["expression"]] if stream.get("expression") \
        else list(stream.get("source", []))
    if len(left) != 1 or len(right) != 1:
        return False
    try:
        return parse(left[0]) == parse(right[0])
    except Unresolved:
        return False


def describe(sources):
    return sorted({source for _, source in sources})


RAW_VALUE_CALL = re.compile(r"\b(\w+)RawValue\b")


def value_tables_named(sources, symbols):
    """Every `{display name: stored number}` map a source text names.

    Two shapes exist. A `(title: String, value: Int)` option table is named through
    the `xRawValue(for:)` helper that reads it -- the helper's own name is the only
    thing that identifies which table it consults, and it is the same naming rule
    `Evaluator.call` already uses, so the identity is inherited rather than guessed.
    The other shape is an `@objc enum … : Int`, named directly by its type, whose
    display names and raw values both come out of the enum's text. Both are collected
    because the label side and the number side of one choice live in different files
    and either spelling can appear on either side.
    """
    tables = []
    for source in sources:
        for match in RAW_VALUE_CALL.finditer(source):
            candidate = match.group(1) + "Options"
            if candidate in symbols.tables:
                tables.append(symbols.tables[candidate])
        for identifier in re.findall(r"[A-Za-z_]\w*", source):
            # Two spellings name a table: the setting's own name plus the suffix,
            # which is how `xRawValue(for:)` is resolved, and the table's name
            # written out, which is how a `first(where:)` lookup names it. Only the
            # second spelling exists once normalisation exists, and a source that
            # names the table is the strongest claim of the two.
            candidate = identifier + "Options"
            if candidate in symbols.tables:
                tables.append(symbols.tables[candidate])
            if identifier in symbols.tables:
                tables.append(symbols.tables[identifier])
            entry = symbols.enums.get(identifier)
            if entry and entry.get("keys") and entry.get("raw"):
                tables.append({title: entry["raw"][case]
                               for case, title in entry["keys"].items()
                               if case in entry["raw"]})
    return tables


def display_names_agree(interface, stream, symbols):
    """True when the picker's label and the stream's number are one option.

    The interface layer returns what the row shows (`"Auto"`), the bridge exports the
    number that gets stored (`0`), and both come from one table. Calling that a fork is
    the mistake this function prevents; calling it an agreement without checking the
    table is the opposite mistake, so the mapping is looked up rather than assumed --
    a fallback that points at a *different* row still reports. A table that names the
    label but maps it elsewhere is enough to refuse, so an ambiguous spelling is never
    resolved by picking whichever table happens to match.
    """
    label, number = interface.get("value"), stream.get("value")
    if isinstance(number, bool) or not isinstance(number, int):
        return False
    if not isinstance(label, str):
        return False
    tables = value_tables_named(stream.get("source", []), symbols)
    tables += value_tables_named(interface.get("source", []), symbols)
    naming = [table for table in tables if label in table]
    return bool(naming) and all(table[label] == number for table in naming)


def display_name_conflict(interface, stream, symbols):
    """The row *every* naming table gives the interface label, when it is not `stream`'s.

    The mirror of `display_names_agree`, and it exists because the absence of agreement
    is not one state: "a table resolves the label to another number" and "nothing in the
    source says which row this number is" look the same to the caller unless they are
    told apart, and the second is unproven while the first is a fork. Reporting the
    first as unproven is not conservative -- it lets a change that moves the stream to
    another option be filed as a gap in the analysis, which is exactly the kind of
    quiet the other rules in this file were written to remove.

    Returns that number only when the tables that name the label agree on it and it
    differs from the stream's; None otherwise. The unanimity is required, not decoration:
    two tables that resolve one label to two rows mean the source does not say which row
    governs, and that is a question for a reviewer, so it stays unproven. The unproven
    account is where an unprovable claim must remain -- promoting it to a divergence to
    avoid a debt entry would put a verdict the source does not support into the one book
    that cannot be excused.
    """
    label, number = interface.get("value"), stream.get("value")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    if not isinstance(label, str):
        return None
    tables = value_tables_named(stream.get("source", []), symbols)
    tables += value_tables_named(interface.get("source", []), symbols)
    naming = [table[label] for table in tables if label in table]
    if not naming:
        return None
    first = naming[0]
    if any(other != first for other in naming[1:]):
        return None  # the tables answer two different ways: which governs is unknown
    return first if first != number else None


# `Self.getInt(from: Self.defaultPacingOptions, in: Self.pacingOptions)` is how the
# stream spells "the row the picker shows". The table is a plain `[String]`, so its
# stored number is the element's position and there is no `(title, value)` pair to
# read -- `value_tables_named` cannot see it, and `Symbols.arrays` holds the labels
# under the name the call's `in:` label names.
STRING_INDEX_READ = re.compile(r"\bgetInt\(\s*(?:[^()]*?,\s*)?in:\s*(?:[\w.]*\.)?(\w+)")


def index_tables_named(sources, symbols):
    """The `[String]` option tables a piece of source reads an index out of.

    Only the table named at the call site counts. Searching the surrounding text for
    any array whose elements include the label would let an unrelated list -- the app
    has `mouseModes`, `videoCodecs`, and a dozen more, and two of them carry the word
    "Auto" -- settle a comparison it has nothing to do with.
    """
    found = []
    for source in sources:
        for match in STRING_INDEX_READ.finditer(source):
            table = symbols.arrays.get(match.group(1))
            if table:
                found.append((match.group(1), table))
    return found


# The loader decodes a stored index back into the label the row shows:
# `selectedPacingOptions = Self.getString(from: settings.framePacing, in:
# Self.pacingOptions)`. The table named there is the same table `getInt` writes the
# index into, so it is what says which option the number 0 stands for -- the source
# fact a bare `return 0` in an accessor is missing.
ENCODE_TABLE = re.compile(r"\bgetString\(\s*from:\s*settings\.(\w+)"
                          r"(?:\s*\?\?[^,]*)?,?\s*in:\s*(?:[\w.]*\.)?(\w+)", re.S)


def key_index_tables(tree):
    """{profile key: [table name]} for keys the loader decodes out of an option array.

    Read out of the loader rather than hard-coded: a table that rots silently is the
    defect class this whole gate exists for. A key that decodes out of two different
    tables is dropped rather than guessed -- the index would then mean two things, and
    picking one is how a false green gets manufactured.
    """
    text = tree.read(PERSISTENCE)
    marker = re.search(r"func loadSettings\(\)\s*\{", text)
    if not marker:
        return {}
    try:
        body = text[marker.end():brace_matched(text, marker.end() - 1)]
    except Unresolved:
        return {}
    found = {}
    for key, table in ENCODE_TABLE.findall(body):
        found.setdefault(key, set()).add(table)
    return {key: sorted(tables) for key, tables in found.items() if len(tables) == 1}


def label_index_agreement(interface, stream, symbols, loader_tables=()):
    """Decide a label compared against an index: 'agrees', 'conflicts', or 'unproven'.

    Three answers, because there are three situations and the old code conflated two
    of them. When the stream side reads an index out of a table it names
    (`in: pacingOptions`), the table settles the question: `1` beside "Smoothest
    Video" is that row, and calling it a fork is the false red this function prevents
    -- three of them, on `audioConfiguration`, `controllerDriver`, and `framePacing`,
    all shipped and all harmless. When the stream side reads *no* table --
    `audioConfiguration(for:)` ends with a bare `return 0` and a `// Stereo default`
    comment -- nothing in the source says which row 0 is, and the comment is not
    evidence: a comment is exactly what stops agreeing with the code. That is
    'unproven', which goes on the debt books. And when the named table puts the label
    at a different index, that is a real fork and stays a violation.

    Returning 'unproven' rather than falling through to a violation is the strict
    direction: the key leaves the ledger-less green column, a reviewer sees it, and a
    later edit that spells the index against the table clears it for real.
    """
    label, number = interface.get("value"), stream.get("value")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    if not isinstance(label, str):
        return None
    tables = index_tables_named(stream.get("source", ()), symbols)
    tables += index_tables_named(interface.get("source", ()), symbols)
    if not tables:
        # The accessor spells a bare number, so the call site names no table. The
        # loader may still name one: `audioConfiguration` is decoded with
        # `getString(from: settings.audioConfiguration, in: audioConfigurations)`, and
        # the encoder writes the index into that same array, so the number's meaning
        # is a source fact -- not the `// Stereo default` comment beside it, which is
        # the first thing to stop being true when the array is reordered.
        tables = [(name, symbols.arrays[name]) for name in loader_tables
                  if symbols.arrays.get(name)]
    if not tables:
        return "unproven", ("the stream side spells its default as the bare index %r "
                            "and names no option table, so no source says which row "
                            "the picker's %r is" % (number, label))
    naming = [(name, table) for name, table in tables if label in table]
    if not naming:
        return "conflicts", ("%r is not a row of %s, which is the table the index is "
                             "read out of" % (label, ", ".join(sorted({
                                 name for name, _ in tables}))))
    if all(table.index(label) == number for _, table in naming):
        return "agrees", ", ".join(sorted({name for name, _ in naming}))
    return "conflicts", ("the table %s puts %r at index %d, the stream defaults to %d"
                         % (naming[0][0], label, naming[0][1].index(label), number))


class Deferred:
    """An environment binding whose value is another expression, not a literal.

    A `let` inside the loader can be the fallback the interface uses
    (`legacyResponsivenessBias` is derived from another setting), so the audit binds
    it and evaluates it lazily. The alternative -- treating any such name as
    unresolved -- would push a third of the keys into the ledger for no gain.
    """

    def __init__(self, source):
        self.source = source


def audit(tree=None):
    """Compare the interface value, the bridge value, and the stream value.

    Returns the full account, not just the verdict, because `--self-test` needs to
    point at the specific item a mutation was supposed to break.
    """
    tree = tree or Tree()
    symbols = Symbols()
    symbols.load([tree.read(BRIDGE), tree.read(PERSISTENCE),
                  tree.read(DERIVED), tree.read(MODEL)])
    problems = []
    fields = settings_fields(tree)
    bridge = bridge_fallbacks(tree)
    persistence = fallbacks(tree, PERSISTENCE)
    # A default written against an alias for the profile field is still that layer's
    # default for that key, so it joins the same table rather than a side list: the
    # audit's conclusion for the key has to depend on every fallback the layer
    # states, and a shape that only shows up in a second table would be consulted by
    # whichever code path happened to look there.
    for key, entries in aliased_fallbacks(tree, PERSISTENCE).items():
        persistence.setdefault(key, []).extend(entries)
    for key, entries in aliased_fallbacks(tree, BRIDGE).items():
        bridge.setdefault(key, []).extend(entries)
    # A default written on an optional chain is that layer's default for that key, and
    # it is the only default some accessors state: `enhancedAudioEQGains(for:)` never
    # binds `Settings.getSettings` to a name, so `settings.x ??` cannot see it. The
    # chained reads go through the `Settings`/`persistedSettings` lookup, which is a
    # *stream-side* path -- they therefore join `bridge`, and joining `persistence` too
    # would let a stream-only default settle an interface question.
    for key, entries in chained_fallbacks(tree, BRIDGE).items():
        bridge.setdefault(key, []).extend(entries)
    # Snapshot of what the `??` search found, before the trailing-return shape joins.
    # A non-optional profile field makes `settings.x ?? d` dead code, and that verdict
    # must keep applying to the coalesce; the accessor's trailing `return` answers a
    # different question (`Settings.getSettings(for:)` returned nil, so there is no
    # profile at all) and is live for exactly those non-optional fields -- which is why
    # the shape exists. Without the split, the six non-optional tail keys would be
    # reported as dead fallbacks and skipped, trading one false green for a false red.
    coalesced = set(bridge)
    # A key that already has a coalesce default on either layer keeps the judgement it
    # had. Adding a second stream-side source to it would break `same_expression`
    # (which requires one expression per side) and push the key into evaluation, so
    # `displayMode` -- green before this shape existed -- would report as unproven
    # purely because the reader got wider. That is a new red this wave did not earn, and
    # a gate that moves verdicts it was not asked to move stops being evidence. Those
    # keys keep one audited default and the gap is recorded in the goal-mode contract;
    # the keys that join are the ones no account held at all.
    tails = {key: entries for key, entries in accessor_tails(tree).items()
             if key not in coalesced and key not in persistence}
    # One layer deeper for the keys whose accessor delegates its whole tail. The
    # substitution happens *before* the tails join `bridge` so the bridge keeps exactly
    # one expression for the key: leaving both the delegated call and the helper's
    # default in the table would make `same_expression` refuse (it requires one
    # expression per side) and turn a key this wave can now prove into a new red.
    # Keys whose read-through stopped at a second call are not substituted -- their
    # bridge entry stays the call, and `stream_value` reports where the proof stopped.
    readthrough = {key: entry for key, entry in accessor_tail_readthrough(tree).items()
                   if key in tails}
    for key, entry in readthrough.items():
        if entry.get("expression"):
            tails[key] = [(entry["line"], entry["expression"])]
    for key, entries in tails.items():
        bridge.setdefault(key, []).extend(entries)
    # Branch-local defaults, indexed by the field the branch is about. Kept out of
    # `bridge` so the value inside a sentinel arm is not charged to the key it merely
    # reads, and passed to `stream_value` so it is *proved* against the interface rather
    # than skipped: skipping would remove a report without replacing it with evidence.
    guarded_bridge = guarded_fallbacks(tree, BRIDGE)
    stream_view = objc_fallbacks(tree)
    read_by_objc = objc_reads(tree)
    wrapped = helper_wrapped(tree)
    helper_defaults_found = helper_defaults(tree)
    enum_reads = enum_init_reads(tree)

    local = local_bindings(tree.read(PERSISTENCE))
    fields_for_env = settings_fields(tree)
    # A `let` in the loader can be the fallback, so it is bound the same way a
    # default constant is. Names that are also profile fields are skipped: there the
    # profile binding is the one that matters, and a same-named local elsewhere in
    # the file would be a different value.
    overrides = {name: source for name, source in local.items()
                 if name not in fields_for_env}
    overrides = {name: Deferred(source) for name, source in overrides.items()}

    compared, divergences, ledger, unresolved, unread = [], [], [], [], []
    # Every setting either layer mentions with a fallback of its own, plus every key
    # the stream substitutes a number for. A key only the stream defaults is exactly
    # as much a fork risk as a key only the interface defaults.
    # `guarded_bridge` is in the union on purpose: a key the audit only reaches through
    # a sentinel branch still has to be on the books, because a key that leaves the
    # candidate set looks identical to a key that got proven, and the debt ratchet
    # would retire its entry on a silence.
    dangling = dangling_accessor_calls(tree)
    # What the loader writes for the all-defaults profile: the interface's answer
    # for "nothing was ever stored", and the fourth default source the published
    # field must be stated by.
    loader = defaults_assignments(tree)
    candidates = sorted(set(bridge) | set(persistence) | set(stream_view)
                        | set(dangling)
                        | {key for entries in guarded_bridge.values()
                           for _line, key, _source in entries})
    field_map = interface_field_map(tree)
    # {profile key: [option array name]} for keys the loader decodes by index.
    loader_tables = {key: tuple(tables) for key, tables in key_index_tables(tree).items()}
    for key in candidates:
        optional = fields.get(key)
        if optional is False:
            # The left side of `??` can never be nil, so whatever follows it is
            # decoration. Saying so is cheaper than deleting it and keeps the claim
            # checkable if the field ever becomes optional.
            # `coalesced` is the pre-merge snapshot: a trailing return that just joined
            # `bridge` is *not* a dead coalesce, and reading `bridge` here would report
            # every non-optional tail key as a dead fallback the audit cannot skip.
            if key in coalesced or key in persistence:
                problems.append("dead fallback: %s is not optional" % key)
            if key not in tails and key not in dangling:
                continue
            # The dead coalesce is still reported above; the key keeps its audit,
            # because its live default is the accessor's trailing return.
            # `dangling` is the second reason a non-optional key keeps its audit: the
            # stream still asks Objective-C for the value, so the key has a live
            # consumer whose default is no longer stated anywhere. Skipping it here is
            # how a one-sided rename makes a key leave the books in silence -- the
            # accessor's tail return is uncredited (wrong name), the dictionary never
            # carried it, and the surviving call site is the only evidence left.
        if optional is None:
            problems.append("unknown profile field %s" % key)
            continue

        evaluator = Evaluator(symbols,
                              profile_bindings(symbols, fields, overrides=overrides))
        interface = interface_value(key, tree, evaluator, persistence,
                                    wrapped, helper_defaults_found, enum_reads)
        if interface.get("unresolved") and key not in persistence:
            # The loader may name the field something else (`framePacing` is shown as
            # `selectedPacingOptions`), which is a source fact, not a guess.
            renamed = field_map.get(key)
            if renamed and renamed != key:
                retry = interface_value(renamed, tree, evaluator, persistence,
                                        wrapped, helper_defaults_found, enum_reads)
                if not retry.get("unresolved"):
                    retry["source"] = list(retry.get("source", [])) + [
                        "profile key %s" % key]
                    interface = retry
        stream = stream_value(key, tree, evaluator, bridge, stream_view, read_by_objc,
                              guarded_bridge, dangling=dangling,
                              readthrough=readthrough)
        entry = {"key": key, "interface": interface, "stream": stream}

        # One layer stating two different values for the same absent key is a fault
        # in that layer, checked before the two layers are compared: the comparison
        # picks one expression per side and can be green while each side has two
        # answers. Checked on evaluated values, so `0.0` beside `0` stays quiet.
        for side, table in (("interface", persistence), ("stream", bridge)):
            if key not in table:
                continue
            try:
                rival = self_conflict(evaluate_sources(evaluator, table[key]))
            except Unresolved:
                continue  # the side already reports itself as unresolved
            if rival:
                problems.append(
                    "%s layer defaults %s to %r and %r in the same layer -- which "
                    "value runs depends on which path the reader took"
                    % (side, key, rival[0], rival[1]))

        if same_expression(interface, stream):
            entry["same_expression"] = True
            compared.append(entry)
            continue
        if stream.get("unread"):
            # Nothing on the stream side asks for the key, so there is one value in
            # the system and no way for the two layers to disagree. It is reported
            # separately: an unread key that *starts* being read is how a real fork
            # gets created, and the ledger entry for it has to say so.
            if interface.get("unresolved"):
                unresolved.append((key, describe(persistence.get(key, [])),
                                   describe(bridge.get(key, [])),
                                   interface["unresolved"]))
                continue
            unread.append((key, interface["value"], interface["source"]))
            continue
        if interface.get("unresolved") or stream.get("unresolved"):
            note = interface.get("unresolved") or stream.get("unresolved")
            if key in LEDGER and condition_holds(LEDGER[key]["check"], key, tree):
                ledger.append((key, note))
            else:
                unresolved.append((key, describe(persistence.get(key, [])),
                                   describe(bridge.get(key, []))
                                   + describe(stream_view.get(key, [])), note))
            continue
        if stream.get("divergent_from_guard"):
            # The key's own interface value is not the left side of this comparison --
            # the branch answers its guard -- so the guard's interface value is
            # substituted. Comparing the key's value instead reports a fork between two
            # numbers that were never claimed to be the same thing.
            guard = stream["guard"]
            guard_interface = interface_value(guard, tree, evaluator, persistence,
                                             wrapped, helper_defaults_found, enum_reads)
            left = guard_interface.get("value") if not guard_interface.get("unresolved") \
                else interface["value"]
            divergences.append((key, left, ["interface value for the branch guard %s"
                                            % guard],
                                stream["value"], stream["source"]))
            continue
        if equivalent(interface["value"], stream["value"]):
            compared.append(entry)
        else:
            if display_names_agree(interface, stream, symbols):
                # Recorded as an evaluation rather than a ledger entry: the two layers
                # do hold different literals, and the reason they are the same choice
                # is a table both sides read, so the table is what makes the judgement.
                entry["display_name_mapping"] = True
                compared.append(entry)
                continue
            verdict, note = label_index_agreement(
                interface, stream, symbols,
                loader_tables=loader_tables.get(key, ())) or (None, None)
            if verdict == "agrees":
                # The picker's label and the stored index are one option row, and the
                # array the call names is what proves it. Recorded on the entry so the
                # report says *why* two different literals are the same choice.
                entry["display_name_mapping"] = True
                entry["index_table"] = note
                compared.append(entry)
                continue
            if verdict == "unproven":
                # Not a fork, not an agreement: the stream side's number has no table
                # in the source that says which row it is. Reported as unproven so the
                # key lands on the debt books, where a reviewer sees it and can settle
                # it by spelling the index against the table.
                # One exception, checked before filing: if another table in the tree
                # *does* resolve the label and puts it on a different number, the source
                # proves a disagreement and calling that a gap in the analysis hands a
                # route to green -- the unproven key can be accepted as reviewed debt,
                # and the fork then hides there permanently. A proven fork has to stay
                # in the one account that cannot be excused.
                conflict = display_name_conflict(interface, stream, symbols)
                if conflict is not None:
                    divergences.append((
                        key, interface["value"], interface["source"],
                        stream["value"],
                        stream["source"] + ["the option table names %r row %r"
                                            % (interface["value"], conflict)]))
                    continue
                unresolved.append((key, describe(persistence.get(key, [])),
                                   describe(bridge.get(key, []))
                                   + describe(stream_view.get(key, [])), note))
                continue
            divergences.append((key, interface["value"], interface["source"],
                                stream["value"], stream["source"]))

    for key in LEDGER:
        if key not in candidates:
            problems.append("ledger entry %s no longer names a compared key" % key)
        elif any(item["key"] == key for item in compared):
            problems.append("ledger entry %s is stale: the key now evaluates equal" % key)
    # The candidate set is built from what the layers read, so a brand-new field
    # that no layer has met yet never becomes a candidate and the books stay
    # quiet. The gap question runs on the model's own declaration list instead:
    # a published optional profile field with no default in any audited layer is
    # a zero the two layers silently agree on by accident.
    gap = published_defaults_gap(tree.read(MODEL), fields, persistence, bridge,
                                 stream_view, loader)
    for key in sorted(gap):
        problems.append("published optional profile field %s has no default in "
                        "persistence, the bridge, the stream, or the loader -- "
                        "an unset profile runs on the zero of its type" % key)
    return {"candidates": candidates, "compared": compared, "divergences": divergences,
            "ledger": ledger, "unresolved": unresolved, "unread": unread,
            "problems": problems,
            "read_by_objc": read_by_objc, "stream_view": stream_view,
            "published_defaults_gap": gap}


def interface_value(key, tree, evaluator, persistence, wrapped, helper_defaults_found,
                    enum_reads=None):
    """What the window shows when the profile holds nothing for `key`."""
    if key in persistence:
        try:
            values = evaluate_sources(evaluator, persistence[key])
        except Unresolved as error:
            return {"unresolved": str(error), "source": describe(persistence[key])}
        return {"value": values[0], "source": describe(persistence[key])}
    # No inline fallback. The value can still come from an enum initializer whose
    # absent-value arm is the default, read from the enum's own text.
    for source in sorted((enum_reads or {}).get(key, ())):
        try:
            return {"value": evaluator.value(parse(source)), "source": [source]}
        except Unresolved as error:
            return {"unresolved": str(error), "source": [source]}
    # No inline fallback. The value can still come from a helper that defaults it.
    helpers = sorted(wrapped.get(key, ()))
    for helper in helpers:
        for _, default in helper_defaults_found.get(helper, ()):
            try:
                return {"value": evaluator.value(parse(default)),
                        "source": ["%s() guard-let %s" % (helper, default)]}
            except Unresolved as error:
                return {"unresolved": str(error),
                        "source": ["%s() guard-let %s" % (helper, default)]}
    if helpers:
        return {"unresolved": "%s reads the value through %s, which has no absent "
                              "default to read" % (key, ", ".join(helpers)),
                "source": ["%s(...)"] * len(helpers)}
    # Still nothing inline. The interface's own all-defaults function is the last
    # place it can have said so, and it says it for most keys.
    assigned = defaults_assignments(tree).get(key)
    if assigned:
        # `expression` is what `same_expression` compares; `source` is what the report
        # prints. They cannot be the same string: the prefixed spelling is the one that
        # tells a reviewer where the value came from, and it is also the one that makes
        # two identical expressions parse differently, which is how `streamShortcuts`
        # -- both layers calling `StreamShortcutProfile.defaultShortcuts()` -- reported
        # "unsupported call" instead of "one expression, so it cannot have forked".
        try:
            return {"value": evaluator.value(parse(assigned[0][1])),
                    "expression": assigned[0][1],
                    "source": ["loadDefaultSettings() %s" % assigned[0][1]]}
        except Unresolved as error:
            return {"unresolved": str(error),
                    "expression": assigned[0][1],
                    "source": ["loadDefaultSettings() %s" % assigned[0][1]]}
    return {"unresolved": "%s is read by the interface with no fallback anywhere" % key,
            "source": []}


def stream_value(key, tree, evaluator, bridge, stream_view, read_by_objc,
                 guarded=None, dangling=None, readthrough=None):
    """What the stream runs with when the profile holds nothing for `key`.

    Three possible sources, in the order the runtime reaches them: the bridge's own
    fallback (the key is present), Objective-C's substitution for an absent key, or
    no value at all because nothing asks for the key.

    A key whose only stream-side default sits inside a sentinel branch (`customFps`)
    is settled here rather than left out of the audit: the branch's value has to equal
    what the interface lands on for the same all-defaults profile, which is the claim
    the branch is implicitly making. The judgement is on values, and an unevaluable
    guard is reported as unproven -- excusing the fallback without checking it is the
    silence every other rule in this file exists to refuse.
    """
    if readthrough and key in readthrough and readthrough[key].get("stopped"):
        # Checked before the bridge read on purpose: for such a key the bridge entry
        # *is* the delegated call the reader just followed, so evaluating it would
        # answer "what is the default" with `unbound name 'key'` -- true, but it names
        # neither function, which is what a reviewer needs in order to finish the proof
        # by hand. The key stays on the books either way; only the reason improves.
        entry = readthrough[key]
        return {"unresolved": entry["stopped"],
                "source": ["%s line %d" % (entry["helper"], entry["line"])]}
    if key in bridge:
        try:
            values = evaluate_sources(evaluator, bridge[key])
        except Unresolved as error:
            return {"unresolved": str(error), "source": describe(bridge[key])}
        return {"value": values[0], "source": describe(bridge[key])}
    if key in stream_view:
        try:
            return {"value": evaluator.value(parse(stream_view[key][0][1])),
                    "source": describe(stream_view[key])}
        except Unresolved as error:
            return {"unresolved": str(error), "source": describe(stream_view[key])}
    branch = [(guard, line, source)
              for guard, entries in (guarded or {}).items()
              for line, defaulted, source in entries if defaulted == key]
    if branch:
        # One branch per (guard, value) pair is one claim to check; two different
        # values for the same key is a fork inside the stream layer, reported as such
        # rather than settled by whichever branch was read first.
        checked = []
        for guard, line, source in branch:
            try:
                branch_value = evaluator.value(parse(source))
                guard_value = evaluator.value(parse("settings.%s" % guard))
            except Unresolved as error:
                return {"unresolved": "the branch default for %s (line %d) cannot be "
                                      "checked because %s" % (key, line, error),
                        "source": ["%s.%s == .zero ? ... %s ?? %s ..."
                                   % ("settings", guard, key, source)]}
            checked.append((branch_value, guard, guard_value, line, source))
        first = checked[0]
        for other in checked[1:]:
            if not equivalent(other[0], first[0]):
                return {"unresolved": "%s is defaulted twice inside sentinel branches "
                                      "(lines %d and %d) with %r and %r"
                                % (key, first[3], other[3], first[0], other[0]),
                        "source": [item[4] for item in checked]}
        if not equivalent(first[0], first[2]):
            # The branch's literal answers its guard, so the comparison that means
            # something is branch value against the interface's value for the guard --
            # that pair is the derived quantity both layers are really claiming. A
            # mismatch is a live fork in what the stream runs with, not a gap in the
            # audit, so it is reported as a divergence on those two values.
            return {"divergent_from_guard": True,
                    "value": first[0],
                    "guard": first[1],
                    "guard_value": first[2],
                    "source": ["settings.%s == .zero ? ... ?? %s (line %d)"
                               % (first[1], first[4], first[3])]}
        # Proved equal is not the same as proved *equal to this key's* default. The
        # branch answers a question about its guard (`fps` runs at 60 when no preset
        # was picked), while the key inside the branch keeps its own meaning --
        # `customFps` is nil by design, meaning "follow the global framerate". Charging
        # the branch's number to the key reports a fork that cannot happen; saying
        # nothing instead would let the key leave the books, where a later edit to the
        # branch's literal would go unread. So the guard comparison is the check that
        # stays, and the key is reported as unproven with that check named.
        return {"unresolved": "%s has no default of its own: the stream only reads it "
                              "inside a %s==.zero branch, whose fallback (%s) does agree "
                              "with the interface value for %s, so the derived framerate "
                              "is settled and this key is not"
                              % (key, first[1], first[4], first[1]),
                "source": ["settings.%s == .zero ? ... ?? %s (line %d)"
                           % (first[1], first[4], first[3])]}
    if dangling and key in dangling:
        # The stream still asks Objective-C for this key; the Swift side no longer
        # exports an accessor under the name it asks with. Whatever default the old
        # accessor spelled is no longer the stream's default for anything, and the
        # key must stay visible while a reviewer works that out.
        return {"unresolved": "%s is called by Objective-C through %s, which names no "
                              "accessor on the Swift side, so its default left the "
                              "books with the accessor" % (key, dangling[key]),
                "source": [dangling[key]]}
    if key in read_by_objc:
        return {"unresolved": "%s reaches Objective-C with no fallback in either the "
                              "bridge or the stream, so an unset profile reads as the "
                              "zero of its type" % key,
                "source": ['prefs[@"%s"]' % key]}
    return {"value": None, "source": ["nobody reads the key"], "unread": True}


def condition_holds(name, key, tree):
    if name.startswith("objc_does_not_read_key:"):
        return key not in objc_reads(tree)
    if name.startswith("both_sides_read_absent_as_false:"):
        # The interface spells `false`. The bridge exports the bare optional, so an
        # unset key does not reach the dictionary at all, and Objective-C reading it
        # gets a nil object -- whose `boolValue` is false. The two agree because
        # there is only one value in the system, not because two expressions matched.
        # If the bridge ever gains a `?? true`, or the stream starts substituting a
        # number, the condition stops holding and the key is reported.
        persistence = fallbacks(tree, PERSISTENCE).get(key, [])
        interface_false = bool(persistence) and all(
            source == "false" for _, source in persistence)
        stream_silent = (key in objc_reads(tree)
                         and key not in objc_fallbacks(tree)
                         and key not in bridge_fallbacks(tree))
        return interface_false and stream_silent
    return False


def equivalent(left, right):
    """Numeric equality across int/float spellings; strict otherwise."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def read_baseline():
    """The accepted debt: {(key, reason)} plus the file's own notes."""
    if not os.path.exists(BASELINE):
        # A set, not {}: the bare literal is a dict, and `current - accepted` below
        # then dies on a first run before anyone has reviewed any debt at all.
        return set()
    with open(BASELINE, encoding="utf-8") as handle:
        document = json.load(handle)
    return {(entry["key"], entry["reason"]) for entry in document.get("debts", ())}


def write_baseline(result):
    document = {
        "_about": "Keys the defaults audit cannot yet reduce to one value on both "
                  "sides. Regenerate with `python3 scripts/defaults-consistency.py "
                  "--write-baseline` and read the diff: an entry that leaves means a "
                  "key got proven, which is the only good reason for one to go. The "
                  "reason text is part of the identity, so a key that stops being "
                  "unprovable for the reviewed reason is a new debt, not an old one.",
        "debts": [{"key": key, "reason": note}
                  for key, _, _, note in sorted(result["unresolved"])],
    }
    with open(BASELINE, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(document["debts"])


def reconcile_debt(unresolved, accepted):
    """Split the unproven keys into accepted debt, new debt, and stale excuses.

    Shrinking is a failure too, on purpose: an entry whose key now evaluates means the
    file still carries an excuse for something that no longer needs one, which is how a
    baseline turns into a list of things nobody looks at.
    """
    current = {(key, note) for key, _, _, note in unresolved}
    return (sorted(current - accepted), sorted(accepted - current))


# ---------------------------------------------------------------------------
# self-test: the gate has to refuse the mistakes it exists to catch
# ---------------------------------------------------------------------------
# Mutations are made to source *text*, and the audit re-derives everything from
# that text. A harness that patched an in-memory dictionary instead would prove
# only that the test can edit a dictionary -- which is the flaw that let an earlier
# draft claim three caught mutations with no evidence behind the claim.
def mutate(tree, relative, old, new, count=1):
    text = tree.read(relative)
    if text.count(old) < count:
        raise AssertionError("mutation anchor missing: %r" % old[:60])
    return tree.with_override(relative, text.replace(old, new, count))


def relaunch(mutations):
    """Re-audit the tree with the given (file, old, new) edits applied."""
    tree = Tree()
    for relative, old, new in mutations:
        tree = mutate(tree, relative, old, new)
    return audit(tree)


def key_reported(result, key):
    return (any(item[0] == key for item in result["divergences"])
            or any(item[0] == key for item in result["unresolved"]))


def key_books(result, key):
    """The names of every account the audit filed `key` under.

    The Wave Y contract is about *silence*, and silence is not the same defect as a
    wrong verdict: a key that leaves the books entirely reports nothing at all, so a
    check that only asks "is it red" passes when the gate stops looking. Returning the
    account names lets a check assert the book the key landed in, including the
    "must be somewhere" case that has no red to point at.
    """
    books = []
    for name in ("divergences", "compared", "unresolved", "unread", "ledger"):
        if any((item["key"] if isinstance(item, dict) else item[0]) == key
               for item in result[name]):
            books.append(name)
    return books


def self_test():
    baseline = audit()
    if baseline["divergences"]:
        for item in baseline["divergences"]:
            # The tuple is (key, interface value, interface source, stream value,
            # stream source); printing [1] and [2] printed the value next to its own
            # source and raised, so this path crashed instead of explaining itself.
            print("VIOLATION %s: interface %r vs stream %r" % (item[0], item[1], item[3]))
        print("self-test refused: the tree has real divergences, so a mutation result "
              "here would say nothing about the mutation", file=sys.stderr)
        return 1
    checks = []

    # 1. A bridge fallback that stops matching the interface has to be reported. This
    #    is the defect the whole gate exists for -- Wave V's `ignoreAspectRatio`, where
    #    the interface read `false` and the stream ran `true`. The anchor is the literal
    #    the bridge spells today; the interface side reads the named constant, so a
    #    bridge that stops agreeing with it is exactly the shape Wave V shipped in.
    result = relaunch([(BRIDGE, '"ignoreAspectRatio": settings.ignoreAspectRatio ?? false,',
                             '"ignoreAspectRatio": settings.ignoreAspectRatio ?? true,')])
    checks.append(("bridge fallback flipped",
                   key_reported(result, "ignoreAspectRatio")))

    # 2. A default constant that one layer reads by name and the other re-spells as a
    #    literal. Moving the constant has to be reported for the key whose interface
    #    value depends on it while the stream side keeps its own literal: this is the
    #    same-value-spelled-two-ways trap, seen from the side where the value changes.
    result = relaunch([(DERIVED, "static let defaultEdgeSensorBandWidthPoints = 0.0",
                              "static let defaultEdgeSensorBandWidthPoints = 13.0")])
    checks.append(("interface default moved alone",
                   key_reported(result, "edgeSensorBandWidthPoints")))

    # 3. An Objective-C substitution that stops agreeing with the interface has to be
    #    reported. This is the third layer; a two-layer audit cannot see it at all. The
    #    key has to be one the bridge does *not* export -- for a key the bridge always
    #    puts in the dictionary the substitution is unreachable, and a mutation there
    #    would prove nothing about the gate. `videoRendererMode` is the one key the
    #    stream substitutes a number for and the bridge leaves out.
    result = relaunch([(STREAM_VIEW,
                        '[prefs[@"videoRendererMode"] intValue] : 2',
                        '[prefs[@"videoRendererMode"] intValue] : 3')])
    checks.append(("stream-side substitution changed",
                   key_reported(result, "videoRendererMode")))

    # 4. A fallback that disappears must leave the key accounted for as uncovered,
    #    never silently reclassified as agreement. The anchor has to be a key whose
    #    interface default is stated exactly once: `enableVsync` looked like the obvious
    #    choice and is not, because `loadDefaultSettings()` also writes it, so deleting
    #    the inline `??` leaves the layer still defaulting the key and the two layers
    #    still equal -- which is the correct verdict, not a miss. `upscalingMode` is
    #    defaulted in one place, so a vanished fallback has nowhere else to hide.
    result = relaunch([(PERSISTENCE,
                        "settings.upscalingMode ?? Self.defaultUpscalingMode",
                        "settings.upscalingMode")])
    checks.append(("deleted fallback reports as unresolved",
                   key_reported(result, "upscalingMode")))

    # 4b. Negative control for the check above: the same deletion on a key that keeps a
    #     second default must stay quiet. Reporting it would mean the gate treats the
    #     *shape* of a fallback as the default rather than the value the layer lands on,
    #     and a gate that cries at that shape gets muted the same way an over-eager
    #     linter does.
    result = relaunch([(PERSISTENCE,
                        "settings.enableVsync ?? SettingsModel.defaultEnableVsync",
                        "settings.enableVsync")])
    checks.append(("deleting one of two interface defaults stays green",
                   not key_reported(result, "enableVsync")))

    # 5. Negative control, paired with its positive twin on the same key and line:
    #    rewriting the bridge's `?? defaultHoverActivatesStreamWindow` to the literal
    #    that constant holds must stay green, while the literal one step away must
    #    fire. One negative control alone only proves the gate is quiet; the pair
    #    proves the judgement is made on the evaluated value rather than the spelling
    #    -- which is the whole reason the audit evaluates instead of diffing text.
    result = relaunch([(BRIDGE,
                        "settings.hoverActivatesStreamWindow ?? SettingsModel"
                        ".defaultHoverActivatesStreamWindow",
                        "settings.hoverActivatesStreamWindow ?? true")])
    checks.append(("equal literal stays green",
                   not key_reported(result, "hoverActivatesStreamWindow")))
    result = relaunch([(BRIDGE,
                        "settings.hoverActivatesStreamWindow ?? SettingsModel"
                        ".defaultHoverActivatesStreamWindow",
                        "settings.hoverActivatesStreamWindow ?? false")])
    checks.append(("unequal literal on the same line fires",
                   key_reported(result, "hoverActivatesStreamWindow")))

    # 6. The derivation both layers now share has to stay shared. Neither layer spells
    #    the mode: each calls `derivedSmoothnessLatencyMode`, so the audit settles the
    #    key by one shared expression. Breaking that sharing -- one side going back to
    #    a constant -- has to land in the accounted-for states, never silently in
    #    "agrees". The mutation is chosen so the value still evaluates to something: a
    #    gate that only notices when evaluation breaks would stay green here.
    #    The mutation is the pre-Wave-W code restored: the bridge going back to the
    #    static preset while the interface still derives. The value still evaluates on
    #    the mutated side, so a gate that only notices when evaluation breaks is green.
    result = relaunch([(BRIDGE,
                        "        ?? SettingsModel.derivedSmoothnessLatencyMode(\n"
                        "          framePacing: settings.framePacing,\n"
                        "          enableVsync: settings.enableVsync,\n"
                        "          timingBufferLevel: settings.timingBufferLevel,\n"
                        "          timingPrioritizeResponsiveness: settings"
                        ".timingPrioritizeResponsiveness,\n"
                        "          timingCompatibilityMode: settings"
                        ".timingCompatibilityMode,\n"
                        "          timingSdrCompatibilityWorkaround: settings"
                        ".timingSdrCompatibilityWorkaround\n"
                        "        )",
                        "        ?? SettingsModel.getInt(\n"
                        "          from: SettingsModel.defaultSmoothnessLatencyMode,\n"
                        "          in: SettingsModel.smoothnessLatencyModes)")])
    checks.append(("shared derivation unshared reported",
                   key_reported(result, "smoothnessLatencyMode")))

    # 7. The ledger rests on "nothing on the stream side reads this key", so a read
    #    appearing anywhere the audit looks has to retire that excuse. The mutation
    #    writes the read into `Connection.m` rather than `StreamViewController.m`:
    #    the ledger's key is read by neither file today, and a scan list that silently
    #    stopped including the second file would keep this check green while the
    #    unread-ness it asserts was already false.
    connection = os.path.join("Limelight", "Stream", "Connection.m")
    result = relaunch([(connection,
                        "        NSDictionary* settings = [SettingsClass getSettingsFor:settingsKey];",
                        "        NSDictionary* settings = [SettingsClass getSettingsFor:settingsKey];\n"
                        "        (void)[settings[@\"enhancedAudioEQLayout\"] intValue];")])
    checks.append(("ledger excuse retired by a read outside the main file",
                   key_reported(result, "enhancedAudioEQLayout")))

    # 7b. The check above still writes the read through a name the old pattern knew
    #     (`settings`) into a file the old list knew. The two blind spots that made
    #     two live keys look unread were independent: a file the scan never opened,
    #     and a local name the read pattern never matched. This mutation puts a read
    #     in `DiscoveryWorker.m` -- a file the hand-written list omitted -- through
    #     `hostSettings` -- a name the hand-written alternation omitted -- and asks
    #     that a key currently reported as "unread, so no fork is possible" stops
    #     being excused on those grounds. Both halves have to be derived from the
    #     source for this to pass, which is the property the list used to break.
    discovery = os.path.join("Limelight", "Network", "DiscoveryWorker.m")
    result = relaunch([(discovery,
                        "        hostSettings = [SettingsClass getSettingsFor:_host.uuid];",
                        "        hostSettings = [SettingsClass getSettingsFor:_host.uuid];\n"
                        '            (void)hostSettings[@"mouseMode"];')])
    checks.append(("read in a never-scanned file through an unknown name is seen",
                   key_reported(result, "mouseMode")))

    # 7c. A layer that states two defaults for one key is a fault inside that layer,
    #     and the two-layer comparison cannot see it: each side contributes one
    #     expression to the comparison, and both may contribute the same one.
    #     `timingPrioritizeResponsiveness` is defaulted twice today -- once as the
    #     named constant, once as the literal the constant holds -- so it is the one
    #     key where the check can be shown working rather than merely present. The
    #     positive twin moves one spelling off the constant's value; the negative
    #     twin re-spells it as that value, which must stay green for the same reason
    #     check 5 does: the judgement is on values, not on text.
    result = relaunch([(PERSISTENCE,
                        "settings.timingPrioritizeResponsiveness "
                        "?? Self.defaultTimingPrioritizeResponsiveness",
                        "settings.timingPrioritizeResponsiveness ?? true")])
    checks.append(("a layer defaulting one key two ways is reported",
                   any("timingPrioritizeResponsiveness" in problem
                       for problem in result["problems"])))
    result = relaunch([(PERSISTENCE,
                        "settings.timingPrioritizeResponsiveness "
                        "?? Self.defaultTimingPrioritizeResponsiveness",
                        "settings.timingPrioritizeResponsiveness ?? false")])
    checks.append(("two spellings of one value in a layer stay green",
                   not any("timingPrioritizeResponsiveness" in problem
                           for problem in result["problems"])))

    # 8. The debt ratchet has to refuse both ways, and it is checked as a function
    #    rather than against the tree: the point is the rule, and a rule checked
    #    against the current tree cannot show what an entry that should not be there
    #    does. A key nobody reviewed must fail, and an entry whose key stopped being
    #    unprovable must fail too -- otherwise a baseline only ever grows.
    sample = [("someKey", [], [], "read through a helper with no absent default")]
    fresh, stale = reconcile_debt(sample, set())
    same, stale_same = reconcile_debt(sample, {("someKey", sample[0][3])})
    proven_new, proven_stale = reconcile_debt([], {("someKey", sample[0][3])})
    # A key that is still unprovable but for another reason is new debt: the entry on
    # file reviewed a different shape, and an excuse carried across a refactor is the
    # thing this whole file argues against.
    reshaped_new, _ = reconcile_debt(
        [("someKey", [], [], "profile key is not bound in this profile")],
        {("someKey", sample[0][3])})
    checks.append(("unreviewed debt fails and reviewed debt does not",
                   bool(fresh) and not same and not stale_same))
    checks.append(("an excuse for a proven key fails",
                   bool(proven_stale) and not proven_new))
    checks.append(("debt that changed shape is new debt", bool(reshaped_new)))

    # 9. A sentinel branch's fallback is checked against its *guard's* interface value,
    #    not against the defaulted key's own (`customFps` is nil by design -- "follow
    #    the global framerate" -- so the branch's 60 is not claiming to be its default).
    #    The positive twin moves the branch literal off `Self.defaultFps`, which is a
    #    live fork in what framerate the stream runs with when no preset was picked:
    #    the interface shows 60 and the stream sends 120. The negative twin re-spells
    #    the same number as an integer, which has to stay green for the same reason the
    #    other negative controls do -- the judgement is on values, not on text.
    result = relaunch([(BRIDGE, "Int(settings.customFps ?? 60.0)",
                             "Int(settings.customFps ?? 120.0)")])
    checks.append(("sentinel branch literal off the guard's default reported",
                   any(item[0] == "customFps" for item in result["divergences"])))
    result = relaunch([(BRIDGE, "Int(settings.customFps ?? 60.0)",
                             "Int(settings.customFps ?? 60)")])
    checks.append(("sentinel branch literal re-spelled stays green",
                   not any(item[0] == "customFps" for item in result["divergences"])))

    # 10. The consumer surface: a key read out of the `getSettings` dictionary has to
    #     be defaulted *in that dictionary*. This is the false green Wave X found --
    #     `muteOnFocusLoss` was exported as a bare optional, `compactMapValues { $0 }`
    #     dropped the nil so the key never arrived, and the only `?? default` in the
    #     file sat in `muteOnFocusLoss(for:)`, an accessor no Objective-C caller uses.
    #     Four checks, because the one that mattered failed silently:
    #
    # 10a. A dictionary fallback that stops agreeing with the interface fires. The
    #      interface reads the named constant, so this is the shape where the settings
    #      window shows YES while the stream mutes nothing.
    dict_row = ('"muteOnFocusLoss": settings.muteOnFocusLoss\n'
                '          ?? SettingsModel.defaultMuteOnFocusLoss,')
    result = relaunch([(BRIDGE, dict_row,
                        dict_row.replace("?? SettingsModel.defaultMuteOnFocusLoss",
                                         "?? true"))])
    checks.append(("dictionary export fallback flipped fires",
                   any(item[0] == "muteOnFocusLoss"
                       for item in result["divergences"])))

    # 10b. Negative twin on the same line: the named constant re-spelled as the literal
    #      it holds must stay green, for the reason every other negative control gives.
    result = relaunch([(BRIDGE, dict_row,
                        dict_row.replace("?? SettingsModel.defaultMuteOnFocusLoss",
                                         "?? false"))])
    checks.append(("dictionary fallback equal literal stays green",
                   not key_reported(result, "muteOnFocusLoss")))

    # 10c. The shipped bug, restated as a check: put the row back to a bare optional so
    #     the dictionary has no fallback and the file still has one (in the accessor
    #     nobody calls). The key must land in the accounted-for states, never in
    #     "agrees" -- before Wave X it read as agreed, and that verdict was wrong.
    result = relaunch([(BRIDGE, dict_row,
                        '"muteOnFocusLoss": settings.muteOnFocusLoss,')])
    checks.append(("bare optional in the dictionary is never read as agreement",
                   key_reported(result, "muteOnFocusLoss")))

    # 10d. Attribution stays narrow in the strict direction. `loadMoonlightSettings`
    #     reads a dozen settings to derive a width and a height; its
    #     `?? false` is a step in that arithmetic, not the dictionary's default for
    #     `matchDisplayResolution`. Crediting it is what let the key look agreed, so a
    #     change there must not be *credited* to the key as a fork. What it does mean
    #     is stated where it can be seen: that line is a third consumer path this audit
    #     does not model, so it is unattributed rather than excused.
    result = relaunch([(BRIDGE,
                        "let usingMatchDisplayResolution = "
                        "settings.matchDisplayResolution ?? false",
                        "let usingMatchDisplayResolution = "
                        "settings.matchDisplayResolution ?? true")])
    checks.append(("a multi-key reader's fallback is not credited to the key",
                   not key_reported(result, "matchDisplayResolution")))

    # 11. Spelling the default at the export must not freeze a value. Moving the
    #     constant the interface reads has to move the stream too, because the export
    #     names the same constant: were this reported, X2 would have traded a false
    #     green for a literal that silently rots.
    result = relaunch([(DERIVED, "static let defaultMuteOnFocusLoss = false",
                             "static let defaultMuteOnFocusLoss = true")])
    checks.append(("export naming the constant follows it",
                   not key_reported(result, "muteOnFocusLoss")))

    # 11b. The accessor half of `bridge_read_ranges` has to be credited, not just the
    #      dictionary half. `pointerSensitivity` is the accessor-read key that is also
    #      exported by the dictionary, so moving only the accessor's fallback is a fork
    #      *inside one layer* -- reported as a problem rather than a divergence, which
    #      is the honest shape: which value runs really does depend on which path the
    #      reader took. Deleting the attribution instead (searching the dictionary body
    #      only) makes this mutation invisible, so a check has to fail on it. The
    #      negative twin re-spells the accessor's default as the literal the named
    #      constant holds, which must stay quiet for the usual reason.
    accessor = ("      return settings.pointerSensitivity ?? "
                "SettingsModel.defaultPointerSensitivity")
    result = relaunch([(BRIDGE, accessor,
                        "      return settings.pointerSensitivity ?? 3.0")])
    checks.append(("credited accessor fallback moved is reported",
                   any("pointerSensitivity" in problem
                       for problem in result["problems"])))
    result = relaunch([(BRIDGE, accessor,
                        "      return settings.pointerSensitivity ?? 1.0")])
    checks.append(("accessor default re-spelled as its own value stays green",
                   not any("pointerSensitivity" in problem
                           for problem in result["problems"])))

    # 12. The trailing-`return` shape: eight keys state their stream-side default as
    #     the last statement of an accessor that Objective-C calls by name, with no
    #     `??` anywhere. A gate that only searches `settings.x ??` never sees them, so
    #     the window can offer rumble while the stream refuses it and the audit prints
    #     "0 divergent" (measured on this tree, 2026-11-01). Four checks, both
    #     polarities, because the failure mode is a key with no entry at all.
    #     (a) the accessor's tail default moved while the interface still reads the
    #         named constant -- a real fork, so it must be a divergence;
    result = relaunch([(BRIDGE, "    return SettingsModel.defaultRumble",
                        "    return false")])
    checks.append(("accessor trailing return diverging from the interface is reported",
                   key_books(result, "rumble") == ["divergences"]))
    #     (b) the same default re-spelled as the literal the constant holds: the value
    #         did not move, so this must stay green. Without it, (a) only proves the
    #         gate string-matches a constant name;
    result = relaunch([(BRIDGE, "    return SettingsModel.defaultRumble",
                        "    return true")])
    checks.append(("accessor trailing return re-spelled as its own value stays green",
                   key_books(result, "rumble") == ["compared"]))
    #     (c) the accessor renamed so Objective-C's `rumbleFor:` names nothing: the tail
    #         return stops being credited *and* the dictionary never carried the key, so
    #         the easy way out is for the key to vanish. It has to surface as unproven,
    #         naming the surviving call site.
    result = relaunch([(BRIDGE, "@objc static func rumble(for key: String) -> Bool",
                        "@objc static func rumbleRenamed(for key: String) -> Bool")])
    checks.append(("an accessor rename cannot delete the key from the books",
                   key_books(result, "rumble") == ["unresolved"]))
    #     (d) the interface-side name mapping has to come from the source too:
    #         `framePacing` is shown as `selectedPacingOptions`, which the loader fills
    #         from `settings.framePacing`. Renaming the profile key the loader reads has
    #         to break the mapping and the proof with it -- a hardcoded alias table
    #         would keep judging the two equal.
    result = relaunch([(PERSISTENCE,
                        "selectedPacingOptions = Self.getString(from: settings.framePacing,"
                        " in: Self.pacingOptions)",
                        "selectedPacingOptions = Self.getString(from: "
                        "settings.framePacingRenamed, in: Self.pacingOptions)")])
    checks.append(("the profile-key-to-field mapping is read from the loader",
                   key_books(result, "framePacing") != ["compared"]))

    # 13. The one-function read-through. `mouseDriver`'s accessor states no default:
    #     its whole body is `mouseInputStrategy(for: key).rawValue`, and the default is
    #     that helper's trailing `return MouseInputDriverStrategy.defaultStrategy`. The
    #     three polarities below are what tell "the reader crossed one function and
    #     read it" apart from "the reader gave up and called it equal".
    #     (a) the helper's own default moved -- the accessor text is untouched, so only
    #     a reader that actually entered the helper can see the fork;
    result = relaunch([(BRIDGE, "    return MouseInputDriverStrategy.defaultStrategy",
                             "    return MouseInputDriverStrategy.gameController")])
    checks.append(("a delegated default that moved is reported",
                   key_books(result, "mouseDriver") == ["divergences"]))
    #     (b) the delegation inlined: the accessor spells the helper's value itself.
    #     The value did not move, so this must stay green -- without it, (a) would only
    #     prove the reader marks call-shaped tails red;
    result = relaunch([(BRIDGE, "    mouseInputStrategy(for: key).rawValue",
                             "    MouseInputDriverStrategy.defaultStrategy.rawValue")])
    checks.append(("a delegated default inlined at the accessor stays green",
                   key_books(result, "mouseDriver") == ["compared"]))
    #     (c) a second layer appears under the helper. Crossing twice is where a reader
    #     starts inventing defaults, so the reader has to stop *and say where*: the key
    #     keeps an entry whose reason names the helper it read and the call it stopped
    #     at. Vanishing (the key leaves every book) and judging it equal are both fails.
    result = relaunch([(BRIDGE, "    return MouseInputDriverStrategy.defaultStrategy",
                             "    return fallbackMouseDriverStrategy(for: key)")])
    stopped = [note for key, _left, _right, note in result["unresolved"]
               if key == "mouseDriver"]
    checks.append(("a second delegation layer stops and names where",
                   key_books(result, "mouseDriver") == ["unresolved"]
                   and any("mouseInputStrategy" in note and "another call" in note
                           for note in stopped)))
    #     (d) the helper has to be handed *this* key. `helper(for: someOtherHost)`
    #     answers what another profile would run, so its absent arm is not this key's
    #     default and may not be substituted; the key stays on the books unproven.
    result = relaunch([(BRIDGE, "    mouseInputStrategy(for: key).rawValue",
                             "    mouseInputStrategy(for: SettingsModel.globalHostId)"
                             ".rawValue")])
    checks.append(("a helper handed another host's id is not credited",
                   key_books(result, "mouseDriver") == ["unresolved"]))

    # 14. The three states behind "the two sides did not match" on the label/number
    #     seam. No key on the clean tree reaches this arm, so a source mutation cannot
    #     summon it -- the judgement is exercised directly against a symbol table, which
    #     is the only way to show the arm answers all three ways rather than one.
    def conflict(label, number, tables):
        """Judge one label/number pair against hand-written tables.

        The tables are reached the way a real source reaches them -- the source text
        names each one with an `xRawValue(for:)` call, and `value_tables_named` resolves
        that name through the symbol table -- so the check exercises the shipped lookup
        rather than a private shape. One table per named call, which is how two tables
        come to answer one label at all.
        """
        names = ["probe", "spare"][:len(tables)]
        stub = Symbols()
        stub.tables = {"%sOptions" % name: table for name, table in zip(names, tables)}
        source = " ".join("%sRawValue(for: key)" % name for name in names)
        return display_name_conflict({"value": label},
                                     {"value": number, "source": [source]}, stub)

    checks.append(("a table that resolves the label to the same row is not a fork",
                   conflict("Automatic", 3, [{"Automatic": 3}]) is None))
    checks.append(("a table that resolves the label to another row is a fork",
                   conflict("Automatic", 1, [{"Automatic": 3}]) == 3))
    # Two tables name one label and disagree, so the source does not say which row
    # governs. That answers a fork no better than no table at all, and it must not be
    # filed as one: the unproven book is where an unprovable claim stays reviewable.
    checks.append(("two tables that disagree about the row leave it unproven",
                   conflict("Automatic", 1, [{"Automatic": 3},
                                             {"Automatic": 4}]) is None))

    # 15. A published optional profile field whose default no layer states is a
    #     ratcheted gap: the current tree has none, so a new field is a violation
    #     until a default is written for it. The anchor is the loader's one line for
    #     `customFps` -- the field's only stated default, in the one layer that
    #     writes it, so deleting the line leaves the field with no answer for
    #     "nothing was ever stored". The gate must name the field and land it in the
    #     gap account the report prints.
    result = relaunch([(PERSISTENCE,
                        "    customFps = Self.defaultCustomFps\n",
                        "")])
    checks.append(("published field with no default in any layer is reported",
                   any(p.startswith("published optional profile field customFps")
                       for p in result["problems"])
                   and result["published_defaults_gap"].get("customFps") == []))
    # 15b. The paired negative control on the key's *second* default: `absoluteMouseMode`
    #      is stated in the loader and in one persistence read, and deleting only the
    #      persistence read must stay quiet. The loader still answers for the field,
    #      and a gate that cried at the deletion would be counting *shapes* of
    #      defaults instead of asking whether one still exists -- the same over-eager
    #      trap the 4b control guards against on the two-layer books.
    result = relaunch([(PERSISTENCE,
                        "      absoluteMouseMode = settings.absoluteMouseMode "
                        "?? Self.defaultAbsoluteMouseMode\n",
                        "")])
    checks.append(("published field that keeps a second default stays green",
                   "absoluteMouseMode" not in result["published_defaults_gap"]
                   and not any(p.startswith("published optional profile field "
                                            "absoluteMouseMode")
                                for p in result["problems"])))

    failed = 0
    for name, passed in checks:
        print("%s %s" % ("ok  " if passed else "FAIL", name))
        if not passed:
            failed += 1
    if failed:
        print("self-test failed: %d of %d checks did not fire" % (failed, len(checks)),
              file=sys.stderr)
        return 1
    print("self-test ok: %d checks -- bridge fallback, interface default, stream "
          "substitution, deleted fallback, the derived Objective-C read set (a file the "
          "old list omitted and a name the old pattern omitted), a layer defaulting one "
          "key two ways, a sentinel branch's fallback against its guard's default, and "
          "the debt ratchet both ways, and the consumer surface (a dictionary export "
          "fallback flipped, a bare optional that must never read as agreement, a "
          "multi-key reader's fallback that must not be credited to its key, an "
          "accessor fallback that must be credited) and the accessor's trailing return "
          "(moved reported, re-spelled forgiven, a rename that must not silence the key, "
          "and a name mapping read from the loader rather than hardcoded); %d of the "
          "checks are negative "
          "controls, so an equivalent re-spelling staying green is asserted, not assumed"
          % (len(checks), sum(1 for name, _ in checks
                              if "stays green" in name or "stay green" in name)))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record the current unproven keys as accepted debt")
    options = parser.parse_args()
    if options.self_test:
        return self_test()
    result = audit()
    if options.write_baseline:
        count = write_baseline(result)
        print("baseline written: %d unproven key(s)" % count)
        return 0
    readable = {key: value for key, value in result.items() if key != "symbols"}
    if options.json:
        print(json.dumps(readable, default=str, indent=2))
    print("shared keys: %d evaluated equal, %d ledgered, %d unresolved, %d divergent"
          % (len(result["compared"]), len(result["ledger"]), len(result["unresolved"]),
             len(result["divergences"])))
    if result["unread"]:
        print("unread by the stream (one value exists, so no fork is possible): %s"
              % ", ".join(key for key, _, _ in result["unread"]))
    failed = False
    for key, interface, interface_source, stream, stream_source in result["divergences"]:
        failed = True
        print("VIOLATION %s: interface %r vs stream %r" % (key, interface, stream))
        print("             interface: %s" % interface_source)
        print("             stream:    %s" % stream_source)
    accepted = read_baseline()
    new_debt, stale = reconcile_debt(result["unresolved"], accepted)
    for key, bridge_sources, stream_sources, note in result["unresolved"]:
        if (key, note) not in accepted:
            failed = True
        print("%s %s: %s" % ("UNRESOLVED" if (key, note) not in accepted else "debt    ",
                             key, note))
        if bridge_sources:
            print("             bridge: %s" % bridge_sources)
        if stream_sources:
            print("             stream: %s" % stream_sources)
    if accepted:
        print("debt baseline: %d accepted, %d new, %d stale"
              % (len(accepted), len(new_debt), len(stale)))
    for key, note in stale:
        failed = True
        print("PROBLEM baseline excuses %s (%s) but the audit no longer reports it -- "
              "the key is proven now, drop the entry" % (key, note))
    for problem in result["problems"]:
        failed = True
        print("PROBLEM %s" % problem)
    for key, note in result["ledger"]:
        print("ledger   %s -- condition holds (%s)" % (key, note))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
