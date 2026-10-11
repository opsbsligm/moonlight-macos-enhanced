#!/usr/bin/env python3
"""Replay midpoint/source submission, pressure retries and stale VT completion.

Compiles the shipping decision functions. Mutations must fail the same replay.
Wiring checks ensure both the draw and refresh callback consult that decision.
"""
from pathlib import Path
import subprocess
import tempfile
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'Limelight/Stream/EnhancedPresentationPolicy.h'
DRIVER = r'''
#include "EnhancedPresentationPolicy.h"
#include <assert.h>
int main(void) {
    assert(!MLPresentationNeedsDraw(0,0,0,0,false));
    // Staging cannot let the source overtake its midpoint.
    assert(!MLPresentationNeedsDraw(10,10,9,0,false));
    assert(MLInterpolationResultIsCurrent(10,10,9));
    // A failed GPU/drawable submission leaves state unchanged and must retry.
    for (int i=0; i<4; ++i) assert(MLPresentationNeedsDraw(10,0,9,10,false));
    // Midpoint submitted; the source still needs its own refresh.
    assert(MLPresentationNeedsDraw(10,0,9,10,true));
    // Source submitted: no duplicate SR or presents on idle refreshes.
    for (int i=0; i<4; ++i) assert(!MLPresentationNeedsDraw(10,0,10,0,false));
    assert(!MLPresentationNeedsDraw(10,0,10,10,true));
    // Decode overtakes VT: old midpoint must be discarded, latest source remains drawable.
    assert(!MLInterpolationResultIsCurrent(11,10,9));
    assert(MLPresentationNeedsDraw(11,0,10,10,false));
    assert(!MLInterpolationResultIsCurrent(10,10,10));
    assert(!MLInterpolationResultIsCurrent(0,10,0));
    assert(!MLInterpolationResultIsCurrent(0,0,0));
    // Plain stream and a failed/warming interpolator retain the source path.
    assert(MLPresentationNeedsDraw(12,0,11,0,false));
    assert(!MLPresentationNeedsDraw(12,0,12,0,false));
    return 0;
}
'''
def replay(header):
    with tempfile.TemporaryDirectory(prefix='ml-present-') as d:
        p = Path(d)
        (p/'EnhancedPresentationPolicy.h').write_text(header)
        (p/'replay.c').write_text(DRIVER)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'replay.c'),'-o',str(p/'replay')],check=True)
        return subprocess.run([str(p/'replay')],capture_output=True).returncode

header = POLICY.read_text()
assert replay(header) == 0, 'shipping replay failed'
mutations = [
    ('source-overtakes-midpoint', 'current == 0 || staging == current', 'current == 0 || staging == UINT64_MAX'),
    ('repeat-super-resolution', 'return current != submittedSource;', 'return current != UINT64_MAX || submittedSource == 0;'),
    ('accept-stale-VT', 'result == current', 'result <= current'),
    ('accept-late-midpoint', 'result != submittedSource', '(result != UINT64_MAX || submittedSource == 0)'),
    ('lose-pressure-retry', 'if (midpointSource == current && !midpointSubmitted) return true;', 'if (midpointSource == current && !midpointSubmitted) return false;'),
]
for name, before, after in mutations:
    assert header.count(before) == 1, name
    assert replay(header.replace(before,after)) != 0, name + ' survived'
source = (ROOT/'Limelight/Stream/VideoDecoderRenderer.m').read_text()
def section(start, end):
    return source[source.index(start):source.index(end,source.index(start))]
draw = section('- (void)drawInMTKView:', '- (void)start\n')
stage = section('- (BOOL)stageInterpolatedFrameFromPreviousSource:', '- (BOOL)presentationCadenceForInterpolationHold:')
callback = section('static CVReturn displayLinkCallback(CVDisplayLinkRef displayLink,\n', '- (void)stop\n')
decode = section('- (void)handleDecompressionOutput:', '- (BOOL)createDecompressionSession')
assert draw.index('MLPresentationNeedsDraw(') < draw.index('copyFrameUsingFrameProcessorIfNeeded:'), 'duplicate SR work'
assert 'MLPresentationNeedsDraw(' in callback and 'if (shouldRetryEnhancedFrame)' in callback, 'refresh retry disconnected'
assert stage.index('MLInterpolationResultIsCurrent(') < stage.index('_pendingInterpolatedFrame = interpolatedFrame;'), 'stale publication'
assert '_currentFrame != sourceFrame' in stage, 'buffer identity guard missing'
assert '_interpolationStagingSequence = sourceSequence;' in decode, 'staging guard disconnected'
assert '_interpolationStagingSequence == sourceSequence' in decode, 'old completion clears newer staging'
assert draw.index('dispatch_semaphore_wait(') < draw.index('copyFrameUsingFrameProcessorIfNeeded:'), 'SR runs before GPU admission'
assert draw.count('dispatch_semaphore_wait(') == 1, 'double reservation'
assert '@finally' in draw and 'inflightSemaphore != nil && !submittedCommandBuffer' in draw, 'early exit leaks permit'
assert draw.count('dispatch_semaphore_signal(inflightSemaphore)') == 2, 'GPU/early-exit release paths'
assert 'dispatch_semaphore_signal(self->_metalInflightSemaphore)' not in draw, 'completion signals new session'
# Exercise the legacy cache mutation against both enclosing scopes. A moved draw
# must not make the battery silently lose the lifetime regression it guards.
spec = importlib.util.spec_from_file_location('presentation_battery', ROOT/'scripts/assertion-battery.py')
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)
for indent in ('    ', '        '):
    fixture = '\n'.join(indent + line[4:] for line in battery.CACHE_SNAPSHOT_BLOCK.splitlines())
    assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(fixture)
assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(source)
print('ok: presentation replay, 5 mutations caught, 11 renderer wiring checks, 3 cache anchors')
