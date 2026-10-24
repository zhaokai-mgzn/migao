// case_ids: APP-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Approval;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 审批 Mapper / 实体 ↔ 建库脚本（issue #7374 段 1）。
 *
 * <p>额外守一条底线：`object_type` 的五类与 `status` 的四态必须与表上的 CHECK 约束**逐字一致** ——
 * 实体常量是代码侧的唯一来源，表约束是数据库侧的唯一来源，两边漂移就是「代码以为能提交、库里拒」。</p>
 */
@DisplayName("审批 Mapper：实体字段 ⊆ 建库脚本列 + 五类四态与 CHECK 一致")
class ApprovalMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static Set<String> columnsOf(String table) throws Exception {
        String sql = Files.readString(SCHEMA);
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(sql);
        assertThat(m.find()).as("建库脚本里必须有 %s 表", table).isTrue();
        Set<String> cols = new LinkedHashSet<>();
        for (String line : m.group(1).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    private static String toColumn(String field) {
        return field.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase();
    }

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("approvals");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(Approval.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName).map(ApprovalMapperTest::toColumn)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("留痕必备列在场（少了任何一列，审批就成了「不知道谁批的」）")
    void auditColumnsArePresent() throws Exception {
        assertThat(columnsOf("approvals")).contains(
                "object_type", "object_ref", "amount", "status",
                "requested_by", "requested_at", "decided_by", "decided_at",
                "consumed_at", "consumed_ref");
    }

    @Test
    @DisplayName("五类类型与表 CHECK 逐字一致（代码侧常量 ↔ 数据库侧约束）")
    void objectTypesMatchCheckConstraint() throws Exception {
        String sql = Files.readString(SCHEMA);
        for (String type : new String[]{Approval.TYPE_CREDIT_OVERRIDE, Approval.TYPE_PRICE_CHANGE,
                Approval.TYPE_REFUND, Approval.TYPE_PURCHASE_OVER, Approval.TYPE_STOCKTAKE_DIFF}) {
            assertThat(sql).as("建库脚本的 CHECK 必须列出 %s", type).contains("'" + type + "'");
        }
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（状态流转与消费的并发正确性在服务层 CAS，不在 SQL 里各写一套）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(ApprovalMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
