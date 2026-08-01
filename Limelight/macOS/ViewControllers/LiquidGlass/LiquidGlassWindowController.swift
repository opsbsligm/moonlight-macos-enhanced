//
//  LiquidGlassWindowController.swift
//  Moonlight for macOS
//
//  macOS 26 Liquid Glass window controller.
//  Drops all legacy macOS <26 fallback paths; dedicated to the new
//  translucent material system and native .liquidGlass split view.
//
//  Note: configuration mirrors SettingsHostingController — the window is
//  fully opaque (no .fullSizeContentView, no transparent titlebar) to
//  satisfy the "settings window must be completely opaque with no desktop
//  penetration" hard constraint.
//

import AppKit
import SwiftUI
import Combine

final class LiquidGlassWindowController<RootView: View>: NSWindowController, NSWindowDelegate {
  private var languageObserver: Any?

  convenience init(rootView: RootView, title: String, minSize: NSSize = NSSize(width: 560, height: 420)) {
    let hosting = NSHostingController(rootView: rootView)

    let window = NSWindow(contentViewController: hosting)
    // Standard opaque window — NO fullSizeContentView, NO transparent titlebar.
    // Matches SettingsHostingController so the window is completely opaque.
    window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
    window.collectionBehavior = [.fullScreenNone, .participatesInCycle]
    window.tabbingMode = .disallowed
    window.minSize = minSize
    window.title = title
    window.titleVisibility = .visible
    window.titlebarAppearsTransparent = false
    // styleMask does not include .fullSizeContentView, so the content view
    // does not extend under the titlebar — hasFullScreenContentView is moot.
    window.isMovable = true

    self.init(window: window)

    window.delegate = self
    setupAppearanceBindings()

    languageObserver = NotificationCenter.default.addObserver(
      forName: .init("LanguageChanged"), object: nil, queue: .main
    ) { [weak window, title] _ in
      window?.title = title
    }
  }

  deinit {
    if let languageObserver { NotificationCenter.default.removeObserver(languageObserver) }
  }

  private func setupAppearanceBindings() {
    // Opaque configuration — matches SettingsHostingController. The window
    // and its content view draw an opaque controlBackgroundColor layer so
    // the desktop can never show through (hard constraint).
    window?.contentView?.wantsLayer = true
    window?.contentView?.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
    window?.contentView?.layer?.isOpaque = true
    window?.isOpaque = true
    window?.hasShadow = true
    window?.backgroundColor = .controlBackgroundColor
  }

  func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
    // Enforce minimum size for the liquid-glass tab bar so tiles never collapse.
    let minSize = sender.minSize
    return NSSize(
      width: max(frameSize.width, minSize.width),
      height: max(frameSize.height, minSize.height)
    )
  }
}
