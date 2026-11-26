#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# bmini-release.sh — B 端小程序「发一版」的**一条命令**（编排层，issue #9069）
#
# ## 治什么（2026-11-23 用户裁定「不碰C端，先把B端做夯实」；1.0.2 发出去时的形态）
#
#   发一版 = **三步手打 + 三处人肉记忆**：
#     ① `./scripts/cut-release.sh`（发布线 ⊆ main）→ ② `bmini-experience.sh build --env prod`
#     → ③ `bmini-experience.sh upload --version X.Y.Z --desc '…'`
#   靠人记的三处：
#     · **顺序即安全顺序**（先 cut 再 build 再上传）—— 记反一次就发错包；
#     · **生产包只在部署机构建 + 上传**（2026-11-23 用户裁定）—— 本机误跑会产出指向
#       `localhost` 的漂移包（1.0.1 就是这么废的：真机 `request:fail errcode:-102`）；
#     · **上传后 `TOTAL` 读数要人手抄进 docs 的发布记录表** —— 抄错没人知道。
#
# ## 本脚本是什么 / 不是什么
#
#   是**编排层**：把上面三步按安全顺序串起来，并把「人肉记忆」变成**判据**。
#   不是**判据本体**：构建与常量注入仍归 `scripts/bmini-experience.sh`（它内部调产物断言），
#   产物判据仍归 `deploy/scripts/bmini-assert-dist.sh`，发布线口径仍归 `scripts/cut-release.sh`
#   （本脚本只调 `--check`：**cut 是显式动作，本脚本永不自己 cut**）。
#   ⇒ 这里**不出现**任何上限常量 / 域名常量 / 构建命令拼接（第二把尺子会被
#     `test_bmini_dist_budget.py::test_no_second_ruler_and_the_allowlist_only_shrinks` 判红）。
#
# ## 六道关（每条都有判据；顺序即安全顺序）
#
#   | # | 闸门 | 判据 | 不满足 |
#   |---|---|---|---|
#   | ① | **机器闸门** | 本机身份 == `ssh -G <别名>` 解析出的 `HostName`（别名缺省 `migao-deploy`，**禁写死 IP**） | 退 1（具名拒绝 + 出口）· 读数不可得 ⇒ 退 3 |
#   | ② | **顺序闸门** | `origin/release` ⊆ `origin/main`（复算 = `cut-release.sh --check`，退 2 即旁路）+ **本检出 HEAD == `origin/release`** + 无未提交改动 | 退 1（具名 + 出口「在部署机跑 cut-release.sh」）· 取不到远端 ⇒ 退 3 |
#   | ③ | **构建** | `bmini-experience.sh build --env prod`（常量注入 + build:weapp + 产物断言，全是它的实现） | 退 1 |
#   | ④ | **上传前断言** | 再跑一次 `deploy/scripts/bmini-assert-dist.sh <dist> --env prod`（dist 可能是上一次留下的） | 不过 ⇒ **拒绝上传**（退 1 / 不可判定退 3） |
#   | ⑤ | **上传** | `bmini-experience.sh upload --env prod --version <显式给的版本号>`（版本号不自动递增、不猜） | 退 1 |
#   | ⑥ | **回读 + 记录行** | 从上传日志抓 `TOTAL` 字节；`dist ÷ TOTAL` 必须落在「预算文件 calibration 台账的比值 ±3%」内 | 打印可粘贴行；比值越界 ⇒ **警告并退 3**（不可判定，不静默通过）；抓不到 TOTAL ⇒ 退 3 |
#
# ## 用法
#
#   scripts/bmini-release.sh --host-assert                 # 只判「本机是不是部署机」（零副作用）
#   scripts/bmini-release.sh                               # ① ② ③ ④：构建 + 断言，**不上传**
#   scripts/bmini-release.sh --upload --version 1.0.3 --desc "…"
#                                                          # ①~⑥：再上传并打印可粘贴的发布记录行
#
#   没有 `--env`：本脚本是**发布**路径，恒为 `--env prod`（test 包那条腿是
#   `bmini-experience.sh build --env test`，不是发布）。
#
# ## 退出码（沿用仓库既有三态）
#
#   `0` 成功 / `1` 判红（闸门不成立，具名） / `2` 用法错误 / `3` **不可判定**（读数拿不到，`3` 不当 `0` 读）
#
# ## 边界（照实登记，别读成「全自动发布」）
#
#   · 传完仍要人到**微信后台 → 版本管理 → 选为体验版 → 提审 → 发布**（`miniprogram-ci` 只提供上传/预览）；
#   · `TOTAL` 是**微信开发者工具**的读数：走 `miniprogram-ci`（`--key`）通道时它不打印 ⇒ 本脚本退 3
#     （不猜读数，记录表那一格需要 devtools 通道复跑一次）；
#   · 抓 `TOTAL` 的形态是按开发者工具的输出写的（含 `TOTAL` 的行里第一个 ≥4 位数字）——
#     形态变了 ⇒ 退 3 并给日志路径（不静默通过）；
#   · 本脚本**不删** `dist`（不做破坏性动作）：上一次构建的残留会被④的域名断言判红，处置 = 人工删 `dist` 重跑；
#   · 机器闸门是**防误跑**，不是防对抗：它读的就是人用的那个 SSH 别名（不写死 IP）；谁改自己的
#     `~/.ssh/config` 说「这台就是部署机」，闸门就认（同「改脚本」一样——别把它当权限边界）。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EXPERIENCE="${ROOT}/scripts/bmini-experience.sh"
CUT_RELEASE="${ROOT}/scripts/cut-release.sh"
ASSERT_DIST="${ROOT}/deploy/scripts/bmini-assert-dist.sh"
BUDGET_JSON="${ROOT}/deploy/scripts/bmini-dist-budget.json"
APP_DIR="${ROOT}/frontend/bmini-app"
DIST="${APP_DIR}/dist"

