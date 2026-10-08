#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# C 端元元 H5（`frontend/mini-app` 的 `build:h5` 产物）静态落位 —— **远端执行体**（issue #4184）
#
# 落位：`app.migaozn.com` 的**静态根本身**（nginx `root` = `/opt/migao-deploy/h5`，
# 见 `deploy/swas/nginx.conf` 的 `server_name app.migaozn.com` 段）——
# 这是**第一条「拥有静态根本身」的发布腿**：此前 `w/`（工人端，#4837）与 `b/`（商家端，#5668）
# 两条腿都只收敛自己的**子目录**，从未有人往根上发。
#
# 🔴 红线一（与 `deploy/swas/h5-publish-remote.sh` 头部同源）：**绝不能删静态根**。
#   本脚本**只删/只替换「上一次由本脚本登记过的顶层条目」**：
#     · `assert_target_safe()` 拒绝 `/`、拒绝软链、拒绝相对路径、拒绝以 `/` 结尾、拒绝不存在的根；
#     · 删除集 = 上一次发布写下的清单（`managed_top_level`）**∩** 磁盘现值 ⇒ 首次发布（无清单）
#       删除集恒为空 —— 连根上的 `index.html` 都不删（见下面的 `TAKEOVER_REQUIRED`）。
#   ⇒ 「把根清空」这条路在结构上不存在（不是靠注释承诺，`tests/unit_ci_workflows/test_c_end_h5_hosting.py`
#      有沙箱红证：预置根内容 ⇒ 跑发布 ⇒ 清单外的条目逐字节不变）。
#
# 🔴 红线二（**本腿特有，也是本单最危险的一处**）：静态根下**已经住着两条腿的产物** ——
#   `w/`（工人端，线上有工人在用）与 `b/`（商家端）。它们**不是**本脚本的托管物，
#   本脚本对它们的全部动作 = **一个字节都不动**。判据三层：
#     ① 结构层：`w` `b` 是**保留前缀**（`H5_RESERVED_PREFIXES`）—— 既不许进产物顶层条目，
#        也不许进托管清单（进了就 die），更不可能进删除集；
#     ② 产物层：本腿自己的 `index.html` **不许引用** `/<保留前缀>/…`（引用了就是「C 端页面加载
#        别的应用的包」= 串端）；`assert_no_reserved_refs()` 在**写入任何东西之前**判；
#     ③ 自证层：发布前后逐子树算**规范化摘要**（相对路径 + 文件 sha256，按行排序后再 sha256 ——
#        不吃 mtime/uid/顺序），并另打 `w/index.html` / `b/index.html` 的单文件哈希 ⇒
#        `PROTECTED_<p>_BEFORE_SHA256` / `..._AFTER_SHA256` 读数为证（不是注释承诺）。
#        ⚠️ tar 的字节流**不算证**（含 mtime/uid/顺序，同一份内容可打包出不同字节 ⇒ 假绿）。
#
# ⚠️ 为什么必须有「接管开关」（首次发布的真实形态，**本单不代替人做这个决定**）：
#   线上根的现值（实测 2026-09-27：`index.html` + `js/` + `css/`，`Last-Modified` = 08-30）
#   是**历史上某次发布**留下的，**没有任何清单说明它由谁托管**。本脚本不接管「无人认领的根」——
#   它要求调用方**显式** `--takeover-first-publish`，否则**拒绝发布（exit 2）并打印将要替换的条目**
#   （先 `--dry-run` 看清，再决定）。⇒「第一次接管线上根」是一个**有人签字**的动作。
#
# 用法（本地 / 远端**同一入口**；CLI 参数覆盖环境变量）：
#   # ① 线上（CI 侧只注入环境变量后把本文件拼接成 RunCommand 内容）
#   H5_PUBLISH_SHA=<40 位 sha> H5_TAKEOVER_FIRST_PUBLISH=1 bash deploy/swas/c-end-h5-publish-remote.sh --apply
#   # ② 本地沙箱复跑 / 人工排障（**默认 dry-run**：只打印计划，什么都不改）
#   H5_STATIC_ROOT=/tmp/h5-sandbox bash deploy/swas/c-end-h5-publish-remote.sh --from-dir frontend/mini-app/dist
#
# 退出码：0 = 已发布（或 dry-run 完成计划）且自证通过；非零 = **什么都没改 / 已显式失败**：
#   1 = 环境/参数错；2 = 需要 `--takeover-first-publish`（拒绝接管无人认领的根）；3 = 目标/产物守卫拒绝。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
shopt -s nullglob   # 暂存区没有点文件时 `stage/.[!.]*` 展开为空（不是字面量，也不让循环空转）

