package com.migao.admin.service;

import java.util.List;

/**
 * 解析后的客户 Excel（issue #8295）。
 *
 * @param headers 表头（空表头已补成「列N」）
 * @param rows    数据行；每行长度 = headers.size()
 */
public record ParsedCustomerSheet(List<String> headers, List<List<String>> rows) {

    public int totalRows() {
        return rows.size();
    }
}
