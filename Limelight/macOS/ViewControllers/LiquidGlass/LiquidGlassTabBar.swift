import AppKit
import SwiftUI

// The settings tab bar: one interactive liquid-glass surface, drawn by the system.
//
// Why not NSSegmentedControl: the beta this app ships against renders the control's
// tab-role selection white-on-white (measured: darkest selected-label pixel 0.92 over a
// light base), and its non-tab role paints an opaque accent block -- a solid chip on a
// page of glass, which is exactly the flat look the page was rejected for. A segmented
// control cannot opt out of drawing its own selection, so the bar draws its selection
// as system glass instead: a tinted capsule inside the same GlassEffectContainer as the
// track, so the two merge and morph as one material, and a real Button per segment so
// activation stays a button to accessibility and the keyboard.
enum TabBarConfig {
  static let iconSize: CGFloat = 13
  static let iconTextSpacing: CGFloat = 6
  static let fontSize: CGFloat = 12
  static let interSpacing: CGFloat = 2
  // Tint strength of the selected capsule. The glass itself is the system's; this only
  // colours it, and the cool accent keeps its read in both appearances at this weight.
  static let glassTintOpacity: Double = 0.18
  // The bar lays out at the system control's metrics: 13pt labels, 28pt row, 3pt track
  // inset, capsule ends.
  static let labelFontSize: CGFloat = 13
  static let tabBarHeight: CGFloat = 28
  static let outerPadding: CGFloat = 3
  static let minimumSegmentWidth: CGFloat = 66

  static let accentCoolBlue = Color(
    .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
  )
  // The selected label sits on glass over the page, not on a solid chip, so it needs a
  // colour that reads against both page appearances. The page base is light in Aqua and
  // near-black in Dark Aqua, so a single blue cannot serve both: deep blue on light,
  // pale blue on dark, the same pair the system uses for its own tinted-on-glass text.
  static let selectedLabelColor = Color(nsColor: NSColor(name: nil) { appearance in
    let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
    return isDark
      ? NSColor(srgbRed: 0.55, green: 0.75, blue: 1.0, alpha: 1.0)
      : NSColor(srgbRed: 0.13, green: 0.42, blue: 0.85, alpha: 1.0)
  })

  static let animationDuration: Double = 0.22
  static let curveCP1x: Double = 0.4
  static let curveCP1y: Double = 0.0
  static let curveCP2x: Double = 0.2
  static let curveCP2y: Double = 1.0
}

/// Carries the selected trait as a real branch, not a computed trait set, so the
/// accessibility tree re-answers AXSelected when the selection moves (see the note at
/// the call site -- measured: a trait union leaves the flag on the first segment forever
/// for out-of-process clients).
private struct SelectionTrait: ViewModifier {
  let selected: Bool
  func body(content: Content) -> some View {
    if selected {
      content.accessibilityAddTraits(.isSelected)
    } else {
      content.accessibilityRemoveTraits(.isSelected)
    }
  }
}

public struct LiquidGlassTabItem: Identifiable {
  public let id: Int
  public let title: String
  public let symbol: String
  /// Retained for callers that still pass a per-tab tint; the bar renders one cool
  /// accent everywhere, so no tab can drift warm on its own.
  public let tint: Color

  public init(id: Int, title: String, symbol: String, tint: Color) {
    self.id = id
    self.title = title
    self.symbol = symbol
    self.tint = tint
  }
}

public struct LiquidGlassTabBar: View {
  @Binding public var selection: Int
  public let items: [LiquidGlassTabItem]

  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Namespace private var nsMorph

  /// The system-shaped curve (no overshoot). Reduce Motion drops the travel, not the
  /// selection: the capsule appears at its destination instead of sliding.
  private var fluidAnimation: Animation {
    Animation.timingCurve(
      TabBarConfig.curveCP1x, TabBarConfig.curveCP1y,
      TabBarConfig.curveCP2x, TabBarConfig.curveCP2y,
      duration: TabBarConfig.animationDuration
    )
  }

  public init(selection: Binding<Int>, items: [LiquidGlassTabItem]) {
    self._selection = selection
    self.items = items
  }

