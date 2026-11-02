# 上游框架「二郎神 / ershen」出处记录（仓已删除）

> **2026-11-02 已删除**（用户的仓，`gh repo delete`，不可逆）。此前 2026-10-02 归档。
> 本页 = 出处记录 + **从本地 bundle 取回**的唯一路径。

## 裁定

用户 2026-10-02 逐字：「**当前只给 migao 在用**」⇒ 上游框架仓没有其他消费者，先归档。
用户 2026-11-02 逐字：「**把 ershen 和 mattpocock-skills-dsh 都删了，不要 fork 别人的东西了**」⇒ 归档仓删除。
（背景：`zhaokai-mgzn/ershen`「二郎神 Loop Engineering 部署包」自述「将任意 git 项目接入 AI 驱动的全链路质量闭环」，
330 文件，最后提交 `8a8cfa5` @2026-09-02，最后推送 2026-09-21。）

## 它是 migao 的什么

**上游框架 + 种子来源**（不是死代码）：

| 上游内容 | migao 侧现状 |
|---|---|
| `seed/migao/cases/*.yml`、`seed/migao/ci/*.yml` | **已被取代**：本仓 `.github/cases/**`（单一源）与 `.github/workflows/**` 自成体系 |
| `design/01..20+.md`（含 `16-case-contract.md`、`20-migao-ui-redesign.md`） | migao 代码/注释曾以它们为「标准/设计依据」⇒ 引用已改成「上游已删除」并指向本页 |
| `engine/{ci,dsh,visual,junshi,openclaw,qa,agents}` | 通用引擎（含 DSH 集成补丁）—— **与 migao 现用链路无关**：migao 的研发模式现由独立预设仓承载 |
| `seed/verticals/ecommerce`、`seed/template` | 面向**其他项目**的种子/模板，migao 不用 |
| `contracts/`、`config/`、`memory/`、手册两本、`deploy.sh` | 框架自身运行物，migao 不用 |

**migao 对它的运行期/部署期依赖 = 0**：现取没有任何 workflow / deploy 腿读 `/opt/ershen`（该路径仅出现在一处旧说明里，本包已修）。

## 未搬入 migao 的资产（**有意**，具名）

`qa-prompt-v4.txt`、`learned_rules.json`、`keyword-coverage.yml`、`keyword-stop.yml`、`jobs.json`
（框架自身的循环运行物；migao 侧无对应消费点）。**若将来发现需要 ⇒ 按下面的 bundle 路径取回。**

## 要取回时（仓已不存在，**只能**从本地 bundle 取）

删除前已留**双副本** git bundle（两份 sha256 逐字节一致 = `cc8534a4169700e805f7e3e1a25cda999282912c56e31d63c9b384503cf93c7f`）：

```
~/migao-archive/2026-11-02-ershen-backup/            # 主副本
~/Documents/migao-archive/2026-11-02-ershen-backup/  # 第二副本
├── ershen-local-20261002.bundle            全量历史（17 个 ref / 1844 个对象 / 1.29 MB）
├── ershen-local-20261002.uncommitted.patch 打包时未提交的改动
├── ershen-local-20261002.status.txt        打包时的工作树状态
└── README.md                               校验读数 + 取回说明
```

```bash
B="$HOME/migao-archive/2026-11-02-ershen-backup/ershen-local-20261002.bundle"
git bundle verify "$B"                    # 应输出：The bundle records a complete history.
mkdir -p ershen && cd ershen && git init -q
git fetch "$B" 'refs/*:refs/mirror/*'
git checkout refs/mirror/heads/main       # 或 refs/mirror/tags/<tag>
git apply ../migao-archive/2026-11-02-ershen-backup/ershen-local-20261002.uncommitted.patch  # 需要那三处未提交改动时
```

- **最后有效 sha（GitHub 侧 main HEAD）**：`8a8cfa5daf96996dafc15b67ad2a92eb6b8682ab`
  （2026-09-02「fix(automerge): dependabot PR 跳过关联 issue 要求」）
- **bundle 里的 `refs/mirror/heads/main`**：`0390bb079f9f2b337771e12594bd8cd69f1a62c9` —— 是 `8a8cfa5` 的**子提交**
  （「fix(labels): 标签名对齐 review/* 并停止 automerge 重复评论」），**只存在于本地、从未推送**
- 标签：`phase-1` … `phase-5`、`pre-demigao`（bundle 内齐全）

## 删除执行读数

```
执行时间（本机 Asia/Shanghai）：2026-11-02 16:46
取消归档（如需，已不可能：仓已删除）—— 2026-10-02 的 gh repo archive 读数保留如下：
  2026-10-02 22:16:25 CST  gh repo archive zhaokai-mgzn/ershen --yes  ⇒ archived=true
  归档时 main HEAD sha：8a8cfa5daf96996dafc15b67ad2a92eb6b8682ab
删除命令：gh repo delete zhaokai-mgzn/ershen --yes          ⇒ rc=0
删除前复验：git bundle verify ⇒ The bundle records a complete history.（17 refs）
删除后复验：gh repo view zhaokai-mgzn/ershen ⇒ Could not resolve to a Repository
```

- **`gh repo unarchive` 这条路已作废**：仓已删除，任何「去 unarchive / 去 clone」的旧指引都会 404，取回只认上面的本地 bundle。
- migao 侧对本仓的依赖 = **0**（运行期/部署期无引用；文本引用已在本页 + 各引用点标注「上游已删除」）。
