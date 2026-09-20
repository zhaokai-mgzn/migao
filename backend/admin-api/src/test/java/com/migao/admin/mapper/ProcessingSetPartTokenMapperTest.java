// case_ids: PG-018, PG-020
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingSetPartTokenMapper 契约测试（一部位一码 token，切片 ⓪ / issue #4698，V92；
 * 稳定短链短码 issue #4802，V99）。
 * 验证：表映射 processing_set_part_tokens + 实体字段与 V92 / V99 / schema.sql 收敛。
 * 扫码解析的**第一优先**形态：新 token（带套带部位）⇒ 部位由码给出、工人不选（设计 §2.3 / §2.6）。
 */
@DisplayName("ProcessingSetPartTokenMapper 表/字段契约（一部位一码）")
class ProcessingSetPartTokenMapperTest {

    private static final String V92 =
            "backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql";
    private static final String V99 =
            "backend/admin-api/src/main/resources/db/migration/V99__add_short_code_to_set_part_tokens.sql";

    @Test
    @DisplayName("实体映射 processing_set_part_tokens 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingSetPartToken.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_set_part_tokens");
    }

    @Test
    @DisplayName("实体字段与迁移 V92 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingSetPartToken.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "processingOrderId", "setId", "orderItemId",
                "positionKind", "token", "shortCode", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V92, "processing_set_part_tokens",
                "id", "tenant_id", "processing_order_id", "set_id", "order_item_id", "position_kind",
                "token", "deleted");
    }

    @Test
    @DisplayName("短码列（V99 / issue #4802）：迁移加列 + 唯一索引 + bootstrap 终态 + 实体字段收敛")
    void shortCodeColumnAndIndexExist() {
        // V99 是 ALTER TABLE（不是 CREATE TABLE）⇒ 逐条断言形态，不复用「表体列清单」helper
        String v99 = ProductionMigrationSql.read(V99);
        assertThat(v99).as("V99 必须给 processing_set_part_tokens 加 short_code 列")
                .containsPattern("(?is)ALTER TABLE\\s+processing_set_part_tokens\\b[\\s\\S]*?"
                        + "ADD COLUMN IF NOT EXISTS\\s+short_code\\s+CHAR\\(8\\)");
        assertThat(v99).as("短码必须全局唯一（/s/ 那一跳没有租户上下文）")
                .containsPattern("(?is)CREATE UNIQUE INDEX IF NOT EXISTS\\s+uk_set_part_tokens_short_code"
                        + "[\\s\\S]*?ON\\s+processing_set_part_tokens\\s*\\(\\s*short_code\\s*\\)");
        // bootstrap 终态（新建库路径不跑迁移链 ⇒ 只写迁移 = 新建库没有该列，#3270 同族）
        String schema = ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA);
        assertThat(schema).as("schema.sql 的 processing_set_part_tokens 缺 short_code 列")
                .containsPattern("(?m)^\\s*short_code\\s+CHAR\\(8\\)");
        assertThat(schema).contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_short_code");
        // 实体字段必须真的映射到该列（否则「同一行的两种表示」只在迁移里成立、代码里读不到）
        assertThat(Arrays.stream(ProcessingSetPartToken.class.getDeclaredFields()).map(Field::getName))
                .contains("shortCode");
    }

    @Test
    @DisplayName("🔴 短码查询**必须**绕过多租户拦截器（/s/ 是公开入口，无租户上下文 ⇒ 否则恒 500）")
    void shortCodeLookupIgnoresTenantLine() throws Exception {
        Method lookup = ProcessingSetPartTokenMapper.class.getMethod("selectByShortCode", String.class);
        InterceptorIgnore ignore = lookup.getAnnotation(InterceptorIgnore.class);
        assertThat(ignore).as("selectByShortCode 缺 @InterceptorIgnore ⇒ 公开短链路径必 500").isNotNull();
        assertThat(ignore.tenantLine()).isEqualTo("true");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingSetPartTokenMapper.class)).isTrue();
    }
}