# 部署机的**唯一标识** = SSH 别名（`~/.ssh/config` 的 `Host migao-deploy`）。禁写死 IP：
# 那台机器走 DHCP，地址会变；别名是人与脚本都用同一个名字。
DEPLOY_ALIAS="${MIGAO_BMINI_DEPLOY_SSH_ALIAS:-migao-deploy}"
# 本机身份的可注入读数（只用于**测试与排障**；缺省读真机：scutil LocalHostName / hostname）。
HOST_ID_OVERRIDE="${MIGAO_BMINI_HOST_ID:-}"
# `ssh -G` 的配置来源可注入（测试用；缺省 = 人正常的 `~/.ssh/config`）。
# ⚠️ 不存空数组再展开：macOS 自带 bash 3.2 在 `set -u` 下会把 `"${空数组[@]}"` 当 unbound 崩掉。
SSH_CONFIG_FILE="${MIGAO_BMINI_SSH_CONFIG:-}"
# 比值容差 = ±3%（**容差**，不是尺子：尺子 = 预算文件的 calibration 台账，见⑥）。
RATIO_TOLERANCE_PERMILLE=30

USAGE=0
UPLOAD=0
HOST_ASSERT=0
VERSION=""
DESC=""
KEY=""

usage() {
  cat <<'USAGE'
用法: scripts/bmini-release.sh [--upload --version X.Y.Z [--desc '…'] [--key <私钥路径>]]
      scripts/bmini-release.sh --host-assert

  （无参数）  ① 机器闸门 → ② 顺序闸门 → ③ 构建（--env prod）→ ④ 上传前断言
              **不上传**（要上传必须显式 --upload），最后打印「未上传」
  --upload    再叠加 ⑤ 上传 + ⑥ 回读：从上传日志抓 TOTAL，打印一行可直接粘贴进
              docs/deployment/bmini-experience-release.md「发布记录」表的 Markdown 行
  --host-assert  只判「本机是不是部署机」（零副作用；CI / 排障用）

选项:
  --version X.Y.Z   **必填**（仅 --upload）：体验版版本号，显式给、不自动递增、不从 package.json 猜
  --desc '…'        版本备注（缺省交给 bmini-experience.sh：'bmini 体验版 <version>'）
  --key <路径>      代码上传私钥（转交 bmini-experience.sh；等价于 MINIPROGRAM_UPLOAD_KEY）

环境变量:
  MIGAO_BMINI_DEPLOY_SSH_ALIAS  部署机的 SSH 别名（缺省 migao-deploy；**不要**写 IP）
  MIGAO_BMINI_HOST_ID           本机身份读数（缺省读真机；测试 / 排障用）
  MIGAO_BMINI_SSH_CONFIG        ssh 配置路径（缺省 ~/.ssh/config；测试用）

退出码: 0 成功 / 1 判红（闸门不成立） / 2 用法错误 / 3 不可判定（读数拿不到，不得当 0 读）

⚠️ 本脚本恒为 --env prod，且**只在部署机**可用（生产包只在部署机构建 + 上传，2026-11-23 用户裁定）。
USAGE
}

