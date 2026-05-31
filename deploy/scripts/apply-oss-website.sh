#!/bin/bash
# 应用 OSS 静态网站托管配置到指定 bucket
#
# 修复历史：
#   - 早期使用 ErrorDocument=index.html + HttpStatus=200 出现误展示首页问题，
#     一度改为 ErrorDocument=404.html + HttpStatus=404；但该配置不支持 Next.js
#     SPA 动态路由（如 /products/:id/edit），访问会返回真实 404。
#   - 后续恢复 ErrorDocument=index.html+200 + 客户端守卫鉴权。但因为根 index.html
#     属于 (corporate) 路由组，访问未预渲染的动态路由会回退渲染营销首页，
#     破坏 /products/:id/edit/ 等 dashboard 路由。
#   - 当前版本配置（SPA 路由分派器方案）：
#       IndexDocument: index.html, SupportSubDir=true, Type=0(Redirect)
#       ErrorDocument: _spa-fallback.html, HttpStatus=200
#     _spa-fallback.html 由 admin-web 构建时通过 scripts/generate-spa-fallback.js
#     自动生成，包含动态路由模式 → 占位 HTML 的映射。OSS 命中 ErrorDocument 时
#     先服务该分派器，由其内联脚本将原始 URL 透传到对应占位页（query=__spa_path），
#     占位页加载后由根 layout 中的早期脚本通过 history.replaceState 还原 URL，
#     再由前端组件正常渲染 dashboard 内容；受保护页面继续依赖客户端守卫鉴权。
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
