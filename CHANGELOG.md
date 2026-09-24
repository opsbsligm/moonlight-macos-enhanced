# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Block notification observers are now counted against a real AppKit,
  because the owner of one is not the object that registered it.**
  `scripts/notification-observer-tests.py` compiles observers that differ only
  in the shape the shipped code uses and runs them with a real window: one
  post reaches every block registered for its name; overwriting a token leaves
  the previous block registered and unreachable; withdrawing the token first
  ends at exactly one observer, and withdrawing by token then posts nothing;
  `-removeObserver:name:object:` removes a selector observer and leaves a
  tokenless block in place; a strongly capturing block keeps its owner alive
  and callable, so a stop parked in that owner's `-dealloc` cannot run, while
  a weakly capturing one releases it. It also counts `-viewDidAppear` reaching
  one view controller three times over three parent changes and again after a
  hide and show, which is the path the fix above rests on. Two `constraints-
  audit.py` rules read the sources: a block observer registered in
  `-viewDidAppear` without withdrawing the token already held, and a
  registration that stores no token at all. Both are planted both ways -- each
  refusal is shown to fire on a planted file and to clear on the shipped
  shape, including one stored on the line above. `-viewDidLoad` is
  deliberately outside the first rule: nothing measured it, and a rule that
  refuses a path nobody watched is one somebody has to work around later. It
  rides `scaling-output-evidence-tests.py` because a step of its own needs a
  `workflow` scope this credential does not carry.


- **A settings callback is now compiled to find out whether its model dies.**
  `scripts/settings-callback-ownership-tests.py` cuts the two closures out of
  `SettingsStreamPane.swift`, compiles them unchanged, and runs three shapes:
  the shipped one, the same code with the weak capture tidied away, and the
  closure reaching for the pane the way it used to. The model is a stand-in
  that counts the times it was released; the closures are the ones that ship.
  Shipped releases the model, the other two do not, and all three write the
  same answer -- which is the point: behaviour is exactly what a cycle leaves
  untouched, so a test that only asks the page whether it still works cannot
  see one. `@State` is not used inside the harness and says why in a comment:
  a state binding needs a location SwiftUI only hands out while it is
  rendering the view. It rides `scaling-output-evidence-tests.py` because a
  step of its own needs a `workflow` scope this credential does not carry.

- **Device attribution gained the entry point the real bus needs, because the composite
  device rule could not be expressed without it.** `MLUSBDeviceIdentityFromRegistryNodes`
  takes the device node plus every interface node hanging off it and returns one identity:
  identifiers from the first node that spells them, interfaces as the union over all nodes,
  duplicates kept because two identical interface nodes is what the registry said. The shape
  was measured, not assumed (docs/usb-redirection-design.md 2.5): on macOS 27.2 each interface
  is its own `IOUSBHostInterface` object publishing one numeric `bInterfaceClass` and one
  `bInterfaceProtocol`, and no class array is published anywhere. A dock that is storage plus
  a smart card therefore arrives split in two, and the single-node reader handed the policy a
  storage device -- exactly the face-choosing that the reserved-class refusal exists to prevent.
- **A USB measurement can no longer be wrong about a key name it invented.**
  `scripts/usb-registry-shape.py` compiles a read-only IORegistry probe whose list of keys
  is extracted out of `USBDeviceEnumeration.m` itself, prints the node counts the probe saw,
  and reports whether every value shape on the bus today is pinned by a named case in the
  Stage 1 harness. It is deliberately not a gate: on a runner with no USB devices it prints
  `not measured` and does not print `covered`, and that state is itself tested against a
  faked toolchain. `docs/usb-redirection-design.md` 8 records the reproduction commands,
  and 8.1 the eight planted defects that have to turn it red.

- **The order a device may be handed over in, checked against a host that does not exist.**
  `MLDeviceRedirectionSession` carries stage 2's client half: a host first answers `1` in
  `/serverinfo`, then a bind, then a state request, then an upload, and no step happens before the
  one before it was accepted. Only an explicit yes is a yes; a tag that answered two different
  things is not resolved by picking one; a message on a channel this contract does not define ends
  the session rather than being skipped, because the next answer would be read against the wrong
  step; and an unanswered step is a different stop from a refused one, so a slow host and a full
  host do not come out of the log looking the same. 44 compiled assertions, 10 planted defects all
  caught. It is **not wired into the stream start path, deliberately**: the three calls it sequences
  exist in no host, so wiring it would mean deciding the wire format by guessing, and a guess that
  reads as support costs a player a device they were told they had.
- **A driver extension that nobody can load can no longer be counted as one that works.**
  `MLDriverLifecycle` covers the logic on this side of the signing wall: an install that times out
  falls back to `not-installed` with a reason instead of sitting in `installing` forever, an
  unanswered *removal* stays in `removing` rather than claiming a system state nobody observed, a
  crash keeps the leases it held (they expire; they are not returned by a process that died), a
  spent crash budget cannot be argued out of holding back, and a replugged device starts a new
  lease even when the removal event never arrived. 39 compiled assertions, 10 planted defects all
  caught. Devices are named by the stage 1 digest, and the log line is asserted not to contain it.
- **A gate over the prerequisite stage 3 is actually missing.**
  `scripts/driver-extension-signing-audit.py` refuses the combination of "the tree builds a driver
  extension" and "the workflow cannot notarise it": a `.dext` target, a DriverKit import, a system
  extension request or the DriverKit entitlement each require a Developer ID signature, the
  hardened runtime, `notarytool` and a staple in the workflow, and each names the file to change.
  Its `--self-test` includes a properly signed tree that has to pass, because a gate that can only
  ever fire is as useless as one that never does.

- **What a build may claim about its own signature, read from the running binary.**
  `MLCodeSignatureProfile` answers the one question the devices panel has to settle before it can say
  anything else: could this identity load a driver extension at all. It reads the code signature the
  kernel already checked, not a build setting, because a build setting reports what was asked for and
  the panel is reporting what this binary can do. Measured first: an ad-hoc build's signing
  information carries no certificate list, no entitlement dictionary and no team id at all, while a
  shipped Developer ID application carries a three-certificate chain and both, so the form is decided
  by certificate chain plus leaf-subject prefix rather than by flag bits whose meaning is not in the
  installed SDK. `mayAttemptDriverExtension` is true only for a Developer ID leaf *and* a DriverKit
  authorisation among the entitlement keys. `scripts/code-signature-profile-tests.py` feeds the
  classifier three certificates generated by openssl at run time, one per issuer shape; its type guard
  caught a real crash on the way, an array element bridged into a `SecCertificateRef` unconditionally.
  46 python assertions, 106 compiled assertions, 11 planted defects all caught.
- **The bus is measured from the device down, because measuring it by interface loses a third of it.**
  `MLUSBBusSnapshot` groups registry nodes by ownership instead of asking an interface iterator for
  the interface universe. Measured on the machine the gate runs on: 10 device nodes own 16 unique
  nodes carrying `bInterfaceNumber`, while `IOServiceMatching("IOUSBHostInterface")` publishes 11 of
  those 16 and nothing else -- 31% of the interfaces invisible, and the invisible ones are composite
  faces, so the old route let a dock choose which of its faces the policy saw. Grouping therefore
  accepts a parent only where it is exactly one, an orphan becomes its own group rather than being
  dropped, and the role test reads key *names* and never values. `scripts/usb-bus-snapshot-tests.py`
  forbids the interface-iterator class names in the source and, in the other direction, requires this
  measurement to stay in the header comment, so the rule reads as a finding rather than a preference.
  Privacy is cross-checked against an independent `ioreg` read: 14 product names and serial numbers
  taken from the bus, each asserted absent from the program's own output. 49 python assertions, 37
  compiled assertions, 9 planted defects all caught.
- **The devices panel: the first screen that says why USB redirection is not available yet.**
  Settings gained a Devices pane (`SettingsDevicesPane.swift`, rendered entirely from
  `MLDeviceRedirectionPanelModel`). Its 90 compiled assertions and 18 planted defects cover the logic; its source assertions
  cover the wiring, because an unwired panel fails silently: model reachable through the bridging
  header, pane a member of the target, pane actually reachable from the tab bar, and every sentence it
  can print answered in both language tables. The four preconditions sit above the device list because
  a page of refusals without them would dress a missing signing identity up as a room full of broken
  devices -- the design document's own Stage 1 boundary said that, and that is what had kept the UI
  unbuilt until now. Every string on the page is the spelling the log uses, so a screenshot and a log
  line name the same obstacle; a device is shown as identifier, interface class and serial digest and
  nothing more, and the gate asserts the rows produced from a real bus carry no product name. The
  switches are stored, validated, and read by nothing that streams: until the extension exists they
  authorise nothing, and the pane says so as an `UNLOCK(stage3)` checklist that a gate keeps present.
  Two defects were caught before any of this shipped and are recorded because they are the interesting
  kind. Three of the new harnesses had a `CHECK` macro that evaluated its expression twice, so a rule
  "added once" came back as two rules and the failure looked like a defect in the panel rather than in
  the test; and deleting or switching a rule addressed a slot in storage rather than the row the player
  was looking at, which silently removed an unreadable record instead of the rule whenever one sat
  above it. Both now have planted defects of their own.
  The page also had to stop being written against the guesses a compiler makes about
  Objective-C: a no-argument `+panelModel` became an `init()` competing with the declared
  initialiser, `removeRuleAtIndex:` was translated as `removeRule(at:)` and
  `rowsByScanningBusWithHostPaired:` as `rowsByScanningBus(withHostPaired:)`, and a readonly
  property beside a separate `setFeatureEnabled:` stayed a getter plus a setter. Every selector
  the pane calls now carries an `NS_SWIFT_NAME`, the two switches are readwrite properties whose
  accessors do the validating, and the page builds the model through its declared initialiser;
  the gate asserts the pinned spellings are still in the header, because the alternative is a
  page that compiles on one compiler version and not on the next.

### Fixed
- **A re-shown stream window no longer answers one event twice.**
  `-viewDidAppear` is delivered again to the same view controller when its
  window is hidden and shown again, and once per show across three parent
  changes; both counts came from `scripts/notification-observer-tests.py`, not
  from a reading of the docs. Five block observers in `StreamViewController`
  and one in `AppsViewController` were registered on that path, and the
  notification centre keeps every block it is handed -- measured: three
  registrations answered one post three times, and writing a fresh token over
  an old one left the old block registered while taking away the only name the
  owner had for it. A settings change therefore reached
  `-updateWindowSubtitle` once per visit and one log line reached the overlay
  once per visit, growing with every hide and show. The stream page now
  withdraws the tokens it holds through one `-removeStreamSettingsObservers`,
  which the teardown already uses, and the apps page withdraws its own before
  registering again. `AppDelegate` kept no token at all for its local-network
  observer and asked `-removeObserver:` to withdraw it in `-dealloc`; that
  call removes a selector observer and removes nothing of a block one, which
  the same harness counts, so the token is now stored and removed by token.


- **The audit's method reader could not see a method whose brace was on the
  next line.** `method_bodies` asked for the signature and its `{` on one
  line, and the tree writes both ways: 1315 definitions put the brace on the
  signature's line and 244 put it on the line after. Every rule that lives per
  method had been reporting on the first group and calling the second group
  clean -- including the IOKit iterator rule added the round before, which is
  the same blind spot one day old. It surfaced the wrong way round: the moment
  the reader could see the other style, the CoreFoundation rule reported three
  colour spaces in `VideoDecoderRenderer.m` as taken and never accounted for.
  Reading them says the code is right -- each `prepare` calls its own
  `teardown` first, which releases the previous value and clears it -- and the
  rule was wrong, because it knew two honest endings for a Create (release
  before the method ends, return from a method annotated
  `CF_RETURNS_RETAINED`) and colour spaces have a third: store it in an ivar
  and release it in the teardown. That ending is now accepted when the same
  file really does release that ivar, and it comes with a planted pair instead
  of a promise: stored-and-released reads clean, stored-and-never-released
  reads dirty, and both are asserted every run. The whole audit was then re-
  read against the fixed reader rather than assumed: 0 failures, and the only
  findings it produced were the three above.

- **The gamepad pointer stopped answering whenever the Mac took over the run
  loop.** The pointer poll was scheduled, and scheduling registers a repeating
  timer in `NSDefaultRunLoopMode` only. A modal session runs in
  `NSModalPanelRunLoopMode` and a menu or a window drag in
  `NSEventTrackingRunLoopMode`, so in those stretches the timer that turns a
  right stick into a cursor fired zero times. Two places reach a modal mid-
  session by name: the microphone helper's Input Monitoring alert -- whose own
  text is about mouse polling -- and the settings page's file picker. It is
  measured rather than argued: `scripts/timer-registration-tests.py` compiles
  four repeating timers that differ only in the mode they were added to and
  counts what fired in 300ms. A poll added to the default mode fired 30 times
  in the default mode and 0 times in a modal session and 0 in event tracking;
  the same timer added to the common modes fired 30 in all three. Both
  directions of every case are counted, so a zero is never read as a dead
  timer, and the app's four other repeating timers already asked for the
  common modes by hand. The same file measured the other half: a repeating
  timer scheduled with `target:self` was still alive and still being polled
  300ms after the object's last reference outside the timer was dropped, which
  is why the only thing that stops this one -- `-cleanup`, behind a main-
  thread guard that returns without acting -- cannot be moved into `dealloc`.
  The poll now holds its owner weakly and invalidate itself, the shape the
  clipboard monitor in this app already uses. Interval, repeats, and
  `-cleanup` staying the deliberate stop are unchanged. Not measured: this was
  not reproduced against the shipped renderer, and nothing here counts how
  often a player opens a modal during a stream.

- **The settings page kept its model alive after the window closed.** The
  presenter builds a fresh `SettingsModel` for every settings window, and the
  stream pane handed that model two closures to call when a value it shows
  changes. The model holds them, and each closure reached the pane through a
  local function -- the pane keeps the model as an environment object, so
  model held closure held pane held model, and every window a player opened
  and closed left one behind. Nothing about settings behaved differently while
  it leaked, which is the usual way a leak is found late: the page answered,
  animated and closed on cue. The notifications were checked first and are not
  it -- five are selector-based, which the centre holds weakly, and the block
  one captures `self` weakly and is removed in `deinit`. The closures now
  capture the model weakly, read it through their own argument and write the
  pane's state through a binding, so nothing on that path leads back. The
  harness added in this round compiles these closures as written and counts
  releases: as shipped the model goes, with the weak capture removed it does
  not, and the answer the page shows is identical in all three.

- **Two stores nothing was going to read stayed because a baseline said so.**
  `AppCellView` asked its window for the mouse location, converted the answer
  into the view's own coordinates and never used it, and `mouseModeToggled:`
  set a menu title that both of its branches then overwrote. Both were on file
  in `scripts/analyzer-baseline.json` as accepted findings, and that is why
  they survived every reading of those files: an accepted finding is a claim
  that somebody looked and chose to keep it, and nothing on disk recorded
  anybody having done that. Removing them changes no behaviour the analyzer
  can see, and the sweep went from 41 findings across 19 entries to 39 across
  17 with no other entry moving, which is the only baseline change that is
  evidence rather than a refreshed number.

- **The discovery stack and the apps page were kept alive by their own
  callbacks.** `MDNSManager` was told to report hosts to the
  `DiscoveryManager` that owns it and held that promise strongly, and
  `AppAssetManager` did the same to the apps page that asked for box art.
  Under ARC a bare `id` ivar is strong and so is `@property id<X> name;`, so
  neither read as anything special: each pair owned the other, nothing could
  release either, and the hosts page built a new pair every time it refreshed
  while every host whose artwork was fetched leaked the page behind it. Both
  references are weak now, and the rule is that a back-reference to an owner
  is weak or its reason is written down with a line that has to still be true
  -- five reasons stand today, including the stream's delegate, which is safe
  because the page nils its controller support on the way out. Three planted
  defects and the scan's own 17 sites are in the aggregate.

- **Installing the microphone helper could stop the app instead of saying
  so.** `makeLaunchdPlist` answered with `try!` on the argument that its
  property list is a literal of plist-safe types and cannot throw. That is a
  claim about that day's source, not a property of the type: one field added
  beside it that is not plist-safe, and the trap sits on the way to installing
  a privileged helper. It throws now, and the caller already had a failure it
  could show, so the answer costs nothing. No shipping Swift source may trap
  unless it has argued for the trap; two storyboard `init(coder:)` stubs stand
  argued for, and the scan reads 33 files.

- **A shortcut capture could outlive the page that opened it, and go on
  writing shortcuts.** Both capture sheets read keys through an app local
  event monitor, because that is the only thing that sees a chord no control
  will accept, and each sheet removed its monitor from `onDisappear`.
  `SettingsOverlayPresenter.dismiss()` takes the page out of the view tree
  itself, and two of its exits -- Command+W, and the host window closing --
  arrive while a sheet is open. Whether SwiftUI then runs that sheet's
  `onDisappear` is a question about the SwiftUI version doing the presenting,
  and the monitor is app local, so one left behind answers a keyDown by
  writing a shortcut into the player's settings and swallowing the key, in
  every window, including the one streaming a game. The token belongs to
  `SettingsKeyCaptureMonitor` now rather than to a view: the page's teardown
  ends the capture, a capture takes the slot from whoever held it, and a sheet
  ending reports which capture it started, so a late `onDisappear` cannot stop
  the capture the player just began. The monitor asks that type what to do
  with each key instead of closing over one sheet's handler, which is what
  makes an ended capture leave a monitor with nothing to say -- the keys go
  back to the game. Eight rules and three planted defects are in the
  aggregate, and no claim here depends on what SwiftUI does: the keyboard
  comes back whichever way that goes.

- **The Command+W fix came with a probe that crashed the runner.** The first
  version asked a second window whether it held a settings page, and the Debug
  probe died on its way to the report, so the fix reached CI with every local
  gate green -- green because the one gate that reads that page had been filed
  under "needs a CI build artefact" and skipped. The assertion now asks one
  window the same question on both sides of the page: no page in it before the
  present, a page in it after. That is the predicate the filter consults, so
  it is the answer that decides whether the gesture comes back, and the probe
  records `settingsReportedBeforePresent` rather than only asserting it.
- **Command+W closed a stream window, and the settings page was not the
  reason.** The filter that makes the gesture mean "go back" is an app local
  event monitor, which sees the key in every window the app owns. It asked the
  presenter to dismiss a page in the window the event named -- which does
  nothing when that window has no page -- and then returned nil anyway, so the
  key was gone either way and Window > Close stopped working in every window
  except the one holding settings. The event now goes back to AppKit unless
  that window is the one holding the page, asked through the same
  `isSettingsPresentedInWindow:` the accessibility bridge already uses. The
  launch probe asserts both halves: the window with the page owns the gesture,
  and a window that never held a page does not report the gesture as its own.
- **`v1.4.0-beta.1` lost to `v1.4.0-alpha.9`, so a version could not mature.**
  The tag grammar accepts `-alpha.N` and `-beta.N`, and the ordering folded
  all three suffixes into one counter, so the highest prerelease already in
  the tree had to be beaten by number alone. A channel rank now comes before
  the number inside it -- alpha, beta, then stable -- while a bare version
  still sorts below every build of itself, which is what keeps `v1.3.9`
  refused once `v1.3.9-build19` shipped. Four self-test cases cover the
  transitions: alpha to beta, beta to stable, an alpha sequence going
  backwards, and a beta arriving after the version already shipped.
- **A gradient could sit on the glass and the audit would call that
  compliant.** The rule says the glass is the system's to draw, and its list
  of prohibited spellings stopped at blurs and materials: `LinearGradient`,
  `RadialGradient`, `AngularGradient` and the `.linearGradient` family of view
  modifiers were all undetected, so a panel could hold one native effect and
  paint depth by hand beside it. Every prohibited spelling now has its own
  fixture -- twelve needles, twelve planted defects -- because one planted
  blur proves the loop runs and nothing about the needles that come after it.
- **A later job could answer for the release job's own gate.** The workflow
  check took everything after the release key, which is the whole tail of the
  file -- correct today only because release is the last job. The day a
  rehearsal or a dry run calls `scripts/release-gate.py` below it, that check
  passes while the release job publishes ungated. The audit now reads one job
  body up to the next key at the same indentation, and exercises the boundary
  against a fixture whose later job holds the gate call.
- **A missing host identifier would have crashed the page instead of matching nobody, and only a
  warning the local sweep could not run said so.** `TemporaryHost.h` declares `uuid` with no
  nullability annotation, so the importer hands Swift an implicitly unwrapped `String`, and
  `host.uuid ?? ""` never reached its right-hand side -- the branch the guard exists for. A
  host whose identifier this app had never learned would have unwrapped nil and taken the
  settings page down, which is the opposite of what the sentence above it claims. Read through
  `as String?` the fallback is a fallback again, and the compiler stopped objecting because it
  was no longer being asked to promise something it could not deliver.
- **The devices page reported a host decision that nobody heard.**
  `/serverinfo` either answered or it did not, and the panel had two states for the answer and
  none for the silence: no address, a failed request, an error status, or a reply from a different
  machine all printed `host-refused`. That contradicts what this repository already decided for
  the session layer, where unanswered and refused are two stops precisely because a slow host and
  a full host must not look the same in a log -- and it sent the player to the PC's settings when
  the thing to check was the connection. `host-unreachable` is a fourth state now, named separately
  in the page and the audit line, held in orange rather than red because nothing is broken, and
  never sticky: changing the selected host clears an answer that belonged to another machine, which
  the page used to keep showing. Two planted defects cover the two ways that went wrong.
- **The devices page would have told a player their host refused devices when it offered them.**
  The page compared the `uniqueid` of a `/serverinfo` answer against the stored host, and the
  advertised tag against `"1"`, both untrimmed. Every other tag read from that response is
  trimmed by `ServerInfoResponse` before it is stored -- which is why the stored uuid is trimmed
  and the fresh answer was not -- so an answer carrying the whitespace an XML reader leaves
  behind fails the comparison, and the panel reports a refusal it then states as fact. The
  harness could not see it, because a harness hands the model a clean `@"1"`: the defect lives
  in the seam between the transport and the model, not in either. Both sides are trimmed now,
  the model refuses to be fooled whatever its caller does, and four cases plus a planted defect
  cover the shape a clean literal never takes. The same comparison carried a second hole: an
  absent stored uuid and an absent answer are two missing strings that compare equal, which
  would credit whoever replied on that address with the paired host's capability bit. An unknown
  identifier now matches nobody.
