#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# B 端商家端 h5（`frontend/bmini-app` 的 `build:h5` 产物）静态落位 —— **远端执行体**（issue #5668）
#
# 落位：`app.migaozn.com` 静态根（nginx `root` = `/opt/migao-deploy/h5`）下的 **`b/`** 子树。
#
# 🔴 红线一（与工人端 `w/` 同源）：静态根**同时承载线上 C 端小布 H5**（同一个 root、同一个
#   `location /`）⇒ 本脚本**只允许**清空/覆盖 `<静态根>/<子目录>`（默认 `b/`）子树，
#   **绝不**对静态根本身做 `--delete` / 清空 / `rm -rf`。判定落在 `assert_target_safe()` +
#   `purge_target()`（都在动手之前），并有「发布前后父目录 `index.html` 哈希必须一致」的自证。
#
# 🔴 红线二（**本应用特有**）：产物**必须落在自己的命名空间里**。bmini h5 是 Taro 打出来的
#   SPA，默认 `publicPath: '/'` 时 index.html 引用的是 `/js/app.js`、`/css/app.css` ——
#   与**同静态根下的 C 端小布产物同名同路径**（实测：两端都打成 `js/app.js`）。若把这样一份
#   产物发到 `/b/`，浏览器会在 `/b/` 的页面上加载**C 端的包**：页面"打得开"，跑的是另一个应用。
#   ⇒ `assert_product_scoped()` 在**写入目标之前**逐条检查 index.html 的同源引用，
#      任何一个逃出 `/<子目录>/` 前缀 ⇒ **拒绝发布**（fail-closed，而不是发上去再等人发现）。
#
# ⚠️ 为什么身份判据不能用"页面文案/标题"：实测 `dist/index.html` 的 `<title>` 是
#   「米高窗帘 · 小布智能助手」、且带 `window.TARO_ENV = 'h5'` —— 与 C 端**逐字相同**
#   ⇒ 标记法区分不了这两端。可判的只有 **字节哈希**（本脚本 + CI 侧的 `PUBLISHED_INDEX_SHA256`）
#   与**资源命名空间**（上面那条）。
#
# 用法（本地 / 远端**同一入口**；CLI 参数覆盖环境变量）：
#   # ① 线上（CI 侧注入环境变量后把本文件拼接成 RunCommand 内容）
#   H5_PUBLISH_IMAGE=<registry>/<ns>/bmini-h5:sha-xxxxxxx bash deploy/swas/bmini-h5-publish-remote.sh
#   # ② 本地沙箱复跑（不联网、不碰真实静态根 —— 守卫测试与人工排障）
#   H5_PUBLISH_FROM_DIR=frontend/bmini-app/dist H5_STATIC_ROOT=/tmp/h5-sandbox bash deploy/swas/bmini-h5-publish-remote.sh
#
# 幂等：连跑两次结果逐字节一致（先把目标子树收敛为空，再整份拷入）。
# 退出码：0 = 已发布且自证通过；非零 = **什么都没改 / 已显式失败**（绝不静默半成品）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# 默认值 = 线上真值（`deploy/swas/nginx.conf` 的 `root` + 本单约定的子目录 `b`）。
# ⚠️ 用 `${VAR-default}`（**不是** `${VAR:-default}`）：**显式置空 ⇒ 拒绝**（见 assert_target_safe），
#    而不是「悄悄回落到 b」—— 把空值当默认值会把一个写错的调用变成一次真实发布。
STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${H5_SUBDIR-b}
IMAGE=${H5_PUBLISH_IMAGE:-}
FROM_DIR=${H5_PUBLISH_FROM_DIR:-}
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
      -h|--help)     sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,44p'; exit 0 ;;
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

# ── 取产物到 ${STAGE}（两条等价来源；发布腿走 IMAGE，本地/沙箱走 FROM_DIR）──────
stage_product() {
  mkdir -p "$STAGE"
  if [ -n "$FROM_DIR" ]; then
    [ -d "$FROM_DIR" ] || die "发布源目录不存在：'$FROM_DIR'"
    echo "SOURCE_DIR=${FROM_DIR}"
    cp -R "$FROM_DIR/." "$STAGE/" || die "拷贝发布源失败：'$FROM_DIR'"
    return 0
  fi
  command -v docker >/dev/null 2>&1 \
    || die "实例上没有 docker —— 无法从传输镜像里取出产物（见 deploy/bmini-h5/Dockerfile）"
  echo "SOURCE_IMAGE=${IMAGE}"
  docker pull "$IMAGE" >&2 || die "拉取传输镜像失败：'$IMAGE'（实例是否已 docker login ACR？）"
  local cid
  cid=$(docker create "$IMAGE") || die "创建临时容器失败：'$IMAGE'"
  if ! docker cp "$cid:/dist/." "$STAGE/"; then
    docker rm -f "$cid" >/dev/null 2>&1 || true
    die "从镜像里取产物失败（镜像里没有 /dist？）—— 临时容器已清理"
  fi
  docker rm -f "$cid" >/dev/null || die "清理临时容器失败：'$cid'（实例上可能残留一个已停止容器）"
  return 0
}

