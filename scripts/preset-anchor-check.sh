#!/usr/bin/env bash
# =============================================================================
# preset-anchor-check.sh — 活锚新鲜度自检（**红就停**；issue #4026 / 迁移单 #6020）
#
# 判的是什么：**DSH 真正加载的那份内容**（软链 `~/.dsh/.agent-presets/migao` 解析出的 preset 目录）
# 是否就是**预设仓 `zhaokai-mgzn/migao-agent-presets` 的 `main`** —— 内容逐字节 + 检出 sha 两面都核。
#
# 🔴 S4（issue #6020）：预设的**权威源**已从业务仓 `.agent-presets/migao/**` 迁到**独立预设仓**，
#   本仓**不再承载**预设内容。因此：
#     · 活锚 = 软链 → **专职只读镜像的仓根**（`$HOME/migao-dev-preset-anchor`，旧口径是
#       `<镜像>/.agent-presets/migao`）；
#     · 基线 = **预设仓的 `origin/main`**（旧口径是业务仓的 origin/main）；
#     · 镜像的克隆源 = **预设仓**（`MIGAO_PRESET_REPO_URL` 覆盖）。
#   S3 换链**已执行**（2026-10-02）⇒ 本脚本的默认调用落在**拓扑 A**（活锚 = 预设仓检出）并给出**真判定**；
#   旧的「业务仓当基线」口径在拓扑 C 下会**恒绿**（空集比空集）—— 那种绿已按 `3` 判掉，见下面「按拓扑」。
#
# 为什么单靠 `preset-guard` / 预设仓自己的 CI 不够：那两条只查**仓内**内容（版本单调、沿革不回流），
# **查不出活锚落后** —— 实测活锚曾指向一个落后 `origin/main` **42 个提交**的主工作区：
# 内容当时恰好一致（无害），但只要下一次有人改预设并合并，改进就**永远到不了加载点**，
# 后续所有会话读到的仍是旧模式。这就是「迭代了但模式没进化」的确切机制。
#
# ⚠️ 「镜像自己有没有跟上远端」是**另一条**判据，且它必须用**远端**当参照物：镜像既当活锚
#   （只读、绝不 fetch）又当基线的话，拿它自己量自己是恒等的 ⇒ 落后永远判不出来。故本脚本用
#   `git ls-remote <预设仓> main`（**只读远端、不写入镜像**）取远端 sha 传给判定本体。
#   取不到（离线 / 无权限）⇒ 退到镜像本地已知的 ref，并**降级出声**，不静默当通过。
#
# 用法（在任一 migao 工作区根目录执行；**开工第一件事** + 提交前）：
#   ./scripts/preset-anchor-check.sh                    # 核本机活锚 vs 预设仓 main（按拓扑自动选判定）
#   ./scripts/preset-anchor-check.sh --fetch            # 先 fetch 活锚检出到预设仓 main 再核（取不到远端 ⇒ 3）
#   ./scripts/preset-anchor-check.sh --anchor <路径>     # 核指定路径（**显式 ⇒ 一律判定**）
#   ./scripts/preset-anchor-check.sh --repo <基线仓> --ref <ref>
#   ./scripts/preset-anchor-check.sh --anchor-base ''      # 基线仓 = 预设仓（仓根就是 preset 目录）
#   MIGAO_PRESET_LIVE=<路径> ./scripts/preset-anchor-check.sh
#   MIGAO_PRESET_MIRROR=<路径> ./scripts/preset-anchor-check.sh
#   MIGAO_PRESET_REPO_URL=<url|路径> ./scripts/preset-anchor-check.sh
#
# 🔴 **按拓扑自动选判定**（判定本体 = `scripts/agent-presets-guard.py` 的 `anchor` 子命令，口径只放一处）：
#   · **拓扑 A**（活锚 = 预设仓检出的**仓根**，= 换链后的当前形态）：判 ① 形态（`preset.yml` + `skills/`
#     缺一即红）② 工作树**干净**（读不到状态 ⇒ `3`）③ HEAD == **活锚自己的** `origin/main`
#     （取不到远端 ⇒ `3`；不同 ⇒ 红）④ **比对面解析出 0 个文件 ⇒ `3`**（issue #6178：空比对
#     证不了任何字节，**不许**报绿）+ 打印两个技能 version 供人眼核对；
#   · **拓扑 B**（活锚仍是基线仓里的 `.agent-presets/migao` 子树，兼容窗口）：历史口径（内容逐字节比对）；
#   · **拓扑 C**（拓扑 B 形态且基线仓该前缀**空集**）：`⏭️ 未跑判定` + **`3`** —— 「基线仓已无该前缀
#     ⇒ 这条比对本就不适用」。**绝不**输出「✅ 新鲜（0 个文件）」：空集比空集恒等 = **假绿**。
#
# 退出码（**三态**，与 `scripts/agent-presets-guard.py` / `scripts/drift_audit.py` 同口径）：
#         0 = 绿（新鲜）**或** ⏭️ 未跑判定（本机没接线 / 与基线仓**有证据地**不同源）；
#         1 = 红（落后 / 悬空 / 内容不同 / **镜像不在远端 main 上** / **活锚工作树不干净** / 技能加载不了 /
#             **接线不可解析**）；
#         3 = **无法判定**（基线 ref 取不到；拓扑 A 下**活锚自己的远端 main 取不到**或**工作树状态读不到**；
#             或**基线仓该前缀空集 ⇒ 比对本就不适用**；或**接线判据未跑** —— 均**不得当 0 读**；
#             issue #5430 / #6020）；
#         2 = 环境或用法错误（找不到 python3 等）。
# ⚠️ `⏭️ 未跑判定` 与 `3 无法判定` **都不是**「通过」，读输出时别把它们混起来（本仓库「空跑=假绿」同族）。
#
# 判定本体在 `scripts/agent-presets-guard.py` 的 `anchor` 子命令（三态与判据写在那里的文件头），
# 本脚本只是入口 —— 判据只放一处，避免第二份口径。
#
# 🔌 **接线可解析性**（2026-11-25 实测故障；`scripts/agent-preset-wiring-guard.py`）：
#   本机生效的 `migao` preset 是 `~/.dsh/profiles/web/cordis.patch.yml` 里的**声明行**，其
#   `skill-filesystem.customSkillDirs` 曾指向改布局后已不存在的 `<anchor>/skills` —— 插件**静默跳过**，
#   preset 自带的两个技能从未加载，而 `~/.dsh/skills` 的临时软链让 catalog「看起来有技能」。
#   ⇒ 本脚本先跑接线判据（缺根 / 指错副本 / 覆盖不全 / 兜底遮蔽 ⇒ 红；无声明行 ⇒ 3），**再**跑活锚新鲜度；
#   两者取最坏退出码（红 > 无法判定 > 绿）。新增环境变量：`MIGAO_PRESET_ID`（默认 migao）、
#   `MIGAO_PRESET_DSH_HOME`（默认 `$DSH_HOME` 或 `~/.dsh`；profile patch 从它下面找）。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANCHOR="${MIGAO_PRESET_LIVE:-$HOME/.dsh/.agent-presets/migao}"
MIRROR="${MIGAO_PRESET_MIRROR:-$HOME/migao-dev-preset-anchor}"
# 基线仓 = 预设仓的本地检出（默认就是镜像）。S4 起预设内容在**仓根**（不再有 `.agent-presets/migao` 层）。
REPO="${MIGAO_PRESET_BASELINE:-$MIRROR}"
REPO_URL="${MIGAO_PRESET_REPO_URL:-git@github.com:zhaokai-mgzn/migao-agent-presets.git}"
REF="origin/main"
#: 预设内容相对**基线仓根**的路径（`""` = 预设仓口径：仓根**就是** preset 目录；S4 / issue #6020）。
#: 🔴 2026-11-25 实测：预设仓 2026-11-21 改成 `presets/<name>/` 布局后，写死的默认 `.agent-presets/migao`
#:   在基线仓里**恒为空集** ⇒ 本自检每天只报 `3 无法判定`（「⏭️ 未跑判定」），谁也没注意到它其实一直没判。
#:   故默认改为**从活锚自己推**（活锚在基线仓检出里的相对路径），推不出来才退回历史口径；
#:   显式 `--anchor-base`（含空串）一律优先。
ANCHOR_BASE=""
ANCHOR_BASE_GIVEN=0
#: 活锚是否被显式覆盖（`--anchor` / `MIGAO_PRESET_LIVE`）—— 覆盖时**接线判据不适用**（比的是别人家的锚）。
ANCHOR_GIVEN=0
FETCH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --fetch) FETCH=1; shift ;;
    --anchor) [ $# -ge 2 ] || { echo "❌ --anchor 缺参数（用法见脚本头部）" >&2; exit 2; }; ANCHOR="$2"; ANCHOR_GIVEN=1; shift 2 ;;
    --repo)   [ $# -ge 2 ] || { echo "❌ --repo 缺参数（用法见脚本头部）" >&2; exit 2; };   REPO="$2";   shift 2 ;;
    --ref)    [ $# -ge 2 ] || { echo "❌ --ref 缺参数（用法见脚本头部）" >&2; exit 2; };    REF="$2";    shift 2 ;;
    --anchor-base) [ $# -ge 2 ] || { echo "❌ --anchor-base 缺参数（用法见脚本头部；预设仓口径传空串：--anchor-base=）" >&2; exit 2; }; ANCHOR_BASE="$2"; ANCHOR_BASE_GIVEN=1; shift 2 ;;
    -h|--help) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^preset-anchor-check.sh/,/^====/p'; exit 0 ;;
    *) echo "❌ 未知参数：$1（用法见脚本头部）" >&2; exit 2 ;;
  esac
