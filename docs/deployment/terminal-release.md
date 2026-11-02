# 观星台终端发布与回滚（Windows 一体机 / Android 手持机）

> 关联：issue #8195（本仓发布腿 + 官网下载页）、终端仓 `zhaokai-mgzn/migao-terminal` 的 `docs/release.md`（产物怎么构建）。
> 本文只讲**从终端仓 Release 到线上可用**这一段，不重复构建步骤。

## 1. 线上坐标（终端程序里写死的，不是本仓的自由选择）

| 件 | 地址 / 位置 | 出处 |
|---|---|---|
| Windows 更新清单 | `https://app.migaozn.com/terminal/latest.json` | 终端 `src/terminal/Program.cs` 的 `latestJsonUrl` 默认值 |
| Android 更新清单 | `https://app.migaozn.com/terminal/android/latest.json` | 终端 `android/.../Updater.java` 的 `DEFAULT_MANIFEST` |
| 安装包 | `https://app.migaozn.com/terminal/<文件名>`（清单里的 `download_url`） | 发布腿生成 |
| 官网下载页 | `https://migaozn.com/download`（`www` 301 到裸域） | 本仓 `frontend/admin-web/src/app/(corporate)/download/` |
| 静态根 | `/opt/migao-deploy/h5` 下的 `terminal/` 子树 | `deploy/swas/nginx.conf` 的 `root` + `location /terminal/` |

nginx 口径（`deploy/swas/nginx.conf`）：`/terminal/` 有**自己的 location**，`try_files $uri =404`
⇒ 缺失文件是 404，**不回落**根 `index.html`（回落 = HTTP 200 的一页 C 端元元 HTML，监控不红）；
清单 `application/json`、安装包 `application/octet-stream`；**不限流**（批量更新会误伤）。

## 2. 发布源：终端仓的 GitHub Release

发布腿**不构建**产物，只搬运终端仓某个 Release 里的资产：

- 资产名：`*.exe`（Windows 安装包）与 `*.apk`（Android 安装包），**各自恰好一个**；
  名字可以显式指定（`--windows-asset` / `--android-asset`，workflow 走默认发现）。
- 可选：Release 里带 `latest-android.json` ⇒ 未显式给 `android_version_code` 时从中读 `versionCode`。
- 从 Release 的 tag 推导 Windows 版本（`terminal-v1.0.1` / `v1.0.1` ⇒ `1.0.1`），也可用 `version` 输入显式给出。

> ⚠️ **发布源这一侧尚未闭合**：终端仓当前**没有**发布 workflow（`.github/workflows/android.yml`
> 只上传 artifact，Windows 出包在本地 `build/package.ps1`）⇒ 「Release 里的 exe/apk 从哪来」
> 由终端仓另单（terminal#12）补齐。**发布腿已按上面的命名契约可用**，缺资产时第一步就判红并列出实际资产。

## 3. 一次性前置（由人完成，缺了 workflow 会出声失败）

终端仓是 **private** ⇒ 本仓的 `GITHUB_TOKEN` 读不到它的 Release ⇒ 需要一个只读 PAT：

```bash
# fine-grained PAT：Repository access = 仅 zhaokai-mgzn/migao-terminal，Permissions = Contents: Read-only
gh secret set TERMINAL_REPO_TOKEN --repo zhaokai-mgzn/migao --body '<PAT>'
```

其余凭据都是既有的（`ALIYUN_ACCESS_KEY_ID/SECRET` + `ACR_USERNAME/ACR_PASSWORD`），**不新增**。

## 4. 发布步骤（人工闸，必须点名 tag）

