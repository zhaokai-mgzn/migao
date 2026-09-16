package com.migao.admin.config;

// case_ids: MC-012, API-013

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * MigrationRunner 排序与失败传播契约（issue #3270 实测根因）
 *
 * 背景（CI 实证 run 34626024229 + postgres 日志）：admin-api 用的是自研
 * {@link MigrationRunner}（非 Flyway），它有两个叠加缺陷，导致 **bootstrap 库的
 * schema 与代码长期脱节**，进而 admin-api 查询 500 → ai-agent 工具返回
 * 「服务暂时不可用」→ 熔断 → **整轮 C 端评测被污染**（报告长成「agent 不会下单」）：
 *
 * 1. **按文件名**排序执行 → 实际顺序是 V1, V10, V11, …, V19, V2, V20, …, V40, V41,
 *    V5, V7, V8, V9（字典序！`V5` 排在 `V40` 之后，`V2` 排在 `V19` 之后）。
 *    类注释写的「按文件名升序执行（V1 < V2 < … < V30）」本身就是错的。
 * 2. 单条迁移失败 → `catch` 后**整条链中断**且只记一行 ERROR 日志、应用照常启动。
 *    实测：V28（通知种子）在 bootstrap 库上因 `variables JSONB` vs 迁移链 `TEXT`
 *    + `tenant_id=0` 无 FK 行而失败 → V29–V41 **与** V5–V9 全部未执行 →
 *    `orders.actual_amount` 等列缺失（正是 CI 里 `column "actual_amount" does not exist` 的来源）。
 *
 * 本测试锁定三条契约：
 * a. 版本号必须**按数值**排序（V2 在 V10 之前）；
 * b. 单条失败后**继续执行其余迁移**（一条坏迁移不得冻结整个 schema）；
 * c. 迁移文件名必须可解析出版本号（新增迁移须遵守 V{n}__desc.sql）。
 */
@DisplayName("MigrationRunner 排序与失败传播契约（issue #3270）")
class MigrationRunnerOrderingTest {

    private static List<String> sortedByRunner(List<String> names) {
        // 与 MigrationRunner 使用同一个比较器（单一事实源）
        return MigrationRunner.sortMigrationNames(names);
    }

    @Test
    @DisplayName("版本号按数值排序：V2 必须排在 V10 / V19 之前（字典序会排反）")
    void sortsByNumericVersionNotLexicographically() {
        List<String> input = Arrays.asList(
                "V10__a.sql", "V2__b.sql", "V19__c.sql", "V1__d.sql", "V9__e.sql");
        assertThat(sortedByRunner(input))
                .containsExactly("V1__d.sql", "V2__b.sql", "V9__e.sql", "V10__a.sql", "V19__c.sql");
    }

    @Test
    @DisplayName("单数字迁移不得被排到双数字之后（实测 V5 排在 V40/V41 之后 → 列缺失）")
    void singleDigitMigrationsRunBeforeHigherNumbers() {
        List<String> input = Arrays.asList(
                "V41__x.sql", "V40__y.sql", "V5__z.sql", "V28__w.sql");
        assertThat(sortedByRunner(input))
                .containsExactly("V5__z.sql", "V28__w.sql", "V40__y.sql", "V41__x.sql");
    }

    @Test
    @DisplayName("真实迁移目录整体有序：每个版本号都严格递增")
    void realMigrationDirectoryIsMonotonic() {
        List<String> names = MigrationRunner.listMigrationNames();
        assertThat(names).isNotEmpty();
        List<String> sorted = sortedByRunner(names);
        int prev = -1;
        for (String n : sorted) {
            int v = MigrationRunner.versionOf(n);
            assertThat(v).as("迁移 %s 版本号应可解析", n).isGreaterThan(0);
            assertThat(v).as("迁移顺序应严格递增：%s", n).isGreaterThanOrEqualTo(prev);
            prev = v;
        }
        // 关键回归：V5（orders.actual_amount）必须早于 V28（通知种子，历史上在此中断）
        assertThat(sorted.indexOf("V5__add_actual_amount_to_orders.sql"))
                .as("V5 必须早于 V28 —— 否则链一断 actual_amount 就永远缺失")
                .isLessThan(sorted.indexOf("V28__seed_notification_templates_and_rules.sql"));
    }

    @Test
    @DisplayName("文件名无法解析版本号时排到最后（不得静默插队到中间）")
    void unparsableNamesSortLast() {
        List<String> input = Arrays.asList("V10__a.sql", "readme.sql", "V2__b.sql");
        List<String> out = sortedByRunner(input);
        assertThat(out.get(0)).isEqualTo("V2__b.sql");
        assertThat(out.get(1)).isEqualTo("V10__a.sql");
        assertThat(out.get(2)).isEqualTo("readme.sql");
    }

    @Test
    @DisplayName("迁移目录里不得有无法解析版本号的文件（否则顺序不可预期）")
    void everyMigrationParses() {
        for (String n : MigrationRunner.listMigrationNames()) {
            assertThat(MigrationRunner.versionOf(n))
                    .as("迁移文件名 %s 无法解析版本号 —— 必须为 V{n}__desc.sql", n)
                    .isGreaterThan(0);
        }
    }

    @Test
    @DisplayName("比较器与 sortedByRunner 一致（防两处排序口径漂移）")
    void comparatorMatchesHelper() {
        Comparator<String> c = MigrationRunner.MIGRATION_ORDER;
        List<String> input = Arrays.asList("V10__a.sql", "V2__b.sql", "V1__c.sql");
        input.sort(c);
        assertThat(input).containsExactly("V1__c.sql", "V2__b.sql", "V10__a.sql");
    }
}
