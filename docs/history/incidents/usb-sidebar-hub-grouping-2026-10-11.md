# USB 串流侧栏：基础设施折叠

设置已将纯集线器折叠，串流侧栏此前仍混列。本阶段让两处复用
`MLDeviceRedirectionPanelRow.isInfrastructureDevice`：只有身份可读且所有接口均为
0x09 的设备归入“USB 集线器 (数量)”子菜单；复合设备、未知设备留在主列表。

## 实现

`StreamViewController+MenuUI.m` 的 shipping AppKit helper 负责路由与尾部添加分组。
空分组不添加，纯hub总线仍能展开查看，不删除任何设备；主列表和组内保留模型顺序。
分组菜单同样关闭 autoenablesItems；连接按钮仍禁用，缺少真实通道和驱动不能声称连接。
未改权限、设备扫描、会话能力或系统驱动。

## 验证范围

`device-redirection-panel-model-tests.py` 编译实际菜单helper并用原生 AppKit
回放外设-only、混合、hub-only三个布局，验证项目身份、顺序、分组数量和空组缺席。
交换路由及无条件添加空组两个变异都先成功编译，再被运行时验证拒绝。
已有模型门禁验证复合/unknown不归入hub、纯hub归入hub及权限不受分组影响。
shipping 侧栏的真实调用接线与关闭autoenable另有断言。

这不是打开串流侧栏后的视觉验收，也不是USB重定向成功证据；没有修改安装版应用。
本地Debug完整构建和提交后constraints检查结果见本阶段记录。

## 回滚

revert 本阶段提交可恢复侧栏混列，既有设置折叠及权限保持原状。
