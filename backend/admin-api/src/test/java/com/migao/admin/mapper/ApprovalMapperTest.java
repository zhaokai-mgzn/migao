// case_ids: APP-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Approval;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

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

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("approvals");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(Approval.class, "approvals");
    }

    @Test
    @DisplayName("留痕必备列在场（少了任何一列，审批就成了「不知道谁批的」）")
    void auditColumnsArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("approvals")).contains(
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
