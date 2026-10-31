#!/usr/bin/env python3
"""Check that the source matrix says what the repository can actually prove.

`docs/source-matrix-2026-10-25.md` is where every competitor claim gets its evidence
tier, and the tier is the whole point: `仅宣传` must never be designed against, and
`上游已验证` must be re-runnable. Until now nothing checked either half of that. The
matrix is prose, the evidence lives in `docs/evidence/*/README.md` plus the snapshot
files beside it, and the two were free to disagree. Measured state when this audit was
written -- four cells disagreed with the repository and no gate noticed:

  * the moonlight-qt cell said "快照未钉 commit/SHA，无法复核到具体行" while
    `docs/evidence/qt-snapshot/README.md` had pinned commit `de2467e4` and two blob
    SHAs that `git hash-object` reproduces exactly;
  * the Sunshine cell pinned release `v2026.1018.5342`, a tag that does not exist
    (GitHub's latest stable at that moment was `v2026.914.233613`), while the snapshot
    README had pinned `master` at `a679b059`;
  * the common-c cell pinned a submodule SHA the checkout no longer had;
  * Parsec's pinned SHA-256 was abbreviated into a form nothing can re-verify.

The shape is the same defect Wave S fixed on the diagnostics report: producer and
consumer each green, the seam between them unwatched. So the rules below are all
seam rules, and every one of them is satisfied in exactly one of two ways -- pin the
commit, or write down that you did not. An unsatisfied cell has to *admit* it, which is
what makes an unverified tier impossible to leave quietly in place.

Rules (codes are stable; they appear in the report):

  SM001 a referenced `docs/evidence/...` path does not exist
  SM002 a snapshot README declares a git blob SHA that `git hash-object` does not
        reproduce for the file sitting next to it (the snapshot drifted, or the README
        was typed rather than measured)
  SM003 a snapshot README quotes `file.ext:LINE` for a file it ships, and the identifier
        named in the same bullet is not on that line -- the quote no longer lands where
        the document says it does
  SM005 a cell whose object has a snapshot with a pinned commit does not name that
        commit in its version column
  SM006 a cell denies having pinned a commit ("未钉 commit") for an object that does
        have a pinned snapshot -- the matrix disowning evidence the repository holds
  SM007 a cell carries no commit-shaped pin and does not admit it in either its version
        or its unknown column ("未钉" / "无版本")
  SM008 a 40-hex commit for *this* repository does not resolve in the local object
        database (an invented or mistyped SHA)
  SM009 the evidence tier column starts with none of the four tiers the discipline
        defines -- a tier invented in prose is a tier nobody can check
  SM010 a verification date is missing, malformed, or in the future
  SM011 a snapshot README abbreviated a SHA-256 (`prefix…suffix`) and the matrix
        repeats an abbreviation that does not match the full value the README carries
  SM012 a cell for *this* repository pins both a commit and a build number that the
        repository says are the same fact twice (`build = git rev-list --count HEAD`),
        and the two disagree -- a stale pair reads as self-consistent prose
  SM013 a cell for *this* repository pins a commit that resolves as an object but is
        not reachable from the checked-out history (an object left behind by a fetch,
        or a SHA copied from a branch that never merged)
  SM014 the audit is running in a shallow clone, where SM012 and SM013 cannot be scored
        honestly: `rev-list --count` reports the fetch depth, so a correct-looking pair

  A code stays out of this list when it has no `add(findings, ...)` behind it. `SM004`
  ("the matrix and the snapshot README give different commits") was drafted, never
  implemented, and removed on 2026-10-31; its intent is exactly SM005, which does fire.
  That gap is what the three-way self-test below now refuses to let reopen, so the note
  is prose rather than a rule line -- a rule nobody emits is the defect this file checks
  other documents for.

        can be certified by a tree that never saw the commits it claims to have counted

What this audit does not see, stated rather than implied: it cannot tell whether a
release tag exists upstream (that needs the network, and a gate that needs the network
is a gate that goes red for reasons the tree did not cause), it cannot tell whether a
quote is *relevant* to the claim it supports, and it does not know whether a cell is
stale -- a cell pinned to a real commit stays green after the upstream moves on. Those
are the reasons the pin column is paired with a verification date, not a substitute for
re-checking.

Usage:
  source-matrix-audit.py [--verify] [--json] [--quiet]
  source-matrix-audit.py --self-test
Exit 0 only when every rule holds on the shipped matrix and evidence.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join("docs", "source-matrix-2026-10-25.md")
EVIDENCE = os.path.join("docs", "evidence")

# The four tiers `docs/input-mapping-benchmark.md` §1 defines. A cell may qualify a tier
# in parentheses, but it has to *start* with one of these, or the tier is prose only.
TIERS = ("本仓库可复核", "上游已验证", "机制级证据", "仅宣传", "无证据", "待调研")

# Writing one of these is the honest way to hold an unpinned cell. It satisfies SM007 so
# that "we did not pin this" has exactly one spelling in the matrix.
ADMIT = ("未钉", "无版本")

HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
HEXSHORT = re.compile(r"\b[0-9a-f]{7,12}\b")
SHA256_FULL = re.compile(r"\b[0-9a-f]{64}\b")
SHA256_ABBREV = re.compile(r"\b([0-9a-f]{6,})…([0-9a-f]{4,})\b")
DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# The build number and the commit are the same fact stated twice, because
# `Limelight/build-number.sh` defines BUILD_NUMBER as `git rev-list --count HEAD`. A cell
# that pairs them is therefore checkable without the network: recompute one from the other.
BUILD_PAIR = re.compile(r"main\s*`([0-9a-f]{7,40})`\s*[，,]\s*build\s*(\d+)")
EVIDENCE_REF = re.compile(r"docs/evidence/([A-Za-z0-9._-]+)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
# `gamepad.cpp:763`, `windows_input.cpp:684-705`, or a bare `:690-692` that inherits the
# file named earlier in the same bullet.
LINEREF = re.compile(r"`([A-Za-z0-9_.+-]*\.(?:cpp|h|c|hpp|mm|swift))?(?<!`):?(\d{1,6})(?:-(\d{1,6}))?`")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def rows(matrix):
    """Data rows of every table in the matrix, as column lists."""
    out = []
    for line in matrix.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cols):
            continue
        if cols[0] in ("对象", "产品"):
            continue
        out.append(cols)
    return out


def snapshot_files(readme_text):
    """The `| file | upstream path | blob SHA |` table a snapshot README declares."""
    out = []
    for line in readme_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 3:
            continue
        name = cols[0].strip("`")
        blob = cols[-1].strip("`")
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", name):
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", blob):
            continue
        out.append({"name": name, "upstream": cols[1].strip("`"), "blob": blob})
    return out


def declared_commits(readme_text):
    return set(HEX40.findall(readme_text.split("|")[0]))


def git_blob_sha(path):
    """git's own hash of the file's bytes, independent of any repository."""
    proc = subprocess.run(["git", "hash-object", "--", path],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def line_claims(readme_text, sole_file=None):
    """Bullets that pair an identifier with a `file:LINE` in the same breath.

    The bullet is the unit because that is where a snapshot README says "this name is at
    this line". Requiring the longest identifier in the bullet to appear on the cited
    line is what stops a quote from silently pointing somewhere else after an edit.

    A bare `:690-692` inherits the file from the snapshot when it ships just one.
    """
    claims = []
    for bullet in readme_text.splitlines():
        if not bullet.strip().startswith("-"):
            continue
        refs = LINEREF.findall(bullet)
        if not refs:
            continue
        # Identifiers come from code spans only. Prose words are prose: a bullet that
        # says "ViGEm 类型选择块：`windows_input.cpp:684-705`" describes the block, it
        # does not claim the string ViGEm is on those lines. `config::input.gamepad`
        # contributes its first segment, which is what appears in the source.
        names = []
        for span in re.findall(r"`([^`]+)`", bullet):
            if LINEREF.search("`%s`" % span):
                continue
            head = re.split(r"[:.(\[]", span.strip())[0]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", head):
                names.append(head)
        for fname, start, end in refs:
            if not fname:
                fname = sole_file or ""
            claims.append({"file": fname, "start": int(start),
                           "end": int(end) if end else int(start),
                           "names": names})
    return claims


def audit_snapshot(root, directory, findings):
    """Rules SM002/SM003 over one snapshot directory. Returns its pinned commits."""
    snap = os.path.join(root, EVIDENCE, directory)
    readme = os.path.join(snap, "README.md")
    if not os.path.isfile(readme):
        return set()
    text = read(readme)
    header = text.split("|")[0]
    commits = declared_commits(text)

    files = snapshot_files(text)
    # A bare `:690-692` inherits the file. With one file in the snapshot that is
    # unambiguous, and it is the common shape; skipping those would leave the rule
    # covering only the READMEs that happen to repeat the filename.
    sole = files[0]["name"] if len(files) == 1 else None

    for entry in files:
        path = os.path.join(snap, entry["name"])
        if not os.path.isfile(path):
            add(findings, "SM002", "%s/%s" % (directory, entry["name"]),
                "README declares blob %s for a file that is not in the snapshot"
                % entry["blob"][:12])
            continue
        actual = git_blob_sha(path)
        if actual != entry["blob"]:
            add(findings, "SM002", "%s/%s" % (directory, entry["name"]),
                "README declares blob %s, git hash-object says %s -- the snapshot and "
                "the document that pins it disagree"
                % (entry["blob"][:12], (actual or "?")[:12]))

    for claim in line_claims(text, sole):
        if not claim["file"]:
            continue
        path = os.path.join(snap, claim["file"])
        if not os.path.isfile(path):
            continue  # a quote about a file the snapshot does not ship is out of reach
        lines = read(path).splitlines()
        if claim["start"] > len(lines):
            add(findings, "SM003", "%s:%s" % (claim["file"], claim["start"]),
                "README cites line %d of a %d-line snapshot file"
                % (claim["start"], len(lines)))
            continue
        window = "\n".join(lines[claim["start"] - 1:claim["end"]])
        if claim["names"] and not any(name in window for name in claim["names"]):
            add(findings, "SM003", "%s:%d-%d" % (claim["file"], claim["start"], claim["end"]),
                "README cites this range for %s, none of whose identifiers appear there "
                "anymore" % ", ".join(sorted(set(claim["names"]))[:3]))

    return commits | set(HEX40.findall(header))


def git(root, *args):
    """Run git inside the tree under audit, returning stdout or None.

    The tree is a parameter rather than a constant because --self-test audits a copy: a
    helper that always reached for the shipped checkout would grade the sample matrix
    against the real repository's history, and a mutation in the sample could never make
    a history rule fail.
    """
    proc = subprocess.run(["git"] + list(args), cwd=root, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def local_commit_resolves(root, sha):
    return git(root, "cat-file", "-e", "%s^{commit}" % sha) is not None


def rev_count(root, sha):
    """The commit's position in its own history: 1-based, matching build-number.sh."""
    out = git(root, "rev-list", "--count", sha)
    return int(out) if out and out.isdigit() else None


