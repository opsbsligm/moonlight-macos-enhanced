#!/usr/bin/env python3
"""Compile and exercise the production edge-control lifecycle and native sensor.

The contract is two acts and never one: arrival at the edge lights the docked tab
(a 12pt x handle local-pointer dwell, in the states where the local pointer is
authoritative), and a click on that lit tab opens the bar. Locked game motion has no
pointer entry at all -- the accumulated-motion slam gesture that used to stand in for
arrival completed on ordinary aiming and took the pointer out of the game each time,
so it is deleted rather than retuned, and locked mode opens the bar with the configured
shortcut. One exclusive presentation phase governs everything. This gate covers that
contract plus the prior right/middle click, modifier-release and tab-click bugs. No
mouse/key events are posted to the desktop.
"""
from pathlib import Path
import re
import sys
from edge_sensor_runtime_probe import run_runtime_probe, method

root=Path(__file__).resolve().parents[1]
vc=root/'Limelight/macOS/ViewControllers'
mouse=(vc/'StreamViewController+MouseCapture.m').read_text()
menu=(vc/'StreamViewController+MenuUI.m').read_text()
internal=(vc/'StreamViewController_Internal.h').read_text()
run_runtime_probe(mouse,menu,internal,self_test='--self-test' in sys.argv)
band=re.search(r'MLEdgeSensorBandWidth = ([0-9.]+)', internal)
assert band and 8.0 <= float(band.group(1)) <= 16.0, 'summon band must stay findable after release without growing into the old 24pt regression'
# The locked-mode slam gesture is deleted, not tuned. Out-and-back-and-out motion inside
# 1.5s is what aiming at moving targets looks like, and each completion pulled the pointer
# out of the game; that is the report this gate exists to keep fixed. Restoring it in any
# form must fail here, and so must a sensor path that opens anything from motion.
for _dead in ('MLEdgeSensorPushStrokeCount', 'MLEdgeSensorPushWindowMs', 'edgePushStrokePoints'):
    assert _dead not in internal, 'the locked-mode slam gesture is back: ' + _dead
for _dead in ('noteEdgeSensorPushMotionForEvent', 'edge-sensor-push'):
    assert _dead not in mouse, 'the locked-mode slam gesture is back: ' + _dead
summon_path = method(mouse, '- (BOOL)handleEdgeSensorSummonForEvent:')
for _banned in ('summonEdgeMenuDock', 'uncaptureMouse', 'activateEdgeMenuDock'):
    assert _banned not in summon_path, 'mouse motion can still %s' % _banned
assert 'edgeMenuReleaseExitEdgeForEvent' not in mouse, 'legacy outward-motion activation bypass remains'
assert 'CGWarpMouseCursorPosition' not in method(mouse,'- (void)summonEdgeMenuDockForEdge:'), 'hover must not warp a guessed remote cursor'
hover=method(menu,'self.edgeMenuButton.hoverHandler =')
assert 'handleEdgeMenuHover' in hover and 'uncaptureMouse' not in hover, 'native hover bypasses the common sensor'
assert 'menuToken != self.edgeMenuLifecycleToken' in method(menu,'- (void)presentStreamMenuFromView:(NSView *)sourceView event:'), 'nested menu tracking can revive a closed session'
for name in ('edgeMenuButtonExpanded','edgeMenuDragging','edgeMenuMenuVisible'):
    assert 'self.'+name+' =' not in menu, name+' has an independent writable state'
# The settings copy is the only thing a player can read, so the numbers in it are a
# contract, not prose. It drifted to "4pt" while the code armed a 12pt band, and no
# assertion counted because no assertion read the strings. Derive them from the code.
def constant(name):
    return re.search(r'%s = ([0-9.]+)' % name, internal).group(1)
def points(name):
    return ('%dpt' % round(float(constant(name))))
def millis(name):
    return ('%dms' % round(float(constant(name)) * 1000))
