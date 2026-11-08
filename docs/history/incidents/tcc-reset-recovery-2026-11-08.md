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

- A binary `exec`'d directly (an SSH command, or `subprocess.run([binary])`
  the way `render-probe.py` launches the Debug app) is attributed by the
  OS to the calling process lineage -- the shell/runner -- not to the app
  bundle, so the `std.skyhua.MoonlightMac` grant is never consulted. A
  directly-exec'd probe refuses no matter what TCC says.
- The same bundle started through LaunchServices (`open`) is attributed to
  the app, enters the ScreenCaptureKit callback, and is no longer an instant
  refusal.

That is why the pipeline stays red: the probe's own code path is the direct
exec one. The durable fix is not more TCC rows -- it is making the probe
capture through a path macOS attributes to a granted process (launch via
LaunchServices, or drop ScreenCaptureKit for a current-process API that does
not need the grant). Until one of those lands, `audit:deep` on the mini is
**not green**, and the grant should be treated as accepted configuration
that is necessary but unproven to be sufficient.

## Durability (still open)

What is verified is that the row reads back as `auth_value=2`. What is not
verified is that the grant does anything useful in CI, because the direct
-exec attribution problem above means the grant is never consulted on the
path that runs (see "Still open"). Survival across a reboot / `tccd` reload
is likewise unproven. Treat the rows as accepted configuration, not as a
green `audit:deep`. Any macOS security update or another TCC reset can wipe
them again.

## Runner hygiene notes

- Sudo password for the mini lives in
  `~/.config/gitlab-1306/mini-admin-password` (mode 600); it is **not**
  the legacy host SSH password. (The earlier draft named this file
  `runner-sudo-password`; no such file exists, so a recovery that reads
  that path silently gets an empty password and the sudo insert fails.)
- The scratch files (`/tmp/csreq.swift`, `/tmp/tcc*.sh|py`,
  `~/ScProbe.app` on the mini) were cleared after the fix; this page
  is the canonical record of the recovery procedure.

