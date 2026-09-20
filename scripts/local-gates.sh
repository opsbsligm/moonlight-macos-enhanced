#!/bin/bash
# Run the CI gate list on this machine, and say plainly which parts it cannot run.
#
# The failure this exists to prevent is a green local sweep next to a red build: the
# tree carries more than forty gates, and a hand-picked half dozen of them proved
# nothing about the rest. The list therefore comes from the workflow itself, so a gate
# added to CI is run here the next time this script is called, instead of depending on
# someone remembering which gates they usually run.
#
# Gates that consume a CI artefact -- an xcodebuild log, derived data, a built .app --
# cannot run without the artefact, so they are counted and named rather than faked or
# skipped in silence. Pass --all to run the full constraint battery (it plants defects
# one at a time and takes minutes rather than seconds); without it that gate runs in
# its quick mode.
set -u
cd "$(dirname "$0")/.." || exit 2

workflow=".github/workflows/build.yml"
[ -f "$workflow" ] || { echo "no $workflow" >&2; exit 2; }

all=0
[ "${1:-}" = "--all" ] && all=1
# One command per line, deduplicated. A step whose command is folded across lines with
# a trailing backslash has to be unfolded first: cutting it at the fold is how this
# script once reported "dmg-audit.py: error: nothing to check" for a step that had been
# passing its flags on the next line, and a gate invoked wrongly reports a failure that
# is not in the tree.
unfold() {
  awk '{
    line = $0
    while (line ~ /\\[ 	]*$/ && (getline nxt) > 0) {
      sub(/\\[ 	]*$/, " ", line)
      gsub(/^[ 	]+/, "", nxt)
      line = line nxt
    }
    print line
  }' "$workflow"
}

gate_commands() {
  unfold | grep -o "python3 scripts/[a-zA-Z0-9_.-]*[.]py.*" \
         | sed 's/[[:space:]]*$//' | sort -u
}

[ "${1:-}" = "--list" ] && { gate_commands; exit 0; }
gate_commands > /tmp/local-gates.list

passed=0 failed=0 skipped=0
: > /tmp/local-gates.failed

while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  case "$cmd" in
    # Gates pointed at runner scratch take a mode that stands on its own, so drop the
    # scratch and run the gate: --derived and --log are where they read a build, and
    # each has a self-contained invocation besides.
    *--derived*|*--log*)
      cmd=$(printf '%s' "$cmd" | sed -e 's/ --derived.*//' -e 's/ --log.*//');;
    # Anything else still holding a variable wants a value only the runner computes --
    # a tag name, a matrix arch, a build number this checkout does not carry. Running
    # it with an empty value would report a failure the tree does not have, which is
    # the one thing a local sweep must never do.
    *'$'*)
      echo "skip  $cmd (needs a value only CI computes)"; skipped=$((skipped+1)); continue;;
  esac
  case "$cmd" in
    *analyzer-audit*|*compiled-source-audit*|*launch-code-audit*|*render-probe*)
      echo "skip  $cmd (needs a CI build artefact)"; skipped=$((skipped+1)); continue;;
    *constraints-audit.py*)
      [ "$all" = 1 ] || cmd="$cmd --no-battery";;
  esac
  out=$(eval "$cmd" 2>&1)
  if [ $? -eq 0 ]; then
    passed=$((passed+1))
  else
    failed=$((failed+1))
    echo "FAIL  $cmd" | tee -a /tmp/local-gates.failed
    printf '%s\n' "$out" | grep -E 'FAIL|error:|rror' | tail -3 | sed 's/^/      /'
  fi
done < /tmp/local-gates.list

echo "$passed gates passed, $failed failed, $skipped need a CI artefact"
[ "$failed" -eq 0 ]
