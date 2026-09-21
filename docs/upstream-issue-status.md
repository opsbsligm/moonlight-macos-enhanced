# Upstream issue status

## 1. Why this document exists

`skyhua0224/moonlight-macos-enhanced` carries open issues that a fork cannot tell apart
from a glance: some are fixed in this branch and simply never closed upstream, some need a
piece of information nobody supplied, some need a Windows host or a second machine, and a
few are open because the maintainer answered with a promise rather than a commit. This file
records which is which, per issue, together with what this repository can actually point at.

It is deliberately not a changelog. A changelog says what changed; this says what a reader
may conclude from an open issue upstream, and how far that conclusion can be trusted.

## 2. How each entry was checked

1. The upstream issue text and every comment were read (`gh issue view --json body,comments`).
2. This branch was searched for a commit, a gate, or a released artefact that touches the
   surface the issue describes (`git log`, `CHANGELOG.md`, `scripts/*-tests.py`).
3. A verdict was assigned only at the level the evidence supports.

Verdicts:

| Verdict | Means |
| --- | --- |
| **resolved here** | This branch contains the change, and a gate or artefact in the tree demonstrates it. |
| **deliverable** | Nothing blocks it: the work is ours to do, and the shape of it is known. |
| **needs input** | Progress needs information or a retest from the reporter that is not in the thread. |
| **needs external** | Progress needs something outside this repository: a Windows host, a second machine, a specific OS build, or upstream software. |
| **not applicable** | The premise no longer holds for a current build. |
| **open** | A real defect or request with no work here to point at. |

What this check cannot do, stated once instead of per entry: the upstream repository runs no
build or test workflow, so a claim in an upstream comment is a claim, not a green tick; and
four issues attach their evidence as images or pasted log fragments, which were read as text
only where the thread also pasted it inline.

## 3. Per-issue status

Open upstream issues, as of 2026-09-21. Upstream `master` has not moved: this branch is 202
commits ahead and 0 behind, so "the upstream answer was X" and "the code says X" are two
different statements, and both are given below.

