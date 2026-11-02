#!/bin/bash
# One bootstrap for the two jobs that need a parser: `audit:python` and
# `mutation-battery`. Both previously spelled `python3 -m venv` plus a
# `pip install pyyaml==6.0.2` inline, and both then trusted pip's exit code as
# proof that the audits could run.
#
# Why a script and not two inline blocks: on 2026-11-02 the eight-day-old
# failure on `9e914350`, and the first failure of this branch, were both
# `pip install` dying with `SSLEOFError` against pypi.org -- measured on the
# runner itself, with github.com and bing.com failing the same handshake at the
# same moment, so the route was down rather than the package being missing.
# Two jobs that cannot install the one module every workflow audit imports
# reported "job failed" and nothing about what was actually lost. The fallback
# index below was measured from the same shell: mirrors.aliyun.com answers 200
# and installs the identical pin while pypi.org is unreachable.
#
# pypi.org stays the primary on purpose. The mirror is only consulted after the
# primary has already failed, so a healthy network still resolves the pin from
# the canonical index and the fallback is a route, not a preference.
#
# Usage: . scripts/ci/bootstrap-python.sh <venv-dir>          -- note the dot
# Exits non-zero, loudly, if the parser is not importable afterwards.
#
# Sourced, not run. Pipeline 1025 is why: the job called `bash` on this file, the
# `activate` below ran inside that child process, and the job's own shell never
# learned the virtualenv existed -- the very next line reported
# `python: command not found` with the parser installed one directory away. That
# is worse than the inline block this replaced, because it also gets to announce
# that the pin installed first.
#
# No `set -e` / `set -u` here on purpose: this file is sourced into a job that
# already chose its own options, and a helper that silently widens or narrows them
# for the remaining 60 audit commands is its own class of surprise. Every failure
# path below is an explicit `|| { ...; exit 1; }` for the same reason. `exit` in a
# sourced file ends the job shell, which is exactly the intent.
#
# And it refuses to be executed, before it does any work. Without this the child
# process activates perfectly well, prints its success line, and exits 0 -- so the
# one call shape that cannot work is also the one shape that reports nothing wrong,
# and the failure surfaces two commands later in someone else's job. Comparing
# `$0` to `BASH_SOURCE` is the only way this file can tell the two apart from the
# inside, and it has to be the first thing it does: after a thirteen-second install
# the child still cannot know the caller is still stranded.
if [ "${BASH_SOURCE:-}" = "$0" ]; then
  echo "bootstrap-python: executed rather than sourced, so the virtualenv this file" >&2
  echo "  builds dies with this process and the caller's shell is left with no parser." >&2
  echo "  Call it as: . scripts/ci/bootstrap-python.sh <venv-dir>" >&2
  exit 2
fi

venv_dir="${1:-}"
if [ -z "$venv_dir" ]; then
  echo "bootstrap-python: usage: . scripts/ci/bootstrap-python.sh <venv-dir>" >&2
  exit 2
fi

PIN="pyyaml==6.0.2"
MIRROR="${PYPI_FALLBACK_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"

python3 -m venv "$venv_dir" || {
  echo "bootstrap-python: could not create a virtualenv at $venv_dir" >&2
  exit 1
}
# shellcheck disable=SC1091
. "$venv_dir/bin/activate"

pip_args=(install --quiet --disable-pip-version-check)
if ! python -m pip "${pip_args[@]}" "$PIN"; then
  if python -m pip "${pip_args[@]}" --retries 3 --extra-index-url "$MIRROR" "$PIN"; then
    echo "bootstrap-python: $PIN from $MIRROR after the primary index failed"
  else
    # Not fatal on its own: the parser can already be importable (a preinstalled
    # module, or an index that served a wheel on a later retry). The acceptance
    # test is the import below, and it has to be the thing that decides.
    echo "bootstrap-python: $PIN did not install from either index; continuing to" >&2
    echo "  the import test, which is what actually decides this job." >&2
  fi
else
  echo "bootstrap-python: $PIN from the primary index"
fi

# The acceptance test is the interpreter the job will really invoke, not pip's
# exit code and not merely the module. Pipeline 1025 installed the pin and still
# died on `python: command not found`: the virtualenv answers to `python`, the
# caller's shell answered to neither name, and every command after the bootstrap
# -- test_pipeline, the 60-odd audits, the battery's judge -- is reached through
# one of those two spellings. A bootstrap that cannot name both has nothing to
# report green about.
for interpreter in python python3; do
  if ! command -v "$interpreter" >/dev/null 2>&1; then
    echo "bootstrap-python: $venv_dir/bin/$interpreter is missing, so the virtualenv" >&2
    echo "  did not survive creation (a partial venv, or an activation file that does" >&2
    echo "  not match the interpreter that built it)." >&2
    exit 1
  fi
  if ! "$interpreter" -c "import yaml" 2>/dev/null; then
    echo "bootstrap-python: $PIN is not importable by $interpreter in $venv_dir" >&2
    echo "  (neither the primary index nor $MIRROR produced a usable parser). Every" >&2
    echo "  workflow audit in this job would fail on 'import yaml', so the job stops" >&2
    echo "  here rather than reporting a green run that checked nothing." >&2
    exit 1
  fi
done
