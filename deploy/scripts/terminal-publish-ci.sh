#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 观星台终端（Windows EXE / Android APK）发布腿 —— **CI 侧**（issue #8195）
#
# 两个子命令，**同一份实现**覆盖「生成清单」与「发布 + 验收」：
#
#   ① prepare：把**已下载好的**终端仓 Release 目录 → 载荷目录（安装包 + 两份清单）
#      用法: terminal-publish-ci.sh prepare --release-dir DIR --out DIR --tag TAG --version V
#                               --android-version-code N [--notes TEXT] [--published-at YYYY-MM-DD]
#                               [--base-url URL] [--windows-asset NAME] [--android-asset NAME]
#      为什么把「下载」留在 workflow（`gh release download`）而不在这里做：
#      跨仓读权限是**人的动作**（终端仓是 private，需要 `TERMINAL_REPO_TOKEN`），而这里只做
#      「确定性、可离线复算」的活 —— 于是**守卫测试能在沙箱里真跑 prepare**，不必联网。
#
#   ② publish：把载荷装进 ACR 传输镜像，经 SWAS RunCommand 落到静态根下的 `terminal/`，
#      并在**自有输出里**断言「线上字节 == 本地载荷」（状态码 200 不算通过）。
#      用法: terminal-publish-ci.sh publish <INSTANCE_ID> <REGION> <IMAGE_TAG>
#                               --dist-dir DIR --release-tag TAG
#      AK/SK 从 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` 取（省略 ⇒ 走本机 aliyun 配置）。
#
# 通道与既有三条发布腿**同一把钥匙、同一条云 API**（SWAS RunCommand）：**不引入任何新 secret**
# （AK/SK + ACR 凭据都是已有的）。
#
# 🔴 命令内容契约（issue #6095 / #6124；台账 tests/unit_ci_workflows/swas_command_content_legs_ledger.json）：
#    命令内容**只做**「按不可变 sha 从 codeload 取回远端执行体并执行」，**绝不内联**远端脚本；
#    且在**发起云调用之前**在本机断言字节数 < 上限（否则超限只会在云上冒一个 `SDKError 400`）。
#
# 退出码：0 = 已发布且断言全过；非零 = 未发布 / 已发布但与本地载荷不一致（显式失败）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# `TERMINAL_REMOTE_SCRIPT_PATH` = **判据注入夹具用**（生产不带它 ⇒ 走默认路径）。
# 它**不是**后门：远端脚本路径不是安全边界（命令内容才是），且注入只影响**本机**这一侧。
REMOTE_SCRIPT=${TERMINAL_REMOTE_SCRIPT_PATH:-"$ROOT/deploy/swas/terminal-publish-remote.sh"}
STATIC_ROOT=${TERMINAL_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${TERMINAL_SUBDIR-terminal}
DEFAULT_BASE_URL=${TERMINAL_BASE_URL:-https://app.migaozn.com/terminal}

# 与 deploy-frontend.yml / deploy-reconcile.yml 同域同命名空间（**不新增 secret**）
ACR_REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}
ACR_NAMESPACE=${ACR_NAMESPACE:-ai-customer-service}
IMAGE_NAME=${IMAGE_NAME:-terminal-dist}

# 超时参数（**墙钟**上界，不是次数上界；守卫测试调小以免空耗）
PUBLISH_TIMEOUT_SECONDS=${TERMINAL_PUBLISH_TIMEOUT_SECONDS:-300}
CLI_TIMEOUT_SECONDS=${TERMINAL_CLI_TIMEOUT_SECONDS:-60}
POLL_INTERVAL_SECONDS=${TERMINAL_POLL_INTERVAL_SECONDS:-10}

# SWAS RunCommand 的 `CommandContent` 上限（**最保守取值**：官方口径 base64 后 ≤ 16 KB）。
# 出处必须留在活代码行里（判据 4：16 KB 不许是没有出处的魔数）。
COMMAND_CONTENT_LIMIT_BYTES=${TERMINAL_COMMAND_CONTENT_LIMIT_BYTES:-16384}
COMMAND_CONTENT_LIMIT_SOURCE="SWAS Open RunCommand：CommandContent 与自定义参数在 base64 编码后综合长度 ≤ 16 KB —— https://help.aliyun.com/zh/simple-application-server/developer-reference/api-swas-open-2020-06-01-runcommand"

die() { echo "❌ $*" >&2; exit 1; }

usage() {
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,40p'
}

say() {
  echo "$*"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf '%s\n' "$*" >> "$GITHUB_STEP_SUMMARY"; fi
  return 0
}

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# 受 deadline 约束的等待（绝不 sleep 超过剩余预算）
DEADLINE=$(( $(date +%s) + PUBLISH_TIMEOUT_SECONDS ))
nap() {
  local want=$1 left
  left=$(( DEADLINE - $(date +%s) ))
  [ "$left" -lt "$want" ] && want=$left
  if [ "$want" -gt 0 ]; then sleep "$want"; fi
  return 0
}

# 带硬上界的子进程执行（防 CLI 自己挂住 ⇒ 轮询永不返回 ⇒ run 卡在 in_progress 占住并发组）
with_deadline() {
  local secs=$1; shift
  local out_file pid watchdog rc=0
  out_file=$(mktemp)
  "$@" >"$out_file" 2>&1 &
  pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null || true; sleep 2; kill -KILL "$pid" 2>/dev/null || true ) >/dev/null 2>&1 &
  watchdog=$!
  wait "$pid" || rc=$?
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  cat "$out_file" || true
  rm -f "$out_file"
  return "$rc"
}

