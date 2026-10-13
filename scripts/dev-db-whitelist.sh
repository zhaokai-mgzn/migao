#!/usr/bin/env bash
# case_ids: MC-092
# ============================================================================
# 云 dev DB（阿里云 RDS）白名单：本机公网 IP 的**一条命令**（issue #6789）
# ============================================================================
# 病：本机公网 IP 不在 RDS 白名单 ⇒ 本地起栈失败，第一现场却是 7403 行 Spring 栈
#     （`PSQLException 尝试连线已失败` / `SocketTimeoutException`）⇒ 每次都要人肉排查。
#     预设 §10 里本来就有三条手工命令，但「手工合并旧列表」这一步天然容易误删他人 IP。
# 修法：诊断 + 追加 + 复测收敛成一条命令；**只追加**（`--ModifyMode Append`），
#     永不手拼旧列表整体覆盖（overwrite 才是误删他人 IP 的入口）。
#
# 用法：
#   ./scripts/dev-db-whitelist.sh            # 打印当前 IP / 是否在列；不在列则**打印**待执行的命令
#   ./scripts/dev-db-whitelist.sh --yes      # 不在列 ⇒ 真调用 ModifySecurityIps 追加 + 回读 + TCP 复测
#   ./scripts/dev-db-whitelist.sh --check    # 只诊断不写（含 TCP 复测）；0 = 在列且可达，1 = 不在列/不可达
#
# 环境：
#   ENV_FILE        从哪个 .env 读 RDS_HOST / RDS_PORT（默认 $REPO_ROOT/backend/admin-api/.env）
#   REPO_ROOT       仓库根（默认本脚本的上一级）
#   RDS_INSTANCE_ID 覆盖从主机名推出来的实例 id
#   ALIYUN_BIN      覆盖 aliyun 可执行文件（判据里喂桩用）
#   NC_BIN          覆盖 nc 可执行文件（判据里喂桩用）
#   REGION_ID       缺省 cn-hangzhou
#
# 安全边界：
#   ① 只动 `dev_local` 组，`default` 组一个字不动；
#   ② **不打印任何凭据**（.env 里的密码值不进 stdout/stderr）；
#   ③ IP 取不到 / Describe 失败 / Modify 失败 / 回读不含新 IP / 复测失败 ⇒ 一律非零退出 + 可行动文案；
#   ④ 不新增 schedule/cron —— 这是人在现场时的一条命令（铁律 10）。
#
# 兼容：macOS 自带 bash 3.2 —— `$var` 后紧跟中文会被并入变量名 ⇒ 显式 `${var}`；
#      空数组禁裸 `"${A[@]}"`（set -u 下报 unbound variable）⇒ 一律 `${A[@]+"${A[@]}"}`。
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/backend/admin-api/.env}"
ALIYUN_BIN="${ALIYUN_BIN:-aliyun}"
NC_BIN="${NC_BIN:-nc}"
REGION_ID="${REGION_ID:-cn-hangzhou}"

GROUP="dev_local"
DO_APPLY=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --yes) DO_APPLY=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "✗ 未知参数：${arg}（可用：--yes / --check）" >&2; exit 2 ;;
  esac
done

die() { echo "✗ $1" >&2; shift; for line in "$@"; do echo "  $line" >&2; done; exit 1; }
tcp_retest() { "$NC_BIN" -G 5 -z "$1" "$2" >/dev/null 2>&1; }

public_ip() {
  local url ip
  for url in https://checkip.amazonaws.com https://ipinfo.io/ip https://ifconfig.me/ip; do
    ip="$(curl -fsS -m 8 "$url" 2>/dev/null | tr -d '[:space:]')"
    if printf '%s' "$ip" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then printf '%s' "$ip"; return 0; fi
  done
  return 1
}

# .env 只在**本 shell 进程内**解析；密码值随进程一起消失，不进任何输出。
load_env() {
  [ -f "$ENV_FILE" ] || die "找不到 .env：${ENV_FILE}" \
    "本脚本要读 RDS_HOST / RDS_PORT（worktree 形态缺件补齐见 scripts/ui_smoke_merchant.sh 的 [prep] 段）"
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    case "$key" in
      RDS_HOST) RDS_HOST="$val" ;;
      RDS_PORT) RDS_PORT="$val" ;;
    esac
  done < "$ENV_FILE"
}

# DescribeDBInstanceIPArrayList ⇒ 把**指定分组**的 IP 逐行打到 stdout（走临时文件，不喂 stdin：
# bash 3.2 的 `while read` 管道会跑在子 shell 里，变量改不动）。三态：0 = 读到, 1 = 有输出但失败/无此组。
group_ips() {  # $1=instance  $2=group
  local out="${TMPD}/ips.json" err="${TMPD}/ips.err" rc
  rm -f "$out" "$err"
  "$ALIYUN_BIN" rds DescribeDBInstanceIPArrayList --DBInstanceId "$1" --RegionId "$REGION_ID" >"$out" 2>"$err"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "  aliyun 输出：$(head -c 300 "$err" 2>/dev/null | tr '\n' ' ')" >&2
    return 1
  fi
  OUT="$out" GRP="$2" python3 -c '
import json, os, sys
try:
    d = json.load(open(os.environ["OUT"]))
except Exception as e:
    sys.stderr.write("  Describe 输出不是 JSON：%r\n" % (e,))
    sys.exit(1)
items = (d.get("Items") or {}).get("DBInstanceIPArray") or []
grp = os.environ["GRP"]
hit = [x for x in items if x.get("DBInstanceIPArrayName") == grp]
if not hit:
    sys.stderr.write("  实例里没有 %s 分组（现取分组：%s）\n" % (grp, ",".join(x.get("DBInstanceIPArrayName", "?") for x in items)))
    sys.exit(1)
sys.stdout.write("\n".join((hit[0].get("SecurityIPList") or "").split(",")))
' 2>&1
}

