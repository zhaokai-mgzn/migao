#!/usr/bin/env bash
# 生产部署后冒烟（六面 / 版本身份 / 域名泄漏）。**失败即判红**，不许「打印一下就过」。
#
# 用法：
#   REL_SHA=<40位> bash deploy/scripts/prod-smoke.sh
#   REL_SHA=... SMOKE_BASE=cytda.com bash deploy/scripts/prod-smoke.sh   # 换域名（演练/测试）
#
# 退出码：0 = 全通过；1 = 有面失败；3 = 无法判定（如版本身份取不到）——**3 不得当 0 读**。
#
# 为什么这三类：
#   ① 六面 200 —— 静态根为空 / nginx 渲染错域 / 蓝绿切流失败，都表现为某面非 200（实测事故形态）；
#   ② 版本身份 —— 「部署成功」不等于「跑的是这一版」；`/api/version` 与 `/version` 必须逐字等于发布身份；
#   ③ 域名泄漏 —— 生产页面里出现 `migaozn` 就说明构建用了测试基址（实测事故形态，见 issue #8966）。
#
# 边界（如实登记）：本脚本只探「能不能用」，**不验业务正确性**（那是回归 R1~R6 的活）。
set -uo pipefail

BASE="${SMOKE_BASE:-cytda.com}"
REL_SHA="${REL_SHA:-}"
FAILED=0
UNKNOWN=0

say() { printf '%-46s %s\n' "$1" "$2"; }

# 面清单：路径|期望（允许 200；www 归一化允许 308/301 → 跟随后必须 200）
FACES="
https://${BASE}/|200
https://www.${BASE}/|200
https://merchant.${BASE}/login|200
https://api.${BASE}/api/version|200
https://ai-api.${BASE}/version|200
https://app.${BASE}/|200
https://app.${BASE}/b/|200
https://app.${BASE}/w/|200
"

echo "== ① 八面（跟随重定向）=="
while IFS='|' read -r url expect; do
  [ -n "$url" ] || continue
  code=$(curl -sL -o /dev/null -w '%{http_code}' -m 20 "$url" 2>/dev/null || echo 000)
  if [ "$code" = "$expect" ]; then
    say "$url" "✅ $code"
  else
    say "$url" "❌ $code（期望 $expect）"
    FAILED=$((FAILED + 1))
  fi
done <<EOF
$FACES
EOF

echo
echo "== ② 版本身份（必须 == 发布身份）=="
if [ -z "$REL_SHA" ]; then
  say "REL_SHA" "⚠️ 未提供 ⇒ 本项**不可判定**（不当通过）"
  UNKNOWN=$((UNKNOWN + 1))
else
  for pair in "api.${BASE}/api/version|${REL_SHA}" "ai-api.${BASE}/version|${REL_SHA}"; do
    host="${pair%%|*}"; want="${pair##*|}"
    got=$(curl -s -m 20 "https://${host}" 2>/dev/null | tr -d ' \n' | grep -o '"sha":"[a-f0-9]\{7,40\}"' | head -1 | cut -d'"' -f4)
    if [ -z "$got" ]; then
      say "https://${host}" "⚠️ 取不到 sha ⇒ 不可判定"
      UNKNOWN=$((UNKNOWN + 1))
    elif [ "$got" = "$want" ]; then
      say "https://${host}" "✅ ${got:0:7} == 发布身份"
    else
      say "https://${host}" "❌ ${got:0:7} ≠ 发布身份 ${want:0:7}"
      FAILED=$((FAILED + 1))
    fi
  done
fi

echo
echo "== ③ 域名泄漏（生产页面不得出现 migaozn）=="
for url in "https://${BASE}/" "https://www.${BASE}/sitemap.xml" "https://www.${BASE}/robots.txt" "https://app.${BASE}/b/js/app.js"; do
  body=$(curl -sL -m 30 "$url" 2>/dev/null)
  code=$(curl -sL -o /dev/null -w '%{http_code}' -m 20 "$url" 2>/dev/null || echo 000)
  hits=$(printf '%s' "$body" | grep -c 'migaozn\.com' 2>/dev/null || true)
  hits=${hits:-0}
  if [ "$code" != "200" ]; then
    say "$url" "⚠️ $code ⇒ 拿不到内容，不可判定"
    UNKNOWN=$((UNKNOWN + 1))
  elif [ "$hits" = "0" ]; then
    say "$url" "✅ 0 处"
  else
    say "$url" "❌ ${hits} 处 migaozn"
    FAILED=$((FAILED + 1))
  fi
done

echo
echo "合计：失败 ${FAILED} 项 / 不可判定 ${UNKNOWN} 项"
if [ "$FAILED" -gt 0 ]; then
  echo "::error::生产冒烟未通过（${FAILED} 项失败）"
  exit 1
fi
if [ "$UNKNOWN" -gt 0 ]; then
  echo "::warning::有 ${UNKNOWN} 项不可判定（**不是通过**）"
  exit 3
fi
echo "✅ 生产冒烟通过"
