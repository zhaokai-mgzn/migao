package com.migao.admin.dto;

import java.time.LocalDate;

/**
 * 「待指派」的入库单供应商名（issue #7369 段 2，A 口径的人工出口）。
 *
 * @param supplierName    入库单上的供应商**文本**（历史快照，可能拼写不一）
 * @param orderCount      还没挂档案的单据数（按文本名分组）
 * @param lastInboundDate 该名字最近一次入库日期（用于判断「是不是老数据」）
 */
public record UnassignedInboundSupplier(String supplierName, int orderCount, LocalDate lastInboundDate) {
}
