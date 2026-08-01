//
//  LiquidGlassWindowController.swift
//  Moonlight for macOS
//
//  macOS 26 Liquid Glass window controller.
//  Drops all legacy macOS <26 fallback paths; dedicated to the new
//  translucent material system and native .liquidGlass split view.
//

import AppKit
import SwiftUI
import Combine

final class LiquidGlassWindowController<RootView: View>: NSWindowController {
  private var languageObserver: Any?

  convenience init(rootView: RootView, title: String, minSize: NSSize = NSSize(width: 560, height: 420)) {
    let hosting = NSHostingController(rootView: rootView)

    let window = NSWindow(contentViewController: hosting)
    window.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
    window.collectionBehavior = [.fullScreenNone, .participatesInCycle]
    window.tabbingMode = .disallowed
    window.minSize = minSize
    window.title = title
    window.titleVisibility = .visible
    window.titlebarAppearsTransparent = true
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
    // macOS 26 Liquid Glass windows respond to system vibrancy automatically;
    // the content view should never draw opaque backgrounds.
    window?.contentView?.wantsLayer = true
    window?.contentView?.layer?.backgroundColor = .clear
    window?.isOpaque = false
    window?.hasShadow = true
    window?.backgroundColor = .clear
  }
}

extension LiquidGlassWindowController: NSWindowDelegate {
  func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
    // Enforce minimum size for the liquid-glass tab bar so tiles never collapse.
    let minSize = sender.minSize
    return NSSize(
      width: max(frameSize.width, minSize.width),
      height: max(frameSize.height, minSize.height)
    )
  }
}
