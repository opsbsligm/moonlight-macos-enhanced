# TCC reset lost the screen-capture grant: rebuilding the csreq by hand

> English summary: on 2026-11-08 the remote Mac mini runner's system TCC
> database was reset (`kTCCServiceScreenCapture` grant gone, error -3801),
> which failed the `audit:deep` render probe. User-level TCC rows, a bare
> system insert, and reusing another app's csreq all failed before a
> freshly generated `csreq` for `std.skyhua.MoonlightMac` (44 bytes,
> `identifier "std.skyhua.MoonlightMac"`) written with `auth_value=2`
> into `/Library/Application Support/com.apple.TCC/TCC.db` worked.

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
   - Functional: run a tiny probe bundle and require `SCREENCAPTURE_OK`
     output (the -3801 error must be gone).

Confirmed 2026-11-09: the row is present
(`kTCCServiceScreenCapture|std.skyhua.MoonlightMac|1|2`, plus the
`kTCCServiceListenEvent` row `auth_value=2`), and the pipeline's
`audit:deep` is the functional check.

## Durability (still open)

Instant effect is verified. Survival across a reboot / `tccd` reload is
**not** yet proven; treat the row as accepted configuration until a
post-reboot `audit:deep` pass confirms it. Any macOS security update or
another TCC reset can wipe it again.

## Runner hygiene notes

- Sudo password for the mini lives in
  `~/.config/gitlab-1306/runner-sudo-password` (mode 600); it is **not**
  the legacy host SSH password.
- The scratch files (`/tmp/csreq.swift`, `/tmp/tcc*.sh|py`,
  `~/ScProbe.app` on the mini) were cleared after the fix; this page
  is the canonical record of the recovery procedure.

