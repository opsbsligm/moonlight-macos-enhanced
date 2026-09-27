//
//  LiquidGlassSettingsView.swift
//  Moonlight for macOS
//
//  macOS 26 Liquid Glass settings view.
//
//  Presentation contract: this view is embedded into the content region of the
//  main window by SettingsOverlayPresenter. It is no longer hosted in its own
//  window, so two properties are load bearing and were both wrong before:
//
//  • The background has to be fully opaque. Under the older .regularMaterial
//    the settings surface was translucent over whatever page it covered, and
//    the previous host window additionally set isOpaque = false with a clear
//    background colour, which let the desktop show through. Both violated the
//    "settings must be completely opaque" constraint that the file comments
//    claimed to satisfy.
//  • No intrinsic minimum size. As an embedded page it has to adapt to the
//    main window instead of forcing a 640x520 floor that the main window's
//    own 650x350 minimum contradicts.
//
//  When onClose is supplied the view draws its own back control, because an
//  embedded page has no close button of its own.
//

import AVFoundation
import AppKit
import SwiftUI

private typealias Pane = SettingsPaneType

struct LiquidGlassSettingsView: View {
  // Owned by whoever presents the page (SettingsOverlayPresenter) rather than
  // created inside SwiftUI's view identity. As a `@StateObject` the instance the
  // user is looking at could not be reached from outside -- reading it through the
  // hosting controller handed back a brand new model -- so nothing could check
  // that what the page shows is what its own rules say. Keeping it outside also
  // stops a settings model being rebuilt, with its Video Toolbox probe and its
  // preference reads, every time SwiftUI recreates the view value.
  let settingsModel: SettingsModel
  @ObservedObject var languageManager = LanguageManager.shared

  @AppStorage("selected-settings-pane") private var selectedPane: Pane = .stream

  var hostId: String?
  /// Supplied when the view is embedded in the main window. Draws a back
  /// control and reports dismissal so the presenter can remove the page.
  var onClose: (() -> Void)?

  init(hostId: String? = nil, onClose: (() -> Void)? = nil, settingsModel: SettingsModel? = nil) {
    self.hostId = hostId
    self.onClose = onClose
    self.settingsModel = settingsModel ?? SettingsModel()
  }

  var body: some View {
    let tabs: [LiquidGlassTabItem] = Pane.allCases.map { p in
      LiquidGlassTabItem(
        id: p.rawValue,
        title: languageManager.localize(p.title),
        symbol: p.symbol,
        tint: p.color
      )
    }

    let selectionBinding = Binding<Int>(
      get: { selectedPane.rawValue },
      set: {
        if let p = Pane(rawValue: $0) {
          selectedPane = p
        }
      }
    )

    // Root: a single ScrollView, with the tab bar injected into the top safe
    // area through .safeAreaInset(edge: .top). As an embedded page the region
    // below the title bar belongs to us alone, so the tab bar and the optional
    // back row stack inside that inset and the content scrolls under them.
    ScrollView(.vertical, showsIndicators: true) {
      VStack(spacing: 16) {
        Group {
          switch effectivePane {
          case .stream:
            SettingPaneLoader(settingsModel) {
              StreamView()
            }
          case .video:
            SettingPaneLoader(settingsModel) {
              VideoView()
            }
          case .audio:
            SettingPaneLoader(settingsModel) {
              AudioView()
            }
          case .input:
            SettingPaneLoader(settingsModel) {
              InputView()
            }
          case .app:
            SettingPaneLoader(settingsModel) {
              AppView()
            }
          case .devices:
            SettingPaneLoader(settingsModel) {
              DevicesView()
            }
          case .legacy:
            EmptyView()
          }
        }
        .environmentObject(settingsModel)
      }
      .frame(maxWidth: 920)
      .padding(.horizontal, 24)
      .padding(.top, 20)
      .padding(.bottom, 20)
      .frame(maxWidth: .infinity)
    }
    .scrollContentBackground(.hidden)
    .safeAreaInset(edge: .top, spacing: 0) {
      SettingsNavigationLayout {
        if onClose != nil {
          headerBar.frame(width: 76, alignment: .leading)
        } else {
          Color.clear.frame(width: 0, height: 0)
        }
        LiquidGlassTabBar(selection: selectionBinding, items: tabs).fixedSize()
      }
      .padding(.horizontal, 24)
      .padding(.vertical, 14)
      .background(opaqueBase)
      .overlay(alignment: .bottom) { Divider() }
    }

    // Fully opaque base colour, not a material. This page covers the main
    // window content rather than a desktop, so anything translucent here
    // would show the host list underneath it. The glass pill samples this
    // base the same way the tab bar track does.
    .background(opaqueBase)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .onAppear {
      if selectedPane == .legacy {
        selectedPane = .app
      }
      if let hostId {
        settingsModel.selectHost(id: hostId)
      } else {
        settingsModel.selectHost(id: SettingsModel.globalHostId)
      }
    }
    .environment(\.defaultMinListRowHeight, 28)
    .dynamicTypeSize(.xSmall ... .xxxLarge)
  }

