#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# CI → GitHub：把 **CI 这一次构建出来的** `frontend/mini-app/dist/` 推成一个
# **孤儿单提交**（无父提交 ⇒ 不胀历史），force-push 到专用分支 `h5-dist`，
# 并把**该提交的 sha** 打到 stdout（供发布腿当「不可变引用」用）。issue #6095 第三层。
#
# ── 为什么需要它（第三层缺陷，设计层）────────────────────────────────────────
# 前两层修完（#6095）后，远端发布仍然失败，且**失败在设计上**：
#   · 远端 `stage_product()` 取发布源 = `codeload …/tar.gz/<sha>` 的**源码 tarball**
#     （`H5_SRC_SUBPATH=frontend/mini-app` ⇒ 发布源 = `frontend/mini-app/`）；
#   · 而 `dist/` 是**构建产物**：`git ls-tree -r origin/main --name-only frontend/mini-app/dist`
#     = **0 个文件**，`.gitignore` 里有 `dist/` ⇒ **源码 tarball 里永远没有 dist/index.html**
#     ⇒ 远端必然 `❌ 发布源里没有 index.html`（run 37078030820 实测读数）。
# ⇒ 「CI 构建的那份 dist」与「远端能取到的东西」之间**没有通路**。本脚本补的正是这一段：
#   **产物进 git 对象库（专用分支的孤儿提交）⇒ 远端那条既有的 tarball 取回通道原样可用。**
#
# ── 为什么是「孤儿单提交 + 专用分支」（而不是别的四条路）──────────────────────
#   · **B2（把 dist 提交进发布分支的普通历史）**：每次发布都往历史里塞一份 MB 级产物 ⇒
#     历史与 clone 体积单调膨胀（本仓单次 dist 约 MB 级；每天 N 次发布 ⇒ 一年 N×365 份）。
#     孤儿单提交**没有父**，分支每次 force-push 都只有 1 个提交 ⇒ 不存在累积。
#   · **B3（OSS 上传）**：现取仓内**没有**任何 bucket/凭据面（`grep -rn "OSS_" .github/ deploy/
#     scripts/` 命中 0；现存的 `oss-cn-hangzhou` 字样全在**用例里的公开只读图片 URL**）
#     ⇒ 需要新增 secret + 基础设施 ⇒ 按单子口径**停下报告**，不自造。
#   · **B4（远端自己 build）**：现取**没有** SWAS 实例装 node/npm 的证据（`test_swas_server_side_build.py`
#     证明的是**服务器侧 docker 构建**，与 node 无关）⇒ 无法证明 ⇒ 排除。
#   · **⚠️ 把 dist 塞进 SWAS 命令内容**：16 KB 上限，dist 是 MB 级 ⇒ 结构性不可行（也禁止）。
#
# ── 🔴 不可变 sha（本脚本的**核心语义**，不许放宽）────────────────────────────
# 远端取回用的 ref **必须**是「某次构建产出的具体 sha」。本脚本只可能输出**一个 commit 对象名**
# （`git commit-tree` 的返回值），且发布腿把它当**唯一**输入传下去：
#   · **不输出** `h5-dist`（分支名会漂）· **不输出** `refs/heads/*` · **不碰** main；
#   · 发布腿（`c-end-h5-publish-ci.sh`）另有**一致性断言**：拿到的 sha 必须逐字等于本文件
#     `H5_DIST_SHA`（由 workflow 从本脚本的 step output 传下来）⇒ 「CI 推的」与「远端取的」
#     必定同一个对象（判据 + 红证见 `tests/unit_ci_workflows/test_c_end_h5_hosting.py`）。
#
# ── 触发面（现取证据，2026-10-03）────────────────────────────────────────────
# push 到 `h5-dist` **不会**触发本仓任何 workflow：现取全部带 `push` 的 workflow，
# 其 `on.push.branches` **一律是 `['main']`**（见 `tests/unit_ci_workflows/test_c_end_h5_hosting.py`
# 的 `TestDistBranchPushSurface`，它从真 YAML 现取、不写死清单）。提交信息里再带 `[skip ci]`
# 作为第二道（幂等，不改变上面的结论）。
#
# 用法（CI 侧由 `.github/workflows/c-end-h5-publish.yml` 的「Prepare dist ref」步调用）：
#   bash deploy/scripts/c-end-h5-dist-push.sh <DIST_DIR> [BRANCH]
#     环境变量：
#       H5_DIST_DIR        —— 等价于第 1 个参数（判据用注入面）
#       H5_DIST_BRANCH     —— 目标分支，默认 `h5-dist`
#       H5_DIST_GIT_REMOTE —— 远端名，默认 `origin`
#     stdout 最后一行 = `H5_DIST_SHA=<40 位 sha>`（workflow 把它写进 `$GITHUB_OUTPUT`）
#
# 退出码：0 = 已推送且给出了 sha；非零 = **没推任何东西**（本地具名判红，不允许沉默）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DIST_DIR=${1:-${H5_DIST_DIR:-}}
BRANCH=${2:-${H5_DIST_BRANCH:-h5-dist}}
GIT_REMOTE=${H5_DIST_GIT_REMOTE:-origin}