# Arrival feedback has no side effects: no byte leaves, the pointer stays in the game,
# and nothing opens. A dwell that long makes the tab look broken to a pointer that is
# already at the edge, which is how "it lit up but nothing happened" started.
assert float(constant('MLEdgeSensorDwellSeconds')) * 1000.0 <= 150.0, 'arriving at the edge waits too long to answer'
def ms(name):
    v = float(constant(name))
    return ('%.0fs' % (v / 1000.0)) if v >= 1000.0 else ('%dms' % round(v))
promised = [points('MLEdgeSensorBandWidth'), millis('MLEdgeSensorDwellSeconds'),
            millis('MLEdgeMenuAutoCollapseDelay'), points('MLEdgeMenuButtonWidth'),
            millis('MLEdgeMenuSummonGraceDelay'),
            # The locked-mode flick is an entry the player must be able to read about,
            # with the same numbers the code enforces and no promises the code dropped.
            points('MLEdgeSensorFlickMinTravel'), millis('MLEdgeSensorFlickWindowSeconds'),
            ms('MLEdgeSensorFlickCooldownMs')]
for locale, locked_entry in (('en', 'open-control-center'), ('zh-Hans', '控制中心')):
    strings = (root / 'Limelight/macOS' / (locale + '.lproj') / 'Localizable.strings').read_text()
    detail = re.search(r'"Edge Sensor Summon detail" = "(.*?)";\n', strings, re.S).group(1)
    for fact in promised:
        assert fact in detail, '%s copy states a different geometry than the code: %s' % (locale, fact)
    assert locked_entry in detail, '%s copy hides how to open the bar with a locked game mouse' % locale
    # Arrival and opening are two different acts now, and a player who reads "hover to
    # open" will keep blaming the bar for opening itself.
    if locale == 'en':
        assert 'click' in detail.lower(), '%s copy still promises that hovering opens the bar' % locale
        assert 'lights' in detail.lower(), '%s copy never says what arriving at the edge actually does' % locale
    else:
        assert '点击' in detail, '%s copy still promises that hovering opens the bar' % locale
        assert '把手亮起' in detail, '%s copy never says what arriving at the edge actually does' % locale
    if locale == 'en':
        assert 'flick' in detail.lower(), '%s copy never names the locked-mode gesture' % locale
    else:
        assert '甩' in detail, '%s copy never names the locked-mode gesture' % locale
print('PASS settings copy carries the geometry the code arms and the locked-mode entry')

# Arrival must not be able to open anything, and the click must be aimed at the drawing.
# Both used to be true at once: the dwell summoned the dock, and the click measured the
# expanded interaction box nobody could see.
arm = method(mouse, '- (void)armEdgeMenuHandleIfStillAtEdge:')
for banned in ('summonEdgeMenuDock', 'uncaptureMouse', 'activateEdgeMenuDock'):
    assert banned not in arm, 'arriving at the edge still %s' % banned
