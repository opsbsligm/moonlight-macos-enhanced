//
//  CoreHIDMouseDriver.swift
//  Moonlight for macOS
//

import CoreHID
import Foundation
import IOKit.hidsystem

@objc protocol CoreHIDMouseDriverDelegate: AnyObject {
  @objc optional func coreHIDMouseDriver(
    _ driver: CoreHIDMouseDriver, didObserveRawDeltaX deltaX: Double, deltaY: Double)
  func coreHIDMouseDriver(
    _ driver: CoreHIDMouseDriver, didReceiveDeltaX deltaX: Double, deltaY: Double)
  func coreHIDMouseDriver(
    _ driver: CoreHIDMouseDriver, didFailWithReason reason: String, messageKey: String)
}

@objcMembers
final class CoreHIDMouseDriver: NSObject {
  private enum Failure {
    static let unsupportedOSReason = "unsupported-os"
    static let permissionDeniedReason = "permission-denied"
    static let managerErrorReason = "manager-error"
    static let clientErrorReason = "client-error"

    static let unsupportedOSMessageKey = "CoreHID Mouse requires macOS 15 or later."
    static let permissionDeniedMessageKey =
      "CoreHID Mouse access denied. Allow Input Monitoring in System Settings."
    static let runtimeErrorMessageKey = "CoreHID Mouse input failed."
  }

  private enum ReportRate {
    static let unlimited = 0
    static let defaultMaximum = 1000
    static let maxRate = 8000
  }

  weak var delegate: CoreHIDMouseDriverDelegate?
  var maximumReportRate = ReportRate.defaultMaximum
  var requestsListenAccessIfNeeded = false

  private let stateLock = NSLock()
  private var managerTask: Task<Void, Never>?
  private var pendingDeltaX = 0.0
  private var pendingDeltaY = 0.0
  private var lastDispatchTimestamp: TimeInterval = 0
  private var hasPostedFailure = false
  private var lastMovementEventTimestamp: TimeInterval = 0
  private var flushTask: Task<Void, Never>?
  private var stateGeneration: UInt64 = 0
  private var flushToken: UInt64 = 0

  var secondsSinceLastMovementEvent: TimeInterval {
    stateLock.lock()
    let timestamp = lastMovementEventTimestamp
    stateLock.unlock()

    guard timestamp > 0 else {
      return .greatestFiniteMagnitude
    }

    return max(0, ProcessInfo.processInfo.systemUptime - timestamp)
  }

  func start() {
    stop()

    guard #available(macOS 15.0, *) else {
      postFailureIfNeeded(
        reason: Failure.unsupportedOSReason,
        messageKey: Failure.unsupportedOSMessageKey
      )
      return
    }

    let permissionManager = InputMonitoringPermissionManager.sharedManager
    if requestsListenAccessIfNeeded {
      let granted = permissionManager.requestAuthorizationIfNeeded(
        interactive: true
      )
      guard granted else {
        postFailureIfNeeded(
          reason: Failure.permissionDeniedReason,
          messageKey: Failure.permissionDeniedMessageKey
        )
        return
      }
    } else {
      permissionManager.requestAuthorizationIfNeeded(interactive: false)
    }

