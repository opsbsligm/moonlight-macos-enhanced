#!/bin/bash
# Run the CI gate list on this machine, and say plainly which parts it cannot run.
#
# The failure this exists to prevent is a green local sweep next to a red build: the
# tree carries more than forty gates, and a hand-picked half dozen of them proved
# nothing about the rest. The list therefore comes from the pipeline definitions
# themselves, so a gate added to CI is run here the next time this script is called,
# instead of depending on someone remembering which gates they usually run.
#
# Both definitions are read, because the repository carries two: `.gitlab-ci.yml` is
# the source of truth and `.github/workflows/build.yml` is the image GitHub sees. When
# the list came only from the mirror, a gate that reached the source of truth and not
# the image was invisible to this sweep, so a local green said nothing about the
# authority that actually decides whether a merge request ships.
#
# Where both files call the same script, the mirror's form wins: `artefact_command`
# below knows how to rewrite those commands for a laptop, while the source of truth
# spells artefact paths in CI variables (`$app`, `$DERIVED_DATA_PATH`) that resolve to
# nothing here. A gate only the source of truth calls is still run, as written.
#
# Gates that consume a CI artefact -- an xcodebuild log, derived data, a built .app --
# cannot run without the artefact, so they are counted and named rather than faked or
# skipped in silence. Pass --all to run the full constraint battery (it plants defects
# one at a time and takes minutes rather than seconds); without it that gate runs in
# its quick mode.
set -u
cd "$(dirname "$0")/.." || exit 2

mirror_workflow=".github/workflows/build.yml"
truth_workflow=".gitlab-ci.yml"
for known in "$mirror_workflow" "$truth_workflow"; do
  [ -f "$known" ] || { echo "no $known" >&2; exit 2; }
done

all=0
[ "${1:-}" = "--all" ] && all=1

skip_full_battery() {
  case "$1" in
    *assertion-battery.py*) [ "$all" != 1 ];;
    *) return 1;;
  esac
}
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
  }' "$@"
}

# Scripts a definition calls that are not gates: they change something outside the
# checkout instead of judging it. `scripts/ci/publish-github.py` pushes refs to the
# GitHub mirror, so a local sweep must never run it -- and it cannot be left out by
# accident, because its call line is `MIRROR_DRY_RUN=1 python3 scripts/ci/publish-github.py`
# and a pattern that cuts from the interpreter loses the prefix that made it a dry run.
# Naming it here rather than filtering on path shape is deliberate: a real gate that
# lands under `scripts/ci/` still has to reach the list.
non_gate_scripts=" scripts/ci/publish-github.py "

# Cut the gate command out of an unfolded line.
#
# Matching from the interpreter, not from the path, is what keeps a prose mention of
# `scripts/build-warning-audit.py` in a comment out of the list. `python3?` is not a
# stylistic choice: the source of truth builds a venv and then calls its gates as
# `python scripts/x.py`, so a pattern that knew only `python3` hid every gate the
# authority runs on its own -- 15 calls, and the exact silence this sweep exists to
# remove, reintroduced by the discovery pattern itself. Nested paths count too, because
# `scripts/ci/test_pipeline.py` is the pipeline's own contract test and was invisible to
# the old flat pattern.
#
# The origin marker is attached per file, after the cut. Attaching it to the raw line and
# then anchoring the pattern at the start of the line matches nothing at all -- a call in
# a definition is indented and usually carries a YAML list marker -- and a sweep with an
# empty list reports "0 gates failed" in the same voice a green sweep uses.
discover() {
  unfold "$1" | sed -nE 's|.*(python3? scripts/[A-Za-z0-9_./-]*\.py.*)$|\1|p' \
              | sed 's/[[:space:]]*$//'
}

