#!/usr/bin/env bash
# check-jacoco-coverage.sh — 解析 JaCoCo CSV，对 PR 变更的 Java 文件检查行覆盖率
#
# 用法:
#   CHANGED_FILES="comma-or-newline-separated" bash scripts/ci/check-jacoco-coverage.sh
#
# 环境变量:
#   CHANGED_FILES          PR 中变更的文件列表（空格或换行分隔）
#   JACOCO_CSV             jacoco.csv 路径（默认 backend/admin-api/target/site/jacoco/jacoco.csv）
#   COV_THRESHOLD_NEW      新增文件覆盖率阈值（默认 80）
#   COV_THRESHOLD_EXISTING 已有文件覆盖率阈值（默认 60）
#
# 输出:
#   - Markdown 表格到 GITHUB_STEP_SUMMARY
#   - WARNINGS 计数到 GITHUB_OUTPUT
#   - 退出码 0（检查完成，有问题时通过输出变量报告）
set -euo pipefail

JACOCO_CSV="${JACOCO_CSV:-backend/admin-api/target/site/jacoco/jacoco.csv}"
COV_THRESHOLD_NEW="${COV_THRESHOLD_NEW:-80}"
COV_THRESHOLD_EXISTING="${COV_THRESHOLD_EXISTING:-60}"

if [ ! -f "$JACOCO_CSV" ]; then
  echo "::warning::JaCoCo CSV 不存在 ($JACOCO_CSV)，跳过覆盖率检查"
  echo "COV_WARNINGS=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# 只处理 Java 源文件（非测试文件）
JAVA_FILES=$(echo "$CHANGED_FILES" | tr ' ' '\n' | grep -E '^backend/admin-api/src/main/java/.*\.java$' || true)

if [ -z "$JAVA_FILES" ]; then
  echo "## 🔬 JaCoCo 覆盖率 — 无 Java 源文件变更" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  echo "COV_WARNINGS=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

WARNINGS=0
WARN_DETAIL=""

# 写 Markdown 表头
echo "## 🔬 JaCoCo 行覆盖率检查" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "| 文件 | 行覆盖 | 阈值 | 状态 |" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "|------|--------|------|------|" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

# 检查文件是否在 main 分支已存在（新增 vs 已有）
is_new_file() {
  local file="$1"
  # 检查该文件在 main 中是否存在
  if git cat-file -e "origin/main:$file" 2>/dev/null; then
    return 1  # 存在 → 已有文件
  else
    return 0  # 不存在 → 新增文件
  fi
}

# 遍历每个 Java 变更文件
while IFS= read -r java_file; do
  [ -z "$java_file" ] && continue

  # 提取包名和类名
  # 路径格式: backend/admin-api/src/main/java/com/migao/admin/{subpkg}/{ClassName}.java
  rel_path="${java_file#backend/admin-api/src/main/java/}"
  pkg=$(dirname "$rel_path" | tr '/' '.')
  class=$(basename "$java_file" .java)

  # 在 JaCoCo CSV 中查找该类
  # CSV 格式: GROUP,PACKAGE,CLASS,...,LINE_MISSED,LINE_COVERED,...
  csv_line=$(grep -F ",$pkg,$class," "$JACOCO_CSV" 2>/dev/null || true)

  if [ -z "$csv_line" ]; then
    # 该类在 CSV 中不存在（可能是配置类、接口等无执行代码的类）
    echo "| \`$rel_path\` | N/A | — | ℹ️ 无执行代码 |" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    continue
  fi

  # 解析列: LINE_MISSED=col8, LINE_COVERED=col9 (1-indexed)
  line_missed=$(echo "$csv_line" | cut -d',' -f8)
  line_covered=$(echo "$csv_line" | cut -d',' -f9)

  total=$((line_missed + line_covered))
  if [ "$total" -eq 0 ]; then
    echo "| \`$rel_path\` | N/A | — | ℹ️ 无可覆盖行 |" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    continue
  fi

  coverage=$(( line_covered * 100 / total ))

  # 判断阈值
  if is_new_file "$java_file"; then
    threshold=$COV_THRESHOLD_NEW
    file_type="新增"
  else
    threshold=$COV_THRESHOLD_EXISTING
    file_type="已有"
  fi

  if [ "$coverage" -lt "$threshold" ]; then
    echo "| \`$rel_path\` | ${coverage}% | ${threshold}% (${file_type}) | ⚠️ 低于阈值 |" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    WARN_DETAIL="${WARN_DETAIL}\n- \`$rel_path\`: ${coverage}% 行覆盖率（阈值 ${threshold}%）"
    WARNINGS=$((WARNINGS + 1))
  else
    echo "| \`$rel_path\` | ${coverage}% | ${threshold}% | ✅ |" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  fi

done <<< "$JAVA_FILES"

# 输出汇总
if [ "$WARNINGS" -gt 0 ]; then
  {
    echo ""
    echo "## ⚠️ ${WARNINGS} 个文件行覆盖率低于阈值"
    echo -e "$WARN_DETAIL"
    echo ""
    echo "> 📋 新增文件需 ≥${COV_THRESHOLD_NEW}%，已有文件需 ≥${COV_THRESHOLD_EXISTING}%"
    echo "> 此检查为**警告**，暂不阻塞合并。请在测试中覆盖新增代码路径。"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
else
  echo "" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  echo "## ✅ 所有 Java 文件行覆盖率达标" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
fi

echo "COV_WARNINGS=$WARNINGS" >> "${GITHUB_OUTPUT:-/dev/null}"
