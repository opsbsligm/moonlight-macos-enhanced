# GitHub 镜像门禁对 failed+allow_failure 安全 job 的放行策略（Wave AP9 决策记录）

状态：**草案待决策**。默认维持现状（retry 兜底人肉流程），不自行改行为。
基点：main `0ea0b209`（2026-11-12）。

## 问题现场（均已复核）

- 门禁实现：镜像主机 `/opt/gitlab-mirror/bin/controller.py:187`。对 pipeline 内每个非
  publish job：`success` 放行；`skipped` 且 `allow_failure=true` 放行（唯一合法跳过）；
  其余（含 `failed` + `allow_failure=true`）一律 409 `other_gate_not_success_or_legal_skip`。
- 两次实际命中：
  - pipeline `1865`（main `ff7aece1`）：`跨文件静态安全扫描`（14224）failed+af（22min 超时
    terminated），publish-github（14220）首跑被 409 拦；用 owner 临时 PAT API retry 后
    14224→14339 success、14220→14408 success，pipeline 终态 success。
  - 同环境（Intel 老 Xeon + SAST 镜像缓存冷 + 离线受限网络）下 Advanced SAST 全量扫描
    经常撞 30min job 超时；P17 策略已把「跨文件静态安全扫描」设为 `allow_failure=true`，
    但它 failed 时仍被本条门禁拦死 publish。

## 两个选项

### 选项 A（默认）：维持现状，retry 兜底

- 门禁语义不变：只有 success 或明确豁免的 skipped 能放行镜像。
- 代价：failed+af 出现时 publish 被拦，需要 owner 用 liguangming 临时 PAT 走
  API retry（已跑通两遍，每次约 10-20 分钟人工/自动时间）。
- 收益：对"该 job 是否真该放行"保持逐次人工判断，不扩大放行面。

### 选项 B：controller 白名单加一条

- `failed` 且 `allow_failure=true` 且 job 名在 P17 豁免清单内（目前只有
  「跨文件静态安全扫描」）时放行 publish。
- 代价：controller 与 P17 豁免清单变成双源，清单变更需要两边同步（可加约束审计钉住）；
  放行面扩大到"未来任何 failed+af 的豁免清单成员"。
- 收益：Release 链不再因该环境已知的慢扫描人工兜底。

## 建议

维持选项 A，直到以下任一成立再切 B：同一豁免 job 在 30 天内第三次触发人工 retry，
或 Intel 扫描环境扩容（换 runner/升超时/缓存预热）使失败率显著下降。切换 B 时须同时：
controller 变更进 `/opt/gitlab-mirror/` 版本控制、加镜像侧单测、仓内 `constraints-audit`
加一条双源一致性检查。

## 关联证据

- `docs/gitlab-ci.md`（publish-github 唯一写镜像方、stage barrier 语义）
- 波次记录：AP8 收口（main `ff7aece1`，#1865 16/16）、本波 #1900