# Arrival-opening exists, and only the preference decides it: the dwell timer is the
# one place allowed to open from arrival, and it must ask edgeSensorSummonOnArrival
# first so the two-step protocol stays reachable. An ungated open here is the old
# "sidebar fires on its own" bug wearing today's clothes.
dwell = method(mouse, '- (void)beginEdgeSensorDwellTimerIfNeededForEdge:')
assert 'summonEdgeMenuDockForEdge' in dwell, 'arrival can no longer open the dock at all'
assert 'edgeSensorSummonOnArrival' in dwell, 'the dwell opens the dock without asking the preference'
assert 'edgeMenuHandleArmed' in dwell, 'a dwell that lost its arm still opens the dock'
click = method(mouse, '- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer')
assert 'edgeMenuVisibleHandleRectInBounds' in click, 'the click is aimed at something other than the drawn tab'
assert 'edgeMenuInteractionRectInBounds' not in click, 'the invisible expanded box still decides which clicks open the bar'
# The gate is pointer authority. The capture flag alone refused the click in remote
# desktop mode, where capture stays on and the tab lights anyway.
assert '(self.isMouseCaptured && !self.isRemoteDesktopMode)' in click, 'the tab click is gated on the capture flag rather than on pointer authority'
peek = float(constant('MLEdgeMenuButtonVisiblePeek'))
idle, lit = float(constant('MLEdgeMenuHandleIdleThickness')), float(constant('MLEdgeMenuHandleArmedThickness'))
slop = float(constant('MLEdgeMenuHandleHitSlop'))
assert peek >= 24.0, 'the dock has shrunk back to a seam nobody can find or aim at'
assert lit > idle >= 12.0, 'arming the tab changes nothing the player can see'
assert lit <= peek, 'the armed tab is drawn wider than the panel that carries it'
assert 0.0 <= slop <= 2.0, 'the click tolerance has grown back into a second sensor'
assert idle + 2.0 + slop <= 18.0, 'an idle click reaches deeper into the frame than the tab it can see'
assert lit + 2.0 + slop <= 36.0, 'a lit click reaches deeper into the frame than the tab it can see'
# One gate decides whether the bar may answer at all, and the runtime probe deliberately
# stubs it away. That makes the gate's own contents a static contract: losing focus, app
# inactivity, miniaturising, a Space switch, a fullscreen transition, a stop and a reconnect
# are each named on the acceptance list, and no stub can re-derive them.
GATE_FACTS = ('window.isKeyWindow', 'window.isVisible', '!window.isMiniaturized',
              '[NSApp isActive]', '!self.stopStreamInProgress', '!self.reconnectInProgress',
              '!self.spaceTransitionInProgress', '!self.fullscreenTransitionInProgress',
              '[self isWindowInCurrentSpace]')
def gate_ok(text):
    return all(fact in text for fact in GATE_FACTS)
gate = method(menu, '- (BOOL)edgeMenuCanInteract')
assert gate_ok(gate), 'the interaction gate lost: ' + ', '.join(f for f in GATE_FACTS if f not in gate)
assert 'self.userReleasedInput' not in gate, 'the interaction gate also owns pointer release'
# The sensor measures the video view, not the window frame. Fullscreen insets and letterbox
# bars move the picture inside the window, and a tab parked on the window edge would sit on
# the black bar instead of on the frame the player is aiming at.
def anchor_ok(text):
    return ('self.view.bounds' in text and 'convertRectToScreen' in text and
            'window.frame' not in text and 'backingScaleFactor' not in text)
anchor = method(menu, '- (NSRect)edgeMenuAnchorRectInScreen')
assert anchor_ok(anchor), 'the anchor rect stopped being the video view converted to screen coordinates'
if '--self-test' in sys.argv:
    for lost in GATE_FACTS:
        assert not gate_ok(gate.replace(lost, 'YES')), 'the gate check tolerates losing ' + lost
    print('PASS negative control: a lifecycle condition removed from the interaction gate')
    for broken in (anchor.replace('self.view.bounds', 'self.view.window.frame'),
                   anchor.replace('convertRectToScreen', 'convertRect'),
                   anchor.replace('rectInWindow', 'rectInWindow), backingScaleFactor:self.view): return [self.view.window convertRectToScreen:rectInWindow')):
        assert not anchor_ok(broken), 'the anchor check tolerates leaving the video view'
    print('PASS negative control: an anchor measured from the window frame or in pixels')
print('PASS arrival cannot open the bar, the click follows the drawing, and the tab is visible')
print('PASS no activation bypass, cursor warp, duplicate presentation state or stale menu completion')

