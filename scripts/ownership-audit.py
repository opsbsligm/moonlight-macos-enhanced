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
HOST_ASSIGNMENT = re.compile(r"\b[A-Za-z_]\w*\.host\s*=")


def method_span(text, offset):
    """The (start, end) of the Objective-C method containing `offset`, or None.

    The crude version, deliberately: the question asked of the body is "does this same body also
    hand that holder a host", and a smarter body-finder would answer the same question. Methods
    here start at column zero with `- (` or `+ (` and end at a `}` at column zero.
    """
    start = max(text.rfind("\n- (", 0, offset), text.rfind("\n+ (", 0, offset))
    if start < 0:
        return None
    end = text.find("\n}", start)
    return (start, len(text)) if end < 0 else (start, end)


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
        for match in APP_ASSIGNMENT.finditer(text):
            holder = match.group("holder")
            span = method_span(text, match.start())
            body = text[span[0]:span[1]] if span else ""
            paired = any(HOST_ASSIGNMENT.search(line) and
                         line.split(".host")[0].strip().endswith(holder)
                         for line in body.splitlines() if ".host =" in line)
            sites.append({"file": os.path.basename(path), "holder": holder,
                          "key": "%s|%s.app" % (os.path.basename(path), holder),
                          "statement": match.group(0).strip(), "pairedWithHost": paired})
    return sites


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


def probe_problems(report, require_reap=True):
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
    problems.extend(reap_problems(ownership, seed, require_reap))
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
        for shape in SHAPES:
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
            " commit that flips the back-pointer, not in a later one. The measurement is here and"
            " the judgement is unchanged until a commit moves it")


REAP_STATUSES = ("empty", "kept", "reaped", "removed-some")


def reap_problems(ownership, seed, require_reap=True):
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
    return " | ".join("%s: held=%s no-holder=%s (appList %s)"
                      % (shape,
                         "yes" if shapes[shape]["hostAliveWhileAppHeld"] else "no",
                         "yes" if shapes[shape]["hostAliveWithNoHolder"] else "no",
                         shapes[shape]["appListCount"])
                      for shape in SHAPES if isinstance(shapes.get(shape), dict))


# ---------------------------------------------------------------------------
# The fixtures: every refusal this gate can issue, driven from a synthetic report
# ---------------------------------------------------------------------------
def shipped_report():
    """The shape today's declarations promise, as the laptop measured it.

    Written from a real run rather than typed: the numbers below are what the probe recorded on
    a machine with a library of its own (two hosts, the picked one carrying three apps).
    """
    def shape(count, held, readable, leak_host, leak_app):
        return {"appListCount": count, "hostAliveWhileAppHeld": held,
                "appHostReadableWhileAppHeld": readable, "hostAliveWithNoHolder": leak_host,
                "appAliveWithNoHolder": leak_app}

    return {"ownership": {"holder": "app-only", "libraryHosts": 2, "probeOwnedHosts": 0,
                          "reapedHosts": {"status": "kept", "found": 2, "probeOwned": 0},
                          "productionHostUuid": "86D1F81F-4D3D-E306-D694-EFDFE6BCD6CE",
                          "seedHosts": {"status": "existing-hosts", "requested": 1,
                                        "existing": 2, "seeded": 0},
                          "shapes": {"productionGraph": shape(3, True, True, True, True),
                                     "handBuiltGraph": shape(1, True, True, True, True),
                                     "backpointerOnly": shape(0, True, True, False, False)}},
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
                                  "removed": 1, "remaining": 1},
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 1,
                                "seeded": 0}),
         strong, baseline, []),
        ("a clean-up that left one of its own behind",
         report_with(shipped_report(), libraryHosts=1, probeOwnedHosts=1,
                     reapedHosts={"status": "removed-some", "found": 2, "probeOwned": 1,
                                  "removed": 1, "remaining": 1},
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
    diagnosis = [
        ("the escape hatch, opened", shipped_report(), False, []),
        ("the escape hatch, with a leftover library",
         report_with(shipped_report(), libraryHosts=2, probeOwnedHosts=2,
                     seedHosts={"status": "existing-hosts", "requested": 1, "existing": 2,
                                "seeded": 0}),
         False, ["not clean"]),
    ]
    for label, report, require_reap, expected in diagnosis:
        problems = probe_problems(report, require_reap=require_reap)
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


def mutate(report, shape, **changes):
    report = report_with(report)
    shapes = report["ownership"]["shapes"]
    shapes = dict(shapes, **{shape: dict(shapes[shape], **changes)})
    return report_with(report, shapes=shapes)


def with_filed_reap(report):
    """The reap entry a pre-reap run would have written for the library it actually found.

    Only ever used by the red team, on a record filed before the field existed. It is a repair of
    the sample, not of the rule: without it the missing field answers every question the red team
    asks, and the rules it is trying to prove bite never get to open their mouths.
    """
    if isinstance(report["ownership"].get("reapedHosts"), dict):
        return report
    total = int(report["ownership"].get("libraryHosts") or 0)
    owned = int(report["ownership"].get("probeOwnedHosts") or 0)
    status = "empty" if total == 0 else ("kept" if owned == 0 else "mixed")
    return report_with(report, reapedHosts={"status": status, "found": total,
                                            "probeOwned": owned})


# ---------------------------------------------------------------------------
# The red team: break a real record and check that the rules bite on it
# ---------------------------------------------------------------------------
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
        if want != "no reapedHosts":
            # The filed record predates the reap, so every mutation of it would otherwise be
            # refused for the missing field and the rules underneath would go untested: the red
            # team would report nine bites while proving one. Filling the field in is a mutation
            # of its own, so it is spelled out here -- the record gains the reap entry that run
            # would have written for the library it found, and nothing else is touched. The one
            # case that tests the missing field keeps it missing.
            report = with_filed_reap(report)
        problems = probe_problems(report)
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
            said = "; ".join(probe_problems(filed))
            if want:
                missing = [expected for expected in want if expected not in said]
                if missing:
                    print("FAIL red team: %s was refused for the wrong reason(s): wanted %r, got %s"
                          % (name, missing[0], said[:200] or "no complaints at all"))
                    failures += 1
                    continue
                # And the refusal has to be about that and nothing else: give the old run the"
                # record it would have written and it must go green, or the rule is refusing the
                # shape rather than the missing evidence.
                quiet = probe_problems(with_filed_reap(json.loads(json.dumps(filed))))
                if quiet:
                    print("FAIL red team: %s is still refused after the reap entry it predates is"
                          " filled in, so the refusal was not about the reap: %s"
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


def capture(timeout, reap=True):
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
        print("%d/%d ownership fixtures passed" % (total - failures, total))
        return 1 if failures else 0
    if "--red-team" in arguments:
        return 1 if red_team(sample, baseline, decls) else 0

    reap = "--no-reap" not in arguments
    report = capture(timeout, reap=reap)
    problems = probe_problems(report, require_reap=reap)
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
