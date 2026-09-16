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
#   ./scripts/dev-worktree.sh rebase <分支|路径>    # 丢弃预设快照差异 → rebase origin/main → 重新刷新预设（issue #3972）
#   ./scripts/dev-worktree.sh preset-guard [--source both|index|worktree]  # 提交路径守卫（版本下降即非零退出）
#   ./scripts/dev-worktree.sh prune --dry-run       # worktree 存量体检（只打印清单，不删除）
#
# 预设快照地雷与两层防线（v1.8，2026-09-15 新增，issue #3851）：
#   worktree 的 `.agent-presets/**` 是**创建时刻快照**；此后 main 上预设再推进，
#   工作区不会自动跟上 ⇒ 这些文件相对 origin/main 就是「改动」（内容在**回退**），
#   一条 `git add -A` + push 就提交一个把研发模式回退若干版本的 PR，
#   而 **CI 不看 `.agent-presets/**` 的版本 ⇒ 不红**（静默）。
#   ① 创建路径（本脚本）：`add` 建完工作区后**自动**把 `.agent-presets/**` 刷新到 origin/main；
#   ② 提交路径（本脚本 preset-guard）：判定暂存/工作区是否构成**版本下降**，命中即 fail-closed；
#      **合法升级放行**（改研发模式本身不能被堵死），同版本内容不同 = 分叉 → 告警；
#   ③ 机械安全网（别处，互补）：#3843 的统一审计 `drift_audit --check` 将加
#      「`.agent-presets/**` 版本单调性」守卫（全库/定时对账；本脚本管增量/贴合工作区）。
#   v1.9（issue #3972）：刷新后工作区相对**本分支 HEAD** 就是「改动」，`git rebase origin/main`
#   会被 git 拒绝（未跟踪快照挡 checkout / 已跟踪但版本旧= unstaged changes）⇒ 新增 `rebase`
#   子命令：丢弃预设快照差异 → rebase → 重新刷新（只丢弃与 origin/main 一致的纯刷新产物，
#   内容不一致即停手，避免丢掉别人正在改的研发模式）。
#   也不用「让 git 忽略这些文件的改动」那类手法（索引标记 / 本地忽略）：那会把**合法的预设改动**
#   （改研发模式本身）一起吞掉 —— 「眼不见为净」在这里等于把正事也堵死。
#   详见 docs/wiki/DEV-FLOW.md「预设快照地雷」节（落地单 #3859，事实单 #3851）。
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
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被
# 并入变量名（如 `$path（` → `path<0xE3>` 报 unbound variable），
# 因此所有后跟中文的变量一律用 ${var} 显式包裹。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# v1.6（issue #2933）：归一化到主仓库根 —— --git-common-dir 总是指向主仓库 .git
# （在 worktree 内执行时亦然），git 命令/会话锁/默认 worktree 目录都基于它
REPO_ROOT="$(cd "$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || echo "$ROOT/.git")/.." && pwd)"
WT_BASE="${MIGAO_WT_BASE:-$REPO_ROOT/../migao-wt}"
LOCK_DIR="$REPO_ROOT/.git/sessions"
mkdir -p "$LOCK_DIR"

usage() {
  # head 上限需覆盖「用法」块 + v1.8 的预设地雷说明（加新条目时同步上调，否则 --help 会截断）
  # v1.9（issue #3972）：用法块 +1 行（rebase 子命令）⇒ 上限同步 +2
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^dev-worktree.sh/,/^===/p' | head -42
  exit 1
}

# 分支名 → 工作区目录名：feat/xiaobu-voice-holdtalk → xiaobu-voice-holdtalk
slug() { echo "$1" | sed -E 's#^(feat|fix|chore|docs|test|refactor)/##; s#/#-#g'; }

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
  [ "$found" = "0" ] && echo "（无会话锁）"
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

