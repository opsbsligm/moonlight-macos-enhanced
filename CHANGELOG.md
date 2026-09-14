# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Post-release engineering audit of the v1.3.9-build19 tree. Every item below was
verified against a clean `xcodebuild clean build` and an x86_64 cross-compile on
Apple Silicon hardware.

### Fixed

- **The CI pipeline never started.** `build.yml` carried a step with a name and
  no command, and the step after it with two commands. GitHub loads neither: the
  run after that commit reported failure inside a minute, which is no time at all
  for a job that cross-compiles two architectures, and there was no job list to
  read. A workflow that dies while being parsed leaves no log to diagnose, so the
  pipeline looked broken rather than miswritten. The syntax step in the same job
  reported success throughout, because `yaml.safe_load` tolerates both shapes: it
  keeps the last duplicate key and never asks whether a step can execute. That
  step now runs `scripts/workflow-audit.py`, which checks the nineteen rules a
  plain parse cannot see -- each broken by its own fixture or control, including
  one that proves a reference to a committed script stays quiet -- and it installs
  its own parser,
  because the runner image does not promise PyYAML and a guard that silently loses
  its dependency reports success while checking nothing.
- **The dependency script only ran on macOS.** `download-frameworks.sh` began with
  `#!/bin/zsh`, so on the ubuntu audit runner the kernel could not find the
  interpreter and Python reported the script itself as missing: the constraint
  that runs its layout self-test failed while naming the wrong file, and every
  local run passed because macOS ships zsh. The four scripts that located
  themselves with `${0:A:h}`, a zsh modifier bash reads as an unbound variable,
  now resolve the project directory from `BASH_SOURCE`. `workflow-audit.py`
  rejects any shebang that does not resolve on both kinds of runner, checked with
  a portable, a zsh-only and a missing-shebang control.

- **No key could be held down, and two keys could not overlap.** The key
  equivalent gate in `StreamViewController+MouseCapture.m` ended by calling
  `keyDown:` and `keyUp:` back to back for every key it had not consumed, then
  returned `YES` so AppKit never delivered the event again. Holding `W` therefore
  reached the host as `DOWN,UP,DOWN,UP` from autorepeat instead of one held edge,
  and the `UP` that closed `W` was queued before the next key was read, so a
  second key could never be held alongside it. That is the reported "W and Space
  collide" symptom, and it affected every held key and every combination. The gate
  now returns `NO` for keys it does not consume, so `-keyDown:` and `-keyUp:`
  deliver the two edges separately, which is the contract the branches above
  already used for the keys they deliberately let through.
- **CI never prepared the OpenSSL dependency.** The build job unzipped the
  framework archive with its own inline `curl` step, so `download-frameworks.sh`
  never ran on a runner. That script is the only place that lays down
  `Packages/OpenSSL.xcframework` for the Swift package and the `libs/openssl`
  header symlink for `moonlight-common`, so both inputs were missing and every job
  failed on errors that named neither of them. The build job now runs the same
  script a developer runs. The warning filter had already listed `libs/openssl`,
  which is how the two definitions were known to be expected but never verified.
- **The vendored OpenSSL bundle sat one directory too deep.** A mistargeted unzip
  left `Packages/OpenSSL.xcframework/OpenSSL.xcframework`, so the manifest pointed
  at an outer shell with no `Info.plist` and Xcode kept working only by finding the
  framework inside it. `download-frameworks.sh` now flattens that shell, then
  refuses to report success unless `Info.plist` is where the manifest looks and the
  header symlink actually resolves.
- **The local network probe was defined below its only call site.** The local
  toolchain parses that order without a diagnostic, so a stricter one stops
  compiling the file and nothing in the build warned about it. The probe and its
  two `NSUserDefaults` keys now sit above the `@implementation` that calls them.
- **Fresh clones could not build.** `moonlight-common.xcodeproj` resolves OpenSSL
  headers through `HEADER_SEARCH_PATHS = ../libs/**`, but `libs/openssl` was an
  undocumented hand-made symlink into a SwiftPM debug build directory, and `libs/`
  is gitignored. `download-frameworks.sh` now creates it from the downloaded
  `OpenSSL.xcframework` macOS slice.