# The control-center shortcut once opened the dock and then stacked a modal menu on top
# of it. A modal menu in front of a pointer that has no position to aim with swallowed the
# player's next click, and one field log shows that click landing on Disconnect. The dock
# and the menu are alternatives at both shortcut callsites; the menu is the fallback for
# windowed mode, where there is no dock to open. (The third presentation is the separate
# keyboard-translation action, which never opens a dock.)
guarded = len(re.findall(r'if \(!\[(?:self|strongSelf) openEdgeMenuDockForControlCenterShortcut\]\)\s*\{\s*\[(?:self|strongSelf) presentControlCenterFromShortcut\];', mouse))
assert guarded == 2, 'the control-center shortcut must open the dock OR present the menu, never both (%d guarded callsites)' % guarded
bare = len(re.findall(r'^\s*\[(?:self|strongSelf) openEdgeMenuDockForControlCenterShortcut\];', mouse, re.M))
assert bare == 0, 'an unguarded dock call can no longer report whether the menu is still needed'
DOCK_MENU = r'if \(!\[(?:self|strongSelf) openEdgeMenuDockForControlCenterShortcut\]\)\s*\{\s*\[(?:self|strongSelf) presentControlCenterFromShortcut\];'
if '--self-test' in sys.argv:
    legacy = re.sub(r'if \(!\[(\w+) openEdgeMenuDockForControlCenterShortcut\]\)\s*\{\s*\[\1 presentControlCenterFromShortcut\];\s*\}',
                    r'[\1 openEdgeMenuDockForControlCenterShortcut];\n [\1 presentControlCenterFromShortcut];', mouse)
    assert len(re.findall(DOCK_MENU, legacy)) == 0, 'the shape guard accepts the calls it exists to prevent'
    print('PASS negative control: modal menu stacked on the open sidebar')
print('PASS the control-center shortcut cannot stack a modal menu on the open sidebar')

# Windowed mode is a first-class presentation for the dock, not a mode where the bar
# "does not exist". It used to refuse the dock outright and leave a 240pt pill fused into
# the right end of the titlebar as the only entry, which is the report this gate exists to
# keep fixed: the same edge gesture worked fullscreen and did nothing windowed, and the pill
# read as the titlebar itself. A future "simplification" that re-adds the presentation
# refusal or re-widens the pill must fail here rather than reopen the report.
visible = method(menu, '- (BOOL)edgeMenuShouldBeVisible')
assert '![self isWindowFullscreen] && ![self isWindowBorderlessMode]' not in visible, \
    'windowed mode is hidden from the edge dock again: the edge gesture only works in two of three presentations'
assert 'isWindowFullscreen' in visible and 'hideFullscreenControlBall' in visible, \
    'the fullscreen opt-out for the on-screen entry was lost'
pill = re.search(r'const CGFloat containerWidth = ([0-9.]+);', menu)
assert pill and float(pill.group(1)) <= 160.0, \
    'the titlebar pill grew back into a wide fake button: %s pt' % pill.group(1)
badge = method(menu, '- (NSString *)currentStreamHealthBadgeText')
assert 'MLString(@"Control Center", nil)' not in badge, \
    'the pill labels itself "Control Center" again, which is the fusion the edge tab replaced'

# The pill's final form: no titlebar furniture at all while the stream is healthy.
# The user's verdict on even the shrunken 132pt badge was that it still fuses into
# the titlebar and the open menu lands on top of it; the edge tab is the entry, so
# the accessory may only mount to shout about a stream that is actually wrong.
ensure = method(menu, '- (void)ensureMenuTitlebarAccessoryInstalledIfNeeded')
assert 'currentStreamHealthBadgeText' in ensure, \
    'the titlebar pill is furniture again: it must mount only while the stream is unhealthy'



# A top-docked handle has to draw above the menu-bar seam. AppKit clamps
# borderless panels below the menu bar, which cut the top handle in half (the
# matrix read that as "the handle is gone" while the app still had it). The
# panel owns its geometry and opts out of that one clamp; a future refactor
# that drops the opt-out silently re-breaks top docking.
edgeui=(vc/'MLEdgeMenuUI.m').read_text()
assert 'constrainFrameRect:(NSRect)frame toScreen:' in edgeui, \
    'the edge panel lost its menu-bar clamp opt-out: a top-docked handle gets cut in half again'


