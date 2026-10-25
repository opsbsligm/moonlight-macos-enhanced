moonlight-qt v6.2.0 输入层快照（2026-10-25 抓取）

钉住版本：tag `v6.2.0`，commit `de2467e433821664cdd2224aad8c89a625be1ad9`。

| 文件 | 上游路径 | git blob SHA |
| --- | --- | --- |
| `gamepad.cpp` | `app/streaming/input/gamepad.cpp` | `b649971b693beac4c2db5cc89d220b1168161355` |
| `streamingpreferences.h` | `app/settings/streamingpreferences.h` | `ad611f6a28d1e76aff9b983f20bab8e59b0e9449` |

关键行号（本快照内，供 roadmap §2.3/§6 引用核对）：

- `LiSendControllerArrivalEvent` 调用：`gamepad.cpp:763`
- `sendGamepadBatteryState` 定义：`gamepad.cpp:116`（旧文档误记 154）
- `LiSendControllerTouchEvent2` 调用：`gamepad.cpp:485`
- 三个协议回调：`rumbleTriggers` `gamepad.cpp:901`、`setMotionEventState` `gamepad.cpp:915`、`setControllerLED` `gamepad.cpp:950`

协议常量不在 gamepad.cpp，而在其 pin 的 common-c（`f900dd4`，"Add MODIFIER_EXTENDED flag"）：

- `LI_CTYPE_STEAM`：`src/Limelight.h:781`
- `LI_CCAP_DUAL_TOUCHPAD`：`src/Limelight.h:790`
- touchpad index 说明（0/1）：`src/Limelight.h:807-808`
