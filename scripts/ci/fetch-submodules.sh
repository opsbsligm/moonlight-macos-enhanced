#!/usr/bin/env bash
set -euo pipefail

: "${GRP_CI_JOB_TOKEN:?GRP_CI_JOB_TOKEN is required for private submodules}"

# Runtime config is inherited by recursive clones but never written to a Git
# config file. Keep any configuration the runner already supplied.
config_index="${GIT_CONFIG_COUNT:-0}"
[[ "$config_index" =~ ^[0-9]+$ ]]
auth_header="$(printf 'oauth2:%s' "$GRP_CI_JOB_TOKEN" | base64 | tr -d '\r\n')"
export "GIT_CONFIG_KEY_${config_index}=http.http://172.16.130.6/moonlight/moonlight-common-c.git.extraHeader"
export "GIT_CONFIG_VALUE_${config_index}=Authorization: Basic ${auth_header}"
export GIT_CONFIG_COUNT="$((config_index + 1))"
export GIT_TERMINAL_PROMPT=0

git submodule sync --recursive
git submodule update --init --recursive
