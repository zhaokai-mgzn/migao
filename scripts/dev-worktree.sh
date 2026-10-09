#!/usr/bin/env bash
# =============================================================================
# dev-worktree.sh — MIGAO 多分支并行开发工作区管理（git worktree 快捷封装）
#
# 背景：本地开多个分支做开发/验证时，反复 `git checkout` 切换会把工作区文件
# 整体替换为旧分支内容，未提交改动还会被静默携带 → 「切换分支后功能退化」。
# git worktree 让每个分支拥有独立工作目录（node_modules/dist 互不干扰），
# 切换零污染。本脚本封装常用操作。
#
# 用法（在 migao 仓库根目录执行）：
#   ./scripts/dev-worktree.sh add <branch> [路径]   # 为分支创建独立工作区（默认 ../migao-wt/<分支>）
#   ./scripts/dev-worktree.sh list                  # 列出所有工作区 + 会话锁状态
#   ./scripts/dev-worktree.sh lock                  # 查看/清理会话锁（多会话并发时先查锁）
#   ./scripts/dev-worktree.sh rm <分支|路径> [--delete-branch]  # 移除工作区（可选连带删分支）
#   ./scripts/dev-worktree.sh rebase <分支|路径>    # rebase origin/main（+ 顺带把活锚镜像带到预设仓 main）
#   ./scripts/dev-worktree.sh preset-guard [--source both|index|worktree]  # 提交路径守卫（版本下降 / 同号不同内容撞车 / 活锚落后即非零退出）
#   ./scripts/dev-worktree.sh prune --dry-run       # worktree 存量体检（只打印清单，不删除）
#   ./scripts/dev-worktree.sh doctor [--heal]       # 登记表 × 磁盘一致性自检（--heal：显式修复；默认只读）
#   ./scripts/preset-anchor-check.sh                # 活锚新鲜度自检（红就停；开工第一件事）
#   ./scripts/preset-anchor-refresh.sh              # 活锚自愈：只读镜像（预设仓）→ 预设仓 main（自检转绿）
#
# 🔴 S4（issue #6020，2026-10-02）：**预设已迁出业务仓**。预设内容的权威源 = 独立仓
#   `zhaokai-mgzn/migao-agent-presets`；本业务仓**不再承载** `.agent-presets/**`。
#   ⇒ 原先那套「worktree 的 `.agent-presets/**` 是创建时刻快照 / 快照挡住 rebase」的机制
#   （`refresh_presets()` / `discard_preset_snapshot()`，v1.8 #3851 + v1.9 #3972 + v1.13 #5707）
#   **随路径一起消失**：`add` / `rebase` 不再对 `.agent-presets/**` 做任何刷新或丢弃
#   （业务仓里根本没有这个路径 ⇒ 那是零动作）；`rebase` 现在就是一条普通的 `git rebase origin/main`。
#   真正的加载点仍然是**活锚**（软链 → 专职只读镜像 `$HOME/migao-dev-preset-anchor`），
#   由 `./scripts/preset-anchor-refresh.sh` 负责让它跟上**预设仓**的 main。
#
# 预设地雷与**三个面**（v1.8，2026-09-15 新增，issue #3851；S4 起面①/面④已不存在）：
#   ① 提交路径（本脚本 `preset-guard`）：判暂存/工作区**业务仓** `.agent-presets/**` 是否构成
#      **版本下降**，命中即 fail-closed；**合法升级放行**（改研发模式本身不能被堵死）；
#      **同号不同内容 = 跨包撞车 ⇒ 也判红**（v1.12 / #5425；出口逐字给「抬号到「基准版本 + 1」」）。
#      ⚠️ S4 起业务仓无该路径 ⇒ 本面**零动作放行**；预设内容侧的版本判据由**预设仓自己的 CI**承担
#      （预设仓 `.github/workflows/preset-guards.yml` + `tests/test_preset_guards.py`）。
#   ② 加载点（活锚 `~/.dsh/.agent-presets/migao`）：**必须自愈** —— `./scripts/preset-anchor-refresh.sh`
#      把专职只读镜像刷到**预设仓** main（`preset-guard` 同时判活锚新鲜度，落后/悬空即非零退出）。
#   ③ 清理半径：`rm` / `prune` 会命中 **worktree 里的软链与工作区目录** ⇒ 清理前先 `readlink` 活锚目标并
#      排除它（issue #3956 实证：软链目标被删 ⇒ DSH 静默加载不到研发模式）。
#   另：机械安全网（别处，互补）—— #3843 的统一审计 `drift_audit --check` 的版本单调性守卫（全库/定时对账）。
#   详见 docs/wiki/DEV-FLOW.md「预设落后地雷」节（落地单 #3859，事实单 #3851）。
#
# 地雷 B：内容全对，但**到不了加载点**（v1.10，2026-09-17 新增，issue #4026）：
#   `preset-guard` 原先只判「仓库里的 `.agent-presets/**` 有没有版本下降」——**查不出活锚落后**。
#   实测活锚（`~/.dsh/.agent-presets/migao` 软链）曾指向一个落后 `origin/main` **42 个提交**的主工作区：
#   内容当时恰好一致（无害），但只要下一次有人改预设并合并，改进就**永远到不了加载点**
#   ⇒ 后续所有会话读到的仍是旧模式（「迭代了但模式没进化」的确切机制）。
#   v1.10 起：`preset-guard`（判定本体 `scripts/agent-presets-guard.py`）同时判**活锚新鲜度**
#   （内容逐字节 + 检出 sha；落后/悬空/内容不同 ⇒ 非零退出），并给出同步命令：
#     ./scripts/preset-anchor-check.sh      # 只判（开工第一件事；红就停）
#     ./scripts/preset-anchor-refresh.sh    # 判 + 自愈（把**专职只读镜像**刷到预设仓 main）
#   活锚目标必须是**独立克隆**（不是任何会被开发的 worktree —— 那在 rm/prune 清理半径内，
#   被删即软链悬空、DSH 静默加载不到研发模式，issue #3956 实证）；见根 AGENTS.md「开发环境准备」。
#
# 地雷 C：**跨工作区共享 node_modules 的软链** × **任何删/重建 node_modules 的动作**
#   （v1.14，2026-10-01，issue #5930）：
#   现场实测（本机 22:18）：主工作区 `tests/node_modules` 变成**空目录**，而 **git 里看不见任何异常**
#   （软链不入库、破坏发生在**仓库外**）⇒ 静默失效，没有任何判据会报。共同根因是一个**类**：
#   worktree 里把依赖软链到主工作区（`node_modules` → 主仓库同名目录），此后
#   ① `npm ci`（第一步就是删 node_modules）**会穿过软链把目标清空** —— 本包实测：目标目录仍在、
#      内容全空（fixture 3 → 0 个文件；现场读数 = 空目录），读数与复算命令写进 issue #5930；
#   ② 删除 worktree 的动作**不得**再给它一次机会 —— 本脚本 `rm` 现在**先解链再删**（见下）。
#   两条口径（**同源**，别处不另写一份）：
#     · 依赖一律在本工作区内安装（npm ci）；禁止把 node_modules 软链到主工作区或其他工作区
#       （正确姿势见 docs/wiki/Development.md 的「worktree 依赖准备」节，与 `add` 的输出同源）；
#     · `rm` 的**顺序即安全顺序**：`unlink_symlinks_before_remove` 必须**先于** `git worktree remove`，
#       否则删除动作就可能穿过软链打到仓库外。判据 =
#       tests/unit_ci_workflows/test_dev_worktree_symlink_safety.py（控制流判据 + PATH 垫片见证
#       「删除那一刻 worktree 里还有没有软链」+ 真 fixture 上断言外部目标逐字节完好）。
#
# 地雷 D：**登记表 × 磁盘不一致**（v1.15，2026-10-03，issue #6235）：
#   `git worktree list` **登记**了某个 worktree，但它的目录**在磁盘上不存在**。此时
#   ① 该分支被判「已被该 worktree 占用」⇒ `git worktree add <path> <branch>` 直接
#      `fatal: … is already used by worktree at …`；
#   ② **`git worktree prune` 与 `git worktree remove --force` 都可能无效**（实测两种顽固形态：
#      a) `.git/worktrees/<name>/locked` 存在且目录已消失 ⇒ prune 静默**什么都删不掉**、remove 报
#         `cannot remove a locked working tree`；b) 目录还在但 `.git` 已没 ⇒ prune 静默不动、add 报
#         `already exists`。两种都**没有任何东西会因此变红** ⇒ 每个撞上的包白花 3~4 轮手工诊断
#      —— 与铁律 11「声明存在 ≠ 可达」同族）。
#   ⇒ 本脚本把「**登记表里的每个路径在磁盘上真的存在**」变成一条**断言**：
#      · 每个入口（`add` / `rebuild` / `rm` / `rebase`）前置自查：命中漂移 ⇒ 打印**将删清单** →
#        自愈（先 `git worktree prune`，仍残留的按白名单删除 `.git/worktrees/<name>` 后复跑 prune）
#        → 复检；**仍红则 fail-closed 拒绝继续**；
#      · `doctor`（只读）/ `doctor --heal`（显式入参修复）随时可单跑；
#      · 🔴 **安全护栏**：删除落点**只允许** `.git/worktrees/<name>`（git 元数据），
#        `…/migao-wt/<name>` / `…/migao-dev/<name>` / `$HOME` / **本仓 worktree 根目录** / 任何
#        越界或**经软链逃逸**的路径**一律拒绝**并打印原因（`wt_registry_guard`）；
#        删除类动作**不做无人值守**：`doctor --heal` 要显式入参，任何删除前都**先打印将删清单**。
#      · 判据 = tests/unit_ci_workflows/test_dev_worktree_registry_drift.py（红证：造「登记存在、
#        磁盘没有」的 fixture ⇒ 旧行为下 add 复现「already used by worktree」；新行为下自愈后 add 成功）。
#
# 会话锁（v1.3，2026-09-04 新增）：
#   多 DSH 会话并行开发防踩脚 —— add 时自动在 $REPO_ROOT/.git/sessions/ 登记会话锁
#   （进程 PID + 时间戳），同一分支已有活跃锁时拒绝重复建工作区；
#   rm 自动清理；lock 子命令查看/手动清理（含失效锁）。锁目录在 .git/ 下，
#   不污染工作区、不进 git。
#
# 误删保护（v1.5，2026-09-05 新增）：
#   rm --delete-branch 曾因 worktree 分支解析歧义误删本地 main（issue #2930）：
#   ① 改为按 path 从 `git worktree list --porcelain` 权威解析该工作区 HEAD 的分支；
#   ② 主干分支（main/master）硬保护，拒绝通过 --delete-branch 删除；
#   ③ 删除前打印实际删除的分支名，便于审计。
#
# worktree 内执行支持（v1.6，2026-09-05 新增，issue #2933）：
#   在任一 git worktree 内直接运行本脚本时，$ROOT/.git 是指针文件（gitdir: → 主仓库），
#   git 管理命令 / 会话锁 / 默认 worktree 目录必须基于主仓库根 REPO_ROOT（由
#   `git rev-parse --git-common-dir` 归一化），否则 mkdir 锁目录会静默失败。
#
# 环境变量：
#   MIGAO_WT_BASE=...  # 覆盖工作区根目录（默认仓库父目录下的 migao-wt/）
#   FORCE_LOCK=1       # 忽略会话锁强制建工作区（危险，仅确认无活跃会话时用）
#   MIGAO_WT_PY=...    # 覆盖用于「登记表 × 磁盘」自查的 python3（默认 python3.11 || python3；判据注入点）
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被
# 并入变量名（如 `$path（` → `path<0xE3>` 报 unbound variable），
# 因此所有后跟中文的变量一律用 ${var} 显式包裹。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# v1.6（issue #2933）：归一化到主仓库根 —— --git-common-dir 总是指向主仓库 .git
# （在 worktree 内执行时亦然），git 命令/会话锁/默认 worktree 目录都基于它。
# ⚠️ issue #6235 修正：`git rev-parse --git-common-dir` 常返回**相对路径**（`.git`），而
# `cd .git/..` 是相对**当前工作目录**解析的 —— 从别处调用本脚本（`bash <repo>/scripts/…`）
# 时那个路径不存在 ⇒ `cd` 失败（`set -e` 下更糟）。先用 `git -C "$ROOT"` 把主仓库根解成绝对路径。
REPO_ROOT="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
REPO_ROOT="$(cd "$(dirname "${REPO_ROOT:-$ROOT/.git}")" && pwd)"
WT_BASE="${MIGAO_WT_BASE:-$REPO_ROOT/../migao-wt}"
LOCK_DIR="$REPO_ROOT/.git/sessions"
mkdir -p "$LOCK_DIR"

