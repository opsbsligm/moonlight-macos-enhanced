//
//  LiquidGlassTabBar.swift
//  Moonlight for macOS
//
//  v14.0 — 完整重构版
//          ═══════════════════════════════════════════════════════
//          修复透明穿透：独立背景基底 + clipped边界裁剪 + zIndex层级锁定
//          纯原生 .glassEffect 液态玻璃 + matchedGeometryEffect 流体跟随
//          组件完全解耦，外部仅通过 selection Binding 通信
//          ═══════════════════════════════════════════════════════
//
//  渲染层级 (从底到顶):
//    L0  trackContainer   — 不透明基底 (controlBackgroundColor)，玻璃采样源
//    L1  glassPill        — 液态玻璃胶囊，matchedGeometryEffect 流体跟随
//    L2  tabButtonsRow    — 图标+文字按钮，最顶层确保可交互
//
//  隔离策略:
//    • trackContainer 提供实体背景，.glassEffect 采样此基底而非穿透到桌面
//    • glassPill 层 .clipped() 限制渲染范围，防止玻璃采样溢出
//    • 整个 ZStack .clipped() 确保玻璃效果不溢出容器边界
//    • zIndex 锁定三层顺序，切换动画中层纈权重不变
//

import SwiftUI

// MARK: - 可调参数集中区 ────────────────────────────────────────────
// 所有视觉/动画参数集中在此，方便微调玻璃通透度、光晕强度、动画速度。
// 修改参数后无需改动任何逻辑代码。

// Internal so the surrounding settings surface can reuse the same geometry,
// colour and animation constants instead of repeating them.
enum TabBarConfig {
  // ── 布局 (贴近 macOS 原生「设置 App」比例) ──
  static let tabBarHeight: CGFloat          = 28   // Tab 内容区高度
  static let containerCornerRadius: CGFloat = 10   // 容器圆角
  static let pillCornerRadius: CGFloat      = 8    // 选中胶囊圆角 (与容器比例 ~0.62)
  static let outerPadding: CGFloat          = 3    // 容器内边距
  static let interSpacing: CGFloat          = 2    // Tab 间距
  static let iconSize: CGFloat              = 12   // 图标尺寸
  static let iconTextSpacing: CGFloat       = 5    // 图标与文字间距
  static let fontSize: CGFloat              = 12   // 文字字号

  // ── 玻璃材质 (通透度调整) ──
  // ↓ glassTintOpacity → 更通透; ↑ → 更浓 (范围 0.0–1.0,建议 0.10–0.30)
  static let glassTintOpacity: Double       = 0.18

  // ── 选中高亮色 (冷调通透淡蓝，禁止橙/高饱和暖色) ──
  static let accentCoolBlue = Color(
    .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
  )

  // ── 外部柔光 (轻微泛光，不大面积扩散) ──
  // ↓ glowRadius / glowOpacity → 更克制; ↑ → 更明显
  static let glowRadius: CGFloat            = 3
  static let glowOpacity: Double            = 0.18

  // ── 动画 (流体跟随) ──
  static let animationDuration: Double      = 0.22  // 0.22s 持续时间
  // macOS 原生系统曲线近似 cubic Bezier (0.4, 0.0, 0.2, 1) — 无回弹、无顿挫
  static let curveCP1x: Double = 0.4
  static let curveCP1y: Double = 0.0
  static let curveCP2x: Double = 0.2
  static let curveCP2y: Double = 1.0

  // ── 容器基底 (修复透明穿透的关键参数) ──
  // trackContainer 使用 controlBackgroundColor 提供不透明基底，
  // .glassEffect 采样此基底而非穿透到桌面/下层页面。
  // containerBaseOpacity = 1.0 完全不透明; 降低可微调通透感但不建议低于 0.85
  static let containerBaseOpacity: Double   = 0.92
}

// MARK: - Data Model

public struct LiquidGlassTabItem: Identifiable {
  public let id: Int
  public let title: String
  public let symbol: String
  /// 保留字段以兼容调用方传入;实际渲染统一使用冷调淡蓝，忽略暖色 tint。
  public let tint: Color