# aliyun CLI 新版 swas-open 要求 kebab-case，旧版用 CamelCase ⇒ 双兼容
run_cmd() {
  local k=$1 c=$2; shift 2
  local kebab_args=() camel_args=() arg
  for arg in "$@"; do
    case "$arg" in
      --instance-id)     kebab_args+=(--instance-id);     camel_args+=(--InstanceId) ;;
      --region-id)       kebab_args+=(--biz-region-id);   camel_args+=(--RegionId) ;;
      --name)            kebab_args+=(--name);            camel_args+=(--Name) ;;
      --type)            kebab_args+=(--type);            camel_args+=(--Type) ;;
      --timeout)         kebab_args+=(--timeout);         camel_args+=(--Timeout) ;;
      --command-content) kebab_args+=(--command-content); camel_args+=(--CommandContent) ;;
      --invoke-id)       kebab_args+=(--invoke-id);       camel_args+=(--InvokeId) ;;
      *)                 kebab_args+=("$arg");            camel_args+=("$arg") ;;
    esac
  done
  local out1 out2
  out1=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$k" "${kebab_args[@]}") && { echo "$out1"; return 0; }
  if echo "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$c" "${camel_args[@]}") && { echo "$out2"; return 0; }
  fi
  echo "$out1" >&2
  return 1
}

extract_status() {
  python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('InvocationResult') or d;print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo ""
}

# `InvocationResult.Output` 是 **base64**；解不开就原样打印（**绝不吞信息**）
extract_remote_log() {
  python3 - "$1" <<'PY'
import base64, binascii, json, sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    sys.stdout.write(raw); sys.exit(0)
v = data.get("InvocationResult") if isinstance(data, dict) else None
v = v if isinstance(v, dict) else (data if isinstance(data, dict) else {})
out = v.get("Output") if isinstance(v.get("Output"), str) else None
if out is None:
    sys.stdout.write(raw); sys.exit(0)
try:
    sys.stdout.write(base64.b64decode(out.strip(), validate=True).decode("utf-8", "replace"))
except (binascii.Error, ValueError):
    sys.stdout.write(out)
PY
}

