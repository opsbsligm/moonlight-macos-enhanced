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
actual_header = (ROOT/'Limelight/Stream/ActualPresentationMetrics.h').read_text()
DRIVER = r'''
#include "EnhancedPresentationPolicy.h"
#include "EnhancementProcessingPolicy.h"
#include "ActualPresentationMetrics.h"
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
    assert(MLEnhancementOverloadStrikes(0,true,4,5)==0);
    // Missing the publish deadline alone is a late publish, not an overrun: the
    // measured engine costs 1.6x-3.7x a source frame, so striking 1x-2x opens the
    // breaker on every dynamic scene. A call at twice the deadline taxes the next
    // frame and scores; four times the deadline is the pace that cannot coexist.
    assert(MLEnhancementOverloadStrikes(0,true,5,5)==0);
    assert(MLEnhancementOverloadStrikes(0,true,9,5)==0);
    assert(MLEnhancementOverloadStrikes(2,true,9,5)==0);
    assert(MLEnhancementOverloadStrikes(0,true,10,5)==1);
    assert(MLEnhancementOverloadStrikes(1,true,10,5)==2);
    assert(MLEnhancementOverloadStrikes(2,true,10,5)==3);
    assert(MLEnhancementOverloadStrikes(2,true,4,5)==0);
    assert(MLEnhancementOverloadStrikes(0,true,20,5)==3);
    assert(MLEnhancementOverloadStrikes(0,false,0,5)==3);
    assert(MLEnhancementOverloadStrikes(0,true,1,0)==3);
    assert(MLEnhancementOverloadStrikes(0,true,UINT64_MAX,5)==3);
    // An adaptive deadline may raise the window to meet a measured engine, up to
    // two source frames; it may never go below the honest fixed window, and an
    // engine measured out of that ceiling earns strikes instead of forgiveness.
    assert(MLEnhancementAdaptiveBudgetMs(0,180,60)==16);
    // A cheap engine may not pull the window under the honest fixed floor.
    assert(MLEnhancementAdaptiveBudgetMs(1,180,60)==16);
    assert(MLEnhancementAdaptiveBudgetMs(20,180,60)==26);
    assert(MLEnhancementAdaptiveBudgetMs(30,180,60)==32);
    assert(MLEnhancementAdaptiveBudgetMs(100,180,60)==32);
    assert(MLEnhancementAdaptiveBudgetMs(20,0,0)==26);
    // The staging deadline must be a window the work can honestly fit: one
    // source frame, never below a display period, never below a service floor.
    assert(MLEnhancementStagingBudgetMs(180,60)==16);
    assert(MLEnhancementStagingBudgetMs(180,90)==11);
    assert(MLEnhancementStagingBudgetMs(60,30)==33);
    assert(MLEnhancementStagingBudgetMs(30,60)==33);
    assert(MLEnhancementStagingBudgetMs(0,60)==16);
    assert(MLEnhancementStagingBudgetMs(240,0)==16);
    assert(MLEnhancementStagingBudgetMs(1000,1000)==8);
    assert(MLEnhancementNextBackoff(0,14)==2000);
    assert(MLEnhancementNextBackoff(0,741)==5928);
    assert(MLEnhancementNextBackoff(5928,741)==11856);
    assert(MLEnhancementNextBackoff(40000,1)==60000);
    assert(MLEnhancementNextBackoff(0,UINT64_MAX)==60000);
    // Cooldown probe: a paused engine retries one frame once the backoff elapsed.
    assert(MLEnhancementProbeDue(100,2100,2000));
    assert(MLEnhancementProbeDue(100,1100,1000));
    assert(MLEnhancementProbeDue(100,100,0));
    assert(!MLEnhancementProbeDue(100,1099,1000));
    assert(!MLEnhancementProbeDue(100,50,2000));
    assert(!MLEnhancementProbeDue(100,99,0));
    MLActualPresentationState actual = {0};
    assert(MLActualPresentationRecord(&actual,0,10,9.997,false,true));
    assert(!MLActualPresentationRead(&actual,10).available);
    assert(MLActualPresentationRecord(&actual,0,10+1.0/180,10+1.0/180-0.003,true,false));
    MLActualPresentationReading observed = MLActualPresentationRead(&actual,10.01);
    assert(observed.available && fabs(observed.fps-180)<0.00001);
    assert(fabs(observed.frameP95Ms-1000.0/180)<0.00001);
    assert(observed.waitAvailable && fabs(observed.waitP95Ms-3)<0.00001);
    assert(actual.presented==2 && actual.interpolated==1 && actual.scaled==1);
    assert(!MLActualPresentationRecord(&actual,0,0,0,true,true));
    assert(actual.unpresented==1 && actual.presented==2);
    assert(!MLActualPresentationRecord(&actual,0,NAN,0,false,false));
    assert(!MLActualPresentationRecord(&actual,0,INFINITY,0,false,false));
    assert(!MLActualPresentationRecord(&actual,0,-1,0,false,false));
    assert(actual.invalid==3);
    assert(MLActualPresentationRecord(&actual,0,10.02,10.018,false,false));
    assert(MLActualPresentationRecord(&actual,0,10.01,10.008,false,false));
    observed=MLActualPresentationRead(&actual,10.03);
    assert(observed.available && fabs(observed.fps-150)<0.00001);
    assert(fabs(observed.frameP95Ms-10)<0.00001);
    assert(!MLActualPresentationRead(&actual,13).available);
    assert(!MLActualPresentationRead(&actual,NAN).available);
    assert(!MLActualPresentationRead(&actual,9).available);
    assert(MLActualPresentationRecord(&actual,0,10.01,10,false,false));
    assert(!MLActualPresentationRead(&actual,10.03).available);
    uint64_t previousPresented = actual.presented;
    assert(MLActualPresentationRecord(&actual,0,20,19.998,false,false));
    assert(actual.count==1 && actual.presented==previousPresented+1);
    assert(!MLActualPresentationRead(&actual,20).available);
    assert(MLActualPresentationRecord(&actual,0,20.01,20.008,false,false));
    observed=MLActualPresentationRead(&actual,20.02);
    assert(observed.available && fabs(observed.fps-100)<0.00001);
    assert(!MLActualPresentationRecord(&actual,0,10.04,10.03,false,false));
    assert(MLActualPresentationRead(&actual,20.02).available);
    MLActualPresentationReset(&actual);
    assert(actual.generation==1 && actual.count==0 && actual.presented==0);
    assert(!MLActualPresentationRecord(&actual,0,20,19,false,false));
    for(int i=0;i<1000;i++) {
        double t=20+i/180.0;
        assert(MLActualPresentationRecord(&actual,1,t,t-0.002,(i%2)==1,false));
        assert(actual.count<=ML_ACTUAL_PRESENTATION_CAPACITY);
    }
    observed=MLActualPresentationRead(&actual,20+999/180.0);
    assert(actual.count==128 && actual.presented==1000 && actual.interpolated==500);
    assert(observed.available && fabs(observed.fps-180)<0.00001);
    MLActualPresentationReset(&actual);
    assert(MLActualPresentationRecord(&actual,2,30,NAN,false,false));
    assert(MLActualPresentationRecord(&actual,2,30.01,31,false,false));
    observed=MLActualPresentationRead(&actual,30.02);
    assert(observed.available && !observed.waitAvailable);
    return 0;
}
'''
def replay(header, processing_header=enhancement_header, observations_header=actual_header):
    with tempfile.TemporaryDirectory(prefix='ml-present-') as d:
        p = Path(d)
        (p/'EnhancedPresentationPolicy.h').write_text(header)
        (p/'EnhancementProcessingPolicy.h').write_text(processing_header)
        (p/'ActualPresentationMetrics.h').write_text(observations_header)
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
    ('ignore-probe-compute-cost', 'elapsedMs * 8', 'elapsedMs * 0'),
    ('stop-growing-probe-backoff', 'previousMs * 2', 'previousMs'),
    ('deadline-equality-resets-overload', 'elapsedMs / budgetMs >= 2', 'elapsedMs / budgetMs > 2'),
    ('strike-the-late-publish-again', 'elapsedMs / budgetMs >= 2', 'elapsedMs >= budgetMs'),
    ('ignore-failed-process', '!processed || budgetMs == 0', '(budgetMs == 0 && processed)'),
    ('ignore-severe-overload', 'elapsedMs / budgetMs >= 4', 'elapsedMs / budgetMs >= 400'),
    ('never-stop-mild-overload', 'previous >= 2 ? 3 : previous + 1', 'previous >= 2 ? 2 : previous + 1'),

    ('publish-after-stop', 'taskGeneration == currentGeneration', 'taskGeneration <= currentGeneration'),
    ('publish-old-frame', 'taskSequence == currentSequence', 'taskSequence <= currentSequence'),
    ('publish-wrong-buffer', 'inputIsCurrent &&', '(inputIsCurrent || !inputIsCurrent) &&'),
    ('publish-after-fallback', '!alreadySubmitted;', '(alreadySubmitted || !alreadySubmitted);'),
    ('wait-on-older-input', 'return sameInput &&', 'return (sameInput || !sameInput) &&'),
    ('wait-past-deadline', 'nowMs - startedAtMs < budgetMs', 'nowMs - startedAtMs <= budgetMs'),
    ('probe-boundary-off-by-one', 'nowMs - suspendedSinceMs >= backoffMs', 'nowMs - suspendedSinceMs > backoffMs'),
    ('probe-underflow-guard-dropped', 'nowMs >= suspendedSinceMs && nowMs', 'nowMs'),
    ('staging-budget-ignores-source-frame', 'double budget = sourceFrameMs;', 'double budget = displayFrameMs + 0.0 * sourceFrameMs;'),
    ('staging-budget-service-floor-dropped', 'if (budget < 8.0) {\n        budget = 8.0;\n    }', '(void)budget;'),
    ('staging-budget-unknown-rate-refuses', 'return 16;', 'return 0;'),
    ('adaptive-budget-can-shrink', 'measured > frameBudget ? measured : frameBudget', 'measured'),
    ('adaptive-budget-ignores-its-ceiling', 'uint64_t ceiling = 2 * frameBudget;', 'uint64_t ceiling = frameBudget;'),

]
for name, before, after in enhancement_mutations:
    assert enhancement_header.count(before) == 1, name
    assert replay(header, enhancement_header.replace(before, after)) != 0, name + ' survived'
