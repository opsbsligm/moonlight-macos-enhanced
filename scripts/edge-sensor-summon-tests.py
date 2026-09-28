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
            millis('MLEdgeMenuAutoCollapseDelay'), points('MLEdgeMenuButtonWidth')]
for locale, locked_entry in (('en', 'open-control-center'), ('zh-Hans', '控制中心')):
    strings = (root / 'Limelight/macOS' / (locale + '.lproj') / 'Localizable.strings').read_text()
    detail = re.search(r'"Edge Sensor Summon detail" = "(.*?)";\n', strings, re.S).group(1)
    for fact in promised:
        assert fact in detail, '%s copy states a different geometry than the code: %s' % (locale, fact)
    assert locked_entry in detail, '%s copy hides how to open the bar with a locked game mouse' % locale
print('PASS settings copy carries the geometry the code arms and the locked-mode entry')
print('PASS no activation bypass, cursor warp, duplicate presentation state or stale menu completion')

rebuild=method(menu,'- (void)rebuildStreamMenu')
assert rebuild.index('if (self.edgeMenuMenuVisible) return;') < rebuild.index('[self.streamMenu removeAllItems]'), 'live updates can mutate the tracked menu'
