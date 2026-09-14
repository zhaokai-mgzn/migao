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

## ⚠️ 已知限制：从构建产物启动时软链会被静默忽略

**软链布局只在「从源码运行 DSH」时可靠**（如 `pnpm dsh web` 经 `tsx` → 解析到包的 `src/`）。
**从构建产物启动（包入口 `lib/`，例如 npm 安装的 CLI / desktop 壳 / 直接依赖 `@deepseek-ai/dsh-agent-presets`）
时，本目录这种「目录软链」会被静默跳过** —— **不报错、不告警**，表现只是「研发模式不见了」。

- 差异在 DSH 的 preset 扫描器（DSH 仓库 `packages/preset/agent-presets/`）：
  - `src/discovery.ts` **已支持软链** —— `Dirent.isDirectory()` 不跟随软链，故对 `child.isSymbolicLink()`
    再用 `stat` 判目录（**dangling link 不算 preset**）；注释原文即称这是
    “the documented layout for a version-controlled preset repo” 场景（2026-09-14 加入）；
  - 构建产物 `lib/index.js` 的 `scanRoot` 仍只有
    `if (!child.isDirectory() || !PRESET_ID.test(child.name)) continue;` —— **没有任何软链解析**。
- 该构建产物**比源码旧**（实测 mtime：`src/discovery.ts` **2026-09-14 18:45** > `lib/index.js` **2026-09-11 22:31**），
  且该包**没有自己的 build 脚本**（由 DSH 仓库根 `scripts/build.ts` 统一构建，只接受 `--profile`，**无单包选择器**）
  ⇒ **无法只重建这一个包**。
- ⇒ **若你走构建产物路径，请先整体重建 DSH**（使 `lib` 含软链修复）；否则表现为
  **「研发模式不见了，但没有任何报错」** —— 正是我们一直在治的静默失效形态。
- **⚠️ 证据强度限定（登记为未验证项，勿当实测结论）**：以上是**静态证据**（读 `src`/`lib` 源码 + 包入口
  `"main": "lib/index.js"` + 文件 mtime 对比），**尚未实际用构建产物启动 DSH 复现**「研发模式无声消失」；
  本次也**未重建 DSH 的 `lib`**（全仓重建影响面大，且不属于本仓库职责）。**是否重建交由用户裁定。**

## 纪律

- 这是**团队标准**，不是个人草稿：改动请走 PR + 评审，commit message 写清「为什么改」。
- 与产品仓库的分工：产品契约/门禁代码在仓库对应模块；**流程与人机协作规则**在本目录。
- 决策记录（例如「行为映射门禁不纳入 required」「交互形态统一，安全由 admin-api 层承担」）写在
  `skills/*/SKILL.md` 里，作为可追溯依据。
