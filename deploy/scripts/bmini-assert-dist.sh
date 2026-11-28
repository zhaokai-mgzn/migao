#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# bmini-assert-dist.sh — B 端小程序 **weapp 构建产物** 的纯断言（issue #8980）
#
# ## 为什么要有一份「产物断言」（2026-11-21 首次手工发体验版暴露的三个形态）
#
#   ① **生产常量靠人手记**：`TARO_APP_API_URL` / `TARO_APP_AI_API_URL` /
#      `TARO_APP_PUBLIC_APP_ORIGIN` 必须显式注入 cytda 值；少给一个，产物就**静默**烘进测试域
#      （或 localhost）—— 上传照样成功、微信照样收包，只有真机/体验版**运行时**连不上，
#      而开发者工具勾了「不校验合法域名」时连那个错都看不见（同族病史见 #8942 / #8966）。
#   ② **体积没有闸门**：本地构建不报，只在上传那一刻由微信报错（分包规划见 #8979）。
#   ③ **结构没人核**：少一张 `.wxml` / 少一页的 `.json`，只有上传时才由微信报错。
#
# ⇒ 本脚本只做**断言**（不构建、不上传、不写盘），可被 CI 直接调用；判据三条：
#
#   | # | 判据 | 红证（都能单独变红） |
#   |---|---|---|
#   | ① | **结构**：`app.json` 存在且 `pages` 非空；`app.js` 在；每页 `.js` / `.wxml` / `.json`
#   |   | 都在（`.wxss` 允许缺省 —— Taro 对不含样式的页面本就不产出） | 删掉某页的 `.wxml` ⇒ 红 |
#   | ② | **域名策略**（本脚本的核心）：`--env prod` ⇒ `migaozn.com` 出现 **0** 次、
#   |   | `cytda.com` **≥1** 次、且**不得残留 `localhost`**（抓「三件套只注入了两个」）；
#   |   | `--env test` ⇒ 反向（`migaozn.com` ≥1、`cytda.com` 0） | prod 模式喂含 `migaozn.com`
#   |   | 的产物 ⇒ 红；只注入 label origin、API 仍是 localhost ⇒ 红（只靠前两条抓不住） |
#   | ③ | **体积**（issue #8979 / #8981）：**主包** ≤ 单包上限 − 主包预留（预留 = #8979 要求的
#   |   | ≥300KB 余量）、**每个分包**各自 ≤ 单包上限、**总包** ≤ 总包上限；常量**唯一来源** =
#   |   | `deploy/scripts/bmini-dist-budget.json`（本文件不写死任何上限） | 主包顶过预算 1 字节 ⇒ 红；
#   |   | 某分包 = 上限 +1 ⇒ 红且点名那个分包；分包合计越过总包上限 ⇒ 红 |
#
# ## 体积判据的**口径**（#8981 的收口；读数与出处见预算文件 + docs 的「体积判据」节）
#
#   判的是 **dist 字节**。它与微信开发者工具上传后报的 `TOTAL` **等价**：2026-11-23 部署机实测
#   `dist 1,465,245 → TOTAL 1,461,748`（比值 0.998）⇒ 用 dist 判是**偏严**方向。
#   ⇒ **不叠折算系数**。历史上那个「×1.425 ⇒ 微信 2,079,753」的读数在部署机四份产物与
#   devtool 日志里都复现不出来（登记在预算文件的 `unreproducibleReadings`）；据它收紧闸门
#   会把门禁错误压到 ≈1.47MB、制造假红。
#
# 🔴 **三态退出码**（`3` 不得当 `0` 读 —— 「没构建」与「产物合格」是两件事）：
#
#   | 码 | 含义 |
#   |---|---|
#   | `0` | 三条判据全部成立 |
#   | `1` | 至少一条判据不成立（逐条打印哪条 + 读数） |
#   | `2` | 用法错误（未知参数 / `--env` 取值非法 / 缺 dist 位置参数） |
#   | `3` | **不可判定**：dist 不存在 / 不是目录 / 不可读 / **空目录**（构建没产出）/ 缺 `python3` |
#
# 用法: deploy/scripts/bmini-assert-dist.sh <dist 目录> [--env prod|test]
#   `--env` 缺省 = `test`：CI 的 weapp 构建**不注入**生产常量（既有行为不变）⇒ 产物就该是测试域。
#   生产包由 `scripts/bmini-experience.sh build --env prod` 在**部署机**上构建并断言
#   （用户 2026-11-23 裁定：生产包只在那台机器上构建 + 上传；开发机只做只读复算）。
#
# 边界（照实登记，不粉饰）：
#   · 分包（#8979）**已落地**（2026-11-28）：`pages/admin/{pool,inbound,after-sales,piecework}` 在
#     `subPackages` 里（root = `pages/admin`）⇒ 判据 ③ 的 `subPackages[].root` 分支在**真实产物**上生效
#     （主包剔除分包字节、每个分包各自判、总包判）；路由字符串一个字节没变。
#   · 判不了「产物能不能跑起来」（那要真机/模拟器），也判不了微信后台的「服务器域名」白名单。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# 包体预算的**唯一来源**（单包上限 / 总包上限 / 主包预留 / 口径台账）——本文件不写死任何上限。
BUDGET_JSON="${SCRIPT_DIR}/bmini-dist-budget.json"
BUDGET_REL="deploy/scripts/bmini-dist-budget.json"
SELF_REL="deploy/scripts/bmini-assert-dist.sh"