# 默认值 = 线上真值（`deploy/swas/nginx.conf` 里 `app.migaozn.com` 的 `root`）。
# ⚠️ `${VAR-default}`（**不是** `${VAR:-default}`）：显式置空 ⇒ 拒绝（见 assert_target_safe），
#    而不是「悄悄回落到线上路径」—— 把空值当默认值会把一次写错的调用变成一次真实发布。
STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
REPO=${H5_REPO:-zhaokai-mgzn/migao}
SRC_SUBPATH=${H5_SRC_SUBPATH:-frontend/mini-app}
SHA=${H5_PUBLISH_SHA:-}
FROM_DIR=${H5_PUBLISH_FROM_DIR:-}
# 产出这份 dist 的**源码 commit**（只写进托管清单，不参与取回 —— 取回用的是 `SHA`）。
PUBLISHED_COMMIT=${H5_PUBLISHED_COMMIT:-}
MANIFEST=${H5_MANIFEST-.migao-c-end-h5-manifest.json}
# 保留前缀（**本腿不许碰的子树**）：工人端 `w/`（#4837，线上有工人在用）与商家端 `b/`（#5668）
RESERVED_PREFIXES=${H5_RESERVED_PREFIXES:-"w b"}
# 首次发布接管开关（空 = 不收管无人认领的根 ⇒ 拒绝并打印将要替换的条目）
TAKEOVER=${H5_TAKEOVER_FIRST_PUBLISH:-}
APPLY=0
TARGET=""
WORK=""
BACKUP=""
MANAGED=""; NEW=""; REPLACE=""; DELETE=""; UNCLAIMED=""
PROTECTED_BEFORE=""; PROTECTED_AFTER=""

# die <消息> [<退出码>]（退出码：1 参数/环境错 · 2 需接管开关 · 3 目标/产物守卫拒绝）
die() { local msg=$1 code=${2:-1}; printf '❌ %s\n' "$msg" >&2; exit "$code"; }

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

stream_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
}

# 子树的**规范化摘要**：逐文件「相对路径 + sha256」排序后取 sha256。只吃**路径与内容**
# （不吃 mtime/uid/顺序）⇒ 逐字可复算，且「不变」是真的不变。
subtree_digest() {
  local dir=$1
  [ -d "$dir" ] || { echo "(absent)"; return 0; }
  ( cd "$dir" && find . -type f -print0 | sort -z | while IFS= read -r -d '' f; do
      printf '%s  %s\n' "${f#./}" "$(file_sha256 "$f")"
    done ) | stream_sha256 | awk '{print $1}'
}

# 采集保留前缀的读数（**发布前**一次、**发布后**一次），把结果存进 `PROTECTED_BEFORE/AFTER`
# 并同时打进输出（CI 侧逐字比对）。存变量是为了自查时**读的是采集当时的读数**，
# 而不是「再算一遍现值 ⇒ 与自己恒等」那种空断言。
collect_protected_readings() {
  local phase=$1 p d
  local out=""
  for p in $RESERVED_PREFIXES; do
    d="$(subtree_digest "$STATIC_ROOT/$p")"
    out="${out}${p}=${d}"$'\n'
    echo "PROTECTED_${p}_${phase}_SHA256=${d}"
    echo "PROTECTED_${p}_${phase}_INDEX_SHA256=$(file_sha256_or_absent "$STATIC_ROOT/$p/index.html")"
  done
  if [ "$phase" = "BEFORE" ]; then PROTECTED_BEFORE="$out"; else PROTECTED_AFTER="$out"; fi
}

