#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# bmini-experience.sh — B 端小程序「构建 + 上传体验版」的**唯一入口**（issue #8980）
#
# ## 治什么（2026-11-21 首次手工发体验版的三个形态）
#
#   ① **生产常量靠人手记**：三个 `TARO_APP_*` 少给一个，产物就**静默**烘进测试域 / localhost
#      （上传照样成功，只有真机连不上）⇒ 现在由 `--env` **一处**决定，且构建完**立刻**跑产物断言；
#   ② **上传命令靠临时拼**：项目目录 / appid / 版本号 / 通道每次现敲（换机器 / 换人就得重来）⇒
#      现在由本脚本拼，且**断言不通过不许上传**；
#   ③ **发错包没人拦**：`upload` 先跑 `deploy/scripts/bmini-assert-dist.sh`（结构 / 域名策略 / 体积），
#      红即拒绝上传（这就是「顺序即安全顺序」的那一条）。
#
# ## 用法
#
#   scripts/bmini-experience.sh build  [--env prod|test]
#   scripts/bmini-experience.sh upload --version X.Y.Z [--desc '…'] [--env prod|test] [--key <私钥路径>]
#   scripts/bmini-experience.sh all    --version X.Y.Z [--desc '…'] [--env prod|test] [--key <私钥路径>]
#
#   `build`  = 注入三个 `TARO_APP_*` → `npm run build:weapp` → 产物断言
#   `upload` = 先跑产物断言（**不过不许上传**）→ 有私钥走 `miniprogram-ci`，否则 macOS + 已登录的
#              微信开发者工具 CLI（临时工程：自动生成含 appid 的 project.config.json）
#   `all`    = build + upload
#
#   `--env prod`（缺省）= 三个常量都注入 `https://app.cytda.com`（生产域，nginx 已代理 `/api/`）
#   `--env test`        = 三个常量都注入 `https://app.migaozn.com`（测试域）
#
# 🔴 **为什么缺省是 prod 而不是 test**：本脚本的存在意义是**发布**。缺省 prod 时，误跑一次
#    只是「构建了一个生产包」（惰性、无害，且断言会把它验一遍）；而缺省 test 时，误跑一次会把
#    **指向测试域的包**上传成体验版 —— 那正是本单要根治的形态（上传成功、真机连不上、
#    开发者工具勾了「不校验合法域名」时连错都看不见）。
#
# 🔴 **版本号必须显式给**（不自动递增、不从 package.json 猜）：体验版版本号是人对「这次发了什么」
#    的承诺，自动递增会把它变成一个谁也没看过的数字。
#
# 退出码：0 成功 / 1 构建·断言·上传失败 / 2 用法错误
#
# 边界（照实登记）：
#   · `miniprogram-ci` 通道**要**小程序后台的「代码上传私钥」+ 代码上传 IP 白名单（官方口径），
#     而且**只能**上传/预览 —— 提交审核 / 选体验版 / 发布仍要在后台点（`miniprogram-ci` 无此能力）；
#   · 开发者工具 CLI 通道**要**那台机器上 IDE 已登录该小程序的开发者账号（本脚本不代登录）；
#   · 两条通道都**不**校验微信后台的「服务器域名」白名单（仓库侧判不了，见 docs 的发布前置条件）。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_DIR="${ROOT}/frontend/bmini-app"
DIST="${APP_DIR}/dist"
ASSERT="${ROOT}/deploy/scripts/bmini-assert-dist.sh"

# 小程序 AppID（与 frontend/mini-app/project.private.config.json 同一主体；appid 不是密钥）
APPID="wx6ee2f682c1b4822c"
DEVTOOLS_CLI="/Applications/wechatwebdevtools.app/Contents/MacOS/cli"

PROD_ORIGIN="https://app.cytda.com"
TEST_ORIGIN="https://app.migaozn.com"

CMD=""
ENV_NAME="prod"
VERSION=""
DESC=""
KEY=""

