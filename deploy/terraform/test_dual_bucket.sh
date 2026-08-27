#!/bin/bash
# OSS 单 Bucket 配置验证脚本
# 用途：验证 Terraform 仅声明永久 Bucket（临时 Bucket ai-customer-service-chat-dev
#       已于 2026-08-27 删除，双 Bucket 方案废弃，聊天图片与商品图片共用永久 Bucket）

set -e

echo "=========================================="
echo "OSS 单 Bucket 配置验证"
echo "=========================================="

# 1. 检查 Terraform 变量定义
echo ""
echo "✓ 检查变量定义..."
grep -q "variable \"permanent_bucket_name\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 permanent_bucket_name 变量定义"
    exit 1
}
grep -q "variable \"temporary_bucket_name\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 temporary_bucket_name 变量定义（废弃变量保留为空默认值）"
    exit 1
}
grep -A 3 "variable \"temporary_bucket_name\"" deploy/terraform/main.tf | grep -q 'default     = ""' || {
    echo "✗ temporary_bucket_name 默认值必须为空（临时 Bucket 已删除）"
    exit 1
}
echo "  ✓ 变量定义正确（temporary 保留为空默认值）"

# 2. 检查 OSS Bucket 资源定义（仅 permanent）
echo ""
echo "✓ 检查 OSS Bucket 资源..."
grep -q "resource \"alicloud_oss_bucket\" \"permanent\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 permanent bucket 资源定义"
    exit 1
}
if grep -q "resource \"alicloud_oss_bucket\" \"temporary\"" deploy/terraform/main.tf; then
    echo "✗ temporary bucket 资源仍存在，应删除（临时 Bucket 已于 2026-08-27 删除）"
    exit 1
fi
echo "  ✓ 仅 permanent Bucket 资源已定义"

# 3. 检查临时 Bucket 生命周期规则已移除
echo ""
echo "✓ 检查生命周期规则..."
if grep -q "lifecycle_rule" deploy/terraform/main.tf; then
    echo "✗ 不应存在临时 Bucket 生命周期规则（chat/ 自动过期策略随临时 Bucket 一并废弃）"
    exit 1
fi
echo "  ✓ 无临时 Bucket 生命周期规则"

# 4. 检查 OSS 环境变量注入（历史 SAE 时代；2026-08-14 起为 SWAS .env.admin-api）
echo ""
echo "✓ 检查 OSS 环境变量注入（main.tf）..."
grep -q "OSS_PERMANENT_BUCKET" deploy/terraform/main.tf || {
    echo "✗ 缺少 OSS_PERMANENT_BUCKET 环境变量"
    exit 1
}
if grep -q "\"OSS_TEMPORARY_BUCKET\"" deploy/terraform/main.tf; then
    echo "✗ OSS_TEMPORARY_BUCKET 环境变量仍存在，应删除（临时 Bucket 已删除）"
    exit 1
fi
echo "  ✓ OSS 环境变量正确（仅永久 Bucket）"

# 5. 检查 output 定义
echo ""
echo "✓ 检查 Terraform output..."
grep -q "output \"oss_permanent_bucket_domain\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 oss_permanent_bucket_domain output"
    exit 1
}
if grep -q "output \"oss_temporary_bucket_domain\"" deploy/terraform/main.tf; then
    echo "✗ oss_temporary_bucket_domain output 仍存在，应删除"
    exit 1
fi
echo "  ✓ output 正确（仅 permanent 域名）"

# 6. 检查 admin_frontend bucket 已重命名
echo ""
echo "✓ 检查 admin_frontend bucket 重命名..."
if grep -q "resource \"alicloud_oss_bucket\" \"admin_frontend\"" deploy/terraform/main.tf; then
    echo "✗ 旧的 admin_frontend bucket 资源仍然存在，应重命名为 permanent"
    exit 1
fi
echo "  ✓ admin_frontend 已重命名为 permanent"

echo ""
echo "=========================================="
echo "✓ 所有验证通过！"
echo "=========================================="