in_group() {  # $1=instance  $2=group  $3=ip  ⇒ 0 = 在列
  local ips
  ips="$(group_ips "$1" "$2")" || return 2
  printf '%s\n' "$ips" | grep -Fxq "$3"
}

command -v python3 >/dev/null 2>&1 || die "PATH 里没有 python3（解析 Describe 的 JSON 要用）"

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

load_env
[ -n "${RDS_HOST:-}" ] || die "读不到 RDS_HOST（.env：${ENV_FILE}）"
[ -n "${RDS_PORT:-}" ] || die "读不到 RDS_PORT（.env：${ENV_FILE}）"
case "$RDS_PORT" in ''|*[!0-9]*) die "RDS_PORT 不是端口号：'${RDS_PORT}'（.env：${ENV_FILE}）" ;; esac

if [ -n "${RDS_INSTANCE_ID:-}" ]; then
  INSTANCE_ID="$RDS_INSTANCE_ID"
else
  INSTANCE_ID="$(printf '%s' "$RDS_HOST" | sed -nE 's/^(pgm-[0-9a-z]+)(-pub)?\.pg\.rds\.aliyuncs\.com$/\1/p')"
  [ -n "$INSTANCE_ID" ] || die "从 RDS_HOST 推不出实例 id：'${RDS_HOST}'" \
    "预期形态 <实例id>[-pub].pg.rds.aliyuncs.com；也可用 RDS_INSTANCE_ID 显式指定"
fi

IP="$(public_ip)" || die "多源都取不到本机公网 IP" \
  "试过：checkip.amazonaws.com / ipinfo.io/ip / ifconfig.me/ip（取不到就 fail-closed，不猜）"

echo "==> 云 dev DB 白名单（实例 ${INSTANCE_ID} · 分组 ${GROUP} · 只追加）"
echo "    本机公网 IP：${IP}"

in_group "$INSTANCE_ID" "$GROUP" "$IP"; IN_RC=$?
[ "$IN_RC" = "2" ] && die "读取 ${GROUP} 组白名单失败（aliyun 不可用 / 无凭据 / 输出无法解析）" \
  "自查：aliyun configure list" "追加需人显式确认：./scripts/dev-db-whitelist.sh --yes"

if [ "$CHECK_ONLY" = "1" ]; then
  if [ "$IN_RC" = "0" ]; then
    echo "    ✅ 已在 ${GROUP} 组"
  else
    echo "    ✗ **不在** ${GROUP} 组 ⇒ 起栈必失败（PSQLException 尝试连线已失败 / SocketTimeoutException）"
    echo "      ⇒ 处置：./scripts/dev-db-whitelist.sh --yes"
  fi
  if tcp_retest "$RDS_HOST" "$RDS_PORT"; then
    echo "    TCP ${RDS_HOST}:${RDS_PORT} ⇒ Connection succeeded ✅"
    [ "$IN_RC" = "0" ] || exit 1
  else
    echo "    TCP ${RDS_HOST}:${RDS_PORT} ⇒ 不可达 ✗"
    exit 1
  fi
  exit 0
fi

if [ "$IN_RC" = "0" ]; then
  echo "    ✅ 已在 ${GROUP} 组 ⇒ **不调用** ModifySecurityIps（幂等）"
else
  if [ "$DO_APPLY" != "1" ]; then
    die "IP ${IP} 不在 ${GROUP} 组（未写任何云资源 —— 本脚本默认只诊断）" \
      "确认后执行：./scripts/dev-db-whitelist.sh --yes"
  fi
  echo "    追加到 ${GROUP}（--ModifyMode Append：只追加，不覆盖既有条目）..."
  if ! "$ALIYUN_BIN" rds ModifySecurityIps --DBInstanceId "$INSTANCE_ID" \
        --DBInstanceIPArrayName "$GROUP" --SecurityIps "$IP" --ModifyMode Append \
        --RegionId "$REGION_ID" >"${TMPD}/mod.json" 2>&1; then
    die "ModifySecurityIps 失败（未改默认组、未覆盖旧列表）" \
      "aliyun 输出：$(head -c 300 "${TMPD}/mod.json" 2>/dev/null | tr '\n' ' ')" \
      "自查：aliyun configure list"
  fi
  echo "    ✓ 追加已提交"
fi

if in_group "$INSTANCE_ID" "$GROUP" "$IP"; then
  echo "    ✓ 回读确认：${GROUP} 组已含 ${IP}"
else
  die "回读失败：${GROUP} 组里读不到 ${IP}（Describe / 追加不一致）"
fi

if tcp_retest "$RDS_HOST" "$RDS_PORT"; then
  echo "    ✓ TCP 复测 ${RDS_HOST}:${RDS_PORT} ⇒ Connection succeeded"
else
  die "TCP 复测失败：${RDS_HOST}:${RDS_PORT} 不可达" \
    "白名单已含 ${IP} ⇒ 更可能是安全组 / 网络 / 实例状态，不是本脚本能修的"
fi