# ── 预设快照刷新（v1.8，issue #3851）：worktree 的 .agent-presets/** 是创建时刻快照 ──
# 建完工作区后立刻把 .agent-presets/** 对齐 origin/main，使其**开局就不是「相对 main 的改动」**。
# 若你自己确实要改研发模式：在工作区里改即可（本函数只在 `add` 那一刻跑一次，不覆盖你的后续改动）。
# 刷新方式用 `checkout origin/main -- .agent-presets/`（与 issue #3851 记录的人工修法同一形状），
# 不用「让 git 忽略这些文件改动」的索引标记手法 —— 那会把合法的预设改动一起吞掉（见文件头说明）。
refresh_presets() {
  local wt="$1"
  echo
  echo "🔄 预设快照刷新（.agent-presets/** → origin/main）..."
  if [ ! -d "${wt}" ]; then
    echo "❌ 跳不过去：工作区目录不存在（${wt}）—— 预设未刷新，**不要**在这种情况下提交 .agent-presets/**"
    return 1
  fi
  if ! git -C "$wt" rev-parse --verify --quiet origin/main >/dev/null; then
    echo "⚠️  跳过：本仓库无 origin/main 引用 —— 无法刷新，请自行核对 .agent-presets/** 版本。"
    return 0
  fi
  if ! git -C "$wt" fetch --quiet origin main 2>/dev/null; then
    echo "⚠️  fetch origin main 失败（离线/无权限？）—— 下面按**本地已知的** origin/main 刷新。"
  fi
  # 列出将要被刷新的文件（`head` 兜底：`grep -c` 无匹配会 exit 1 且 set -e 会中止）
  local changed
  changed="$(git -C "$wt" ls-files --others --exclude-standard -- .agent-presets/ 2>/dev/null | head -20 || true)"
  if [ -n "${changed}" ]; then
    echo "   ↑ 以下文件是创建时刻的未跟踪快照（相对 origin/main 即「改动」）："
    echo "${changed}" | sed 's/^/     /'
  fi
  git -C "$wt" checkout origin/main -- .agent-presets/
  local n
  n="$(git -C "$wt" ls-tree -r --name-only origin/main -- .agent-presets/ | wc -l | tr -d ' ')"
  echo "✅ 已把 .agent-presets/**（${n} 个文件）刷新到 origin/main —— 开局即不是「相对 main 的改动」。"
  echo "   理由：worktree 的 .agent-presets/** 是**创建时刻快照**，main 推进后不自动跟上；"
  echo "         不刷新则一条 \`git add -A\` 就会把研发模式**静默回退**（CI 不看预设版本 ⇒ 不红）。"
  echo "   你自己要改研发模式：直接在工作区改 + 升 version（提交前跑 preset-guard，升级放行）。"
}