  public init(id: Int, title: String, symbol: String, tint: Color) {
    self.id = id
    self.title = title
    self.symbol = symbol
    self.tint = tint
  }
}

// MARK: - Core Control

public struct LiquidGlassTabBar: View {
  @Binding public var selection: Int
  public let items: [LiquidGlassTabItem]

  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Namespace private var nsMorph

  /// 系统动画曲线 (macOS 原生 ease，无回弹)。
  /// reduceMotion 启用时返回 nil，禁用位移动画。
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
    GeometryReader { geo in
      let segW = segmentWidth(in: geo.size.width)

      // ════════════════════════════════════════════════════════════
      // ZStack 三层结构：基底 → 玻璃胶囊 → 按钮行
      // 整体 clipped() 确保玻璃效果渲染范围严格限制在容器内
      // ════════════════════════════════════════════════════════════
      ZStack(alignment: .topLeading) {
        // ── L0: 容器底槽 (不透明基底) ──────────────────────────
        // 提供实体背景，.glassEffect 采样此基底而非穿透到桌面。
        // 这是修复透明穿透问题的核心：禁止无基底裸渲染。
        trackContainer
          .zIndex(0)

        // ── L1: 选中胶囊 (原生 .glassEffect 液态玻璃) ──────────
        // 仅在选中 Tab 位置渲染，通过 matchedGeometryEffect 流体跟随位移。
        // clipped() 限制渲染范围，防止玻璃采样溢出到容器外。
        HStack(spacing: TabBarConfig.interSpacing) {
          ForEach(items) { item in
            if item.id == selection {
              glassPill(width: segW)
                .matchedGeometryEffect(id: "selectionPill", in: nsMorph)
            } else {
              Color.clear
                .frame(width: segW, height: TabBarConfig.tabBarHeight)
            }
          }
        }
        .padding(.horizontal, TabBarConfig.outerPadding)
        .padding(.vertical, TabBarConfig.outerPadding)
        .clipped()                    // ← 边界裁剪：限制玻璃渲染范围
        .zIndex(1)                    // ← 层级锁定：玻璃层在基底之上
        .animation(reduceMotion ? nil : fluidAnimation, value: selection)

        // ── L2: Tab 按钮行 (图标 + 文字，水平居中) ─────────────
        // 最顶层确保可交互，玻璃胶囊在按钮下方不影响点击。
        tabButtonsRow(segmentWidth: segW)
          .zIndex(2)                  // ← 层级锁定：按钮在最顶层
      }
      .frame(
        width: geo.size.width,
        height: TabBarConfig.tabBarHeight + 2 * TabBarConfig.outerPadding
      )
      .clipped()                      // ← 整体裁剪：玻璃效果绝不溢出容器
    }
    .frame(height: TabBarConfig.tabBarHeight + 2 * TabBarConfig.outerPadding)
  }

  // MARK: - 容器底槽 (L0: 不透明基底)
  // v14 重构核心修复：恢复不透明基底。
  // 使用 controlBackgroundColor 提供实体背景，.glassEffect 采样此基底
  // 而非穿透到桌面/下层页面。这是修复透明穿透的关键。
  //
  // v13 的 Color.clear 导致玻璃效果采样不到任何实体背景，
  // 穿透到桌面壁纸，造成"完全透明"问题。
  private var trackContainer: some View {
    RoundedRectangle(
      cornerRadius: TabBarConfig.containerCornerRadius,
      style: .continuous
    )
    .fill(Color(nsColor: .controlBackgroundColor))
    .opacity(TabBarConfig.containerBaseOpacity)
  }

  // MARK: - 玻璃胶囊 (L1: 原生 macOS 26 .glassEffect)
  // 不使用任何手工渐变 / 模糊模拟，纯原生液态玻璃材质。
  // .glassEffect 采样下方的 trackContainer 基底，渲染冷调通透淡蓝玻璃。
  @ViewBuilder
  private func glassPill(width: CGFloat) -> some View {
    RoundedRectangle(
      cornerRadius: TabBarConfig.pillCornerRadius,
      style: .continuous
    )
    .fill(Color.clear)
    .frame(width: width, height: TabBarConfig.tabBarHeight)
    .glassEffect(
      .regular.tint(
        TabBarConfig.accentCoolBlue.opacity(TabBarConfig.glassTintOpacity)
      ),
      in: RoundedRectangle(
        cornerRadius: TabBarConfig.pillCornerRadius,
        style: .continuous
      )
    )
    // 外部轻微柔和泛光 — 小 radius 确保不大面积扩散
    .shadow(
      color: TabBarConfig.accentCoolBlue.opacity(TabBarConfig.glowOpacity),
      radius: TabBarConfig.glowRadius,
      x: 0, y: 0
    )
  }

  // MARK: - Geometry
  // 根据容器总宽度和 Tab 数量计算每个 Tab 的等分宽度。
  // 窗口缩放时 GeometryReader 自动重算，指示器位置同步修正。
  private func segmentWidth(in totalWidth: CGFloat) -> CGFloat {
    let count = CGFloat(max(1, items.count))
    return (totalWidth
            - 2 * TabBarConfig.outerPadding
            - CGFloat(max(0, items.count - 1)) * TabBarConfig.interSpacing) / count
  }

  // MARK: - Tab 按钮行 (L2: 图标 + 文字)
  private func tabButtonsRow(segmentWidth: CGFloat) -> some View {
    HStack(alignment: .center, spacing: TabBarConfig.interSpacing) {
      ForEach(items) { item in
        let isSelected = item.id == selection
        Button {
          selection = item.id
        } label: {
          HStack(spacing: TabBarConfig.iconTextSpacing) {
            Image(systemName: item.symbol)
              .font(.system(size: TabBarConfig.iconSize,
                            weight: isSelected ? .semibold : .medium))
              .symbolRenderingMode(.hierarchical)
            Text(item.title)
              .font(.system(size: TabBarConfig.fontSize,
                            weight: isSelected ? .semibold : .regular))
              .lineLimit(1)
              .minimumScaleFactor(0.6)
              .allowsTightening(true)
          }
          .foregroundStyle(isSelected ? TabBarConfig.accentCoolBlue : Color.secondary)
          .frame(width: segmentWidth, height: TabBarConfig.tabBarHeight, alignment: .center)
          .contentShape(
            RoundedRectangle(cornerRadius: TabBarConfig.pillCornerRadius, style: .continuous)
          )
        }
        .buttonStyle(.plain)
        .focusable(false)
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityLabel(Text(item.title))
      }
    }
    .padding(.horizontal, TabBarConfig.outerPadding)
    .padding(.vertical, TabBarConfig.outerPadding)
  }
}

