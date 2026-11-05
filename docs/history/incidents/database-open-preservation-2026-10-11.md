# 数据库打开失败：保留数据并明确停止

## 风险

原 `DatabaseSingleton` 在 `addPersistentStore...` 失败时删除 SQLite，再递归打开。
权限不足、磁盘空间不足、迁移失败和损坏均可能触发这条路径；不能将打开失败等同于
用户授权清空资料。对象还会在成功打开前发布 coordinator，掩盖不可用状态。

## 修复

- 在同步锁内单次尝试打开，成功后才发布 coordinator；失败不删除/重命名 SQLite 或侧文件，
  不递归重试，也不自动建替代空库。
- 保存原 NSError；即使后端未提供 NSError，也有明确备用错误。下一次应用启动可重新尝试。
- `DataManager.init` 在存储不可用时返回 nil，不创建无存储上下文；singleton 自有 context 同样拒绝。
- macOS 启动在主界面创建前核验错误，显示本地化说明（数据保留、检查空间/权限或恢复有效备份），
  用户关闭提示后退出。不可把失败显示成正常空主机列表。
- 旧 API `_Null_unspecified` 保持原导入语义，新 error 属性 nullable；没有广泛标成 nonnull。

## 验证

`database-open-preservation-tests.py` 编译完整生产 singleton 与提取的生产 DataManager.init：
带错误/未给错误的注入失败，以及真实畸形 SQLite 文件失败，均保留专属临时 fixture 的
sqlite/wal/shm 原字节；多次读取和 32 并发读取不会重新打开。实际有效 SQLite 可打开，
32 并发首次读取都等到已打开的 store，DataManager 使用该 store。

五个可编译负变异：删除库、去掉同步、失败重试、提前发布、忽略不可用 store。
均在原生运行时被捕获。启动提示与顺序另有接线断言，完整Debug编译验证 AppKit API。
门禁挂到 `scaling-output-evidence-tests.py`，随两架构构建与constraints运行。

测试仅操作随机临时目录，不向个人数据库注入故障。没有真实启动错误对话框的视觉验收，
也没有实际权限不足/磁盘满/迁移失败的逐种实机演练；失败分支注入不能冒充这些全量场景。
这不是备份恢复演练或串流/USB硬件验收。

## 构建隔离

独立工作树避免污染 HEAD78d6f766 正在运行的完整回归。
新工作树最初缺 OpenSSL 和 FFmpeg/Opus/SDL2 框架，因此初次两次构建失败；补齐既有本地
依赖和用户 fork 的固定 submodule 后 Debug 构建成功，不属于生产源码编译故障。
不替换安装版；合并前后仍需核验。

## 回滚

可 revert 本阶段提交，但会重新引入打开失败删库风险；不得把回滚等同于安全修复。
用户资料保持原位置，无自动清理或格式迁移操作由本阶段直接执行。