# ── 预设快照 × rebase 的冲突处置（v1.9，issue #3972）───────────────────────────
# refresh_presets 把 .agent-presets/** 对齐到 origin/main 后，工作区相对**本分支 HEAD**
# 就出现了改动，于是 `git rebase origin/main` 会被 git 拒绝。实测两种形态：
#   · 本分支 HEAD **未跟踪**该路径（旧分支，早于预设入库）⇒ checkout 把快照留在**索引**里
#     （staged new files）→ 「untracked working tree files would be overwritten by checkout」；
#   · 本分支 HEAD 跟踪但版本较旧 ⇒ 刷新后相对 HEAD 变成**已修改** → 「cannot rebase: You have unstaged changes」。
# 两者都不是开发者的活（预设是主干资产），故处置 = **丢弃预设差异 → rebase → 重新刷新**。
# 刻意不用「本地忽略 / 索引标记」手法（见文件头 v1.8 说明：那会把合法的预设改动一起吞掉）。
# 安全护栏：只丢弃**与 origin/main 完全一致**的快照（= 纯刷新产物）；一旦不一致，
# 视为开发者自己的研发模式改动 ⇒ 停手，交人工处置（不静默丢别人的活）。
discard_preset_snapshot() {
  local wt="$1"
  local drifted=0 f h1 h2
  if git -C "$wt" ls-tree -r --name-only HEAD -- .agent-presets/ 2>/dev/null | grep -q .; then
    git -C "$wt" diff --quiet origin/main -- .agent-presets/ 2>/dev/null || drifted=1
  else
    # 未跟踪**与已暂存**文件都不进常规 `git diff` 比较（陷阱形态正是"已暂存"）
    # ⇒ 逐文件比 blob 哈希：工作区实际内容 + 索引内容，两侧都要与 origin/main 一致
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      h2="$(git -C "$wt" rev-parse "origin/main:$f" 2>/dev/null || echo '!')"
      if [ -f "$wt/$f" ]; then
        h1="$(git -C "$wt" hash-object "$wt/$f" 2>/dev/null || echo '?')"
        [ "$h1" = "$h2" ] || drifted=1
      fi
      h3="$(git -C "$wt" rev-parse ":$f" 2>/dev/null || echo '!')"
      if [ "$h3" != "!" ] && [ "$h3" != "$h2" ]; then drifted=1; fi
    done < <(git -C "$wt" ls-files --cached --others --exclude-standard -- .agent-presets/ 2>/dev/null || true)
  fi
  if [ "$drifted" = "1" ]; then
    echo "❌ .agent-presets/** 与 origin/main 不一致 —— 可能是你自己的研发模式改动，拒绝自动丢弃。"
    echo "   人工处置（确认可弃后再执行）："
    echo "     已跟踪：git -C ${wt} checkout origin/main -- .agent-presets/"
    echo "     未跟踪：rm -rf ${wt}/.agent-presets   # 旧分支；rebase 到含该路径的 main 后会由 main 带出"
    return 1
  fi
  if git -C "$wt" ls-tree -r --name-only HEAD -- .agent-presets/ 2>/dev/null | grep -q .; then
    git -C "$wt" checkout -q HEAD -- .agent-presets/
  else
    git -C "$wt" rm -r -q --cached --ignore-unmatch -- .agent-presets/ 2>/dev/null || true
    rm -rf "${wt}/.agent-presets"
  fi
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

  echo "🔄 rebase origin/main：${path}（分支 ${branch:-detached}）"
  discard_preset_snapshot "$path"
  if ! git -C "$path" rebase origin/main; then
    echo "❌ rebase 未完成（上面是 git 原始输出）。冲突需你自行解决，然后："
    echo "   git -C ${path} rebase --continue    # 或 --abort 放弃"
    echo "   ./scripts/dev-worktree.sh rebase ${branch:-<分支>}   # 完成后重新刷新预设"
    exit 1
  fi
  refresh_presets "$path"
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
  mkdir -p "$(dirname "$path")"
  if [ "$branch_is_local" = "1" ]; then
    git -C "$REPO_ROOT" worktree add "$path" "$branch"
  else
    git -C "$REPO_ROOT" worktree add --track -b "$branch" "$path" "origin/$branch"
  fi
  lock_register "$branch" "$path"

  # v1.8（issue #3851）：建完立刻把预设快照对齐 origin/main（否则 `git add -A` 会静默回退研发模式）
  refresh_presets "$path"

  echo
  echo "✅ 工作区就绪：${path}（分支 ${branch}）"
  echo "   ⚠️  worktree 是独立目录，首次使用需自行安装依赖："
  echo "      cd ${path}"
  [ -f "$REPO_ROOT/package.json" ] && echo "      npm ci"
  [ -d "$REPO_ROOT/frontend/mini-app" ] && echo "      cd frontend/mini-app && npm ci"
  echo "   ⚠️  build 产物（dist/）不入库，worktree 之间互不影响。"
  echo "   ⚠️  本工作区已刷新 .agent-presets/**（相对本分支 HEAD 即「改动」）——要 rebase 请用："
  echo "      ./scripts/dev-worktree.sh rebase ${branch}"
  echo "      （该子命令会先丢弃预设快照差异再 rebase，否则 git 会以「本地改动会被覆盖」拒绝；issue #3972）"
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

cmd_rm() {
  [ $# -ge 1 ] || usage
  local target="$1"
  local delete_branch=0
  for a in "$@"; do [ "$a" = "--delete-branch" ] && delete_branch=1; done

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
    # v1.8（issue #3851）：提交路径 fail-closed 守卫 —— 判定 .agent-presets/** 是否构成版本下降。
    # 判定逻辑在 scripts/agent-presets-guard.py（可独立单测，含红证）。
    shift
    PY="$(command -v python3.11 || command -v python3 || true)"
    if [ -z "${PY}" ]; then
      echo "❌ 找不到 python3 —— 无法判定 .agent-presets/** 版本单调性（fail-closed）："
      echo "   worktree 的 .agent-presets/** 是创建时刻快照，未判定前不得提交它。"
      echo "   兜底修法：git checkout origin/main -- .agent-presets/"
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
  lock)
    shift
    case "${1:-}" in
      --prune) lock_prune ;;
      *)       lock_list ;;
    esac
    ;;
  *)    usage ;;
esac
