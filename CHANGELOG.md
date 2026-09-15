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
