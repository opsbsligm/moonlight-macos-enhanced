//
//  SettingsOverlayPresenter.swift
//  Moonlight for macOS
//
//  Presents the settings page inside the content region of the main window.
//
//  Settings used to be a separate NSWindow that was closed and rebuilt on every
//  invocation, so the app carried two competing window layers. This presenter
//  keeps one window: the page is attached as a child view controller over the
//  content region, the toolbar is hidden while it is up so main window actions
//  cannot fire underneath an invisible page, and the title reads Settings.
//
//  Exit paths, each of which restores the previous window state:
//    • the back control
//    • Escape, through SwiftUI cancelAction on that control
//    • Command+W, filtered by a local monitor scoped to the page
//    • the host window closing while the page is up
//
//  Concurrency note: the two event closures deliberately capture nothing but
//  values they can obtain from the event itself, which keeps them free of
//  non-Sendable captures while still reaching the right window.
//

import AppKit
import SwiftUI

/// Indirection so the SwiftUI back control can point at the presenter without
/// the presenter handing out ``self`` before ``super.init`` has run.
private final class DismissBox {
  var action: () -> Void = {}
}

@MainActor
@objc final class SettingsOverlayPresenter: NSObject {
  private static var active: [ObjectIdentifier: SettingsOverlayPresenter] = [:]

  private let window: NSWindow
  private let hostId: String?
  private let hosting: NSHostingController<LiquidGlassSettingsView>
  /// The box the page reports dismissal through, held here on purpose.
  ///
  /// The view keeps the box weakly -- `onClose` closes over `[weak box]`, so a box
  /// that nothing else owns is deallocated the moment `init` returns, and the back
  /// control then calls through a nil and does nothing. Escape rides the same button,
  /// so a page a player can walk into would only leave by Command+W or by the host
  /// window closing. The box exists so the control can name the presenter without the
  /// presenter handing out `self` before `super.init`; owning it is what makes that
  /// name mean something for as long as the page is up.
  private let dismissBox: DismissBox
  /// The closure the page's back control runs, kept so the probe can run exactly
  /// that closure. It closes over the box weakly, so on a build where nothing owns
  /// the box the call does nothing -- which is why asking it is a different claim
  /// from dismissing the page, and the claim the player depends on.
  private let pageOnClose: () -> Void
  /// The page's model, held here so the page and anything measuring it look at one
  /// instance instead of two. See the note on `LiquidGlassSettingsView.settingsModel`.
  private let settingsModel: SettingsModel
  private var savedTitle: String?
  private var savedToolbarVisible: Bool?
  /// Who held the key focus before the page asked for it. The page borrows it the
  /// way it borrows the title and the toolbar, so it gives it back as well.
  private var savedFirstResponder: NSResponder?
  private var commandWMonitor: Any?
  private var closeObserver: Any?
  private var isClosing = false

  /// Presents settings in the window, replacing the page when another host is
  /// requested. Reopening the same host only brings the window forward.
  @objc(presentSettingsInWindow:hostId:)
  static func present(in window: NSWindow?, hostId: String?) {
    guard let window, let content = window.contentView else { return }
    let key = ObjectIdentifier(window)

    if let existing = active[key] {
      if existing.hostId == hostId {
        window.makeKeyAndOrderFront(nil)
        return
      }
      existing.dismiss()
    }

    let presenter = SettingsOverlayPresenter(window: window, content: content, hostId: hostId)
    active[key] = presenter
    presenter.show(in: content)
  }

#if DEBUG
  /// The model instance the presented page is observing, for the Debug render probe.
  ///
  /// The probe used to construct its own ``SettingsModel`` and compare the page
  /// against it. Measured, the two disagreed on three settings, because a model
  /// built before the configuration store is open answers with defaults: the page
  /// showed Metal while the checker believed the user had chosen Native, and every
  /// assertion it then made was a comparison between two different machines. Read
  /// the page's own model and the claim becomes what it should be -- this page
  /// agrees with the rules it is rendering from.
  @objc(presentedSettingsModelForProbeInWindow:)
  static func presentedSettingsModelForProbe(in window: NSWindow?) -> AnyObject? {
    guard let window else { return nil }
    return active[ObjectIdentifier(window)]?.settingsModel
  }
#endif

  /// Runs the closure the back control runs, so the probe presses what the player
  /// presses instead of the teardown behind it.
  @objc(pressBackControlInWindow:)
  static func pressBackControl(in window: NSWindow?) -> Bool {
    guard let window, let presenter = active[ObjectIdentifier(window)] else { return false }
    presenter.pageOnClose()
    return true
  }

  @objc(dismissSettingsFromWindow:)
  static func dismiss(from window: NSWindow?) {
    guard let window else { return }
    active[ObjectIdentifier(window)]?.dismiss()
  }

  @objc(isSettingsPresentedInWindow:)
  static func isPresented(in window: NSWindow?) -> Bool {
    guard let window else { return false }
    return active[ObjectIdentifier(window)] != nil
  }

