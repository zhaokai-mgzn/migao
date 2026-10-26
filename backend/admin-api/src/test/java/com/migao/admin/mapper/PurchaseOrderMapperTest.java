// case_ids: SP-005
package com.migao.admin.mapper;

import com.migao.admin.entity.PurchaseOrder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 采购单 Mapper：实体字段 ⊆ 建库脚本列（issue #7369 段 4）。
 *
 * <p>同其余 Mapper 判据的理由：Mapper 在单测里几乎总被 mock ⇒ 列名/字段对不上要等生产上第一次真跑才炸。
 * 守：实体字段 ⊆ 建库脚本列、租户列在场。</p>
 *
 * <p>红证方向：给实体加一个脚本里没有的字段 ⇒ 本类红。</p>
 */
@DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列")
class PurchaseOrderMapperTest {

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("purchase_orders");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(PurchaseOrder.class, "purchase_orders");
    }

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列：关键列在场")
    void keyColumnsArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("purchase_orders")).contains("tenant_id", "po_no", "status", "total_amount", "supplier_id");
    }

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列：只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(PurchaseOrderMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
