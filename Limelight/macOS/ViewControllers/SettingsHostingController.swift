//
//  SettingsHostingController.swift
//  Moonlight for macOS
//
//  Created by Michael Kenny on 15/1/2024.
//  Copyright © 2024 Moonlight Game Streaming Project. All rights reserved.
//

import Cocoa
import AVFoundation
import Combine
import SwiftUI

class SettingsHostingController<RootView: View>: NSWindowController, NSWindowDelegate {
  // Inline macOS 26 Liquid Glass window configuration; avoids the need
  // to reference an external LiquidGlassWindowController type that may
  // not be in the same Swift frontend compilation batch.
  private var languageObserver: Any?

  convenience init(rootView: RootView) {
    let title = LanguageManager.shared.localize("Settings")
    let hosting = NSHostingController(rootView: rootView)

    let window = NSWindow(contentViewController: hosting)
    // ── Liquid Glass window chrome (macOS 26) ────────────────────────
    // fullSizeContentView: 使内容视图延伸到标题栏下方,让 Liquid Glass
    //                     标题栏与下方内容视觉上连续,不再有"分隔条"
    // titlebarAppearsTransparent = true:
    //                     macOS 26 标题栏用 Liquid Glass 玻璃材质,
    //                     必须 transparent 才能让背景内容透出
    // titleVisibility = .hidden: 隐藏"设置"标题文字,标题栏只留红黄绿
    //                     控制按钮 + Liquid Glass 玻璃条,与下方 Tab bar 一体
    window.styleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
    window.collectionBehavior = [.fullScreenNone, .participatesInCycle]
    window.tabbingMode = .disallowed
    window.minSize = NSSize(width: 640, height: 520)
    window.title = title
    window.titleVisibility = .hidden
    window.titlebarAppearsTransparent = true
    window.isMovableByWindowBackground = true
    window.isMovable = true

    self.init(window: window)
    window.delegate = self

    // Bind the content view to a clear, vibrancy-friendly canvas so the
    // glass material cards render against a translucent backdrop.
    window.contentView?.wantsLayer = true
    window.contentView?.layer?.backgroundColor = .clear
    window.isOpaque = false
    window.hasShadow = true
    window.backgroundColor = .clear

    languageObserver = NotificationCenter.default.addObserver(
      forName: .init("LanguageChanged"), object: nil, queue: .main
    ) { [weak window, title] _ in
      window?.title = title
    }
  }

  deinit {
    if let languageObserver { NotificationCenter.default.removeObserver(languageObserver) }
  }

  func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
    let minSize = sender.minSize
    return NSSize(
      width: max(frameSize.width, minSize.width),
      height: max(frameSize.height, minSize.height)
    )
  }
}

private enum WelcomePermissionsState {
  static let defaultsKey = "welcome.permissions.shown.v1"

  static func markShown() {
    UserDefaults.standard.set(true, forKey: defaultsKey)
  }

  static func shouldShowOnLaunch() -> Bool {
    guard !UserDefaults.standard.bool(forKey: defaultsKey) else {
      return false
    }

    let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    let inputState = InputMonitoringPermissionManager.sharedManager.authorizationState
    let awdlState = AwdlHelperManager.sharedManager.authorizationState
    let needsMic = micStatus != .authorized
    let needsInput = inputState != .unsupported &&
      inputState != .granted &&
      inputState != .grantedNeedsReentry
    let needsAwdl = awdlState == .notDetermined || awdlState == .failed
    return needsMic || needsInput || needsAwdl
  }
}

private struct WelcomePermissionsView: View {
  @ObservedObject private var languageManager = LanguageManager.shared
  @ObservedObject private var microphoneManager = MicrophoneManager.shared
  @ObservedObject private var inputMonitoringManager = InputMonitoringPermissionManager.sharedManager
  @ObservedObject private var awdlManager = AwdlHelperManager.sharedManager
  let onContinue: () -> Void

