//
//  LiquidGlassSettingsView.swift
//  Moonlight for macOS
//
//  macOS 26 Liquid Glass settings view.
//  v12.0 — 修复透明穿透：移除 Color.clear 背景，改用 GlassView 实体材质
//          作为整个视图的背景基底。TabBar 自带独立 trackContainer 基底，
//          玻璃效果采样实体背景而非穿透到桌面。
//          注意：宿主 SettingsHostingController 使用标准不透明窗口
//          （无 .fullSizeContentView、titlebarAppearsTransparent=false），
//          TabBar 通过 .safeAreaInset 布局在内容区顶部，位于标题栏下方，
//          并不进入标题栏扩展区，也不与系统标题栏材质融合。
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

  init(hostId: String? = nil) {
    self.hostId = hostId
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

    // Root: a single ScrollView. The tab bar is injected into the top safe
    // area via .safeAreaInset(edge: .top), placing it at the top of the
    // content region. Because the hosting SettingsHostingController uses a
    // standard opaque window (no .fullSizeContentView), the tab bar sits
    // below the AppKit title bar rather than extending into it; it does not
    // share or fuse with the system title bar material.
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
      // Tab bar sits at the top of the opaque content region (below the
      // AppKit title bar — the host window has no .fullSizeContentView).
      // TabBar 自带独立 trackContainer 基底，无需依赖外部透明背景。
      LiquidGlassTabBar(selection: selectionBinding, items: tabs)
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 10)
    }
    // v12: 实体材质背景 — SwiftUI .regularMaterial
    // 提供不透明 frosted glass 基底，替代 v11 的 Color.clear。
    // 玻璃效果采样此基底，不再穿透到桌面。
    .background(.regularMaterial)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .frame(minWidth: 640, idealWidth: 900, maxWidth: .infinity,
           minHeight: 520, idealHeight: 680, maxHeight: .infinity)
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

  private var effectivePane: Pane {
    selectedPane == .legacy ? .app : selectedPane
  }
}
