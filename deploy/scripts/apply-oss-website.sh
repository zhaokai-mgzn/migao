#!/bin/bash
# 应用 OSS 静态网站托管配置到指定 bucket
#
# 修复历史：
#   - 历史配置 ErrorDocument=index.html + HttpStatus=200，导致任何 404 都回退
#     到首页 HTML，浏览器看到"营销首页"取代受保护的 /dashboard/ 等路由。
#   - 新版本配置：
#       IndexDocument: index.html, SupportSubDir=true, Type=0(Redirect)
#       ErrorDocument: 404.html, HttpStatus=404
#     从而 /dashboard/ 会真正路由到 dashboard/index.html，错误请求返回 404
#     而不是误展示首页内容。
#
# ⚠️ 前置条件：
#   - OSS website hosting 仅在请求路径走 "bucket.oss-website-{region}.aliyuncs.com"
#     时生效；通过自定义域名（CNAME）直连 bucket REST endpoint 时，SubDir
#     路由不会生效（会返回 NoSuchKey 404）。生产环境推荐使用 Aliyun CDN，
#     源站填写 OSS 静态网站托管域名（website endpoint），由 CDN 透传 website
#     hosting 行为到自定义域名。详见 docs/deployment/deployment-aliyun.md。
#
# 用法：
#   ./apply-oss-website.sh [bucket-name] [region] [profile] [config-xml]

set -uo pipefail

BUCKET="${1:-ai-customer-service-admin-dev}"
REGION="${2:-cn-hangzhou}"
PROFILE="${3:-oss-bucket-put-object}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_XML="${4:-$SCRIPT_DIR/../oss-website.xml}"

if [ ! -f "$CONFIG_XML" ]; then
  echo "[apply-oss-website] ERROR: config xml not found: $CONFIG_XML" >&2
  exit 1
fi

echo "[apply-oss-website] bucket=$BUCKET region=$REGION profile=$PROFILE"
echo "[apply-oss-website] applying $CONFIG_XML ..."

aliyun --profile "$PROFILE" oss website "oss://$BUCKET" \
  "$CONFIG_XML" \
  --region "$REGION" \
  --method put

echo "[apply-oss-website] verifying current config ..."
aliyun --profile "$PROFILE" oss website "oss://$BUCKET" \
  --region "$REGION" \
  --method get

echo "[apply-oss-website] done"
