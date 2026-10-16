package com.migao.admin.mapper;

// case_ids: PG-073

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.PieceworkSettlement;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * PieceworkSettlementMapper 契约测试（V156，issue #5653 计件结算单）。
 *
 * <p><b>三源收敛</b>：Java 实体 ↔ 迁移 {@code V156__create_piecework_settlements.sql} ↔
 * bootstrap {@code backend/admin-api/src/main/resources/db/init/schema.sql}
 * （只写实体不写迁移、或迁移不同步建库脚本 ⇒ 新建库缺表 / 存量库缺列 ⇒ 端点 500）。</p>
 *
 * <p><b>另钉两条结构判据</b>：① 唯一性是**部分唯一索引**（谓词 {@code voided_at IS NULL AND deleted = 0}）
 * —— 漏一条的后果分别是「作废后永远不能重开」与「软删行占位」，两条都只有索引文本能判；
 * ② 本 mapper **没有**任何 UPDATE 金额 / 期间 / 工人的语句（「生成即冻结」的结构面）。</p>
 */
@DisplayName("PieceworkSettlementMapper 表/字段/索引契约（计件结算单）")
class PieceworkSettlementMapperTest {

    private static final String V156 =
            "backend/admin-api/src/main/resources/db/migration/V156__create_piecework_settlements.sql";

    @Test
    @DisplayName("实体映射 piecework_settlements；含租户列与快照/留痕两族列")
    void entityMapsToTable() {
        TableName tableName = PieceworkSettlement.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("piecework_settlements");
        assertThat(tableName.autoResultMap()).as("JSONB 列要过 typeHandler ⇒ 必须 autoResultMap").isTrue();

        List<String> fields = Arrays.stream(PieceworkSettlement.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "period", "workerName", "totalAmount", "lineItems",
                "generatedBy", "generatedAt", "voidedAt", "voidedBy", "voidReason",
                "createdAt", "updatedAt", "deleted");
    }

    @Test
    @DisplayName("契约列在**迁移**与**建库脚本**两源齐备（冻结契约逐字）")
    void contractColumnsExistInBothSources() {
        ProductionMigrationSql.assertTableColumnsIn(V156, "piecework_settlements",
                "id", "tenant_id", "period", "worker_name", "total_amount", "line_items",
                "generated_by", "generated_at", "voided_at", "voided_by", "void_reason",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("id 为 UUID 形态（响应里的 id 立刻可回带；真库路径由框架在语句执行前赋值）")
    void idIsAssignedUuid() throws Exception {
        TableId tableId = PieceworkSettlement.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("ASSIGN_UUID");
        assertThat(BaseMapper.class.isAssignableFrom(PieceworkSettlementMapper.class)).isTrue();
    }

    @Test
    @DisplayName("🔴 期间唯一性是**部分**唯一索引：谓词 voided_at IS NULL + deleted = 0 两源逐字在场")
    void activeUniquenessIsAPartialUniqueIndex() {
        for (String source : List.of(V156, ProductionMigrationSql.SCHEMA)) {
            String sql = ProductionMigrationSql.read(source);
            assertThat(sql).as("%s 缺 uk_piecework_settlements_active", source)
                    .contains("uk_piecework_settlements_active");
            // 锚在**建索引那条语句**上：文件头注记里也会提到同一个名字（那不是 DDL）⇒
            // 从 `CREATE UNIQUE INDEX` 处开始截到该语句结束（分号），注记里的提及不会命中
            String marker = "CREATE UNIQUE INDEX IF NOT EXISTS uk_piecework_settlements_active";
            int at = sql.indexOf(marker);
            assertThat(at).as("%s 缺 `%s`（建索引语句不在 ⇒ 唯一性没有落成 DDL）", source, marker)
                    .isGreaterThanOrEqualTo(0);
            String statement = sql.substring(at, sql.indexOf(';', at));
            assertThat(statement).as("%s 的唯一索引不是 UNIQUE", source).contains("UNIQUE INDEX");
            assertThat(statement).as("%s 的谓词漏了 voided_at IS NULL ⇒ 作废后永远不能重开", source)
                    .contains("voided_at IS NULL");
            assertThat(statement).as("%s 的谓词漏了 deleted = 0 ⇒ 软删行占位", source)
                    .contains("deleted = 0");
        }
    }

    @Test
    @DisplayName("🔴 原子生成：ON CONFLICT 目标**带索引谓词**（PG 冲突推断要求匹配，不带就报错）")
    void atomicInsertTargetsThePartialIndex() throws Exception {
        String sql = String.join(" ", PieceworkSettlementMapper.class
                .getMethod("insertActiveIfAbsent", PieceworkSettlement.class, String.class)
                .getAnnotation(org.apache.ibatis.annotations.Insert.class).value());
        assertThat(sql).contains("ON CONFLICT (tenant_id, period, worker_name)")
                .contains("WHERE voided_at IS NULL AND deleted = 0")
                .contains("DO NOTHING");
        assertThat(sql).as("明细必须 CAST 成 jsonb（列类型是 JSONB）").contains("CAST(").contains("AS jsonb)");
    }

    @Test
    @DisplayName("🔴 不可改（结构面）：mapper 只有两条写语句，且 voidActive 的 SET 子句不含快照列")
    void noUpdateSurfaceOnTheSnapshot() throws Exception {
        long writes = Arrays.stream(PieceworkSettlementMapper.class.getDeclaredMethods())
                .filter(m -> m.isAnnotationPresent(org.apache.ibatis.annotations.Insert.class)
                        || m.isAnnotationPresent(org.apache.ibatis.annotations.Update.class)
                        || m.isAnnotationPresent(org.apache.ibatis.annotations.Delete.class))
                .count();
        assertThat(writes).as("写语句只该有两条：原子生成 + 作废 CAS").isEqualTo(2);
        for (java.lang.reflect.Method m : PieceworkSettlementMapper.class.getDeclaredMethods()) {
            String name = m.getName().toLowerCase();
            if (m.isAnnotationPresent(org.apache.ibatis.annotations.Update.class)) {
                String set = String.join(" ", m.getAnnotation(org.apache.ibatis.annotations.Update.class).value())
                        .toLowerCase();
                set = set.substring(set.indexOf("set") + 3, set.indexOf("where"));
                assertThat(set).doesNotContain("total_amount").doesNotContain("period")
                        .doesNotContain("worker_name").doesNotContain("line_items");
            }
            assertThat(name).as("mapper 方法 %s 看起来是改写结算单的入口", m.getName())
                    .doesNotContain("update").doesNotContain("edit");
        }
    }
}
