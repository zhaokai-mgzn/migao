// case_ids: SP-004
package com.migao.admin.mapper;

import com.migao.admin.entity.SupplierPaymentAllocation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 冲抵明细 Mapper / 实体 ↔ 建库脚本（issue #7369 段 3-B）。
 *
 * <p>额外守一条**业务底线**：明细表必须同时带 `payment_id` 与 `inbound_order_id` ——
 * 少了任何一个，这张表就退化成「有钱流动但不知道对应哪个付款/哪张单」的孤行。</p>
 */
@DisplayName("冲抵明细 Mapper：实体字段 ⊆ 建库脚本列 + 两侧引用在场")
class SupplierPaymentAllocationMapperTest {

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("supplier_payment_allocations");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(SupplierPaymentAllocation.class, "supplier_payment_allocations");
    }

    @Test
    @DisplayName("两侧引用与金额列在场（缺 payment_id / inbound_order_id = 孤行，账对不上）")
    void bothReferencesArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("supplier_payment_allocations"))
                .contains("tenant_id", "payment_id", "inbound_order_id", "amount");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(SupplierPaymentAllocationMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