usage() {
  # head 上限需覆盖「用法」块 + v1.8 的预设地雷说明（加新条目时同步上调，否则 --help 会截断）
  # v1.9（issue #3972）：用法块 +1 行（rebase 子命令）⇒ 上限同步 +2
  # v1.10（issue #4026）：用法块 +2 行（活锚自检/自愈脚本）⇒ 上限再 +2
  # v1.14（issue #5930）：新增「地雷 C：删除不许穿过软链」段（文件头 +18 行）⇒ 上限 46 → 80
  # S4（issue #6020）：文件头重写（预设迁出业务仓）⇒ 头部现 95 行，上限 80 → 100
  # v1.15（issue #6235）：新增「地雷 D：登记表 × 磁盘不一致」段（文件头 +20 行）⇒ 上限 100 → 120
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^dev-worktree.sh/,/^===/p' | head -120
  exit 1
}

# 分支名 → 工作区目录名：feat/xiaobu-voice-holdtalk → xiaobu-voice-holdtalk
slug() { echo "$1" | sed -E 's#^(feat|fix|chore|docs|test|refactor)/##; s#/#-#g'; }

# ── 地雷 D（issue #6235）：worktree **登记表 × 磁盘**一致性自查 / 自愈 ──────────────
# 登记条目 = `<common git dir>/worktrees/<name>`，其 `gitdir` 文件写的是该工作区里
# `.git` 的绝对路径 ⇒ 断言 = 「那个目录在磁盘上真的存在」（铁律 11：声明存在 ≠ 可达）。
# 判定与删除**全在下面这段 python 里**（pathlib 大小写/软链归一化比 bash 3.2 可靠得多），
# 出口码三态：`0` 无漂移 / `1` 有漂移（未自愈或存在被拒的落点）/ `2` 用法错 / `3` 无法判定。
GIT_COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || echo ".git")"
case "${GIT_COMMON_DIR}" in
  /*) : ;;
  *)  GIT_COMMON_DIR="${REPO_ROOT}/${GIT_COMMON_DIR}" ;;
esac
PY_BIN="${MIGAO_WT_PY:-$(command -v python3.11 || command -v python3 || true)}"
#: 登记表根（**删除落点白名单的唯一前缀**）。
WT_REGISTRY_DIR="${GIT_COMMON_DIR}/worktrees"

# ── 安全护栏：删除落点的白名单判定（守 `wt_registry_doctor --heal` 的**每一个**删除候选）──
# 只允许 `<common git dir>/worktrees/<name>`（git 元数据）。拒绝：
#   · 越界（`…/migao-wt/<name>` / `…/migao-dev/<name>` / `$HOME` / 本仓 worktree 根目录…）
#   · `<name>` 带路径分隔符或 `..` / `.`（`rm -rf .git/worktrees/../../..` 这种）
#   · 登记表目录或候选本身是**软链**（`rm -rf` 不跟随，但守卫路径必须 fail-closed）
#   · 落点本该是空目录却不是（防把有内容的目录当"残留"删掉）
# 入参：`<allow-empty-true|false>` + 候选绝对路径。逐条打印判定；任一被拒 ⇒ 非零退出。
wt_registry_guard() {
  [ -n "${PY_BIN}" ] || { echo "❌ 找不到 python3 —— 无法判定删除落点白名单（fail-closed）"; return 1; }
  "${PY_BIN}" - "$WT_REGISTRY_DIR" "$@" <<'PY'
import os, sys
from pathlib import Path

registry = sys.argv[1]
allow_empty = sys.argv[2] == "true"


def norm(p: str) -> Path:
    """归一化：软链展开 + `..`/`.` 折叠（比较前一律过这一道，防"看着在里面、实际在外面"）。"""
    return Path(os.path.realpath(p))


reg_n = norm(registry)
print("🛡️  白名单校验（删除落点**只允许** " + str(reg_n) + "/<name> —— git 元数据路径）：")
bad = 0
for arg in sys.argv[3:]:
    p = Path(arg)
    why = ""
    if not p.is_absolute():
        why = "不是绝对路径"
    elif p.is_symlink():
        why = "候选**本身是软链**（不跟随删除 = 拒绝，防落点被引到仓外）"
    else:
        n = norm(arg)
        name = n.name
        if name in ("", ".", ".."):
            why = f"落点名非法：{name!r}"
        elif n.parent != reg_n:
            why = f"落点不在白名单内：父目录 {n.parent} ≠ {reg_n}"
        elif name != p.name:
            why = f"名称经解析后变化：{p.name!r} → {name!r}"
        else:
            full = n / "gitdir"
            if not full.exists():
                pass  # 已消失的登记条目（无 gitdir）⇒ 允许
            elif not (n / "gitdir").is_file():
                why = "gitdir 不是普通文件"
            elif name == (registry.split("/")[-1] if registry.split("/") else "") or name in ("worktrees",):
                why = "名称与登记表根同名（越界形态）"
            elif not (n / "commondir").exists():
                pass  # 旧版 git 可无 commondir ⇒ 不作拒绝理由
            if not why and allow_empty and n.exists() and n.is_dir() and any(n.iterdir()):
                why = "落点是**非空目录** —— 只在它确系本登记条目残留时才允许删除"
    if why:
        bad += 1
        print(f"   ⛔ 拒绝删除：{arg}")
        print(f"      原因：{why}")
    else:
        print(f"   ✅ 允许删除（在 .git/worktrees 白名单内）：{arg}")
print(f"🛡️  白名单校验结果：允许 {len(sys.argv) - 3 - bad} / 拒绝 {bad}")
sys.exit(1 if bad else 0)
PY
}

# ── 登记表自查 / 自愈（地雷 D 的判定本体）────────────────────────────────────
# `_wt_registry_scan`：**只读**扫一遍登记表（`<name>\t<登记路径>\t<说明>\t<drift|indeterminate>`），
# 出口 0 = 无漂移 / 1 = 有漂移 / 3 = 无法判定。它**不做任何删除**（删除全在 `wt_registry_doctor --heal`）。
_wt_registry_scan() {
  [ -n "${PY_BIN}" ] || return 3
  "${PY_BIN}" - "$WT_REGISTRY_DIR" <<'PY'
import os, sys
from pathlib import Path

reg = Path(sys.argv[1])
print(f"[登记表] {reg}")
if not reg.is_dir():
    print("  （无登记表：本仓没有任何 link 出来的 worktree）")
print("[漂移]")
found = 0
for name in sorted(p.name for p in reg.glob("*") if p.is_dir()):
    gd = reg / name / "gitdir"
    if not gd.is_file():
        continue
    raw = gd.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        print(f"  {name}\t?\t（gitdir 为空 ⇒ 无法判定该条目指向哪里，不猜、不删）\tindeterminate")
        continue
    wt = Path(os.path.realpath(raw)).parent
    locked = (reg / name / "locked").exists()
    if not wt.is_dir():
        found += 1
        print(f"  {name}\t{wt}\t登记目录在磁盘上不存在（locked={str(locked).lower()}）\tdrift")
    elif not (wt / ".git").exists():
        found += 1
        print(f"  {name}\t{wt}\t登记目录存在但其中的 .git 没了 ⇒ git 不认它是工作树\tdrift")
print(f"[汇总] 漂移 {found} 条")
sys.exit(1 if found else 0)
PY
}

# `wt_registry_doctor [--heal|--dry-run]`；配合 `wt_registry_guard` 使用：
# 第一阶段（python）**只报不删** → 第二阶段（bash + guard）**先打印将删清单再删** →
# 第三阶段（python）复检。这样「删了什么」永远先打印、且落点逐个过白名单。
wt_registry_doctor() {
  local mode="${1:---dry-run}"
  if [ -z "${PY_BIN}" ]; then
    echo "⚠️  找不到 python3 —— 无法自查「worktree 登记表 × 磁盘」一致性（无法判定，exit 3）"
    return 3
  fi
  local out="" rc=0
  out="$(_wt_registry_scan)" || rc=$?
  if [ "${rc}" = "0" ]; then
    if [ "${mode}" = "--heal" ]; then
      echo "🧭 登记表 × 磁盘一致：无漂移（无需自愈；issue #6235）"
    else
      echo "✅ 登记表 × 磁盘一致：无漂移（worktree 登记表里的每个路径都在磁盘上，issue #6235）"
    fi
    return 0
  fi
  printf '%s\n' "${out}"
  if [ "${rc}" != "1" ]; then
    echo "⚠️  自查未能完成（exit ${rc}）—— 无法判定，不当成通过"
    return 3
  fi
  # ── 漂移存在：默认只读；`--heal` 才进入修复（且逐个落点过白名单）──
  if [ "${mode}" != "--heal" ]; then
    echo "🔴 命中漂移（worktree 登记表 × 磁盘不一致，issue #6235）："
    echo "   · 该分支会被判「已被该 worktree 占用」⇒ git worktree add 报 already used by worktree；"
    echo "   · git worktree prune / worktree remove --force **可能都无效**（locked 形态 / 目录残留形态）。"
    echo "   修：./scripts/dev-worktree.sh doctor --heal   # 先打印将删清单，再按白名单删除 + prune + 复检"
    return 1
  fi
  echo "🔧 --heal：开始修复（顺序 = 先 prune，再对仍残留的条目按白名单删除）"
  local prune_out; prune_out="$(git -C "$REPO_ROOT" worktree prune -v 2>&1 || true)"
  if [ -n "${prune_out}" ]; then printf '%s\n' "${prune_out}" | sed 's/^/   prune: /'; else echo "   prune: （无动作 —— 常见于 locked 形态：prune 会静默什么都不删）"; fi
  local stale="" line name path reason
  while IFS= read -r line; do
    case "${line}" in "[漂移]"*) stale=1; continue ;; "[汇总]"*) stale=0; continue ;; esac
    [ "${stale:-0}" = "1" ] || continue
    case "${line}" in "  "*) : ;; *) continue ;; esac
    name="$(printf '%s' "${line#  }" | cut -f1)"
    path="$(printf '%s' "${line#  }" | cut -f2)"
    reason="$(printf '%s' "${line#  }" | cut -f4)"
    [ "${reason}" = "drift" ] || continue
    [ -n "${name}" ] && [ "${name}" != "?" ] || { echo "   ⚠️  条目名无法判定 ⇒ 跳过（不猜、不删）：${line}"; continue; }
    echo "   🧹 将删除登记条目：${WT_REGISTRY_DIR}/${name}（登记指向 ${path}）"
    if ! wt_registry_guard false "${WT_REGISTRY_DIR}/${name}"; then
      echo "   ⛔ 落点未通过白名单 ⇒ **拒绝删除**（issue #6235 要求：落点在白名单外一律拒绝并打印原因）"
    else
      rm -rf -- "${WT_REGISTRY_DIR}/${name}"
      echo "      ✅ 已删除登记条目 ${name}"
    fi
    [ -n "${path}" ] && [ -d "${path}" ] && [ ! -e "${path}/.git" ] && {
      if rmdir -- "${path}" 2>/dev/null; then
        echo "      ✅ 顺带清掉残留的空目录 ${path}"
      else
        echo "      ⚠️  登记目录的**残留还在**（非空，绝不删）：${path}"
        echo "         里面还有 $(find "${path}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ') 个条目（如 $(find "${path}" -mindepth 1 -maxdepth 1 2>/dev/null | head -1)）"
        echo "         ⇒ 登记条目已清（分支不再被判占用）；但这个路径还在，git worktree add ${path} 会报 already exists。"
        echo "           确认里面没有你要的东西后自己处理：rm -rf -- \"${path}\""
      fi
    }
  done <<EOF
${out}
EOF
  # ── 复检（自愈后仍红 ⇒ 不许当成已修）──
  local verify="" verify_rc=0
  verify="$(_wt_registry_scan)" || verify_rc=$?
  printf '%s\n' "${verify}"
  if [ "${verify_rc}" != "0" ]; then
    echo "⛔ 修复后**复检仍红**（exit ${verify_rc}）—— 漂移还在，不许当成已修："
    echo "   请人工看上面 [漂移] 清单（落点被白名单拒绝的条目尤其要看：它多半不在 .git/worktrees 里）。"
    return 1
  fi
  echo "✅ 登记表 × 磁盘已一致（复检绿）—— 分支不再被判「被该 worktree 占用」（issue #6235）。"
  return 0
}

# ── 各入口的前置断言（地雷 D；issue #6235 要求「所有入口路径都过这道断言」）──────
# 命中漂移 ⇒ **打印将删清单 → 自愈 → 复检**；仍红 ⇒ fail-closed 拒绝继续。
wt_registry_assert_for_entry() {
  local entry="$1" rc=0
  [ -n "${PY_BIN}" ] || { echo "⚠️  ${entry}：找不到 python3 ⇒ 无法自查登记表 × 磁盘（不当成通过）"; return 3; }
  echo "🧭 前置自查（worktree 登记表 × 磁盘；issue #6235）：${entry}"
  wt_registry_doctor --heal || rc=$?
  if [ "${rc}" != "0" ]; then
    echo "❌ ${entry} 拒绝继续：worktree 登记表与磁盘仍不一致（issue #6235）。"
    echo "   手工出口：./scripts/dev-worktree.sh doctor        # 只读看清单"
    echo "             ./scripts/dev-worktree.sh doctor --heal # 显式修复（打印将删清单后按白名单删除）"
    echo "   边界：本自查只治「登记了但磁盘没有」；「磁盘有、git 不认」的反向形态见 issue #6235 的观察项。"
    return 1
  fi
  return 0
}

# ── 会话锁（v1.3）：锁文件 = .git/sessions/<slug>.lock，内容 "PID|时间戳|分支|工作区路径"
lock_path() { echo "$LOCK_DIR/$(slug "$1").lock"; }

# 锁是否活跃：文件存在且记录 PID 对应的进程存活
lock_alive() {
  local f; f="$(lock_path "$1")"
  [ -f "$f" ] || return 1
  local pid; pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# 登记锁（add 成功后调用）
lock_register() {
  local branch="$1" path="$2"
  echo "$$|$(date '+%Y-%m-%d %H:%M:%S')|${branch}|${path}" > "$(lock_path "$branch")"
  echo "🔒 会话锁已登记：${branch}（PID $$）"
}

# 清理锁（rm / 手动）
lock_clean() {
  local f; f="$(lock_path "$1")"
  [ -f "$f" ] && rm -f "$f"
  echo "🔓 会话锁已释放：$1"
}

# 列出全部锁（含失效标记）
lock_list() {
  [ -d "$LOCK_DIR" ] || { echo "（无会话锁）"; return 0; }
  local found=0
  for f in "$LOCK_DIR"/*.lock; do
    [ -f "$f" ] || continue
    found=1
    local pid ts branch path
    pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
    ts="$(cut -d'|' -f2 "$f" 2>/dev/null || true)"
    branch="$(cut -d'|' -f3 "$f" 2>/dev/null || true)"
    path="$(cut -d'|' -f4 "$f" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "🔒 $(basename "$f" .lock) | PID $pid | ${ts} | ${path}"
    else
      echo "💀 $(basename "$f" .lock) | PID ${pid:-?} | ${ts} | ${path}（进程已退出，锁失效）"
    fi
  done
  # 🔴 issue #6243：**末行必须是显式的 `return 0`**。这里曾写成 `[ "$found" = "0" ] && echo "（无会话锁）"`
  #   —— `found=1` 时 `&&` 短路 ⇒ 该复合命令退出码 = 1 ⇒ 它就是本函数返回值；而 `lock_list` 又是
  #   `cmd_list` 的最后一条命令 ⇒ **只要 `$LOCK_DIR` 里有任何 `*.lock`（哪怕全是失效锁）**，
  #   `./scripts/dev-worktree.sh list` 就 exit 1（「表列得好好的却报错」）。
  #   真出错仍是非零：`git worktree list` 由 `set -e` 承担（本函数不吞错）。
  if [ "$found" = "0" ]; then
    echo "（无会话锁）"
  fi
  return 0
}

# 清理失效锁（进程已退出的）
lock_prune() {
  local pruned=0
  for f in "$LOCK_DIR"/*.lock; do
    [ -f "$f" ] || continue
    local pid; pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      echo "🧹 清理失效锁：$(basename "$f" .lock)"
      rm -f "$f"
      pruned=$((pruned + 1))
    fi
  done
  echo "已清理 ${pruned} 个失效锁"
}

# ── 活锚镜像刷新（v1.10，issue #4026）：让活锚**跟随 main**，而不是停在某个时刻 ──
# 只在「与主干同步」的两个时机顺带刷新（add / rebase）。best-effort：
# 镜像缺失（本机没接线）或离线 ⇒ **只告警**，不得因此把建工作区 / rebase 弄失败。
# 为什么值得在这里做：预设 PR 合并后活锚必然落后一格（`migao-dev-flow` §18.2），
# 而「落后 ⇒ 改进到不了加载点」正是 #4026 的病灶 —— 让同步时机顺带把锚点带上，
# 「会跟随」就不依赖人记得跑命令（判据仍在 preset-anchor-check.sh / preset-guard 里）。
refresh_anchor_mirror() {
  local script="${ROOT}/scripts/preset-anchor-refresh.sh"
  if [ ! -x "${script}" ]; then
    echo "ℹ️  跳过活锚刷新：${script} 不存在或不可执行（本机可能没接线活锚）"
    return 0
  fi
  local out="" rc=0
  out="$("${script}" --no-check 2>&1)" || rc=$?
  if [ "${rc}" = "0" ]; then
    local moved
    moved="$(printf '%s\n' "${out}" | sed -n 's/^✅ 镜像已跟随.*：//p' | head -1)"
    echo "🔄 活锚镜像已刷新（${moved:-已在 origin/main}）—— 改进能到加载点（issue #4026）"
  else
    echo "⚠️  活锚镜像未刷新（exit ${rc}）—— 活锚会落后 ⇒ 改预设的改进到不了加载点："
    printf '%s\n' "${out}" | tail -4 | sed 's/^/     /'
    echo "     修：./scripts/preset-anchor-refresh.sh"
  fi
  return 0
}

cmd_rebase() {
  [ $# -ge 1 ] || usage
  local target="$1"
  local path="" branch="" line
  if [ -d "$target" ]; then
    path="$target"
    branch="$(wt_branch_of "$path" || true)"
  else
    line="$(git -C "$REPO_ROOT" worktree list --porcelain | grep -B2 "^branch refs/heads/$target$" | grep '^worktree' | head -1 || true)"
    [ -z "$line" ] && { echo "❌ 找不到 worktree：${target}"; exit 1; }
    path="${line#worktree }"
    branch="$target"
  fi
  [ -n "$path" ] || { echo "❌ 无法解析工作区路径：${target}"; exit 1; }

  # 🔴 地雷 D（issue #6235）：任何入口都过这道断言 —— rebase 前先确认登记表 × 磁盘一致
  #    （漂移时 `git -C <path> rebase` 会以 "not a working tree" 之类的方式失败，且原因不显眼）。
  wt_registry_assert_for_entry "rebase ${branch:-$target}" || exit 1

  echo "🔄 rebase origin/main：${path}（分支 ${branch:-detached}）"
  if ! git -C "$path" rebase origin/main; then
    echo "❌ rebase 未完成（上面是 git 原始输出）。冲突需你自行解决，然后："
    echo "   git -C ${path} rebase --continue    # 或 --abort 放弃"
    echo "   ./scripts/dev-worktree.sh rebase ${branch:-<分支>}   # 完成后重跑一次"
    exit 1
  fi
  # v1.10（issue #4026）：与主干同步的时机顺带把**活锚镜像**带上预设仓 main。
  # ⚠️ S4（issue #6020）起 `add` / `rebase` **不再**有「把 `.agent-presets/**` 刷到业务仓 origin/main」
  #    这一步 —— 预设内容已迁出业务仓，业务仓只在**加载点**（活锚 → 只读镜像）消费它。
  refresh_anchor_mirror
  echo
  echo "✅ rebase 完成：$(git -C "$path" log -1 --format='%h %s')"
}

cmd_add() {
  [ $# -ge 1 ] || usage
  local branch="$1"
  local path="${2:-$WT_BASE/$(slug "$branch")}"
  # 相对路径归一化为绝对路径（v1.8）：脚本可能从**任一工作区**被调用（$ROOT ≠ 调用者 cwd），
  # 而之后要用 `git -C "$path"` 刷新预设。若按**调用者 cwd** 解析，路径会落到
  # `<某工作区>/../migao-wt/...`（实测造出 `migao-wt/migao-wt/...` 这种双层目录）⇒ 刷新刷错地方。
  # 既有语义（`git -C "$REPO_ROOT" status` 等）也是**相对主仓库根**，故此处与之一致。
  case "${path}" in
    /*) : ;;
    *)  path="${REPO_ROOT}/${path}" ;;
  esac

  # 🔴 地雷 D（issue #6235）：**前置断言** —— 登记表里的每个路径必须在磁盘上真的存在；
  #    命中漂移 ⇒ 打印将删清单 → 自愈 → 复检；仍红则 fail-closed（见 wt_registry_assert_for_entry）。
  wt_registry_assert_for_entry "add ${branch}" || exit 1

  # 会话锁检查（v1.3）：同一分支已有活跃会话锁 → 拒绝重复建工作区（防多会话踩脚）
  if lock_alive "$branch" && [ "${FORCE_LOCK:-0}" != "1" ]; then
    echo "❌ 分支 ${branch} 已有活跃会话锁（见下方），拒绝重复建工作区："
    lock_list
    echo "   确认无其他会话在用后：./scripts/dev-worktree.sh lock --prune 清理失效锁；"
    echo "   或确有需要：FORCE_LOCK=1 强制（危险，仅确认无活跃会话时用）。"
    exit 1
  fi

  # 建 worktree 前先提醒主工作区未提交改动（防被静默携带/混淆）
  if [ "$(git -C "$REPO_ROOT" status --porcelain | wc -l | tr -d ' ')" -gt 0 ]; then
    echo "⚠️  主工作区有未提交改动，建议先 commit/stash 再建 worktree："
    git -C "$REPO_ROOT" status --short | head -10
  fi

  # 分支必须存在（本地或远程），否则给出创建提示
  if ! git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$branch" \
     && ! git -C "$REPO_ROOT" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "❌ 分支 ${branch} 不存在（本地/远程均无）。请先创建并推送，或指定已存在的分支。"
    echo "   远程存在但本地无分支时，脚本会自动创建跟踪分支。"
    exit 1
  fi
  # v1.7（issue #3319 实战）：此前用字符串 "--track $branch origin/$branch" 再以
  # 未加引号的 `$branch_arg` 展开 → git 把 `--track` 的**可选参数**吃成 `<branch>`、
  # 把 `origin/<branch>` 当成多余位置参数 → `git worktree add` 直接打 usage 报错。
  # 现象：**只存在远程分支、本地无同名分支**时 `add` 必失败（文档承诺的
  # 「远程存在但本地无分支时脚本会自动创建跟踪分支」实际从未生效）。
  # 修复：显式 `--track -b <branch> <path> origin/<branch>`。
  local branch_is_local=0
  if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
    branch_is_local=1
  fi

  if [ -e "$path" ]; then
    echo "❌ 目标路径已存在：${path}"
    exit 1
  fi
  # v1.11（issue #5422）：建工作区前把「已合并但没人收尾」的自动收掉（事件驱动，判定在 issue_lifecycle.py；失败不阻塞建工作区）
  bash "$REPO_ROOT/scripts/issue-lifecycle.sh" reap-merged --apply --no-artifacts --except "$branch" || echo "⚠️  自动收尾未完成（exit≠0 不阻塞建工作区；原因见上）"
  mkdir -p "$(dirname "$path")"
  if [ "$branch_is_local" = "1" ]; then
    git -C "$REPO_ROOT" worktree add "$path" "$branch"
  else
    git -C "$REPO_ROOT" worktree add --track -b "$branch" "$path" "origin/$branch"
  fi
  lock_register "$branch" "$path"

  # v1.10（issue #4026）：与主干同步的时机顺带把**活锚镜像**带上预设仓 main ——
  # 否则「预设 PR 合并后活锚落后一格」会一直留到有人手动刷（改进到不了加载点）。
  # 🔴 S4（issue #6020）：这里**不再**刷新业务仓的 `.agent-presets/**`（预设已迁出业务仓；
  #    那条"创建时刻快照"的地雷随路径一起消失）。活锚镜像才是真正要跟上的那一份。
  refresh_anchor_mirror

  echo
  echo "✅ 工作区就绪：${path}（分支 ${branch}）"
  echo "   ⚠️  worktree 是独立目录，首次使用需自行安装依赖："
  echo "      cd ${path}"
  [ -f "$REPO_ROOT/package.json" ] && echo "      npm ci"
  [ -d "$REPO_ROOT/frontend/mini-app" ] && echo "      cd frontend/mini-app && npm ci"
  echo "   ⚠️  build 产物（dist/）不入库，worktree 之间互不影响。"
  echo "   🔴 依赖一律在本工作区内安装（npm ci）；禁止把 node_modules 软链到主工作区或其他工作区"
  echo "      软链（${path}/tests/node_modules → 主仓库同名目录）会在「删/重建 node_modules」的动作下**打穿目标**："
  echo "      2026-10-01 实测一次 worktree 内的 npm ci 就把主工作区 tests/node_modules 清成空目录（issue #5930）。"
  echo "      正确姿势见 docs/wiki/Development.md 的「worktree 依赖准备」节（与本提示**同源**，不另写一份）。"
  # 🔴 S4（issue #6020）：本仓**不再承载** `.agent-presets/**` ⇒ 这里既没有「预设快照」要对齐，
  #   也没有「快照挡住 rebase」要处置。预设住在**预设仓**，业务仓只在**加载点**消费它
  #   （活锚软链 → 专职只读镜像 `$HOME/migao-dev-preset-anchor`）；上面那一步已把镜像带到预设仓 main。
  echo "   ℹ️  预设内容已迁出本仓（issue #6020）⇒ 本工作区**没有**预设快照要刷/要丢，rebase 直接跑即可。"
  echo "      要改研发模式：到预设仓 zhaokai-mgzn/migao-agent-presets 提 PR；活锚自检 ./scripts/preset-anchor-check.sh"
}

cmd_list() {
  git -C "$REPO_ROOT" worktree list
  echo
  echo "── 会话锁 ──"
  lock_list
}

# 按工作区路径权威解析其 HEAD 引用的分支名（v1.5，替代 branch --show-current：
# 后者在部分 git 场景下解析歧义，曾导致 rm 误删本地 main，见 issue #2930）。
# detached HEAD 无 branch 行 → 输出空。
wt_branch_of() {
  local wt="$1"
  git -C "$REPO_ROOT" worktree list --porcelain \
    | grep -A3 "^worktree ${wt}$" \
    | grep "^branch refs/heads/" \
    | cut -d' ' -f2- \
    | sed 's#^refs/heads/##'
}

# ── 删除前解链（v1.14，2026-10-01，issue #5930）────────────────────────────────
# 为什么必须在 `git worktree remove` **之前**：删除动作一旦拿到一个**活着的**软链，它就可能
# 被"跟随"而删掉**目标**（软链指向的、仓库外的东西）。这不是假想 —— 现场真实发生过：
# worktree 的 `tests/node_modules` 指向主工作区，随后「删/重建 node_modules」的动作把**主工作区**
# 的依赖清空了，而 git 里毫无痕迹（软链不入库）。解链 = 只删**链接本身**，不跟随、不递归。
unlink_symlinks_before_remove() {
  local wt="$1"
  [ -d "${wt}" ] || return 0
  local n=0 outside=0 inrepo=0 printed=0 p t note
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    if [ "${printed}" = "0" ]; then
      echo "🔗 解链检查（删除**之前**先摘掉软链 —— 防删除动作穿过软链打到仓库外的目标）："
      printed=1
    fi
    n=$((n + 1))
    t="$(readlink "${p}" 2>/dev/null || echo '?')"
    note=""
    case "${t}" in
      "${REPO_ROOT}"/*) note=" ⚠️ 指向**本仓库工作区** —— 跨工作区共享 node_modules 的典型形态（issue #5930 的成因）"; inrepo=$((inrepo + 1)) ;;
      /*)                note=" ⚠️ 指向**工作区之外** —— 删除动作若穿过它，打到的是仓库外的数据";   outside=$((outside + 1)) ;;
    esac
    echo "     - ${p} → ${t}${note}"
    unlink "${p}" 2>/dev/null || rm -f -- "${p}" 2>/dev/null || true
  done < <(find "${wt}" -type l -print 2>/dev/null || true)
  if [ "${n}" = "0" ]; then
    echo "🔗 解链检查：worktree 内无符号链接 —— 删除动作没有可穿越的软链面。"
    return 0
  fi
  echo "✅ 已解链 ${n} 个符号链接（指向仓库外 ${outside} 个 / 指向本仓库工作区 ${inrepo} 个）—— 只删链接本身，未触碰任何目标。"
  if [ "$((outside + inrepo))" -gt 0 ]; then
    echo "   🔴 依赖一律在本工作区内安装（npm ci）；禁止把 node_modules 软链到主工作区或其他工作区"
    echo "      正确姿势见 docs/wiki/Development.md 的「worktree 依赖准备」节（与本提示同源）。"
  fi
  return 0
}

cmd_rm() {
  [ $# -ge 1 ] || usage
  local target="$1"
  local delete_branch=0
  for a in "$@"; do [ "$a" = "--delete-branch" ] && delete_branch=1; done

  # 🔴 地雷 D（issue #6235）：入口断言 —— 漂移时 `rm <分支>` 会解析到一个已被登记、但磁盘上
  #    并不存在的条目，`worktree remove` 会报 `not a working tree`（现象极具误导性）。
  wt_registry_assert_for_entry "rm ${target}" || exit 1

  local path=""
  local branch=""
  if [ -d "$target" ]; then
    path="$target"
    branch="$(wt_branch_of "$path" || true)"
  else
    # target 视为分支名：porcelain 按 worktree/HEAD/branch 分组，branch 是块尾，向前 2 行找 worktree
    local line
    line="$(git -C "$REPO_ROOT" worktree list --porcelain | grep -B2 "^branch refs/heads/$target$" | grep '^worktree' | head -1 || true)"
    [ -z "$line" ] && { echo "❌ 找不到 worktree：${target}"; exit 1; }
    path="${line#worktree }"
    branch="$target"
  fi

  # v1.14（issue #5930）：**顺序即安全顺序** —— 解链必须在这一行**之前**，绝不让删除动作穿过软链。
  unlink_symlinks_before_remove "$path"

  git -C "$REPO_ROOT" worktree remove "$path" --force
  echo "✅ 已移除工作区：${path}"

  # 会话锁清理（v1.3）：移除工作区后释放对应锁
  if [ -n "$branch" ] && lock_alive "$branch" 2>/dev/null; then
    lock_clean "$branch"
  fi

  if [ "$delete_branch" = "1" ] && [ -n "$branch" ]; then
    # 主干分支硬保护（v1.5，issue #2930）：main/master 拒绝经 --delete-branch 删除
    if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
      echo "🛡️  拒绝删除主干分支：${branch}（如需删除请手动 git branch -D ${branch} 并确认）"
      return 0
    fi
    # 分支可能同时被其他 worktree 使用，检查后再删
    if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$branch" \
       && ! git -C "$REPO_ROOT" worktree list --porcelain | grep -q "^branch refs/heads/$branch$"; then
      git -C "$REPO_ROOT" branch -D "$branch"
      echo "✅ 已删除分支：${branch}"
    else
      echo "ℹ️  分支 ${branch} 仍被其他工作区引用，未删除"
    fi
  fi
}

case "${1:-}" in
  add)  shift; cmd_add "$@" ;;
  list) cmd_list ;;
  rm)   shift; cmd_rm "$@" ;;
  rebase) shift; cmd_rebase "$@" ;;
  preset-guard)
    # v1.8（issue #3851）：提交路径 fail-closed 守卫 —— 判定**业务仓** .agent-presets/** 是否构成版本下降。
    # v1.10（issue #4026）：同一守卫同时判**活锚新鲜度**（内容 + sha；落后/悬空即非零退出）
    #   —— 「仓库内容全对但改进到不了加载点」也是静默失效的一种，光看仓库内容查不出来。
    # v1.11（issue #4350）：本分支提示按**面**说清（旧口径「快照建好之后就不再跟随」已改判 ⇒ 脚本侧同步）。
    # 🔴 S4（issue #6020，2026-10-02）：预设**已迁出业务仓**（权威源 = 独立仓 zhaokai-mgzn/migao-agent-presets），
    #   业务仓**不再承载** `.agent-presets/**` ⇒ 本子命令对业务仓**零动作放行**（没有候选可比）；
    #   预设内容侧的版本 / 同号撞车 / 沿革不回流由**预设仓自己的 CI**承担。
    #   仍保留本子命令：它同时判**加载点**（活锚 → 只读镜像 `$HOME/migao-dev-preset-anchor`）。
    # v1.12（issue #5425）：候选与基准 **`version:` 相同、但文件内容不同** = **跨包撞车** ⇒ **判红**。
    # v1.13（issue #5430）：退出码**三态** —— `0` 通过 / `1` 判红 / **`3` 无法判定**（基线 ref 取不到
    #   ⇒ 连「能不能比」都判不了，**不得当 0 读**；1 优先于 3）+ `2` 用法错误。
    # 判定逻辑在 scripts/agent-presets-guard.py（可独立单测，含红证）—— 本分支只负责提示与出口。
    shift
    PY="$(command -v python3.11 || command -v python3 || true)"
    if [ -z "${PY}" ]; then
      echo "❌ 找不到 python3 —— 无法判定 .agent-presets/** 版本单调性 / 活锚新鲜度（fail-closed）："
      echo "   两个面：① 提交路径（判业务仓 .agent-presets/** 版本下降；S4 起本仓无该路径 ⇒ 零动作放行）；"
      echo "           ② 加载点（活锚）**必须自愈**：./scripts/preset-anchor-refresh.sh。"
      echo "   预设内容已迁出业务仓（issue #6020）⇒ 改预设去 zhaokai-mgzn/migao-agent-presets 提 PR。"
      exit 1
    fi
    guard="${ROOT}/scripts/agent-presets-guard.py"
    [ -f "${guard}" ] || { echo "❌ 守卫脚本缺失：${guard}"; exit 1; }
    # ⚠️ 必须用 $ROOT（**本工作区**根），**不能**用 $REPO_ROOT（主仓库根）：
    # 提交路径读的是「本次要提交的那个工作区的索引」。用主仓库根会读到**另一个仓库的索引**
    # ⇒ 本工作区的降级在索引侧看不见 ⇒ 判据「绿了但没跑」（正是本单要防的形态；实测踩过一次）。
    exec "${PY}" "${guard}" --repo "$ROOT" check "$@"
    ;;
  prune)
    # v1.8（issue #3851）：存量体检 —— **只打印清单，绝不删除**
    shift
    PY="$(command -v python3.11 || command -v python3 || true)"
    [ -n "${PY}" ] || { echo "❌ 找不到 python3 —— 无法体检 worktree 存量"; exit 2; }
    guard="${ROOT}/scripts/agent-presets-guard.py"
    [ -f "${guard}" ] || { echo "❌ 守卫脚本缺失：${guard}"; exit 1; }
    # 存量体检看的是**全部工作区**（common git dir 权威），故用 $REPO_ROOT
    exec "${PY}" "${guard}" --repo "$REPO_ROOT" prune "$@"
    ;;
  doctor)
    # 🔴 地雷 D（issue #6235，2026-10-03）：worktree **登记表 × 磁盘**一致性自查。
    # 默认**只读**（有漂移 ⇒ exit 1，红就停）；`--heal` 才进入修复，且：
    #   ① 任何删除前**先打印将删清单**；② 每个删除落点逐个过 `wt_registry_guard` 白名单
    #   （只允许 `<common git dir>/worktrees/<name>`；落点在白名单外 ⇒ **拒绝并打印原因**）；
    #   ③ 修完**复检**，仍红则非零退出（不许"删了就算修好了"）。
    # 「删除类动作不做无人值守」在这里的落法 = **显式入参** `--heal`（没有默认修复、没有后台修复）。
    shift
    case "${1:-}" in
      --heal)  wt_registry_doctor --heal ;;
      --dry-run|"") wt_registry_doctor --dry-run ;;
      *) echo "用法：./scripts/dev-worktree.sh doctor [--heal|--dry-run]"; exit 2 ;;
    esac
    ;;
  lock)
    shift
    case "${1:-}" in
      --prune) lock_prune ;;
      *)       lock_list ;;
    esac
    ;;
  *)    usage ;;
esac
