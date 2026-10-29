# GitLab CI and the GitHub mirror

GitLab is the source of truth. Push development commits to the `gitlab` remote;
`publish-github` is the only writer to the GitHub mirror.

## Execution order

`lint -> deps -> build -> test -> package -> verify -> mirror`

- Pushes (branches and tags), merge requests, and web runs execute the core gates.
- The default branch and tags also produce a DMG.
- The default branch and tags also run `mutation-battery`: the full assertion
  battery in its own `verify` stage. It mutates the checked-out source and needs
  no build artifacts, but it declares no `needs:`, so the stage barrier holds it
  until the build, both test jobs, both audits and the DMG have left the runner.
  That is deliberate: as a `needs: []` job in the test stage it competed with the
  release path for one 8-core runner and starved `audit:python` into a timeout
  (pipeline 647), which skipped every downstream gate. Measured at 71 minutes
  (146 cases) on a clean local tree; the job ceiling is 180 minutes and a
  `resource_group` keeps two batteries off the runner at the same time. A failed
  battery on a tag is still a release-blocker by construction, because `mirror`
  stays after `verify`; only the DMG artifact arrives early.
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

- `audit:python` is the slowest fast-path job (pip/venv setup plus the full audit
  list) and needs about 140 seconds on an idle runner. When two pipelines are
  active at once its ceiling can be reached with no code change, so the ceiling
  is now 60 minutes: pipeline 647 recorded 1803 seconds before the old 30-minute
  ceiling killed the job (trace gaps of 608s and 779s while load sat at 20-33 on
  eight cores) because the mutation battery and the security jobs shared the
  runner. The battery has moved out of the fast path; the extra headroom covers
  the overlap that remains at `concurrent=2`. Retrying a single starved job after
  the other pipeline drains is still the standard fix and pipelines #492 turned
  green that way.
- The mutation battery is the one job expected to exceed an hour on this
  runner: 9302 seconds (155 minutes) in pipeline 647 while it fought the release
  path for CPU, against a measured 71 minutes standalone, so its ceiling is three
  hours. It runs in the `verify` stage after packaging with a `macos-battery`
  resource group, so it no longer competes with any gate and two batteries never
  overlap. Schedule tag pipelines knowing the release window still includes up to
  about two hours of single-runner occupancy on top of the normal build.
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

## Gate parity across both definitions

Two definitions drift. Gates have historically landed in the mirror workflow
first, so the source of truth reached a subset while `local-gates.sh` -- which
used to build its list from the mirror -- reported a green local sweep over all
of them. Measured when this section was written: 88 gate calls on the mirror, 33
written out on the source of truth, and a local sweep that claimed all of them.

`python3 scripts/gate-coverage-audit.py --verify` is the reconciliation. Every
gate the mirror calls must be reachable on the source of truth, either spelled
out in `.gitlab-ci.yml` or emitted at run time by `audit:gates` through
`--emit-commands --class=fast|selftest|deep`. A gate leaves the fast set only
through `NON_FAST`, with a reason, and the self-test refuses an entry there that
no longer names a real gate -- a stale excuse is how a gate stops being looked
at. The audit reads the two files as text on purpose: PyYAML is not on a bare
checkout, and an audit that needs a venv is an audit that does not run.

- `audit:gates` (test stage, `macos`, no artefacts) runs `--self-test`, then
  `--verify`, then every emitted fast and self-test command. 47 fast plus 5
  self-test commands, measured around 80 seconds for all 47 on an M2 laptop.
- `audit:deep` (verify stage, tag and main only) takes the two compile-first
  gates: `render-probe.py` and `scaling-output-evidence-tests.py`. No `needs:`,
  so the stage barrier keeps its xcodebuild off the release path -- the pipeline
  647 starvation again otherwise -- and it shares the battery's `resource_group`.
- The mirror's form of a command wins inside `local-gates.sh`, because that file
  rewrites artefact paths for a laptop while the source of truth spells them in
  CI variables (`$app`, `$DERIVED_DATA_PATH`) that resolve to nothing locally. A
  gate only the source of truth calls is still run, as written. `scripts/ci/
  publish-github.py` is excluded by name, not by path shape: it pushes refs, and
  its prefix (`MIRROR_DRY_RUN=1`) is the only thing that makes the call harmless.

Two limits worth knowing. A job that asks for a class and throws the answer away
still counts as reachable -- the audit reads text, so it knows a class is asked
for, not that the commands reach a shell. And a gate both files call is judged by
the mirror's form locally, so a source-of-truth-only spelling change to an
already-covered gate is not re-proven on a laptop.

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