def history_is_shallow(root):
    """Whether this checkout's history is a fetch fragment rather than the whole line.

    `Limelight/build-number.sh` refuses to name a build number from a shallow tree, and
    for good reason that `constraints-audit.py` enforces: `rev-list --count` there returns
    the fetch depth, so a shallow clone once derived build 71 for a commit CI stamped 1407.
    The same trap sits under SM012, so the pair check refuses the same input instead of
    certifying a number it never counted.
    """
    return git(root, "rev-parse", "--is-shallow-repository") == "true"


def add(findings, code, where, message):
    findings.append({"code": code, "where": where, "message": message})


def audit(root):
    """All rules against a tree. `root` is swapped for a copy by --self-test."""
    findings = []
    matrix_path = os.path.join(root, MATRIX)
    if not os.path.isfile(matrix_path):
        return [dict(code="SM001", where=MATRIX, message="matrix file is missing")]
    matrix = read(matrix_path)
    today = subprocess.run(["date", "+%Y%m%d"], stdout=subprocess.PIPE,
                           text=True).stdout.strip() or "99999999"

    # Evidence side, collected once so the matrix side can be reconciled against it.
    snapshots = {}
    evidence_root = os.path.join(root, EVIDENCE)
    if os.path.isdir(evidence_root):
        for name in sorted(os.listdir(evidence_root)):
            if os.path.isfile(os.path.join(evidence_root, name, "README.md")):
                snapshots[name] = audit_snapshot(root, name, findings)

    for cols in rows(matrix):
        strip = lambda text: text.replace("**", "")
        subject = strip(cols[0])
        source = strip(cols[1])
        version = strip(cols[3])
        verified = strip(cols[4])
        tier = strip(cols[5])
        unknown = strip(cols[6])
        where = subject[:28]
        # A pin counts wherever the row states it. One cell puts the 40-hex commit in its
        # source column and another in its version column; both are pinned.
        row_text = " ".join((source, version, unknown))

        refs = [r for r in EVIDENCE_REF.findall(source + " " + version + " " + unknown)]
        for ref in refs:
            if ref not in snapshots and not os.path.isfile(
                    os.path.join(root, EVIDENCE, ref)):
                add(findings, "SM001", where,
                    "cell points at docs/evidence/%s, which does not exist" % ref)

        pinned = set()
        for ref in refs:
            pinned |= snapshots.get(ref, set())

        if pinned:
            cell_commits = set(HEX40.findall(version)) | {c for c in HEXSHORT.findall(version)
                                                          if len(c) >= 7}
            if not any(any(pin.startswith(c) for pin in pinned) for c in cell_commits):
                add(findings, "SM005", where,
                    "snapshot pins %s but the cell's version column names none of them"
                    % ", ".join(sorted(p[:8] for p in pinned)))
            if "未钉" in unknown:
                add(findings, "SM006", where,
                    "cell says 未钉 commit while docs/evidence/%s pins one" % (refs or ["?"])[0])

        if not pinned:
            has_pin = bool(HEX40.search(row_text) or HEXSHORT.search(row_text)
                           or SHA256_FULL.search(row_text)
                           or SHA256_ABBREV.search(row_text))
            if not has_pin and not any(word in version or word in unknown for word in ADMIT):
                add(findings, "SM007", where,
                    "no commit is pinned and the cell does not say so -- write 未钉版本 in "
                    "the version or unknown column to record that this is deliberate")

        if not any(tier.startswith(t) for t in TIERS):
            add(findings, "SM009", where,
                "evidence tier %r starts with none of the defined tiers" % tier[:24])

        dates = DATE.findall(verified)
        if not dates:
            add(findings, "SM010", where, "verification column carries no ISO date")
        else:
            for year, month, day in dates:
                stamp = "%s%s%s" % (year, month, day)
                if int(month) > 12 or int(day) > 31:
                    add(findings, "SM010", where, "verification date %s-%s-%s is not a date"
                        % (year, month, day))
                elif stamp > today:
                    add(findings, "SM010", where, "verification date %s is in the future"
                        % stamp)

        # This repository's own pin has to exist as a commit here; upstream commits are
        # reconciled against their snapshot README instead, since we do not hold them.
        if "本项目" in subject:
            for sha in set(HEX40.findall(version)) | set(HEXSHORT.findall(version)):
                if len(sha) >= 7 and not local_commit_resolves(root, sha):
                    add(findings, "SM008", where,
                        "main is pinned to %s, which this checkout cannot resolve" % sha)

            if history_is_shallow(root):
                add(findings, "SM014", where,
                    "this checkout is shallow, so `git rev-list --count` reports the fetch "
                    "depth rather than the build number; check this matrix from a full "
                    "history (fetch-depth 0) instead of trusting the pair")
                continue

            # The build number is defined as `rev-list --count HEAD`, so a cell that
            # states both is making two claims about one fact. An outdated pair -- right
            # commit, stale build, or the reverse -- reads as ordinary prose and no reader
            # recomputes it by hand, which is how the 8945676e/1993 cell went stale twice.
            for sha, build in BUILD_PAIR.findall(version):
                count = rev_count(root, sha)
                if count is None:
                    continue  # SM008 already reports a SHA this tree cannot resolve
                if count != int(build):
                    add(findings, "SM012", where,
                        "cell pairs main %s with build %s, but `git rev-list --count %s` "
                        "= %s; the build number is that count, so one of the two is stale"
                        % (sha[:12], build, sha[:12], count))
                # Reachability is a separate question from resolvability: an object can
                # exist in the store from a fetch and still be on no line of our history.
                elif git(root, "merge-base", "--is-ancestor", sha, "HEAD") is None:
                    add(findings, "SM013", where,
                        "cell pins main %s, which resolves here but is not an ancestor of "
                        "the checked-out HEAD" % sha[:12])

        # An abbreviated SHA-256 in the matrix has to match the full value next door.
        for prefix, suffix in SHA256_ABBREV.findall(version + " " + source + " " + unknown):
            # Only READMEs that are actually there. Reaching for a reference SM001 just
            # declared missing raised FileNotFoundError out of the whole audit, which
            # meant a broken evidence link could never be *reported*: the tool died
            # before printing the finding, and a crashed gate reads as "not run" rather
            # than "red" wherever a pipeline treats a nonzero-but-no-verdict as noise.
            neighbours = [read(os.path.join(root, EVIDENCE, r, "README.md"))
                          for r in refs
                          if os.path.isfile(os.path.join(root, EVIDENCE, r, "README.md"))]
            full = SHA256_FULL.findall(" ".join(neighbours))
            if full and not any(f.startswith(prefix) and f.endswith(suffix) for f in full):
                add(findings, "SM011", where,
                    "abbreviated SHA-256 %s…%s matches no full value in the snapshot README"
                    % (prefix, suffix))

    return findings