// MARK: - 可调参数清单 ────────────────────────────────────────────
// ┌─────────────────────────────────────────────────────────────┐
// │ 参数名                    │ 默认值  │ 说明                    │
// ├───────────────────────────┼─────────┼────────────────────────┤
// │ glassTintOpacity          │ 0.18    │ 玻璃着色透明度 (0-1)    │
// │ glowRadius                │ 3       │ 外部柔光半径 (pt)       │
// │ glowOpacity               │ 0.18    │ 柔光透明度 (0-1)        │
// │ animationDuration         │ 0.22    │ 动画时长 (秒)           │
// │ pillCornerRadius          │ 8       │ 胶囊圆角 (pt)           │
// │ containerCornerRadius     │ 10      │ 容器圆角 (pt)           │
// │ containerBaseOpacity      │ 0.92    │ 基底不透明度 (0.85-1.0) │
// │ tabBarHeight              │ 28      │ Tab 高度 (pt)           │
// │ accentCoolBlue            │ #58A0F2 │ 冷调淡蓝高亮色          │
// │ curveCP1x/y, CP2x/y       │ 见上    │ 动画贝塞尔曲线控制点    │
// └─────────────────────────────────────────────────────────────┘
//
// 调参指南:
// • 玻璃更通透 → 降低 glassTintOpacity (如 0.12)
// • 玻璃更浓郁 → 升高 glassTintOpacity (如 0.25)
// • 柔光更明显 → 升高 glowRadius + glowOpacity
// • 动画更快/慢 → 调整 animationDuration
// • 基底更不透明 → 升高 containerBaseOpacity (建议不低于 0.85)