DIST=""
ENV_NAME="test"
ENV_GIVEN=0

usage() {
  cat <<'USAGE'
用法: deploy/scripts/bmini-assert-dist.sh <dist 目录> [--env prod|test]

  <dist 目录>       weapp 构建产物目录（frontend/bmini-app/dist）
  --env prod|test   域名策略（缺省 test）
  -h, --help        显示本帮助

判据：
  ① 结构   app.json 存在且 pages 非空；app.js 在；每页 .js / .wxml / .json 都在（.wxss 允许缺省）
  ② 域名   prod ⇒ migaozn.com 出现 0 次、cytda.com ≥ 1、localhost 0 次
           test ⇒ migaozn.com ≥ 1、cytda.com 0 次
  ③ 体积   主包 ≤ 单包上限 − 主包预留；每个分包 ≤ 单包上限；总包 ≤ 总包上限。
           常量唯一来源 = deploy/scripts/bmini-dist-budget.json（本脚本不写死上限）。

退出码：0 全绿 / 1 有判据不成立 / 2 用法错误 / 3 不可判定（dist 不存在·不可读·空目录·缺 python3）
USAGE
}

die_usage() {
  echo "❌ 用法错误：$*" >&2
  usage >&2
  exit 2
}

undecidable() {
  echo "⚠️  不可判定（退出码 3）：$*" >&2
  echo "   ⇒ 本脚本对这一形态**不判通过**（不可判定不得当 0 读）。" >&2
  exit 3
}

FAIL=0
ok() { echo "  ✅ $*"; }
bad() { echo "  ❌ $*"; FAIL=$(( FAIL + 1 )); }

# ── 参数 ───────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --env)
      [ $# -ge 2 ] || die_usage "--env 缺值（只接受 prod|test）"
      ENV_NAME=$2
      ENV_GIVEN=1
      shift 2
      ;;
    --env=*)
      ENV_NAME=${1#--env=}
      ENV_GIVEN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      die_usage "未知参数：$1"
      ;;
    *)
      [ -z "$DIST" ] || die_usage "多余的位置参数：$1（只接受一个 dist 目录）"
      DIST=$1
      shift
      ;;
  esac
done

case "$ENV_NAME" in
  prod|test) ;;
  *) die_usage "--env 只接受 prod|test（收到：${ENV_NAME}）" ;;
esac
[ -n "$DIST" ] || die_usage "缺少 <dist 目录> 位置参数"
# 去掉一个尾斜杠，让下面「分包归属」的相对路径前缀判得稳
DIST=${DIST%/}
[ -n "$DIST" ] || DIST=/

echo "== B 端小程序 weapp 产物断言（issue #8980）=="
echo "   dist=${DIST}"
echo "   env=${ENV_NAME}$( [ "$ENV_GIVEN" -eq 1 ] || echo '（未给 --env ⇒ 默认 test）' )"
echo ""

