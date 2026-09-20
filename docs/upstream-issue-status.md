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
| 22 | 10-bit SDR (force 10-bit transport while the host keeps SDR) | **deliverable** | The client side exists: HDR-to-SDR tone mapping with a `No Exposure Shift` policy entry, and `scripts/hdr-sdr-exposure-tests.py`. The requested mode is a separate thing -- an explicit "10-bit transport, host SDR off" selection plus the colour handling that keeps it from reading oversaturated or grey. Nothing external blocks it; the grey/oversaturated complaint in the report is exactly the failure our exposure gate is shaped to test. |
| 24 | Pointer frozen in Locked Mouse mode | **open** | The upstream reply calls it a known issue with how the cursor is locked; no commit here addresses that path, and the pointer gates in the tree (`relative-pointer-gain-tests.py`, `pointer-entry-takeover-tests.py`) cover relative gain and entry takeover, not a locked pointer that accepts buttons but no movement. A reproduction on a current build is the missing step, and the thread supplies a debug log that this repository has not replayed. |
| 25 | Gamepad mapping dead on Win11 25H2 (Xbox Elite 2, Betop Zeus) | **needs external** | A device-identification change is in the tree (`isXbox()` extended to `0x0B00/0x0B05/0x0B22`, `isKingKong()` for VID `0x2DC8`), and the reporter then said both drivers still do nothing on `26200.8457`. That is a Windows-side or driver-side problem this machine cannot reach: it needs the specific pad, that Windows build, and a host session. |
| 26 | Crashes two seconds after the stream page appears on macOS 12.7.4 | **not applicable** | The app target's `MACOSX_DEPLOYMENT_TARGET` is 26.0 (`Moonlight.xcodeproj/project.pbxproj`, four configurations), so a current build does not launch on macOS 12 at all; `compile-audit.py` prints the same number as the floor it checks against. The only 12.0 in the tree is the vendored `moonlight-common` project, which does not lower the app's floor. A defensive guard for the reported `viewDidLayout` crash was committed under this issue's number, which is worth knowing, but the crash log is an image nobody transcribed, so the original cause is still unidentified -- it is simply unreachable on a supported system. |
| 28 | Cannot connect | **needs input** | The thread says "see logs" and pastes a discovery sequence that ends at "Local address chosen", i.e. before any TLS or session step. This branch already ships the tooling for that gap: a connection-diagnostics command in the Help menu, browse-failure logging that names the local-network permission, and direct-address probing. Without a log that reaches the failing layer there is nothing to fix. |
| 29 | Picture washed out with HDR on, over-bright without it | **needs input** | The Native renderer's HDR path is where the original reply pointed, and this branch has since added the tone-mapping policy choice and a `No Exposure Shift` entry, which is the knob for exactly that complaint. The reporter has not retested a build that has it, so the issue stays open rather than being claimed as fixed. |
| 31 | 1% low frames stuck near 30 fps | **open** | The upstream reply is that the 1% low figure itself is unreliable and a larger rewrite is coming. That answer is consistent with this branch too: nothing here touches the render or decode pacing path, and the numbers the reporter compared against are from `moonlight-qt` 6.2.89, a different client. A pacing investigation is its own piece of work, not a fix attached to a thread. |
| 33 | Official Moonlight finds and connects the host, this client does not | **needs input** | Same family as 35 and the most actionable thing here is missing evidence: discovery is browse-only for `_nvstream._tcp` in both this client and the Qt one, so "the other client sees it" narrows the cause to the local-network permission, the browse domain, or a host that answers with a name this client rejects -- all three of which the diagnostics command reports. The thread has screenshots only. |
| 35 | No LAN hosts found, and a manually typed IP fails too | **needs input** | A manual address failing means the failure is not discovery but the request that follows it, which puts it next to 28. `NSBonjourServices` and `NSLocalNetworkUsageDescription` are both present in `Limelight/macOS/Supporting Files/Info.plist`, and `scripts/dmg-audit.py` now verifies the localisation tables inside the shipped image, so the usual permission-declaration causes are excluded on the build side. The reporter's macOS 27 beta and Sunshine build are the two variables still untested. |
| 41 | Installing this build replaces the Qt Moonlight | **deliverable** | The bundle identifiers already differ -- this app is `std.skyhua.MoonlightMac2` (`Moonlight.xcodeproj/project.pbxproj`) -- but `PRODUCT_NAME` and therefore `CFBundleName` are still `Moonlight`, so both drop a `Moonlight.app` into `/Applications` and one replaces the other. A distinct product name is the whole fix and it is ours to make. The cost belongs in the release notes rather than being discovered later: the local-network and input-monitoring grants, the paired identity in the Keychain, and any updater state are keyed to the old name, so existing installs would need to re-grant and re-pair. The upstream reply already promises a new product name. |
| 43 | Store the Windows password and sign in automatically | **deliverable, needs a design first** | Nothing external blocks it: the client already sends a secure attention sequence, so the injection path exists, and the Keychain is already used for the pairing identity. What it needs before any code is a written decision about where a Windows password may live, how it is protected when the Mac is unlocked, and what happens when the host rejects the credential -- a feature that stores a domain password quietly is not one to implement by accident. |

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
2. **22** -- the 10-bit SDR mode, because the exposure gate already exists to prove the
   failure the reporter described.
3. **24** -- replay the attached debug log against a current build; either it closes or it
   becomes the first issue in this table with a reproduction.
4. **43** -- a design note before a pull request.
5. **19, 28, 29, 33, 35** -- nothing to build. These need the diagnostics report the app
   already produces, which suggests the next useful work is making the app offer it
   unprompted after a failure rather than waiting for a menu item.
