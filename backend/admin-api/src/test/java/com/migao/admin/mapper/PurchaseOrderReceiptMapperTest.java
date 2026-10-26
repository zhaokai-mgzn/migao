// case_ids: SP-005
package com.migao.admin.mapper;

import com.migao.admin.entity.PurchaseOrderReceipt;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 采购收货 Mapper：实体字段 ⊆ 建库脚本列（issue #7369 段 4）。
 *
 * <p>同其余 Mapper 判据的理由：Mapper 在单测里几乎总被 mock ⇒ 列名/字段对不上要等生产上第一次真跑才炸。
 * 守：实体字段 ⊆ 建库脚本列、租户列在场，且两侧引用在场（缺一个就是孤行）。</p>
 *
 * <p>红证方向：给实体加一个脚本里没有的字段 ⇒ 本类红。</p>
 */
@DisplayName("采购收货 Mapper：实体字段 ⊆ 建库脚本列")
class PurchaseOrderReceiptMapperTest {

    @Test
    @DisplayName("采购收货 Mapper：实体字段 ⊆ 建库脚本列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("purchase_order_receipts");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(PurchaseOrderReceipt.class, "purchase_order_receipts");
    }

    @Test
    @DisplayName("采购收货 Mapper：实体字段 ⊆ 建库脚本列：关键列在场")
    void keyColumnsArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("purchase_order_receipts")).contains("tenant_id", "purchase_order_id", "purchase_order_item_id", "quantity", "received_at");
    }

    @Test
    @DisplayName("采购收货 Mapper：实体字段 ⊆ 建库脚本列：只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(PurchaseOrderReceiptMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
