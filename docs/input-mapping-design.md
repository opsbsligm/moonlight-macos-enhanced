# 键盘与鼠标映射设计（含已修复问题的根因记录）

> 读者：想弄清「为什么这样映射」的贡献者，以及准备改动输入路径的人。
> 使用者只需读 [`../README.md`](../README.md) 的一句话差异说明。
> 本页内容自 `README.md` 搬移而来（2026-09-24 文档信息架构重构），事实未删改。
> 逐项对标 Parsec、UU 远程、Citrix、moonlight-qt 的结论见 [`input-mapping-benchmark.md`](input-mapping-benchmark.md)。

## 串流标准键盘映射

采用与 **Parsec / UU 远程 / Steam Link** 一致的直接映射方案，彻底消除旧版兼容模式导致的映射混乱：

| macOS 物理键 | Windows 虚拟键（Win32 VK） |
|:---:|:---:|
| **Command (⌘)** 左/右 | Windows Win 键 (VK_LWIN 0x5B / VK_RWIN 0x5C) |
| **Control (⌃)** 左/右 | Windows Ctrl 键 (VK_LCTRL 0xA2 / VK_RCONTROL 0xA3) |
| **Option (⌥)** 左/右 | Windows Alt 键 (VK_LALT 0xA4 / VK_RALT 0xA5) |
| **Shift (⇧)** 左/右 | Windows Shift 键 (VK_LSHIFT 0xA0 / VK_RSHIFT 0xA1) |

> **这些值是 Win32 虚拟键码，不是 HID scancode。** `LiSendKeyboardEvent()` 的契约写明了这点
> （`Limelight.h:832-840`：*“Key codes are Win32 Virtual Key (VK) codes and interpreted as keys
> on a US English layout.”*）：我们把 macOS 的**物理位置**查成 US 布局上的 VK，宿主拿到之后自己
> 反查 scancode。整张 `keys[]` 表的值域已被审计钉在 Microsoft 官方定义的 VK 上
> （`scripts/mac_keycodes.py`、`docs/input-mapping-review.md` §2–§3）。

- **零延迟**：修饰键按下即发送，无 120ms 延迟判定
- **零耦合**：鼠标事件不会影响键盘修饰键状态（修复了「双击鼠标触发开始菜单」的根因）
- **单一真相源**：所有映射通过 `KeyboardMapResolver` 的静态表驱动，无运行时分支

## 设计原则（CI/CD 最佳实践）

1. **单一真相源 (Single Source of Truth)**
   - 所有映射逻辑集中在 `KeyboardMapResolver`，通过静态表 `s_mapTable` 定义
   - 消除了旧版 4 处重复 switch/case 映射

2. **无状态 (Stateless)**
   - 映射函数是纯函数，无副作用，无全局变量
   - 修饰键状态由 `flagsChanged:` 事件驱动，不依赖定时器或状态机

3. **零耦合 (Zero Coupling)**
   - 鼠标事件路径完全不触碰键盘修饰键状态
   - `HIDEffectivePhysicalModifierMaskForEvent()` 不再从 `event.modifierFlags` 推断修饰键

4. **可测试性 (Testable)**
   - 映射表在编译期确定，可通过单元测试验证
   - `KMR_LogActiveMapping()` 在启动时打印完整映射矩阵

## 修复的关键 Bug

**「双击鼠标触发 Windows 开始菜单」根因分析：**
- 旧版 `HIDEffectivePhysicalModifierMaskForEvent()` 会从鼠标事件的 `event.modifierFlags` 中推断修饰键状态
- 当用户按住 ⌘ + 点击鼠标时，鼠标事件携带 `NSEventModifierFlagCommand` → 被注入物理掩码 → 触发 VK_LWIN DOWN
- **修复**：该函数现在完全忽略 `event.modifierFlags`，物理修饰键状态只从键盘事件追踪

## 完整映射表（`keys[]` 全 114 行）

README 承诺「完整的键位映射表」，这一节就是那张表。它**不是手写**的：内容按 `HIDSupport.m:89`
的 `keys[]` 逐行渲染，kVK 名经 `scripts/mac_keycodes.py` 的 `KVK_CODES` 解析成数字，Windows 侧的
名称与十六进制码取自同一文件里的 `WINDOWS_VK_DEFINED`（Microsoft 官方 VK 表）。

- 第 2 列是 macOS 的**虚拟键码**（`kVK_*`，代表物理位置，与输入法/布局无关）。
- 第 3 列是发到宿主机上的 **Win32 VK**：字母/数字行的官方名称本身就是 `A`、`1` 这种单字符，
  其余是 `VK_F17`、`VK_VOLUME_UP` 这类带前缀的名字。协议只传 VK，不传 scancode（见上文引用）。
- 表格数据行数与 `keys[]` 行数由 `scripts/constraints-audit.py` 比对，表里少一行或多一行都会红；
  改了 `keys[]` 就重新渲染这一节。


### 字母、数字与标点（US 布局的物理位置）（48 项）

