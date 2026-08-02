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

    private let bundleID = "std.skyhua.MoonlightMac2"

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
        let task = Process()
        task.launchPath = "/usr/sbin/tccutil"
        task.arguments = ["reset", "LocalNetwork", bundleID]
        task.qualityOfService = .utility

        do {
            try task.run()
            task.waitUntilExit()
            Log(LOG_I, "[NetworkPerm] TCC LocalNetwork reset initiated")
        } catch {
            Log(LOG_W, "[NetworkPerm] TCC reset failed: \(error.localizedDescription)")
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
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
        alert.messageText = "Gatekeeper 阻止了 Moonlight"
        alert.informativeText = "macOS 安全机制阻止了 Moonlight 运行。\n\n请执行以下操作：\n\n1. 打开 系统设置 → 隐私与安全性\n2. 向下滚动找到 Moonlight 被阻止的提示\n3. 点击「仍要打开」按钮\n4. 在确认对话框中点击「打开」\n\n或者：右键点击 Moonlight.app → 选择「打开」→ 确认。"
        alert.alertStyle = .warning
        alert.addButton(withTitle: "打开系统设置")
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn {
                self.openSystemSettings()
            }
        }
    }

    private func showNetworkPermissionHelpDialog() {
        guard let window = NSApp.mainWindow ?? NSApp.windows.first else { return }

        let alert = NSAlert()
        alert.messageText = "需要网络权限"
        alert.informativeText = "Moonlight 需要访问本地网络来发现和连接您的游戏主机。\n\n请执行以下操作：\n\n1. 打开 系统设置 → 隐私与安全性 → 本地网络\n2. 找到 Moonlight 并开启开关\n3. 重新启动 Moonlight"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "打开系统设置")
        alert.addButton(withTitle: "知道了")
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
