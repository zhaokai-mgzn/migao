// case_ids: SP-004
package com.migao.admin.mapper;

import com.migao.admin.entity.SupplierPayment;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 付款单 Mapper / 实体 ↔ 建库脚本（issue #7369 段 3-B）。
 *
 * <p>同 {@code SupplierMapperTest} 的理由：Mapper 在单测里几乎总被 mock ⇒ 列名/字段对不上要等
 * **生产上第一次真跑** 才炸（那是 500）。守两条：实体字段 ⊆ 脚本列、租户列在场。</p>
 *
 * <p>红证方向：把 {@code SupplierPayment} 的 {@code referenceNo} 改名而脚本未加列 ⇒ 本类红。</p>
 */
@DisplayName("付款单 Mapper：实体字段 ⊆ 建库脚本列 + 租户列在场")
class SupplierPaymentMapperTest {

    @Test
    @DisplayName("实体每个字段都有对应列（加字段不加列 ⇒ 每次 SQL 都炸）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("supplier_payments");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(SupplierPayment.class, "supplier_payments");
    }

    @Test
    @DisplayName("租户列在场 + 金额/状态/方式三列在场（涉钱面的最小列契约）")
    void moneyColumnsArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("supplier_payments"))
                .contains("tenant_id", "amount", "status", "method", "supplier_id");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（手写 SQL 不走租户插件 ⇒ 必须另补判据）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(SupplierPaymentMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
