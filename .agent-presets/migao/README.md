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
  软链指向**专职只读镜像**（独立克隆的 `.agent-presets/migao`，见「接线」）后，仓库 `main` 的内容即生效内容 ——
  ⚠️ 但**镜像要有人去刷新**（`./scripts/preset-anchor-refresh.sh`）：锚点落后时「合并即生效」并不成立（`#4026`）。
- **历史独立仓库 `zhaokai-mgzn/migao-agent-presets` = 历史 / 镜像**：本目录内容由它迁入。
  **迁移后以产品仓库为准**；两边都可被编辑 → 会漂移，因此**不要再向独立仓库提交新改动**
  （除用户明确裁定的归档窗口内的一次性收尾）。
- **⚠️ 待用户拍板的分叉**：独立仓库的远程（**保留 / 归档 / 删除**）尚未裁定。
  裁定前**不删除、不 force-push** 该仓库；换链前本机 `~/.dsh/.agent-presets/migao` 仍指向它
  （换链见「接线」，顺序：**先合并、后换链**）。

## 接线（本机 / 换机 / 新队友）

**⚠️ 两条铁律**：① **先合并含本目录的 PR，再换链** —— 仓库尚无 `.agent-presets/migao/` 时换链会让 DSH 当场失效；
② **锚点必须指向「专职只读镜像」**（独立克隆），**不是**任何会被开发、被切分支、被清理的工作区 —— 理由见下节「两条实测」。

```bash
# ① 建专职只读镜像（独立克隆；本机约定 $HOME/migao-preset-anchor —— 长期保留、勿删）
MIRROR="$HOME/migao-preset-anchor"
git clone --no-checkout <产品仓库 URL> "$MIRROR"
git -C "$MIRROR" checkout --detach origin/main
ls "$MIRROR/.agent-presets/migao/preset.yml"     # 镜像里已有该路径才继续

# ② 摘掉旧目录 / 旧软链（若是实体目录，先备份而不是直接删）
mv "$HOME/.dsh/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true

# ③ 换链：-s 建软链 / -f 覆盖已存在项 / -n 不跟随已存在的软链目录
ln -sfn "$MIRROR/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao"

# ④ 校验：应能读到 preset 元数据与技能
cat "$HOME/.dsh/.agent-presets/migao/preset.yml"
head -3 "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/SKILL.md"

# ⑤ 开工自检 / 自愈（在产品仓库任一工作区根目录跑）
./scripts/preset-anchor-check.sh      # 落后 / 悬空 / 内容不同 / 技能加载不了 ⇒ 非零退出（红就停）
./scripts/preset-anchor-refresh.sh    # 把镜像刷到 origin/main 并复检（预设 PR 合并后必跑一次）
```

- **换机 / 新队友**：`git clone` 产品仓库 → 跑上面 ①~④，即获得**同一份**研发模式
  （不再依赖个人 `~/.dsh` 里的手抄副本：手抄副本没有跟随机制，必然腐烂）。
- ⚠️ **「合并到 `main` 就自动生效」只在锚点跟得上时才成立**：镜像**不会自己 fetch** ——
  预设 PR 合并后跑一次 `./scripts/preset-anchor-refresh.sh`，否则下一个会话读到的仍是旧模式（`#4026`）。

## 本机 live 锚点与运维铁律（2026-09-17 换链到**专职只读镜像** `~/migao-preset-anchor`；issue #4026）

**现行锚点**：`~/.dsh/.agent-presets/migao` → `$HOME/migao-preset-anchor/.agent-presets/migao`
（**独立克隆** + `checkout --detach origin/main`：它不是 worktree、不是主工作区、不承载任何开发改动）。

**为什么必须是独立克隆（两条实测，缺一不可）**：

- **落后形态**（`#4026`，2026-09-17）：原锚点指向产品仓库**主工作区**。主工作区会落后 `main`
  —— 实测落后 **42 个提交**，而**内容当时恰好一致**（所以「比版本号/比内容」都看不出问题）。
  危险在**下一次**：一旦有 PR 改了 `.agent-presets/**` 并合并，改进就**永远到不了加载点**，
  后续所有会话读到的仍是旧模式 —— 这就是「**迭代了但模式没进化**」的确切机制，且**零检查会因此变红**。
- **被删形态**（`#3956`，2026-09-16 事故）：更早的锚点是独立 sparse clone `~/ai native/migao-preset-live/`，
  一条 AI 会话的清理命令 `rm -rf migao-loop migao-preset-live migao-agent-presets …` 把**软链目标**硬删了
  ⇒ 软链悬空 ⇒ DSH 扫不到 preset（“a dangling link is not a preset”）⇒「米高研发」从 DSH 消失、
  新建/恢复会话报 `agent-preset/not-found`，且**无任何报错**（静默失效）。
  **教训：锚点是「live 内容本身」，不是可清理的工作副本 —— 目标被删 = 模式当场消失。**
  故本机锚点路径取 `$HOME/migao-preset-anchor`（名字即「锚点」，刻意不带 `-live`/`-wt` 这类"临时工作副本"语义），
  并在镜像根放 `DO-NOT-DELETE-anchor.md` 供人识别。

