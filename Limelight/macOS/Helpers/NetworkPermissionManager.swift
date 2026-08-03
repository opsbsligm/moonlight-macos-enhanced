//
//  NetworkPermissionManager.swift
//  Moonlight for macOS
//
//  Created by Moonlight Team on 2026.
//  Copyright © 2026 Moonlight Game Streaming Project. All rights reserved.
//

import AppKit
import Foundation

@MainActor
@objc final class NetworkPermissionManager: NSObject, ObservableObject {
    static let shared = NetworkPermissionManager()

    @Published var networkPermissionStatus: NetworkPermissionStatus = .unknown
    @Published var hasAttemptedRepairThisSession = false

    private let bundleID = Bundle.main.bundleIdentifier ?? "std.skyhua.MoonlightMac2"

    enum NetworkPermissionStatus {
        case unknown
        case gatekeeperBlocked
        case quarantinePresent
        case tccDenied
        case ready
    }

    private init() {}

    @objc(performStartupRepairOnMainThread)
    class func performStartupRepairOnMainThread() {
        Task { @MainActor in
            shared.performStartupRepair()
        }
    }

    func performStartupRepair() {
        let appPath = Bundle.main.bundlePath

        removeQuarantineIfNeeded(appPath: appPath)
        checkGatekeeper(appPath: appPath)
        checkNetworkPermission()

        hasAttemptedRepairThisSession = true
    }

    private func removeQuarantineIfNeeded(appPath: String) {
        let task = Process()
        task.launchPath = "/usr/bin/xattr"
        task.arguments = ["-d", "com.apple.quarantine", appPath]
        task.qualityOfService = .utility
        do {
            try task.run()
            task.waitUntilExit()
            Log(LOG_I, "[NetworkPerm] Quarantine attribute removed (exit: \(task.terminationStatus))")
        } catch {
            Log(LOG_W, "[NetworkPerm] Failed to remove quarantine: \(error.localizedDescription)")
        }
    }

    private func checkGatekeeper(appPath: String) {
        let task = Process()
        task.launchPath = "/usr/sbin/spctl"
        task.arguments = ["--assess", "--verbose=4", appPath]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        task.qualityOfService = .utility

        do {
            try task.run()
            task.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""

            if task.terminationStatus == 0 {
                Log(LOG_I, "[NetworkPerm] Gatekeeper: accepted")
            } else {
                Log(LOG_W, "[NetworkPerm] Gatekeeper: blocked - \(output)")
                DispatchQueue.main.async { [weak self] in
                    self?.networkPermissionStatus = .gatekeeperBlocked
                    self?.showGatekeeperHelpDialog(output: output)
                }
            }
        } catch {
            Log(LOG_W, "[NetworkPerm] Gatekeeper check failed: \(error.localizedDescription)")
        }
    }

    private func checkNetworkPermission() {
        // NOTE: tccutil reset LocalNetwork has been intentionally removed.
        // Resetting the TCC database for the app on every startup is a destructive
        // violation of the user's privacy state and also triggers the macOS
        // permission re-prompt unnecessarily. We simply probe the current state
        // and prompt the user to make a change only when the state is denied.

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            guard let self = self else { return }
            self.requestLocalNetworkPermission()
        }
    }

    private func requestLocalNetworkPermission() {
        let task = Process()
        task.launchPath = "/usr/sbin/tccutil"
        task.arguments = ["list", bundleID]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.qualityOfService = .utility

        do {
            try task.run()
            task.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            Log(LOG_I, "[NetworkPerm] TCC permissions: \(output)")

            if output.contains("LocalNetwork") && output.contains("allowed") {
                DispatchQueue.main.async { [weak self] in
                    self?.networkPermissionStatus = .ready
                }
            } else {
                DispatchQueue.main.async { [weak self] in
                    self?.networkPermissionStatus = .tccDenied
                    self?.showNetworkPermissionHelpDialog()
                }
            }
        } catch {
            Log(LOG_W, "[NetworkPerm] TCC list failed: \(error.localizedDescription)")
        }
    }

    private func showGatekeeperHelpDialog(output: String) {
        guard let window = NSApp.mainWindow ?? NSApp.windows.first else { return }

        let alert = NSAlert()
        let loc = LanguageManager.shared.localize
        alert.messageText = loc("Gatekeeper Blocked")
        alert.informativeText = loc("Gatekeeper blocked Moonlight") + "\n\n" +
            loc("Gatekeeper blocked informative")
        alert.alertStyle = .warning
        alert.addButton(withTitle: loc("Open System Settings"))
        alert.addButton(withTitle: loc("Dismiss"))
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn {
                self.openSystemSettings()
            }
        }
    }

    private func showNetworkPermissionHelpDialog() {
        guard let window = NSApp.mainWindow ?? NSApp.windows.first else { return }

        let alert = NSAlert()
        let loc = LanguageManager.shared.localize
        alert.messageText = loc("Network Permission Required")
        alert.informativeText = loc("Moonlight needs local network access") + "\n\n" +
            loc("Local network permission informative")
        alert.alertStyle = .informational
        alert.addButton(withTitle: loc("Open System Settings"))
        alert.addButton(withTitle: loc("Dismiss"))
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn {
                self.openSystemSettingsNetwork()
            }
        }
    }

    private func openSystemSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_General")!
        NSWorkspace.shared.open(url)
    }

    private func openSystemSettingsNetwork() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork")!
        NSWorkspace.shared.open(url)
    }
}