actual_mutations = [
    ('old-drawable-enters-new-session', 'generation != state->generation', 'generation > state->generation'),
    ('zero-time-counts-as-presented', 'if (time == 0.0)', 'if (time < 0.0)'),
    ('unbounded-sample-count', 'state->count < ML_ACTUAL_PRESENTATION_CAPACITY', 'state->count <= ML_ACTUAL_PRESENTATION_CAPACITY'),
    ('stale-fps-stays-visible', 'now - result.latestTime > 2.0', 'now - result.latestTime > 200.0'),
    ('callbacks-assumed-ordered', 'qsort(times, state->count, sizeof(double), MLActualPresentationCompare);', '(void)times;'),
    ('counts-a-submit-instead-of-present', 'state->presented++;', 'state->presented += 2;'),
    ('resume-includes-stale-history', 'time - state->latestTime > 2.0', 'time - state->latestTime > 200.0'),
    ('late-callback-revives-old-window', 'state->latestTime - time > 2.0', 'state->latestTime - time > 200.0'),
]
for name, before, after in actual_mutations:
    assert actual_header.count(before) == 1, name
    assert replay(header, enhancement_header, actual_header.replace(before,after)) != 0, name + ' survived'
source = (ROOT/'Limelight/Stream/VideoDecoderRenderer.m').read_text()
def section(start, end):
    return source[source.index(start):source.index(end,source.index(start))]
