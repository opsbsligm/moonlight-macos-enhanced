# Input mapping benchmark: keyboard and mouse

## 1. Why this document exists

The USB design (`docs/usb-redirection-design.md` §2.4) benchmarked competitors only at
the level of *whether* a feature is advertised, and it did that for device redirection.
Nobody had benchmarked the input surface: which modifier maps to which, which system
shortcut stays on the Mac, what a pointer mode actually means. That gap is what this
document closes, because a claim that our keyboard and mouse handling is competitive is
worthless until it is compared against something, and the comparison is what tells us
whether the next sprint belongs to input at all.

The evidence discipline is the one the USB document established, and it is not relaxed
here:

- **Verified in this repository** -- a reader can re-run the command in §6 and see it.
- **Verified upstream** -- a public source file was fetched over HTTP with a 200 and the
  quoted text is in it.
- **Advertised only** -- the vendor's own marketing page says it. This proves intent and
  existence of a feature, never its mechanism. Never design against this tier.
- **Not evidenced** -- the source was unreachable. It is listed so that nobody later
  mistakes an absence of evidence here for a finding.

## 2. Sources

| Tier | Source | What it actually gave |
| --- | --- | --- |
| Verified in this repository | `Limelight/macOS/ViewControllers/SettingsObjCBridge.swift`, `SettingsShortcuts.swift`, `SettingsModel+DerivedValues.swift`, `Limelight/Input/HIDSupport_Internal.h`, `HIDSupport.m`, `HIDSupport+Pointer.m`, `StreamViewController+WindowModes.m`, `StreamViewController+MouseCapture.m`, `Limelight/macOS/{en,zh-Hans}.lproj/Localizable.strings`, `scripts/*-tests.py` | The complete input surface we ship, listed in §3. |
| Verified upstream | `moonlight-stream/moonlight-qt` `app/settings/streamingpreferences.h` (HTTP 200) | The full option list of the upstream Qt client. |
| Verified upstream | `FlorianSLZ/scloud` `Policies/ADMX/Citrix/Receiver-Intune.admx` (HTTP 200); `fwmechanic/shell/citrix_alttab`; real `.ica` files | Two separate Citrix mechanisms, read off the ADMX itself: the hotkey table under `Lockdown\Client Engine\Hot Keys`, and the capture tier under `Lockdown\Virtual Channels\Keyboard`. §5.2. |
| Advertised only | `todesk.com` homepage (HTTP 200) | ToDesk: `Command` to `Ctrl` remap, Alt+Tab relay through a chord, virtual mouse and trackpad mode, mouse acceleration, tablet/3D-mouse/gamepad device mapping. |
| Advertised only | `uuyc.163.com` (HTTP 200) | UU Remote: 300+ touch key-mapping schemes for phones controlling a PC. |
| Not evidenced | `support.parsecgaming.com` (403 through Cloudflare on two paths, archive.org returned nothing), `parsec.dev` (empty), `parsecgaming.com/features/` (no input copy), no public Parsec repository exists | **Parsec is not benchmarked.** Its input model is closed source and its documentation was unreachable at the time of writing. Nothing in §3 or §4 is a claim about Parsec. |

## 3. Our own surface, enumerated

Anything a reader cannot find by running the commands in §6 does not appear in this
table. This is the list the comparison is made against.

