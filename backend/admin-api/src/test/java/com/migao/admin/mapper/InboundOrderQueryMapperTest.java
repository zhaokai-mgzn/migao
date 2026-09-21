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
                "selectOrderLines", Long.class, String.class, String.class, int.class);
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

    @Test
    @DisplayName("列别名与 InboundOrderLine 的属性名逐一对齐（别名写错 ⇒ 字段静默为 null）")
    void aliasesMatchDtoProperties() throws NoSuchMethodException {
        String sql = sql();
        // MyBatis 按列别名映射到属性名：别名与 DTO 属性名不一致时**不报错**，字段只是永远为 null
        for (String alias : new String[]{
                "inboundNo", "supplier", "supplierDocNo", "warehouse", "inboundDate",
                "status", "totalAmount", "remark", "postedAt", "postedBy", "createdAt",
                "itemCount", "totalQuantity"}) {
            assertThat(sql).as("列表 SQL 缺别名 %s（DTO 字段会静默为 null）", alias)
                    .contains("AS " + alias);
        }
        // DTO 上确有其属性（反射，避免别名与属性名各改一半）
        for (String prop : new String[]{
                "inboundNo", "supplier", "supplierDocNo", "warehouse", "inboundDate",
                "status", "totalAmount", "remark", "postedAt", "postedBy", "createdAt",
                "itemCount", "totalQuantity"}) {
            assertThat(InboundOrderLine.class.getDeclaredFields())
                    .as("InboundOrderLine 缺属性 %s", prop)
                    .anyMatch(f -> f.getName().equals(prop));
        }
    }
}