draw = section('- (void)drawInMTKView:', '- (void)start\n')
stage = section('- (BOOL)stageInterpolatedFrameFromPreviousSource:', '- (BOOL)presentationCadenceForInterpolationHold:')
callback = section('static CVReturn displayLinkCallback(CVDisplayLinkRef displayLink,\n', '- (void)stop\n')
decode = section('- (void)handleDecompressionOutput:', '- (BOOL)createDecompressionSession')
assert draw.index('MLPresentationNeedsDraw(') < draw.index('copyFrameUsingFrameProcessorIfNeeded:'), 'duplicate SR work'
assert 'MLPresentationNeedsDraw(' in callback and 'if (shouldRetryEnhancedFrame)' in callback, 'refresh retry disconnected'
assert stage.index('MLEnhancementMayPublish(') < stage.index('_pendingInterpolatedFrame = interpolatedFrame;'), 'stale publication'
assert '_currentFrame != sourceFrame' in stage, 'buffer identity guard missing'
fi_compute = section('- (CVImageBufferRef)copyInterpolatedFrameFromPreviousSource:', '// A slow VT task')
fi_teardown = section('- (void)teardownFrameInterpolationProcessor\n', '- (void)teardownHDRPresentationResources')
fi_expire = section('- (void)expireInterpolationStagingIfNeeded', '- (BOOL)stageInterpolatedFrameFromPreviousSource:')
assert 'processWithParameters:' not in decode and 'dispatch_async(_vtInterpolationQueue' in stage, 'FI still blocks decode'
assert '_frameInterpolationProcessor' not in fi_compute and '_currentFrame' not in fi_compute, 'FI reads mutable live state on worker'
assert 'sourceLifetime' in stage and 'previousLifetime' in stage and 'poolLifetime' in stage, 'FI snapshots lose lifetimes'
assert '_interpolationProcessInFlight ||' in stage and 'MLEnhancementShouldWait(' in stage, 'FI CPU queue is unbounded'
assert 'expireInterpolationStagingIfNeeded' in callback and 'expireInterpolationStagingIfNeeded' in draw, 'FI timeout cannot progress on refresh'
assert 'MLEnhancementShouldWait(' in fi_expire and '_interpolationStagingSequence = 0;' in fi_expire, 'FI staging can wait indefinitely'
assert 'dispatch_async(_vtInterpolationQueue' in fi_teardown and '_interpolationProcessInFlight = NO;' not in fi_teardown, 'FI stop races process or frees active slot'
assert '!queuedInterpolation && _interpolationStagingSequence == sourceSequence' in decode, 'decode immediately clears async staging'

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
assert 'report:enhancementProcessingPending' in draw and 'MLVideoEnhancementProcessingReport(enhancementSuspended)' in draw and 'enhancementSuspended = _enhancementSuspended;' in draw, 'CPU pressure/pause is mislabeled or disconnected from the circuit breaker'
assert 'framePresentationTimeStamp = _pendingInterpolatedPresentationTimeStamp;' in draw and 'outputTimeStamp:&interpolatedTimeStamp' in stage, 'midpoint timestamp is not carried with its output'
assert 'if (processedFrame != NULL)' in draw and 'if (resolvedEngine != MLActiveVideoEnhancementEngineVTLowLatencySuperResolution' in draw, 'VT is marked active merely from selection'
observation = section('- (void)recordActualDrawableTime:', '- (void)recordRenderedFrameSampleAtTimeMs:')
clear = section('- (void)clearCurrentFrame\n', '- (NSDictionary<NSString *, NSNumber *> *)actualPresentationMetrics')
assert 'MLActualPresentationRecord(' in observation and 'MLActualPresentationRead(' in observation, 'drawable observations bypass replayed policy'
assert 'MLActualPresentationReset(&_actualPresentationState)' in clear, 'old presentation callbacks survive stop'
assert draw.index('observationGeneration = _actualPresentationState.generation;') < draw.index('frame = CVBufferRetain(_currentFrame);'), 'generation is captured after its frame may have stopped'
assert draw.index('[drawable addPresentedHandler:') < draw.index('[commandBuffer presentDrawable:'), 'handler registered too late'
assert 'presentedDrawable.presentedTime' in draw and 'weakRenderer' in draw, 'missing actual timestamp or renderer retained by drawable'
actual_overlay = (ROOT/'Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m').read_text()
assert 'actualPresentationMetrics]' in actual_overlay and 'actualPresent[@"available"]' in actual_overlay, 'overlay uses submission counters or stale observations'
# Exercise the legacy cache mutation against both enclosing scopes. A moved draw
# must not make the battery silently lose the lifetime regression it guards.
spec = importlib.util.spec_from_file_location('presentation_battery', ROOT/'scripts/assertion-battery.py')
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)
for indent in ('    ', '        '):
    fixture = '\n'.join(indent + line[4:] for line in battery.CACHE_SNAPSHOT_BLOCK.splitlines())
    assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(fixture)
