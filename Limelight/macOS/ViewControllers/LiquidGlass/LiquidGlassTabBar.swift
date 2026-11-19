import AppKit
import SwiftUI

// Presentation timing is independent of AppKit's native control interaction.
enum TabBarConfig {
  static let iconSize: CGFloat = 13
  static let iconTextSpacing: CGFloat = 6
  static let fontSize: CGFloat = 12
  static let accentCoolBlue = Color(
    .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
  )
  static let animationDuration: Double = 0.22
  static let curveCP1x: Double = 0.4
  static let curveCP1y: Double = 0.0
  static let curveCP2x: Double = 0.2
  static let curveCP2y: Double = 1.0
}

public struct LiquidGlassTabItem: Identifiable {
  public let id: Int
  public let title: String
  public let symbol: String
  public let tint: Color

  public init(id: Int, title: String, symbol: String, tint: Color) {
    self.id = id
    self.title = title
    self.symbol = symbol
    self.tint = tint
  }
}

// Use the system segmented control, including its optical selection, pointer
// tracking, keyboard navigation and accessibility. Do not overlay a second
// glass surface or intercept the native tracking loop with a SwiftUI gesture.
public struct LiquidGlassTabBar: NSViewRepresentable {
  @Binding public var selection: Int
  public let items: [LiquidGlassTabItem]

  public init(selection: Binding<Int>, items: [LiquidGlassTabItem]) {
    self._selection = selection
    self.items = items
  }

  public func makeCoordinator() -> Coordinator { Coordinator(self) }

  public func makeNSView(context: Context) -> NSSegmentedControl {
    let control = NSSegmentedControl()
    control.segmentStyle = .rounded
    control.trackingMode = .selectOne
    control.isContinuous = false
    control.controlSize = .large
    control.font = .systemFont(ofSize: 13)
    control.segmentDistribution = .fit
    control.borderShape = .capsule
    // Not merely version-guarded: the macOS 26 SDK has no `role` symbol at all, so `#available`
    // alone fails to compile there. ML_APPKIT_TABS_ROLE is declared by the project only when the
    // SDK in use declares the property; #available still guards the run on older systems.
    // Dropping the assignment instead would change the accepted Activity-Monitor-style tabs look.
#if ML_APPKIT_TABS_ROLE
    if #available(macOS 27.0, *) {
      control.role = .tabs
    }
#endif
    control.target = context.coordinator
    control.action = #selector(Coordinator.selectSegment(_:))
    control.setAccessibilityIdentifier("settings-navigation")
    configure(control, context: context)
    return control
  }

  public func updateNSView(_ control: NSSegmentedControl, context: Context) {
    configure(control, context: context)
  }

  public func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSSegmentedControl,
                          context: Context) -> CGSize? {
    nsView.intrinsicContentSize
  }

  private func configure(_ control: NSSegmentedControl, context: Context) {
    context.coordinator.parent = self
    if control.segmentCount != items.count { control.segmentCount = items.count }
    for (index, item) in items.enumerated() {
      if control.label(forSegment: index) != item.title {
        control.setLabel(item.title, forSegment: index)
      }
      if control.tag(forSegment: index) != item.id {
        control.setTag(item.id, forSegment: index)
      }
      let labelWidth = (item.title as NSString).size(withAttributes: [
        .font: control.font ?? NSFont.systemFont(ofSize: 13)
      ]).width
      let width = max(66, ceil(labelWidth) + 28)
      if control.width(forSegment: index) != width {
        control.setWidth(width, forSegment: index)
      }
    }
    // Pane IDs are not consecutive. Always map by identity, never by raw ID.
    let index = items.firstIndex { $0.id == selection } ?? -1
    if control.selectedSegment != index { control.selectedSegment = index }
  }

  public static func dismantleNSView(_ control: NSSegmentedControl, coordinator: Coordinator) {
    coordinator.isActive = false
    coordinator.pendingSelection = nil
    control.target = nil
  }

  public final class Coordinator: NSObject {
    var parent: LiquidGlassTabBar
    var isActive = true
    var pendingSelection: Int?
    private var selectionScheduled = false
    init(_ parent: LiquidGlassTabBar) { self.parent = parent }

    @objc func selectSegment(_ sender: NSSegmentedControl) {
      let index = sender.selectedSegment
      guard parent.items.indices.contains(index) else { return }
      pendingSelection = parent.items[index].id
      guard !selectionScheduled else { return }
      selectionScheduled = true
      // Native tracking runs in eventTracking mode. Commit only after it exits,
      // so mounting a settings pane cannot block the glass under the pointer.
      RunLoop.main.perform(inModes: [.default]) { [weak self] in
        guard let self else { return }
        self.selectionScheduled = false
        guard self.isActive, let selection = self.pendingSelection,
              self.parent.items.contains(where: { $0.id == selection }) else { return }
        self.pendingSelection = nil
        if self.parent.selection != selection { self.parent.selection = selection }
      }
    }
  }
}