SAMPLE_MATRIX = """# matrix

| 对象 | 来源 | 平台 | 版本 / 钉住点 | 验证日期 | 证据层级 | 未知项 |
| --- | --- | --- | --- | --- | --- | --- |
| 样例对象 | `docs/evidence/sample-snapshot/README.md` | x | commit `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | 2026-10-31 | 本仓库可复核 | 无 |
| 未钉对象 | 官网 | x | 未钉版本 | 2026-10-31 | 仅宣传 | 无 |
| 本项目（样例） | 本地仓库 | x | main `%(own_sha)s`，build %(own_build)d | 2026-10-31 | 本仓库可复核 | 无 |
| 摘要对象 | `docs/evidence/sample-snapshot/README.md` | x | commit `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` 的产物 SHA-256 `cccccc…cccc` | 2026-10-31 | 机制级证据 | 无 |
"""

SAMPLE_README = """样例快照

钉住版本：commit `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`

被检文件整体 SHA-256：`cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`

| 文件 | 上游路径 | git blob SHA |
| --- | --- | --- |
| `thing.cpp` | `src/thing.cpp` | `%s` |

- `ImportantSymbol` 调用：`thing.cpp:2`
"""

SAMPLE_SNIPPET = "line one\nImportantSymbol();\nline three\n"