| Axis | What ships here | Where |
| --- | --- | --- |
| Modifier translation | One fixed mapping and no user-facing choice of one: Command to Win, Control to Ctrl, Option to Alt, Shift to Shift | `KeyboardMapResolver.m`'s `s_mapTable`, whose own comment reads "This is the ONLY place that defines modifier mapping"; `KeyboardCompatibilityMode` carries the single case `streamingStandard` (`SettingsModel+DerivedValues.swift:179`) |
| Per-shortcut ownership | Unlimited user rules: record a Mac chord, choose output = **Remote Shortcut** (any key from a 97-entry key table with any of Control/Option/Shift/Command/Function) or **Moonlight Action** (10 actions, incl. `releaseMouseCapture`, `disconnectStream`, `openControlCenter`) | `KeyboardTranslationOutputKind`, `KeyboardTranslationRule`, `StreamShortcutProfile.orderedActions` |
| Escape hatch while captured | Ten named actions, plus `performClose` preserving a local shortcut rather than forwarding it | `StreamShortcutProfile.orderedActions`, `handleKeyboardTranslationForCurrentCloseEventAllowingLocalAction:` |
| Local/remote key pairing | `keyboardSuppressedKeyDownKeyCodes` -- a key the host never saw go down must not be seen coming up | `HIDSupport.m` `keyUp:` |
| Unmapped keys | Translation table answers 0, and the press is dropped on both edges rather than shipping a key that does not exist | `HIDSupport.m` `keyDown:` |
| Pointer modes | Absolute, Relative, and Free (`freeMouseMotionMode`, `absoluteMouseMode`, `mouseMode`, plus CoreHID and GameController driver strategies) | `mouseDriver`, `MouseInputDriverStrategy` |
| Pointer scaling | Linear gain 0.25--3.0 with the sub-pixel remainder carried to the next frame (`HIDDrainRelativeDelta`), so a slow move is late rather than overstated | `HIDPointerSensitivityForHost`, `scripts/relative-pointer-gain-tests.py` |
| Pointer rate | Configurable Core HID max report rate | `coreHIDMaxMouseReportRate` |
| Pointer entry | Entering the stream window need not activate the app (switch, default on) | `MLPointerEntryActionsForState`, `scripts/pointer-entry-takeover-tests.py` |
| Wheel | Reverse direction; three independent speeds (physical wheel, rewritten events, trackpad gesture); high-precision scale 1--12; smart tail filter; notch consumption | `reverseScrollDirection`, `HIDWheelScrollSpeedForHost`, `HIDPhysicalWheelHighPrecisionScaleForHost`, `scripts/scroll-notch-consumption-tests.py` |
| Buttons | Swap mouse buttons; discrete scroll-click; gamepad-to-mouse emulation | `swapMouseButtons`, `gamepadMouseMode`, `scripts/discrete-scroll-click-tests.py`, `scripts/controller-mouse-emulation-tests.py` |

17 scripts under `scripts/` gate input behaviour (controller key navigation, controller
mouse emulation, discrete scroll click, gameplay modifier, held key identity, held
modifier keyboard pair, exhaustive key order, keyboard concurrency, keyboard modifier
mapping, keyboard shortcut modifier, Mac key codes, modifier-only release collision,
pointer entry takeover, relative pointer gain, scroll notch consumption, shortcut menu
key, space transition held key).

## 4. The comparison

`---` means the tool has no option on that axis that the evidence shows, not that the
behaviour is bad. `n/e` means not evidenced.

| Axis | This fork | moonlight-qt (verified upstream) | Citrix (verified upstream) | ToDesk (advertised only) | UU Remote (advertised only) | Parsec |
| --- | --- | --- | --- | --- | --- | --- |
| Modifier / layout translation | one fixed mapping (Command to Win) | none | none | yes (Command to Ctrl) | n/e | n/e |
| Per-shortcut custom ownership | unlimited rules, any key x any modifier, output to host chord *or* to a local action | none | a hotkey table: each entry binds a remote action to a chord drawn from `(none)/Alt/Ctrl/Shift` x `(none)/F1-F12/minus/plus/star/tab` -- 4 x 17 | chord relay for Alt+Tab class | 300+ preset schemes (touch to PC) | n/e |
| Capture tier switch | no equivalent (see §5.2) | none | `TransparentKeyPassthrough` = Local / Remote / FullScreenOnly, with the Windows key given its own instance of it | n/e | n/e | n/e |
| Windows-key treated as its own class | no choice to make. Mac Command *is* Win, so the Windows key is always reachable and never separable from Command | none | yes (`Part_Keyboard_Windows_Key`) | n/e | n/e | n/e |
| Secure attention sequence (Ctrl+Alt+Del) | reachable, no dedicated entry (see §5.3) | n/e | its own policy item | n/e | n/e | n/e |
| Pointer modes | absolute, relative, free, plus 2 driver strategies | absolute on/off | n/e | n/e | n/e | n/e |
| Pointer scaling | linear 0.25--3.0, sub-pixel carry | none | n/e | mouse acceleration | n/e | n/e |
| Pointer report rate | configurable | none | n/e | n/e | n/e | n/e |
| Wheel semantics | reverse + 3 speeds + precision scale + tail filter + notch | `reverseScrollDirection` | n/e | n/e | n/e | n/e |
| Button swap / gamepad-as-mouse | both | both | n/e | gamepad mapping | n/e | n/e |
| Tablet / 3D-mouse passthrough | not yet (USB Stage 1 only) | no | n/e | yes -- its Design and 3D tiers sell it | n/e | n/e |
| Touch chord preset library | n/a (macOS client) | n/a | n/a | virtual mouse, trackpad mode | 300+ | n/e |

## 5. What the comparison actually says

### 5.1 We are not behind on keyboard mapping, and the claim is now checkable