is_reserved() {
  local name=$1 p
  for p in $RESERVED_PREFIXES; do [ "$name" = "$p" ] && return 0; done
  return 1
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply)           APPLY=1; shift ;;
      --dry-run)         APPLY=0; shift ;;
      --from-dir)        FROM_DIR=${2:-}; shift 2 ;;
      --sha)             SHA=${2:-}; shift 2 ;;
      --static-root)     STATIC_ROOT=${2:-}; shift 2 ;;
      --repo)            REPO=${2:-}; shift 2 ;;
      --src-subpath)     SRC_SUBPATH=${2:-}; shift 2 ;;
      --takeover-first-publish) TAKEOVER=1; shift ;;
      -h|--help)         sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,52p'; exit 0 ;;
      *)                 die "未知参数：$1（-h 看用法）" ;;
    esac
  done
}

# ── 目标守卫（fail-closed，**在创建/清理任何东西之前**）───────────────────────
# 本腿的 TARGET **就是**静态根本身（与 `w/` `b/` 两条腿相反）⇒ 这里的判据是
# 「这个根**是不是**我们要接管的那个根、它的边界可不可判定（软链 ⇒ 不可判定 ⇒ 拒绝）」。
assert_target_safe() {
  case "$STATIC_ROOT" in
    /*) : ;;
    *) die "静态根必须是绝对路径：'$STATIC_ROOT'" ;;
  esac
  [ "$STATIC_ROOT" != "/" ] || die "静态根不能是 /（拒绝在根目录上工作）"
  case "$STATIC_ROOT" in
    */) die "静态根不能以 / 结尾：'$STATIC_ROOT'（本腿目标 = 根本身，路径必须规范化）" ;;
  esac
  [ ! -L "$STATIC_ROOT" ] || die "静态根是软链：'$STATIC_ROOT' ⇒ 拒绝（「我发到哪里」必须可判定）"
  [ -d "$STATIC_ROOT" ] || die "静态根不存在：'$STATIC_ROOT'（路径写错时**宁可红**，不新建目录）"
  case "$MANIFEST" in
    ""|/*|*/*|.|..) die "清单名必须是静态根下的单一普通文件名（不接受空/绝对路径/含斜杠/\`.\`/\`..\`）：'$MANIFEST'" ;;
  esac
  TARGET="$STATIC_ROOT"
}

# ── 取产物（两条等价来源；发布腿走 SHA，本地/沙箱走 FROM_DIR）──────────────────
stage_product() {
  local src
  mkdir -p "$WORK/stage"
  if [ -n "$FROM_DIR" ]; then
    [ -d "$FROM_DIR" ] || die "发布源目录不存在：'$FROM_DIR'"
    src="$FROM_DIR"
    echo "SOURCE_DIR=${src}（本地目录直达，不联网）"
  else
    case "$SHA" in
      ''|*[!0-9a-fA-F]*) die "SHA 非法：'$SHA'（只接受十六进制 commit sha）" ;;
    esac
    [ "${#SHA}" -ge 7 ] || die "SHA 太短：'$SHA'"
    local url="https://codeload.github.com/$REPO/tar.gz/$SHA"
    echo "SOURCE_URL=$url"
    # 与 `deploy/scripts/swas-h5-publish-ci.sh` 同一条通道（实测：服务器走 codeload 可达，
    # raw.githubusercontent.com 在杭州机房超时）
    curl -fsSL --retry 3 --retry-delay 2 "$url" -o "$WORK/src.tgz" || die "下载源码失败：$url"
    mkdir -p "$WORK/unpack"
    tar xzf "$WORK/src.tgz" -C "$WORK/unpack" --strip-components=1 || die "解包失败"
    src="$WORK/unpack/$SRC_SUBPATH"
  fi
  [ -f "$src/index.html" ] || die "发布源里没有 index.html：'$src'（不是 build:h5 的 dist/？）"
  cp -R "$src/." "$WORK/stage/" || die "拷贝发布源到暂存区失败：'$src'"
}