die_usage() {
  echo "❌ 用法错误：$*" >&2
  usage >&2
  exit 2
}

# 判红：闸门不成立（具名 + 出口由调用方给）
die_named() {
  echo "❌ $*" >&2
  exit 1
}

# 不可判定：读数拿不到（3 不当 0 读）
undecidable() {
  echo "⚠️  不可判定（退出码 3）：$*" >&2
  echo "   ⇒ 本脚本对这一形态**不判通过**（不可判定不得当 0 读）。" >&2
  exit 3
}

ok() { echo "   ✅ $*"; }
warn() { echo "   ⚠️  $*"; }

# ── 参数 ───────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --upload)
      UPLOAD=1
      shift
      ;;
    --host-assert)
      HOST_ASSERT=1
      shift
      ;;
    --version)
      [ $# -ge 2 ] || die_usage "--version 缺值（形如 1.0.3）"
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
    --env|--env=*)
      die_usage "本脚本没有 --env：发布路径恒为 --env prod（test 腿是 bmini-experience.sh build --env test，不是发布）"
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

for dep in "$EXPERIENCE" "$CUT_RELEASE" "$ASSERT_DIST"; do
  [ -f "$dep" ] || die_named "缺少被编排的脚本 ${dep} —— 没有它就没有判据，本脚本不许自己实现一份"
done

# ── 主机名归一：小写、去尾点、去 `.local` 后缀（`HostName zhk-mbp.local` == `LocalHostName zhk-mbp`）──
normalize_host() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's/\.$//' -e 's/\.local$//'
}

# 部署机的 HostName —— 唯一来源是 ssh 配置（`ssh -G` 会把别名解析成 HostName，含 ~/.ssh/config）
deploy_host_name() {
  command -v ssh >/dev/null 2>&1 || return 3
  local resolved
  if [ -n "$SSH_CONFIG_FILE" ]; then
    resolved=$(ssh -G -F "$SSH_CONFIG_FILE" "$DEPLOY_ALIAS" 2>/dev/null) || return 3
  else
    resolved=$(ssh -G "$DEPLOY_ALIAS" 2>/dev/null) || return 3
  fi
  printf '%s\n' "$resolved" | awk '$1 == "hostname" { print $2; exit }'
}

