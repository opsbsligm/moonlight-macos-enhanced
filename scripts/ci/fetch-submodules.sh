#!/usr/bin/env bash
set -euo pipefail

# The protocol library is tracked with the client. Only its pinned public
# ENet and SIMDe dependencies remain submodules; neither needs a private token.
export GIT_TERMINAL_PROMPT=0

# Reused checkouts can retain the old parent submodule's .git file after the
# gitlink becomes tracked sources. Preserve that pointer outside the worktree;
# its object database and both dependency repositories remain available.
legacy_git_file="moonlight-common/moonlight-common-c/.git"
if [[ -f "$legacy_git_file" ]]; then
  git ls-files --error-unmatch moonlight-common/moonlight-common-c/src/Limelight.h >/dev/null
  metadata_dir="$(git rev-parse --git-path protocol-migration)"
  mkdir -p "$metadata_dir"
  saved_git_file="$(mktemp "$metadata_dir/legacy-git-file.XXXXXX")"
  mv "$legacy_git_file" "$saved_git_file"
fi

git submodule sync --recursive
git submodule update --init --recursive
