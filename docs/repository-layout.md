# 仓库与依赖维护

客户端与协议源码统一保存在 `moonlight-macos-enhanced`，通过同一个 MR 审查、构建和发布。
GitLab 负责开发与审批，GitHub 提供自动单向镜像和下载入口。

## 源码分工

| 路径 | 内容 | 修改方式 |
| --- | --- | --- |
| `Limelight/` | macOS 客户端 | 在主仓开发分支提交 |
| `moonlight-common/moonlight-common-c/` | 串流协议源码 | 与客户端修改放在同一个 MR |
| `moonlight-common/moonlight-common-c/enet/` | ENet 依赖 | 更新根 `.gitmodules` 对应子模块的固定提交 |
| `moonlight-common/moonlight-common-c/nanors/deps/simde/` | SIMDe 依赖 | 更新根 `.gitmodules` 对应子模块的固定提交 |

协议源码来自原独立协议仓的 `093098f5f8caa8177598bb9fe3016eab70df845b`。
导入时未修改 C 源码、头文件、构建文件或许可证；原协议仓自身的 CI、镜像发布脚本和
子模块配置由主仓统一管理。来源与两个依赖的导入版本见
[`UPSTREAM.json`](../moonlight-common/moonlight-common-c/UPSTREAM.json)。该文件记录导入基点，
后续协议修改以主仓 Git 历史为准；更新依赖时同时维护其中的固定提交。

## 检出与验证

```bash
git clone --recurse-submodules <repo-url>
cd moonlight-macos-enhanced
bash scripts/ci/fetch-submodules.sh
python3 scripts/ci/test_pipeline.py
```

ENet 与 SIMDe 都是公开依赖，当前版本的检出不需要私有协议仓或组令牌。
仓库下载地址见根 [`README.md`](../README.md)。
构建工具链与完整门禁见 [`contributing.md`](contributing.md)。

## 历史兼容

旧客户端 tag 和提交仍通过 Git 子模块引用独立的 `moonlight-common-c` 仓库。
独立协议仓保留用于历史版本重建；新协议开发统一在本主仓进行。
不得删除旧协议仓、改写旧 tag，或删除旧流水线仍需的凭据来完成本次目录整理。
归档仓不会自动补入主仓的新协议修改。

上游源码、作者署名与许可证保留。独立开发约定继续适用，不自动同步上游分支；
需要吸收外部修复时，在主仓明确记录来源并经审查与门禁验证。
