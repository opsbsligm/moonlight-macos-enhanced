# TCC reset lost the screen-capture grant: rebuilding the csreq by hand

> English summary: on 2026-11-08 the remote Mac mini runner's system TCC
> database was reset (`kTCCServiceScreenCapture` grant gone, error -3801),
> which failed the `audit:deep` render probe. User-level TCC rows, a bare
> system insert, and reusing another app's csreq all failed before a
> freshly generated `csreq` for `std.skyhua.MoonlightMac` (44 bytes,
> `identifier "std.skyhua.MoonlightMac"`) written with `auth_value=2` into
> `/Library/Application Support/com.apple.TCC/TCC.db` made the grant read
> back as allowed. **This is not a fix for `audit:deep`.** A later retry
> with the row present still failed (see "Still open" below): the row lets
> TCC read back `auth_value=2`, but the render probe launches the Debug app
> as a direct subprocess, so macOS attributes the capture to the runner
> lineage rather than the granted bundle id, and ScreenCaptureKit still
> returns -3801. The grant is necessary; on its own it is not sufficient.
>
> Update, same day: the attribution cause is fixed in the probe (it launches
> through `open` now), and a second, unrelated cause was found underneath it
> -- a panel that fell asleep leaves ScreenCaptureKit with no active display
> and every capture answers -3811. Both are described in "Still open" and
> neither is certified green until the pipeline for the fix commit says so.

## What happened

The render probe in `audit:deep` needs ScreenCaptureKit. The mini's system
TCC database was reset at 04:35 on 2026-11-08, so the Moonlight bundle id
had no `kTCCServiceScreenCapture` row and every capture attempt returned
`error=-3801` in `com.apple.ScreenCaptureKit.SCStreamErrorDomain`.

## What did not work (do not retry)

- User-level TCC database insert -- the probe runs as a non-sandboxed
  app, so the user DB row is not consulted.
- System-level insert with `csreq NULL` -- the stricter system schema
  rejects a null requirement.
- Copying Parsec's `tv.parsec.www` csreq -- the requirement is bound to
  the signing identity, so a foreign csreq fails validation.
- GUI automation ("allow" button clicks) -- CI has no WindowServer, the
  prompt never appears.

## What worked

1. Generate a csreq that matches the shipped bundle. Compile a small
   ObjC helper that calls `SecRequirementCreateWithString` +
   `SecRequirementCopyData` on `identifier "std.skyhua.MoonlightMac"`
   and writes the result (44 bytes). A Swift variant failed on a type
   conversion and was dropped; keep the ObjC one.
2. Insert the row with `auth_value=2` (allowed) and the generated csreq
   into the **system** database. Drive `sudo` through an expect-style
   wrapper because the password prompt eats the newline.
3. Verify in two layers:
   - `select service,client,client_type,auth_value from access where
     client like "%skyhua%"` must show
     `kTCCServiceScreenCapture|std.skyhua.MoonlightMac|1|2`.
   - Functional: run a tiny probe bundle and require capture to start.
     This layer **never actually passed**. Started through LaunchServices
     the probe stopped being an instant refusal and entered the
     ScreenCaptureKit callback, but it never produced a completed capture
     either, so `SCREENCAPTURE_OK` is not a claim this page can make. The
     only functional check that matters -- `audit:deep` -- is still red.

Confirmed 2026-11-09: the row is present. A second system row was also
inserted for the runner binary by path (`client_type=1`, `auth_value=2`),
so both the app bundle id and the runner path read back as allowed.

## Still open: the row is present but `audit:deep` is still red

`audit:deep` was retried on 2026-11-09 with both rows in the database
(job 11652, Mac mini runner 8) and it failed the same way: every pane
reports `capture refused`, error -3801. So "the row is present" is not the
same as "capture works". The functional difference between the passing and
failing case is *how the process starts*:

- A binary `exec`'d directly (an SSH command, or the `subprocess.run([binary])`
  `render-probe.py` used for the Debug app) is attributed by the OS to the
  calling process lineage -- the shell/runner -- not to the app bundle, so the
  `std.skyhua.MoonlightMac` grant is never consulted. A directly-exec'd probe
  refuses no matter what TCC says.
- The same bundle started through LaunchServices (`open`) is attributed to
  the app, enters the ScreenCaptureKit callback, and is no longer an instant
  refusal.

That is why the pipeline stayed red: the probe's own code path was the direct
exec one. The durable fix is not more TCC rows -- it is making the probe
capture through a path macOS attributes to a granted process.

## The second cause, and what shipped

Launching through LaunchServices is necessary but was not the whole story.
Comparing a working capture against a refused one on the mini found a second
environment cause with the same symptom: with the panel asleep
`CGGetActiveDisplayList` returns zero displays, and ScreenCaptureKit answers
`-3811` ("cannot start stream playback") rather than -3801. `caffeinate -u`
brought the count back to one in about a second. Both causes are invisible to
the reader of the report -- each pane says `capture refused` and the report
still shows the page mounted and every readable row matching the model, so an
environment fault is indistinguishable from the rendering defect the job
exists to catch.

`render-probe.py` now does both, as runtime preconditions rather than
verdicts: it wakes the panel and waits for an active display before asking for
pixels, and it launches the Debug bundle with `open -n -W --stderr ... --env
...` so the capture is attributed to the bundle the grant names. Two
consequences of `open` were measured on the mini and are load-bearing:
`--env` does reach the app and `--stderr` keeps the diagnostics; `open -W`
waits but does **not** propagate the app's exit status -- a bundle that exits
1 makes `open` exit 0 -- so `report.json` is the verdict and no exit code is
quoted as one. `constraints-audit.py` pins all four properties so a later edit
that reintroduces the direct exec, drops the env carry-over, drops the display
wake, or trusts `open`'s exit status fails the gate with the symptom spelled
out.

**Status: not yet certified green.** The self-test and the constraint audit
pass locally; `audit:deep` on the mini is only believed fixed until the
pipeline for `1330b040` reports its own result, because this job's history is
exactly a series of plausible causes. Until then the grant stays accepted
configuration that is necessary but unproven to be sufficient.

Verification has one awkward property worth naming: `audit:deep` runs on the
default branch and on tags only, so no MR pipeline can ever show this fix
working. The first honest reading is the main-branch pipeline after the merge,
and nothing before it counts as evidence.

## Durability (still open)

What is verified is that the row reads back as `auth_value=2`. What is not
verified is that the grant does anything useful in CI, because the direct
-exec attribution problem above means the grant is never consulted on the
path that used to run (see "Still open" and "The second cause"). Now that the
probe launches through LaunchServices the grant is at least consulted, so a
green run would be the first evidence the rows do anything -- and it would
still not prove they survive a reboot or a `tccd` reload. Treat the rows as
accepted configuration, not as a green `audit:deep`. Any macOS security update
or another TCC reset can wipe them again.

## Runner hygiene notes

- Sudo password for the mini lives in
  `~/.config/gitlab-1306/mini-admin-password` (mode 600); it is **not**
  the legacy host SSH password. (The earlier draft named this file
  `runner-sudo-password`; no such file exists, so a recovery that reads
  that path silently gets an empty password and the sudo insert fails.)
- The scratch files (`/tmp/csreq.swift`, `/tmp/tcc*.sh|py`,
  `~/ScProbe.app` on the mini) were cleared after the fix; this page
  is the canonical record of the recovery procedure.