# The list with its origin still attached: `M` for a command the mirror calls, `T` for one
# only the source of truth calls. The marker has to survive as far as the representation
# check, because the list chooses one form per script and a count taken from that choice can
# no longer say which definition a command came from.
#
# Deduplication is across definitions, never within one. The mirror calls some gates twice,
# once bare and once with `--self-test`, and those are two claims about two behaviours: an
# earlier version of this function folded them into one entry and the sweep quietly halved
# its own coverage. What is dropped is the source of truth's form of a script the mirror
# also calls, because `artefact_command` below knows how to make the mirror's form runnable
# here while the source of truth spells its artefact paths in CI variables.
gate_entries() {
  local entry side known
  for entry in "M $mirror_workflow" "T $truth_workflow"; do
    side=${entry%% *}; known=${entry#* }
    discover "$known" | sed "s/^/$side /"
  done | sort -u | awk -v excluded="$non_gate_scripts" '
    { n++; line[n] = $0
      cmd = substr($0, 3)
      script = cmd; sub(/^python3? ?["'"'"']?/, "", script); sub(/[[:space:]].*$/, "", script)
      which[n] = script
      if (substr($0, 1, 1) == "M" && index(excluded, " " script " ") == 0) mirrored[script] = 1 }
    END {
      for (i = 1; i <= n; i++) {
        script = which[i]
        # Said out loud: a sweep that silently grew shorter is the failure this script
        # exists to prevent, even when the reason is a legitimate one.
        if (index(excluded, " " script " ") > 0) {
          if (!(script in named)) { named[script] = 1
            print "note    not a gate, excluded: " script > "/dev/stderr" }
          continue }
        if (substr(line[i], 1, 1) == "T" && (script in mirrored)) continue
        print line[i]
      }
    }'
}

gate_commands() {
  gate_entries | sed 's/^[MT] //' | expand_emitters
}

# One definition may ask a script for the gate list at run time instead of writing the
# gates out. The coverage audit is wired that way -- a job asks it for one class and runs
# what comes back -- so the sweep has to run the answer, not the request: running
# `--emit-commands` on its own would report a green sweep over 47 gates it never touched.
#
# When the expansion yields nothing the request stays in the list as written. A sweep that
# quietly expanded to zero lines is the same silence this script was written to end, and an
# unexpanded request fails in its own voice, which is louder than an empty pass.
expand_emitters() {
  local line class emitted
  while IFS= read -r line; do
    case "$line" in
      *"gate-coverage-audit.py --emit-commands --class="*)
        class=${line##*--class=}
        class=${class%%[[:space:]]*}
        if emitted=$(python3 scripts/gate-coverage-audit.py --emit-commands \
                       --class="$class" 2>/dev/null) && [ -n "$emitted" ]; then
          printf '%s\n' "$emitted"
        else
          printf '%s\n' "$line"
        fi ;;
      *) printf '%s\n' "$line" ;;
    esac
  done
}

# The list is the whole point of this script, so the list gets checked before any gate
# runs. The rule is containment, per definition: every call the file makes has to have a
# representative in the list -- either itself, or the mirror's form of the same script,
# which is the form the sweep chose to run (see the header).
#
# Containment rather than a count equality, because the list deduplicates: a definition
# that calls one gate twice, once bare and once with a flag, is two calls and one entry,
# and an equality would report that as a dropped gate every time. What equality could not
# see is the shape that does matter -- a call the discovery pattern does not know, so it
# never reaches the list at all. Two such shapes have already happened here: a quoted path,
# and an interpreter written as a full path, where the loose pattern sees `python3
# scripts/x.py` inside the line and the strict pattern refuses it because of the prefix.
# A runner that quietly drops a gate is exactly how a green sweep and a red build coexist,
# and the check is per file so a mirror and a source of truth cannot cancel each other out.
# Every gate call a definition makes, in whatever shape it is written. Deliberately
# looser than the discovery pattern: an interpreter reached through a full path still
# contains `python3 scripts/x.py`, and a path wrapped in quotes still runs. The looseness
# is what makes the check worth having -- it is the difference between "this call is not
# in the list" and "this call was never looked at".
calls_in() {
  unfold "$1" | grep -oE "python3? [\"']?scripts/[a-zA-Z0-9_.-]*[.]py.*" \
               | sed 's/[[:space:]]*$//' | sort -u
}

