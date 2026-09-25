#!/usr/bin/env python3
"""Who keeps a host alive, and what that costs. Judged from what the objects report.

``docs/memory-ownership.md`` section 5 wants ``TemporaryApp.host`` turned into a ``weak``
back-pointer and has refused to do it without evidence: the cycle is measured, the danger of
the fix is argued from ``StreamViewController`` holding an app and no host, and nobody has
ever been able to *see* either fact. Both are claims about who holds what, and who holds what
can be asked of the objects instead of argued. The Debug build carries ``ML_OWNERSHIP_PROBE``,
which builds the pair three ways, holds it the way ``prepareForSegue:`` holds it -- the app and
nothing else -- and records what survived. This script reads that record.

Three shapes, and the reason for each is a different failure:

``productionGraph``
    The app comes out of ``-[DataManager getHosts]``, the call whose graph leaked. This is the
    one that describes the app, and the one that cannot be blamed on how a test assembled its
    fixture.
``handBuiltGraph``
    The same shape written by hand. It exists to *agree* with the shape above. If the two
    disagree, something outside the pair is retaining it, and then no reading in this report
    describes the pair.
``backpointerOnly``
    An app that knows its host with nothing pointing back -- ``AppAssetRetriever``'s shape, and
    what every holder becomes the day the back-pointer turns weak. Nothing is supposed to
    survive this one. If it does, this probe is holding the objects it claims to be watching,
    and the leak the other two report would be the harness's own.

What the rules judge:

* the controls. A control that fails is not a warning, because the control is the only reason
  the other two readings mean anything.
* the declarations against the observations. ``scripts/ownership-baseline.json`` records what
  the headers say and what was seen under those declarations, keyed together. A run whose
  observations do not match the profile for its own declarations is refused -- including the
  direction a reader would most want to be fooled by: ``weak`` in the header and the host still
  alive is not the fix working, it is somebody else holding the host.
* the shape a fix has to leave behind. Flipping the back-pointer to ``weak`` without writing the
  matching profile in the baseline is refused, so ownership cannot change in a commit that did
  not first say what it expects to see.

What the graph cannot see, said in one sentence rather than by silence: no experiment here can
watch a live stream read ``app.host``, because the holder that matters there is a property on
``StreamViewController``, which this probe does not build. That half is judged off the tree by
the holder rule below -- every statement that hands an app to something else has to give that
holder a host too, refused outright under a weak back-pointer and refused as a new entry under
today's strong one -- and the two halves together are what section 5 asked for before it would
let ownership change.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import project_identity

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "build-render-probe")
BASELINE = os.path.join(ROOT, "scripts", "ownership-baseline.json")
SAMPLE = os.path.join(ROOT, "scripts", "ownership-sample.json")

SHAPES = ("productionGraph", "handBuiltGraph", "backpointerOnly")
# The two shapes that hand the pair to a holder which is not the app. The three above cannot ask
# whether a holder can keep a host alive on its own terms, because in every one of them the outside
# holder *is* the app, which is the thing under study rather than a variable. These two cut the
# back-pointer by hand and then hold the app alone, or the app and the host, from outside the graph.
# The difference between the two readings is the pairing's contribution, which is the whole of step
# 2 and step 3 of the section 5 fix, and it is measured here instead of read off the declarations.
SEVERED_SHAPES = ("severedBackpointerAppOnlyHolder", "severedBackpointerPairedHolder")
# Different fields, because they watch a different holder: these record whether the app is alive
# while a third object holds it, and whether the holder itself dies when the probe lets go.
SEVERED_OBSERVATIONS = ("holderKind", "backpointerSevered", "hostAliveWhileHeldByHolder",
                        "appAliveWhileHeldByHolder", "holderAliveWithNoHolder",
                        "hostAliveWithNoHolder", "appAliveWithNoHolder")
# The two questions the experiment asks of every shape, plus the one that checks the shape was
# really the shape it names.
OBSERVATIONS = ("appListCount", "hostAliveWhileAppHeld", "appHostReadableWhileAppHeld",
                "hostAliveWithNoHolder", "appAliveWithNoHolder")

STRONG_WORDS = ("retain", "strong")
WEAK_WORDS = ("weak", "unsafe_unretained", "assign")


def declaration(text, property_name, type_names):
    """The memory semantics a header declares for one property: 'strong', 'weak' or 'unknown'.

    The type is named rather than guessed because the back-pointer is declared as a
    `TemporaryHost *` while the far edge of the same cycle is an `NSSet *` that happens to hold
    `TemporaryApp`s: reading the property by name alone would let either line answer for both.

    Only what the declaration line itself says. A property with no attribute is `retain` under
    ARC for an object type, which is why the fallback answer for a found-but-bare line is
    'strong' and the answer for a missing line is 'unknown' -- and 'unknown' is refused by the
    caller rather than guessed at, because every rule below reads this value.
    """
    pattern = re.compile(r"@property\s*\((?P<attrs>[^)]*)\)[\s(]*(?:"
                         + "|".join(re.escape(one) for one in type_names)
                         + r")\s*\*_?\s*" + re.escape(property_name) + r"\s*;")
    for match in pattern.finditer(text):
        attributes = match.group("attrs")
        lowered = attributes.lower()
        if any(word in lowered for word in WEAK_WORDS):
            return "weak"
        if any(word in lowered for word in STRONG_WORDS):
            return "strong"
        return "strong"  # ARC's default for an object pointer with no attribute
    return "unknown"


def declarations(root=ROOT):
    """The two declarations the experiment is about, read from the headers that ship."""
    with open(os.path.join(root, "Limelight", "Database", "TemporaryApp.h"),
              encoding="utf-8") as handle:
        app_header = handle.read()
    with open(os.path.join(root, "Limelight", "Database", "TemporaryHost.h"),
              encoding="utf-8") as handle:
        host_header = handle.read()
    return {"app.host": declaration(app_header, "host", ("TemporaryHost",)),
            "host.appList": declaration(host_header, "appList", ("NSSet",))}


def signature(decls):
    """The profile key: a weak back-pointer changes every expected answer, so the expectations
    are filed under the declarations they were written against."""
    return "app.host=%s,host.appList=%s" % (decls["app.host"], decls["host.appList"])


# ---------------------------------------------------------------------------
# The other half of section 5: who is allowed to hold an app without holding its host
# ---------------------------------------------------------------------------
APP_ASSIGNMENT = re.compile(r"^\s*(?P<holder>[A-Za-z_]\w*)\.app\s*=\s*(?P<value>[^;]+);", re.M)
# The receiver is captured so the caller can ask whether this body handed *that* holder a host, and
# the `(?!=)` is the whole point: `\s*=` on its own matches the first `=` of `app.host == nil`, so a
# page that merely compared a holder's host was recorded as having paired it -- which exempts it from
# the change that has to happen before `app.host` turns weak, and a holder exempted in that way is the
# nil dereference this rule exists to prevent.
HOST_ASSIGNMENT = re.compile(r"\b([A-Za-z_][\w.]*?)\.host\s*=(?!=)\s*([^;]*)")
# `= nil` assigns nothing. The rule asks whether a body *gave* the holder a host, and a page whose
# only statement of that shape clears the pointer rather than filling it answered yes under the
# pattern above: the assignment is real, so `(?!=)` was satisfied, and the holder was exempted from
# the very change that has to reach it. The right-hand side is captured because nil is the one value
# that is not a host -- `NULL` and `0` are the same instruction spelled another way.
NO_HOST_ASSIGNED = ("nil", "NULL", "0")


def hands_a_host(receiver, value, holder):
    """Whether one `x.host = y` pairs the holder this site is about.

    The receiver answers the question section 23 asked (somebody else's host is not this holder's);
    the value answers the one it did not: a pointer set to nothing leaves the holder holding the same
    nil it will read the day `app.host` turns weak. An empty value stays credited rather than
    refused, because the blank `code_only` leaves behind a literal is indistinguishable from a shape
    this reader has not thought of, and a reader that refuses what it cannot spell invents red.
    """
    return receiver.endswith(holder) and value.strip() not in NO_HOST_ASSIGNED


def code_only(text):
    """A copy of `text` with comments and literals blanked to spaces, the same length and lines.

    The pairing judgement asked whether a body contained `<holder>.host =` and got its answer out of
    the raw text, so a holder whose host was only ever *mentioned* inside a commented-out
    implementation was recorded as paired. Section 21 taught the reader to step over comments when
    finding a boundary; this is the same lesson applied to what the reader then says about the text it
    found, and it matters more, because a wrong `pairedWithHost` decides which holder is exempt from
    the fix that turns `app.host` weak. Blanking rather than deleting keeps every offset pointing at
    the same character, so a match located in the copy still indexes the original.
    """
    out = list(text)
    index = 0
    while index < len(text):
        past = past_noise(text, index)
        if past != index:
            for position in range(index, past):
                if out[position] != "\n":
                    out[position] = " "
            index = past
            continue
        index += 1
    return "".join(out)


def method_spans(text):
    """Every [(body_start, body_end)] in one file, found by walking the text forward.

    The span used to be guessed backwards -- the nearest column-zero `- (` before the offset, then
    the next column-zero `}` -- and section 19 and section 21 already cost this file two rounds over
    exactly those two guesses. Both directions were wrong here too, and the direction that matters
    is the dangerous one: when no column-zero `}` follows, the span ran to the end of the file, so
    any `.host =` further down paired a holder that was never paired, which is the reading that
    decides who is exempt from the fix. Walking forward and reusing the brace matcher fixes the end,
    and skipping comments and literals before looking for a declaration fixes the start, so a
    commented-out `- (void)deadCode {` inside a method is no longer mistaken for a method.
    """
    spans = []
    index = 0
    while index < len(text):
        skipped = past_noise(text, index)
        if skipped != index:
            index = skipped
            continue
        at_line_start = text.rfind("\n", 0, index) + 1 == index
        if at_line_start and text[index] in "+-":
            line_end = text.find("\n", index)
            line = text[index:len(text) if line_end == -1 else line_end]
            if METHOD_HEAD.match(line):
                body_start = (line_end + 1) if line_end != -1 else len(text)
                body = method_text(text, body_start)
                spans.append((body_start, body_start + len(body)))
                index = body_start
                continue
        index += 1
    return spans


def method_span(text, offset):
    """The (start, end) of the body of the method containing `offset`, or None.

    None means the offset sits outside every method body -- a C function, an `@implementation` line,
    a top-level statement -- and the caller reads that as "this body does not pair anything", which
    errs toward asking for a pairing rather than excusing one.
    """
    for body_start, body_end in method_spans(text):
        if body_start <= offset < body_end:
            return (body_start, body_end)
    return None


def first_party_sources(root=ROOT):
    """{relative path: text} for the sources that could hand an app to something else."""
    texts = {}
    for directory, _, names in os.walk(os.path.join(root, "Limelight")):
        for name in sorted(names):
            if not name.endswith((".m", ".mm", ".swift")):
                continue
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8", errors="replace") as handle:
                texts[os.path.relpath(path, root)] = handle.read()
    return texts


def app_assignment_sites(texts):
    """Every statement that hands an app to a holder, and whether that body also gives it a host.

    Why this is the rule that pairs with the object graph: the graph says a strong `app.host` is
    what keeps a host alive today, and that is only reassuring for a holder that is *kept* alive
    with it. A holder that was never given a host of its own is fine at this second and becomes a
    nil dereference in the middle of a stream the moment the back-pointer turns weak -- which is
    why this rule is a record today and a refusal on the day of the fix. It is armed by the very
    change it polices, so it does not force an ownership change it cannot test; and it cannot be
    disarmed by forgetting, because disarming it is the change it exists to guard.
    """
    sites = []
    for path, text in sorted(texts.items()):
        code = code_only(text)
        for match in APP_ASSIGNMENT.finditer(code):
            holder = match.group("holder")
            span = method_span(code, match.start())
            body = code[span[0]:span[1]] if span else ""
            # The body is read as one text: a pairing written across two lines is still a pairing,
            # and section 20 already showed what a line-based reader of this kind does to a gate.
            paired = any(hands_a_host(match.group(1), match.group(2), holder)
                         for match in HOST_ASSIGNMENT.finditer(body))
            sites.append({"file": os.path.basename(path), "holder": holder,
                          "key": "%s|%s.app" % (os.path.basename(path), holder),
                          "statement": match.group(0).strip(), "pairedWithHost": paired})
    return sites


# A method definition, anchored at column zero and required to open its brace on the same line: a
# declaration ending in `;` is a prototype in an interface, and treating one as a definition would
# make the body run to the next brace that ever appears.
# Everything between the return type and the opening brace is allowed, because a selector with a
# parameter is written `- (void) retrieveAssetsFromHost:(TemporaryHost*)host {` and a pattern that
# stops at the selector name finds no such method: the app-asset manager's pairing then looked like
# a holder nobody had given a host, which is a refusal against code that was already correct. The
# brace has to be on the declaration line, which is what keeps a prototype in an interface from
# being read as a definition whose body runs to the next brace in the file.
METHOD_HEAD = re.compile(r"[+-]\s*\([^)]*\)\s*[^{;{}]*\{$")
APPEARANCE_METHOD = re.compile(r"^[+-]\s*\(\s*void\s*\)\s*(viewDidAppear|viewWillAppear)\b", re.M)
REGISTER_SELECTOR = re.compile(r"addObserver:\s*\w+\s+selector:@selector\((\w+:?)\)\s*"
                               r"name:\s*(?:@\"([^\"]+)\"|([A-Za-z_][\w.]*))")
REGISTER_BLOCK = re.compile(r"(?:addObserverForName:|notificationCenter\]\s*\n?\s*"
                            r"addObserverForName:)\s*(?:@\"([^\"]+)\"|([A-Za-z_][\w.]*))")
TOKEN_ASSIGN = re.compile(r"\w+\.(\w*[Oo]bserver\w*)\s*=")
REMOVE_BY_NAME = re.compile(r"removeObserver:\s*\w+\s+name:\s*(?:@\"([^\"]+)\"|([A-Za-z_][\w.]*))")
REMOVE_TOKEN = re.compile(r"removeObserver:\s*\w+\.(\w*[Oo]bserver\w*)")


def first_group(match_groups):
    """The one non-empty alternative out of a pattern with two ways to name a thing.

    `NSUserDefaultsDidChangeNotification` is a symbol and `@"HostLatencyUpdated"` is a string, so the
    patterns that find a notification name carry both branches and `findall` hands back a pair with
    one half empty. Comparing the pair against a name never matches, which would report a protected
    registration as a defect; emptying the pair first is what makes the comparison a comparison.
    """
    return next((part for part in match_groups if part), "")


def past_noise(text, i):
    """The index just past a comment or literal starting at `i`, or `i` when nothing opens there.

    Braces inside comments and string literals are not braces to a compiler, so they cannot be
    braces to this reader either. That is not a hypothetical about tidiness: `// }` is one brace a
    naive depth count would consume, and `@"{ all in one string @"` holds two, so a matcher written
    without these skips has its own way to end a method in the wrong place -- which is the failure
    this function exists to remove. `stream-menu-addressing-tests.py` matches braces this naive way
    and is fine because it reads one shipped method it controls; a gate that reads every page in the
    tree does not get that licence.
    """
    pair = text[i:i + 2]
    if pair == "//":
        end = text.find("\n", i)
        return len(text) if end == -1 else end
    if pair == "/*":
        end = text.find("*/", i + 2)
        return len(text) if end == -1 else end + 2
    if pair == '@"' or text[i] == '"':
        quote = i + (1 if pair == '@"' else 0)
        index = quote + 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == '"':
                return index + 1
            if text[index] == "\n":
                return index  # a string that does not close on its line stops being a string
            index += 1
        return index
    if text[i] == "'":
        index = i + 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == "'":
                return index + 1
            if text[index] == "\n":
                return index
            index += 1
        return index
    return i


def method_text(text, start):
    """The text of one method, from the line after its declaration to its own closing brace.

    Three guesses have now been measured and replaced, each of them a way the gate could report a
    clean tree about a registration it had not read. The first boundary was the first line holding
    nothing but a closing brace, which a block literal laid out at column zero satisfied early. The
    second was the next declaration or `@end` at column zero, which is satisfied early by a dead
    implementation left inside a method in a `/* */` comment -- the shape that ended a method at its
    own comment block here, leaving `sites=0` and no complaint. Neither guess survives here: the
    brace that closes a method is found by counting braces, ignoring the ones inside comments and
    literals. What remains unproven is only what cannot be counted from text at all, which is a
    declaration whose opening brace is not on the declaration line; that layout returns the rest of
    the text rather than a shorter slice, so it over-reads -- and a reader that reads too much is
    annoying, while one that reads too little is green.
    """
    if start < 2:
        return text[start:]
    end_of_declaration = start - 1          # the newline that ended the declaration line
    declaration = text[text.rfind("\n", 0, end_of_declaration) + 1:end_of_declaration]
    if "{" not in declaration:
        # The opening brace is not on the declaration line, so there is nothing here to count from.
        # Reading the rest of the text is the only answer that cannot lose a registration.
        return text[start:]
    depth = 1
    index = start
    while index < len(text):
        skipped = past_noise(text, index)
        if skipped != index:
            index = skipped
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
        index += 1
    return text[start:]


def appearance_bodies(text):
    """{method name: (body text, line of the body)} for the appearance methods in one file.

    `viewDidAppear` and `viewWillAppear` are the methods this rule is about because they are not run
    once per object: two measurements in this tree -- one of the apps page across three show/hide
    cycles, one of the stream page across two window hide/show cycles -- recorded them arriving
    again to the same controller. The notification centre coalesces nothing: three registrations of
    one observer/selector/name pair and one notification produced three callbacks, which is a number
    taken from a two-line program rather than an assumption.
    """
    bodies = {}
    for match in APPEARANCE_METHOD.finditer(text):
        bodies[match.group(1)] = method_text(text, text.index("\n", match.start()) + 1)
    return bodies


def helper_removes_token(text, earlier, token):
    """Whether a `[self removeSomethingObservers]` call made before this registration withdraws it.

    The stream page withdraws its five block registrations through one helper rather than five
    copies of the same five lines, and it should not have to be less safe for that. A call counts
    when the helper's own body removes this token, so the credit is given for the withdrawal and not
    for the name of the method that performs it.

    What counts is the text that precedes the registration, not the whole method. Scanning the
    method was measured to credit a page that registered first and cleaned up afterwards, which is
    the one ordering this rule exists to refuse: the selector half has had a fixture for it since it
    was written, and a block withdrawn through a helper was let through by the same shape. The
    shipped page keeps its credit under the tighter rule because `[self removeStreamSettingsObservers]`
    sits above the five registrations rather than below them.
    """
    for helper in set(re.findall(r"\[self\s+(\w*[Rr]emove\w*[Oo]bserver\w*)\]", earlier)):
        found = re.search(r"^[+-]\s*\([^)]*\)\s*%s\b" % re.escape(helper), text, re.M)
        if not found:
            continue
        removed = REMOVE_TOKEN.findall(method_text(text, text.index("\n", found.start()) + 1))
        if token in removed:
            return helper
    return None


def observer_registration_sites(texts):
    """Every notification registration made in an appearance method, and how it is withdrawn.

    A registration made in a method that runs once per visit is a multiplier: the centre holds what
    it was given, so visit N leaves N registrations live and one notification then runs its callback
    N times. For a block the withdrawal is the token it was handed; for a selector there is no token
    to hold, which is exactly why half of one page stayed unprotected after the other half was fixed
    -- a token cannot release a registration the centre keyed by selector.

    A method body is read as one text rather than as its lines, for the reason section 19 gives for
    the method boundary: a reader whose answer depends on where the author broke a line reports a
    wrapped registration as absent, which is a green about something it did not read. Both failures
    were measured before this was changed -- a call wrapped over four lines produced no site at all,
    and a wrapped block call whose token was assigned on the first line was reported as a block
    nobody kept, refusing a page that was in fact protected.
    """
    sites = []
    for path, text in sorted(texts.items()):
        for method, body in sorted(appearance_bodies(text).items()):
            for match in REGISTER_SELECTOR.finditer(body):
                # Only what precedes the registration counts as its withdrawal: a page that removes
                # the registration after adding it again has the multiplier, just briefly resolved.
                earlier = body[:match.start()]
                withdrawn_names = [first_group(pair) for pair in REMOVE_BY_NAME.findall(earlier)]
                name = first_group(match.groups()[1:])
                sites.append({"key": "%s|%s|%s" % (path, method, name), "file": path,
                              "method": method, "name": name, "kind": "selector",
                              "statement": "%s; name %s" % (match.group(1), name),
                              "withdrawn": name in withdrawn_names, "via": ""})
            for match in REGISTER_BLOCK.finditer(body):
                name = first_group(match.groups())
                earlier = body[:match.start()]
                withdrawn_tokens = REMOVE_TOKEN.findall(earlier)
                # The token is looked for inside the statement that performs this registration rather
                # than on the line it starts on: a long call wraps, and the assignment and the name
                # then sit on different lines.
                statement = body[body.rfind(";", 0, match.start()) + 1:match.start()]
                assigned = TOKEN_ASSIGN.findall(statement)
                token = assigned[0] if assigned else None
                if token is None:
                    # A block registered where nobody keeps the token can never be withdrawn at
                    # all, which is the worst case of this rule rather than an unread one.
                    sites.append({"key": "%s|%s|%s" % (path, method, name), "file": path,
                                  "method": method, "name": name,
                                  "kind": "block-untokened",
                                  "statement": "block registered and never kept",
                                  "withdrawn": False, "via": ""})
                    continue
                sites.append({"key": "%s|%s|%s" % (path, method, name), "file": path,
                              "method": method, "name": name, "kind": "block",
                              "statement": "%s; name %s" % (token, name),
                              "withdrawn": token in withdrawn_tokens or
                                           bool(helper_removes_token(text, earlier, token)),
                              "via": helper_removes_token(text, earlier, token) or ""})
    return sites


def registration_blind_spots(texts):
    """Registrations this rule cannot read, named instead of skipped.

    The reader understands `- (void)viewDidAppear {`, which is the language every page in this
    application is written in today. A Swift page would declare `override func viewDidAppear()` and
    register with `addObserver(forName:object:queue:using:)`, and the rule would find nothing to
    complain about -- a rule that reads one language is a rule that passes the other, which is the
    failure mode this repository refuses everywhere else by asking for a number and finding no field.
    Refusing the unread case costs one page a rule extension, and turns the alternative -- a green
    that never looked -- into a message.
    """
    problems = []
    for path, text in sorted(texts.items()):
        if not path.endswith(".swift"):
            continue
        if not re.search(r"func\s+viewDidAppear|func\s+viewWillAppear", text):
            continue
        if not re.search(r"addObserver", text):
            continue
        problems.append("%s registers for notifications in a file with an appearance method that "
                        "this rule cannot read (it parses Objective-C method declarations only). "
                        "Move the registration somewhere the rule can see it, or teach "
                        "appearance_bodies() the Swift declaration in the same commit -- the option "
                        "that is not allowed is leaving the page unjudged" % path)
    return problems


def judge_registrations(sites, baseline):
    """(problems, notes): a registration that repeats per visit is a callback multiplier.

    Armed on every run rather than on the day of a change: unlike the holder rule this one has no
    future trigger, because the defect is already possible today -- every page in this application
    can be shown more than once, and the centre has never coalesced anything.
    """
    problems, notes = [], []
    recorded = sorted((baseline.get("notification_registration_sites") or {}).keys())
    keys = sorted(site["key"] for site in sites)
    unprotected = [site for site in sites if not site["withdrawn"]]
    if unprotected:
        problems.append("%d notification registration(s) are made in a method that runs again on"
                        " every visit without withdrawing what is already held: %s. The centre"
                        " keeps every registration it is given -- measured: three registrations of"
                        " one observer/selector/name pair turn one notification into three"
                        " callbacks -- so the page's callback work grows by one copy per visit."
                        " Withdraw the previous registration first (`removeObserver:name:object:`"
                        " for a selector, whose registration has no token; the token itself for a"
                        " block), which changes nothing on the first appearance and caps every"
                        " later one at one callback each"
                        % (len(unprotected), ", ".join(sorted("%s (%s, %s)"
                                                              % (site["key"], site["kind"],
                                                                 site["statement"])
                                                              for site in unprotected))))
    new = [key for key in keys if key not in recorded]
    gone = [key for key in recorded if key not in keys]
    if new:
        problems.append("a new notification registration appeared in an appearance method: %s."
                        " Today it is protected, so it is not a defect -- it is a record that has"
                        " to gain an entry in the same commit that added it, because the next"
                        " reader cannot tell a protected registration from a rule that stopped"
                        " matching" % ", ".join(new))
    if gone:
        problems.append("these registrations are no longer made in an appearance method: %s. Say"
                        " which moved them, in the commit that moved them: a record that loses an"
                        " entry nobody removed is a rule that has quietly stopped reading the tree"
                        % ", ".join(gone))
    notes.append("%d registration(s) are made in an appearance method, %d of them withdrawn before"
                 " re-registering" % (len(sites), len(sites) - len(unprotected)))
    return problems, notes


def judge_pairing(sites, decls, baseline):
    """Refusals about holders, separate from the graph because it answers a different question."""
    problems, notes = [], []
    recorded = baseline.get("app_assignment_sites") or {}
    unpaired = [site for site in sites if not site["pairedWithHost"]]
    keys = sorted(site["key"] for site in unpaired)
    if decls["app.host"] == "weak":
        if unpaired:
            problems.append("the back-pointer is declared weak and these sites still hand an app"
                            " to a holder without ever giving it a host: %s. Under a weak"
                            " back-pointer such a holder reaches through `app.host` for a host"
                            " that nobody is keeping, which is the empty pointer section 4 said"
                            " the fix must not ship -- steps 2 and 3 of section 5 are the ones"
                            " that give each of these holders a host by name"
                            % ", ".join("%s (%s)" % (site["key"], site["statement"])
                                        for site in unpaired))
        else:
            notes.append("every site that hands an app to a holder also gives that holder its"
                         " host, so the weak back-pointer has no holder left that would read nil"
                         " out of `app.host`")
        return problems, notes
    new = [key for key in keys if key not in recorded]
    gone = [key for key in sorted(recorded) if key not in keys]
    if new:
        problems.append("a new holder started storing an app without a host: %s. Today's strong"
                        " back-pointer hides it, which is exactly why it is refused now: on the"
                        " day the back-pointer turns weak it becomes a nil read in the middle of"
                        " a stream. Give the holder a host, or say here in the commit why this"
                        " one is different"
                        % ", ".join("%s (%s)" % (key, next(site["statement"] for site in unpaired
                                                           if site["key"] == key)) for key in new))
    if gone:
        problems.append("these holders no longer store an app without a host: %s. That is the"
                        " direction the fix goes in, so it is not a defect -- it is a record that"
                        " has to change in the same commit that changed it, because the next"
                        " reader cannot tell a fixed holder from a rule that stopped matching"
                        % ", ".join(gone))
    notes.append("%d site(s) hand an app to a holder and %d of them also give it a host; the rest"
                 " are alive today only because the back-pointer is strong"
                 % (len(sites), len(sites) - len(unpaired)))
    return problems, notes


def probe_problems(report, require_reap=True, rules=None, require_partial=False):
    """Why this run may not be judged at all, read out of the probe's own record.

    Kept apart from `capture()` so the fixtures can drive every one of these: each is a shape a
    real run produces -- a flag that reached a build which ignores it, a library with hosts but no
    app behind any of them -- and none of them can be summoned when the gate happens to run.
    """
    if report is None:
        return ["the probe left no report.json behind, so the flag reached a build that ignores"
                " it, and an ownership audit over a run that never happened is a green that read"
                " nothing"]
    problems = []
    failures = report.get("failures") or []
    if failures:
        problems.append("the probe refused its own run, so there is no ownership reading to"
                        " judge: %s" % "; ".join(str(problem) for problem in failures[:4]))
    ownership = report.get("ownership")
    if not isinstance(ownership, dict):
        return ["the report carries no `ownership` object, so this is not the probe's report"]
    if ownership.get("holder") != "app-only":
        problems.append("the experiment's premise is that the app is the only outside holder,"
                        " which is how prepareForSegue: leaves a stream; the probe recorded"
                        " holder=%r, so whatever these numbers describe, it is not a stream's"
                        " ownership" % ownership.get("holder"))
    seed = ownership.get("seedHosts")
    if not isinstance(seed, dict):
        problems.append("the audit asked for one host through the production DataManager and the"
                        " probe recorded no seedHosts, so there is no graph behind the reading")
    elif seed.get("status") not in ("seeded", "existing-hosts"):
        problems.append("the audit asked for a host graph and got status %r, so the production"
                        " shape was never there to hold" % seed.get("status"))
    problems.extend(reap_problems(ownership, seed, require_reap, rules))
    problems.extend(partial_host_problems(ownership, require_partial))
    problems.extend(partial_name_problems(ownership, require_partial))
    shapes = ownership.get("shapes")
    if not isinstance(shapes, dict):
        problems.append("the probe recorded no shapes, so there is no control and no reading")
        return problems
    for shape in SHAPES:
        record = shapes.get(shape)
        if not isinstance(record, dict):
            problems.append("shape %s is missing, so %s" % (
                shape,
                "the production graph was never measured -- that is the subject, not a"
                " control that can be skipped" if shape == "productionGraph"
                else "its control is missing and the remaining readings have nothing to be"
                     " checked against"))
            continue
        for observation in OBSERVATIONS:
            if observation not in record:
                problems.append("shape %s recorded no %s, so the run did not ask the question"
                                " this gate answers" % (shape, observation))
    # The holder shapes are asked for on every run: no flag gates them, so a report without them is
    # a build that does not have them, and the pairing would go back to being argued rather than
    # measured. Same refusal, whatever the declarations say.
    for shape in SEVERED_SHAPES:
        record = shapes.get(shape)
        if not isinstance(record, dict):
            problems.append("the probe recorded no %s shape, so nothing in this run says whether a"
                            " holder that keeps an app can keep its host alive once the"
                            " back-pointer is gone -- which is the claim the fix rests on" % shape)
            continue
        for observation in SEVERED_OBSERVATIONS:
            if observation not in record:
                problems.append("shape %s recorded no %s, so the run did not ask the question"
                                " this gate answers" % (shape, observation))
    unknown = [name for name in sorted(shapes) if name not in list(SHAPES) + list(SEVERED_SHAPES)]
    if unknown:
        problems.append("the report carries shape(s) this audit does not know: %s. A shape that no"
                        " rule judges reads as green whatever it measures, so a new shape and the"
                        " rules that judge it have to arrive in the same commit"
                        % ", ".join(unknown))
    return problems


def judge(report, decls, baseline):
    """(problems, notes). Every problem is a claim about this run; every note is context a
    reader needs next to a green."""
    problems, notes = [], []
    ownership = report["ownership"]
    shapes = ownership["shapes"]
    app_host = decls["app.host"]
    host_app_list = decls["host.appList"]
    if "unknown" in (app_host, host_app_list):
        problems.append("the audit could not read the memory semantics of %s out of the headers,"
                        " and a rule that cannot name what the code declares is a rule that"
                        " passes whatever it cannot see"
                        % ", ".join(name for name, value in decls.items() if value == "unknown"))
        return problems, notes

    # The controls first. Both of these refuse before any expectation is compared, because the
    # expectations are only worth what the controls make them worth.
    backpointer = shapes["backpointerOnly"]
    if backpointer["hostAliveWithNoHolder"] or backpointer["appAliveWithNoHolder"]:
        problems.append("the back-pointer-only pair survives with nothing holding it, which the"
                        " shape does not allow: an app retains its host and nothing retains the"
                        " app. Something outside this probe is holding the pair (or the pool was"
                        " never drained), so the leak the other shapes report may be the"
                        " harness's rather than the app's and this run proves nothing")
    production = shapes["productionGraph"]
    hand_built = shapes["handBuiltGraph"]
    for key in ("hostAliveWhileAppHeld", "hostAliveWithNoHolder"):
        if bool(production[key]) != bool(hand_built[key]):
            problems.append("the production graph and the hand-built graph disagree on %s (%s"
                            " against %s). Both hold an app that owns a host and a host that"
                            " owns back, so a disagreement means the production graph is not the"
                            " shape `-[TemporaryHost initFromHost:]` declares, or something"
                            " outside it is retaining it"
                            % (key, production.get(key), hand_built.get(key)))

    # The two holder shapes and their controls. These are the only readings in the report that
    # watch a holder which is not the app, so the controls below are the only thing standing between
    # the pairing's measured contribution and the harness's own references, which is why a holder
    # that will not die voids the shape rather than merely noting it.
    for shape in SEVERED_SHAPES:
        record = shapes.get(shape)
        if not isinstance(record, dict):
            continue  # refused as a missing shape, where absence is not a verdict about anything
        if not bool(record.get("backpointerSevered")):
            problems.append("%s: the probe did not cut the back-pointer, so this is the graph shape"
                            " under the holder shape's name. The reading under it would credit the"
                            " app with keeping its host alive for the very reason the fix is trying"
                            " to remove" % shape)
        if bool(record.get("holderAliveWithNoHolder")):
            problems.append("%s: the holder survived being dropped by the probe, so the probe is"
                            " holding on to what it claims to watch. Every yes in this shape"
                            " belongs to the harness, and a reading taken while the harness leaks"
                            " describes the harness")
        if not bool(record.get("appAliveWhileHeldByHolder")):
            problems.append("%s: the holder was given the app and lost it, so there was never a"
                            " holder standing outside the graph, and whatever the two shapes agree"
                            " on they did not hold the pair to agree on it" % shape)
        if bool(record.get("hostAliveWithNoHolder")) or bool(record.get("appAliveWithNoHolder")):
            problems.append("%s: something in this process outlived the last holder of the pair,"
                            " including the holder these shapes were measured against, so the pair"
                            " leaks and the two readings beside it are not measuring the pairing"
                            % shape)
    severed_app_only = shapes.get("severedBackpointerAppOnlyHolder")
    severed_paired = shapes.get("severedBackpointerPairedHolder")
    if isinstance(severed_app_only, dict) and isinstance(severed_paired, dict):
        if bool(severed_app_only.get("hostAliveWhileHeldByHolder")):
            problems.append("severedBackpointerAppOnlyHolder: with the back-pointer cut by hand a"
                            " holder keeping only the app still kept the host alive, so something"
                            " other than `app.host` is holding it. The app would not be the whole"
                            " of the leak, and every statement this report makes about who holds"
                            " what would be a statement about a holder it cannot see")
        if not bool(severed_paired.get("hostAliveWhileHeldByHolder")):
            problems.append("severedBackpointerPairedHolder: a holder that kept the app and the"
                            " host together still lost the host, so naming a host to a holder does"
                            " not keep it alive and the pairing cannot stand in for the strong"
                            " back-pointer. That is the premise the fix starts from, not one of its"
                            " outcomes: a holder rule built on it would ship a nil read in the"
                            " middle of a stream")

    # The definitions of the shapes, read from the same file as the expectations. `appListCount`
    # is how a reader knows which shape was built, and a shape that quietly changes its own
    # definition takes its control with it: a hand-built graph with nothing pointing back is the
    # third shape wearing the second shape's name, and the agreement between the two graphs --
    # the reason either of them means anything -- would then be an agreement between two copies
    # of one shape.
    contract = baseline.get("shape_contract") or {}
    for shape, wants in sorted(contract.items()):
        if not isinstance(wants, dict):
            continue  # `why` is prose for the reader, not a rule
        record = shapes.get(shape)
        if not isinstance(record, dict):
            continue  # refused above, as a missing shape
        for observation, want in sorted(wants.items()):
            got = record.get(observation)
            if got != want:
                problems.append(
                    "%s.%s is %r and the shape contract says %r. That count is what makes %s the"
                    " shape it is named: %s" % (shape, observation, got, want, shape,
                                                contract.get("why", "")))

    # Declaration against observation.
    for shape in SHAPES:
        record = shapes[shape]
        alive = bool(record["hostAliveWhileAppHeld"])
        if app_host == "strong" and not alive:
            problems.append("%s: the header declares `app.host` strong and the host still went"
                            " back while an app holding it was alive. One of the two is lying --"
                            " either the pair was never built as the probe claims, or the strong"
                            " back-pointer is not doing what ARC says it does" % shape)
        if app_host == "weak" and alive:
            problems.append("%s: the header declares `app.host` weak and the host outlived every"
                            " reference to it, so the weak flip did not remove a holder, it"
                            " moved the holder somewhere this experiment cannot see" % shape)
        if bool(record["appHostReadableWhileAppHeld"]) != alive:
            problems.append("%s: the host and `app.host` disagree about whether the host is"
                            " there while the app is held (%s against %s). Under a strong"
                            " property both are yes and under a zeroing weak both are no; a"
                            " run where they differ is a dangling read or an unreadable object"
                            % (shape, record["hostAliveWhileAppHeld"],
                               record["appHostReadableWhileAppHeld"]))

    # A cycle that the declarations promise has to show up, or the shapes were not built.
    cycle_declared = app_host == "strong" and host_app_list == "strong"
    for shape in SHAPES:
        record = shapes[shape]
        has_back_edge = int(record["appListCount"]) > 0
        if cycle_declared and has_back_edge and not bool(record["hostAliveWithNoHolder"]):
            problems.append("%s: both edges of the cycle are declared strong (%d app(s) in the"
                            " host's `appList`, `app.host` strong) and nothing survived the last"
                            " holder. `leaks` reports this shape as ROOT CYCLE, so a run that"
                            " sees no leak here is a run that did not build the graph it"
                            " reports" % (shape, record["appListCount"]))
        if app_host == "weak" and bool(record["hostAliveWithNoHolder"]):
            problems.append("%s: `app.host` is declared weak and the pair still survived its"
                            " last holder, so the cycle is still there and only its declaration"
                            " changed" % shape)

    # Where the expectations live: keyed by the declarations, so changing ownership without
    # writing down the expected result is itself the refusal.
    key = signature(decls)
    profiles = baseline.get("profiles") or {}
    expected = profiles.get(key)
    if expected is None:
        problems.append("the headers now declare %s and %s has no profile for that, so this run"
                        " cannot be judged against an expectation nobody wrote. Add the expected"
                        " observations for that declaration to `profiles` first -- ownership"
                        " changes in the commit that predicts what it will see"
                        % (key, os.path.relpath(BASELINE, ROOT)))
    else:
        for shape in list(SHAPES) + list(SEVERED_SHAPES):
            want = (expected.get("shapes") or {}).get(shape)
            if want is None:
                problems.append("the profile for %s says nothing about %s, so that shape is"
                                " unjudged" % (key, shape))
                continue
            for observation, value in sorted(want.items()):
                got = shapes[shape].get(observation)
                if bool(got) != bool(value):
                    problems.append("%s.%s: the profile %r (%s) expects %r and this run reports"
                                    " %r. If this run is right, the profile and the document"
                                    " beside it are the things that need updating -- say which in"
                                    " the commit" % (shape, observation, key,
                                                     expected.get("name", "unnamed"),
                                                     value, got))
    return problems, notes


def site(key, paired=True):
    """One synthetic holder site, keyed the way the record keys the real ones.

    The key is the file and the holder rather than a line number, so a fixture can be about the
    rule and not about where a statement happens to sit.
    """
    holder = key.split("|")[1].split(".")[0]
    return {"file": key.split("|")[0], "holder": holder, "key": key,
            "statement": "%s.app = app;" % holder, "pairedWithHost": paired}


def reader_verdict(page, holder="retriever"):
    """What the pairing reader says about one page: True, False, or a word when it is unsure."""
    sites = app_assignment_sites({"Reader.m": page})
    if len(sites) != 1:
        return "%d sites" % len(sites)
    return sites[0]["pairedWithHost"]


def assignment_reader_self_test(baseline):
    """(failures, count): whether the reader of the pairing record can read a page.

    `pairing_self_test` hands `judge_pairing` synthetic sites whose `pairedWithHost` is written by
    the fixture, so across every round so far it never once asked whether `app_assignment_sites`
    reads source correctly. A credit that is asserted rather than read is untested no matter how many
    verdicts are then scored on it, and the untested reader had three ways to be wrong: it recorded
    `if (retriever.host == nil)` as a holder given its host, because `\\s*=` matched the first `=` of
    `==`; it recognised no method whose declaration carries a parameter, so the one holder in this
    tree that really is paired read as unpaired; and it credited `retriever.host = nil`, which is an
    assignment that hands the holder nothing at all -- the same nil it will read the day the
    back-pointer turns weak. All three decide who is exempt when `app.host` turns weak.
    """
    head = "@implementation Reader\n"
    tail = "@end\n"
    def page(*body):
        return head + "- (void)wireRetriever {\n" + "".join(body) + "}\n" + tail
    cases = [
        ("a holder given its host in the same method",
         page("    retriever.app = app;\n", "    retriever.host = host;\n"), True),
        ("a holder given nothing but the app",
         page("    retriever.app = app;\n"), False),
        ("a comparison that mentions the holder's host",
         page("    retriever.app = app;\n",
              "    if (retriever.host == nil) { [self complain]; }\n"), False),
        ("an assertion comparing the holder's host",
         page("    retriever.app = app;\n",
              '    NSCAssert(retriever.host == nil, @"wired");\n'), False),
        ("a different receiver given a host",
         page("    retriever.app = app;\n", "    other.host = host;\n"), False),
        ("a pairing the page also guards with a comparison",
         page("    retriever.app = app;\n",
              "    if (retriever.host != nil) { retriever.host = host; }\n"), True),
        ("a pairing written on a commented-out implementation",
         page("    retriever.app = app;\n",
              "/*\n- (void)dead {\n    retriever.host = host;\n}\n@end\n*/\n"), False),
        ("a pairing inside a line comment",
         page("    retriever.app = app;\n", "    // retriever.host = host;\n"), False),
        ("an app assignment that is itself commented out",
         page("// retriever.app = app;\n"), "0 sites"),
        ("a pairing made in a different method of the same file",
         head + "- (void)wireRetriever {\n    retriever.app = app;\n}\n"
                "- (void)unrelated {\n    retriever.host = host;\n}\n" + tail, False),
        # The shape that made the first version of this reader wrong in the safe direction: a
        # declaration with a parameter is the commonest kind in this tree.
        ("a pairing in a method that takes a parameter",
         head + "- (void) retrieveAssetsFromHost:(TemporaryHost*)host {\n"
                "    retriever.app = app;\n    retriever.host = host;\n}\n" + tail, True),
        # The assignment that is not one. The pattern was written against a comparison, and a
        # comparison and a clearing look the same to anything that only asks whether an `=` followed
        # the property, so the page below was the one exempted holder this rule cannot protect.
        ("a holder whose host is only ever cleared",
         page("    retriever.app = app;\n", "    retriever.host = nil;\n"), False),
        ("a holder cleared in another spelling",
         page("    retriever.app = app;\n", "    retriever.host = NULL;\n"), False),
        ("a holder cleared and then given a host",
         page("    retriever.app = app;\n",
              "    retriever.host = nil;\n    retriever.host = host;\n"), True),
        ("a holder that is handed the host it came from",
         page("    retriever.app = app;\n", "    retriever.host = app.host;\n"), True),
        ("a clearing written for somebody else",
         page("    retriever.app = app;\n", "    other.host = nil;\n"), False),
        # The guard against the opposite overreach: nil is a reason to withhold credit, not a reason
        # to take it away from a body that also assigns a host in the same breath.
        ("a real pairing beside a commented-out clearing",
         page("    retriever.app = app;\n",
              "    retriever.host = host;\n    // retriever.host = nil;\n"), True),
    ]
    failures = total = 0
    for label, source, want in cases:
        total += 1
        got = reader_verdict(source)
        if got != want:
            print("FAIL reader fixture: %s read as %r, expected %r. The pairing record is written"
                  " from this reading, so a wrong answer here exempts a holder from the fix that"
                  " needs to reach it" % (label, got, want))
            failures += 1
    return failures, total


def pairing_self_test(baseline):
    """(failures, count) for the holder rule.

    The two directions that matter are the two halves of the fix's danger: a holder nobody gave a
    host must be a refusal the moment the back-pointer is weak, and it must also be refused the
    day it appears, while it is merely latent -- otherwise the rule exists only on the day of the
    change, which is the day with no time for it.
    """
    weak = fixed_declarations()
    recorded = sorted(baseline.get("app_assignment_sites") or {})
    total = 1
    if not recorded:
        print("FAIL pairing fixture: the baseline records no app-assignment sites, so the rule"
              " that refuses a new holder has nothing to compare against and every new holder"
              " would look like the old ones")
        return 1, total
    known = [site(key, paired=False) for key in recorded]
    stray = site(recorded[0].split("|")[0] + "|freshHolder.app", paired=False)
    cases = [
        ("the holders that ship, under today's header", known, shipped_declarations(), baseline,
         []),
        ("every holder given its own host, under a weak header",
         [site(key) for key in recorded], weak, baseline, []),
        ("a weak header with a holder that never got a host", known, weak, baseline,
         ["hand an app"]),
        ("a holder nobody recorded, while the header is still strong",
         known + [stray], shipped_declarations(), baseline, ["new holder"]),
        ("a holder the fix actually fixed", known[1:], shipped_declarations(), baseline,
         ["no longer store"]),
    ]
    failures = 0
    for label, sites, decls, base, expected in cases:
        total += 1
        problems, _notes = judge_pairing(sites, decls, base)
        if expected and not problems:
            print("FAIL pairing fixture: %s passed, and it should have been refused" % label)
            failures += 1
        elif expected:
            wanted = [want for want in expected if want not in "; ".join(problems)]
            if wanted:
                print("FAIL pairing fixture: %s refused for the wrong reason: wanted %r, got %s"
                      % (label, wanted[0], problems[0][:160]))
                failures += 1
            else:
                print("ok   pairing fixture: %s" % label)
        elif problems:
            print("FAIL pairing fixture: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   pairing fixture: %s" % label)

    # The matcher itself, on source rather than on records. A body that hands a host to somebody
    # else has to stay unpaired: judging `streamVC.app` by the presence of `otherVC.host` two
    # lines away is how a rule like this certifies a stream it never looked at.
    total += 1
    planted = {
        "PlantedPaired.m": "\n- (void)startStream:(id)sender {\n"
                           "    streamVC.app = self.runningApp;\n"
                           "    streamVC.host = self.host;\n}\n",
        "PlantedUnpaired.m": "\n- (void)startStream:(id)sender {\n"
                             "    streamVC.app = self.runningApp;\n"
                             "    otherVC.host = self.host;\n}\n",
    }
    verdicts = {planted_site["file"]: planted_site["pairedWithHost"]
                for planted_site in app_assignment_sites(planted)}
    if verdicts != {"PlantedPaired.m": True, "PlantedUnpaired.m": False}:
        print("FAIL pairing fixture: the matcher could not tell a holder's own host from"
              " somebody else's: %r" % verdicts)
        failures += 1
    else:
        print("ok   pairing fixture: a host given to one holder does not pair another holder's"
              " app")
    return failures, total


def section5_status(report, decls):
    """What section 5 still lacks, in the words this run can back up. Printed beside whatever
    verdict the rules reach, so a green never reads as `the cycle is fixed`."""
    if app_weak(decls) and not any_leaks(report):
        return ("the back-pointer is weak and no shape survives its last holder: the leak that"
                " `leaks` called ROOT CYCLE is gone, and the acceptance the document waited for"
                " is on disk. What the graph cannot show is whether every holder that was living"
                " off that cycle now holds its host by name, and that is what the holder rule"
                " below judges -- a weak back-pointer with an unpaired holder is refused rather"
                " than called clean")
    if app_weak(decls):
        return ("the back-pointer is weak and something still survives its last holder, which is"
                " the state the fix was supposed to end")
    return ("`app.host` is still strong: every shape keeps its host alive on the app alone, so"
            " each holder on the baseline's list -- a stream that holds only its app, a cell that"
            " reads its host out of the app -- has to be given a host of its own in the same"
            " commit that flips the back-pointer, not in a later one. The two holder shapes beside"
            " them say what such a holder is worth: with the back-pointer cut, the app-only holder"
            " loses the host and the holder that was given the host keeps it, so the pairing does"
            " replace the edge -- measured, not argued. The judgement is unchanged until a commit"
            " moves it")


REAP_STATUSES = ("empty", "kept", "reaped", "removed-some")


MODEL_DIR = os.path.join(ROOT, "Limelight", "Limelight.xcdatamodeld")
CURRENT_VERSION = os.path.join(MODEL_DIR, ".xccurrentversion")


def deletion_rules(root=ROOT):
    """Read the Core Data deletion rules out of the model the store actually opens.

    `-[DataManager removeHost:]` deletes a host and nothing else. Whether the apps that host was
    holding go with it is not a fact about any line of Objective-C in this repository: it is the
    `deletionRule` on `Host.appList`, inside whichever `.xcdatamodel` the `.xccurrentversion` file
    names -- there are nine model versions in this tree, so reading the wrong one is reading a
    model the app never opens. The probe counts what the store did; this says what the rule claims;
    the two are then required to agree.
    """
    out = {"model": "unknown", "Host.appList": "unknown", "App.host": "unknown"}
    try:
        with open(CURRENT_VERSION, encoding="utf-8") as handle:
            version = handle.read()
    except OSError as error:
        out["error"] = "cannot read %s (%s)" % (CURRENT_VERSION, error)
        return out
    named = re.search(r"<string>([^<]+\.xcdatamodel)</string>", version)
    if not named:
        out["error"] = "%s does not name a current model" % CURRENT_VERSION
        return out
    out["model"] = named.group(1)
    contents = os.path.join(MODEL_DIR, named.group(1), "contents")
    try:
        with open(contents, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        out["error"] = "cannot read %s (%s)" % (contents, error)
        return out
    for entity, name, key in (("Host", "appList", "Host.appList"),
                              ("App", "host", "App.host")):
        found = re.search(r'<relationship\s+name="%s"[^>]*deletionRule="([^"]+)"' % name, text)
        if not found:
            out["error"] = "%s declares no deletionRule on %s.%s" % (out["model"], entity, name)
            return out
        out[key] = found.group(1)
    return out


def app_record_problems(reap, rules=None):
    """Reconcile a removal against what the model says a removal does to the app rows.

    Only runs when the reap actually deleted something. An app record whose host is gone is worse
    than a leaked object, because it is invisible to every production read -- `getHosts` reaches
    apps through hosts -- so nothing in the app can list it or delete it, while the store keeps
    paying for it. A cascade that removed nothing is the other direction of the same mistake: the
    store is not running the model this file just read, and every claim built on the model is
    floating.
    """
    problems = []
    removed = reap.get("removed")
    if not isinstance(removed, int) or removed == 0:
        return problems
    before = reap.get("appRecordsBefore")
    after = reap.get("appRecordsAfter")
    orphans = reap.get("orphanAppRecordsAfter")
    if reap.get("appRecordProblem") or before is None or after is None or orphans is None:
        problems.append("the reap removed %d host(s) and the app records were not counted on both"
                        " sides of it (%s), so nothing here may claim the deletion was clean"
                        % (removed, reap.get("appRecordProblem") or "no count recorded"))
        return problems
    if rules is None:
        rules = deletion_rules()
    if "error" in rules or "unknown" in (rules["Host.appList"], rules["App.host"]):
        problems.append("the deletion rule under test could not be read out of the model (%s), so"
                        " the %d host(s) removed here cannot be called clean: the model decides"
                        " where the app rows go, and this run cannot say which model the store"
                        " opened" % (rules.get("error", rules["model"]), removed))
        return problems
    if orphans > 0:
        problems.append("removing %d host(s) left %d app record(s) belonging to no host, and a row"
                        " whose host is gone is invisible to `getHosts` and therefore undeletable"
                        " through the app: nothing lists it and nothing removes it"
                        % (removed, orphans))
    if rules["Host.appList"] == "Cascade" and after >= before:
        problems.append("the model says `Host.appList` cascades, yet removing %d host(s) took the"
                        " app records from %d to %d, so either the store is not running the model"
                        " `.xccurrentversion` names (%s) or those apps were never attached to the"
                        " host that was deleted -- and the seed attaches three"
                        % (removed, before, after, rules["model"]))
    if rules["Host.appList"] != "Cascade" and after == before and orphans == 0:
        problems.append("the model says `Host.appList` is `%s`, but removing %d host(s) changed"
                        " neither the app count (%d) nor the orphan count, so the store did"
                        " something the model does not describe"
                        % (rules["Host.appList"], removed, before))
    return problems


def _field_experiment_problems(partial, label):
    """The two things every missing-field experiment has to establish about itself.

    Split out because the second record measures the same shape and would otherwise carry a copy of
    these sentences, which is how two rules drift: one gets tightened and the other quietly keeps
    accepting what it used to.
    """
    problems = []
    if partial.get("status") != "measured":
        problems.append("the %s run recorded status %r instead of measuring, so the"
                        " server-info body never became the host this rule is about"
                        % (label, partial.get("status")))
        return problems
    planted = partial.get("plantedUuid") or ""
    if not planted.startswith("probe-host-"):
        problems.append("the %s run planted %r, which is not a probe-owned uuid, so"
                        " it was measuring somebody's real host and any number below it belongs to"
                        " that person's library rather than to this test" % (label, planted))
    if partial.get("cleanedUp") != "by-the-probe":
        problems.append("the probe reports it left the host it planted as %r, so either the"
                        " measurement deleted its own subject or something else did, and the"
                        " library the next run reads is not the one this one started from"
                        % partial.get("cleanedUp"))
    if partial.get("appRecordProblem"):
        problems.append("the app records could not be counted while judging the %s"
                        " (%s), so the cascade above is unmeasured rather than absent"
                        % (label, partial["appRecordProblem"])
                        if label == "partial-response" else
                        "the app records could not be counted while judging the %s (%s), so what"
                        " the write cost is unmeasured rather than free"
                        % (label, partial["appRecordProblem"]))
    return problems


def partial_name_problems(ownership, require_partial=False):
    """Judge the response that arrived without a hostname.

    `-[ServerInfoResponse populateHost:]` assigns the name it was given, and until this rule the
    write-back assigned it bare like `uuid` used to be, so a body with no `hostname` emptied the name
    of a host that had one and left `-[TemporaryHost displayName]` falling through to an empty string
    unless a custom name sat behind it. Measured before the guard: `nameAfterPropagate` empty, the
    display name empty, and -- the part that decides how bad this is -- the host and app counts
    unmoved. An empty name is ugly; an empty uuid is a deletion. It is refused anyway, because the
    method promises not to overwrite with nil and a promise kept for six fields and broken for two is
    not a promise.

    The record also exists to keep the one field that stays unguarded from being "fixed" by
    somebody's tidy hands: `customName` is written bare because the rename sheet clears it with nil,
    and a guard there would make a custom name impossible to unset.
    """
    named = ownership.get("partialHostName")
    if not isinstance(named, dict):
        if require_partial:
            return ["the audit asked for the missing-field experiments and the probe recorded no"
                    " partialHostName, so the flag reached a build that ignores it and no run here"
                    " says what a response with no hostname does to a saved name"]
        return []
    problems = _field_experiment_problems(named, "missing-name run")
    if named.get("status") != "measured":
        return problems
    planted_name = named.get("plantedName")
    if not planted_name:
        problems.append("the missing-name run recorded no planted name, so there is no value to"
                        " compare the write against and the numbers below it cannot be read")
    if named.get("parsedName") != "<absent>":
        problems.append("the body the probe parsed carried a name (%r), so nothing was missing and"
                        " the run measured an ordinary response while reporting it as this one"
                        % named.get("parsedName"))
    survived = named.get("nameAfterPropagate")
    if survived != planted_name:
        problems.append("a response without a hostname left the stored host's name as %r where the"
                        " planted one was %r: the device list shows whatever that reads as, and"
                        " `displayName` answers with the empty string when nothing else is behind it"
                        % (survived, planted_name))
    if not named.get("displayNameAfterPropagate"):
        problems.append("the host reads out of the library with no display name at all, which is the"
                        " row a person sees in the device list: an unlabelled machine they cannot"
                        " tell apart from the next one")
    if named.get("appsAfter") != named.get("appsBefore"):
        problems.append("app records moved from %s to %s across a response that only failed to carry"
                        " a name, so the write did more than overwrite a label and this rule has"
                        " never seen that shape before -- it is not the one judged above"
                        % (named.get("appsBefore"), named.get("appsAfter")))
    return problems


def partial_host_problems(ownership, require_partial=False):
    """Judge what one host-info response without a unique id did to a host that has one.

    The shipping code expects a response like this: `-[DataManager
    getHostForTemporaryHost:withHostRecords:]` carries a branch commented "Fallback matching when
    UUID is missing" and finds the stored host by mac, address or name instead. Until 2026-09-25
    `-[TemporaryHost propagateChangesToParent:]` then wrote the missing value back -- every other
    field in that method is guarded by the nil check the method's own comment asks for, and `uuid`
    was not -- which took the identifier off a paired machine. Nothing repaired it afterwards:
    `SettingsModel.hosts` and the device sidebar both call `removeHostsWithEmptyUuid` before they
    read a row, so the next look at the device list deleted the host, and `Host.appList` is
    `Cascade`, so the applications somebody added to that machine were deleted with it. Measured on
    a live store: hosts 2 to 1, apps 6 to 3, for one response that simply omitted a tag.

    These rules therefore refuse the outcome and not merely the missing evidence: a uuid that went
    empty, a host count that dropped across a look at the device list, or app records that went
    with it, are each a refusal. A record that is absent when the step was asked for is also a
    refusal, because a flag that reached a build which ignores it is the one failure mode a green
    would otherwise cover for.
    """
    partial = ownership.get("partialHostInfo")
    if not isinstance(partial, dict):
        if require_partial:
            return ["the audit set ML_PROBE_PARTIAL_HOST_INFO and the probe recorded no"
                    " partialHostInfo, so the flag reached a build that ignores it and no run here"
                    " says what a response without a unique id does to a paired host"]
        return []
    problems = _field_experiment_problems(partial, "partial-response")
    if partial.get("status") != "measured":
        return problems
    planted = partial.get("plantedUuid") or ""
    if partial.get("parsedUuid") != "<absent>":
        problems.append("the server-info body the probe parsed carried a uuid (%r), so the"
                        " fall-back branch was never reached and this run measured a normal"
                        " response instead of the one being asked about" % partial.get("parsedUuid"))
    for field in ("parsedName", "parsedMac"):
        value = partial.get(field)
        if not value or value == "<absent>":
            problems.append("the body parsed to no %s, so the host the fall-back matched on was"
                            " not the host that was planted and the write below it landed"
                            " somewhere else" % field)
    survived = partial.get("uuidAfterPropagate")
    if survived != planted:
        problems.append("a response without a unique id left the stored host's uuid as %r where the"
                        " planted one was %r: writing the missing identifier back is what starts"
                        " the sequence this rule exists for, because the next read of the device"
                        " list deletes a row with no uuid" % (survived, planted))
    if partial.get("hostsAfterCleanup") != partial.get("hostsBeforeCleanup"):
        problems.append("looking at the device list took the library from %s host(s) to %s, so the"
                        " read deleted a host -- which is only survivable if nothing hung off it,"
                        " and the app count below says whether anything did"
                        % (partial.get("hostsBeforeCleanup"), partial.get("hostsAfterCleanup")))
    if partial.get("appsAfterCleanup") != partial.get("appsBefore"):
        problems.append("app records went from %s to %s across one look at the device list, so the"
                        " cascade that follows a deleted host took user configuration with it --"
                        " these are the applications somebody added, not probe scratch that can be"
                        " re-made" % (partial.get("appsBefore"), partial.get("appsAfterCleanup")))
    return problems


def reap_problems(ownership, seed, require_reap=True, rules=None):
    """Judge what the probe did about the library it found itself in.

    The reason these rules exist is that handing a probe a private `HOME` does not give it a
    private database: the support directory resolves out of the account, not out of `$HOME`, so
    every probe on a machine -- and every step of one CI job -- opens the same store. A run that
    did not look at who owned the hosts in it could therefore measure a graph an earlier run left
    behind and report it as the production shape, which is exactly what the runner had been doing
    while its comment described a clean room.
    """
    problems = []
    reap = ownership.get("reapedHosts")
    if not isinstance(reap, dict):
        if not require_reap:
            # `--no-reap` asks the probe to leave the library alone, so the absence of the record
            # is the run doing what it was told. It is not a clean reading either: without the
            # reap the shapes may be measured over whatever the previous run left, which is why the
            # leftover rule below still runs -- it needs only the two counts, not the verdict.
            return []
        return ["the audit set ML_PROBE_REAP_OWN_HOSTS and the probe recorded no reapedHosts, so"
                " the flag reached a build that ignores it -- the same failure the seed flag has"
                " its own rule for, and the reap cannot be assumed any more than the seed was"]
    status = reap.get("status")
    if status not in REAP_STATUSES:
        problems.append("the reap recorded status %r, which is not a library the probe may judge:"
                        " the outcomes it may report are %s"
                        % (status, ", ".join(REAP_STATUSES)))
        return problems
    found = int(reap.get("found") or 0)
    ours = int(reap.get("probeOwned") or 0)
    # The record has to describe one library. A probe that counted the hosts and then chose a
    # verdict by a different count is describing two, and neither reading can be trusted.
    if status == "kept" and ours > 0:
        problems.append("the reap kept a library of %d host(s) while calling %d of them"
                        " probe-owned, so hosts a probe planted are still in the graph this run"
                        " measured" % (found, ours))
    if status == "reaped" and int(reap.get("remaining") or 0) != 0:
        problems.append("the reap reported reaping and then read %s host(s) back, so the library"
                        " the shapes were measured over is not the empty one the status claims"
                        % reap.get("remaining"))
    if status == "empty" and found != 0:
        problems.append("the reap called a library of %d host(s) empty" % found)
    problems.extend(app_record_problems(reap, rules))
    library = int(ownership.get("libraryHosts") or 0)
    probe_owned = int(ownership.get("probeOwnedHosts") or 0)
    if not isinstance(reap, dict):
        return problems
    if status in REAP_STATUSES and isinstance(reap.get("probeOwned"), int):
        # The two counts are taken at different moments -- the reap looks before this run seeds,
        # the measurement looks after -- so they are compared through the seeding rather than
        # against each other. Getting this wrong is not hypothetical: the first version of the
        # shape loop stopped counting where it stopped searching, and a laptop holding one planted
        # host among two reported none beside a reap that said one.
        owned_after_reap = 0 if status != "kept" else int(reap["probeOwned"])
        seeded_now = isinstance(seed, dict) and seed.get("status") == "seeded"
        expected = owned_after_reap + (int(seed.get("seeded") or 0) if seeded_now else 0)
        if probe_owned != expected:
            problems.append("the library the shapes were measured over holds %d probe-owned"
                            " host(s), which is not the %d the reap left (%s) plus whatever this"
                            " run seeded (%s), so the two halves of the record do not describe"
                            " one library"
                            % (probe_owned, owned_after_reap, status,
                               seed.get("seeded") if seeded_now else "nothing"))
    if probe_owned > library:
        problems.append("the probe counted %d probe-owned host(s) inside a library of %d, which"
                        " is a count that cannot come from one look at one library"
                        % (probe_owned, library))
    if (isinstance(seed, dict) and seed.get("status") == "existing-hosts" and library > 0
            and probe_owned >= library):
        problems.append("every one of the %d host(s) in the library was planted by a probe and the"
                        " seed still reported existing-hosts, so this run measured a graph an"
                        " earlier probe left in the database instead of one it made: the room was"
                        " not clean, and the production shape is the previous run's handiwork"
                        % library)
    return problems


def app_weak(decls):
    return decls["app.host"] == "weak"


def any_leaks(report):
    shapes = report["ownership"]["shapes"]
    return any(bool(shapes[shape].get("hostAliveWithNoHolder"))
               or bool(shapes[shape].get("appAliveWithNoHolder"))
               for shape in SHAPES if isinstance(shapes.get(shape), dict))


def summary(ownership):
    shapes = ownership["shapes"]
    line = " | ".join("%s: held=%s no-holder=%s (appList %s)"
                      % (shape,
                         "yes" if shapes[shape]["hostAliveWhileAppHeld"] else "no",
                         "yes" if shapes[shape]["hostAliveWithNoHolder"] else "no",
                         shapes[shape]["appListCount"])
                      for shape in SHAPES if isinstance(shapes.get(shape), dict))
    # The pairing's contribution, printed beside the graph readings because it is the number the fix
    # has to keep hold of when it lands: the app-only holder is where today's holders stand, and the
    # paired holder is where step 2 and step 3 would put them.
    holder = []
    for shape in SEVERED_SHAPES:
        record = shapes.get(shape)
        if isinstance(record, dict):
            holder.append("%s: host held=%s" % (
                "app-only" if record.get("holderKind") == "app-only" else "app+host",
                "yes" if record.get("hostAliveWhileHeldByHolder") else "no"))
    if holder:
        line += " | severed back-pointer, %s" % " vs ".join(holder)
    return line


# ---------------------------------------------------------------------------
# The fixtures: every refusal this gate can issue, driven from a synthetic report
# ---------------------------------------------------------------------------
REGISTRATION_FILE = "Fixture.m"


def registration_fixture(body, helpers=""):
    """A page whose appearance method contains exactly the statements a case is about.

    The registrations have to be read out of text that looks like the real thing -- the rule is a
    reader of source, so a fixture made of dictionaries would test the reader's data structure and
    not the reader. `viewDidLoad` is present and unregistered from the record on purpose: it is where
    a registration that should live with the controller belongs, and the rule must not claim it.
    """
    return ("@implementation FixtureViewController\n"
            "- (void)viewDidLoad {\n"
            "    [[NSNotificationCenter defaultCenter] addObserver:self"
            " selector:@selector(languageChanged:) name:@\"LanguageChanged\" object:nil];\n"
            "}\n"
            "- (void)viewDidAppear {\n" + body + "}\n" + helpers + "@end\n")


WITHDRAWN_SELECTOR_BODY = (
    "    [[NSNotificationCenter defaultCenter] removeObserver:self"
    " name:@\"HostLatencyUpdated\" object:nil];\n"
    "    [[NSNotificationCenter defaultCenter] addObserver:self"
    " selector:@selector(handleLatency:) name:@\"HostLatencyUpdated\" object:nil];\n")
LATE_WITHDRAWAL_BODY = (
    "    [[NSNotificationCenter defaultCenter] addObserver:self"
    " selector:@selector(handleLatency:) name:@\"HostLatencyUpdated\" object:nil];\n"
    "    [[NSNotificationCenter defaultCenter] removeObserver:self"
    " name:@\"HostLatencyUpdated\" object:nil];\n")
WITHDRAWN_BLOCK_BODY = (
    "    if (self.logObserver != nil) {\n"
    "        [[NSNotificationCenter defaultCenter] removeObserver:self.logObserver];\n"
    "    }\n"
    "    self.logObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"LogDidAppend\" object:nil queue:nil"
    " usingBlock:^(NSNotification *note) { }];\n")
UNTOKENED_BLOCK_BODY = (
    "    [[NSNotificationCenter defaultCenter] addObserverForName:@\"LogDidAppend\" object:nil"
    " queue:nil usingBlock:^(NSNotification *note) { }];\n")
HELPER_WITHDRAWAL_BODY = (
    "    [self removeFixtureObservers];\n"
    "    self.logObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"LogDidAppend\" object:nil queue:nil"
    " usingBlock:^(NSNotification *note) { }];\n")
# The same helper, called after the registration it is supposed to protect: the multiplier is
# resolved for a moment at the end of the visit and then restored, which is a defect rather than a
# fix, and the selector half of this rule already refuses that shape.
LATE_HELPER_WITHDRAWAL_BODY = (
    "    self.logObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"LogDidAppend\" object:nil queue:nil"
    " usingBlock:^(NSNotification *note) { }];\n"
    "    [self removeFixtureObservers];\n")
HELPER_METHOD = (
    "- (void)removeFixtureObservers {\n"
    "    [[NSNotificationCenter defaultCenter] removeObserver:self.logObserver];\n"
    "}\n")
NO_WITHDRAWAL_BODY = (
    "    [[NSNotificationCenter defaultCenter] addObserver:self"
    " selector:@selector(handleLatency:) name:@\"HostLatencyUpdated\" object:nil];\n")
NO_REGISTRATION_BODY = "    [self doSomethingElse];\n"
# The block literal below closes its brace at column zero, which is how a long block is often laid
# out and which the reader once took for the end of the method.
STRAY_BRACE_PREFIX = (
    "    [self startWatching:^{\n"
    "NSLog(@\"tick\");\n"
    "}\n"
    "];\n")
FLUSH_LEFT_BRACE_BODY = STRAY_BRACE_PREFIX + NO_WITHDRAWAL_BODY
FLUSH_LEFT_WITHDRAWAL_BODY = (
    STRAY_BRACE_PREFIX +
    "    [[NSNotificationCenter defaultCenter] removeObserver:self"
    " name:@\"HostLatencyUpdated\" object:nil];\n"
    "    [[NSNotificationCenter defaultCenter] addObserver:self"
    " selector:@selector(handleLatency:) name:@\"HostLatencyUpdated\" object:nil];\n")


# Both bodies below are a single Objective-C call, wrapped because the line would otherwise be too
# long, which is what the calls in this tree do under a column limit.
WRAPPED_SELECTOR_BODY = (
    "    [[NSNotificationCenter defaultCenter] addObserver:self\n"
    "                              selector:@selector(handleLatency:)\n"
    "                                  name:@\"HostLatencyUpdated\"\n"
    "                              object:nil];\n")
WRAPPED_BLOCK_BODY = (
    "    if (self.logObserver != nil) {\n"
    "        [[NSNotificationCenter defaultCenter] removeObserver:self.logObserver];\n"
    "    }\n"
    "    self.logObserver = [[NSNotificationCenter defaultCenter]\n"
    "        addObserverForName:@\"LogDidAppend\" object:nil\n"
    "        queue:nil usingBlock:^(NSNotification *note) { }];\n")


# A dead implementation commented out inside the live method, which is what an edit leaves behind
# when it means to keep the old code around rather than delete it.
DEAD_CODE_COMMENT = "/*\n@implementation OldView\n- (void)deadCode {\n}\n@end\n*/\n"
BRACED_COMMENT_BODY = (
    "    [self run:^{\n"
    "    // }\n"
    "    }];\n" + NO_WITHDRAWAL_BODY)
STRING_BRACE_BODY = (
    '    NSLog(@"}%s");\n' % "{ note" + NO_WITHDRAWAL_BODY)
BLOCK_COMMENT_BODY = DEAD_CODE_COMMENT + NO_WITHDRAWAL_BODY


def registration_fixture_without_a_closing_brace(body):
    """A page that ends inside the implementation, so the method has no closing brace to find.

    This is what a file with no final newline looks like to the reader when the appearance method is
    the last text it was given. Whether such a file compiles is not the point: a reader that cannot
    find the end of a method must still report what it can see, because the alternative -- reading
    nothing and complaining about nothing -- is indistinguishable from a page that is fixed.
    """
    return "- (void)viewDidAppear {\n" + body

SELECTOR_KEY = "%s|viewDidAppear|HostLatencyUpdated" % REGISTRATION_FILE
BLOCK_KEY = "%s|viewDidAppear|LogDidAppend" % REGISTRATION_FILE


def registration_case(body, helpers="", keys=(), page=None):
    """(sources, baseline) for one case: the tree, and the record that would make it lawful."""
    sources = {REGISTRATION_FILE: registration_fixture(body, helpers)
               if page is None else page}
    baseline = {"notification_registration_sites": {key: "fixture" for key in keys}}
    return sources, baseline


def observer_self_test(baseline):
    """(failures, count) for the registration rule.

    The order cases matter most here: a withdrawal that runs after the registration resolves the
    multiplier for a moment and then restores it, and a rule that only asks whether a withdrawal
    exists somewhere in the method would score that as protected.
    """
    cases = [
        ("a selector registration withdrawn before it is taken",
         registration_case(WITHDRAWN_SELECTOR_BODY, keys=(SELECTOR_KEY,)), []),
        ("a selector registration that multiplies per visit",
         registration_case(NO_WITHDRAWAL_BODY, keys=(SELECTOR_KEY,)),
         ["runs again on every visit"]),
        ("a withdrawal written after the registration it protects",
         registration_case(LATE_WITHDRAWAL_BODY, keys=(SELECTOR_KEY,)),
         ["runs again on every visit"]),
        ("a block registration withdrawn by its own token",
         registration_case(WITHDRAWN_BLOCK_BODY, keys=(BLOCK_KEY,)), []),
        ("a block registration nobody kept a token for",
         registration_case(UNTOKENED_BLOCK_BODY, keys=(BLOCK_KEY,)),
         ["runs again on every visit"]),
        ("a withdrawal performed through a helper",
         registration_case(HELPER_WITHDRAWAL_BODY, HELPER_METHOD, keys=(BLOCK_KEY,)), []),
        ("a withdrawal performed through a helper called after the registration",
         registration_case(LATE_HELPER_WITHDRAWAL_BODY, HELPER_METHOD, keys=(BLOCK_KEY,)),
         ["runs again on every visit"]),
        ("a withdrawal helper that does not name this token",
         registration_case(HELPER_WITHDRAWAL_BODY,
                           HELPER_METHOD.replace("self.logObserver", "self.someOtherObserver"),
                           keys=(BLOCK_KEY,)), ["runs again on every visit"]),
        # Noise that is not syntax. The first of these three was measured to be invisible before the
        # brace count replaced the column-zero guess; the other two guard the new matcher against the
        # failure mode a naive brace count has, which is a brace that only looks like one.
        ("a registration after a commented-out implementation in the same method",
         registration_case(BLOCK_COMMENT_BODY, keys=()), ["new notification registration"]),
        ("a registration after a brace inside a comment",
         registration_case(BRACED_COMMENT_BODY, keys=()), ["new notification registration"]),
        ("a registration after braces inside a string literal",
         registration_case(STRING_BRACE_BODY, keys=()), ["new notification registration"]),
        # Whether a line break changes the answer, which was measured the way the boundary was: a
        # wrapped selector call produced no site at all, and a wrapped block call that did keep its
        # token was refused as a block nobody kept.
        ("a selector registration whose call is wrapped over four lines",
         registration_case(WRAPPED_SELECTOR_BODY, keys=(SELECTOR_KEY,)),
         ["runs again on every visit"]),
        ("a block registration whose call is wrapped, token and withdrawal intact",
         registration_case(WRAPPED_BLOCK_BODY, keys=(BLOCK_KEY,)), []),
        # The reader's own failure modes, which are defects of the gate rather than of a page, and
        # which were measured on the reader before the boundary was changed: both shapes below made
        # a registration invisible, and an invisible registration plus a record that does not name it
        # is silence.
        ("a registration after a brace at column zero, unrecorded",
         registration_case(FLUSH_LEFT_BRACE_BODY, keys=()), ["new notification registration"]),
        ("the same registration, withdrawn before it is taken",
         registration_case(FLUSH_LEFT_WITHDRAWAL_BODY, keys=(SELECTOR_KEY,)), []),
        ("a registration in the last text the reader was given, unrecorded",
         registration_case(NO_WITHDRAWAL_BODY, keys=(),
                           page=registration_fixture_without_a_closing_brace(NO_WITHDRAWAL_BODY)),
         ["new notification registration"]),
        ("the same registration, withdrawn before it is taken",
         registration_case(WITHDRAWN_SELECTOR_BODY, keys=(SELECTOR_KEY,),
                           page=registration_fixture_without_a_closing_brace(
                               WITHDRAWN_SELECTOR_BODY)), []),
        # The record, in both directions. A rule that only ever refuses new things is a rule whose
        # coverage can shrink to nothing without anybody noticing, which is why a registration that
        # left the appearance method has to say so too.
        ("a registration the record does not mention",
         registration_case(WITHDRAWN_SELECTOR_BODY, keys=()), ["new notification registration"]),
        ("a registration the record still names",
         registration_case(NO_REGISTRATION_BODY, keys=(SELECTOR_KEY,)), ["no longer made"]),
        ("a page with no registration in its appearance method",
         registration_case(NO_REGISTRATION_BODY, keys=()), []),
        # The reader's own limit, tested so that growing the rule is the only way to silence it.
        ("a Swift page the rule cannot read",
         ({"Page.swift": "final class Page: NSViewController {\n"
           "    override func viewDidAppear() {\n"
           "        center.addObserver(forName: nil, object: nil, queue: nil) { _ in }\n"
           "    }\n}\n"}, {"notification_registration_sites": {}}),
         ["cannot read"]),
        ("a Swift page that registers nowhere near an appearance method",
         ({"Page.swift": "final class Page: NSViewController {\n"
           "    override func viewDidLoad() {\n"
           "        center.addObserver(forName: nil, object: nil, queue: nil) { _ in }\n"
           "    }\n}\n"}, {"notification_registration_sites": {}}), []),
        ("a Swift appearance method that registers nothing",
         ({"Page.swift": "final class Page: NSViewController {\n"
           "    override func viewDidAppear() { redraw() }\n}\n"},
          {"notification_registration_sites": {}}), []),
    ]
    failures = 0
    for label, (sources, base), expected in cases:
        problems, _notes = judge_registrations(observer_registration_sites(sources), base)
        problems = problems + registration_blind_spots(sources)
        if expected and not problems:
            print("FAIL fixture: %s passed, and it should have been refused" % label)
            failures += 1
        elif expected and expected[0] not in "; ".join(problems):
            print("FAIL fixture: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, expected[0], problems[0][:170] if problems else "nothing"))
            failures += 1
        elif not expected and problems:
            print("FAIL fixture: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   fixture: %s" % label)
    return failures, len(cases)


def shipped_report():
    """The shape today's declarations promise, as the laptop measured it.

    Written from a real run rather than typed: the numbers below are what the probe recorded on
    a machine with a library of its own (two hosts, the picked one carrying three apps).
    """
    def shape(count, held, readable, leak_host, leak_app):
        return {"appListCount": count, "hostAliveWhileAppHeld": held,
                "appHostReadableWhileAppHeld": readable, "hostAliveWithNoHolder": leak_host,
                "appAliveWithNoHolder": leak_app}

    def holder_shape(kind, host_held):
        # The two holder shapes as this laptop measured them on 2026-09-25, over a graph whose
        # back-pointer the probe cut by hand: a holder given the app alone lost the host, a holder
        # given the app and the host kept it, and both holders died when the probe let go. The last
        # is the control -- a holder that survived would mean the harness was holding the pair.
        return {"holderKind": kind, "backpointerSevered": True,
                "hostAliveWhileHeldByHolder": host_held, "appAliveWhileHeldByHolder": True,
                "holderAliveWithNoHolder": False, "hostAliveWithNoHolder": False,
                "appAliveWithNoHolder": False}

    return {"ownership": {"holder": "app-only", "libraryHosts": 2, "probeOwnedHosts": 0,
                          "reapedHosts": {"status": "kept", "found": 2, "probeOwned": 0},
                          "productionHostUuid": "86D1F81F-4D3D-E306-D694-EFDFE6BCD6CE",
                          "seedHosts": {"status": "existing-hosts", "requested": 1,
                                        "existing": 2, "seeded": 0},
                          "shapes": {"productionGraph": shape(3, True, True, True, True),
                                     "handBuiltGraph": shape(1, True, True, True, True),
                                     "backpointerOnly": shape(0, True, True, False, False),
                                     "severedBackpointerAppOnlyHolder": holder_shape("app-only",
                                                                                     False),
                                     "severedBackpointerPairedHolder": holder_shape("app-and-host",
                                                                                    True)}},
            "failures": []}


def fixed_declarations():
    """The declarations the section 5 fix would leave behind."""
    return {"app.host": "weak", "host.appList": "strong"}


def fixed_report():
    report = shipped_report()
    shapes = report["ownership"]["shapes"]
    for name in ("productionGraph", "handBuiltGraph"):
        shapes[name].update({"hostAliveWhileAppHeld": False,
                             "appHostReadableWhileAppHeld": False,
                             "hostAliveWithNoHolder": False, "appAliveWithNoHolder": False})
    shapes["backpointerOnly"].update({"hostAliveWhileAppHeld": False,
                                      "appHostReadableWhileAppHeld": False})
    # Unchanged, deliberately: these two shapes cut the edge by hand, so what the header declares
    # about it cannot change their readings. That is why the two profiles expect the same thing from
    # them, and why a fixer cannot make them agree with the declaration by editing the expectation.
    return report


def self_test(baseline):
    """(failures, count). Each case names the sentence it expects, because a refusal for the
    wrong reason is the same bug as a pass with no evidence: it says the rule bit when a
    different rule did."""
    strong = shipped_declarations()
    cases = [
        ("the shipped build, as measured", shipped_report(), strong, baseline, []),
        ("the section 5 fix, applied", fixed_report(), fixed_declarations(), baseline, []),
        ("a build that ignored the flag", None, strong, baseline,
         ["no report.json"]),
        ("a probe that refused itself", dict(shipped_report(), failures=["library unreadable"]),
         strong, baseline, ["refused its own run"]),
        ("a holder that is not the app", report_with(shipped_report(), holder="host-and-app"),
         strong, baseline, ["only outside holder"]),
        ("a seed that never landed", report_with(shipped_report(),
                                                 seedHosts={"status": "did-not-read-back"}),
         strong, baseline, ["did-not-read-back"]),
        ("no production graph to hold", production_missing(shipped_report()), strong, baseline,
         ["productionGraph"]),
        ("the control leaking", mutate(shipped_report(), "backpointerOnly",
                                       hostAliveWithNoHolder=True), strong, baseline,
         ["back-pointer-only pair survives"]),
        ("the two graphs disagreeing", mutate(shipped_report(), "productionGraph",
                                             hostAliveWithNoHolder=False), strong, baseline,
         ["disagree"]),
        ("strong header, host that went back",
         mutate(shipped_report(), "handBuiltGraph", hostAliveWhileAppHeld=False), strong,
         baseline, ["declares `app.host` strong"]),
        ("weak header, host that stayed", mutate(fixed_report(), "handBuiltGraph",
                                                 hostAliveWhileAppHeld=True),
         fixed_declarations(), baseline, ["did not remove a holder"]),
        ("the host and the property disagreeing",
         mutate(shipped_report(), "handBuiltGraph", appHostReadableWhileAppHeld=False), strong,
         baseline, ["disagree about whether the host is"]),
        ("a declared cycle that leaked nothing", mutate(shipped_report(), "handBuiltGraph",
                                                        hostAliveWithNoHolder=False), strong,
         baseline, ["ROOT CYCLE"]),
        ("a weak declaration that still leaks", mutate(fixed_report(), "productionGraph",
                                                       hostAliveWithNoHolder=True),
         fixed_declarations(), baseline, ["only its declaration"]),
        # A third combination, and the one a fixer is likeliest to land on by half-editing:
        # the back-pointer stays strong while the host's set turns weak. No rule objects to the
        # observations -- no cycle is declared, so no leak is owed -- and only the expectation
        # nobody wrote stops the run.
        ("ownership changed with no expectation written", shipped_report(),
         {"app.host": "strong", "host.appList": "weak"}, baseline, ["no profile for that"]),
        ("a reading that moved under an unchanged header",
         mutate(shipped_report(), "handBuiltGraph", hostAliveWithNoHolder=False,
                appAliveWithNoHolder=False), strong, baseline, ["expects"]),
        ("the hand-built shape is not the shape it names",
         mutate(shipped_report(), "handBuiltGraph", appListCount=0), strong, baseline,
         ["handBuiltGraph.appListCount"]),
        ("a shape that recorded nothing", dropped_observation(shipped_report()), strong,
         baseline, ["recorded no"]),
        # The two holder shapes. Their absence, their controls, and the difference between them are
        # the whole of what step 2 and step 3 of the fix are justified by, so each of the six below
        # is a way the pairing's measured contribution could be reported without existing.
        ("the holder shapes never measured",
         shapes_without(shipped_report(), SEVERED_SHAPES), strong, baseline,
         ["no severedBackpointerAppOnlyHolder", "no severedBackpointerPairedHolder"]),
        ("the back-pointer left in place",
         mutate(shipped_report(), "severedBackpointerAppOnlyHolder",
                backpointerSevered=False), strong, baseline,
         ["did not cut the back-pointer"]),
        ("the holder that would not die",
         mutate(shipped_report(), "severedBackpointerPairedHolder",
                holderAliveWithNoHolder=True), strong, baseline,
         ["holding on to what it claims to watch"]),
        ("the holder that never held the app",
         mutate(shipped_report(), "severedBackpointerPairedHolder",
                appAliveWhileHeldByHolder=False), strong, baseline,
         ["given the app and lost it"]),
        ("an app-only holder that kept the host alive",
         mutate(shipped_report(), "severedBackpointerAppOnlyHolder",
                hostAliveWhileHeldByHolder=True), strong, baseline,
         ["something other than `app.host` is holding it"]),
        ("a paired holder that could not keep the host",
         mutate(shipped_report(), "severedBackpointerPairedHolder",
                hostAliveWhileHeldByHolder=False), strong, baseline,
         ["cannot stand in for the strong"]),
        ("a holder shape that leaks with nobody holding it",
         mutate(shipped_report(), "severedBackpointerPairedHolder",
                hostAliveWithNoHolder=True), strong, baseline,
         ["outlived the last holder"]),
        ("a shape the audit has no rule for", shapes_with_extra(shipped_report()), strong,
         baseline, ["does not know"]),
        ("a holder that is not the holder its shape names",
         mutate(shipped_report(), "severedBackpointerAppOnlyHolder",
                holderKind="app-and-host"), strong, baseline,
         ["severedBackpointerAppOnlyHolder.holderKind"]),
        # The reap rules. These are the refusals that keep a probe from reading somebody else's
        # library and calling it the production shape, which the private `HOME` was believed to
        # do and does not.
        ("the reap flag reaching a build that ignored it",
         report_with(shipped_report(), reapedHosts=None), strong, baseline, ["no reapedHosts"]),
        ("a library left in the state a probe cannot name",
         report_with(shipped_report(), reapedHosts={"status": "mixed", "found": 3,
                                                    "probeOwned": 1}),
         strong, baseline, ["not a library the probe may judge"]),
        ("a reap that kept hosts of its own",
         report_with(shipped_report(), reapedHosts={"status": "kept", "found": 2,
                                                    "probeOwned": 1}),
         strong, baseline, ["probe-owned, so hosts a probe planted"]),
        ("a reap that said reaped and left hosts",
         report_with(shipped_report(), reapedHosts={"status": "reaped", "found": 2,
                                                   "probeOwned": 2, "removed": 2,
                                                   "remaining": 1}),
         strong, baseline, ["reported reaping and then read"]),
        # The clean-up flag, which a person presses and a job never does. The green case is the
        # shape this laptop actually reported while clearing its library: one planted host removed,
        # somebody's real host left standing, and the shapes then measured over the host that
        # remains. The red case is the same run one notch wrong -- it says removed-some and leaves
        # one of ours in there -- which is the failure mode a flag like this has.
        ("a clean-up that left somebody's host standing",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=0,
                     reapedHosts={"status": "removed-some", "found": 2, "probeOwned": 1,
                                  "removed": 1, "remaining": 1, "appRecordsBefore": 3,
                                  "appRecordsAfter": 0, "orphanAppRecordsAfter": 0},
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                                "seeded": 0}),
         strong, baseline, []),
        ("a clean-up that left one of its own behind",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=1,
                     reapedHosts={"status": "removed-some", "found": 2, "probeOwned": 1,
                                  "removed": 1, "remaining": 1, "appRecordsBefore": 3,
                                  "appRecordsAfter": 0, "orphanAppRecordsAfter": 0},
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                                "seeded": 0}),
         strong, baseline, ["not the 0 the reap left"]),
        # The CI runner's record on 2026-09-24: one host, planted by the step before, and a seed
        # that reported it as somebody's library. Red by these rules, green by none of them
        # before they existed, which is the point of writing them down.
        ("the leftover library the runner reported",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=1,
                     reapedHosts={"status": "empty", "found": 0, "probeOwned": 0},
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                               "seeded": 0}),
         strong, baseline, ["not clean"]),
        ("a library the probe seeded for itself",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=1,
                     reapedHosts={"status": "empty", "found": 0, "probeOwned": 0},
                     seedHosts={"status": "seeded", "requested": 1, "seeded": 1}),
         strong, baseline, []),
    ]
    failures = 0
    for label, report, decls, base, expected in cases:
        problems = probe_problems(report)
        if not problems and report is not None:
            problems, _notes = judge(report, decls, base)
        if expected and not problems:
            print("FAIL fixture: %s passed, and it should have been refused" % label)
            failures += 1
        elif expected:
            said = "; ".join(problems)
            missing = [want for want in expected if want not in said]
            if missing:
                print("FAIL fixture: %s refused for the wrong reason: wanted %r, got %s"
                      % (label, missing[0], problems[0][:160]))
                failures += 1
            else:
                print("ok   fixture: %s" % label)
        elif problems:
            print("FAIL fixture: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   fixture: %s" % label)
        if not expected and report is not None:
            status = section5_status(report, decls)
            if not status:
                print("FAIL fixture: %s left the reader with no statement of what section 5"
                      " still lacks" % label)
                failures += 1
    # The diagnosis mode, tested apart from the table because it changes one input rather than
    # one shape: `--no-reap` is how a person looks at the library the way the previous run left it,
    # and an escape hatch that the gate kills on the spot is not a hatch. The same record that must
    # be refused for a missing reap entry has to pass when nobody asked for one -- and the leftover
    # rule, which needs no reap verdict at all, must still refuse it.
    total = 0
    CASCADE = {"model": "fixture", "Host.appList": "Cascade", "App.host": "Nullify"}
    NULLIFY = {"model": "fixture", "Host.appList": "Nullify", "App.host": "Nullify"}
    UNREADABLE = {"model": "unknown", "Host.appList": "unknown", "App.host": "unknown",
                  "error": "the fixture cannot read a model"}

    def reap_case(before, after, orphans):
        """A reap that removed one host and took the app rows with it, or did not."""
        return report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=1,
                           reapedHosts={"status": "reaped", "found": 1, "probeOwned": 1,
                                        "removed": 1, "remaining": 0,
                                        "appRecordsBefore": before,
                                        "appRecordsAfter": after,
                                        "orphanAppRecordsBefore": 0,
                                        "orphanAppRecordsAfter": orphans},
                           seedHosts={"status": "seeded", "requested": 1, "seeded": 1})

    # The Core Data question, tested against the rule it is supposed to match. These cases inject
    # the model rather than reading it, because the point is the reconciliation: the same numbers
    # are a clean deletion under one rule and a refusal under another, and the file has to know
    # which rule the store is running to tell them apart.
    diagnosis = [
        ("the escape hatch, opened", shipped_report(), False, None, []),
        ("the escape hatch, with a leftover library",
         report_with(shipped_report(), libraryHosts=2, probeOwnedHosts=2,
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 2,
                                "seeded": 0}),
         False, None, ["not clean"]),
        # What this laptop actually measured on 2026-09-25: six app rows, one host removed, three
        # rows left and none of them orphaned. `Cascade` in the model, three rows gone in the
        # store. The same numbers under any other rule would be a lie about the model.
        ("the cascade the store performed", reap_case(6, 3, 0), True, CASCADE, []),
        ("a cascade that removed no rows", reap_case(6, 6, 0), True, CASCADE,
         ["cascades, yet"]),
        ("rows left with no host", reap_case(6, 6, 3), True, CASCADE,
         ["belonging to no host"]),
        ("a deletion the run never counted",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=0,
                     reapedHosts={"status": "reaped", "found": 1, "probeOwned": 1,
                                  "removed": 1, "remaining": 0},
                     seedHosts={"status": "seeded", "requested": 1, "seeded": 1}),
         True, CASCADE, ["not counted on both sides"]),
        ("a store that will not answer the orphan question",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=0,
                     reapedHosts={"status": "reaped", "found": 1, "probeOwned": 1,
                                  "removed": 1, "remaining": 0,
                                  "appRecordProblem": "counting failed: locked store"},
                     seedHosts={"status": "seeded", "requested": 1, "seeded": 1}),
         True, CASCADE, ["not counted on both sides"]),
        ("a model that cannot be read", reap_case(6, 3, 0), True, UNREADABLE,
         ["could not be read out of the model"]),
        # The same three rows leaving under a rule that says they should stay: green by count
        # alone, red because the store then is not running the model the audit read.
        ("rows vanishing under a non-cascade rule", reap_case(6, 3, 0), True, NULLIFY, []),
        ("rows staying under a non-cascade rule", reap_case(6, 6, 0), True, NULLIFY,
         ["something the model does not describe"]),
    ]
    for label, report, require_reap, rules, expected in diagnosis:
        problems = probe_problems(report, require_reap=require_reap, rules=rules)
        if expected and not problems:
            print("FAIL fixture: %s passed, and it should have been refused" % label)
            failures += 1
        elif expected and expected[0] not in "; ".join(problems):
            print("FAIL fixture: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, expected[0], problems[0][:160]))
            failures += 1
        elif not expected and problems:
            print("FAIL fixture: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   fixture: %s" % label)
        total += 1

    # The response that arrived without a unique id. Driven on its own because the flag that asks
    # for it changes what an absent record means: unasked, no record is the run minding its own
    # business; asked and unanswered, it is a flag that reached a build which ignores it -- and that
    # is the one failure a green would otherwise be covering for.
    CLEAN = {"status": "measured", "plantedUuid": "probe-host-partial", "parsedName": "Probe Host"
                                                                          " Partial",
             "parsedMac": "aa:bb:cc:dd:ee:f0", "parsedUuid": "<absent>",
             "uuidAfterPropagate": "probe-host-partial", "rowAfterPropagate": True,
             "hostsBeforeCleanup": 2, "hostsAfterCleanup": 2, "appsBefore": 6,
             "appsAfterCleanup": 6, "cleanedUp": "by-the-probe"}

    CLEAN_NAME = {"status": "measured", "plantedUuid": "probe-host-named",
                  "plantedName": "Probe Host Named", "parsedName": "<absent>",
                  "parsedUuid": "probe-host-named", "nameAfterPropagate": "Probe Host Named",
                  "displayNameAfterPropagate": "Probe Host Named", "hostsAfter": 2,
                  "probeOwnedAfter": 1, "appsBefore": 3, "appsAfter": 3,
                  "cleanedUp": "by-the-probe"}

    def partial_case(**changes):
        # Both records travel together, so a case that names one shape still has to hand the other
        # one over: otherwise every uuid case would also be refused for the name record it lacks.
        return report_with(shipped_report(), partialHostInfo=dict(CLEAN, **changes),
                           partialHostName=dict(CLEAN_NAME))

    def partial_name(**changes):
        return report_with(shipped_report(), partialHostInfo=dict(CLEAN),
                           partialHostName=dict(CLEAN_NAME, **changes))

    partials = [
        # Measured on 2026-09-25 after the guard went in: the uuid survived, the library kept its
        # host across a look at the device list, and the six app rows were still six. Both footings
        # are here on purpose -- asked for by name, and not asked for at all -- because the record
        # means different things to a CI job and to a laptop that never set the flag.
        ("the guarded write, as measured", partial_case(), True, []),
        ("the same record on a run nobody asked", partial_case(), False, []),
        # The record this laptop filed before the guard existed: the uuid gone, the host deleted by
        # the read, and three of somebody's applications gone with it. Every one of those three is
        # refused on its own, because each is a separate thing a future change can break.
        ("the uuid written away", partial_case(uuidAfterPropagate="<empty>"), True,
         ["left the stored host's uuid"]),
        ("a device list that deletes",
         partial_case(uuidAfterPropagate="<empty>", hostsBeforeCleanup=2, hostsAfterCleanup=1),
         True, ["took the library from"]),
        ("the cascade taking user configuration",
         partial_case(uuidAfterPropagate="<empty>", hostsBeforeCleanup=2, hostsAfterCleanup=1,
                      appsAfterCleanup=3),
         True, ["cascade that follows"]),
        # The premise. A body that carried its uuid never reaches the fall-back branch, so the run
        # below it would be measuring an ordinary response and reporting it as this one.
        ("a body that was not the one being asked about",
         partial_case(parsedUuid="probe-host-partial"), True, ["never reached"]),
        ("a body that parsed to nothing matchable", partial_case(parsedMac="<absent>"), True,
         ["parsed to no parsedMac"]),
        ("a run that planted somebody's real host",
         partial_case(plantedUuid="1c9d0e2f-3a4b-5c6d"), True, ["not a probe-owned uuid"]),
        ("a probe that could not count the rows",
         partial_case(appRecordProblem="counting failed: locked store"), True,
         ["could not be counted"]),
        ("a probe that left its subject behind", partial_case(cleanedUp="by-the-app"), True,
         ["left the host it planted"]),
        ("a status that measured nothing", partial_case(status="body-did-not-parse-as-intended"),
         True, ["instead of measuring"]),
        ("the flag reaching a build that ignores it", report_with(shipped_report(),
                                                                  partialHostInfo=None),
         True, ["reached a build that ignores it"]),
        # The name asked the same way. The red case is the record this laptop filed before the
        # second guard went in: the name gone, the display name reading as the empty string, and the
        # counts unmoved -- the shape that costs a blank row rather than a deleted machine.
        ("the name kept by the guard", partial_name(), True, []),
        ("the name written away",
         partial_name(nameAfterPropagate="<empty>", displayNameAfterPropagate=""), True,
         ["left the stored host's name"]),
        ("a row that reads out unlabelled",
         partial_name(nameAfterPropagate="Probe Host Named", displayNameAfterPropagate=""), True,
         ["no display name"]),
        ("a body that was not missing a name",
         partial_name(parsedName="Probe Host Named", nameAfterPropagate="Other"), True,
         ["nothing was missing"]),
        ("a name run that wrote more than a label",
         partial_name(appsAfter=0), True, ["did more than overwrite a label"]),
        ("the name step silently not running",
         report_with(shipped_report(), partialHostName=None), True, ["no partialHostName"]),
        # No record when nobody asked for one: the local run and the shape loops must not start refusing
        # over a step only CI sets.
        ("no record when nobody asked for one", shipped_report(), False, []),
    ]
    for label, report, require_partial, expected in partials:
        # Both rules judge every case, because both records are asked for together: a uuid shape
        # judged on its own would be refused for the name record it does not mention, and the case
        # that is meant to prove one rule bites would be proved by the other one instead.
        problems = (partial_host_problems(report["ownership"], require_partial)
                    + partial_name_problems(report["ownership"], require_partial))
        total += 1
        if expected and not problems:
            print("FAIL fixture: %s passed, and it should have been refused" % label)
            failures += 1
        elif expected and expected[0] not in "; ".join(problems):
            print("FAIL fixture: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, expected[0], problems[0][:160]))
            failures += 1
        elif not expected and problems:
            print("FAIL fixture: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   fixture: %s" % label)

    return failures, len(cases) + total


def report_with(report, **changes):
    ownership = dict(report["ownership"], **changes)
    return dict(report, ownership=ownership)


def production_missing(report):
    report = report_with(report)
    shapes = dict(report["ownership"]["shapes"], productionGraph="not-measured")
    return report_with(report, shapes=shapes)


# The declarations these fixtures were written against, spelled out rather than read: the self
# test has to keep working whatever the headers say today, and a fixture set that quietly changes
# meaning when somebody flips a property is a fixture set that stopped testing anything.
def shipped_declarations():
    return {"app.host": "strong", "host.appList": "strong"}


def dropped_observation(report):
    report = report_with(report)
    shapes = report["ownership"]["shapes"]
    record = {key: value for key, value in shapes["handBuiltGraph"].items()
              if key != "hostAliveWhileAppHeld"}
    return report_with(report, shapes=dict(shapes, handBuiltGraph=record))


def shapes_without(report, names):
    """A record from a build that never measured the named shapes.

    The shapes are not behind a flag, so this is what a build predating them -- or one where the
    call was dropped -- actually looks like, and it has to be refused rather than quietly judged
    over the shapes that happen to be there.
    """
    report = report_with(report)
    shapes = {name: record for name, record in report["ownership"]["shapes"].items()
              if name not in names}
    return report_with(report, shapes=shapes)


def shapes_with_extra(report, name="someFutureHolderShape"):
    """A build that grew a shape the audit has no rule for: green by omission, so refused."""
    report = report_with(report)
    shapes = dict(report["ownership"]["shapes"])
    shapes[name] = {"hostAliveWhileHeldByHolder": True}
    return report_with(report, shapes=shapes)


def mutate(report, shape, **changes):
    report = report_with(report)
    shapes = report["ownership"]["shapes"]
    shapes = dict(shapes, **{shape: dict(shapes[shape], **changes)})
    return report_with(report, shapes=shapes)


# The mutations that test a missing-evidence rule have to keep the evidence missing, or the repair
# below hands it back and the rule the case exists to prove bites never opens its mouth.
MISSING_EVIDENCE_WANTS = ("no reapedHosts", "not counted on both sides",
                               "no partialHostInfo", "no partialHostName",
                               "no severedBackpointerAppOnlyHolder",
                               "no severedBackpointerPairedHolder")


def with_filed_app_counts(report):
    """The app-record counts a pre-counting run would have written, from the seed's own fan-out.

    A record written before the app rows were counted cannot say how many there were, so the fill
    is an inference and is labelled as one: the seed attaches three apps to every host it plants,
    so a run that removed N hosts and left no orphans would have reported 3N rows going to 0. The
    number is only ever used to prove that a refusal came from the missing field -- if the filed
    record still fails once the field is filled, the rule is refusing something real.
    """
    reap = report["ownership"].get("reapedHosts")
    if not isinstance(reap, dict):
        return report
    removed = reap.get("removed")
    if not isinstance(removed, int) or removed == 0:
        return report
    if reap.get("appRecordsBefore") is not None or reap.get("appRecordsAfter") is not None:
        return report
    filled = dict(reap, appRecordsBefore=3 * removed, appRecordsAfter=0,
                  orphanAppRecordsBefore=0, orphanAppRecordsAfter=0)
    return report_with(report, reapedHosts=filled)


def with_filed_reap(report):
    """The reap entry a pre-reap run would have written for the library it actually found.

    Only ever used by the red team, on a record filed before the field existed. It is a repair of
    the sample, not of the rule: without it the missing field answers every question the red team
    asks, and the rules it is trying to prove bite never get to open their mouths.
    """
    if isinstance(report["ownership"].get("reapedHosts"), dict):
        return with_filed_app_counts(report)
    total = int(report["ownership"].get("libraryHosts") or 0)
    owned = int(report["ownership"].get("probeOwnedHosts") or 0)
    status = "empty" if total == 0 else ("kept" if owned == 0 else "mixed")
    return report_with(report, reapedHosts={"status": status, "found": total,
                                            "probeOwned": owned})


# ---------------------------------------------------------------------------
# The red team: break a real record and check that the rules bite on it
# ---------------------------------------------------------------------------
def with_filed_partial(report):
    """The same run with the partial-response step's record filled in.

    Records filed before a step existed cannot carry it, and the refusal for that absence has to be
    about the absence: hand the run the record it would have written had the step been there, and it
    must go green. Without this check the rule reads as "those runs were wrong", when what it says
    is "those runs did not look".
    """
    report = json.loads(json.dumps(report))
    ownership = report.get("ownership")
    if not isinstance(ownership, dict):
        return report
    if isinstance(ownership.get("partialHostInfo"), dict):
        # Filling in means supplying what was never looked at. A record that did look -- including
        # one the red team just broke -- keeps what it saw, or the repair would erase the mutation
        # it exists to test, which is exactly how a red team reports bites it never proved.
        return report
    if not isinstance(ownership.get("partialHostInfo"), dict):
        ownership["partialHostInfo"] = {
            "status": "measured", "plantedUuid": "probe-host-partial",
            "parsedName": "Probe Host Partial", "parsedMac": "aa:bb:cc:dd:ee:f0",
            "parsedUuid": "<absent>", "uuidAfterPropagate": "probe-host-partial",
            "rowAfterPropagate": True, "hostsBeforeCleanup": 2, "hostsAfterCleanup": 2,
            "appsBefore": 6, "appsAfterCleanup": 6, "cleanedUp": "by-the-probe",
        }
    if not isinstance(ownership.get("partialHostName"), dict):
        # The same repair for the record that came second: both experiments are asked for together,
        # so a record predating one of them is refused for that one and for nothing else.
        ownership["partialHostName"] = {
            "status": "measured", "plantedUuid": "probe-host-named",
            "plantedName": "Probe Host Named", "parsedName": "<absent>",
            "parsedUuid": "probe-host-named", "nameAfterPropagate": "Probe Host Named",
            "displayNameAfterPropagate": "Probe Host Named", "hostsAfter": 2,
            "probeOwnedAfter": 1, "appsBefore": 3, "appsAfter": 3, "cleanedUp": "by-the-probe",
        }
    return report


def with_filed_holder_shapes(report):
    """The two holder shapes a build predating them would have written, had it measured them.

    Same discipline as `with_filed_partial`: the repair supplies only the absent record, with the
    readings this laptop took of that shape, and never overwrites what a record did record -- or the
    red team would hand back the very evidence its mutation deleted and report a bite it did not
    prove. It exists to show that a filed record's refusal for a missing shape is about the absence,
    and that the shape is worth measuring rather than that the old run was wrong.
    """
    report = json.loads(json.dumps(report))
    shapes = report.get("ownership", {}).get("shapes")
    if not isinstance(shapes, dict):
        return report
    readings = {"severedBackpointerAppOnlyHolder": ("app-only", False),
                "severedBackpointerPairedHolder": ("app-and-host", True)}
    for name, (kind, host_held) in readings.items():
        if not isinstance(shapes.get(name), dict):
            shapes[name] = {"holderKind": kind, "backpointerSevered": True,
                            "hostAliveWhileHeldByHolder": host_held,
                            "appAliveWhileHeldByHolder": True,
                            "holderAliveWithNoHolder": False, "hostAliveWithNoHolder": False,
                            "appAliveWithNoHolder": False}
    return report


def red_team(sample_path, baseline, decls):
    """Mutate the committed record of a real run rather than an invented one.

    Same reason the leak audit reads a committed report and not a made-up one: an invented
    fixture can only contain the shapes its author thought of, and the mutations below are the
    shapes a future change is most likely to produce by accident.
    """
    try:
        with open(sample_path, encoding="utf-8") as handle:
            sample = json.load(handle)
    except (OSError, ValueError) as error:
        print("FAIL cannot read %s (%s), so the red team has nothing to mutate. A rule nobody"
              " can exercise is a rule nobody can trust." % (sample_path, error))
        return 1
    mutations = [
        ("a cycle that stopped leaking while the header still promises it",
         lambda report: mutate(report, "handBuiltGraph", hostAliveWithNoHolder=False),
         "ROOT CYCLE"),
        ("the control holding its own pair",
         lambda report: mutate(report, "backpointerOnly", hostAliveWithNoHolder=True),
         "back-pointer-only pair survives"),
        ("the production graph quietly becoming the hand-built one",
         lambda report: mutate(report, "handBuiltGraph", appListCount=0),
         "handBuiltGraph.appListCount"),
        # The guard coming back off. This is the shape a real store reported before the guard
        # existed -- uuid empty, one host gone across a look at the list, three user applications
        # gone with it -- so the mutation is not invented, it is the record this repository filed.
        ("a response without an id writing the identifier away",
         lambda report: report_with(report, partialHostInfo={
             "status": "measured", "plantedUuid": "probe-host-partial",
             "parsedName": "Probe Host Partial", "parsedMac": "aa:bb:cc:dd:ee:f0",
             "parsedUuid": "<absent>", "uuidAfterPropagate": "<empty>", "rowAfterPropagate": True,
             "hostsBeforeCleanup": 2, "hostsAfterCleanup": 1, "appsBefore": 6,
             "appsAfterCleanup": 3, "cleanedUp": "by-the-app"}),
         "left the stored host's uuid"),
        ("the partial-response step silently not running",
         lambda report: report_with(report, partialHostInfo=None), "no partialHostInfo"),
        ("a response with no hostname writing the name away",
         lambda report: report_with(report, partialHostName={
             "status": "measured", "plantedUuid": "probe-host-named",
             "plantedName": "Probe Host Named", "parsedName": "<absent>",
             "parsedUuid": "probe-host-named", "nameAfterPropagate": "<empty>",
             "displayNameAfterPropagate": "", "hostsAfter": 2, "probeOwnedAfter": 1,
             "appsBefore": 3, "appsAfter": 3, "cleanedUp": "by-the-probe"}),
         "left the stored host's name"),
        ("the missing-name step silently not running",
         lambda report: report_with(report, partialHostName=None), "no partialHostName"),
        ("the seed flag reaching a build that ignored it",
         lambda report: report_with(report, seedHosts=None),
         "no seedHosts"),
        ("the premise changing under the numbers",
         lambda report: report_with(report, holder="host-and-app"),
         "only outside holder"),
        ("a shape dropped from the report",
         lambda report: report_with(report, shapes={
             name: record for name, record in report["ownership"]["shapes"].items()
             if name != "productionGraph"}),
         "productionGraph"),
        # The library question, asked of a real record. Both of these are the runner's shape on
        # 2026-09-24: one host in the database, planted by the sweep a step earlier, and a run
        # that called it existing-hosts and measured it as the production graph.
        ("a library in which every host was planted by a probe",
         lambda report: report_with(
             report, libraryHosts=1, probeOwnedHosts=1,
             reapedHosts={"status": "empty", "found": 0, "probeOwned": 0},
             seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                        "seeded": 0}),
         "not clean"),
        ("a build that never saw the reap flag",
         lambda report: report_with(report, reapedHosts=None),
         "no reapedHosts"),
        # The clean-up flag reported honestly once and can report dishonestly the same way: the
        # verdict says the probe's own hosts are gone while the library still counts one of them.
        # The model's own rule, broken the way a migration would break it: the store stops
        # honouring `Cascade` and the rows simply stay, attached to a host that no longer exists.
        ("a removal that left every app row behind while the model cascades",
         lambda report: report_with(report, reapedHosts={
             "status": "reaped", "found": 1, "probeOwned": 1, "removed": 1, "remaining": 0,
             "appRecordsBefore": 6, "appRecordsAfter": 6, "orphanAppRecordsAfter": 0}),
         "cascades, yet"),
        ("a removal whose app rows were never counted",
         lambda report: report_with(report, reapedHosts={
             "status": "reaped", "found": 1, "probeOwned": 1, "removed": 1, "remaining": 0}),
         "not counted on both sides"),
        # The holder shapes, broken the four ways that would each turn the pairing's measured
        # contribution into a green that measured nothing. The first is what a build predating them
        # looks like, which is also what a build that lost the call looks like.
        ("the holder shapes silently not measured",
         lambda report: shapes_without(report, SEVERED_SHAPES),
         "no severedBackpointerPairedHolder"),
        ("the back-pointer quietly left attached",
         lambda report: mutate(report, "severedBackpointerPairedHolder",
                               backpointerSevered=False), "did not cut the back-pointer"),
        ("the harness holding its own holder",
         lambda report: mutate(report, "severedBackpointerAppOnlyHolder",
                               holderAliveWithNoHolder=True),
         "holding on to what it claims to watch"),
        ("a hidden holder behind the app-only shape",
         lambda report: mutate(report, "severedBackpointerAppOnlyHolder",
                               hostAliveWhileHeldByHolder=True),
         "something other than `app.host` is holding it"),
        ("the pairing unable to hold a host",
         lambda report: mutate(report, "severedBackpointerPairedHolder",
                               hostAliveWhileHeldByHolder=False),
         "cannot stand in for the strong"),
        ("a holder shape that outlived every holder",
         lambda report: mutate(report, "severedBackpointerPairedHolder",
                               hostAliveWithNoHolder=True), "outlived the last holder"),
        ("a shape nobody wrote a rule for",
         lambda report: shapes_with_extra(report), "does not know"),
        ("a clean-up that claimed to finish and did not",
         lambda report: report_with(
             report, libraryHosts=1, probeOwnedHosts=1,
             reapedHosts={"status": "removed-some", "found": 2, "probeOwned": 1,
                          "removed": 1, "remaining": 1},
             seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                        "seeded": 0}),
         "not the 0 the reap left"),
    ]
    failures = 0
    for label, change, want in mutations:
        report = change(json.loads(json.dumps(sample)))
        if want not in MISSING_EVIDENCE_WANTS:
            # The filed record predates the reap, so every mutation of it would otherwise be
            # refused for the missing field and the rules underneath would go untested: the red
            # team would report nine bites while proving one. Filling the field in is a mutation
            # of its own, so it is spelled out here -- the record gains the reap entry that run
            # would have written for the library it found, and nothing else is touched. The one
            # case that tests the missing field keeps it missing.
            report = with_filed_reap(with_filed_partial(with_filed_holder_shapes(report)))
        # CI runs this audit with the partial-response step asked for by name, so the red team
        # bites on CI's footing: a rule that only fires under a flag nobody passes in a fixture is
        # a rule nobody has watched fire.
        problems = probe_problems(report, require_partial=True)
        if not problems:
            problems, _notes = judge(report, decls, baseline)
        if not problems:
            print("FAIL red team: %s passed. The sample it was built from is a real record, so"
                  " this is a rule that does not bite." % label)
            failures += 1
        elif want not in "; ".join(problems):
            print("FAIL red team: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, want, problems[0][:180]))
            failures += 1
        else:
            print("ok   red team: %s" % label)

    # Every record filed in this repository, refused or accepted for the reason the baseline says
    # and no other. Filing a run is a claim about what the rules will make of it, and the claim
    # belongs to the record rather than to the code that reads it: when a greener run arrives, the
    # expectation changes because the evidence arrived, not because a rule was relaxed.
    records = baseline.get("filed_record_refusals")
    if not isinstance(records, dict) or not records:
        print("FAIL red team: the baseline files no `filed_record_refusals`, so nothing says what"
              " the committed records are supposed to do under these rules -- and a record that"
              " is expected to pass is as much a claim as one expected to fail.")
        failures += 1
    else:
        for name, want in sorted(records.items()):
            path = os.path.join(ROOT, "scripts", name)
            try:
                with open(path, encoding="utf-8") as handle:
                    filed = json.load(handle)
            except (OSError, ValueError) as error:
                print("FAIL red team: the baseline names %s and it cannot be read (%s)" % (name, error))
                failures += 1
                continue
            said = "; ".join(probe_problems(filed, require_partial=True))
            if want:
                missing = [expected for expected in want if expected not in said]
                if missing:
                    print("FAIL red team: %s was refused for the wrong reason(s): wanted %r, got %s"
                          % (name, missing[0], said[:200] or "no complaints at all"))
                    failures += 1
                    continue
                # And the refusal has to be about that and nothing else: give the old run the
                # record it would have written and it must go green, or the rule is refusing the
                # shape rather than the missing evidence.
                repaired = with_filed_reap(with_filed_partial(with_filed_holder_shapes(filed)))
                quiet = probe_problems(repaired, require_partial=True)
                if quiet:
                    print("FAIL red team: %s is still refused after the entries it predates are"
                          " filled in, so the refusal was not about the missing evidence: %s"
                          % (name, quiet[0][:180]))
                    failures += 1
                    continue
                print("ok   red team: %s, refused for exactly %r and for nothing else" % (name, want))
            else:
                if said:
                    print("FAIL red team: %s was expected to pass and was refused: %s"
                          % (name, said[:220]))
                    failures += 1
                    continue
                print("ok   red team: %s, accepted as the baseline files it" % name)

    # The holder rule is read off the tree rather than off a record, so its red team breaks the
    # tree -- in a dictionary in memory, with no file touched. The break is the interesting one:
    # un-pair the one site in this repository that does pair its app, and the rule has to notice
    # a holder lost its host rather than shrug, because a rule that shrugs here is the rule that
    # will shrug on the day somebody flips the back-pointer.
    sources = first_party_sources()
    paired_key = next((path for path, body in sorted(sources.items())
                       if "retriever.host =" in body), None)
    if paired_key is None:
        print("FAIL red team: no site in the tree pairs an app with a host any more, so the"
              " pairing rule cannot be broken here to prove it bites. If that is because the"
              " section 5 fix landed, the rule and this red team both need re-reading.")
        return failures + 1
    broken_sources = dict(sources)
    broken_sources[paired_key] = "\n".join(line for line in sources[paired_key].splitlines()
                                            if "retriever.host =" not in line)
    tree_cases = [
        ("the tree as it is, under the header that ships", app_assignment_sites(sources),
         decls, []),
        ("the one paired holder quietly un-paired", app_assignment_sites(broken_sources),
         decls, ["new holder"]),
        ("the holders that ship, under a weak header", app_assignment_sites(sources),
         fixed_declarations(), ["hand an app"]),
    ]
    stream_page = next((path for path in sources
                        if path.endswith("StreamViewController.m")), None)
    apps_page = next((path for path in sources if path.endswith("AppsViewController.m")), None)
    if apps_page is None:
        print("FAIL red team: no apps page in the tree, so the registrations that were measured"
              " multiplying here cannot be broken to prove the rule bites.")
        return failures + 1
    if stream_page is None:
        print("FAIL red team: no stream page in the tree, so the helper withdrawal that was measured"
              " protecting five registrations there cannot be moved to prove the ordering is judged.")
        return failures + 1

    def stream_page_late_withdrawal(tree, path):
        """A tree whose stream page calls `[self removeStreamSettingsObservers]` after registering.

        Only the position of the call moves. The registrations, the helper, and the tokens they
        assign stay as they ship, so a rule that reads the withdrawal as protecting them regardless
        of where the call sits has nothing left to complain about -- which is the whole point.
        """
        text = tree[path]
        call = "    [self removeStreamSettingsObservers];\n"
        first = text.find(call)
        assert first != -1, "the stream page no longer withdraws through that helper"
        text = text[:first] + text[first + len(call):]
        last = text.rfind("addObserverForName:")
        assert last != -1, "the stream page registers nothing"
        end_of_line = text.index("\n", last) + 1
        return dict(tree, **{path: text[:end_of_line] + call + text[end_of_line:]})

    registration_cases = [
        ("the registrations that ship, withdrawn before they are taken", sources, []),
        # The defect this rule was written for, broken out of the tree that produced it: two
        # withdrawals deleted from the apps page, which is the page where the multiplier was
        # measured, and the rule has to name both registrations rather than one.
        ("the apps page's selector withdrawals deleted",
         dict(sources, **{apps_page: "\n".join(
             line for line in sources[apps_page].splitlines()
             if "removeObserver:self name:@\"HostLatencyUpdated\"" not in line
             and "removeObserver:self name:NSUserDefaultsDidChangeNotification"
             not in line)}),
         ["2 notification registration(s) are made in a method that runs again"]),
        ("a Swift page with an appearance method and a registration",
         dict(sources, **{"Limelight/macOS/Page.swift":
                          "final class Page: NSViewController {\n"
                          "    override func viewDidAppear() {\n"
                          "        center.addObserver(forName: nil, object: nil, queue: nil)"
                          " { _ in }\n    }\n}\n"}),
         ["cannot read"]),
        # The hole in the reader, attacked through the tree it actually judges: a page whose only
        # registration sits behind a brace at column zero, withdrawn the way the shipped pages do,
        # and absent from the record. Reading the method early meant seeing no registration at all,
        # so the tree looked clean; the rule has to notice a registration it was never told about.
        ("a registration hidden behind a brace at column zero",
         dict(sources, **{"Limelight/macOS/TailPage.m":
                          "@implementation TailViewController\n"
                          "- (void)viewDidAppear {\n"
                          "    [self startWatching:^{\n"
                          "NSLog(@\"tick\");\n"
                          "}\n"
                          "];\n"
                          "    [[NSNotificationCenter defaultCenter] removeObserver:self"
                          " name:@\"TailLatencyUpdated\" object:nil];\n"
                          "    [[NSNotificationCenter defaultCenter] addObserver:self"
                          " selector:@selector(handleTail:) name:@\"TailLatencyUpdated\""
                          " object:nil];\n"
                          "}\n@end\n"}),
         ["new notification registration"]),
        # The same dependence attacked through the shipped tree: one wrapped call, withdrawn the way
        # the real pages withdraw theirs, absent from the record. Reading line by line saw no
        # registration in this page at all, so the tree looked clean.
        ("a registration whose call is wrapped, absent from the record",
         dict(sources, **{"Limelight/macOS/WrappedPage.m":
                          "@implementation WrappedViewController\n"
                          "- (void)viewDidAppear {\n"
                          "    [[NSNotificationCenter defaultCenter] removeObserver:self\n"
                          "        name:@\"WrappedLatencyUpdated\" object:nil];\n"
                          "    [[NSNotificationCenter defaultCenter] addObserver:self\n"
                          "        selector:@selector(handleWrapped:)\n"
                          "        name:@\"WrappedLatencyUpdated\" object:nil];\n"
                          "}\n@end\n"}),
         ["new notification registration"]),
        # The shape that ended a method at its own comment block: dead code kept inside the live
        # method, and one registration after it that the record does not name.
        ("a registration after a commented-out implementation",
         dict(sources, **{"Limelight/macOS/CommentedPage.m":
                          "@implementation CommentedViewController\n"
                          "- (void)viewDidAppear {\n"
                          "/*\n@implementation OldView\n- (void)deadCode {\n}\n@end\n*/\n"
                          "    [[NSNotificationCenter defaultCenter] removeObserver:self\n"
                          "        name:@\"CommentedLatencyUpdated\" object:nil];\n"
                          "    [[NSNotificationCenter defaultCenter] addObserver:self\n"
                          "        selector:@selector(handleCommented:)\n"
                          "        name:@\"CommentedLatencyUpdated\" object:nil];\n"
                          "}\n@end\n"}),
         ["new notification registration"]),
        # The stream page's own helper withdrawal moved below the five registrations it protects.
        # The page stays in the record and no line of the withdrawal itself changes, so the only
        # thing left to notice is the ordering -- and a rule that credited a helper wherever it sat
        # in the method noticed nothing: this injection passed with no problem at all before the
        # credit was restricted to the text preceding each registration.
        ("the stream page's helper withdrawal moved below its registrations",
         stream_page_late_withdrawal(sources, stream_page),
         ["made in a method that runs again"]),
        ("a registration deleted from a page without saying so",
         dict(sources, **{apps_page: "\n".join(
             line for line in sources[apps_page].splitlines()
             if "addObserver:self selector:@selector(handleHostLatencyUpdate:)"
             not in line)}),
         ["no longer made"]),
    ]
    for label, tree, want in registration_cases:
        problems, _notes = judge_registrations(observer_registration_sites(tree), baseline)
        problems = problems + registration_blind_spots(tree)
        if want and not problems:
            print("FAIL red team: %s passed. The registration rule did not notice the tree it was"
                  " written to read." % label)
            failures += 1
        elif want and want[0] not in "; ".join(problems):
            print("FAIL red team: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, want[0], problems[0][:170] if problems else "nothing"))
            failures += 1
        elif not want and problems:
            print("FAIL red team: %s was refused: %s" % (label, problems[0][:200]))
            failures += 1
        else:
            print("ok   red team: %s" % label)

    for label, sites, tree_decls, want in tree_cases:
        problems, _notes = judge_pairing(sites, tree_decls, baseline)
        if want and not problems:
            print("FAIL red team: %s passed. This is the rule that guards the fix, and it is not"
                  " guarding it." % label)
            failures += 1
        elif want and not any(expected in "; ".join(problems) for expected in want):
            print("FAIL red team: %s refused for the wrong reason: wanted %r, got %s"
                  % (label, want[0], problems[0][:180]))
            failures += 1
        elif not want and problems:
            print("FAIL red team: %s was refused: %s" % (label, problems[0][:180]))
            failures += 1
        else:
            print("ok   red team: %s" % label)
    return failures


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def read_probe_record(output_directory):
    path = os.path.join(output_directory, "report.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def capture(timeout, reap=True, partial=False):
    """Ask the Debug build who holds what, and hand back what it recorded.

    It needs the product `render-probe.py` builds and nothing else: no `leaks`, no page, no
    stream session, no LAN. That is the whole reason this measurement was cheap enough to run on
    every push while the one `leaks` does was not.
    """
    app = os.path.join(DERIVED, "Build", "Products", "Debug",
                       project_identity.product_name() + ".app")
    if not os.path.isdir(app):
        print("FAIL no Debug build at %s -- `render-probe.py` builds it, and this audit reads"
              " the product it leaves behind rather than building its own" % app)
        return None
    home = tempfile.mkdtemp(prefix="ownership-home.")
    out = tempfile.mkdtemp(prefix="ownership-out.")
    binary = os.path.join(app, "Contents", "MacOS", project_identity.bundle_executable(app))
    env = dict(os.environ, HOME=home, ML_OWNERSHIP_PROBE="1", ML_RENDER_PROBE_OUTPUT=out)
    if reap:
        # The flag is on by default, and off only for a person who wants to see the library as
        # the previous run left it. Leaving it off always would keep the gate blind to the one
        # thing the private `HOME` cannot do: give this run a database of its own.
        env["ML_PROBE_REAP_OWN_HOSTS"] = "1"
    if partial:
        # The flag that produces the record travels with the judgement that requires it, rather
        # than living in the workflow beside the `--require-partial` that asks for it. The local
        # gates replay the command line a job runs and nothing else, so a pair split between a
        # step's environment and its arguments is a pair the local run can only fail: it asked the
        # probe for a record it had never told the probe to write, and went red on its own harness
        # rather than on the code. One owner, one truth.
        env["ML_PROBE_PARTIAL_HOST_INFO"] = "1"
        env["ML_PROBE_PARTIAL_HOST_NAME"] = "1"
    try:
        try:
            subprocess.run([binary], capture_output=True, text=True, env=env, timeout=timeout,
                           cwd=ROOT)
        except subprocess.TimeoutExpired:
            print("FAIL the ownership probe did not answer inside %d seconds, so it never wrote"
                  " the record this audit reads. Raise `--timeout` if this machine is slow; it"
                  " does not change what is judged." % timeout)
            return None
        return read_probe_record(out)
    finally:
        # Both directories are this function's to remove, and removing them is worth doing --
        # but it is not isolation, and used to be described as if it were. The support directory
        # the probe opens resolves out of the account record rather than out of `HOME`, so the
        # database behind this run is the machine's own, and what keeps the run from inheriting
        # an earlier probe's graph is the reap flag above rather than the directory below.
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


def load_baseline():
    try:
        with open(BASELINE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        print("FAIL cannot read %s (%s). This gate judges observations against the expectations"
              " filed there, so with no file there is nothing to judge against and the run"
              " refuses rather than passes." % (BASELINE, error))
        return None


def parse(arguments):
    timeout = 120
    sample = SAMPLE
    index = 0
    while index < len(arguments):
        if arguments[index] == "--timeout":
            timeout = int(arguments[index + 1])
            index += 2
        elif arguments[index] == "--no-reap":
            index += 1
        elif arguments[index] == "--require-partial":
            index += 1
        elif arguments[index] == "--sample":
            sample = arguments[index + 1]
            index += 2
        else:
            index += 1
    return timeout, sample


def main():
    arguments = sys.argv[1:]
    timeout, sample = parse(arguments)
    baseline = load_baseline()
    if baseline is None:
        return 1
    decls = declarations()
    if "--self-test" in arguments:
        failures, total = self_test(baseline)
        pairing_failures, pairing_total = pairing_self_test(baseline)
        failures += pairing_failures
        total += pairing_total
        registration_failures, registration_total = observer_self_test(baseline)
        failures += registration_failures
        total += registration_total
        reader_failures, reader_total = assignment_reader_self_test(baseline)
        failures += reader_failures
        total += reader_total
        print("%d/%d ownership fixtures passed" % (total - failures, total))
        return 1 if failures else 0
    if "--red-team" in arguments:
        return 1 if red_team(sample, baseline, decls) else 0

    reap = "--no-reap" not in arguments
    partial = "--require-partial" in arguments
    report = capture(timeout, reap=reap, partial=partial)
    problems = probe_problems(report, require_reap=reap, require_partial=partial)
    notes = []
    if not problems:
        problems, notes = judge(report, decls, baseline)
    # The holders are judged off the source rather than off the run: which classes are handed an
    # app is a fact about the assignments, and no experiment can enumerate them by building
    # objects. Both halves have to answer before the gate answers.
    pairing, pairing_notes = judge_pairing(app_assignment_sites(first_party_sources()),
                                           decls, baseline)
    problems += pairing
    notes += pairing_notes
    # The second fact read off the tree rather than off this run. A notification registration made
    # where a visit runs it again is a multiplier on whatever its callback does -- on the apps page
    # that callback rereads the whole library -- and no probe can see it, because nothing about the
    # object graph changes when the same selector is registered twice.
    registrations, registration_notes = judge_registrations(
        observer_registration_sites(first_party_sources()), baseline)
    problems += registrations
    problems += registration_blind_spots(first_party_sources())
    notes += registration_notes
    if problems:
        for problem in problems:
            print("FAIL %s" % problem)
        if report is not None:
            print(json.dumps(report, indent=1, sort_keys=True))
        print("%d ownership failure(s)" % len(problems))
        return 1
    ownership = report["ownership"]
    seed = ownership.get("seedHosts") or {}
    # Named on every green line rather than left in the record: "measured on a host this run
    # wrote" and "measured on a graph an earlier run left in the shared database" are different
    # claims, and on a runner the two are one host apart -- which is exactly the pair of claims
    # the first version of this line got the wrong way round, because the sweep that seeds a host
    # runs a step earlier in the same job. The reap status is printed beside the count so the log
    # says both what the library held and what this run did about it.
    reap = ownership.get("reapedHosts") or {}
    print("ownership: declarations %s" % signature(decls))
    print("ownership: %d host(s) in the library (%s planted by a probe), seed status %s, reap"
          " status %s"
          % (ownership.get("libraryHosts", 0), ownership.get("probeOwnedHosts", "unrecorded"),
             seed.get("status", "unrecorded"), reap.get("status", "unrecorded")))
    if isinstance(reap.get("removed"), int) and reap["removed"]:
        # Named because the host count going to zero does not say the app rows went with it, and
        # an app row whose host is gone can never be listed or deleted through the app again.
        print("ownership: removing %d host(s) took the app records from %s to %s, with %s of them"
              " left belonging to no host"
              % (reap["removed"], reap.get("appRecordsBefore", "unrecorded"),
                 reap.get("appRecordsAfter", "unrecorded"),
                 reap.get("orphanAppRecordsAfter", "unrecorded")))
    print("ownership: %s" % summary(ownership))
    print("ownership: %d site(s) hand an app to a holder"
          % len(app_assignment_sites(first_party_sources())))
    for note in notes:
        print("note  %s" % note)
    print("note  section 5: %s" % section5_status(report, decls))
    print("0 ownership failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
