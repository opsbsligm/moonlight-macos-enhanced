#!/usr/bin/env python3
"""Refuse a commit that carries a live credential in the repository.

This gate exists because a personal access token was pasted into a working
session on 2026-09-16 while this repository was being debugged. It never
reached a commit, and nothing in the pipeline would have noticed if it had:
the token was read by a helper that wrote it to /tmp, the push step printed
nothing, and every audit in the audit job reads source text for behaviour and
says nothing about what the text happens to contain.

The failure this prevents is permanent, not temporary. A secret pushed to a
branch is in the object database, in every fork made afterwards, and in the
runner log of any job that echoes the file -- so the one moment it is cheap to
fix is the commit that adds it.

Detection is shape-based, never value-based: the report prints a rule name and
a redacted fragment so a green-to-red transition is explainable without the
report itself becoming another copy of the secret.

Usage:
  credential-scan-audit.py [--history] [--self-test]
Exit 0 only when no credential-shaped text is present.
"""
import os
import re
import hashlib
import signal
import subprocess
import sys
import tempfile

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = "credential-scan-audit:allow"
DEFAULT_TIMEOUT_SECONDS = 300


def _joined(*parts):
    # Sample credentials are assembled at run time so this file never carries a
    # string that satisfies one of its own rules. Without this the gate would
    # have to exempt itself, and an exemption written by the gate it exempts is
    # not an exemption anyone should trust.
    return "".join(parts)


