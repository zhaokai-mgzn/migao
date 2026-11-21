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
#   ② **体积没有闸门**：主包 2,079,753 字节 / 微信上限 2,097,152，只剩 17KB。本地构建不报，
#      只在上传那一刻爆（分包规划见 #8979）。
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
#   | ③ | **体积**：全部文件合计 < 微信上限 2097152 的 90%（= **1887436** 字节，整数运算）；
#   |   | 超限时打印顶层条目占比 top5，指出该往哪儿砍 | 塞一个 1.9MB 的夹具 ⇒ 红 |
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
#   生产包由 `scripts/bmini-experience.sh build --env prod` 在发布时构建并断言。
#
# 边界（照实登记，不粉饰）：
#   · **判的是本仓 dist 的字节，不是微信后台的包体读数**。微信按自己的规则统计主包（区分主包 /
#     分包），本脚本目前**没有分包**（#8979 未落地）⇒ 直接断言 dist 全量；分包一旦引入，
#     必须在下面「体积」段按 `app.json` 的 `subPackages[].root` 剔除子包，否则闸门会比微信更严
#     （偏严是安全方向，但会误红 —— 届时改这里，别改期望值）。
#     🔴 **两者不是同一个数**（本单实测，已登记为独立 issue）：同一份产物 dist = 1,459,140 字节时
#     微信后台报 2,079,753 字节（≈ 1.425 倍）⇒ 「dist 闸门绿」不等于「微信还有余量」。因此体积段
#     额外打一行**折算读数**（不是判据，不改退出码），见下面「体积」段的说明。
#   · 判不了「产物能不能跑起来」（那要真机/模拟器），也判不了微信后台的「服务器域名」白名单。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

# 微信小程序单包上限（字节）。与 issue #8979 的分包规划口径同一个数字。
CAP_BYTES=2097152
# 留 10% 缓冲：闸门 = 上限 × 90%（bash 没有浮点 ⇒ 整数运算 2097152*90/100 = 1887436）
RATIO_PERCENT=90

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
  ③ 体积   全部文件合计 < 2097152 × 90% = 1887436 字节；超限打印顶层条目占比 top5

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
# 去掉一个尾斜杠，让下面「顶层条目相对路径」的 ${entry#${DIST}/} 拼接形态稳定
DIST=${DIST%/}
[ -n "$DIST" ] || DIST=/

echo "== B 端小程序 weapp 产物断言（issue #8980）=="
echo "   dist=${DIST}"
echo "   env=${ENV_NAME}$( [ "$ENV_GIVEN" -eq 1 ] || echo '（未给 --env ⇒ 默认 test）' )"
echo ""

# ── 不可判定闸门（先于任何判据）───────────────────────────────────────────────
[ -d "$DIST" ] || undecidable "dist 目录不存在：${DIST}（先构建：scripts/bmini-experience.sh build --env <env>）"
[ -r "$DIST" ] && [ -x "$DIST" ] || undecidable "dist 目录不可读：${DIST}"
command -v python3 >/dev/null 2>&1 || undecidable "缺少 python3（解析 app.json 的 pages 需要）"
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

# ── ③ 体积 ─────────────────────────────────────────────────────────────────────
echo "③ 体积（主包 < 微信上限 ${CAP_BYTES} 的 ${RATIO_PERCENT}%）"
LIMIT_BYTES=$(( CAP_BYTES * RATIO_PERCENT / 100 ))
TOTAL_BYTES=$(find "$DIST" -type f -exec cat {} + 2>/dev/null | wc -c | tr -d ' ')
TOTAL_BYTES=${TOTAL_BYTES:-0}
echo "   主包合计 ${TOTAL_BYTES} 字节 / 闸门 ${LIMIT_BYTES} 字节（微信上限 ${CAP_BYTES}）"
# 🔴 为什么要多打一行「折算读数」（本单实测出来的边界，别把它当装饰）：
#   本脚本判的是 **dist 字节**，微信后台报的是**它自己编译打包后**的包体 —— 2026-11-21 首次体验版
#   的**同一份**产物实测：dist = 1,459,140 字节 ⇒ 微信后台 = 2,079,753 字节（≈ **1.425 倍**）。
#   ⇒ 「闸门绿」**不代表**微信还有余量：那次真实余量只有 17KB，而本闸门当时还剩 43 万字节。
#   这一行是**读数、不是判据**（折算比只实测过一版，且随产物构成漂移）—— 它再吓人也不改变退出码；
#   用途 = 让人一眼看见「该不该先做分包（#8979）」，而不是把绿读成安全。
WECHAT_RATIO_PERMILLE=1425   # 1.425，千分数（bash 只有整数运算）
WECHAT_FOLDED=$(( TOTAL_BYTES * WECHAT_RATIO_PERMILLE / 1000 ))
echo "   参考折算（不是判据）：×1.425 ⇒ 微信后台包体约 ${WECHAT_FOLDED} 字节 / 上限 ${CAP_BYTES}（余量 $(( CAP_BYTES - WECHAT_FOLDED )) 字节；出处 = 2026-11-21 实测 dist 1,459,140 → 微信 2,079,753）"
if [ "$WECHAT_FOLDED" -gt "$CAP_BYTES" ]; then
  echo "   ⚠️  折算读数已超微信上限：真机上传会失败，而本脚本的闸门（${LIMIT_BYTES}）**仍可能判绿** —— 先做分包（issue #8979）"
fi

# 超限时的归因：顶层条目（文件与目录）逐项占总量比 top5 —— 指出该往哪儿砍。
print_top_entries() {
  local entry size
  echo "   顶层条目占比 top5（按字节）："
  {
    while IFS= read -r entry; do
      [ -e "$entry" ] || continue
      size=$(find "$entry" -type f -exec cat {} + 2>/dev/null | wc -c | tr -d ' ')
      printf '%s\t%s\n' "${size:-0}" "${entry#"${DIST}"/}"
    done < <(find "$DIST" -mindepth 1 -maxdepth 1 2>/dev/null | LC_ALL=C sort)
  } | sort -rn -k1 | head -5 \
    | awk -v total="${TOTAL_BYTES}" '{ printf "     %10d 字节  %5.1f%%  %s\n", $1, ($1 * 100 / total), $2 }'
}

if [ "$TOTAL_BYTES" -ge "$LIMIT_BYTES" ]; then
  bad "主包 ${TOTAL_BYTES} 字节 ≥ 闸门 ${LIMIT_BYTES} 字节（距微信上限只剩 $(( CAP_BYTES - TOTAL_BYTES )) 字节）—— 上传会失败或下一版加不进功能（分包规划见 issue #8979）"
  print_top_entries
else
  ok "主包 ${TOTAL_BYTES} 字节 < 闸门 ${LIMIT_BYTES} 字节（对微信上限余量 $(( CAP_BYTES - TOTAL_BYTES )) 字节）"
fi
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "❌ 产物断言失败 ${FAIL} 条（env=${ENV_NAME}，dist=${DIST}）"
  exit 1
fi
echo "✅ 产物断言全部通过（结构 / 域名策略 / 体积；env=${ENV_NAME}）"
exit 0
