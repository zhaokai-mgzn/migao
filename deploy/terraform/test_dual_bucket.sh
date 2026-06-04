#!/bin/bash
# OSS 双 Bucket 配置验证脚本
# 用途：验证 Terraform 是否正确配置了双 Bucket 存储策略

set -e

echo "=========================================="
echo "OSS 双 Bucket 配置验证"
echo "=========================================="

# 1. 检查 Terraform 变量定义
echo ""
echo "✓ 检查变量定义..."
grep -q "variable \"permanent_bucket_name\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 permanent_bucket_name 变量定义"
    exit 1
}
grep -q "variable \"temporary_bucket_name\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 temporary_bucket_name 变量定义"
    exit 1
}
grep -q "variable \"chat_image_retention_days\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 chat_image_retention_days 变量定义"
    exit 1
}
echo "  ✓ 所有必需变量已定义"

# 2. 检查 OSS Bucket 资源定义
echo ""
echo "✓ 检查 OSS Bucket 资源..."
grep -q "resource \"alicloud_oss_bucket\" \"permanent\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 permanent bucket 资源定义"
    exit 1
}
grep -q "resource \"alicloud_oss_bucket\" \"temporary\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 temporary bucket 资源定义"
    exit 1
}
echo "  ✓ 双 Bucket 资源已定义"

# 3. 检查生命周期规则
echo ""
echo "✓ 检查生命周期规则..."
grep -q "lifecycle_rule" deploy/terraform/main.tf || {
    echo "✗ 缺少生命周期规则配置"
    exit 1
}
grep -A 5 "lifecycle_rule" deploy/terraform/main.tf | grep -q "chat/" || {
    echo "✗ 生命周期规则未针对 chat/ 目录"
    exit 1
}
echo "  ✓ 生命周期规则已配置（chat/ 目录）"

# 4. 检查 SAE 环境变量注入
echo ""
echo "✓ 检查 SAE 环境变量注入..."
grep -q "OSS_PERMANENT_BUCKET" deploy/terraform/main.tf || {
    echo "✗ 缺少 OSS_PERMANENT_BUCKET 环境变量"
    exit 1
}
grep -q "OSS_TEMPORARY_BUCKET" deploy/terraform/main.tf || {
    echo "✗ 缺少 OSS_TEMPORARY_BUCKET 环境变量"
    exit 1
}
echo "  ✓ SAE 环境变量已配置"

# 5. 检查 output 定义
echo ""
echo "✓ 检查 Terraform output..."
grep -q "output \"oss_permanent_bucket_domain\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 oss_permanent_bucket_domain output"
    exit 1
}
grep -q "output \"oss_temporary_bucket_domain\"" deploy/terraform/main.tf || {
    echo "✗ 缺少 oss_temporary_bucket_domain output"
    exit 1
}
echo "  ✓ 所有必需 output 已定义"

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
