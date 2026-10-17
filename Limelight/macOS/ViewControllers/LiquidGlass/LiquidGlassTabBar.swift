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
  // The selected capsule's tint, measured off the system's own tab pickers (Activity
  // Monitor's functional areas): the slide rides *lighter* than its track (measured:
  // the system's track sits at 235 grey and its selected capsule at 252), so the tint
  // is a near-white frost pushed hard, not a neutral mid-grey. A mid-grey tint darkens
  // the glass over a light page -- measured 212 under a 246 track -- and a darkened
  // slide reads as a sunken smudge, which is the version the user rejected as "not
  // restored at all". Neutral still means the channels agree: the audit refuses a tint
  // whose channels drift apart, so a regression to blue has to pass a measurement first.
  static let selectedGlassTint = Color(
    .sRGB, red: 0.95, green: 0.96, blue: 0.98, opacity: 0.85
  )
  // The track's own tint, measured off the same reference: Activity Monitor's track
  // sits at 235 grey under a white slide at 252 -- the track is *darker* than what
  // rides on it. A track with no tint copies the page (measured: 246 over the washed
  // base) and a white slide on a near-white track is invisible, which is the flat bar
  // the user threw back as "not restored". A neutral grey pull puts the depth back.
  static let trackGlassTint = Color(
    .sRGB, red: 0.45, green: 0.46, blue: 0.48, opacity: 0.30
  )
  // The slide is raised, not painted on: the system's picker keeps a soft shadow under
  // the selected capsule, and the refraction edge alone did not read as depth over the
  // light page. A shadow is chrome, not fake glass -- it bends nothing and colours
  // nothing, it only sits the capsule above the track.
  static let selectionShadowColor = Color.black.opacity(0.18)
  // The bar lays out at the system control's metrics: 13pt labels, 28pt row, 3pt track
  // inset, capsule ends.
  static let labelFontSize: CGFloat = 13
  static let tabBarHeight: CGFloat = 28
  static let outerPadding: CGFloat = 3
  static let minimumSegmentWidth: CGFloat = 66

  static let accentCoolBlue = Color(
    .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
  )
  // The selected label sits on a light frost, exactly where the system puts its own:
  // the system keeps that label dark in Aqua and light in Dark Aqua (measured off
  // Activity Monitor's selected segment: around (30,30,30) over a light page). A white
  // label was tried and reads as an accent chip, not a glass slide -- measured 0.99
  // lightest pixel on the very surface that is supposed to be the point.
  // One dark for both appearances, because the slide is one bright frost in both:
  // the white capsule over a dark track measured unreadable with the light label this
  // used to pick in Dark Aqua (white on white). The system's picker keeps the slide's
  // label dark wherever the slide frosts light, and this slide always frosts light.
  static let selectedLabelColor = Color(
    .sRGB, red: 0.12, green: 0.12, blue: 0.13, opacity: 1.0
  )
  // Unselected labels keep the system's own primary label colour: the system's tab
  // picker does not dim them into greyed-out secondary text, and neither does this bar.
  static let unselectedLabelColor = Color(nsColor: .labelColor)
  // The hairline between two unselected segments, the way the system's picker separates
  // its segments; the selected capsule needs none, its refraction edge is the seam.
  static let separatorColor = Color(nsColor: .separatorColor)

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
            .glassEffect(
              .regular.tint(TabBarConfig.trackGlassTint),
              in: Capsule(style: .continuous))
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
                      .tint(TabBarConfig.selectedGlassTint),
                    in: Capsule(style: .continuous)
                  )
                  .shadow(color: TabBarConfig.selectionShadowColor,
                          radius: 2.5, y: 1)
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
        ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
          if index > 0 && item.id != selection && items[index - 1].id != selection {
            // The system's picker keeps a hairline between neighbours; the selected
            // capsule needs none because its refraction edge already is the seam.
            Rectangle()
              .fill(TabBarConfig.separatorColor)
              .frame(width: 1, height: 14)
          }
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
                ? TabBarConfig.selectedLabelColor : TabBarConfig.unselectedLabelColor)
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
