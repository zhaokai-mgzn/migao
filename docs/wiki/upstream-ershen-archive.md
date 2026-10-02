# 上游框架「二郎神 / ershen」归档记录

> 2026-10-02 归档。**只读、可 unarchive**（不是删除）。本页 = 出处记录 + 「要取回时怎么取」。

## 裁定

用户 2026-10-02 逐字：「**当前只给 migao 在用**」⇒ 上游框架仓没有其他消费者，归档处置。
（背景：`zhaokai-mgzn/ershen`「二郎神 Loop Engineering 部署包」自述「将任意 git 项目接入 AI 驱动的全链路质量闭环」，
330 文件，最后提交 `8a8cfa5` @2026-09-02，最后推送 2026-09-21。）

## 它是 migao 的什么

**上游框架 + 种子来源**（不是死代码）：

| 上游内容 | migao 侧现状 |
|---|---|
| `seed/migao/cases/*.yml`、`seed/migao/ci/*.yml` | **已被取代**：本仓 `.github/cases/**`（单一源）与 `.github/workflows/**` 自成体系 |
| `design/01..20+.md`（含 `16-case-contract.md`、`20-migao-ui-redesign.md`） | migao 代码/注释曾以它们为「标准/设计依据」⇒ 本包已把引用改成「上游已归档」并指向本页 |
| `engine/{ci,dsh,visual,junshi,openclaw,qa,agents}` | 通用引擎（含 DSH 集成补丁）—— **与 migao 现用链路无关**：migao 的研发模式现由独立预设仓承载 |
| `seed/verticals/ecommerce`、`seed/template` | 面向**其他项目**的种子/模板，migao 不用 |
| `contracts/`、`config/`、`memory/`、手册两本、`deploy.sh` | 框架自身运行物，migao 不用 |

**migao 对它的运行期/部署期依赖 = 0**：现取没有任何 workflow / deploy 腿读 `/opt/ershen`（该路径仅出现在一处旧说明里，本包已修）。

## 未搬入 migao 的资产（**有意**，具名）

`qa-prompt-v4.txt`、`learned_rules.json`、`keyword-coverage.yml`、`keyword-stop.yml`、`jobs.json`
（框架自身的循环运行物；migao 侧无对应消费点）。**若将来发现需要 ⇒ 从归档仓按下面的 sha 取回。**

## 要取回时

```bash
# 归档仓仍可读（只读）：
git clone git@github.com:zhaokai-mgzn/ershen.git          # 或 gh repo clone
git -C ershen checkout <sha>                              # 最后有效状态
# 需要解归档（恢复可写）时：
gh repo unarchive zhaokai-mgzn/ershen
```

- **本记录建立时的最后有效 sha**：`8a8cfa5`（2026-09-02「fix(automerge): dependabot PR 跳过关联 issue 要求」）
- **归档动作执行时的 sha**：`8a8cfa5daf96996dafc15b67ad2a92eb6b8682ab`（见下方读数）

## 归档执行读数

```
执行时间（本机 Asia/Shanghai）：2026-10-02 22:16:25 CST
命令：gh repo archive zhaokai-mgzn/ershen --yes
结果：archived=true（只读；内容仍可 clone / 网页只读访问）
归档时 main HEAD sha：8a8cfa5daf96996dafc15b67ad2a92eb6b8682ab
```

- 归档**不删内容**；需要恢复可写：`gh repo unarchive zhaokai-mgzn/ershen`。
- migao 侧对本仓的依赖 = **0**（运行期/部署期无引用；文本引用已在本页 + 各引用点标注「已归档」）。