done

# 预设内容相对基线仓根的路径：默认**从活锚推**（预设仓 `presets/<name>/` 布局），推不出才退回历史口径。
if [ "${ANCHOR_BASE_GIVEN}" = "0" ]; then
  REPO_TOP="$(git -C "${REPO}" rev-parse --show-toplevel 2>/dev/null || true)"
  ANCHOR_REAL="$(cd "${ANCHOR}" 2>/dev/null && pwd -P || true)"
  if [ -n "${REPO_TOP}" ] && [ -n "${ANCHOR_REAL}" ]; then
    REPO_TOP_REAL="$(cd "${REPO_TOP}" && pwd -P)"
    case "${ANCHOR_REAL}" in
      "${REPO_TOP_REAL}")   ANCHOR_BASE="" ;;
      "${REPO_TOP_REAL}"/*) ANCHOR_BASE="${ANCHOR_REAL#"${REPO_TOP_REAL}"/}" ;;
      *)                    ANCHOR_BASE=".agent-presets/migao" ;;
    esac
  else
    ANCHOR_BASE=".agent-presets/migao"
  fi
fi

PY="$(command -v python3.11 || command -v python3 || true)"
if [ -z "${PY}" ]; then
  echo "❌ 找不到 python3 —— 无法判定活锚新鲜度（fail-closed，判定不得退化成放行）：" >&2
  echo "   人工兜底：readlink \"\$HOME/.dsh/.agent-presets/migao\" 后与预设仓的" >&2
  echo "   \`git show origin/main:skills/migao-dev-flow/SKILL.md\` 的 version 对一下（在预设仓检出里跑）" >&2
  exit 2
fi

GUARD="${ROOT}/scripts/agent-presets-guard.py"
[ -f "${GUARD}" ] || { echo "❌ 判定本体缺失：${GUARD}" >&2; exit 2; }

# 🔴 镜像必须**只读且绝不 fetch**：它是活锚的软链目标，就地写它 = 在 DSH 正加载的那份内容上动手。
#   故「把镜像刷到预设仓 main」这条自愈**只在这里**（`--fetch`，人显式要求），其余一律只读。
# 🔴 `--fetch` 一律**转交判定本体**（口径只放一处）：fetch 的对象随**拓扑**定 —— 拓扑 A（活锚 = 预设仓
#   检出的仓根）fetch **活锚自己**，且**取不到远端 ⇒ 判 `3`**（不许拿本地旧 ref 报绿）；拓扑 B fetch 基线仓
#   （失败只降级出声，沿用历史容忍度）。判定本体据此把「有没有第二视角」判成三态，本脚本不复制这套规则。
FETCH_ARGS=()
[ "${FETCH}" = "1" ] && FETCH_ARGS=(--fetch)

# 镜像相对**远端** main 落后与否（换链后「活锚 ⇄ 镜像」是同一份，旧判据失去第二视角 ⇒ 这里补上
# 一条**新增**判据；既有判据一条不放宽）。`ls-remote` **只读远端**、不写镜像 ⇒ 与「镜像只读」不冲突；
# 取不到时**出声降级**（只跳过这一条），不静默当成通过。
REMOTE_ARGS=()
if git -C "${REPO}" rev-parse --git-dir >/dev/null 2>&1; then
  REMOTE_SHA="$(git ls-remote "${REPO_URL}" main 2>/dev/null | awk '{print $1}' | head -1 || true)"
  if [ -n "${REMOTE_SHA}" ]; then
    REMOTE_ARGS=(--remote-sha "${REMOTE_SHA}")
  else
    echo "⚠️ 取不到预设仓 main 的远端 sha（${REPO_URL}：离线 / 无权限 / 仓名变了）"
    echo "   ⇒ 这一轮**判不了「镜像有没有落后远端」**（其余判据照常跑）—— 这不是「通过」。"
  fi
fi

# 🔌 接线可解析性（2026-11-25 实测故障）：profile 声明行的技能根必须**存在** / **覆盖活锚全部技能** /
#   **realpath 就是活锚技能目录**（防改错副本）/ **无宿主兜底遮蔽**（`$DSH_HOME/skills` 里的临时软链会让
#   断线继续「看起来有技能」）。口径只放一处（`scripts/agent-preset-wiring-guard.py`）。
WIRING_GUARD="${ROOT}/scripts/agent-preset-wiring-guard.py"
WIRING_RC=0
if [ "${ANCHOR_GIVEN}" = "1" ] || [ -n "${MIGAO_PRESET_LIVE:-}" ]; then
  # 显式覆盖活锚 = 诊断别人的锚；本机 profile 声明行的接线判不了（也不该判）。
  echo "⏭️ 接线判据**未跑判定**：活锚被 --anchor / MIGAO_PRESET_LIVE 显式覆盖 ⇒ 本机接线不适用"
  echo "   （这条是「没跑」，不是「通过」；日常开工自检请用默认调用）"
elif [ -f "${WIRING_GUARD}" ]; then
  WIRING_RC=0
  "${PY}" "${WIRING_GUARD}" \
    --anchor "${ANCHOR}" \
    --preset-id "${MIGAO_PRESET_ID:-migao}" \
    --dsh-home "${MIGAO_PRESET_DSH_HOME:-${DSH_HOME:-$HOME/.dsh}}" || WIRING_RC=$?
else
  echo "⏭️ 接线判据缺失（${WIRING_GUARD}）⇒ 这一轮**判不了接线**（不得当 0 读）"
  WIRING_RC=3
fi
case "${WIRING_RC}" in
  0|3) ;;
  1) echo "" >&2
     echo "❌ 接线不可解析（exit 1）—— 修好上面点名的接线后重跑本自检（红就停）。" >&2
     exit 1 ;;
  *) echo "❌ 接线判据环境错误（exit ${WIRING_RC}；缺 node 等）" >&2; exit 2 ;;
esac

# `--anchor` 一律显式传给判定本体：显式 ⇒ **一律判定**（不因「与基线仓不同源」跳过）
# `--anchor-base`：preset 内容相对**基线仓根**的路径 —— 默认 `.agent-presets/migao`（旧业务仓口径，
#   兼容窗口）；S4 换链后传 `""`（基线仓 = 预设仓，**仓根就是 preset 目录**）。
set +e
"${PY}" "${GUARD}" --repo "${REPO}" anchor \
  --anchor "${ANCHOR}" \
  --anchor-base "${ANCHOR_BASE}" \
  --ref "${REF}" \
  --expected-remote "${REPO_URL}" \
  ${FETCH_ARGS[@]+"${FETCH_ARGS[@]}"} \
  ${REMOTE_ARGS[@]+"${REMOTE_ARGS[@]}"}
ANCHOR_RC=$?
set -e

# 取最坏退出码：红(1) > 无法判定(3) > 绿(0)。
if [ "${ANCHOR_RC}" = "1" ]; then
  exit 1
fi
if [ "${WIRING_RC}" = "3" ] || [ "${ANCHOR_RC}" = "3" ]; then
  echo "" >&2
  echo "⏭️ 整体判 **3 无法判定**（接线或活锚有一条没跑出结论）—— 不得当 0 读。" >&2
  exit 3
fi
exit 0
