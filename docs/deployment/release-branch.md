# 发布线（`release`）：main 收 PR，部署只认 release

> 定于 2026-11-21（用户裁定 A）。适用于生产环境 `cytda.com` 的一切发布。

## 口径

| 分支 | 角色 | 谁动它 |
|---|---|---|
| `main` | **集成线**：PR、CI、评审、auto-merge 全部照旧 | 开发者（走 PR） |
| `release` | **发布线**：部署机**只认它** | 只有 `scripts/cut-release.sh`（快进） |

一句话：**「合进 main」≠「上线」**。上线是 `cut-release.sh` 那一下。

## 为什么

- 生产的可变因素收敛到**一个 sha**：`origin/release`。发布记录、`/api/version`、回滚点全用它对齐；
- 「谁合了 main 就自动上线」会让上线时间不可控（半夜合并、半成品合并都会直接出现在生产）；
- release 只允许快进 ⇒ **release 上永远不会有 main 没有的提交**，杜绝「生产跑的代码在仓库里找不到」。

## 怎么发

```bash
# ① 快进发布线（可在任意工作区跑；只改远端 ref，不动本地分支）
./scripts/cut-release.sh
#   ✅ release 快进完成 → a0b758b
#   REL_SHA=a0b758b01d6f736c425231927538a470afceb02d

# ② 只看差多少（不改远端）
./scripts/cut-release.sh --check

# ③ 部署机按 REL_SHA 发布（详见 prod-ops 技能）
#    发布后必须核对 /api/version == REL_SHA
```

## 判据（机械可查）

1. `git merge-base --is-ancestor origin/release origin/main` ⇒ 必须为真；
2. 部署机发布的 `sha` == `git rev-parse origin/release`；
3. `cut-release.sh` 遇到「release 有 main 没有的提交」⇒ **退出码 2**，不推送、不覆盖。

## 边界（如实登记）

- **没有**在 GitHub 侧加分支保护/守卫 workflow（本仓当前没开 auto-merge / 免费版无分支保护）。
  真正的强制点在**部署机**：`prod-ops` 技能要求发布前核 `release ⊆ main`、发布后核 `/api/version`；
- 因此「有人直接 push 到 release」在仓库侧**不会**当场变红 —— 只会在下一次发布时被部署机判据拦下。
  这是已知取舍：先用零成本判据挡住「发错版本」，等有分支保护时再前移。

## 手工路径也有判据（issue #9086，2026-11-23）

上面那条闸门此前只有**一处**：`deploy-prod.yml` 的「发布线纪律（只认 release）」步骤。
**主机上手工敲** `/opt/migao-deploy/deploy.sh` 就整段绕过它 —— 实测 2026-11-23 11:32–11:39 那次
绕过只更新了 admin-api（admin-web 还是两天前的镜像），脚本自己的结论却是绿的。

⇒ 部署脚本自己在 **1.0.1 段**（`# >>> release-line-assert` / `# <<< release-line-assert`）判一次，
位置**在任何下载 / 构建 / 拉镜像 / 切流之前**（检查晚于部署 = 没检查）：

| 判定 | 退出码 | 你会看到 |
|---|---|---|
| 目标 commit 是 `origin/release` 的**祖先** | `0` | `✅ RELEASE-LINE=OK target=<sha7> release=<sha7>`，继续部署 |
| **不是**祖先 | **`2`** | `❌ RELEASE-LINE=VIOLATION` + 两个 40 位 sha + 差多少个提交 + 「先 `./scripts/cut-release.sh` 把 release 快进到该提交」 |
| **判不了**（不是 git 仓 / `git fetch` 连续 3 次失败 / 拿不到 `origin/release` / 追不到目标 commit） | **`3`** | `❌ RELEASE-LINE=UNVERIFIED` + 具名原因 + 三个出口 |
| 判不了 + 显式逃生口 | `0` | `::warning::RELEASE-LINE=UNVERIFIED …` + 追加一行到 `/opt/migao-deploy/release-ledger.jsonl`，继续部署 |

判不了时**默认拒绝**（fail-closed）：与「不许往回走」闸门（`#4852`，判不了 fail-open）**有意不同** ——
那条判的是「往不往回走」（判不了可以放行），这条判的是「该不该发」，判不了放行 = 闸门消失。

### 逃生口（必须留在明面上并被记录）

```bash
# 两种写法等价（后者由脚本在解析 $TAG 之前剥掉）
ALLOW_UNVERIFIABLE_RELEASE=1 ./deploy.sh sha-<7位hex>
./deploy.sh --allow-unverified-release sha-<7位hex>
```

- 台账：`/opt/migao-deploy/release-ledger.jsonl`，每行
  `{"at":"<UTC ISO8601>","decision":"unverified-release","target":"<tag>","reason":"<为什么判不了>"}`；
- 为什么要有：生产机到 `github.com:443` 时通时不通（#4852 实测 `git clone --filter=tree:0` 超时 32s），
  没有逃生口的 fail-closed 会被绕成「把这段检查删掉」；有逃生口 + 落账 ⇒ 绕过是**可见的**、可追溯。

### 生效边界（照实登记）

- **新检查从「下一次部署」起生效**：主机盘上跑的是**旧脚本**；该脚本的自同步段
  （`# >>> deploy-selfsync`）先把同源脚本落到盘上、再 `exec` 原地重入，才执行得到新段
  ⇒ **手工跑旧脚本那一轮不受保护**（真正的止血点是「下一次部署」）。
- 本段只回答「这个 commit 在不在发布线上」，**不回答**「它过没过 CI」「镜像推没推上去」
  —— 那两条分别归 `deploy-prod.yml` 的其它步骤与拉取步骤。
- 判据（15 条，含 4 条注入式红证）= `tests/unit_ci_workflows/test_swas_deploy_release_line.py`
  （用例 `MC-346`）；既有执行式沙箱（blue-green / no-downgrade / disk-recovery 等）通过共享桩
  `tests/unit_ci_workflows/deploy_release_line_stub.py` 模拟「目标提交是 release 祖先」的正常形态。
