#!/usr/bin/env bash
set -euo pipefail

: "${GH_DEPLOY_KEY:?GH_DEPLOY_KEY must be a CI file variable}"
: "${CI_REPOSITORY_URL:?CI_REPOSITORY_URL is required}"
: "${CI_COMMIT_REF_NAME:?CI_COMMIT_REF_NAME is required}"
: "${CI_COMMIT_SHA:?CI_COMMIT_SHA is required}"
test -s "$GH_DEPLOY_KEY"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
destination="${GITHUB_MIRROR_URL:-git@github.com:opsbsligm/moonlight-macos-enhanced.git}"
trigger_ref="refs/heads/${CI_COMMIT_REF_NAME}"
if [[ -n "${CI_COMMIT_TAG:-}" ]]; then
  trigger_ref="refs/tags/${CI_COMMIT_TAG}"
fi
git check-ref-format "$trigger_ref"

umask 077
job_dir="$(mktemp -d "${TMPDIR:-/tmp}/moonlight-mirror.XXXXXX")"
trap 'rm -rf -- "$job_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cp "$GH_DEPLOY_KEY" "$job_dir/key"
chmod 600 "$job_dir/key"
cp "$script_dir/github_known_hosts" "$job_dir/known_hosts"
cat > "$job_dir/ssh_config" <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile "$job_dir/key"
  IdentitiesOnly yes
  IdentityAgent none
  UserKnownHostsFile "$job_dir/known_hosts"
  GlobalKnownHostsFile /dev/null
  StrictHostKeyChecking yes
  BatchMode yes
  ConnectTimeout 15
  ConnectionAttempts 2
  ServerAliveInterval 15
  ServerAliveCountMax 2
EOF
export GIT_SSH_COMMAND="ssh -F $(printf '%q' "$job_dir/ssh_config")"
export GIT_SSH_VARIANT=ssh
export GIT_TERMINAL_PROMPT=0

# The GitLab resource_group is held before this fresh snapshot is fetched.
# Never reuse refs left by an older job in a runner's shared checkout.
snapshot="$job_dir/snapshot.git"
git init --bare --quiet "$snapshot"
git --git-dir="$snapshot" config remote.source.url "$CI_REPOSITORY_URL"
git --git-dir="$snapshot" fetch --quiet --no-tags source \
  '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
git --git-dir="$snapshot" for-each-ref --format='%(refname)' refs/heads > "$job_dir/heads"
if [[ ! -s "$job_dir/heads" ]]; then
  echo "FAIL: source has no branches; refusing to prune the mirror" >&2
  exit 1
fi

source_sha="$(git --git-dir="$snapshot" rev-parse --verify "${trigger_ref}^{commit}" 2>/dev/null || true)"
if [[ "$source_sha" != "$CI_COMMIT_SHA" ]]; then
  echo "SKIP: triggering ref was updated or deleted; this pipeline is superseded"
  exit 0
fi

# One atomic update covers branch/tag changes and deletions together.
git --git-dir="$snapshot" push --atomic --force --prune "$destination" \
  'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
git --git-dir="$snapshot" for-each-ref --format='%(objectname)%09%(refname)' \
  refs/heads refs/tags | LC_ALL=C sort > "$job_dir/expected"
git --git-dir="$snapshot" ls-remote --refs --heads --tags "$destination" \
  | LC_ALL=C sort > "$job_dir/actual"
diff -u "$job_dir/expected" "$job_dir/actual"
echo "Mirror verified: $(wc -l < "$job_dir/expected" | tr -d ' ') refs; trigger ${CI_COMMIT_SHA}"
