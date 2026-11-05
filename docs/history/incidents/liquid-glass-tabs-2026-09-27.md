## 窗口与分段控件性能优化

用户确认窗口拖动和分段滑动均卡。system_profiler 确认当前外接屏为 1920×1080 @ 180Hz；3 秒主线程采样主要为空闲等待，未采到实际拖动，不能从该采样推断拖动 FPS。

本次改动：
- 设置页由窗口四边约束尺寸，NSHostingController.sizingOptions=[]，停止对整个表单重复计算 min/ideal/max 尺寸。
- 用单个 SettingsNavigationLayout 保留一份原生分段控件，替代 ViewThatFits 中的两份控件。
- 分段标签、标记与宽度只在改变时写入，避免无效原生尺寸失效。
- 原生控制非连续发送；选择提交排到主 RunLoop.default，追踪中不构建页面，快速选择合并为最后一次，关闭后取消待提交选择。
- 根设置容器不再观察整份 SettingsModel 的所有发布；各 pane 继续通过 EnvironmentObject 更新自身。

验证：Release 构建、签名、玻璃审计和 git diff --check 通过。生产 presenter 与分段组件的离屏探针通过 214 项布局、交互提交时序和生命周期检查。简化内容对照测试（相同尺寸变化和分类选择）测量次数从 408 到 96；总耗时主要由探针主动等待构成，不能当实际性能提升比例或 FPS。该测试不是实际设置页 GPU 合成/拖动帧率测试。

官方参考：https://developer.apple.com/documentation/swiftui/nshostingview/sizingoptions
原生 UI 继续交由 AppKit/Core Animation 调度，本次没有实现自定义显示循环，也不声称锁定 180 FPS。正式应用已替换启动，报告 build-input-review/settings-performance-install-result.json。设置页 CUA 仍返回 native pipe closed，真实鼠标拖动帧率未完成自动测量。

---

## 布局与标题栏修订

用户认可原生控件效果，反馈布局松散、点击分类后不能移动窗口。本次保留原生分段控件，字号 13、每段至少 66pt；返回和导航在宽窗口同一行，窄窗口自动两行；正文居中限宽 920pt、外侧 24pt 间距。

主线程采样正常等待事件，没有发现卡死。主窗口启用了 fullSizeContentView，旧 presenter 将 NSHostingView 铺满 contentView，包含原生标题栏。现在设置展示期间暂时移除此样式，顶部约束使用 contentLayoutGuide，退出后恢复原来样式。系统标题栏和设置命中区域分离，不添加事件拦截或模拟拖动。

验证：Release 构建与签名检查通过；玻璃审计、diff 空白检查通过；scripts/probes/settings-window-layout.swift 直接编译生产 presenter 和分段控件、使用简化设置内容，在不显示的窗口中通过 210 项检查（两种初始窗口样式、三次展示/关闭、两种尺寸、反复分类切换、原生标题栏区域、恢复工具栏与标题）。用改动前 presenter 运行相同探针，因覆盖原生标题栏被拒绝。这是布局回归覆盖，并非真实鼠标拖动验收。

正式应用已替换启动，安装报告 build-input-review/settings-layout-install-result.json。正式设置页的 CUA 仍报告 native pipe closed，未能取得新版完整截图或进行实际拖动。全库 constraints-audit 存在本次未修改的键盘抑制计数、enhancement-report-tests CI 接线失败，且启动大量无关子测试，已停止；不将其报告为通过。

---

## 19:40 修订：以活动监视器分段控件为参照

用户明确提供活动监视器 CPU / 内存分段控件作为目标。此前自定义透镜方案不符合目标，已删除并改成 AppKit NSSegmentedControl（rounded、capsule、large、selectOne；macOS 27 使用 tabs role）。文字使用系统颜色与尺寸，不再强制蓝色选中项、760 宽轨道、自绘拉伸或拦截拖动。由系统提供液态交互、键盘操作及辅助功能。页面 ID 仍按 items 中的身份映射，音频等非连续 ID 不按下标处理。

Release 构建成功，玻璃审计及全部负对照通过，git diff --check 通过。审计允许原生分段控件自主管理玻璃，只有手动 glassEffect 才要求 GlassEffectContainer。安装签名及 SHA256 验证通过，报告为 build-input-review/native-segments-install-result.json。

同一生产组件在独立验证程序中由 AX 确认呈现 tab group，设备、音频、串流的选择变化正常。正式设置页 CUA 读取/截图返回 native pipe closed，独立程序被台前调度缩成缩略图，未取得可用于完整动效验收的画面。不能声称与参考逐帧一致。验证程序已关闭，正式应用已替换启动。

---

# 设置导航的 Liquid Glass 改造

用户指出旧导航只有玻璃条外观，缺少类似浮动 Tab Bar 的选中透镜滑动。保留顶部位置和既有六个设置分类，仅修改 LiquidGlassTabBar.swift 与 LiquidGlassSettingsView.swift。

旧实现使用 ForEach 条件创建选中块与普通 matchedGeometryEffect，28pt 内容高度，外层裁剪；未使用玻璃身份、玻璃过渡或拖动交互。新实现为固定身份的原生玻璃透镜，使用 GlassEffectContainer、glassEffect(.regular.tint(...).interactive())、glassEffectID 和 glassEffectTransition。尺寸与位置在 glassEffect 前定义，取消容器裁剪。玻璃与中性底槽分层，保留设置页不透明背景，避免设置页穿透主机列表。

导航最大宽度 760pt，内容高度 40pt；采用胶囊形状。点击执行显式动画事务，透镜连续移动并轻微伸缩；拖动只更新预览，松开才提交选中项并加载页面。身份使用原有非连续 pane ID，支持 RTL；窗口失焦、尺寸变化及页面离开清理拖动状态。保留 0.22s 无回弹曲线与冷蓝色约束，适配减少动态效果和减少透明度。

验证：Release 构建通过，第一方零警告；liquid-glass-audit 及负对照自检通过，diff 检查与严格签名通过。安装路径 /Applications/MoonlightEnhanced.app，SHA-256：46771af7ebe93a6a8744a19c0491b9bae10d67dd4737a4ed1679cb3941e6ce57。

视觉验收限制：设置页的自动操作服务再次返回 native pipe closed。从同一生产源构建独立预览，AX 点击确认“串流→视频→设备”正确切换选中状态。离屏 bitmap 无法获得可靠的 WindowServer 玻璃合成，不能用它证明视觉质量；预览截图处于台前调度缩略状态。尝试展开预览时工具报告 Mac 已锁屏，拖动及全尺寸动画验收待解锁后继续。未宣称完整视觉验收通过。

参考 Apple 官方：
https://developer.apple.com/documentation/swiftui/applying-liquid-glass-to-custom-views

本轮未修改已验收的键鼠输入实现。

## 解锁后的交互验证

用户解锁并将独立预览从台前调度展开后，获得 810×162 的完整窗口截图。同一份生产 LiquidGlassTabBar 源码在预览中实测：点击视频、设备和音频，选中状态正确；从设备向左拖到视频、从音频向右拖到应用，均正确提交对应的非连续 pane ID，松开后透镜落在目标按钮。截图确认胶囊尺寸、文字层级和选中位置正常。没有录制逐帧视频，因此不把静态截图当作所有动画帧无残影的证明。

已安装应用的设置页自动读取仍会导致工具 native pipe closed；此次完成的是生产组件的双向拖动、点击和完整尺寸显示验证，并非设置整页的自动化视觉验收。预览留在前台供用户查看。