- **CI published no artifacts at all.** The workflow requested the
  `macos-26-intel` runner, which GitHub does not offer (macOS 26 requires Apple
  Silicon). x86_64 is now cross-compiled on the arm64 runner; verified locally that
  the vendored `macos-arm64_x86_64` framework slices link a real x86_64 binary.
- **The generated build number never reached the product.** Three separate causes:
  GitLab wrote `GeneratedBuildNumber.xcconfig` to the derivedData root instead of
  the target's `DerivedSources`; GitHub Actions overrode `BUILD_NUMBER` with
  `github.run_number`; and `#include? "$(DERIVED_FILE_DIR)/..."` in
  `Version.xcconfig` does not resolve at xcconfig parse time, so it is inert for
  command-line builds. CI now injects `git rev-list --count HEAD` as a
  command-line build setting, which is the only channel proven to apply.
- **Three first-party compiler warnings** that the v1.3.8 entry already claimed
  were gone: `keyboardTeardownAlreadyCalled` was redeclared `atomic` internally
  while the public header said `nonatomic`; `HIDIsPrintableANSIKey()` was dead
  after the keyboard refactor; the 15-second discovery diagnostic block captured
  the `shouldDiscover` isa ivar implicitly. First-party sources are now
  warning-free and CI enforces it.

### Added

- **The Liquid Glass rules are now executable.** `scripts/liquid-glass-audit.py`
  checks the glass surface for the decisions already made: the native material is
  used and grouped in a `GlassEffectContainer`, no blur, `NSVisualEffectView` or
  system Material stands in for it, the accent stays cold with blue and green above
  red, the shared transition is still 0.22s, no glass path picks its own duration,
  and nothing overshoots and settles back. Its fixture suite breaks each rule on
  its own to prove each one fires. Note that the pixel-level appearance cannot be
  measured from a headless session: `ImageRenderer` returns a flat 502 byte image
  there, and `screencapture` returns black, so that confirmation needs a real
  window session.
- **Release tags are checked against the tree they point at.**
  `scripts/release-gate.py` refuses a tag whose base version is not the project's
  `MARKETING_VERSION`, whose `-buildN` suffix is not the build number this commit
  generates, which has no matching `CHANGELOG.md` section, or which repeats or
  lowers an existing release. The release job runs it before publishing, and the
  audit runs its fixture suite so the rules are exercised even on commits where
  every real tag is correctly blocked.
- `Limelight/build-number.sh --print` emits the resolved build number without
  writing anything, so CI can feed it to `xcodebuild`.
- CI gate that fails a build on new warnings in first-party sources, while
  tolerating vendored OpenSSL umbrella headers and `moonlight-common`.
- `Xcode version` pinned to `latest-stable` instead of `latest` (beta drift).

### Documentation corrections

- The v1.3.8 entry "zero compiler warnings" and the v1.3.9-build19 claim that the
  `Version.xcconfig` baseline and the generated xcconfig "now agree" were both
  inaccurate; the behaviour is now as described and re-verified.
- README build requirements said macOS 15.0+, while the project targets 26.0.

### Second audit pass (input, permissions, CI, settings surface)

#### Fixed

- **Keyboard input discarded real keystrokes.** The three-check synthetic
  keydown detector added in v1.3.9 was redundant: the `MLIsKeyboardKeyEvent`
  type gate in `onKeyboardEquivalent:` already prevents a double click from
  producing a letter, because `keyCode` is undefined on mouse events. What the
  detector did instead was drop keys. Its proximity check discarded every
  keyDown within 120 ms of any mouse button event and never reset the
  timestamp, which is the reported W-plus-space conflict. Its character check
  validated US-ANSI glyphs, so every printable key was dropped on AZERTY,
  QWERTZ, Cyrillic, Greek, Hebrew and Arabic layouts and under any input
  method. Its numeric-pad whitelist omitted the four arrow keys, so arrow keys
  were discarded as synthetic, which is the reported D-pad failure in issue 39.
- **The KingKong axis map was unreachable.** `isXbox` listed product id
  `0x02E0` under the Microsoft vendor id, and `isKingKong` matched the same
  pair, so the callback always took the Xbox branch. KingKong reports the right
  stick on Rx/Ry and the triggers on Z/Rz where Xbox reports the right stick on
  Z/Rz, so every KingKong and Betop Zeus pad was mis-mapped: the issue 25 fix
  announced in v1.3.9 was never actually in effect.
