#!/bin/bash
# 应用 OSS 静态网站托管配置到指定 bucket
#
# 修复历史：
#   - 早期使用 ErrorDocument=index.html + HttpStatus=200 出现误展示首页问题，
#     一度改为 ErrorDocument=404.html + HttpStatus=404；但该配置不支持 Next.js
#     SPA 动态路由（如 /products/:id/edit），访问会返回真实 404。
#   - 当前版本配置（恢复 SPA 回退 + 客户端路由守卫）：
#       IndexDocument: index.html, SupportSubDir=true, Type=0(Redirect)
#       ErrorDocument: index.html, HttpStatus=200
#     OSS 找不到文件时回退到 index.html，由 Next.js 客户端路由接管动态路由；
#     受保护页面（如 /dashboard/）需依赖前端客户端守卫做鉴权与跳转，
#     不能再依靠服务端 404 阻止未授权访问。
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
