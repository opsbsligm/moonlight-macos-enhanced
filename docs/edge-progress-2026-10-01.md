# 侧边控制栏进度 2026-10-01（续 locked-flick）

## 基线
- 分支 integration/round74 @ 431ca52b；未提交改动=上一轮摘要所列（flick 实现、i18n、工装、build/download-frameworks 修复）。
- 已部署 1.6.0(1720) sha256 ab8f998a…，pid 30014 (23:52 启动)。

## 本轮新证据
1. **flick 注入不通（工装问题，非产品问题的可能性大）**
   - 锁定态下 mouseMoved 注入（hid/session/warp/source 四形态）app 零反应：无 sample、无 refused、无 opened。
   - 但同状态真实 HID 按钮事件正常进入（00:18/00:34 button-held refused、resume by explicit click 多次）。
   - released hover PASS（tracking area 路径，不经 motion 入口）；锁定态 motion 入口此前从未有 INFO 级可见性（sample 是 DEBUG，curated 不落盘）。
   - 结论：真实手在锁定态的 motion 是否进 motion 入口 = 尚未验收。已加 INFO 级 Motion entry 探针（限流1/s，验收后可删）。
2. **focus 测试 FAIL 是脚本前置条件破坏**
   - 两次复跑均 park/hover 签名相同(白把手)。日志显示 focus 段开始时 captured=1（01:23 段 held-drag 清理把点击发进串流→重捕获），
     released 前提被吞，hover 天然无差。→ 脚本需在 focus 段前重新断言并恢复 released 前提；不是产品回归。
3. macOS 更新横幅已点掉（干扰 blue_button）。

## 下一步
- 构建（含 Motion 探针）→ 部署 → 锁定态注入 motion 看 Motion entry 行 → 判定注入路径 vs 产品路径。
- 修 focus 行前置条件恢复逻辑。
- flick 实机=用户手测（注入不通则记 UNVERIFIED-注入路径）。
