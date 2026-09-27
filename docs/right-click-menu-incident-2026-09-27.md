# 边缘释放后右键反复打开本地菜单

用户截图中的菜单属于 Moonlight。旧 rightMouseDown 只要 isMouseCaptured 为 NO 就调用 presentStreamMenuAtEvent，并吞掉下一次右键松开；边缘临时释放和快捷键主动释放都会进入该条件。它没有像左键一样先恢复捕获，因此重复右键继续弹菜单。

修复：删除串流视图右键打开本地菜单的旧分支及对应的 suppressNextRightMouseUp 状态和已无调用的 presentStreamMenuAtEvent 方法。右键与中键/侧键在有效画面点击时，沿用左键的激活窗口、显式恢复、边缘临时释放交接和捕获路径，再发送原始按下；松开沿用既有按钮状态配对。活动菜单和控制栏拖动不能被显式恢复抢占。控制菜单入口仍是边缘按钮、标题栏按钮或配置快捷键。C 键保护未修改。

验证：抽取生产右键、中键、释放与边缘状态实现回放，两种鼠标模式 × 两种释放来源 × 30 轮，共 120 轮右键完整按下/松开，无本地菜单；涵盖首次按下、恢复失败、按钮区域、活动菜单和拖动。边缘自测共 27 项几何、2086 项运行断言通过；恢复旧未捕获右键菜单分支的负对照失败。完整键鼠回归 45/45，Release 构建、警告审计、diff 和严格签名通过。

实机：新版 PID 58386 连入 HOME-PC Desktop；19:00:14 首次 right-down captured=0、right-up captured=1，重复右键未出现本地菜单。工具尝试打开控制菜单但未确认成功，不能将此验收说成实机重现所有边缘触发路径。详细按键阶段证据见 build-input-review/right-click-live-check.log。

已安装 /Applications/MoonlightEnhanced.app，SHA-256：3e4a0fe5b2549d9242f7cb0e2aa3c8940a05ba3b3281f2d47ce92e090a3f8aa7。旧版移入废纸篓，安装记录见 build-input-review/right-click-install-result.json。
