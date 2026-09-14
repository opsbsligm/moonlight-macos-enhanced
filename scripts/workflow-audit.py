#!/usr/bin/env python3
"""Audit the CI definition itself, because a workflow that never starts gates nothing.

A run that dies while the file is being parsed produces a red check with no jobs
and no readable log. Two such defects reached this repository at once: one step
lost its `run:` key, and another step grew a second `run:` at the same mapping
level. `yaml.safe_load` accepts both -- it keeps the last duplicate key and never
asks whether a step can execute -- so the step that was supposed to protect the
pipeline was blind to the one file it was checking.

Every rule below is either something GitHub Actions refuses to load, or a mistake
GitHub accepts while silently making a matrix value empty, a condition always
true, or a gate skippable. Each violation prints its own code, so a failure names
its own reason.
"""

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

RULES = {
    "WF001": "duplicate mapping key (GitHub refuses to load the file)",
    "WF002": "workflow file has no jobs section",
    "WF003": "step has neither `run` nor `uses` (GitHub refuses to load the file)",
    "WF004": "step has both `run` and `uses` (GitHub refuses to load the file)",
    "WF005": "step id is reused inside one job, so the step context is ambiguous",
    "WF006": "job id is not a legal identifier",
    "WF007": "job has no `runs-on` (GitHub refuses to load the file)",
    "WF008": "job has no steps",
    "WF009": "`needs` names a job that does not exist (GitHub refuses to load the file)",
    "WF010": "`needs` graph has a cycle (GitHub refuses to load the file)",
    "WF011": "`needs.<job>.outputs.<name>` reads an output that job never declares",
    "WF012": "`${{ matrix.<name> }}` is not part of the job matrix, so it expands to empty",
    "WF013": "`needs.<job>` is read but that job is not in `needs`",
    "WF014": "a referenced repository script does not exist",
    "WF015": "`continue-on-error` turns a gate into a suggestion",
    "WF016": "an expression block is left open, so the rest of the line is literal text",
    "WF017": "workflow file cannot be parsed",
    "WF018": "step name is empty, so a failing step cannot be identified in the log",
    "WF019": "a shell script names an interpreter the audit runner does not have",
    "WF020": "a shell script uses zsh syntax that the interpreter it names cannot run",
}

# A script that switched from zsh to bash while keeping a zsh-only construct
# parses cleanly and fails at run time, inside a build phase, with a message that
# points at nothing useful. These are the constructs that survive bash -n.
ZSH_ONLY_SYNTAX = (
    (r"\$\{=", "forced word splitting"),
    (r"\$\{\^", "glob-flagged expansion"),
    (r"\$\{\(", "bracketed expansion flags"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*:[ahlrtueqQA]\}", "history-style modifier"),
    (r"\bfor\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", "parenthesised for list"),
    (r"\b(?:autoload|zmodload|setopt|whence|vared)\b", "zsh-only builtin"),
    (r"\bprint\s+-[a-zA-Z]\b", "zsh print flags"),
    (r"\$\{pipestatus\[", "zsh pipe status array"),
)

# The audit job runs on ubuntu, so a shebang has to resolve there as well as on
# the macOS machine that wrote it. /bin/zsh exists on macOS and not on ubuntu,
# and the kernel reports the missing interpreter as the script itself being
# absent, so the failure names the wrong file.
RUNNER_INTERPRETERS = {"/bin/bash", "/bin/sh", "/usr/bin/env bash", "/usr/bin/env sh"}


JOB_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EXPR_OPEN = re.compile(r"\$\{\{")
SCRIPT_REF = re.compile(r"(?:^|[\s'\"(])(\.?[A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)*\.(?:py|sh))")
NEEDS_OUTPUT = re.compile(r"\bneeds\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")
NEEDS_ANY = re.compile(r"\bneeds\.([A-Za-z0-9_-]+)\b")
MATRIX_REF = re.compile(r"\bmatrix\.([A-Za-z0-9_-]+)")