usage() {
  cat <<'USAGE'
用法: scripts/bmini-experience.sh <build|upload|all> [选项]

  build  [--env prod|test]
      注入三个 TARO_APP_* → npm run build:weapp → 产物断言（结构 / 域名策略 / 体积）

  upload --version X.Y.Z [--desc '…'] [--env prod|test] [--key <私钥路径>]
      先跑产物断言（不通过**拒绝上传**）→ miniprogram-ci 或微信开发者工具 CLI

  all    --version X.Y.Z [--desc '…'] [--env prod|test] [--key <私钥路径>]
      build + upload

选项:
  --env prod|test   注入哪一套常量（缺省 prod）；断言按同一 env 判域名策略
  --version X.Y.Z   **必填**（upload / all）：体验版版本号，显式给、不自动递增
  --desc '…'        版本备注（缺省 'bmini 体验版 <version>'）
  --key <路径>      代码上传私钥；也可用环境变量 MINIPROGRAM_UPLOAD_KEY

环境变量:
  MINIPROGRAM_UPLOAD_KEY   等价于 --key（有它就走 miniprogram-ci）

退出码: 0 成功 / 1 构建·断言·上传失败 / 2 用法错误
USAGE
}

die_usage() {
  echo "❌ 用法错误：$*" >&2
  usage >&2
  exit 2
}

die() {
  echo "❌ $*" >&2
  exit 1
}

# ── 子命令 + 选项 ──────────────────────────────────────────────────────────────
[ $# -ge 1 ] || { usage >&2; exit 2; }
CMD=$1
shift
case "$CMD" in
  build|upload|all) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    die_usage "未知子命令：${CMD}（只接受 build|upload|all）"
    ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --env)
      [ $# -ge 2 ] || die_usage "--env 缺值（只接受 prod|test）"
      ENV_NAME=$2
      shift 2
      ;;
    --env=*)
      ENV_NAME=${1#--env=}
      shift
      ;;
    --version)
      [ $# -ge 2 ] || die_usage "--version 缺值（形如 1.0.0）"
      VERSION=$2
      shift 2
      ;;
    --version=*)
      VERSION=${1#--version=}
      shift
      ;;
    --desc)
      [ $# -ge 2 ] || die_usage "--desc 缺值"
      DESC=$2
      shift 2
      ;;
    --desc=*)
      DESC=${1#--desc=}
      shift
      ;;
    --key)
      [ $# -ge 2 ] || die_usage "--key 缺值（私钥路径）"
      KEY=$2
      shift 2
      ;;
    --key=*)
      KEY=${1#--key=}
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die_usage "未知参数：$1"
      ;;
  esac
done

case "$ENV_NAME" in
  prod|test) ;;
  *) die_usage "--env 只接受 prod|test（收到：${ENV_NAME}）" ;;
esac

if [ "$CMD" != "build" ]; then
  [ -n "$VERSION" ] || die_usage "${CMD} 必须显式给 --version X.Y.Z（不自动递增）"
  # 版本号形态：显式给 + 形态可判 ⇒ 打错一个数字当场拦住，而不是变成一个奇怪的版本落进后台
  if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    die_usage "--version 必须是 X.Y.Z（收到：${VERSION}）"
  fi
  [ -n "$DESC" ] || DESC="bmini 体验版 ${VERSION}"
fi

origin_for_env() {
  case "$1" in
    prod) printf '%s' "$PROD_ORIGIN" ;;
    test) printf '%s' "$TEST_ORIGIN" ;;
  esac
}

# ── 产物断言（**唯一**实现 = deploy/scripts/bmini-assert-dist.sh）─────────────────
assert_dist() {
  [ -f "$ASSERT" ] || die "缺少产物断言脚本 ${ASSERT} —— 没有判据不许构建/上传"
  bash "$ASSERT" "$DIST" --env "$ENV_NAME"
}

# ── build ─────────────────────────────────────────────────────────────────────
cmd_build() {
  local origin
  origin=$(origin_for_env "$ENV_NAME")
  echo "== 构建 B 端小程序 weapp 产物（env=${ENV_NAME}）=="
  echo "   TARO_APP_API_URL=${origin}"
  echo "   TARO_APP_AI_API_URL=${origin}"
  echo "   TARO_APP_PUBLIC_APP_ORIGIN=${origin}"
  echo "   （三个常量由本脚本注入；外部再给会被这里的值覆盖）"
  [ -d "$APP_DIR/node_modules" ] || die "缺少依赖：先在 ${APP_DIR} 跑 npm ci（本工作区的 node_modules，不要软链别的 worktree）"
  (
    cd "$APP_DIR" || exit 1
    TARO_APP_API_URL="$origin" \
    TARO_APP_AI_API_URL="$origin" \
    TARO_APP_PUBLIC_APP_ORIGIN="$origin" \
      npm run build:weapp
  ) || die "npm run build:weapp 失败（看上面的构建日志）"
  echo ""
  assert_dist || die "产物断言未通过 ⇒ 这个产物不许上传（env=${ENV_NAME}）"
  echo ""
}

