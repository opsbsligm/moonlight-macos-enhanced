# 键盘与鼠标映射设计（含已修复问题的根因记录）

> 读者：想弄清「为什么这样映射」的贡献者，以及准备改动输入路径的人。
> 使用者只需读 [`../README.md`](../README.md) 的一句话差异说明。
> 本页内容自 `README.md` 搬移而来（2026-09-24 文档信息架构重构），事实未删改。
> 逐项对标 Parsec、UU 远程、Citrix、moonlight-qt 的结论见 [`input-mapping-benchmark.md`](input-mapping-benchmark.md)。

## 串流标准键盘映射

采用与 **Parsec / UU 远程 / Steam Link** 一致的直接映射方案，彻底消除旧版兼容模式导致的映射混乱：

| macOS 物理键 | Windows HID 功能 |
|:---:|:---:|
| **Command (⌘)** 左/右 | Windows Win 键 (VK_LWIN 0x5B / VK_RWIN 0x5C) |
| **Control (⌃)** 左/右 | Windows Ctrl 键 (VK_LCTRL 0xA2 / VK_RCONTROL 0xA3) |
| **Option (⌥)** 左/右 | Windows Alt 键 (VK_LALT 0xA4 / VK_RALT 0xA5) |
| **Shift (⇧)** 左/右 | Windows Shift 键 (VK_LSHIFT 0xA0 / VK_RSHIFT 0xA1) |

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