assert 'cacheSnapshot = NULL;' not in battery.draw_with_the_shared_pointer(source)
# Same-format preparation must preserve a paused session; changed input may recover.
fi_pool = section('- (BOOL)ensureFrameInterpolationOutputPoolForConfiguration:(VTLowLatencyFrameInterpolationConfiguration *)configuration\n                                         sourcePixelFormat:(OSType)sourcePixelFormat API_AVAILABLE(macos(26.0))\n{', '- (void)requestFrameInterpolationWarmupForStreamWidth:')
assert fi_pool.index('_frameInterpolationSourcePixelFormat == sourcePixelFormat') < fi_pool.index('_interpolationSuspended = NO;'), 'same source format resets the breaker every frame'
assert '_frameInterpolationSourcePixelFormat = sourcePixelFormat;' in fi_pool
assert 'if (!queuedInterpolation && _interpolationStagingSequence == sourceSequence)' in source, 'paused FI holds the source staging'
assert stage.index('prepareFrameInterpolationProcessorForSourceFrame:') < stage.index('if (_interpolationSuspended)'), 'new input configuration cannot reset the breaker'
# Extract the actual async/retirement methods, with a deterministic VT double.
# Native CV buffers/pool and dispatch queues stay real; this is lifecycle evidence,
# never evidence of VT quality, supported scale factors or on-screen smoothness.
native_toolchain = apple_toolchain.clang_and_sdk_or_none()
if native_toolchain is None:
    print('SKIP native async lifecycle harness: Apple toolchain unavailable')
