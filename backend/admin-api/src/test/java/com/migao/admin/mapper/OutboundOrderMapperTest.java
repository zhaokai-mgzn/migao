// case_ids: WH-004
package com.migao.admin.mapper;

import com.migao.admin.entity.OutboundOrder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 出库单 Mapper / 实体 ↔ 建库脚本（V196，issue #7750 / 用例 WH-004）。
 *
 * <p>守三条：① 实体字段 ⊆ 建库列；② 单号**租户内唯一**；③ 出库单**没有草稿态** ——
 * 状态由表 CHECK 锁成唯一取值 {@code posted}（不靠服务层自觉，服务层写错也落不了库）。</p>
 */
@DisplayName("出库单 Mapper：字段 ⊆ 列 + 单号唯一 + 状态只有 posted（V196）")
class OutboundOrderMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static String schemaSql() throws Exception {
        return Files.readString(SCHEMA);
    }

    @Test
    @DisplayName("实体每个字段都有对应列（单号 / 业务类别 / 来源 / 过账痕迹）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("outbound_orders");
        assertThat(columns).isNotEmpty().contains("outbound_no", "biz_category", "source",
                "warehouse_id", "status", "posted_at", "posted_by");
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(OutboundOrder.class, "outbound_orders");
    }

    @Test
    @DisplayName("🔴 单号租户内唯一（部分唯一索引，软删不占位）")
    void outboundNoIsUniquePerTenant() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("uk_outbound_orders_no");
        assertThat(sql).contains("ON outbound_orders (tenant_id, outbound_no) WHERE deleted = 0");
    }

    @Test
    @DisplayName("🔴 出库单**没有草稿态**：表 CHECK 锁成 status = 'posted'（不是 IN (…)）")
    void statusIsLockedToPosted() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("ck_outbound_orders_status");
        assertThat(sql).as("状态必须是「只有 posted 一个取值」的 CHECK")
                .contains("CHECK (status = 'posted')");
        assertThat(OutboundOrder.STATUS_POSTED).isEqualTo("posted");
    }

    @Test
    @DisplayName("业务类别 / 来源的封闭集合与表 CHECK 逐字一致")
    void categoryAndSourceMatchCheckConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("'" + OutboundOrder.BIZ_FABRIC + "'", "'" + OutboundOrder.BIZ_FINISHED + "'",
                "'" + OutboundOrder.SOURCE_MANUAL + "'", "'" + OutboundOrder.SOURCE_SHIP + "'");
    }

    @Test
    @DisplayName("Mapper 只有**一条**自定义语句：原子占号 INSERT（唯一性交给索引；不许加查询式取号）")
    void mapperOnlyCarriesTheAtomicNumberClaim() {
        var declared = java.util.Arrays.stream(OutboundOrderMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).toList();
        assertThat(declared).as("自定义语句必须恰好一条（issue #8490 的原子占号）"
                + "—— 多写一条 SQL 就是多一份会漂的取号口径").hasSize(1);

        var claim = declared.get(0);
        assertThat(claim.getName()).isEqualTo("insertIgnoreOutboundNoConflict");
        assertThat(claim.isAnnotationPresent(org.apache.ibatis.annotations.Select.class)
                || claim.isAnnotationPresent(org.apache.ibatis.annotations.Update.class)
                || claim.isAnnotationPresent(org.apache.ibatis.annotations.Delete.class))
                .as("不许出现查询 / 更新 / 删除式取号（那不是「一条语句占号」）").isFalse();

        org.apache.ibatis.annotations.Insert insert =
                claim.getAnnotation(org.apache.ibatis.annotations.Insert.class);
        assertThat(insert).as("必须是 @Insert（取号与落库同一条语句）").isNotNull();
        String sql = String.join(" ", insert.value());
        assertThat(sql).as("冲突目标必须带部分唯一索引的谓词（否则 PG 推断不到冲突）")
                .contains("ON CONFLICT (tenant_id, outbound_no) WHERE deleted = 0 DO NOTHING");
        assertThat(sql).as("不许在 SQL 里再写一套取号逻辑（SELECT / FOR UPDATE）")
                .doesNotContainIgnoringCase("SELECT")
                .doesNotContainIgnoringCase("FOR UPDATE");
    }
}