# 本机身份候选（每行一个）。注入读数优先：那是**读数**的口子，不是「跳过闸门」的开关。
local_host_ids() {
  if [ -n "$HOST_ID_OVERRIDE" ]; then
    printf '%s\n' "$HOST_ID_OVERRIDE"
    return 0
  fi
  local ids=() name=""
  if command -v scutil >/dev/null 2>&1; then
    name=$(scutil --get LocalHostName 2>/dev/null) || name=""
    if [ -n "$name" ]; then
      ids+=("$name" "${name}.local")
    fi
  fi
  name=$(hostname -s 2>/dev/null) || name=""
  [ -n "$name" ] && ids+=("$name")
  name=$(hostname 2>/dev/null) || name=""
  [ -n "$name" ] && ids+=("$name")
  [ ${#ids[@]} -gt 0 ] || return 3
  printf '%s\n' "${ids[@]}"
}

# ── ① 机器闸门 ────────────────────────────────────────────────────────────────
gate_machine() {
  echo "== ① 机器闸门（生产包只在部署机构建 + 上传；2026-11-23 用户裁定）=="
  local target rc=0
  target=$(deploy_host_name) || rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$target" ]; then
    undecidable "读不到 SSH 别名 '${DEPLOY_ALIAS}' 的 HostName（ssh -G 不可用 / ssh 配置不可读）——
       无法判定本机是不是部署机。出口：确认 ssh 可用、~/.ssh/config 里有 'Host ${DEPLOY_ALIAS}' 段（或用
       MIGAO_BMINI_SSH_CONFIG=<配置文件> 指定），再跑 scripts/bmini-release.sh --host-assert"
  fi
  local ids rc_ids=0
  ids=$(local_host_ids) || rc_ids=$?
  if [ "$rc_ids" -ne 0 ] || [ -z "$ids" ]; then
    undecidable "读不到本机身份（scutil LocalHostName / hostname 都失败）—— 无法判定是不是部署机。
       出口：显式给读数 MIGAO_BMINI_HOST_ID=\$(hostname -s) 后重跑 --host-assert"
  fi
  echo "   部署机（SSH 别名 ${DEPLOY_ALIAS} → HostName）= ${target}"
  echo "   本机身份 = $(printf '%s\n' "$ids" | paste -sd' /' -)"
  local target_norm id
  target_norm=$(normalize_host "$target")
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if [ "$(normalize_host "$id")" = "$target_norm" ]; then
      ok "本机就是部署机（${target}）"
      echo ""
      return 0
    fi
  done <<< "$ids"
  die_named "非部署机 ⇒ 拒绝执行（生产包只在部署机构建 + 上传：产物与「真正上传的那份」必须同机同源）
   本机 = $(printf '%s\n' "$ids" | head -1)
   部署机（SSH 别名 '${DEPLOY_ALIAS}'）的 HostName = ${target}
   出口（三选一）：
     · **正确路径**：ssh ${DEPLOY_ALIAS} 之后在部署机上跑本脚本（本机只做只读判据复算）
     · 这台**就是**部署机（别名指错了）：把 ~/.ssh/config 的 'Host ${DEPLOY_ALIAS}' 段的 HostName 改成
       <本机 LocalHostName>.local，再跑 scripts/bmini-release.sh --host-assert 复验
     · 只想要「一个生产域产物 + 断言」而**不发布**：scripts/bmini-experience.sh build --env prod
       （那条腿不是发布路径，但会构建 + 断言）"
}

# ── ② 顺序闸门 ────────────────────────────────────────────────────────────────
gate_release() {
  echo "== ② 顺序闸门（发布线 ⊆ main + 本检出就是发布线；cut 是显式动作，本脚本不 cut）=="
  local out rc=0
  out=$( cd "$ROOT" && bash "$CUT_RELEASE" --check 2>&1 ) || rc=$?
  printf '%s\n' "$out" | sed 's/^/   /'
  case "$rc" in
    0)
      ;;
    2)
      die_named "发布线被旁路：${CUT_RELEASE} --check 退 2（origin/release 上有 origin/main 没有的提交）——
       本脚本**不会**替你 cut / 对齐远端（cut 是显式动作）。
       出口：查清那些提交从哪来（应为 0）；确认后在部署机上跑 ./scripts/cut-release.sh"
      ;;
    3)
      undecidable "${CUT_RELEASE} --check 退 3：取不到远端 ref（网络 / origin 不可达）——
       发布线是否 ⊆ main 不可判定，不许当通过。出口：恢复对 origin 的访问后重跑"
      ;;
    *)
      die_named "${CUT_RELEASE} --check 退 ${rc}（未预期）—— 发布线口径不可信，拒绝继续。看上面读数"
      ;;
  esac

  local release_sha head_sha
  release_sha=$(git -C "$ROOT" rev-parse --verify --quiet origin/release) || release_sha=""
  if [ -z "$release_sha" ]; then
    die_named "拿不到 origin/release ⇒ 发布线还不存在，这次不许发（构建会变成「工作区是什么就发什么」）
       出口：在部署机上跑 ./scripts/cut-release.sh（把 release 快进到 main，显式动作）后重跑本脚本"
  fi
  head_sha=$(git -C "$ROOT" rev-parse --verify HEAD) || undecidable "拿不到本检出的 HEAD（不是 git 检出？）"
  if [ "$head_sha" != "$release_sha" ]; then
    die_named "本检出不是发布线：HEAD $(printf '%s' "$head_sha" | cut -c1-7) ≠ origin/release $(printf '%s' "$release_sha" | cut -c1-7)
       （2026-11-21 差点用「停在旧特性分支的工作区」构建，正是这一条要拦的形态）
       出口：git fetch && git checkout --detach origin/release（在部署机的发布检出上），或在部署机上跑 ./scripts/cut-release.sh 后再切"
  fi
  ok "HEAD == origin/release（$(printf '%s' "$release_sha" | cut -c1-7)）"

  local dirty
  dirty=$(git -C "$ROOT" status --porcelain --untracked-files=no) || undecidable "跑不动 git status（不是 git 检出？）"
  if [ -n "$dirty" ]; then
    printf '%s\n' "$dirty" | head -10 | sed 's/^/      /' >&2
    die_named "工作区有未提交的改动（上面列出）⇒ 产出的包不是 origin/release 的内容，拒绝继续。
       出口：先 commit / stash（发布检出上不该有未提交改动）"
  fi
  ok "工作区干净（无未提交改动；未跟踪文件不拦 —— 它们不进构建）"
  local untracked
  untracked=$(git -C "$ROOT" status --porcelain --untracked-files=normal | grep '^??' | head -5) || true
  if [ -n "$untracked" ]; then
    warn "有未跟踪文件（不入构建，但发布检出上最好清掉）：$(printf '%s' "$untracked" | tr '\n' ' ')"
  fi
  echo ""
}