  // MARK: - Embedded chrome

  private var opaqueBase: some View {
    Color(nsColor: .controlBackgroundColor)
  }

  // Back control for the embedded page. It uses the built-in glass button
  // style rather than a hand-applied .glassEffect: the system style owns the
  // press, focus and hover response of glass, and reusing the tab bar geometry
  // keeps the two rows reading as one instrument panel.
  private var headerBar: some View {
    HStack(spacing: 0) {
      Button {
        onClose?()
      } label: {
        HStack(spacing: TabBarConfig.iconTextSpacing) {
          Image(systemName: "chevron.backward")
            .font(.system(size: TabBarConfig.iconSize, weight: .semibold))
          Text(languageManager.localize("Back"))
            .font(.system(size: TabBarConfig.fontSize, weight: .medium))
        }
        .foregroundStyle(TabBarConfig.accentCoolBlue)
        .frame(height: 28)
        .padding(.horizontal, 10)
        .contentShape(Rectangle())
      }
      .buttonStyle(.glass)
      .keyboardShortcut(.cancelAction)
      .accessibilityLabel(languageManager.localize("Back"))

    }
  }

  private var effectivePane: Pane {
    selectedPane == .legacy ? .app : selectedPane
  }
}

// One native segmented control survives both wide and narrow layouts. Measure
// the two small header views, never instantiate a second control just to test fit.
private struct SettingsNavigationLayout: Layout {
  struct Cache {
    var back: CGSize
    var navigation: CGSize
  }

  func makeCache(subviews: Subviews) -> Cache {
    Cache(back: subviews[0].sizeThatFits(.unspecified),
          navigation: subviews[1].sizeThatFits(.unspecified))
  }

  func updateCache(_ cache: inout Cache, subviews: Subviews) {
    cache = makeCache(subviews: subviews)
  }

  private func fits(_ width: CGFloat, _ cache: Cache) -> Bool {
    cache.navigation.width + (cache.back.width > 0 ? 2 * (cache.back.width + 16) : 0) <= width
  }

  func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
    let width = proposal.width ?? cache.navigation.width + 2 * (cache.back.width + 16)
    let height = fits(width, cache)
      ? max(cache.back.height, cache.navigation.height)
      : cache.back.height + 12 + cache.navigation.height
    return CGSize(width: width, height: height)
  }

  func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                     subviews: Subviews, cache: inout Cache) {
    let singleRow = fits(bounds.width, cache)
    subviews[0].place(at: CGPoint(x: bounds.minX,
                                 y: singleRow ? bounds.midY : bounds.minY + cache.back.height / 2),
                      anchor: .leading, proposal: ProposedViewSize(cache.back))
    subviews[1].place(at: CGPoint(x: bounds.midX,
                                 y: singleRow ? bounds.midY : bounds.maxY - cache.navigation.height / 2),
                      anchor: .center, proposal: ProposedViewSize(cache.navigation))
  }
}
