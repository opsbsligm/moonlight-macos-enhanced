# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Post-release engineering audit of the v1.3.9-build19 tree. Every item below was
verified against a clean `xcodebuild clean build` and an x86_64 cross-compile on
Apple Silicon hardware.

### Fixed

- **A key consumed locally still released itself on the host.** AppKit only asks
  the key-equivalent question on `keyDown:`, so every branch that swallowed a key
  -- the translation rules, the borderless and control-centre shortcuts,
  disconnect, quit, reconnect, and `Command+W` -- still had its `keyUp:` delivered
  and forwarded. The host was told a key came up that it never saw go down, which
  is what makes a local shortcut look like the game letting go of a key
  mid-action. Consuming a key now records it; the matching release is consumed as
  well; a forwarded press of the same key clears the record, so a stale entry can
  never stick a key down on the host; and session teardown drops the table.
- **Typing in settings moved the character on the host.** The settings page is a
  child of the stream content region, so any key the page did not use walked the
  responder chain back to the stream view and was forwarded to the machine. While
  the page owns the region those keys are kept locally and recorded as consumed,
  so their releases pair as well.

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
  a portable, a zsh-only and a missing-shebang control. The port initially left
  `${=ARCHS}` behind in the helper build phase, which is zsh forced word splitting
  and fails at run time under bash, so `bash -n` reported nothing and both
  architecture jobs died in that step; the loop now splits the way bash splits,
  verified by running the phase with `ARCHS="arm64 x86_64"` and reading the two
  slices back with `lipo`, and the audit rejects zsh-only syntax in any script
  that no longer runs under zsh.
- **A clean checkout never downloaded the frameworks.** `download-frameworks.sh`
  decided the frameworks were present by asking whether `xcframeworks/` was
  non-empty, and the repository commits `xcframeworks/.gitignore` so the
  directory exists in the first place. Every clean checkout therefore skipped the
  download, and the next step failed with no explanation: the header search passed
  a root that did not exist to `find`, which fails the pipeline under
  `set -euo pipefail` before the script's own error message can print, and
  `head -n 1` aborts the same way when it closes the pipe early. Readiness is now
  judged per bundle, each with its own `Info.plist`; each search root is tested
  before use; and the self-test covers the placeholder directory, a complete tree,
  a bundle missing its manifest, an absent search root, a truncated search, and
  both header spellings resolving.

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


### Fourth audit pass (capture-end key debt and measured capabilities)

- **A key that was still held when capture ended stayed pressed forever.**
  Releasing the mouse set `shouldSendInputEvents = NO`, and `keyUp:` forwards only
  while that flag is on, so the release of an action key held at that moment never
  reached the host; session teardown released the eight modifiers and the mouse
  buttons but never an ordinary key. Holding a movement key and pressing the
  capture shortcut left the remote holding that key for the rest of the session.
  Every key code forwarded as a press is now recorded in the encoding it was sent
  in, spent on a forwarded release, and replayed as a release from the uncapture
  funnel and from teardown.
- **Stored configuration could take a bare gameplay key from the host.** The
  responder gate, the keyboard translation matcher, and an `NSMenuItem` key
  equivalent all consume the key they match, and each of them decided from stored
  shortcuts whether a press was theirs, so a binding without a modifier would
  silently delete W or Space. The settings form rejects such a binding, which is
  why it survived review; the hot path no longer relies on that. One predicate now
  requires at least one relevant modifier at all three sites.
- **Three video capabilities claimed hardware that is not present.** MetalFX
  availability asked the operating system version; low-latency interpolation and
  low-latency super resolution asked `isSupported`. Measured on an Apple M2
  (macOS 27 build 26A428): `VTLowLatencyFrameInterpolationConfiguration.isSupported`
  is true, the configuration is created, `startSessionWithConfiguration:` succeeds,
  and the configuration reports zero interpolation slots, while the low-latency
  scaler's supported scale factors are empty at 1920x1080 and offer only 1.5 at
  1280x720 with a 2x configuration refusing to be created. Interpolation now
  counts the slots across 720p, 1080p and 4K, super resolution reads the supported
  scale factors per size, and MetalFX asks the device. The probe prints both the
  support property and the measured facts on every run.
- **Release preparation became a command instead of a scramble.** The gate refuses
  a tag with no `CHANGELOG.md` section, and `BUILD_NUMBER` is
  `git rev-list --count HEAD`, so the tag for a commit is derivable from it.
  `scripts/prepare-release.py` prints that tag, relays the gate's objections, and
  promotes the Unreleased heading only when the changelog is the sole objection.
- **Assertions now have to fail to be believed.** `scripts/assertion-battery.py`
  applies 22 realistic regressions to the real source -- a guard prefixed with
  `NO &&`, a guard missing its return, a clear moved after the dispatch, a held-key
  set left nil so records fall into a nil receiver, a modifier floor of zero, a
  capability that trusts `isSupported` -- and CI fails unless every one of them is
  caught. Constraint coverage reached 64 checks at that point.

### Fifth audit pass (unmapped key codes)

- **A key with no mapping was forwarded as virtual key 0.**
  `translateKeyCodeWithEvent:` answers 0 when the table has no entry, and callers
  used that value as if it were a key code. 0 is not a Windows virtual key, so
  the host received a press for a key that exists on no keyboard and had no
  matching release path for it. Measured on this Mac: `kVK_ISO_Section` (10) and
  `kVK_ContextualMenu` (110) have no rows, and every code a newer keyboard adds
  reaches the same path. Both edges now refuse zero before dispatch, and the two
  missing rows are in the table -- the press that is ignored on the way down is
  ignored on the way up, so the pair stays paired.
- **The table itself is now under test.** `scripts/mac_keycodes.py` records the
  virtual key codes from the SDK header, and the audit parses the table and
  requires that every code a game can bind has a row, that no physical code
  appears twice (the dictionary build in `init:` keeps the last row and drops the
  earlier one in silence), and that no row maps to zero. The mutations added
  with these checks are a zero guard neutered on each edge, the space row
  deleted, and a duplicated row.

### Sixth audit pass (a gate that could not see)

- **The localization gate checked nothing on the CI runner.** It scanned the
  sources with `grep -rhoE` and a pattern containing a `(?:` group. BSD grep on
  macOS accepts that and the local run reported 162 keys; the ubuntu audit
  runner's grep produced nothing, its stderr was captured and thrown away, and
  the step printed "0 keys referenced in code" followed by "localization
  coverage is complete on both sides". Both missing-key lists were empty because
  nothing had been scanned. The scan now reads the sources itself, and
  `scan_health()` refuses an empty scan: call sites counted as plain text with no
  keys found can only mean the scanner is blind, and that is a failure, not a
  clean tree.
- **153 call sites were invisible to it as well.** `NSLocalizedString` and
  `MLString` are ObjC macros over the same lookup and every one of their call
  sites passes an `@"..."` literal, while the pattern allowed only a bare quote,
  so those keys were never compared against either layer. Two of them,
  `Reconnecting…` and `Reconnecting… (%ld)`, have no entry in either table and
  rendered as the raw English key in the reconnect overlay; both are now
  translated. The audit sees 259 keys instead of 162.
- **A gate whose proof can be switched off is not a gate.** The localization
  self-test has no opt-out, and `scripts/assertion-battery.py` now judges a
  mutation by the gate that is supposed to notice it, so the localization audit
  is exercised by three of its own regressions: a health rule that always
  accepts, a pattern that loses the `@"..."` branch, and a scan that shells out to
  the host grep again. Constraint coverage reached 74 checks and the battery 29
  mutations at that point.

### Seventh audit pass (what the static analyzer found)

- **A synthesized key event leaked on every gamepad navigation press.**
  `CollectionView.m` and `NavigatableAlertView.m` each built a CGEvent to hand a
  gamepad button to the responder chain and released nothing, so browsing the app
  list with a controller leaked one event per press, in the class whose only job is
  controller navigation. Both release it now, after `eventWithCGEvent:` has copied
  what the responder needs.
- **Three copies of one path helper disagreed about ownership.** Each built a
  `CGPathRef` and returned a +1 reference under a name that did not say so. The
  callers in `StreamViewController+Diagnostics.m` and `MLEdgeMenuUI.m` released it;
  the caller in `AppCell.m` assigned it to `CALayer.shadowPath` and leaked a path
  on every shadow refresh. The helpers now carry `CF_RETURNS_RETAINED`, which is
  the compiler's version of that sentence, the leaking caller releases, and the
  audit refuses a path-returning method that stays silent about ownership.