# ── 不可判定闸门（先于任何判据）───────────────────────────────────────────────
[ -d "$DIST" ] || undecidable "dist 目录不存在：${DIST}（先构建：scripts/bmini-experience.sh build --env <env>）"
[ -r "$DIST" ] && [ -x "$DIST" ] || undecidable "dist 目录不可读：${DIST}"
command -v python3 >/dev/null 2>&1 || undecidable "缺少 python3（解析 app.json / 摊体积需要）"
FILE_COUNT=$(find "$DIST" -type f 2>/dev/null | wc -l | tr -d ' ')
[ "${FILE_COUNT:-0}" -gt 0 ] || undecidable "dist 目录为空：${DIST}（构建没有产出，不是「产物合格」）"

# 单页 page 列表：唯一实现（下面结构判据只消费它的输出）。
# 退出码：4 = app.json 读不出 / pages 不是数组（把「结构不可信」与「pages 为空」分开报）。
page_list() {
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        data = json.load(fh)
except Exception as exc:  # noqa: BLE001 —— 任何解析失败都属「结构不可信」
    print('APP_JSON_UNREADABLE: %s' % exc, file=sys.stderr)
    raise SystemExit(4)
pages = data.get('pages')
if not isinstance(pages, list):
    print('APP_JSON_PAGES_NOT_LIST', file=sys.stderr)
    raise SystemExit(4)
for page in pages:
    print(page)
PY
}

# ── ① 结构 ─────────────────────────────────────────────────────────────────────
echo "① 结构（app.json + app.js + 每页 js/wxml/json；.wxss 允许缺省）"
APP_JSON="${DIST}/app.json"
PAGES=""
PY_RC=0
if [ -f "$APP_JSON" ]; then
  PAGES=$(page_list "$APP_JSON")
  PY_RC=$?
  if [ "$PY_RC" -ne 0 ]; then
    bad "app.json 读不出 pages（解析退出码 ${PY_RC}）—— 产物结构不可信"
    PAGES=""
  fi
else
  bad "缺少 app.json：${APP_JSON}（weapp 产物的根必须有它）"
fi

[ -f "${DIST}/app.js" ] && ok "app.js 在" || bad "缺少 app.js：${DIST}/app.js（小程序入口）"

PAGE_TOTAL=0
MISSING=0
while IFS= read -r page; do
  [ -n "$page" ] || continue
  PAGE_TOTAL=$(( PAGE_TOTAL + 1 ))
  for ext in js wxml json; do
    if [ ! -f "${DIST}/${page}.${ext}" ]; then
      bad "缺页文件 ${page}.${ext}（微信上传会在这一步失败）"
      MISSING=$(( MISSING + 1 ))
    fi
  done
done <<< "$PAGES"

if [ -f "$APP_JSON" ] && [ "$PY_RC" -eq 0 ] && [ "$PAGE_TOTAL" -eq 0 ]; then
  bad "app.json 的 pages 为空（没有任何页面可访问）"
fi
[ "$MISSING" -eq 0 ] && [ "$PAGE_TOTAL" -gt 0 ] && ok "${PAGE_TOTAL} 页，js/wxml/json 齐备（.wxss 允许缺省）"
echo ""

# ── ② 域名策略 ─────────────────────────────────────────────────────────────────
# 一个域名的出现次数（-a 把二进制当文本：产物里的图片/分包也可能含同一串；-o 逐次计数）。
count_hits() {
  grep -rao -- "$1" "$DIST" 2>/dev/null | wc -l | tr -d ' '
}

echo "② 域名策略（env=${ENV_NAME}）"
MIGAO_HITS=$(count_hits 'migaozn\.com')
CYTDA_HITS=$(count_hits 'cytda\.com')
LOCAL_HITS=$(count_hits 'localhost')
echo "   读数：migaozn.com=${MIGAO_HITS} 次 · cytda.com=${CYTDA_HITS} 次 · localhost=${LOCAL_HITS} 次"

