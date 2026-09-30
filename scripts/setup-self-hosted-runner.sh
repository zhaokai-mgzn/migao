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
#   ./scripts/setup-self-hosted-runner.sh                    # 装好环境并**前台**运行 runner
#   RUNNER_SERVICE=1 ./scripts/setup-self-hosted-runner.sh   # 装成 launchd 服务并启动（常驻）
#   ./scripts/setup-self-hosted-runner.sh --check            # **只读**自检：环境漂移即非零退出
#   ./scripts/setup-self-hosted-runner.sh --print-env        # 打印将写入 .env 的内容（无密钥）
#   ./scripts/setup-self-hosted-runner.sh --help
#
# 两档分离（`--check` 档**只读**，绝不与安装档混在一起）：
#   安装档 = 建立**有意持有**的环境（幂等、不打印任何密钥）
#   自检档 = 对**有意持有的环境**做判据（逐行比对期望行；不打印任何从 `.env` 读出的值）
#
# 前置：
#   - gh CLI 已登录且有仓库 admin 权限（用于现取 registration token）
#   - 目标机器已装 CI 所需工具（Java 21 / Node 20 / Python 3.11 / PostgreSQL 16，按需）
#   - 自托管面**没有 docker** ⇒ docker 构建腿**有意**留在 GitHub 托管侧，见
#     tests/unit_ci_workflows/runner_plane_ledger.json
#
# 注意：
#   - registration token 1 小时内有效，本脚本每次运行**动态获取**，**绝不落盘 / 绝不打印**
#   - 本机到 github.com 的**批量** git 传输会被掐断（实测 `early EOF`）⇒ 必须「本地预置工作区
#     + alternates」两件事同时做，否则 `actions/checkout` 卡满 10 分钟被 cancelled
#   - `actions/setup-python@v7` 在非 `/Users/runner` 主机上**必然失败**（macOS 预编译产物把
#     `/Users/runner` 烤死、`/Users` 归 root 无法创建）⇒ workflow 侧带
#     `if: runner.environment != 'self-hosted'`，python/pip 由本脚本建的 `_shims` 提供
#   - 本机 `/bin/bash` = 3.2.57 ⇒ 本脚本**只用** bash 3.2 兼容语法（无 `declare -A` /
#     `mapfile` / `${v,,}` / `[[ -v`）
#
# 判据（脚本是「真值」，workflow 侧的环境假设必须与它同源）：
#   tests/unit_ci_workflows/test_runner_plane_ledger.py —— 自托管侧**哪些 job** + 这些 job
#   对环境的假设（用 setup-python 的 job 必须带自托管跳过条件、runs-on 取值必须已登记）。
# =============================================================================
set -uo pipefail

REPO="${RUNNER_REPO:-zhaokai-mgzn/migao}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner-migao}"
RUNNER_NAME="${RUNNER_NAME:-migao-mac-m1}"
RUNNER_LABELS="${RUNNER_LABELS:-migao-mac}"          # runner 侧附加标签（workflow 侧另写 self-hosted）
RUNNER_VERSION="${RUNNER_VERSION:-2.337.0}"          # 按需升级：gh api repos/actions/runner/releases/latest
MIRROR_REPO="${MIRROR_REPO:-$HOME/ai native/migao}"  # 本机已有克隆 ⇒ 预置工作区 + alternates 的来源
TOOL_CACHE="${TOOL_CACHE:-$RUNNER_DIR/_tool}"        # actions/setup-node 等的工具缓存

HB="${HOMEBREW_PREFIX:-/opt/homebrew}"
PY_BIN="$HB/opt/python@3.11/bin"
NODE_BIN="$HB/opt/node@20/bin"
JAVA_HOME_DEFAULT="$HB/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"

SHIMS="$RUNNER_DIR/_shims"
WORK_DIR="$RUNNER_DIR/_work"
ENV_FILE="$RUNNER_DIR/.env"
CHECK=0
PRINT_ENV=0

case "${1:-}" in
  --check)     CHECK=1 ;;
  --print-env) PRINT_ENV=1 ;;
  -h|--help)   sed -n '2,55p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "")          ;;
  *)           echo "❌ 未知参数：$1（用 --help）" >&2; exit 2 ;;
esac

# ── `PATH` 期望值（**唯一真相源**：`.env` 与 `--check` 都读它）────────────────────
# 顺序即语义：shim 在最前（`python` 这个**名字**只在 shim 里有）；Homebrew 在前，因为 launchd
# 启动的 runner **默认 PATH 不含 Homebrew** ⇒ pr-check 的 fail-closed PG 前置断言（只查 PATH +
# Debian 的 /usr/lib/postgresql/*/bin）会找不到 `initdb`/`pg_ctl`/`psql`。
EXPECTED_PATH="$SHIMS:$HB/bin:$HB/sbin:$NODE_BIN:$PY_BIN:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

