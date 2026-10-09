# 插帧节拍整除门限（cadence divisibility）— 2026-10-09

## 现象与根因（实测，非猜测）
用户实测：1080p120 串流 + LLFI 激活，画面"粘稠如蜂蜜"，不可用。
现场日志（`moonlight-debug-curated.log`）：

  `reason=display 180.00Hz provides cadence headroom over 120 FPS`

即旧门限（refresh ≥ max(1.5×fps, fps+12)）在 180Hz/120FPS 恰好压线放行。
但 LLFI 输出 2×120=240 帧，屏幕每秒只扫描 180 次（实测 179.82）：240 不能
整除 180，部分帧等一次 vsync、部分不等——judder 在低延迟数字下依旧存在，
体感就是粘稠。120 FPS 恰是 180Hz 面板所有可选值中最差的一个。

## 新规则（InterpolationCadencePolicy.h，唯一权威）
放行的充要条件从"有余量"改为"整除节拍"：

  refresh ≈ k × (2 × sourceFps)，k 为正整数，容差 3%

- 容差是对刷新率本身的（不是比值）：179.82/180 差 0.1%，放行；
  144Hz 上 60FPS 的 1.2× 节拍差 20%，拒绝。3% 两侧都有余量。
- `MLInterpolationMinimumRefreshForSourceFps` 改为 2×fps（一拍一帧的地板，
  force 日志引用它）。
- `MLInterpolationHasCadenceHeadroom` 做整除判定（round + 容差）。
- `MLInterpolationMaxSourceFpsForRefresh` / `SuggestedFps` 只从整除可承载的
  offered 档位中取最大——没有整除配对就如实推荐 0（不可用），不再端出
  "1.5× 有余量"的伪推荐。

新旧对照（offered 档位 30/60/90/120/144）：

| 面板 | 旧建议 | 新建议 | 理由 |
| --- | --- | --- | --- |
| 60 Hz | 30 | 30 | 60=2×30 整除 ✓ |
| 90 Hz | 60 | 0(不可用) | 90 与任何档位的 2× 都不整除（72 不在档位） |
| 120 Hz | 60 | 60 | 120=2×60 ✓ |
| 144 Hz | 90(1.5×压线) | 0(不可用) | 144/180=0.8、144/120=1.2，均非整数 |
| 180 Hz | 120(蜂蜜) | 90 | 180=2×90 每帧恰好一拍 ✓；120→240 不整除 |
| 240 Hz | 120 | 120 | 240=2×120 ✓ |

180Hz 面板的正解是 90 FPS：2×90=180 每次刷新恰好一帧，零 judder。

## 改动落点
- `Limelight/macOS/InterpolationCadencePolicy.h`：新规则 + 头注重写。
- `Limelight/Stream/VideoDecoderRenderer.m`：三处 reason 如实改写
  （拒绝=“不匹配任何整数倍节拍”；force 日志=“承载不了整除节拍”；
  放行=“以整数倍刷新承载二倍帧率”）。force 语义不变：只跳检查，
  文案如实声明"强制修不好节拍"。
- `SettingsModel+VideoPageRules.swift`：注释与规则描述同步。
- en/zh-Hans `Localizable.strings`：6 条文案（Advice / No Headroom /
  Force detail ×2 / Active Forced / No Cadence Headroom）改为整除表述，
  并给出 180Hz→90、120/240Hz→60 的可操作建议。
- 测试：`interpolation-cadence-policy-tests.py`（61 readings，含
  180/90、179.82/90、174/90、121/60、61/30 等边界与新的 red-proof：
  把旧 1.5× 规则植回必须变红）；`interpolation-readout-tests.py`
  （建议值表按新规则修正）；`frame-interpolation-status-tests.py`
  （放行用例改 240Hz/60 的合法配对；144Hz/120 仍是 force 越过用例）。

## 验证
- 4 个秒级门禁 + `./scripts/local-gates.sh` 全绿（见 commit 说明）。
- strings 文件 `plutil -lint` 双双 OK。
- 待实机验收：HOME-PC 192.168.3.110，90 FPS + 插帧，主观确认
  蜂蜜感消失（未完成，不得先行宣称）。

## 回滚
`git revert` 单一 commit 即可；无状态迁移、无默认值变更。

## 已知边界
- 90/144Hz 面板现在如实报"插帧不可用"而非端出会抖的伪推荐；
  这类面板仍可用 force（风险自担，文案已如实）。
- VRR/刷新率映射面板的实测节拍仍走同一整除判定；59.94 一类
  在 3% 容差内按 60 处理。