def sample_tree():
    """A miniature *git repository* that passes every rule, so mutations start clean.

    Reusing the shipped files here would mean a mutation check could only ever observe a
    tree that is already red or already green for reasons unrelated to the mutation.
    The history rules (SM008, SM012, SM013) ask git questions, so the sample has to be a
    repository of its own: auditing a plain directory against the real checkout's history
    would let those three rules pass without ever being able to fail.
    """
    root = tempfile.mkdtemp(prefix="source-matrix-audit-")
    docs = os.path.join(root, "docs")
    os.makedirs(os.path.join(docs, "evidence", "sample-snapshot"))
    blob = git_blob_sha_of_text(SAMPLE_SNIPPET)
    with open(os.path.join(docs, "evidence", "sample-snapshot", "thing.cpp"),
              "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_SNIPPET)
    with open(os.path.join(docs, "evidence", "sample-snapshot", "README.md"),
              "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_README % blob)
    git(root, "init", "-q")
    git(root, "-c", "user.name=audit", "-c", "user.email=audit@example.invalid",
        "add", "-A")
    git(root, "-c", "user.name=audit", "-c", "user.email=audit@example.invalid",
        "commit", "-q", "-m", "sample baseline")
    own_sha = git(root, "rev-parse", "HEAD")
    own_build = rev_count(root, own_sha) if own_sha else None
    if not own_sha or not own_build:
        raise AssertionError("sample repository did not produce a resolvable HEAD commit")
    # Written last, because the self-pinning row can only name a commit that exists.
    with open(os.path.join(docs, MATRIX.split(os.sep)[1]), "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_MATRIX % {"own_sha": own_sha, "own_build": own_build})
    return root


def git_blob_sha_of_text(text):
    proc = subprocess.run(["git", "hash-object", "--stdin"], input=text.encode(),
                          stdout=subprocess.PIPE)
    return proc.stdout.decode().strip()


def mutate(root, relative, old, new, count=1):
    path = os.path.join(root, relative)
    text = read(path)
    if old not in text:
        raise AssertionError("mutation target absent: %s" % old[:40])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new, count))


def self_test():
    """Every rule has to refuse something, or it is not a rule."""
    root = sample_tree()
    try:
        baseline = audit(root)
        if baseline:
            print("self-test failed: the sample tree is not a clean baseline: %s"
                  % "; ".join("%s %s" % (f["code"], f["where"]) for f in baseline),
                  file=sys.stderr)
            return 1

        matrix = os.path.join(*MATRIX.split(os.sep))
        readme = os.path.join("docs", "evidence", "sample-snapshot", "README.md")
        snippet = os.path.join("docs", "evidence", "sample-snapshot", "thing.cpp")
        # The sample pins itself, so the history mutations know what to overwrite. The
        # sha is stable across the copy because the copy carries the object store.
        own = git(root, "rev-parse", "HEAD")
        own_build = rev_count(root, own)
        EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

        checks = []

        # 1. A blob the bytes do not reproduce.
        def one(r):
            mutate(r, readme, "`%s`" % git_blob_sha_of_text(SAMPLE_SNIPPET),
                   "`bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`")
        checks.append(("SM002", one))

        # 2. The snapshot file itself changes under a README that still pins the old blob.
        def two(r):
            with open(os.path.join(r, snippet), "a", encoding="utf-8") as fh:
                fh.write("appended line\n")
        checks.append(("SM002", two))

        # 3. A line quote that no longer lands on the name it was written for.
        def three(r):
            mutate(r, readme, "`thing.cpp:2`", "`thing.cpp:1`")
        checks.append(("SM003", three))

        # 4. The matrix and the snapshot pin different commits.
        def four(r):
            mutate(r, matrix, "commit `aaaa", "commit `eeee")
        checks.append(("SM005", four))

        # 5. The matrix disowning a commit the snapshot holds: the exact shape the
    #    shipped matrix had for moonlight-qt.
        def five(r):
            mutate(r, matrix, "| 无 |\n| 未钉对象",
                   "| 未钉 commit/SHA |\n| 未钉对象")
        checks.append(("SM006", five))

        # 6. An unpinned cell that does not admit it.
        def six(r):
            mutate(r, matrix, "未钉版本 | 2026-10-31 | 仅宣传", "v1.2.3 | 2026-10-31 | 仅宣传")
        checks.append(("SM007", six))

        # 7. A tier invented in prose.
        def seven(r):
            mutate(r, matrix, "| 仅宣传 |", "| 明显更强 |")
        checks.append(("SM009", seven))

        # 8. A verification date that has not happened yet.
        def eight(r):
            mutate(r, matrix, "2026-10-31 | 本仓库可复核", "2999-01-01 | 本仓库可复核")
        checks.append(("SM010", eight))

        # 9. A commit this tree cannot resolve at all.
        def nine(r):
            mutate(r, matrix, own, "f" * 40)
        checks.append(("SM008", nine))

        # 10. The pinned commit and the build number disagreeing while each still looks
        #     plausible on its own -- the exact shape of the stale 8945676e/1993 cell.
        def ten(r):
            mutate(r, matrix, "，build %d " % own_build, "，build %d " % (own_build + 1))
        checks.append(("SM012", ten))

        # 11. A commit that exists in the object store but is on no line of our history:
        #     reachable-by-hash, unreachable-by-ancestry, and self-consistent as a pair.
        def eleven(r):
            orphan = git(r, "-c", "user.name=audit", "-c", "user.email=audit@example.invalid",
                         "commit-tree", EMPTY_TREE, "-m", "orphan")
            mutate(r, matrix, own, orphan)
        checks.append(("SM013", eleven))

        # 12. A tree whose history is a fetch fragment. The pair still *reads* correct
        #     here -- that is the danger -- because `rev-list --count` answers with the
        #     fetch depth, so SM012 would certify a number this tree never counted.
        def twelve(r):
            with open(os.path.join(r, ".git", "shallow"), "w", encoding="utf-8") as fh:
                fh.write(own + "\n")
        checks.append(("SM014", twelve))

        # 13. A cell pointing at evidence that is not in the repository. Renaming the
        #     directory is the honest mutation: deleting it would also satisfy SM007's
        #     "does the cell admit it has no pin" branch, and the check would then pass
        #     for a reason that has nothing to do with the reference being broken.
        def thirteen(r):
            snap = os.path.join(r, EVIDENCE, "sample-snapshot")
            os.rename(snap, snap + "-renamed")
        checks.append(("SM001", thirteen))

        # 14. An abbreviated SHA-256 that matches nothing next door. The digest has to
        #     stay well-formed -- a short or non-hex token reads as a typo to the reader
        #     and to the regex, so the rule would fire on the wrong grounds.
        def fourteen(r):
            mutate(r, matrix, "`cccccc\u2026cccc`", "`dddddd\u2026cccc`")
        checks.append(("SM011", fourteen))

        # Three sets have to be the same set, because each gap between two of them is a
        # rule dying quietly. A code the docstring promises with no `add()` behind it is
        # a claim nothing keeps -- SM004 sat in exactly that state until 2026-10-31, and
        # it read as extra diligence. A code something emits that no mutation proves
        # fires is indistinguishable from a rule that stopped firing, which is the
        # sentence at the top of this file aimed back at itself.
        with open(os.path.abspath(__file__), encoding="utf-8") as own_source:
            own_text = own_source.read()
        documented = set(re.findall(r"^  (SM\d{3}) ", own_text, re.MULTILINE))
        emitted = set(re.findall(r"add\(findings,\s*\"(SM\d{3})\"", own_text))
        proved = {code for code, _ in checks}
        for label, wider, narrower in (
                ("documented as a rule but never emitted by any code path",
                 documented, emitted),
                ("emitted but never proved to fire by a mutation", emitted, proved),
                ("proved by a mutation yet missing from the rule list", proved, documented)):
            if wider - narrower:
                print("self-test failed: %s: %s"
                      % (", ".join(sorted(wider - narrower)), label), file=sys.stderr)
                return 1
        print("rule inventory: %d codes documented, emitted and proved" % len(documented))

        for index, (code, apply_mutation) in enumerate(checks, 1):
            work = tempfile.mkdtemp(prefix="sma-mutation-")
            try:
                shutil.copytree(root, work, dirs_exist_ok=True)
                apply_mutation(work)
                codes = {f["code"] for f in audit(work)}
            finally:
                shutil.rmtree(work, ignore_errors=True)
            if code not in codes:
                print("self-test failed: mutation %d (%s) was not caught, caught=%s"
                      % (index, code, sorted(codes) or "nothing"), file=sys.stderr)
                return 1
            print("mutation %d caught by %s" % (index, code))
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="audit the shipped tree")
    parser.add_argument("--self-test", action="store_true", help="prove the rules refuse")
    parser.add_argument("--json", action="store_true", help="machine-readable findings")
    parser.add_argument("--quiet", action="store_true", help="only report the verdict")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    findings = audit(ROOT)
    if args.json:
        print(json.dumps({"violations": len(findings), "findings": findings},
                         ensure_ascii=False, indent=2))
    elif not args.quiet:
        for item in findings:
            print("%s %s: %s" % (item["code"], item["where"], item["message"]))
        print("source matrix: %d violation(s)" % len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