say() { echo "▸ $*"; }
ok()  { echo "✓ $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# `actions/checkout` 落点是 `_work/<repo>/<repo>`
wexpected_dir() { printf '%s/%s/%s' "$WORK_DIR" "${REPO#*/}" "${REPO#*/}"; }

# `git -C` 的仓库根（**自证**该目录真是 git 仓库，而不是「目录存在」）
is_git_repo() { [ -d "$1" ] && git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }

# =============================================================================
# 只读自检档：环境漂移即非零退出（**不写任何东西**）
# =============================================================================
if [ "$CHECK" = "1" ]; then
  problems=0
  prob() { echo "  · $*"; problems=$((problems+1)); }

  [ -f "$ENV_FILE" ] || prob "缺 $ENV_FILE（runner 的环境真值；没有它 PATH/Java/PG 全不可见）"
  if [ -f "$ENV_FILE" ]; then
    while IFS= read -r kv; do
      grep -qxF "$kv" "$ENV_FILE" || prob "$ENV_FILE 缺少/漂移的期望行：$kv"
    done <<EOF
LANG=zh_CN.UTF-8
JAVA_HOME=$JAVA_HOME_DEFAULT
PATH=$EXPECTED_PATH
EOF
    grep -qE '^GIT_ALTERNATE_OBJECT_DIRECTORIES=.*\.git/objects$' "$ENV_FILE" \
      || prob "$ENV_FILE 缺 GIT_ALTERNATE_OBJECT_DIRECTORIES（批量 checkout 会被 github.com 掐断）"
  fi

  for s in python python3 pip; do
    [ -x "$SHIMS/$s" ] || prob "缺 shim $SHIMS/$s（自托管侧跳过 setup-python 后由它提供 $s）"
  done

  d="$(wexpected_dir)"
  is_git_repo "$d" || prob "预置工作区 $d 不是 git 仓库（checkout 退回全量克隆 ⇒ 卡满超时）"
  [ -d "$TOOL_CACHE" ] || prob "缺 tool cache $TOOL_CACHE（setup-node 无法命中缓存）"

  if [ "$problems" = "0" ]; then
    ok "自托管 runner 环境自检通过（$RUNNER_DIR）"
    exit 0
  fi
  echo "❌ 自托管 runner 环境漂移（$problems 处）—— 修复：$0" >&2
  exit 1
fi

# =============================================================================
# 安装档
# =============================================================================
say "仓库: $REPO | 目录: $RUNNER_DIR | runner 名: $RUNNER_NAME | 标签: self-hosted,$RUNNER_LABELS"

OS="$(uname -s | tr 'A-Z' 'a-z')"                     # darwin / linux
ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && RUNNER_ARCH="arm64" || RUNNER_ARCH="x64"

# 1. 工具缓存目录（setup-node / setup-python 的 `_tool` 落点）
[ -d "$TOOL_CACHE" ] || { mkdir -p "$TOOL_CACHE"; ok "建 tool cache $TOOL_CACHE"; }

# 2. shim：Homebrew 的 python@3.11 只提供 `python3`，而 CI 判据步写的是 `python -m pytest`
#    ⇒ 补 `python` / `python3` / `pip` 三个**名字**（`.env` 的 PATH 把 `_shims` 排在最前）
mkdir -p "$SHIMS"
for pair in "python3.11:python" "python3.11:python3" "pip3.11:pip"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ ! -x "$PY_BIN/$src" ]; then
    say "⚠️ 找不到 $PY_BIN/$src —— 跳过 shim $dst（python 判据腿会红，见本脚本头部）"
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
ALT_OBJ=""
if is_git_repo "$MIRROR_REPO"; then
  ALT_OBJ="$MIRROR_REPO/.git/objects"
else
  say "⚠️ 本机镜像仓库不可用（$MIRROR_REPO 不是 git 仓库）⇒ 不写 GIT_ALTERNATE_OBJECT_DIRECTORIES；"
  say "   runner 将自行克隆 —— 实测本机到 github.com 的批量传输会被掐断（early EOF），checkout 可能卡满超时"
fi
ENV_BODY="LANG=zh_CN.UTF-8
JAVA_HOME=$JAVA_HOME_DEFAULT
PATH=$EXPECTED_PATH
GIT_ALTERNATE_OBJECT_DIRECTORIES=$ALT_OBJ"
if [ "$PRINT_ENV" = "1" ]; then
  echo "──── 将写入 $ENV_FILE（无密钥）────"
  printf '%s\n' "$ENV_BODY"
  exit 0
fi
if [ -f "$ENV_FILE" ] && [ "$(cat "$ENV_FILE")" = "$ENV_BODY" ]; then
  ok ".env 已是最新（未改写）"
else
  printf '%s\n' "$ENV_BODY" > "$ENV_FILE"
  ok "写入 $ENV_FILE"
fi

# 4. 预置工作区：本机已有克隆 ⇒ 本地克隆（实测 291 MB / 0.28 s），再靠 `.env` 的 alternates
#    只读共享对象库 ⇒ `actions/checkout` 的 fetch 秒级完成。
WEXP="$(wexpected_dir)"
if is_git_repo "$WEXP"; then
  ok "预置工作区已存在（未重建）：$WEXP"
elif is_git_repo "$MIRROR_REPO"; then
  mkdir -p "$(dirname "$WEXP")"
  if git clone --no-checkout "$MIRROR_REPO" "$WEXP" >/dev/null 2>&1; then
    ok "预置工作区 $WEXP（本地克隆自 $MIRROR_REPO）"
  else
    say "⚠️ 本地克隆失败 ⇒ 交给 runner 自行 checkout（可能卡满超时）"
  fi
else
  say "⚠️ 无本机镜像仓库可克隆 —— 工作区将首次由 runner 全量克隆"
fi

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
  ok "runner 已注册（名 $RUNNER_NAME，标签 self-hosted,$RUNNER_LABELS）"
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