  private var microphoneStatus: AVAuthorizationStatus {
    microphoneManager.permissionStatus
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      HStack(alignment: .top, spacing: 16) {
        Image(nsImage: NSApp.applicationIconImage)
          .resizable()
          .interpolation(.high)
          .frame(width: 72, height: 72)
          .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

        VStack(alignment: .leading, spacing: 8) {
          Text(languageManager.localize("Welcome to Moonlight macOS Enhanced"))
            .font(.system(size: 28, weight: .semibold, design: .rounded))
          Text(languageManager.localize("Welcome Permissions Subtitle"))
            .foregroundColor(.secondary)

          Link(languageManager.localize("GitHub Repository"), destination: githubURL)
            .font(.callout.weight(.medium))
        }
      }

      GroupBox {
        VStack(alignment: .leading, spacing: 16) {
          if inputMonitoringManager.authorizationState != .unsupported {
            permissionRow(
              title: "Input Monitoring",
              subtitle: "Input Monitoring detail",
              stateLabel: inputStatusText,
              isGranted: inputMonitoringManager.isGranted,
              supplementalMessageKey: inputMonitoringManager.supplementalStatusMessageKey,
              actionTitle: inputActionTitle,
              action: inputAction
            )
          }

          permissionRow(
            title: "AWDL Stability Helper",
            subtitle: "Welcome AWDL detail",
            stateLabel: awdlStatusText,
            isGranted: awdlGrantedState,
            actionTitle: awdlActionTitle,
            action: awdlAction
          )

          permissionRow(
            title: "Microphone",
            subtitle: "Microphone Permission detail",
            stateLabel: microphoneStatusText,
            isGranted: microphoneStatus == .authorized,
            actionTitle: microphoneActionTitle,
            action: microphoneAction
          )
        }
        .padding(.vertical, 8)
      }

      HStack {
        Spacer()
        Button(languageManager.localize("Continue")) {
          onContinue()
        }
        .keyboardShortcut(.defaultAction)
      }
    }
    .padding(24)
    .frame(width: 560)
    .onAppear {
      microphoneManager.refreshPermissionStatus()
      inputMonitoringManager.refreshAuthorizationStatus()
      awdlManager.refreshAuthorizationStatus()
    }
  }

  private var githubURL: URL {
    URL(string: "https://github.com/skyhua0224/moonlight-macos-enhanced")!
  }

  @ViewBuilder
  private func permissionRow(
    title: String,
    subtitle: String,
    stateLabel: String,
    isGranted: Bool,
    supplementalMessageKey: String? = nil,
    actionTitle: String?,
    action: (() -> Void)?
  ) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(alignment: .center, spacing: 12) {
        VStack(alignment: .leading, spacing: 4) {
          Text(languageManager.localize(title))
            .font(.headline)
          Text(languageManager.localize(subtitle))
            .font(.footnote)
            .foregroundColor(.secondary)
        }

        Spacer(minLength: 12)

        Label(
          languageManager.localize(stateLabel),
          systemImage: isGranted ? "checkmark.circle.fill" : "minus.circle"
        )
        .foregroundColor(isGranted ? .green : .secondary)
        .font(.callout)

        if let actionTitle, let action {
          Button(languageManager.localize(actionTitle)) {
            action()
          }
          .controlSize(.small)
        }
      }

      if let supplementalMessageKey {
        Text(languageManager.localize(supplementalMessageKey))
          .font(.footnote)
          .foregroundColor(.secondary)
      }
    }
  }

  private var inputStatusText: String {
    inputMonitoringManager.displayStatusLabelKey
  }

  private var inputActionTitle: String? {
    inputMonitoringManager.primaryActionTitleKey
  }

  private func inputAction() {
    switch inputMonitoringManager.primaryActionTitleKey {
    case "Request":
      inputMonitoringManager.requestAuthorization()
    case "Open Settings":
      inputMonitoringManager.openSystemPreferences()
    default:
      break
    }
  }

  private var microphoneStatusText: String {
    switch microphoneStatus {
    case .authorized:
      return "Granted"
    case .denied, .restricted:
      return "Denied"
    case .notDetermined:
      return "Not Granted"
    @unknown default:
      return "Not Granted"
    }
  }

  private var microphoneActionTitle: String? {
    switch microphoneStatus {
    case .authorized:
      return nil
    case .denied, .restricted:
      return "Open Settings"
    case .notDetermined:
      return "Request"
    @unknown default:
      return "Request"
    }
  }

  private func microphoneAction() {
    switch microphoneStatus {
    case .denied, .restricted:
      microphoneManager.openSystemPreferences()
    case .notDetermined:
      microphoneManager.requestPermission()
    case .authorized:
      break
    @unknown default:
      microphoneManager.requestPermission()
    }
  }

  private var awdlStatusText: String {
    switch awdlManager.helperInstallState {
    case .installed:
      return "Installed"
    case .notReady:
      return "Not Ready"
    case .adminPromptOnly:
      return "Admin Prompt Only"
    case .unavailable:
      return "Unavailable"
    case .unknown:
      return "Checking"
    @unknown default:
      return "Checking"
    }
  }

  private var awdlActionTitle: String? {
    if awdlManager.supportsPersistentHelperInstallation,
       awdlManager.helperInstallState != .installed
    {
      return "Install Persistent Helper"
    }

    switch awdlManager.authorizationState {
    case .ready, .unavailable:
      return nil
    case .failed, .notDetermined:
      return "Request"
    @unknown default:
      return "Request"
    }
  }

  private func awdlAction() {
    if awdlManager.supportsPersistentHelperInstallation,
       awdlManager.helperInstallState != .installed
    {
      awdlManager.installPersistentHelper()
    } else {
      awdlManager.requestAuthorization()
    }
  }

  private var awdlGrantedState: Bool {
    awdlManager.helperInstallState == .installed
  }
}