- **The HID manager could outlive the object its callbacks point into.** It is a
  CoreFoundation reference this project owns by hand -- clang does not manage a CF
  typed property, checked by compiling a probe and reading the absence of
  `objc_storeStrong` -- and only `tearDownHidManager` dropped it. `dealloc` now
  unschedules, closes and releases it: left scheduled with four callbacks whose
  context is a freed `HIDSupport`, that is a use-after-free on the next gamepad
  event rather than merely a leak.
- **The stored gamepad state could hold stack garbage.**
  `controllerStateFromGamepad:` declared its struct without initialising it while
  the thumbstick copy lines are commented out, so the "previous state" carried
  uninitialised bytes; re-enabling those comparisons would read them back as
  thumbstick presses.
- **`xcodebuild analyze` is a required job now.** `scripts/analyzer-audit.py`
  compares findings with `scripts/analyzer-baseline.json` by file, checker and
  message shape, counted, so a new class fails, one more instance of an accepted
  class fails, and a finding that got fixed fails until someone reads it and
  refreshes the baseline. It refuses a sweep that did not run -- an analyzer that
  analysed nothing reports nothing, which is the same silence this repository has
  been bitten by twice -- and the battery plants a mutation against each of its
  three rules.
- Accepted findings are recorded with their reason: an NSNumber nil test that the
  retain-count checker reads as a boolean conversion, a VideoToolbox parameter
  Apple documents as pass-NULL while the header marks it nonnull, and a CG colour
  reference kept in an assign property. The baseline also freezes 81 hard-coded
  user-facing strings across five view controllers, which are now unable to grow
  and are waiting for a translation pass.

Coverage after this pass is 80 constraint checks and 35 planted mutations, of
which five belong to the analyzer findings fixed here: a leaked key event, a path
helper that stops declaring ownership, a HID manager left alive, an analyzer sweep
that silently stops running, and a baseline that accepts anything.

### Tenth audit pass (the two visual claims stopped waiting for a human)

- **The embedded settings page is now proven at runtime, not in source.** The
  goal that settings should live in the same interface as the stream, and the goal
  that the surface should read as Liquid Glass, had both been answered with "needs
  a human eye" for several passes while the machine sat running a build from before
  the work. A gate that cannot see is not a gate, so the app now carries a
  Debug-only entry point, inert unless `ML_RENDER_PROBE` is set, which drives the
  production `SettingsOverlayPresenter` through the production call against a
  window of its own and measures what happened; `scripts/render-probe.py` builds
  that Debug binary, runs it with `HOME` pointed at a scratch directory so the
  database and preferences under test are the probe's own, and reads the report.
  On this machine the report says: no window opened, the page arrived as exactly
  one view inside that same window's content view, the fade finished to alpha 1,
  dismissal unmounted it and cleared the presenter's record, the page drew real
  pixels, and four `CABackdropLayer` instances are composited inside it. The
  rendered page was inspected as a PNG and is legible: back control, the five-pane
  tab bar, localized Chinese strings, popups and switches.
- **Two measurements that were wrong, corrected before they could mislead.** The
  first glass check counted AppKit views whose class name contains "Glass" and
  passed -- on the hosting view's own name, which merely contains
  `LiquidGlassSettingsView`. The second swapped the backdrop under the page and
  refused when nothing moved, which would have failed the shipping code: the page
  sits on a deliberate opaque base, so its materials read the page's own content
  rather than the window behind it, and zero read-through is the designed
  behaviour. Materials are now measured where they actually exist, in the Core
  Animation layer tree, and read-through is reported without being asserted.
- **The analyzer gate caught the new probe on its first run, and the probe was
  wrong to object.** `NonLocalizedStringChecker` reported one more user-facing
  string than accepted, in the probe's own `window.title = @"render-probe"`. The
  title bought the probe nothing and a diagnostic window that never outlives its
  own process has nothing to title, so the string was deleted rather than the
  baseline widened; the run then matched the accepted 106 findings again. Worth
  recording because it is the gate behaving as designed on code written to make
  the gate better.

- **The verifier is checked for teeth**: eight doctored reports -- a second
  window, a page that is not inside the content view, two pages stacked, a fade
  that never finished, a page left mounted after dismissal, a blank capture, no
  material layer, an empty report -- are each refused. The wiring rule now covers
  `-probe.py` as well, so a probe that exists but is never run is itself a failure.
- **What this still does not prove**: how the material looks over a live stream.
  The probe composites the real view tree; it cannot judge taste, and the pixel
  check here deliberately stops short of asserting a backdrop read-through it
  cannot justify.

### Ninth audit pass (the two-key report, made checkable)

- **Walking and jumping at the same time is now a scenario CI runs.** The report
  that started this project was not a crash but a game: W and Space together,
  the two most basic inputs there are, behaved as if one key interfered with the
  other. Nothing in a build, a warning, or a review can see that -- a held-key
  table with exactly the right words in it can still tangle two concurrent keys,
  which is what several shipped regressions did. `scripts/keyboard-concurrency-tests.py`
  extracts the keyboard state machine from `HIDSupport.m` verbatim, compiles it,
  and drives it with real `NSEvent`s through the same calls the stream window
  makes. It covers both release orders of a W/Space pair, a press the settings
  page kept while another key was legitimately forwarded, a flush that must not
  invent a release for a key the host never saw pressed, two keys held when input
  forwarding is switched off, an auto-repeat, and a second flush. The harness is
  then run against the pre-fix shape -- one slot for "the key we forwarded last"
  -- and has to reject it, so the scenarios cannot silently stop meaning anything.
- **Two probes settled what belongs to AppKit and what belongs to us.** A window
  offscreen answered `acceptsFirstResponder=0` for both the view controller and
  its view, yet `makeFirstResponder:` still returned YES and the responder chain
  delivered `keyDown:13, keyDown:49, keyUp:49, keyUp:13`: AppKit does not steal
  Space or W in this topology, and does not merge them. Menu items, the other
  place a key can vanish before the stream view sees it, are already guarded by
  the modifier floor in `menuKeyEquivalent(for:)`. With the state machine passing
  every two-key shape above, the current tree handles the reported pair correctly
  on the evidence available; the symptom matches the build still running on the
  machine, which predates the input work and has never been replaced.
- **A gate nobody wired is now a failure.** Every audit and harness in `scripts/`
  has to be reachable from the workflow, directly or through another reachable
  script (`release-gate --self-test` legitimately drives the preparation
  fixtures, and those fixtures exist only to satisfy that gate). Unplugging the
  keyboard gate from the workflow is now one of the planted regressions: 38/38
  caught.
- **The harnesses ask xcrun for the macOS SDK by name.** A bare
  `xcrun --show-sdk-path` answers with the Command Line Tools copy on this
  machine, whose `.tbd` files the Xcode linker rejects with "unknown architecture
  arm64e.x1"; a gate that fails for that reason reads like broken code and gets
  silenced rather than fixed.

### Eighth audit pass (a version number that depended on the clone)

- **The build number was a property of the working tree, not of the commit.**
  The universal DMG CI published for a commit carries `CFBundleVersion` 1407,
  while the release tool on the same commit named it `v1.3.9-build71`, and the
  gate that promotes the changelog heading raised no objection. A release cut
  locally would have tagged a build no binary ever carried, and the mismatch
  was invisible until the package already existed.
  Root cause: two places computed the number independently. `build-number.sh`
  injects it for CI, and `prepare-release.py` counted commits again with its own
  `git rev-list --count HEAD`. The working tree is a shallow clone, so that
  second count returned the size of the shallow window (71) rather than the
  history (1407); CI checks out with `fetch-depth: 0`, so only the local number
  was wrong, which is the wrong one to be wrong, because the local number is the
  one that writes the changelog heading and the tag.
  Fix: `--print` now refuses a shallow clone instead of reporting its depth; the
  PreAction path still writes its baseline, so building in the IDE is unchanged.
  `prepare-release.py` asks that script, so one number has one owner and the
  refusal is inherited rather than duplicated. `release-gate.py --self-test`
  builds a three-commit repository, clones it at depth one and requires the
  refusal, and requires the complete clone to still print 3 -- a wording check
  would have passed on a guard that never ran. Two constraints pin both halves
  and the battery plants each one: 37/37 mutations caught. Unshallowing the
  working tree then reproduced the CI figure exactly, which is how the fix was
  confirmed rather than assumed.
- **Checked, not changed: the frameworks CI ships are unsigned.** OpenSSL inside
  the CI package has no signature at all, while the copy in a locally built app
  is `adhoc,runtime`. A `dlopen` probe built for arm64 loads the unsigned copy
  without error, because the main binary is linker-signed adhoc and does not ask
  for library validation, so this does not break launching and no code was
  changed for it. It does mean the package cannot be notarised and a downloaded
  DMG needs to be opened once through Finder's Open menu.

