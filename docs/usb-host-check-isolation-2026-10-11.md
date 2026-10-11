# USB设置主机能力检查隔离（2026-10-11）

## 现场缺陷

设置中的异步serverinfo检查验证了响应UUID等于请求UUID，但没有再验证回调时当前所选主机和页面代次。切换配置或离开页面后，旧请求仍能修改hostClaim。另一个问题是pairedTemporaryHost只筛选UUID，然而DataManager.getHosts读取全部Host记录，并非已配对集合。

## 修复

- 主机选择必须确实为PairState.paired，不能用“有记录”代替。
- 独立hostCheckGeneration在请求开始、页面出现/离开、主机切换时递增。
- 完成在主线程释放单飞槽，然后通过生产MLUSBScanMayPublish验证页面可见、代次一致、当前主机身份一致且仍配对，再更新能力/不可达状态。
- 主机切换立即清除旧claim，并用已有设备identity重新评估行，不重新扫描IOKit。已有请求保留单飞槽直到完成，防止主机切换导致请求FIFO。
- 证书在发请求前快照，不在后台读取可变host字段。每次打开页清除旧claim，不把过去问过的答案当当前主机的实时能力。

## 验证范围

device-redirection-panel-model-tests.py提取生产note与pairedTemporaryHost方法，编译Swift测试夹具；C调度/发布策略直接由Swift桥接导入生产USBScanPolicy.h。真实Dispatch/main RunLoop，HTTP、主机存储及面板接收端为替身。9种场景：成功、旧代次、页面离开、换主机、已取消配对、全局配置、主机记录删除、真实请求不可达、空UUID。四个合法编译负变异验证忽略页面代次/主机身份/离开状态/配对状态分别被捕获。另有实际界面接线约束、完整Swift类型检查和Debug应用构建。

本阶段不打开设备、不改许可、不自动检测远端，更没有启用USB连接。真实DriverKit和远端通道仍缺失；界面和调度测试不是设备真实接管/回收验收。回滚撤销本阶段USB提交。

完整冷缓存analyzer发现单参onChange重载已弃用；最低部署macOS26，监听改为双参当前重载，测试同时锁定该接线，不修改告警基线。最终分析门禁结果以阶段记录为准。