  private init(window: NSWindow, content: NSView, hostId: String?) {
    self.window = window
    self.hostId = hostId

    let box = DismissBox()
    self.dismissBox = box
    let pageOnClose: () -> Void = { [weak box] in box?.action() }
    self.pageOnClose = pageOnClose
    self.settingsModel = SettingsModel()
    self.hosting = NSHostingController(
      rootView: LiquidGlassSettingsView(hostId: hostId,
                                        onClose: pageOnClose,
                                        settingsModel: settingsModel)
    )
    super.init()
    box.action = { [weak self] in self?.dismiss() }

    hosting.view.translatesAutoresizingMaskIntoConstraints = false
    hosting.view.frame = content.bounds
    hosting.view.alphaValue = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? 1 : 0
  }

  deinit {
    if let commandWMonitor { NSEvent.removeMonitor(commandWMonitor) }
    if let closeObserver { NotificationCenter.default.removeObserver(closeObserver) }
  }

  private func show(in content: NSView) {
    if let parent = window.contentViewController {
      parent.addChild(hosting)
    }
    content.addSubview(hosting.view)

    NSLayoutConstraint.activate([
      hosting.view.leadingAnchor.constraint(equalTo: content.leadingAnchor),
      hosting.view.trailingAnchor.constraint(equalTo: content.trailingAnchor),
      hosting.view.topAnchor.constraint(equalTo: content.topAnchor),
      hosting.view.bottomAnchor.constraint(equalTo: content.bottomAnchor)
    ])

    savedTitle = window.title
    savedFirstResponder = window.firstResponder
    window.title = LanguageManager.shared.localize("Settings")

    savedToolbarVisible = window.toolbar?.isVisible
    window.toolbar?.isVisible = false

    installCommandWFilter()
    installCloseObserver()

    if hosting.view.alphaValue < 1 {
      NSAnimationContext.runAnimationGroup { context in
        context.duration = TabBarConfig.animationDuration
        context.timingFunction = CAMediaTimingFunction(
          controlPoints: Float(TabBarConfig.curveCP1x), Float(TabBarConfig.curveCP1y),
          Float(TabBarConfig.curveCP2x), Float(TabBarConfig.curveCP2y))
        hosting.view.animator().alphaValue = 1
      }
    }

    window.makeFirstResponder(hosting.view)
  }

  private func dismiss() {
    guard !isClosing else { return }
    isClosing = true

    if let commandWMonitor {
      NSEvent.removeMonitor(commandWMonitor)
      self.commandWMonitor = nil
    }
    if let closeObserver {
      NotificationCenter.default.removeObserver(closeObserver)
      self.closeObserver = nil
    }

    window.toolbar?.isVisible = savedToolbarVisible ?? true
    if let savedTitle { window.title = savedTitle }

    // Give the key focus back while the page is still in the view tree. If the
    // page is the first responder when it disappears, AppKit chooses the
    // successor, and the successor is where every key the page's gate hands back
    // to AppKit then lands: on the window, where Space and Return belong to the
    // default button and the arrow keys move the key view loop. A page that
    // closes by taking the keys with it is the same fault as a title that came
    // back blank -- this class already returns the title and the toolbar, so the
    // focus is the third borrowed thing, and the only one it let go of.
    //
    // The first responder is any NSResponder, and only a view or the window
    // itself can say which window it belongs to, so the ownership test has two
    // shapes. A responder that belongs to some other window is not somebody to
    // hand the keyboard back to, and the content view is the fallback.
    if let savedFirstResponder,
       (savedFirstResponder as? NSView)?.window === window
         || savedFirstResponder === window {
      window.makeFirstResponder(savedFirstResponder)
    } else {
      window.makeFirstResponder(window.contentView)
    }

    hosting.view.removeFromSuperview()
    hosting.removeFromParent()

    Self.active.removeValue(forKey: ObjectIdentifier(window))
  }

  // Command+W is bound to Window > Close, which would take the whole window
  // down while the page is up. Swallow it for as long as the page owns the
  // content region so the gesture either means "go back" or nothing at all.
  private func installCommandWFilter() {
    commandWMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
      guard event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
            event.charactersIgnoringModifiers?.lowercased() == "w"
      else { return event }
      let target = event.window ?? NSApp.keyWindow
      MainActor.assumeIsolated {
        SettingsOverlayPresenter.dismiss(from: target)
      }
      return nil
    }
  }

  // The static table keeps the presenter alive while the page is up, so it has
  // to be emptied when the window disappears underneath it.
  private func installCloseObserver() {
    closeObserver = NotificationCenter.default.addObserver(
      forName: NSWindow.willCloseNotification, object: window, queue: .main
    ) { note in
      guard let target = note.object as? NSWindow else { return }
      MainActor.assumeIsolated {
        SettingsOverlayPresenter.dismiss(from: target)
      }
    }
  }
}
