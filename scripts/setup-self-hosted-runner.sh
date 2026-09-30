#!/usr/bin/env bash
# =============================================================================
# setup-self-hosted-runner.sh — 把一台 macOS 机器装成 migao 仓库的 Actions runner
#
# 背景：
#   · issue #2786 —— GitHub 托管 runner 高峰慢/排队，E2E 门禁因 timeout 误报，故引入自托管。
#   · issue #5814（2026-09-30）—— PR 面验证腿**迁到自托管**。这一步的前提是「runner 的环境
#     必须可复原」：整套配置原先只存在于 `~/` 与 issue 评论里（`.env` / `_shims` / 预置工作区），
#     一旦丢失，pr-check 的两条 **required** 腿会在自托管 runner 上**必红，而没有任何东西会变红**
#     （铁律 12(c)③「只存在于会话上下文里的规格」）。⇒ 本脚本就是那份配置的可执行形态。
#
# 用法（幂等；重复执行不会重复注册 / 不会重复克隆）：
#   ./scripts/setup-self-hosted-runner.sh                    # 装环境 + 自愈工作区 + 前台运行
#   RUNNER_SERVICE=1 ./scripts/setup-self-hosted-runner.sh   # 装成 launchd 服务并启动（常驻）
#   ./scripts/setup-self-hosted-runner.sh --check            # **只读**自检：漂移即非零退出
#   ./scripts/setup-self-hosted-runner.sh --reseed-workdir   # 只做「预置工作区」的健康判定+必要时重建
#   ./scripts/setup-self-hosted-runner.sh --print-env        # 打印将写入 .env 的内容（无密钥）
#   ./scripts/setup-self-hosted-runner.sh --verify           # 在**期望 PATH** 下验证 shim 真的可解析
#   ./scripts/setup-self-hosted-runner.sh --help
#
# 三档分离（**只读档绝不与安装档混在一起**）：
#   安装档 = 建立**有意持有**的环境（幂等、不打印任何密钥）
#   自检档（`--check` / `--reseed-workdir` / `--verify`）= 对**有意持有的环境**做判据
#
# 🔴 为什么「预置工作区」必须自愈（issue #5814 的实测，2026-09-30 集成侧两轮真机读数）
#   ① `actions/checkout` 的 `--depth=1` **必然**把预置仓库 shallow 化 —— 但 **shallow 不是病**
#      （实测：`shallow=true` 时 `.git` 仍 293M，且服务端建的分支照样 fetch ✅）。把它当病
#      会让判定**每个 job 之后都假红 + 白重建**。
#   ② 真正的坏态 = `HEAD`/refs 指向**对象已不存在**的提交（实测退化成 `.git` 293M → 2.6M、
#      `git fsck` 报 `invalid sha1 pointer` / `HEAD: invalid sha1 pointer`）。**到了这个状态，
#      下一次 checkout 就得重新做真·批量拉取 ⇒ 回到「本机到 github.com 被掐断（early EOF）、
#      卡满超时」。**
#   ⇒ 所以：① 判定 = `.git` 在 ∧ `HEAD` 可解析 ∧ `HEAD^{commit}` 存在 ∧ `git fsck` 无 `error`
#            （**shallow 不计入**）；
#            ② 不满足就**重建**（`rm -rf` + `git clone --no-checkout <本机主仓>`，实测 293 MB / 0.28 s）；
#            ③ 安装档每次运行都先做这个判定（幂等；健康则**不动**）。
#   ⚠️ 这条脆弱性必须写明：checkout 能过，**部分依赖**「预置仓库 + alternates 同时健康」——
#      所以要有自愈脚本 + 判据，而不是靠「上次是绿的」。
#
# 前置：
#   - gh CLI 已登录且有仓库 admin 权限（用于现取 registration token）
#   - 目标机器已装 CI 所需工具（Java 21 / Node 20 / Python 3.11 / PostgreSQL 16，按需）
#   - 自托管面**没有 docker** ⇒ docker 构建腿**有意**留在 GitHub 托管侧，见
#     tests/unit_ci_workflows/runner_plane_ledger.json
#
# 注意：
#   - registration token 1 小时内有效，本脚本每次运行**动态获取**，**绝不落盘 / 绝不打印**
#   - `actions/setup-python@v7` 在非 `/Users/runner` 主机上**必然失败**（macOS 预编译产物把
#     `/Users/runner` 烤死、`/Users` 归 root 无法创建）⇒ workflow 侧带
#     `if: runner.environment != 'self-hosted'`，自托管侧 python/pip 由本脚本建的 `_shims` 提供
#   - 本机 `/bin/bash` = 3.2.57 ⇒ 本脚本**只用** bash 3.2 兼容语法（无 `declare -A` /
#     `mapfile` / `${v,,}` / `[[ -v`）
#
# 判据（环境假设必须与本脚本同源）：
#   tests/unit_ci_workflows/test_runner_plane_ledger.py —— 执行面登记表 + 自托管侧跳过条件
#   + 本脚本的**可夹具化**行为（工作区健康判定 / 重建 / 幂等 / shim 解析）。
# =============================================================================
set -uo pipefail

