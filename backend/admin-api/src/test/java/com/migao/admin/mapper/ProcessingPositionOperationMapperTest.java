package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingPositionOperation;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingPositionOperationMapper 契约测试（工序实例，issue #3995，V49）
 * 验证：表映射 processing_position_operations + 实体字段与迁移 V49 / schema.sql 收敛。
 * 工序实例是扫码报工的推进单元（qty 应做数量 / done_qty 合格累计 / is_must_finish 必完）。
 */
@DisplayName("ProcessingPositionOperationMapper 表/字段契约（工序实例）")
class ProcessingPositionOperationMapperTest {

    @Test
    @DisplayName("实体映射 processing_position_operations 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingPositionOperation.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_position_operations");
    }

    @Test
    @DisplayName("实体字段与迁移 V49 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingPositionOperation.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "processingOrderId", "positionName", "seq", "operationName",
                "groupName", "unit", "qty", "unitPrice", "factor", "isMustFinish",
                "isStartMarker", "status", "doneQty", "deleted"
        );
        ProductionMigrationSql.assertTableColumns("processing_position_operations",
                "id", "tenant_id", "processing_order_id", "position_name", "seq", "operation_name",
                "group_name", "unit", "qty", "unit_price", "factor", "is_must_finish",
                "is_start_marker", "status", "done_qty", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingPositionOperationMapper.class)).isTrue();
    }

    // ══════════════════ 未定价实例补价（V94，issue #4709 C）：红线落在 SQL 谓词上 ══════════════════

    @Test
    @DisplayName("🔴 补价只补 NULL：`fillUnpricedUnitPrice` 的谓词含 `unit_price IS NULL`（删掉 ⇒ 会改写已有价）")
    void fillUnpricedUnitPriceOnlyMatchesNullRows() throws Exception {
        String sql = sqlOf("fillUnpricedUnitPrice");

        assertThat(sql).contains("AND unit_price IS NULL");
        // 租户 + 软删边界（跨租户/已软删的行不得被补价）
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("id = #{id}");
    }

    @Test
    @DisplayName("🔴 红线④：补价的 SET 子句**只**含 unit_price/updated_at（碰 done_qty/status/factor ⇒ 进度被清零）")
    void fillUnpricedUnitPriceNeverTouchesProgressOrFactor() throws Exception {
        String sql = sqlOf("fillUnpricedUnitPrice");
        String set = sql.substring(sql.indexOf("SET"), sql.indexOf("WHERE"));

        assertThat(set).contains("unit_price = #{unitPrice}").contains("updated_at = #{updatedAt}");
        assertThat(set).as("补价不是报工：不得推进/清零生产进度")
                .doesNotContain("done_qty").doesNotContain("status");
        assertThat(set).as("补价不得动计件系数（历史报工按快照算，系数是当时工资的证据）")
                .doesNotContain("factor");
    }

    @Test
    @DisplayName("🔴 回滚只还原账本记录的那次补价：谓词含 `unit_price = #{expectedUnitPrice}`（不覆盖后续改动）")
    void revertFilledUnitPriceOnlyMatchesTheLedgerValue() throws Exception {
        String sql = sqlOf("revertFilledUnitPrice");

        assertThat(sql).contains("SET unit_price = NULL");
        assertThat(sql).contains("AND unit_price = #{expectedUnitPrice}");
        assertThat(sql).contains("tenant_id = #{tenantId}").contains("deleted = 0");
        String set = sql.substring(sql.indexOf("SET"), sql.indexOf("WHERE"));
        assertThat(set).doesNotContain("done_qty").doesNotContain("status").doesNotContain("factor");
    }

    /** 取某个 Mapper 方法的 {@code @Update} SQL 原文（结构判据：谓词/SET 子句写在 SQL 里才拦得住）。 */
    private static String sqlOf(String methodName) throws Exception {
        Method method = ProcessingPositionOperationMapper.class.getMethod(methodName,
                String.class, Long.class, java.math.BigDecimal.class, java.time.OffsetDateTime.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).as("%s 必须是 @Update 注解方法（SQL 可被本测试逐字核验）", methodName).isNotNull();
        return String.join(" ", update.value());
    }
}