# Each rule is (name, pattern). Patterns are written so the source text of this
# file cannot match them: every rule literal is broken by a character class or
# an escape that a real credential would never contain.
RULES = [
    ("github-fine-grained-pat",
     re.compile(r"github_[p]at_[0-9A-Za-z]{6,}_[0-9A-Za-z]{20,}")),
    ("github-token",
     re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}")),
    ("aws-access-key-id",
     re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack-token",
     re.compile(r"xox[baprs]-[0-9A-Za-z-]{20,}")),
    ("google-api-key",
     re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("stripe-secret-key",
     re.compile(r"sk_(?:live|test)_[0-9A-Za-z]{20,}")),
    ("private-key-block",
     re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    # The assignment shape is the noisy one, so it is deliberately narrower than
    # "any long word": it needs a credential-looking name, a quote, and a value
    # long enough that a placeholder in documentation is unlikely to reach it.
    ("quoted-credential-assignment",
     re.compile(r"(?i)\b(?:api[\-_]?key|access[\-_]?token|secret[\-_]?key|"
                r"client[\-_]?secret|auth[\-_]?token|personal[\-_]?access[\-_]?token)"
                r"\b\s*[=:]\s*[\"'][0-9A-Za-z_\-/+=.]{24,}[\"']")),
    # A vendor token is a credential because of who issued it. A literal password is a
    # credential because of what it unlocks, and nothing in the shape above
    # describes it: this repository shipped a temporary-keychain password as a
    # `static const char *` in a shipped binary for as long as that file existed,
    # and the eight rules above watched it go through every release. The name has
    # to say password, so the value never has to.
    ("hardcoded-credential-assignment",
     re.compile(r"(?i)\b[A-Za-z0-9_]*(?:password|passphrase|passwd|p12key)"
                r"[A-Za-z0-9_]*\s*(?:\[[^\]]*\])?\s*=\s*(?:CFSTR\()?(?:@?\")"
                r"([0-9A-Za-z_\-/.+]{8,})\"")),
]


# A byte-level prescreen in front of the rules. It must stay a superset: a
# value that satisfies a rule but not the prescreen gets skipped, and a gate
# that quietly skips is worse than an absent one, because the run still reads
# as a pass. self_test() proves the superset property for every rule. The
# prescreen is only worth the risk because --history visits every blob this
# project ever committed, almost none of which can contain a credential.
PRESCREEN = re.compile(
    rb"(?i)github_pat_|gh[pousr]_|AKIA[0-9A-Z]|xox[baprs]-|AIza|"
    rb"sk_(?:live|test)_|-----BEGIN|"
    rb"api.?key|access.?token|secret.?key|client.?secret|auth.?token|"
    rb"password|passwd|passphrase|p12key")


# The prescreen is a regular expression over every byte of every blob, and on a
# 607 MiB history it became the slowest step in the pipeline: 39 seconds warm on
# the development machine, and the CI runner passed its 300-second self-imposed
# budget doing it. Two tests run before the regex, both provably lossless, and
# together they remove most of that work:
#
#   1. A blob containing a NUL byte was already invisible to the rules -- the
#      history scan decodes it and skips anything with a NUL -- so checking for
#      one earlier cannot change a verdict. It is what 311 archive and media
#      blobs, 366 MiB of this repository's history, are made of.
#   2. The anchor set below is a superset of the rules: every string that
#      satisfies a rule contains one of these substrings, so a blob without an
#      anchor cannot contain a credential. self_test() proves it per rule, and
#      the regex prescreen still runs on everything that survives, so dropping a
#      rule family from the prescreen still goes red.
#
# Measured on this repository: 62s to walk the history before, 15s after, with
# the surviving set unchanged at 411 blobs.
ANCHORS = (b"key", b"token", b"secret", b"github_pat_", b"ghp_", b"gho_",
           b"ghu_", b"ghs_", b"ghr_", b"akia", b"xoxb-", b"xoxa-", b"xoxp-",
           b"xoxr-", b"xoxs-", b"aiza", b"sk_live_", b"sk_test_", b"-----begin",
           # password, passwd and passphrase each need their own anchor --
           # neither is a substring of the other, and only p12key is covered by
           # "key". An anchor set that misses one silences its rule before any
           # rule runs, which self_test() proves against a planted value.
           b"password", b"passwd", b"passphrase")


# Values that are knowingly still reachable in the object database, by the
# sha256 of the value rather than by path or commit: a path exemption hides the
# next file that copies the same literal, and a commit exemption hides whatever
# else that commit touched.
#
# An entry silences a HISTORY hit only, and only while the same value is absent
# from the tracked tree. Put the value back into a tracked file and both scans
# fail again, so an exemption can never become a back door that the next
# developer walks through without noticing.
HISTORY_EXEMPTIONS = {
    "732dfa98275bb3b007c639b1f7a3cb2051b638faaf075cd7c370e1589f664b2e": {
        "rule": "hardcoded-credential-assignment",
        "removed_from_tip": "the literal is gone from HttpManager.m; the "
                            "throwaway keychain password is now drawn at run time",
        "reason": "password of a keychain that is deleted before every import, so the "
                  "literal only taught every shipped binary the same secret; 56 blobs, "
                  "one distinct value, no live key material behind it",
    },
}


def fingerprint(value):
    """Stable identity for a matched value, never the value itself."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def matched_value(pattern, match):
    """The secret part of a match: a capture group when the rule has one."""
    if pattern.groups and match.group(1):
        return match.group(1)
    return match.group(0)


def history_exempt(value, tree_fingerprints):
    """True when a history-only exemption covers this value.

    The tree check is the load-bearing part: without it an exemption stays valid
    after the value returns to live code, which is exactly the state a security
    gate has to refuse.
    """
    fp = fingerprint(value)
    entry = HISTORY_EXEMPTIONS.get(fp)
    if entry is None:
        return False
    if fp in tree_fingerprints:
        return False
    return True


def is_exempt(value, mode, tree_fingerprints):
    """Whether one finding may be excused. Every scan asks this and nothing else.

    `mode` is the load-bearing argument, not `rule`: only the history walk may
    excuse anything, and it excuses one value at a time. Both scans route
    through here so the mode test is the single place a finding can be talked
    out of, which is what makes it something self_test() can hold open -- an
    exemption that also applied to the tree would otherwise be a back door with
    no switch to test.
    """
    if mode != "history":
        return False
    return history_exempt(value, tree_fingerprints)


def tree_value_fingerprints():
    """Fingerprints of every credential-shaped value in the tracked tree."""
    fps = set()
    for name in tracked_files():
        try:
            with open(os.path.join(root, name), "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            if ALLOW in line:
                continue
            for rule, pattern in RULES:
                match = pattern.search(line)
                if match:
                    fps.add(fingerprint(matched_value(pattern, match)))
    return fps


def carries_credential_shape(body):
    """Cheap gate in front of PRESCREEN; must stay a superset of the rules."""
    if b"\x00" in body:
        return False  # binary: the rules never saw a NUL-bearing blob anyway
    low = body.lower()
    for anchor in ANCHORS:
        if anchor in low:
            return True
    return False


def redact(value):
    """Show enough to identify a match, never the whole value."""
    if len(value) <= 12:
        return "*" * len(value)
    return "%s%s%s" % (value[:6], "*" * min(len(value) - 10, 24), value[-4:])


def tracked_files():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True)
    if result.returncode != 0:
        print("FAIL git ls-files failed: %s" %
              result.stderr.decode("utf-8", "replace").strip())
        return []
    names = [n.decode("utf-8", "replace")
             for n in result.stdout.split(b"\x00") if n]
    return names


def history_blobs():
    """Yield (label, rule, redacted) for every blob in every reachable object.

    `git cat-file --batch` frames each object as a header line followed by
    exactly <size> raw bytes. Splitting that stream on newlines would walk into
    the bytes of a compressed or binary blob and read them as headers, so the
    size from the header is the only thing that may advance the reader.
    """
    objects = subprocess.run(["git", "rev-list", "--objects", "--all"],
                             cwd=root, capture_output=True)
    if objects.returncode != 0:
        return
    paths = {}
    shas = []
    for line in objects.stdout.decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if not sha:
            continue
        shas.append(sha)
        if path:
            paths[sha] = path

    # The object list goes over as a file, not a pipe. Five thousand shas are
    # more than a pipe buffer, so writing that list while the reader is behind
    # deadlocks us against git's own stdout: the scan then hangs a runner
    # instead of failing it, which is the more expensive mistake of the two.
    with tempfile.TemporaryFile() as list_file:
        list_file.write("".join(sha + "\n" for sha in shas).encode())
        list_file.seek(0)
        proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                                stdin=list_file, stdout=subprocess.PIPE)
    # Computed once, before the walk, from the tree as it is now. An exemption is
    # a statement about the past, and the present is what decides whether it
    # still holds; re-deriving it per blob would let a value reappear mid-walk
    # and still be excused by the entry it was excused by.
    tree_fps = tree_value_fingerprints()
    for finding in _drain_batch(proc, paths, tree_fps):
        yield finding


def _drain_batch(proc, paths, tree_fps=()):
    """Read git's framed objects without losing the framing."""
    out = proc.stdout
    try:
        while True:
            header = out.readline()
            if not header:
                break
            parts = header.split()
            if len(parts) != 3 or parts[1] != b"blob":
                continue  # "missing", a tree, a commit, or a bad object
            body = out.read(int(parts[2]))
            out.read(1)  # the single newline that closes the payload
            # Cheapest test first: the NUL check and the literal anchors are what
            # make the whole-history walk fit its budget. The prescreen that
            # follows is the same one the tree scan uses, so both modes still
            # agree on what a credential-shaped value is.
            if not carries_credential_shape(body):
                continue
            if PRESCREEN.search(body) is None:
                continue
            text = body.decode("utf-8", "replace")
            if "\x00" in text:
                continue
            label = "history:" + paths.get(
                parts[0].decode("utf-8", "replace"), "(unreachable blob)")
            # "history" is the only mode that may consult the exemption table,
            # and it excuses one value at a time. The tree scan reaches the same
            # helper as "tree", so the same literal in a tracked file stays a
            # finding even while its history twin is excused. Four fields,
            # exactly like scan_file(), because the two modes are concatenated
            # before they are printed.
            for finding in scan_lines(label, text.splitlines(), "history",
                                      tree_fps):
                yield finding
    finally:
        proc.stdout.close()
        proc.wait()


def scan_file(name):
    path = os.path.join(root, name)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return []
    if b"\x00" in raw:
        return []
    text = raw.decode("utf-8", "replace")
    return scan_lines(name, text.splitlines(), "tree")


def scan_lines(name, lines, mode, tree_fps=()):
    """Apply every rule to the already-decoded lines of one blob or file.

    Both scan modes go through here, so a rule that works in one mode works in
    the other and a finding has one shape wherever it was found. `mode` is what
    separates them, and the exemption table is the only thing that reads it:
    "tree" never excuses anything, so a value that a historical exemption names
    is still a finding the moment it is back in live code.
    """
    findings = []
    for number, line in enumerate(lines, start=1):
        if ALLOW in line:
            continue
        for rule, pattern in RULES:
            match = pattern.search(line)
            if not match:
                continue
            value = matched_value(pattern, match)
            if is_exempt(value, mode, tree_fps):
                continue
            findings.append((name, number, rule, redact(match.group(0))))
    return findings


def scan_tree():
    findings = []
    for name in tracked_files():
        findings.extend(scan_file(name))
    return findings


def report(findings, quiet=False):
    """Print every finding with a redacted value. Returns True if any exist.

    Both scan modes hand rows to this one function, which is what keeps the
    tree scan and the history scan telling the same story -- and what makes a
    row with the wrong number of fields fail here, in the self-test, rather
    than on the first real hit.
    """
    for name, number, rule, shown in findings:
        if not quiet:
            print("FAIL %s:%s %s %s" % (name, number, rule, shown))
    if findings:
        if not quiet:
            print("\n%d credential-shaped value(s) in the repository. Revoke the "
              "credential first, then remove it; rewriting history after a "
              "push is cleanup, not a fix." % len(findings))
        return True
    return False


def fake_credentials():
    """Credential-shaped strings that are not credentials."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    tail = alphabet[:40]
    return [
        ("github-fine-grained-pat",
         _joined("github_", "pat_", "11CHI4KTY", "0" * 24, "_", tail)),
        ("github-token", _joined("gh", "p_", tail)),
        ("aws-access-key-id", _joined("AKIA", "EXAMPLEIDXXXXXABCD")),
        ("slack-token", _joined("xox", "b-", "0" * 22)),
        ("google-api-key", _joined("AIza", tail[:35])),
        ("stripe-secret-key", _joined("sk_", "live_", tail[:24])),
        ("private-key-block", _joined("-----BEGIN ", "RSA ",
                                      "PRIVATE KEY-----")),
        ("quoted-credential-assignment",
         _joined("api_key = \"", tail, "\"")),
        # Assembled from parts for the same reason as the others: a whole literal
        # in this file would satisfy the rule this sample exists to prove works.
        ("hardcoded-credential-assignment",
         _joined("password", " = \"", "CorrectHorse", "7", "\"")),
        # The shape this repository actually shipped: the credential noun is a
        # suffix of the identifier, not its start, and the value is nine
        # characters -- too short for the vendor-token rules, unnamed enough for
        # the assignment rule. A matcher that only anchors on a name that
        # *begins* with the noun passes the sample above and misses this one,
        # which is the exact hole that shipped.
        ("hardcoded-credential-assignment",
         _joined("static const char *kTempKeychain", "password",
                 " = \"", "SaltedNot", "42", "\"")),
    ]


def self_test():
    """Prove every rule catches its shape, and the report stays redacted."""
    failures = []
    caught = set()
    for rule, sample in fake_credentials():
        # Each sample is judged on its own. A rule may now carry more than one
        # sample because one shape is not enough to describe a family: the
        # credential that shipped here had the noun as the *end* of its
        # identifier, and a matcher narrowed to names that start with the noun
        # still matches the sample whose identifier starts with it. Accumulating
        # `caught` across samples let that narrowed rule pass, so the verdict is
        # taken per sample and the running set only records what nothing matched.
        matched = [name for name, pattern in RULES if pattern.search(sample)]
        caught.update(matched)
        if rule not in matched:
            failures.append("rule %s does not match its own sample" % rule)

    clean = [
        "github_pat is documented as the fine-grained token family",
        "The token is read from a file at run time and never stored.",
        "uses: actions/checkout@v6",
        "let apiKeyPlaceholder = \"your-key-here\"",
        "NSString *password = readClientCertificatepassword();",
        "settings.lockOnSleep = FALSE;",
    ]
    for line in clean:
        for name, pattern in RULES:
            if pattern.search(line):
                failures.append("clean line matched %s: %s" % (name, line))

    # The prescreen may decide what never reaches the rules, so it has to be a
    # superset of them. An empty scan over a tree that contains a credential is
    # the exact failure a security gate is allowed not to have.
    for rule, sample in fake_credentials():
        if PRESCREEN.search(sample.encode()) is None:
            failures.append("prescreen would skip %s before any rule ran" % rule)

    # The anchor test in front of the prescreen is a second chance to skip
    # silently, so it answers the same question for the same samples. A rule
    # added later whose value carries no anchor trips this, not the history walk.
    for rule, sample in fake_credentials():
        if not carries_credential_shape(sample.encode()):
            failures.append("the anchor test would skip %s before any rule ran"
                            % rule)

    # And it has to reject something, or it is decoration that cannot fail. The
    # line below names none of the anchors, so a gate that always says "maybe"
    # is caught here rather than on the day it stops short-circuiting anything.
    if carries_credential_shape(b"uses: actions/checkout@v6"):
        failures.append("the anchor test admits a line with no credential "
                        "anchor, so it short-circuits nothing")

    # An exemption is the one place this gate can be talked out of a finding, so
    # its two limits run as checks. The historical value cannot be re-derived --
    # that is the point of keying by digest -- so the mechanism is proved on a
    # probe entry built here, and the real rows are held to their metadata.
    for fp, entry in HISTORY_EXEMPTIONS.items():
        if entry.get("rule") not in {name for name, _pattern in RULES}:
            failures.append("exemption %s.. names a rule that does not exist: %s"
                            % (fp[:8], entry.get("rule")))
        if not entry.get("reason"):
            failures.append("exemption %s.. carries no reason" % fp[:8])
        if len(fp) != 64:
            failures.append("exemption %s.. is not keyed by a sha256 digest"
                            % fp[:8])

    probe = _joined("password", " = \"Correct", "Horse7\"")
    probe_match = dict(RULES)["hardcoded-credential-assignment"].search(probe)
    if probe_match is None:
        failures.append("the exemption probe no longer has the shape the rule "
                        "detects, so its two checks below prove nothing")
    else:
        probe_value = probe_match.group(1)
        probe_fp = fingerprint(probe_value)
        HISTORY_EXEMPTIONS[probe_fp] = {
            "rule": "hardcoded-credential-assignment", "reason": "self-test"}
        try:
            if not is_exempt(probe_value, "history", frozenset()):
                failures.append("an exemption does not excuse the value it "
                                "names in history mode")
            if is_exempt(probe_value, "history", frozenset({probe_fp})):
                failures.append("an exemption still excuses its value once that "
                                "value is back in the tracked tree")
            # The mode is what keeps an exemption historical, so it is asserted
            # rather than assumed. Same value, same table entry, same empty tree
            # set -- the only difference is which scan is asking, and a tree scan
            # has to be told no whatever the table says.
            if is_exempt(probe_value, "tree", frozenset()):
                failures.append("an exemption excuses a value in tree mode, so "
                                "the same literal back in live code would go "
                                "unreported")
            if is_exempt(probe_value, "tree", frozenset({probe_fp})):
                failures.append("tree mode consults the exemption table at all")
        finally:
            del HISTORY_EXEMPTIONS[probe_fp]

    # The tree scan never consults the table, so an exempt value that reappears in
    # live code has to be visible here. It is a statement about this checkout, and
    # it is the check that keeps the table from quietly rotting into a back door.
    shared = set(HISTORY_EXEMPTIONS) & tree_value_fingerprints()
    if shared:
        failures.append("an exempt value is present in the tracked tree (%s..), "
                        "so the history exemption must go" % next(iter(shared))[:8])

    # A gate that prints the secret is a second leak of the secret.
    for rule, sample in fake_credentials():
        shown = redact(sample)
        if shown == sample:
            failures.append("redaction returned the whole value for %s" % rule)
        if len(shown) > 40:
            failures.append("redaction leaked %d characters for %s"
                            % (len(shown), rule))

    # Both scan modes feed one printer. A row shaped for one mode and read by
    # the other is a crash on the first real finding, which is the moment a
    # security gate is least allowed to become a traceback.
    rows = [("scripts/example.py", 7, "github-token", redact(
        fake_credentials()[1][1]))]
    rows.append(("history:scripts/example.py", 3, "aws-access-key-id",
                 redact(fake_credentials()[2][1])))
    try:
        found = report(rows, quiet=True)
    except Exception as error:  # noqa: BLE001 - the shape is the assertion
        failures.append("report() cannot print a finding from both modes: %s"
                        % error)
    else:
        if not found:
            failures.append("report() called a list of findings clean")

    # The source of this gate must satisfy the gate.
    this_file = os.path.relpath(os.path.abspath(__file__), root)
    for name, number, rule, _hidden in scan_file(this_file):
        failures.append("this gate trips its own rule: %s:%d %s"
                        % (name, number, rule))

    if failures:
        for failure in failures:
            print("FAIL %s" % failure)
        print("\ncredential scan self-test: %d failures" % len(failures))
        return 1
    print("credential scan self-test: %d rules armed, %d clean samples, "
          "report stays redacted" % (len(RULES), len(clean)))
    return 0


class ScanTimedOut(Exception):
    """The scan stopped itself rather than holding a runner open."""


def main():
    argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    seconds = DEFAULT_TIMEOUT_SECONDS
    if "--timeout" in argv:
        seconds = max(1, int(argv[argv.index("--timeout") + 1]))

    def _expired(signum, frame):
        raise ScanTimedOut()

    # A whole-history scan is bounded by wall clock on purpose. Without a bound
    # the failure mode of a framing bug is a job that sits until the runner
    # reaps it an hour later, which looks like infrastructure and gets retried
    # into silence; a bounded scan fails with a sentence that says why.
    signal.signal(signal.SIGALRM, _expired)
    signal.alarm(seconds)
    findings = []
    try:
        findings = scan_tree()
        if "--history" in argv:
            findings.extend(list(history_blobs()))
    except ScanTimedOut:
        print("FAIL the credential scan exceeded %d seconds and stopped "
              "rather than reporting a verdict it had not earned" % seconds)
        return 1
    finally:
        signal.alarm(0)
    # The verdict sentence lives in report(), so a finding is described once
    # however it was found.
    if report(findings):
        return 1
    scanned = len(tracked_files())
    print("ok %d tracked file(s) carry no credential shape (%d rule(s) armed)"
          % (scanned, len(RULES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