| macOS 键（`keys[]` 行原文） | kVK | Windows 侧 |
|:---|:---:|:---|
| `kVK_ANSI_A` | 0 | `A` `0x41` |
| `kVK_ANSI_B` | 11 | `B` `0x42` |
| `kVK_ANSI_C` | 8 | `C` `0x43` |
| `kVK_ANSI_D` | 2 | `D` `0x44` |
| `kVK_ANSI_E` | 14 | `E` `0x45` |
| `kVK_ANSI_F` | 3 | `F` `0x46` |
| `kVK_ANSI_G` | 5 | `G` `0x47` |
| `kVK_ANSI_H` | 4 | `H` `0x48` |
| `kVK_ANSI_I` | 34 | `I` `0x49` |
| `kVK_ANSI_J` | 38 | `J` `0x4A` |
| `kVK_ANSI_K` | 40 | `K` `0x4B` |
| `kVK_ANSI_L` | 37 | `L` `0x4C` |
| `kVK_ANSI_M` | 46 | `M` `0x4D` |
| `kVK_ANSI_N` | 45 | `N` `0x4E` |
| `kVK_ANSI_O` | 31 | `O` `0x4F` |
| `kVK_ANSI_P` | 35 | `P` `0x50` |
| `kVK_ANSI_Q` | 12 | `Q` `0x51` |
| `kVK_ANSI_R` | 15 | `R` `0x52` |
| `kVK_ANSI_S` | 1 | `S` `0x53` |
| `kVK_ANSI_T` | 17 | `T` `0x54` |
| `kVK_ANSI_U` | 32 | `U` `0x55` |
| `kVK_ANSI_V` | 9 | `V` `0x56` |
| `kVK_ANSI_W` | 13 | `W` `0x57` |
| `kVK_ANSI_X` | 7 | `X` `0x58` |
| `kVK_ANSI_Y` | 16 | `Y` `0x59` |
| `kVK_ANSI_Z` | 6 | `Z` `0x5A` |
| `kVK_ANSI_0` | 29 | `0` `0x30` |
| `kVK_ANSI_1` | 18 | `1` `0x31` |
| `kVK_ANSI_2` | 19 | `2` `0x32` |
| `kVK_ANSI_3` | 20 | `3` `0x33` |
| `kVK_ANSI_4` | 21 | `4` `0x34` |
| `kVK_ANSI_5` | 23 | `5` `0x35` |
| `kVK_ANSI_6` | 22 | `6` `0x36` |
| `kVK_ANSI_7` | 26 | `7` `0x37` |
| `kVK_ANSI_8` | 28 | `8` `0x38` |
| `kVK_ANSI_9` | 25 | `9` `0x39` |
| `kVK_ANSI_Equal` | 24 | `VK_OEM_PLUS` `0xBB` |
| `kVK_ANSI_Minus` | 27 | `VK_OEM_MINUS` `0xBD` |
| `kVK_ANSI_RightBracket` | 30 | `VK_OEM_6` `0xDD` |
| `kVK_ANSI_LeftBracket` | 33 | `VK_OEM_4` `0xDB` |
| `kVK_ANSI_Quote` | 39 | `VK_OEM_7` `0xDE` |
| `kVK_ANSI_Semicolon` | 41 | `VK_OEM_1` `0xBA` |
| `kVK_ANSI_Backslash` | 42 | `VK_OEM_5` `0xDC` |
| `kVK_ANSI_Comma` | 43 | `VK_OEM_COMMA` `0xBC` |
| `kVK_ANSI_Slash` | 44 | `VK_OEM_2` `0xBF` |
| `kVK_ANSI_Period` | 47 | `VK_OEM_PERIOD` `0xBE` |
| `kVK_ANSI_Grave` | 50 | `VK_OEM_3` `0xC0` |
| `kVK_ISO_Section` | 10 | `VK_OEM_102` `0xE2` |

### 小键盘（18 项）

| macOS 键（`keys[]` 行原文） | kVK | Windows 侧 |
|:---|:---:|:---|
| `kVK_ANSI_KeypadDecimal` | 65 | `VK_DECIMAL` `0x6E` |
| `kVK_ANSI_KeypadMultiply` | 67 | `VK_MULTIPLY` `0x6A` |
| `kVK_ANSI_KeypadPlus` | 69 | `VK_ADD` `0x6B` |
| `kVK_ANSI_KeypadClear` | 71 | `VK_OEM_CLEAR` `0xFE` |
| `kVK_ANSI_KeypadDivide` | 75 | `VK_DIVIDE` `0x6F` |
| `kVK_ANSI_KeypadEnter` | 76 | `VK_RETURN` `0x0D` |
| `kVK_ANSI_KeypadMinus` | 78 | `VK_SUBTRACT` `0x6D` |
| `kVK_ANSI_KeypadEquals` | 81 | `VK_OEM_PLUS` `0xBB` |
| `kVK_ANSI_Keypad0` | 82 | `VK_NUMPAD0` `0x60` |
| `kVK_ANSI_Keypad1` | 83 | `VK_NUMPAD1` `0x61` |
| `kVK_ANSI_Keypad2` | 84 | `VK_NUMPAD2` `0x62` |
| `kVK_ANSI_Keypad3` | 85 | `VK_NUMPAD3` `0x63` |
| `kVK_ANSI_Keypad4` | 86 | `VK_NUMPAD4` `0x64` |
| `kVK_ANSI_Keypad5` | 87 | `VK_NUMPAD5` `0x65` |
| `kVK_ANSI_Keypad6` | 88 | `VK_NUMPAD6` `0x66` |
| `kVK_ANSI_Keypad7` | 89 | `VK_NUMPAD7` `0x67` |
| `kVK_ANSI_Keypad8` | 91 | `VK_NUMPAD8` `0x68` |
| `kVK_ANSI_Keypad9` | 92 | `VK_NUMPAD9` `0x69` |