Upstream exposes 25 boolean streaming preferences, enumerable with the command in §6:
`absoluteMouseMode absoluteTouchMode autoAdjustBitrate backgroundGamepad
configurationWarnings connectionWarnings detectNetworkBlocking enableHdr enableMdns
enableVsync enableYUV framePacing gameOptimizations gamepadMouse keepAwake multiController
muteOnFocusLoss playAudioOnHost quitAppAfter reverseScrollDirection richPresence
showPerformanceOverlay swapFaceButtons swapMouseButtons unlockBitrate`. Eight of them are
input at all -- `absoluteMouseMode, absoluteTouchMode, gamepadMouse, swapMouseButtons,
backgroundGamepad, reverseScrollDirection, swapFaceButtons, multiController` (`keepAwake`
is power, `muteOnFocusLoss` is audio, which is the honest reading of the list rather than a
generous one). The point is that it is enumerable rather than summarised: not one of the 25
names a key, a modifier, a shortcut, or a capture tier. Everything this fork has
on the keyboard axis -- a 97-key x 5-modifier rule editor, ten named actions, and
suppressed-key pairing -- is work this repository added. The picker that once advertised
`MoonlightClassic` and four other mappings no longer offers a choice: `KeyboardCompatibilityMode`
has one case, and the sentences for the deleted modes were still sitting in both language
tables, which is how this document came to report seven modes it could not point at (§5.5). Citrix's hotkey table
(`Policy_Keyboard_Hotkeys`) is the same shape as our rule editor and strictly narrower
than it. An administrator binds eleven fixed remote actions -- `Alt_Backtab`, `Alt_Tab`,
`Close_Remote_Application`, `Ctrl_Alt`, `Ctrl_Alt_Del`, `Ctrl_Esc`, `Ctrl_Shift_Esc`,
`Tasklist`, `Toggle_LOCALIME`, `Toggle_Latency_Reduction`, `Toggle_Title_Bar` -- each to
one chord built from a modifier enum (`(none)/Alt/Ctrl/Shift`) crossed with a key enum,
where our editor records any chord and offers any of 97 keys against five modifiers. The
eleven ids are listed because that is what the file contains; the human-readable labels in
this ADMX copy are `$(string.unknown_164)` placeholders, so no wording is quoted from it.
ToDesk's headline keyboard feature, Command becoming Ctrl, is **not** something this fork
ships. Its mapping is the opposite preference: Command goes to Win, which is the
Parsec-style choice its own code comment names. A player can still get Command-becomes-Ctrl
today -- the rule editor records `Command+W` and emits `Control+W`, and
`sendSyntheticRemoteShortcut:` sends exactly the modifiers the rule names -- but each
shortcut is one rule the player wrote, not a switch they flipped. That is a discoverability gap and a difference of opinion about defaults, not a missing
mechanism, and it is the one thing on this page where a competitor's default serves a Mac
keyboard better than ours does.

Decision: **the keyboard axis needs no code work.** Not "no work I want to do" -- the
competitor evidence for a gap is empty, and the one place a competitor is ahead is a
touchscreen preset library, which a macOS client has no surface to carry.

### 5.2 The one axis Citrix has and we do not, and why it should stay that way

Citrix's ADMX shows the two mechanisms kept apart, and reading them apart is the whole
point of this section. One is the hotkey table (`Lockdown\Client Engine\Hot Keys`),
which decides *which local chord means what*, and the other is the capture tier
(`Lockdown\Virtual Channels\Keyboard`, value `TransparentKeyPassthrough`), which decides
*who keeps a key at all*, with Local, Remote and FullScreenOnly as its answers and the
Windows key given a separate instance of that same enum. The second axis exists because
Windows shortcuts are contested -- Alt+Tab and Ctrl+Alt+Del belong to whichever session is
in front, so a client must be told who wins.

Reproducing it on macOS buys nothing. Outside full screen macOS will not hand a client
Cmd+Tab or Cmd+Space at all, so `Remote` and `FullScreenOnly` collapse into whatever full
screen already does; and what the `Local` setting exists to guarantee -- that the player can
always get something back -- is already guaranteed here by ten named actions plus a
`performClose` that checks the player's local shortcut before it forwards anything. A
three-state switch whose states cannot differ is a setting that lies.

### 5.3 Ctrl+Alt+Del: reachable, undiscoverable, and not a bug

Citrix gives the secure attention sequence its own policy item because Windows swallows
it before any application can see it. macOS has no such interception, so the ordinary
path works here: the rule editor's key table contains both `Delete` and `Forward Delete`
and accepts Control, Option, Shift, Command and Function as modifiers, which means a
player can bind any chord to Control+Alt+Forward Delete and have it arrive on the host.
That is verified as far as the editor's own constraints go; it has not been driven
end-to-end on a real host from this document.

So the finding is discoverability, not capability, and the fix is a preset in the rule
editor -- not a new mechanism. It stays on the list below rather than becoming code in
this round, because §5.1 holds: nothing on this axis is broken.

### 5.4 The real gap, and it is the one already in flight

