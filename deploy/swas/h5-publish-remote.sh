#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 工人端 H5（frontend/worker-h5/）静态落位 —— **远端执行体**（issue #4837）
#
# 背景（实测，非推断）：`frontend/worker-h5/` 是**零依赖 + 零构建**的纯 ES module 目录
# （`index.html` + `src/{api,app,render,scan-input}.mjs` + `src/styles.css`）⇒ 发布 = **逐字拷贝**，
# **不引入 npm build**（设计文档 §706「无新构建腿」）。而 `app.migaozn.com` 的静态根
# （nginx `root` = `/opt/migao-deploy/h5`）此前**仓内没有任何 CI 发布**
# （`grep -rn '/opt/migao-deploy' .github/workflows/` = 0 命中）⇒ 稳定短链 302 到 `/w/` 时命中的是
# `location /` 的 `try_files $uri $uri/ /index.html` **静默回落**：HTTP 200 + **C 端 Taro H5**
# （不是 404 ⇒ 监控不会红）。本脚本把 `w/` 真正落上去。
#
# 为什么是**独立文件**而不是把命令内联进 workflow：
#   同一份代码在**三个**地方执行 —— ① SWAS 云助手（CI 发布）② 本地沙箱复跑
#   （守卫 `tests/unit_ci_workflows/test_worker_h5_hosting.py` 的行为级红证）③ 人工排障。
#   内联会立刻造出「测试测的是另一份实现」这个形态。
#
# 🔴 红线（本单最重要的一条）：静态根 `/opt/migao-deploy/h5` **同时承载线上 C 端 H5**
#   （Taro `build:h5` 产物：`index.html` + `js/` + `css/` + `chunk/`）⇒
#   本脚本**只允许**清空/覆盖 `<静态根>/<子目录>`（默认 `w/`）**子树**，
#   **绝不**对静态根本身做 `--delete` / 清空 / `rm -rf`。
#   判定落在 `assert_target_safe()` + `purge_target()`（都在动手之前），
#   并有「发布前后父目录 `index.html` 哈希必须一致」的**自证**（`PARENT_INDEX_*_SHA256`）——
#   也就是说：红线不是靠注释承诺，而是每次发布都在输出里留下判据。
#
# 用法（本地 / 远端**同一入口**；CLI 参数覆盖环境变量）：
#   # ① 线上（CI 侧只注入环境变量后把本文件拼接成 RunCommand 内容）
#   H5_PUBLISH_SHA=<40 位 commit> bash deploy/swas/h5-publish-remote.sh
#   # ② 本地沙箱复跑（不联网、不碰真实静态根 —— 守卫测试与人工排障）
#   H5_PUBLISH_FROM_DIR=frontend/worker-h5 H5_STATIC_ROOT=/tmp/h5-sandbox bash deploy/swas/h5-publish-remote.sh
#
# 发布内容 = `index.html` + `src/**`（含 `styles.css`）；`tests/**` **不发**。
# 幂等：连跑两次结果逐字节一致（先把目标子树收敛为空，再整份拷入）。
# 退出码：0 = 已发布且自证通过；非零 = **什么都没改 / 已显式失败**（绝不静默半成品）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# 默认值 = 线上真值（`deploy/swas/nginx.conf` 的 `root` + 本单约定的子目录 `w`）。
# ⚠️ 用 `${VAR-default}`（**不是** `${VAR:-default}`）：**显式置空 ⇒ 拒绝**（见 assert_target_safe），
#    而不是「悄悄回落到 w」—— 把空值当默认值会把一个写错的调用变成一次真实发布。
STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${H5_SUBDIR-w}
REPO=${H5_REPO:-zhaokai-mgzn/migao}
SRC_SUBPATH=${H5_SRC_SUBPATH:-frontend/worker-h5}
SHA=${H5_PUBLISH_SHA:-}
FROM_DIR=${H5_PUBLISH_FROM_DIR:-}
TARGET=""

die() { echo "❌ $*" >&2; exit 1; }

usage() { sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,34p'; }

# macOS 无 `sha256sum`（本地复跑要跑得动 ⇒ 两种实现都认；远端是哪种都不影响判定）
file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

file_sha256_or_absent() {
  if [ -f "$1" ]; then file_sha256 "$1"; else echo "(absent)"; fi
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --sha)         SHA=${2:-}; shift 2 ;;
      --from-dir)    FROM_DIR=${2:-}; shift 2 ;;
      --static-root) STATIC_ROOT=${2:-}; shift 2 ;;
      --subdir)      SUBDIR=${2:-}; shift 2 ;;
      --repo)        REPO=${2:-}; shift 2 ;;
      --src-subpath) SRC_SUBPATH=${2:-}; shift 2 ;;
      -h|--help)     usage; exit 0 ;;
      *)             die "未知参数：$1（-h 看用法）" ;;
    esac
  done
}