REPO="${RUNNER_REPO:-zhaokai-mgzn/migao}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner-migao}"
RUNNER_NAME="${RUNNER_NAME:-migao-mac-m1}"
# runner 侧附加标签；workflow 侧要同时写 `self-hosted`（见 runner_plane_ledger.json）
RUNNER_LABELS="${RUNNER_LABELS:-migao-mac}"
RUNNER_VERSION="${RUNNER_VERSION:-2.337.0}"          # 按需升级：gh api repos/actions/runner/releases/latest
MIRROR_REPO="${MIRROR_REPO:-$HOME/ai native/migao}"  # 本机已有克隆 ⇒ 预置工作区 + alternates 的来源
TOOL_CACHE="${TOOL_CACHE:-$RUNNER_DIR/_work/_tool}"  # 实测落点 = `_work/_tool`（runner 默认的
                                                     # RUNNER_TOOL_CACHE 就在 work 目录下）

HB="${HOMEBREW_PREFIX:-/opt/homebrew}"
PY_BIN="$HB/opt/python@3.11/bin"
NODE_BIN="$HB/opt/node@20/bin"
JAVA_HOME_DEFAULT="$HB/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"

SHIMS="$RUNNER_DIR/_shims"
WORK_DIR="$RUNNER_DIR/_work"
ENV_FILE="$RUNNER_DIR/.env"
MODE="install"

case "${1:-}" in
  --check)          MODE="check" ;;
  --reseed-workdir) MODE="reseed" ;;
  --print-env)      MODE="print-env" ;;
  --verify)         MODE="verify" ;;
  -h|--help)        sed -n '2,58p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "")               ;;
  *)                echo "❌ 未知参数：$1（用 --help）" >&2; exit 2 ;;
esac

# ── `PATH` 期望值（**唯一真相源**：`.env` / `--check` / `--verify` 都读它）─────────
# 顺序即语义：shim 在最前（`python` 这个**名字**只在 shim 里有）；Homebrew 在前，因为 launchd
# 启动的 runner **默认 PATH 不含 Homebrew** ⇒ pr-check 的 fail-closed PG 前置断言（只查 PATH +
# Debian 的 /usr/lib/postgresql/*/bin）会找不到 `initdb`/`pg_ctl`/`psql`。
EXPECTED_PATH="$SHIMS:$HB/bin:$HB/sbin:$NODE_BIN:$PY_BIN:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
EXPECTED_ENV="LANG=zh_CN.UTF-8
JAVA_HOME=$JAVA_HOME_DEFAULT
PATH=$EXPECTED_PATH"
#: 需要存在的 shim 名字（`python` 是 CI 判据步逐字要用的那个名字）
SHIM_NAMES="python python3 pip"

