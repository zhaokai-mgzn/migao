// case_ids: MIG-004

package com.migao.admin.service;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 解析结果 DTO（issue #8295）：行数只由数据行决定，不把表头算进去。
 */
class ParsedCustomerSheetTest {

    @Test
    void totalRowsCountsDataRowsOnly() {
        ParsedCustomerSheet sheet = new ParsedCustomerSheet(
                List.of("客户编号", "客户名称"),
                List.of(List.of("C001", "张三"), List.of("C002", "李四")));

        assertThat(sheet.headers()).containsExactly("客户编号", "客户名称");
        assertThat(sheet.totalRows()).isEqualTo(2);
        assertThat(sheet.rows()).hasSize(2);
    }

    @Test
    void emptyDataRowsIsZero() {
        ParsedCustomerSheet sheet = new ParsedCustomerSheet(List.of("客户名称"), List.of());

        assertThat(sheet.totalRows()).isZero();
        assertThat(sheet.rows()).isEmpty();
    }
}
