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
    rb"api.?key|access.?token|secret.?key|client.?secret|auth.?token")


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
    for finding in _drain_batch(proc, paths):
        yield finding


def _drain_batch(proc, paths):
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
            if PRESCREEN.search(body) is None:
                continue
            text = body.decode("utf-8", "replace")
            if "\x00" in text:
                continue
            label = "history:" + paths.get(
                parts[0].decode("utf-8", "replace"), "(unreachable blob)")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if ALLOW in line:
                    continue
                for rule, pattern in RULES:
                    match = pattern.search(line)
                    if match:
                        # Four fields, exactly like scan_file(). The two scan
                        # modes are concatenated before they are printed, so a
                        # finding that carries fewer fields is a crash that only
                        # happens on the day the gate has found something.
                        yield label, line_number, rule, redact(match.group(0))
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
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW in line:
            continue
        for rule, pattern in RULES:
            match = pattern.search(line)
            if match:
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
    ]


def self_test():
    """Prove every rule catches its shape, and the report stays redacted."""
    failures = []
    caught = set()
    for rule, sample in fake_credentials():
        for name, pattern in RULES:
            if pattern.search(sample):
                caught.add(name)
        if rule not in caught:
            failures.append("rule %s does not match its own sample" % rule)

    clean = [
        "github_pat is documented as the fine-grained token family",
        "The token is read from a file at run time and never stored.",
        "uses: actions/checkout@v6",
        "let apiKeyPlaceholder = \"your-key-here\"",
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
