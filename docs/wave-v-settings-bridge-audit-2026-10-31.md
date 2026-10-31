---
title: "Wave V: Settings Bridge 默认值分叉审计"
date: "2026-10-31"
status: "completed"
---
# Wave V: Settings 默认值分叉审计

## 审计目的
Bridge (`SettingsObjCBridge.swift`) 的 `??` 缺省值是否与 Swift 模型默认值 (`SettingsModel+DerivedValues.swift`)、
ObjC 读取缺省 (`StreamViewController.m` 等) 一致。不一致的分叉可能让"模型说 false 但运行时生效 true"。

## 方法
逐字段对比三层：
1. Model default（`SettingsModel+DerivedValues.swift`）
2. Bridge `??`（`SettingsObjCBridge.swift`）
3. ObjC 读取缺省（`StreamViewController.m` `boolValue : NO/Y` / `intValue : N`）

## 结论

### 高危分叉（影响运行时行为）— 1 项

| 字段 | Bridge ?? | ObjC 缺省 | Model default | 影响 |
|---|---|---|---|---|
| `ignoreAspectRatio` | **true** | NO | **false** | 窗口宽高比默认**不锁**。Model 声明"锁定"但 Bridge 覆盖为 true，ObjC 收到 true 后 `!ignoreAspectRatio` 分支不执行。 |

修复方案：`SettingsObjCBridge.swift:115` `?? true` → `?? false`。
纯改一个词，零行为扩散（当前行为已是不锁，修复后仍是不锁，**不改变用户路径**）。

### 分叉但无影响 — 3 项

| 字段 | Bridge ?? | ObjC 缺省 | Model default | 说明 |
|---|---|---|---|---|
| `autoAdjustBitrate` | true | NO | true | Model + Bridge 一致为 true。ObjC `boolValue : NO` 在 Bridge 已填 true 时不会触发。✅ |
| `edgeSensorSummon` | true | YES | true | 三层一致 ✅ |
| `edgeSensorSummonOnArrival` | true | YES | true | 三层一致 ✅ |

### 三层一致 ✅ — 其余字段

| 字段 | 值 | 说明 |
|---|---|---|
| `yuv444` | false | ✅ |
| `sdr10bit` | false | 无直接 ObjC 读取 |
| `showLocalCursor` | false | ✅ |
| `microphone` | false | Connection.m 读 boolValue，缺省由 Bridge 填 false ✅ |
| `streamResolutionScale` | false | ✅ |
| `remoteResolution` | false | 间接使用 |
| `remoteFps` | false | 间接使用 |
| 数字类型 (`?? 0`/`?? 100`) | 0/100 | 与 ObjC `intValue : 0`/`100` 一致 ✅ |
| HDR / Sunshine 枚举 | Default 常量 | 通过 `defaultXXX` 常量路径，无 `??` 直接分叉 ✅ |

## 门禁建议
自动化检查 `SettingsObjCBridge.swift` 的 `??` 值 vs `SettingsModel+DerivedValues.swift` 的 default：
- 所有 `?? true` → 对应 Model default 必须为 true
- 所有 `?? false` → 对应 Model default 必须为 false
- 所有 `?? N` → 对应 Model default 必须为 N