### Eleventh audit pass (what the page says, and where it was read from)

- **What the settings pages display is measured now, not read off a screenshot.** The
  video page's capability wording, whether its two enhancement controls are live, and
  the eleven rows of the capability matrix had been signed off by looking at a captured
  image. The app now answers those questions itself: a Debug-only class forwards the
  rules the panes actually read, from the model the page is rendering from, and
  `scripts/render-probe.py` refuses any report whose expectation did not come from that
  model (`expectationsFromPageModel`), because two models built at different moments of
  launch disagree and every comparison then happens between two different machines.
  Reaching the text needed the in-process `NSAccessibility` protocol:
  `AXUIElementCreateApplication(getpid())` asked from inside the process it queries
  returns the application element referring to itself, no window and no text, on any
  thread and with any amount of run-loop pumping; issuing that one request is enough to
  wake AppKit's own tree, which is what the pass walks instead. It runs after
  `applicationDidFinishLaunching:`, because asked during
  `applicationWillFinishLaunching:` the tree is a placeholder for a page that was
  visibly drawing text, and a control carries no label of its own, so each row is
  paired with the nearest pop-up button to the right of its title at the same height.
- **A Debug-only Swift file was never Debug-only.** The project defined no
  `SWIFT_ACTIVE_COMPILATION_CONDITIONS` anywhere, so `#if DEBUG` in a `.swift` file
  compiled to nothing while the Debug configuration defined `DEBUG=1` for C-family
  sources, whose half of the same feature kept compiling and calling a Swift class that
  had never been emitted. A Release build shows nothing wrong, because in Release the
  code is absent on both sides. The rule is now stated as the shape that was actually
  broken -- if Debug names `DEBUG` for one language it has to name it for the other --
  and not as "if a Swift file says `#if DEBUG` then check": that first version read as
  clean at the commit which added the build setting, because with no Debug-only Swift
  file present it had nothing to examine and the mutation planted against it went
  uncaught. 42/42 mutations are caught now. The shipped binary was also read rather
  than reasoned about: the Release binary carries no probe entry point, no probe
  strings and no expectation class, while the Debug build, whose code lives in
  `Moonlight.debug.dylib`, carries all three.
- **CI went red on the capability matrix while this machine kept saying green, and both
  readings were correct.** The matrix sits in a `DisclosureGroup` whose state is stored
  under `settings.app.videoCapabilityStatusExpanded` and defaults to collapsed, and a
  collapsed SwiftUI group vends nothing inside it. A clean launch vends 50 readable rows
  on the app page and none of the eleven matrix rows exist in the tree at all; a machine
  where somebody opened that section once vends 84 rows and the same check passes. The
  pass now starts with that preference forced off, so every run faces what a first run
  faces, and restores it afterwards; it decides the state from the label the page itself
  displays, taken through the page's own wording rather than a literal baked into the
  probe, because pressing a disclosure that is already open shuts it; and it presses
  the triangle the way a pointer does, then reads again and asserts the matrix against
  that reading alone. One triangle is found and one pressed -- counted by identity,
  because until then the walk reached the same hosted element through the accessibility
  children and through the view tree and reported 65 triangles for the one section the
  page has, and sixty-five presses would have looked like a pass. Here 50 readable rows
  become 84; the merged text of every pass is what had let the claim survive, since a
  machine that never opened the section and one that did are indistinguishable in a
  union. Five further doctored reports are refused for this path and the self-test
  refuses 24 in all, and a constraint pairs the preference the probe forces with the
  string the app page stores it under, so a rename cannot leave the probe shutting a
  preference nobody reads.
- The folder a hand-off package is written into, `dist/`, is ignored. `*.dmg` already
  was, which left the checksum line in `git status` on every session and taught a
  reader to skim past the output that is supposed to show an uncommitted change.

### Twelfth audit pass (wording that decided behaviour)

- **Three buttons on the connection-timeout overlay did nothing at all in the
  English interface, and had done so since the day they shipped.** The overlay offers
  Resolution, Bitrate and Display Mode by popping up the stream menu's Monitor,
  Quality and Window submenus. It found them by comparing each item's title against a
  Chinese literal, and the titles come out of the language table, where `Monitor`
  reads 屏幕 and `Window` reads 窗口. In the Chinese interface the comparison held; in
  English the loop matched nothing, `popUpMenuPositioningItem:` was never reached, and
  the buttons returned without a crash, without a log line and without a build
  failure. Any check that read the source for the word it compared against stayed
  satisfied the entire time. The three items are now built with an integer tag and the
  overlay asks for that tag, and `scripts/stream-menu-addressing-tests.py` compiles the
  lookup that ships, hands it menus wearing both languages' titles, and rebuilds the
  title comparison to show that it still finds nothing in English.
- **A file with no localization macro shipped its strings untranslated.** `MLString`
  was a `#define` inside `StreamViewController_Internal.h`, so only the stream files
  could use it: `AppDelegateForAppKit` and `ConnectionEditorViewController` had no
  macro and passed bare literals to the UI, `HostsViewController` `#undef`-ed
  `NSLocalizedString` and re-pointed it, and `ContainerViewController` called the
  manager inline and produced `localize:MLString(...)`, which asks the table twice and
  returns the second answer. One header, `Limelight/macOS/Localization.h`, owns the
  macro now, and 108 more call sites go through it. While doing that the two tables
  were read instead of counted: each declared 23 keys more than it had, and the plist
  keeps the last of a repeated pair, so the entry above it was dead text every reader
  of the file believed was live -- seven Chinese keys carried two competing answers
  each, including `Audio` (音频 or 声音) and `Balanced` (常规 or 均衡), and whichever
  line happened to come last was what users read. Three keys had also drifted onto one
  side only. Both tables now declare 862 keys, once each, identically.
- **A button could get stuck reading "Copied" forever.** The feedback after copying
  the log scheduled its own undo and then asked the button whether it still read
  `Copied` before putting the previous title back. Click the button twice within the
  1.5 seconds and the second click recorded "Copied" as the title to restore. Switch
  the interface language within those 1.5 seconds and the comparison never matched at
  all. The button now carries which click owns it, and only that click puts its title
  back.
- **Pairing decided whether to retry by reading its own error message.** It reported a
  failure as one sentence, and `HostsViewController` lowercased it and searched for
  "timeout", "timed out", "network", "disconnected", "connection" and three Chinese
  phrases to decide whether the failure looked transient enough to try a second
  address. The object that wrote the sentence already knew: it tested `statusCode`
  against `NSURLErrorTimedOut`, and one line earlier tested the same field for a
  negative value to decide whether to undo the pairing. One fact drove two decisions
  and only one of them read it. Pairing reports a `PairFailureReason` now, the retry
  reads that, and the five sentences the network layer carried have moved to the file
  with a language table behind them.
- **The log browser folded repeated warnings by looking for a Chinese fragment in a
  different file.** `Logger.m` wrote its suppression summary as prose and the browser
  matched `内重复`, so rewording the summary switched the folding off with nothing
  printed anywhere. The marker between the two is ASCII now, and a constraint reads it
  from both ends.
- **Five alert and report strings showed `\n` on screen instead of breaking a line.**
  Four carried an escaped backslash-n inside an `NSAlert`, and a fifth used a real
  newline against a table key that spelled it escaped, so that key never found its own
  translation and the diagnostic report header stayed untranslated in both languages.
- **The localization gate could not read a long key, and reported three of them as
  missing translations.** Its pattern stopped at 120 characters, so alert strings of
  121, 140 and 161 characters were looked up as their own prefix -- and the cap was the
  real defect, because a key too long to read could only ever be reported as absent,
  never as unread. Keys are read one character or one escape pair at a time now, which
  also stops an escaped quote from splitting a key in two; both shapes are self-test
  cases. The gate also refused to notice 23 repeated declarations per table and three
  keys declared on one side only, because it compared sets and never counts.
- **The static analyzer stopped reporting 64 findings it had been told to accept.**
  Wrapping the literals moved the translation behind a method call, and its own run for
  this tree named the remaining count per file: 17 sites left, two files off the list
  entirely. The baseline carries what the transcript said, not a rounder number.

Constraints went from 100 to 110, each of the ten new ones reading a shape rather than
a word -- the three submenus have to advertise the tag they are addressed by, each
overlay button has to name its own section, one header has to own the localization
macro, no string may be localized twice, the log marker has to be the one `Logger.m`
writes, and every pairing reason has to have wording behind it. The planted-regression
battery went from 42 to 51 and every one is still caught.