else:
    native_clang, native_sdk = native_toolchain
    queue_methods = section('- (int)desiredPendingFramesForDisplayRefreshRate:', '- (BOOL)setupMetalRenderer {')
    assert draw.index('[self updateEnhancedQueueDepthIfNeeded]') < draw.index('dispatch_semaphore_t inflightSemaphore'), 'queue update races its own submission'
    assert 'setupMetalRenderer' not in callback, 'refresh callback asynchronously rebuilds presentation'
    assert 'DISPATCH_TIME_FOREVER' not in queue_methods, 'queue depth adjustment blocks UI'
    mode_start = source.index('typedef NS_ENUM(NSInteger, MLActiveVideoRendererMode)')
    mode_enum = source[mode_start:source.index('};', mode_start) + 2]
    clamp = section('static int MLClampInt(', 'static BOOL MLPixelFormatIsVideoRange(')
    constants = '\n'.join('enum { %s = %s };' % (name, re.search(name + r'\s*=\s*(\d+)', source).group(1))
                          for name in ('kMLEnhancedStartupPacingWindowMs', 'kMLEnhancedStartupPacingPresentThreshold'))
    def queue_replay(methods, expected, name):
        text = (ROOT/'scripts/fixtures/enhanced-queue-depth.m').read_text()
        for key, value in [('@@METHODS@@', methods), ('@@RENDERER_ENUM@@', mode_enum),
                           ('@@CLAMP@@', clamp), ('@@CONSTANTS@@', constants)]:
            text = text.replace(key, value)
        with tempfile.TemporaryDirectory(prefix='ml-queue-depth-') as d:
            p = Path(d)
            (p/'probe.m').write_text(text)
            built = subprocess.run([native_clang, '-isysroot', native_sdk, '-fobjc-arc', '-fblocks',
                '-Wall', '-Werror', '-framework', 'Foundation', '-I', str(ROOT/'Limelight/macOS'),
                str(p/'probe.m'), '-o', str(p/'probe')], capture_output=True, text=True)
            if built.returncode != 0:
                # The queue-depth probe never built, so no rule was replayed. That is the
                # harness having no answer, not the shipping shape failing a check.
                print('%s: the queue-depth probe (%s) does not compile:\n%s'
                      % (apple_toolchain.PROBE_BUILD_FAILED_MESSAGE, name, built.stderr.strip()[-700:]))
                raise SystemExit(1)
            ran = subprocess.run([str(p/'probe')], capture_output=True, text=True, timeout=10)
            assert (ran.returncode == 0) == expected, name + ': ' + ran.stdout + ran.stderr
            print(ran.stdout.strip() if expected else 'ok: queue replay rejects ' + name)
    queue_replay(queue_methods, True, 'shipping queue')
    for name, before, after in [
        ('replace-with-outstanding-GPU-work', 'if (!drained) return;', 'if (!drained) { /* unsafe */ }'),
        ('lose-partial-reservations', 'while (reserved > 0)', 'while (reserved > 1)'),
        ('vsync-floor-lost', 'target = MAX(target - 1, _timingEnableVsync ? 1 : 0);', 'target -= 1;'),
        ('compatibility-loses-depth', 'if (_timingCompatibilityMode) {\n        return 3;', 'if (_timingCompatibilityMode && false) {\n        return 3;'),
    ]:
        assert before in queue_methods, name
        queue_replay(queue_methods.replace(before, after, 1), False, name)
    enum_start = source.index('typedef NS_ENUM(NSInteger, MLActiveVideoEnhancementEngine)')
    enum_end = source.index('};', enum_start) + 2
    release_history = section('- (void)releasePreviousEnhancedFrames\n', '- (void)releaseFrameInterpolationFrames\n')
    def native_replay(methods, name, should_pass, template_override=None):
        rendered = template_override if template_override is not None else (ROOT/'scripts/fixtures/async-enhancement-lifecycle.m').read_text()
        rendered = rendered.replace('@@ENUM@@', source[enum_start:enum_end]).replace('@@METHODS@@', methods)
        rendered = '#define MLTestRunInline(block) ((block)())\n' + rendered
        with tempfile.TemporaryDirectory(prefix='ml-enhancement-lifecycle-') as d:
            p = Path(d)
            (p/'EnhancementProcessingPolicy.h').write_text(enhancement_header)
            (p/'probe.m').write_text(rendered)
            built = subprocess.run([native_clang, '-isysroot', native_sdk, '-fobjc-arc', '-fblocks', '-Wall', '-Werror',
                '-Wno-unused-function', '-framework', 'Foundation', '-framework', 'CoreVideo',
                '-framework', 'CoreMedia', str(p/'probe.m'), '-o', str(p/'probe')], capture_output=True, text=True)
            if built.returncode != 0:
                print('%s: the enhancement lifecycle probe (%s) does not compile:\n%s'
                      % (apple_toolchain.PROBE_BUILD_FAILED_MESSAGE, name, built.stderr.strip()[-700:]))
                raise SystemExit(1)
            ran = subprocess.run([str(p/'probe')], capture_output=True, text=True, timeout=30)
            assert 'is implemented in both' not in ran.stderr, name + ': runtime class collision: ' + ran.stderr
            if 'SKIP' in ran.stdout:
                print(ran.stdout.strip())
                return False
            assert (ran.returncode == 0) == should_pass, name + ': ' + ran.stdout + ran.stderr
            print(ran.stdout.strip() if should_pass else 'ok: native lifecycle rejects ' + name + ' (mutation compiled)')
            return True
    methods = release_history + teardown + processor
    if native_replay(methods, 'control', True):
        template = (ROOT/'scripts/fixtures/async-enhancement-lifecycle.m').read_text()
        native_replay(methods, 'SR-wrong-runtime-double', False, template.replace('#define VTFrameProcessor MLTestSRFrameProcessor', '#define VTFrameProcessor MLTestSRWrongFrameProcessor', 1))
        admission = 'MLEnhancementShouldWait(true, nowMs, LiGetMillis(), budgetMs);'
        assert processor.count(admission) == 2
        native_replay(methods.replace(admission, 'true;', 1), 'SR-starts-after-queue-deadline', False)
        publication = 'BOOL publish = eligible && MLEnhancementShouldWait(true, nowMs, LiGetMillis(), budgetMs);'
        assert processor.count(publication) == 1
        native_replay(methods.replace(publication, 'BOOL publish = eligible;'), 'SR-publishes-expired-output', False)
        native_replay(methods.replace('} else if (eligible) {', '} else if (eligible && processed) {', 1), 'SR-requeues-expired-source', False)
        expired = 'if ((isInterpolated ? _enhancementFailedInterpolatedSequence : _enhancementFailedSequence) == frameSequence) {'
        assert processor.count(expired) == 1
        native_replay(methods.replace(expired, 'if (_enhancementFailedSequence == frameSequence) {'), 'SR-failure-crosses-source-midpoint', False)
        native_replay(methods.replace('if (isInterpolated) self->_enhancementFailedInterpolatedSequence = frameSequence;', 'if (isInterpolated) self->_enhancementFailedSequence = frameSequence;'), 'SR-failure-loses-input-kind', False)
        start = methods.index(expired)
        end = methods.index('return NULL;', start)
        broken = methods[:start] + methods[start:end].replace('if (processingPending) *processingPending = YES;', 'if (processingPending) *processingPending = NO;') + methods[end:]
        native_replay(broken, 'SR-expiry-retires-breaker-history', False)


        native_replay(methods.replace('if (_enhancementSuspended)', 'if (_enhancementSuspended && false)', 1), 'ignore-session-breaker', False)
        native_replay(methods.replace('if (currentTask && processor == self->_frameProcessor &&', 'if (currentTask &&', 1).replace('generation == self->_enhancementProcessGeneration) {', 'generation <= self->_enhancementProcessGeneration) {', 1), 'retired-task-poisons-breaker', False)

        assert teardown.count('dispatch_async(_vtEnhancementQueue, ^{') == 1
        native_replay(release_history + teardown.replace('dispatch_async(_vtEnhancementQueue, ^{', 'MLTestRunInline(^{') + processor,
                      'end-session-during-process', False)
        assert processor.count('dispatch_async(_vtEnhancementQueue, ^{') == 1
        native_replay(release_history + teardown + processor.replace('dispatch_async(_vtEnhancementQueue, ^{', 'MLTestRunInline(^{'),
                      'VT-runs-on-the-draw-caller', False)
        assert processor.count('if (_enhancementProcessInFlight)') == 1
        native_replay(release_history + teardown + processor.replace('if (_enhancementProcessInFlight)', 'if (_enhancementProcessInFlight && _enhancementTaskSequence == UINT64_MAX)'),
                      'multiple-CPU-tasks-in-flight', False)
