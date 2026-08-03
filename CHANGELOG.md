# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.9-build19] - 2026-08-03

### Phase 2 Milestone — CI/CD & Input Pipeline Overhaul

### Added

- **Deterministic synthetic-keyDown detector** (`MLKeyDownIsSyntheticDoubleClick()`
  in `StreamViewController_Internal.h`): replaces the flaky
  `suppressingKeyboardFromMouseEvent` time-window boolean with a three-check
  evidence-based detector (proximity + character-consistency + spurious-modifier).
  Applied uniformly at all three keyDown entry points:
  `localKeyDownMonitor`, `onKeyboardEquivalent:`, `HIDSupport.keyDown:`.
- **`MLMonotonicMillis()`**: mach-time-based monotonic timestamp for the
  proximity check, immune to wall-clock drift.
- **`MLPrintableANSIKeyCodeMatchesCharacter()`**: validates that the
  `charactersIgnoringModifiers` of a keyDown event matches the expected US-104
  ANSI glyph for the keyCode — synthetic events from mouse double-click fail
  this check.
- `lastMouseButtonEventAtMs` property on `StreamViewController` — every mouse
  button handler (left/right/other × down/up) updates this timestamp.
- `en.lproj/Localizable.strings` and `zh-Hans.lproj/Localizable.strings` now
  include all control center menu items (Issue #30).
- CI/CD: `build-number.sh` no longer overwrites the git-tracked
  `Version.xcconfig`. `#include?` directive added to pull
  `GeneratedBuildNumber.xcconfig` from `DERIVED_FILE_DIR`.
- CI/CD: `package-dmg.sh` is now the single source of truth for DMG naming.
  `.gitlab-ci.yml` no longer passes a CI-specific DMG name.

### Changed

- `BUILD_NUMBER` baseline updated 16 → 18 (fallback); CI generates 19 from
  `git rev-list --count HEAD` via `GeneratedBuildNumber.xcconfig`.
- `Version.xcconfig` now includes a comment explaining the
  `#include? GeneratedBuildNumber.xcconfig` override mechanism.
- `build-number.sh` fallback path removed — script always writes to
  `DERIVED_FILE_DIR` (or a derived default), never pollutes the working tree.

### Fixed

- **"Double-click left mouse sends C key" (root cause fix)**: The old
  `suppressingKeyboardFromMouseEvent` flag was written from 3+ locations,
  used a 300ms time-window that could expire or be reset by rapid clicks,
  and only checked `MLIsPrintableANSIKeyCode` + `!Command`. The new
  deterministic detector uses three independent evidence checks that cannot
  be defeated by forged events.
- **Modifier key sticking on space switch** (Issue #37+#19): added
  `[self.hidSupport releaseAllModifierKeys]` in `activeSpaceDidChangeObserver`.
- **Gamepad mapping for Xbox Elite 2 / Betop Zeus** (Issue #25): extended
  `isXbox()` to match 0x0B00/0x0B05/0x0B22; added `isKingKong()` for
  Betop Zeus VID 0x2DC8.
- **UI crash in `viewDidLayout`** (Issue #26): wrapped
  `bringStreamControlsToFront` in `@try/@catch` defensive guard.
- **Window hover steals focus** (Issue #21): removed
  `[NSApp activateIgnoringOtherApps:YES]` from global mouse monitor.
- **Control center menu not localized** (Issue #30): all hardcoded Chinese
  strings replaced with `MLString()` calls.
- **First click lost after stream start**: ensured window is key + app is
  active before `captureMouse` in `viewDidAppear` and `connectionStarted`.
- **NetworkPermissionManager violating tccutil**: removed
  `tccutil reset LocalNetwork` call (destructive privacy reset).

### Removed

- `scheduleKeyboardSuppressionClear` method and all call sites (legacy
  300ms timer-based suppression).
- `keyboardSuppressionClearToken` active usage (property retained as no-op
  for binary compatibility).

## [1.3.9] - 2026-08-02

### BREAKING CHANGES

- **Removed all 6 legacy keyboard compatibility modes.** The following modes
  have been deleted entirely and are no longer selectable in Settings:
  - `CommandToControl` ("⌘ Always as Ctrl")
  - `SwapLeftControlAndWin` ("Left Ctrl ↔ Left Win")
  - `ShortcutTranslation` ("Mac Shortcuts as Windows Shortcuts")
  - `Hybrid` ("Windows Shortcuts + Left Ctrl ↔ Left Win")
  - `MoonlightClassic` ("Moonlight Classic Mapping")
  - `Standard` ("Keep Mac Shortcuts")
- Any persisted user preference for a legacy mode is silently remapped to
  the new single `StreamingStandard` mode via `init(persistedRawValue:)`.

### Added

- **KeyboardMapResolver** (`Input/KeyboardMapResolver.h/.m`): a new
  stateless, table-driven module that serves as the single source of
  truth for macOS-to-Windows modifier key mapping.
- Diagnostic function `KMR_LogActiveMapping()` that prints the full
  mapping matrix at stream start for CI verification.
- `LICENSE` file declaring GPLv3 with third-party component attributions.
- `README.md` with project overview, mapping table, build instructions,
  and contribution guidelines.
- `CHANGELOG.md` (this file).

### Changed

- Keyboard mapping is now the **Streaming Standard** (Parsec / UU Remote
  / Steam Link convention):

  | macOS | Windows |
  |:---:|:---:|
  | Command (⌘) L/R | Win (VK_LWIN 0x5B / VK_RWIN 0x5C) |
  | Control (⌃) L/R | Ctrl (VK_LCTRL 0xA2 / VK_RCTRL 0xA3) |
  | Option (⌥) L/R | Alt (VK_LALT 0xA4 / VK_RALT 0xA5) |
  | Shift (⇧) L/R | Shift (VK_LSHIFT 0xA0 / VK_RSHIFT 0xA1) |

- Settings UI keyboard section now shows a single unchangeable option
  labelled "Streaming Standard (Recommended)".
- Bumped `MARKETING_VERSION` 1.3.8 → 1.3.9, `BUILD_NUMBER` 11 → 12.

### Fixed

- **Root cause of "double-click left mouse opens Windows Start menu"**:
  `HIDEffectivePhysicalModifierMaskForEvent()` previously inferred physical
  modifier state from `event.modifierFlags` for ALL events, including mouse
  events. When a user held ⌘ and clicked, the mouse event carried
  `NSEventModifierFlagCommand`, which got force-injected into the physical
  mask and triggered a spurious `VK_LWIN` DOWN to the remote host. The
  function now returns the physical mask as-is, ignoring
  `event.modifierFlags` entirely.
- **"Ctrl / Option / Win keys don't respond"**: the 4 duplicated
  switch/case blocks that previously defined modifier mappings had
  inconsistent mode branches, causing some keys to be silently dropped
  under certain modes. All paths now route through `KeyboardMapResolver`'s
  single static table.
- Removed `MLDeferredCommandStateMachine` and its 120ms timer race that
  caused intermittent modifier-key desync under rapid input.
- Removed `keyboardDeferredShortcutTranslationCommandMask` property and
  all `begin/endDeferredShortcutTranslation` logic from `HIDSupport`.
- All 20+ `resolveDeferredCommandModifierWithoutRemoteTapWithReason:`
  call sites in `StreamViewController+MouseCapture.m` are now permanent
  no-ops; mouse and keyDown paths no longer touch deferred state.

### Removed

- `MLDeferredCommandStateMachine` class (entire file section deleted).
- `KeyboardCompatibilityMode` enum cases: `standard`, `commandToControl`,
  `swapLeftControlAndWin`, `shortcutTranslation`, `hybrid`, `moonlightClassic`.
  Replaced by `streamingStandard = 0`.
- `KMR_ModeFlags` type and all mode-flag parameters from
  `KeyboardMapResolver` API.
- `KMR_DescribeModeFlags()` and `KMR_EnsureInvariants()` functions.
- `keyboardDeferredShortcutTranslationCommandMask` property from
  `HIDSupport_Internal.h`.

## [1.3.8] - 2026-08-01

### Added

- CI/CD best-practice hardening pass: zero compiler warnings.
- Network permission manager for macOS local network access prompts.
- Connection robustness improvements for first-time install and version
  upgrades.
- `fix-moonlight-permissions.sh` script for resetting broken permissions.
- `.gitlab-ci.yml` CI pipeline configuration.
- AWDL privileged helper for Apple Wireless Direct Link discovery.

### Changed

- Improved connection watchdog with 15s timeout and automatic retry.
- Enhanced diagnostics logging for connection failure analysis.
- Streamlined DiscoveryManager and MDNSManager for faster host discovery.

## [1.3.7] - 2026-07-26

### Added

- Initial enhanced edition based on Moonlight for macOS upstream.
- Core HID mouse driver for high-precision input.
- Liquid Glass UI components.
- Performance overlay with real-time stats.
- Edge menu for quick access during streaming.
- Borderless windowed mode.
- Clipboard sync support.
- Physical wheel scroll modes (automatic / notched / high-precision).

[Unreleased]: https://github.com/skyhua/Moonlight-macOS/compare/v1.3.9-build19...HEAD
[1.3.9-build19]: https://github.com/skyhua/Moonlight-macOS/releases/tag/v1.3.9-build19
[1.3.9]: https://github.com/skyhua/Moonlight-macOS/releases/tag/v1.3.9
[1.3.8]: https://github.com/skyhua/Moonlight-macOS/releases/tag/v1.3.8
[1.3.7]: https://github.com/skyhua/Moonlight-macOS/releases/tag/v1.3.7
