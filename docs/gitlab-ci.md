# GitLab CI and the GitHub mirror

GitLab is the source of truth. Push development commits to the `gitlab` remote;
`publish-github` is the only writer to the GitHub mirror.

## Execution order

`lint -> deps -> build -> test -> package -> mirror`

- Pushes (branches and tags), merge requests, and web runs execute the core gates.
- The default branch and tags also produce a DMG.
- The default branch and tags also run `mutation-battery`: the full assertion
  battery in the test stage. It mutates the checked-out source and needs no
  build artifacts, so it declares `needs: []` and runs in parallel with the
  build instead of blocking the release DMG. Measured at 71 minutes (146
  cases) on a clean local tree; the job ceiling is 150 minutes. A failed
  battery on a tag is a release-blocker by construction.
- Push and web runs mirror after every applicable earlier stage succeeds.
  Merge request pipelines never publish with the deploy key.
- `publish-github` has no `needs` shortcut. Its stage barrier includes packaging.
  Each job has a timeout and no gate is allowed to fail.
- Build logs come from `clean build`; incremental logs cannot demonstrate full
  source coverage. Both the build and smoke-test pipelines propagate failures
  through `tee`. Resolving the build number must also succeed before compilation.
- The smoke test starts the bundle executable directly, checks that child's PID,
  and terminates only that child. An existing instance cannot satisfy the check.

## Mirror isolation and ordering

`scripts/ci/publish-github.sh` uses a temporary directory for its bare Git
snapshot, deploy key, SSH config and known-hosts file. It removes that directory
on success, failure and handled cancellation. It does not write `~/.ssh/config`,
`~/.ssh/gh_deploy`, or global Git configuration.

The GitHub Ed25519 public host key is checked into
`scripts/ci/github_known_hosts`. Its SHA256 fingerprint is
`+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`, verified through GitHub's HTTPS
Meta API on 2026-10-21. SSH uses strict host verification, the job's single
identity, and no agent. Host-key changes require verification and a reviewed
repository change, not `ssh-keyscan` or trust on first use during deployment.

The `github-mirror` resource group serializes publishers. Fetching starts only
after GitLab grants that lock, so jobs do not carry an old snapshot into it.
The triggering branch or peeled tag must still point to `CI_COMMIT_SHA`;
superseded/deleted refs produce an explicit skip. An empty or unreadable source
fails without touching the destination.

All branches and tags, including deletions, are pushed in one atomic operation.
The script compares every destination head/tag with the fetched snapshot before
reporting success. This is a full GitLab mirror: the stage barrier proves the
triggering pipeline's gates, not the validation status of other fetched branches.

GitLab configures resource-group ordering through the API, not YAML. After the
resource group exists, set `process_mode=newest_ready_first` on project 6's
`github-mirror` resource group and read it back. The stale-ref check remains
necessary regardless of queue order; serialization alone does not reject retries.

## Credentials and dependencies

- `GH_DEPLOY_KEY`: GitLab project **file** variable, write access to this mirror.
- `GRP_CI_JOB_TOKEN`: GitLab group **env_var**, used for the private common-c
  submodule. `fetch-submodules.sh` adds a URL-scoped Basic header through
  `GIT_CONFIG_COUNT` only for its child Git processes, including recursive clones.
  It preserves runner-provided runtime config and writes no credential to Git
  config. Existing credentials left by older pipelines are not scrubbed by this
  script.
- Only `download-deps` reads/writes the framework cache. The build consumes that
  job's artifacts, not a mutable cache. No derived data is cached.
- The Python audit job installs `pyyaml==6.0.2` in a temporary virtualenv.
- The mutation battery installs the same `pyyaml==6.0.2` pin in its own
  temporary virtualenv; the two jobs never share a venv.

## Single runner and concurrency

The project runs on one shared macOS runner (`local-shell-1306`, shell
executor) plus the mirror runner. The shared runner's `concurrent` setting is
2, so at most two of its jobs run at once; every other job queues.

- `audit:python` carries a 30-minute ceiling because pip/venv setup plus the
  full audit list is the slowest fast-path job. When two pipelines are active
  at once (for example a merge pipeline and a branch pipeline), the second
  pipeline's audit job can approach that ceiling without any code change;
  retrying the job after the first pipeline drains is the standard fix.
  Pipelines #492 recorded this exact shape and turned green on retry.
- The mutation battery is the one job expected to exceed an hour on this
  runner. While it runs, everything else from the same pipeline that shares
  the runner waits; cross-pipeline work queues behind both. Schedule tag
  pipelines knowing the release window includes roughly two hours of
  single-runner occupancy on top of the normal build.
- `audit:python` and `audit:sources` both compile or import Objective-C
  surface. Do not "fix" a red by raising a timeout before reading which of
  the two jobs the other pipeline's job starved.

## Mirror controller failures

`publish-github` talks to the GitLab-hosted mirror controller over HTTPS.
Pipelines #510 and #511 failed with `Mirror rejected` / unavailable during an
~8-minute controller outage that had nothing to do with the commit content.
The publisher now retries five attempts with a fixed 5s/15s/30s/60s/120s
backoff (roughly 230 seconds of total headroom), which survives the outage
observed so far.

- A `publish-github` red on an otherwise green pipeline is first suspected to
  be the controller, not the commit: read the job log for the HTTP code, then
  retry the single job. The `github-mirror` resource group and the stale-ref
  check make a retried publish safe.
- If the controller stays down longer than the backoff budget, restart the
  mirror service on the GitLab host (`/opt/gitlab-mirror/`) and retry once.
- Do not clear a red mirror job by deleting and re-creating the resource
  group: that reorders publishers that are already serialized.

## Verification and limits

Run `python3 scripts/ci/test_pipeline.py` (requires PyYAML). It uses disposable
bare repositories to verify branch/tag mirroring and pruning, annotated tags,
old-run retries, deleted triggers, fetch failures, empty sources, atomic failure
on a rejected tag, SSH isolation, process-only submodule credentials, trigger
rules, and build/test failure propagation. On macOS it also compiles and signs
a harmless launch fixture to check existing-instance isolation and startup
failure detection.

Before pushing, validate `.gitlab-ci.yml` using the project's CI Lint API with
`dry_run=true`, `include_jobs=true`, and an existing branch and tag.
After pushing, find the pipeline by the exact commit SHA, wait for its terminal
status, compare GitLab/GitHub refs, and inspect the DMG artifact. Job success
alone does not prove a real streaming session or controller behavior.

Current coverage is selected repository audits, clean native-architecture
build/source checks, diagnostics replay, and bundle/signature/startup smoke.
`lint:toolchain` checks tool availability only. A full formatting baseline, the
full mutation battery on merge-request pipelines (it runs on tags and the
default branch only), both-architecture release acceptance, Developer ID
signing/notarization, and physical streaming/input validation are separate
work. Do not report them as covered by this pipeline.

Rollback the CI changes with a new revert commit pushed to GitLab and validate
that commit's pipeline. Do not restore shared SSH writes or bypass a red gate
just to make a mirror job pass.

References: GitLab resource groups and SSH-keys documentation, Git's
`GIT_CONFIG_COUNT` documentation, and GitHub's public Meta API.
