# Moonlight for macOS — Enhanced Edition

[![Build](https://github.com/opsbsligm/moonlight-macos-enhanced/actions/workflows/build.yml/badge.svg)](https://github.com/opsbsligm/moonlight-macos-enhanced/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/opsbsligm/moonlight-macos-enhanced?label=release&color=blue)](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/opsbsligm/moonlight-macos-enhanced/total)](https://github.com/opsbsligm/moonlight-macos-enhanced/releases)
[![Platform](https://img.shields.io/badge/platform-macOS%2026%2B-lightgrey)](https://developer.apple.com/macos/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

A standalone enhanced macOS client historically originating from [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) which itself derives from the [Moonlight Game Streaming Project](https://github.com/moonlight-stream). Since October 2026 this repository is the independent mainline and no longer syncs with any upstream. The upstream author rejected this fork's PR; the repository now evolves independently with its own direction.

**What differs from the original, in one line**: keyboard and mouse input follow the same industrial-standard mapping used by Parsec, UU Remote and Steam Link, and that mapping is testable and diagnosable. Everything else — codecs, HDR, audio, controllers — is continuously enhanced on top. The mapping table, the design rules and the root causes behind the fixed issues are in [`docs/input-mapping-design.md`](docs/input-mapping-design.md); the head-to-head comparison is in [`docs/input-mapping-benchmark.md`](docs/input-mapping-benchmark.md).

## What it does

- **Core streaming**: GameStream / Sunshine host discovery and pairing; H.265/HEVC & AV1 hardware decoding; HDR with multi-strategy HDR→SDR tone mapping (including `No Exposure Shift`); multi-channel audio plus microphone streaming
- **Video enhancement pipeline**: MetalFX super-resolution and scaling (quality/performance/off), VideoToolbox low-latency frame interpolation, **forced interpolation** (bypasses the display-refresh ≥2× stream-FPS gate, trades 4:4:4 for working FI), runtime-observable render path and engine attachment state
- **Input system**: Core HID high-precision mouse (locked/free-pointer dual modes), fully-repaired industrial-standard keyboard mapping (benchmarked against Parsec/UU Remote/Steam Link), virtual Xbox 360 controller with device identification fixes (Xbox Elite 2, Betop Zeus), clipboard sync
- **Streaming control bar (edge sidebar)**: A handle dockable on any of four edges (14×48pt when collapsed), smart glow/click-to-open/shortcut activation, locked-mode toggle via ⌃⌥C, no remote cursor guessing, auto-timeout return
- **Performance diagnostics**: Real-time performance overlay, video pipeline runtime status panel, input diagnostics recorder, one-tap diagnostics report export
- **USB device diagnostics pane**: Enumerates the local USB bus, attributes each device to a specific reason (reserved class / local input device / no matching rule / precondition unmet), reports whether this build's signature could load a driver extension, reads the host's claim as one of four states (offered / refused / unreachable / never asked)
- **Interface**: Bilingual Chinese/English (menus, permission prompts, log panel, host cards all localised), macOS 27 Liquid Glass frosted-glass design language, Activity-Monitor-style native tab navigation
- **Quality gates**: 60+ behavioural constraint audits (memory leaks, reference cycles, keyboard conflicts, resource leaks, build warnings, etc.), each gate carries its own self-test decoy

## Current limitations

- **No USB device redirection**. The devices pane diagnoses only. Redirection still needs a Developer ID signature ($99/year Apple Developer Program) and a host-side virtual bus (DriverKit DExt) — neither is in place. The trade-off is documented in [`docs/usb-redirection-design.md`](docs/usb-redirection-design.md).
- **macOS 26.0+ required at runtime**. `MACOSX_DEPLOYMENT_TARGET = 26.0` because the Liquid Glass window layer needs it.
- **Ad-hoc signed builds**. Every build needs a first-run allowance under System Settings → Privacy & Security. Notarised Developer ID builds are currently unavailable.
- **Real-world interpolation/SR tuning**. The video enhancement pipeline architecture is complete, but 90fps dynamic interpolation needs ongoing real-stream polishing.

## Host compatibility

| Host software | Compatibility | Notes |
|---------------|---------------|-------|
| [Foundation Sunshine](https://github.com/qiin2333/foundation-sunshine) | ⭐ Recommended | Best support for microphone uplink, YUV 4:4:4, multi-channel audio and two-way clipboard for text and single images |
| [Sunshine (LizardByte)](https://github.com/LizardByte/Sunshine) | ✅ Supported | Most features work; some advanced paths are limited |
| GeForce Experience | ⚠️ Basic | Deprecated, missing newer features such as microphone uplink |

## Download and install

1. Take the newest image from [Releases](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest): `Moonlight-macOS-Enhanced-{arm64,x86_64,universal}.dmg`, each with a matching `.sha256`.
2. Open the DMG and drag `MoonlightEnhanced.app` into Applications.
3. On first launch, allow it under System Settings → Privacy & Security.

> ℹ️ This build installs as `MoonlightEnhanced.app`, so it does not replace the Qt client's `Moonlight.app` (issue #41) and the two can coexist. If `/Applications` still holds a `Moonlight.app` installed by an earlier build of *this* repository, delete it first: both carry the same bundle identifier (`std.skyhua.MoonlightMac2`), so LaunchServices may keep launching the stale copy and permissions follow the old path.

## Building from source

```bash
git clone --recurse-submodules <repo-url>
cd moonlight-macos-enhanced
scripts/download-frameworks.sh   # required before the first build
scripts/build.sh                 # or open Moonlight.xcodeproj in Xcode
scripts/package-dmg.sh
```

Skipping `download-frameworks.sh` makes common-c fail to compile. Xcode and deployment-target requirements are in [`docs/contributing.md`](docs/contributing.md).

## Reporting a problem

1. **Copy the diagnostics report first.** `Settings → App → Debug Log → Copy Diagnostics Report…` puts a paste-ready report on the clipboard, and the pairing-failure popup carries the same button.
2. **If a mouse stopped moving, turn on `Settings → App → Debug Log → Input Diagnostics`, reproduce once, then copy.** The switch has to be on during the reproduction because the ledger only records the session being watched.
3. Then add: which host software and version, whether Mos/BetterMouse/SteerMouse or another pointer utility is running, and the steps next to what you expected.

What the report contains and what is redacted is in [`docs/diagnostics-report.md`](docs/diagnostics-report.md).

## Documentation

[`docs/README.md`](docs/README.md) indexes every document by reader; [`docs/contributing.md`](docs/contributing.md) covers the gates — each one ships with a self-test, because a gate that has never failed is not evidence. Per-release detail with root causes is in [`CHANGELOG.md`](CHANGELOG.md).

## Screenshots

| Host list | App list |
|:---------:|:--------:|
| <img src="readme-assets/images/host-list.png" width="400" alt="Host list"> | <img src="readme-assets/images/app-list.png" width="400" alt="App list"> |

| Performance overlay | Connection manager |
|:-------------------:|:------------------:|
| <img src="readme-assets/images/performance-overlay.png" width="400" alt="Performance overlay"> | <img src="readme-assets/images/connection-manager.png" width="400" alt="Connection manager"> |

| Streaming overlay | Connection error |
|:-----------------:|:----------------:|
| <img src="readme-assets/images/streaming-overlay.png" width="400" alt="Streaming overlay"> | <img src="readme-assets/images/connection-error.png" width="400" alt="Connection error"> |

## Contributing

Fork → feature branch → commit in [Conventional Commits](https://www.conventionalcommits.org/) form → pull request. The gate list (60+ behavioural constraints, each with its own self-test decoy), commit types and version/tag conventions are in [`docs/contributing.md`](docs/contributing.md). CI/CD runs the full gate suite on every push; the release gate blocks publishing until all checks pass.

## Licence

GPL-3.0 — see [LICENSE](LICENSE). Bundled third-party components: moonlight-common-c (GPLv3, as a Git submodule), OpenSSL (Apache 2.0), FFmpeg (LGPLv2.1+), SDL2 (zlib), MASPreferences (BSD-2-Clause), Roboto Font (Apache 2.0).

## Acknowledgements

- [Moonlight Game Streaming Project](https://github.com/moonlight-stream) — the original upstream
- [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) — the origin this project started from (now independent)
- [opsbsligm/moonlight-macos-enhanced](https://github.com/opsbsligm/moonlight-macos-enhanced) — the current independent home
- [Parsec](https://parsec.app) — reference for keyboard-mapping practice
- Every contributor and test player