if [ "$ENV_NAME" = "prod" ]; then
  if [ "$MIGAO_HITS" -eq 0 ]; then
    ok "prod：产物内 migaozn.com 出现 0 次（没有指向测试域）"
  else
    bad "prod：产物内 migaozn.com 出现 ${MIGAO_HITS} 次 —— 生产包不许指向测试域；构建时必须显式注入三个 TARO_APP_*（见 scripts/bmini-experience.sh build --env prod）"
  fi
  if [ "$CYTDA_HITS" -ge 1 ]; then
    ok "prod：产物内 cytda.com 出现 ${CYTDA_HITS} 次（生产域已烘进产物）"
  else
    bad "prod：产物内 cytda.com 出现 0 次 —— 这不是生产构建（三个 TARO_APP_* 一个都没注入，产物会连 localhost 或测试域）"
  fi
  # 为什么单列这一条：三件套只注入两个时，前两条判据抓不住
  # （label origin 给了 cytda ⇒ migaozn=0、cytda≥1 全绿，而 API 仍是 http://localhost:8080）。
  if [ "$LOCAL_HITS" -eq 0 ]; then
    ok "prod：产物内没有 localhost（三件套都注入了）"
  else
    bad "prod：产物内 localhost 出现 ${LOCAL_HITS} 次 —— TARO_APP_API_URL / TARO_APP_AI_API_URL 至少有一个没注入（会回落到 http://localhost:8080 / :8001）"
  fi
else
  if [ "$MIGAO_HITS" -ge 1 ]; then
    ok "test：产物内 migaozn.com 出现 ${MIGAO_HITS} 次（测试域在位）"
  else
    bad "test：产物内 migaozn.com 出现 0 次 —— 这不像测试构建（是不是把生产常量注入了测试包）"
  fi
  if [ "$CYTDA_HITS" -eq 0 ]; then
    ok "test：产物内 cytda.com 出现 0 次（没有把生产域烘进测试包）"
  else
    bad "test：产物内 cytda.com 出现 ${CYTDA_HITS} 次 —— 生产域漏进了测试包（要么这条产物其实是生产包，要么常量注错）"
  fi
fi
echo ""

# ── ③ 体积（主包 / 各分包 / 总包；常量唯一来源 = 预算文件）────────────────────
# 全部判定在 python3 里做（字节摊算 / 分包归属 / 三个上限），bash 只把结果并进 FAIL 计数。
# 为什么不在 bash 里做：bash 只有整数运算，且「哪些文件属于哪个分包」要按 `app.json` 的
# `subPackages[].root` 前缀判 —— 既容易写错，也会与判据侧的算法分叉（#8981 的病根）。
echo "③ 体积（主包 ≤ 单包上限 − 主包预留；每个分包 ≤ 单包上限；总包 ≤ 总包上限）"
echo "   常量唯一来源：${BUDGET_REL}"
VOLUME_RC=0
VOLUME_OUT=$(python3 - "$DIST" "$BUDGET_JSON" "$BUDGET_REL" "$SELF_REL" <<'PY'
"""摊体积并判定（输出即人读报告；退出码 0 绿 / 1 红）。"""
import json
import os
import sys

dist, budget_path, budget_rel, self_rel = sys.argv[1:5]


def human(n):
    return f"{n:,}"


try:
    with open(budget_path, encoding='utf-8') as fh:
        budget = json.load(fh)
except Exception as exc:  # noqa: BLE001 —— 没有常量就没有闸门 ⇒ 按判据不成立处理
    print(f"  ❌ 预算文件读不出：{budget_path}（{exc}）—— 没有常量就没有闸门（唯一来源：{budget_rel}）")
    raise SystemExit(1)

cap = int(budget['wechatPackageCapBytes'])
total_cap = int(budget['wechatTotalCapBytes'])
reserve = int(budget['mainPackageReserveBytes'])
main_limit = cap - reserve

# 分包根：`app.json` 的 `subPackages`（官方字段名）与历史拼写 `subpackages` 都认。
try:
    with open(os.path.join(dist, 'app.json'), encoding='utf-8') as fh:
        app = json.load(fh)
except Exception:  # noqa: BLE001 —— 结构判据 ① 已经报过；这里只当「没有分包」
    app = {}
roots = []
for item in (app.get('subPackages') or app.get('subpackages') or []):
    root = str((item or {}).get('root') or '').strip('/')
    if root and root not in roots:
        roots.append(root)

files = []  # (相对路径, 字节, 归属分包 root 或 None)
for dirpath, _dirnames, filenames in os.walk(dist):
    for name in filenames:
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, dist).replace(os.sep, '/')
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        owner = next((r for r in roots if rel == r or rel.startswith(r + '/')), None)
        files.append((rel, size, owner))