say() { echo "▸ $*"; }
ok()  { echo "✓ $*"; }
warn() { echo "⚠️ $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# `actions/checkout` 落点是 `_work/<repo>/<repo>`
wexpected_dir() { printf '%s/%s/%s' "$WORK_DIR" "${REPO#*/}" "${REPO#*/}"; }

# `git -C ... rev-parse` 的仓库根（**自证**该目录真是 git 仓库，而不是「目录存在」）
is_git_repo() { [ -d "$1" ] && git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }

# ── 预置工作区的**健康判定**（`0` = 健康；否则非零 + stdout 一行具名原因）──────────
# 病根见文件头「为什么预置工作区必须自愈」：`actions/checkout` 的 `--depth=1` **必然**把预置
# 仓库变 shallow（实测：shallow=true 时 `.git` 仍 293M，且服务端建的分支照样 fetch ✅
# ⇒ **shallow 不是病** —— 把它当病会让判据**每个 job 之后都假红 + 白重建**）。
# 真正的坏态是「`HEAD`/refs 指向**对象已不存在**的提交」（实测退化成 `.git` 293M → 2.6M、
# `git fsck` 报 `invalid sha1 pointer`）⇒ 下一次 checkout 退回真·批量拉取 ⇒ early EOF 卡死。
workdir_problem() {
  d="$1"
  [ -d "$d/.git" ] || { echo "缺仓库（目录缺失 or .git 不见了）"; return 1; }
  git -C "$d" rev-parse --verify --quiet HEAD >/dev/null 2>&1 || { echo "HEAD 悬空"; return 1; }
  git -C "$d" cat-file -e 'HEAD^{commit}' 2>/dev/null || { echo "HEAD 对象缺失"; return 1; }
  if git -C "$d" fsck --no-progress 2>&1 | grep -q "error"; then
    echo "git fsck 报错（对象/引用损坏，实测形态 = invalid sha1 pointer）"
    return 1
  fi
  return 0
}

# ── 工作区「重建」（幂等：健康则**不动**；必要时才 clone）──────────────────────────
reseed_workdir() {
  WEXP="$(wexpected_dir)"
  if problem="$(workdir_problem "$WEXP")"; then
    ok "预置工作区健康（未重建）：$WEXP"
    return 0
  fi
  say "预置工作区不健康：$WEXP —— $problem"
  if ! is_git_repo "$MIRROR_REPO"; then
    warn "本机镜像仓库不可用（$MIRROR_REPO 不是 git 仓库）⇒ 无法重建；"
    warn "  下一次 actions/checkout 会退回真·批量拉取（实测本机到 github.com 会被掐断 early EOF）"
    return 1
  fi
  mkdir -p "$(dirname "$WEXP")"
  rm -rf "$WEXP" || { warn "删不掉旧工作区 $WEXP"; return 1; }
  if git clone --no-checkout "$MIRROR_REPO" "$WEXP" >/dev/null 2>&1; then
    if problem2="$(workdir_problem "$WEXP")"; then
      ok "重建完成并复检通过：${WEXP}（本地克隆自 ${MIRROR_REPO}）"
      return 0
    fi
    warn "重建后复检仍不健康：$problem2"
    return 1
  fi
  warn "本地克隆失败 ⇒ 交给 runner 自行 checkout（可能卡满超时）"
  return 1
}

# ── python/pip shim 在**期望 PATH** 下是否真的可解析 ────────────────────────────
shim_resolution_problem() {
  for n in $SHIM_NAMES; do
    if ! PATH="$EXPECTED_PATH" command -v "$n" >/dev/null 2>&1; then
      echo "在期望 PATH 下解析不到 $n"
      return 1
    fi
  done
  v="$(PATH="$EXPECTED_PATH" python --version 2>&1 || true)"
  case "$v" in
    Python\ 3.*) ;;
    *) echo "期望 PATH 下的 python --version 读出：$v"; return 1 ;;
  esac
  if ! PATH="$EXPECTED_PATH" python -m pip --version >/dev/null 2>&1; then
    echo "期望 PATH 下的 python 没有可用的 pip（判据步 pip install 会红）"
    return 1
  fi
  return 0
}

# =============================================================================
# 只读自检档：环境漂移即非零退出（**不写任何东西**）
# =============================================================================
if [ "$MODE" = "check" ]; then
  problems=0
  prob() { echo "  · $*"; problems=$((problems+1)); }

  [ -f "$ENV_FILE" ] || prob "缺 ${ENV_FILE}（runner 的环境真值；没有它 PATH/Java/PG 全不可见）"
  if [ -f "$ENV_FILE" ]; then
    while IFS= read -r kv; do
      grep -qxF "$kv" "$ENV_FILE" || prob "$ENV_FILE 缺少/漂移的期望行：$kv"
    done <<EOF
