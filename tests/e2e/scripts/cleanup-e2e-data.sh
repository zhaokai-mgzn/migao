#!/bin/bash
# E2E 数据清理快捷脚本
# 用法: ./e2e/scripts/cleanup-e2e-data.sh
set -e
cd "$(dirname "$0")/../.."
echo "🧹 清理 E2E 测试脏数据..."
npx tsx e2e/scripts/cleanup-e2e-data.ts "$@"