# ── upload ────────────────────────────────────────────────────────────────────
upload_with_miniprogram_ci() {
  local key=$1
  [ -f "$key" ] || die "代码上传私钥不存在：${key}"
  echo "   通道：miniprogram-ci（npm npx，无新依赖）"
  echo "   私钥：${key}（不入库、不进日志）"
  # ⚠️ miniprogram-ci 的 CLI 里 `--version` 是「显示版本号」的布尔开关；
  #    上传版本号是 `--upload-version`（简写 `--uv`）—— 写成 `--version 1.0.0` 会被当成布尔位吞掉。
  ( cd "$APP_DIR" && npx --yes miniprogram-ci@2 upload \
      --appid "$APPID" \
      --project-path "$APP_DIR" \
      --private-key-path "$key" \
      --upload-version "$VERSION" \
      --upload-description "$DESC" ) \
    || die "miniprogram-ci upload 失败（看上面的报错；常见：私钥与 appid 不匹配 / 代码上传 IP 白名单未含本机出口 IP）"
}

upload_with_devtools() {
  local tmp="${TMPDIR:-/tmp}/bmini-experience-$$"
  rm -rf "$tmp"
  mkdir -p "$tmp" || die "无法创建临时工程目录：${tmp}"
  # 临时工程 = 产物副本 + 自动生成的 project.config.json（含 appid）。
  # 为什么要复制而不是软链：`miniprogramRoot` 必须落在工程目录**内**（`../dist` 这类越界路径
  # 开发者工具不接受），而复制 1.5MB 是零风险的最小代价。
  cp -R "$DIST" "${tmp}/dist" || { rm -rf "$tmp"; die "复制产物失败：${DIST} → ${tmp}/dist"; }
  # project.config.json 的口径**从仓库那份派生**（单一真源：setting / compileType 不另写一份），
  # 只覆盖 appid 与 miniprogramRoot。
  python3 - "${APP_DIR}/project.config.json" "${tmp}/project.config.json" "$APPID" <<'PY' || { rm -rf "$tmp"; die "生成 project.config.json 失败"; }
import json
import sys

src, dst, appid = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding='utf-8') as fh:
    cfg = json.load(fh)
cfg['appid'] = appid
cfg['miniprogramRoot'] = './dist'
with open(dst, 'w', encoding='utf-8') as fh:
    json.dump(cfg, fh, ensure_ascii=False, indent=2)
    fh.write('\n')
PY
  echo "   通道：微信开发者工具 CLI（需该机 IDE 已登录本小程序开发者账号）"
  echo "   临时工程：${tmp}（含自动生成的 project.config.json，appid=${APPID}）"
  if ! "$DEVTOOLS_CLI" upload --project "$tmp" --version "$VERSION" --desc "$DESC"; then
    rm -rf "$tmp"
    die "微信开发者工具 CLI upload 失败（常见：IDE 未登录 / 端口未开 / 「安全设置」未开 CLI）"
  fi
  rm -rf "$tmp"
}

cmd_upload() {
  echo "== 上传体验版（version=${VERSION}，env=${ENV_NAME}）=="
  echo "   desc=${DESC}"
  echo ""
  # 🔴 顺序即安全顺序：**先断言，再上传**。断言红（或不可判定 = 3）⇒ 一行都不传。
  assert_dist || die "产物断言未通过 ⇒ 拒绝上传（env=${ENV_NAME}，dist=${DIST}）"
  echo ""
  KEY=${KEY:-${MINIPROGRAM_UPLOAD_KEY:-}}
  if [ -n "$KEY" ]; then
    upload_with_miniprogram_ci "$KEY"
  elif [ "$(uname -s)" = "Darwin" ] && [ -x "$DEVTOOLS_CLI" ]; then
    upload_with_devtools
  else
    die "没有可用的上传通道：给 --key <私钥> 或 MINIPROGRAM_UPLOAD_KEY（miniprogram-ci），或在**已装且已登录**微信开发者工具的 macOS 上跑（当前 uname=$(uname -s)，cli=${DEVTOOLS_CLI}）"
  fi
  echo ""
  echo "✅ 上传完成：version=${VERSION}（接下来在微信后台「版本管理」里选为体验版 —— 那一步 miniprogram-ci 做不了）"
}

# ── 分发 ──────────────────────────────────────────────────────────────────────
case "$CMD" in
  build)
    cmd_build
    ;;
  upload)
    cmd_upload
    ;;
  all)
    cmd_build || exit 1
    cmd_upload || exit 1
    ;;
esac