final class WelcomePermissionsHostingController: NSWindowController, NSWindowDelegate {
  convenience init() {
    let window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 520, height: 320),
      styleMask: [.titled, .closable, .miniaturizable],
      backing: .buffered,
      defer: false
    )
    let hostingController = NSHostingController(
      rootView: WelcomePermissionsView {
        if let sheetParent = window.sheetParent {
          sheetParent.endSheet(window, returnCode: .OK)
        } else {
          WelcomePermissionsState.markShown()
          window.performClose(nil)
        }
      }
    )
    window.contentViewController = hostingController
    window.styleMask = [.titled, .closable, .miniaturizable]
    window.collectionBehavior = [.fullScreenNone]
    window.tabbingMode = .disallowed
    window.title = LanguageManager.shared.localize("Permissions")
    window.isReleasedWhenClosed = false

    self.init(window: window)
    window.delegate = self
  }

  func windowShouldClose(_ sender: NSWindow) -> Bool {
    if let sheetParent = sender.sheetParent {
      sheetParent.endSheet(sender, returnCode: .cancel)
      return false
    }
    return true
  }

  func windowWillClose(_ notification: Notification) {
    WelcomePermissionsState.markShown()
  }
}

@objc class SettingsWindowObjCBridge: NSView {
  @objc class func makeSettingsWindow(hostId: String?) -> NSWindowController {
    // Liquid Glass redesign (macOS 26) replaces the legacy sidebar-based
    // SettingsView with a horizontal glass tab bar layout.
    let settingsView = LiquidGlassSettingsView(hostId: hostId)
    return SettingsHostingController(rootView: settingsView)
  }

  @objc class func syncSelectedProfile(hostId: String?) {
    let resolvedHostId: String
    if let hostId, !hostId.isEmpty {
      resolvedHostId = hostId
    } else {
      resolvedHostId = SettingsModel.globalHostId
    }

    UserDefaults.standard.set(resolvedHostId, forKey: "selectedSettingsProfile")
    NotificationCenter.default.post(
      name: Notification.Name("MoonlightSelectedSettingsProfileChanged"),
      object: nil,
      userInfo: ["hostId": resolvedHostId]
    )
  }
}

@objc class WelcomePermissionsWindowObjCBridge: NSView {
  @objc class func shouldShowWelcomeWindow() -> Bool {
    WelcomePermissionsState.shouldShowOnLaunch()
  }

  @objc class func markWelcomeWindowShown() {
    WelcomePermissionsState.markShown()
  }

  @objc class func makeWelcomeWindow() -> NSWindowController {
    WelcomePermissionsHostingController()
  }
}
