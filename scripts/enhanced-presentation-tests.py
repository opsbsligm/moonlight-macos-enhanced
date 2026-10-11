#!/usr/bin/env python3
"""Replay midpoint/source submission, pressure retries and stale VT completion.

Compiles the shipping decision functions. Mutations must fail the same replay.
Wiring checks ensure both the draw and refresh callback consult that decision.
"""
from pathlib import Path
import subprocess
import tempfile
import importlib.util
import re
import apple_toolchain

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'Limelight/Stream/EnhancedPresentationPolicy.h'
ENHANCEMENT_POLICY = ROOT / 'Limelight/Stream/EnhancementProcessingPolicy.h'
enhancement_header = ENHANCEMENT_POLICY.read_text()
DRIVER = r'''
#include "EnhancedPresentationPolicy.h"
#include "EnhancementProcessingPolicy.h"
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
    assert(MLEnhancementMayPublish(2,2,10,10,true,false));
    assert(!MLEnhancementMayPublish(1,2,10,10,true,false));
    assert(!MLEnhancementMayPublish(2,2,9,10,true,false));
    assert(!MLEnhancementMayPublish(2,2,10,10,false,false));
    assert(!MLEnhancementMayPublish(2,2,10,10,true,true));
    assert(MLEnhancementShouldWait(true,100,109,10));
    assert(!MLEnhancementShouldWait(true,100,110,10));
    assert(!MLEnhancementShouldWait(true,100,140,10));
    assert(!MLEnhancementShouldWait(false,100,101,10));
    assert(!MLEnhancementShouldWait(true,100,99,10));
    assert(!MLEnhancementShouldWait(true,100,100,0));
    return 0;
}
'''
def replay(header, processing_header=enhancement_header):
    with tempfile.TemporaryDirectory(prefix='ml-present-') as d:
        p = Path(d)
        (p/'EnhancedPresentationPolicy.h').write_text(header)
        (p/'EnhancementProcessingPolicy.h').write_text(processing_header)
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
enhancement_mutations = [
    ('publish-after-stop', 'taskGeneration == currentGeneration', 'taskGeneration <= currentGeneration'),
    ('publish-old-frame', 'taskSequence == currentSequence', 'taskSequence <= currentSequence'),
    ('publish-wrong-buffer', 'inputIsCurrent &&', '(inputIsCurrent || !inputIsCurrent) &&'),
    ('publish-after-fallback', '!alreadySubmitted;', '(alreadySubmitted || !alreadySubmitted);'),
    ('wait-on-older-input', 'return sameInput &&', 'return (sameInput || !sameInput) &&'),
    ('wait-past-deadline', 'nowMs - startedAtMs < budgetMs', 'nowMs - startedAtMs <= budgetMs'),
]
for name, before, after in enhancement_mutations:
    assert enhancement_header.count(before) == 1, name
    assert replay(header, enhancement_header.replace(before, after)) != 0, name + ' survived'
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
processor = section('- (CVImageBufferRef)copyFrameUsingFrameProcessorIfNeeded:', '- (MTLPixelFormat)metalLumaPlaneFormatForPixelBuffer:')
teardown = section('- (void)teardownEnhancementProcessor\n', '- (void)teardownFrameInterpolationProcessor\n')
assert 'processWithParameters:' not in draw, 'draw synchronously invokes VT'
assert processor.index('dispatch_async(_vtEnhancementQueue') < processor.index('processWithParameters:'), 'VT is outside its processing queue'
assert re.search(r'\bdispatch_sync\s*\(', processor + teardown) is None, 'main-thread CPU wait reintroduced'
assert '_enhancementProcessInFlight = YES;' in processor and 'if (_enhancementProcessInFlight)' in processor, 'unbounded VT queue'
assert 'MLEnhancementShouldWait(' in processor and 'MLEnhancementMayPublish(' in processor, 'shipping async policy disconnected'
assert 'inputLifetime' in processor and 'poolLifetime' in processor and 'CFRetain(_frameProcessorOutputPool)' in processor, 'task loses source or pool on stop'
assert '_currentFramePresentationTimeStamp' not in processor and 'framePresentationTimeStamp = _currentFramePresentationTimeStamp;' in draw, 'VT uses next decode timestamp'
assert 'presentationTimeStamp:framePresentationTimeStamp' in draw and 'if (waitForEnhancedOutput)' in draw, 'draw never waits by bounded refresh retry'
assert teardown.index('dispatch_async(_vtEnhancementQueue') < teardown.index('[retiredProcessor endSession]'), 'stop ends the processing session concurrently'
assert '_enhancementProcessGeneration += 1;' in teardown and '_enhancementProcessInFlight = NO;' not in teardown, 'stop releases a slot still owned by old work'
assert '!enhancementWarmupPending && !enhancementProcessingPending' in draw, 'temporary fallback tears down an in-use processor'
assert 'report:enhancementProcessingPending' in draw and 'MLVideoEnhancementReportProcessingBudget' in draw, 'CPU pressure is mislabeled as model warmup'
assert 'framePresentationTimeStamp = _pendingInterpolatedPresentationTimeStamp;' in draw and 'outputTimeStamp:&interpolatedTimeStamp' in stage, 'midpoint timestamp is not carried with its output'
assert 'if (processedFrame != NULL)' in draw and 'if (resolvedEngine != MLActiveVideoEnhancementEngineVTLowLatencySuperResolution' in draw, 'VT is marked active merely from selection'
# Exercise the legacy cache mutation against both enclosing scopes. A moved draw
# must not make the battery silently lose the lifetime regression it guards.
spec = importlib.util.spec_from_file_location('presentation_battery', ROOT/'scripts/assertion-battery.py')
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)
for indent in ('    ', '        '):
    fixture = '\n'.join(indent + line[4:] for line in battery.CACHE_SNAPSHOT_BLOCK.splitlines())
    assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(fixture)
assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(source)
# Extract the actual async/retirement methods, with a deterministic VT double.
# Native CV buffers/pool and dispatch queues stay real; this is lifecycle evidence,
# never evidence of VT quality, supported scale factors or on-screen smoothness.
native_toolchain = apple_toolchain.clang_and_sdk_or_none()
if native_toolchain is None:
    print('SKIP native async lifecycle harness: Apple toolchain unavailable')
else:
    native_clang, native_sdk = native_toolchain
    enum_start = source.index('typedef NS_ENUM(NSInteger, MLActiveVideoEnhancementEngine)')
    enum_end = source.index('};', enum_start) + 2
    release_history = section('- (void)releasePreviousEnhancedFrames\n', '- (void)releaseFrameInterpolationFrames\n')
    def native_replay(methods, name, should_pass):
        rendered = (ROOT/'scripts/fixtures/async-enhancement-lifecycle.m').read_text()
        rendered = rendered.replace('@@ENUM@@', source[enum_start:enum_end]).replace('@@METHODS@@', methods)
        rendered = '#define MLTestRunInline(block) ((block)())\n' + rendered
        with tempfile.TemporaryDirectory(prefix='ml-enhancement-lifecycle-') as d:
            p = Path(d)
            (p/'EnhancementProcessingPolicy.h').write_text(enhancement_header)
            (p/'probe.m').write_text(rendered)
            built = subprocess.run([native_clang, '-isysroot', native_sdk, '-fobjc-arc', '-fblocks', '-Wall', '-Werror',
                '-Wno-unused-function', '-framework', 'Foundation', '-framework', 'CoreVideo',
                '-framework', 'CoreMedia', str(p/'probe.m'), '-o', str(p/'probe')], capture_output=True, text=True)
            assert built.returncode == 0, name + ': ' + built.stderr
            ran = subprocess.run([str(p/'probe')], capture_output=True, text=True, timeout=30)
            if 'SKIP' in ran.stdout:
                print(ran.stdout.strip())
                return False
            assert (ran.returncode == 0) == should_pass, name + ': ' + ran.stdout + ran.stderr
            print(ran.stdout.strip() if should_pass else 'ok: native lifecycle rejects ' + name + ' (mutation compiled)')
            return True
    methods = release_history + teardown + processor
    if native_replay(methods, 'control', True):
        assert teardown.count('dispatch_async(_vtEnhancementQueue, ^{') == 1
        native_replay(release_history + teardown.replace('dispatch_async(_vtEnhancementQueue, ^{', 'MLTestRunInline(^{') + processor,
                      'end-session-during-process', False)
        assert processor.count('dispatch_async(_vtEnhancementQueue, ^{') == 1
        native_replay(release_history + teardown + processor.replace('dispatch_async(_vtEnhancementQueue, ^{', 'MLTestRunInline(^{'),
                      'VT-runs-on-the-draw-caller', False)
        assert processor.count('if (_enhancementProcessInFlight)') == 1
        native_replay(release_history + teardown + processor.replace('if (_enhancementProcessInFlight)', 'if (_enhancementProcessInFlight && _enhancementTaskSequence == UINT64_MAX)'),
                      'multiple-CPU-tasks-in-flight', False)
print('ok: presentation + asynchronous enhancement replay, 11 mutations caught, 25 renderer wiring checks, 3 cache anchors')
