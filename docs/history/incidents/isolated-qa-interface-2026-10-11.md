# 独立 QA 身份与真实界面取证

正式版和旧Debug应用共享bundle ID，Computer Use无法可靠区分。本阶段Debug新增
严格的`std.skyhua.MoonlightMac2.QA`身份判据，仅该身份使用Application Support/Moonlight-QA。
普通Debug和所有Release继续原Moonlight路径；不依赖无效的HOME隔离，不复制用户库或证书。
生产路径直接使用helper；native门禁验证两种构建模式、nil/普通/未知身份与两个负变异。

QA构建命令：
```
xcodebuild -project Moonlight.xcodeproj -scheme 'Moonlight for macOS' -configuration Debug \
  -derivedDataPath /tmp/ml-cp17-qa PRODUCT_BUNDLE_IDENTIFIER=std.skyhua.MoonlightMac2.QA \
  CODE_SIGN_IDENTITY=- CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO build
```

实际构建成功，Info.plist身份正确。Computer Use启动新QA，读到欢迎页和空首页，
未授权输入监控/麦克风或安装Helper，仅点击继续。专属目录实际生成sqlite/wal/shm。
不能按标题中的1720区分构建新旧：只读sample确认运行PID8712为/private/tmp/ml-cp17-qa
并具有QA身份；正式版未替换，个人库未被作为QA数据使用。

点击设置后AX读取与截图均遭native pipe closed。进程仍存活，采样主线程正常等待事件；
不能由此判定App崩溃，也不能宣称设置/USB视觉验收成功。不要用外部UI自动化绕过工具。
后续需继续解决设置窗口读取问题。

欢迎页现场还显示原作者仓库链接。本阶段将欢迎与About产品导航改为用户独立仓库，
README使用#readme避免硬编码错误分支（gh确认当前default为pr-overhaul）。保留作者署名。
constraints新guard与两种错误链接自测验证实际源码接线；没有点击外部链接的浏览器验收。
QA实际截图前构建尚用旧链接，链接修正后另构建验证，不伪造已看到更新。

这仍不是串流、画质、USB通道验收；QA空库没有配对能力，不应声称可真实串流。
回滚本阶段提交恢复旧导航与QA共享目录，正常用户库位置不变。
