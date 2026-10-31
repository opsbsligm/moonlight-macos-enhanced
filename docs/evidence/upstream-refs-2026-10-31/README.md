对标来源矩阵的上游引用投影（2026-10-31 抓取）

目的：让 `docs/source-matrix-2026-10-25.md` 里"某个 release tag 存在吗 / 某分支此刻的头是什么"
这类断言在**仓库内**就能复核，不要求复核者联网。抓取的是 GitHub REST 只读接口的响应，
按 `extract.py` 的固定投影裁剪后入库（原始 releases 响应 792 KB，全是与结论无关的
changelog 正文，故不入库）。

| 文件 | 上游路径 | git blob SHA |
| --- | --- | --- |
| `extract.py` | GitHub REST（只读投影，见下） | `40e2174649a68ad0b964ed7fc78932e470536e91` |
| `qt-tag-v6.2.0.json` | GitHub REST（只读投影，见下） | `68804bc869eb2ab3da16dc3aab2d87fc1590a150` |
| `scloud-commit.json` | GitHub REST（只读投影，见下） | `500e3c634d766d48e91807b66f0ad827f24fa7d0` |
| `skyhua0224-master.json` | GitHub REST（只读投影，见下） | `3c03f012101346399c22f37a8d48f300752a2e2c` |
| `sunshine-master.json` | GitHub REST（只读投影，见下） | `9bc3eb19cb421f1ac27518d55065d4402f68ae8d` |
| `sunshine-releases.json` | GitHub REST（只读投影，见下） | `7d788a11b13d42aa290b54e9889b23ea42dddd63` |
| `sunshine-tag-v2026.1018.5342.json` | GitHub REST（只读投影，见下） | `5676aee4d200c194825f61cbed5ca9bf060d4c62` |

复核方式（对每个文件重算 blob，应与上表一致）：

```sh
cd docs/evidence/upstream-refs-2026-10-31
for f in extract.py *.json; do git hash-object "$f"; done
```

重新抓取并重放投影（联网，结果应逐字节等于入库文件；不等即上游已移动，须重钉而非改文档）：

```sh
python3 extract.py <(curl -ksS https://api.github.com/repos/LizardByte/Sunshine/releases?per_page=5) sunshine-releases.json
python3 extract.py <(curl -ksS https://api.github.com/repos/LizardByte/Sunshine/commits/master) sunshine-master.json
python3 extract.py <(curl -ksS https://api.github.com/repos/moonlight-stream/moonlight-qt/git/ref/tags/v6.2.0) qt-tag-v6.2.0.json
python3 extract.py <(curl -ksS https://api.github.com/repos/skyhua0224/moonlight-macos-enhanced/commits/master) skyhua0224-master.json
python3 extract.py <(curl -ksS https://api.github.com/repos/FlorianSLZ/scloud/commits/2f32dfbfbb3c5855d87da8a5b874191afc9c5d37) scloud-commit.json
python3 extract.py <(curl -ksS -w '\n' https://api.github.com/repos/LizardByte/Sunshine/git/ref/tags/v2026.1018.5342) sunshine-tag-v2026.1018.5342.json
```

## 这批投影回答了什么（逐条可复核）

- `sunshine-releases.json`：最近的 5 个 release 中没有 `v2026.1018.5342`；最新 stable 是
  `v2026.914.233613`（`target_commitish` `63d35f702ee9e362e43263742981836ec0710384`），
  其后两个 `v2026.1028.*` 均 `prerelease=true`。矩阵旧格的"最新 release `v2026.1018.5342`
  （2026-10-18）"因此判定为**记录错误**，不是上游改名。
- `sunshine-tag-v2026.1018.5342.json`：对同一 tag 的直接探针返回 `404 Not Found`，
  与上一条互相独立地否定同一个字符串。两条证据都入库，是因为单独一条可以解释成接口抖动。
- `sunshine-master.json`：抓取时刻 `master` 头为 `2c8825ad5b66cf9750f8154691202f0cd8768ac0`
  （2026-10-30T17:23:44Z）。它**不是** `sunshine-snapshot` 钉住的 `a679b059…`——快照钉的是
  抓取时刻的 master，两者相差若干提交属正常，故此文件的作用是"master 会继续移动"的凭据，
  而非对快照 commit 的第二重确认。
- `qt-tag-v6.2.0.json`：tag `v6.2.0` 解析到 commit
  `de2467e433821664cdd2224aad8c89a625be1ad9`，与 `docs/evidence/qt-snapshot/README.md`
  钉住的 commit 一致。
- `skyhua0224-master.json`：基地版 `master` 头 `c4dd84daa6440468f4e9a2e48f8c482f24bec965`
  （2026-10-27T06:09:06Z）。矩阵旧格写"最后推送 2026-10-13"，已过期 14 天且无 commit。
- `scloud-commit.json`：Citrix ADMX 证据钉的 commit `2f32dfbf…` 存在，提交时间
  2026-08-17T11:24:01Z。

## 边界

投影只保留结论用到的字段。`target_commitish` 是 release 的**标签指向**而非构建输入，
不能当作"该 release 由此 commit 构建"的证据；本快照用它记录 tag→commit 的可解析性，
不使用其构建语义。上游分支头随时间移动，`sunshine-master.json`/`skyhua0224-master.json`
的日期即其有效期边界：它们证明"那天是多少"，不证明"现在是多少"。
