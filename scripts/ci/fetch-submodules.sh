#!/usr/bin/env bash
set -euo pipefail

: "${GRP_CI_JOB_TOKEN:?GRP_CI_JOB_TOKEN is required for private submodules}"

# Runtime config is inherited by recursive clones but never written to a Git
# config file. Keep any configuration the runner already supplied.
# The mirror of this repository is public, so the GitLab LAN base may not be
# hard-coded here. Read the submodule URL the way git resolves it: an absolute
# .gitmodules URL is used as-is, and a relative one is expanded against the
# clone's own remote URL (the same base the fetch will actually use).
submodule_url="$(sed -n 's|^[[:space:]]*url[[:space:]]*=[[:space:]]*||p' .gitmodules | head -n 1)"
case "$submodule_url" in
  http://*|https://*) : ;;
  ../*)
    origin_url="$(git config --local --get remote.origin.url 2>/dev/null || git remote get-url origin 2>/dev/null || true)"
    case "$origin_url" in
      http://*|https://*) submodule_url="${origin_url%/*}/${submodule_url#../}" ;;
      *) echo "cannot expand relative submodule URL '$submodule_url' against origin '$origin_url'" >&2
         exit 1 ;;
    esac
    ;;
  *) echo "submodule URL is not fetchable: '$submodule_url'" >&2
     exit 1 ;;
esac
config_index="${GIT_CONFIG_COUNT:-0}"
[[ "$config_index" =~ ^[0-9]+$ ]]
auth_header="$(printf 'oauth2:%s' "$GRP_CI_JOB_TOKEN" | base64 | tr -d '\r\n')"
export "GIT_CONFIG_KEY_${config_index}=http.${submodule_url}.extraHeader"
export "GIT_CONFIG_VALUE_${config_index}=Authorization: Basic ${auth_header}"
export GIT_CONFIG_COUNT="$((config_index + 1))"
export GIT_TERMINAL_PROMPT=0

git submodule sync --recursive
git submodule update --init --recursive
