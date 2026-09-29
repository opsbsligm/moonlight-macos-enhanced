# 边缘把手实机一键验收工具（2026-09-29）

## 为什么

发布 1720 后最大的空洞是"用户实机验收"：八步清单靠人手动做并凭记忆下结论，
"前两次有效、后面失效"正是这样漏掉的。`scripts/edge-handle-live-acceptance.py`
把人留在只有人能做的部分（开串流、按实体修饰键），其余自己做：
经 WindowServer 注入真实指针事件、截真实屏幕、按应用自己画出的把手
（收起 14 pt / 点亮 30 pt）做几何测量，逐步给出 PASS/FAIL 并保留截图。

## 组成与本轮实测

| 件 | 事实 |
| --- | --- |
| `scripts/edge_acceptance_helper.swift` | swiftc 编译通过；screens/idle/move/click/down/up/key/mod 子命令全部走 CGEvent HID tap。`mod` 用"先按 A、B 携 A 的 flags 按下、再先后松开"的顺序，纯修饰键规则只有在两键同按的窗口内才可能命中，单次 down/up 对它什么都测不到 |
| `--self-test` | 合成图判定 **3/3 通过**：idle 14.0 pt、armed 30.0 pt、空边缘 none。判据是"从屏幕最外列起、覆盖 48 pt 把手长度的连续近白列"，视频亮度无法伪造第 0 列的连续 run |
| 无串流冒烟 | 正确拒绝：baseline FAIL 并指向截图，其余 UNVERIFIED，非零退出 |
| `constraints-audit.py --no-battery` | 0 failures（工具不进 workflow：它需要真实串流会话，属独立验收层，不伪装 CI 覆盖） |

## 用法（对着本机真实配置）

```
python3 scripts/edge-handle-live-acceptance.py --loops 30   # 验收要求 30 次
```

先启动 `/Applications/MoonlightEnhanced.app` 并连上 HOME-PC（192.168.3.110，
本轮 ping 47989 在线确认）。模式问句：free / released（⇧⌥ 释放后）/ locked。
锁定模式不跑 hover 循环（本地指针被捕获，设计如此），只跑 `⌃⌥C` 开关两项；
产物目录含每步 PNG 与 `acceptance.json`。

## 边界（如实）

- 全部指针/按键为**注入**，矩阵标注 injected，不冒充硬件；
  实体 ⇧⌥、拔插外置鼠标、多显示器排列仍是人工验收行，工具写 UNVERIFIED。
- 只测主屏；多显示器明确 UNVERIFIED。
- `⌃⌥C` 开合面板给 CHECK（面板几何不在把手判据内），用户看图确认。
- 本工具**不会**代开串流，也不会打断正在串流的用户。

## 下一步

- 用户跑一次 `--loops 30`（约 3 分钟），或口头反馈，两者取其一即可把
  "尚未验收"变绿或变红；红了按截图与 JSON 回到诊断层。
- CHECK 两项（⌃⌥C 开/合）如需像素判据，把面板 diff 判据加进 `shot()` 即可，
  判据素材（截图）已经在产物目录里。
