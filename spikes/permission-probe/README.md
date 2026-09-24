# permission probe（权限段读法的实测依据）

`docs/diagnostics-report.md` 与诊断报告的 `permissions` 段照着这里读。

```sh
clang -fobjc-arc -Wall -Werror=incompatible-pointer-types \
      -isysroot "$(xcrun --sdk macosx --show-sdk-path)" \
      -framework AppKit -framework ApplicationServices \
      -o /tmp/probe2.bin spikes/permission-probe/probe2.m && /tmp/probe2.bin
```

## 它证明了什么（macOS 27.2 / 26B5091g，本机）

* **`CGWindowListCopyWindowInfo` 看不到一个还没映射的窗口。** 窗口刚创建、`isVisible=no` 时
  `kCGWindowListOptionAll|kCGWindowListOptionOnScreenOnly` 返回 33 条且**不含自己的 windowNumber**；
  `makeKeyAndOrderFront:` 加一个 runloop 之后同样调用返回 35 条且**含自己的号**（`own=YES`）。
  所以 `isWindowInCurrentSpace`（`StreamViewController+WindowModes.m:527`）在窗口真的上过屏的前提下
  拿得到自己——它没有坏。
* **上屏后四种 option 组合都能看见自己**：`All|OnScreenOnly` 35、`OnScreenOnly` 35、`All` 187、
  `OnScreenOnly|ExcludeDesktopElements` 29。

## 它没证明什么（别拿它当结论）

* **屏幕录制未授予时的行为没测到。** 我本来以为命令行工具天然处于「未授予」，实测**本机是全部已授予**：
  `CGPreflightScreenCaptureAccess=yes`、`AXIsProcessTrusted=trusted`、HID `granted/granted`。
  要测未授予分支得先撤销授权，那需要人动系统设置，不由这个 spike 代做。
* 探针是 `ActivationPolicyAccessory` 的裸二进制，不是 app bundle，也不是目标 app 本身；
  WindowServer 视角下同类，但不等于在串流窗口里逐条验证过。

## 因此报告的 `permissions` 段这么写

`screen recording` 一项继续测量（门禁要求它在报告里），但**不把二值答案当因果结论**：
本 build 不调用任何像素捕获 API（`ScreenCaptureKit` / `SCStream` / `CGDisplayCreateImage` /
`CGDisplayStream` 全仓 0 命中，`CGPreflightScreenCaptureAccess` 只有报告自己这一处），
唯一的 `CGWindowListCopyWindowInfo` 只比对自己的 window number，
而**未授予会怎样，本仓库没有实测**——这句话印在报告里，而不是留给读报告的人猜。