if [ $# -lt 1 ]; then usage >&2; exit 2; fi
MODE=$1
shift

case "$MODE" in
# ══════════════════════════════════════════════════════════════════════════════
prepare)
  RELEASE_DIR=""; OUT=""; TAG=""; VERSION=""; VERSION_CODE=""
  NOTES=""; PUBLISHED_AT=""; BASE_URL="$DEFAULT_BASE_URL"; WIN_ASSET=""; APK_ASSET=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --release-dir)          RELEASE_DIR=${2:-}; shift 2 ;;
      --out)                  OUT=${2:-}; shift 2 ;;
      --tag)                  TAG=${2:-}; shift 2 ;;
      --version)              VERSION=${2:-}; shift 2 ;;
      --android-version-code) VERSION_CODE=${2:-}; shift 2 ;;
      --notes)                NOTES=${2:-}; shift 2 ;;
      --published-at)         PUBLISHED_AT=${2:-}; shift 2 ;;
      --base-url)             BASE_URL=${2:-}; shift 2 ;;
      --windows-asset)        WIN_ASSET=${2:-}; shift 2 ;;
      --android-asset)        APK_ASSET=${2:-}; shift 2 ;;
      -h|--help)              usage; exit 0 ;;
      *)                      die "prepare：未知参数 $1" ;;
    esac
  done

  [ -n "$RELEASE_DIR" ] || die "prepare 需要 --release-dir（已下载的终端仓 Release 目录）"
  [ -d "$RELEASE_DIR" ] || die "release 目录不存在：'$RELEASE_DIR'"
  [ -n "$OUT" ] || die "prepare 需要 --out（载荷输出目录）"
  [ -n "$TAG" ] || die "prepare 需要 --tag（终端仓 Release tag，例如 terminal-v1.0.1）"
  [ -n "$VERSION" ] || die "prepare 需要 --version（Windows 版本，与 ProductVersion 同形，如 1.0.1.0）"
  [ -n "$VERSION_CODE" ] || die "prepare 需要 --android-version-code（Android 更新只按 versionCode 单调比较，不许猜）"
  PUBLISHED_AT=${PUBLISHED_AT:-$(date -u +%F)}
  NOTES=${NOTES:-"$TAG"}

  # 字符集白名单（**注入防线**：这些值会进 JSON 与远端命令内容）。
  # ⚠️ 判据写**否定类**（`*[!允许集]*`）而不是「正向类 + `*`」—— 后者只要串首合法、串尾落在允许集内
  #    就会匹配成功（`/tmp/er;rm -rf/` 也能过）⇒ 那是**假校验**。
  case "$TAG" in *[!A-Za-z0-9._-]*) die "tag 含非法字符：'$TAG'（白名单 [A-Za-z0-9._-]）" ;; esac
  case "$VERSION" in *[!A-Za-z0-9._-]*) die "version 含非法字符：'$VERSION'" ;; esac
  case "$VERSION_CODE" in *[!0-9]*) die "android-version-code 必须是整数：'$VERSION_CODE'" ;; esac
  case "$PUBLISHED_AT" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) : ;;
    *) die "published-at 必须是 YYYY-MM-DD：'$PUBLISHED_AT'" ;;
  esac
  case "$BASE_URL" in https://*) : ;; *) die "base-url 必须是 https 绝对地址：'$BASE_URL'" ;; esac
  case "$BASE_URL" in *[!A-Za-z0-9._:/-]*) die "base-url 含非法字符：'$BASE_URL'" ;; esac
  case "$BASE_URL" in */) die "base-url 结尾不要带斜杠：'$BASE_URL'" ;; esac

  # 资产名可以显式给（终端仓将来改命名也不用改脚本）；不给就按扩展名**恰好一个**地发现。
  discover_asset() {
    local pattern=$1 label=$2 found count
    found=$(cd "$RELEASE_DIR" && find . -maxdepth 1 -type f -name "$pattern" | sed 's|^\./||' | sort)
    if [ -z "$found" ]; then
      die "${label}：release 目录里没有匹配 '$pattern' 的文件（现有：$(cd "$RELEASE_DIR" && find . -maxdepth 1 -type f | sed 's|^\./||' | sort | tr '\n' ' ')）"
    fi
    count=$(printf '%s\n' "$found" | grep -c . || true)
    if [ "$count" != "1" ]; then
      die "${label}：release 目录里匹配 '$pattern' 的文件有 ${count} 个（用 --windows-asset / --android-asset 指定）：
$(printf '%s\n' "$found" | sed 's/^/  /')"
    fi
    printf '%s\n' "$found" | head -1
  }
  [ -n "$WIN_ASSET" ] || WIN_ASSET=$(discover_asset '*.exe' 'Windows 安装包')
  [ -n "$APK_ASSET" ] || APK_ASSET=$(discover_asset '*.apk' 'Android 安装包')

  mkdir -p "$OUT"
  python3 - "$RELEASE_DIR" "$OUT" "$TAG" "$VERSION" "$VERSION_CODE" "$NOTES" "$PUBLISHED_AT" "$BASE_URL" "$WIN_ASSET" "$APK_ASSET" <<'PY'
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