### Thirteenth audit pass (the log browser's rows, the map nobody read, and the compiler that refused)

- **The log browser showed Chinese in the English interface, and no table was ever
  asked.** `compactPresentationForLogLine:` assembles the folded rows the browser
  lists. Its severity tag was ASCII and its category and sentence were Chinese
  literals written into the file, so an English interface read
  `<INFO> [发现] 开始扫描主机`. Twenty rows now go through one helper, `MLLogRow`, which
  keeps the tag ASCII because the browser's own filters read it and asks the table for
  the other two halves. Twenty-five keys were added to each side; both tables are
  892 entries, declared once each, identically, and lint clean.
- **A gate that reported complete coverage over strings it could not see.** The first
  version of that helper translated its own category and sentence inside itself, which
  made all twenty call sites look like an ordinary method call to `l10n-audit`. It
  printed 0 failures and every key accounted for. I wrote that shape on purpose to find
  out whether the audit would notice, and it did not -- so the audit now walks a row's
  arguments itself (`top_level_arguments()`, `log_row_keys()`, `unreadable_rows()`) and
  refuses a row whose translatable half exists only in a value, because a key that only
  exists at run time cannot be asked of a table either. Keys referenced in code went
  from 350 to 382, and six row shapes are self-test cases: literal halves accepted, an
  inline `stringWithFormat` sentence accepted, a variable holding the translation
  refused, a row missing its sentence refused.
- **Five localization calls would not have compiled, and the audit had read them as
  covered.** `MLString` is a macro with two parameters, the second accepted so a call
  site reads like `NSLocalizedString`; five of the new rows passed it one argument,
  which is a preprocessor error rather than a comment left out. The audit's pattern read
  the first literal of each call and reported the key as answered. Every `MLString` call
  in the sources the audit scans is counted by argument now -- 203 of them, all two -- and
  a `#define` line is not mistaken for a call site.
- **Nothing in the tree had ever read the modifier map.** `KeyboardMapResolver`'s header
  calls itself the only place modifier mapping is defined, and the mapping is the reason
  the keyboard reports exist: Command to Win, Control to Ctrl, Option to Alt, each side
  to its own side. Not one test, constraint or scenario named `KMR_` anywhere, so a row
  pointing at the wrong hand, two rows pointing at one slot, or a virtual key one digit
  off would have shipped and come back as "my keyboard feels wrong in games".
  `scripts/keyboard-modifier-mapping-tests.py` compiles the shipped file and walks all
  eight mac modifier keys from keycode to physical slot to remote bit to Windows virtual
  key, with the virtual keys written out in the harness rather than read back from the
  header, because comparing a table to itself proves nothing. Two variants built from the
  same source have to fail: both hands answering as the left one -- the shape behind a
  double-click sending a Win key -- and the flags path answering Command with Alt. Five
  shape constraints keep the map checked where no compiler answers, so the eight virtual
  keys have to be the Windows ones, the eight remote bits have to sit in eight distinct
  positions, no remote key may be named twice, and the flags path, which cannot observe
  a side, has to name four left slots and no right one.
- **Four compiling harnesses had refused to run rather than failed, on this machine
  only.** Each of them asked `xcrun` for a compiler, and the Xcode license on this host
  has not been accepted from a Terminal, so `xcrun --find clang` and `xcodebuild` both
  exit 69. That reads as an untestable tree, and a gate that is red for an environment
  reason is a gate someone silences. The Command Line Tools ship their own clang and
  their own SDK, which need no such consent; `scripts/apple_toolchain.py` hands out
  matched pairs, because a compiler from one vendor and an SDK from the other produces
  `unknown architecture arm64e.x1` out of the linker, which reads as broken code. All
  four now run here: pointer concurrency (5/5 teeth), keyboard concurrency (13
  scenarios), menu addressing in both languages, and the modifier walk.
- **Two defects in the newest harness, found by compiling it locally.** It used
  `NSEventModifierFlags` with only `Foundation` in its probe -- the resolver header
  pulls in Carbon, and inside the app something else in the translation unit brings
  AppKit -- so the error appeared only in CI, in one line, and it named
  `KMR_Remote_LeftOption`, which the enum does not contain: the shipped name is
  `KMR_Remote_LeftAlt`. Both are fixed, and the failure line prints the mask it got
  against the mask it wanted, which a bit count could not say.

Constraints went from 110 to 116 -- five for the shape of the modifier map, one for the
log marker read from both ends, one so that no harness writes the compiler answer again,
and one so that every log row names its halves where a scan can read them. The
planted-regression battery went from 51 to 56, and every one is still caught, including
the two new localizability injections, which fail on the row hidden behind a variable and
the macro invoked with one argument. The localization audit's own cases went from 32 to
38, and the audit now reads log rows whole instead of trusting the call sites around them.

### Fourteenth audit pass (a shortcut that dropped a held key, and the panels that never moved to glass)

- **A translation rule could take a modifier away from the player, and the app never
  noticed it had.** A mouse-driven rule fires its shortcut by hand: it presses its
  modifiers, fires its key, then lets its modifiers go. When the player was holding one
  of those modifiers with a real finger -- Shift to sprint while a Shift+Tab rule exists
  -- that last step released a key nobody had let go of. The tracker of physical modifier
  state is separate from that hand-written packet sequence, and
  `syncKeyboardModifierStateForEvent:` decides what to send by diffing the desired mask
  against it, so the diff came out zero, no corrective press was ever sent, and the game
  stayed without Sprint while the finger stayed on the key. Nothing is logged on either
  side. The measured packets, from the new harness running the shipped state machine:
  `00A0D01 00A0D01 800FD01 800FU01 00A0U00` where `00A0D01 800FD01 800FU01` was asked
  for, with the app's tracker at `0x01` against a host holding `0x00`. A synthetic
  sequence may now only press and release modifiers it actually put down.
  `scripts/keyboard-shortcut-modifier-tests.py` asserts two things for each of its eight
  scenarios -- the packet list the host would receive, and that the tracker still matches
  the held set derived from those packets -- and the unconditional-release shape rebuilt
  from the same source fails six of them.
- **The stream's panels were the part of the interface that never moved to glass.** Seven
  overlays built their own `NSVisualEffectView` with `NSVisualEffectMaterialHUDWindow`,
  the material from before the liquid-glass APIs: the log browser, the stream menu and its
  pill, the timeout panel, the reconnect panel, the connection warning, the mouse-mode hint
  and the notification banner. The settings page and the tab bar used the system glass; the
  surfaces a player looks at for a whole session did not. `GlassOverlayContainer` now owns
  that answer once -- `NSGlassEffectView` where the system has it, the shipped vibrancy
  material where it does not -- and the log browser is on it. What the container really
  built is measured, not asserted: the background class behind the content, the corner
  radius reaching it, `CABackdropLayer` in the layer tree underneath, and that the content
  still covers the panel (`inset 0.00/0.00, size delta 0.00`), which matters because the
  log browser lays out every control by frame and a glass rim inset would have moved the
  whole toolbar. The other six are named in the gate's debt list rather than converted
  unseen: a new panel on vibrancy is refused, and so is a conversion that leaves the list
  lying.
- **A constraint for the class of bug, not just the bug.** Every body in `HIDSupport.m`
  that emits a modifier edge -- by literal virtual key or through
  `HIDRemoteModifierKeyCode` -- now has to answer to the modifier tracker: consult it, ask
  the ownership helper that consults it, or clear it before releasing everything. This is
  the second shipped defect of exactly that shape; the first one made a double-click send
  a Win key.

Constraints went from 116 to 117 and the glass audit now also checks 8 panels against its
debt list. The planted-regression battery went from 56 to 59: the synthetic shortcut
releasing a held modifier, a release-all that forgets to clear the tracker, and a panel
moving back to the pre-glass material -- all three caught, the first by the new harness
and the third by the glass audit. The new panel gate compiles and runs the container on
whichever host the workflow lands on and reports which side of the availability branch it
found, so a host without glass says so instead of passing quietly.

### Fifteenth audit pass (the artifact, not the project file)

- **The glass panel that was never in the product.** The log browser was moved onto
  `GlassOverlayContainer`, the container was compiled and run by its own harness, the
  source-membership audit reported the tree clean locally, and CI refused the push:
  `Limelight/macOS/Views/GlassOverlayContainer.m` was not a member of any target. This
  project lists its compiled sources in the project file's membership exception list, and
  a file absent from that list belongs to nothing, so nothing compiled it, nothing linked
  it, and nothing complained about it. Reading the `__objc_classname` table of the shipped
  build 1433 confirms it: 153 class names, `GlassOverlayContainer` not among them. The
  feature worked in the harness and did not exist in the app.