  public var body: some View {
    // Two layers, one stack. The container's business is glass and nothing else: a
    // GlassEffectContainer folds its own content into the material, so labels placed
    // inside it come back out of the compositor bleached (measured on the real page:
    // darkest label pixel 212 over a light base, i.e. unreadable). The buttons ride on
    // top of the container instead, aligned by identical padding, and the container
    // renders only glass bending the page underneath it.
    ZStack(alignment: .topLeading) {
      GlassEffectContainer(spacing: TabBarConfig.interSpacing) {
        ZStack(alignment: .topLeading) {
          // Track: the bar's own glass, bending the page base underneath it.
          Capsule(style: .continuous)
            .fill(Color.clear)
            .glassEffect(.regular, in: Capsule(style: .continuous))
            .zIndex(0)

          // Selection: a second glass capsule inside the same container, so the system
          // renders track and selection as one interacting material. It morphs between
          // segments instead of a chip jumping between them.
          HStack(spacing: TabBarConfig.interSpacing) {
            ForEach(items) { item in
              if item.id == selection {
                Capsule(style: .continuous)
                  .fill(Color.clear)
                  .glassEffect(
                    .regular.interactive()
                      .tint(TabBarConfig.accentCoolBlue
                        .opacity(TabBarConfig.glassTintOpacity)),
                    in: Capsule(style: .continuous)
                  )
                  .matchedGeometryEffect(id: "selectionPill", in: nsMorph)
                  .frame(width: width(for: item), height: TabBarConfig.tabBarHeight)
              } else {
                Color.clear.frame(width: width(for: item),
                                  height: TabBarConfig.tabBarHeight)
              }
            }
          }
          .padding(TabBarConfig.outerPadding)
          .zIndex(1)
          .animation(reduceMotion ? nil : fluidAnimation, value: selection)
        }
      }

      // Buttons on top of the glass: real Buttons, so VoiceOver hears a button with a
      // selection state and the keyboard reaches every pane. .plain keeps them
      // invisible so the glass stays the only chrome.
      HStack(spacing: TabBarConfig.interSpacing) {
        ForEach(items) { item in
          Button {
            if selection != item.id { selection = item.id }
          } label: {
            Text(item.title)
              .font(.system(size: TabBarConfig.labelFontSize,
                            weight: item.id == selection ? .semibold : .regular))
              .lineLimit(1)
              .minimumScaleFactor(0.6)
              .allowsTightening(true)
              .foregroundStyle(item.id == selection
                ? TabBarConfig.selectedLabelColor : Color.secondary)
              .frame(width: width(for: item), height: TabBarConfig.tabBarHeight)
              .contentShape(Capsule(style: .continuous))
          }
          .buttonStyle(.plain)
          .accessibilityElement(children: .ignore)
          .accessibilityLabel(Text(item.title))
          .accessibilityAddTraits(.isButton)
          // Not a ternary on the trait set: a conditional branch whose two sides carry
          // .isSelected / .removeTraits(.isSelected) separately. Measured against a real
          // out-of-process AX client, the union form leaves AXSelected frozen at its
          // first answer when the selection moves; the branching form updates it (the
          // shipped settings window shows exactly that: System Events reads the selected
          // flag on whichever tab is live, after every click).
          .modifier(SelectionTrait(selected: item.id == selection))
        }
      }
      .padding(TabBarConfig.outerPadding)
      .zIndex(2)
    }
    .fixedSize()
    .accessibilityIdentifier("settings-navigation")
    // How the segments stay speakable, measured over the real AXAPI on this SDK: a
    // .plain button's own label text does not surface -- AXDescription came back nil
    // on all six with .plain, with .accessibilityLabel(item.title), and with the
    // String form of it. The pairing that works is .accessibilityElement(children:
    // .ignore) plus .accessibilityLabel(Text(...)) on the button itself: a raw
    // AXUIElement read then carries the pane name on every segment (返回/串流/视频/…)
    // with AXSelected on the live one. Dropping either half goes nameless again, so
    // the audit pins the pair.
  }

  /// Segment widths follow the label, with a floor, the way the system control sizes
  /// itself -- equal widths would bloat short labels and clip long localisations.
  private func width(for item: LiquidGlassTabItem) -> CGFloat {
    let labelWidth = (item.title as NSString).size(withAttributes: [
      .font: NSFont.systemFont(ofSize: TabBarConfig.labelFontSize)
    ]).width
    return max(TabBarConfig.minimumSegmentWidth, ceil(labelWidth) + 28)
  }
}