ToDesk sells tablet passthrough with pressure, 3D mice, and gamepads as its Design and
3D tiers' reason to exist. That is device redirection, not key mapping -- which is exactly
where `docs/usb-redirection-design.md` is: Stage 0 policy and Stage 1 bus reads are
merged, and the device itself stays unreachable until the protocol and signing questions
in its §2.4 are answered. Input mapping is done; the peripheral axis is the open one, and
this benchmark is what proves it is the right place to spend the next round.

### 5.5 What this document got wrong when it was written, and what fixed it

The first version of this page reported seven keyboard translation modes and named
`shortcutTranslationMode` among the settings behind them. Both claims were wrong, and the way
they were wrong is worth writing down, because the mechanism of the error is available to
anyone who reads this repository.

`Localizable.strings` still carried seven sentences named `Shortcut Translation Mode <mode>
detail`. Sentences in a language table are evidence that somebody meant to ship a thing; they
are not evidence that a thing ships. `KeyboardCompatibilityMode` had already been reduced to
one case, its own comment saying the other five were "removed completely", and the identifier
`shortcutTranslationMode` does not exist anywhere in the tree. The table said a mode had a
description; the code said there was no mode.

Two repairs, both checkable. The seven sentences are gone from both tables (1029 keys per
language became 1024), so the next reader cannot be shown a mode that was deleted. And the
hole that let them live -- and let a picker's option label and its explanatory sentence lose
their table entries while the audit printed complete coverage -- is closed: `l10n-audit.py`
now reads keys carried by a variable, which is how both a `*Key` computed property and an
enum's `displayKey` reach `localize()`. Neither literal sits inside a call, so the scan had
never seen them; 384 referenced keys became 394, and two of those ten were genuinely
unanswered in both languages until this round. The audit's own fixtures cover the two new
shapes and refuse a third: a property that merely returns English is not a key.

## 6. Re-running the evidence

Our own surface:

```sh
grep -n 'keyboardCompatibilityMode\|mouseDriver\|coreHIDMaxMouseReportRate\|freeMouseMotionMode\|absoluteMouseMode\|swapMouseButtons\|gamepadMouseMode\|mouseMode\|pointerSensitivity\|reverseScrollDirection' \
  Limelight/macOS/ViewControllers/SettingsObjCBridge.swift
sed -n '/supportedKeySymbols: \[Int: String\] = \[/,/^\s*\]$/p' \
  Limelight/macOS/ViewControllers/SettingsShortcuts.swift | grep -c kVK_   # 97
sed -n '/static func relevantModifierFlags/,/^  }/p' \
  Limelight/macOS/ViewControllers/SettingsShortcuts.swift   # .control .option .shift .command .function
grep -n 'Shortcut Translation Mode .* detail' Limelight/macOS/en.lproj/Localizable.strings
```

Upstream and Citrix, both fetched at 12:00 +08:00 on 2026-09-20 with HTTP 200:

```sh
curl -s https://raw.githubusercontent.com/moonlight-stream/moonlight-qt/master/app/settings/streamingpreferences.h \
  | grep -o 'Q_PROPERTY(bool [a-zA-Z]*' | awk '{print $2}' | sort
# 25 booleans. None of them names a key, a modifier, a shortcut, or a capture tier.
curl -s https://raw.githubusercontent.com/FlorianSLZ/scloud/2f32dfbfbb3c5855d87da8a5b874191afc9c5d37/Policies/ADMX/Citrix/Receiver-Intune.admx \
  | grep -n 'TransparentKeyPassthrough\|Ctrl_Alt_Del\|Tasklist\|Part_Keyboard_Windows_Key'
```

The ToDesk and UU claims come from their homepage text and are tier 3. Do not turn one
into a mechanism claim without a source that states the mechanism.

## 7. Carried forward

| Item | Status | Blocking decision |
| --- | --- | --- |
| USB Stage 2 -- open a device, and the entitlement/signing that permits it | open, tracked in `docs/usb-redirection-design.md` §7 | none yet; the protocol question in §2.4 of that document is still the gate |
| Secure attention sequence preset in the rule editor | open, new in this document | needs a UI placement decision, not a mechanism |
| Global capture-tier switch a la `TransparentKeyPassthrough` | **rejected** -- §5.2 | closed unless macOS starts delivering Cmd+Tab to a windowed app |
| Command-becomes-Ctrl as a default (ToDesk's preference) | open -- a rule already does the job, and no switch does | needs a decision about which keyboard the defaults should serve; a picker whose only job is to flip one mapping is exactly the surface `KeyboardCompatibilityMode` was reduced away from |
| Touch chord preset library (UU's 300+) | **not applicable** -- a macOS client has no touch surface to carry it | closed |