# FI uses shipping admission/completion/compute/retirement, not a second workflow.
if native_toolchain is not None:
    enums = []
    for name in ('MLActiveVideoFrameInterpolationEngine', 'MLVideoFrameInterpolationReport'):
        a = source.index('typedef NS_ENUM(NSInteger, ' + name + ')')
        enums.append(source[a:source.index('};', a)+2])
    fi_release = section('- (void)releaseFrameInterpolationFrames\n', '- (void)teardownEnhancementProcessor\n')
    def fi_native_replay(methods, name, expected, template_override=None):
        template = template_override if template_override is not None else (ROOT/'scripts/fixtures/async-interpolation-lifecycle.m').read_text()
        text = '#define MLTestRunInline(block) ((block)())\n' + template.replace('@@ENUMS@@', '\n'.join(enums)).replace('@@METHODS@@', methods)
        with tempfile.TemporaryDirectory(prefix='ml-fi-lifecycle-') as d:
            p=Path(d)
            (p/'EnhancementProcessingPolicy.h').write_text(enhancement_header)
            (p/'EnhancedPresentationPolicy.h').write_text(header)
            (p/'probe.m').write_text(text)
            built=subprocess.run([native_clang,'-isysroot',native_sdk,'-fobjc-arc','-fblocks','-Wall','-Werror','-Wimplicit-retain-self','-Wno-unused-function',
                '-framework','Foundation','-framework','CoreVideo','-framework','CoreMedia',str(p/'probe.m'),'-o',str(p/'probe')],capture_output=True,text=True)
            if built.returncode!=0:
                print('%s: the FI lifecycle probe (%s) does not compile:\n%s'
                      % (apple_toolchain.PROBE_BUILD_FAILED_MESSAGE, name, built.stderr.strip()[-700:]))
                raise SystemExit(1)
            ran=subprocess.run([str(p/'probe')],capture_output=True,text=True,timeout=30)
            assert 'is implemented in both' not in ran.stderr, name + ': runtime class collision: ' + ran.stderr
            assert (ran.returncode==0)==expected, name+': '+ran.stdout+ran.stderr
            print(ran.stdout.strip() if expected else 'ok: native FI rejects '+name+' (mutation compiled)')
    fi_methods=fi_release+fi_teardown+fi_compute+fi_expire+stage
    fi_native_replay(fi_methods,'control',True)
    template = (ROOT/'scripts/fixtures/async-interpolation-lifecycle.m').read_text()
    fi_native_replay(fi_methods, 'FI-wrong-runtime-double', False, template.replace('#define VTFrameProcessor MLTestFIFrameProcessor', '#define VTFrameProcessor MLTestFIWrongFrameProcessor', 1))
    fi_native_replay(fi_methods.replace('if (_interpolationSuspended)', 'if (_interpolationSuspended && false)', 1), 'FI-ignore-session-breaker', False)
    fi_native_replay(fi_methods.replace('if (runTask && processor == self->_frameInterpolationProcessor &&', 'if (runTask &&', 1).replace('generation == self->_interpolationProcessGeneration) {', 'generation <= self->_interpolationProcessGeneration) {', 1), 'FI-retired-task-poisons-breaker', False)

    fi_native_replay(fi_methods.replace('dispatch_async(_vtInterpolationQueue, ^{','MLTestRunInline(^{',1),'FI-end-session-during-process',False)
    fi_native_replay(fi_methods.replace('_interpolationProcessInFlight ||','(_interpolationProcessInFlight && false) ||',1),'FI-overlapping-tasks',False)
    fi_native_replay(fi_methods.replace('!MLEnhancementShouldWait(true, _interpolationStagingStartedAtMs,','!MLEnhancementShouldWait(true, LiGetMillis(),',1),'FI-unbounded-staging',False)
# Hardware is opt-in, but its report contract is verified on every normal gate run.
spec=importlib.util.spec_from_file_location('vt_hardware_probe', ROOT/'scripts/vt-enhancement-probe.py')
vt_probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(vt_probe)
assert vt_probe.self_test()==0
print(f'ok: presentation + asynchronous enhancement replay, {len(mutations)+len(enhancement_mutations)+len(actual_mutations)} policy mutations caught, renderer wiring checks, 3 cache anchors')