### 控制、导航与编辑（25 项）

| macOS 键（`keys[]` 行原文） | kVK | Windows 侧 |
|:---|:---:|:---|
| `kVK_ContextualMenu` | 110 | `VK_APPS` `0x5D` |
| `kVK_Delete` | 51 | `VK_BACK` `0x08` |
| `kVK_Tab` | 48 | `VK_TAB` `0x09` |
| `kVK_Return` | 36 | `VK_RETURN` `0x0D` |
| `kVK_Shift` | 56 | `VK_LSHIFT` `0xA0` |
| `kVK_Control` | 59 | `VK_LCONTROL` `0xA2` |
| `kVK_Option` | 58 | `VK_LMENU` `0xA4` |
| `kVK_CapsLock` | 57 | `VK_CAPITAL` `0x14` |
| `kVK_Escape` | 53 | `VK_ESCAPE` `0x1B` |
| `kVK_Space` | 49 | `VK_SPACE` `0x20` |
| `kVK_PageUp` | 116 | `VK_PRIOR` `0x21` |
| `kVK_PageDown` | 121 | `VK_NEXT` `0x22` |
| `kVK_End` | 119 | `VK_END` `0x23` |
| `kVK_Home` | 115 | `VK_HOME` `0x24` |
| `kVK_LeftArrow` | 123 | `VK_LEFT` `0x25` |
| `kVK_UpArrow` | 126 | `VK_UP` `0x26` |
| `kVK_RightArrow` | 124 | `VK_RIGHT` `0x27` |
| `kVK_DownArrow` | 125 | `VK_DOWN` `0x28` |
| `kVK_ForwardDelete` | 117 | `VK_DELETE` `0x2E` |
| `kVK_Help` | 114 | `VK_HELP` `0x2F` |
| `kVK_Command` | 55 | `VK_LWIN` `0x5B` |
| `kVK_RightCommand` | 54 | `VK_RWIN` `0x5C` |
| `kVK_RightShift` | 60 | `VK_RSHIFT` `0xA1` |
| `kVK_RightOption` | 61 | `VK_RMENU` `0xA5` |
| `kVK_RightControl` | 62 | `VK_RCONTROL` `0xA3` |

### 功能键（20 项）

| macOS 键（`keys[]` 行原文） | kVK | Windows 侧 |
|:---|:---:|:---|
| `kVK_F1` | 122 | `VK_F1` `0x70` |
| `kVK_F2` | 120 | `VK_F2` `0x71` |
| `kVK_F3` | 99 | `VK_F3` `0x72` |
| `kVK_F4` | 118 | `VK_F4` `0x73` |
| `kVK_F5` | 96 | `VK_F5` `0x74` |
| `kVK_F6` | 97 | `VK_F6` `0x75` |
| `kVK_F7` | 98 | `VK_F7` `0x76` |
| `kVK_F8` | 100 | `VK_F8` `0x77` |
| `kVK_F9` | 101 | `VK_F9` `0x78` |
| `kVK_F10` | 109 | `VK_F10` `0x79` |
| `kVK_F11` | 103 | `VK_F11` `0x7A` |
| `kVK_F12` | 111 | `VK_F12` `0x7B` |
| `kVK_F13` | 105 | `VK_F13` `0x7C` |
| `kVK_F14` | 107 | `VK_F14` `0x7D` |
| `kVK_F15` | 113 | `VK_F15` `0x7E` |
| `kVK_F16` | 106 | `VK_F16` `0x7F` |
| `kVK_F17` | 64 | `VK_F17` `0x80` |
| `kVK_F18` | 79 | `VK_F18` `0x81` |
| `kVK_F19` | 80 | `VK_F19` `0x82` |
| `kVK_F20` | 90 | `VK_F20` `0x83` |

### 媒体键（3 项）

| macOS 键（`keys[]` 行原文） | kVK | Windows 侧 |
|:---|:---:|:---|
| `kVK_Mute` | 74 | `VK_VOLUME_MUTE` `0xAD` |
| `kVK_VolumeDown` | 73 | `VK_VOLUME_DOWN` `0xAE` |
| `kVK_VolumeUp` | 72 | `VK_VOLUME_UP` `0xAF` |
