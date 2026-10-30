Sunshine 主机侧手柄类型处置快照（2026-10-30 抓取）

钉住版本：分支 `master`，commit `a679b059096bcdd502e2192ce4f6a3c3732fbaae`
（提交时间 2026-10-28T16:50:07Z）。抓取方式为 `raw.githubusercontent.com` 按 commit 取原始文件，
SHA-256 `2af306a6068140fb7804bd1b919ec0addccd7c2b3fdf29650df013e3bad9b1f7`。

| 文件 | 上游路径 | git blob SHA |
| --- | --- | --- |
| `windows_input.cpp` | `src/platform/windows/input.cpp` | `73f2acf03837ba990f03a0b07c7bb179167ef53e` |

关键行号（本快照内，供 roadmap §2.1 的"主机侧真正拿到什么"引用核对）：

- ViGEm 类型选择块：`windows_input.cpp:684-705`
- 客户端上报类型的两个分支：`metadata.type == LI_CTYPE_PS` → `DualShock4Wired`（`:690-692`）、
  `metadata.type == LI_CTYPE_XBOX` → `Xbox360Wired`（`:693-695`）
- 其余类型（含 `LI_CTYPE_STEAM`、`LI_CTYPE_NINTENDO`、`LI_CTYPE_UNKNOWN`）继续往下走：
  按 capabilities 判 DS4（`:696-701`，需 `motion_as_ds4`/`touchpad_as_ds4` 配置开启），
  否则落 `Xbox360Wired (default)`（`:702-704`）
- 手动覆盖：`config::input.gamepad == "x360"|"ds4"`（`:684-689`）优先于任何自动判定
- Xbox 360 模拟下运动传感器不可用的显式告警：`:707-709`

结论边界：这只证明 Windows 平台的 ViGEm 路径怎么读 `metadata.type`，不外推到 GFE
（NVIDIA GameStream 主机侧未取证）、也不证明任何游戏内图标表现。
