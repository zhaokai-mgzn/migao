#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 观星台终端（Windows EXE / Android APK）静态落位 —— **远端执行体**（issue #8195）
#
# 落位：`app.migaozn.com` 静态根（nginx `root` = `/opt/migao-deploy/h5`）下的 **`terminal/`** 子树：
#   `<静态根>/terminal/latest.json`           ← Windows 更新清单（终端 Program.cs 硬编码读取）
#   `<静态根>/terminal/android/latest.json`   ← Android 更新清单（终端 Updater.java 硬编码读取）
#   `<静态根>/terminal/<安装包.exe>`
#   `<静态根>/terminal/<安装包.apk>`
# 两个清单地址是**终端仓定的**，不是本脚本的自由选择；改名 = 已装机器再也检查不到更新。
#
# 🔴 红线一（与工人端 `w/`、B 端 `b/` 同源）：静态根**同时承载线上 C 端元元 H5**（同一个 root、
#   同一个 `location /`）⇒ 本脚本**只允许**清空/覆盖 `<静态根>/terminal` 子树，
#   **绝不**对静态根本身做 `--delete` / 清空 / `rm -rf`。判定落在 `assert_target_safe()` +
#   `purge_target()`（都在动手之前），并有「发布前后父目录 `index.html` 哈希必须一致」的自证。
#
# 🔴 红线二（本面特有）：**清单必须与载荷对得上**。`latest.json` / `latest-android.json` 里写着
#   `download_url` / `sha256` / `size`；只要其中任一项与实际文件不符（搬坏了、发错版本、
#   清单被手改过），终端就会「永远检查到同一个版本」或「下载后校验失败」——
#   而这两种都**不会**在服务器侧报错 ⇒ `assert_payload_complete()` 在**写入目标之前**逐条比对，
#   不一致就 die（fail-closed，而不是发上去再等人发现）。
#
# 用法（本地 / 远端**同一入口**；CLI 参数覆盖环境变量）：
#   # ① 线上（CI 侧注入环境变量后把本文件拼接成 RunCommand 内容）
#   TERMINAL_PUBLISH_IMAGE=<registry>/<ns>/terminal-dist:sha-xxxxxxx \
#     TERMINAL_RELEASE_TAG=terminal-v1.0.1 bash deploy/swas/terminal-publish-remote.sh
#   # ② 本地沙箱复跑（不联网、不碰真实静态根 —— 守卫测试与人工排障）
#   TERMINAL_PUBLISH_FROM_DIR=/tmp/terminal-dist TERMINAL_STATIC_ROOT=/tmp/h5-sandbox \
#     bash deploy/swas/terminal-publish-remote.sh
#
# 幂等：连跑两次结果逐字节一致（先把目标子树收敛为空，再整份拷入）。
# 退出码：0 = 已发布且自证通过；非零 = **什么都没改 / 已显式失败**（绝不静默半成品）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# 默认值 = 线上真值（`deploy/swas/nginx.conf` 的 `root` + 本单约定的子目录 `terminal`）。
# ⚠️ 用 `${VAR-default}`（**不是** `${VAR:-default}`）：**显式置空 ⇒ 拒绝**（见 assert_target_safe），
#    而不是「悄悄回落」—— 把空值当默认值会把一个写错的调用变成一次真实发布。
STATIC_ROOT=${TERMINAL_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${TERMINAL_SUBDIR-terminal}
IMAGE=${TERMINAL_PUBLISH_IMAGE:-}
FROM_DIR=${TERMINAL_PUBLISH_FROM_DIR:-}
RELEASE_TAG=${TERMINAL_RELEASE_TAG:-}
TARGET=""
STAGE=""
WORK=""

die() { echo "❌ $*" >&2; exit 1; }

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
      --from-dir)    FROM_DIR=${2:-}; shift 2 ;;
      --image)       IMAGE=${2:-}; shift 2 ;;
      --static-root) STATIC_ROOT=${2:-}; shift 2 ;;
      --subdir)      SUBDIR=${2:-}; shift 2 ;;
      --release-tag) RELEASE_TAG=${2:-}; shift 2 ;;
      -h|--help)     sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,40p'; exit 0 ;;
      *)             die "未知参数：$1（-h 看用法）" ;;
    esac
  done
}