```bash
# 1) 确认终端的 versionCode 大于线上
curl -fsS https://app.migaozn.com/terminal/android/latest.json | python3 -m json.tool

# 2) 触发（workflow_dispatch；失败在 run 上可见，不静默半成品）
gh workflow run terminal-publish.yml --ref main \
  -f release_tag=terminal-v1.0.1 \
  -f android_version_code=<大于线上> \
  -f version=1.0.1.0 \
  -f notes='首个发布版：车间一体机裁高终端'

# 3) 看结论（不要只看「有没有绿」——看最后两步的断言读数）
gh run watch $(gh run list --workflow terminal-publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

发布腿内部顺序（`deploy/scripts/terminal-publish-ci.sh` + `deploy/swas/terminal-publish-remote.sh`）：

1. `gh release download` 取资产（**跨仓**，用 `TERMINAL_REPO_TOKEN`）；
2. `prepare`：复制安装包 → 生成 `latest.json` / `latest-android.json`，**回读校验**字段与哈希；
3. 载荷装进 ACR 传输镜像并推送（`docker manifest inspect` 复验，推送有墙钟上界）；
4. SWAS `RunCommand` 执行远端脚本：**先** `assert_payload_complete`（清单 ⇄ 载荷的 `sha256` / `size` /
   `download_url` 逐条比对）**再**收敛 `<静态根>/terminal` 子树并整份拷入；
5. 断言：远端 `latest.json` / `android/latest.json` 的哈希 == 本地载荷、静态根 `index.html` 前后一致；
6. served 断言：两份清单元数据哈希一致 + `Content-Type: application/json` + 安装包
   `application/octet-stream` + 缺失文件 **404**。

**幂等**：远端先收敛目标子树再整份拷入 ⇒ 同一版连发两次逐字节一致；陈旧文件（上一版的安装包）会被收敛掉。
**失败可见**：任一步失败 ⇒ 非零退出；载荷与清单不一致时**什么都没改**（校验在写入之前）。

## 5. 回滚

| 场景 | 做法 |
|---|---|
| 新版本装坏了（还没扩散） | 重新触发 `terminal-publish.yml` 并 `release_tag` 指向**上一个正常版本**的 tag（这是唯一可靠的回滚：`terminal/` 子树被整份覆盖，不残留坏包）；Android 的 `versionCode` 必须**大于**线上才会被已装机器判定为更新 ⇒ 若上一版的 versionCode 更小，已升级的机器只能**手动重装**（登记到终端仓 terminal#12） |
| 只想让「检查更新」停止提示 | 把清单的 `version`（Windows）/ `versionCode`（Android）改回当前线上版本后重新发布 —— 仍走同一条腿（不要手改线上文件：手改没有哈希自证，下一次发布也会被覆盖） |
| 下载页要立刻变「暂未发布」 | 删除线上清单（`terminal/latest.json` / `terminal/android/latest.json`）⇒ 下载页读不到就显示「暂未发布」，不编造版本号；恢复 = 重新跑一次发布 |

## 6. 证书现状（如实登记）

- **Windows 未签名**：已购的 `migaozn.com` 是 TLS 域名证书（DV，EKU=Server Authentication），
  **不能**用于 Authenticode；代码签名需另买 OV/EV 且要云签名/HSM 形态（否则 CI 无法自动出包）。
- 因此 Windows 首次运行会出现 **SmartScreen** 提示（「Windows 已保护你的电脑」）⇒ 官网下载页写明
  「更多信息 → 仍要运行」，并公布 **SHA256**；安装程序启动时也会把自己的 SHA-256 写进日志/界面（终端仓实现）。
- **Android 签名**：keystore 只存终端仓 Secrets（`ANDROID_KEYSTORE_BASE64` 等）。**换 key = 已装机器无法升级**
  （必须卸载重装）⇒ 这把 key 是长期资产，不随发布流程变动。
- **不上架应用市场**：终端只从官网下载页面直发（企业内部工具、无市场审核流程）；
  安装需允许「未知来源应用」，下载页已写明。

## 7. 已知坑（终端仓侧，登记待办）

- **Windows 版本比较是字符串比较**（`string.Compare(latest, current) > 0`，`current` = `1.0.0.0`）
  ⇒ `1.0.10.0` 会被判成小于 `1.0.9.0`。**当前口径**：本仓发布时把版本写成 4 段（`x.y.z.0`），
  并在跨十位时人工确认；根治在终端仓（terminal#12：改成数值比较）。
- **Android `versionCode` 必须单调递增**：它由终端仓 CI 的 `github.run_number` 产生
  ⇒ 本仓发布时以 Release 里的 `latest-android.json`（或人工输入）为准，**不许猜**。

## 8. 未覆盖 / 重启条件

- 终端仓的「Release 自动出包」不在本仓射程（terminal#12）；本仓发布腿对缺失/命名不符的资产**判红**。
- `TERMINAL_REPO_TOKEN` 是人工前置；本仓判据**不验证**它是否已配置（需要一个真 token 才能验），
  只保证「缺它 ⇒ 第一步出声失败」。
- 线上 served 断言跑在发布腿里（`.github/workflows/terminal-publish.yml` 最后一步），本文**不代替**它。