- **A Swift type check read a whole tree as clean while `xcodebuild` failed on the same source.**
  The gate located an error with a pattern that refused spaces, and the compiler locates an
  error inside a macro expansion at `macro expansion @State:7:71:` -- a location with a space
  in it. The one complaint in the tree was therefore read as prose, the run printed `clean`,
  and the build job found it twelve minutes later: exactly the failure this gate exists to move
  earlier. The locator now accepts a space in either kind of location, and it had to be paired
  with a rule rather than just widened -- on a host without Xcode's macro plugin, expansion
  errors are what a refused plugin does to the code around it, which is unreadable rather than
  wrong. So an expansion error counts as a defect only when no plugin was refused in that run,
  which is every host that has the plugin and every CI runner. Two self-test cases pin both
  halves. The nested case is why the rule is keyed on the run rather than on the macro the gap
  names: `@State` expands into `_StateInitialStoredValue`, which is where the renamed factory
  method actually surfaced.
- **The enumeration no longer relies on a key name the kernel does not publish, and its
  harness no longer drives it with shapes nobody hands over.** Measurement found
  `USB Vendor ID` absent from every one of the 21 unique nodes on the bus -- the identifiers
  that answer are `idVendor`/`idProduct`, as numbers. **An earlier version of this entry also
  claimed no node published a serial number, and that claim was wrong**: the probe asked for
  `USB SerialNumber` while the kernel publishes `USB Serial Number`, with the space, and a
  probe cannot report that it asked for the wrong name. Measured with the right key, the
  serial answers on 7 of 10 device nodes and 11 of 11 interface nodes, so digesting it is the
  work the design assumed it was, and `token=none` appears when a device really has none. The
  node count in the same entry was the probe's own eight-per-class cap rather than the size of
  the bus; that cap is gone. The fixture set now carries the measured node shapes, including a
  product name on every node and identifiers on the interface nodes, which is what pins two
  rules previously asserted only against invented input: a product name stays out of the
  diagnostic line, and walking only the interface nodes still identifies the device instead of
  recording a visible thing as anonymous. Three planted defects cover the aggregation -- stop
  at the first node, read identifiers only off a node that carries no interface, collapse
  duplicate interfaces -- and the compiled run now reports its own case count, refused below a
  floor.

### Maintenance

- **Stage 3's activation callbacks are now read by a gate, and the staged half
  is held staged.** `staging/driver-
  extension/MLDriverExtensionActivation.{h,m}` translates Apple's activation
  delegate into `MLDriverLifecycle`: `Completed` activates, while
  `WillCompleteAfterReboot`, `requestNeedsUserApproval:`, the replacement
  question, a canceled or superseded request, and every shape nobody
  recognised -- a code off the list, an error from another domain, a failure
  that carried no error, a callback value this switch does not carry -- change
  no phase, because none of them is evidence that anything is installed.
  `MLDriverLifecycle` gained one stop, `build-cannot-load-extension`: eight of
  the error codes are about this build -- no entitlement, a signature the
  system will not accept, a bundle it cannot find -- and reading them as
  `user-declined` blames a player who never saw a dialog for a certificate,
  then lets the retry path ask again for a result that cannot change. The
  source sits outside `Limelight/` because that group is file-system-
  synchronised, so anything dropped under it is compiled into the product
  whether or not anybody wired it; `driver-extension-signing-audit.py` now
  reads the project file and refuses staged code that reaches it, staged code
  that lost its `UNLOCK(stage3)` marker, and staged code that outlived the
  signing prerequisites (self-test 10 -> 15). `scripts/driver-extension-
  activation-tests.py` compiles the pair against the SDK headers the build
  itself uses -- 54 compiled assertions, 12 planted defects, and every
  `OSSystemExtension*` name checked against that header, so naming a method
  Apple does not have is a build failure -- and the three Apple calls that
  need a loadable extension to answer are compile-verified rather than
  claimed. One citation is also corrected: `driver-lifecycle-tests.py`'s
  header credited design 2.3 with an
  `OSSystemExtensionErrorAuthorizationFailed` measurement it does not contain
  and this SDK's error enum does not name.

- **The control-center shortcut now logs when it has no capture to return.**
  The hand-back sits inside the capture guard, but `shouldSendInputEvents`
  turns on as soon as the input context binds -- before any mouse capture --
  so forwarding without a capture is a state a player can reach, and this
  entry then opens a panel with no held-key release on the path. Whether that
  state can strand a key is recorded as open rather than cleared: the
  synthetic probe delivered a key up to the window behind a sheet in one
  revision and not in the next, so the code states what it knows -- a debug
  line with the two numbers, and a warning on the one combination that has
  nothing to return -- instead of what it cannot prove.

- **A new assertion keeps the disconnect alert from opening over a key the
  host still holds.** `-performClose:` hands the keyboard back before the
  sheet goes up, and that order is the one the release-on-uncapture family
  relies on: a release needs a live input context, and once a panel owns the
  session nothing after it runs until the player answers. It is now an
  `ordered_once` rule, and its mutant moves the call into the alert's
  completion handler -- every word stays in the method, while a key held when
  the close shortcut opened the panel stays down on the host for as long as
  the panel is up, which is the outcome the family exists to prevent. The rule
  pins the order the code has rather than a claim about AppKit: probes against
  a bare command line harness disagreed with themselves about whether a sheet
  keeps a key up from reaching the window behind it, and that harness is never
  the active application, so nothing here asserts what a sheet swallows.

- **The CoreFoundation property rule now asks one class, not one repository.**
  It used to join every source into one string and look for `...Release(name)`
  anywhere in it, so a handle was cleared by whoever happened to release one
  under the same name. The shipped tree shows the shape: `HIDSupport` owns
  `displayLink`, `VideoDecoderRenderer` owns one of its own under that same
  name and releases it, and the rule cleared HIDSupport's handle on that
  evidence -- right answer, wrong reason, and the next class to borrow a name
  would have been cleared by whichever class released first. `class_segments`
  cuts the text along `@interface`/`@implementation` lines (a category or a
  class extension names its class first, and a `-tearDown` inside `HIDSupport
  (Private)` still runs on a HIDSupport), and a declaration that falls outside
  every class -- the planted snippet, or a file-scope one -- is filed under a
  name no release can share rather than going unanswered. The refusal now
  names the class it blames. Two mutants went into the assertion battery:
  HIDSupport stops releasing its display link in both places, which the name-
  matching version never saw because the other class kept releasing its own,
  and a class reader that matches no class at all, which is visible to the
  planted pair because the tree it then blames is the whole tree.

- **The assertion battery now refuses to start writing into a checkout
  somebody is standing in.** It plants defects by editing the shipped sources
  and restores what it read, so a run stopped between the plant and the
  restore leaves the planted defect in the tree -- one such run left the
  record of a forwarded key press sitting after its dispatch in
  `HIDSupport.m`, on a file that also carried an uncommitted edit, and nothing
  in the checkout said which of the two wrote what. An earlier uncommitted fix
  was simply found gone after a gate had run over the same working tree.
  `refuse_a_dirty_checkout` asks git, before the first write, whether any file
  the battery is about to edit differs from HEAD, names the files, and exits
  rather than guessing; `--allow-dirty` is the escape hatch, and it says so
  out loud. The reader is judged both ways by `constraints-audit.py`,
  including the rename line where git names both sides, and a rule refuses a
  battery whose guard exists but is never called before the write.

- **The two observer rules each got a mutant that has to be caught.** Five
  went into the assertion battery: taking the withdrawal out of
  `-viewDidAppear` while leaving the comment that describes it; throwing the
  app delegate's token away again; making the probe never hide the window, so
  it never learns that `-viewDidAppear` arrives twice; making the lifecycle
  reader match a method AppKit never calls; and making the stored-token reader
  answer yes without looking. The first two are judged against the shipped
  tree, the third against the harness that measures the premise, and the last
  two against the planted files -- a rule that stopped looking is only visible
  to its own self test, because a clean tree is exactly what a dead rule also
  reports. All five were applied and reported by hand before the battery ran
  them, and each mutation anchor is read out of the shipped file rather than
  retyped, so a moved line fails as an anchor rather than passing quietly.

- **Two timer rules, and the measurement that says they are not guesses.**
  `constraints-audit.py` now refuses a repeating timer that names one run loop
  mode -- which includes `+scheduledTimerWithTimeInterval:` -- and refuses a
  repeating timer whose only stop is its owner's `dealloc`, which is not a
  stop, because a repeating timer keeps the object it polls alive and that
  object therefore cannot reach the code that would end it. Both land at zero
  exemptions over the six repeating timers in the app: all six name the common
  modes, and all six are stopped on a path that can run. Each rule carries its
  planted counter-example, and `scripts/timer-registration-tests.py` measures
  both premises by compiling and running the shapes rather than quoting the
  docs. The reachable-stop rule was first written too wide -- it asked every
  timer an object stores, eleven names, and one of them an iOS-only file --
  which demands a stop the measurement gives no reason to demand, since a one-
  shot releases its target by firing; it now asks only the timers that repeat,
  and a planted one-shot that is stored and never stopped asserts the narrower
  rule stays narrow. Three mutations join the battery: the pointer poll back
  into one mode, its stop taken out, and -- aimed at the new harness itself --
  having it drain the default mode and report the count as the modal one. 128
  mutations become 131.

- **Two more kinds of handle the app borrows from the system now have to give
  it back.** An IOKit registry iterator and a CoreFoundation-typed property
  were both read by hand this round -- six IOKit locals in `USBBusSnapshot`,
  the only file that walks the registry, every one released, and three CF-
  typed properties, every one released -- and "read by hand" describes today.
  clang's AST calls `@property (nonatomic) IOHIDManagerRef` an assign, so ARC
  does not own a reference like that, and the analyzer catches the store it
  cannot follow, not the owner that never hands it back. A leaked
  `io_iterator_t` is worse than a leaked block: it pins a walk over the live
  registry, so it accumulates against the kernel's map. Each rule now carries
  a planted counter-example that has to stay red -- a walk that never releases
  its iterator, and a `CFReadStreamRef plantedStream` nobody releases --
  because a rule that only ever answers "clean" is the defect it was written
  to catch. `iookit-rule-blinded` and `cf-property-rule-blinded` join the
  battery: each blinds its guard so the rule returns nothing, which turns the
  planted case green and the gate red. 128 mutations, 128 caught.

- **The display link got the net the HID manager already had.** `HIDSupport`
  releases its CoreFoundation manager in `dealloc`, because four run loop
  callbacks hold that object as their context and a manager left scheduled is
  worse than the leak. Its display link is the same shape one property later
  -- a CF reference an assign property does not own, and a C callback whose
  context is this object -- and had no such net, because the only stop it has
  lives in `tearDownHidManager`. That still covers the app today, and this
  round checked it rather than assumed it: an `HIDSupport` is built once in
  `prepareForStreaming`, the one call site that rebuilds it stops the previous
  one first, and the stream controller's `dealloc` stops the last one, so no
  path drops a running link. So nothing player-visible is repaired here; what
  changed is that a claim about code that has not been written yet is no
  longer load-bearing. The callback is the riskier of the two -- it runs on
  the display link's own thread and converts its context straight back into a
  strong reference without asking whether anybody still holds the object.
  `constraints-audit.py` now refuses the release missing or out of order, and
  `display-link-outlives` joins the battery: taking the release out turns both
  assertions red, and putting it back turns them green.

- **An accepted analyzer warning now has to carry the reason it was
  accepted.** `scripts/analyzer-baseline.json` keeps sentences explaining why
  every tolerated finding is tolerated, and `analyzer-audit.py` pairs a reason
  to a warning by looking for the reason's key inside the warning text. Read
  against the tree, none of the four keys on file appear in any of the seven
  warning shapes, so every accepted class looked unexplained at once and the
  notice meant to name a finding that had lost its explanation was saying it
  about every line in the file -- which is the failure mode where the signal
  stops existing. `--self-test` had been green throughout, because its fixture
  keys phrases the way the contract asks and only the real data broke the
  contract. Every reason is now keyed by a phrase from the shape it explains,
  the built-in table is keyed the same way and tested against that fixture,
  and a class with no reason on file fails the audit instead of earning a
  notice. The reasons were rewritten from this round's reading: clang's AST
  says `@property (nonatomic) IOHIDManagerRef` is `assign ...
  unsafe_unretained`, so the `CFRelease` in `dealloc` is the one release
  rather than an over-release, and the eight dead stores are five habits -- a
  default a later branch recomputes, an argmax cursor whose last write fed
  only the comparison it lost, a layout cursor advanced past the last control
  of a row, an iOS-only read the macOS build compiles out, and a block that
  reads a weak self-reference after the assignment the path model stopped
  following. `accepted-finding-without-a-why` joins the battery and answers
  "explained" to everything; it fails three of the self-test assertions, so
  the new gate is known to be able to fail.

- **A changelog entry cannot lose its bullet twice.** Three entries had become
  `- - `, which no markdown renderer reads as a list item, and they survived
  two rounds because every changelog rule reads sentences, round numbers and
  section headings -- never the bullet itself. `constraints-audit.py` now
  refuses a doubled bullet, and because the file is clean today it also plants
  one before it reports success: a rule that passes on a tree with nothing
  wrong in it has proved nothing.

- **The compile gate now reads the half of the app the fork edits least.**
  `scripts/compile-audit.py` walked `Limelight/macOS` and `Limelight/Stream`
  only, which is where most of this fork's work lands, and it reported 56 of
  56 as though that were the app. Discovery, pairing, the asset retriever, the
  database and the crypto helpers reached a runner before any local command
  type-checked them -- including the two files this round's leak fix changed.
  It now covers Network, Database, Crypto, Utility and the one source at the
  top of `Limelight/`: 82 of 82, with `CryptoManager.m` reported as skipped on
  a checkout with no vendored OpenSSL headers rather than counted as clean.
  `Limelight/Input` stays out on purpose: five of its thirteen sources are
  iOS-only and ask for UIKit, and a gate that reports failures the build does
  not have is a gate people stop believing.

- **The sweep now says which skipped gates a laptop really cannot run.** The
  render probe was listed with the ones that need a runner, and it does not:
  it builds its own Debug binary and measures the page inside the app, which
  is exactly the check a change to the probe owes itself before a push. Twenty
  minutes is a reason to skip it on every save and no reason to claim it
  cannot be run, so the skip line names the command.
- **The membership audit read the project file backwards, and the build log
  says so.** `Limelight` is a synchronized root group, and its one exception
  set lists 137 entries, 93 of them implementation files. Exceptions mean "not
  a member", so the audit had been reading that list as the target's explicit
  member list -- the only reading under which the tree makes sense. It is not
  the reading the build gives. Every one of those 93 files appears on a
  `CompileC` or `ScanDependencies` line, and the linked binary is missing 0 of
  90 first-party classes, because the target carries no
  `fileSystemSynchronizedGroups` at all: neither the group nor its exception
  set is attached to anything, and the target's own sources phase holds three
  `PBXBuildFile` entries with no file reference behind them. The audit now
  treats an entry as an exclusion only when that association is present, says
  out loud when the project carries membership metadata nobody attached, and
  takes `--build-log` -- which both macOS build jobs now hand it, straight
  from the step that wrote the transcript -- as the authority for whether a
  file was ever compiled. Its planted defect changed with the semantics: the
  old one deleted a line from the list, which under the real rules excludes
  nothing, and the new one writes the association Xcode writes when a folder
  joins a target, which makes 127 exclusions real at once and is caught.
- **A cancelled job restored the tree and then died reporting a clean
  restore.** The battery plants each mutation into the real file and puts it
  back in a `finally`, and a SIGTERM runs the same restore on its way out,
  emptying the table first. The `finally` then popped a key somebody else had
  already restored, so a cancelled CI run ended in a traceback after the
  sources were safely back. It now checks whether the tree is still its job to
  put back.
- **The generated header was looked for in one configuration only.** `local-
  gates.sh` hands `swift-typecheck.py` the header map a build left behind, and
  it probed only the Debug intermediates -- so a laptop that had just built
  Release, which is what the build job's own command line asks for, was told
  the gate needed an artefact it had just written, and the type-check gate
  left the local count silently. It probes both configurations now, Release
  first, because that is the order a build most often leaves them in.
- **The README promised a switch for everything on the settings page and then
  did not list the one a player now has to find.** The devices page had
  shipped -- its pane, its rules table, its four host states -- while both
  language copies of the feature list stopped at the log panel. They list it
  now, and say what it is: a page that enumerates a bus this build cannot hand
  over would otherwise read as support that failed to appear.
- **The warning rule left the build job's shell and came home to `scripts/build-warning-audit.py.**
  `local-gates.sh` takes its list of gates from the `python3 scripts/*.py` calls in the
  workflow, so a check written as `grep` was never on that list and never ran on a laptop.
  The one gate that would have refused
  `left side of nil coalescing operator '??' has non-optional type 'String'` in a first-party
  Swift file therefore ran only after a push, beside a local build log that already contained
  the line. It has one home now, four self-test cases -- one of them that exact line -- and a
  workflow check that refuses an inline copy of the rule surviving next to it. It is registered
  as needing a build transcript, a thinner excuse than most of the others and worth reading:
  the script runs anywhere, it cannot invent the build it judges, so point it at the log your
  own build wrote before calling a local sweep green.
- **`local-gates.sh` counted a gate that had read nothing as a passing gate.**
  It cut `--derived` and `--log` off the command line and ran what was left, on the theory
  that each such gate has a self-contained invocation besides. The gates left with no input
  printed that they had nothing to check and exited zero, and the sweep reported them green:
  the Swift type check, which needs one build's generated headers, sat in a passing count of
  forty while it checked no file at all. Cutting the flag is also the wrong answer --
  `compile-audit` type-checks all 56 macOS sources from a bare checkout -- so each artefact
  gate now answers for itself in `artefact_command`, with what it needs written down beside
  the answer. The honest count here is 41 passed and 11 skipped; the twelfth appears when
  `LOCAL_BUILD_LOG` names the transcript of a build this checkout actually ran.
- The Stage 1 gate reports what its run proved and how many cases the binary executed,
  instead of a count transcribed into a document. Two shapes the measured bus never published
  are pinned anyway -- an identifier as raw bytes, and as a list -- because the parser can be
  handed both, and each has a planted defect that turns the run red if either blob is ever
  read as an identifier. The bus-shape classifier is exercised from this gate too, so the
  measurement that justified the fixtures is checked on runners that have no USB devices.
- Neither new state machine reads a clock, and that is enforced rather than asserted in prose:
  the gates check that `NSDate`, `CACurrentMediaTime`, `clock_gettime`, `gettimeofday` and
  `NSUserDefaults` do not appear in the sources, so a timeout has to arrive as an event the caller
  reports. A run of either harness on a machine whose clock is wrong gives the same answers.

## [1.6.0-build1574] - 2026-09-22


### Added

- **The `input` block now says which pointer mode it is describing before it prints a single
  number.** `relative dispatches 0` has two opposite readings: an absolute-pointer session
  sends no relative packet at all, so that report describes a client working as configured,
  while a locked-mode session with no relative dispatches is the failure issue 24 is about.
  The digits are identical, so a reader in an issue thread cannot tell the two apart. The
  block prints `pointer mode` and `absolute pointer path active` ahead of the counters, and
  neither waits for the `Input Diagnostics` switch: like the strategy and the CoreHID answers,
  they are written by the code that decides them rather than inferred from the row a settings
  page displays. That also collects the one measurement issue 24 still owed -- whether
  `NSEvent.deltaX` still reports motion while the system's cursor association is off -- on the
  reporter's own machine. A locked `pointer mode`, a non-zero `pointer events` count and a
  non-zero `relative motion` count answer it; zero deltas against non-zero events say the fix
  is a delta source that does not read cursor position, not another sentence in a document.

### Maintenance

- **The report harness now says how many checks it ran, and refuses a case list below a
  floor.** The v1.5.0 notes quoted a check count taken from the harness' own printed output,
  which is the tail of the driver transcript rather than its case list, so that number was
  wrong from the start and nothing would have noticed it going on being wrong. The compiled
  binary now prints how many assertions it executed and the harness rejects a case list
  shorter than a floor, because a test whose cases were quietly deleted keeps reporting
  success -- only the number notices. Release notes say what a run proves instead of quoting a
  count that drifts, and the published v1.5.0 body was corrected from the same file.

## [1.5.0-build1570] - 2026-09-22


### Added

- **The copyable diagnostics report now carries an `input` section, which is what issue 24 was
  waiting on.** A pointer that stops moving during a session left one trace only: a line in the
  in-stream overlay, gone the moment the overlay is. The numbers behind it lived on the stream
  view controller and its `HIDSupport` instance, both released before the copy button is
  reachable, so the report a player could paste had nothing to say about the mouse. The block
  carries the strategy the settings resolved together with the value stored for it, whether
  CoreHID was allowed by that strategy, whether the session attempted to start the driver,
  whether it delivered movement, and the reason if it failed; the sender that last handed motion
  to the host and how long ago; and, with `Input Diagnostics` on, arrived versus dispatched
  versus suppressed counts, raw versus sent deltas, capture and rearm counters with their top
  reasons, and the packets that reached the host counted per sender, with the relative and
  absolute paths kept apart. The sender line, the strategy and the CoreHID answers are recorded
  by the code that produces them rather than by the logging switch, so they survive a session
  that ran without it -- and a session that ran without it says so instead of printing zeros,
  because zeros there read as a pointer that never moved when the truth is that nobody counted.
  `scripts/diagnostics-report-tests.py` compiles the block with a real clang, drives it against
  a session whose state is known exactly, and re-plants seven defects in it, among them a block
  that describes a session that never started and one that prints counters nobody collected.

## [1.4.0-build1568] - 2026-09-22


### Fixed

- **The rename had a second half nobody had done.** A bundle's binary is named after
  the product as well, and three consumers had `Contents/MacOS/Moonlight` written into
  them -- the render probe, the DMG audit and the integration test -- so the probe failed
  on the runner looking for a file the build no longer produces. Each now asks the bundle
  which binary it points at (`CFBundleExecutable`), because the bundle is the thing that
  launches it. The same run also caught a single `nullable` annotation added to a header
  that carries none: one annotation is enough to turn on
  `-Wnullability-completeness` for the whole file, which arrived as 360 new analyzer
  findings and a red analyzer job. It is gone, and a local `xcodebuild analyze` now
  confirms zero new findings before a push instead of eight minutes after one.
