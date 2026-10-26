package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 批量新建仓位结果（issue #7791）。
 *
 * <p>{@code created + skipped = 区间大小}；{@code skipped} 是「仓位号已存在，按幂等跳过」，
 * 不是失败（重复提交同一批次不会报错）。</p>
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class WarehouseLocationBatchCreateResult {

    /** 实际新建数量 */
    private int created;

    /** 已存在而跳过的数量 */
    private int skipped;

    /** 区间首号（如 A-01） */
    private String fromCode;

    /** 区间末号（如 A-20） */
    private String toCode;

    /** 本区域每仓容量（件） */
    private int capacity;
}