$EXPECTED_ENV
EOF
    grep -qE '^GIT_ALTERNATE_OBJECT_DIRECTORIES=.*\.git/objects$' "$ENV_FILE" \
      || prob "$ENV_FILE 缺 GIT_ALTERNATE_OBJECT_DIRECTORIES（批量 checkout 会被 github.com 掐断）"
  fi

  for s in $SHIM_NAMES; do
    [ -x "$SHIMS/$s" ] || prob "缺 shim $SHIMS/${s}（自托管侧跳过 setup-python 后由它提供 ${s}）"
  done
  if p="$(shim_resolution_problem)"; then :; else prob "shim 解析失败：$p"; fi

  d="$(wexpected_dir)"
  if p="$(workdir_problem "$d")"; then :; else
    prob "预置工作区 $d 不健康：${p}（自愈：$0 --reseed-workdir）"
  fi
  if [ ! -d "${TOOL_CACHE}" ] && [ ! -d "${RUNNER_DIR}/_work/_tool" ]; then
    prob "缺 tool cache（期望位置之一：${TOOL_CACHE} 或 ${RUNNER_DIR}/_work/_tool）——setup-node 无法命中缓存"
  fi

  if [ "$problems" = "0" ]; then
    ok "自托管 runner 环境自检通过（${RUNNER_DIR}）"
    exit 0
  fi
  echo "❌ 自托管 runner 环境漂移（$problems 处）—— 修复：$0" >&2
  exit 1
fi

# =============================================================================
# 只做「工作区健康判定 + 必要时重建」档（给人一条命令；也是判据的入口）
# =============================================================================
if [ "$MODE" = "reseed" ]; then
  reseed_workdir || exit 1
  exit 0
fi

# =============================================================================
# 在期望 PATH 下验证 shim（不写盘）
# =============================================================================
if [ "$MODE" = "verify" ]; then
  if p="$(shim_resolution_problem)"; then
    ok "shim 在期望 PATH 下解析正常（$SHIM_NAMES · $(PATH="$EXPECTED_PATH" python --version 2>&1)）"
    exit 0
  fi
  echo "❌ shim 解析失败：$p" >&2
  exit 1
fi

# =============================================================================
# 安装档
# =============================================================================
say "仓库: $REPO | 目录: $RUNNER_DIR | runner 名: $RUNNER_NAME | 标签: self-hosted,$RUNNER_LABELS"

OS="$(uname -s | tr 'A-Z' 'a-z')"                     # darwin / linux
ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && RUNNER_ARCH="arm64" || RUNNER_ARCH="x64"

# 1. 工具缓存目录（setup-node / setup-python 的 `_tool` 落点）
[ -d "$TOOL_CACHE" ] || { mkdir -p "$TOOL_CACHE"; ok "建 tool cache ${TOOL_CACHE}"; }

# 2. shim：Homebrew 的 python@3.11 只提供 `python3`，而 CI 判据步写的是 `python -m pytest`
#    ⇒ 补 `python` / `python3` / `pip` 三个**名字**（`.env` 的 PATH 把 `_shims` 排在最前）
mkdir -p "$SHIMS"
for pair in "python3.11:python" "python3.11:python3" "pip3.11:pip"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ ! -x "$PY_BIN/$src" ]; then
    warn "找不到 $PY_BIN/$src —— 跳过 shim ${dst}（python 判据腿会红，见本脚本头部）"
    continue
  fi
  if [ "$(readlink "$SHIMS/$dst" 2>/dev/null)" != "$PY_BIN/$src" ]; then
    ln -sfn "$PY_BIN/$src" "$SHIMS/$dst"
    ok "shim $dst -> $PY_BIN/$src"
  fi
done