release = Path(sys.argv[1])
out = Path(sys.argv[2])
tag, version, version_code, notes, published_at, base_url, win_name, apk_name = sys.argv[3:11]


def fail(message):
    sys.stdout.flush()
    sys.exit(f"❌ {message}")


def sha256_of(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", version):
    fail(f"version 必须是 1.0.1 或 1.0.1.0 形态（终端按字符串比较 ProductVersion）：'{version}'")
if not version_code.isdigit() or int(version_code) <= 0:
    fail(f"android-version-code 必须是正整数：'{version_code}'")
if not re.fullmatch(r"https://[^\s]+", base_url):
    fail(f"base-url 必须是 https 绝对地址：'{base_url}'")

# Android 的 `versionName` 给人看：`1.0.1.0` 去掉末位平台号 ⇒ `1.0.1`。
version_name = version[:-2] if re.fullmatch(r"\d+\.\d+\.\d+\.0", version) else version

out.mkdir(parents=True, exist_ok=True)
# 载荷目录是**本次构建独占**的：先清掉上一次的发布面文件（避免旧版本的安装包被一起搬上线）。
for stale in list(out.iterdir()):
    if stale.is_file() and (stale.suffix in {".exe", ".apk"} or stale.name in {"latest.json", "latest-android.json"}):
        stale.unlink()

payload = {}
for name in (win_name, apk_name):
    src = release / name
    if src.is_symlink():
        fail(f"载荷不许是符号链接：{src}")
    if not src.is_file():
        fail(f"release 目录缺文件：{src}")
    dst = out / name
    shutil.copyfile(src, dst)
    payload[name] = dst

windows = {
    "version": version,
    "download_url": f"{base_url}/{win_name}",
    "sha256": sha256_of(payload[win_name]),
    "size": payload[win_name].stat().st_size,
    "notes": notes,
    "published_at": published_at,
}
android = {
    "versionCode": int(version_code),
    "versionName": version_name,
    "download_url": f"{base_url}/{apk_name}",
    "sha256": sha256_of(payload[apk_name]),
    "size": payload[apk_name].stat().st_size,
    "notes": notes,
    "published_at": published_at,
}

latest_path = out / "latest.json"
android_path = out / "latest-android.json"
latest_path.write_text(json.dumps(windows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
android_path.write_text(json.dumps(android, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def need(obj, key, kind, label):
    value = obj.get(key)
    if not isinstance(value, kind) or isinstance(value, bool):
        fail(f"{label} 清单的 {key} 不是 {kind.__name__}：{value!r}")

# 逐条回读 —— 口径就是**终端客户端的读法**（`Program.cs` / `Updater.java`）：
# Windows 读 version / notes / download_url（字符串比较）；Android 读 versionCode(int) + versionName + download_url。
for label, path in (("Windows", latest_path), ("Android", android_path)):
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("download_url", "sha256", "size", "notes", "published_at"):
        need(data, key, str if key != "size" else int, label)
    if not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
        fail(f"{label} 清单的 sha256 不是 64 位十六进制：{data['sha256']!r}")
    if not data["download_url"].startswith("https://") or not data["download_url"].endswith("/" + Path(data["download_url"]).name):
        fail(f"{label} 清单的 download_url 形态不对：{data['download_url']!r}")
    asset = out / Path(data["download_url"]).name
    if not asset.is_file():
        fail(f"{label} 清单指向的文件不在载荷里：{asset.name}")
    if sha256_of(asset) != data["sha256"] or asset.stat().st_size != data["size"]:
        fail(f"{label} 清单与载荷不一致（sha256 / size）—— 生成器写坏了？")

need(json.loads(latest_path.read_text(encoding="utf-8")), "version", str, "Windows")
need(json.loads(android_path.read_text(encoding="utf-8")), "versionCode", int, "Android")

print("PREPARE_OK")
print(f"DIST_DIR={out}")
print(f"RELEASE_TAG={tag}")
print(f"WINDOWS_ASSET={win_name}")
print(f"ANDROID_ASSET={apk_name}")
print(f"VERSION={version}")
print(f"ANDROID_VERSION_CODE={int(version_code)}")
print(f"ANDROID_VERSION_NAME={version_name}")
print(f"LATEST_SHA256={sha256_of(latest_path)}")
print(f"ANDROID_LATEST_SHA256={sha256_of(android_path)}")
PY
  ;;

# ══════════════════════════════════════════════════════════════════════════════
publish)
  [ $# -ge 3 ] || die "用法: terminal-publish-ci.sh publish <INSTANCE_ID> <REGION> <IMAGE_TAG> --dist-dir DIR --release-tag TAG"
  INSTANCE_ID=$1
  REGION=$2
  IMAGE_TAG=$3
  shift 3
  DIST_DIR=""; RELEASE_TAG=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dist-dir)    DIST_DIR=${2:-}; shift 2 ;;
      --release-tag) RELEASE_TAG=${2:-}; shift 2 ;;
      -h|--help)     usage; exit 0 ;;
      *)             die "publish：未知参数 $1" ;;
    esac
  done

  AK=${ALIYUN_ACCESS_KEY_ID:-}
  SK=${ALIYUN_ACCESS_KEY_SECRET:-}

  # ── 前置校验（在**发起任何云调用之前**）─────────────────────────────────
  [ -f "$REMOTE_SCRIPT" ] || die "远端执行体缺失：$REMOTE_SCRIPT"
  [ -n "$DIST_DIR" ] || die "publish 需要 --dist-dir（prepare 生成的载荷目录；身份断言以它为准）"
  [ -d "$DIST_DIR" ] || die "载荷目录不存在：'$DIST_DIR'"
  LOCAL_LATEST="$DIST_DIR/latest.json"
  LOCAL_ANDROID="$DIST_DIR/latest-android.json"
  [ -f "$LOCAL_LATEST" ] || die "载荷里没有 latest.json —— 先跑 prepare（发布内容单一源）：$LOCAL_LATEST"
  [ -f "$LOCAL_ANDROID" ] || die "载荷里没有 latest-android.json —— 先跑 prepare：$LOCAL_ANDROID"
  [ -n "$RELEASE_TAG" ] || die "publish 需要 --release-tag（发布自证要写清发的是哪一版）"
  [ -n "$INSTANCE_ID" ] || die "缺少 SWAS 实例 ID"
  [ -n "$REGION" ] || die "缺少地域"
  [ -n "$IMAGE_TAG" ] || die "缺少镜像 tag（不可变引用；按 latest 取会让「发布的是哪一次构建」不可判定）"

  case "$STATIC_ROOT" in
    /*) : ;;
    *) die "TERMINAL_STATIC_ROOT 必须是绝对路径：'$STATIC_ROOT'" ;;
  esac
  case "$STATIC_ROOT" in *[!A-Za-z0-9._/-]*) die "TERMINAL_STATIC_ROOT 含非法字符：'$STATIC_ROOT'" ;; esac
  case "$SUBDIR" in ""|*/*|*[!A-Za-z0-9._-]*) die "TERMINAL_SUBDIR 非法：'$SUBDIR'（单一组件，白名单 [A-Za-z0-9._-]）" ;; esac
  case "$ACR_REGISTRY" in ""|*[!A-Za-z0-9._:/-]*) die "ACR_REGISTRY 非法：'$ACR_REGISTRY'" ;; esac
  case "$ACR_NAMESPACE" in ""|*[!A-Za-z0-9._/-]*) die "ACR_NAMESPACE 非法：'$ACR_NAMESPACE'" ;; esac
  case "$IMAGE_NAME" in ""|*[!A-Za-z0-9._-]*) die "IMAGE_NAME 非法：'$IMAGE_NAME'" ;; esac
  case "$IMAGE_TAG" in *[!A-Za-z0-9._-]*) die "IMAGE_TAG 非法：'$IMAGE_TAG'（只接受 [A-Za-z0-9._-]）" ;; esac
  case "$RELEASE_TAG" in *[!A-Za-z0-9._-]*) die "release-tag 含非法字符：'$RELEASE_TAG'" ;; esac

  # 🔴 **执行体 ref**：引导**按它**从 codeload 取回 `deploy/swas/terminal-publish-remote.sh` 并执行
  #    ⇒ 远端执行的那份 == 本次 CI 审过的 commit（取 main 的最新会漂移）。
  SCRIPT_SHA=${TERMINAL_PUBLISHED_COMMIT:-${GITHUB_SHA:-}}
  case "$SCRIPT_SHA" in
    "") die "执行体 ref 为空：请给 TERMINAL_PUBLISHED_COMMIT（CI 里 = github.sha）或 GITHUB_SHA" ;;
    *[!0-9a-fA-F]*) die "执行体 ref 非法：'$SCRIPT_SHA'（只接受十六进制 sha；它会被拼进 codeload URL）" ;;
  esac
  [ "${#SCRIPT_SHA}" -eq 40 ] || die "执行体 ref 必须是 40 位十六进制 commit sha，实际 '$SCRIPT_SHA'（长度 ${#SCRIPT_SHA}）"

  EXPECTED_TARGET="$STATIC_ROOT/$SUBDIR"
  IMAGE="$ACR_REGISTRY/$ACR_NAMESPACE/$IMAGE_NAME:$IMAGE_TAG"
  LOCAL_LATEST_SHA="$(file_sha256 "$LOCAL_LATEST")"
  LOCAL_ANDROID_SHA="$(file_sha256 "$LOCAL_ANDROID")"

  # 「清单 ⇄ 载荷」自检（与远端 `assert_payload_complete` 同口径、同一组判据）：
  # 不一致在**发起云调用之前**就红，而不是发到线上再等终端报「校验失败」。
  python3 - "$DIST_DIR" <<'PY' || exit 1
