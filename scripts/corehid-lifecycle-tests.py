#!/usr/bin/env python3
"""Run CoreHID's shipping cancellation, generation and timer code without hardware.

The timer methods are extracted from the Swift driver. A deliberately stale
callback is invoked after replacement/restart so correctness does not depend on
winning a scheduler race. Real cancelled tasks and delayed tail delivery are
also exercised.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from apple_toolchain import swiftc_and_sdk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Limelight/Input/CoreHIDMouseDriver.swift'

PREFIX = r'''
import Foundation
protocol CoreHIDMouseDriverDelegate: AnyObject {
  func coreHIDMouseDriver(_ driver: CoreHIDMouseDriver, didObserveRawDeltaX: Double, deltaY: Double)
  func coreHIDMouseDriver(_ driver: CoreHIDMouseDriver, didReceiveDeltaX: Double, deltaY: Double)
}
final class CoreHIDMouseDriver: NSObject {
__MEMBERS__
__STOP__
__METHODS__
}
final class Recorder: CoreHIDMouseDriverDelegate {
  private let lock = NSLock()
  private var deltas: [Double] = []
  func coreHIDMouseDriver(_ driver: CoreHIDMouseDriver, didObserveRawDeltaX: Double, deltaY: Double) {}
  func coreHIDMouseDriver(_ driver: CoreHIDMouseDriver, didReceiveDeltaX x: Double, deltaY: Double) {
    lock.lock(); deltas.append(x); lock.unlock()
  }
  var sum: Double { lock.lock(); defer { lock.unlock() }; return deltas.reduce(0, +) }
}
extension CoreHIDMouseDriver {
  func reportForTest(_ delta: Double) {
    stateLock.lock(); let generation = stateGeneration; stateLock.unlock()
    reportDelta(deltaX: delta, deltaY: 0, generation: generation)
  }
  func cancelledTimerPreservesPending() -> Bool {
    stop()
    stateLock.lock()
    pendingDeltaX = 7
    schedulePendingFlushLocked(after: 1, generation: stateGeneration)
    flushTask?.cancel()
    stateLock.unlock()
    Thread.sleep(forTimeInterval: 0.05)
    stateLock.lock(); defer { stateLock.unlock() }
    return pendingDeltaX == 7
  }
  func staleTimerCannotClearReplacement() -> Bool {
    stop()
    stateLock.lock()
    let generation = stateGeneration
    pendingDeltaX = 9
    schedulePendingFlushLocked(after: 1, generation: generation)
    let oldToken = flushToken
    flushTask?.cancel()
    flushTask = nil
    schedulePendingFlushLocked(after: 1, generation: generation)
    stateLock.unlock()
    // Models a callback that had passed its cancellation check before the
    // replacement acquired the state lock.
    flushPendingDeltaIfNeeded(generation: generation, token: oldToken)
    stateLock.lock(); defer { stateLock.unlock() }
    return pendingDeltaX == 9 && flushTask != nil
  }
  func previousSessionCannotDrainNewSession() -> Bool {
    stop()
    stateLock.lock(); let oldGeneration = stateGeneration; stateLock.unlock()
    stop()
    stateLock.lock()
    pendingDeltaX = 11
    schedulePendingFlushLocked(after: 1, generation: stateGeneration)
    let newToken = flushToken
    stateLock.unlock()
    flushPendingDeltaIfNeeded(generation: oldGeneration, token: newToken)
    stateLock.lock(); defer { stateLock.unlock() }
    return pendingDeltaX == 11 && flushTask != nil
  }
  func previousClientCannotReportIntoNewSession() -> Bool {
    stop()
    stateLock.lock(); let oldGeneration = stateGeneration; stateLock.unlock()
    stop()
    reportDelta(deltaX: 13, deltaY: 0, generation: oldGeneration)
    stateLock.lock(); defer { stateLock.unlock() }
    return pendingDeltaX == 0 && lastMovementEventTimestamp == 0
  }
  var timerCleared: Bool {
    stateLock.lock(); defer { stateLock.unlock() }
    return flushTask == nil && pendingDeltaX == 0
  }
}
var failures = 0
func check(_ result: Bool, _ message: String) {
  print("\(result ? "PASS" : "FAIL") \(message)")
  if !result { failures += 1 }
}
let driver = CoreHIDMouseDriver()
let recorder = Recorder()
driver.delegate = recorder
check(driver.cancelledTimerPreservesPending(), "cancelled sleep never drains pending motion")
check(driver.staleTimerCannotClearReplacement(), "old timer cannot clear replacement or steal its deltas")
check(driver.previousSessionCannotDrainNewSession(), "old session timer cannot drain new session")
check(driver.previousClientCannotReportIntoNewSession(), "late device client cannot publish across restart")
driver.stop()
let previousSum = recorder.sum
driver.maximumReportRate = 50
driver.reportForTest(1)
driver.reportForTest(2)
Thread.sleep(forTimeInterval: 0.08)
check(recorder.sum - previousSum == 3 && driver.timerCleared, "real delayed timer delivers final motion exactly once")
driver.stop()
print("\(failures) failure(s)")
exit(failures == 0 ? 0 : 1)
'''

def function(source, anchor):
    start = source.index(anchor)
    opening = source.index('{', start)
    depth = 1
    cursor = opening + 1
    while depth:
        if source[cursor] == '{': depth += 1
        if source[cursor] == '}': depth -= 1
        cursor += 1
    return source[start:cursor]

def run(negative=False):
    source = SOURCE.read_text()
    enum = function(source, '  private enum ReportRate {')
    start = source.index('  weak var delegate:')
    end = source.index('  var secondsSinceLastMovementEvent:', start)
    members = enum + '\n' + source[start:end]
    methods = source[source.index('  private func reportDelta('):source.index('  private func postFailureIfNeeded(')]
    methods = methods.replace('coreHIDMouseDriver?(', 'coreHIDMouseDriver(')
    if negative:
        gate = '''    guard generation == stateGeneration, token == flushToken else {
      stateLock.unlock()
      return
    }
'''
        assert gate in methods
        methods = methods.replace(gate, '')
    code = PREFIX.replace('__MEMBERS__', members).replace('__STOP__', function(source, '  func stop() {')).replace('__METHODS__', methods)
    pair = swiftc_and_sdk('CoreHID lifecycle regression')
    if pair is None:
        raise SystemExit('Swift compiler and macOS SDK are required')
    swiftc, sdk = pair
    with tempfile.TemporaryDirectory(prefix='moonlight-corehid-lifecycle-') as directory:
        probe = Path(directory) / 'probe.swift'
        executable = Path(directory) / 'probe'
        probe.write_text(code)
        subprocess.run([swiftc, '-sdk', sdk, '-swift-version', '5', str(probe), '-o', str(executable)], check=True)
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if negative:
            if result.returncode == 0:
                raise SystemExit('FAIL missing token/generation guard was not detected')
            print('PASS negative control detects stale timer execution')
        elif result.returncode:
            raise SystemExit(result.returncode)

if __name__ == '__main__':
    run('--self-test' in sys.argv)
