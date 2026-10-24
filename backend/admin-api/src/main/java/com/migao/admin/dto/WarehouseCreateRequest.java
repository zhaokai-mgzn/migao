package com.migao.admin.dto;

import lombok.Data;

/** 建仓请求（issue #7373 段 1）。 */
@Data
public class WarehouseCreateRequest {

    /** 仓编码（同租户唯一）。 */
    private String code;

    private String name;

    /** store 门店仓 / processing 加工仓（缺省 store）。 */
    private String warehouseType;

    /** 设为默认仓（会把旧的默认仓取消）。 */
    private Boolean isDefault;

    private String remark;
}