class DuplicateKey(Exception):
    def __init__(self, key, line):
        super().__init__(key)
        self.key = key
        self.line = line


def load_yaml(text, strict=True):
    """Parse workflow YAML. In strict mode a duplicate mapping key is an error."""
    try:
        import yaml
        from yaml.constructor import SafeConstructor
    except ImportError:
        raise SystemExit(
            "workflow-audit: PyYAML is required. The CI audit job installs it; locally "
            "use `python3 -m pip install pyyaml`."
        )
    if not strict:
        return yaml.safe_load(text)

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise DuplicateKey(key, key_node.start_mark.line + 1)
            seen.add(key)
        return SafeConstructor.construct_mapping(loader, node, deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(text, Loader=Loader)


def load(path):
    """Return (document, text, fatal_code, fatal_detail) for one workflow file."""
    text = path.read_text(encoding="utf-8")
    try:
        return load_yaml(text), text, None, None
    except DuplicateKey as exc:
        return None, text, "WF001", "duplicate key %r at line %d" % (exc.key, exc.line)
    except Exception as exc:  # noqa: BLE001 - any parse failure stops the whole pipeline
        return None, text, "WF017", str(exc).replace("\n", " ")[:200]


def needs_list(job):
    needs = job.get("needs")
    if isinstance(needs, str):
        return [needs]
    return list(needs or [])


def matrix_keys(job):
    strategy = job.get("strategy")
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if not isinstance(matrix, dict):
        return set()
    keys = {key for key in matrix if key != "include"}
    for entry in matrix.get("include") or []:
        if isinstance(entry, dict):
            keys.update(entry.keys())
    return keys


def strip_shell_comments(text):
    """Drop comments, so the dialect scan does not read prose as code."""
    kept = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            kept.append("")
            continue
        index, quote = 0, None
        while index < len(line):
            char = line[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in (chr(39), chr(34)):
                quote = char
            elif char == "#" and (index == 0 or line[index - 1] in " \t"):
                line = line[:index]
                break
            index += 1
        kept.append(line)
    return "\n".join(kept)


def audit_shell_dialect(root):
    """Report zsh-only syntax in scripts that no longer run under zsh."""
    findings = []
    scripts = sorted(root.glob("scripts/*.sh")) + sorted(root.glob("Limelight/*.sh")) \
        + sorted((root / ".github").glob("**/*.sh"))
    for script in scripts:
        body = strip_shell_comments(script.read_text(errors="replace"))
        hits = []
        for pattern, label in ZSH_ONLY_SYNTAX:
            for match in re.finditer(pattern, body):
                line = body[:match.start()].count("\n") + 1
                hits.append("line %d: %s (%s)" % (line, label, match.group(0)))
        if hits:
            findings.append(("WF020", str(script.relative_to(root)), "; ".join(sorted(hits))))
    return findings


def audit_script_shebangs(root):
    """Check every shell script the audit job exercises can start on ubuntu."""
    findings = []
    scripts = sorted(root.glob("scripts/*.sh")) + sorted((root / ".github").glob("**/*.sh"))
    for script in scripts:
        first = script.read_text(errors="replace").split("\n", 1)[0].strip()
        if not first.startswith("#!"):
            findings.append(("WF019", str(script.relative_to(root)), "no shebang line at all"))
            continue
        interpreter = first[2:].strip()
        if interpreter.endswith(" bash") or interpreter.endswith(" sh"):
            head, _, argument = interpreter.rpartition(" ")
            interpreter = "%s %s" % (head.strip(), argument) if head else interpreter
        if interpreter not in RUNNER_INTERPRETERS:
            findings.append(("WF019", str(script.relative_to(root)), "shebang %r" % first))
    return findings


def audit_needs_graph(jobs, name):
    graph = {node: [n for n in needs_list(job or {}) if n in jobs] for node, job in jobs.items()}
    state = {}

    def visit(node, trail):
        if state.get(node) == "open":
            return trail + [node]
        if state.get(node) == "done":
            return None
        state[node] = "open"
        for nxt in graph[node]:
            found = visit(nxt, trail + [node])
            if found:
                return found
        state[node] = "done"
        return None

    for node in sorted(graph):
        found = visit(node, [])
        if found:
            return [("WF010", name, "cycle: %s" % " -> ".join(found))]
    return []


def audit_document(doc, name, root=ROOT):
    """Return [(code, location, detail)] for one parsed workflow document."""
    problems = []
    jobs = (doc or {}).get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [("WF002", name, "no `jobs:` mapping was found")]

    for job_name, job in jobs.items():
        loc = "%s job %s" % (name, job_name)
        if not JOB_ID.match(str(job_name)):
            problems.append(("WF006", loc, "job id %r" % job_name))
        if not isinstance(job, dict):
            problems.append(("WF008", loc, "job body is not a mapping"))
            continue
        if not job.get("runs-on"):
            problems.append(("WF007", loc, "missing `runs-on`"))
        if job.get("continue-on-error") is True:
            problems.append(("WF015", loc, "job-level continue-on-error"))

        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            problems.append(("WF008", loc, "missing or empty `steps`"))
            steps = []

        seen_ids = set()
        for index, step in enumerate(steps, 1):
            where = "%s step %d" % (loc, index)
            if not isinstance(step, dict):
                problems.append(("WF003", where, "step is not a mapping"))
                continue
            step_name = str(step.get("name") or "").strip()
            if not step_name:
                problems.append(("WF018", where, "step has no name"))
            if "run" in step and "uses" in step:
                problems.append(("WF004", where, "name %r" % step_name))
            elif "run" not in step and "uses" not in step:
                problems.append(("WF003", where, "name %r" % step_name))
            step_id = step.get("id")
            if step_id:
                if str(step_id) in seen_ids:
                    problems.append(("WF005", where, "id %r" % step_id))
                seen_ids.add(str(step_id))
            if step.get("continue-on-error") is True:
                problems.append(("WF015", where, "name %r" % step_name))

        needs = [n for n in needs_list(job)]
        for need in needs:
            if need not in jobs:
                problems.append(("WF009", loc, "needs %r" % need))

        declared = matrix_keys(job)
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            where = "%s step %d" % (loc, index)
            body = step["run"]
            for match in EXPR_OPEN.finditer(body):
                close = body.find("}}", match.end())
                if close == -1:
                    problems.append(
                        ("WF016", where, "${{ opened at offset %d is never closed: %r"
                         % (match.start(), body[match.start():match.start() + 50].strip()))
                    )
            for match in NEEDS_OUTPUT.finditer(body):
                need, output = match.group(1), match.group(2)
                if need not in needs:
                    problems.append(("WF013", where, "reads %s, which is not in needs" % need))
                elif output not in set(((jobs.get(need) or {}).get("outputs") or {}).keys()):
                    problems.append(("WF011", where, "job %s does not declare output %r" % (need, output)))
            for match in NEEDS_ANY.finditer(body):
                need = match.group(1)
                if need not in needs and need != "outputs":
                    problems.append(("WF013", where, "reads %s, which is not in needs" % need))
            for match in MATRIX_REF.finditer(body):
                if match.group(1) not in declared:
                    problems.append(("WF012", where, "matrix.%s is undefined" % match.group(1)))
            for match in SCRIPT_REF.finditer(body):
                ref = match.group(1)
                if not ref.startswith("./") and "scripts/" not in ref:
                    continue
                relative = ref[2:] if ref.startswith("./") else ref
                candidate = Path(ref) if ref.startswith("/") else root / relative
                if not candidate.exists():
                    problems.append(("WF014", where, "%s is referenced but absent" % ref))

    problems.extend(audit_needs_graph(jobs, name))
    return problems


# --- self test -------------------------------------------------------------
# Each fixture breaks exactly one rule, so a rule that stops working fails here
# instead of failing silently in a pipeline that can no longer start.

GOOD = """
name: good
on: push
jobs:
  audit:
    runs-on: ubuntu-latest
    outputs:
      stamp: ${{ steps.stamp.outputs.stamp }}
    steps:
      - name: Stamp
        id: stamp
        run: echo "stamp=1" >> "$GITHUB_OUTPUT"
  build:
    needs: audit
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - variant: arm64
            archs: arm64
    steps:
      - name: Build ${{ matrix.variant }}
        run: echo "${{ needs.audit.outputs.stamp }} ${{ matrix.archs }}" > /dev/null
"""

FIXTURES = [
    ("WF001", "a second run key hides the first", """
name: dup
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo a
        run: echo b
"""),
    ("WF002", "no jobs at all", """
name: empty
on: push
jobs: {}
"""),
    ("WF003", "a step left with only a name", """
name: nokey
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: Verify something
"""),
    ("WF004", "run and uses together", """
name: both
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: both
        uses: actions/checkout@v6
        run: echo hi
"""),
    ("WF005", "two steps sharing an id", """
name: dupid
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: one
        id: shared
        run: echo 1
      - name: two
        id: shared
        run: echo 2
"""),
    ("WF006", "a job id with a dot", """
name: badid
on: push
jobs:
  "a.b":
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo 1
"""),
    ("WF007", "a job with no runner", """
name: norunner
on: push
jobs:
  a:
    steps:
      - name: one
        run: echo 1
"""),
    ("WF008", "a job with no steps", """
name: nosteps
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps: []
"""),
    ("WF009", "needs a job that is not there", """
name: badneeds
on: push
jobs:
  a:
    needs: ghost
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo 1
"""),
    ("WF010", "two jobs that wait for each other", """
name: cycle
on: push
jobs:
  a:
    needs: b
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo 1
  b:
    needs: a
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo 1
"""),
    ("WF011", "an output nobody declares", """
name: badoutput
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: one
        run: echo 1
  b:
    needs: a
    runs-on: ubuntu-latest
    steps:
      - name: read
        run: echo "${{ needs.a.outputs.missing }}"
"""),
    ("WF012", "a matrix key nobody defines", """
name: badmatrix
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - variant: arm64
    steps:
      - name: build
        run: echo "${{ matrix.plaform }}"
"""),
    ("WF013", "a needs context without needs", """
name: badctx
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: read
        run: echo "${{ needs.other.result }}"
"""),
    ("WF014", "a script that was never committed", """
name: badscript
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: run it
        run: python3 scripts/not-committed.py
"""),
    ("WF015", "a gate allowed to fail", """
name: soft
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: Verify something
        continue-on-error: true
        run: exit 1
"""),
    ("WF016", "an expression that never closes", """
name: openexpr
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: open
        run: echo "value ${{ github.sha
"""),
    ("WF017", "not yaml at all", """
name: broken
  bad indentation here: [
"""),
    ("WF018", "a step nobody can name", """
name: noname
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo 1
"""),
]


def fixture_code(source):
    """Return the first rule code a fixture trips, or None when nothing trips."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "build.yml"
        path.write_text(source, encoding="utf-8")
        doc, _, fatal, _ = load(path)
        if fatal:
            return [fatal]
        codes = {code for code, _, _ in audit_document(doc, path.name, root=Path(tmp))}
        return sorted(codes) if codes else []


PRESENT_SCRIPTS = """
name: present
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: Run committed scripts
        run: |
          python3 scripts/committed.py
          ./.github/scripts/also_committed.py
          bash scripts/committed.sh
"""


def present_script_control():
    """A workflow that points at committed scripts must report nothing.

    Without this control, a bug in path handling shows up as a passing audit that
    would fail every real run, which is the failure mode this script exists to
    prevent.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / ".github" / "scripts").mkdir(parents=True)
        (root / "scripts" / "committed.py").write_text("#\n", encoding="utf-8")
        (root / "scripts" / "committed.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        (root / ".github" / "scripts" / "also_committed.py").write_text("#\n", encoding="utf-8")
        return audit_document(load_yaml(PRESENT_SCRIPTS), "present.yml", root=root)


def shebang_controls():
    """The shebang rule needs both a passing and a failing tree to be believed."""
    findings = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / "portable.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
        (root / "scripts" / "posix.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        clean = audit_script_shebangs(root)
        if clean:
            findings.append("the portable-script control reports %s" % (clean,))
        (root / "scripts" / "mac_only.sh").write_text("#!/bin/zsh\necho ok\n", encoding="utf-8")
        found = audit_script_shebangs(root)
        if [code for code, where, _ in found] != ["WF019"] or found[0][1] != "scripts/mac_only.sh":
            findings.append("the zsh control reports %s, expected one WF019 naming mac_only.sh" % (found,))
        (root / "scripts" / "mac_only.sh").unlink()
        (root / "scripts" / "bare.sh").write_text("echo ok\n", encoding="utf-8")
        missing = audit_script_shebangs(root)
        if [code for code, where, _ in missing] != ["WF019"] or missing[0][1] != "scripts/bare.sh":
            findings.append("the missing-shebang control reports %s" % (missing,))
    return findings


def dialect_controls():
    """The dialect scan must catch the zsh forms and forgive the bash lookalikes."""
    findings = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / "bash_idioms.sh").write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "value=\"${DEF:-fallback}\"      # default, not a modifier\n"
            "tail=\"${value##*/}\"            # strip prefix, not a modifier\n"
            "part=\"${value:2:3}\"             # substring, not a modifier\n"
            "echo \"$value $tail $part\"      # bash splits this on its own\n"
            "# a note about ${=ARCHS} is prose, not code" + "\n",
            encoding="utf-8")
        clean = audit_shell_dialect(root)
        if clean:
            findings.append("the bash idiom control reports %s" % (clean,))
        (root / "scripts" / "zsh_left_behind.sh").write_text(
            "#!/usr/bin/env bash\n"
            "setopt extended_glob\n"
            "for arch in ${=ARCHS}; do echo \"$arch\"; done\n",
            encoding="utf-8")
        found = audit_shell_dialect(root)
        codes = {code for code, _, _ in found}
        if codes != {"WF020"} or "zsh_left_behind.sh" not in found[0][1]:
            findings.append("the zsh control reports %s" % (found,))
        else:
            detail = found[0][2]
            if "forced word splitting" not in detail or "zsh-only builtin" not in detail:
                findings.append("the zsh control names only %s" % detail)
    return findings


def self_test():
    failures = []
    present = present_script_control()
    if present:
        failures.append("the committed-script control reports %s" % (present,))
    failures.extend(shebang_controls())
    failures.extend(dialect_controls())
    good = audit_document(load_yaml(GOOD), "good.yml")
    if good:
        failures.append("the good fixture reports %s" % (good,))
    for code, label, source in FIXTURES:
        found = fixture_code(source)
        # One fixture, one rule: a fixture that trips two rules makes the pair
        # untestable, because silencing either rule would hide the other.
        if found != [code]:
            failures.append("fixture %r expected only %s, got %s" % (label, code, found or "nothing"))
    for line in failures:
        print("SELF TEST FAIL: %s" % line)
    if failures:
        return 1
    print(
        "workflow-audit self test: %d rules, each broken by a fixture or control and named correctly"
        % len(RULES)
    )
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    paths = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not paths:
        print("workflow-audit: no workflow files under %s" % WORKFLOW_DIR)
        return 1
    problems = []
    for path in paths:
        doc, _, fatal, detail = load(path)
        if fatal:
            problems.append((fatal, path.name, detail))
            continue
        problems.extend(audit_document(doc, path.name))
    problems.extend(audit_script_shebangs(ROOT))
    problems.extend(audit_shell_dialect(ROOT))
    if problems:
        for code, where, detail in sorted(problems):
            print("%s: %s: %s  [%s]" % (code, where, detail, RULES[code]))
        print("workflow-audit: %d problem(s)" % len(problems))
        return 1
    print("workflow-audit: %d workflow file(s) pass %d rules" % (len(paths), len(RULES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