# ── 目标守卫（fail-closed，**在创建/清理任何东西之前**）───────────────────────
# 判据 = 「目标必须是静态根下的**严格子目录**，且子目录名是**单一普通组件**」。
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

# 收敛**目标子树**（唯一允许的清理动作）。
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

# ── 取载荷到 ${STAGE}（两条等价来源；发布腿走 IMAGE，本地/沙箱走 FROM_DIR）──────
stage_payload() {
  mkdir -p "$STAGE"
  if [ -n "$FROM_DIR" ]; then
    [ -d "$FROM_DIR" ] || die "发布源目录不存在：'$FROM_DIR'"
    echo "SOURCE_DIR=${FROM_DIR}"
    cp -R "$FROM_DIR/." "$STAGE/" || die "拷贝发布源失败：'$FROM_DIR'"
    return 0
  fi
  command -v docker >/dev/null 2>&1 \
    || die "实例上没有 docker —— 无法从传输镜像里取出载荷（见 deploy/terminal-dist/Dockerfile）"
  echo "SOURCE_IMAGE=${IMAGE}"
  docker pull "$IMAGE" >&2 || die "拉取传输镜像失败：'$IMAGE'（实例是否已 docker login ACR？）"
  local cid
  cid=$(docker create "$IMAGE") || die "创建临时容器失败：'$IMAGE'"
  if ! docker cp "$cid:/dist/." "$STAGE/"; then
    docker rm -f "$cid" >/dev/null 2>&1 || true
    die "从镜像里取载荷失败（镜像里没有 /dist？）—— 临时容器已清理"
  fi
  docker rm -f "$cid" >/dev/null || die "清理临时容器失败：'$cid'（实例上可能残留一个已停止容器）"
  return 0
}

# 清单字段（生成器固定 2 空格缩进、一键一行 ⇒ 这里的抽取值是**确定**的；抽不到即红）
manifest_field() {
  sed -n "s/.*\"$2\": *\"\\([^\"]*\\)\".*/\\1/p" "$1" | head -1
}

manifest_number() {
  sed -n "s/.*\"$2\": *\\([0-9][0-9]*\\).*/\\1/p" "$1" | head -1
}

# 单份清单 ⇄ 载荷的一致性（**在写入目标之前**）：
# ① `download_url` 指向的文件必须在载荷里（否则线上会出现「清单说有、下载 404」）；
# ② `sha256` 必须等于该文件实际哈希（否则终端下载完校验失败，且服务器侧无感）；
# ③ `size` 必须等于实际字节数（同一条，多一道）。
check_manifest() {
  local mf=$1 label=$2 url sha size name actual_sha actual_size
  [ -f "$mf" ] || die "${label} 清单缺失：$mf"
  url=$(manifest_field "$mf" download_url)
  sha=$(manifest_field "$mf" sha256)
  size=$(manifest_number "$mf" size)
  [ -n "$url" ] || die "${label} 清单缺 download_url（不是合法的发布清单）：$mf"
  [ -n "$sha" ] || die "${label} 清单缺 sha256（或不是 64 位十六进制）：$mf"
  [ -n "$size" ] || die "${label} 清单缺 size：$mf"
  name=$(basename "$url")
  [ -f "$STAGE/$name" ] || die "${label} 清单指向的文件不在载荷里：'$name'（清单说有、实际没有 = 线上 404）"
  actual_sha=$(file_sha256 "$STAGE/$name")
  actual_size=$(wc -c < "$STAGE/$name" | tr -d ' ')
  [ "$actual_sha" = "$sha" ] \
    || die "${label} 清单的 sha256 与载荷不一致：清单 '$sha' ≠ 实际 '$actual_sha'（清单被改过 / 载荷搬坏了）"
  [ "$actual_size" = "$size" ] \
    || die "${label} 清单的 size 与载荷不一致：清单 '$size' ≠ 实际 '$actual_size'"
}

