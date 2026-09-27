// Compile alongside the production presenter and segmented-control source.
// Uses offscreen windows; never posts mouse/keyboard events to the desktop.
import AppKit
import SwiftUI

final class SettingsModel: ObservableObject {}
final class LanguageManager {
  static let shared = LanguageManager()
  func localize(_ key: String) -> String { key }
}
enum SettingsKeyCaptureMonitor { static func end() {} }
struct LiquidGlassSettingsView: View {
  let hostId: String?
  let onClose: (() -> Void)?
  let settingsModel: SettingsModel
  @State private var selection = 0
  var body: some View {
    MeasuredLayout { VStack {
      LiquidGlassTabBar(selection: $selection, items: [
        .init(id: 0, title: "Stream", symbol: "", tint: .blue),
        .init(id: 5, title: "Audio", symbol: "", tint: .blue),
        .init(id: 2, title: "Input", symbol: "", tint: .blue)
      ])
      Text("Page \(selection)")
    }.frame(maxWidth: .infinity, maxHeight: .infinity) }
  }
}

struct MeasuredLayout: Layout {
  static var measurements = 0
  func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
    Self.measurements += 1
    return subviews[0].sizeThatFits(proposal)
  }
  func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
    subviews[0].place(at: bounds.origin, proposal: ProposedViewSize(bounds.size))
  }
}
@main struct LayoutProbe {
  @MainActor static func main() {
    let started = Date()
    _ = NSApplication.shared
    var checks = 0
    func check(_ ok: Bool, _ message: String) {
      guard ok else { fatalError(message) }
      checks += 1
    }
    func segments(in view: NSView) -> NSSegmentedControl? {
      if let control = view as? NSSegmentedControl { return control }
      for child in view.subviews {
        if let result = segments(in: child) { return result }
      }
      return nil
    }
    // Actions received during native tracking must not mount a pane in that
    // tracking loop. Multiple pending selections coalesce, and dismissal cancels.
    var selectedID = 0
    let binding = Binding<Int>(get: { selectedID }, set: { selectedID = $0 })
    let bar = LiquidGlassTabBar(selection: binding, items: [
      .init(id: 0, title: "Stream", symbol: "", tint: .blue),
      .init(id: 5, title: "Audio", symbol: "", tint: .blue),
      .init(id: 2, title: "Input", symbol: "", tint: .blue)
    ])
    let coordinator = bar.makeCoordinator()
    let native = NSSegmentedControl(labels: ["Stream", "Audio", "Input"],
                                   trackingMode: .selectOne, target: nil, action: nil)
    native.selectedSegment = 1
    coordinator.selectSegment(native)
    check(selectedID == 0, "page committed synchronously inside native action")
    native.selectedSegment = 2
    coordinator.selectSegment(native)
    RunLoop.main.run(mode: .eventTracking, before: Date(timeIntervalSinceNow: 0.01))
    check(selectedID == 0, "page mounted while native tracking is active")
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.01))
    check(selectedID == 2, "latest nonconsecutive page ID was not committed")
    native.selectedSegment = 1
    coordinator.selectSegment(native)
    LiquidGlassTabBar.dismantleNSView(native, coordinator: coordinator)
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.01))
    check(selectedID == 2, "dismissed page received a stale selection")

    for fullSize in [false, true] {
      var style: NSWindow.StyleMask = [.titled, .closable, .resizable]
      if fullSize { style.insert(.fullSizeContentView) }
      let window = NSWindow(contentRect: NSRect(x: -4000, y: -4000, width: 852, height: 566),
                            styleMask: style, backing: .buffered, defer: false)
      window.isReleasedWhenClosed = false
      window.title = "Browser"
      let parent = NSViewController()
      parent.view = NSView(frame: window.contentView!.bounds)
      window.contentViewController = parent
      window.toolbar = NSToolbar(identifier: "probe")
      let initialToolbar = window.toolbar!.isVisible
      for _ in 0..<3 {
        SettingsOverlayPresenter.present(in: window, hostId: nil)
        window.contentView!.layoutSubtreeIfNeeded()
        check(!window.styleMask.contains(.fullSizeContentView), "settings overlaps native titlebar")
        let host = parent.children.last!.view
        for size in [NSSize(width: 650, height: 350), NSSize(width: 1010, height: 660)] {
          window.setContentSize(size)
          window.contentView!.layoutSubtreeIfNeeded()
          guard let control = segments(in: host) else { fatalError("missing native tabs") }
          for index in [1, 2, 0, 1, 0] {
            control.selectedSegment = index
            control.sendAction(control.action!, to: control.target)
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.01))
            window.contentView!.layoutSubtreeIfNeeded()
            let occupied = host.convert(host.bounds, to: nil)
            check(occupied.maxY <= window.contentLayoutRect.maxY + 0.5,
                  "settings hit area covers titlebar after selection")
            check(window.isMovable, "native window movement disabled")
            check(control.tag(forSegment: 1) == 5, "nonconsecutive pane ID lost")
          }
        }
        SettingsOverlayPresenter.dismiss(from: window)
        check(window.styleMask.contains(.fullSizeContentView) == fullSize, "window style not restored")
        check(window.toolbar!.isVisible == initialToolbar, "toolbar not restored")
        check(window.title == "Browser", "title not restored")
        check(parent.children.isEmpty, "hosting controller leaked")
      }
      window.close()
    }
    print("Layout measurements: \(MeasuredLayout.measurements), elapsed: \(Date().timeIntervalSince(started))s")
    print("PASS: \(checks) settings window geometry, selection and lifecycle checks")
  }
}
