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
# Usage: bash scripts/ci/bootstrap-python.sh <venv-dir>
# Exits non-zero, loudly, if the parser is not importable afterwards.

set -uo pipefail

venv_dir="${1:-}"
if [ -z "$venv_dir" ]; then
  echo "bootstrap-python: usage: $0 <venv-dir>" >&2
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
if python -m pip "${pip_args[@]}" "$PIN"; then
  echo "bootstrap-python: $PIN from the primary index"
elif python -m pip "${pip_args[@]}" --retries 3 --extra-index-url "$MIRROR" "$PIN"; then
  echo "bootstrap-python: $PIN from $MIRROR after the primary index failed"
fi

# The acceptance test is the import, not the installer's exit code. Everything
# downstream -- workflow-audit, constraints-audit, the battery's judge -- fails
# on `import yaml`, so a bootstrap that cannot say that word has nothing to
# offer the rest of the job.
if ! python -c "import yaml" 2>/dev/null; then
  echo "bootstrap-python: $PIN is not importable in $venv_dir (neither the" >&2
  echo "  primary index nor $MIRROR produced a usable parser). Every workflow" >&2
  echo "  audit in this job would fail on 'import yaml', so the job stops here" >&2
  echo "  rather than reporting a green run that checked nothing." >&2
  exit 1
fi