- **The connection diagnostics menu never reset anything.** It invoked
  `/usr/sbin/tccutil`, but tccutil lives in `/usr/bin`; the task launch threw,
  `syncRunTask` swallowed the exception and reported `exit=-1`, so the
  promised `tccutil reset LocalNetwork` never ran while the dialog told the
  user to watch for a prompt that was never re-armed. The same code also
  probed TCC state with `tccutil dump`, and tccutil implements only
  `reset SERVICE [BUNDLE_ID]`, so that report line was noise. It now records
  what the discovery probe actually observed.
- **Both CI architecture jobs failed on one stale literal.** They asserted the
  AWDL helper at
  `Contents/Library/LaunchServices/std.skyhua.MoonlightMac.AwdlPrivilegedHelper`,
  while the build phase names it from `$(PRODUCT_BUNDLE_IDENTIFIER)`, which has
  been `std.skyhua.MoonlightMac2` since the rename. The path it checked has not
  existed for some time. Both jobs now derive the name from the built
  `Info.plist`; verified locally that the derived path exists and the old
  literal does not.
- **`scripts/fix-moonlight-permissions.sh` reported a false Gatekeeper block.**
  It ran `spctl --assess`, which an Apple Development signature always fails by
  design, and then told every user to look for an "Open Anyway" button. It now
  verifies signature integrity with `codesign --verify --strict`. The same
  script also ran `tccutil reset All`, which revokes microphone and input
  monitoring along with local network access; that is now a documented manual
  step rather than something the script does.
- **Thirteen log browser strings had no translation** in either layer and
  rendered as raw keys.

#### Changed

- **Settings is a page inside the main window instead of a second window.** It
  is attached over the content region, hides the toolbar while it is up so main
  window actions cannot fire underneath an invisible page, and switches the
  title. The back control, Escape, Command+W and the window closing all restore
  the previous state, and reopening the same host no longer discards the page.
  Verified on the built product: the titled visible window count stays at one
  while settings is up, the page is a descendant of the content view, and a
  repeated request for the same host does not rebuild it.
- **The settings surface is now genuinely opaque.** The old host set
  `isOpaque = false` with a clear content background and the view used
  `.regularMaterial`, so the page was translucent over whatever lay underneath,
  while its own comments claimed a standard opaque window.
- **`LiquidGlassWindowController` was deleted.** It carried the correct opaque
  configuration and was never referenced by anything.
- **`scripts/fix-moonlight-permissions.sh` accepts the app path as an
  argument** instead of hardcoding `/Applications/Moonlight.app`.

#### Added

- **A repository audit job gates every build job**, running on Linux in seconds:
  localization coverage across both layers, project membership for every
  implementation file, and the constraint set that regressions have actually
  broken (bundle identifier, Bonjour and local-network declarations, network
  entitlements, sandbox state, forbidden tool paths, `waitsForConnectivity`, and
  the stale helper path in CI). Every audit was also checked in reverse with a
  planted violation.
- **Runtime status for the video pipeline is now visible** in the video
  settings pane. The renderer already published the active render path,
  upscaler and interpolator per host, and five localized strings were written
  for it, but no view read them. Interpolation rejection reasons are also split
  apart, so a stream without display cadence headroom no longer looks identical
  to the feature being switched off or unavailable.

#### Verified

- **MetalFX spatial scaling is effective.** The draw path constructs an
  `MTLFXSpatialScaler`, encodes into the drawable and rebuilds it whenever size
  or pixel format changes; the framework is weak-linked with a class-lookup
  guard for older systems.
- **VideoToolbox low-latency frame interpolation is a real implementation**, and
  the refresh-rate gate is a legitimate constraint rather than a defect: Apple's
  `VTLowLatencyFrameInterpolationConfiguration` places no refresh-rate
  requirement of its own, but interpolated frames still need scanout slots, so
  the comparison against `CVDisplayLinkGetActualOutputVideoRefreshPeriod` is
  sound. The practical gap was observability, which is addressed above.
- **No source file was silently excluded from the build.** The project's
  membership exception list is its explicit member list, which is how
  `NetworkPermissionManager.swift` came to sit in the tree uncompiling for
  months; that file is now removed along with its unused strings.