# 3. `.env`：launchd 启动的 runner **默认 PATH 不含 Homebrew**（实测复现：
#    `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin bash -c 'command -v initdb'` ⇒ 找不到）
#    ⇒ 显式声明 PATH / JAVA_HOME / alternates。**幂等**：内容一致则不改写（保 mtime）。
#    🔴 alternates **必须**在这里写：它是「job 侧拿到本地对象库」的唯一来源（读数 3）。
ALT_OBJ=""
if is_git_repo "$MIRROR_REPO"; then
  ALT_OBJ="$MIRROR_REPO/.git/objects"
else
  warn "本机镜像仓库不可用（$MIRROR_REPO 不是 git 仓库）⇒ 不写 GIT_ALTERNATE_OBJECT_DIRECTORIES；"
  warn "   runner 将自行克隆 —— 实测本机到 github.com 的批量传输会被掐断（early EOF），checkout 可能卡满超时"
fi
ENV_BODY="$EXPECTED_ENV
GIT_ALTERNATE_OBJECT_DIRECTORIES=$ALT_OBJ"
if [ "$MODE" = "print-env" ]; then
  echo "──── 将写入 ${ENV_FILE}（无密钥）────"
  printf '%s\n' "$ENV_BODY"
  exit 0
fi
if [ -f "$ENV_FILE" ] && [ "$(cat "$ENV_FILE")" = "$ENV_BODY" ]; then
  ok ".env 已是最新（未改写）"
else
  printf '%s\n' "$ENV_BODY" > "$ENV_FILE"
  ok "写入 $ENV_FILE"
fi

# 4. 预置工作区：**先判定健康**（shallow / 悬空 HEAD / invalid sha1 ⇒ 重建）。
#    健康则不动；不健康才 `git clone --no-checkout`（实测 293 MB / 0.28 s），
#    再靠 `.env` 的 alternates 只读共享对象库 ⇒ `actions/checkout` 的 fetch 秒级完成。
reseed_workdir || warn "预置工作区未就绪（见上）；runner 会把首次 checkout 当全量拉取"

# 5. 下载并解压 runner（幂等：`config.sh` 已在则跳过）
if [ ! -x "$RUNNER_DIR/config.sh" ]; then
  command -v gh >/dev/null 2>&1 || die "需要 gh CLI（brew install gh / 官方安装脚本）"
  mkdir -p "$RUNNER_DIR"
  PKG="actions-runner-${OS}-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
  URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${PKG}"
  say "下载 $PKG ..."
  curl -sL -o "/tmp/${PKG}" "$URL" || die "下载失败：$URL"
  tar xzf "/tmp/${PKG}" -C "$RUNNER_DIR" || die "解压失败"
  ok "runner 已解压到 $RUNNER_DIR"
fi

# 6. 注册（幂等：`.runner` 已在则跳过）。token **现取现用、不落盘、不打印**
if [ ! -f "$RUNNER_DIR/.runner" ]; then
  command -v gh >/dev/null 2>&1 || die "需要 gh CLI（用于现取 registration token）"
  TOKEN="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token 2>/dev/null)"
  [ -n "$TOKEN" ] || die "无法获取 registration token（gh 需仓库 admin 权限）"
  ( cd "$RUNNER_DIR" && ./config.sh --url "https://github.com/${REPO}" --token "$TOKEN" \
      --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --unattended --replace --work "_work" ) \
    || die "config.sh 失败"
  unset TOKEN
  ok "runner 已注册（名 ${RUNNER_NAME}，标签 self-hosted,${RUNNER_LABELS}）"
fi

# 7. 运行（前台 / launchd 服务）。服务档用 runner 自带的 `svc.sh`（与 .env 同目录，环境自然生效）
if [ "${RUNNER_SERVICE:-0}" = "1" ]; then
  ( cd "$RUNNER_DIR" && ./svc.sh install && ./svc.sh start ) || die "svc.sh 安装/启动失败"
  ok "已注册为 launchd 服务并启动（常驻）。停止：cd $RUNNER_DIR && ./svc.sh stop"
  ok "自检：$0 --check"
else
  say "前台运行（Ctrl+C 停止）；常驻请用 RUNNER_SERVICE=1 $0"
  cd "$RUNNER_DIR" && exec ./run.sh
fi