# ── ③ 构建（复用 bmini-experience.sh：常量注入 + Taro + 产物断言都在它那儿）──────
step_build() {
  echo "== ③ 构建（复用 scripts/bmini-experience.sh build --env prod）=="
  if ! bash "$EXPERIENCE" build --env prod; then
    die_named "构建失败（含 bmini-experience.sh 内部的产物断言）—— 看上面读数；本脚本不自己拼 Taro 命令、不自己注入常量"
  fi
  echo ""
}

# ── ④ 上传前断言（复用 deploy/scripts/bmini-assert-dist.sh；不过就拒绝上传）──────
gate_assert() {
  echo "== ④ 上传前断言（复用 deploy/scripts/bmini-assert-dist.sh）=="
  local rc=0
  bash "$ASSERT_DIST" "$DIST" --env prod || rc=$?
  case "$rc" in
    0)
      ok "产物断言通过（结构 / 域名策略 / 体积）"
      ;;
    3)
      undecidable "产物断言**不可判定**（${ASSERT_DIST} 退 3：dist 不存在 / 为空 / 读不到）⇒ 拒绝上传。
         出口：确认构建真的产出了 ${DIST}"
      ;;
    *)
      die_named "产物断言未通过（${ASSERT_DIST} 退 ${rc}）⇒ **拒绝上传**（顺序即安全顺序：先断言、再上传）"
      ;;
  esac
  echo ""
}

# ── ⑥ 口径尺子的来源：预算文件的 calibration 台账（比值**现算**，不在这里另写一份）──
calibration_permille() {
  python3 - "$BUDGET_JSON" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        data = json.load(fh)
except Exception as exc:  # noqa: BLE001 —— 读不到台账 = 口径不可判定（不是「没问题」）
    print('BUDGET_UNREADABLE: %s' % exc, file=sys.stderr)
    raise SystemExit(4)
rows = data.get('calibration') or []
if not rows:
    print('CALIBRATION_EMPTY', file=sys.stderr)
    raise SystemExit(4)
latest = max(rows, key=lambda row: row['date'])
print(round(latest['distBytes'] / latest['wechatBytes'] * 1000))
PY
}

# 从上传日志抓 `TOTAL` 字节（开发者工具的输出形态：`TOTAL <字节>`；形态变了 ⇒ 抓不到 ⇒ 退 3，不猜）。
# 🔴 取**最后一行**含 `TOTAL` 的：前面几道产物断言的输出里也有「… → TOTAL 1,461,748，比值 0.998」
#    这种**口径交代行**（体积段引用实测读数），取第一行会抓到那句里的数字（实测抓到过年份 2026）。
#    定位 = 最后一个 TOTAL 之后的第一串 ≥4 位数字。
extract_total_bytes() {
  local log=$1 line num=""
  line=$(grep -aE 'TOTAL' "$log" 2>/dev/null | tail -1)
  if [ -n "$line" ]; then
    num=$(printf '%s' "$line" | sed 's/.*TOTAL//' | tr -d ',' | grep -oE '[0-9]{4,}' | head -1)
  fi
  printf '%s' "$num"
}

