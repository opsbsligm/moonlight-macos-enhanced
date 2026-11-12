# upstream-refs-2026-11-13

对标来源矩阵（`docs/source-matrix-2026-10-25.md`）深信服 aDesk 与锐捷云桌面两行的入口
重找与存证。两行证据档位维持「仅宣传 / 待调研」：本轮钉住的是入口 URL 与旧 404 路径的
更正记录，输入映射细节仍无公开可复核来源，版本号仍未钉。

- `sangfor-adesk-entry-2026-11-13.json`：深信服 aDesk 产品页
  `https://www.sangfor.com.cn/sangfor-cloud/adesk`（200，首页链接命中）；
  旧记录的产品子页 `product/24.html` 确认 404。
- `ruijie-cloud-desktop-entry-2026-11-13.json`：锐捷云桌面官网公开面以行业方案为主，
  钉住医疗方案页 `https://www.ruijie.com.cn/fa/yl/87104/`（200）；`/rd/` 确认 404；
  通用产品页因 JS 动态渲染未能从静态 HTML 钉住。

复核命令：
```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://www.sangfor.com.cn/sangfor-cloud/adesk"
curl -s -o /dev/null -w "%{http_code}\n" "https://www.ruijie.com.cn/fa/yl/87104/"
```
