package com.migao.admin.dto;

import lombok.Data;

/**
 * 批量新建仓位请求（issue #7791）。
 *
 * <p>用户输入一个数字区间（如 A 区 1~20），服务端生成 {@code A-01}…{@code A-20}；
 * 已存在的仓位号自动跳过（不报错），返回新建 / 跳过计数。单次最多 500 个。</p>
 */
@Data
public class WarehouseLocationBatchCreateRequest {

    /** 区域编码（缺省 A） */
    private String zoneCode;

    /** 区域名称（缺省 成品区） */
    private String zoneName;

    /** 起始编号（含；1~9999，如 1 ⇒ A-01） */
    private Integer numberFrom;

    /** 结束编号（含；1~9999，如 20 ⇒ A-20） */
    private Integer numberTo;

    /** 每仓容量（件；null = 沿用本区域现有容量，新区域缺省 10；1~999） */
    private Integer capacity;
}