# $1 = side marker, $2 = definition file. A call is represented when the list carries it
# itself, or -- for the source of truth only -- when the list carries the mirror's form of
# the same script. The substitution is not offered to the mirror's own calls: that side is
# where a command has to appear as written, or the sweep would be claiming to run a
# command it silently rewrote.
unrepresented_calls() {
  local side="$1" known="$2"
  awk -v side="$side" '
    NR == FNR {
      entry_side = substr($0, 1, 1); cmd = substr($0, 3)
      exact[entry_side " " cmd] = 1
      script = cmd; sub(/^python3? /, "", script); sub(/[[:space:]].*$/, "", script)
      if (entry_side == "M") mirrored[script] = 1
      next
    }
    { cmd = $0; script = cmd
      sub(/^python3? ?["'"'"']?/, "", script); sub(/[[:space:]].*$/, "", script)
      # The loose pattern swallows the closing quote of `python3 "scripts/x.py"`, and a
      # script name carrying it matches nothing, so a quoted call could never be
      # represented no matter what the list held. Dropping the quote is what makes the
      # substitution above testable rather than permanently false.
      sub(/[^A-Za-z0-9_.\/[-]+$/, "", script)
      if ((side " " cmd) in exact) next
      if (side == "T" && (script in mirrored)) next
      bad++ }
    END { print bad + 0 }' <(gate_entries) <(calls_in "$known")
}

check_the_list() {
  local folded known side unmatched file
  folded=$(gate_commands | grep -c '\\$')
  if [ "$folded" -ne 0 ]; then
    echo "list error: $folded commands are still folded" >&2
    return 1
  fi
  for known in "$mirror_workflow" "$truth_workflow"; do
    side=$( [ "$known" = "$mirror_workflow" ] && echo M || echo T )
    unmatched=$(unrepresented_calls "$side" "$known")
    if [ "$unmatched" -ne 0 ]; then
      echo "list error: $known makes $unmatched gate call(s) the list does not represent" >&2
      return 1
    fi
  done
}

if [ "${1:-}" = "--self-test" ]; then
  sandbox=$(mktemp -d); trap 'rm -rf "$sandbox"' EXIT
  # The discovery helpers read the two real definitions, so a self-test that wants to
  # hand them a shape points both names at throwaway files. Naming both, rather than
  # only the mirror, is the point: a list built from one file cannot show what the
  # other file contributes.
  mirror_workflow="$sandbox/mirror.yml"; truth_workflow="$sandbox/truth.yml"
  # A call with its flags on the next line unfolds into one entry; a quoted call is a
  # second call the pattern does not know, so the two together must be reported.
  {
    printf 'run: python3 scripts/one-tests.py\n'
    printf '        python3 scripts/two-tests.py \\\n'
    printf '          --tag v1\n'
    printf 'run: python3 "scripts/three-tests.py"\n'
  } > "$mirror_workflow"
  printf '  - python3 scripts/four-tests.py\n' > "$truth_workflow"
  if check_the_list >/dev/null 2>&1; then
    echo "self-test failed: an unfolder that loses a quoted call still passed" >&2
    exit 1
  fi
  {
    printf 'run: python3 scripts/one-tests.py\n'
    printf '        python3 scripts/two-tests.py \\\n'
    printf '          --tag v1\n'
  } > "$mirror_workflow"
  if ! check_the_list; then
    echo "self-test failed: a list with nothing missing was refused" >&2
    exit 1
  fi
  # The union has to be the union. A gate only the mirror calls, a gate only the
  # source of truth calls, and a gate both call must all reach the list, and the form
  # kept for a gate both call has to be the mirror's -- the source of truth spells its
  # artefact paths in CI variables that resolve to nothing on a laptop.
  {
    printf 'run: python3 scripts/mirror-only-tests.py\n'
    printf 'run: python3 scripts/shared-tests.py --self-test\n'
  } > "$mirror_workflow"
  {
    printf '  - python3 scripts/truth-only-tests.py\n'
    # The same gate with the CI-only artefact flag the mirror form does not carry.
    printf '  - python3 scripts/shared-tests.py --self-test --log "$build.log"\n'
  } > "$truth_workflow"
  list=$(gate_commands)
  for wanted in mirror-only-tests truth-only-tests; do
    printf '%s\n' "$list" | grep -q "scripts/$wanted.py" || {
      echo "self-test failed: a gate only one definition calls never reached the list" >&2
      exit 1; }
  done
  if [ "$(printf '%s\n' "$list" | grep -c 'scripts/shared-tests.py')" -ne 1 ] ||
     printf '%s\n' "$list" | grep 'scripts/shared-tests.py' | grep -q -- '--log'; then
    echo "self-test failed: a gate both definitions call was duplicated, or the CI-only" \
         "artefact form won over the mirror form" >&2
    exit 1
  fi
  # The substitution that lets one definition's call be represented by the other's form is
  # offered to the source of truth only. Here the mirror writes a gate in a shape discovery
  # never sees while the source of truth writes the same gate plainly: a check that asked
  # only "is this script somewhere in the list?" would pass, and the sweep would then run a
  # command other than the one the image defines.
  printf 'run: python3 "scripts/shared-tests.py"\n' > "$mirror_workflow"
  printf '  - python3 scripts/shared-tests.py\n' > "$truth_workflow"
  if check_the_list >/dev/null 2>&1; then
    echo "self-test failed: the mirror's own call was let through by the substitution meant" \
         "for the source of truth" >&2
    exit 1
  fi
  # The same pair the other way round is legal, so the failure above has to come from the
  # asymmetry and not from the quoted shape on its own.
  printf 'run: python3 scripts/shared-tests.py\n' > "$mirror_workflow"
  {
    printf '  - python3 scripts/shared-tests.py\n'
    printf '  - python3 "scripts/shared-tests.py"\n'
  } > "$truth_workflow"
  if ! check_the_list; then
    echo "self-test failed: the source of truth was refused for a call its mirror represents" >&2
    exit 1
  fi
  if ! skip_full_battery "python3 scripts/assertion-battery.py" ||
     skip_full_battery "python3 scripts/diagnostics-report-tests.py"; then
    echo "self-test failed: quick mode must skip only the full mutation battery" >&2
    exit 1
  fi
  all=1
  if skip_full_battery "python3 scripts/assertion-battery.py"; then
    echo "self-test failed: --all must run the full mutation battery" >&2
    exit 1
  fi
  echo "self-test ok: union command discovery, per-file list counts and quick/full battery selection"
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
# laptop, not hopes: compile-audit is measured at 82 of 82 sources with no flag -- macOS,
# Stream, Network, Database, Crypto, Utility and the one source at the top of Limelight/ --
# swift-typecheck needs one generated-header root from a build that has happened here,
# and the warning audit needs
# the transcript of the build you just ran, because a log from last week would certify a tree it
# never saw.
artefact_command() {
  case "$1" in
    *leak-audit.py*--red-team*)
      # The flag says --log, but the report it names lives in this tree, so the CI form
      # of this command is the local form: no build artefact is involved and nothing here
      # needs rewriting. It is spelled out rather than left to fall through, because a
      # red team that quietly skipped is the same silence as a red team that quietly
      # passed, and it is the only thing that says the leak reader still reads.
      printf '%s' "$1";;
    *compile-audit.py*)
      printf '%s' "$1" | sed 's/ --derived.*//';;
    *swift-typecheck.py*)
      # The generated header is per configuration, and which one exists is decided by
      # how this checkout was last built: a laptop building Release and CI's analyze job
      # running Debug are the same project with different paths. Probing one of the two
      # skipped the gate for whoever built the other way, which is the silence this
      # function exists to remove.
      for root in build/xcode/derivedData build-analyze build-header-check build build-probe; do
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
  if skip_full_battery "$cmd"; then
    echo "skip  $cmd (complete mutation battery; run this sweep with --all)"
    skipped=$((skipped+1)); continue
  fi
  # sed rather than a bash pattern substitution: `${APP_NAME}` inside `${cmd//...}` is the
  # kind of nesting that quietly rewrites the wrong part of a command line.
  [ -n "$app_name" ] && cmd=$(printf '%s' "$cmd" | sed "s/\${APP_NAME}/$app_name/g")
  # The source of truth runs its python gates inside a venv it activates a few lines
  # above them, so `python scripts/ci/test_pipeline.py` is a real command there and a
  # missing binary here -- macOS ships `python3`, and a sweep that reported `command not
  # found` would be a red the tree does not have. Anchored to the start of the line, so
  # `python3` and any argument that spells the word are left alone; the interpreter is
  # the only thing rewritten, never a flag or a path.
  cmd=$(printf '%s' "$cmd" | sed 's/^python /python3 /')
  case "$cmd" in
    # A gate handed no artefact is not a gate that passed, and the old shape did exactly that:
    # it cut --derived and --log off the command line, ran what was left, and counted the exit
    # code, so a gate that had printed "nothing to check" and exited zero arrived as a pass. Two
    # of them sat in that count while a build log carrying a first-party warning swept green --
    # the pairing this script's header says it exists to prevent. Dropping the flag outright is
    # the other mistake, and costs coverage: compile-audit type-checks all 82 first-party sources from
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
    *ci/test_pipeline.py*)
      # The source of truth installs PyYAML into the venv it builds for this job, so the
      # import is guaranteed there and not here. A missing third-party module is the host
      # being unprepared, not the tree being wrong, so the line names the install rather
      # than reporting a failure -- and it stays a skip with a remedy, not a pass, because
      # this is the one gate that loads `.gitlab-ci.yml` with the parser GitLab itself
      # uses, which is what says a CI edit can be pre-checked before a runner sees it.
      if ! python3 -c "import yaml" >/dev/null 2>&1; then
        echo "skip  $cmd (wants PyYAML, which CI installs into its venv; run \`python3 -m pip install pyyaml\` to gate CI definitions locally)"
        skipped=$((skipped+1)); continue
      fi;;
    *leak-audit.py*)
      # Two of its three shapes run anywhere: the fixtures and the red team judge a report
      # that lives in this tree. The third drives the app under Apple's `leaks`, so it
      # wants the Debug product render-probe.py leaves behind -- which this sweep does not
      # build (that build is the twenty-minute price) but has no need to rebuild either.
      # So the question goes to the disk instead of being written down as a permanent
      # excuse: with the product on disk the sweep runs here -- about forty seconds of setup per
      # sweep plus the visits themselves, and `--growth` asks for two of them (a one-visit sweep
      # and a sixteen-visit sweep, because fifteen extra visits is the shortest window the graph
      # rule will judge: the leaked count is a snapshot, and over five visits six sweeps of
      # unchanged code spread the difference 3 to 6 graphs where the reads entitled 5). Expect
      # the line to take the better part of ten minutes on a laptop, which is what a memory
      # measurement costs when the alternative is a rule that refuses correct code. Without the
      # product the line says which of the two is missing.
      case "$cmd" in
        *--self-test*|*--red-team*|*--log*) ;;
        *)
          if ! compgen -G "build-render-probe/Build/Products/Debug/*.app" > /dev/null; then
            echo "skip  $cmd (wants the Debug product render-probe.py builds; once it is on disk this gate runs here in about forty seconds)"
            skipped=$((skipped+1)); continue
          fi;;
      esac;;
    *ownership-audit.py*)
      # Two of its three shapes run anywhere: the fixtures judge refusals that no laptop can
      # summon on demand, and the red team mutates a record a real app wrote -- the record lives
      # in this tree, so the claim it tests is the same claim CI makes. The third asks the built
      # app who is holding what, which needs the Debug product and about two seconds of running
      # it. The product is on disk or it is not, and the line says which rather than carrying a
      # permanent excuse the way this script's first version did for the render probe.
      case "$cmd" in
        *--self-test*|*--red-team*) ;;
        *)
          if ! compgen -G "build-render-probe/Build/Products/Debug/*.app" > /dev/null; then
            echo "skip  $cmd (wants the Debug product render-probe.py builds; once it is on disk this gate runs here in about two seconds)"
            skipped=$((skipped+1)); continue
          fi;;
      esac;;
    *constraints-audit.py*)
      [ "$all" = 1 ] || cmd="$cmd --no-battery";;
  esac
  printf 'run  %s\n' "$cmd"
  out=$(eval "$cmd" 2>&1)
  if [ $? -eq 0 ]; then
    passed=$((passed+1))
  else
    failed=$((failed+1))
    echo "FAIL  $cmd" | tee -a /tmp/local-gates.failed
    printf '%s\n' "$out" | grep -E 'FAIL|error:|rror' | tail -3 | sed 's/^/      /'
  fi
done < /tmp/local-gates.list

if [ "$skipped" -eq 0 ]; then
  echo "$passed gates passed, $failed failed"
else
  echo "$passed gates passed, $failed failed, $skipped skipped (reasons printed above)"
fi
[ "$failed" -eq 0 ]
