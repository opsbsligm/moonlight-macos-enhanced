# user-memory spike（源码在仓库内，结论在设计文档）

本目录是 `docs/Design/user-memory.md` 第 10 节附录的**复现物**：附录里粘贴的每一段输出
都由这里的源码在同一台机器上产出。源码入库是为了让那些输出能被别人重算；
编译产物（`*.bin`）与被写坏的 `~/Library/Preferences/usermem.*.plist` 都不入库。

设计正文：`docs/Design/user-memory.md`（全中文）。

## 复现

```sh
cd spikes/user-memory
./run_spike.sh spike_migration     # 期望 RUN PASSED (29 checks, 0 failures)
./run_spike.sh spike_concurrency   # 期望 RUN PASSED (16 checks, 0 failures)，并打印 suite 名
python3 run_mutants.py             # 期望 14 caught, 1 missed（见下：脚本因此以 1 退出）
```

`run_mutants.py` 以 `__file__` 定位源码，可在任意目录调用；它每次改动源码副本后重新编译并重跑，
所以一轮下来会跑满 15 次编译。它以退出码 1 结束是**预期**的——那一个漏抓的变异是已记录的事实，
不是一个待修的失败。CI 不跑本目录：spike 是设计阶段的证据，不是回归门禁。

| 文件 | 作用 |
| --- | --- |
| `spike_migration.m` | schema 版本迁移 + 「未知版本按不利处理」的读写层最小形状，29 条断言 |
| `spike_concurrency.m` | 并发写：单键原子性、复合值丢更新、乐观 CAS、跨进程可见性、同进程实例互见，16 条断言 |
| `run_mutants.py` | 15 个植入缺陷逐个破坏源码后重编重跑，检查断言是否变红 |
| `run_spike.sh` | 与 `scripts/apple_toolchain.py` 同规则的 clang/SDK 配对探测（同一厂商成对取） |
| `why_abort.m` | 单独复现「写 `NSNull` 使进程 abort」 |
| `corrupt_probe.m` | 磁盘 plist 为垃圾文本 / 被截断时，CFPreferences 读到什么 |

后两个需要手敲命令，因为它们要往 `~/Library/Preferences` 里放东西，不该被顺手执行：

```sh
clang -fobjc-arc -isysroot "$(xcrun --sdk macosx --show-sdk-path)" \
      -framework Foundation -o /tmp/corrupt_probe.bin corrupt_probe.m
/tmp/corrupt_probe.bin <suite>
```

环境：macOS 27.2 (26B5091g)、arm64、Xcode clang + `MacOSX27.0.sdk`、Python 3.14.7。
换机器或换 macOS 主版本需要重跑，设计文档不声称跨版本成立。

## 实测结论摘要（对应设计文档节号）

1. **单键写没有半值**。8 线程 × 3000 次写 + 并发读回并按 payload 自校验，数千次读 0 次撕裂。
   → 单键不需要锁（§4.4-1）。
2. **复合值的 read-modify-write 稳定丢设置**。两个持有者各读一次、之后各存自己那份，
   最终只剩一个字段，4 次运行 4 次复现。→ 复合偏好必须单写者（§4.4-2）。
3. **`synchronize` 不是跨进程可见性开关**：会 synchronize 与直接 `_exit` 的独立进程子节点，
   3/3 与 3/3 同样可见；同进程两个 `NSUserDefaults` 实例也互相可见（无需 synchronize）。
   所以丢设置是「副本过期」问题，不是缓存问题（§4.4-3）。
4. **乐观 CAS 不是保证**：24 轮 × 4 次运行，两字段都保住的轮数依次是 22、22、23、21，重试仅 1–2 次。
   这是概率现象，所以设计**不提供** CAS（§4.4-4）。
5. **写非法值 abort 进程，不是 ObjC 异常**：`CoreFoundation _CFPrefsValidateValueForKey → abort`，
   `@try` 抓不住。→ 写前必须自校验 property-list 类型；「清除偏好」= `removeObjectForKey:`（§4.4-5）。
6. **磁盘 plist 是滞后子集**：`defaults read` 25 键 vs 文件 22 键，`plutil -lint` 合法。
   → 导出/快照只能走 API（§4.4-6）。
7. **整域损坏表现为空域**：垃圾文本与被截断的 plist 都读出 nil / 0 键且不崩溃，`defaults read` 报
   `Domain not found`。→ 损坏是静默的，域级自检必须自己写（§4.4-7）。
8. **植入缺陷 14/15 被抓**，1 个（去掉复合写的 `@synchronized`）在本机上无法区分，
   按仓库「抓不住的变异是噪音」的惯例不进门禁，并留下一条禁令：不得写「实现里必须有 `@synchronized`」
   这类字面量断言（§7）。其中两条变异在补强断言之前也漏抓过，原因分别是**分支不可达**与
   **被破坏的正是检查器本身**，补了直调断言与「检查器每读必调用」计数断言才抓住。

## 开发过程中被实测推翻的两个预设（记录以免被当成一开始就想对）

- 一开始的 spike 让迁移步骤「认不出来就原样返回」，被自己的断言抓出 `@"not a pair"` 会伪装成一次成功迁移。
  补上的三条直调 `Migrate()` 的断言，就是 `spike_migration.m` 从 26 条变 29 条的原因。
- 一开始以为「子进程不 `synchronize` 就丢写」，实测推翻：真正丢写的形状是 `fork()` 之后不 `execv`
  （3 次观测 0/6 可见）；而本仓库 `git grep` 没有 `fork`/`posix_spawn`/`vfork`，故只作为平台事实记录。