- **The gate now reads the binary.** `scripts/compiled-source-audit.py` takes the linked
  Mach-O, thins the slice under test, and compares every first-party `@implementation`
  against the class table the linker produced. The project file is a claim about the build;
  this is the build. It runs in both architecture jobs and again after the universal merge,
  where a half-merged slice would drop a class. Its `--self-test` requires that a class no
  one declares is reported missing, and that a section read that returns unrelated names is
  noticed as too little overlap. The first thing it found was the defect above, so the
  known-bad case is a real artifact rather than a fixture. Swift types are deliberately not
  covered: their names are mangled, and a half-read of that section would report success on
  a build that dropped a file.
- **`local green` and `CI green` were two different things.** The audits job runs five
  audit scripts; a local run exercised two of them, which is exactly how the uncompiled
  file reached a runner and failed eight minutes before a release. The audits job is now the
  specification: every script it runs has to be reachable from `constraints-audit.py`, so
  one local command gives the same verdict as that job. Writing the rule found another gap
  on the spot -- `release-gate.py --self-test` was a CI-only check. The five added runs cost
  under a second in total, so none of them had an excuse.
- **Correction to the fourteenth pass.** Its glass measurements came from a standalone
  harness build, which proves the container behaves as described and proves nothing about
  what shipped. Both are now covered: the harness for the behaviour, the artifact gate for
  the presence.

Constraints went from 117 to 124 assertions and the planted-regression battery from 59 to
61: a source file dropped from the project file so that no target compiles it, and the
aggregate quietly losing a step that CI still runs. Both caught.

### Sixteenth audit pass (the header that no build ever read)

- **The glass container was compiled by nobody.** Registering `GlassOverlayContainer.m`
  made the app compile it for the first time, and the first thing that happened is that
  the app stopped compiling: `StreamViewController_Internal.h` declared
  `GlassOverlayContainer *logOverlayContainer` without importing or forward-declaring
  the class, so every translation unit that reached that header failed. The defect was
  two commits old and had been through a green audits job twice, because nothing had
  ever compiled that header -- not the overlay harness, which builds the container on
  its own, and not the aggregate, which does not build at all. A runner found it, in a
  probe step, on a build line that had already been reported green.
- **A first-party class named by a property now has to be reachable from that header**,
  through its own quoted imports or a `@class` forward declaration, with the prefix
  header counted because the compiler counts it. Category declarations (`NSNumber (F)`)
  are not class declarations: reading them as such produced 27 phantom defects in code
  that compiles, against 1 real one, which is the difference between a gate and noise.
  Across 77 headers the rule finds exactly what broke the build and nothing else.
- **The parity rule got the rest of the workflow.** The version written an hour earlier
  covered the audits job, and the gap it was aimed at immediately reappeared in the build
  jobs: `render-probe.py` is the only thing that compiles the app, and no local command
  ran it -- because it cannot, it drives `xcodebuild`, which needs a license this host
  has not accepted. A rule that quietly cannot be satisfied gets worked around, so the
  workflow's script list is now the specification and anything that genuinely cannot run
  here is named with the marker that makes that true; a marker that stops being true
  fails. The seven behavioural harnesses do run here, in under two seconds each, so the
  only reason they had been CI-only was habit.
- **What this machine cannot prove is now written down rather than inferred.** `local
  green` means the audits, the harnesses, and the shape rules. It does not mean the app
  links or that a pixel is in the right place: the artifact gate and the render probe run
  on a runner, and the two reasons are in the aggregate's source.

- **The parity rule then broke the job it was written for, and the fault was its own.**
  Running the seven behavioural harnesses wherever the aggregate runs meant running them
  on the audits job's ubuntu runner, where there is no clang and no macOS SDK, so seven
  gates failed for a reason no source caused. A gate that is red for the wrong reason is
  the exact pattern this file complains about elsewhere -- it teaches people to expect a
  failure and then to ignore it. The aggregate now asks `apple_toolchain` for a pair
  first: a host that has one runs all seven, a host that does not prints which seven it
  skipped and why, and the ubuntu skip is not a loss of coverage because the build jobs
  run the same seven on macOS on every change.

The constraint count went from 124 to 133 on a host with an Apple toolchain, and the
battery from 61 to 62: a header that names a type it cannot see, caught by the rule that
replaced the missing build.

### Seventeenth audit pass (two CI runs lost to a host that is not a Mac)

- **The parity rule was written on one machine and shipped to two.** It put the seven
  behavioural harnesses into the aggregate; the aggregate also runs on the audits job's
  ubuntu runner, which has no clang, no macOS SDK and no `xcrun`. Seven gates failed for
  a reason no source caused. The aggregate now asks `apple_toolchain` for a compiler pair
  before it asks anything to compile: a host with one runs all seven, a host without one
  prints the seven it skipped and the reason. That is not lost coverage -- the build jobs
  run the same seven on macOS on every change -- but a red that means nothing is the exact
  pattern this file complains about elsewhere, because it teaches people to expect a
  failure and then to ignore it.
- **The crash underneath it was older and worse.** `apple_toolchain.clang_and_sdk()` is
  the one answer five harnesses ask, and on a host with no `xcrun` it did not answer
  "none": `subprocess` raised `FileNotFoundError` and the traceback escaped, so a machine
  that cannot compile looked like code that does not compile. It now reports an empty pair
  and lets `clang_and_sdk` give its normal refusal.
- **A host with no `xcrun` is reproducible on a Mac.** Empty `PATH` and call the finder:
  before this change it raised, now it answers `('', '')`. That is a constraint, and the
  battery plants the narrowing that would bring the crash back (63 planted regressions,
  all caught). What still cannot be tested here is the rest of what ubuntu is -- the probe
  covers the one thing that broke, not the whole environment, and the two runs it took to
  find that are the honest price of developing on one platform and shipping on another.

Constraints are 134 on a host with an Apple toolchain; the battery is 63.

### Eighteenth audit pass (a gate that could not read the thing it was built to read)

- **The class-table audit died on both build jobs while passing at home, and the
  difference was the shape of the file.** A per-architecture build produces a thin
  Mach-O and a release build a fat one. The audit asked `lipo -info` whether the word
  `fat` appeared in its answer -- and a single-architecture file answers "Non-fat" --
  so it asked `lipo -thin` to thin a file with one slice, and `lipo` refused. It now
  reads the slice list from `lipo -archs`, which distinguishes the two instead of
  grepping a sentence, and refuses an artifact that does not carry the architecture
  under test rather than reading the wrong slice (which would report a defect that is
  not in that build, or hide one that is). Fat, thin, right architecture and wrong are
  all exercised against the shipped artifact before this was pushed.
- **The universal job has no repository, and its new gate asked for one.** That job
  builds its workspace out of two downloaded app bundles, so `scripts/` was not there
  and the gate failed with "No such file or directory" -- a red about the pipeline, not
  the merge. A checkout step fixes the job; rule **WF021** refuses the shape wherever it
  is written again, with both directions asserted (a job that runs a committed script
  without a checkout, and the same job with one). Narrowing the rule took a pass: the
  script-reference pattern also matches `github.sha`, so the first version reported an
  unclosed expression as a missing checkout.
- **What the four failed runs of this round have in common:** each one was a claim that
  held on the machine that wrote it. The uncompiled source file, the header that could
  not see its own property type, the harnesses put on a Linux runner, the thin binary
  that was not fat, the workspace with no repository. Every one of them was found by a
  machine that did not agree, which is the argument for running the same gate on two
  platforms rather than trusting that one of them represents both.

Workflow rules are 20 to 21; constraints stay 134 on a host with an Apple toolchain and
the battery 63.

### Nineteenth audit pass (the pipeline gate that only ran when someone remembered)

Scope note: from here on this work lands on the maintainer's own repository and this
working tree. The upstream pull request is left alone -- no body edits, no comments, no
merge, no tag.

- **Pushing a branch ran no CI at all.** The push trigger named only `master` and `main`,
  so every verification of `pr-overhaul` meant pressing *Run workflow* by hand -- six
  times this morning, each a full macOS matrix, each a red arriving minutes after the
  commit rather than at it. `push` now also names `pr-*` and `integration/*`, and
  **WF024** refuses the shape: any branch listed for `pull_request` has to be gated by
  `push` as well, because a branch you can push to is a branch you can break.
- **No job declared `timeout-minutes`, anywhere.** A hung `xcodebuild` or a stalled
  `brew install` would sit on a macOS runner -- billed at ten times the Linux rate --
  until the six-hour default expired, producing neither log nor failure. Every job now
  states a bound next to a note about what it is bound by, and **WF022** refuses a job
  without one.
