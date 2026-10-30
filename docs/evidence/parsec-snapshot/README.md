Parsec macOS 客户端主机侧输入机制快照（2026-10-30 抓取）

钉住对象：本机已安装的 Parsec.app（`CFBundleIdentifier tv.parsec.www`，
`CFBundleShortVersionString` / `CFBundleVersion` 均为 `150.101.1`，
`LSMinimumSystemVersion 10.9.0`，可执行体与库均为 x86_64 + arm64 通用二进制）。
被检文件是宿主守护进程的动态库：

```
/Applications/Parsec.app/Contents/Resources/skel/parsecd-150-101a.dylib
size      6,235,664 bytes
SHA-256   9cce85059c7f95f1a8e578b3c9f7200cb364520e557b5c85294802c8c596cdd5
```

二进制不入库（第三方分发物，且 5.9 MiB 无复核价值）。复核方式是在装有同版本 Parsec 的
macOS 上重跑：

```sh
D=/Applications/Parsec.app/Contents/Resources/skel/parsecd-150-101a.dylib
shasum -a 256 "$D"                       # 应等于上面的 SHA-256
strings -a "$D" | grep -Ex \
  'host_gamepad_mode|host_gamepad_type|host_virtual_mouse|host_virtual_tablet|host_exclusive_input|client_png_cursor' | sort -u
strings -a "$D" | grep -E '^host_virtual' | sort -u
strings -a "$D" | grep -i 'vigem' | sort -u
```

## 能证明什么（机制级）

输入面的相关配置键（同一 `strings` pass 命中，均为完整键名匹配）：

| 键 | 机制含义（键名本身的语义，不含实现） |
| --- | --- |
| `host_virtual_mouse` | 主机侧存在"虚拟鼠标"开关，即注入路径可选虚拟 HID 而非系统级合成 |
| `host_virtual_tablet` | 主机侧另有虚拟平板/数字化仪路径，即**绝对坐标**是独立于相对鼠标的第二条注入通道 |
| `host_gamepad_mode` | 主机侧手柄注入模式可配（是否启用/采用哪条路径） |
| `host_gamepad_type` | 主机侧虚拟手柄**类型**可配，即客户端上报的类型会影响主机设备类型 |
| `host_exclusive_input` | 存在独占输入模式（主机本地输入被抑制） |
| `client_png_cursor` | 客户端侧光标以 PNG 位图形式承载（自定义光标的传输形态） |

同一 `host_virtual` 前缀下还存在 `camera` / `microphone` / `monitors` /
`usb_passthrough` / `usb_tracing`，说明它把"主机侧虚拟设备"当成统一的一族能力，
其中 `usb_passthrough` 正是我们**主动冻结**的那一项（依赖 Developer ID 分发）。

虚拟手柄后端的线索只有这些：命中 `ViGEm`、`https://github.com/ViGEm/ViGEmBus`、
`vigem_installed`、`XInput`、`Xbox`；即 Windows 侧同样走 ViGEmBus 一类驱动，
且存在"是否已安装"的运行时判断。客户端侧另有
`org_pqrs_Karabiner_DriverKit_VirtualHIDKeyboard` 与
"Using Karabiner compatibility for IOHID access."，说明 macOS 侧键盘注入考虑了
Karabiner 虚拟 HID 的兼容性。

未命中的标识：`DS4` / `DualShock` / `DualSense` / `joycon` / `ProController` /
`virtual_gamepad` / `ps4` / `ps5`（`ps5` 仅命中 `uEpS5` 这类噪声串，不计）。

## 边界（必须与上表一起引用）

- 字符串存在只证明**机制存在与可配置**，不证明默认值、取值域、支持的类型集合，
  也不证明任何手感或延迟表现。
- 未做运行时验证：没有抓包、没有反汇编取值域、没有观察主机设备枚举结果。
- 与我们的对照只到"Parsec 也把虚拟鼠标/手柄类型做成配置项"这一层，
  足以把 roadmap §2.5 的 Parsec 行从"无证据"提升为"机制级证据"，
  **不足以支撑任何"我们超过/不如 Parsec"的结论**（roadmap §4 的禁令继续有效）。
- 未出现 DS4/DualSense/Switch 标识可能是"不支持"，也可能是字符串被裁剪或键名在别处
  （`host_gamepad_type` 的取值域没有以配置键形式出现在同一次扫描里），
  本次快照无法区分，**不得据此断言 Parsec 缺少 PS/任天堂手柄支持**。
- `host_virtual_usb_passthrough` 只证明 Parsec 有该能力族，不构成解冻我们 USB 重定向的理由；
  解冻条件仍是 Developer ID 分发，由用户决定。