# ── 产物身份断言（**在写入目标之前**，fail-closed）──────────────────────────
# ① 同源引用必须全部落在 `/<子目录>/` 前缀内（否则 = 与同根下的 C 端共用命名空间 ⇒ 静默串端）；
# ② index.html 引用的资源必须真的在产物里（防「只发了 index」的半成品）。
assert_product_scoped() {
  [ -f "$STAGE/index.html" ] || die "产物里没有 index.html（发布源不是 build:h5 的 dist/？）"
  local refs out_of_scope="" missing=0 r rel
  # 只取 `src="..."` / `href="..."` 的字面值（产物是 webpack 生成的静态 HTML，形态稳定）
  refs=$(grep -oE '(src|href)="[^"]*"' "$STAGE/index.html" | sed -E 's/^(src|href)="//; s/"$//' || true)
  [ -n "$refs" ] || die "index.html 里没有任何 src/href —— 产物不完整，拒绝发布"
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    case "$r" in
      # 协议绝对 / 协议相对 / data: URI —— 不是同源相对引用，不受本前缀约束（也**不**做存在性检查）
      *"://"*|"//"*|data:*) continue ;;
      "/$SUBDIR/"*) : ;;
      *) out_of_scope="${out_of_scope} ${r}" ;;
    esac
  done <<< "$refs"
  [ -z "$out_of_scope" ] \
    || die "index.html 引用了本应用命名空间（/${SUBDIR}/）之外的资源：${out_of_scope} —— 这是「与同静态根下的 C 端小布共用路径」的串端形态，拒绝发布（构建时须传 TARO_APP_H5_PUBLIC_PATH=/${SUBDIR}/）"
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    case "$r" in
      *"://"*|"//"*|data:*) continue ;;
    esac
    rel="${r#/$SUBDIR/}"
    if [ ! -f "$STAGE/$rel" ]; then
      echo "  ⚠️ index.html 引用了产物里不存在的文件：${r}"
      missing=$(( missing + 1 ))
    fi
  done <<< "$refs"
  [ "$missing" -eq 0 ] || die "index.html 引用了 ${missing} 个产物里不存在的文件（半成品：只发了 index？）"
  echo "ASSET_REFS_SCOPED=1"
  echo "ASSETS_PRESENT=1"
}

main() {
  parse_args "$@"
  assert_target_safe

  [ -n "$FROM_DIR" ] || [ -n "$IMAGE" ] || die "必须给 H5_PUBLISH_FROM_DIR（本地目录）或 H5_PUBLISH_IMAGE（传输镜像）"

  WORK=$(mktemp -d)
  STAGE="$WORK/stage"
  # 注意：清掉的是**自己刚建的临时目录**，与静态根无关（唯一一处 rm -rf，参数不含任何静态根变量）
  trap 'rm -rf "$WORK"' EXIT

  stage_product
  assert_product_scoped

  PARENT_BEFORE="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"

  mkdir -p "$TARGET"
  purge_target
  cp -R "$STAGE/." "$TARGET/"

  PARENT_AFTER="$(file_sha256_or_absent "$STATIC_ROOT/index.html")"
  local staged published file_count
  staged="$(file_sha256 "$STAGE/index.html")"
  published="$(file_sha256 "$TARGET/index.html")"
  file_count="$(find "$TARGET" -type f | wc -l | tr -d ' ')"

  echo "TARGET=$TARGET"
  echo "PARENT_INDEX_BEFORE_SHA256=$PARENT_BEFORE"
  echo "PARENT_INDEX_AFTER_SHA256=$PARENT_AFTER"
  echo "PUBLISHED_INDEX_SHA256=$published"
  echo "STAGED_INDEX_SHA256=$staged"
  echo "PUBLISHED_FILE_COUNT=$file_count"
  echo "PUBLISHED_FILES_BEGIN"
  ( cd "$TARGET" && find . -type f | sort | sed 's/^/  /' )
  echo "PUBLISHED_FILES_END"

  [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] || die "红线被破坏：静态根的 index.html 在发布前后不一致"
  [ "$published" = "$staged" ] || die "发布后的 index.html 与暂存产物不一致（拷贝过程出问题？）"
  echo "✅ 已发布 ${TARGET}（${file_count} 个文件；父目录 index.html 未被触碰：${PARENT_AFTER}）"
}

main "$@"
