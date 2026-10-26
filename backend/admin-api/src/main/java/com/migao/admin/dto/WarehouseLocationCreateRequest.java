package com.migao.admin.dto;

import lombok.Data;

/**
 * 新建仓位请求（issue #7785）。
 *
 * <p>{@code binCode} 统一大写并限定为字母 / 数字 / 短横线 / 下划线（与自动分配的
 * {@code A-01} 同一形态）；区域不传 = 默认「A / 成品区」。成品仓不存在时由服务端
 * 自动建（与打包同一 {@code ensureFinishedWarehouse}）。</p>
 */
@Data
public class WarehouseLocationCreateRequest {

    /** 仓位号（必填；如 A-01） */
    private String binCode;

    /** 区域编码（缺省 A） */
    private String zoneCode;

    /** 区域名称（缺省 成品区） */
    private String zoneName;

    /** 每仓容量（件；null = 沿用本区域现有容量，新区域缺省 10；1~999） */
    private Integer capacity;

    private String remark;
}