import hashlib
import json
import sys
from pathlib import Path

dist = Path(sys.argv[1])
problems = []
for label, name in (("Windows", "latest.json"), ("Android", "latest-android.json")):
    path = dist / name
    if not path.is_file():
        problems.append(f"{label} 清单缺失：{path}")
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        problems.append(f"{label} 清单不是合法 JSON：{exc}")
        continue
    url = data.get("download_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        problems.append(f"{label} 清单的 download_url 不是 https 绝对地址：{url!r}")
        continue
    asset = dist / Path(url).name
    if not asset.is_file():
        problems.append(f"{label} 清单指向的文件不在载荷里：{asset.name}")
        continue
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    if digest != data.get("sha256"):
        problems.append(f"{label} 清单的 sha256 与载荷不一致：清单 {data.get('sha256')!r} ≠ 实际 {digest}")
    if asset.stat().st_size != data.get("size"):
        problems.append(f"{label} 清单的 size 与载荷不一致：清单 {data.get('size')!r} ≠ 实际 {asset.stat().st_size}")
if problems:
    sys.exit("❌ 载荷与清单不一致：\n  - " + "\n  - ".join(problems))
print("✅ 本地清单与载荷一致（%s）" % dist)
PY

  say "# 观星台终端静态落位（issue #8195）"
  say ""
  say "- 目标：\`$EXPECTED_TARGET\`（静态根 = nginx 的 \`root\`，**同时承载 C 端元元 ⇒ 只收敛 $SUBDIR/ 子树**）"
  say "- 版本：\`$RELEASE_TAG\`"
  say "- 传输：ACR 镜像 \`$IMAGE\`（实例 \`docker cp\` 取出 /dist ⇒ 线上字节 == Release 里的字节）"
  say "- 本地 \`latest.json\` 哈希：\`$LOCAL_LATEST_SHA\`；\`latest-android.json\` 哈希：\`$LOCAL_ANDROID_SHA\`"

  # ── 组装远端命令 = **极小的引导**（远端执行体**不进**命令内容；issue #6124）──────
  REMOTE_FETCH='WORK=$(mktemp -d) && T=$(mktemp) && die() { echo "❌ 引导失败：$1 —— 未做任何发布动作" >&2; exit 1; } && trap '"'"'rc=$?; rm -rf "$WORK"; rm -f "$T"; exit $rc'"'"' EXIT && curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 180 -o "$T" "https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/'"$SCRIPT_SHA"'" || die "取不到远端执行体（codeload tar.gz/'"$SCRIPT_SHA"'）" && tar xzf "$T" -C "$WORK" --strip-components=1 || die "解不开远端执行体（$T）" && bash "$WORK/deploy/swas/terminal-publish-remote.sh"'

  COMMAND_CONTENT="export TERMINAL_STATIC_ROOT=$STATIC_ROOT
export TERMINAL_SUBDIR=$SUBDIR
export TERMINAL_PUBLISH_IMAGE=$IMAGE
export TERMINAL_RELEASE_TAG=$RELEASE_TAG
$REMOTE_FETCH"

  # ── 字节前置断言（**在发起任何云调用之前**）──────────────────────────────
  COMMAND_CONTENT_BYTES=$(printf '%s' "$COMMAND_CONTENT" | wc -c | tr -d ' \n')
  if [ "$COMMAND_CONTENT_BYTES" -ge "$COMMAND_CONTENT_LIMIT_BYTES" ]; then
    die "SWAS 命令内容超限：${COMMAND_CONTENT_BYTES} 字节 / 上限 ${COMMAND_CONTENT_LIMIT_BYTES} 字节 —— 拒绝发起云调用。
   上限出处：${COMMAND_CONTENT_LIMIT_SOURCE}
   口径：远端执行体**不许**被内联进命令内容（命令内容只做「按 sha 取回执行体并执行」）。
   修法：① 新增的发布逻辑加进远端脚本 deploy/swas/terminal-publish-remote.sh（不占命令内容）；
         ② 复核是否有人把「内联远端脚本」的旧写法又加回来了。"
  fi

  # 判据入口（**可注入**）：只打印组装结果与字节读数，**不发起任何云调用**。
  if [ -n "${TERMINAL_PRINT_COMMAND_CONTENT:-}" ]; then
    printf 'COMMAND_CONTENT_BEGIN\n'
    printf '%s\n' "$COMMAND_CONTENT"
    printf 'COMMAND_CONTENT_END\n'
    printf 'COMMAND_CONTENT_BYTES=%s\n' "$COMMAND_CONTENT_BYTES"
    printf 'COMMAND_CONTENT_LIMIT_BYTES=%s\n' "$COMMAND_CONTENT_LIMIT_BYTES"
    printf 'EXPECTED_TARGET=%s\n' "$EXPECTED_TARGET"
    exit 0
  fi

  if [ -n "$AK" ] && [ -n "$SK" ]; then
    command -v aliyun >/dev/null 2>&1 || die "未安装 aliyun CLI（CI 侧应先安装，见 .github/workflows/terminal-publish.yml）"
    aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION" >/dev/null
  else
    echo "ℹ️ 未传 AK/SK —— 使用本机 aliyun 既有配置（人工排障模式）" >&2
  fi

  echo "== 触发 SWAS 云助手执行远端发布脚本 ==" >&2
  INVOKE=$(run_cmd run-command RunCommand \
    --instance-id "$INSTANCE_ID" \
    --name migao-terminal-publish \
    --type RunShellScript \
    --timeout 900 \
    --region-id "$REGION" \
    --command-content "$COMMAND_CONTENT" 2>&1) || die "RunCommand 调用失败：$INVOKE"
  INVOKE_ID=$(echo "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
  [ -n "$INVOKE_ID" ] || die "未获得 InvokeId：$INVOKE"
  echo "publish invokeId=$INVOKE_ID" >&2

  # ── 轮询（墙钟上界）─────────────────────────────────────────────────────
  REMOTE_LOG=""
  STATUS=""
  while :; do
    [ "$(( DEADLINE - $(date +%s) ))" -gt 0 ] || die "发布硬超时（>${PUBLISH_TIMEOUT_SECONDS}s）：远端状态未知"
    RES=$(run_cmd describe-invocation-result DescribeInvocationResult \
      --instance-id "$INSTANCE_ID" \
      --invoke-id "$INVOKE_ID" \
      --region-id "$REGION" 2>&1) || { nap "$POLL_INTERVAL_SECONDS"; continue; }
    STATUS=$(extract_status <<<"$RES")
    if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
      REMOTE_LOG=$(extract_remote_log "$RES")
      [ -n "$REMOTE_LOG" ] || REMOTE_LOG="$RES"
      break
    fi
    echo "  publish status: ${STATUS:-?}（剩余 $(( DEADLINE - $(date +%s) ))s）" >&2
    nap "$POLL_INTERVAL_SECONDS"
  done

  echo ""
  echo "──────── 远端发布输出 ────────"
  printf '%s\n' "$REMOTE_LOG"
  echo "──────── 远端发布输出结束 ────────"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    { echo ""; echo "### 远端发布输出"; echo '````'; printf '%s\n' "$REMOTE_LOG"; echo '````'; } >> "$GITHUB_STEP_SUMMARY"
  fi

  [ "$STATUS" = "Success" ] || die "远端发布失败（InvocationStatus=${STATUS}）—— 见上面的完整远端输出"

  # ── 验收断言（fail-closed；**状态码 200 不算通过**）──────────────────────
  grep -q "^TARGET=$EXPECTED_TARGET$" <<<"$REMOTE_LOG" \
    || die "远端 TARGET 不是期望值：期望 '$EXPECTED_TARGET'（输出里：$(grep -m1 '^TARGET=' <<<"$REMOTE_LOG" || echo '(缺 TARGET 行)')）"

  grep -q "^PAYLOAD_MANIFEST_OK=1$" <<<"$REMOTE_LOG" \
    || die "远端没有给出「清单 ⇄ 载荷」自证行（PAYLOAD_MANIFEST_OK）—— 拒绝把沉默当通过"

  grep -q "^RELEASE_TAG=$RELEASE_TAG$" <<<"$REMOTE_LOG" \
    || die "远端发布的版本不是本次指定的：期望 '$RELEASE_TAG'（输出里：$(grep -m1 '^RELEASE_TAG=' <<<"$REMOTE_LOG" || echo '(缺 RELEASE_TAG 行)')）"

  REMOTE_LATEST_SHA=$(sed -n 's/^PUBLISHED_LATEST_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
  [ "$REMOTE_LATEST_SHA" = "$LOCAL_LATEST_SHA" ] \
    || die "发布的 latest.json 与本地载荷不一致：远端 '$REMOTE_LATEST_SHA' ≠ 本地 '$LOCAL_LATEST_SHA'"

  REMOTE_ANDROID_SHA=$(sed -n 's/^PUBLISHED_ANDROID_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
  [ "$REMOTE_ANDROID_SHA" = "$LOCAL_ANDROID_SHA" ] \
    || die "发布的 android/latest.json 与本地载荷不一致：远端 '$REMOTE_ANDROID_SHA' ≠ 本地 '$LOCAL_ANDROID_SHA'"

  PARENT_BEFORE=$(sed -n 's/^PARENT_INDEX_BEFORE_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
  PARENT_AFTER=$(sed -n 's/^PARENT_INDEX_AFTER_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
  [ -n "$PARENT_BEFORE" ] && [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] \
    || die "静态根 index.html 被触碰（$PARENT_BEFORE → ${PARENT_AFTER}）—— 红线"

  say ""
  say "✅ 发布完成：\`$EXPECTED_TARGET/latest.json\` 哈希 \`$REMOTE_LATEST_SHA\`、\`$EXPECTED_TARGET/android/latest.json\` 哈希 \`$REMOTE_ANDROID_SHA\`（= 本地载荷），静态根未触碰（\`$PARENT_AFTER\`）"
  ;;

-h|--help)
  usage
  exit 0
  ;;
*)
  echo "未知子命令：$MODE（只支持 prepare / publish；-h 看用法）" >&2
  exit 2
  ;;
esac
