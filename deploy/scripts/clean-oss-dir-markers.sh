#!/bin/bash
# 清理 OSS bucket 中所有以 "/" 结尾的空目录标记 object
#
# 背景：
#   - ossutil/aliyun-cli 在 cp 上传时会为每个目录创建一个 0 字节的 placeholder
#     object（如 "dashboard/"、"products/"），用以在 OSS 控制台展示"目录"。
#   - 这些标记对象会"遮挡" OSS 静态网站托管中 IndexDocument + SupportSubDir
#     的子目录路由：当请求 "/dashboard/" 时，OSS 优先匹配到空 object 而不是
#     fallback 到 "dashboard/index.html"，导致返回空内容或异常。
#
# 用法：
#   ./clean-oss-dir-markers.sh [bucket-name] [region] [profile]
#
# 示例：
#   ./clean-oss-dir-markers.sh ai-customer-service-admin-dev cn-hangzhou oss-bucket-put-object
#
# 注意：
#   - 仅在每次完整发布后运行一次即可，CI 中可纳入部署流水线最后一步。
#   - 不会删除真实文件（仅删除 key 以 "/" 结尾且大小为 0 的占位 object）。

set -uo pipefail

BUCKET="${1:-ai-customer-service-admin-dev}"
REGION="${2:-cn-hangzhou}"
PROFILE="${3:-oss-bucket-put-object}"

LIST_FILE="${TMPDIR:-/tmp}/oss-dir-markers-$$.txt"
trap "rm -f $LIST_FILE" EXIT

echo "[clean-oss-dir-markers] bucket=$BUCKET region=$REGION profile=$PROFILE"
echo "[clean-oss-dir-markers] listing dir-marker objects ..."

aliyun --profile "$PROFILE" oss ls "oss://$BUCKET/" \
  --short-format \
  --region "$REGION" \
  --limited-num 50000 \
  2>/dev/null | awk '/\/$/' > "$LIST_FILE"

TOTAL=$(wc -l < "$LIST_FILE" | tr -d ' ')
echo "[clean-oss-dir-markers] found $TOTAL dir-marker objects"

if [ "$TOTAL" -eq 0 ]; then
  echo "[clean-oss-dir-markers] nothing to do, exit"
  exit 0
fi

COUNT=0
FAIL=0
while IFS= read -r url; do
  [ -z "$url" ] && continue
  if aliyun --profile "$PROFILE" oss rm "$url" --region "$REGION" --force >/dev/null 2>&1; then
    COUNT=$((COUNT + 1))
  else
    echo "[clean-oss-dir-markers] FAIL: $url"
    FAIL=$((FAIL + 1))
  fi
done < "$LIST_FILE"

echo "[clean-oss-dir-markers] deleted=$COUNT failed=$FAIL"
exit "$FAIL"
