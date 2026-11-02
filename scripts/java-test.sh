#!/usr/bin/env bash
# =============================================================================
# java-test.sh — Java 定点判据的**唯一可信入口**（issue #6495）
#
# 病（2026-11-03 本机实跑，读数见 docs/wiki/Development.md 的「Java 定点判据」节）：
#   ① `target/surefire-reports/<fqn>.txt` 的 `Tests run:` 在 @Nested 类上**恒报 0**
#      （实测：同一次运行 XML/console 15 条，该摘要写 0）⇒ 拿它判「空跑 / 通过」都会误诊，
#      issue #6495 的原始读数就是这么来的；
#   ② `-Dtest=<外层类>#<方法>`，方法声明在 `@Nested` 内 ⇒ **真·空跑**：
#      `Tests run: 0 / BUILD SUCCESS / exit=0`，且不产出 XML。
#
# 本入口：选择器自动纠正（②）+ 只信 XML + 断言 `Tests run > 0`（0 = 红）。
#
# 用法:
#   ./scripts/java-test.sh OssConfigTest                      # 类（@Nested 会被真跑到，实测 15/15）
#   ./scripts/java-test.sh 'AgentBatchServiceTest$Create#persistsPreviewWithOldValueCollectedFromDb'
#   ./scripts/java-test.sh AgentBatchServiceTest#someNestedMethod   # 会被自动纠正并打印原因
#   ./scripts/java-test.sh --check OssConfigTest              # 只解析/纠正，不跑
#   ./scripts/java-test.sh OssConfigTest -- -Dsurefire.rerunFailingTestsCount=1   # 额外 mvn 参数
#   MIGAO_MVN_OFFLINE=0 ./scripts/java-test.sh OssConfigTest  # 冷 m2 缓存时走联网（默认离线 `-o`）
#
# 退出码：0 真跑且绿 / 1 红（空跑 / 失败 / @Nested 没跑到）/ 2 用法 / 3 不可判定
#
# 判定逻辑全在 scripts/java_test_readings.py（同源判据：tests/unit_ci_workflows/test_java_nested_pointed_run_guard.py）
# —— 本文件只做入口，不复制口径。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/java_test_readings.py" --root "$ROOT" "$@"
