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
