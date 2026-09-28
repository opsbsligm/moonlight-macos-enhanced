#!/usr/bin/env python3
"""Compile and exercise the production edge-control lifecycle and native sensor.

The full-edge/push-budget contract has been replaced by two explicit entries: a
12pt × handle local-pointer dwell (free mouse and explicit release, where the local
pointer is authoritative) and a separated two-stroke slam gesture for locked game
motion, which never infers a remote position. One exclusive presentation phase
governs both. This gate covers that contract plus the prior right/middle click,
modifier-release and tab-click bugs. No mouse/key events are posted to the desktop.
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
assert 'MLEdgeSensorPushStrokeCount' in internal and 'MLEdgeSensorPushWindowMs' in internal, 'locked-mode slam entry must not be silently dropped'
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
promised = [points('MLEdgeSensorBandWidth'), millis('MLEdgeSensorDwellSeconds'),
            millis('MLEdgeMenuAutoCollapseDelay'), points('MLEdgeMenuButtonWidth'),
            millis('MLEdgeMenuSummonGraceDelay')]
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
print('PASS settings copy carries the geometry the code arms and the locked-mode entry')

# Arrival must not be able to open anything, and the click must be aimed at the drawing.
# Both used to be true at once: the dwell summoned the dock, and the click measured the
# expanded interaction box nobody could see.
arm = method(mouse, '- (void)armEdgeMenuHandleIfStillAtEdge:')
for banned in ('summonEdgeMenuDock', 'uncaptureMouse', 'activateEdgeMenuDock'):
    assert banned not in arm, 'arriving at the edge still %s' % banned
click = method(mouse, '- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer')
assert 'edgeMenuVisibleHandleRectInBounds' in click, 'the click is aimed at something other than the drawn tab'
assert 'edgeMenuInteractionRectInBounds' not in click, 'the invisible expanded box still decides which clicks open the bar'
peek = float(constant('MLEdgeMenuButtonVisiblePeek'))
idle, lit = float(constant('MLEdgeMenuHandleIdleThickness')), float(constant('MLEdgeMenuHandleArmedThickness'))
slop = float(constant('MLEdgeMenuHandleHitSlop'))
assert peek >= 24.0, 'the dock has shrunk back to a seam nobody can find or aim at'
assert lit > idle >= 12.0, 'arming the tab changes nothing the player can see'
assert lit <= peek, 'the armed tab is drawn wider than the panel that carries it'
assert 0.0 <= slop <= 8.0, 'the click tolerance has grown back into a second sensor'
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

rebuild=method(menu,'- (void)rebuildStreamMenu')
assert rebuild.index('if (self.edgeMenuMenuVisible) return;') < rebuild.index('[self.streamMenu removeAllItems]'), 'live updates can mutate the tracked menu'
