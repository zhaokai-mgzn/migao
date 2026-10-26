// case_ids: AR-002
package com.migao.admin.mapper;

import com.migao.admin.entity.ReceiptAllocation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 核销明细 Mapper / 实体 ↔ 建库脚本（issue #7370 段 3）。
 *
 * <p>额外守一条**业务底线**：明细表必须同时带 `transaction_id` 与 `order_id` ——
 * 少了任何一个，这张表就退化成「有钱但没有去向」的孤行，而现金真值源本来就不在这张表里。</p>
 */
@DisplayName("核销明细 Mapper：实体字段 ⊆ 建库脚本列 + 两侧引用在场")
class ReceiptAllocationMapperTest {

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("receipt_allocations");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(ReceiptAllocation.class, "receipt_allocations");
    }

    @Test
    @DisplayName("两侧引用与金额列在场（缺 transaction_id / order_id = 孤行，账对不上）")
    void bothReferencesArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("receipt_allocations"))
                .contains("tenant_id", "transaction_id", "order_id", "amount");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（核销的读写都要过服务层准入，不许有旁路 SQL）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(ReceiptAllocationMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