# 载荷完整性（**在写入目标之前**，fail-closed）。
assert_payload_complete() {
  local unexpected=""
  [ -f "$STAGE/latest.json" ] || die "载荷里没有 latest.json（发布源不是 prepare 生成的目录？）"
  [ -f "$STAGE/latest-android.json" ] || die "载荷里没有 latest-android.json（发布源不是 prepare 生成的目录？）"
  # 只允许发布面内的文件：多一个文件就是「有人把别的目录当载荷发」的形态
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    case "$rel" in
      latest.json|latest-android.json|*.exe|*.apk) : ;;
      *) unexpected="${unexpected} ${rel}" ;;
    esac
  done < <(cd "$STAGE" && find . -mindepth 1 -type f | sed 's|^\./||')
  [ -z "$unexpected" ] || die "载荷里有发布面之外的文件：${unexpected}（只允许 exe/apk/两份清单）"
  [ -z "$(find "$STAGE" -mindepth 1 -type d)" ] || die "载荷里不该有子目录（会打乱落位布局）"
  [ -z "$(find "$STAGE" -mindepth 1 -type l)" ] || die "载荷里不许有符号链接（越界读风险）"

  check_manifest "$STAGE/latest.json" "Windows"
  check_manifest "$STAGE/latest-android.json" "Android"
  echo "PAYLOAD_MANIFEST_OK=1"
}

main() {
  parse_args "$@"
  assert_target_safe
  [ -n "$FROM_DIR" ] || [ -n "$IMAGE" ] || die "必须给 TERMINAL_PUBLISH_FROM_DIR（本地目录）或 TERMINAL_PUBLISH_IMAGE（传输镜像）"
  [ -n "$RELEASE_TAG" ] || die "必须给 --release-tag（发布自证要写清发的是哪一版）"

  WORK=$(mktemp -d)
  STAGE="$WORK/stage"
  # 注意：清掉的是**自己刚建的临时目录**，与静态根无关（唯一一处 rm -rf，参数不含任何静态根变量）
  trap 'rm -rf "$WORK"' EXIT

  stage_payload
  assert_payload_complete

  PARENT_BEFORE="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"

  mkdir -p "$TARGET"
  purge_target
  cp -R "$STAGE/." "$TARGET/"
  # 载荷里的生成期文件名 `latest-android.json` 落到线上必须叫 `android/latest.json`
  # （终端 Updater.java 的硬编码地址）。改名不改变内容 ⇒ 哈希不变。
  mkdir -p "$TARGET/android"
  mv "$TARGET/latest-android.json" "$TARGET/android/latest.json"

  PARENT_AFTER="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"
  local staged_latest staged_android published_latest published_android file_count
  staged_latest="$(file_sha256 "$STAGE/latest.json")"
  staged_android="$(file_sha256 "$STAGE/latest-android.json")"
  published_latest="$(file_sha256 "$TARGET/latest.json")"
  published_android="$(file_sha256 "$TARGET/android/latest.json")"
  file_count="$(find "$TARGET" -type f | wc -l | tr -d ' ')"

  echo "TARGET=$TARGET"
  echo "RELEASE_TAG=$RELEASE_TAG"
  echo "PARENT_INDEX_BEFORE_SHA256=$PARENT_BEFORE"
  echo "PARENT_INDEX_AFTER_SHA256=$PARENT_AFTER"
  echo "STAGED_LATEST_SHA256=$staged_latest"
  echo "PUBLISHED_LATEST_SHA256=$published_latest"
  echo "STAGED_ANDROID_SHA256=$staged_android"
  echo "PUBLISHED_ANDROID_SHA256=$published_android"
  echo "PUBLISHED_FILE_COUNT=$file_count"
  echo "PUBLISHED_FILES_BEGIN"
  ( cd "$TARGET" && find . -type f | sort | sed 's/^/  /' )
  echo "PUBLISHED_FILES_END"

  [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] || die "红线被破坏：静态根的 index.html 在发布前后不一致"
  [ "$published_latest" = "$staged_latest" ] || die "发布后的 latest.json 与载荷不一致（拷贝过程出问题？）"
  [ "$published_android" = "$staged_android" ] || die "发布后的 android/latest.json 与载荷不一致（拷贝过程出问题？）"
  echo "✅ 已发布 ${TARGET}（${file_count} 个文件；父目录 index.html 未被触碰：${PARENT_AFTER}）"
}

main "$@"