main_bytes = sum(size for _rel, size, owner in files if owner is None)
sub_bytes = {root: sum(size for _rel, size, owner in files if owner == root) for root in roots}
total_bytes = main_bytes + sum(sub_bytes.values())

problems = []


def top_files(predicate, limit=5):
    picked = sorted(((size, rel) for rel, size, owner in files if predicate(owner)), reverse=True)[:limit]
    return "".join(f"\n       {human(size):>12} 字节  {rel}" for size, rel in picked)


headroom = main_limit - main_bytes
print(f"   主包   {human(main_bytes):>12} 字节 / 预算 {human(main_limit)}"
      f"（= 单包上限 {human(cap)} − 主包预留 {human(reserve)}）· 余量 {human(headroom)}")
if main_bytes > main_limit:
    problems.append(
        f"  ❌ 主包 {human(main_bytes)} 字节 超预算 {human(main_bytes - main_limit)} 字节"
        f"（预算 {human(main_limit)} = 单包上限 {human(cap)} − 主包预留 {human(reserve)}）"
        f"\n       主包最大的文件：{top_files(lambda owner: owner is None)}"
        f"\n       复算：bash {self_rel} <dist> ｜ 常量：{budget_rel}"
        f"（wechatPackageCapBytes / mainPackageReserveBytes）"
    )

for root in roots:
    used = sub_bytes[root]
    print(f"   分包[{root}] {human(used):>12} 字节 / 上限 {human(cap)} · 余量 {human(cap - used)}")
    if not any(owner == root for _rel, _size, owner in files):
        print("        ⚠️  分包 root 在产物里没有任何文件（app.json 声明了它却没产出，上传会报错）")
    if used > cap:
        problems.append(
            f"  ❌ 分包[{root}] {human(used)} 字节 超上限 {human(used - cap)} 字节"
            f"（单包上限 {human(cap)}）"
            f"\n       该分包最大的文件：{top_files(lambda owner, r=root: owner == r)}"
            f"\n       复算：bash {self_rel} <dist> ｜ 常量：{budget_rel}（wechatPackageCapBytes）"
        )

print(f"   总包   {human(total_bytes):>12} 字节 / 上限 {human(total_cap)}"
      f" · 余量 {human(total_cap - total_bytes)}")
if total_bytes > total_cap:
    problems.append(
        f"  ❌ 总包 {human(total_bytes)} 字节 超上限 {human(total_bytes - total_cap)} 字节"
        f"（总包上限 {human(total_cap)} = 主包 + 全部 {len(roots)} 个分包）"
        f"\n       复算：bash {self_rel} <dist> ｜ 常量：{budget_rel}（wechatTotalCapBytes）"
    )

# 口径交代（不是判据，但必须可见、可复算 —— #8981 就是从「读数没有出处」长出来的）
rows = sorted(budget.get('calibration') or [], key=lambda r: (r or {}).get('date') or '')
if rows:
    latest = rows[-1]
    ratio = latest['wechatBytes'] / latest['distBytes']
    print(f"   微信口径：dist 字节 ≈ 开发者工具上传读数（{latest['date']} 实测 dist "
          f"{human(latest['distBytes'])} → TOTAL {human(latest['wechatBytes'])}，比值 {ratio:.3f}）"
          f"⇒ 用 dist 判即偏严，**不叠折算系数**")

for line in problems:
    print(line)
if problems:
    print("   ↳ 口径与分包规划正文：docs/deployment/bmini-experience-release.md（issue #8979 / #8981）")
    raise SystemExit(1)
print(f"  ✅ 主包 {human(main_bytes)} 字节 ≤ 预算 {human(main_limit)}"
      f"（余量 {human(headroom)} 字节 ≥ 预留 {human(reserve)} = issue #8979 的 300KB 地板）")
raise SystemExit(0)
PY
) || VOLUME_RC=$?

if [ -n "$VOLUME_OUT" ]; then
  printf '%s\n' "$VOLUME_OUT"
fi
if [ "$VOLUME_RC" -ne 0 ]; then
  FAIL=$(( FAIL + 1 ))
fi
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "❌ 产物断言失败 ${FAIL} 条（env=${ENV_NAME}，dist=${DIST}）"
  exit 1
fi
echo "✅ 产物断言全部通过（结构 / 域名策略 / 体积；env=${ENV_NAME}）"
exit 0
