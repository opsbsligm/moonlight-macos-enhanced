#!/usr/bin/env bash
# Print the bundle and executable name this project builds.
#
# A one-line wrapper, and that is the point: bash and the Python gates ask the same
# question of scripts/project_identity.py, which reads the project file and refuses the
# name the Qt client installs under (upstream issue 41). A shell script with its own copy
# of the name is how a rename ships half-done.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
python3 "$root/scripts/project_identity.py" --print 2>/dev/null \
  || python3 "$root/scripts/project_identity.py"
