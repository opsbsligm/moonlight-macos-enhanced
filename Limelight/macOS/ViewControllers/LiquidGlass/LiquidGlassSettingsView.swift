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
  @StateObject var settingsModel = SettingsModel()
  @ObservedObject var languageManager = LanguageManager.shared

  @AppStorage("selected-settings-pane") private var selectedPane: Pane = .stream

  var hostId: String?
  /// Supplied when the view is embedded in the main window. Draws a back
  /// control and reports dismissal so the presenter can remove the page.
  var onClose: (() -> Void)?

  init(hostId: String? = nil, onClose: (() -> Void)? = nil) {
    self.hostId = hostId
    self.onClose = onClose
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
          case .legacy:
            EmptyView()
          }
        }
        .environmentObject(settingsModel)
      }
      .padding(.horizontal, 20)
      .padding(.top, 8)
      .padding(.bottom, 20)
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .scrollContentBackground(.hidden)
    .safeAreaInset(edge: .top, spacing: 0) {
      VStack(spacing: 8) {
        if onClose != nil {
          headerBar
            .padding(.horizontal, 20)
            .padding(.top, 12)
        }
        // TabBar 自带独立 trackContainer 基底，无需依赖外部透明背景。
        LiquidGlassTabBar(selection: selectionBinding, items: tabs)
          .padding(.horizontal, 20)
          .padding(.top, onClose == nil ? 14 : 0)
          .padding(.bottom, 10)
      }
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
        .frame(height: TabBarConfig.tabBarHeight)
        .padding(.horizontal, 10)
        .contentShape(Rectangle())
      }
      .buttonStyle(.glass)
      .keyboardShortcut(.cancelAction)
      .accessibilityLabel(languageManager.localize("Back"))

      Spacer(minLength: 0)
    }
  }

  private var effectivePane: Pane {
    selectedPane == .legacy ? .app : selectedPane
  }
}