human_bytes() {
  python3 -c 'import sys; print(format(int(sys.argv[1]), ","))' "$1" 2>/dev/null || printf '%s' "$1"
}

# ── ⑤ 上传 + ⑥ 回读 ───────────────────────────────────────────────────────────
step_upload() {
  echo "== ⑤ 上传（复用 scripts/bmini-experience.sh upload --env prod）=="
  local log rc=0 args
  log=$(mktemp "${TMPDIR:-/tmp}/bmini-release-upload.XXXXXX") || undecidable "建不了上传日志临时文件"
  args=(upload --env prod --version "$VERSION")
  [ -n "$DESC" ] && args+=(--desc "$DESC")
  [ -n "$KEY" ] && args+=(--key "$KEY")
  ( bash "$EXPERIENCE" "${args[@]}" 2>&1 | tee "$log"; exit "${PIPESTATUS[0]}" ) || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "   （上传日志：${log}）" >&2
    die_named "上传失败（bmini-experience.sh upload 退 ${rc}）—— 常见：IDE 未登录 / 私钥与 appid 不匹配 / 代码上传 IP 白名单未含本机出口 IP"
  fi
  echo ""

  echo "== ⑥ 回读（从上传日志抓 TOTAL，产出可粘贴的发布记录行）=="
  local total
  total=$(extract_total_bytes "$log")
  if [ -z "$total" ]; then
    undecidable "上传成功了，但日志里抓不到 TOTAL 字节（拖取的形态按「含 TOTAL 的行里第一个 ≥4 位数字」写的）。
       出口：① 日志在 ${log}，人工 grep 一下；② 走 --key（miniprogram-ci）通道时它**不打印** TOTAL ——
       记录表的包体那一格要用开发者工具通道复跑一次才有读数。不猜读数、不填假数"
  fi
  local dist_bytes
  dist_bytes=$(find "$DIST" -type f -exec cat {} + 2>/dev/null | wc -c | tr -d ' ')
  dist_bytes=${dist_bytes:-0}
  [ "$dist_bytes" -gt 0 ] || undecidable "取不到 dist 字节合计（${DIST}）—— 比值无从复算"

  local cal rc_cal=0
  cal=$(calibration_permille) || rc_cal=$?
  if [ "$rc_cal" -ne 0 ]; then
    undecidable "读不到包体预算的 calibration 台账（${BUDGET_JSON}）—— 没有口径就没有「等价」判据。
       出口：确认该文件在（它是包体预算的**唯一来源**，与 deploy/scripts/bmini-assert-dist.sh 同一份）"
  fi
  local low=$(( cal - RATIO_TOLERANCE_PERMILLE ))
  local high=$(( cal + RATIO_TOLERANCE_PERMILLE ))
  local measured ratio
  measured=$(awk -v d="$dist_bytes" -v t="$total" 'BEGIN { printf "%d", (d / t * 1000) + 0.5 }')
  ratio=$(awk -v d="$dist_bytes" -v t="$total" 'BEGIN { printf "%.3f", d / t }')

  echo "   读数：dist=${dist_bytes} 字节 · TOTAL=${total} 字节 · dist÷TOTAL=${ratio}"
  echo "   口径：预算文件 calibration 台账的比值 $(awk -v c="$cal" 'BEGIN { printf "%.3f", c / 1000 }') ± ${RATIO_TOLERANCE_PERMILLE}‰ ⇒ 允许 [$(( low ))‰, $(( high ))‰]（现算，不另存一份尺子）"

  local top repo_path date_str rel_sha
  top=$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null) || top=$ROOT
  case "$top" in
    "$HOME"/*) repo_path="~${top#"$HOME"}" ;;
    *) repo_path="$top" ;;
  esac
  rel_sha=$(git -C "$ROOT" rev-parse --verify --quiet origin/release | cut -c1-7) || rel_sha="?"
  date_str=$(date '+%F %H:%M')

  if [ "$measured" -lt "$low" ] || [ "$measured" -gt "$high" ]; then
    warn "比值 ${ratio} 落在 [$(( low ))‰, $(( high ))‰] 之外 ⇒ **口径分叉**（dist 字节与微信 TOTAL 不再等价）"
    echo "   行（**仅供参考，不要粘进发布记录**；先查清口径）：" >&2
    printf '| %s | %s · 部署机 `%s`（`%s`，HEAD = `origin/release` `%s`） | — | — | %s 字节 | dist %s 字节（比值 %s） |\n' \
      "$VERSION" "$date_str" "$DEPLOY_ALIAS" "$repo_path" "$rel_sha" "$(human_bytes "$total")" "$(human_bytes "$dist_bytes")" "$ratio" >&2
    undecidable "比值越界（见上）⇒ 不可判定，退 3（**不静默通过**）。
       出口：① 核对这次 dist 与 TOTAL 是不是同一份产物；② 口径真变了 ⇒ 更新 ${BUDGET_JSON} 的 calibration 台账
       （同一 PR 里同步 docs/deployment/bmini-experience-release.md 的「体积判据的口径」节），别改这里的容差"
  fi
  ok "比值 ${ratio} 落在 [$(( low ))‰, $(( high ))‰] 内（与台账等价）"
  echo ""
  echo "== 可粘贴行（docs/deployment/bmini-experience-release.md → §六 发布记录 表；审核列/发布者列仍需人手填）=="
  printf '| %s | %s · 部署机 `%s`（`%s`，HEAD = `origin/release` `%s`） | — | — | %s 字节 | dist %s 字节（比值 %s） |\n' \
    "$VERSION" "$date_str" "$DEPLOY_ALIAS" "$repo_path" "$rel_sha" "$(human_bytes "$total")" "$(human_bytes "$dist_bytes")" "$ratio"
  echo ""
  echo "   接下来（命令行做不了）：微信后台 → 版本管理 → 选为体验版 → 提审 → 发布；提审清单见 docs §一~§五"
  rm -f "$log"
  echo ""
  echo "✅ 完成：version=${VERSION} 已上传（TOTAL=${total} 字节）"
}

# ── 版本号形态（仅上传需要；显式给 + 形态可判 ⇒ 打错一个数字当场拦住）──────────
if [ "$HOST_ASSERT" -eq 1 ]; then
  gate_machine
  echo "✅ 机器闸门通过：本机 = 部署机（${DEPLOY_ALIAS}）"
  exit 0
fi

if [ "$UPLOAD" -eq 1 ]; then
  [ -n "$VERSION" ] || die_usage "--upload 必须显式给 --version X.Y.Z（不自动递增、不从 package.json 猜）"
  if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    die_usage "--version 必须是 X.Y.Z（收到：${VERSION}）"
  fi
elif [ -n "$VERSION" ] || [ -n "$DESC" ] || [ -n "$KEY" ]; then
  die_usage "--version / --desc / --key 只在 --upload 时有效（本档只构建 + 断言；要上传请显式加 --upload）"
fi

echo "════ B 端小程序发布（一条命令；issue #9069）════"
echo "   checkout=${ROOT}"
echo "   部署机 SSH 别名=${DEPLOY_ALIAS} · env=prod（发布路径无 --env）· 上传=$([ "$UPLOAD" -eq 1 ] && echo '是' || echo '否（未上传）')"
echo ""

gate_machine
gate_release
step_build
gate_assert

if [ "$UPLOAD" -eq 0 ]; then
  echo "== ⑤ 上传 —— **未上传**（没给 --upload）=="
  echo "   本档只做了 ① 机器闸门 ② 顺序闸门 ③ 构建 ④ 上传前断言；没有上传动作，也就没有 TOTAL 读数"
  echo "   ⇒ **不产出**「可粘贴发布记录行」（不猜读数）。要上传（仍在部署机上跑）："
  echo "      scripts/bmini-release.sh --upload --version X.Y.Z --desc '这次发了什么'"
  exit 0
fi

step_upload
exit 0
