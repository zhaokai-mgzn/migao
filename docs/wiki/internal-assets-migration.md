# 内部资产迁出公开仓（2026-11-02）

> 公开仓 `zhaokai-mgzn/migao` 只承载「**CI 真读的东西**」。本页记录 2026-11-02 迁出的三类内部资产。

## 迁去了哪里

**私有仓 `zhaokai-mgzn/migao-internal`**（需 `zhaokai-mgzn` 账号访问）。

| 原路径 | 现位置 | 为什么迁 |
|---|---|---|
| `product/**`（9 文件） | `migao-internal:product/**` | 商业机密：商业化蓝图 / 定价设计（年费/毛利/锚点）/ 投资人材料 / POC 方案 |
| `acceptance/**`（2607 文件 / 116 MB） | `migao-internal:acceptance/**` | 验收证据：截图、smoke 结果、harness 日志；含测试账号手机号 / 租户名 / 登录 token 截断残留 |
| `docs/audit-2026-08/09/10` | `migao-internal:docs/audit-2026-*/` | 内部审计：缺陷与风险清单、代码体量报告 |

## 判据（迁移前实测，零影响）

- `product/`：被 `.github/workflows/**` 引用 **0** 次、被 `tests/**` + `scripts/**` 引用 **0** 次；
- `acceptance/`：无任何测试 `open()` 它（`plaintext_credential_guard` 的 R3 射程只是**路径字符串**，
  目录不存在也不判红）；`xiaobu-acceptance.yml` 运行期自建 `acceptance/ci-<run_id>/`；
- `docs/audit-2026-*`：只在文档互链里出现（散文引用属历史记录，按 §9 口径不回改）。

**部署零影响**：三个服务从整仓 tarball 构建（`deploy/swas/deploy.sh`），这些路径都不在
`admin-api` / `ai-agent` / `admin-web` 的 Docker 构建上下文里。

## 边界（重要）

1. **历史没删**：`git rm` 只是「今后不再入库」。这些内容仍留在公开仓的 git 历史里
   （`product/` 5 个提交、`acceptance/` 150 个提交）——**已公开的事实无法回收**，
   要真正下架只能 `git filter-repo` 重写历史，代价是全部 commit sha 变化（134 个 issue、
   台账、验收证据里的 `@<sha>` 钉全部失效）。**裁定：不做**（forward-only）。
2. **公开仓不引用私有仓**：private 仓无法被 public 仓的 CI 读取 ⇒ 单向依赖只允许
   `migao-internal` 引用 `migao`。
3. **本仓的规矩照旧**：CI 门禁、case_ids、CHANGELOG 都留在公开仓；`migao-internal` 里的改动
   不面向用户、不产生可观察行为，**不需要**这些手续。

## 今后放哪儿

新增材料先问一句「**这能不能给陌生人看**」：

- 能 ⇒ 公开仓（`docs/**` 的规范与设计、代码、测试、CI）；
- 不能（客户名单、合同报价、现场照片、账号凭据、内部缺陷清单）⇒ `migao-internal`。

## 相关

- 拆分方案与判据全文：`research/repo-topology-2026-11-02.md`（本机工作区，非本仓）。
- 同批处置：上游框架 `ershen` 仓已删除，出处见 [upstream-ershen-archive.md](upstream-ershen-archive.md)。
