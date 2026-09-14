# MIGAO 研发模式 preset（米高研发）

MIGAO（米高）**研发模式**的 DSH agent preset，**随产品仓库一起版本化**：权威源就是本目录
（`migao/.agent-presets/migao/`）—— 可评审、可回溯、换机不丢（issue #3614）。

## 这是什么

DSH（DeepSeek Harness）的 agent preset：定义「米高研发」Agent 的人格、技能与工作流约束。
DSH 从**已配置的 roots** 发现 preset（`USER_PRESET_DIR = '.agent-presets'`，即本机 `~/.dsh/.agent-presets/`），
本目录通过软链接入（见下文「接线」）。

包含：

| 文件 | 作用 |
|---|---|
| `preset.yml` | preset 元数据（名称/描述） |
| `agent.cordis.yml` | agent-plane 组合：persona + 技能挂载 |
| `skills/migao-dev-flow/SKILL.md` | 开发提效流程：三把工具、提交流程、§13 行为改动自动体检、§13.5 用例陷阱、§14 用例库演进、§15 前端 UI 旅程、§16 分层探测/门禁矩阵、**§17 并行修复原则**、决策记录 |
| `skills/migao-acceptance/SKILL.md` | 可执行验收协议：L1/L2/UA + 证据链 + 双 AI 交叉验证（零人工执行步骤）+ **假绿/假红治理（断言红证）** + **空跑治理（核「真的跑了吗」）** |
| `.gitignore` | 仅**本目录**生效：排除本机残留备份（`*.rc2-backup` / `*.bak`）/ `.DS_Store`；**不覆盖产品仓库根 `.gitignore`** |

> 原独立技能 `tdd-iron-law` 已于 2026-09-14 收敛并入 `migao-dev-flow`（E2E 选择器优先级 → §15.6、QA Gate 文件类型表 → §3.4），不再单独存在。

## 权威源与历史独立仓库（⚠️ 含一项待裁定）

- **权威源（single source of truth）= 本目录** `migao/.agent-presets/migao/`（issue #3614 裁定）。
  研发模式的**改动 = 产品仓库的 PR**，与代码同流程评审、同历史回溯；`~/.dsh/.agent-presets/migao`
  软链指向本目录（或本目录所在的工作区）后，仓库 `main` 的内容即生效内容。
- **历史独立仓库 `zhaokai-mgzn/migao-agent-presets` = 历史 / 镜像**：本目录内容由它迁入。
  **迁移后以产品仓库为准**；两边都可被编辑 → 会漂移，因此**不要再向独立仓库提交新改动**
  （除用户明确裁定的归档窗口内的一次性收尾）。
- **⚠️ 待用户拍板的分叉**：独立仓库的远程（**保留 / 归档 / 删除**）尚未裁定。
  裁定前**不删除、不 force-push** 该仓库；换链前本机 `~/.dsh/.agent-presets/migao` 仍指向它
  （换链见「接线」，顺序：**先合并、后换链**）。

## 接线（本机 / 换机 / 新队友）

**⚠️ 顺序铁律：先合并含本目录的 PR，再换链** —— 仓库尚无 `.agent-presets/migao/` 时换链会让 DSH 当场失效。

```bash
# 在已克隆（且已含本目录）的 migao 仓库根目录执行
ls .agent-presets/migao/preset.yml     # ① 先确认仓库里已有该路径

# ② 摘掉旧目录 / 旧软链（若是实体目录，先备份而不是直接删）
mv "$HOME/.dsh/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true

# ③ 换链：-s 建软链 / -f 覆盖已存在项 / -n 不跟随已存在的软链目录
ln -sfn "$PWD/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao"

# ④ 校验：应能读到 preset 元数据与技能
cat "$HOME/.dsh/.agent-presets/migao/preset.yml"
head -3 "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/SKILL.md"
```

- **换机 / 新队友**：`git clone` 产品仓库 → 在仓库根跑上面 ②~④ 即获得**同一份**研发模式
  （不再依赖个人 `~/.dsh` 里的手抄副本）。
- 软链指向工作区文件，**合并到 `main` 后自动生效**（拉取即更新，无需重链）。

## 纪律

- 这是**团队标准**，不是个人草稿：改动请走 PR + 评审，commit message 写清「为什么改」。
- 与产品仓库的分工：产品契约/门禁代码在仓库对应模块；**流程与人机协作规则**在本目录。
- 决策记录（例如「行为映射门禁不纳入 required」「交互形态统一，安全由 admin-api 层承担」）写在
  `skills/*/SKILL.md` 里，作为可追溯依据。