| # | Subject | Verdict | Evidence, and what is missing |
| --- | --- | --- | --- |
| 19 | Input dead or scrambled after switching back to a Linux host | **needs input** | This branch hardened the adjacent surface: `[hidSupport releaseAllModifierKeys]` on `activeSpaceDidChange`, plus `scripts/space-transition-held-key-tests.py` and `scripts/held-modifier-keyboard-pair-tests.py`. That is not a fix for the report: the maintainer asked twice for desktop environment, session type, Sunshine fork and a diagnostics log, and the thread has no answer that identifies the failure. No verdict is possible without it. |
| 22 | 10-bit SDR (force 10-bit transport while the host keeps SDR) | **built here, needs a host** | The switch exists: `Enable 10-Bit SDR` per host, off by default, negotiated through `Limelight/Stream/VideoFormatNegotiation.h`, proved by `scripts/sdr-10bit-codec-tests.py` (all 32 input combinations against the answer that shipped before it, plus the dynamic range swept with HDR off). The protocol never required HDR to reach a 10-bit profile, and the renderer already resolved its transfer mode from the HDR preference alone, so the oversaturated/grey failure the report describes has no route in this tree. Not measured: no stream was played against a real host, so host acceptance and the visual result are unverified. That is what remains, and it needs a Sunshine or NVIDIA host rather than a code change. |
| 24 | Locked Mouse mode: the pointer cannot be moved at all, clicks still work | **located here, partly fixed here** | **A correction first: the earlier version of this row, and the settings row it rewrote, both stated that this client has no NSEvent relative sender. It has one.** `HIDSupport+Pointer.m` hands `event.deltaX`/`event.deltaY` to `dispatchRelativeMouseDeltaX:`, which sends `LiSendMouseMoveEventCtx` -- a protocol-relative move that does not depend on CoreHID at all. The wrong fact came from reading the strings table instead of the sender, and a gate was written to protect the wrong fact; both are gone. Three things that do hold. (1) The strategy the picker labelled `HID` was the one strategy that stops CoreHID from starting -- the opposite of its label -- and its only ObjC reader, `shouldUseCompatibilityMouse`, had no caller anywhere in `Limelight/`. (2) An unrecognised or absent stored strategy fell through to exactly that mode, so a host nobody configured had its fastest relative source switched off while the settings page displayed the default. (3) The status line credited motion to a sender nobody observed: the AppKit line was written where the event arrived, upstream of the warp-window suppression, the zero-pixel quantisation and the absolute-path detour, and a CoreHID start failure then declared an AppKit fallback no code had seen deliver anything. **Fixed here:** the strategy is retired with its raw value held reserved, so a stored `0`, the string `HID` the menu no longer lists, an absent value and a corrupt value all resolve to the default; the orphan rows that described it are out of both tables; each sender now credits the status line itself, after its packet reaches the host, and a CoreHID failure reports that CoreHID stopped and leaves the sender line uncredited. Six `constraints-audit.py` assertions hold that shape and `assertion-battery.py` re-plants each one (114/114 caught). **Still open:** the reporter's own setting is unknown -- the issue's `moonlight-debug.log` sits at `files/27594278` and answers only to a signed-in fetch, so nobody here has read it -- and nobody has observed whether `NSEvent.deltaX` stays non-zero with the cursor association off and the pointer warped to the centre. The shipped diagnostic report carries the counters that settle both: raw versus sent relative deltas per source tag, so one report from build 1559 or newer says whether the AppKit path was fed and whether it sent. |
| 25 | Gamepad mapping dead on Win11 25H2 (Xbox Elite 2, Betop Zeus) | **needs external** | A device-identification change is in the tree (`isXbox()` extended to `0x0B00/0x0B05/0x0B22`, `isKingKong()` for VID `0x2DC8`), and the reporter then said both drivers still do nothing on `26200.8457`. That is a Windows-side or driver-side problem this machine cannot reach: it needs the specific pad, that Windows build, and a host session. |
| 26 | Crashes two seconds after the stream page appears on macOS 12.7.4 | **not applicable** | The app target's `MACOSX_DEPLOYMENT_TARGET` is 26.0 (`Moonlight.xcodeproj/project.pbxproj`, four configurations), so a current build does not launch on macOS 12 at all; `compile-audit.py` prints the same number as the floor it checks against. The only 12.0 in the tree is the vendored `moonlight-common` project, which does not lower the app's floor. A defensive guard for the reported `viewDidLayout` crash was committed under this issue's number, which is worth knowing, but the crash log is an image nobody transcribed, so the original cause is still unidentified -- it is simply unreachable on a supported system. |
| 28 | Cannot connect | **needs input** | The thread says "see logs" and pastes a discovery sequence that ends at "Local address chosen", i.e. before any TLS or session step. This branch already ships the tooling for that gap: a connection-diagnostics command in the Help menu, browse-failure logging that names the local-network permission, and direct-address probing. Without a log that reaches the failing layer there is nothing to fix. |
| 29 | Picture washed out with HDR on, over-bright without it | **needs input** | The Native renderer's HDR path is where the original reply pointed, and this branch has since added the tone-mapping policy choice and a `No Exposure Shift` entry, which is the knob for exactly that complaint. The reporter has not retested a build that has it, so the issue stays open rather than being claimed as fixed. |
| 31 | 1% low frames stuck near 30 fps | **open** | The upstream reply is that the 1% low figure itself is unreliable and a larger rewrite is coming. That answer is consistent with this branch too: nothing here touches the render or decode pacing path, and the numbers the reporter compared against are from `moonlight-qt` 6.2.89, a different client. A pacing investigation is its own piece of work, not a fix attached to a thread. |
| 33 | Official Moonlight finds and connects the host, this client does not | **needs input** | Same family as 35 and the most actionable thing here is missing evidence: discovery is browse-only for `_nvstream._tcp` in both this client and the Qt one, so "the other client sees it" narrows the cause to the local-network permission, the browse domain, or a host that answers with a name this client rejects -- all three of which the diagnostics command reports. The thread has screenshots only. |
| 35 | No LAN hosts found, and a manually typed IP fails too | **needs input** | A manual address failing means the failure is not discovery but the request that follows it, which puts it next to 28. `NSBonjourServices` and `NSLocalNetworkUsageDescription` are both present in `Limelight/macOS/Supporting Files/Info.plist`, and `scripts/dmg-audit.py` now verifies the localisation tables inside the shipped image, so the usual permission-declaration causes are excluded on the build side. The reporter's macOS 27 beta and Sunshine build are the two variables still untested. |
| 41 | Installing this build replaces the Qt Moonlight | **resolved here** | The collision was on the file name, not the identifier: both clients installed as `/Applications/Moonlight.app`. `PRODUCT_NAME` is now `MoonlightEnhanced`, so the two bundles coexist, and `CFBundleDisplayName` localizes the name a user reads (`Moonlight Enhanced` / `Moonlight 增强版`) while the disk name stays ASCII. The bundle identifier is unchanged (`std.skyhua.MoonlightMac2`), so the paired identity and the permission grants still describe the same application; what a user of an earlier build of this repository owes is deleting the `Moonlight.app` this repository installed, because two bundles with one identifier in `/Applications` is how LaunchServices launches the stale copy. The name is read, not copied: `scripts/project_identity.py` is the only reader and refuses the Qt name on read, `scripts/constraints-audit.py` runs its self-test and the project constraint, the workflow reads the name from it before writing any path, and `scripts/dmg-audit.py` certifies the name inside the image a user downloads. |
| 43 | Store the Windows password and sign in automatically | **designed here, not built** | `docs/windows-auto-signin-design.md` now records the decision the code needs: the Keychain is the only permitted home (`AfterFirstUnlockThisDeviceOnly`, one item per host, keyed by bundle identifier so the product rename does not orphan it), the settings record and every log line are named as forbidden, a two-attempt cap because domain accounts lock out, a visible forget control, no auto-enable, and status wording that stops at what the client can actually observe. It also states the two questions that are the maintainers' to answer -- whether a client distributed without a Developer ID should offer this at all, and whether host-side autologon is the better answer -- and recommends not building it until those are answered. |

