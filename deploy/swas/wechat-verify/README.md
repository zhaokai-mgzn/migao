# `deploy/swas/wechat-verify/` —— 微信「扫普通链接二维码打开小程序」校验文件落位目录

本目录**不预置任何文件**，它只是一个**承接位**：微信后台生成的校验文件由**用户**下载后原样放进来，
部署时由 `deploy/swas/deploy.sh` 幂等拷到静态根（`/opt/migao-deploy/h5`）的**根下** ——
微信只认 `https://app.migaozn.com/<名字>.txt` 这一种 URL。

## 怎么做（用户侧，3 步）

1. 微信公众平台 → 小程序后台 → **开发 → 开发管理 → 扫普通链接二维码打开小程序** →
   添加规则（URL 前缀填 `https://app.migaozn.com/s/`，页面填 `pages/worker/report/index`）→
   按后台提示**下载校验文件**（档名形如 `<一串字符>.txt`，每个小程序各自不同）。
2. 把下载到的那个 `.txt` **原样**放进本目录：
   ```bash
   cp ~/Downloads/<微信给的名字>.txt deploy/swas/wechat-verify/
   ```
3. 提交这个文件（它**不是**秘密：微信要能从公网取到，后台也能随时重新下载）。

🔴 **不要**改文件名、不要改内容、不要自己造一个 —— 校验是按「文件名 + 内容」逐字比对的；
仓库里也**不允许**出现伪造的样例文件（判据 = `tests/unit_ci_workflows/test_wechat_verify_route.py`
的「本目录不得预置 `*.txt`」）。

## 部署时会发生什么（仓库侧，已自动化）

- `deploy/swas/deploy.sh` 的 `2.6.2` 段把本目录下**所有 `*.txt`** 拷到静态根根下：
  - 只**增 / 覆盖** `.txt`；**不删**任何别的文件（那个静态根同时是 C 端 h5 的落地面）；
  - **幂等**：同一份输入连跑两次，结果逐字节一致；
  - 还没放文件 / 没有源码树 ⇒ **出声跳过**，**不拖垮部署**。
- `deploy/swas/nginx.conf` 给根下 `.txt` 一个**显式**的面：
  `location ~ ^/[^/]+\.txt$ { try_files $uri =404; }` —— 文件缺失就是 **404**，
  **绝不**回落 SPA 的 `index.html`（否则「校验文件不在」会伪装成 HTTP 200 的一页 HTML，
  与「内容对不上」无法区分）。本正则只匹配**根下单段**，不劫持 `/b/` `/w/` `/terminal/` 任何命名空间。

## 怎么自证（部署后在任意能上网的机器上）

```bash
# ① 校验文件真的在、内容逐字一致（把 <名字> 换成微信给的那个）
curl -s https://app.migaozn.com/<名字>.txt | diff - deploy/swas/wechat-verify/<名字>.txt && echo OK

# ② 响应头是文本，而不是一页 HTML
curl -sI https://app.migaozn.com/<名字>.txt | grep -iE '^HTTP/|^content-type'

# ③ 反向：根下**别的** .txt 缺失必须是 404（不是 200 的 index.html）
curl -s -o /dev/null -w '%{http_code}\n' https://app.migaozn.com/__missing__.txt   # 期望 404
```

## 与小程序的关系

校验通过 ⇒ 微信里扫纸上的 `https://app.migaozn.com/s/<短码>` 会**直接打开小程序**
`pages/worker/report/index`（A 档），参数在 `q`。界面口径、appid / 上传私钥 / 提审步骤、回滚，
见 [`docs/deployment/wechat-mini-program-qr.md`](../../../docs/deployment/wechat-mini-program-qr.md)。