    stateLock.lock()
    let generation = stateGeneration
    managerTask = Task { [weak self] in
      guard let self else { return }
      await self.monitorManager(generation: generation)
    }
    stateLock.unlock()
  }

  func stop() {
    stateLock.lock()
    stateGeneration &+= 1
    flushToken &+= 1
    managerTask?.cancel()
    managerTask = nil
    flushTask?.cancel()
    flushTask = nil
    pendingDeltaX = 0
    pendingDeltaY = 0
    lastDispatchTimestamp = 0
    hasPostedFailure = false
    lastMovementEventTimestamp = 0
    stateLock.unlock()
  }

  deinit {
    stop()
  }

  @available(macOS 15.0, *)
  private func monitorManager(generation: UInt64) async {
    let manager = HIDDeviceManager()
    let criteria = HIDDeviceManager.DeviceMatchingCriteria(primaryUsage: .genericDesktop(.mouse))

    do {
      let stream = await manager.monitorNotifications(matchingCriteria: [criteria])
      var clientTasks: [HIDDeviceClient.DeviceReference: Task<Void, Never>] = [:]

      defer {
        for task in clientTasks.values {
          task.cancel()
        }
      }

      for try await notification in stream {
        if Task.isCancelled {
          break
        }

        switch notification {
        case .deviceMatched(let deviceReference):
          guard clientTasks[deviceReference] == nil,
            let client = HIDDeviceClient(deviceReference: deviceReference)
          else {
            continue
          }

          guard await shouldMonitorDevice(client) else {
            continue
          }

          clientTasks[deviceReference] = Task { [weak self] in
            guard let self else { return }
            await self.monitorClient(client, generation: generation)
          }

        case .deviceRemoved(let deviceReference):
          clientTasks[deviceReference]?.cancel()
          clientTasks.removeValue(forKey: deviceReference)

        @unknown default:
          continue
        }
      }
    } catch {
      if !Task.isCancelled {
        postFailureIfNeeded(
          reason: Failure.managerErrorReason,
          messageKey: Failure.runtimeErrorMessageKey,
          generation: generation
        )
      }
    }
  }

  @available(macOS 15.0, *)
  private func monitorClient(_ client: HIDDeviceClient, generation: UInt64) async {
    let allElements = await client.elements
    let movementElements = allElements.filter { element in
      isMovementUsage(element.usage)
    }
    guard !movementElements.isEmpty else {
      return
    }

    let reportIDs: [ClosedRange<HIDReportID>] = []

    do {
      let stream = await client.monitorNotifications(
        reportIDsToMonitor: reportIDs,
        elementsToMonitor: movementElements
      )

      for try await notification in stream {
        if Task.isCancelled {
          break
        }

        switch notification {
        case .elementUpdates(let values):
          var deltaX = 0.0
          var deltaY = 0.0

          for value in values {
            switch value.element.usage {
            case .genericDesktop(.x):
              deltaX += valueAsDelta(value)
            case .genericDesktop(.y):
              deltaY += valueAsDelta(value)
            default:
              continue
            }
          }

          if deltaX != 0 || deltaY != 0 {
            reportDelta(deltaX: deltaX, deltaY: deltaY, generation: generation)
          }

        case .deviceRemoved:
          return

        case .inputReport, .deviceSeized, .deviceUnseized:
          continue

        @unknown default:
          continue
        }
      }
    } catch {
      if !Task.isCancelled {
        postFailureIfNeeded(
          reason: Failure.clientErrorReason,
          messageKey: Failure.runtimeErrorMessageKey,
          generation: generation
        )
      }
    }
  }

  @available(macOS 15.0, *)
  private func shouldMonitorDevice(_ client: HIDDeviceClient) async -> Bool {
    if await client.isBuiltIn {
      return false
    }

    let product =
      await client.product?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
    if product.contains("trackpad") {
      return false
    }

    return true
  }

  @available(macOS 15.0, *)
  private func valueAsDelta(_ value: HIDElement.Value) -> Double {
    if let logicalValue = value.logicalValue(asTypeTruncatingIfNeeded: Int64.self) {
      return Double(logicalValue)
    }
    return Double(value.integerValue(asTypeTruncatingIfNeeded: Int64.self))
  }

  @available(macOS 15.0, *)
  private func isMovementUsage(_ usage: HIDUsage) -> Bool {
    if case .genericDesktop(.x) = usage {
      return true
    }
    if case .genericDesktop(.y) = usage {
      return true
    }
    return false
  }

  private func reportDelta(deltaX: Double, deltaY: Double, generation: UInt64) {
    guard deltaX.isFinite, deltaY.isFinite else { return }
    let maxRate = Self.normalizedMaximumReportRate(maximumReportRate)
    var deltaToDispatch: (x: Double, y: Double)?

    stateLock.lock()
    guard generation == stateGeneration else {
      stateLock.unlock()
      return
    }
    pendingDeltaX += deltaX
    pendingDeltaY += deltaY
    let now = ProcessInfo.processInfo.systemUptime
    let minimumInterval = maxRate == ReportRate.unlimited ? 0 : 1.0 / Double(maxRate)
    let elapsed = lastDispatchTimestamp == 0 ? TimeInterval.greatestFiniteMagnitude : now - lastDispatchTimestamp
    if elapsed >= minimumInterval {
      deltaToDispatch = (pendingDeltaX, pendingDeltaY)
      pendingDeltaX = 0
      pendingDeltaY = 0
      lastDispatchTimestamp = now
      lastMovementEventTimestamp = now
      flushToken &+= 1
      flushTask?.cancel()
      flushTask = nil
    } else if flushTask == nil {
      // Publish the task while holding the same lock that its callback takes.
      // Otherwise a short timer can finish before flushTask is assigned and
      // leave a completed task blocking every future flush.
      schedulePendingFlushLocked(after: max(0, minimumInterval - elapsed), generation: generation)
    }
    stateLock.unlock()

    delegate?.coreHIDMouseDriver?(self, didObserveRawDeltaX: deltaX, deltaY: deltaY)
    if let deltaToDispatch, isCurrentGeneration(generation) {
      delegate?.coreHIDMouseDriver(self, didReceiveDeltaX: deltaToDispatch.x, deltaY: deltaToDispatch.y)
    }
  }

  // Called with stateLock held.
  private func schedulePendingFlushLocked(after delaySeconds: TimeInterval, generation: UInt64) {
    flushToken &+= 1
    let token = flushToken
    let delayNanoseconds = UInt64(max(0, delaySeconds) * 1_000_000_000.0)
    flushTask = Task { [weak self] in
      do {
        try await Task.sleep(nanoseconds: delayNanoseconds)
      } catch {
        return
      }
      guard !Task.isCancelled else { return }
      self?.flushPendingDeltaIfNeeded(generation: generation, token: token)
    }
  }

  private func flushPendingDeltaIfNeeded(generation: UInt64, token: UInt64) {
    var deltaToDispatch: (x: Double, y: Double)?
    stateLock.lock()
    // A cancelled callback may already have awakened. It cannot clear a newer
    // task or drain deltas from a later start() generation.
    guard generation == stateGeneration, token == flushToken else {
      stateLock.unlock()
      return
    }
    flushTask = nil
    if pendingDeltaX != 0 || pendingDeltaY != 0 {
      deltaToDispatch = (pendingDeltaX, pendingDeltaY)
      pendingDeltaX = 0
      pendingDeltaY = 0
      lastDispatchTimestamp = ProcessInfo.processInfo.systemUptime
      lastMovementEventTimestamp = lastDispatchTimestamp
    }
    stateLock.unlock()

    if let deltaToDispatch, isCurrentGeneration(generation) {
      delegate?.coreHIDMouseDriver(self, didReceiveDeltaX: deltaToDispatch.x, deltaY: deltaToDispatch.y)
    }
  }

  private func isCurrentGeneration(_ generation: UInt64) -> Bool {
    stateLock.lock()
    defer { stateLock.unlock() }
    return generation == stateGeneration
  }

  private static func normalizedMaximumReportRate(_ value: Int) -> Int {
    let clamped = max(ReportRate.unlimited, min(value, ReportRate.maxRate))
    if clamped == ReportRate.unlimited {
      return ReportRate.unlimited
    }
    return max(1, clamped)
  }

  private func postFailureIfNeeded(reason: String, messageKey: String, generation: UInt64? = nil) {
    stateLock.lock()
    if hasPostedFailure || (generation != nil && generation != stateGeneration) {
      stateLock.unlock()
      return
    }
    hasPostedFailure = true
    let failureGeneration = stateGeneration
    stateLock.unlock()

    DispatchQueue.main.async { [weak self] in
      guard let self, self.isCurrentGeneration(failureGeneration) else { return }
      self.delegate?.coreHIDMouseDriver(self, didFailWithReason: reason, messageKey: messageKey)
    }
  }
}