- **The two third-party actions floated on moving tags.** `maxim-lobanov/setup-xcode`
  runs before the compiler on every build job and decides which toolchain the build
  sees; `softprops/action-gh-release` is the one step holding `contents: write`. Both are
  pinned to commits now (`ed7a3b1` = v1, `efb3536` = v3) with the version named beside
  them, and **WF023** requires a 40-character ref from any owner outside `actions/` and
  `github/`. The control asserts both directions -- a pinned third-party plus a floating
  `actions/checkout` is clean, the same action on `@v2` is not -- because a rule that
  only ever fires is a rumour.
- **Artifacts expire.** Four uploads now carry `retention-days: 14`; a fork has no use
  for ninety days of 10 MB disk images, and storage that nobody asked for is still
  storage.
- **What a green run now proves.** Build 1450 was downloaded, mounted and read: dual
  slice, `CFBundleVersion` 1450, both language tables at 892 keys, and the class table
  holding 154 names with **zero** first-party classes missing -- the 154th being
  `GlassOverlayContainer`, which was in no artifact at all yesterday. Checksums verified
  against the published `.sha256`, and the stale build 1433 image was deleted rather
  than left beside it as a plausible-looking lie.

Workflow rules went from 21 to 24. Constraints stay at 134 on a host with an Apple
toolchain and the battery at 63.

### Twentieth audit pass (nobody had ever opened the disk image)

- **The packaging step could quietly build an uninstallable image.** It ends in
  `|| hdiutil create`, so when `create-dmg` is unavailable the fallback runs,
  succeeds, and writes an image whose root holds the app and nothing else -- no
  `Applications` link, which is the drop target the whole macOS install gesture
  depends on -- while the job that built it reports success, because it only
  asked for an exit code. Mounting the build 1450 image shows what a correct one
  looks like: `Applications -> /Applications` at the root, and
  `hdiutil verify` answering VALID. `scripts/dmg-audit.py` now builds nothing and
  asserts all of it from the mounted image, and refuses the fallback shape by
  name rather than letting it reach a release page.
- **Three copies of the same 10 MB image were never compared.** The artifact
  service, the release job's download, and the asset on the release page are
  three separate copies of a file, and nothing hashed any of them in CI: the
  checksum in front of you had been computed on a laptop by hand. Each build job
  now mounts, verifies and hashes its own image, publishes
  `Moonlight-macOS-checksum-<variant>` beside `Moonlight-macOS-dmg-<variant>`,
  and the release job refuses any image that no longer hashes to what the build
  job recorded -- then publishes the hashes next to the files they describe, so a
  download can be checked by whoever uses it.
- **The build number was only ever asserted on the source side.** The image now
  answers for itself: the architecture jobs compare the `CFBundleVersion` inside
  the image with the number the same job resolved, and the universal job expects
  the arm64 slice's number rather than the merged bundle's own, so an image made
  from a stale copy of the app -- or from the wrong side's `Info.plist` after the
  merge -- is refused on the machine that built it.
- **A gate that only runs on a tag is a gate nobody has run.** The checksum check
  belonged to the release job, which runs only on `refs/tags/v*`, so its download
  pattern, its `*.sha256` glob and its refusal of a missing image would all have
  been exercised for the first time while publishing something people install.
  `scripts/verify-release-images.sh` owns that answer now, and a `verify_images`
  job runs the identical line on every push against the artifacts a release would
  publish, with the release job depending on it.
- **The rehearsal found two things before it ever reached a runner.** The
  `Moonlight-macOS-dmg-*` download pattern also matched the new checksum
  artifacts, so the checksums live under `Moonlight-macOS-checksum-*` instead;
  and the script resolved its two directory arguments after moving to its own
  project root, which is correct only when the caller happens to stand in the
  repository. Both were run locally against the build 1450 image, good path and
  tampered path, and the good path hashes to
  `eceebe05f3b910168db886d6bef91dfb4b2fd490df184d235c977a837f19a349` -- the
  checksum already recorded for that build, now reproduced by the pipeline rather
  than by a person.
- **The self-test makes its own images.** A throwaway bundle is packed twice,
  once with a drop target and once the way the fallback packs it: the good image
  passes, the bare one is refused, a build number that disagrees is refused, and
  one appended byte is caught twice over, by the image's own checksum and by the
  sidecar. The half that needs no toolchain runs on every host, including the
  ubuntu audits runner and the battery's nested runs; the half that mounts costs
  about as much as the seven behavioural harnesses, so it belongs to the full pass
  and says so out loud on a host that cannot mount HFS+.


What the pipeline now answers without being told: run `34940804782`, pushed to
this branch, built both images, mounted and hashed each, then downloaded all
three images and all three checksums on a Linux runner and compared them in five
seconds -- the release job's own check, on the release job's own artifacts,
minutes after the commit rather than on release day.

Constraints went from 134 to 136 on a host with an Apple toolchain (127 to 128
without one), the battery stays at 63, and workflow rules stay at 24.

### Twenty-first audit pass (the shipped bundle was never signed)

- **The main executable of the shipped app carried no signature at all.** Read
  back from the build 1450 image, four of its six Mach-O objects failed
  `codesign --verify --strict` -- `Contents/MacOS/Moonlight: code object is not
  signed at all`, and both vendored frameworks plus their versioned binaries: `a
  sealed resource is missing or invalid` -- while the bundle itself reported
  `Sealed Resources=none`, which is the difference between an app you can prove
  is the one that was built and one you cannot.
- **The universal merge is what broke the frameworks.** `lipo -create` replaces a
  signed binary during the merge, and the framework headers the upstream seal was
  computed over are not shipped by this repository at all, so the seals were
  describing a layout that no longer existed. Nothing noticed because nothing
  looked: no step in the pipeline ever opened a signature.
