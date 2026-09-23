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

# The list is the whole point of this script, so the list gets checked before any gate
# runs. Both ways it can come up short are shapes this script has already shown: a call
# the unfold left folded, because its flags went to the next line and the pattern
# stopped at the backslash, and a call written in a shape the pattern does not know --
# a quoted path, a variable, a wrapper -- which never matches at all. A runner that
# quietly drops a gate is exactly how a green sweep and a red build coexist.
check_the_list() {
  local raw found folded
  raw=$(unfold | grep -c 'python3 ["'"'"']\?scripts/')
  found=$(gate_commands | wc -l | tr -d ' ')
  folded=$(gate_commands | grep -c '\\$')
  if [ "$folded" -ne 0 ]; then
    echo "list error: $folded of $found commands are still folded" >&2
    return 1
  fi
  if [ "$raw" -ne "$found" ]; then
    echo "list error: the workflow calls a script $raw times, the list holds $found" >&2
    return 1
  fi
}

if [ "${1:-}" = "--self-test" ]; then
  workflow=$(mktemp); trap 'rm -f "$workflow"' EXIT
  # A call with its flags on the next line unfolds into one entry; a quoted call is a
  # second call the pattern does not know, so the two together must be reported.
  {
    printf 'run: python3 scripts/one-tests.py\n'
    printf '        python3 scripts/two-tests.py \\\n'
    printf '          --tag v1\n'
    printf 'run: python3 "scripts/three-tests.py"\n'
  } > "$workflow"
  if check_the_list >/dev/null 2>&1; then
    echo "self-test failed: an unfolder that loses a quoted call still passed" >&2
    exit 1
  fi
  {
    printf 'run: python3 scripts/one-tests.py\n'
    printf '        python3 scripts/two-tests.py \\\n'
    printf '          --tag v1\n'
  } > "$workflow"
  if ! check_the_list; then
    echo "self-test failed: a list with nothing missing was refused" >&2
    exit 1
  fi
  echo "self-test ok: the list notices a call it cannot read, and accepts one it can"
  exit 0
fi


[ "${1:-}" = "--list" ] && { gate_commands; exit 0; }
check_the_list || exit 2
gate_commands > /tmp/local-gates.list

# CI reads the bundle name into the job environment before it writes a path; the sweep has
# to do the same, or a gate whose path contains ${APP_NAME} is excused here as "a value only
# CI computes" when in truth only the built bundle is missing -- and an excuse that names the
# wrong reason is how a gate stops being looked at.
app_name=$(./scripts/product-name.sh 2>/dev/null || echo "")

# Which artefact gates can be run honestly on this checkout, and what they need.
#
# Empty means no: the gate reads something only CI produces, and running it with an empty path
# would report a failure the tree does not have. Three answers below are verified claims about a
# laptop, not hopes: compile-audit is measured at 56 of 56 sources with no flag, swift-typecheck
# needs one generated-header root from a build that has happened here, and the warning audit needs
# the transcript of the build you just ran, because a log from last week would certify a tree it
# never saw.
artefact_command() {
  case "$1" in
    *compile-audit.py*)
      printf '%s' "$1" | sed 's/ --derived.*//';;
    *swift-typecheck.py*)
      # The generated header is per configuration, and which one exists is decided by
      # how this checkout was last built: a laptop building Release and CI's analyze job
      # running Debug are the same project with different paths. Probing one of the two
      # skipped the gate for whoever built the other way, which is the silence this
      # function exists to remove.
      for root in build-analyze build-header-check build build-probe; do
        for configuration in Release Debug; do
          derived="$root/Build/Intermediates.noindex/Moonlight.build/$configuration/Moonlight for macOS.build/DerivedSources"
          [ -d "$derived" ] && {
            printf 'python3 scripts/swift-typecheck.py . --derived "%s"' "$derived"; return; }
        done
      done;;
    *source-membership-audit.py*)
      # The transcript is the only authority that can say whether a file was compiled.
      # LOCAL_BUILD_LOG is this checkout's transcript -- the same one the warning gate
      # reads -- and without it the audit says so instead of guessing from a project
      # file whose membership metadata belongs to no target.
      if [ -n "${LOCAL_BUILD_LOG:-}" ] && [ -f "${LOCAL_BUILD_LOG}" ]; then
        printf 'python3 scripts/source-membership-audit.py --build-log "%s"' "${LOCAL_BUILD_LOG}"
      else
        printf ''
      fi;;
    *build-warning-audit.py*)
      # LOCAL_BUILD_LOG is the transcript of this checkout's own build, on purpose: the point of
      # the gate is the warning in the compiler's words, and only the build you just ran has a
      # right to certify the source you just changed.
      if [ -n "${LOCAL_BUILD_LOG:-}" ] && [ -f "${LOCAL_BUILD_LOG}" ]; then
        printf 'python3 scripts/build-warning-audit.py --log "%s"' "${LOCAL_BUILD_LOG}"
      fi;;
  esac
  printf ''
}

passed=0 failed=0 skipped=0
: > /tmp/local-gates.failed

while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  # sed rather than a bash pattern substitution: `${APP_NAME}` inside `${cmd//...}` is the
  # kind of nesting that quietly rewrites the wrong part of a command line.
  [ -n "$app_name" ] && cmd=$(printf '%s' "$cmd" | sed "s/\${APP_NAME}/$app_name/g")
  case "$cmd" in
    # A gate handed no artefact is not a gate that passed, and the old shape did exactly that:
    # it cut --derived and --log off the command line, ran what was left, and counted the exit
    # code, so a gate that had printed "nothing to check" and exited zero arrived as a pass. Two
    # of them sat in that count while a build log carrying a first-party warning swept green --
    # the pairing this script's header says it exists to prevent. Dropping the flag outright is
    # the other mistake, and costs coverage: compile-audit type-checks all 56 macOS sources from
    # this checkout with no flag at all. So each artefact gate is asked whether it can stand on
    # its own here, and the answer is written down below with its reason rather than inferred.
    *--derived*|*--log*|*--build-log*)
      local_cmd=$(artefact_command "$cmd")
      if [ -z "$local_cmd" ]; then
        echo "skip  $cmd (needs a build artefact this sweep was not given: see artefact_command)"
        skipped=$((skipped+1)); continue
      fi
      cmd="$local_cmd";;
    # Anything else still holding a variable wants a value only the runner computes --
    # a tag name, a matrix arch, a build number this checkout does not carry. Running
    # it with an empty value would report a failure the tree does not have, which is
    # the one thing a local sweep must never do.
    *'$'*)
      echo "skip  $cmd (needs a value only CI computes)"; skipped=$((skipped+1)); continue;;
  esac
  case "$cmd" in
    *render-probe*)
      # Filing this one in with the gates that need a runner was a small lie with a
      # twenty-minute price: the script builds its own Debug binary and measures the page
      # inside the app, so a laptop can run it -- it is slow, not impossible. Say which.
      echo "skip  $cmd (runnable here: python3 scripts/render-probe.py builds its own Debug binary, about twenty minutes)"
      skipped=$((skipped+1)); continue;;
    *analyzer-audit*|*compiled-source-audit*|*launch-code-audit*)
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
