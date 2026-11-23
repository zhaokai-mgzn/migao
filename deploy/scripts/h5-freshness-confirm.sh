#!/usr/bin/env bash
# C 端 H5 产物新鲜度：时间戳判「陈旧」⇒ **内容等价**复核（issue #8924）
#
# ## 为什么需要这一层
#
# `scripts/h5_freshness_guard.py` 的时间戳判据（线上 `Last-Modified` vs 源码最近改动）只是
# 「发布了没有」的**代理**。源码改动**不影响产物字节**时（devDependency 升级 / 只动 lint 配置 /
# 注释），它会判「陈旧」并要求一次发布，而发布出来的字节与线上**完全相同** —— 于是「红 → 人跑一次
# 发布 → 绿 → 下次 devDep 升级又红」成为周期性噪音（#8860/#8861/#8862/#8924 的形态）。
#
# 修法**不是**放宽：判「陈旧」之后**构建一次**，把线上产物与本次构建**逐字节比对**
# （构建确定性实测见 guard 的 docstring）：
#   · 全部一致 ⇒ guard 的 `--dist-dir` 复核给 `equivalent` ⇒ **exit 0**（不需要发布）；
#   · 有差异   ⇒ 仍 `stale` ⇒ **exit 2**，并印出**差异文件清单**（真陈旧的红一分不降）；
#   · 构建失败 ⇒ **不得**当等价（fail-closed，exit 2）。
#
# 实现体只有**一份**：两条腿（`.github/workflows/c-end-h5-publish.yml` 的 notify 档 /
# `.github/workflows/h5-freshness-guard.yml`）都调用本脚本，不各写一份口径。
#
# 用法：deploy/scripts/h5-freshness-confirm.sh <线上产物URL> [ref] [额外的 guard 参数...]
# 退出码与 guard 同口径：0 新鲜/等价、2 陈旧（判红）、3 无法判定、1 参数错。
set -uo pipefail

URL=${1:?用法: h5-freshness-confirm.sh <线上产物URL> [ref] [额外的 guard 参数...]}
REF=${2:-origin/main}
# 位置参数 3 起是「额外的 guard 参数」（如 --no-gate）。用 `shift` 而不是数组展开：
# macOS 自带 bash 3.2 在 `set -u` 下对**空数组**的 `${EXTRA[@]}` 会报 unbound variable。
if [ "$#" -ge 2 ]; then shift 2; else shift "$#"; fi
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT" || exit 1

# 构建必须与**发布腿同 env**：`TARO_APP_API_URL` / `TARO_APP_AI_API_URL` 会被 baked 进产物
# （publish 步骤显式注入它们）⇒ 复核如果不给同一组变量，字节必然不同 = 恒假红。
SITE=$(printf '%s' "$URL" | sed -e 's#^\(https\?://[^/]*\)/.*#\1#')
case "$SITE" in
  http*) : ;;
  *) echo "::error::h5-freshness-confirm：URL 里取不到站点根（$URL）⇒ 无法复核" >&2; exit 2 ;;
esac

OUT=$(python3 scripts/h5_freshness_guard.py --url "$URL" --ref "$REF" "$@")
RC=$?
printf '%s\n' "$OUT"
if [ "$RC" -ne 2 ]; then
  exit "$RC"
fi

echo "ℹ️ 时间戳判据判「陈旧」⇒ 起一次**内容等价**复核（构建 + 逐字节比对；与发布腿同 env）"
if ! ( cd frontend/mini-app \
       && npm ci --no-audit --no-fund --loglevel=error \
       && TARO_APP_API_URL="$SITE" TARO_APP_AI_API_URL="$SITE" npm run build:h5 ); then
  echo "::error::内容等价复核的构建失败 ⇒ **不能证明等价**，按陈旧处理（fail-closed；判据本体 = scripts/h5_freshness_guard.py）"
  exit 2
fi

OUT=$(python3 scripts/h5_freshness_guard.py --url "$URL" --ref "$REF" --dist-dir frontend/mini-app/dist "$@")
RC=$?
printf '%s\n' "$OUT"
exit "$RC"