- **The product rename broke every build from a clean derived data path.** A
  Swift generated header is named `$(PRODUCT_NAME)-Swift.h` by default, so
  naming the bundle `MoonlightEnhanced.app` silently renamed the header to
  `MoonlightEnhanced-Swift.h` while 17 Objective-C files went on importing
  `Moonlight-Swift.h`. A stale derived data path made a local build report
  success and hid this; the analyzer job and the render probe, which both start
  from a clean path, failed in twenty-four seconds. The name the compiler hands
  back is a compile-time contract rather than a name a user reads, so it is now
  pinned to `Moonlight-Swift.h` in both configurations: the disk name moves, the
  imports do not. `constraints-audit.py` compares the pin against every import of
  it in the tree, and the battery re-plants both ways it can go wrong.

- **A mouse strategy nobody chose used to be the one that switches CoreHID
  off (issue #24).** `MouseInputDriverStrategy` read its stored value with a
  `default:` case pointing at the retired `.compatibility` mode, so a host
  with nothing stored, a number written by a future build, or a corrupted
  value was handed the one mode whose observable effect is that CoreHID never
  starts -- while the settings page displayed the default, so nothing on
  screen said the pointer had been left to a single source. An unrecognised
  value now means "nobody chose yet" and lands on the default strategy.
- **The input path line is now written by whoever moved the pointer
  (issue #24).** The `AppKit compatibility active` sentence was written where
  a pointer event arrived, which is upstream of every reason that event is
  still dropped before the host sees it: suppressed inside the warp window,
  quantised down to a zero-pixel move, or routed to the absolute path
  instead. A CoreHID start failure wrote an `AppKit fallback active` line on
  top of that, naming a replacement nothing had observed. Each sender now
  credits the line itself, after its packet is handed to the host, and a
  CoreHID failure reports only that CoreHID stopped, with the reason, leaving
  the sender line uncredited until a sender appears.

### Removed

- **The mouse strategy labelled "HID" (issue #24).** Its label said HID and
  its only effect was to stop CoreHID, the client's highest-polling relative
  mouse source, from starting; its single Objective-C reader,
  `shouldUseCompatibilityMouse`, had no caller anywhere in `Limelight/`, so
  choosing it changed nothing else. A setting whose label recommends the
  opposite of its effect is not a troubleshooting option, and the settings
  row that used to describe it was an orphan string no code ever asked for.
  The case is retired with its raw value held reserved, so a stored `0`, the
  string `HID` the menu no longer lists, and an absent value all resolve to
  the default instead of being reinterpreted as some other mode.

### Performance

- **The input path line stops rewriting itself.** The `GameController active`
  and `Absolute pointer sync active` lines were written once per frame of
  pointer motion, which re-encoded the same sentence into settings sixty
  times a second. A sender now credits itself once, and it is the previous
  sender's credit that makes the next change visible.

### Changed

- **The build no longer replaces the Qt client's app (issue #41).** Both
  clients installed themselves as `/Applications/Moonlight.app`, so
  installing one quietly removed the other, and the fact that their bundle
  identifiers differed did nothing about it: the collision is on the file
  name, not the identifier. The bundle is now `MoonlightEnhanced.app`, and
  the name a user reads -- in the Finder, the Dock and the Force Quit list
  -- is a display name the system localizes: `Moonlight Enhanced` in
  English, `Moonlight 增强版` in Chinese. The disk name stays ASCII so a DMG
  layout, a codesign path and a README install line can all quote the same
  string without asking a shell to cope with non-ASCII paths. What did not
  change is the bundle identifier, so the paired identity in the Keychain
  and the permission grants still describe the same application to the
  system. What a user of an older build of *this* repository has to do is
  delete the `Moonlight.app` this repository left behind: two bundles
  carrying one identifier in `/Applications` is how LaunchServices ends up
  launching the stale copy while the grants follow the old path. The name
  is now read rather than copied -- `scripts/project_identity.py` is the
  only reader, it refuses the Qt name when it reads it, the workflow asks it
  for the name before it writes a single path, and the DMG packaging, the
  codesign step, the README install lines, the permission helper and the
  image audit all ask it too. A rename that left one of those copies behind
  would have shipped an image whose bundle name no gate had ever looked at.

## [1.3.10-build1559] - 2026-09-21


### Added

- **A failure now leaves something behind: a diagnostics report the player
  can paste (issues 19, 28, 33, 35).** Five open upstream issues are stuck
  in the same place: the report describes a symptom, the maintainer asks for
  the machine's answers, and the thread never gets them, because assembling
  them by hand is a chore nobody will do while their game is down. The app
  assembles it now. One action builds English text carrying the app version
  and build, the macOS build, the model and CPU, whether Gatekeeper is
  running the app out of a read-only `AppTranslocation` mount (the condition
  that silently voids the grants a player believes they gave), what the
  system answers right now for Input Monitoring (`IOHIDCheckAccess` for both
  listen and post, plus the CoreGraphics preflight), Accessibility and
  Screen Recording, which Bonjour services the bundle declares and whether
  `_nvstream._tcp` is one of them -- the first question an "every other
  client finds my host" report has -- the hosts in the store with their
  paired and online state, and the tail of the app's own debug log, read from
  the end of the file rather than whole.
  `Limelight/macOS/Helpers/DiagnosticsReportBuilder.m` holds the shape and
  the rules and `DiagnosticsReportBuilder+Live.m` the measurements, because a
  rule that needs a running app cannot be driven by a harness.
- **What that report may not carry is executed, not reviewed.** A report is
  code writing down whatever it was handed, so no amount of reading shows a
  PIN leaving; `scripts/diagnostics-report-tests.py` compiles the shipping
  builder and drives it with planted secrets -- a PIN stated in a sentence, a
  password, a pairing secret, a base64 certificate, a MAC address, a UUID,
  another user's home path, this machine's -- and every one has to come back
  replaced by a marker such as `[redacted-pin]`. Two controls matter as much:
  `NSLocalNetworkUsageDescription` is longer than the blob threshold and all
  letters, so it has to survive a rule written for base64, and an ordinary
  line has to arrive unchanged. The size policy is played too: a report
  built from four thousand log lines has to fit what an issue body takes, and
  what gives way is the oldest lines -- the version, the macOS build, the
  permission answers and the newest lines may not. Eight defects are planted
  one at a time in the source under test (newest lines replaced by oldest,
  the PIN rule narrowed to a length no host uses, the blob pass removed, the
  home path kept, the log block no longer giving way, an empty section no
  longer saying so, every long token treated as a secret, the UUID prefix
  lost) and all eight are caught. Three fields are never read, and the gate
  refuses the file if anyone starts: the host MAC address, the pinned
  certificate, the client UUID.
- **It is offered where the app already knows it failed.** The pairing
  failure alert carries a `Copy Diagnostics` button beside `OK`, because that
  alert is the moment a report is worth having, and the settings pane's Debug
  Log section gained `Copy Diagnostics Report…`, which says afterwards
  whether the clipboard took the text -- a button that only appears to work
  stays invisible until somebody replies asking for the information that
  never left the machine. The English text is deliberate: the reader is
  whoever triages the report, not the player whose language the menus are in.

- **10-bit samples can now carry an SDR picture (issue #22).** The Qt client has two
  controls here and this client had one: HDR was the only route to a 10-bit format bit,
  so the combination the protocol plainly allows -- 10-bit encoding of an ordinary
  desktop -- could not be asked for, and a player wanting smoother gradients had to take
  PQ or HLG with it. `Limelight/Stream/VideoFormatNegotiation.h` now holds the answer,
  and the request carries `hdrRequested` and `sdrTenBitRequested` as the two separate
  things they are: Limelight.h itself keeps the profile bits in
  `supportedVideoFormats` and the picture's dynamic range in `dynamicRangeMode`, and its
  own comment calls that field the preferred range "for HDR-capable 10-bit streams", a
  statement about the picture rather than a consequence of the profile. A switch appears
  in the video pane beside 4:4:4, per host, off by default, because a preference nobody
  chose must not change what a host encodes. It is not wired to the bitrate: deeper
  samples carry the same picture at the same bitrate, so raising the target would charge
  for something nobody asked for.
  `scripts/sdr-10bit-codec-tests.py` compiles the shipping negotiation with a real clang
  against the core headers and drives all 32 combinations of its five inputs. The first
  thing it compares against is the answer that shipped before this change -- the old
  if-chain, kept beside it as a model -- and the two may not differ anywhere the new
  switch is off: a refactor that quietly improved one combination would be reported, not
  enjoyed. Then the new request itself: the 10-bit bits appear under SDR; the 10-bit 4:4:4
  profiles appear with it; AV1 switches profile rather than offering two, so its 8-bit
  bit has to go while HEVC keeps its separate 8-bit Main bit; HDR plus the switch is the
  same answer as HDR alone; and a Mac with no 10-bit codec in hardware advertises none.
  The reported symptom is a colour one, so the second half matters more than the bits:
  the dynamic range is taken from the file that decides it and swept across every
  transfer preference with HDR off, and the answer may not move, which is the rule that
  would catch the oversaturation if this client ever routed an SDR stream to the BT.2020
  path. Six planted defects have to be noticed -- the request ignored, the request turned
  into a second HDR, AV1 left at 8-bit, the dynamic range starting to follow sample depth,
  a machine with no 10-bit codec promised one, and 10-bit SDR refused as unsatisfiable.
  What it does not claim: no stream was played against a real host, so "the host accepts
  10-bit for SDR and renders it correctly" is reasoned from the protocol and the
  renderer's existing 10-bit path, not measured. The row says a fallback happens where
  the host cannot encode it; that fallback is what the host does, not something this
  repository observed. Where to look once someone does play it: the connection logs the
  request and the answer together (`sdr10bit=` beside `tenBit=` and the resulting
  `formats=`), and the diagnostics panel already reads the selected format's 10-bit mask.
  The stream picture the risk assessor prints is the one place that still names chroma
  without naming depth, so a screenshot of it cannot tell 10-bit SDR from 8-bit.


- **`scripts/local-gates.sh`, so a local sweep means the whole list.** The red build
  above was green locally: six gates had been run by hand, and the one that failed was
  not among them. The tree carries forty-odd gates now, so the list is read out of
  `build.yml` rather than remembered -- a gate added to CI runs here next time, with no
  one having to recall it. Gates that need something only a runner has (an xcodebuild
  log, derived data, a built `.app`, a tag or a matrix arch the checkout does not carry)
  are named and counted as skipped, never run with an empty argument: a local sweep that
  reports a failure the tree does not have is worse than one that admits a gap. Folded
  steps are unfolded before they are read, which is what turned up two invocations whose
  flags live on the following line. `--all` runs the full constraint battery;
  `--list` prints the commands it found. The list is checked before the first gate
  runs, because a sweep that quietly drops a gate is the failure this exists to end: a
  call left folded, or written in a shape the reader does not know, is now reported
  instead of gone. `--self-test` plants one of each, and it caught this script's own
  first version, whose unfold pattern asked for two backslashes and matched none. What
  it cannot yet do is protect itself in CI: the workflow it reads is the thing that can
  break it silently, and a push that touches `.github/workflows` needs a token scoped
  for workflows, which this one is not. `bash scripts/local-gates.sh --self-test` as a
  step in the audit job is the missing line, and the workflow's existing
  `bash -n scripts/*.sh` loop is what covers it until then.

### Fixed

- **The localization audit forgave a row the parser stops at.** Writing the 10-bit row
  above, the insertion lost its closing semicolon on both language tables. `plutil -lint`
  rejected the file; the audit, which is the tool that was supposed to catch it, reported
  zero failures, because its own reader treated a terminator as optional and walked on.
  Walking on is what makes this invisible rather than merely untidy: the broken row and
  the row after it both come back as entries, so the entry count agrees with the count the
  rules read, symmetry sees two complete tables, and every number is consistent with the
  others while CoreFoundation has stopped reading the table at that line. The reader now
  reports an unterminated entry with the line it begins on, and the shapes are planted --
  a row that forgets the semicolon, and a last row that forgets it -- because a rule
  nobody broke is indistinguishable from a rule nobody wrote.

- **A gate that read the file it was auditing, and went red when that file stopped
  existing.** `gameplay-modifier-tests.py` asked for the reserved-shortcut wording
  inside `LanguageManager.swift`, which is where the sentence lived until the tables
  became the only carrier. Deleting the two dictionaries left the wording exactly
  where the app reads it -- one entry in each `.strings` table -- and left the gate
  counting a file that no longer holds it, so the arm64 and x86_64 builds failed on
  a message about wording that was present. The gate now reads both tables and asks
  each one for a non-empty value, which is what the app will actually find. Proof it
  has teeth rather than merely being green: with the key deleted from a copy of the
  English table, the gate reports the missing English wording and fails.
  `LanguageManager.swift` was the last gate still pointing at a deleted carrier;
  the whole `scripts/` tree was swept for the pattern and nothing else matched.

- **Two entries shared one line, and every rule in the localization audit was
  scoring a table with a row missing.** The audit reads a `.strings` table with a
  line-anchored pattern, which is correct for a table written one entry per line and
  silently wrong for any other layout: an entry that begins after a `;"` on the line
  above it never matches `^"key" =`, and an entry whose value carries a real newline
  is only half inside any line. Both shapes are legal OpenStep plist, and
  CoreFoundation reads them without complaint. `Clipboard Sync detail` was written on
  the same line as the entry before it, in both tables, line 795 in each. It
  translated correctly at runtime and was invisible to coverage, symmetry,
  placeholder and duplicate checks alike -- an entry no rule was watching, so a
  rename or a one-sided edit to it would have passed CI. The line is split in both
  tables, with the parsed tables compared key by key before and after to show that
  not one string changed. Two checks now keep the two views of the file together: the
  table is parsed entry by entry the way OpenStep does it, and every entry has to be
  one the line-anchored rules can actually reach, while the entry count from that
  parse has to equal the count the rules read. The parse is asserted rather than
  trusted -- a second entry riding on a line and a value carrying a real newline both
  have to be reported, while an ordinary table and a commented-out row both have to
  pass. The planted case caught a first draft of the check that treated any entry
  starting on an anchored line as visible, which is precisely the mistake the check
  exists to prevent. The cross-check first reached for `plutil`, and the constraint
  battery refused it: a rule that only answers on a macOS host fails the same way the
  `grep` it replaced did, by going quiet somewhere else, so the table is read here
  with no helper at all.


## [1.3.10-build1544] - 2026-09-21


### Changed

- **The debug log panel's category menu and badges now speak the system language.**
  Issue #30 asked for English in the context menus and the logs; the reason there was none
  is that these strings were never keys. `MLLogCategoryDescriptor` stored the text itself --
  the name written bilingually (`发现 / Discovery`), the badge Chinese-only (`发现`) -- so an
  English system had no key to look up and rendered what the source said. The descriptor now
  stores `nameKey`/`badgeKey`, the two language tables answer them, and the name stops being
  printed in both languages at once. The filter box was not left behind: it matches every
  localization plus the ASCII keys the log lines carry, so an English player can still paste a
  Chinese category name and find it. What this recorded rather than claimed:
  the panel's rewritten log-line titles were left Chinese-only and became a number instead of
  an invisible assumption. The first Changed entry below is that number reaching zero.

- **The log panel's own sentences became keys, and the recorded debt reached zero.** Issue #30's
  second half was the sentences the panel writes itself: 55 Chinese literals arrived at `title:`
  and `detail:` inside `DebugLogParser`, so a Chinese system read its log in Chinese and an
  English system read the same panel as half Chinese titles over half raw English lines. They are
  58 keys now -- three of them `String(format:)` templates, because `Error code %@` is a sentence
  with a number in it while `\(captures[0]) -> \(captures[1])` is not a sentence at all -- and the
  row translates them where it renders. `displayTitle` and `displayDetail` live on the entry and
  `localize()` is not in the parser, because a row is parsed once and drawn again after a language
  change, which is the moment a title translated at parse time starts being wrong. The filter box
  kept up: every table's value for a key joins the search index, so the box answers a Chinese
  category name while the row shows English. Two gate changes carry the weight rather than the
  edit. The key collector reads a fifth shape -- a literal handed to `title:` or `detail:` in that
  one file, escapes excepted because an interpolated host name is data -- so a key no table
  answers fails coverage instead of sitting in the panel as source text forever, which is what
  `keys_handed_to_a_row` and its four self-test cases exist for. And `UNTRANSLATED_OUTLETS` is
  empty, kept as an empty dictionary because the check below it is written to read one: a file in
  that dictionary is a debt somebody chose to carry, and carrying none is the rule now. What this
  does not claim: no screenshot of the panel in two languages, because there is no build of the
  panel to photograph on this machine -- `swift-typecheck.py` and `l10n-audit.py` are the evidence
  here, not a picture.

- **The app had two localisation tables per language and asked the older one first.**
  `LanguageManager` carried two Swift dictionaries answering 227 keys, and `localize()` consulted
  them before the tables in the bundle. Three things followed, none of them visible from either
  layer on its own. 21 Chinese and 6 English rows in `Localizable.strings` were text no user ever
  read, because the dictionary answered first -- including `Disconnect Alert`, whose dead row was
  the actual question and whose live row was the key, so the disconnect dialog greeted the user
  with `Disconnect Alert` instead of asking anything. 131 keys existed only in the dictionaries,
  which put them outside `scripts/dmg-audit.py`: that audit compares the tables **inside the
  released image** against the repository, so those sentences were the one part of the
  localisation never verified in the file a user downloads. And the log panel's filter box indexes
  the `.strings` tables while the UI showed the dictionary, so a player could copy a phrase off
  the screen, paste it into the box, and be told there was nothing. The dictionaries are deleted
  (the file is 613 lines shorter), `LanguageManager` asks one table, and the move was checked by
  replaying the old lookup order against the new one for all 1123 keys in both languages: **three
  rows change what a user reads**, and all three are rows where the text that could never take
  effect is the text that is right -- the disconnect question in both languages, and the Chinese
  hint for YUV 4:4:4, which credited the graphics card for something the host provides. Four
  rules keep the shape: the dictionaries may not come back, a Chinese row must say Chinese unless
  it is a name or token a player searches verbatim (sixteen of those are named), both tables must
  answer a format string with the same placeholders `String(format:)` is handed, and no row may
  hide a lookalike character -- the last one paying off on arrival, because nine Chinese rows
  wrote `Wi-Fi` with a non-breaking hyphen, so copying it off the screen produced a string no
  search box or log file matches the ASCII word against. Twelve self-test cases cover the four.
- **One bundle per language instead of one per lookup.** `localizedString(_:languageCode:)` built a
  `Bundle(path:)` on every call, and the log panel calls it for every key in every language to
  build a search index it rebuilds per log line: a few thousand rows on screen meant tens of
  thousands of bundle allocations for answers that cannot change while the process runs. The
  bundles are resolved once per language now.
### Fixed

- **A log line stopped arriving in the language of the machine that wrote it.** Five log strings
  ended with `Help → 诊断连接问题`, which names a menu item whose English title is
  `Diagnose Connection Problems…`: an English system was told to open an item that does not
  exist there, and a log body written in Chinese is text `DebugLogParser` and `NoiseSummaryNames`
  would have to match in two languages forever. PR #44 asked for exactly this kind of translation
  inside `Logger.m`, and the answer given there was that a log body is data; these five were the
  rest of that answer. `l10n-audit.py` now refuses a log call whose literal is written in CJK --
  the macro definition exempted, since its parameters are not bodies, and a sentence behind
  `MLString()` exempted, since a key belongs to the tables -- with the self-test required to see
  all three shapes. CJK rather than non-ASCII on purpose: an em dash in an English log line is
  typography, and a rule that refused it would be one nobody intends to enforce.
- **A permission prompt could be translated in the repository and untranslated in the
  download.** Issue #44's fix installed the `InfoPlist.strings` tables and read them back --
  from the bundle being signed, which proves the bundle at signing time. The image is
  packaged after that, the universal merge writes over `Contents/Resources`, and every job
  stayed green while a table went missing, because the image audit asked about the drop
  target, the version, and the checksum, and never about localization. `scripts/dmg-audit.py`
  now compares the tables inside the image entry by entry against the repository's own: a
  language missing, a table whose text is not the source's, a table for a language no source
  provides, and a table that translates none of the prompts the `Info.plist` declares are each
  rejected, and the self-test has to see all six shapes. The published
  `v1.3.10-build1537` universal image passes it -- build 1537, both tables, all three
  `UsageDescription` keys translated in both -- so the sentence a user reads in a prompt is
  now verified in the file a user downloads rather than two steps earlier. What the rule still
  cannot do on the ubuntu audit runner is mount anything: `verify_images` binds the bytes, and
  the mount stays a macOS-host assertion.

- **A Chinese string written where a player reads it is now refused, and the debt that
  remains is a number that has to shrink.** Issue #30's second half. The rule is about the
  outlet, not the characters: `containsAny(line, ["正在连接"])` is data the parser compares
  log lines against, and translating it breaks the match rather than the language, so 55 of
  those literals in the same file are correctly left alone. What is refused is a Chinese
  literal arriving at a named UI parameter (`title:`, `badgeText:`, `messageText:`, ...) or
  inside `Text()`. `scripts/l10n-audit.py` also counts `nameKey:`/`badgeKey:` as localization
  requests, which is the only reason the panel's new keys cannot silently stop being
  answered -- without that, a table that stopped replying would print `Discovery · mDNS`
  and report complete coverage. `UNTRANSLATED_OUTLETS` holds one ceiling per file and fails
  in both directions: a file that grows past its own number, and a number that is still
  sitting above what the tree now holds. Verified by breaking the tree three ways -- adding a
  Chinese badge, lowering the recorded number without paying it, and deleting one table
  entry -- each refused, then restored to `0 localization failures`.
## [1.3.10-build1537] - 2026-09-20


### Added

- The half of USB device redirection that a client cannot finish alone is now a document
  another repository can say no to. `docs/usb-redirection-host-contract.md` states the
  capability a host has to answer in `/serverinfo`, the session messages it is asking for,
  and what each side has to prove before either calls the pair compatible. Everything it
  rests on was read this round with the command printed beside it: the core submodule and
  the upstream public header carry no USB symbol at all, Sunshine's `virtualhid_input.cpp`
  and the one function that assembles `/serverinfo` are both real and named by file and
  line, and a search of that host's issues for the feature returns nothing -- which is the
  same answer upstream gave here. The proposal borrows the shape of the clipboard, because
  `LiSendClipboardItem` is the existing proof that a new payload can ride the reliable
  control channel and be chunked by the core. It also says plainly that the three new
  symbols do not exist in either tree, and that the client keeps its capability read
  unwired until a host can be observed answering it: wiring a check no one consumes,
  against hosts that never send the field, would be code that cannot be tested even once.

- A controller's Menu button can be handed back to the game. Holding it past a second and
  letting go has flipped mouse mode for as long as this fork has had a controller, with a
  rumble to mark it, and a player whose game needs that hold had no way to keep the button
  -- issue #45. The switch is per host and defaults to on, which is the behaviour every
  build until now, and it is read per press, so turning it off lands on the next hold
  rather than the next connection. `scripts/gamepad-menu-gesture-tests.py` compiles the
  decision with a real clang and drives it with samples rather than seconds: a release at
  exactly one second stays the game's short press, a hold nobody released has not toggled,
  one release cannot fire twice, a hold begun while the switch was off does not inherit a
  timer, and a hold that straddles the switch coming back on does not bank the time it
  spent off. Six planted defects have to be noticed, and one of them was the shape this
  change's first draft actually had: the idle state was written as `-1.0 / 0.0`, which is
  minus infinity rather than a NaN, so it compared, subtracted, and answered "still
  holding" forever -- every release toggled. The sample table found it, and it needed a
  case of its own before the frozen-timer mutation could be told apart from the fix.

- A player whose Copy and Paste habit is a Control habit can now keep it. `Command Key Sends
  Control` is a per-host switch, off by default, that makes every Command chord arrive on the
  host as Control. It was not built as a mode: `KeyboardCompatibilityMode` was reduced to one
  case in `a43313f`, whose own commit message records the removal of all six legacy modes as a
  breaking change, and `docs/input-mapping-benchmark.md` §5.5 is what that deletion cost in
  over-claimed language rows. Nothing here resurrects a rival table -- the one table still
  answers, and the preference relabels the two Windows bits inside its single answer, which is
  why a Command press under the switch cannot send Control and Win at once. A translation rule
  could not have carried this: a rule names one chord, and Command-as-Control has to hold for
  every chord a player might press, including the rules they bound with Command. `scripts/command-to-control-tests.py`
  compiles the mapping with a real clang and pins both answers across the mask, the keycode and
  the AppKit-flags paths; seven planted defects have to be noticed, including the two half-mapped
  shapes (the shortcut path still answering Win, the typed keys answering Ctrl) and the shape
  where a release of one of two held Control keys takes the key away. The default is written
  twice, in C and in Swift, and the gate is what compares them. Two things it does not claim:
  the switch is unverified end-to-end against a real host, since nothing here has a Windows
  desktop to type into; and with the switch on, no key sends the Windows key at all, which the
  setting's own text says rather than leaving the player to find. The pane names the key the same
  way now: `remoteDisplayTokens` takes the switch, so a rule whose output was bound with Command
  reads Ctrl on its card once the switch is on, with Control and Command counted as the one bit the
  host is told about. The three ways that agreement could rot -- the branch ignoring the switch,
  the two keys counted twice, the card asking for nothing -- are planted for the gate to notice.

- The secure attention sequence has a button. `docs/input-mapping-benchmark.md` §5.3 had already
  worked out that nothing was missing mechanically -- macOS does not intercept Ctrl+Alt+Del the
  way Windows does, so an ordinary translation rule carrying Control, Option and Forward Delete
  reaches the host -- and that the gap was that no player would ever think to write one. The rule
  editor therefore gained an `Add Preset` menu whose one entry prefills exactly that rule, and no
  new mechanism: the preset builds its chord once and hands the same value to the trigger and the
  output, so the two cannot drift, and the sheet it opens still says "Add", because a player who
  asked for a starting point is not editing anything. `scripts/keyboard-shortcut-modifier-tests.py`
  gained a scenario that fires that chord through the shipping `sendSyntheticRemoteShortcut:` and
  reads the packets the host would receive -- Left Control down, Left Alt down, 0x2E down and up,
  released in reverse, with Control and Alt in the modifier byte -- and `scripts/sas-preset-tests.py`
  pins the button to that chord, reads the local actions' own default chords to prove none of them
  already claims Control+Option+Forward Delete, and refuses either half drifting: a preset built on
  Delete instead of Forward Delete, a wire test moved to another key, a wording the table stopped
  answering, a local action stepping onto the same chord, and a preset that opens as an edit. Six
  planted shapes, all noticed. What remains unproven is stated in the document rather than here: no
  Windows desktop was in the loop, so the packets are asserted and the effect on a real login
  screen is not.

### Fixed

- **A settings menu with one item was not a choice.** The keyboard panel kept a picker over
  `KeyboardCompatibilityMode` after `a43313f` left that mode with a single case, so opening it
  listed `Streaming Standard` and changed nothing. The row now states the mapping as text, which is
  worth reading, and leaves the deciding to the Command switch underneath it, which is the only
  thing there a player can actually decide. `scripts/command-to-control-tests.py` pins both
  directions, because the tidier-looking wrong fix was right there: a row that shows nothing also
  clears the menu, and asks the player to guess what the app does to their keys.

- **One gesture kept two clocks, and a design document called it missing.** The Menu long
  press was implemented twice, once per controller driver: a 16 ms timer in
  `ControllerSupport.m` reading `gamepad.buttonMenu.pressed`, and
  `updateButtonFlags:state:` in `HIDSupport.m` reading `PLAY_FLAG`. Each kept its own
  `NSDate` on the shared `Controller` and each compared it against its own private `-1.0`,
  which is how a boundary that has to mean one thing to a player ends up meaning two. Both
  now ask `MLGamepadMenuGestureToggles`, so the requirement is one number in one file and
  the switch is one preference read by both paths -- which is what the issue's "both input
  paths read this switch" asked for. The same document had recorded this gesture as absent,
  because it had looked only at where `toggleMouseMode` is called (the keyboard shortcut
  path) and concluded there was no controller gesture at all. That row is corrected in
  `docs/usb-redirection-design.md`, and it is worth saying why it mattered: a finished
  feature written down as a gap makes someone rebuild it, and it takes the credibility of
  every other row in that table with it.

## [1.3.10-build1529] - 2026-09-20


### Added

- A pointer moving into the stream window no longer has to take the window. Issues #21 and
  #40 are one mechanism: the tracking area is installed with `NSTrackingActiveAlways`, so
  `mouseEntered:` arrives while Moonlight is in the background, and the entry path made the
  stream window key, which activates the application. The decision now lives in
  `MLPointerEntryActionsForState` instead of five early returns inside an AppKit callback,
  and the mouse panel carries a switch for it. The default is yes -- what every build has
  done, and what a player who clicked in and stepped the pointer out to a second display
  should keep. Turning it off gives #21 what it asked for: the window keeps tracking the
  pointer and waits for a click. Gated by `scripts/pointer-entry-takeover-tests.py`, which
  compiles the decision with a real clang, drives every input field on its own, compares
  the C and Swift copies of the default that nothing else compares, and has to notice six
  planted defects in the decision and one in the wiring.

- The first layer of USB device redirection: a policy that refuses every device until an
  allow-list entry earns the yes, a host capability read that treats an unanswered
  question as a no, and an audit line that carries a digest of a serial number instead of
  the serial number. Nothing here opens a device, loads a driver, or adds an entitlement:
  `docs/usb-redirection-design.md` records why the protocol and the signing identity make
  the device itself unreachable today, and what has to be true before it is. Gated by
  `scripts/device-redirection-policy-tests.py`, which compiles the shipping answer with a
  real clang and has to notice all nine planted defects.

- The second layer, still without touching a device: reading the bus honestly.
  `MLUSBDeviceIdentity` answers one question from the IORegistry properties any plain user
  process can already read -- what may be *said* about a device that is plugged in -- and
  needed no new entitlement and no driver extension to do it. Identifiers arrive as numbers
  or as hex text under more than one key name; text that is not hex shaped stays `unread`
  rather than becoming a decimal guess, because a vendor id that was misread is a device
  offered against the wrong rule. A serial number is digested where it is read and never
  stored, so no object this layer builds carries one, and the diagnostic line names the
  device by that digest and states the refusal that applies to it. An interface whose
  protocol byte never arrived is treated as a boot input rather than a harmless one: the
  cost of that reading is a device nobody plugged in, and the cost of the other reading is
  the keyboard of whoever did. What is deliberately missing is a user interface -- a list of
  refused devices, shown while the host protocol still has no device channel and the signing
  identity still cannot load a driver extension, advertises a feature that does not exist.
  Gated by `scripts/usb-device-enumeration-tests.py`, which compiles the enumeration and the
  Stage 0 policy as one translation unit and has to notice six planted defects: the serial
  written out, the serial dropped so every device looks alike, an over-long string parsed as
  an identifier, half a hex number believed, one protocol byte shared across two interfaces,
  and a key name struck from the list. The fourth is why the gate also feeds it a four
  character half-hex id: the length guard alone hides that defect from every longer input.

- HDR-to-SDR tone mapping gained the choice upstream PR #47 argued for, without any policy
  changing the number it applies today. The overall exposure used to be a literal inside the
  Metal source, where the only way to learn what a policy actually applied was to read the
  shader and do the arithmetic. It is now `MLHDRSdrExposureForPolicy`, and the kernel is
  handed the answer through a uniform component it never read before. The policy that answers
  1.0 -- nothing shifted, reference white left to the transfer function and the metadata -- is
  the new `No Exposure Shift` entry under Tone Mapping Policy. Auto, the three Preserve
  policies and Reference keep 0.82 for PQ and 1.08 for everything else, which is exactly what
  they applied before the constant moved. Two other asks from that pull request turned out to
  be already answered rather than missing: an HDR stream can be told to use PQ explicitly
  today, and `Peak` in EDR Strategy is the "use the headroom the display reports" behaviour.
  Gated by `scripts/hdr-sdr-exposure-tests.py`, which compiles the answer with a real clang
  across all eighteen policy-and-transfer pairs and has to notice seven planted defects: three
  in the answer, four in the structure around it -- the constant back inside the shader, a
  kernel no longer handed the value, a picker that lost a policy, and one policy meaning two
  different numbers in two languages.

- A benchmark for the one surface nobody had benchmarked. Every claim this project makes
  about input has been checked against itself: seventeen gates say what our keyboard does,
  and none of them says whether anyone else does it better. `docs/input-mapping-benchmark.md`
  reads five other clients and records which tier each sentence earns -- readable here,
  fetched upstream, advertised by a vendor, or not evidenced at all -- because the
  alternative to that discipline is a document that says Parsec does it well. Parsec turned
  out to be unbenchmarkable: its documentation answers 403, its archive came back empty, and
  it has no public repository, so the document says so instead of guessing. What the reading
  found is that the keyboard axis is not behind. Upstream's streaming preferences are
  twenty-five booleans, enumerable in one command, and not one of the twenty-five names a
  key, a modifier or a shortcut; Citrix's much-copied hotkey table binds eleven fixed remote
  actions to a chord drawn from four modifiers crossed with seventeen keys, where this fork
  records any chord against ninety-seven keys; the Command-becomes-Ctrl feature ToDesk
  advertises is what `MoonlightClassic` already does, plus the symmetric Control-to-Win
  half. Two things came out of it anyway, because a benchmark that only confirms you are
  fine was not worth the hour. Citrix's per-hotkey entries are bindings and not ownership --
  the ADMX keeps the two mechanisms apart, the capture tier is a separate value, and its
  Windows-key instance is the reason that axis exists on Windows and cannot exist here. And
  the secure attention sequence has no preset, though it needs none of the machinery Citrix
  reserves for it, because macOS does not intercept Control-Alt-Delete: the rule editor's own
  table already carries Forward Delete and accepts the two modifiers. The gap that survived
  is the one already being worked. ToDesk sells tablet and 3D-mouse passthrough, which is
  device redirection and not key mapping, and that is USB Stage 2. No behaviour changed, and
  every number in the document came out of the commands printed in its own last section.

### Removed

- Seven sentences that described settings which no longer exist: `Shortcut Translation Mode
  Keep Mac detail` and its five siblings plus `MoonlightClassic`, left behind when
  `KeyboardCompatibilityMode` was cut to a single case. They survived because nothing asks for
  them, which is precisely why they were dangerous: `docs/input-mapping-benchmark.md` read
  those rows and reported seven keyboard translation modes this fork does not have. Both
  tables dropped them together (1029 keys became 1024 each), and §5.5 of that document now
  records how a language table was mistaken for a feature list, so the mistake has a written
  end rather than a corrected sentence.
### Fixed
- **Setting a custom resolution turned off a switch nobody had touched.** Three places in
  `SettingsObjCBridge.swift` rebuild the whole `Settings` value by hand -- read what is
  stored, spell all ninety-one fields out again, change one thing, persist -- and one of those
  ninety-one rows read a different field than it named: `hoverActivatesStreamWindow`
  was being handed `settings.emulateGuide`, sitting directly under the `emulateGuide`
  row it had been copied from. So choosing a custom resolution wrote the controller Guide
  switch into the switch that decides whether a pointer entering the stream window may
  activate it. Both default to on, which is why it survived review and survived CI: the fault
  only surfaced for a player who had turned controller Guide emulation off, and for that
  player it was silent -- one setting
  changed by another setting, with no page to look at afterwards and nothing in the log. The
  field is carried by its own name now. `scripts/settings-rebuild-passthrough-tests.py` reads
  the three tables and refuses three kinds of fault: a row that hands a field some other
  field's value, unless the rename is written down with a reason; a rename written down that
  no row uses any more, because an unused exemption is a hole with a note beside it; and a
  whole table that no longer matches its neighbours, since a dropped row is the same fault
  arriving as the initialiser's default. It mispells the original row in the table that
  actually shipped it, and in one that got it right, and drops a row, and invents a rename,
  and registers one nothing uses, and has to turn red for all five and stay clean for the
  tree. It promises three tables that agree; what it does not promise is that every field of
  `Settings` is spelled -- a field that gains a default and disappears from all three tables
  would still pass, and that limit is written where the code is. Needs no toolchain, so it
  rides `scaling-output-evidence-tests.py`, which is a step on every macOS build, and
  `constraints-audit.py` now refuses that entry if the driver stops reaching the call.

- **The keyboard page asked for two strings no language table had.** Both were invisible to
  the audit that says localization is complete. The picker's option label reaches `localize()`
  as a variable holding an enum's `displayKey`, and the explanatory sentence under it is the
  return value of a computed property; neither literal sits inside a call, so the scan had
  never seen either key, and the sentence had meanwhile been written *as* its own English key.
  An English user could not tell the difference, because a missing key renders as itself and
  in both cases the key happened to read as English. A Chinese user read two lines of English
  inside a Chinese page, on the one setting that explains what their keyboard is going to do.
  The property now returns a key and both tables answer it and the option label, which reads
  流式标准（推荐） in Chinese. The scan now also reads keys a variable carries, in the two
  shapes the settings panes actually use -- 384 referenced keys became 394 -- and it is
  deliberately narrow there, because a scan that invents keys fails clean trees: its fixtures
  cover a `*Key` property and an enum `displayKey`, and refuse a property that merely returns
  English. Deleting either of the two new table entries, in either language, or renaming the
  option label without adding an entry, turns the audit red.


- **Permission prompts reached users in a language nobody chose.** Two separate faults sat in
  the same few sentences. The local network prompt was written into `Info.plist` in Chinese,
  which is not a translation of anything but what an English system is therefore made to
  display; it reads English there now -- the development region -- and the Chinese arrives as
  a translation of that. And no prompt was ever translated at all, because nothing put the
  language tables into the bundle: Xcode does not produce `InfoPlist.strings` for a
  hand-written plist behind a file-system-synchronized group, and the `INFOSTRINGS_PATH` in a
  build log only names where such a file would go. The proof was an artifact downloaded from a
  green run, carrying neither the strings file nor a `.loctable`, which is also the reading
  that an earlier commit here had to take back after it had moved those tables beside the
  plist on the assumption that proximity was enough. `scripts/codesign-bundle.sh` installs the
  tables before the signature seals the bundle, refuses to sign when the repository declares
  no table to install, and counts what the bundle holds against what it installed;
  `scripts/build.sh` asks that same step of the signing script, so a local build shows what a
  download will show. `l10n-audit.py` refuses a sentence baked into the plist in a language
  other than the development region, a sentence answered by one table and not the other, and a
  language folder with no plist beside it -- each of the three tested against the case it
  exists for.

- **The release tool wrote a changelog heading the changelog audit refuses.** Preparing a
  release was a two-command scramble that ended in a red build. `prepare-release.py
  --apply` promoted the Unreleased heading to the version's own heading with no date on
  it, while the changelog shape audit refuses a released section that lost its date, so
  the tree that had just been told the release gate accepts it failed its own audit on
  the one day it had to ship. The heading carries a date now, taken from the commit the
  tag points at rather than the day somebody happened to run the tool -- the reading
  every tag in this changelog already agrees with -- and `promote()` refuses to write
  text of a shape the audit would reject, so an unusable date ends the command instead of
  leaving a section to repair by hand. The rule is read out of
  `scripts/constraints-audit.py` rather than copied beside it, and one fixture refuses a
  rule that would accept an undated heading, which is what keeps two files that have to
  agree from drifting apart while both stay green.

- **The release preparation reported a release that could not be published.** Preparing
  a release looked like two commands, and the second one cleared a step the first had
  never looked at. The publish step does not write its notes from the changelog:
  `build_release_body.py` reads `.github/release-notes/<tag>.md` and exits the job when
  that file is absent, so a tree answering every rule `release-gate.py` knows about
  still died after three DMGs had been built and downloaded. `prepare-release.py` names
  the file in its report -- before the tag exists, which is the only moment writing it
  is cheap -- and `--apply` no longer calls a release prepared while its body is
  missing. Four fixtures hold the shape: the missing body named by path, a promotion
  that stays incomplete while it is missing, a tag the gate accepts that publishing
  still holds, and the both-present case that has to stay quiet. The rule belongs to
  this line of history rather than to the whole repository: the commit that requires
  curated notes is not an ancestor of the August release, whose tree has no
  release-notes directory at all, while the three releases since it each carry one.

- **A release step that only the person releasing could know about.** The `BUILD_NUMBER`
  fallback in `Limelight/Version.xcconfig` exists for a source tarball with no git history
  to count, and its own comment says it is moved by hand on release tags. Every
  release tag agrees with that comment -- `v1.3.9-build19` carries 19, and
  `v1.3.10-build1508`, `1509` and `1510` each carry their own number -- and nothing
  checked it, so a release made without that edit ships an installable package whose
  tarball rebuild reports the previous release's build. The preparation report names
  it beside the changelog section and the release body, so the three edits a release
  commit owes arrive together instead of one of them arriving as a surprise in the
  About box. Two fixtures hold it: a baseline left behind the tag, and an xcconfig
  with no baseline to move at all.


## [1.3.10-build1510] - 2026-09-19

### Fixed

- **A window of a different shape stretched the picture instead of letterboxing
  it.** A 2560x1440 stream in a 16:10 window was drawn across the whole drawable, so
  every face in it was wider than the stream made it, while every counter on screen
  stayed truthful about a stretch nobody asked for. The metal view resizes with its
  window on both axes, so the drawable is whatever shape the player dragged the
  window into, and nothing anywhere compared that shape against the stream's. Three
  places had each been deciding it alone, and fixing any one of them still leaves a
  stretched picture: the blit's viewport, which is where the stretch happened;
  MetalFX's output size, because a scaler handed the whole drawable writes pixels
  that are already out of shape and a viewport cannot restore a shape the scaler
  never had; and the Video Toolbox super resolution target, one step earlier still,
  together with the enhancement decision that asks whether there is anything worth
  enlarging -- measured against the drawable it can promise a scaler the letterbox
  then makes pointless. One function now answers the shape and every consumer asks
  it, including the warm-up, which used to prepare a session for the drawable's size
  and then never use it, and the scaling evidence, so the size the overlay prints is
  the size a scaler wrote rather than the size of the window. Where the two shapes
  agree the answer is the whole surface: the proportional cases are asserted at six
  source shapes and five multiples each, which is the promise that a stream already
  fitting its screen changed nothing. The bars clear to black, because a drawable
  under a letterbox belongs to no picture and left as `DontCare` it keeps the
  previous frame in them. Two mutation expectations in the scaling evidence harness
  moved with this and moved to the truth: a 1280x720 stream in a 3840x720 drawable
  now reports the 1280x720 it fits to, instead of claiming a 3840-wide present that
  was never made.

## [1.3.10-build1509] - 2026-09-19

### Fixed

- **The settings page could not be left with its own back control.** The page
  reports dismissal through a box it holds weakly, so a control inside the view can
  name the presenter without the presenter handing out `self` before `super.init`
  -- but nothing owned that box, so it was deallocated as `init` returned and every
  press called through a nil. The back control and `Escape` did nothing; only
  Command+W and the host window closing still worked, so the page was one a player
  walks into and can only leave with a shortcut nobody reads. The presenter now owns
  the box for as long as the page is up. The probe had closed the page by asking the
  presenter directly, which proves the teardown and says nothing about the control,
  so it passed on the shape that shipped. It now runs the very closure the back
  control runs -- the code a press executes -- and refuses one that leaves the page
  presented, still mounted, holding the keyboard, or holding the window title.
  Whether the control is also visible to accessibility is reported rather than
  asserted: SwiftUI publishes that tree only to an external client, so a runner
  with no client attached answers empty, and the first version of this probe
  refused a working page for exactly that reason. On its first run the new probe
  found two flaws in itself: the title baseline was read after the presenter had
  already renamed the window, so no close could ever match it, and the keyboard
  hand-back was asserted on a window that is never key, where AppKit does not move
  the first responder at all. Both are now read the way the claim means.

## [1.3.10-build1508] - 2026-09-18

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

- **The release gate refused its own tag.** The release job hands
  `release-gate.py` its `--existing-tags` from `git tag --list`, so the tag that
  triggered the run is in its own list, and the rule against a build that already
  shipped read that as a repeat of itself: `1.3.10-build1508 is not newer than
  build 1508 of the same version`. Every release was unreachable, and the gate
  fixtures had the same shape as the bug, so the suite stayed green while the
  pipeline it guarded could not run. The gate now leaves the tag it is gating out
  of the comparison, and the fixture set carries both sides: the CI shape passes,
  and a tag that a different and higher tag already in the tree outranks still
  refuses.

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

### Round 57: two fingers that share a key code kept only one of them

### Fixed

- The keyboard table sends Return and Keypad Enter to the host as the same
  Windows code, VK_RETURN, and Equals and Keypad Equals as another,
  VK_OEM_PLUS: 114 rows cover 112 codes, so exactly two pairs are shared. The
  record of presses the host had been told about was filed under that
  dispatched code, which is one entry per pair rather than one per finger, so
  letting go of either member spent the record that belonged to the other.
  Capture ending while the other finger was still down then found nothing to
  release: keyUp: stops forwarding once input is off, and the host kept that
  key pressed for the rest of the session.
- The record is filed under the physical key code the event carried and keeps
  the dispatched code as its value, so a release spends only its own entry
  and capture end releases every press the host was told about, twice where
  two fingers were sending one code.
- Measured against the shape that shipped, it leaves the host holding a key:
  pressing Return and Keypad Enter and releasing the second first sends 800DD
  800DD 800DU and nothing more, one press net still pressed, while the
  shipped record also sends the release capture end owes. A pair that shares
  no code, W and Space, comes out identical under both shapes, so what the
  new test reports is the collision and not a general change in behaviour.
- scripts/held-key-identity-tests.py reads the colliding pairs out of keys[]
  itself rather than hard-coding them, presents 3 scenarios to each of the
  two shapes, and refuses the old record. It runs in build_arch, now 41
  steps, and in the aggregate, and the battery carries the mutation record-
  keys-the-dispatched-code, which reddens it (exit 1) when the shipping
  source is edited back to the old identity: 105 of 105 mutations caught.
- The migration had to be the whole record rather than one line of it, and
  the compiler said so: the vocabulary of a set does not exist on a
  dictionary, and clang refuses removeObject: with no visible @interface
  declaring that selector.

### Round 56: the window that needed a scaler was told it needed none

### Fixed

- **A window that is bigger than the stream in a different proportion got no
  hardware scaler at all, and was told it needed none.** The renderer decided
  whether to scale by asking for a scale factor, and a factor only exists
  when the window has the stream's own shape; a window that differed by more
  than two percent on the two axes was answered with a factor of zero, which
  the next line read as "target size does not require upscale" and resolved
  to no engine. So a 1280x720 stream drawn into 2560x2160 -- two times
  across, three times down, what a resized window or a non-16:9 display gives
  a player who asked for MetalFX -- was stretched by the bilinear blit while
  the log blamed the target size. The question was the wrong shape: MetalFX
  is handed an input size and an output size rather than a factor, measured
  here to fill the window it was given on both axes, ramp reaching ramp. The
  gate now asks whether the panel has more pixels to fill than the stream
  delivered, on every axis, and still lets the two Video Toolbox scalers take
  only the factors they were offered, because that is a limit those APIs
  have. An HDR stream enlarged onto the panel is now labelled the direct
  Metal scaling it is rather than a bypass it is not; the pixels are
  unchanged. - **No counter anywhere recorded that a scaler had enlarged a
  frame.** The overlay quotes the resolution of the stream, so a 1280x720
  picture stretched to fill the window and a 1280x720 picture resampled to
  2560x2160 print the same line, and the one figure that separates them --
  how many pixels arrived, and at what size -- was dropped. VideoStats gained
  a tally of scaled frames, its rate, and the size the scaler wrote; the
  overlay shows `Scaled +N fps -> WxH` only when a scaler produced something.
  Two scalers can enlarge a frame here and neither is the blit that shows it,
  so the charge goes through one file-scope decision asked what the encode
  actually did -- MetalFX answers for its own, and Video Toolbox super
  resolution announces itself only by having handed back an enlarged buffer.
  It refuses a present whose sizes came out as they went in: a scaler that
  invented no pixels has nothing to report, and a scaler that only widened a
  frame is resampling rather than making picture. - **Two gates were added
  and one was rewritten to match the rule it now guards.** The enhancement
  sweep went from five hundred and sixty resolutions to six hundred and
  seventy-six, with two non-uniform pairs that have to disagree: two across
  and three down is an upscale, one and a half across and zero-nine-seven
  down is not, since a window shorter than the stream is not asking the
  client to make picture. The new scaling gate lifts the decision and the
  draw pass verbatim out of the renderer and plays three hundred and sixty
  presents, every one of them into a bigger drawable, because the question is
  whether a scaler ran rather than whether the sizes differ. The hardware
  premise underneath the change -- that an anisotropic window is one the
  scaler can write -- is now measured on the GPU that runs the gate, ramp
  sampled at all four edges, and a machine without MetalFX says it cannot
  answer instead of passing quietly.

### Round 55: a stream it could never take was retried every frame

### Fixed

- **On a machine with the interpolation engine, a 10-bit or 4:4:4 stream paid
  for interpolation it could never get, once per frame.** A low-latency
  interpolation configuration accepts one source pixel format, and measured
  here that format is 420v. The decoder is asked for something else whenever
  the stream is 10-bit or 4:4:4 -- ordinary settings, HEVC 10-bit being a
  common default -- so the mismatch arrived on every decoded frame. The old
  shape of the decision fell through to a warmup request; the warmup answered
  that a session for that size already exists and did nothing; the caller
  read that silence as a runtime failure and tore the session down; and the
  next frame built another configuration, asked the hardware for its slots,
  allocated another frame processor and started another session, only to be
  refused at the same line. One hardware video session destroyed and rebuilt
  per frame, a warning per frame, and a settings status that alternated
  between two sentences, so it never de-duplicated and posted to the main
  queue at frame rate. Whether the machine even has the engine decides who
  pays: a GPU with no slots is refused before any session exists and never
  reached this path. The refusal is now remembered as a fact about the
  stream, the session already standing is left alone, the decision lives in
  one file-scope function so the two cannot drift, and the settings page has
  its own sentence instead of borrowing the one that says a session broke.

### Round 54: nothing on earth could say interpolation made a frame

### Added

- **A stream being doubled to 120 FPS reported the same numbers as a stream
  that is not being doubled.** The app could name the interpolation engine it
  had chosen and could not say whether that engine had produced one frame or
  none: nothing in the tree counted a produced frame. The figure a player
  actually reads while streaming, Rd on the performance overlay, is fed from
  the branch that records a first source present, so interpolated pixels left
  the drawable without touching any counter. Two machines running the same
  setting at the same frame rate looked identical, one of them doubling and
  one silently offering no interpolation slots. A present has to choose a
  counter, because both kinds of frame leave through the same drawable, and
  the choice runs both ways: charged to the rendered counter, an interpolated
  frame takes its queue time from a neighbouring frame's enqueue stamp, gives
  the 1% low an 8ms cadence nobody streamed, and reports twice the frames the
  host ever sent; counted nowhere, the work stays invisible. VideoStats
  therefore gained a counter of its own, one file-scope function decides
  which tally a present feeds, the measurement window publishes it as a rate
  as it closes, and the overlay reads it back as "+N Interpolated" beside Rd,
  and only when there is a number to say. Rd stays the source-frame figure,
  so latency and the 1% low still describe the frames that crossed the
  network.

### Round 53: Shift is not a free modifier

### Fixed

- **A rule bound to Shift and a movement key took the keys the game moves
  with.** A keyboard translation rule that fires keeps the press: the client
  consumes the key down, and the release that AppKit still delivers is the
  client's to swallow as well. That is the right bargain for a binding nobody
  reaches by playing, and the wrong one for Shift+W. Shift is sprint, aim,
  crouch-walk and the jump variant, and a player holds it while pressing W,
  A, S, D and the space bar, so such a rule fires during ordinary play: the
  host never learns the player started running forward, and the release that
  does arrive reads as a key letting go by itself. One answer was missing at
  both ends. The settings form accepted any trigger with one modifier, and so
  did the matcher, which is the half that matters, because rules are decoded
  from per-host stored data and normalization repairs identity rather than
  validity. Control, Option and Command are left alone -- no game reads one
  of them as an action of its own, so a binding behind one is not reachable
  by playing -- and a bare Function key is left alone too, since that is a
  binding a person picks knowingly and nothing has reported it.

### Added

- **One question, asked in two languages, answered by one sweep of both.**
  The guard has to exist at two moments that cannot see each other: in
  Objective-C when a key arrives, and in Swift when a person records a
  binding. Two answers drift, so `scripts/gameplay-modifier-tests.py`
  compiles both out of the shipping files -- the inline function from the
  internal header, the Swift function with nothing but a fake shortcut as its
  container -- plays all 128 shapes of the five relevant modifiers with and
  without a key code, and requires the two answers to agree shape by shape.
  Agreement is not correctness, so the shipped defaults are parsed out of
  `defaultShortcuts()` and every one of the ten has to survive: the six
  Control+Option actions, the Command+W that opens the disconnect page and
  the Control+Shift+W that quits are keys a player must not lose. Shift+W and
  Shift+Space have to be named. Three planted shapes fail it -- a guard that
  never fires, one that also seizes Control, Option and Command, and a
  settings form that learned the rule on its own -- and a sweep that checked
  nothing fails with them, because a coverage count of zero is this file's
  own known failure.

- **The rule-consumption sweep now states the second gate as well as the
  first.** That harness promises only that the matcher obeys the gates it
  asks, and it took the answer from the shipping guard rather than restating
  it, so its own statement of what a rule means grew the same clause and two
  of its 1544 cases left the sweep -- the Shift-only presses it used to
  expect a rule to take are now expected to reach the host. Its coverage
  moved from 18 taken and 1520 released to 18 taken and 1524 released, and
  the four planted shapes still fail, one of them now by answering four cases
  wrongly instead of failing to compile.

### Audited, and not changed

- **Two suspected gaps in the shortcut layer are not gaps.** The settings
  form refuses a binding that collides with a translation rule, and the rule
  form refuses a trigger that collides with a shortcut: the check is
  symmetric and both halves exclude the entry being edited, so neither can be
  reached around from the other side. And the settings page is still a page
  inside the main window's content region -- the offscreen probe window that
  counts how many windows host settings is the evidence, and it reports no
  second window.

- **The host cannot regenerate the bridging header, and that is what decided
  where the answer lives.** A Swift method reached from Objective-C needs
  `Moonlight-Swift.h`, which CI takes from the build its analyzer step just
  made. Regenerating it here with the Command Line Tools fails, because
  emitting a header means generating code and `@State`'s macro plugin ships
  with Xcode and not with the tools -- the same gap that makes the 27 SDK
  report itself skipped. So the guard is a static inline in the header the
  runtime already reads, and the Objective-C half calls it without asking a
  generated file for a new symbol: 46 of 46 sources type-check against both
  installable SDKs, seventeen behavioural harnesses pass, the assertion
  battery catches 104 of 104 mutations, and the build job's step list is
  thirty-seven.

### Round 52: the settings page described the feature backwards

### Fixed

- **Frame interpolation reported itself the wrong way round, in both
  directions, while it was working.** The settings page shows two rows about
  this feature: the engine that ran, and a sentence meant to explain it. That
  sentence was chosen by searching the reason for a phrase, and the phrasing
  was the bug. "provides cadence headroom over" and "does not have cadence
  headroom over" share the phrase a branch tested for, so a player whose
  interpolation was running read "the display leaves no headroom,
  interpolation stays off" under a row naming the VT low-latency engine. The
  other direction is worse to act on: a frame that failed after the processor
  existed was caught by the shortcut that asks only whether the engine is
  none, before the word "unavailable" is ever read, so the settings page told
  a player who had turned the feature on that no stream had asked for it. Two
  translated sentences -- the one that says interpolation is running, the one
  that says it fell back -- were unreachable on every machine. The state is
  named now, the sentence comes from a switch over it, and the two readings
  of the runtime branch are chosen from one flag so the log and the page
  cannot part company. Searching a message to decide what to do is the shape
  the pairing layer gave up years ago for exactly this reason.

### Added

- **Every state the renderer can report, checked against what the player
  should be told.** `scripts/frame-interpolation-status-tests.py` enumerates
  eleven states -- five refusals asked of the shipping gate itself, four
  texts lifted from the inline branches, two from the slot verdict -- and
  compares the summary and the detail beside each other, because the two
  render one under the other and a summary naming a hardware engine above a
  detail claiming the feature is off is exactly what a player reads. The log
  sentence is demanded non-empty on every state. Both halves of each report
  are lifted from the call site rather than typed into the probe: which
  sentence a player reads is a pair of a state and a text, and a harness that
  wrote either half itself would be auditing its own transcription. Four
  planted shapes fail, one state each: the working report answering the
  refusal line, a runtime failure answering "not enabled", a landed frame
  still named as a pending one, and a cadence refusal named as an unknown
  refresh rate. The last collapses two refusals into one sentence, and the
  count of distinct answers is what notices -- a player with a 120 FPS stream
  on a 144 Hz panel would be advised to look at the refresh rate sensor
  instead of the frame rate.

- **The wording is checked against the language tables, and the check is
  checked.** Three rules: the detail key comes from a switch on the state
  with no phrase search anywhere in it; every state in the enum has a case;
  every key the switch hands back exists in English and in Simplified
  Chinese. The first version of the third rule collected keys with a pattern
  that could not match a space, so it read six of the ten sentences and
  reported green over the other four -- the same failure this round keeps
  tripping over, arriving in the checker instead of the product. The number
  of returns is now itself a check, and six mutations each turn at least one
  rule red: a word search restored inside the dispatcher, a state added with
  no case, a key no table has, one Chinese line removed, a cast over the
  switch, and prose returned where a key belongs.

- **The harness that guarded the two zero-slot answers now guards the enum
  that replaced the word search.** `video-enhancement-tests.py` used to
  insist that the resolution sentence be tested before the hardware sentence,
  because the settings line was picked by searching a reason and order was
  all that kept the two answers apart. The report enum removes that ordering,
  so the harness asks the enum: each slot verdict has to reach its own state,
  each state its own key, and the two keys have to differ. The mapping is
  compiled into the model that already measures the slot verdicts, so merging
  the answers fails the shipping classifier's own binary rather than a string
  comparison in Python. Two planted shapes fail it from inside the harness,
  and three more were planted in the shipping file -- the two answers sharing
  one sentence, the two verdicts sharing one report, and a phrase search
  restored beside the switch -- each turning the harness red and the file
  returning byte-identical.

### Audited, and not changed

- **The same word search over the enhancement side answers correctly today,
  and was left where it is.** `runtimeDetailKeyForEnhancementEngine:` still
  reads phrases, and every reason its resolver can produce lands on the right
  sentence, because an enhancement fallback never resolves to no engine --
  which is the one thing that let the engine-is-none shortcut pre-empt
  interpolation. The other half is already guarded from outside: the sweep
  added last round refuses a fallback that resolves to nothing. No evidence,
  no change.

- **Four suspicions about this feature were chased and none of them are
  defects.** `@(MLInterpolationSlotReason(verdict))` reads like a C string
  boxed into an `NSValue` and then sent `lowercaseString`, which would be an
  unrecognized-selector crash on the main queue for every Mac whose GPU
  offers no interpolation slots; boxed C strings are `NSString`s, established
  by running it rather than by reading the spec, and nothing is wrong.
  `_lastDisplayRefreshRate` is written from the display link's measured
  output period, so the cadence gate is not reading a zero it never learns.
  The settings page's own cadence analysis disagrees with the interpolation
  gate on purpose: one asks whether the display suits the frame rate, the
  other whether there is room to also show interpolated frames. And
  `frameRate` is an `int`, so the `%d` in the working report is the right
  conversion. No line moved beyond the report itself: `constraints-audit`
  ends at zero failures with the battery at 104 of 104, the behavioural
  harnesses rise to sixteen and the build job's step list to thirty-six.

### Round 51: the answer was being recorded, and never read

### Added

- **The enhancement that runs had never been compared with the enhancement
  that was asked for.** `scripts/enhancement-engine-resolution-tests.py`
  lifts `resolveEnhancementEngineForSourceWidth:` out of
  `VideoDecoderRenderer.m` verbatim and sweeps it against a statement of the
  policy written from the policy. The rules already over this feature ask the
  GPU what it can scale and count the interpolation slots a machine offers,
  which are true things about capability and one step away from the frame;
  the resolver's own answer is stored next to the requested mode and read by
  nothing, so a mode could resolve to nothing everywhere, or to a quieter
  engine than the one picked, and every rule would have stayed green. Seven
  requested modes, HDR on and off, five source-and-window pairs, the three
  capabilities every which way, and four calls that decline the
  out-parameters: 564 resolutions, each judged on the engine, on the scale
  the decision was made from, and on giving a reason at all, because "why did
  my scaler not engage" is answered out of the log and nowhere else. Five
  planted shapes fail 12, 8, 26, 80 and 220 of them: Auto that never reaches
  the hardware it is being offered, an explicit choice replaced by a quieter
  one, a menu read for the wrong frame, a resolution that leaves no reason,
  and one that is always nothing.

- **Expectations are written down rather than recomputed, and the two scaler
  menus disagree on purpose.** The scale each pair of sizes means, and
  whether each menu offers it, are tables in the harness. Recomputing either
  would have made the expectation the code's own arithmetic under a different
  name, unable to disagree with anything. The per-size menu and the any-size
  menu answer differently because the two real APIs do, which is the only
  reason a fallback from VT quality to VT low latency ever gets exercised;
  and the per-size menu answers only for the frame it is asked about, which
  is what turns the 26-case shape above into a failure: ask about the window
  instead of the stream and the machine reports a scaler it does not have,
  silently, because nothing checks which dimensions the question was asked
  with.

### Audited, and not changed

- **The suspicion that the local gate was asking the wrong machine was
  checked and did not survive.** The mode a player picks is named
  `upscalingMode`, which reads like a setting handed to the host for
  execution -- in which case a client-side gate would be settling a question
  it has no standing to answer. It is not: the client turns it into a
  requested enhancement mode of its own before the resolver runs, which is
  the method this round now sweeps, so the decision under test is a local one
  and the gate is pointed at the right machine. `enhancement.vtLowLatencyFI`
  looked like a second switch over the same feature and is not one; it is a
  row of the capability display matrix, and the switch is the upscaling-mode
  option list.

- **The probe was answered by the system before it was ever run, which the
  runtime said out loud.** The stand-ins for the two scaler configurations
  carry the names the shipping source uses, so the lifted text needed no
  adaptation -- and on a machine with VideoToolbox loaded, that produced
  "implemented in both", with either class free to answer. That is the
  green-that-tests-nothing in a new costume: the probe would have been asking
  a real machine what it offers instead of asking the case. The lifted text
  still spells both names as the source does, and the names are bound to the
  stand-ins instead. No product line moved: `constraints-audit` ends at zero
  failures with the battery at 104 of 104, the behavioural harnesses rise to
  fifteen and the build job's step list to thirty-five.

### Round 50: a green sweep that had never fired a rule

### Added

- **A rule that takes a key has to take that key's release, and nothing
  checked it across the two events.**
  `scripts/translation-rule-consumption-tests.py` drives the shipping
  `keyboardTranslationRuleMatchingEvent:` against the shipping suppression
  record in `HIDSupport.m`, with the release path that reads it. The promise
  being tested spans events, which is why the rules already written over that
  file -- counting how many times a method is called -- stay green while the
  state that has to outlive the call is wrong. Two keys, the two from the
  report; every combination of the five modifiers the shortcut layer reads;
  six rule shapes; the guard answering both ways, because what is checked is
  that the matcher obeys the guard rather than what it answers; and three
  shapes of release, the third being one that never arrives at all, which is
  what a window losing focus while a key is held looks like to the record.
  Four planted shapes fail 304, 210, 80 and 6 of the cases: a rule firing on
  extra modifiers the player never bound it to, a shortcut the guard refused
  still taking the key, a consumed press that records no debt, and a press
  that leaves an old record behind so the next release is swallowed with it.

- **A sweep that never reaches its branch reports ok, so coverage is now
  counted and demanded.** The first version of the sweep above came back
  green over every case. A stand-in had forgotten to carry the guard's
  answer, so every shortcut was refused, no press was ever taken, no debt was
  ever recorded, and two of the four planted shapes walked free beside a
  passing sweep. The counts of presses taken by a rule, presses released,
  releases following a taken press, and taken presses whose release never
  came are now printed and have to be non-zero. `known-bad` shapes were what
  eventually surfaced the emptiness; coverage is what says it in one line, in
  the run where it happens, rather than waiting for a planted shape to happen
  to notice.

### Audited, and not changed

- **The remaining suspects in the W-and-Space report were checked and left
  alone.** Four candidates were chased this round and none survived being
  looked at. `MLRelevantShortcutModifiers` keeps the Shift bit, so sprinting
  does not reduce a key to its bare form and cannot make a held key match a
  rule bound to nothing.
  `StreamShortcutProfile.shortcutCanMatchKeyboardEvent` requires a modifier,
  and its own comment names this report -- a bare binding "deletes a movement
  or action key from the host" -- which is the guard the new sweep now proves
  is obeyed rather than merely present. The control-centre pill is a button,
  which on AppKit is a key-equivalent shape worth fearing, but it carries no
  key equivalent and refuses first responder, so a Space pressed during a
  stream is not eaten by it. And the pass-through branch that turns every key
  into a tap -- the shape that made W and Space collide for every held key --
  was fixed in an earlier round and is what the new sweep now runs on top of.
  No product line moved: `constraints-audit` ends at zero failures with the
  battery at 104 of 104, and the behavioural harnesses rise to fourteen.

### Round 49: the orders nobody wrote down

### Added

- **The pair harnesses each replay one timeline; this one plays every order
  the four fingers can make.** The report is W and Space -- walk and jump,
  arriving as one gesture. Two harnesses already drive that pair and both
  pass, so what was left to ask was not which keys but which order. Each of
  them replays a sequence somebody wrote down, which means the orders they
  cover are the orders a person thought of, and a stranded key is exactly the
  kind of defect that lives in an order nobody pictured: the right Shift let
  go between the jump's press and its release, while the left one is still
  holding the sprint. `scripts/key-order-exhaustive-tests.py` enumerates
  instead of imagining. Four keys, each a press and a release, every
  interleaving that keeps each key's own order -- 2520 of them, each against
  a fresh state machine lifted from the shipping file, with a host recorder
  that keeps the modifier byte beside the key code. It borrows its facts
  about the keyboard -- which bit is the left shift, which byte the host
  calls Shift, which Windows key a Mac key becomes -- from the harness that
  already lifts that machine, because a second reader of those facts would
  drift and then check a build the app does not run.

- **Four rules for 2520 orders, and the one that looked right and was not.**
  The host must be told about each key once down and once up; both modifier
  masks must be empty when the hands leave; nothing may arrive that is not
  one of those four keys, so a Shift that goes out as Control reports itself
  instead of slipping through a range check; and every modifier byte must
  agree with the shift keys the host was itself told about. That last rule
  nearly became 'a release repeats the byte its press carried', which reads
  like the right thing and fails most of the sweep for the rightest reason:
  letting go of Shift mid-jump is ordinary play, and then the jump comes up
  without the sprint bit because the host was already told that shift was
  coming up. Agreement, not equality, is the rule. Three planted shapes show
  the sweep can fail -- a press that drops a sprint the other finger holds, a
  release that lifts one, and a release that answers with the raw AppKit flag
  bits -- and each breaks 1816 of the 2520 orders, which is the whole
  argument for enumerating: no single hand-written timeline is obliged to
  come near a third of them. The sweep is its own step in the architecture
  job and is driven by the aggregate, which rose to thirteen behavioural
  harnesses.

### Audited, and not changed

- **The tree is not what was wrong this time, so nothing in it moved.** All
  2520 orders pass against unmodified `Limelight/Input/HIDSupport.m`, and the
  full audit ends at zero failures with the battery at 104 of 104. Before
  that answer could be trusted, the harness had to be wrong three times, each
  in the direction of accusing a correct tree. Its first version cleared the
  left Shift's device bit when the right Shift came up, so the state machine
  -- reading the flag it is supposed to read -- never saw that shift
  released, and the sweep came back red on every order, the planted shapes
  included. Its log drew a shift press and a shift release with the same
  character, so the failure it printed could not name an edge. And it looked
  a host-side virtual key code up in the table keyed by Mac key code, which
  called both W and Space 'Space'. Each of the three could have been 'fixed'
  by bending the shipping file until the probe agreed, which would have been
  a fabricated defect rather than a found one; the file is unchanged this
  round.

### Round 48: the Swift half waited for a runner to notice its types

### Fixed

- **A stale anchor threw away a hundred and three proofs.** The battery
  plants a regression by replacing a piece of text it has found in the real
  source, and it asks first that the piece be there exactly once. It used to
  answer a missing anchor by leaving: the one mutation whose anchor had gone
  took the run with it, the aggregate had no line left to read, reported "no
  verdict reported", and nobody could tell from that phrase whether the
  battery had proved nothing or almost everything. It happened the day the
  compiler finder's body moved up one level of indentation -- a correct
  refactor, with the battery reading as though the tree had failed a hundred
  and one assertions. A gate that cannot distinguish "this regressed" from "I
  stopped looking" is not a gate, so a missing anchor is now its own outcome:
  named on the console, counted apart from a mutation a gate genuinely failed
  to catch, and never again allowed to end the run early.


- **The gate crashed on the machine that mattered, and passed on the one that
  lied.** Its include list is the one the Objective-C gate uses, and that
  list ends with the headers xcodebuild generates -- the CoreData classes and
  the Swift interface the bridge imports -- which live wherever the build was
  told to go. On the machine this round was written on, eight old build
  directories sat inside the checkout, so the headers were found and the
  check looked clean. On a runner the derived data is outside the checkout,
  the lookup answered with nothing, and the script pasted that nothing into
  the compiler's argument list: `TypeError: can only concatenate list (not
  "NoneType") to list`, one step red, and two build jobs green beside it. A
  gate that dies when its environment is thin is worse than one that refuses,
  because the log says nothing about the tree: the answer is now the same
  shape the Objective-C gate gives -- name the missing precondition, say that
  it will not guess, and let the aggregate treat it as a skip -- and the run
  takes `--derived`, the same path the compile step is given. The wiring rule
  was tightened in the same breath to require that flag, because the honest
  skip is also the shape a Swift check would take forever if somebody dropped
  the flag and the log stayed polite.

### Added

- **The Swift half of the app now has the check the Objective-C half has
  had.** A type error in Swift reached three failing jobs before anything in
  this repository could see it: asking an `NSResponder` which window it
  belonged to parses, reads as a sensible sentence, and names a member that
  only a view, or the window itself, has. The aggregate compiles every
  Objective-C source against every SDK the host offers, and nothing compiled
  -- or type-checked -- a Swift file. `scripts/swift-typecheck.py` closes
  that: the project's own bridging header, the same vendored include paths
  compile-audit uses, the compiler and SDK taken as one matched pair from the
  one module every harness already asks, and one `swiftc -typecheck` per
  installable SDK over all thirty-two files. On the host that has no Xcode
  licence accepted -- the one this round was written on -- it takes nine
  seconds and says which SDK it read. It was run against the mistake that
  caused the round: the gate refuses it.

- **A compiler complaint is not one thing but three, and the gate is built on
  telling them apart.** A missing macro plugin means this host cannot read
  the file. Every other error means the tree is wrong. Between them sits the
  case that makes the difference worth coding: a macro that never expanded
  breaks the code around it, because a `@State` that did not become a
  property wrapper is not assignable, so the SDK with no plugin also reports
  three "isn't mutable" errors in that same file. Treating those as defects
  would turn every licence-less machine red for a reason no source caused;
  skipping a run the moment any plugin goes missing would let a real defect
  travel inside the noise, which is exactly the hole this gate was written to
  close. So the gap is recorded per file, and an error is only forgiven in a
  file where the compiler had already said it could not see the macro. All
  four readings are exercised, including the one that matters most -- a
  genuine error in another file is not forgiven because a plugin went missing
  here -- and the pipeline has to name the check twice, once for the gate's
  own proof and once for the tree, or the aggregate says so.

- **A check that reads nothing must say so, and a check that reads something
  must not hide behind what it could not read.** The first version of the
  wiring treated any output containing the word "skipped" as a host without
  an answer, which is what the disk image and compile gates do. On a machine
  where one SDK checks clean and another loses a plugin, that erased the
  clean verdict and left the local answer meaning less than CI's -- the
  precise imbalance this repository added its wiring rules to prevent. The
  aggregate now skips only on the sentence the gate prints when it read
  nothing at all: no compiler, or no SDK whose macros it can see.

### Audited, and not changed

- **A borrowed first responder elsewhere is not the same fault.** The
  settings page hands the keyboard back now, so the same question was asked
  of every other site that moves the focus: sixteen call sites in the
  Objective-C sources, counted rather than remembered. Fifteen of them name
  the responder that is to receive the focus -- a controller, a collection
  view, an alert, a search field -- and the one that passes `nil` is not
  leaving the choice to AppKit either: it clears the focus immediately before
  a view-controller transition whose completion handler names the receiver on
  the next line. Nothing was found on the other side of any of them -- no key
  that lands where the user did not aim it, no control that answers after the
  thing that owned it closed. Left alone, because two sites reading alike is
  not evidence, and this repository has already paid for changing code on
  that basis.

The battery stays at 104 mutations, workflow rules stay at 25, the
behavioural harnesses stay at twelve, and the settings-page constraints stay
at twenty. The Swift type check is a gate of its own: ten readings proved in
its self test, and two invocations the pipeline has to keep naming. The
battery now names an anchor it can no longer plant, rather than losing the
verdict for every mutation that would have followed it.

### Round 47: the page took the keyboard and never gave it back

### Fixed

- **The settings page took the key focus and never gave it back.** The page
  borrows the window it is opened in. It saves the title, it saves whether
  the toolbar is visible, and it puts both back when it closes, because a
  page that reopens the title blank is a visible bug. It did not save one
  thing: showing the page calls `makeFirstResponder` on the page's own view,
  so the page takes the keyboard, and closing the page never says who should
  have it instead. AppKit chooses the successor itself, and the successor is
  where the keys go. The page's key gate is deliberately open-handed -- a key
  the page does not use is handed back to AppKit -- so every unconsumed key
  landed on whichever responder AppKit had picked. When that responder is the
  window, Space and Return belong to the default button and the arrow keys
  drive the key view loop, which is what a user reported as the space bar
  having stopped working after the settings page had been opened and closed.
  A borrowed thing that is thrown away instead of returned is the same fault
  as the blank title, made by the same class, on the third of its three
  loans.

- **The fix is ordered, and the order is the meaning.** The save has to
  happen before the page asks for focus, and the restore before the page
  leaves the view tree; either one late leaves nothing to restore. Four
  constraints say that in the audit rather than describing it: the save must
  appear before the call that takes focus, and the close must name both the
  restored responder and the fallback for when that responder no longer
  belongs to the window -- a responder whose window changed while the page
  was up is not somebody to hand the keyboard back to, and the content view
  is. Both directions were exercised: the rules pass on the fixed file, and a
  file that saves after taking focus, or closes without restoring, fails
  exactly the rule that covers it.

- **The first version of that fix was refused, and not by a reviewer.** It
  asked the saved responder which window it belonged to. `NSResponder` has no
  `window` member -- only a view, or the window itself, can answer that -- so
  the line was wrong on the day it was written. The syntax parse accepted it,
  because parsing never resolves a member lookup, and the audit accepted it,
  because the audit reads shape rather than types. Three jobs then refused it
  on the same line: the two slice builds, the analyzer, and the Debug build
  of the probe that the embedded-render check compiles. The ownership test
  now asks a view for its window and compares the responder against the
  window itself, both by identity, and each shape was checked on its own
  before the file was touched: a small file that repeats the wrong lookup
  reproduces the refusal, and the file that repeats the two-shape test
  type-checks clean.

- **A host without `xcodebuild` can still type-check Swift.** That refusal
  took twelve minutes to arrive, which is the price of believing the local
  toolchain is blind to Swift types. It is not: the Command Line Tools
  compiler runs without the licence gate that stops `xcodebuild` and `xcrun`,
  and against the Command Line Tools' own SDKs it will type-check all
  thirty-two Swift files of this project -- the bridging header and the
  vendored include paths included -- in about a minute on the 26.5 SDK, which
  is the SDK the build jobs use. Two things keep it from being a gate today.
  The `#Preview` macro at the end of one file and the `@State` macros on the
  27 SDK both need a macro plugin that ships with Xcode and not with the
  Command Line Tools, so those regions have to come out of the copy that gets
  checked, and a check that silently drops code is worse than no check. And
  the check is not wired into anything yet. What this round established is
  only that it runs, and what it says about this tree: clean on the SDK CI
  builds with.

### Audited, and not changed

- **The glass does not need a transparency-off branch.** The audit looked for
  places that draw the liquid-glass surfaces without respecting Reduce
  Transparency or Increase Contrast. There is nothing to respect: the
  surfaces use the system `NSGlassEffectView`, and the system owns what that
  view looks like when those settings are on. Grepping the three glass files
  for hard-coded colors to compensate returned no hits -- they draw with
  semantic colors. A hand-written degradation path here would have been a
  second opinion about the appearance, which is the class of bug this
  repository keeps paying for.

- **`glassIsInteractive` reports what was asked for, not what happened.** The
  setter takes a request and the getter returns the request, which reads like
  a property that lies. The header says the flag is ignored off the glass
  path and on systems with no interactive glass, and the true answer is
  carried separately by `usesSystemGlass`. Nothing in the tree reads the
  request back -- one call site writes it and none reads it -- so there is no
  caller being misled today, and the property that matters already tells the
  truth.

- **A corner-radius branch that cannot run.** `-setCornerRadius:` has a
  vibrancy path that sets the radius without clipping `masksToBounds`, which
  would be a wrong-looking corner on any system that took it. The deployment
  target is 26.0 and that path is guarded by `@available(macOS 26.0, *)`, so
  on every system this build runs on the guard is true and the other branch
  is the one that executes. Dead code with no user-visible consequence, left
  alone rather than "fixed" without evidence.

The battery stays at 104 mutations, workflow rules stay at 25, the
behavioural harnesses stay at twelve, and the settings-page constraints go
from sixteen to twenty.

### Round 46: an interrupted audit could leave its own defect in the tree

### Fixed

- **An interrupted audit could leave its own defect in the tree.** The
  battery writes each mutation into the real source file, asks the gate
  whether it noticed, and puts the original back in a `finally`. A `finally`
  answers an exception raised inside the gate. It does not answer a signal:
  the first Ctrl+C can land in the restore, and the second can land a few
  instructions later, inside the write that was putting the file back. One
  interrupted audit here did precisely that, and the tree came back holding
  the mutation -- keyboard bookkeeping moved to the wrong side of a dispatch
  -- so the next run reported four broken keyboard scenarios and a
  release-path rule that could find nothing, which is how a defect that never
  existed nearly got fixed. CI cannot see this shape at all, because every CI
  run starts from a fresh checkout; only a person who interrupts a run by
  hand meets it, and they meet it as a regression.

  Every dirty file is tracked now, and the restore is interrupt-proof rather
  than merely exception-proof: the three terminal signals put the tree back
  with the signal mask held, and only then does the process end the way it
  was asked to, with `atexit` and an outer `finally` covering the paths that
  never reach a handler. Restoring before responding is the order that
  matters -- deferring the interrupt until the gate finished would have been
  safe and useless, since a gate here can be the whole audit. Interrupting a
  battery that is holding a planted mutation now returns a clean tree in
  under a tenth of a second, measured against both SIGINT and SIGTERM on the
  mutation that touches the keyboard state machine, and a full uninterrupted
  run still catches 104 of 104.

### Added

- **A popover says none of the four words the old ban knew.** The request was
  that the settings pages share the interface they are opened from instead of
  arriving in a window of their own. The page is an overlay attached to the
  host window, and the audit said so: it refused `NSWindow(`, `NSPanel(`,
  `NSWindowController(` and `initWithContentRect` in the presenter, the view
  and the bridge. Every one of those tokens names a window somebody builds by
  hand. An implementation that hands the page to `NSPopover` builds no window
  at all, passes all three checks, and still puts the page into a window
  AppKit builds for it -- which is the same visible result the request was
  about, reached by a route no gate was watching. Sheets and modal presents
  are the same shape.

  The ban now names the mechanisms that move the page somewhere else:
  popovers, sheets, modal presents, modal windows, `runModal`, SwiftUI's
  `openWindow`, `.sheet`, `.popover` and `fullScreenCover`, across the
  presenter, the view and the bridge. It deliberately does not name
  `makeKeyAndOrderFront`, which the presenter already calls, because
  reopening the same page raises the window that already holds it rather than
  moving the page into another one. The attachment is pinned from the other
  side as well: the page goes into `window.contentView`, not into the view of
  something presented over that window.

  Both directions are proven, and the second one is unusual enough to say
  outright. A settings page handed to a popover must be refused -- it is, by
  name and by file. Under that same mutation the older window-construction
  ban still reports nothing, and that fact is now an assertion of its own, so
  the day the first ban grows the shape the second one covers, the audit says
  so rather than letting two rules quietly agree on the same blind spot.

### Audited, and not changed

- **A held movement key is released on every path that stops forwarding.**
  The asymmetry looked wrong: `-releaseAllModifierKeys` is called from
  sixteen places and `-releaseAllHeldKeys` from two. The question that
  decides it is which state stops `keyUp:` from forwarding, and that is one
  property, `shouldSendInputEvents`, written in exactly three places. The
  uncapture path calls `-releaseAllHeldKeys` on the line before it.
  `-beginStopStreamIfNeeded` writes the flag and clears the input context,
  and the session teardown that follows releases held keys as its step zero,
  before it disables anything -- and `-performCloseStreamWindow` runs that
  teardown first, deliberately, so the context is still valid when the
  packets go. The third write is inside that teardown, after the release. No
  path stops the forwarding and leaves the record behind, so the counts stay
  as they are: modifiers are released more often because a modifier has to be
  returned on more occasions, not because ordinary keys were forgotten.

- **Two front doors, one room.** `-AppDelegateForAppKit` reaches the page
  twice through `SettingsOverlayPresenter` and once through the Objective-C
  bridge, which reads like the two-implementations fault this repository has
  been bitten by before. It is not: the bridge's three methods each forward
  one call and add nothing, and an existing rule already refuses a second
  presentation site and refuses a bridge that stops forwarding. Nothing to
  change, and the shape is already gated.

- **Auto-repeat is forwarded as presses.** `keyDown:` does not test
  `isARepeat`, so a held key sends the host a stream of DOWN edges. That is
  the upstream behaviour, some games read the repeats rather than the state,
  and no wrong outcome was found on the other side of it -- the held-key
  record is a set, so the repeats cannot duplicate what a release has to
  undo. Left alone.

The battery stays at 104 mutations, workflow rules stay at 25, the
behavioural harnesses stay at twelve, and the settings-page constraints go
from ten to sixteen.

### Round 45: a refusal was forgotten, so the hardware was asked again

### Fixed

- **The interpolation question was asked again on every frame.** The renderer
  asks for an interpolation processor as each decoded frame arrives. On a Mac
  with no interpolation engine the answer never changes: the configuration
  offers zero slots, and the probe-size question the settings matrix asks
  says the same. Nothing recorded that answer, so the next frame asked again,
  at frame rate. A refusal cost one or two
  `VTLowLatencyFrameInterpolationConfiguration` constructions -- a capability
  query into the video engine, not a struct fill -- a hop onto the warmup
  queue, and a verdict to classify, sixty times a second, for the whole
  session, on every machine without the engine. The M2 the slots were
  measured on is one of those machines.

  The refusal had a second cost. The runtime reason is chosen by whether a
  warmup is in flight, and with the request restarting every frame that flag
  alternated, so the reason alternated with it. The settings page status only
  de-duplicates when the summary and detail pair is unchanged, so a machine
  that cannot interpolate delivered its refusal as a stream of main-queue
  notifications instead of one line.

  A refusal is now remembered per size, in the same main-queue turn that
  retires the request: a reader that sees the request as finished has to hold
  the answer already, or it asks again. `setupWithVideoFormat:` clears the
  pair, because a new stream, size or setting re-opens the question -- a
  stream above the ceiling and a machine with no engine are different
  answers, and only the second one is permanent.
  `teardownFrameInterpolationProcessor` deliberately does not clear it,
  because the runtime failure path calls it on every failing frame, and
  forgetting the answer there would put the per-frame probe straight back.
  That asymmetry is the shape an assertion now holds.

  Stated plainly, because it is the boundary of this change: it decides what
  happens after a refusal, not whether the machine can interpolate. On a Mac
  that has the engine the processor exists and the first branch of the
  prepare call already returned, so nothing moves there. Whether a session on
  an M1 or M2 feels different is a measurement on hardware, and sixty
  capability queries a second that never reached the screen is not a claim
  about frame delivery.

### The gate that type-checks the sources had never read the streaming sources

- **41 of 41, and this file was not one of them.** `compile-audit.py` exists
  because a build once reached a runner carrying a mistake every local gate
  had called clean, and it does the right thing: `-fsyntax-only` against real
  SDKs and the generated Swift interface, so a translation unit is answered
  by a compiler rather than by a grep. Its file list was `Limelight/macOS`.
  `Limelight/Stream` -- the connection, the stream manager, and
  `VideoDecoderRenderer.m`, the file this round edited -- was compiled by no
  local gate at all.

  Both directions were checked before any of it was believed. An undeclared
  identifier planted in the renderer was met with 41/41 passing and no
  comment. After the list was widened and the macOS slices of the vendored
  frameworks were added to the search path, the same edit is refused on both
  SDKs and 46 of 46 files pass. Only the macOS slices went on the path: the
  iOS and tvOS FFmpeg were configured for another platform, and a type-check
  against them answers a question this build never asks.

  A checkout that never ran `scripts/download-frameworks.sh` genuinely cannot
  answer for those two files, so a header that is absent is reported as
  skipped and dropped from the denominator rather than called a failure --
  the same judgement this script already makes for a missing toolchain and
  for SDKs below the deployment target. What separates it from silence is
  that it names the files it did not read.

- **What this host could not do.** `xcodebuild` is refused here: the Xcode
  license has not been agreed, and agreeing to it is not this round's
  decision to make. That is why the widened gate is worth having rather than
  merely convenient -- it is the first thing on this machine that can say
  anything at all about `VideoDecoderRenderer.m`. It type-checks; it does not
  link, and the pipeline still builds the app for real.

The battery stays at 104 mutations, workflow rules stay at 25, and the
behavioural harnesses stay at twelve.
### Round 44: a released shift stayed held, and every key after it carried it

- **The walk would not slow down, and the jump arrived as something else.** The
  report was still W and Space, the two most basic inputs in a game, and this
  is the layer underneath the pair that was noticed. AppKit's Shift bit is a
  snapshot of a family: left and right shift share it, and nothing else in
  that half of the field says which one moved. Hold one shift and release the
  other and the family bit stays set -- the first one is still holding it --
  so the record built from that bit says the released key is still down. The
  player let go of sprint; the host kept sprinting. Worse, the stranded bit
  is not inert: every key pressed afterwards carries Shift in its modifier
  byte, which is a Space that arrives as Shift+Space and a W that will not
  stop sprinting. To a player that is indistinguishable from two keys
  colliding.

- The shipped read was `event.modifierFlags & NSEventModifierFlagShift`, which
  is a flag AppKit really does set, so no source-level check could call it
  wrong -- the code reads something true and answers a different question.
  The keyboard-concurrency harness does drive W and Space, and it passes,
  because it empties the modifier sync on purpose: it was built to ask
  whether two ordinary keys stay two keys, and nothing has ever run the
  modifier state machine.

- The per-key answer is already in the same field, in its device-dependent
  half, and the record now reads the moved key's own bit. The family bit
  stays the fallback whenever an event supplies none of the per-key bits, so
  a source that only ever reports a family bit keeps behaving exactly as it
  did.

- **A harness that had never run this machine.**
  `scripts/held-modifier-keyboard-pair-tests.py` lifts the shipping state
  machine -- the physical mask, the desired remote mask, the sync that diffs
  them, the flags-changed entry, and the ordinary keyDown:/keyUp: a game key
  travels through -- together with the resolver's mapping table and the
  modifier byte values, so the probe cannot disagree with the build about
  which bit is left shift. The host sender records the byte beside the key
  code, because half the failures here are in that byte and not in the key.
  Scenarios are hand shapes: sprint-walk-jump released in order, sprint let
  go mid-stride, the two shifts as the two keys the host must see them as,
  and a walk key under the right shift alone.

- Two mistakes in the harness itself are worth recording, because both would
  have hidden the defect. Its first version replayed every scenario on the
  same controller, so a modifier stranded by one shape poisoned the next and
  no failure could be attributed; that is exactly how the bug feels to a
  player, but it is not how a test must read. And its first events carried
  only the family bit, which is the one shape under which the old code is
  correct -- a harness that models an incomplete event finds an incomplete
  truth.

- Three regressions are planted on every battery pass (101 to 104): the
  family-bit read restored, the two shift rows of the table swapped, and the
  workflow step removed while the aggregate still runs the harness. All three
  are caught. Two known-bad shapes are rebuilt inside the harness itself --
  answering a modifier change only for the bits that went down, and answering
  a key with the modifier byte of the event before it.

- What is still on the player's side, stated plainly: these per-key bits are a
  field Apple documents as device-dependent rather than as a promise, and the
  fallback exists precisely because a source could stop filling them.
  Alternating the two shift keys while moving and jumping is the one thing
  here that only a real keyboard can confirm.


### Round 43: a token reached a working session, and no gate could see it

- **A personal access token reached a working session.** It never reached a
  commit -- a walk over every blob of every reachable object returned nothing
  -- and the reason that answer had to be asked by hand is the defect this
  round closes. Every audit in the pipeline asks what the source *does*. None
  of them asks what a file happens to *contain*, so a credential written into
  a helper, a debug script, or a workflow step would have been built, tested,
  artefacted, and pushed without a word of comment. A push is the unforgiving
  half: the value is then in the object store, in every fork made afterwards,
  and in any log that echoes the file, and a revert removes it from none of
  those. The only cheap moment to refuse is the commit that adds it.

- `scripts/credential-scan-audit.py` refuses that commit. Eight shape rules
  (the fine-grained and classic GitHub token families, cloud keys,
  private-key blocks, and a deliberately narrow quoted-assignment form) run
  over every tracked file, with `--history` covering the object store as
  well. It reports a rule name and a redacted fragment, because a gate that
  prints what it found is a second copy of the secret -- and this copy would
  be written into the log of every future run. A byte-level prescreen keeps a
  whole-history pass down to twenty-four seconds, and the self test proves
  the prescreen is a superset of the rules: a value that a rule would catch
  but the prescreen skips is the one mistake a security gate is not allowed
  to make quietly.

- **A scan that could not be trusted to finish.** The first version fed five
  thousand object names to `git cat-file --batch` through a pipe while its
  stdout was unread, which deadlocks the writer against git. The second
  emitted history findings with three fields into a printer expecting four,
  and the `--history` pass that looked green before it was fixed meant only
  that nothing had been found: a clean tree and a dead scan are the same
  colour. The tree scan, the self test, and the report path are separate
  assertions now, and the scan stops itself on a clock rather than holding a
  job open until a runner reaps it an hour later.

- **The blind spot behind it was worse.** Deleting a step from the workflow
  used to be invisible. The reachability rule walks from the scripts a step
  names through every script they invoke, and the aggregate invokes nearly
  all of them -- so a gate whose step had been deleted stayed reachable
  through the aggregate that still called it, while CI stopped running it on
  the commits it exists to protect. Reachability that bottoms out at the
  aggregate is only honest while the driver is itself named by a step, so the
  pipeline now has to run every gate in `scripts/` apart from the six that
  need a Mac toolchain and the three that name the gate driving them: the
  assertion battery and the shortcut-menu harness behind the aggregate, and
  the release preparer behind the release gate.

- Four regressions are planted against this on every battery pass (97 to 101):
  a rule whose literal no longer matches the credential it is named for; a
  prescreen that drops a family before any rule can see it; a report that
  quotes the whole value; and the trimmed workflow that stops running the
  scan while the aggregate still does. All four are caught.

- Two things this gate does not do, stated rather than implied. It cannot
  revoke the token that was already exposed, which only its owner can do. And
  a runner checkout is shallow, so the whole-history pass belongs to the
  local aggregate and not to the CI step -- the step claims the tree and
  nothing more.


### Round 42: a translation rule took the key and left the release behind

- **The rule helper consumed a key without saying so.** The pairing rule is
  old and clearly written down: AppKit asks the key-equivalent question on
  `keyDown` only, so any branch that consumes a key has to record the debt, or
  `-keyUp:` forwards a release for a key the host never saw pressed. The
  gate's own branches were paired when that rule was written down;
  `handleKeyboardTranslationRuleForEvent:`, the helper the gate calls for the
  player's own translation rules, had two consuming exits and neither recorded
  anything -- the branch that dispatches a synthetic remote shortcut, and the
  branch that runs a local action.
- **What that looked like on the host.** A rule fires, the host gets the
  shortcut it was asked for, and a moment later it gets the release of
  whatever the player actually tapped -- a key it never saw go down. In a game
  that is an action letting go on its own, which is one of the shapes players
  file as a key conflict. The `isARepeat` exit of the same helper already
  recorded its debt, so this is one rule and three exits, two of them obeying
  it by accident.
- **Why no gate saw it.** The audit rule that counts unpaired swallows slices
  the file from `- (BOOL)onKeyboardEquivalent:` onward, and the helper sits
  above that line, so the two bare `return YES;` answers were outside every
  check that existed. The rule now also reads the helper's own body: no bare
  `return YES;` in it, both consuming exits record the debt, and the answer of
  `performKeyboardTranslationLocalAction:` -- which says whether an action
  ran, not who owns the key -- is turned into a recorded consumption at its
  one call site.
- **Two plantings, both red before this landed.** `translation-rule-consumes-
  a-key-silently` puts the bare `return YES;` back on the shortcut branch, and
  `local-action-answer-becomes-key-ownership` hands the action's answer
  straight back through the gate. The battery went from 95 assertions to 97.

### Round 41: a gamepad kept clicking on a host whose pointer it no longer owned

- **The fourth flush was missing, and the first three prove it.**
  `uncaptureMouseWithCode: reason:` already returns three things before it
  sets `shouldSendInputEvents` to `NO`: the keys being held, the modifiers the
  host was told about, and the HID buttons. Everything that can move or click
  the host's pointer has to be settled there, because the moment the flag goes
  down the paths that pressed them can no longer release them. A gamepad in
  mouse mode clicks those same buttons with A and B through
  `valueChangedHandler`, and nothing asked it whether input was still being
  forwarded. Hand the pointer back to the Mac, keep playing on the desktop,
  and every gamepad click went on landing on the host machine. The same was
  true of a GCMouse device's buttons, movement and wheel, which sit in the iOS
  branch of the shared source.
- **Half a gate is a ghost waiting to be paid.** Refusing the packet is the
  obvious half. The tracker next to it records the edge the packet was built
  from, and if that edge is recorded while the packet is refused, the first
  thing sent after recapture is a release for a button the host never took on.
  So the gate covers the recorded edge as well: while the Mac owns the pointer
  the gamepad leaves no trace on either side of the link.
- **Then the button still has to come up.** A gate alone would strand a button
  the player was holding when the pointer went back: its release has to pass
  the same gate, so it never arrives and the host drags forever.
  `releaseRemoteMouseButtonsForUncapture` runs at the commit point before the
  flag goes down -- the fourth flush -- and empties this class's button
  trackers as it sends, so the host and the trackers both land on nothing
  down. The cost is stated plainly: a button held straight through the hand-
  back has to be pressed again after recapture, which is a click the player
  can see the reason for, rather than one neither side can explain.
- **The probe reads all three facts.** `scripts/controller-mouse-emulation-
  tests.py` bakes the click path's shape in from the source alongside the
  stick timer's: that the click path asks, that its gate covers the edge, that
  the uncapture return happens while the packet can still reach the host --
  found is not enough, it has to happen before the flag goes down. Four
  verdicts run against the model, and `--self-test` now requires six shapes to
  be red, one of them the half gate described above.
- **Where the shared source bit.** Checking the change with `-fsyntax-only`
  found the button table defined inside `#if TARGET_OS_IPHONE`, because every
  line of `registerMouseCallbacks:` is iOS-only and the new macOS flush needed
  the same table. It sits above the platform conditionals now, which is where
  a shared invariant belongs. The GCMouse gate is unreachable in this
  product's binary and stays for the shared source that also builds iOS.
- **Three plantings, all confirmed red.** `mouse-mode-clicks-ignore-the-
  forwarding-gate` is the shipped shape, `click-gate-keeps-the-edge-it-
  refused` is the half gate, and `uncapture-keeps-a-gamepad-button-down`
  removes the fourth flush. The battery went from 92 assertions to 95, all
  judged by the harness that is already a step in both macOS build jobs.

### Round 40: the stick cursor moved a pointer it had handed back

- **One decision, three consumers, and one of them deaf.** Whether motion may
  reach the host right now is one flag, `shouldSendInputEvents`. The button
  path in `ControllerSupport.m` asks it before it sends, and the display-link
  consumer in `HIDSupport+Pointer.m` asks it before it applies accumulated
  motion. The right-stick cursor in `mouseTimerCallback:` asked nothing at
  all. Its timer is made when the pointer is captured and invalidated only in
  `cleanup`, so handing the pointer back to the Mac switched the sends it
  shares a flag with off and left this one reading the stick. A right stick
  resting past its deadzone shipped a packet every sixteen milliseconds to a
  machine whose cursor the player had just stopped controlling -- their own
  mouse moving on the Mac, the remote cursor dragged by the gamepad at the
  same time.
- **Where the ask sits is the fix, not merely the ask.** Asking before the
  send would also stop the packets and would owe the host everything it
  refused: the same method adds a fraction of a pixel a frame to
  `_accumulatedMouseX` and spends it on the next frame, so a gate behind the
  accumulation lets an entire uncapture pile up and recapture throws the
  cursor once. Asking before the deadzone drops refused motion instead, which
  is the choice the display-link consumer already makes for the same reason.
  `MouseEmulation.h` stays the single source for the deadzone and the rate,
  and the gate introduces no number of its own.
- **The probe reads the shape rather than being told it.**
  `scripts/controller-mouse-emulation-tests.py` now reads the method body --
  where it sends, where it asks, where it accumulates, whether it zeroes --
  and bakes those facts into a C model of one timer tick, so the model repeats
  what the shipping source does instead of what this file would like it to do.
  Two verdicts run against it: sixty ticks with forwarding off send nothing,
  and the first tick after recapture answers the current frame rather than the
  whole uncapture. `--self-test` builds three shapes and requires each to be
  red -- the sub-pixel residue thrown away, no gate at all, and a gate sitting
  behind the accumulation -- so the green cannot be bought by deleting the
  ask.
- **Two plantings, one of them already in the tree.** The battery carries
  `stick-cursor-drags-a-pointer-it-no-longer-owns`, which takes the gate out
  because that is the shape that shipped, and `stick-timer-owes-the-whole-
  uncapture`, which leaves the gate in place and moves it behind the
  accumulation. Both judge the same harness the build jobs run, and both were
  confirmed red before this landed: the battery went from 90 assertions to 92.
- **Where it is enforced.** The harness was already a step in both macOS build
  jobs, so it runs twice per push against the tree it compiles, and the ubuntu
  audit job keeps it on the CI-only list because its probe needs a clang and
  SDK pair that image does not have.

### Round 39: capture release handed the pointer back and kept the modifiers

- **A third flush was missing.** `uncaptureMouseWithCode: reason:` says why it
  flushes: input forwarding is about to switch off, `keyUp:` stops
  forwarding once it has, and a movement key held while the mouse is
  released would never reach the host as a release. So it releases the held
  keys and the pressed mouse buttons, and only then sets
  `shouldSendInputEvents` to `NO`. The modifier tracker sits in that same
  position and was not flushed. From that moment `flagsChanged:` stops
  reaching the sync, so a modifier the host had been told about and the
  player let go of on the Mac desktop stayed down on the host until some
  later keyboard event happened to correct it, and every pointer click in
  between carried a modifier nobody was holding.

- **The rule already covered this, and one commit point missed it.** The
  translation gate keeps the list of local actions where releasing is
  correct, and handing the pointer back is on it. The built-in uncaptures --
  the pointer leaving the view, a mouse-mode change made from the embedded
  settings page, a fullscreen exit edge -- reach that same commit point by
  another road and released nothing.

- **The release must not take the hold with it.** `-releaseAllModifierKeys` is
  the obvious call and it is the wrong one here: it zeroes the physical
  tracker in the same breath, which is right at teardown and wrong for an
  uncapture. A player who hands the pointer back with a finger still on
  Shift comes back to find the first gameplay key forwarded with a modifier
  byte of zero -- the sprint they never stopped became a walk, at a site
  that runs once per uncapture and so never showed up in a held-key test.

- **What ships.** `releaseRemoteModifierKeysForUncapture` delegates to
  `-releaseAllModifierKeys`, so the eight packets, the reentry guard and the
  send-before-record order stay in one place, then puts the physical tracker
  back. The remote record is what the host was told and goes to zero; the
  physical record is what the fingers are doing and stays. After recapture
  the sync finds an empty remote mask against a desired mask that is not
  empty and re-presses a modifier that is genuinely held, before the key
  that needs it goes out. `HIDSupport.h` states the difference, because no
  caller can infer it.

- **Both halves pinned, and the wiring too.** The behavioural harness covers
  the uncapture edge in both directions -- the modifier the player let go of
  stays released, the one the finger never left is re-pressed before the
  next key -- and refuses a build that clears the physical hold as well. The
  call itself is a constraint now, written in the shape of the one that
  already makes capture release let go of held keys before forwarding stops,
  and the battery carries a mutation for each half: 88 became 90, one caught
  at the call site and one in the tracker.
### Round 38: a modifier held through the settings page was never learned about

- **One gate, two jobs, the wrong scope.** `-flagsChanged:` returned the moment
  it saw `shouldSendInputEvents` was off. That gate is right about the send and
  wrong about the record: while the embedded settings page owned the keyboard, a
  player pressing Shift left nothing in
  `keyboardPhysicalModifierSourceMask`. Coming back still holding it, the
  desired remote mask is computed from that record, so it says no Shift and the
  host is told to walk where the player is running. The release that follows is
  gated the same way, so the press and its release both vanish without a line in
  the log, which is what makes this one of the reports that reads as a lost key.

- **Recording is not sending.** The record happens first now, and the gate still
  decides what reaches the host. Nothing can be pressed that the host never saw
  go down: `-syncKeyboardModifierStateForEvent:` acts only on the difference
  between what was sent and what is wanted, and while forwarding is off nothing
  is sent, so a modifier that arrived and left behind the door nets to zero.
  `releaseAllModifierKeys` zeroes the physical and remote records together, so
  no path inherits a modifier that was only ever recorded locally.

- **The harness had been restating the method it claimed to cover.**
  `keyboard-shortcut-modifier-tests.py` called the two helpers in the order it
  expected instead of calling `-flagsChanged:`, so it stayed green while the
  shipping method returned early and recorded nothing at all. It extracts and
  calls the shipped method now, gate included, and adds the two shapes a real
  pair of hands produces: a Shift that came down behind the page has to be
  sprinting when the keyboard comes back, and a Shift that both arrived and left
  behind it has to send nothing at all.

- **Teeth in two places.** That file now also refuses a rebuild of the shape
  that shipped, with one gate standing in front of both calls, and the battery
  carries `record-no-modifier-behind-the-door` against the harness that owns
  it.

The battery went from 87 to 88, workflow rules stay at 25, constraints stay at
140, and the behavioural harnesses stay at ten.

### Round 37: the stick moved the cursor at two different speeds

- **Two paths, one feature, two answers.** The right stick drives the
  emulated pointer from two places: the HID consumer in
  `HIDSupport+Pointer.m` and the display-link consumer in
  `ControllerSupport.m`. The second accumulated what it could not ship and
  was already exact. The first normalised the stick, multiplied by 15.0 and
  truncated the product every frame with nothing kept, so held just past the
  deadzone it asked for one and eight tenths pixels a frame and sent one:
  forty-five per cent of a careful player's movement disappeared, and only a
  full deflection kept its promise. The same stick position meant two cursor
  speeds, decided by which device produced the frame.

- **The thresholds disagreed too.** 4000 counts out of 32767 on one side and
  0.1 of full scale on the other, so the paths did not even agree on where
  movement begins. `MouseEmulation.h` owns both numbers and the
  normalisation now, in a header with no project imports, because the two
  consumers sit on opposite sides of the input code and one of them should
  not have to pull in the HID internals to agree on a threshold.

- **Drained rather than truncated.** The stick path hands its frame to the
  draining helper the mouse path already uses, so what a frame cannot ship
  stays with the pointer instead of being thrown away, and a reversal pays
  that residue back instead of being charged for it. The sign the block
  needed was already decided upstream: `updateButtonFlags` inverts raw Z and
  Rz on the way in. The block's six lines of "Invert Y? ... for now", and an
  assignment to `moveY` the next line overwrote, are gone.

- **Judged twice over.** `scripts/controller-mouse-emulation-tests.py`
  compiles the shared normaliser together with the shipping drain and
  asserts that a held deflection arrives at what it asked for, that a full
  deflection arrives at the promised rate, that a shipped total may trail
  but never lead, and that the old truncation loses travel on identical
  input -- which is what gives those verdicts meaning. It also reads the
  block it is testing, because the drain being right in a header proves
  nothing about the call site: `stick-keeps-only-whole-pixels`,
  `stick-rate-drafted-into-a-literal` and `stick-counted-in-raw-units` put
  each of the three regressions back and all three go red.

- **The run for this round went red, and for a good reason.** The analyzer
  job refused the commit because a finding it had been told to accept had
  gone away: the block that lost forty-five per cent of a held stick also
  stored a value it never read, and deleting the line removed the last
  instance of it in the tree. The job treats a finding disappearing as a
  baseline that has stopped describing the code, which is the same refusal
  in the other direction, so the baseline was regenerated from the CI
  transcript rather than adjusted by hand, and the entry is gone for the
  only reason that is allowed.

- **The regeneration destroyed the reasons and said nothing.**
  `analyzer-audit.py --write-baseline` carried its own copy of the
  accepted-reason sentences and wrote that copy over the file, so refreshing
  the baseline after one fixed finding deleted the explanation behind every
  other one and printed a success line while doing it. It keeps what is on
  file now and names the shapes whose reason phrases it could not match;
  `baseline-refresh-forgets-why` puts the overwrite back so the guard is
  judged by the battery rather than by memory.

The battery went from 83 to 87, and the new harness is a step in both macOS
build jobs. Product code moved, so the delivered image has to be rebuilt
from the commit that carries it.

### Round 36: a moment of network ended both macOS builds

- **What the failing run actually said.** The x86_64 job died in dependency
  preparation with `curl: (28) Failed to connect to github.com port 443
  after 9354 ms`, on the commit whose arm64 job passed. Nothing in the diff
  caused it: one connect attempt was the entire retry policy, so a runner
  with a bad route to GitHub cost a build, a red pipeline, and a human
  pushing again.

- **Fixed in the one place a third dependency cannot forget it.** Every
  download goes through `fetch_archive` now, which retries refused and reset
  connections, bounds a connection that never opens, abandons a transfer
  that has stalled, and re-fetches an archive that is not whole.
  `verify_archive` is the other half of the claim: a zip missing its tail
  used to leave a directory tree behind through `unzip -o`, and the layout
  check three steps later blamed the archive for a truncated transfer. The
  self-test builds an archive, truncates it, and refuses both the short file
  and an empty one, so the accept and the reject are both proven.

- **The rule matters more than the flags.**
  `download-gives-up-on-one-connection` takes the retry flags out of the
  helper and the aggregate goes red, because a dependency added next month
  will not know to copy them. CI is the evidence for this round in both
  directions: the previous run is the defect, and the next one is the test.

The battery went from 82 to 83. No product code moved, so the delivered image from round 35 is unchanged until a run goes green end to end.

### Round 35: a three-notch wheel event was answered with one notch

- **The count the driver reports, thrown away.**
  `HIDScrollEventDiscreteDeltaForAxis` reads the notch count out of the
  event's own wheel fields -- raw first, then line, then the AppKit delta --
  and those fields carry more than one whenever AppKit coalesces a fast
  scroll into a single event, a free-spinning wheel reports several detents
  at once, or the driver reports a jump. `HIDNormalizedDiscreteScrollClick`
  rounded that count and clamped it to one notch. This is last round's
  accumulated-consumer loss with nothing to show for it: the quantized and
  fallback branches each answer once per event and keep nothing back, so
  three notches became one and the other two never existed anywhere in the
  process. The floor stays where it belongs -- a real detent that rounds
  below one has to send something, or the wheel looks broken exactly when
  the player is gentlest with it -- and the bound that replaced the clamp is
  the packet.

- **Bounded twice, for two different reasons.** `HIDDiscreteScrollPacketUnits`
  multiplies the notch count by the wheel speed before it clamps. The two
  bounds are not the same number and not the same question: the count is
  bounded by what one packet holds at the default speed, and the units are
  bounded again after a speed multiplier that reaches 4.0 in the settings
  UI. Clamping only the count would still have let three notches at 4x
  overflow the short the wire carries, which does not lose the scroll -- it
  wraps through SHRT_MIN and scrolls the host the other way.

- **A claim from last round that was not true, and the rule that checks it
  now.** Round 34's summary said its harness is a step in both macOS build
  jobs. That sentence went into the commit message and the changelog, and
  the step was never added to `build.yml`. The pipeline audit stayed green
  because the reachability rule counts a gate as wired when another wired
  script runs it, and the assertion battery does name it as a mutation judge
  -- true for a gate, false for a build step. The harness was run by the
  audits job and by nothing else, which is exactly what the round's own
  sentence promised it was not. Both steps are in the workflow now, and
  `constraints-audit.py` reads the changelog's build-step claims back
  against the workflow, folding the eighty-column wraps first -- the first
  version of that rule was itself defeated by a wrap landing inside the
  phrase it searched for, which is the same shape of failure this round
  exists to record.


### Audited, and not changed

- **Zero-size views do not fling the cursor to the corner.**
  `HIDClampFreeMouseCoordinate` answers 0 when a reference size is missing,
  which looked like a full-screen-transition jump to (0,0). It is
  unreachable that way: `updateFreeMouseVirtualCursorAnchorWithViewPoint:`
  and `reconcileFreeMouseVirtualCursorToViewPoint:` both refuse a non-finite
  or non-positive reference size before clamping anything, and the absolute
  path's `HIDAbsoluteMouseReferenceForEvent` refuses a view with no window
  or content view. Recorded as checked so the next reader does not have to
  walk it again.

- **The 25 ms de-duplication still drops whole events, on purpose.**
  `HIDDeduplicatedScrollClick` discards a same-direction wheel event
  arriving inside `HIDQuantizedWheelDuplicateSuppressMinMs`, and it now
  carries a count rather than a single notch, so a dropped event can drop
  several notches. That is the behaviour it was written for -- the
  GameController path receives the same physical wheel twice inside that
  window -- and `deduplicateBurst` is `useGCMouse`, so a plain mouse never
  passes through it. Loosening it would put duplicate scrolls back onto the
  host, and there is no reproducible wrong outcome on the other side of it.

- **A rewrite of this file ate seven rounds, and no gate noticed.** While
  the closing paragraph of this round was being rewritten, the patch's own
  pattern matched to the end of the file, so Round 28 through Round 34 and
  every released-version section went away: 527 lines deleted silently, with
  the aggregate still green. The damage was caught by reading a diffstat,
  not by the pipeline. The `### Round` headings are now checked for a
  gap-free numbering and every `## [` release section for its date, and
  `changelog-loses-a-whole-round` deletes one heading so the shape rule
  answers to the battery as well. Prose about a file is only as safe as a
  check on the shape of the file.

The battery went from 79 to 82 with three entries: one for the defect, one
for the claim last round got wrong, and one for the mistake just described.
`wheel-answers-one-notch-for-several` puts the one-notch clamp back on the
count a wheel event answers with, judged by a harness that
`scripts/discrete-scroll-click-tests.py` compiles and runs, and that harness
is now a step in both macOS build jobs.
`changelog-claims-a-step-the-pipeline-lacks` deletes the step this file
claims for `scripts/relative-pointer-gain-tests.py`, which is a step in both
macOS build jobs and is checked against that claim from now on.
`changelog-loses-a-whole-round` deletes a round heading, so the shape rule
that caught this round's truncation cannot lapse unnoticed either. Product
code moved, so the delivered image has to be rebuilt from the commit that
carries it.

### Round 34: a careful pointer move was answered with a whole pixel

- **A promise that only points one way.** `HIDScaledRelativeDelta` answers
  each display-link frame on its own, and its last branch answers one pixel
  whenever the scaled move is non-zero but under one. Pointer Sensitivity
  goes down to 0.25 -- the settings UI offers it and the shipping clamp
  enforces it -- so moving carefully asks for a tenth of a pixel a frame and
  ships a whole one. The promise is one-directional and nothing ever
  subtracts what it invented: the low half of the slider changed how often
  the promise fired rather than how far the cursor went, and a still hand
  drifted, because jitter of any size bought a pixel in whatever direction
  it happened to point. Measured over twenty frames at the bottom of the
  slider, two pixels of intention shipped twenty.

- **Drained rather than promised.** `HIDDrainRelativeDelta` leaves the sub-
  pixel remainder with the caller and lets the next frame add to it, so over
  any run of frames what ships trails what was asked by under one pixel and
  never leads it. A slow move arrives a frame late, which is what scaling
  means; it does not arrive amplified, and a reversal pays the residue back
  instead of being charged for it. Each consumer keeps its own pair of
  residuals, because the display-link consumer and the HID-queue consumer
  are different threads, and every path that has already decided not to
  dispatch -- the input context vanished, the pointer went absolute, the
  relative path is muted -- drops the debt, since a fraction kept past that
  decision is paid into some later, unrelated movement of the hand.

- **Both halves of the claim are checked.** `scripts/relative-pointer-gain-
  tests.py` runs the extracted shipping functions frame by frame at both
  ends of the real slider range, read out of the expression that clamps it
  rather than restated, asserts the shipped total may trail but not lead,
  that jitter does not move the cursor, that a reversal nets nothing, and
  that an absurd frame clamps to one packet instead of wrapping into the
  opposite direction. It then rewires both shipping paths back to the per-
  frame answer and requires the wiring verdict to go red, and puts the one-
  pixel floor inside the drain and requires six verdicts to go red. The
  shipping per-frame function is still asserted to overshoot on the same
  numbers, so the fixed case cannot quietly become the old one.


### Audited, and not changed

- **The controller stick path truncates, and stays that way for a stated
  reason.** Mouse emulation from the right stick scales by a hard-coded 15.0
  that the comment calls an approximation of the Qt client, applies a
  4000-count dead zone, and then stores `(short)dx`. Past the dead zone that
  is roughly 1.83, truncated to 1, and a push shorter than a pixel ships
  nothing, so the same class of error lives there too. The drain would fix
  the arithmetic. It would also change how the macOS client feels against
  the reference client the constant is trying to match, and the comment
  block above it is still arguing with itself about which way the stick's Y
  axis points. Truncation bias is provable from here; cross-client feel and
  that inversion are not, so the arithmetic stays on the record rather than
  being half-changed next to an unresolved question.


The battery went from 78 to 79 with `pointer-promises-a-pixel`, the new
harness is a step in both macOS build jobs, and product code moved, so the
delivered image has to be rebuilt from the commit that carries it.

### Round 33: a fast flick lost most of its scroll before the host saw it

- **One event was allowed to answer one notch.**
  `HIDConsumeAccumulatedDiscreteScrollClick` in `HIDSupport_Internal.h` is
  the function the notched rewritten-scroll path asks when it wants to know
  how much of the accumulated displacement may leave now. It floored the
  accumulator, clamped the answer to one notch, and subtracted that same one
  -- so an arrival of four notches dispatched one and parked three. Nothing
  else in the file ever empties that accumulator: each sibling branch zeroes
  the other accumulators when that other branch runs, and a gesture that
  ends simply stops calling. Three notches parked after lift-off are three
  notches the host is never told about. Run against the extracted shipping
  function, a four-frame flick asking for 15.5 notches shipped 4.

- **The symptom only shows up at speed, which is why it survived.** A slow
  drag arrives in sub-notch frames, takes the `fabs < 1.0` branch, and
  behaves exactly as intended, so the control reads as fine while the player
  is browsing carefully. The loss appears when they scroll with intent: the
  harder the flick, the larger the fraction that disappears, and the residue
  leaks into the next gesture instead of being paid for the last one. That
  is the whole signature of scrolling that will not keep up and then jerks a
  beat late, and no grep, compile, or unit of the shipping app could see it,
  because the behaviour lives in an inline function no test path calls.

- **Fixed against the neighbour that already gets it right.**
  `HIDDispatchAccumulatedHighResScrollDelta` does the same job one branch
  over: it clamps to what one packet can carry and subtracts exactly what it
  returned, so the residue is always below one unit. The consumer now keeps
  the same bargain -- every whole notch leaves, the fraction stays, which is
  what lets a slow drag add up -- and its return widened to `short` with the
  ceiling derived from the shipped `HIDScrollWheelDelta` rather than
  restated, because the call site multiplies into a short and 274 notches
  would wrap and hand the host the opposite direction.


### Audited, and not changed

- **Trackpad Speed is a calibration, not a units mistake.** The high-
  resolution path scales `scrollingDeltaY` by Trackpad Speed -- default 1.0,
  range 0.1 to 4.0, clamped again in the header -- and sends it on a wire
  whose one tick is 120. That reads at first glance like a twelvefold
  miscalibration. It is not: a tick is on the order of a hundred pixels of
  document movement on the host, while a natural two-finger travel is
  several hundred pixels spread over dozens of accumulating frames, so 1.0
  lands near parity rather than one twelfth, and the physical wheel's 7.0
  scale is the same correction for a device that reports lines instead of
  pixels. Feel is the only thing that could settle the difference, there is
  no way to measure it from here, and a wrong guess would move every working
  scroll. Both values stay, recorded as the open question they are rather
  than quietly "fixed".


The battery went from 77 to 78 with `notch-consumer-hoards-a-notch`, the new
harness is a step in both macOS build jobs, and product code moved, so the
delivered image has to be rebuilt from the commit that carries it.

### Round 32: the preparer reported success while blocking the tag

- **`--apply` cleared a promotion that could not be committed.** The script
  wrote the section the gate asked for and closed with "the gate accepts the
  tag", which is true of the working tree in front of you and misleading
  about the release. The next verb anyone reaches for is `git commit`, and
  BUILD_NUMBER is `git rev-list --count HEAD`, so the commit carrying
  `[1.3.9-build1478]` is precisely what makes HEAD build 1479. Re-asking
  then refuses a tree whose only fault is carrying a section one build back.
  Reproduced in a throwaway clone: prepare, commit, refuse; prepare again,
  commit, refuse again, with the tool reporting success each round. The
  failure shape is not a bad artifact. It is the release stalling at the
  moment of the tag, with someone under pressure hand-editing headings to
  make a tool stop objecting.

- **The report now names the amend and the count that forces it.** The edit
  belongs in the commit that is already HEAD, and `git commit --amend`
  replaces HEAD instead of adding to that count, so the section keeps naming
  the build the binaries carry. The reason travels with the advice because
  advice gets re-litigated at release time, and because the wrong command is
  easy to type: `git commit -qam --amend --no-edit` makes `--amend` the
  commit message and commits normally. That is how the loop was reproduced a
  second time while this fix was being written. The closing sentence no
  longer claims the tag is accepted; it says the tree carries the section,
  tells you to amend, and points at a re-run to confirm.

- **The chase is named while it is still one commit long.** A refusal whose
  changelog already carries the previous build now prints which section sits
  one build back, states that a commit made for the previous refusal moved
  the target, and says to stop committing it forward. The alternative
  reading of that refusal -- prepare again -- is what keeps the loop
  running. The fingerprint is exact rather than a hunch: the gate wants
  build N and the changelog has N-1. A first preparation, and a released
  section seventeen builds back, both stay silent, and both are fixtures,
  because a warning that fires in the ordinary case is a warning that gets
  ignored in the case it exists for. The promotion still writes in that
  state: the section for the current count is the one a tag needs, and
  refusing it would leave a hand edit as the only way out.

- **Ten fixtures, one of them breakable.** The preparer's own self-test went
  from five verdicts to ten: the cleared promotion has to name the amend and
  the count; it may not present acceptance as a verdict; a moved target has
  to be reported as moved; and two check that the hint does not fire where
  it does not belong. Those run inside `release-gate.py --self-test`,
  already wired into the audit job, and the battery gained `promoted-then-
  committed`, which deletes the advice and requires that gate to notice.


### Audited, and not changed

- **The tool cannot police the command you type.** Nothing here intercepts
  `git commit`, and the amend guidance is prose rather than an enforced
  step: this script does not commit, and making it commit would trade a
  misleading sentence for an unrecoverable one. What it can do is stop
  describing an uncommitted working tree as a release, and stop being silent
  the moment the count has moved. The end-to-end check covers both halves:
  after an ordinary commit the warning names the section one build back, and
  after the told amend the count does not move, HEAD itself carries the
  section the tag names, and the script reports nothing left to prepare.


The battery went from 76 to 77, the preparer's fixtures from five to ten, and
this round moved no product code, so the round 31 image is still the one to
install and test.

### Round 31: a hotkey held down fired once per autorepeat

- **Holding a bound key ran its action again and again.** The entry point is
  `-performKeyEquivalent:` in `StreamViewMac.m`, and AppKit keeps sending
  keyDown while a key is held. Whether those deliveries reach the handler
  was assumed rather than known, so it was measured against a live
  `NSWindow`: the key-equivalent chain hands a view an `isARepeat` event
  exactly like the first one. Nothing in `Limelight/macOS` asked the flag --
  `isARepeat` appeared nowhere in the tree -- so every repeat fired the
  action again. Four of the built-in bindings toggle state, so holding one
  flips a panel at the autorepeat rate: the performance overlay strobes, the
  mouse mode alternates under the player, the control ball flickers, the
  control centre is presented again and again. A translation rule fires the
  same way, and one of the actions it can name is in the list that
  legitimately releases the keyboard, so a window-rebuild binding released
  the player's held modifiers over and over while one finger never left the
  key.

- **The repeated delivery is consumed, not ignored.** Ignoring it looks like
  the obvious fix and is a worse bug: the first press was never forwarded,
  so a repeat allowed to fall through reaches `-keyDown:` and hands the host
  a key the player only ever bound to the client -- tap the hotkey and
  nothing happens, hold it and the game starts receiving it. Each affected
  binding now records the suppression where it pays the debt, which is the
  convention the pairing gate in the aggregate already enforces: the first
  version of this fix factored that into one helper, and the gate reported
  it as six unpaired keyDown paths. The gate was right.

### Audited, and not changed

- **The other half of this report was already fixed.** The pass-through block
  records that it used to emit DOWN and UP back to back, which turned every
  key into a tap -- `holding W reached the host as DOWN,UP,DOWN,UP from
  autorepeat ... and a second key could never overlap the first`, the same
  sentence that names the W-and- Space symptom. That shape is gone. What
  this round closes is the second path by which a held key could still reach
  the client's own handlers over and over.

The battery went from 75 to 76, the aggregate prints 148 lines of `ok` with no
failures, and this round changed product code, so the delivered image has to
be rebuilt from the commit that carries it.

### Round 30: three guesses, all three already guarded in the shipped code

Nothing in the product or a gate changed this round. The round went into
trying to find the defect behind "I mapped a Parsec keyboard scheme and W and
Space fight each other", and every candidate turned out to be already guarded
-- worth writing down, because each one cost an audit round to rule out.

### Audited, and not changed

- **A bare key cannot delete a gameplay key, and the code already says so.** A
  shortcut bound to a bare key takes that key away from the game, and every
  consumer does it: the responder gate returns YES, a translation rule
  swallows the press, an `NSMenuItem` key equivalent claims the event before
  the stream view sees it. All four consumers ask
  `shortcutCanMatchKeyboardEvent`, which needs at least one relevant
  modifier -- `event:matchesShortcut:`, the translation-rule matcher,
  `menuKeyEquivalent(for:)`, and through it `applyShortcut:toMenuItem:` --
  and the comment on that predicate names this exact report. The aggregate
  checks each call site and the battery plants three separate removals of
  it.

- **Every glass panel sits on the container.** Eight
  `containerWithCornerRadius:` call sites -- timeout, log, reconnect card,
  performance overlay, connection warning, mouse mode, notification, and the
  control-centre pill -- for the eight overlays, and all eight reach
  `NSGlassEffectView` through the one container class. The shipped binary
  names `NSGlassEffectView`, `MTLFXSpatialScalerDescriptor`,
  `VTLowLatencyFrameInterpolationConfiguration`,
  `VTLowLatencySuperResolutionScalerConfiguration` and
  `VTSuperResolutionScalerConfiguration`.

- **Measured on this machine by the enhancement harness, not by
  `isSupported`.** MetalFX really rescales: the checkerboard comes back with
  3192 interpolated edge pixels. VT reports `isSupported=1` for frame
  interpolation while offering **zero** slots at every probed size, which
  the harness prints as `trust-isSupported would claim interpolation the
  hardware cannot do`; the low-latency scaler offers only 1.5x at 720p, an
  empty factor list at 1080p, and refuses to build a 2x configuration. The
  settings matrix says unavailable where the hardware says unavailable,
  which is the reason to probe sizes instead of asking the class.

Battery still 75/75, still 147 `ok` lines, no failures.

### Round 29: the edge of a key press that no probe had ever looked at

### Audited, and not changed

- **W and Space do not conflict inside this client, and the audit says so with
  packets rather than with reasoning.** The report is precise -- "I mapped a
  Parsec keyboard scheme and now even W and Space, a basic game operation,
  fight each other" -- so every mechanism that could produce it was chased
  down. `HIDDispatchInput` puts every packet on a `DISPATCH_QUEUE_SERIAL`, so
  a release cannot overtake its press; each key owns its own entry in
  `keyboardForwardedKeyDownKeyCodes`, so releasing one cannot disturb another;
  `consumeKeyDownEvent:` records one suppressed key and touches nothing else;
  and the eight releases in the local-shortcut handler all sit inside branches
  that hand the keyboard away (Cmd+1, Cmd+`, Cmd+H, Ctrl+Cmd+F, disconnect,
  disconnect options, quit, reconnect, Cmd+W), which is the test round 28
  wrote down. There is no `LiSendGamepad` anywhere in the target, so the class
  of bug where a button event zeroes the stick cannot happen here either. The
  mechanism that was real is the one already fixed; what this round adds is
  the proof, on the half of the interaction that had none.
- **The release edge had never been probed at all.** The harness extracted
  `-keyDown:` and never `-keyUp:`, which means every "press" in the project
  had packet-level evidence and not one "release" did -- while stuck keys,
  ghost releases, and a release carrying the wrong modifier byte are all
  release-side faults.

### Added

- **`-keyUp:` is now in the probe, with three scenarios for the reported
  gesture.** Running on W and jumping on Space with no modifier in sight: four
  packets, each press answered by its own release, and the held-key record
  empty again. Space belonging to a local binding instead -- which is exactly
  what a Parsec-style scheme does with gameplay keys: neither its press nor
  its release may reach the host, and the held-W record has to still be there
  mid-way, because the entry `-releaseAllHeldKeys` reads at capture end is the
  only thing that stops the host running for the rest of the session. And
  sprinting on Shift while letting go of W first: the release has to carry the
  modifier byte its press carried, or the host is told to lift a key it was
  never handed. Both new failure shapes are built into the harness, so the
  scenarios cannot quietly stop biting.
- **One more aggregate rule, for the same reason as last round's two.** The
  probe needs a compiler and the audit runner has none, so the two lines that
  carry these properties -- the release's modifier byte and the suppressed
  record it consults -- are what the aggregate requires, and the planted
  mutation belongs to it rather than to the compile gate.

The battery went from 74 to 75, the shipped probe's scenarios from 20 to 25,
and the aggregate prints 147 lines of `ok` with no failures. No product file
changed this round -- the audit found the shipping release path correct -- so
the delivered build 1474 is still the current image, and the version bump a
rebuild would cause is not evidence of anything.

### Round 28: two ways the keyboard took a key away, and a gate that can see
### inside a translation unit

### Fixed

- **A keyboard translation rule took away the modifiers the player was
  holding.** `-handleKeyboardTranslationRuleForEvent:` called
  `-releaseAllModifierKeys` before it looked at what the rule does, and a
  Parsec-style rule set fires several times a session. That is the mechanism
  behind "I bound the Parsec keys and now W and Space fight each other": the
  release does not only tell the host that Shift came up, it also zeroes the
  physical tracker in the same breath -- it has to, or the tracker and the
  host diverge -- and `-keyDown:` answers its modifier byte from that
  tracker without ever re-reading the keyboard. Only `-flagsChanged:` does,
  and an edge that already happened will not happen again. So the next
  gameplay key after the rule goes out with a modifier byte of zero: the
  sprint becomes a walk, the crouch stands up, and no log calls it a bug.
  The release now belongs to the actions that actually take the keyboard
  away -- disconnect, disconnect options, quit, reconnect, control centre,
  release-capture, and the window rebuild -- and a rule that keeps the
  stream in the foreground leaves a held key alone.
  `scripts/keyboard-shortcut-modifier-tests.py` compiles the shipped state
  machine and reads the packets: Option held, W then Space, both still carry
  Option;
  and with the old release put back, Space goes out bare and the host stops
  believing in a key the player never let go of. Both directions are
  asserted, and the caller's source is checked so the release cannot creep
  back to the entry point.
- **A bound shortcut could show a hint no keyboard can produce.** The
  settings page names keys for people -- `Space`, `Tab`, `Return`, `Esc`,
  `Page Up`, an arrow glyph -- and `-menuKeyEquivalentFor:` handed those
  names straight to `NSMenuItem.keyEquivalent`. Measured against a live
  `NSMenu`, an item whose key equivalent is `space` matched neither
  Control+Option+S nor Control+Option+Space: a word matches no key at all.
  The row advertised a binding that worked only while the stream view itself
  was receiving keys. One scalar inside ASCII is now the line between a
  character AppKit can compare and a label it cannot, and the answer is read
  out of the compiled `SettingsShortcuts.swift` for every key the page
  offers: 47 letter bindings kept, every word refused, and the shape that
  predates the guard fails with `Space (Space) produced 5 scalar(s)`.

### Added

- **`scripts/compile-audit.py`: the aggregate can see inside a translation
  unit.** Grep cannot read a header the way a compiler does, and twice that
  cost this project a runner round-trip -- a property declared only in a
  newer SDK, and a class used as a property type its own imports could not
  reach. The gate type-checks all 41 macOS sources with the same compiler,
  against **every installed SDK at or above the deployment target**, so the
  mistake the local machine cannot see is not a matter of luck about which
  Mac asked it. On this host that is the 26.5 SDK the CI image builds with
  and the 27 SDK it does not: 41 of 41 both ways in five seconds. Older SDKs
  are named and left alone -- the macOS 11 SDK has no `NSGlassEffectView`
  and no `kCMVideoCodecType_AV1`, and reporting those would only teach
  people that this gate cries. `--self-test` proves both directions on the
  product's own header: a selector that does not exist is refused, one that
  does is accepted. It is wired into the aggregate and into the CI analyze
  job, which points it at the derived data its own scan produced. Reintucing
  the old `effectIsInteractive` mistake is now a planted mutation
  (`naming-an-sdk-the-build-does-not-have`).
- **Two aggregate rules, because a gate that cannot answer must not own a
  mutation.** The first run of this round went red on the Ubuntu audit job, and
  the reason was not the product: the mutation above was assigned to
  `compile-audit.py`, which has no Apple toolchain on that runner. It skipped,
  answered "I cannot tell", and the battery read the skip as a mutation that had
  got through. The Swift menu harness exits for the same reason, so the
  menu-hint mutation was owned by a pass that meant nothing there. Both now
  belong to the aggregate, which can answer on every image: a short list of
  names newer than the build's SDK may only appear inside a string literal,
  reached by a runtime lookup that compiles anywhere and does nothing where the
  answer is absent -- comments and literals are stripped first, or the comment
  explaining the list would fail the file that documents it -- and the menu
  guard has to still be in the source that produces the hint. Each compile gate
  stays wired in for real, as the second look for a name nobody thought to
  list, and proves its own two directions with `--self-test`.

### Audited, and not changed

- **A guess that turned out to be wrong, recorded so nobody spends it
  again.** Multi-character key names looked like they would be taken by
  AppKit's first character, which would have made Control+Option+Space
  silently steal Control+Option+S. A live `NSMenu` says otherwise -- it
  matches neither -- so nothing was "fixed" on the strength of that guess,
  and the real defect is the smaller one above.
- **The key mapping table is healthy.** All 114 rows parsed: no `mac`
  key code appears twice (a repeat would silently lose the earlier row),
  every key on the required list is mapped, and all 81 keys the settings
  page offers resolve -- none of them reaches the `return 0` that drops a
  press and its release together.

The battery went from 71 to 74, the behavioural harnesses from ten to
eleven, the aggregate prints 146 lines of `ok` with no failures, and
workflow rules stay at 25.

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