- **`scripts/codesign-bundle.sh` signs from the inside out**, frameworks then the
  launchd helper then the bundle, since the outer signature is what seals the
  inner ones. Retagging in place turned out to be the wrong move -- keeping the
  previous designated requirement left the framework answering `file modified`,
  because a requirement belongs to the bytes it was written for -- so the old
  signature is removed and a fresh ad-hoc one takes it, carrying any entitlement
  the object had. The pipeline's own universal log now reads `signed
  OpenSSL.framework`, `signed SDL2.framework`, `signed
  std.skyhua.MoonlightMac2.AwdlPrivilegedHelper`, `signed Moonlight.app`, and the
  audit beside it `ok 6 Mach-O object(s) verified, and the bundle is sealed`,
  with 37 resources sealed.
- **The identity is reported, not demanded.** This project has no Developer ID and
  notarizes nothing, so `spctl` rejects the app and will keep doing so. The gate
  prints that as a fact rather than asserting it, because a check held red by a
  certificate nobody here owns is indistinguishable from a check that never
  passes -- and the same audit that refuses the shipped bundle, naming four
  objects and `Sealed Resources=none`, accepts the same bundle after signing:
  `valid on disk`, `satisfies its Designated Requirement`.
- **The self-test compiles its own apps** with the toolchain module the behavioural
  harnesses use: a signed bundle is accepted, an unsigned one is refused, and one
  byte of a file added after signing breaks the seal and is refused. It costs two
  compiles, so it runs on the full pass and on the macOS jobs that package, and
  the audits runner says so out loud instead of failing for having no clang.
- **What this changes for someone installing it.** The signature is ad-hoc, so a
  rebuilt app presents a new code identity and macOS asks for Accessibility and
  Input Monitoring again. It asked before as well, for a bundle no loader could
  check; the difference is that the download can now be verified rather than
  trusted.

Constraints went from 136 to 137 on a host with an Apple toolchain (128 on one
without, where both signature self-tests skip by name), the battery stays at 63,
and workflow rules stay at 24.

### Twenty-second audit pass (the shortcut prefix that let the held keys go)

- **`Ctrl+Option` held alone is the mouse-capture escape hatch**, and it was
  firing underneath the shortcuts that share it. The schedule test in
  `flagsChanged:` and the expiry test 150 ms later are the same question -- "are
  the relevant modifiers exactly Ctrl+Option" -- and nothing in between asks
  whether a key was pressed, which is invisible to that question: a letter key
  does not move the modifier flags at all. The shipped default table puts six
  keyed actions behind that exact pair (`⌃⌥S` performance overlay, `⌃⌥M` mouse
  mode, `⌃⌥G` control ball, `⌃⌥W` disconnect, `⌃⌥R` reconnect, `⌃⌥C` control
  centre), so pressing `⌃⌥S` to read the frame rate toggled the overlay *and*,
  150 ms later, released every modifier on the host, walked the mouse out of the
  game and muted connection warnings for two seconds. That is the "I pressed a
  shortcut and my held keys let go" report, and it is why a Ctrl+Option prefix
  reads as a collision on top of any mapping.
- **One line fixes it, in `-keyDown:`**: a key press says the player is not
  holding modifiers alone, so the pending release is invalidated. The escape
  hatch keeps its meaning -- modifiers without a key still uncapture -- and the
  new harness asserts that half as well, because a "fix" that only silences the
  release would quietly delete the feature.
- **The eighth behavioural harness reads the shipping source rather than
  paraphrasing it**: the schedule condition, the expiry condition, and which
  message bumps the token are lifted out of `flagsChanged:` and `-keyDown:`,
  compiled into one timeline, and run in two orders of the same physical gesture
  -- modifiers-then-key must release nothing, modifiers-alone must still
  uncapture. Removing the guard from the model has to bring the collision back,
  which it does, naming the release and the uncapture.
- **The battery grew a sixty-fourth mutation, and it initially slipped past.**
  `no-key-cancel` deletes that one line and was reported MISSED, because the
  battery's default gate is the aggregate run with `--no-battery`, which is
  exactly where behavioural harnesses do not run. A mutation owned by a harness
  now names that harness -- `COLLISION_GATE` -- and the reason the default cannot
  cover it is written above the default rather than rediscovered by the next
  person. 64/64 after that.
- **The verification package moved into the pipeline.** Build 1457 was pulled
  back from CI rather than built by hand: its published checksum matched the
  downloaded bytes, `hdiutil verify` answered VALID, the drop target and
  `CFBundleVersion 1457` read back off the mounted image, the signature audit
  verified 6 Mach-O objects with 37 sealed resources, both language tables held
  892 keys, and the class table read 154 names with zero missing. The older
  unsigned build 1450 image was deleted so two plausible packages cannot sit in
  one directory.

Constraints went from 137 to 138 on a host with an Apple toolchain, the battery
from 63 to 64, the behavioural harnesses from seven to eight, and workflow rules
stay at 24.

### Twenty-third audit pass (the Space change that released the wrong half of the keyboard)

- **Two release methods exist and they release different things.**
  `-releaseAllModifierKeys` sends eight fixed `KEY_ACTION_UP` packets -- `0x5B`,
  `0x5C` and `0xA0` through `0xA5` -- which clears Shift, Ctrl, Alt and Win and
  cannot clear anything else. `-releaseAllHeldKeys` walks the forwarded key
  records and releases the keys that move a character. Session teardown calls
  both, in that order; mouse uncapture calls the held-key one, with a comment
  saying why: forwarding switches off after it, so a key held at that point never
  reaches the host as a release.
- **The active-Space observer had the reasoning applied to only one half.** When
  the window is off the current Space during a fullscreen transition it skips the
  uncapture -- correctly, the window is coming back -- and then released *only the
  modifiers*, hid the edge menu, and left every ordinary key pressed on the host.
  Holding W while the Space changes is the ordinary way to enter and leave the
  fullscreen Space, and nothing can undo it afterwards: no `keyUp:` arrives,
  because the window is not on the Space receiving events. The character walks
  until the player notices, goes back, and lets go.
- **The ninth behavioural harness reads four facts out of the shipping source** --
  the exact VK set the modifier release sends, that the held-key release walks the
  records, that uncapture still releases held keys, and whether the
  not-in-current-Space branch does -- models one host that remembers what is
  pressed, and runs three shapes: the reported gesture, the uncapture guarantee
  that must not regress, and an idle Space change that must press nothing. Take
  the release out of the model and the stuck key comes back, which is the point.
- **A guard on the guard:** the harness refuses to run its own opinion if
  `releaseAllModifierKeys` ever starts sending an ordinary key, because at that
  point the split this whole test rests on has changed shape and the model, not
  the assertion, is what needs editing.

Constraints went from 138 to 139 on a host with an Apple toolchain, the battery
from 64 to 65, the behavioural harnesses from eight to nine, and workflow rules
stay at 24.

### Twenty-fourth audit pass (the gamepad press that never came back up)

- **The helper always asked which edge it was sending.**
  `-sendKey:down:modifiers:` builds its event with
  `CGEventCreateKeyboardEvent(NULL, keyCode, down)`, so the edge is inside the
  event, and then calls `[self.responder keyDown:event]` on every path. Every
  caller in `-controllerEvent:` passed `YES`, which made what shipped
  self-consistent and incomplete at the same time: a pad button was one press
  edge, and the responder was never told the key came back up. Nothing else in
  the tree asks for the other edge, so no gate, no crash, and no review could
  see the difference.
- **A responder keeps key state, and the release is the edge that ends a
  press.** A control that actuates on release never actuates; anything that
  pairs a press with its release stays in the pressed half of that pair. A pad
  cannot press half a key, so the view that presses keys on its behalf may not
  either. `pressKey:withFlags:` now sends both edges, and `-sendKey:down:` hands
  each one to the selector that matches the event it built -- handing a release
  to `keyDown:` would give the responder an event whose type says key-up and
  whose selector says otherwise.
- **Measured rather than assumed, on the alert this exists for.** Wired the way
  `HostsViewController` wires it -- the navigatable view in the host list's
  content view, `responder` aimed at the alert window, the buttons carrying
  their Return and Escape key equivalents -- the A button actuates the default
  button exactly once with both edges present, not twice, and B still dismisses
  the sheet. The release is the missing half of the stroke, not an extra action.
  What did not change is stated plainly: in a probe that cannot make its window
  key, the X button's Space and the D-pad's Tab moved nothing before the change
  and nothing after, so this pass does not claim a pad can confirm a dialog.
  That question stays on the on-device list, where only a real focus ring can
  answer it.
- **The landmine that crashed the first probe.** `responder` is a `strong`
  reference to the alert window. Attaching the navigatable view as that window's
  own `contentView` -- the obvious next move for whoever reorganises this --
  makes a cycle whose teardown crashes in `-[NavigatableAlertView
  .cxx_destruct]` releasing a window that is already gone. The shipped wiring
  avoids it, so nothing was changed here; it is written down because that crash
  otherwise reads as a bug in whatever was just added.
- **The tenth behavioural harness compiles the real view** --
  `Limelight/macOS/Views/NavigatableAlertView.m`, not a model of it -- against a
  spy `NSResponder` and records, for each of the five mapped buttons: which
  selector ran, the key code, the modifier flags, and whether the `type` carried
  inside the event agrees with the selector it arrived at. The left D-pad must
  be the one stroke carrying shift, and its release must still be carrying it.
  Rebuild the old one-edge shape out of the same source and the harness refuses
  it. The battery carries two mutations for it, one for the missing release and
  one for a release delivered as a second press, so neither half of the original
  mistake can come back quietly.

Constraints went from 139 to 140 on a host with an Apple toolchain, the battery
from 65 to 67, the behavioural harnesses from nine to ten, and workflow rules
stay at 24.

### Twenty-fifth audit pass (zero interpolation slots had meant two different
things)

- **The numbers first, measured on the machine in front of us.** A VideoToolbox
  probe compiled against the macOS 27 SDK and run on the Apple M2 this project
  is tested on: `VTLowLatencyFrameInterpolationConfiguration.isSupported`
  answers YES, a configuration is created for 640x360, 720p, 1080p, 1440p and
  4K, `startSessionWithConfiguration:` succeeds, and every one of them reports
  **zero** interpolated frames -- requesting one, two or three, through both
  initialisers. macOS 27 also publishes the ceiling beside those answers: 1920
  per side and 2073600 pixels for temporal interpolation, 640 per side and
  230400 pixels for the 2x spatial mode. The low-latency super-resolution scaler
  tells the same story in a different shape: `isSupported` YES,
  `maximumDimensions` 1280x1280, 960 per side at 2x, supported scale factors
  `(1.5)` at 720p and nothing at all at 1080p. MetalFX is the one that genuinely
  runs on this GPU: `supportsDevice:` YES, and a rescaled checkerboard comes
  back with interpolated edge pixels.
- **One sentence covered two different facts.** The renderer asked the engine
  only about the *stream size*, and any refusal there was reported as "the
  system offered no interpolation slots". An oversized request is refused
  exactly that way: 2560x1440 and 3840x2160 are outside the ceiling quoted
  above, so a Mac that does have the interpolation engine, streaming at 4K, read
  as a Mac that cannot interpolate -- while the settings page on that same Mac,
  which asks 720p, 1080p and 4K and keeps the best answer, said Available. One
  machine, two surfaces, opposite claims.
- **The fix is to ask a question the engine can answer.**
  `MLClassifyInterpolationSlots()` -- extracted from the renderer by the harness
  and compiled -- takes the slots at the stream size, and when that is zero and
  the stream is larger than the size the settings matrix asks about, it asks
  again at that size. Slots there means the resolution is the story and reports
  "the stream resolution is above the interpolation ceiling"; zero there as well
  means the hardware, which is what the M2 gets, unchanged. The settings page
  has its own line in both languages, and the resolution branch is tested before
  the hardware branch because it is the narrower of the two claims.
- **The two surfaces cannot drift by construction.** The renderer's re-ask size
  and the Swift capability matrix's smallest probe size are compared by the
  harness -- define against source -- and a drift fails the gate rather than
  quietly reintroducing the contradiction this pass removed.
- **No claim that interpolation runs.** On this M2 it does not and cannot: every
  size, including sizes well inside the ceiling, reports zero slots. What
  changed is that a Mac which *can* interpolate at 1080p no longer reports that
  it cannot when the user streams at 4K, and that the line now names the thing
  to change.
- **Two mutations, one per half of the mistake**: collapsing the two verdicts
  back into the hardware answer (caught by the compiled model, which refuses to
  call a 4K stream with slots at 720p a hardware failure), and "re-asking" the
  engine at the same refused size (caught by the source check that the re-ask
  really builds a second configuration).

Constraints stay at 140 on a host with an Apple toolchain, the battery went from
67 to 69, the behavioural harnesses stay at ten, and workflow rules stay at 24.

### Twenty-sixth audit pass (the panels above the video were never glass)

- **Which surfaces, and what they were made of.** Eight things sit on top of
  the picture: the performance HUD, the connection warning, the mouse-mode
  hint, the notification banner, the connection-timeout dialog, the reconnect
  panel, the log browser and the control-centre pill in the titlebar. Seven of
  them built their own `NSVisualEffectView` with
  `NSVisualEffectMaterialHUDWindow`, the material from before the glass APIs
  existed, so the settings page and the tab bar sampled the system glass while
  the panels a player actually reads during a session did not.
  `NSGlassEffectView` is the AppKit half of liquid glass and has been in the
  SDK since macOS 26, and `GlassOverlayContainer` had already been built to
  own that choice -- only the log browser was using it. All eight ask it now.
- **The ratchet changed shape.** While panels were waiting, the audit's list
  was a debt list. With none waiting it is a regression list: a panel that
  builds vibrancy again, that sets a material while claiming the container, or
  that masks its corners by hand to get the old look, is refused, and
  `--self-test` plants each of those shapes on the real files to prove the
  rule fires. Seven panel cases, all refusing.
- **The reconnect overlay was filtering the whole picture.** A full-window
  `NSVisualEffectView` is a scrim and a filter at once. The scrim is a plain
  dimming layer now, with no material of any kind, and the spinner with its
  sentence sit in a glass card sized to the sentence. The audit insists the
  scrim stays material-free.
- **Legibility was measured, not promised, and the measurement is portable.**
  These panels put white labels on the material, and the stream window pins
  `NSAppearanceNameVibrantDark`. The gate asserts the contract that legibility
  leans on wherever it runs: inside that appearance the panel resolves to
  DarkAqua, and inside a light window it does not. Where the host will render
  glass into an offscreen capture it also measures the material: white text
  reads 4.73:1 on dark glass, the same panel in a light appearance reads
  1.02:1, and the two have to keep that relationship or the first number is a
  constant wearing a measurement's clothes. Run against the shape this
  replaced, the dark capture scores 2.43:1 -- the vibrancy was the worse of
  the two, so this is not a legibility trade.
- **CI caught two gates that would have lied.** The first named
  `effectIsInteractive`, which only exists in a newer SDK than the CI image
  builds with, and broke the analyzer and both build jobs while the local
  machine was clean. The second asked a runner that composites no glass into
  an offscreen capture for a contrast ratio and got 1.00:1; an earlier draft
  of the same check compared against a light-appearance capture that is
  legitimately flat, which would have printed a cheerful 0.00:1. Both are
  gone: what every host can answer is asserted everywhere, what only a GPU
  host can answer is asserted there, and a host with nothing to measure is
  told it was skipped instead of handed a free pass.
- **Frame-based panels did not move.** Every one of these overlays positions
  its controls by frame, and a content view inset by the glass rim would have
  shifted all of them. Measured on the compiled container: inset 0.00/0.00,
  size delta 0.00.
- **Interactive glass is read back, not trusted.** The control-centre pill is
  a button, and where the system has it (`effectIsInteractive`, macOS 27) its
  glass now answers interaction; a setter that stores the request and never
  hands it to the glass is invisible to any source rule, so the compiled
  container is run and the glass view is asked. `scripts/assertion-battery.py`
  plants exactly that mistake as `glass-never-told-it-must-answer`, and the
  harness refuses it.
- **Dead by conversion.** The timeout dialog's hand-drawn
  `NSBezierPath`-to-`CGPath` corner mask and the `NSShadow` beside it are gone
  -- real glass owns its corners and its rim, and a shadow behind it doubles
  the depth rather than adding it. That left the bezier helper with no callers
  at all, so it is deleted rather than shelved.
- **The build host's SDK is older than the systems this ships to, and CI
  proved it.** `effectIsInteractive` is declared in the macOS 27 SDK; the CI
  image builds with the 26.5 SDK, where the property is not in the header, so
  naming it was a compile error on every runner while the local machine --
  which has the 27 SDK -- was clean. The container now looks up
  `setEffectIsInteractive:` on the object and invokes it through
  `NSInvocation`, which compiles against any SDK and does nothing where the
  property is absent, and the harness reads the answer back by name with
  `valueForKey:` and says which of the two it got. Re-verified by compiling
  the container against the 26.5 and 26 SDKs with `-Wall` before this went
  back.
- **What still needs an eye.** This is a visual change to eight surfaces. The
  gates say what they are made of and that text still reads; they do not say
  the look is agreed, and a real session on a real Mac is the only thing that
  can.

The battery went from 69 to 70, constraints stay at 140 on a host with an Apple
toolchain, the behavioural harnesses stay at ten, and workflow rules stay at 24.

### Round 27: the pipeline had a split personality, and the keyboard did not

### Fixed

- **One workflow used two versions of the same action.** The analyze job
  uploaded its transcript with `actions/upload-artifact@v4`; the five other
  uploads in the same file used `@v7`. Nothing was red. A tag is resolved
  per job, so both halves ran, and the file had quietly grown two
  implementations of one step -- which is exactly how a major bump arrives:
  on some steps and not others, leaving the artifact a consumer expects to
  read written by code nobody reviewed beside that consumer. Worse, the
  drifted step sits behind `if: failure()`, so the day GitHub retires a
  major is the day the job that explains a failure starts failing too. It
  is on v7 now, like every other upload in the file.
- **Rule WF025 keeps it that way**: inside one file, one action means one
  version, whether the reference is a tag or a pinned commit. The rule is
  proven from both sides -- a fixture that splits one action across two
  majors and reports nothing else, a control with several uploads that all
  agree and must stay silent, and `scripts/assertion-battery.py` planting
  the partial bump as `upload-action-split-across-versions` against the
  pipeline audit. The rule caught the real thing before the fix did.

### Audited, and deliberately not changed

- **The local shortcuts that release every modifier were read one by one.**
  `Command+1`, `Command+\`` and `Command+H` outside fullscreen,
  `Control+Command+F`, `Command+W`, and the disconnect, quit and reconnect
  shortcuts all call `-releaseAllModifierKeys` while the stream is still
  running, and the player's fingers are usually still on the keys at that
  moment. That looked like the old stuck-modifier family. It is not: the
  call zeroes `keyboardPhysicalModifierSourceMask` and
  `keyboardRemoteModifierMask` in the same breath it sends the eight up
  packets, so the tracker and the host are told the same thing, and every
  later edge -- a key kept held, a key let go, another press -- recomputes a
  diff against a state that matches. Narrowing it to "release only the
  modifiers this one shortcut consumed" would make the two trackers answer
  for different worlds, which is the failure the
  `modifier-release-forgets-the-tracker` mutation exists to prevent. There
  is no reproducible wrong outcome on the other side of that change, so the
  code stays as it is and the two remaining bare `return YES` guards in the
  key-equivalent gate stay as the documented, intentional swallows they are.

The battery went from 70 to 71, workflow rules went from 24 to 25, constraints
stay at 140, and the behavioural harnesses stay at ten.

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
