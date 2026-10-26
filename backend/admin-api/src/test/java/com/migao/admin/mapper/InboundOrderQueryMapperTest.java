package com.migao.admin.mapper;

// case_ids: PR-040

import com.migao.admin.dto.InboundOrderLine;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * InboundOrderQueryMapper 契约测试（入库单列表聚合读面，V111 / issue #5034）。
 *
 * <p>这条 SQL 是本单唯一一处**手写 SQL**（其余走 MyBatis-Plus wrapper），因此也是唯一
 * 一处「租户隔离与聚合口径都不会被类型系统挡住」的地方 ⇒ 用文本判据守：</p>
 * <ul>
 *   <li><b>租户维</b>：必须有 {@code o.tenant_id = #{tenantId}} 与 {@code o.deleted = 0}
 *       —— 跨租户读是数据泄漏，不是过滤问题；软删单不得出现在列表里；</li>
 *   <li><b>聚合维</b>：行数/总量取自明细子查询，且子查询也限定 {@code deleted = 0}
 *       —— 否则软删明细会虚增「行数 / 总数量」；</li>
 *   <li><b>上限</b>：必须有 {@code LIMIT}（入库单是流水型单据，不做深分页也不能无界返回）。</li>
 * </ul>
 */
@DisplayName("InboundOrderQueryMapper 聚合读面契约（列表 SQL）")
class InboundOrderQueryMapperTest {

    private static Select selectAnnotation() throws NoSuchMethodException {
        Method m = InboundOrderQueryMapper.class.getMethod(
                "selectOrderLines", Long.class, String.class, String.class, String.class, Long.class, int.class);
        Select select = m.getAnnotation(Select.class);
        assertThat(select).as("selectOrderLines 必须标 @Select").isNotNull();
        return select;
    }

    private static String sql() throws NoSuchMethodException {
        return String.join("\n", selectAnnotation().value());
    }

    @Test
    @DisplayName("租户隔离：SQL 里必须有 o.tenant_id = #{tenantId}（跨租户读 = 数据泄漏）")
    void sqlIsTenantScoped() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).contains("o.tenant_id = #{tenantId}");
        assertThat(sql).contains("o.deleted = 0");
    }

    @Test
    @DisplayName("聚合子查询也限定 deleted = 0（否则软删明细虚增行数/总数量）")
    void aggregateSubqueryExcludesDeletedItems() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).contains("FROM inbound_order_items");
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("COUNT(*)");
        assertThat(sql).contains("SUM(quantity)");
        // 行数/总量必须来自聚合子查询（不是单表计数）
        assertThat(sql).contains("item_count").contains("total_qty");
    }

    @Test
    @DisplayName("必须有 LIMIT（无界返回会把整张流水表拉进内存）")
    void sqlIsBounded() throws NoSuchMethodException {
        assertThat(sql()).contains("LIMIT #{limit}");
    }

    @Test
    @DisplayName("筛选条件：状态精确匹配、关键词按 单号/供应商/送货单号 模糊匹配")
    void sqlSupportsFilters() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).contains("o.status = #{status}");
        assertThat(sql).contains("o.inbound_no ILIKE");
        assertThat(sql).contains("o.supplier ILIKE");
        assertThat(sql).contains("o.supplier_doc_no ILIKE");
    }

    /**
     * issue #7794：类别是「原料仓入库 / 成品仓入库」两个视图的**唯一分界**。
     *
     * <p>去掉这个谓词 ⇒ 服务层传什么都白搭，成品单照旧混进原料仓列表 —— 而页面看起来一切正常
     * （用户 2026-10-26 报的就是这个形态）。</p>
     */
    @Test
    @DisplayName("#7794 类别过滤：o.biz_category = #{bizCategory}（漏掉 ⇒ 两个视图都是全量）")
    void sqlSupportsBizCategoryFilter() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).contains("o.biz_category = #{bizCategory}");
        assertThat(sql).as("条件必须可缺省（null / 空串 = 不过滤，向后兼容）")
                .contains("test=\"bizCategory != null and bizCategory != ''\"");
    }

    /**
     * issue #7807：列表要能**按仓库查单**（改前只有「仓库」文本列可看，查不了）。
     *
     * <p>去掉这个谓词 ⇒ 服务层传什么都白搭，下拉选了仓也照样返回**全部**仓的单 ——
     * 而页面看起来一切正常（下拉有值、列表有行）。</p>
     */
    @Test
    @DisplayName("#7807 仓库过滤：o.warehouse_id = #{warehouseId}（漏掉 ⇒ 选了仓也返回全量）")
    void sqlSupportsWarehouseFilter() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).contains("o.warehouse_id = #{warehouseId}");
        assertThat(sql).as("必须可缺省（null = 全部仓库：既有调用点与站内信深链行为不变）")
                .contains("test=\"warehouseId != null\"");
        // 与类别维**同时**生效：两个 <if> 都在 WHERE 里，不互相吞没
        assertThat(sql.indexOf("o.warehouse_id = #{warehouseId}"))
                .as("仓库条件必须落在 o.biz_category 之后（同一 WHERE 内、顺序邻近）")
                .isGreaterThan(sql.indexOf("o.biz_category = #{bizCategory}"));
        assertThat(sql.indexOf("o.warehouse_id = #{warehouseId}"))
                .as("仓库条件必须在**主查询**的 ORDER BY 之前（落到 ORDER BY 之后 = 语法错 / 静默失效；"
                        + "注意聚合子查询里也有一个 ORDER BY，不能用第一个命中位置）")
                .isLessThan(sql.indexOf("ORDER BY o.inbound_date DESC"));
    }

    @Test
    @DisplayName("#7794 套数合计：成品行按 set_id 去重（没有套号的存量行按一行一套）")
    void sqlAggregatesSetCount() throws NoSuchMethodException {
        String sql = sql();
        assertThat(sql).as("套数 = 不同套号个数；拿行数顶替就把「5 套 × 2 部位」显示成 10 套")
                .contains("COUNT(DISTINCT");
        assertThat(sql).contains("set_count");
    }

    @Test
    @DisplayName("列别名与 InboundOrderLine 的属性名逐一对齐（别名写错 ⇒ 字段静默为 null）")
    void aliasesMatchDtoProperties() throws NoSuchMethodException {
        String sql = sql();
        // MyBatis 按列别名映射到属性名：别名与 DTO 属性名不一致时**不报错**，字段只是永远为 null
        for (String alias : new String[]{
                "inboundNo", "supplier", "supplierDocNo", "warehouse", "inboundDate",
                "status", "bizCategory", "totalAmount", "remark", "postedAt", "postedBy", "createdAt",
                "itemCount", "totalQuantity", "setCount"}) {
            assertThat(sql).as("列表 SQL 缺别名 %s（DTO 字段会静默为 null）", alias)
                    .contains("AS " + alias);
        }
        // DTO 上确有其属性（反射，避免别名与属性名各改一半）
        for (String prop : new String[]{
                "inboundNo", "supplier", "supplierDocNo", "warehouse", "inboundDate",
                "status", "bizCategory", "totalAmount", "remark", "postedAt", "postedBy", "createdAt",
                "itemCount", "totalQuantity", "setCount"}) {
            assertThat(InboundOrderLine.class.getDeclaredFields())
                    .as("InboundOrderLine 缺属性 %s", prop)
                    .anyMatch(f -> f.getName().equals(prop));
        }
    }
}