### Third audit pass (pointer concurrency and dead input state)

#### Fixed

- **Relative pointer motion was both dropped and duplicated.** The
  `mouseDeltaX` and `mouseDeltaY` pair was declared `atomic`, which only makes
  each individual access atomic. The GameController callback ran
  `self.mouseDeltaX += deltaX` while the CVDisplayLink output callback read the
  value and then cleared it, so each side performs several accesses. Motion
  added between a read and the clear that followed was erased, and a producer
  that had already read a stale value could write back a sum that dropped
  concurrent motion. Each axis is now a single atomic add on the producing side
  and a single atomic exchange on the consuming side
  (`HIDMouseDeltaAccumulator`). Verified against the implementation extracted
  from the shipping file: the real one producer and one consumer topology and a
  four producer, three consumer topology both conserve every unit of motion,
  while the previous semantics failed the same harness on every run, by up to
  100,000 units out of 1.2 million.

#### Added

- **A build-time behavioural gate for that handoff**, run by every architecture
  job (`scripts/input-concurrency-tests.py`). A compound update on an atomic
  property produces no compiler, linker or test signal, so the check is
  behavioural. It extracts the implementation from `Limelight/Input` so it
  cannot drift away from the code under test, and rebuilds itself against the
  previous semantics to prove it still notices the race.

#### Removed

- **The deferred Command modifier stub and all ten of its call sites.** Its body
  had been two void casts with a comment saying it was kept to avoid touching
  the call sites, so every one of those lines read as though it resolved
  modifier state when nothing had done so since the state machine was removed.
- **`Package.resolved`.** It pinned the remote OpenSSL package while the project
  references a local package whose manifest points at
  `Packages/OpenSSL.xcframework`, and a local package contributes no pins.
  Every command-line build deleted the file, which kept a clean working tree
  permanently dirty.


### Pipeline policy pass

#### Fixed

- **The x86_64 job asked for a runner GitHub does not publish.** It requested
  `macos-26-intel`, which is not an offered image and could never start, and
  macOS 26 does not run on Intel hardware at all. Both architecture jobs now use
  `macos-26-arm64`, the image that exists in the published release list, and the
  x86_64 job cross-compiles on it. Verified locally: building with that
  destination on Apple Silicon produces a binary that `lipo` reports as
  `architecture: x86_64`. The bare `macos-26` label is also avoided because it
  is the spelling that historically denoted an Intel image.

#### Added

- **Least privilege, one live run per ref, and assertions for both.** The
  workflow declared no `permissions`, so every job inherited whatever write
  scope the repository settings happen to allow; it now starts read-only and
  only the release job raises itself to write. There was no `concurrency` group,
  so a second push queued a second full macOS matrix and a tag release could be
  cancelled underneath by a later push. All three policies are now asserted by
  the audit job, and each was planted and reverted to confirm the assertion
  fires rather than passing vacuously.


## [1.3.9-build19] - 2026-08-03

### Phase 2 Milestone — CI/CD & Input Pipeline Overhaul

### Added

- **Deterministic synthetic-keyDown detector** (`MLKeyDownIsSyntheticDoubleClick()`
  in `StreamViewController_Internal.h`): replaces the flaky
  `suppressingKeyboardFromMouseEvent` time-window boolean with a three-check
  evidence-based detector (proximity + character-consistency + spurious-modifier).
  Applied uniformly at all three keyDown entry points:
  `localKeyDownMonitor`, `onKeyboardEquivalent:`, `HIDSupport.keyDown:`.

  > Superseded by the audit above: this detector and its three companions
  > below (`MLMonotonicMillis()`, `MLPrintableANSIKeyCodeMatchesCharacter()`
  > and `lastMouseButtonEventAtMs`) were removed, because the detector
  > discarded real keystrokes. See *Keyboard input discarded real keystrokes*.

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

- `BUILD_NUMBER` baseline in `Version.xcconfig` updated 16 → 19 to match
  `git rev-list --count HEAD` exactly. CI also generates 19 via
  `GeneratedBuildNumber.xcconfig`; both sources now agree, so local and CI
  builds produce identical `CFBundleVersion`.
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