## 4. Issues that do not need an entry here

| # | Why it is absent |
| --- | --- |
| 21, 40 | Fixed here: the pointer enters the stream window on a switch that the user can turn off, with `scripts/pointer-entry-takeover-tests.py` covering both positions. |
| 23, 32, 37, 39 | Fixed here, recorded in `CHANGELOG.md`. |
| 30 | Localisation. The first half shipped in `v1.3.10-build1537`; the log panel's own 55 sentences were recorded as a number that had to shrink and are keys now, so `UNTRANSLATED_OUTLETS` is empty. |
| 42 | The maintainer took it upstream as their own work. |
| 44, 45, 47 | Pull requests rather than issues; see `docs/` notes in the release body for what was taken, what was declined, and why. |

## 5. What this file suggests doing next

Not a promise, and not ordered by anything but how much of it is blocked on someone else:

1. **41** -- rename the product, because it is a one-line decision with a two-line release note
   and every user who installs beside the Qt client meets it.
2. **22** -- built in this tree and gated; what is left is playing it against a Sunshine
   or NVIDIA host and looking at the picture. Until someone does that, the claim on the
   row is "negotiates 10-bit under SDR", not "looks right".
3. **24** -- the strategy and both unobserved status claims are gone. What remains is a
   measurement, not a search: does `NSEvent.deltaX` stay non-zero with
   `CGAssociateMouseAndMouseCursorPosition(NO)` and a centre warp? That value is the locked
   mode's only relative source besides CoreHID, so if it reads zero on real hardware the fix
   is a delta source that does not depend on cursor position -- not another setting label.
   Until then this row says what is unknown, and the report shipped in build 1559 is what
   would replace the sentence with a number.
4. **43** -- a design note before a pull request.
5. **19, 28, 29, 33, 35** -- nothing to build, and now an excuse less. The app builds a
   pasteable report (`Settings` -> App -> Debug Log -> `Copy Diagnostics Report…`, and the
   same button inside the pairing failure alert): version and build, macOS build, model,
   whether Gatekeeper is running it out of a translocation mount, the live answers for Input
   Monitoring / Accessibility / Screen Recording, the declared Bonjour services including
   whether `_nvstream._tcp` is among them, the hosts in the store with their pair and online
   state, and the tail of its own log. A PIN, a password, a certificate-shaped blob, a MAC
   address, a UUID and the home path are replaced by a marker before the text leaves the
   process, and the host MAC, the pinned certificate and the client identifier are never read
   (`scripts/diagnostics-report-tests.py` plants each of those secrets and refuses the build
   if any survives). What these five issues still need is a reporter who attaches it: the
   app can now answer the question, but only the person with the failing machine can press
   the button. That button ships from `v1.3.10-build1559`, so the ask can now carry a version
   -- a reporter on an older build has to update before the sentence means anything, and a
   report pasted from build 1559 or later answers the question in the thread that has been
   waiting on it since issue 19 was opened.