# ── 产物守卫（**在写入目标之前**，fail-closed）────────────────────────────────
# C 端产物是**根级**产物（Taro `h5.publicPath: '/'` ⇒ `/js/app.js` `/css/app.css`）⇒
# 它的同源引用**必须**落在静态根的根级，**不许**落在 `w/` `b/` 这些保留前缀里。
# 落在保留前缀里 = 「C 端页面加载别的应用的包」= 串端（`/b/` 那条腿的 `assert_product_scoped`
# 是这条判据的**镜像**：那边要求引用**只**落在 `/b/` 内）。
assert_no_reserved_refs() {
  local refs out="" r p
  refs=$(grep -oE '(src|href)="[^"]*"' "$WORK/stage/index.html" | sed -E 's/^(src|href)="//; s/"$//' || true)
  [ -n "$refs" ] || die "产物 index.html 里没有任何 src/href —— 产物不完整，拒绝发布" 3
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    case "$r" in
      *"://"*|"//"*|data:*) continue ;;   # 协议绝对 / 协议相对 / data: URI：不是同源相对引用
      /*) : ;;
      *) die "产物 index.html 引用了**相对路径** '${r}' —— C 端产物必须用根级绝对路径（publicPath='/'），拒绝发布" 3 ;;
    esac
    for p in $RESERVED_PREFIXES; do
      case "$r" in
        "/$p/"*|"/$p") out="${out} ${r}" ;;
      esac
    done
  done <<< "$refs"
  [ -z "$out" ] || die "产物 index.html 引用了**别的应用**的命名空间：${out} —— 发布后 C 端页面会加载该应用的包（串端），拒绝发布" 3
  echo "ASSET_REFS_ROOT_SCOPED=1"
}

# ── 托管清单：只认上一次**本脚本自己**写下的顶层条目 ───────────────────────────
manifest_path() { echo "$STATIC_ROOT/$MANIFEST"; }

load_managed() {
  local mf; mf="$(manifest_path)"
  MANAGED=""
  [ -f "$mf" ] || return 0
  MANAGED=$(python3 - "$mf" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    managed = data.get("managed_top_level") or []
    if not isinstance(managed, list):
        raise ValueError("managed_top_level 不是数组")
except Exception as exc:            # 清单读不出来 ⇒ 宁可红，不猜（拒绝在不可判的托管集上删除）
    sys.stderr.write("manifest-unreadable: %s\n" % exc)
    sys.exit(1)
sys.stdout.write(" ".join(str(x) for x in managed))
PY
) || die "清单存在但读不出来：${mf}（拒绝在不可判的托管集上做删除）"
  echo "MANAGED_TOP_LEVEL_FROM_MANIFEST=${MANAGED:-（空）}"
}

# 本次发布的顶层条目 = 暂存区里除清单文件外的全部顶层项。
# 拒绝任何落在保留前缀里的条目（红线二的结构层）。
compute_new_top_level() {
  local path name
  NEW=""
  for path in "$WORK"/stage/* "$WORK"/stage/.[!.]*; do
    [ -e "$path" ] || continue
    name="$(basename "$path")"
    [ "$name" = "$MANIFEST" ] && continue
    is_reserved "$name" && die "产物里出现保留前缀 '${name}/'（该子树属于别的发布腿：${RESERVED_PREFIXES}）—— 拒绝发布" 3
    NEW="${NEW} ${name}"
  done
  NEW="${NEW# }"
  [ -n "$NEW" ] || die "产物里没有任何顶层条目（暂存区是空的？）—— 拒绝发布" 3
  echo "MANAGED_TOP_LEVEL_NEW=${NEW}"
}

# 需要替换 / 需要删除 / 无人认领的集合。
# ⚠️ 删除集 = **上一次清单 ∩ 磁盘现值**（首次发布无清单 ⇒ 空集）⇒「清空静态根」不可达。
compute_replacement() {
  local name
  REPLACE=""; DELETE=""; UNCLAIMED=""
  for name in $NEW; do
    REPLACE="${REPLACE} ${name}"
    if [ -e "$STATIC_ROOT/$name" ] && ! printf '%s\n' $MANAGED | grep -qx -- "$name"; then
      UNCLAIMED="${UNCLAIMED} ${name}"
    fi
  done
  for name in $MANAGED; do
    is_reserved "$name" && die "清单里出现保留前缀 '${name}' ⇒ 清单被污染（拒绝按它删除）" 3
    case " $NEW " in *" $name "*) continue ;; esac
    DELETE="${DELETE} ${name}"
  done
  REPLACE="${REPLACE# }"; DELETE="${DELETE# }"; UNCLAIMED="${UNCLAIMED# }"
  echo "MANAGED_TOP_LEVEL_REPLACE=${REPLACE:-（空）}"
  echo "MANAGED_TOP_LEVEL_DELETE=${DELETE:-（空）}"
}

planned_actions() {
  local name
  for name in $DELETE; do echo "  · 删除（上一次托管的陈旧条目）：$name"; done
  for name in $REPLACE; do echo "  · 替换：$name"; done
}

# ── 发布（写盘）：先备份 → 再删 → 再拷 → 失败即回滚 ────────────────────────────
# 备份落在**静态根之外**的临时目录（临时物不出现在根里，少一处会被 CDN/nginx 看到的东西）。
apply_publish() {
  local name b rc=0
  mkdir -p "$BACKUP"
  for name in $DELETE $REPLACE; do
    [ -e "$STATIC_ROOT/$name" ] || continue
    cp -R "$STATIC_ROOT/$name" "$BACKUP/$name" || die "备份 '$name' 失败（fail-closed：未做任何删除）"
  done
  for name in $DELETE $REPLACE; do
    [ -e "$STATIC_ROOT/$name" ] || continue
    rm -rf "$STATIC_ROOT/$name" || die "删除陈旧条目失败：'$name'"
  done
  cp -R "$WORK/stage/." "$STATIC_ROOT/" || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "⚠️ 拷贝失败（rc=${rc}）—— 从备份回滚：$BACKUP" >&2
    for b in "$BACKUP"/* "$BACKUP"/.[!.]*; do
      [ -e "$b" ] || continue
      cp -R "$b" "$STATIC_ROOT/" || true
    done
    die "发布失败（已尝试回滚；回滚是否完整见上面输出）"
  fi
}

write_manifest() {
  local mf; mf="$(manifest_path)"
  # `H5_PUBLISHED_COMMIT`（可空）= 产出这份 dist 的**源码 commit**（CI 侧透传；codeload tarball 里
  # 没有 `dist/` ⇒ 远端推不出来）。留空时写空串 —— 不是「拿取回 ref 冒充源码 commit」（#6095 第三层
  # 之后取回 ref 是 dist 的孤儿提交，与源码 commit 不是一回事）。
  python3 - "$mf" "$NEW" "$SHA" "$(file_sha256 "$TARGET/index.html")" "$PUBLISHED_COMMIT" <<'PY'
import datetime, json, os, sys
mf, new, sha, published, published_commit = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
data = {
    "_what": "C 端元元 H5（frontend/mini-app 的 build:h5 产物）在 app.migaozn.com 静态根上的**托管物台账**（issue #4184）。",
    "_why": "发布腿的删除范围 = 本文件的 managed_top_level ∩ 磁盘现值。没有它就没有删除动作（首次发布走 --takeover-first-publish）。",
    "_owner": "deploy/swas/c-end-h5-publish-remote.sh（唯一写者）",
    "managed_top_level": new.split(),
    # ⚠️ **不许**回落到 `sha`（= 产物 ref）：那会把「h5-dist 的孤儿提交」标成「源码 commit」
    #    （#6095 第五层：两个 ref 混用的一族）。没有源码 commit 就照实留空。
    "published_commit": published_commit or "",
    "published_dist_ref": sha or "",
    "published_index_sha256": published,
    "written_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
tmp = mf + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, mf)
PY
  echo "MANIFEST_WRITTEN=$mf"
}

main() {
  parse_args "$@"
  assert_target_safe

  [ -n "$FROM_DIR" ] || [ -n "$SHA" ] || die "必须给 H5_PUBLISH_FROM_DIR（本地目录）或 H5_PUBLISH_SHA（commit sha）"

  WORK="$(mktemp -d)"
  BACKUP="$(mktemp -d)"
  # 注意：清掉的是**自己刚建的两个临时目录**，与静态根无关
  # （唯一一处 rm -rf，参数只含 mktemp 出来的路径，不含任何静态根变量）
  trap 'rm -rf "$WORK" "$BACKUP"' EXIT

  stage_product
  assert_no_reserved_refs

  load_managed
  compute_new_top_level
  compute_replacement

  echo "TARGET=$TARGET"
  echo "TAKEOVER_FIRST_PUBLISH=${TAKEOVER:-（未给）}"
  echo "PROTECTED_PREFIXES=${RESERVED_PREFIXES}"
  collect_protected_readings BEFORE
  echo "PRODUCED_INDEX_SHA256=$(file_sha256 "$WORK/stage/index.html")"
  echo "ROOT_INDEX_BEFORE_SHA256=$(file_sha256_or_absent "$STATIC_ROOT/index.html")"

  if [ -n "$UNCLAIMED" ] && [ -z "$TAKEOVER" ]; then
    echo "PLANNED_ACTIONS_BEGIN"; planned_actions; echo "PLANNED_ACTIONS_END"
    die "静态根上有**无人认领**的既有条目：${UNCLAIMED}
   它们不在本脚本的托管清单里（${MANIFEST}）⇒ 本脚本**不接管**无人认领的根。
   先看清将要被替换的内容（上面的 PLANNED_ACTIONS 就是计划），确认无误后加 --takeover-first-publish 再跑：
     bash deploy/swas/c-end-h5-publish-remote.sh --from-dir <dist> --takeover-first-publish --apply" 2
  fi

  if [ "$APPLY" -eq 0 ]; then
    echo "DRY_RUN=1（默认只打印计划；要真正发布请加 --apply）"
    echo "PLANNED_ACTIONS_BEGIN"; planned_actions; echo "PLANNED_ACTIONS_END"
    echo "PROTECTED_UNCHANGED=not-evaluated（dry-run：什么都没改）"
    echo "✅ dry-run 完成：未做任何修改（TARGET=${TARGET}）"
    return 0
  fi

  apply_publish
  write_manifest

  echo "ROOT_INDEX_AFTER_SHA256=$(file_sha256_or_absent "$STATIC_ROOT/index.html")"
  echo "PUBLISHED_INDEX_SHA256=$(file_sha256 "$STATIC_ROOT/index.html")"
  echo "MANAGED_TOP_LEVEL_FINAL=${NEW}"
  collect_protected_readings AFTER

  # ── 自证（读数为证）────────────────────────────────────────────────────────
  [ "$(file_sha256 "$TARGET/index.html")" = "$(file_sha256 "$WORK/stage/index.html")" ] \
    || die "发布后的 index.html 与暂存产物不一致（拷贝过程出问题？）"
  # 保留子树：比对**发布前采集的读数**与**发布后采集的读数**（两次真实采样，
  # 不是「再算一遍现值 ⇒ 与自己恒等」那种空断言）。
  local p before after
  for p in $RESERVED_PREFIXES; do
    before=$(printf '%s' "$PROTECTED_BEFORE" | sed -n "s/^${p}=//p")
    after=$(printf '%s' "$PROTECTED_AFTER" | sed -n "s/^${p}=//p")
    [ -n "$before" ] && [ "$before" = "$after" ] \
      || die "红线被破坏：保留子树 '$p/' 在发布前后不一致（${before} → ${after}）"
  done
  echo "PROTECTED_UNCHANGED=1"
  echo "✅ 已发布 ${TARGET}（托管顶层：${NEW}；保留子树 ${RESERVED_PREFIXES} 未被触碰）"
}

main "$@"
