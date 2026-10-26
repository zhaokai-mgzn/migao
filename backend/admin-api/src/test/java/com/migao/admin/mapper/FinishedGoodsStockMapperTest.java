// case_ids: WH-005
package com.migao.admin.mapper;

import com.migao.admin.entity.FinishedGoodsStock;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 成品在库 Mapper / 实体 ↔ 建库脚本（V196，issue #7750 / 用例 WH-005）。
 *
 * <p>守四条：</p>
 * <ol>
 *   <li>实体字段 ⊆ 建库列；</li>
 *   <li>🔴 <b>一个仓位可放多件到区域容量</b>（V198 / issue #7791）：bin 上不再有唯一索引，
 *       容量由 {@code warehouse_locations.capacity} + 服务层行锁闸住；同套装/部位仍只一行在库；</li>
 *   <li>🔴 占位是原子的（{@code INSERT … ON CONFLICT DO NOTHING}）：唯一冲突不抛异常（否则 PG 事务 aborted，
 *       服务层「换下一个仓位重试」在同事务内是非法路径）；</li>
 *   <li>状态迁移是**条件更新**（{@code WHERE status='in_stock'}）：发货与撤销打包并发时只有一条能改到。</li>
 * </ol>
 */
@DisplayName("成品在库 Mapper：一仓多件到容量 + 原子占位 + 条件迁移（V196/V198）")
class FinishedGoodsStockMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static String schemaSql() throws Exception {
        return Files.readString(SCHEMA);
    }

    private static String sqlOf(String method, Class<?> annotation) throws Exception {
        for (Method m : FinishedGoodsStockMapper.class.getDeclaredMethods()) {
            if (!m.getName().equals(method)) {
                continue;
            }
            if (annotation.equals(Select.class) && m.getAnnotation(Select.class) != null) {
                return String.join(" ", m.getAnnotation(Select.class).value());
            }
            if (annotation.equals(Update.class) && m.getAnnotation(Update.class) != null) {
                return String.join(" ", m.getAnnotation(Update.class).value());
            }
        }
        throw new AssertionError("FinishedGoodsStockMapper 缺方法：" + method);
    }

    @Test
    @DisplayName("实体每个字段都有对应列（仓位 / 订单行 / 状态 / 入出库单引用）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("finished_goods_stock");
        assertThat(columns).isNotEmpty().contains("warehouse_id", "location_id", "bin_code", "order_id",
                "order_item_id", "quantity", "unit", "status", "inbound_order_id", "outbound_order_id");
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(FinishedGoodsStock.class, "finished_goods_stock");
        // 反向：被排除的字段必须**显式**标 exist = false（不许靠命名 / 注释 / 「约定」绕过这道守卫）
        assertThat(FinishedGoodsStock.class.getDeclaredField("inboundNo")
                .getAnnotation(com.baomidou.mybatisplus.annotation.TableField.class).exist())
                .as("inboundNo 是 join 投影，必须标 @TableField(exist = false)")
                .isFalse();
    }

    @Test
    @DisplayName("🔴 一个仓位可放多件到区域容量（bin 无唯一索引；容量列有界；同套装/部位仍唯一）")
    void oneBinHoldsMultiplePackagesUpToCapacity() throws Exception {
        String sql = schemaSql();
        assertThat(sql).as("V198 起 bin 上不再是唯一索引（一仓可放多件）")
                .contains("idx_finished_goods_bin_in_stock")
                .doesNotContain("uk_finished_goods_bin_in_stock");
        assertThat(sql).contains("capacity INTEGER NOT NULL DEFAULT 10")
                .contains("ck_warehouse_locations_capacity")
                .contains("capacity BETWEEN 1 AND 999");
        // V197（issue #7762）：同套装/部位只一行在库；V196 遗留行由 set_id IS NULL 那条兜底
        assertThat(sql).contains("uk_finished_goods_set_part_in_stock")
                .contains("uk_finished_goods_legacy_item_in_stock");
    }

    @Test
    @DisplayName("水位分子：一次 GROUP BY 查全租户每个仓位的在库件数（不搬整行、不受 500 行截断）")
    void inStockCountsAreGroupedByBin() throws Exception {
        String sql = sqlOf("selectInStockCounts", Select.class);
        assertThat(sql).contains("bin_code AS binCode", "count(*) AS inStockCount")
                .contains("tenant_id = #{tenantId}")
                .contains("status = 'in_stock'", "deleted = 0", "GROUP BY bin_code");
    }

    @Test
    @DisplayName("状态三态与表 CHECK 逐字一致（in_stock / shipped / unpacked）")
    void statusesMatchCheckConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("'" + FinishedGoodsStock.STATUS_IN_STOCK + "'",
                "'" + FinishedGoodsStock.STATUS_SHIPPED + "'",
                "'" + FinishedGoodsStock.STATUS_UNPACKED + "'");
        assertThat(sql).contains("ck_finished_goods_stock_status");
    }

    @Test
    @DisplayName("🔴 占位是原子的：ON CONFLICT DO NOTHING（冲突 ⇒ null，不抛异常）")
    void claimInStockIsAtomic() throws Exception {
        String sql = sqlOf("claimInStock", Select.class).toUpperCase();
        assertThat(sql).contains("ON CONFLICT DO NOTHING", "RETURNING ID", "STATUS");
        assertThat(sql).contains("'IN_STOCK'");
    }

    @Test
    @DisplayName("🔴 发货/撤销是**条件更新**：WHERE status = 'in_stock'（并发只有一条能改到）")
    void transitionsAreConditional() throws Exception {
        assertThat(sqlOf("markShippedByOrder", Update.class))
                .contains("SET status = 'shipped'", "outbound_order_id = #{outboundOrderId}",
                        "status = 'in_stock'", "tenant_id = #{tenantId}");
        assertThat(sqlOf("markUnpackedByOrder", Update.class))
                .contains("SET status = 'unpacked'", "status = 'in_stock'", "tenant_id = #{tenantId}");
    }

    @Test
    @DisplayName("读在库行：在库总览与按单查都限定 tenant_id + status = 'in_stock'")
    void readQueriesAreScoped() throws Exception {
        for (String method : new String[]{"selectInStock", "selectInStockByOrder"}) {
            String sql = sqlOf(method, Select.class);
            assertThat(sql).contains("tenant_id = #{tenantId}", "status = 'in_stock'", "deleted = 0");
        }
    }

    @Test
    @DisplayName("🔴 类级守卫：每条手写 SQL 都标 @InterceptorIgnore(tenantLine=true)（自己写 tenant_id，禁止插件二次注入）")
    void everyHandWrittenSqlOptsOutOfTenantPlugin() {
        java.util.List<String> offenders = new java.util.ArrayList<>();
        for (Method m : FinishedGoodsStockMapper.class.getDeclaredMethods()) {
            if (m.isSynthetic()) {
                continue;
            }
            boolean handWritten = m.isAnnotationPresent(Select.class) || m.isAnnotationPresent(Insert.class)
                    || m.isAnnotationPresent(Update.class);
            if (!handWritten) {
                continue;
            }
            InterceptorIgnore ignore = m.getAnnotation(InterceptorIgnore.class);
            if (ignore == null || ignore.tenantLine() == null || !ignore.tenantLine().contains("true")) {
                offenders.add(m.getName());
            }
        }
        assertThat(offenders)
                .as("手写 SQL 未标 @InterceptorIgnore(tenantLine=true)：%s（全局租户插件会二次注入 tenant_id，"
                        + "在 INSERT … ON CONFLICT / 子查询上改出错误 SQL）", offenders)
                .isEmpty();
    }
}