# ── 目标守卫（fail-closed，**在创建/清理任何东西之前**）───────────────────────
# 判据 = 「目标必须是静态根下的**严格子目录**，且子目录名是**单一普通组件**」。
# 任何一条不成立 ⇒ 立刻 die：宁可红，也不要在错误路径上做清理。
assert_target_safe() {
  case "$STATIC_ROOT" in
    /*) : ;;
    *) die "静态根必须是绝对路径：'$STATIC_ROOT'" ;;
  esac
  [ "$STATIC_ROOT" != "/" ] || die "静态根不能是 /（拒绝在根目录上工作）"
  case "$SUBDIR" in
    ""|"."|".."|*/*|.*) die "子目录必须是单一普通组件（不接受空/./../斜杠/点开头）：'$SUBDIR'" ;;
  esac
  TARGET="$STATIC_ROOT/$SUBDIR"
  [ "$TARGET" != "$STATIC_ROOT" ] || die "目标与静态根相同 —— 拒绝"
  case "$TARGET" in
    "$STATIC_ROOT"/*) : ;;
    *) die "目标 '$TARGET' 不在静态根 '$STATIC_ROOT' 之下 —— 拒绝" ;;
  esac
  [ -d "$STATIC_ROOT" ] || die "静态根不存在：'$STATIC_ROOT'（路径写错时**宁可红**，不新建目录）"
}

# 收敛**目标子树**（唯一允许的清理动作）。两条独立判据重复把关：
# 目标既是静态根的严格子目录，又不等于静态根本身。
purge_target() {
  [ -n "$TARGET" ] || die "内部错误：TARGET 为空（拒绝清理）"
  [ "$TARGET" != "$STATIC_ROOT" ] || die "拒绝清空静态根本身（红线）"
  case "$TARGET" in
    "$STATIC_ROOT"/*) : ;;
    *) die "拒绝清理静态根之外的路径：'$TARGET'" ;;
  esac
  [ -d "$TARGET" ] || return 0
  find "$TARGET" -mindepth 1 -delete || die "清理目标子树失败（fail-closed，不继续）"
}

main() {
  parse_args "$@"
  assert_target_safe

  [ -n "$FROM_DIR" ] || [ -n "$SHA" ] || die "必须给 H5_PUBLISH_FROM_DIR（本地目录）或 H5_PUBLISH_SHA（commit sha）"

  WORK="$(mktemp -d)"
  STAGE="$(mktemp -d)"
  # 注意：清掉的是**自己刚建的两个临时目录**，与静态根无关（唯一一处 rm -rf，参数不含任何静态根变量）
  trap 'rm -rf "$WORK" "$STAGE"' EXIT

  if [ -n "$FROM_DIR" ]; then
    SRC="$FROM_DIR"
    echo "SOURCE_DIR=${SRC}（本地目录直达，不联网）"
  else
    case "$SHA" in
      *[!0-9a-fA-F]*) die "SHA 非法：'$SHA'（只接受十六进制 commit sha）" ;;
    esac
    [ "${#SHA}" -ge 7 ] || die "SHA 太短：'$SHA'"
    URL="https://codeload.github.com/$REPO/tar.gz/$SHA"
    echo "SOURCE_URL=$URL"
    # 与 deploy/scripts/swas-deploy-ci.sh 同一条通道（实测：服务器走 codeload.github.com 可达，
    # raw.githubusercontent.com 在杭州机房超时）
    curl -fsSL --retry 3 --retry-delay 2 "$URL" -o "$WORK/src.tgz" || die "下载源码失败：$URL"
    tar xzf "$WORK/src.tgz" -C "$WORK" --strip-components=1 || die "解包失败"
    SRC="$WORK/$SRC_SUBPATH"
  fi

  [ -f "$SRC/index.html" ] || die "源码里没有 index.html：$SRC"
  [ -d "$SRC/src" ] || die "源码里没有 src/：$SRC"
  [ -f "$SRC/src/app.mjs" ] || die "源码里没有 src/app.mjs（工人端入口）：$SRC"

  # 发布内容 = index.html + src/**（tests/** 不发；**逐字拷贝**，不做任何加工）
  cp "$SRC/index.html" "$STAGE/index.html"
  cp -R "$SRC/src" "$STAGE/src"

  PARENT_BEFORE="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"

  mkdir -p "$TARGET"
  purge_target
  cp -R "$STAGE/." "$TARGET/"

  PARENT_AFTER="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"
  PUBLISHED="$(file_sha256 "$TARGET/index.html")"

  echo "TARGET=$TARGET"
  echo "PARENT_INDEX_BEFORE_SHA256=$PARENT_BEFORE"
  echo "PARENT_INDEX_AFTER_SHA256=$PARENT_AFTER"
  echo "PUBLISHED_INDEX_SHA256=$PUBLISHED"
  echo "PUBLISHED_FILES_BEGIN"
  ( cd "$TARGET" && find . -type f | sort | sed 's/^/  /' )
  echo "PUBLISHED_FILES_END"

  [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] || die "红线被破坏：静态根的 index.html 在发布前后不一致"
  echo "✅ 已发布 ${TARGET}（父目录 index.html 未被触碰：${PARENT_AFTER}）"
}

main "$@"