# Input ownership for the edge dock is one contract with two halves. The panel owns
# ignoresMouseEvents and grants it in exactly one phase (Hidden); the handle owns
# hitTest and, while collapsed, answers only on the drawn strip plus its own slop.
# A collapsed panel that set ignoresMouseEvents would make the clickable tab dead
# again (the exact regression 85783864 fixed), and a compact hit rect that grew past
# the plate would let an invisible overlay swallow game clicks. Pin both halves
# structurally; the runtime probe pins the phase/flag behaviour.
def pinned_input_contract(menu_src, edgeui_src):
    transition = method(menu_src, '- (void)transitionEdgeMenuToPhase:')
    assert 'self.edgeMenuPanel.ignoresMouseEvents = phase == MLEdgeMenuPhaseHidden;' in transition, \
        'the collapsed panel no longer stays clickable: only Hidden may take native input away'
    assert 'MLEdgeMenuPhaseCollapsed' not in transition.split('ignoresMouseEvents')[1].split(';')[0], \
        'a collapsed-phase clause is back on ignoresMouseEvents: the drawn tab cannot be clicked'
    hit = method(edgeui_src, '- (NSView *)hitTest:(NSPoint)point')
    assert 'self.compactAppearance' in hit and 'if (NSIsEmptyRect(_compactHitRect)) return nil;' in hit, \
        'the collapsed handle lost its narrow hit rect: an unseen overlay area can swallow stream clicks'
    assert 'return NSPointInRect(localPoint, _compactHitRect) ? self : nil;' in hit, \
        'the collapsed handle answers outside its drawn strip'
    layout = method(edgeui_src, '- (void)layout')
    assert '_compactHitRect = NSZeroRect;' in layout, \
        'the compact hit rect is no longer reset every layout pass: a moved tab keeps answering on its old strip'
    assert '_compactHitRect = NSInsetRect(plateFrame, -MLEdgeMenuHandleHitSlop, -MLEdgeMenuHandleHitSlop);' in layout, \
        'the compact hit rect no longer follows the drawn plate plus its declared slop'
pinned_input_contract(menu, edgeui)
print('PASS input ownership: collapsed panel clickable, stream protected by the compact hit rect')
if '--self-test' in sys.argv:
    legacy_input = menu.replace(
        'self.edgeMenuPanel.ignoresMouseEvents = phase == MLEdgeMenuPhaseHidden;',
        'self.edgeMenuPanel.ignoresMouseEvents = phase == MLEdgeMenuPhaseCollapsed || phase == MLEdgeMenuPhaseHidden;')
    try:
        pinned_input_contract(legacy_input, edgeui)
        raise AssertionError('the input contract accepts the dead-tab regression')
    except AssertionError as error:
        assert 'ignoresMouseEvents' in str(error) or 'collapsed' in str(error).lower(), error
    print('PASS negative control: collapsed ignoresMouseEvents regression is rejected')
    blind_hit = edgeui.replace('if (NSIsEmptyRect(_compactHitRect)) return nil;', '')
    try:
        pinned_input_contract(menu, blind_hit)
        raise AssertionError('the input contract accepts a handle with no empty-rect guard')
    except AssertionError as error:
        assert 'hit rect' in str(error), error
    print('PASS negative control: unguarded compact hit rect is rejected')
    drift_layout = edgeui.replace(
        '_compactHitRect = NSInsetRect(plateFrame, -MLEdgeMenuHandleHitSlop, -MLEdgeMenuHandleHitSlop);',
        '_compactHitRect = NSMakeRect(0, 0, 56, 56);')
    try:
        pinned_input_contract(menu, drift_layout)
        raise AssertionError('the input contract accepts a hit rect that ignores the drawing')
    except AssertionError as error:
        assert 'plate' in str(error) or 'reset' in str(error), error
    print('PASS negative control: hit rect detached from the drawn plate is rejected')

rebuild=method(menu,'- (void)rebuildStreamMenu')
assert rebuild.index('if (self.edgeMenuMenuVisible) return;') < rebuild.index('[self.streamMenu removeAllItems]'), 'live updates can mutate the tracked menu'
