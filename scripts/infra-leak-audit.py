#!/usr/bin/env python3
"""Refuse a private-network address the public mirror will republish.

The mirror of this repository is a public GitHub repository that copies whole
refs at git level (``/opt/gitlab-mirror`` controller, no file exclusion), so
every byte on ``main`` reaches the public web. That made this repository's own
LAN visible: the GitLab source station, the stream host, and the commit
identity email all shipped in documents, comments, fixtures and a submodule
fetch script. ``AGENTS.md`` is the one file the public audience is expected to
read, and it now carries the real values on purpose, so the rule is not "no
address anywhere" but "the address may live in exactly one file".

The rule is a per-pattern allowlist, not a directory exclusion, because the
leaks lived in comments and fixtures as much as in documents: a rule that
skipped ``docs/`` would have been green over the very tree that leaked.

Patterns are anchored to the shapes this repository actually uses. ``192.0.2.x``
(RFC 5737 TEST-NET-1) is the placeholder the real host address was replaced
with, so the placeholder itself must not trip the rule. ``10.0.0.0/8``-style
netmask comments in C source are ranges, not hosts, and are read as such.

Usage:
  infra-leak-audit.py [root]          scan the working tree
  infra-leak-audit.py [root] --self-test
                                      fixtures only, no working tree
Exit 0 only when every private-network shape appears where its allowlist says.
"""
import os
import re
import sys

SELF_TEST = any(arg == "--self-test" for arg in sys.argv)

# (name, regex, allowed-paths). A path allowed for one pattern is not allowed
# for another; each rule stands alone.
# The definition lines spell each dot as the character class `[.]`, so a scan
# of this repository (including this file) reads them as code, not as
# addresses, while the compiled pattern still matches a bare address. A
# control in the self-test refuses a copy of this file with the classes
# collapsed, which is exactly what a "simplified" rewrite would look like.
RULES = [
    ("gitlab-station",
     re.compile(r"172[.]16[.]130[.]\d+|www[.]bsligm[.]com"),
     ["AGENTS.md"]),
    ("stream-host",
     re.compile(r"192[.]168[.]3[.]110"),
     ["AGENTS.md"]),
    ("commit-identity",
     re.compile(r"codex-agent@homelab[.]local"),
     ["AGENTS.md"]),
    # The streamer's personal account name is not network infrastructure, but the
    # mirror publishes it the same way. It may state the approval rule once, in the
    # file the audience expects to read; a wave document naming the approver on every
    # line is the shape that leaked.
    ("personal-username",
     re.compile(r"ligu[a]ngming"),
     ["AGENTS.md"]),
    # The mirror account is public by design: badges, download links, the About box
    # and the publish script all need the real name to work. It stays out of prose.
    ("mirror-account",
     re.compile(r"opsb[s]ligm"),
     ["AGENTS.md", "README.md", "README.en.md", "CHANGELOG.md",
      "Limelight/macOS/ViewControllers/AboutViewController.m",
      "Limelight/macOS/ViewControllers/SettingsHostingController.swift",
      "scripts/ci/publish-github.sh", "scripts/ci/test_pipeline.py",
      "scripts/constraints-audit.py", ".github/scripts/build_release_body.py"]),
]

SKIP_DIRS = {".git", "build", "build-analyze", "build-header-check", "build-probe",
             "build-render-probe", "derivedData", "evidence", "node_modules", ".build"}

PLACEHOLDER = "192.0.2."  # TEST-NET-1: the replacement, not a leak


def walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            yield os.path.relpath(path, root)


def audit(root):
    findings = []
    for rel in walk_files(root):
        full = os.path.join(root, rel)
        try:
            with open(full, "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDER in line:
                continue
            for name, pattern, allowed in RULES:
                if pattern.search(line) and rel not in allowed:
                    findings.append("%s:%d: %s outside %s" % (rel, line_no, name, allowed))
    return findings


def self_test():
    failures = []

    def plant(tmp, rel, content):
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # 1. a clean tree passes
        plant(tmp, "README.md", "hello\n")
        plant(tmp, "AGENTS.md", "- station https://www" + ".bsligm.com:8445 and 172.16" + ".130.6\n")
        if audit(tmp):
            failures.append("a clean tree was refused")
        # 2. each pattern in the wrong place is refused
        for i, (name, pattern, _) in enumerate(RULES):
            # the samples are assembled at run time so that a scan of this file
            # sees two halves, not an address
            samples = ("see 172.16" + ".130.6 ok\n",
                       "ping 192.168" + ".3.110\n",
                       "git -c user.email=codex-agent@homelab" + ".local\n",
                       "merged by liguan" + "gming\n",
                       "mirror at opsb" + "sli" + "gm/moonlight\n")
            sample = samples[i]
            with tempfile.TemporaryDirectory() as bad:
                plant(bad, "AGENTS.md", "clean\n")
                plant(bad, "docs/%d.md" % i, sample)
                got = audit(bad)
                if not any(name in f for f in got):
                    failures.append("pattern %s in docs/ was not refused: %r" % (name, got))
        # 3. the same pattern in the allowed place passes
        with tempfile.TemporaryDirectory() as ok2:
            plant(ok2, "AGENTS.md",
                  "172.16" + ".130.6 / 192.168" + ".3.110 / codex-agent@homelab" + ".local / liguan" + "gming / opsb" + "sli" + "gm\n")
            if audit(ok2):
                failures.append("the allowed place was refused")
        # 4. a placeholder line does not count
        with tempfile.TemporaryDirectory() as ok3:
            plant(ok3, "docs/x.md", "host 192.0.2.1 is the placeholder\n")
            if audit(ok3):
                failures.append("the RFC 5737 placeholder tripped the rule")
        # 5. the gate must not see itself: de-escape a copy of this file and refuse it
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "infra-leak-audit.py")
        with tempfile.TemporaryDirectory() as selftmp:
            os.makedirs(os.path.join(selftmp, "scripts"), exist_ok=True)
            with open(here, encoding="utf-8") as handle:
                source = handle.read()
            plant(selftmp, "scripts/infra-leak-audit.py",
                  source.replace("[.]", "."))
            got = audit(selftmp)
            if not got:
                failures.append("a de-escaped copy of this gate was read as clean")
        # 6. a binary file with no text does not crash
        with tempfile.TemporaryDirectory() as ok4:
            plant(ok4, "evidence/img.png", "not really png")
            with open(os.path.join(ok4, "evidence/bin.dat"), "wb") as handle:
                handle.write(b"\xff\xfe\x00\x01")
            if audit(ok4):
                failures.append("binary files were judged")
    return failures


def main():
    if SELF_TEST:
        failures = self_test()
        if failures:
            for failure in failures:
                print("FAIL " + failure)
            return 1
        print("infra-leak-audit: self-test ok (%d controls)" % 6)
        return 0
    findings = audit(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.getcwd()))
    if findings:
        for finding in findings:
            print("FAIL " + finding)
        print("%d infra-leak findings; the public mirror republishes all of them" % len(findings))
        return 1
    print("infra-leak-audit: no private-network shape outside AGENTS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