**为什么不用 git worktree 做锚点**：worktree 属 `scripts/dev-worktree.sh rm` / `git worktree prune` 的
**清理半径**（「可丢弃」语义）⇒ 被删即软链悬空 ⇒ DSH 静默加载不到研发模式。
`preset-anchor-refresh.sh` 已把这条**固化成判据**：镜像的 `git-common-dir` 不是它自己的 `.git`（= 它是某仓库的
worktree）⇒ **拒绝刷新**并打印原因，而不是"先刷了再说"。

**运维铁律（锚点不是"另一个工作区"，是 live 内容本身）**：

1. **只读**：不得就地编辑、不得切分支、不得留未提交改动 —— 否则会变成「**藏在软链目标里的第三份副本**」：
   它直接生效，却**没有 PR、没有评审、没有 diff 提醒**，比双源漂移**更隐蔽**。
   `preset-anchor-refresh.sh` 见到**已跟踪文件脏**就 fail-closed 停手（不静默覆盖）。
2. **跟 `main`**：生效版本 = 镜像 `origin/main` 版本。跑 `./scripts/preset-anchor-refresh.sh`
   （`fetch` + `checkout --detach origin/main` + 复检）；开工前先跑 `./scripts/preset-anchor-check.sh`（红就停）。
3. **不可删**：锚点**不参与任何清理流程**。执行清理**之前**先
   `readlink "$HOME/.dsh/.agent-presets/migao"`，把解析出的目标及其父目录**排除在外**。

**健康检查（换链后 / 怀疑「研发模式消失/不变」时）**：

```bash
readlink "$HOME/.dsh/.agent-presets/migao"        # → …/migao-preset-anchor/.agent-presets/migao
test -e "$HOME/.dsh/.agent-presets/migao" && echo "软链目标存在 ✓" || echo "⚠️ 悬空软链——DSH 加载不到 preset"
cat "$HOME/.dsh/.agent-presets/migao/preset.yml" >/dev/null && echo "preset 元数据可读"
./scripts/preset-anchor-check.sh                  # 一条命令判「新鲜 / 落后 / 悬空 / 内容不同 / 加载不了」
```

> ⚠️ 锚点选择**救不了**「从构建产物启动 DSH」这条路径：那条限制与锚点位置无关，见下一节。

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
- **frontmatter `description` 是 YAML 纯标量 ⇒ 第一个「空白 + `#`」处静默截断**（`#` 起被当成注释起始）
  —— 「**文件里写了**」≠「**加载器读到了**」（与 `migao-acceptance`「注释漂移 = 假绿来源」同族，但更隐蔽）。
  实证（2026-09-15，用**加载器同一个 `yaml` 包**解析）：`migao-dev-flow` 的 `description` 原文
  **2666 字符，解析结果只有 192 字符**（截断于「v1.11（2026-09-09 issue」），
  ⇒ v1.12/v1.17/v1.18/v1.19/v1.20 的说明**从未**出现在技能目录里，只有打开文件的人才看得到。
  `migao-acceptance` 的 `description` 原为 **777 字符、100% 是沿革** —— 今天**恰好**完整（内容里 0 个 `#`），
  但**距静默截断只差一处「空白 + `#`」**，且让技能目录每次多背约 700 字符。
  **本目录约定（dev-flow 自 v1.21 起、acceptance 自 v1.7 起，两者均已完成）**：`description` 只写
  **有意简短的摘要**（触发语 + 何时必须加载 + 范围 / 核心机制 —— 现分别 308 / 233 字符）；
  **变更沿革写进正文 `## 版本沿革` 节**；确需在 frontmatter 放长文本，必须加引号或用块标量（`>-`）
  —— 不靠加引号救长文本，因为那等于保留「可以无限往后追加」的坏习惯。
  另注：DSH 的 skill 加载器**只读 `name` + `description`**（缺任一即忽略该技能），且要求
  **第 1 行就是 `---`**（在 frontmatter 之前加注释会让整个技能被忽略）；`version` **不参与加载**，
  仅供人工 / 锚点新鲜度核对。

## 纪律

- 这是**团队标准**，不是个人草稿：改动请走 PR + 评审，commit message 写清「为什么改」。
- 与产品仓库的分工：产品契约/门禁代码在仓库对应模块；**流程与人机协作规则**在本目录。
- 决策记录（例如「行为映射门禁不纳入 required」「交互形态统一，安全由 admin-api 层承担」）写在
  `skills/*/SKILL.md` 里，作为可追溯依据。