# 孤儿提交的作者/提交者身份（**显式给**，见下面「不继承调用方的环境」一节）。
# `github-actions[bot]` = GitHub 官方的 Actions bot 账号（ID 41898282）⇒ 推上去的提交**可追溯到
# 「由哪次 Actions 产出」；它承载的**源码 commit** 另写在提交信息里（`${GITHUB_SHA}`），
# 发布侧还记在托管清单的 `published_commit` / `published_dist_ref`（`deploy/swas/c-end-h5-publish-remote.sh`）。
IDENT_NAME='github-actions[bot]'
IDENT_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'

die() { printf '❌ %s\n' "$*" >&2; exit 1; }

# ── 参数 / 前置校验（在任何 git 写动作之前）────────────────────────────────────
[ -n "$DIST_DIR" ] || die "用法：c-end-h5-dist-push.sh <DIST_DIR> [BRANCH]（dist 目录是必给参数）"
[ -d "$DIST_DIR" ] || die "dist 目录不存在：'$DIST_DIR'（没跑过 npm run build:h5？）"
[ -f "$DIST_DIR/index.html" ] || die "dist 里没有 index.html：'$DIST_DIR'（不是 build:h5 的产物？）"
case "$BRANCH" in
  ""|*/*|*[!A-Za-z0-9._-]*) die "目标分支名非法：'$BRANCH'（只接受单一组件 [A-Za-z0-9._-]）" ;;
esac

command -v git >/dev/null 2>&1 || die "找不到 git"

# 🔴 **不继承调用方的环境**（#6095 第四层 / 与 #6113 同族：「脚本继承了运行环境」）：
#    `GIT_DIR` / `GIT_WORK_TREE` / `GIT_COMMON_DIR` 一旦被调用方设过，本脚本「在哪个仓上工作、
#    把产物推到哪个远端」就**由环境决定**而不是由 cwd 决定 —— 那是静默的错仓发布面。
#    ⇒ 显式清掉（本脚本只认 cwd 所在的工作树；`GIT_INDEX_FILE` 由本脚本自己设，见下）。
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR

# 🔴 git 对象库里的路径**必须相对检出根**（远端解包后按 `frontend/mini-app/dist` 找 index.html
#    ⇒ 树里多一层 `/Users/…` 前缀就等于「发布源里没有 index.html」的旧病换个地方复发）。
#    这里把「绝对路径（在检出内）」规范化成相对路径；在检出**外**的目录直接拒（推不了）。
REPO_TOP=$(git rev-parse --show-toplevel 2>/dev/null) || die "当前目录不在 git 工作树里（CI 应先 actions/checkout）"
[ -n "$REPO_TOP" ] || die "git rev-parse --show-toplevel 没给出检出根"
# 两侧都过一遍 `pwd -P`（macOS 上 `/tmp` 是软链；只规范化一侧会让前缀比对假红）
REPO_TOP=$(cd "$REPO_TOP" && pwd -P) || die "进不去检出根 '$REPO_TOP'"
[ -n "$REPO_TOP" ] || die "检出根的规范化路径为空"
ABS_DIST=$(cd "$DIST_DIR" && pwd -P) || die "进不去 '$DIST_DIR'"
case "$ABS_DIST" in
  "$REPO_TOP"/*) DIST_DIR=${ABS_DIST#"$REPO_TOP"/} ;;
  *) die "dist 目录不在检出内：'$ABS_DIST'（检出根 '$REPO_TOP'）—— 远端按仓内相对路径取回，仓外目录推不了" ;;
esac
[ -n "$DIST_DIR" ] || die "规范化后 dist 路径为空"
[ -f "$DIST_DIR/index.html" ] || die "规范化后 dist 里没有 index.html：'$DIST_DIR'"

# 目标分支是**发布链路的取回面**，不是给别的 workflow 用的 ⇒ 现取禁止把它设成任何
# 会被 push 触发的分支名（`main` 之类）。这条不是「靠注释承诺」：发布腿侧还有一条
# 「取回 ref 必须是 40 位十六进制 sha」的断言（分支名压根过不去）。
case "$BRANCH" in
  main|master) die "目标分支不许是 '$BRANCH'（会把 CI 产物写进主线历史）" ;;
esac

# ── 造孤儿提交（用**临时 index**，绝不碰工作区 / 索引 / 当前 HEAD）────────────
# `git commit-tree` **没有 `--no-verify` 选项**，也不需要它：它不跑 hook，不读 `$GIT_DIR/index`
# （`-p` 一个都不给 ⇒ 无父提交 ⇒ 孤儿），`GIT_INDEX_FILE` 指到 `mktemp` 出来的临时索引
# ⇒ `.gitignore` 里的 `dist/` 不会被 `git add -f` 之外的东西惦记上。
TMP_INDEX=$(mktemp)
TMP_DIR=$(mktemp -d)
cleanup() { rm -f "$TMP_INDEX"; rm -rf "$TMP_DIR"; }
trap cleanup EXIT

export GIT_INDEX_FILE="$TMP_INDEX"
git read-tree --empty
git add -f -- "$DIST_DIR" || die "把 '$DIST_DIR' 加进临时索引失败（git add -f）"
TREE=$(git write-tree) || die "git write-tree 失败（临时索引坏？）"
[ -n "$TREE" ] || die "git write-tree 没给出 tree（空产物？）"

# 自证：对象库里真的有这份产物（**不是**「git 说它加了」）
BLOBS=$(git ls-tree -r "$TREE" --name-only | wc -l | tr -d ' ')
[ "$BLOBS" -gt 0 ] || die "孤儿提交的 tree 里 0 个文件 —— 拒绝推送空产物"
INDEX_BLOB=$(git ls-tree -r "$TREE" --name-only | grep -c 'dist/index.html' || true)
[ "$INDEX_BLOB" -ge 1 ] || die "孤儿提交的 tree 里找不到 dist/index.html（路径前缀不对？）—— 远端会取不到 index.html"

# ⚠️ 提交信息用 `-m` 单个参数传入 ⇒ 不会被 shell 拆分 / 不会被 `git commit-tree` 当参数解析。
#    不带 `-p` ⇒ **无父提交**（孤儿）；分支每次 force-push 都只有这一个提交 ⇒ 不胀历史。
#
# 🔴 **必须显式给 author/committer 身份**（#6095 第四层，run `37081920188` 实测）：
#    `git commit-tree` 需要一个可用身份，而 **CI runner 上没有全局/仓内身份、系统 GECOS 也是空的**
#    ⇒ git 兜底出来的 name 是空串 ⇒ `fatal: empty ident name (for <runner@…>) not allowed` ⇒ exit 128。
#    病根属「**脚本/判据继承了运行环境**」这一族（同 #6113 剔除继承来的 `MIGAO_HEAVY_L*`）：
#    本机有隐式身份（GECOS + hostname 都非空）⇒ **本机跑绿证明不了 CI 会绿**（实测：同一脚本
#    本机 rc=0 / runner rc=128）。
#    ⚠️ 写法取**环境变量前缀**而不是 `-c user.name=…`：`-c` 是 **config 层**，而**环境变量优先于
#    config** ⇒ 若调用方环境里有一个**空**的 `GIT_AUTHOR_NAME`（判据夹具正是这么模拟 runner 的），
#    `-c` 会被它盖掉、仍然 `empty ident name`（实测 rc=128）。四个 `GIT_*` 前缀是**最高优先级**
#    ⇒ 两种继承渠道（环境 / config）都盖得住，且**不写 `--global`**、不污染 runner 配置。
SHA=$(GIT_AUTHOR_NAME="$IDENT_NAME" GIT_AUTHOR_EMAIL="$IDENT_EMAIL" \
      GIT_COMMITTER_NAME="$IDENT_NAME" GIT_COMMITTER_EMAIL="$IDENT_EMAIL" \
      git commit-tree "$TREE" -m "chore(h5-dist): C 端 H5 构建产物 ${GITHUB_SHA:-$(date -u +%Y-%m-%dT%H:%M:%SZ)} [skip ci]")
case "$SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) : ;;
  *) die "git commit-tree 没给出 sha：'$SHA'" ;;
esac
[ "${#SHA}" -eq 40 ] || die "commit sha 长度不是 40：'$SHA'"

# ── 推送（只推这一个对象到专用分支；force 是**有意**的：分支只承载「最新一次构建」）──
# ⚠️ `--force` + 临时 ref：孤儿提交与远端上一个 h5-dist 提交**没有共同祖先**
#    ⇒ 普通 push 会被拒 ⇒ 必须 force。这不是「覆盖别人正在用的历史」：该分支的
#    唯一读者是本腿的发布腿，读的是**具体 sha**（不是分支名）。
PUSH_REF="refs/heads/$BRANCH"
echo "== 推送孤儿提交 $SHA → $GIT_REMOTE:${PUSH_REF}（只含 ${DIST_DIR}，共 ${BLOBS} 个文件）=="
git push --force "$GIT_REMOTE" "$SHA:$PUSH_REF" \
  || die "推送失败：$GIT_REMOTE $SHA:${PUSH_REF}（权限？网络？）—— 没有产物到达远端，发布腿会在取回时判红"

# ── 自证（推送后**再读一次远端**，确认远端那个分支真的是这个 sha）──────────────
REMOTE_SHA=$(git ls-remote "$GIT_REMOTE" "$PUSH_REF" | awk '{print $1}')
[ "$REMOTE_SHA" = "$SHA" ] \
  || die "推送后远端 '$PUSH_REF' 读回 '$REMOTE_SHA' ≠ 本地 '$SHA' —— 产物没有真的到达远端"

echo "H5_DIST_FILES=$BLOBS"
echo "H5_DIST_SHA=$SHA"
